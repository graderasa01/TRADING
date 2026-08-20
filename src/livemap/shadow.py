"""Dynamic, research-only structural shadow participation.

This module consumes one immutable :class:`StructuralFrame` per closed candle.  It does
not detect structure, alter the map, submit orders, or feed a decision back into any
production object.  The state carried between candles is limited to factual movement
origins, explicit hypothesis records, and an optional shadow position.

The separation is deliberate:

``MarketTruth -> MovementState -> HypothesisBrain -> ParticipationState -> ShadowPosition``

Every public result is frozen.  A later candle replaces the current internal record and
can never mutate a snapshot that was already emitted.

Two brain versions exist, and the difference is exactly one rule:

``BRAIN_V1``
    An open shadow position is closed only when its own hypothesis reaches a terminal
    lifecycle state.  This is the frozen behaviour audited as fingerprint
    ``bf497495e394bb87`` and is retained so that historical evidence stays reproducible.

``BRAIN_V2``
    Identical, plus: **market hypothesis falsification and open-position risk are
    separate events.**  An open ROTATION position is returned to FLAT on the first
    closed candle whose close sits at or beyond the position's own frozen Broad
    invalidation level on the adverse side, without waiting for the broader hypothesis
    to receive an accepted structural failure.  The hypothesis lifecycle is untouched by
    that exit; only participation for that one hypothesis instance is consumed.

``BRAIN_V2`` is the default because it is the current authoritative cognition.  A brain
version is a frozen semantic identity, never a tunable parameter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.models import ZERO
from src.livemap.frame import StructuralFrame

TEACH = "teach"
VALIDATE = "validate"
RESEARCH_BUCKETS = frozenset({TEACH, VALIDATE})

UP = "up"
DOWN = "down"
SIDES = frozenset({UP, DOWN})

LOWER_ROTATION = "ROTATION_FROM_LOWER_AREA"
UPPER_ROTATION = "ROTATION_FROM_UPPER_AREA"
CONTINUATION_UP = "OUTSIDE_CONTINUATION_UP"
CONTINUATION_DOWN = "OUTSIDE_CONTINUATION_DOWN"
FAILED_UP_RETURN = "FAILED_UP_RELEASE_RETURN_INSIDE"
FAILED_DOWN_RETURN = "FAILED_DOWN_RELEASE_RETURN_INSIDE"
HYPOTHESIS_FAMILIES = frozenset({
    LOWER_ROTATION,
    UPPER_ROTATION,
    CONTINUATION_UP,
    CONTINUATION_DOWN,
    FAILED_UP_RETURN,
    FAILED_DOWN_RETURN,
})
ROTATION_FAMILIES = frozenset({LOWER_ROTATION, UPPER_ROTATION})
CONTINUATION_FAMILIES = frozenset({CONTINUATION_UP, CONTINUATION_DOWN})

#: Frozen semantic identities, never tunable parameters.
BRAIN_V1 = "BRAIN_V1_HYPOTHESIS_FALSIFICATION_ONLY_EXIT"
BRAIN_V2 = "BRAIN_V2_ROTATION_POSITION_RISK_EXIT"
BRAIN_VERSIONS = frozenset({BRAIN_V1, BRAIN_V2})

#: Open-position risk exit.  Deliberately distinguishable from the hypothesis-level
#: ``ACCEPTED_STRUCTURAL_FAILURE``: the market thesis may still be alive when the open
#: participation no longer deserves exposure.
POSITION_INVALIDATION_LEVEL_CROSSED = "POSITION_INVALIDATION_LEVEL_CROSSED"
POSITION_RISK_EXIT_REASONS = frozenset({POSITION_INVALIDATION_LEVEL_CROSSED})
PARTICIPATION_CONSUMED_BY_POSITION_RISK = "PARTICIPATION_CONSUMED_BY_POSITION_RISK_EXIT"

OBSERVING = "OBSERVING"
ACTIVE = "ACTIVE"
STRESSED = "STRESSED"
COMPLETED = "COMPLETED"
FALSIFIED = "FALSIFIED"
EXPIRED = "EXPIRED"
HYPOTHESIS_STATUSES = frozenset({OBSERVING, ACTIVE, STRESSED, COMPLETED, FALSIFIED, EXPIRED})
TERMINAL_HYPOTHESIS_STATUSES = frozenset({COMPLETED, FALSIFIED, EXPIRED})

NOT_ESTABLISHED = "NOT_ESTABLISHED"
EARLY = "EARLY"
IN_PROGRESS = "IN_PROGRESS"
APPROACHING_REFERENCE = "APPROACHING_REFERENCE"
AT_REFERENCE = "AT_REFERENCE"
STRUCTURAL_TRANSITION = "STRUCTURAL_TRANSITION"
MOVEMENT_PHASES = frozenset({
    NOT_ESTABLISHED,
    EARLY,
    IN_PROGRESS,
    APPROACHING_REFERENCE,
    AT_REFERENCE,
    STRUCTURAL_TRANSITION,
})

NO_ACTIVE_HYPOTHESIS = "NO_ACTIVE_HYPOTHESIS"
HYPOTHESIS_OBSERVING = "HYPOTHESIS_OBSERVING"
HYPOTHESIS_VALID_BUT_NO_PARTICIPATION = "HYPOTHESIS_VALID_BUT_NO_PARTICIPATION"
PARTICIPATION_AVAILABLE = "PARTICIPATION_AVAILABLE"
HYPOTHESIS_CONFLICT = "HYPOTHESIS_CONFLICT"
POSITION_ACTIVE = "POSITION_ACTIVE"
PARTICIPATION_STATUSES = frozenset({
    NO_ACTIVE_HYPOTHESIS,
    HYPOTHESIS_OBSERVING,
    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
    PARTICIPATION_AVAILABLE,
    HYPOTHESIS_CONFLICT,
    POSITION_ACTIVE,
})

FLAT = "FLAT"
SHADOW_LONG = "SHADOW_LONG"
SHADOW_SHORT = "SHADOW_SHORT"
POSITION_STATES = frozenset({FLAT, SHADOW_LONG, SHADOW_SHORT})

WAIT = "WAIT"
ENTER_LONG_SHADOW = "ENTER_LONG_SHADOW"
ENTER_SHORT_SHADOW = "ENTER_SHORT_SHADOW"
HOLD = "HOLD"
EXIT = "EXIT"
NO_ACTION = "NO_ACTION"
ACTIONS = frozenset({WAIT, ENTER_LONG_SHADOW, ENTER_SHORT_SHADOW, HOLD, EXIT, NO_ACTION})

ORIGIN_TO_MIDPOINT = "ORIGIN_TO_MIDPOINT"
MIDPOINT_TO_OPPOSITE_EDGE = "MIDPOINT_TO_OPPOSITE_EDGE"
OUTSIDE_EDGE_TO_MAPPED_REFERENCE = "OUTSIDE_EDGE_TO_MAPPED_REFERENCE"
NO_STRUCTURAL_SEGMENT = "NO_STRUCTURAL_SEGMENT"


@dataclass(frozen=True, slots=True)
class ReferenceFact:
    label: str
    structure_id: str
    role: str
    direction: str
    price: Decimal


@dataclass(frozen=True, slots=True)
class ReleaseFact:
    release_id: str
    scale: str
    direction: str
    broken_id: str
    broken_edge: Decimal
    broken_low: Decimal | None
    broken_high: Decimal | None
    parent_id: str | None
    location: str


@dataclass(frozen=True, slots=True)
class MicroFact:
    state: str = "ABSENT"
    micro_id: str | None = None
    low: Decimal | None = None
    high: Decimal | None = None
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketTruth:
    """Facts copied from one causal frame.  This layer never chooses participation."""

    bucket: str
    source_episode_id: str
    source_ordinal: int
    index: int
    at: datetime
    price: Decimal
    atr: Decimal
    tolerance: Decimal
    broad_id: str | None = None
    broad_kind: str | None = None
    broad_low: Decimal | None = None
    broad_high: Decimal | None = None
    parent_id: str | None = None
    price_location: str = "NO_STRUCTURE"
    interaction: str = ""
    map_status: str = "WAIT"
    market_state: str = "TRANSITION"
    approaching_upper: bool = False
    approaching_lower: bool = False
    left_id: str | None = None
    left_edge: Decimal | None = None
    left_low: Decimal | None = None
    left_high: Decimal | None = None
    left_kind: str | None = None
    accepted_direction: str | None = None
    reentry: bool = False
    references_above: tuple[ReferenceFact, ...] = ()
    references_below: tuple[ReferenceFact, ...] = ()
    releases: tuple[ReleaseFact, ...] = ()
    active_release: ReleaseFact | None = None
    micro: MicroFact = MicroFact()
    source_end: bool = False

    def __post_init__(self) -> None:
        if self.bucket not in RESEARCH_BUCKETS:
            raise ValueError("dynamic shadow research accepts TEACH/VALIDATE only")
        if self.accepted_direction is not None and self.accepted_direction not in SIDES:
            raise ValueError("accepted_direction must be up, down, or None")
        if (self.broad_low is not None and self.broad_high is not None
                and self.broad_high <= self.broad_low):
            raise ValueError("Broad structure must have positive width")

    @property
    def broad_midpoint(self) -> Decimal | None:
        if self.broad_low is None or self.broad_high is None:
            return None
        return (self.broad_low + self.broad_high) / Decimal(2)

    @property
    def accepted_break(self) -> bool:
        return self.accepted_direction is not None and self.left_id is not None


@dataclass(frozen=True, slots=True)
class StructuralInvalidation:
    structure_id: str
    reason: str
    level: Decimal
    adverse_direction: str

    def __post_init__(self) -> None:
        if self.adverse_direction not in SIDES:
            raise ValueError("invalidation direction must be up or down")


@dataclass(frozen=True, slots=True)
class MovementState:
    source_episode_id: str
    index: int
    controlling_broad_id: str | None
    broad_low: Decimal | None
    broad_high: Decimal | None
    broad_midpoint: Decimal | None
    current_price: Decimal
    current_price_location: str
    origin_index: int | None
    origin_price: Decimal | None
    direction: str | None
    origin_reference: str | None
    next_reference: ReferenceFact | None
    travelled_points: Decimal | None
    travelled_atr: float | None
    remaining_points: Decimal | None
    remaining_atr: float | None
    structural_fraction_traversed: float | None
    structural_segment: str
    midpoint_crossed: bool | None
    opposite_edge_approached: bool | None
    opposite_edge_reached: bool | None
    micro_state: str
    micro_location: str
    release_facts: tuple[str, ...]
    reentry_observed: bool
    phase: str

    def __post_init__(self) -> None:
        if self.direction is not None and self.direction not in SIDES:
            raise ValueError("movement direction must be up, down, or None")
        if self.phase not in MOVEMENT_PHASES:
            raise ValueError(f"unknown movement phase {self.phase!r}")


@dataclass(frozen=True, slots=True)
class HypothesisState:
    hypothesis_id: str
    family: str
    side: str | None
    birth_index: int
    factual_premise: tuple[str, ...]
    state: str
    confirmation_facts: tuple[str, ...]
    movement_origin: ReferenceFact
    movement_destination: ReferenceFact | None
    travelled_points: Decimal | None
    remaining_points: Decimal | None
    structural_fraction_traversed: float | None
    invalidation: StructuralInvalidation | None
    structure_id: str
    last_update_index: int
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        if self.family not in HYPOTHESIS_FAMILIES:
            raise ValueError(f"unknown hypothesis family {self.family!r}")
        if self.side is not None and self.side not in SIDES:
            raise ValueError("hypothesis side must be up, down, or None")
        if self.state not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unknown hypothesis state {self.state!r}")


@dataclass(frozen=True, slots=True)
class ParticipationState:
    status: str
    hypothesis_id: str | None
    reasons: tuple[str, ...]
    movement_consumed_points: Decimal | None = None
    movement_consumed_atr: float | None = None
    structural_room_points: Decimal | None = None
    structural_room_atr: float | None = None
    invalidation_distance_points: Decimal | None = None
    invalidation_distance_atr: float | None = None
    midpoint_crossed_before_participation: bool | None = None
    next_reference_already_reached: bool = False

    def __post_init__(self) -> None:
        if self.status not in PARTICIPATION_STATUSES:
            raise ValueError(f"unknown participation status {self.status!r}")


@dataclass(frozen=True, slots=True)
class ShadowPositionState:
    state: str
    hypothesis_id: str | None = None
    family: str | None = None
    entry_index: int | None = None
    entry_price: Decimal | None = None
    invalidation_structure_id: str | None = None
    invalidation_reason: str | None = None
    invalidation_level: Decimal | None = None
    current_distance_to_invalidation: Decimal | None = None
    structural_path_available_at_entry: Decimal | None = None
    structural_path_traversed_while_valid: Decimal | None = None
    path_participation_fraction: float | None = None

    def __post_init__(self) -> None:
        if self.state not in POSITION_STATES:
            raise ValueError(f"unknown shadow position state {self.state!r}")
        if self.state == FLAT and self.hypothesis_id is not None:
            raise ValueError("a flat shadow position cannot retain a hypothesis")
        if self.state != FLAT and self.invalidation_level is None:
            raise ValueError("every shadow position requires factual invalidation")


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    source_episode_id: str
    index: int
    at: datetime
    market: MarketTruth
    movement: MovementState
    hypotheses: tuple[HypothesisState, ...]
    participation: ParticipationState
    position_before: str
    position: ShadowPositionState
    action: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown shadow action {self.action!r}")


@dataclass(frozen=True, slots=True)
class PositionEpisode:
    source_episode_id: str
    hypothesis_id: str
    family: str
    side: str
    entry_index: int
    entry_price: Decimal
    exit_index: int
    exit_price: Decimal
    exit_reason: str
    invalidation_distance_at_entry: Decimal
    structural_path_available_at_entry: Decimal
    structural_path_traversed_while_valid: Decimal
    path_participation_fraction: float | None
    landmarks_reached: tuple[str, ...]
    hypothesis_falsification_index: int | None
    exited_on_first_falsification: bool | None
    distance_entry_to_falsification: Decimal | None


@dataclass(slots=True)
class _MovementAnchor:
    structure_id: str
    structure_low: Decimal
    structure_high: Decimal
    origin_index: int
    origin_price: Decimal
    origin_reference: str
    direction: str | None
    outside: bool = False
    mapped_reference: ReferenceFact | None = None


@dataclass(slots=True)
class _HypothesisRecord:
    hypothesis_id: str
    family: str
    side: str | None
    birth_index: int
    factual_premise: tuple[str, ...]
    state: str
    confirmations: list[str]
    origin: ReferenceFact
    destination: ReferenceFact | None
    invalidation: StructuralInvalidation | None
    structure_id: str
    last_update_index: int
    terminal_reason: str | None = None
    statuses_seen: set[str] = field(default_factory=set)
    terminal_index: int | None = None

    def __post_init__(self) -> None:
        self.statuses_seen.add(self.state)

    def set_state(self, state: str, index: int, reason: str | None = None) -> None:
        self.state = state
        self.last_update_index = index
        self.statuses_seen.add(state)
        if state in TERMINAL_HYPOTHESIS_STATUSES:
            self.terminal_index = index
            self.terminal_reason = reason

    def confirm(self, fact: str) -> None:
        if fact not in self.confirmations:
            self.confirmations.append(fact)


@dataclass(slots=True)
class _OpenPosition:
    hypothesis_id: str
    family: str
    side: str
    entry_index: int
    entry_price: Decimal
    invalidation: StructuralInvalidation
    destination: ReferenceFact
    structural_path_available: Decimal
    furthest_progress: Decimal = ZERO
    landmarks: set[str] = field(default_factory=set)


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator <= ZERO:
        return None
    return float(numerator / denominator)


def _atr_ratio(value: Decimal | None, atr: Decimal) -> float | None:
    if value is None or atr <= ZERO:
        return None
    return float(value / atr)


def _directional_distance(origin: Decimal, price: Decimal, direction: str) -> Decimal:
    return price - origin if direction == UP else origin - price


def _remaining(price: Decimal, destination: Decimal, direction: str) -> Decimal:
    return max(ZERO, destination - price if direction == UP else price - destination)


def _reached(price: Decimal, destination: Decimal, direction: str, tolerance: Decimal) -> bool:
    return (price >= destination - tolerance if direction == UP
            else price <= destination + tolerance)


def crossed_invalidation(price: Decimal, level: Decimal, side: str) -> bool:
    """Does a closed candle sit at or beyond ``level`` on the adverse side of ``side``?

    No tolerance skirt is applied and none is invented here.  The repo's ``tolerance``
    conventions are generous in the *favourable* direction — ``_reached`` accepts a
    destination that is one skirt short, and ``_at_lower``/``_at_upper`` accept an area
    one skirt wide — because being generous there only ever admits a fact earlier.  On
    an adverse risk boundary the same skirt would keep an open position exposed for
    longer, which is the opposite of what this predicate is for.  This is also the exact
    predicate the V2 quality audit already used to measure
    ``first_invalidation_close_cross_index``, so the corrected exit lands on precisely
    the candle that audit named.
    """

    return price <= level if side == UP else price >= level


def _micro_location(truth: MarketTruth) -> str:
    micro = truth.micro
    if micro.low is None or micro.high is None:
        return "NO_MICRO"
    if truth.price < micro.low:
        return "BELOW_MICRO"
    if truth.price > micro.high:
        return "ABOVE_MICRO"
    return "INSIDE_MICRO"


def _reference_fact(reference) -> ReferenceFact:
    return ReferenceFact(
        label=reference.label,
        structure_id=reference.structure_id,
        role=reference.role,
        direction=reference.direction,
        price=reference.price,
    )


def _release_fact(release) -> ReleaseFact:
    return ReleaseFact(
        release_id=release.id,
        scale=release.scale,
        direction=release.direction,
        broken_id=release.broken_id,
        broken_edge=release.broken_edge,
        broken_low=release.broken_low,
        broken_high=release.broken_high,
        parent_id=release.parent_id,
        location=release.location,
    )


def market_truth_from_frame(
        frame: StructuralFrame, *, bucket: str, source_episode_id: str,
        source_ordinal: int, tolerance: Decimal, source_end: bool = False,
        ) -> MarketTruth:
    """Freeze the production facts needed by the shadow research layer."""

    current = frame.map.current
    micro = frame.reading.micro
    releases = tuple(_release_fact(item) for item in frame.release.releases)
    active_release = (_release_fact(frame.active_release)
                      if frame.active_release is not None else None)
    accepted = ({"ACCEPTED_ABOVE": UP, "ACCEPTED_BELOW": DOWN}.get(frame.map.status)
                or {"ACCEPTED_ABOVE": UP, "ACCEPTED_BELOW": DOWN}.get(
                    frame.reading.interaction))
    reentry = (
        frame.map.status == "BREAKOUT_FAILED"
        or frame.reading.interaction == "RE_ENTRY"
        or frame.thesis.current_state == "REENTERING"
    )
    return MarketTruth(
        bucket=bucket,
        source_episode_id=source_episode_id,
        source_ordinal=source_ordinal,
        index=frame.index,
        at=frame.at,
        price=frame.price,
        atr=frame.map.atr,
        tolerance=tolerance,
        broad_id=current.id if current is not None else None,
        broad_kind=current.kind if current is not None else None,
        broad_low=current.low if current is not None else None,
        broad_high=current.high if current is not None else None,
        parent_id=current.parent_id if current is not None else None,
        price_location=frame.thesis.price_location,
        interaction=frame.reading.interaction,
        map_status=frame.map.status,
        market_state=frame.map.market_state,
        approaching_upper=frame.approaching_current_upper,
        approaching_lower=frame.approaching_current_lower,
        left_id=frame.left_id,
        left_edge=frame.map.left_edge,
        left_low=frame.map.left_low,
        left_high=frame.map.left_high,
        left_kind=frame.reading.left_kind,
        accepted_direction=accepted,
        reentry=reentry,
        references_above=tuple(_reference_fact(item) for item in frame.references.up.references),
        references_below=tuple(_reference_fact(item) for item in frame.references.down.references),
        releases=releases,
        active_release=active_release,
        micro=MicroFact(
            state=(micro.micro_state or "ABSENT") if micro is not None else "ABSENT",
            micro_id=micro.micro_id if micro is not None else None,
            low=micro.micro_low if micro is not None else None,
            high=micro.micro_high if micro is not None else None,
            events=tuple(micro.events) if micro is not None else (),
        ),
        source_end=source_end,
    )


class DynamicShadowTrader:
    """One source-episode-scoped dynamic hypothesis and shadow-position machine."""

    def __init__(
            self, bucket: str, source_episode_id: str, *, brain: str = BRAIN_V2,
            ) -> None:
        if bucket not in RESEARCH_BUCKETS:
            raise ValueError("dynamic shadow research accepts TEACH/VALIDATE only")
        if brain not in BRAIN_VERSIONS:
            raise ValueError(f"unknown brain version {brain!r}")
        self.bucket = bucket
        self.source_episode_id = source_episode_id
        self.brain = brain
        self.decisions: list[ShadowDecision] = []
        self.position_episodes: list[PositionEpisode] = []
        self._hypotheses: dict[str, _HypothesisRecord] = {}
        self._hypothesis_history: dict[str, list[HypothesisState]] = {}
        self._anchor: _MovementAnchor | None = None
        self._position: _OpenPosition | None = None
        self._risk_consumed: set[str] = set()
        self._previous: MarketTruth | None = None
        self._last_index: int | None = None
        self._last_source_ordinal: int | None = None

    @property
    def risk_consumed_hypotheses(self) -> frozenset[str]:
        """Hypothesis instances whose participation a position-risk exit consumed."""

        return frozenset(self._risk_consumed)

    @property
    def hypothesis_history(self) -> dict[str, tuple[HypothesisState, ...]]:
        return {key: tuple(items) for key, items in self._hypothesis_history.items()}

    @property
    def hypothesis_records(self) -> tuple[_HypothesisRecord, ...]:
        return tuple(self._hypotheses.values())

    def observe_frame(
            self, frame: StructuralFrame, *, source_ordinal: int,
            tolerance: Decimal, source_end: bool = False,
            ) -> ShadowDecision:
        truth = market_truth_from_frame(
            frame,
            bucket=self.bucket,
            source_episode_id=self.source_episode_id,
            source_ordinal=source_ordinal,
            tolerance=tolerance,
            source_end=source_end,
        )
        return self.observe_truth(truth)

    def observe_truth(self, truth: MarketTruth) -> ShadowDecision:
        self._assert_truth(truth)
        self._update_movement_anchor(truth)
        movement = self._movement_state(truth)
        newly_terminal = self._update_hypotheses(truth, movement)
        self._create_hypotheses(truth, movement, newly_terminal)
        self._resolve_failed_contexts(truth)
        if truth.source_end:
            for record in self._live_records():
                record.set_state(EXPIRED, truth.index, "SOURCE_EPISODE_BOUNDARY")

        snapshots = self._snapshots(truth)
        self._record_hypothesis_history(snapshots)
        before = FLAT if self._position is None else (
            SHADOW_LONG if self._position.side == UP else SHADOW_SHORT)
        participation = self._participation_state(truth, movement, snapshots)
        action, reasons = self._position_action(truth, movement, participation)
        position = self._position_snapshot(truth)
        decision = ShadowDecision(
            source_episode_id=self.source_episode_id,
            index=truth.index,
            at=truth.at,
            market=truth,
            movement=movement,
            hypotheses=snapshots,
            participation=participation,
            position_before=before,
            position=position,
            action=action,
            reasons=reasons,
        )
        self.decisions.append(decision)
        self._last_index = truth.index
        self._last_source_ordinal = truth.source_ordinal
        self._previous = truth
        return decision

    def _assert_truth(self, truth: MarketTruth) -> None:
        if truth.bucket != self.bucket or truth.source_episode_id != self.source_episode_id:
            raise AssertionError("truth crossed a bucket or source episode barrier")
        if self._last_index is not None and truth.index <= self._last_index:
            raise AssertionError("closed-candle indices must be strictly increasing")
        if (self._last_source_ordinal is not None
                and truth.source_ordinal < self._last_source_ordinal):
            raise AssertionError("source ordinals must be non-decreasing")
        if self.decisions and self.decisions[-1].market.source_end:
            raise AssertionError("cannot append after source episode termination")

    def _at_lower(self, truth: MarketTruth) -> bool:
        if truth.broad_low is None:
            return False
        return (
            truth.approaching_lower
            or truth.price_location in {"AT_LOWER_EDGE", "BELOW"}
            or truth.price <= truth.broad_low + truth.tolerance
        )

    def _at_upper(self, truth: MarketTruth) -> bool:
        if truth.broad_high is None:
            return False
        return (
            truth.approaching_upper
            or truth.price_location in {"AT_UPPER_EDGE", "ABOVE"}
            or truth.price >= truth.broad_high - truth.tolerance
        )

    def _matching_release(self, truth: MarketTruth, direction: str) -> ReleaseFact | None:
        return next((
            item for item in truth.releases
            if item.direction == direction and item.broken_id == truth.left_id
        ), None)

    def _immediate_reference(self, truth: MarketTruth, direction: str) -> ReferenceFact | None:
        references = truth.references_above if direction == UP else truth.references_below
        return next((item for item in references if item.role == "IMMEDIATE"), None)

    def _update_movement_anchor(self, truth: MarketTruth) -> None:
        if truth.accepted_break and truth.left_id and truth.left_low is not None and truth.left_high is not None:
            direction = truth.accepted_direction
            assert direction is not None
            edge = truth.left_high if direction == UP else truth.left_low
            self._anchor = _MovementAnchor(
                structure_id=truth.left_id,
                structure_low=truth.left_low,
                structure_high=truth.left_high,
                origin_index=truth.index,
                origin_price=edge,
                origin_reference=f"{truth.left_id}.{'high' if direction == UP else 'low'}",
                direction=direction,
                outside=True,
                mapped_reference=self._immediate_reference(truth, direction),
            )
            return

        if truth.broad_id is None or truth.broad_low is None or truth.broad_high is None:
            if self._anchor is not None and not self._anchor.outside:
                self._anchor = None
            return

        same = self._anchor is not None and self._anchor.structure_id == truth.broad_id
        if not same:
            self._anchor = None
            if self._at_lower(truth):
                self._anchor = _MovementAnchor(
                    truth.broad_id, truth.broad_low, truth.broad_high,
                    truth.index, truth.broad_low, f"{truth.broad_id}.low", None)
            elif self._at_upper(truth):
                self._anchor = _MovementAnchor(
                    truth.broad_id, truth.broad_low, truth.broad_high,
                    truth.index, truth.broad_high, f"{truth.broad_id}.high", None)
            return

        assert self._anchor is not None
        if self._anchor.outside and truth.reentry:
            origin_at_upper = self._anchor.direction == UP
            self._anchor = _MovementAnchor(
                truth.broad_id, truth.broad_low, truth.broad_high,
                truth.index,
                truth.broad_high if origin_at_upper else truth.broad_low,
                f"{truth.broad_id}.{'high' if origin_at_upper else 'low'}",
                None,
            )
            return
        if self._anchor.direction is None and self._previous is not None:
            if (self._anchor.origin_reference.endswith(".low")
                    and truth.price > self._previous.price
                    and truth.price_location in {"INSIDE", "AT_LOWER_EDGE"}):
                self._anchor.direction = UP
            elif (self._anchor.origin_reference.endswith(".high")
                  and truth.price < self._previous.price
                  and truth.price_location in {"INSIDE", "AT_UPPER_EDGE"}):
                self._anchor.direction = DOWN

    def _movement_state(self, truth: MarketTruth) -> MovementState:
        anchor = self._anchor
        if anchor is None:
            return MovementState(
                self.source_episode_id, truth.index, truth.broad_id,
                truth.broad_low, truth.broad_high, truth.broad_midpoint,
                truth.price, truth.price_location, None, None, None, None, None,
                None, None, None, None, None, NO_STRUCTURAL_SEGMENT,
                None, None, None, truth.micro.state, _micro_location(truth),
                tuple(item.release_id for item in truth.releases), truth.reentry,
                NOT_ESTABLISHED,
            )

        midpoint = (anchor.structure_low + anchor.structure_high) / Decimal(2)
        direction = anchor.direction
        midpoint_crossed = (None if direction is None or anchor.outside else (
            truth.price >= midpoint if direction == UP else truth.price <= midpoint))
        opposite_price = anchor.structure_high if direction == UP else anchor.structure_low
        opposite_approached = (None if direction is None or anchor.outside else (
            truth.approaching_upper if direction == UP else truth.approaching_lower))
        opposite_reached = (None if direction is None or anchor.outside else _reached(
            truth.price, opposite_price, direction, truth.tolerance))

        if direction is None:
            next_reference = None
            segment = NO_STRUCTURAL_SEGMENT
            phase = NOT_ESTABLISHED
            destination = None
        elif anchor.outside:
            next_reference = anchor.mapped_reference
            destination = next_reference.price if next_reference is not None else None
            segment = OUTSIDE_EDGE_TO_MAPPED_REFERENCE
            phase = STRUCTURAL_TRANSITION if truth.accepted_break else IN_PROGRESS
        elif midpoint_crossed is False:
            next_reference = ReferenceFact(
                f"{anchor.structure_id}.midpoint", anchor.structure_id,
                "BROAD_MIDPOINT", direction, midpoint)
            destination = midpoint
            segment = ORIGIN_TO_MIDPOINT
            phase = EARLY
        else:
            label = f"{anchor.structure_id}.{'high' if direction == UP else 'low'}"
            next_reference = ReferenceFact(
                label, anchor.structure_id, "OPPOSITE_BROAD_EDGE", direction, opposite_price)
            destination = opposite_price
            segment = MIDPOINT_TO_OPPOSITE_EDGE
            phase = IN_PROGRESS

        travelled = (None if direction is None else max(
            ZERO, _directional_distance(anchor.origin_price, truth.price, direction)))
        remaining = (None if direction is None or destination is None else
                     _remaining(truth.price, destination, direction))
        total = (None if direction is None or destination is None else
                 abs(destination - anchor.origin_price))
        if direction is not None and destination is not None:
            if _reached(truth.price, destination, direction, truth.tolerance):
                phase = AT_REFERENCE
            elif opposite_approached and segment == MIDPOINT_TO_OPPOSITE_EDGE:
                phase = APPROACHING_REFERENCE
        return MovementState(
            source_episode_id=self.source_episode_id,
            index=truth.index,
            controlling_broad_id=anchor.structure_id,
            broad_low=anchor.structure_low,
            broad_high=anchor.structure_high,
            broad_midpoint=midpoint,
            current_price=truth.price,
            current_price_location=truth.price_location,
            origin_index=anchor.origin_index,
            origin_price=anchor.origin_price,
            direction=direction,
            origin_reference=anchor.origin_reference,
            next_reference=next_reference,
            travelled_points=travelled,
            travelled_atr=_atr_ratio(travelled, truth.atr),
            remaining_points=remaining,
            remaining_atr=_atr_ratio(remaining, truth.atr),
            structural_fraction_traversed=_ratio(travelled, total),
            structural_segment=segment,
            midpoint_crossed=midpoint_crossed,
            opposite_edge_approached=opposite_approached,
            opposite_edge_reached=opposite_reached,
            micro_state=truth.micro.state,
            micro_location=_micro_location(truth),
            release_facts=tuple(item.release_id for item in truth.releases),
            reentry_observed=truth.reentry,
            phase=phase,
        )

    def _live_records(self) -> list[_HypothesisRecord]:
        return [item for item in self._hypotheses.values()
                if item.state not in TERMINAL_HYPOTHESIS_STATUSES]

    def _has_live(self, family: str, structure_id: str) -> bool:
        return any(
            item.family == family and item.structure_id == structure_id
            and item.state not in TERMINAL_HYPOTHESIS_STATUSES
            for item in self._hypotheses.values()
        )

    def _record_id(self, family: str, structure_id: str, index: int) -> str:
        return f"{self.source_episode_id}:{family}:{structure_id}:c{index}"

    def _create_record(
            self, *, family: str, side: str | None, truth: MarketTruth,
            premise: tuple[str, ...], origin: ReferenceFact,
            destination: ReferenceFact | None,
            invalidation: StructuralInvalidation | None,
            structure_id: str, state: str,
            ) -> _HypothesisRecord:
        record = _HypothesisRecord(
            hypothesis_id=self._record_id(family, structure_id, truth.index),
            family=family,
            side=side,
            birth_index=truth.index,
            factual_premise=premise,
            state=state,
            confirmations=[],
            origin=origin,
            destination=destination,
            invalidation=invalidation,
            structure_id=structure_id,
            last_update_index=truth.index,
        )
        self._hypotheses[record.hypothesis_id] = record
        return record

    def _update_hypotheses(
            self, truth: MarketTruth, movement: MovementState,
            ) -> list[_HypothesisRecord]:
        terminal: list[_HypothesisRecord] = []
        for record in self._live_records():
            was_terminal = record.state in TERMINAL_HYPOTHESIS_STATUSES
            if record.family in {LOWER_ROTATION, UPPER_ROTATION}:
                self._update_rotation(record, truth, movement)
            elif record.family in {CONTINUATION_UP, CONTINUATION_DOWN}:
                self._update_continuation(record, truth, movement)
            elif record.family in {FAILED_UP_RETURN, FAILED_DOWN_RETURN}:
                record.last_update_index = truth.index
            if not was_terminal and record.state in TERMINAL_HYPOTHESIS_STATUSES:
                terminal.append(record)
        return terminal

    def _update_rotation(
            self, record: _HypothesisRecord, truth: MarketTruth,
            movement: MovementState,
            ) -> None:
        side = record.side
        assert side is not None
        adverse = DOWN if side == UP else UP
        objective_reached = record.destination is not None and _reached(
            truth.price, record.destination.price, side, truth.tolerance)
        accepted_same = truth.accepted_break and truth.left_id == record.structure_id
        if accepted_same and truth.accepted_direction == side:
            record.confirm("OPPOSITE_BROAD_EDGE_REACHED")
            record.set_state(COMPLETED, truth.index, "STRUCTURAL_OBJECTIVE_REACHED")
            return
        if accepted_same and truth.accepted_direction == adverse:
            record.set_state(FALSIFIED, truth.index, "ACCEPTED_STRUCTURAL_FAILURE")
            return
        if objective_reached:
            record.confirm("OPPOSITE_BROAD_EDGE_REACHED")
            record.set_state(COMPLETED, truth.index, "STRUCTURAL_OBJECTIVE_REACHED")
            return
        if truth.broad_id != record.structure_id:
            record.set_state(FALSIFIED, truth.index, "CONTROLLING_STRUCTURE_CHANGED")
            return

        moved_away = (
            movement.direction == side
            and self._previous is not None
            and (_directional_distance(self._previous.price, truth.price, side) > ZERO)
            and truth.price_location in {"INSIDE", "AT_LOWER_EDGE", "AT_UPPER_EDGE"}
        )
        at_origin = self._at_lower(truth) if side == UP else self._at_upper(truth)
        if record.state == OBSERVING and moved_away:
            record.confirm("RETURNED_OR_HELD_INSIDE")
            record.confirm("FACTUAL_MOVE_AWAY_FROM_ORIGIN")
            record.set_state(ACTIVE, truth.index)
        elif record.state in {ACTIVE, STRESSED}:
            if movement.midpoint_crossed:
                record.confirm("BROAD_MIDPOINT_REACHED")
            if at_origin:
                record.set_state(STRESSED, truth.index)
            elif moved_away or not at_origin:
                record.set_state(ACTIVE, truth.index)
        else:
            record.last_update_index = truth.index

    def _update_continuation(
            self, record: _HypothesisRecord, truth: MarketTruth,
            movement: MovementState,
            ) -> None:
        side = record.side
        assert side is not None
        if (truth.reentry and truth.broad_id == record.structure_id) or (
                truth.map_status == "BREAKOUT_FAILED" and truth.broad_id == record.structure_id):
            record.set_state(FALSIFIED, truth.index, "ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE")
            return
        if truth.accepted_break and truth.left_id != record.structure_id:
            if truth.accepted_direction == side:
                record.set_state(COMPLETED, truth.index, "NEW_STRUCTURAL_TRANSITION")
            else:
                record.set_state(FALSIFIED, truth.index, "OPPOSITE_ACCEPTED_STRUCTURAL_TRANSITION")
            return
        if truth.broad_id is not None and truth.broad_id != record.structure_id:
            record.set_state(COMPLETED, truth.index, "NEW_CONTROLLING_STRUCTURE_ESTABLISHED")
            return
        if record.destination is not None and _reached(
                truth.price, record.destination.price, side, truth.tolerance):
            record.confirm("MAPPED_REFERENCE_REACHED")
            record.set_state(COMPLETED, truth.index, "MAPPED_REFERENCE_REACHED")
            return
        if self._previous is not None and truth.index > record.birth_index:
            held = _directional_distance(record.origin.price, truth.price, side) > truth.tolerance
            progressed = _directional_distance(self._previous.price, truth.price, side) > ZERO
            if held and progressed:
                record.confirm("OUTSIDE_HELD_AFTER_ACCEPTANCE")
                record.confirm("FACTUAL_PROGRESS_AFTER_ACCEPTANCE")
                record.set_state(ACTIVE, truth.index)
                return
            if abs(truth.price - record.origin.price) <= truth.tolerance:
                record.set_state(STRESSED, truth.index)
                return
        record.last_update_index = truth.index

    def _create_hypotheses(
            self, truth: MarketTruth, movement: MovementState,
            newly_terminal: Iterable[_HypothesisRecord],
            ) -> None:
        for record in newly_terminal:
            if record.family == CONTINUATION_UP and record.state == FALSIFIED:
                self._create_failed_context(record, truth, FAILED_UP_RETURN)
            elif record.family == CONTINUATION_DOWN and record.state == FALSIFIED:
                self._create_failed_context(record, truth, FAILED_DOWN_RETURN)

        if truth.broad_id and truth.broad_low is not None and truth.broad_high is not None:
            if self._at_lower(truth) and not self._has_live(LOWER_ROTATION, truth.broad_id):
                self._create_record(
                    family=LOWER_ROTATION,
                    side=UP,
                    truth=truth,
                    premise=(
                        "CONTROLLING_BROAD_STRUCTURE_PRESENT",
                        "LOWER_STRUCTURAL_AREA_OBSERVED",
                        "NO_ACCEPTED_FAILURE_BELOW_AT_BIRTH",
                    ),
                    origin=ReferenceFact(
                        f"{truth.broad_id}.low", truth.broad_id,
                        "BROAD_LOWER_EDGE", UP, truth.broad_low),
                    destination=ReferenceFact(
                        f"{truth.broad_id}.high", truth.broad_id,
                        "BROAD_UPPER_EDGE", UP, truth.broad_high),
                    invalidation=StructuralInvalidation(
                        truth.broad_id,
                        "accepted structural failure below controlling Broad",
                        truth.broad_low,
                        DOWN,
                    ),
                    structure_id=truth.broad_id,
                    state=OBSERVING,
                )
            if self._at_upper(truth) and not self._has_live(UPPER_ROTATION, truth.broad_id):
                self._create_record(
                    family=UPPER_ROTATION,
                    side=DOWN,
                    truth=truth,
                    premise=(
                        "CONTROLLING_BROAD_STRUCTURE_PRESENT",
                        "UPPER_STRUCTURAL_AREA_OBSERVED",
                        "NO_ACCEPTED_FAILURE_ABOVE_AT_BIRTH",
                    ),
                    origin=ReferenceFact(
                        f"{truth.broad_id}.high", truth.broad_id,
                        "BROAD_UPPER_EDGE", DOWN, truth.broad_high),
                    destination=ReferenceFact(
                        f"{truth.broad_id}.low", truth.broad_id,
                        "BROAD_LOWER_EDGE", DOWN, truth.broad_low),
                    invalidation=StructuralInvalidation(
                        truth.broad_id,
                        "accepted structural failure above controlling Broad",
                        truth.broad_high,
                        UP,
                    ),
                    structure_id=truth.broad_id,
                    state=OBSERVING,
                )
        if truth.accepted_break and truth.left_id and truth.left_edge is not None:
            direction = truth.accepted_direction
            assert direction is not None
            family = CONTINUATION_UP if direction == UP else CONTINUATION_DOWN
            release = self._matching_release(truth, direction)
            if release is not None and not self._has_live(family, truth.left_id):
                destination = self._immediate_reference(truth, direction)
                self._create_record(
                    family=family,
                    side=direction,
                    truth=truth,
                    premise=(
                        "PRODUCTION_ACCEPTED_STRUCTURAL_BREAK",
                        f"RELEASE_FACT_{release.scale}",
                        "BROKEN_BOUNDARY_FACTUAL",
                    ),
                    origin=ReferenceFact(
                        f"{truth.left_id}.{'high' if direction == UP else 'low'}",
                        truth.left_id,
                        "RELEASED_BROAD_EDGE",
                        direction,
                        truth.left_edge,
                    ),
                    destination=destination,
                    invalidation=StructuralInvalidation(
                        truth.left_id,
                        "accepted return inside released Broad structure",
                        truth.left_edge,
                        DOWN if direction == UP else UP,
                    ),
                    structure_id=truth.left_id,
                    state=ACTIVE,
                )

    def _create_failed_context(
            self, continuation: _HypothesisRecord, truth: MarketTruth,
            family: str,
            ) -> None:
        if self._has_live(family, continuation.structure_id):
            return
        self._create_record(
            family=family,
            side=None,
            truth=truth,
            premise=(
                f"PRIOR_{continuation.family}_WAS_FACTUAL",
                "ACCEPTED_RETURN_INSIDE_OBSERVED",
                "NO_OPPOSITE_PARTICIPATION_IMPLIED",
            ),
            origin=continuation.origin,
            destination=None,
            invalidation=None,
            structure_id=continuation.structure_id,
            state=OBSERVING,
        )

    def _resolve_failed_contexts(self, truth: MarketTruth) -> None:
        for record in self._live_records():
            if record.family not in {FAILED_UP_RETURN, FAILED_DOWN_RETURN}:
                continue
            wanted_side = DOWN if record.family == FAILED_UP_RETURN else UP
            independent = any(
                item.hypothesis_id != record.hypothesis_id
                and item.side == wanted_side
                and item.state == ACTIVE
                for item in self._hypotheses.values()
            )
            if independent:
                record.set_state(
                    COMPLETED, truth.index, "INDEPENDENT_OPPOSITE_HYPOTHESIS_ESTABLISHED")
            elif truth.broad_id != record.structure_id:
                record.set_state(COMPLETED, truth.index, "REASSESSMENT_CONTEXT_CHANGED")

    def _snapshot(self, record: _HypothesisRecord, truth: MarketTruth) -> HypothesisState:
        if record.side is None:
            travelled = remaining = total = None
        else:
            travelled = max(
                ZERO,
                _directional_distance(record.origin.price, truth.price, record.side),
            )
            remaining = (None if record.destination is None else
                         _remaining(truth.price, record.destination.price, record.side))
            total = (None if record.destination is None else
                     abs(record.destination.price - record.origin.price))
        return HypothesisState(
            hypothesis_id=record.hypothesis_id,
            family=record.family,
            side=record.side,
            birth_index=record.birth_index,
            factual_premise=record.factual_premise,
            state=record.state,
            confirmation_facts=tuple(record.confirmations),
            movement_origin=record.origin,
            movement_destination=record.destination,
            travelled_points=travelled,
            remaining_points=remaining,
            structural_fraction_traversed=_ratio(travelled, total),
            invalidation=record.invalidation,
            structure_id=record.structure_id,
            last_update_index=record.last_update_index,
            terminal_reason=record.terminal_reason,
        )

    def _snapshots(self, truth: MarketTruth) -> tuple[HypothesisState, ...]:
        return tuple(self._snapshot(item, truth) for item in self._hypotheses.values())

    def _record_hypothesis_history(self, snapshots: Iterable[HypothesisState]) -> None:
        for snapshot in snapshots:
            history = self._hypothesis_history.setdefault(snapshot.hypothesis_id, [])
            if not history or history[-1].last_update_index != snapshot.last_update_index:
                history.append(snapshot)

    def _participation_state(
            self, truth: MarketTruth, movement: MovementState,
            snapshots: tuple[HypothesisState, ...],
            ) -> ParticipationState:
        if self._position is not None:
            return ParticipationState(
                POSITION_ACTIVE,
                self._position.hypothesis_id,
                ("OPEN_SHADOW_POSITION_MANAGED_BY_ITS_HYPOTHESIS",),
            )
        active = [item for item in snapshots if item.state == ACTIVE and item.side is not None]
        if not active:
            observing = [item for item in snapshots
                         if item.state in {OBSERVING, STRESSED}]
            return ParticipationState(
                HYPOTHESIS_OBSERVING if observing else NO_ACTIVE_HYPOTHESIS,
                None,
                (("PREMISE_NOT_ACTIVE_OR_IS_STRESSED",) if observing
                 else ("NO_DIRECTIONAL_HYPOTHESIS",)),
            )
        if len(active) != 1:
            return ParticipationState(
                HYPOTHESIS_CONFLICT,
                None,
                ("MULTIPLE_ACTIVE_HYPOTHESES_WITHOUT_STRUCTURAL_DOMINANCE",),
            )
        hypothesis = active[0]
        consumed = hypothesis.travelled_points
        room = hypothesis.remaining_points
        invalidation_distance = (
            None if hypothesis.invalidation is None
            else abs(truth.price - hypothesis.invalidation.level)
        )
        common = {
            "hypothesis_id": hypothesis.hypothesis_id,
            "movement_consumed_points": consumed,
            "movement_consumed_atr": _atr_ratio(consumed, truth.atr),
            "structural_room_points": room,
            "structural_room_atr": _atr_ratio(room, truth.atr),
            "invalidation_distance_points": invalidation_distance,
            "invalidation_distance_atr": _atr_ratio(invalidation_distance, truth.atr),
            "midpoint_crossed_before_participation": movement.midpoint_crossed,
            "next_reference_already_reached": (
                hypothesis.movement_destination is not None
                and _reached(
                    truth.price, hypothesis.movement_destination.price,
                    hypothesis.side or UP, truth.tolerance)),
        }
        if hypothesis.hypothesis_id in self._risk_consumed:
            # A position-risk exit consumes participation for that one hypothesis
            # instance.  The hypothesis itself stays observable and may still become
            # STRESSED, recover, COMPLETE or be FALSIFIED; it simply cannot open a
            # second position.  A genuinely new position needs a genuinely new
            # structural premise, which carries a new hypothesis identity.
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=(PARTICIPATION_CONSUMED_BY_POSITION_RISK,),
                **common,
            )
        if hypothesis.invalidation is None:
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=("FACTUAL_INVALIDATION_NOT_AVAILABLE",),
                **common,
            )
        if hypothesis.movement_destination is None or room is None:
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=("NEXT_STRUCTURAL_REFERENCE_NOT_AVAILABLE",),
                **common,
            )
        if common["next_reference_already_reached"]:
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=("ALREADY_AT_STRUCTURAL_DECISION_POINT",),
                **common,
            )
        if (hypothesis.family in {LOWER_ROTATION, UPPER_ROTATION}
                and movement.midpoint_crossed is True):
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=("FIRST_STRUCTURAL_SEGMENT_ALREADY_CONSUMED",),
                **common,
            )
        if hypothesis.family in {CONTINUATION_UP, CONTINUATION_DOWN}:
            needed = {"OUTSIDE_HELD_AFTER_ACCEPTANCE", "FACTUAL_PROGRESS_AFTER_ACCEPTANCE"}
            if not needed.issubset(hypothesis.confirmation_facts):
                return ParticipationState(
                    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                    reasons=("WAITING_FOR_POST_ACCEPTANCE_HOLD_AND_PROGRESS",),
                    **common,
                )
        if movement.phase in {NOT_ESTABLISHED, AT_REFERENCE, STRUCTURAL_TRANSITION}:
            return ParticipationState(
                HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
                reasons=(f"MOVEMENT_PHASE_{movement.phase}",),
                **common,
            )
        return ParticipationState(
            PARTICIPATION_AVAILABLE,
            reasons=(
                "ONE_ACTIVE_HYPOTHESIS",
                "FACTUAL_INVALIDATION_AVAILABLE",
                "STRUCTURAL_REFERENCE_AHEAD",
                "STRUCTURAL_PATH_NOT_YET_CONSUMED",
            ),
            **common,
        )

    def _position_action(
            self, truth: MarketTruth, movement: MovementState,
            participation: ParticipationState,
            ) -> tuple[str, tuple[str, ...]]:
        if self._position is not None:
            self._update_open_position(truth, movement)
            record = self._hypotheses[self._position.hypothesis_id]
            if record.state in TERMINAL_HYPOTHESIS_STATUSES:
                reason = record.terminal_reason or record.state
                self._close_position(truth, record, reason)
                return EXIT, (reason, "RETURNED_TO_FLAT_BEFORE_ANY_REASSESSMENT")
            if self._position_risk_breached(truth):
                self._risk_consumed.add(self._position.hypothesis_id)
                self._close_position(
                    truth, record, POSITION_INVALIDATION_LEVEL_CROSSED)
                return EXIT, (
                    POSITION_INVALIDATION_LEVEL_CROSSED,
                    "OPEN_POSITION_RISK_IS_NOT_HYPOTHESIS_FALSIFICATION",
                    "PARTICIPATION_CONSUMED_FOR_THIS_HYPOTHESIS_INSTANCE",
                    "RETURNED_TO_FLAT_BEFORE_ANY_REASSESSMENT",
                )
            return HOLD, ("ACTIVE_HYPOTHESIS_PREMISE_REMAINS_INTACT",)

        if participation.status == PARTICIPATION_AVAILABLE:
            assert participation.hypothesis_id is not None
            record = self._hypotheses[participation.hypothesis_id]
            assert record.side is not None
            assert record.invalidation is not None
            assert record.destination is not None
            path = abs(record.destination.price - truth.price)
            self._position = _OpenPosition(
                hypothesis_id=record.hypothesis_id,
                family=record.family,
                side=record.side,
                entry_index=truth.index,
                entry_price=truth.price,
                invalidation=record.invalidation,
                destination=record.destination,
                structural_path_available=path,
            )
            action = ENTER_LONG_SHADOW if record.side == UP else ENTER_SHORT_SHADOW
            return action, participation.reasons
        if participation.status == NO_ACTIVE_HYPOTHESIS:
            return NO_ACTION, participation.reasons
        return WAIT, participation.reasons

    def _position_risk_breached(self, truth: MarketTruth) -> bool:
        """Has an open ROTATION position's own frozen invalidation been crossed?

        This asks a different question from the hypothesis lifecycle.  A rotation
        hypothesis stays formally unresolved until production accepted structural
        failure, and that is not changed here.  An *open position* does not need to
        remain exposed after the level it was entered against has been closed beyond.

        Continuations are deliberately excluded: their invalidation is the released
        Broad edge that price has already left, a structurally different geometry, and
        nothing in the audit named them.
        """

        position = self._position
        if self.brain != BRAIN_V2 or position is None:
            return False
        if position.family not in ROTATION_FAMILIES:
            return False
        return crossed_invalidation(
            truth.price, position.invalidation.level, position.side)

    def _update_open_position(self, truth: MarketTruth, movement: MovementState) -> None:
        assert self._position is not None
        progress = max(
            ZERO,
            _directional_distance(
                self._position.entry_price, truth.price, self._position.side),
        )
        self._position.furthest_progress = max(self._position.furthest_progress, progress)
        if movement.midpoint_crossed is True:
            self._position.landmarks.add("BROAD_MIDPOINT_REACHED")
        if movement.opposite_edge_reached is True:
            self._position.landmarks.add("OPPOSITE_BROAD_EDGE_REACHED")
        if _reached(
                truth.price, self._position.destination.price,
                self._position.side, truth.tolerance):
            self._position.landmarks.add("NEXT_STRUCTURAL_REFERENCE_REACHED")
        if truth.accepted_break:
            self._position.landmarks.add("STRUCTURAL_TRANSITION_REACHED")

    def _close_position(
            self, truth: MarketTruth, hypothesis: _HypothesisRecord,
            reason: str,
            ) -> None:
        assert self._position is not None
        opened = self._position
        available = opened.structural_path_available
        traversed = min(opened.furthest_progress, available)
        falsification = hypothesis.terminal_index if hypothesis.state == FALSIFIED else None
        distance_to_false = (
            abs(truth.price - opened.entry_price) if falsification == truth.index else None)
        self.position_episodes.append(PositionEpisode(
            source_episode_id=self.source_episode_id,
            hypothesis_id=opened.hypothesis_id,
            family=opened.family,
            side=opened.side,
            entry_index=opened.entry_index,
            entry_price=opened.entry_price,
            exit_index=truth.index,
            exit_price=truth.price,
            exit_reason=reason,
            invalidation_distance_at_entry=abs(
                opened.entry_price - opened.invalidation.level),
            structural_path_available_at_entry=available,
            structural_path_traversed_while_valid=traversed,
            path_participation_fraction=_ratio(traversed, available),
            landmarks_reached=tuple(sorted(opened.landmarks)),
            hypothesis_falsification_index=falsification,
            exited_on_first_falsification=(
                truth.index == falsification if falsification is not None else None),
            distance_entry_to_falsification=distance_to_false,
        ))
        self._position = None

    def _position_snapshot(self, truth: MarketTruth) -> ShadowPositionState:
        if self._position is None:
            return ShadowPositionState(FLAT)
        opened = self._position
        available = opened.structural_path_available
        traversed = min(opened.furthest_progress, available)
        return ShadowPositionState(
            state=SHADOW_LONG if opened.side == UP else SHADOW_SHORT,
            hypothesis_id=opened.hypothesis_id,
            family=opened.family,
            entry_index=opened.entry_index,
            entry_price=opened.entry_price,
            invalidation_structure_id=opened.invalidation.structure_id,
            invalidation_reason=opened.invalidation.reason,
            invalidation_level=opened.invalidation.level,
            current_distance_to_invalidation=abs(
                truth.price - opened.invalidation.level),
            structural_path_available_at_entry=available,
            structural_path_traversed_while_valid=traversed,
            path_participation_fraction=_ratio(traversed, available),
        )


def replay_truths(
        truths: Iterable[MarketTruth], *, brain: str = BRAIN_V2,
        ) -> list[ShadowDecision]:
    """Replay a pre-frozen source episode, primarily for deterministic synthetic tests."""

    items = list(truths)
    if not items:
        return []
    machine = DynamicShadowTrader(
        items[0].bucket, items[0].source_episode_id, brain=brain)
    return [machine.observe_truth(item) for item in items]


__all__ = [
    "ACTIONS",
    "ACTIVE",
    "AT_REFERENCE",
    "BRAIN_V1",
    "BRAIN_V2",
    "BRAIN_VERSIONS",
    "COMPLETED",
    "CONTINUATION_DOWN",
    "CONTINUATION_FAMILIES",
    "CONTINUATION_UP",
    "DOWN",
    "EARLY",
    "ENTER_LONG_SHADOW",
    "ENTER_SHORT_SHADOW",
    "EXIT",
    "EXPIRED",
    "FAILED_DOWN_RETURN",
    "FAILED_UP_RETURN",
    "FALSIFIED",
    "FLAT",
    "HOLD",
    "HYPOTHESIS_CONFLICT",
    "HYPOTHESIS_FAMILIES",
    "HYPOTHESIS_OBSERVING",
    "HYPOTHESIS_VALID_BUT_NO_PARTICIPATION",
    "IN_PROGRESS",
    "LOWER_ROTATION",
    "NOT_ESTABLISHED",
    "NO_ACTION",
    "NO_ACTIVE_HYPOTHESIS",
    "OBSERVING",
    "PARTICIPATION_AVAILABLE",
    "PARTICIPATION_CONSUMED_BY_POSITION_RISK",
    "POSITION_INVALIDATION_LEVEL_CROSSED",
    "POSITION_RISK_EXIT_REASONS",
    "ROTATION_FAMILIES",
    "SHADOW_LONG",
    "SHADOW_SHORT",
    "STRESSED",
    "STRUCTURAL_TRANSITION",
    "TEACH",
    "UP",
    "UPPER_ROTATION",
    "VALIDATE",
    "WAIT",
    "DynamicShadowTrader",
    "MarketTruth",
    "MicroFact",
    "MovementState",
    "ParticipationState",
    "PositionEpisode",
    "ReferenceFact",
    "ReleaseFact",
    "ShadowDecision",
    "ShadowPositionState",
    "StructuralInvalidation",
    "crossed_invalidation",
    "market_truth_from_frame",
    "replay_truths",
]
