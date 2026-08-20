"""One read-only structural market frame per closed candle.

The frame joins observations that already exist. It does not scan candles, choose
structures, or decide direction. Its only job is to preserve the facts emitted for one
candle in a single immutable value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.boxes.frontier import Frontier, Reading
from src.boxes.snapshot import MapSnapshot
from src.livemap import eye as EY
from src.livemap import reference as RF
from src.livemap import release as RL
from src.livemap import thesis as TH
from src.livemap.interpreter import Interpreter, MapState


@dataclass(frozen=True, slots=True)
class LocalStructure:
    """A passive local observation supplied by a research caller."""

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
    """The complete joined facts available on one closed candle."""

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
    local_low: Decimal | None = None
    local_high: Decimal | None = None
    distance_to_local_low: Decimal | None = None
    distance_to_local_high: Decimal | None = None
    micro_id: str | None = None
    approaching_current_upper: bool = False
    approaching_current_lower: bool = False
    approached_edges: tuple[str, ...] = ()
    broken_edges: tuple[str, ...] = ()
    broken_releases: tuple[RL.Release, ...] = ()
    left_id: str | None = None
    active_release: RL.Release | None = None
    broader_thesis_invalidation: Decimal | None = None

    def lines(self) -> list[str]:
        cur = self.map.current
        broad = "none" if cur is None else (
            f"{cur.id} {cur.band} | low {float(cur.low):,.1f} | high {float(cur.high):,.1f}"
        )
        local = "none" if self.local is None else (
            f"{self.local.id} {self.local.band} | low {float(self.local.low):,.1f} | "
            f"high {float(self.local.high):,.1f}"
        )
        micro = self.reading.micro
        micro_text = "none" if micro is None else (
            f"{micro.micro_id or 'none'} {micro.micro_state or 'none'} | "
            f"low {_number(micro.micro_low)} | high {_number(micro.micro_high)}"
        )
        delta = self.eye.delta("price")
        delta_text = "none" if delta is None or delta.change is None else _signed(delta.change)
        upper_distance = self.eye.upper.distance if self.eye.upper is not None else None
        lower_distance = self.eye.lower.distance if self.eye.lower is not None else None
        releases = ("none" if not self.broken_releases else " | ".join(
            f"{item.id} {item.scale} {item.boundary} {item.direction}"
            for item in self.broken_releases
        ))
        active = ("none" if self.active_release is None else
                  f"{self.active_release.id} {self.active_release.scale} "
                  f"{self.active_release.boundary}")
        next_above = self.map.above.next.id if self.map.above.next is not None else "none"
        next_below = self.map.below.next.id if self.map.below.next is not None else "none"
        identity = TH.identity_of(self.thesis)
        thesis_text = (
            f"{identity or 'none'} | {self.thesis.idea} | "
            f"generation {self.thesis.generation} | {self.thesis.thesis_status}"
        )
        return [
            f"{self.at:%H:%M}",
            f"PRICE {float(self.price):,.1f}",
            f"BROAD {broad}",
            f"LOCAL {local}",
            f"MICRO {micro_text}",
            f"DELTA {delta_text}",
            f"CURRENT EDGE DISTANCES upper {_number(upper_distance)} | "
            f"lower {_number(lower_distance)}",
            f"WATCH ABOVE {self.eye.watch_above or 'none'}",
            f"WATCH BELOW {self.eye.watch_below or 'none'}",
            f"APPROACHED EDGES {', '.join(self.approached_edges) or 'none'}",
            f"RELEASES ON THIS CANDLE {releases}",
            f"ACTIVE RELEASE {active}",
            f"LEFT STRUCTURE {self.left_id or 'none'}",
            f"NEXT REFERENCES above {next_above} | below {next_below}",
            f"BROADER THESIS {thesis_text}",
            "BROADER THESIS INVALIDATION "
            + _number(self.broader_thesis_invalidation),
        ]


def _number(value: Decimal | None) -> str:
    return "none" if value is None else f"{float(value):,.1f}"


def _signed(value: Decimal) -> str:
    return f"{float(value):+,.1f}"


def _approached_edges(state: MapState) -> tuple[str, ...]:
    found: list[str] = []
    if state.status in {"APPROACHING_UPPER", "BREAK_ATTEMPT_UP"}:
        if state.break_up is not None:
            found.append("current.upper")
    if state.status in {"APPROACHING_LOWER", "BREAK_ATTEMPT_DOWN"}:
        if state.break_down is not None:
            found.append("current.lower")
    if state.route_above is not None and state.route_above.watch != "FAR_FROM_NEXT_ZONE":
        found.append("watch.above")
    if state.route_below is not None and state.route_below.watch != "FAR_FROM_NEXT_ZONE":
        found.append("watch.below")
    return tuple(dict.fromkeys(found))


def build(reading: Reading, state: MapState, eye: EY.EyeState,
          release: RL.ReleaseState, references: RF.ReferencePath,
          thesis: TH.LiveThesis, *,
          local: LocalStructure | None = None) -> StructuralFrame:
    approached = _approached_edges(state)
    local_low = local.low if local is not None else None
    local_high = local.high if local is not None else None
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
        local_low=local_low,
        local_high=local_high,
        distance_to_local_low=(state.price - local_low if local_low is not None else None),
        distance_to_local_high=(local_high - state.price if local_high is not None else None),
        micro_id=reading.micro.micro_id if reading.micro is not None else None,
        approaching_current_upper="current.upper" in approached,
        approaching_current_lower="current.lower" in approached,
        approached_edges=approached,
        broken_edges=tuple(item.boundary for item in release.releases),
        broken_releases=release.releases,
        left_id=state.left_id,
        active_release=release.active,
        broader_thesis_invalidation=thesis.invalidation_price,
    )


def observe(snapshot: MapSnapshot, frontier: Frontier, *,
            locals_by_index: dict[int, LocalStructure] | None = None,
            upto: int | None = None) -> list[StructuralFrame]:
    """Join the observation layers already emitted for each available candle."""

    interpreter = Interpreter(snapshot, frontier)
    states = {state.index: state for state in interpreter.states()}
    eyes = {state.index: state for state in EY.observe(snapshot, frontier)}
    releases = {state.index: state for state in RL.observe(frontier, snapshot)}
    theses = {state.index: state for state in TH.narrate(snapshot, frontier)}
    supplied = dict(locals_by_index or {})

    out: list[StructuralFrame] = []
    for reading in frontier.readings:
        if upto is not None and reading.index > upto:
            break
        state = states[reading.index]
        pool = interpreter.pool_at(reading.index)
        nodes = {node.id: node for node in pool}
        thesis = theses[reading.index]
        references = RF.build(
            state, nodes, idea=thesis.idea,
            invalidation_price=thesis.invalidation_price,
            invalidation_rule=thesis.invalidation,
            pool=pool,
        )
        out.append(build(
            reading, state, eyes[reading.index], releases[reading.index],
            references, thesis, local=supplied.get(reading.index)))
    return out


def compact(frame: StructuralFrame) -> str:
    return " | ".join(frame.lines())


__all__ = ["LocalStructure", "StructuralFrame", "build", "observe", "compact"]
