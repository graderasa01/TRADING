"""One read-only structural market frame per closed candle.

The frame joins the livemap observations that already exist. It does not scan candles,
choose structures, score anything, or decide direction. Its job is to make one candle
readable without giving any consumer permission to rebuild the map.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Frontier, Reading
from src.boxes.hierarchy import Node
from src.boxes.snapshot import MapSnapshot
from src.livemap import eye as EY
from src.livemap import reference as RF
from src.livemap import release as RL
from src.livemap import thesis as TH
from src.livemap.interpreter import Interpreter, MapState


@dataclass(frozen=True, slots=True)
class LocalStructure:
    """A published local observation, when research has supplied one.

    This type is intentionally passive. The production frame can carry a local structure,
    but it cannot create one; callers must pass one in by candle index.
    """

    id: str
    kind: str
    low: Decimal
    high: Decimal
    holder_id: str | None = None
    source: str = "research"

    @property
    def band(self) -> str:
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"


@dataclass(frozen=True, slots=True)
class StructuralFrame:
    """The market facts available on one closed candle."""

    index: int
    at: datetime
    price: Decimal
    reading: Reading
    map: MapState
    eye: EY.EyeState
    release: RL.ReleaseState
    references: RF.ReferencePath
    thesis: TH.LiveThesis
    broad_id: str | None = None
    local: LocalStructure | None = None
    micro_id: str | None = None
    approached_edge: str | None = None
    broken_edge: str | None = None
    left_id: str | None = None
    release_held: str | None = None
    local_invalidation: Decimal | None = None
    broader_thesis_invalidation: Decimal | None = None

    def lines(self) -> list[str]:
        cur = self.map.current
        broad = "none" if cur is None else f"{cur.id} {cur.band}"
        local = "none" if self.local is None else f"{self.local.id} {self.local.band}"
        micro = self.micro_id or "none"
        rel = self.release_held or "none"
        return [
            f"{self.at:%H:%M}",
            f"price {float(self.price):,.1f}",
            f"broad {broad}",
            f"local {local}",
            f"micro {micro}",
            f"approached_edge {self.approached_edge or 'none'}",
            f"broken_edge {self.broken_edge or 'none'}",
            f"release_held {rel}",
            f"left {self.left_id or 'none'}",
            "next_above "
            + (self.map.above.next.id if self.map.above.next is not None else "none"),
            "next_below "
            + (self.map.below.next.id if self.map.below.next is not None else "none"),
            "local_invalidation "
            + ("none" if self.local_invalidation is None
               else f"{float(self.local_invalidation):,.1f}"),
            "broader_thesis_invalidation "
            + ("none" if self.broader_thesis_invalidation is None
               else f"{float(self.broader_thesis_invalidation):,.1f}"),
        ]


def _approached_edge(state: MapState) -> str | None:
    if state.status in {"APPROACHING_UPPER", "BREAK_ATTEMPT_UP"} and state.break_up is not None:
        return "upper"
    if state.status in {"APPROACHING_LOWER", "BREAK_ATTEMPT_DOWN"} and state.break_down is not None:
        return "lower"
    if state.route_above is not None and state.route_above.watch != "FAR_FROM_NEXT_ZONE":
        return "next_above"
    if state.route_below is not None and state.route_below.watch != "FAR_FROM_NEXT_ZONE":
        return "next_below"
    return None


def _local_invalidation(frame_local: LocalStructure | None, state: MapState) -> Decimal | None:
    if frame_local is not None:
        middle = (frame_local.low + frame_local.high) / Decimal(2)
        return frame_local.low if state.price >= middle else frame_local.high
    cur = state.current
    if cur is None:
        return None
    middle = (cur.low + cur.high) / Decimal(2)
    return cur.low if state.price >= middle else cur.high


def build(reading: Reading, state: MapState, eye: EY.EyeState,
          release: RL.ReleaseState, references: RF.ReferencePath,
          thesis: TH.LiveThesis, *,
          local: LocalStructure | None = None) -> StructuralFrame:
    active = release.active
    first_release = release.releases[0] if release.releases else None
    return StructuralFrame(
        index=reading.index,
        at=state.at,
        price=state.price,
        reading=reading,
        map=state,
        eye=eye,
        release=release,
        references=references,
        thesis=thesis,
        broad_id=state.current.id if state.current is not None else None,
        local=local,
        micro_id=reading.micro.micro_id if reading.micro is not None else None,
        approached_edge=_approached_edge(state),
        broken_edge=first_release.boundary if first_release is not None else None,
        left_id=state.left_id,
        release_held=active.boundary if active is not None else None,
        local_invalidation=_local_invalidation(local, state),
        broader_thesis_invalidation=thesis.invalidation_price,
    )


def observe(snapshot: MapSnapshot, frontier: Frontier, *,
            locals_by_index: dict[int, LocalStructure] | None = None,
            upto: int | None = None) -> list[StructuralFrame]:
    """Join existing causal observations.

    `locals_by_index` is optional research input. Passing it does not alter the map and
    this function never imports or invokes a detector.
    """

    interpreter = Interpreter(snapshot, frontier)
    states = {s.index: s for s in interpreter.states()}
    eyes = {e.index: e for e in EY.observe(snapshot, frontier)}
    releases = {s.index: s for s in RL.observe(frontier, snapshot)}
    theses = {t.index: t for t in TH.narrate(snapshot, frontier)}
    locals_by_index = dict(locals_by_index or {})

    out: list[StructuralFrame] = []
    for reading in frontier.readings:
        if upto is not None and reading.index > upto:
            break
        state = states[reading.index]
        pool = interpreter.pool_at(reading.index)
        nodes = {n.id: n for n in pool}
        thesis = theses[reading.index]
        refs = RF.build(
            state, nodes, idea=thesis.idea,
            invalidation_price=thesis.invalidation_price,
            invalidation_rule=thesis.invalidation,
            pool=pool,
        )
        out.append(build(
            reading, state, eyes[reading.index], releases[reading.index],
            refs, thesis, local=locals_by_index.get(reading.index)))
    return out


def compact(frame: StructuralFrame) -> str:
    return " | ".join(frame.lines())


__all__ = ["LocalStructure", "StructuralFrame", "build", "observe", "compact"]
