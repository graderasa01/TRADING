"""
The frozen map — `LIVE-FRONTIER.md` §5.

`hierarchy.build_map()` reads a canvas of closed candles and returns a `StructureMap`.
This module turns that into something that can be **handed over and relied on**: a
snapshot that cannot change, a separate append-only record of what happened to it
afterwards, and a way to see how much a rebuild moved.

## A snapshot is not a claim about the market forever

It is *"the map as observed when built at index i"*. That distinction is the whole reason
this type exists, and it is why `label()` never renders a bare version string:

    M001 @ i=999 · 16 Feb 15:29 IST

Read as settled truth, "M001 freeze" would make this layer lie — the map built at candle
900 is genuinely not the map built at candle 1000, because segment boundaries only settle
after the segment ends.

## The three layers, and which one may move

```
M001    HISTORICAL MAP    immutable. Never touched by a live candle.
F001    LIVE FRONTIER     provisional, mutable                   (frontier.py, next)
LOG     LIVE EVENTS       append-only
```

Live state is `M001 + LOG`, never `M001'`. A new observation produces `M002` by an
**explicit rebuild**, and `diff(M001, M002)` says how much moved. That number is the
honest measure of repainting, and hiding it would defeat the point of freezing anything.

Immutability here is enforced by the type system — `frozen=True` and tuples throughout —
not by discipline. `LiveLog` is the one mutable object, and the only thing it can do is
grow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Sequence

from src.boxes.adaptive import overlap
from src.boxes.hierarchy import Node, Relation, Rotation, build_map
from src.boxes.structure import STRUCTURE_KINDS
from src.domain.models import IST, ZERO, Candle

SAME_NODE_OVERLAP = 0.5      # the dedupe threshold `mapper.py` already uses


# ─────────────────────────────────────────────────────────────────────────────
# the snapshot
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MapSnapshot:
    """One immutable reading of the canvas."""

    version: str
    symbol: str
    built_at: datetime
    built_at_index: int
    first_index: int
    nodes: tuple[Node, ...]
    relations: tuple[Relation, ...]

    def label(self) -> str:
        """Never a bare version. The build index and time are part of the identity."""
        return (f"{self.version} @ i={self.built_at_index} · "
                f"{self.built_at:%d %b %H:%M} IST")

    @property
    def n_candles(self) -> int:
        return self.built_at_index - self.first_index + 1

    def by_id(self, nid: str) -> Node | None:
        return next((n for n in self.nodes if n.id == nid), None)

    def structures(self) -> list[Node]:
        return [n for n in self.nodes if n.kind in STRUCTURE_KINDS]

    def children_of(self, nid: str) -> list[Node]:
        return sorted((n for n in self.nodes if n.parent == nid), key=lambda n: n.start)

    def edges(self, kind: str) -> list[Relation]:
        return [r for r in self.relations if r.kind == kind]

    def containing(self, price: Decimal, tol: Decimal = ZERO) -> Node | None:
        """The tightest structure holding `price`. Same rule as `Mapper.current()`."""
        inside = [n for n in self.structures()
                  if n.low - tol <= price <= n.high + tol]
        return min(inside, key=lambda n: n.width) if inside else None


def next_version(previous: str | None) -> str:
    if not previous:
        return "M001"
    return f"M{int(previous.lstrip('M')) + 1:03d}"


def build_snapshot(candles: Sequence[Candle], symbol: str, *,
                   version: str = "M001", first_index: int = 0, **kw) -> MapSnapshot:
    """Scan the canvas once and freeze the result."""
    m = build_map(candles, **kw)
    last = len(candles) - 1
    return MapSnapshot(
        version=version, symbol=symbol,
        built_at=candles[last].close_time if candles else datetime.now(IST),
        built_at_index=last, first_index=first_index,
        nodes=tuple(m.nodes), relations=tuple(m.relations))


# ─────────────────────────────────────────────────────────────────────────────
# the live log
# ─────────────────────────────────────────────────────────────────────────────
EVENT_KINDS = frozenset({"touch", "break", "retest", "re_entry", "failure",
                         "acceptance", "continuation", "approach", "revisit"})


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """Something that happened to a frozen node after the snapshot was taken.

    Note what is **not** here: no new edges, no changed bands. An event records what price
    did to a structure; it never edits the structure.
    """

    kind: str
    node_id: str
    index: int
    at: datetime
    direction: str = ""
    level: Decimal | None = None
    detail: str = ""
    #: What the structure had accumulated when this happened — touches, rotations, dwell.
    #: An event still never edits a structure; this is the evidence *travelling with* the
    #: event, which is the only way a revisited node's live history can survive at all.
    #: `Frontier` never finalises a revisited node, so without this the forty candles
    #: price spent back inside `C20` are simply lost when it breaks again.
    evidence: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(
                f"unknown live event {self.kind!r}. Add it to EVENT_KINDS first — an "
                f"ad-hoc event string makes the log unanalysable, the same reason "
                f"`GATES` is a closed vocabulary in domain/models.py.")


class LiveLog:
    """Append-only. The one mutable object in this module, and it can only grow.

    There is deliberately no `clear()`, no `__setitem__`, and no way to remove an event:
    *"MAP M001 + [live events], never MAP M001'."*
    """

    __slots__ = ("snapshot", "_events")

    def __init__(self, snapshot: MapSnapshot) -> None:
        self.snapshot = snapshot
        self._events: list[LiveEvent] = []

    def append(self, event: LiveEvent) -> LiveEvent:
        if self.snapshot.by_id(event.node_id) is None:
            raise KeyError(f"{event.node_id} is not in {self.snapshot.version}")
        if self._events and event.index < self._events[-1].index:
            raise ValueError(
                f"live events must arrive in candle order: {event.index} after "
                f"{self._events[-1].index}")
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[LiveEvent, ...]:
        return tuple(self._events)

    def for_node(self, nid: str) -> list[LiveEvent]:
        return [e for e in self._events if e.node_id == nid]

    def of_kind(self, kind: str) -> list[LiveEvent]:
        return [e for e in self._events if e.kind == kind]

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[LiveEvent]:
        return iter(self._events)


class LiveEventLog:
    """The same append-only discipline, for structures the **frontier itself** minted.

    `LiveLog` refuses any event whose node is not in the frozen snapshot, and it is right
    to: `M001`'s log describes what happened to `M001`'s structures, and an entry for a
    node the snapshot has never heard of would make it unreadable.

    But the audit measured the cost of having only that log: **live-minted nodes carry
    roughly three quarters of all breaks**, and every one of their `break`, `re_entry` and
    `revisit` events was being dropped on the floor by `Frontier._record`. The live map
    was keeping no history of its own work.

    So there are two logs, and the split is by ownership rather than by importance:

    ```
    LiveLog        what price did to the FROZEN map          M001's nodes
    LiveEventLog   what price did to what the frontier built L01, L02, ...
    ```

    Same closed `EVENT_KINDS`, same candle-order rule, same absence of `clear()`,
    `__setitem__` or any way to remove an entry. The only thing dropped is the snapshot
    membership check, because here membership is the wrong question.
    """

    __slots__ = ("_events",)

    def __init__(self) -> None:
        self._events: list[LiveEvent] = []

    def append(self, event: LiveEvent) -> LiveEvent:
        if self._events and event.index < self._events[-1].index:
            raise ValueError(
                f"live events must arrive in candle order: {event.index} after "
                f"{self._events[-1].index}")
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[LiveEvent, ...]:
        return tuple(self._events)

    def for_node(self, nid: str) -> list[LiveEvent]:
        return [e for e in self._events if e.node_id == nid]

    def of_kind(self, kind: str) -> list[LiveEvent]:
        return [e for e in self._events if e.kind == kind]

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[LiveEvent]:
        return iter(self._events)


# ─────────────────────────────────────────────────────────────────────────────
# diff — how much did a rebuild move?
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NodeChange:
    verdict: str                 # survived | moved | vanished | appeared
    before: Node | None
    after: Node | None
    low_shift: Decimal = ZERO
    high_shift: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    """What a rebuild did. `moved` is the number that matters — it is repainting."""

    before: str
    after: str
    changes: tuple[NodeChange, ...]

    def of(self, verdict: str) -> list[NodeChange]:
        return [c for c in self.changes if c.verdict == verdict]

    def summary(self) -> str:
        return "  ".join(f"{v} {len(self.of(v))}" for v in
                         ("survived", "moved", "vanished", "appeared"))


def diff(a: MapSnapshot, b: MapSnapshot, tol: Decimal) -> SnapshotDiff:
    """Match structurally, not by id.

    Ids are minted per build, so `C12` in `M001` and `C12` in `M002` are unrelated. Two
    nodes are the same structure when they are the same kind, overlap in time, and share
    at least half of the narrower band — the same `overlap` test `mapper.py` uses to
    decide a proposal is a box it has already seen.
    """
    a_nodes = [n for n in a.nodes if n.kind in STRUCTURE_KINDS]
    b_nodes = [n for n in b.nodes if n.kind in STRUCTURE_KINDS]
    taken: set[str] = set()
    changes: list[NodeChange] = []

    for old in a_nodes:
        best: Node | None = None
        best_ov = 0.0
        for new in b_nodes:
            if new.id in taken or new.kind != old.kind:
                continue
            if new.end < old.start or new.start > old.end:
                continue
            ov = overlap((old.low, old.high), (new.low, new.high))
            if ov > best_ov:
                best, best_ov = new, ov

        if best is None or best_ov < SAME_NODE_OVERLAP:
            changes.append(NodeChange("vanished", old, None))
            continue

        taken.add(best.id)
        dl, dh = best.low - old.low, best.high - old.high
        moved = abs(dl) > tol or abs(dh) > tol
        changes.append(NodeChange("moved" if moved else "survived", old, best, dl, dh))

    for new in b_nodes:
        if new.id not in taken:
            changes.append(NodeChange("appeared", None, new))

    return SnapshotDiff(a.version, b.version, tuple(changes))


# ─────────────────────────────────────────────────────────────────────────────
# JSON — the machine-readable artefact a later layer consumes
# ─────────────────────────────────────────────────────────────────────────────
def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    return value


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _rotation(d: dict) -> Rotation:
    return Rotation(d["direction"], d["from_i"], d["to_i"], _dec(d["points"]),
                    d.get("from_node"), d.get("to_node"))


def _node(d: dict) -> Node:
    return Node(
        id=d["id"], kind=d["kind"], start=d["start"], end=d["end"],
        low=_dec(d["low"]), high=_dec(d["high"]),
        parent=d.get("parent"), children=tuple(d.get("children", ())),
        depth=d.get("depth", 0),
        origin=d.get("origin"), exit=d.get("exit"), role=d.get("role", "active"),
        location=d.get("location", ""),
        position_in_parent=_dec(d.get("position_in_parent")),
        rotations=tuple(_rotation(r) for r in d.get("rotations", ())),
        upper_touches=d.get("upper_touches", 0), lower_touches=d.get("lower_touches", 0),
        score=d.get("score", 0.0), parts=dict(d.get("parts", {})),
        window=d.get("window", 0), migration=d.get("migration", 0.0),
        measurements=dict(d.get("measurements", {})),
        spans_sessions=d.get("spans_sessions", False),
        provisional=d.get("provisional", False))


def to_json(snap: MapSnapshot, log: LiveLog | None = None) -> str:
    payload = {
        "version": snap.version, "symbol": snap.symbol,
        "label": snap.label(),
        "built_at": snap.built_at.isoformat(),
        "built_at_index": snap.built_at_index, "first_index": snap.first_index,
        "nodes": [_plain(n) for n in snap.nodes],
        "relations": [_plain(r) for r in snap.relations],
        "live_events": [_plain(e) for e in (log.events if log else ())],
    }
    return json.dumps(payload, indent=1)


def from_json(text: str) -> tuple[MapSnapshot, LiveLog]:
    d = json.loads(text)
    snap = MapSnapshot(
        version=d["version"], symbol=d["symbol"],
        built_at=datetime.fromisoformat(d["built_at"]),
        built_at_index=d["built_at_index"], first_index=d["first_index"],
        nodes=tuple(_node(n) for n in d["nodes"]),
        relations=tuple(Relation(r["src"], r["kind"], r["dst"], r["at"],
                                 r.get("detail", "")) for r in d["relations"]))
    log = LiveLog(snap)
    for e in d.get("live_events", ()):
        log.append(LiveEvent(e["kind"], e["node_id"], e["index"],
                             datetime.fromisoformat(e["at"]), e.get("direction", ""),
                             _dec(e.get("level")), e.get("detail", ""),
                             dict(e.get("evidence", {}))))
    return snap, log


def write(snap: MapSnapshot, path: Path, log: LiveLog | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(snap, log), encoding="utf-8")
    return path


__all__ = ["MapSnapshot", "LiveEvent", "LiveLog", "LiveEventLog", "NodeChange",
           "SnapshotDiff", "EVENT_KINDS", "SAME_NODE_OVERLAP", "build_snapshot",
           "next_version", "diff", "to_json", "from_json", "write"]
