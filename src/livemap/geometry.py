"""STRUCTURAL OPPORTUNITY GEOMETRY — what the controlling structure actually is.

```
StructuralFrame  →  StructureGeometry  →  replay inspector / population study
```

This layer answers seven questions and deliberately stops before the eighth:

1. where is price,
2. what structure contains it,
3. how large and spacious that structure is,
4. where the current movement came from,
5. how much internal structural space remains,
6. how much external space exists above and below,
7. which edge or reference is the next real decision area,

and **not** *should participation occur*.  Nothing here scores, ranks, weights or
recommends, and nothing here is read by the hypothesis brain.

## Broad is a role, not a size

`Broad` / *controlling structure* is the **role** a node currently plays: it is the node
price is standing in.  `cluster` and `range` are its **kind**, straight off
`boxes.structure.STRUCTURE_KINDS`, and this module never collapses them into one another
and never calls a controlling node a "Broad range".

The role says nothing about width.  A controlling structure may be 20 points wide or 200.
That distinction is the whole reason this module exists: an internal edge-to-edge rotation
inside a 20-point cluster and one inside a 200-point range are not the same opportunity,
and until now the stack exposed no fact that told them apart.

## It measures, it does not classify by size

There is no `SMALL`/`BIG` rule here, no width cutoff, no ATR bound, no fitted threshold.
The states in `INTERNAL_SPACE_STATES` are pure topology — is price contained, has it passed
the midpoint of its own movement, is it at an edge the map already published as approached,
does a mapped reference exist — and every one of them is derivable from a fact some other
layer already emitted.  The width numbers are reported raw so a human can see the real
population before anyone proposes a rule about it.

## Two midpoints, never conflated

`ControllingStructure.midpoint` is `(low + high) / 2` of the frozen controlling node.  It
does not move while that node is controlling.  `MovementProvenance.path_midpoint` is the
midpoint between a **frozen movement origin** and that movement's frozen destination, and
exists only when both do.  They answer different questions and are never the same field.

## Causality

`GeometryObserver` is fed closed candles in order and keeps only the previous frame's
price and its own movement anchor.  An emitted `StructureGeometry` is frozen and no later
candle can alter it.  This layer never writes back to the map, the frontier, the
detectors, the references, the thesis or the brain.

## The movement anchor here is observational

`livemap.shadow.DynamicShadowTrader` keeps its own movement anchor and that one remains
the decision authority; this module never feeds it and never reads it.  The anchor here
follows the same published facts for the same reasons, and
`test_the_observational_anchor_agrees_with_the_brain` plus the study's
`G6_PROVENANCE_CAUSAL` ledger check that the two agree on real data, so a divergence is
caught rather than discovered later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.models import ZERO
from src.livemap.frame import StructuralFrame

UP = "up"
DOWN = "down"

UNKNOWN = "UNKNOWN"

#: Topological readings of the internal space. No width rule, no fitted bound.
INTERNAL_GEOMETRY_AVAILABLE = "INTERNAL_GEOMETRY_AVAILABLE"
INTERNAL_GEOMETRY_CONSUMED = "INTERNAL_GEOMETRY_CONSUMED"
AT_EDGE_DECISION = "AT_EDGE_DECISION"
OUTSIDE_REFERENCE_AVAILABLE = "OUTSIDE_REFERENCE_AVAILABLE"
NO_MAPPED_SPACE = "NO_MAPPED_SPACE"
INTERNAL_SPACE_STATES = frozenset({
    INTERNAL_GEOMETRY_AVAILABLE,
    INTERNAL_GEOMETRY_CONSUMED,
    AT_EDGE_DECISION,
    OUTSIDE_REFERENCE_AVAILABLE,
    NO_MAPPED_SPACE,
    UNKNOWN,
})

#: Which structural price the current movement started from.
BROAD_LOWER_EDGE = "BROAD_LOWER_EDGE"
BROAD_UPPER_EDGE = "BROAD_UPPER_EDGE"
RELEASED_EDGE = "RELEASED_EDGE"
MOVEMENT_ORIGIN_ROLES = frozenset({BROAD_LOWER_EDGE, BROAD_UPPER_EDGE, RELEASED_EDGE})

#: Segment names are the ones the dynamic research layer already publishes, so a reader
#: comparing a geometry trace with a shadow decision is not reading two vocabularies.
ORIGIN_TO_MIDPOINT = "ORIGIN_TO_MIDPOINT"
MIDPOINT_TO_OPPOSITE_EDGE = "MIDPOINT_TO_OPPOSITE_EDGE"
OUTSIDE_EDGE_TO_MAPPED_REFERENCE = "OUTSIDE_EDGE_TO_MAPPED_REFERENCE"
NO_STRUCTURAL_SEGMENT = "NO_STRUCTURAL_SEGMENT"

#: The next internal thing price would meet, named rather than measured against a bound.
BROAD_MIDPOINT_LANDMARK = "BROAD_MIDPOINT"
OPPOSITE_EDGE_LANDMARK = "OPPOSITE_BROAD_EDGE"

#: Provenance vocabulary. Every member is an event some existing layer already publishes.
STRUCTURE_BECAME_CONTROLLING = "STRUCTURE_BECAME_CONTROLLING"
CONTROLLING_STRUCTURE_REPLACED = "CONTROLLING_STRUCTURE_REPLACED"
LOWER_EDGE_ORIGIN = "LOWER_EDGE_ORIGIN"
UPPER_EDGE_ORIGIN = "UPPER_EDGE_ORIGIN"
ACCEPTED_RELEASE_UP = "ACCEPTED_RELEASE_UP"
ACCEPTED_RELEASE_DOWN = "ACCEPTED_RELEASE_DOWN"
REENTRY = "REENTRY"
MIDPOINT_CROSSED = "MIDPOINT_CROSSED"
OPPOSITE_EDGE_REACHED = "OPPOSITE_EDGE_REACHED"
NEW_LOCAL_STRUCTURE_OBSERVED = "NEW_LOCAL_STRUCTURE_OBSERVED"
PROVENANCE_EVENTS = frozenset({
    STRUCTURE_BECAME_CONTROLLING,
    CONTROLLING_STRUCTURE_REPLACED,
    LOWER_EDGE_ORIGIN,
    UPPER_EDGE_ORIGIN,
    ACCEPTED_RELEASE_UP,
    ACCEPTED_RELEASE_DOWN,
    REENTRY,
    MIDPOINT_CROSSED,
    OPPOSITE_EDGE_REACHED,
    NEW_LOCAL_STRUCTURE_OBSERVED,
})

INSIDE = "INSIDE"
ABOVE = "ABOVE"
BELOW = "BELOW"
ABSENT = "ABSENT"


def _atr_ratio(value: Decimal | None, atr: Decimal) -> float | None:
    if value is None or atr is None or atr <= ZERO:
        return None
    return float(value / atr)


def _fraction(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator <= ZERO:
        return None
    return float(numerator / denominator)


def _directional(origin: Decimal, price: Decimal, direction: str) -> Decimal:
    return price - origin if direction == UP else origin - price


def _remaining(price: Decimal, destination: Decimal, direction: str) -> Decimal:
    return max(ZERO, destination - price if direction == UP else price - destination)


def _containment(price: Decimal, low: Decimal | None, high: Decimal | None) -> str:
    """Where price is against real edges — never inferred from a status string."""

    if low is None or high is None:
        return ABSENT
    if price < low:
        return BELOW
    if price > high:
        return ABOVE
    return INSIDE


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class ProvenanceEvent:
    """One structural thing that happened, with where it happened."""

    index: int
    event: str
    structure_id: str | None = None
    structure_kind: str | None = None
    price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.event not in PROVENANCE_EVENTS:
            raise ValueError(f"unknown provenance event {self.event!r}")

    def line(self) -> str:
        where = f" {self.structure_id}" if self.structure_id else ""
        kind = f" ({self.structure_kind})" if self.structure_kind else ""
        at = f" @ {float(self.price):,.1f}" if self.price is not None else ""
        return f"c{self.index} {self.event}{where}{kind}{at}"


@dataclass(frozen=True, slots=True)
class ControllingStructure:
    """The node price is standing in: its identity, its real kind, and its size."""

    structure_id: str
    kind: str
    low: Decimal
    high: Decimal
    midpoint: Decimal
    width_points: Decimal
    width_atr: float | None
    parent_id: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if self.high <= self.low:
            raise ValueError("a controlling structure must have positive width")


@dataclass(frozen=True, slots=True)
class PriceGeometry:
    """Where price stands relative to the controlling structure's three prices."""

    price: Decimal
    price_location: str
    containment: str
    distance_to_lower_points: Decimal | None = None
    distance_to_lower_atr: float | None = None
    distance_to_midpoint_points: Decimal | None = None
    distance_to_midpoint_atr: float | None = None
    distance_to_upper_points: Decimal | None = None
    distance_to_upper_atr: float | None = None


@dataclass(frozen=True, slots=True)
class InternalSpace:
    """Structural room left inside the controlling structure. Not a target, not a reward."""

    state: str
    room_to_lower_edge_points: Decimal | None = None
    room_to_lower_edge_atr: float | None = None
    room_to_midpoint_points: Decimal | None = None
    room_to_midpoint_atr: float | None = None
    room_to_upper_edge_points: Decimal | None = None
    room_to_upper_edge_atr: float | None = None
    next_internal_landmark: str | None = None
    room_to_next_internal_landmark_points: Decimal | None = None
    room_to_next_internal_landmark_atr: float | None = None
    room_to_opposite_edge_points: Decimal | None = None
    room_to_opposite_edge_atr: float | None = None

    def __post_init__(self) -> None:
        if self.state not in INTERNAL_SPACE_STATES:
            raise ValueError(f"unknown internal space state {self.state!r}")


@dataclass(frozen=True, slots=True)
class ExternalReference:
    """One immediate mapped reference, copied. Never fabricated when none exists."""

    structure_id: str
    kind: str
    label: str
    price: Decimal
    direction: str
    #: distance the reference layer published, measured from the edge that would break
    edge_distance_points: Decimal
    edge_distance_atr: float | None
    #: distance from where price actually is now
    price_distance_points: Decimal
    price_distance_atr: float | None


@dataclass(frozen=True, slots=True)
class ExternalSpace:
    """What lies beyond each edge. Up and down stay separate, and absent stays absent."""

    next_reference_above: ExternalReference | None = None
    next_reference_below: ExternalReference | None = None
    room_above_current_upper_to_next_reference_points: Decimal | None = None
    room_above_current_upper_to_next_reference_atr: float | None = None
    room_below_current_lower_to_next_reference_points: Decimal | None = None
    room_below_current_lower_to_next_reference_atr: float | None = None
    room_from_current_price_to_immediate_reference_above_points: Decimal | None = None
    room_from_current_price_to_immediate_reference_above_atr: float | None = None
    room_from_current_price_to_immediate_reference_below_points: Decimal | None = None
    room_from_current_price_to_immediate_reference_below_atr: float | None = None
    outside_released_structure_id: str | None = None
    released_edge: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MovementProvenance:
    """Where this movement started, how far it has come, and how it got here."""

    direction: str | None
    origin_index: int | None = None
    origin_price: Decimal | None = None
    origin_reference: str | None = None
    origin_structure_id: str | None = None
    origin_structure_kind: str | None = None
    origin_role: str | None = None
    outside: bool = False
    destination_price: Decimal | None = None
    destination_reference: str | None = None
    #: midpoint of the frozen origin→destination path — NOT the structure's own midpoint
    path_midpoint: Decimal | None = None
    travelled_points: Decimal | None = None
    travelled_atr: float | None = None
    remaining_points: Decimal | None = None
    remaining_atr: float | None = None
    whole_movement_fraction: float | None = None
    current_segment: str = NO_STRUCTURAL_SEGMENT
    current_segment_fraction: float | None = None
    midpoint_crossed: bool | None = None
    opposite_edge_reached: bool | None = None
    events: tuple[ProvenanceEvent, ...] = ()

    def __post_init__(self) -> None:
        if self.direction is not None and self.direction not in (UP, DOWN):
            raise ValueError("movement direction must be up, down, or None")
        if self.origin_role is not None and self.origin_role not in MOVEMENT_ORIGIN_ROLES:
            raise ValueError(f"unknown movement origin role {self.origin_role!r}")

    def story(self) -> str:
        return " -> ".join(item.line() for item in self.events) or "no recorded provenance"


@dataclass(frozen=True, slots=True)
class LocalContext:
    """Micro and observational Local, kept apart from each other and from the Broad."""

    micro_state: str = ABSENT
    micro_id: str | None = None
    micro_low: Decimal | None = None
    micro_high: Decimal | None = None
    micro_width_points: Decimal | None = None
    micro_width_atr: float | None = None
    price_location_vs_micro: str = ABSENT
    local_structure_id: str | None = None
    local_structure_kind: str | None = None
    local_low: Decimal | None = None
    local_high: Decimal | None = None
    local_width_points: Decimal | None = None
    local_width_atr: float | None = None
    local_holder_id: str | None = None
    price_location_vs_local: str = ABSENT


@dataclass(frozen=True, slots=True)
class StructureGeometry:
    """One closed candle's complete structural opportunity geometry. Immutable."""

    index: int
    at: datetime
    price: Decimal
    atr: Decimal
    tolerance: Decimal
    controlling: ControllingStructure | None
    price_geometry: PriceGeometry
    internal: InternalSpace
    external: ExternalSpace
    movement: MovementProvenance
    local: LocalContext
    structural_events: tuple[str, ...] = ()

    @property
    def controlling_structure_id(self) -> str | None:
        return self.controlling.structure_id if self.controlling else None

    @property
    def controlling_structure_kind(self) -> str | None:
        return self.controlling.kind if self.controlling else None

    def lines(self) -> list[str]:
        """A deterministic human-readable block — the textual replay inspector's row."""

        cur = self.controlling
        structure = "none" if cur is None else (
            f"{cur.structure_id} {cur.kind} "
            f"{float(cur.low):,.1f} / {float(cur.midpoint):,.1f} / {float(cur.high):,.1f} "
            f"| width {float(cur.width_points):,.1f} pts"
            + (f" / {cur.width_atr:.2f} ATR" if cur.width_atr is not None else ""))
        mv = self.movement
        movement = "not established" if mv.direction is None else (
            f"{mv.direction.upper()} from {mv.origin_reference} "
            f"({mv.origin_role}, {mv.origin_structure_kind or 'unknown kind'}) "
            f"@ {float(mv.origin_price):,.1f}" if mv.origin_price is not None
            else f"{mv.direction.upper()}")
        above = self.external.next_reference_above
        below = self.external.next_reference_below
        return [
            f"{self.at:%Y-%m-%d %H:%M}  c{self.index}  close {float(self.price):,.1f}",
            f"CONTROLLING   {structure}",
            f"PRICE         {self.price_geometry.price_location} "
            f"({self.price_geometry.containment}) | to low "
            f"{_pts(self.price_geometry.distance_to_lower_points)} | to mid "
            f"{_pts(self.price_geometry.distance_to_midpoint_points)} | to high "
            f"{_pts(self.price_geometry.distance_to_upper_points)}",
            f"INTERNAL      {self.internal.state} | next landmark "
            f"{self.internal.next_internal_landmark or 'none'} "
            f"{_pts(self.internal.room_to_next_internal_landmark_points)} | to opposite edge "
            f"{_pts(self.internal.room_to_opposite_edge_points)}",
            f"EXTERNAL      above "
            f"{above.label if above else 'none'} {_pts(above.price_distance_points if above else None)}"
            f" | below "
            f"{below.label if below else 'none'} {_pts(below.price_distance_points if below else None)}",
            f"MOVEMENT      {movement} | travelled {_pts(mv.travelled_points)} | whole "
            f"{_frac(mv.whole_movement_fraction)} | segment {mv.current_segment} "
            f"{_frac(mv.current_segment_fraction)}",
            f"PATH MIDPOINT {_price(mv.path_midpoint)}   "
            f"BROAD MIDPOINT {_price(cur.midpoint if cur else None)}",
            f"LOCAL         micro {self.local.micro_id or 'none'} "
            f"{self.local.micro_state} ({self.local.price_location_vs_micro}) | local "
            f"{self.local.local_structure_id or 'none'} "
            f"({self.local.price_location_vs_local})",
            f"EVENTS        {', '.join(self.structural_events) or 'none'}",
            f"PROVENANCE    {mv.story()}",
        ]


#: `lines()` is printed by a terminal inspector on Windows consoles, so the renderers
#: below stay ASCII: a cp1252 terminal raises on an em dash or an arrow.
def _pts(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{float(value):,.1f}"


def _price(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{float(value):,.1f}"


def _frac(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class _Anchor:
    """Mutable internal movement anchor. Never emitted; only copied into a frozen view."""

    structure_id: str
    structure_kind: str | None
    structure_low: Decimal
    structure_high: Decimal
    origin_index: int
    origin_price: Decimal
    origin_reference: str
    origin_role: str
    direction: str | None
    outside: bool = False
    destination_price: Decimal | None = None
    destination_reference: str | None = None
    #: latched: a MIDPOINT_CROSSED / OPPOSITE_EDGE_REACHED event happened once and stays
    #: in the provenance chain. The *current* segment is re-read from price every candle,
    #: exactly as `shadow.MovementState` does, so the two layers cannot disagree.
    midpoint_event_recorded: bool = False
    opposite_edge_event_recorded: bool = False
    events: list[ProvenanceEvent] = field(default_factory=list)


class GeometryObserver:
    """Feed it closed candles in order; it emits one frozen `StructureGeometry` each.

    It carries the previous candle's price and its own movement anchor, and nothing else.
    It writes to no other layer.
    """

    def __init__(self) -> None:
        self.geometries: list[StructureGeometry] = []
        self._anchor: _Anchor | None = None
        self._previous_price: Decimal | None = None
        self._previous_broad: str | None = None
        self._previous_local: str | None = None
        self._last_index: int | None = None

    # ── the public seam ─────────────────────────────────────────────────────
    def observe(self, frame: StructuralFrame, *, tolerance: Decimal) -> StructureGeometry:
        if self._last_index is not None and frame.index <= self._last_index:
            raise AssertionError("closed-candle indices must be strictly increasing")
        controlling = _controlling_of(frame)
        events = self._update_anchor(frame, controlling, tolerance)
        geometry = StructureGeometry(
            index=frame.index,
            at=frame.at,
            price=frame.price,
            atr=frame.map.atr,
            tolerance=tolerance,
            controlling=controlling,
            price_geometry=_price_geometry(frame, controlling),
            internal=self._internal(frame, controlling),
            external=_external(frame, controlling),
            movement=self._movement(frame, controlling, tolerance),
            local=_local(frame),
            structural_events=events,
        )
        self.geometries.append(geometry)
        self._previous_price = frame.price
        self._previous_broad = controlling.structure_id if controlling else None
        self._previous_local = frame.local.id if frame.local is not None else None
        self._last_index = frame.index
        return geometry

    # ── movement anchor and provenance ──────────────────────────────────────
    def _record(self, event: ProvenanceEvent) -> None:
        if self._anchor is not None:
            self._anchor.events.append(event)

    def _restart(self, anchor: _Anchor, carried: ProvenanceEvent | None) -> None:
        """A new movement begins. Keep one carried event so the reader sees the hand-off."""

        self._anchor = anchor
        anchor.events.clear()
        if carried is not None:
            anchor.events.append(carried)

    def _update_anchor(
            self, frame: StructuralFrame, controlling: ControllingStructure | None,
            tolerance: Decimal,
            ) -> tuple[str, ...]:
        emitted: list[str] = []
        previous_tail = (self._anchor.events[-1] if self._anchor and self._anchor.events
                         else None)
        accepted = _accepted_direction(frame)

        if (accepted is not None and frame.left_id is not None
                and frame.map.left_low is not None and frame.map.left_high is not None):
            edge = frame.map.left_high if accepted == UP else frame.map.left_low
            anchor = _Anchor(
                structure_id=frame.left_id,
                structure_kind=frame.reading.left_kind,
                structure_low=frame.map.left_low,
                structure_high=frame.map.left_high,
                origin_index=frame.index,
                origin_price=edge,
                origin_reference=f"{frame.left_id}.{'high' if accepted == UP else 'low'}",
                origin_role=RELEASED_EDGE,
                direction=accepted,
                outside=True,
                destination_price=None,
                destination_reference=None,
            )
            reference = _immediate(frame, accepted)
            if reference is not None:
                anchor.destination_price = reference.price
                anchor.destination_reference = reference.label
            self._restart(anchor, previous_tail)
            event = ACCEPTED_RELEASE_UP if accepted == UP else ACCEPTED_RELEASE_DOWN
            self._record(ProvenanceEvent(
                frame.index, event, frame.left_id, frame.reading.left_kind, edge))
            emitted.append(event)
            self._note_local(frame, emitted)
            return tuple(emitted)

        if controlling is None:
            if self._anchor is not None and not self._anchor.outside:
                self._anchor = None
            self._note_local(frame, emitted)
            return tuple(emitted)

        same = self._anchor is not None and self._anchor.structure_id == controlling.structure_id
        if not same:
            replaced = self._previous_broad is not None
            carried = previous_tail
            self._anchor = None
            role = _origin_area(frame, controlling, tolerance)
            if role is not None:
                low_origin = role == BROAD_LOWER_EDGE
                anchor = _Anchor(
                    structure_id=controlling.structure_id,
                    structure_kind=controlling.kind,
                    structure_low=controlling.low,
                    structure_high=controlling.high,
                    origin_index=frame.index,
                    origin_price=controlling.low if low_origin else controlling.high,
                    origin_reference=(
                        f"{controlling.structure_id}.{'low' if low_origin else 'high'}"),
                    origin_role=role,
                    direction=None,
                )
                self._restart(anchor, carried)
                event = (CONTROLLING_STRUCTURE_REPLACED if replaced
                         else STRUCTURE_BECAME_CONTROLLING)
                self._record(ProvenanceEvent(
                    frame.index, event, controlling.structure_id, controlling.kind,
                    controlling.low if low_origin else controlling.high))
                emitted.append(event)
                origin_event = LOWER_EDGE_ORIGIN if low_origin else UPPER_EDGE_ORIGIN
                self._record(ProvenanceEvent(
                    frame.index, origin_event, controlling.structure_id, controlling.kind,
                    controlling.low if low_origin else controlling.high))
                emitted.append(origin_event)
            self._note_local(frame, emitted)
            return tuple(emitted)

        anchor = self._anchor
        assert anchor is not None
        if anchor.outside and _reentry(frame):
            from_upper = anchor.direction == UP
            restarted = _Anchor(
                structure_id=controlling.structure_id,
                structure_kind=controlling.kind,
                structure_low=controlling.low,
                structure_high=controlling.high,
                origin_index=frame.index,
                origin_price=controlling.high if from_upper else controlling.low,
                origin_reference=(
                    f"{controlling.structure_id}.{'high' if from_upper else 'low'}"),
                origin_role=BROAD_UPPER_EDGE if from_upper else BROAD_LOWER_EDGE,
                direction=None,
            )
            self._restart(restarted, previous_tail)
            self._record(ProvenanceEvent(
                frame.index, REENTRY, controlling.structure_id, controlling.kind,
                frame.price))
            emitted.append(REENTRY)
            self._note_local(frame, emitted)
            return tuple(emitted)

        if anchor.direction is None and self._previous_price is not None:
            location = frame.thesis.price_location
            if (anchor.origin_reference.endswith(".low")
                    and frame.price > self._previous_price
                    and location in {"INSIDE", "AT_LOWER_EDGE"}):
                anchor.direction = UP
            elif (anchor.origin_reference.endswith(".high")
                  and frame.price < self._previous_price
                  and location in {"INSIDE", "AT_UPPER_EDGE"}):
                anchor.direction = DOWN

        if anchor.direction is not None and not anchor.outside:
            midpoint = (anchor.structure_low + anchor.structure_high) / Decimal(2)
            crossed = (frame.price >= midpoint if anchor.direction == UP
                       else frame.price <= midpoint)
            if crossed and not anchor.midpoint_event_recorded:
                anchor.midpoint_event_recorded = True
                self._record(ProvenanceEvent(
                    frame.index, MIDPOINT_CROSSED, anchor.structure_id,
                    anchor.structure_kind, midpoint))
                emitted.append(MIDPOINT_CROSSED)
            opposite = (anchor.structure_high if anchor.direction == UP
                        else anchor.structure_low)
            reached = (frame.price >= opposite - tolerance if anchor.direction == UP
                       else frame.price <= opposite + tolerance)
            if reached and not anchor.opposite_edge_event_recorded:
                anchor.opposite_edge_event_recorded = True
                self._record(ProvenanceEvent(
                    frame.index, OPPOSITE_EDGE_REACHED, anchor.structure_id,
                    anchor.structure_kind, opposite))
                emitted.append(OPPOSITE_EDGE_REACHED)

        self._note_local(frame, emitted)
        return tuple(emitted)

    def _note_local(self, frame: StructuralFrame, emitted: list[str]) -> None:
        local_id = frame.local.id if frame.local is not None else None
        if local_id is not None and local_id != self._previous_local:
            self._record(ProvenanceEvent(
                frame.index, NEW_LOCAL_STRUCTURE_OBSERVED, local_id,
                frame.local.kind if frame.local is not None else None, frame.price))
            emitted.append(NEW_LOCAL_STRUCTURE_OBSERVED)

    # ── frozen views ────────────────────────────────────────────────────────
    def _movement(
            self, frame: StructuralFrame, controlling: ControllingStructure | None,
            tolerance: Decimal,
            ) -> MovementProvenance:
        anchor = self._anchor
        if anchor is None:
            return MovementProvenance(direction=None)
        direction = anchor.direction
        events = tuple(anchor.events)
        if direction is None:
            return MovementProvenance(
                direction=None,
                origin_index=anchor.origin_index,
                origin_price=anchor.origin_price,
                origin_reference=anchor.origin_reference,
                origin_structure_id=anchor.structure_id,
                origin_structure_kind=anchor.structure_kind,
                origin_role=anchor.origin_role,
                outside=anchor.outside,
                events=events,
            )

        midpoint = (anchor.structure_low + anchor.structure_high) / Decimal(2)
        # Read from this candle's price, never from the latch: `shadow.MovementState`
        # publishes the instantaneous reading, and a latched segment would silently
        # disagree with the brain the moment price fell back through the midpoint.
        crossed_now = (frame.price >= midpoint if direction == UP
                       else frame.price <= midpoint)
        opposite_price = (anchor.structure_high if direction == UP
                          else anchor.structure_low)
        reached_now = (frame.price >= opposite_price - tolerance if direction == UP
                       else frame.price <= opposite_price + tolerance)
        if anchor.outside:
            whole_destination = anchor.destination_price
            segment = OUTSIDE_EDGE_TO_MAPPED_REFERENCE
            segment_origin = anchor.origin_price
            segment_destination = whole_destination
            destination_reference = anchor.destination_reference
        else:
            whole_destination = (anchor.structure_high if direction == UP
                                 else anchor.structure_low)
            if crossed_now:
                segment = MIDPOINT_TO_OPPOSITE_EDGE
                segment_origin = midpoint
                segment_destination = whole_destination
                destination_reference = (
                    f"{anchor.structure_id}.{'high' if direction == UP else 'low'}")
            else:
                segment = ORIGIN_TO_MIDPOINT
                segment_origin = anchor.origin_price
                segment_destination = midpoint
                destination_reference = f"{anchor.structure_id}.midpoint"

        travelled = max(ZERO, _directional(anchor.origin_price, frame.price, direction))
        whole_available = (None if whole_destination is None
                           else abs(whole_destination - anchor.origin_price))
        remaining = (None if whole_destination is None
                     else _remaining(frame.price, whole_destination, direction))
        segment_available = (None if segment_destination is None
                             else abs(segment_destination - segment_origin))
        segment_progress = (None if segment_destination is None else
                            max(ZERO, _directional(segment_origin, frame.price, direction)))
        path_midpoint = (None if whole_destination is None
                         else (anchor.origin_price + whole_destination) / Decimal(2))
        return MovementProvenance(
            direction=direction,
            origin_index=anchor.origin_index,
            origin_price=anchor.origin_price,
            origin_reference=anchor.origin_reference,
            origin_structure_id=anchor.structure_id,
            origin_structure_kind=anchor.structure_kind,
            origin_role=anchor.origin_role,
            outside=anchor.outside,
            destination_price=whole_destination,
            destination_reference=destination_reference,
            path_midpoint=path_midpoint,
            travelled_points=travelled,
            travelled_atr=_atr_ratio(travelled, frame.map.atr),
            remaining_points=remaining,
            remaining_atr=_atr_ratio(remaining, frame.map.atr),
            whole_movement_fraction=_fraction(travelled, whole_available),
            current_segment=segment,
            current_segment_fraction=_fraction(segment_progress, segment_available),
            midpoint_crossed=None if anchor.outside else crossed_now,
            opposite_edge_reached=None if anchor.outside else reached_now,
            events=events,
        )

    def _internal(
            self, frame: StructuralFrame, controlling: ControllingStructure | None,
            ) -> InternalSpace:
        if controlling is None:
            outside_reference = (_immediate(frame, UP) is not None
                                 or _immediate(frame, DOWN) is not None)
            return InternalSpace(
                state=OUTSIDE_REFERENCE_AVAILABLE if outside_reference else NO_MAPPED_SPACE)

        price = frame.price
        containment = _containment(price, controlling.low, controlling.high)
        to_lower = max(ZERO, price - controlling.low)
        to_upper = max(ZERO, controlling.high - price)
        anchor = self._anchor
        direction = anchor.direction if anchor is not None and not anchor.outside else None

        if direction == UP:
            room_to_midpoint = max(ZERO, controlling.midpoint - price)
            opposite = to_upper
            landmark = (OPPOSITE_EDGE_LANDMARK if price >= controlling.midpoint
                        else BROAD_MIDPOINT_LANDMARK)
            next_room = opposite if price >= controlling.midpoint else room_to_midpoint
        elif direction == DOWN:
            room_to_midpoint = max(ZERO, price - controlling.midpoint)
            opposite = to_lower
            landmark = (OPPOSITE_EDGE_LANDMARK if price <= controlling.midpoint
                        else BROAD_MIDPOINT_LANDMARK)
            next_room = opposite if price <= controlling.midpoint else room_to_midpoint
        else:
            room_to_midpoint = abs(controlling.midpoint - price)
            opposite = None
            landmark = None
            next_room = None

        if containment != INSIDE:
            state = (OUTSIDE_REFERENCE_AVAILABLE
                     if _immediate(frame, UP if containment == ABOVE else DOWN) is not None
                     else NO_MAPPED_SPACE)
        elif frame.approaching_current_upper or frame.approaching_current_lower:
            state = AT_EDGE_DECISION
        elif direction is None:
            state = UNKNOWN
        elif (direction == UP and price >= controlling.midpoint) or (
                direction == DOWN and price <= controlling.midpoint):
            state = INTERNAL_GEOMETRY_CONSUMED
        else:
            state = INTERNAL_GEOMETRY_AVAILABLE

        atr = frame.map.atr
        return InternalSpace(
            state=state,
            room_to_lower_edge_points=to_lower,
            room_to_lower_edge_atr=_atr_ratio(to_lower, atr),
            room_to_midpoint_points=room_to_midpoint,
            room_to_midpoint_atr=_atr_ratio(room_to_midpoint, atr),
            room_to_upper_edge_points=to_upper,
            room_to_upper_edge_atr=_atr_ratio(to_upper, atr),
            next_internal_landmark=landmark,
            room_to_next_internal_landmark_points=next_room,
            room_to_next_internal_landmark_atr=_atr_ratio(next_room, atr),
            room_to_opposite_edge_points=opposite,
            room_to_opposite_edge_atr=_atr_ratio(opposite, atr),
        )


# ═════════════════════════════════════════════════════════════════════════════
# pure readers — every one copies a fact some other layer already published
# ═════════════════════════════════════════════════════════════════════════════
def _controlling_of(frame: StructuralFrame) -> ControllingStructure | None:
    current = frame.map.current
    if current is None:
        return None
    width = current.high - current.low
    if width <= ZERO:
        return None
    return ControllingStructure(
        structure_id=current.id,
        kind=current.kind,
        low=current.low,
        high=current.high,
        midpoint=(current.low + current.high) / Decimal(2),
        width_points=width,
        width_atr=_atr_ratio(width, frame.map.atr),
        parent_id=current.parent_id,
        status=current.status,
    )


def _price_geometry(
        frame: StructuralFrame, controlling: ControllingStructure | None) -> PriceGeometry:
    price = frame.price
    if controlling is None:
        return PriceGeometry(
            price=price, price_location=frame.thesis.price_location, containment=ABSENT)
    atr = frame.map.atr
    to_lower = price - controlling.low
    to_mid = price - controlling.midpoint
    to_upper = controlling.high - price
    return PriceGeometry(
        price=price,
        price_location=frame.thesis.price_location,
        containment=_containment(price, controlling.low, controlling.high),
        distance_to_lower_points=to_lower,
        distance_to_lower_atr=_atr_ratio(abs(to_lower), atr),
        distance_to_midpoint_points=to_mid,
        distance_to_midpoint_atr=_atr_ratio(abs(to_mid), atr),
        distance_to_upper_points=to_upper,
        distance_to_upper_atr=_atr_ratio(abs(to_upper), atr),
    )


def _immediate(frame: StructuralFrame, direction: str):
    """The immediate mapped reference on one side, or None. Never fabricated."""

    path = frame.references.up if direction == UP else frame.references.down
    return path.immediate


def _external(
        frame: StructuralFrame, controlling: ControllingStructure | None) -> ExternalSpace:
    atr = frame.map.atr
    price = frame.price

    def convert(reference, direction: str) -> ExternalReference | None:
        if reference is None:
            return None
        gap = abs(reference.price - price)
        return ExternalReference(
            structure_id=reference.structure_id,
            kind=reference.kind,
            label=reference.label,
            price=reference.price,
            direction=direction,
            edge_distance_points=reference.distance,
            edge_distance_atr=reference.distance_atr,
            price_distance_points=gap,
            price_distance_atr=_atr_ratio(gap, atr),
        )

    above = convert(_immediate(frame, UP), UP)
    below = convert(_immediate(frame, DOWN), DOWN)
    room_above = None
    room_below = None
    if controlling is not None and above is not None:
        room_above = max(ZERO, above.price - controlling.high)
    if controlling is not None and below is not None:
        room_below = max(ZERO, controlling.low - below.price)
    return ExternalSpace(
        next_reference_above=above,
        next_reference_below=below,
        room_above_current_upper_to_next_reference_points=room_above,
        room_above_current_upper_to_next_reference_atr=_atr_ratio(room_above, atr),
        room_below_current_lower_to_next_reference_points=room_below,
        room_below_current_lower_to_next_reference_atr=_atr_ratio(room_below, atr),
        room_from_current_price_to_immediate_reference_above_points=(
            above.price_distance_points if above else None),
        room_from_current_price_to_immediate_reference_above_atr=(
            above.price_distance_atr if above else None),
        room_from_current_price_to_immediate_reference_below_points=(
            below.price_distance_points if below else None),
        room_from_current_price_to_immediate_reference_below_atr=(
            below.price_distance_atr if below else None),
        outside_released_structure_id=(frame.left_id if controlling is None else None),
        released_edge=(frame.map.left_edge if controlling is None else None),
    )


def _local(frame: StructuralFrame) -> LocalContext:
    atr = frame.map.atr
    micro = frame.reading.micro
    micro_low = micro.micro_low if micro is not None else None
    micro_high = micro.micro_high if micro is not None else None
    micro_width = (None if micro_low is None or micro_high is None
                   else micro_high - micro_low)
    local = frame.local
    local_width = (None if local is None else local.high - local.low)
    return LocalContext(
        micro_state=(micro.micro_state or ABSENT) if micro is not None else ABSENT,
        micro_id=micro.micro_id if micro is not None else None,
        micro_low=micro_low,
        micro_high=micro_high,
        micro_width_points=micro_width,
        micro_width_atr=_atr_ratio(micro_width, atr),
        price_location_vs_micro=_containment(frame.price, micro_low, micro_high),
        local_structure_id=local.id if local is not None else None,
        local_structure_kind=local.kind if local is not None else None,
        local_low=local.low if local is not None else None,
        local_high=local.high if local is not None else None,
        local_width_points=local_width,
        local_width_atr=_atr_ratio(local_width, atr),
        local_holder_id=local.holder_id if local is not None else None,
        price_location_vs_local=_containment(
            frame.price,
            local.low if local is not None else None,
            local.high if local is not None else None),
    )


def _accepted_direction(frame: StructuralFrame) -> str | None:
    table = {"ACCEPTED_ABOVE": UP, "ACCEPTED_BELOW": DOWN}
    return table.get(frame.map.status) or table.get(frame.reading.interaction)


def _reentry(frame: StructuralFrame) -> bool:
    return (frame.map.status == "BREAKOUT_FAILED"
            or frame.reading.interaction == "RE_ENTRY"
            or frame.thesis.current_state == "REENTERING")


def _origin_area(
        frame: StructuralFrame, controlling: ControllingStructure,
        tolerance: Decimal) -> str | None:
    """Which edge area price is standing in, using the map's own approach facts."""

    at_lower = (frame.approaching_current_lower
                or frame.thesis.price_location in {"AT_LOWER_EDGE", "BELOW"}
                or frame.price <= controlling.low + tolerance)
    if at_lower:
        return BROAD_LOWER_EDGE
    at_upper = (frame.approaching_current_upper
                or frame.thesis.price_location in {"AT_UPPER_EDGE", "ABOVE"}
                or frame.price >= controlling.high - tolerance)
    if at_upper:
        return BROAD_UPPER_EDGE
    return None


def observe_geometry(
        frames, *, tolerances) -> list[StructureGeometry]:
    """Replay a whole StructuralFrame sequence. `tolerances` is one value per frame."""

    observer = GeometryObserver()
    return [observer.observe(frame, tolerance=tolerance)
            for frame, tolerance in zip(frames, tolerances, strict=True)]


__all__ = [
    "ABOVE",
    "ABSENT",
    "ACCEPTED_RELEASE_DOWN",
    "ACCEPTED_RELEASE_UP",
    "AT_EDGE_DECISION",
    "BELOW",
    "BROAD_LOWER_EDGE",
    "BROAD_MIDPOINT_LANDMARK",
    "BROAD_UPPER_EDGE",
    "CONTROLLING_STRUCTURE_REPLACED",
    "DOWN",
    "INSIDE",
    "INTERNAL_GEOMETRY_AVAILABLE",
    "INTERNAL_GEOMETRY_CONSUMED",
    "INTERNAL_SPACE_STATES",
    "LOWER_EDGE_ORIGIN",
    "MIDPOINT_CROSSED",
    "MIDPOINT_TO_OPPOSITE_EDGE",
    "MOVEMENT_ORIGIN_ROLES",
    "NEW_LOCAL_STRUCTURE_OBSERVED",
    "NO_MAPPED_SPACE",
    "NO_STRUCTURAL_SEGMENT",
    "OPPOSITE_EDGE_LANDMARK",
    "OPPOSITE_EDGE_REACHED",
    "ORIGIN_TO_MIDPOINT",
    "OUTSIDE_EDGE_TO_MAPPED_REFERENCE",
    "OUTSIDE_REFERENCE_AVAILABLE",
    "PROVENANCE_EVENTS",
    "REENTRY",
    "RELEASED_EDGE",
    "STRUCTURE_BECAME_CONTROLLING",
    "UNKNOWN",
    "UP",
    "UPPER_EDGE_ORIGIN",
    "ControllingStructure",
    "ExternalReference",
    "ExternalSpace",
    "GeometryObserver",
    "InternalSpace",
    "LocalContext",
    "MovementProvenance",
    "PriceGeometry",
    "ProvenanceEvent",
    "StructureGeometry",
    "observe_geometry",
]
