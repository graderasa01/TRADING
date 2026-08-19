"""
The authoritative list of structural breaks — from the **event log**, not the interaction.

This module exists because of one measurement. Over 29 replay blocks of real Bank Nifty
5m:

```
distinct breaks                     578
  reported as ACCEPTED_*            457
  overwritten                       121  (21%)  — mostly REVISIT, some NEW_CLUSTER
```

`Frontier.on_candle` step 1 sets `interaction = "ACCEPTED_ABOVE"` and clears
`self.current`. Step 3 then runs **on the same candle** — `current` is now `None`, so the
frontier immediately re-adopts or mints — and unconditionally reassigns `interaction`.
The break still happened, the break event is still in the log, and the reading no longer
names it. `self.left` is cleared by the same step, so `Reading.left_id` and
`Reading.left_edge` go with it.

So *"read the interaction"* silently loses one break in five. Anything that needs the
complete set — Phase D's episodes above all, whose locked rule is that episodes chain
end-to-end from one break to the next — must read the log instead.

## What this module is, and is not

It **is** an information-source correction: one function, resolving the log into records
that carry the geometry the interaction used to supply.

It is **not** a change to break detection. `BREAK_CLOSES`, acceptance, and the meaning of
`ACCEPTED_*` are all exactly as they were; this reads what the frontier already recorded.
No `BreakEpisode` is built here.

## One break, two records

A2 made a **revisited** node's break write twice, and both writes are correct:

```
frontier.py   self._record("break", node.id, side, edge)          -> the owner's log
              if node.revisited:
                  self.live_log.append(LiveEvent("break", ..., "revisit ended",
                                                 node.evidence))  -> live_log
```

The first keeps the owner's log exactly as it was; the second carries the revisit's
accumulated evidence, because a revisited node is never finalised and that evidence would
otherwise die with it. Two records, one break — measured at **991 rows for 578 distinct
breaks**, 42% of rows.

So `from_logs()` collapses on `(index, structure_id, direction)`, keeps the plain record
and folds the twin's `evidence` onto it. Nothing A2 preserved is thrown away, and a
consumer counting episodes counts breaks rather than rows.

## Where the geometry comes from

`LiveEvent` carries the broken edge as `level`, but not the band. On the 208 overwritten
candles `Reading.left_low` / `left_high` are gone too, so the band is resolved from the
node itself:

```
frozen node   MapSnapshot.by_id(node_id)
live node     Frontier.history() — the finalised Node
```

A **revisited** node is never finalised (`Frontier` refuses to duplicate a structure
history already has), so it is found in whichever of the two first knew about it. A break
whose node cannot be resolved in either is reported with `low`/`high` as `None` rather
than dropped — losing a break to keep a dataclass tidy is the failure this module exists
to fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Frontier
from src.boxes.hierarchy import Node
from src.boxes.snapshot import MapSnapshot

#: The two interactions that name a break. A break whose reading says anything else was
#: overwritten by the same candle's re-adopt or mint — see the module docstring.
ACCEPTED = {"ACCEPTED_ABOVE": "up", "ACCEPTED_BELOW": "down"}

#: The **only** event kind that is a break, stated as an allow-list rather than inferred.
#:
#: `EVENT_KINDS` permits nine kinds and `frontier.py` writes three (`break`, `revisit`,
#: `re_entry`). `break` is written in exactly one place — the branch where
#: `closes_beyond >= break_closes` — so it is the *acceptance* event and a `BREAK_ATTEMPT`
#: can never produce one. Six kinds are unwritten today and a future writer could add them,
#: so this is an allow-list of one: a new event kind has to be admitted here deliberately
#: before it can start an episode.
BREAK_KIND = "break"

#: The marker A2 puts on the evidence-carrying twin of a revisited node's break.
REVISIT_ENDED = "revisit ended"

FROZEN = "frozen"      # the break belonged to a node in the snapshot
LIVE = "live"          # ...or to one the frontier minted
SOURCES = frozenset({FROZEN, LIVE})


@dataclass(frozen=True, slots=True)
class BreakRecord:
    """One accepted structural break, lifted from the log.

    Field names deliberately match `retest.Break` so the 1m tool can be pointed at this
    source without reshaping anything — `retest.breaks_from()` reads the interaction and
    therefore carries the same 21% blind spot, but fixing that is its own change and this
    module does not make it.
    """

    index: int
    at: datetime
    structure_id: str
    direction: str                  # up | down
    edge: Decimal | None            # the structure's OWN broken edge
    low: Decimal | None = None
    high: Decimal | None = None
    #: `cluster` | `range`, copied off the broken node. A copy, never a classification —
    #: it is what separates a flip retest from a range-break retest downstream.
    kind: str = ""
    source: str = FROZEN
    #: What the reading said on this candle. `ACCEPTED_ABOVE` / `ACCEPTED_BELOW` when the
    #: interaction survived; the overwriting word otherwise. Diagnostic only.
    interaction: str = ""
    #: What a **revisited** structure had accumulated when it broke — touches, rotations,
    #: dwell. Empty for a break that was not the end of a revisit. Folded here off A2's
    #: twin event, which is the only place it survives at all.
    evidence: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise ValueError(f"direction must be up|down, got {self.direction!r}")
        if self.source not in SOURCES:
            raise ValueError(f"unknown source {self.source!r}")

    @property
    def named_by_interaction(self) -> bool:
        """Whether reading the interaction alone would have found this break."""
        return self.interaction in ACCEPTED

    @property
    def band(self) -> str:
        if self.low is None:
            return "?"
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"


def _resolve(node_id: str, snapshot: MapSnapshot,
             finalised: Sequence[Node]) -> tuple[Node | None, str]:
    node = snapshot.by_id(node_id)
    if node is not None:
        return node, FROZEN
    return next((n for n in finalised if n.id == node_id), None), LIVE


def from_logs(frontier: Frontier, snapshot: MapSnapshot | None = None) -> list[BreakRecord]:
    """Every break the frontier recorded, in candle order, from both logs.

    `Frontier.log` holds what price did to the **frozen** map; `Frontier.live_log` holds
    what it did to structures the frontier built. Phase A2 split them by ownership, and a
    consumer that reads only one of them sees roughly a quarter of the breaks.
    """
    snap = snapshot if snapshot is not None else frontier.snapshot
    finalised = frontier.history()
    at = {r.index: r for r in frontier.readings}

    # One entry per break, keyed by the break itself. A revisited node writes twice; the
    # plain record wins and the twin contributes only its evidence.
    merged: dict[tuple[int, str, str], BreakRecord] = {}
    for event in list(frontier.log) + list(frontier.live_log):
        if event.kind != BREAK_KIND:
            continue
        key = (event.index, event.node_id, event.direction)
        twin = event.detail == REVISIT_ENDED
        seen = merged.get(key)
        if seen is not None:
            # Keep whichever is the plain record; take the evidence from whichever has it.
            merged[key] = BreakRecord(
                **{**{f: getattr(seen, f) for f in
                      ("index", "at", "structure_id", "direction", "edge", "low", "high",
                       "kind", "source", "interaction")},
                   "evidence": dict(seen.evidence or event.evidence)})
            continue
        node, source = _resolve(event.node_id, snap, finalised)
        reading = at.get(event.index)
        merged[key] = BreakRecord(
            index=event.index, at=event.at, structure_id=event.node_id,
            direction=event.direction, edge=event.level,
            low=node.low if node else None, high=node.high if node else None,
            kind=node.kind if node else "", source=source,
            interaction=reading.interaction if reading else "",
            evidence=dict(event.evidence) if twin else {})
    return sorted(merged.values(), key=lambda b: (b.index, b.structure_id))


def hidden(records: Sequence[BreakRecord]) -> list[BreakRecord]:
    """The breaks a consumer reading `Reading.interaction` would never have seen."""
    return [b for b in records if not b.named_by_interaction]


__all__ = ["ACCEPTED", "BREAK_KIND", "REVISIT_ENDED", "FROZEN", "LIVE", "SOURCES",
           "BreakRecord", "from_logs", "hidden"]
