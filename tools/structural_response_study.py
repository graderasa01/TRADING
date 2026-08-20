"""Research-only, candle-by-candle structural response ledgers.

The observer in this module consumes frozen facts already published by
``StructuralFrame``.  It neither changes the production map nor feeds facts back into
it.  Structure, edge-encounter, and release origins are immutable; later candles only
append neutral geometry observations to their linked ledgers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes.frontier import Frontier
from src.boxes.snapshot import build_snapshot
from src.boxes.structure import BREAK_CLOSES, tol_at
from src.domain.models import Candle
from src.learning.split import TEACH, VALIDATE
from src.livemap import frame as structural_frame
from src.livemap import thesis as thesis_mod
from tools.live_structure_truth import (
    ResearchEpisode,
    load_research_episodes,
    observational_local_candidates,
)

SYMBOL = "NIFTY BANK"
UPPER = "upper"
LOWER = "lower"
SIDES = (UPPER, LOWER)
REAL = "REAL"
GHOST = "GHOST"
BOUNDARY_KINDS = (REAL, GHOST)

FROM_INSIDE = "FROM_INSIDE_TOWARD_EDGE"
FROM_OUTSIDE = "FROM_OUTSIDE_TOWARD_EDGE"
ALREADY_AT_EDGE = "ALREADY_AT_EDGE"
UNKNOWN_ORIGIN = "UNKNOWN"
ORIGIN_CLASSES = (FROM_INSIDE, FROM_OUTSIDE, ALREADY_AT_EDGE, UNKNOWN_ORIGIN)
FIRST_ENCOUNTER = "FIRST"
REPEAT_ENCOUNTER = "REPEAT"

EVENTS = frozenset({
    "APPROACH_UPPER", "APPROACH_LOWER", "TOUCH_UPPER", "TOUCH_LOWER",
    "CLOSE_INSIDE_AFTER_UPPER_TEST", "CLOSE_INSIDE_AFTER_LOWER_TEST",
    "CLOSE_AT_UPPER", "CLOSE_AT_LOWER", "CLOSE_OUTSIDE_UPPER",
    "CLOSE_OUTSIDE_LOWER", "RECLAIM_UPPER", "RECLAIM_LOWER",
    "HOLD_INSIDE_AFTER_RECLAIM", "BREAK_ATTEMPT_UP", "BREAK_ATTEMPT_DOWN",
    "ACCEPTED_ABOVE", "ACCEPTED_BELOW", "RE_ENTRY", "MIDPOINT_REACHED",
    "OPPOSITE_EDGE_REACHED", "REVISIT", "LEFT_STRUCTURE", "RETURN_RETEST",
    "OUTWARD_REFERENCE_REACHED", "INWARD_REFERENCE_REACHED",
})


@dataclass(frozen=True, slots=True)
class ReferenceFact:
    label: str
    price: Decimal
    role: str


@dataclass(frozen=True, slots=True)
class MicroContext:
    state: str
    micro_id: str | None = None
    low: Decimal | None = None
    high: Decimal | None = None
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocalContext:
    present: bool
    kind: str | None = None
    low: Decimal | None = None
    high: Decimal | None = None
    holder_id: str | None = None
    relation_to_micro: str = "NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class StructureFact:
    structure_id: str
    kind: str
    low: Decimal
    high: Decimal
    parent_id: str | None
    price_location: str
    birth_index: int | None = None

    @property
    def width(self) -> Decimal:
        return self.high - self.low


@dataclass(frozen=True, slots=True)
class ReleaseFact:
    release_id: str
    scale: str
    origin: str
    broken_id: str
    broken_edge: Decimal
    broken_low: Decimal | None
    broken_high: Decimal | None
    broken_kind: str
    direction: str
    parent_id: str | None
    price: Decimal
    beyond: Decimal
    beyond_atr: float
    location: str
    route_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CausalSample:
    bucket: str
    source_episode_id: str
    source_ordinal: int
    index: int
    at: datetime
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    atr: Decimal
    tolerance: Decimal
    frontier_state: str
    interaction: str
    current: StructureFact | None = None
    left_id: str | None = None
    micro: MicroContext = MicroContext("ABSENT")
    local: LocalContext = LocalContext(False)
    next_above: ReferenceFact | None = None
    next_below: ReferenceFact | None = None
    thesis_identity: str | None = None
    thesis_invalidation: Decimal | None = None
    releases: tuple[ReleaseFact, ...] = ()


@dataclass(frozen=True, slots=True)
class StructureOrigin:
    bucket: str
    source_episode_id: str
    structure_episode_id: str
    structure_id: str
    kind: str
    low: Decimal
    high: Decimal
    width: Decimal
    parent_id: str | None
    birth_index: int | None
    causal_available_index: int
    first_current_index: int
    initial_price_location: str
    originating_interaction: str
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class StructureObservation:
    index: int
    source_ordinal: int
    close_location: str
    frontier_state: str
    interaction: str
    events: tuple[str, ...]


@dataclass(slots=True)
class StructureEpisode:
    origin: StructureOrigin
    observations: list[StructureObservation] = field(default_factory=list)
    bars_alive: int = 0
    bars_current: int = 0
    bars_price_inside: int = 0
    visits: int = 1
    revisits: int = 0
    leaving: int = 0
    reentries: int = 0
    upper_encounters: int = 0
    lower_encounters: int = 0
    accepted_break: str | None = None
    finalised: bool = False
    end_index: int | None = None
    end_reason: str | None = None

    def append(self, observation: StructureObservation, *, current: bool) -> None:
        if self.observations and observation.index <= self.observations[-1].index:
            raise AssertionError("structure observations must be strictly append-only")
        if observation.index < self.origin.causal_available_index:
            raise AssertionError("structure observation predates its frozen origin")
        self.observations.append(observation)
        self.bars_alive += 1
        self.bars_current += int(current)
        self.bars_price_inside += int(observation.close_location == "INSIDE")
        self.revisits += int(observation.interaction == "REVISIT")
        self.leaving += int(observation.frontier_state == "LEAVING")
        self.reentries += int(observation.interaction == "RE_ENTRY")
        if observation.interaction in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"}:
            self.accepted_break = observation.interaction


@dataclass(frozen=True, slots=True)
class EncounterOrigin:
    bucket: str
    source_episode_id: str
    encounter_id: str
    structure_episode_id: str
    structure_id: str
    edge_id: str
    side: str
    edge_price: Decimal
    start_index: int
    source_ordinal: int
    price_location: str
    origin_class: str
    structure_width: Decimal
    atr: Decimal
    micro: MicroContext
    local: LocalContext
    outward_reference: ReferenceFact | None
    inward_reference: ReferenceFact | None
    thesis_identity: str | None
    thesis_invalidation: Decimal | None
    ordinal_for_edge: int


@dataclass(frozen=True, slots=True)
class EncounterObservation:
    index: int
    source_ordinal: int
    close_location: str
    events: tuple[str, ...]
    inside_excursion: Decimal
    outside_excursion: Decimal


@dataclass(slots=True)
class EdgeEncounter:
    origin: EncounterOrigin
    observations: list[EncounterObservation] = field(default_factory=list)
    first_touch_index: int | None = None
    max_penetration_points: Decimal = Decimal(0)
    max_penetration_atr: Decimal | None = None
    next_closed_candle_location: str | None = None
    first_reclaim_index: int | None = None
    first_accepted_break_index: int | None = None
    first_return_retest_index: int | None = None
    first_move_toward_mid_index: int | None = None
    midpoint_reached_index: int | None = None
    opposite_edge_reached_index: int | None = None
    outward_reference_reached_index: int | None = None
    inward_reference_reached_index: int | None = None
    bars_inside: int = 0
    bars_outside: int = 0
    max_inside_excursion: Decimal = Decimal(0)
    max_outside_excursion: Decimal = Decimal(0)
    end_index: int | None = None
    end_reason: str | None = None
    _had_outside: bool = False

    def append(self, observation: EncounterObservation) -> None:
        if self.observations and observation.index <= self.observations[-1].index:
            raise AssertionError("encounter observations must be strictly append-only")
        if observation.index < self.origin.start_index:
            raise AssertionError("encounter observation predates its frozen origin")
        if self.observations and self.next_closed_candle_location is None:
            self.next_closed_candle_location = observation.close_location
        self.observations.append(observation)
        self.bars_inside += int(observation.close_location != "OUTSIDE")
        self.bars_outside += int(observation.close_location == "OUTSIDE")
        self.max_inside_excursion = max(
            self.max_inside_excursion, observation.inside_excursion)
        self.max_outside_excursion = max(
            self.max_outside_excursion, observation.outside_excursion)
        self.max_penetration_points = self.max_outside_excursion
        if self.origin.atr > 0:
            self.max_penetration_atr = self.max_penetration_points / self.origin.atr
        self._had_outside = self._had_outside or observation.close_location == "OUTSIDE"


@dataclass(frozen=True, slots=True)
class ReleaseOrigin:
    bucket: str
    source_episode_id: str
    release_episode_id: str
    release_id: str
    structure_episode_id: str
    encounter_id: str | None
    index: int
    source_ordinal: int
    scale: str
    origin: str
    broken_structure_id: str
    broken_edge: Decimal
    broken_low: Decimal | None
    broken_high: Decimal | None
    broken_kind: str
    direction: str
    parent_id: str | None
    price: Decimal
    beyond: Decimal
    beyond_atr: float
    location: str
    route_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseObservation:
    index: int
    source_ordinal: int
    state: str
    distance_beyond_edge: Decimal


@dataclass(slots=True)
class ReleaseEpisode:
    origin: ReleaseOrigin
    observations: list[ReleaseObservation] = field(default_factory=list)
    bars_held: int = 0
    giveback_index: int | None = None
    end_index: int | None = None
    end_reason: str | None = None

    def append(self, observation: ReleaseObservation) -> None:
        if self.observations and observation.index <= self.observations[-1].index:
            raise AssertionError("release observations must be strictly append-only")
        if observation.index < self.origin.index:
            raise AssertionError("release observation predates its frozen origin")
        self.observations.append(observation)
        self.bars_held += int(observation.state == "HELD")
        if observation.state == "GIVEBACK" and self.giveback_index is None:
            self.giveback_index = observation.index


@dataclass(frozen=True, slots=True)
class NullProbe:
    structure_episode_id: str
    label: str
    side: str | None
    index: int
    close_on_interior_side: bool
    next_close_on_interior_side: bool
    next_close_inside_structure: bool


@dataclass(frozen=True, slots=True)
class BoundaryDefinition:
    """One real or mechanical boundary with identical one-sided topology."""

    boundary_kind: str
    boundary_id: str
    structure_episode_id: str
    structure_id: str
    structure_kind: str
    side: str
    edge_price: Decimal
    band_low: Decimal
    band_high: Decimal
    structure_width: Decimal

    @property
    def band_width(self) -> Decimal:
        return self.band_high - self.band_low


@dataclass(frozen=True, slots=True)
class BoundaryEncounterOrigin:
    bucket: str
    source_episode_id: str
    encounter_id: str
    boundary_kind: str
    boundary_id: str
    structure_episode_id: str
    structure_id: str
    structure_kind: str
    side: str
    edge_price: Decimal
    band_low: Decimal
    band_high: Decimal
    structure_width: Decimal
    start_index: int
    source_ordinal: int
    price_location: str
    origin_class: str
    encounter_order: str
    ordinal_for_boundary: int
    atr: Decimal
    micro: MicroContext
    outward_reference: ReferenceFact | None
    inward_reference: ReferenceFact | None


@dataclass(frozen=True, slots=True)
class BoundaryObservation:
    index: int
    source_ordinal: int
    close_location: str
    touched: bool
    events: tuple[str, ...]
    inside_excursion: Decimal
    outside_excursion: Decimal


@dataclass(slots=True)
class BoundaryEncounter:
    """Shared lifecycle used without branching on REAL versus GHOST."""

    origin: BoundaryEncounterOrigin
    observations: list[BoundaryObservation] = field(default_factory=list)
    first_touch_index: int | None = None
    next_closed_candle_location: str | None = None
    first_outside_close_index: int | None = None
    first_reclaim_index: int | None = None
    first_return_retest_index: int | None = None
    remained_inside_after_reclaim_index: int | None = None
    persistent_outside_index: int | None = None
    first_move_away_index: int | None = None
    bars_inside: int = 0
    bars_outside: int = 0
    max_inside_excursion: Decimal = Decimal(0)
    max_outside_excursion: Decimal = Decimal(0)
    end_index: int | None = None
    end_reason: str | None = None
    _had_outside: bool = False
    _consecutive_outside: int = 0

    def append(self, observation: BoundaryObservation) -> None:
        if self.observations and observation.index <= self.observations[-1].index:
            raise AssertionError("boundary observations must be strictly append-only")
        if observation.index < self.origin.start_index:
            raise AssertionError("boundary observation predates its frozen origin")
        if self.observations and self.next_closed_candle_location is None:
            self.next_closed_candle_location = observation.close_location
        self.observations.append(observation)
        outside = observation.close_location == "OUTSIDE"
        self.bars_inside += int(not outside)
        self.bars_outside += int(outside)
        self.max_inside_excursion = max(
            self.max_inside_excursion, observation.inside_excursion)
        self.max_outside_excursion = max(
            self.max_outside_excursion, observation.outside_excursion)
        self._had_outside = self._had_outside or outside
        self._consecutive_outside = self._consecutive_outside + 1 if outside else 0


def comparison_boundaries(origin: StructureOrigin) -> tuple[BoundaryDefinition, ...]:
    """Create real and midpoint ghost boundaries before any response is observed."""

    midpoint = (origin.low + origin.high) / Decimal(2)
    width = origin.width
    return (
        BoundaryDefinition(
            REAL, f"{origin.structure_episode_id}:REAL:upper",
            origin.structure_episode_id, origin.structure_id, origin.kind,
            UPPER, origin.high, origin.low, origin.high, width),
        BoundaryDefinition(
            REAL, f"{origin.structure_episode_id}:REAL:lower",
            origin.structure_episode_id, origin.structure_id, origin.kind,
            LOWER, origin.low, origin.low, origin.high, width),
        BoundaryDefinition(
            GHOST, f"{origin.structure_episode_id}:GHOST:upper",
            origin.structure_episode_id, origin.structure_id, origin.kind,
            UPPER, midpoint, midpoint - width, midpoint, width),
        BoundaryDefinition(
            GHOST, f"{origin.structure_episode_id}:GHOST:lower",
            origin.structure_episode_id, origin.structure_id, origin.kind,
            LOWER, midpoint, midpoint, midpoint + width, width),
    )


def _close_location(side: str, edge: Decimal, close: Decimal,
                    tolerance: Decimal) -> str:
    outside = close > edge if side == UPPER else close < edge
    if outside:
        return "OUTSIDE"
    if abs(close - edge) <= tolerance:
        return "AT"
    return "INSIDE"


def _structure_location(origin: StructureOrigin, close: Decimal) -> str:
    if close < origin.low:
        return "BELOW"
    if close > origin.high:
        return "ABOVE"
    return "INSIDE"


def _current_price_location(sample: CausalSample, origin: StructureOrigin) -> str:
    current = sample.current
    if current is not None and current.structure_id == origin.structure_id:
        return current.price_location
    return _structure_location(origin, sample.c)


def _same_structure(sample: CausalSample | None, structure_id: str) -> bool:
    return bool(sample and sample.current
                and sample.current.structure_id == structure_id)


def _boundary_interacts(sample: CausalSample, structure_id: str, *,
                        side: str, edge: Decimal,
                        previous: CausalSample | None) -> bool:
    """One threshold-free interaction rule shared by real and ghost boundaries."""

    range_reaches = (sample.l <= edge + sample.tolerance
                     and sample.h >= edge - sample.tolerance)
    current_location = _close_location(side, edge, sample.c, sample.tolerance)
    crossed_between_closes = False
    if _same_structure(previous, structure_id):
        assert previous is not None
        prior_location = _close_location(
            side, edge, previous.c, previous.tolerance)
        crossed_between_closes = (
            current_location == "AT"
            or {prior_location, current_location} == {"INSIDE", "OUTSIDE"})
    return range_reaches or current_location == "AT" or crossed_between_closes


def _encounter_origin_class(previous: CausalSample | None,
                            structure_id: str, *, side: str,
                            edge: Decimal) -> str:
    if not _same_structure(previous, structure_id):
        return UNKNOWN_ORIGIN
    assert previous is not None
    prior = _close_location(side, edge, previous.c, previous.tolerance)
    if prior == "INSIDE":
        return FROM_INSIDE
    if prior == "OUTSIDE":
        return FROM_OUTSIDE
    if prior == "AT":
        return ALREADY_AT_EDGE
    return UNKNOWN_ORIGIN


def _directional_references(sample: CausalSample, side: str
                            ) -> tuple[ReferenceFact | None, ReferenceFact | None]:
    if side == UPPER:
        return sample.next_above, sample.next_below
    return sample.next_below, sample.next_above


def _boundary_excursions(side: str, edge: Decimal,
                         sample: CausalSample) -> tuple[Decimal, Decimal]:
    inside = max(Decimal(0), edge - sample.l if side == UPPER else sample.h - edge)
    outside = max(Decimal(0), sample.h - edge if side == UPPER else edge - sample.l)
    return inside, outside


def _events_for_interaction(interaction: str) -> tuple[str, ...]:
    return (interaction,) if interaction in EVENTS else ()


class ResponseObserver:
    """One source episode's append-only linked ledgers."""

    def __init__(self, bucket: str, source_episode_id: str) -> None:
        if bucket not in (TEACH, VALIDATE):
            raise AssertionError("response observer accepts research buckets only")
        self.bucket = bucket
        self.source_episode_id = source_episode_id
        self.structures: list[StructureEpisode] = []
        self.encounters: list[EdgeEncounter] = []
        self.boundary_encounters: list[BoundaryEncounter] = []
        self.releases: list[ReleaseEpisode] = []
        self.null_probes: list[NullProbe] = []
        self._active_structure: StructureEpisode | None = None
        self._active_encounters: dict[str, EdgeEncounter] = {}
        self._active_boundary_encounters: dict[tuple[str, str], BoundaryEncounter] = {}
        self._active_releases: dict[str, ReleaseEpisode] = {}
        self._latest_structure_by_id: dict[str, StructureEpisode] = {}
        self._structure_counts: Counter[str] = Counter()
        self._encounter_counts: Counter[tuple[str, str]] = Counter()
        self._boundary_encounter_counts: Counter[tuple[str, str]] = Counter()
        self._last_context: StructureEpisode | None = None
        self._last_index: int | None = None
        self._last_sample: CausalSample | None = None
        self._pending_nulls: list[tuple[StructureEpisode, str, str | None,
                                        int, bool]] = []
        self._null_armed: dict[tuple[str, str], bool] = defaultdict(lambda: True)

    def observe(self, sample: CausalSample) -> None:
        self._assert_sample(sample)
        self._update_releases(sample)

        active = self._active_structure
        same = bool(active and sample.current
                    and sample.current.structure_id == active.origin.structure_id)
        if active is not None and not same:
            self._observe_structure(active, sample, current=False)
            for encounter in tuple(self._active_encounters.values()):
                if encounter.origin.structure_episode_id == active.origin.structure_episode_id:
                    self._append_encounter(encounter, active.origin, sample)
            if (sample.left_id == active.origin.structure_id
                    or sample.interaction in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"}):
                self._append_active_boundaries(active.origin, sample)
            reason = ("ACCEPTED_BREAK" if sample.interaction in {
                "ACCEPTED_ABOVE", "ACCEPTED_BELOW"} and sample.left_id == active.origin.structure_id
                      else "CONTROLLING_STRUCTURE_REPLACED" if sample.current is not None
                      else "LEFT_STRUCTURE")
            self._finish_structure(active, sample.index, reason)
            self._active_structure = None

        if sample.current is not None and not same:
            self._active_structure = self._start_structure(sample)
            active = self._active_structure
            same = True

        if same and self._active_structure is not None:
            self._observe_structure(self._active_structure, sample, current=True)
            self._observe_edges(self._active_structure, sample)
            self._observe_comparison_boundaries(self._active_structure, sample)
            self._observe_nulls(self._active_structure, sample)
        else:
            self._complete_pending_nulls(sample)

        self._create_releases(sample)
        self._last_index = sample.index
        self._last_sample = sample

    def finish(self) -> None:
        if self._last_index is None:
            return
        if self._active_structure is not None:
            self._finish_structure(
                self._active_structure, self._last_index, "SOURCE_EPISODE_BOUNDARY")
            self._active_structure = None
        for encounter in tuple(self._active_encounters.values()):
            self._finish_encounter(encounter, self._last_index,
                                   "SOURCE_EPISODE_BOUNDARY")
        for encounter in tuple(self._active_boundary_encounters.values()):
            self._finish_boundary_encounter(
                encounter, self._last_index, "SOURCE_EPISODE_BOUNDARY")
        for release in tuple(self._active_releases.values()):
            release.end_index = self._last_index
            release.end_reason = "SOURCE_EPISODE_BOUNDARY"
        self._active_releases.clear()
        self._pending_nulls.clear()

    def _assert_sample(self, sample: CausalSample) -> None:
        if sample.bucket != self.bucket or sample.source_episode_id != self.source_episode_id:
            raise AssertionError("sample crossed a bucket or source episode barrier")
        if self._last_index is not None and sample.index <= self._last_index:
            raise AssertionError("samples must be source-contiguous and increasing")

    def _start_structure(self, sample: CausalSample) -> StructureEpisode:
        current = sample.current
        assert current is not None
        self._structure_counts[current.structure_id] += 1
        episode_id = (f"{self.source_episode_id}:{current.structure_id}:"
                      f"V{self._structure_counts[current.structure_id]:03d}")
        origin = StructureOrigin(
            bucket=sample.bucket,
            source_episode_id=sample.source_episode_id,
            structure_episode_id=episode_id,
            structure_id=current.structure_id,
            kind=current.kind,
            low=current.low,
            high=current.high,
            width=current.width,
            parent_id=current.parent_id,
            birth_index=current.birth_index,
            causal_available_index=sample.index,
            first_current_index=sample.index,
            initial_price_location=current.price_location,
            originating_interaction=sample.interaction,
            source_ordinal=sample.source_ordinal,
        )
        episode = StructureEpisode(origin)
        self.structures.append(episode)
        self._latest_structure_by_id[current.structure_id] = episode
        self._last_context = episode
        return episode

    def _observe_structure(self, episode: StructureEpisode, sample: CausalSample,
                           *, current: bool) -> None:
        events = list(_events_for_interaction(sample.interaction))
        if not current:
            events.append("LEFT_STRUCTURE")
        observation = StructureObservation(
            index=sample.index,
            source_ordinal=sample.source_ordinal,
            close_location=_structure_location(episode.origin, sample.c),
            frontier_state=sample.frontier_state,
            interaction=sample.interaction,
            events=tuple(dict.fromkeys(events)),
        )
        episode.append(observation, current=current)

    def _finish_structure(self, episode: StructureEpisode, index: int,
                          reason: str) -> None:
        episode.end_index = index
        episode.end_reason = reason
        episode.finalised = reason == "ACCEPTED_BREAK"
        for encounter in tuple(self._active_encounters.values()):
            if encounter.origin.structure_episode_id == episode.origin.structure_episode_id:
                self._finish_encounter(encounter, index, reason)
        for encounter in tuple(self._active_boundary_encounters.values()):
            if encounter.origin.structure_episode_id == episode.origin.structure_episode_id:
                boundary_reason = (
                    "STRUCTURE_CONTEXT_ENDED" if reason == "ACCEPTED_BREAK" else reason)
                self._finish_boundary_encounter(encounter, index, boundary_reason)

    def _near_edge(self, sample: CausalSample, origin: StructureOrigin,
                   side: str) -> bool:
        edge = origin.high if side == UPPER else origin.low
        return _boundary_interacts(
            sample, origin.structure_id, side=side, edge=edge,
            previous=self._last_sample)

    def _observe_edges(self, structure: StructureEpisode, sample: CausalSample) -> None:
        for side in SIDES:
            encounter = self._active_encounters.get(side)
            if encounter is None and self._near_edge(sample, structure.origin, side):
                encounter = self._start_encounter(structure, sample, side)
            if encounter is not None:
                self._append_encounter(encounter, structure.origin, sample)

    def _start_encounter(self, structure: StructureEpisode, sample: CausalSample,
                         side: str) -> EdgeEncounter:
        key = (structure.origin.structure_episode_id, side)
        self._encounter_counts[key] += 1
        ordinal = self._encounter_counts[key]
        edge = structure.origin.high if side == UPPER else structure.origin.low
        outward, inward = _directional_references(sample, side)
        origin = EncounterOrigin(
            bucket=sample.bucket,
            source_episode_id=sample.source_episode_id,
            encounter_id=f"{structure.origin.structure_episode_id}:{side}:E{ordinal:03d}",
            structure_episode_id=structure.origin.structure_episode_id,
            structure_id=structure.origin.structure_id,
            edge_id=f"{structure.origin.structure_id}.{side}",
            side=side,
            edge_price=edge,
            start_index=sample.index,
            source_ordinal=sample.source_ordinal,
            price_location=_current_price_location(sample, structure.origin),
            origin_class=_encounter_origin_class(
                self._last_sample, structure.origin.structure_id,
                side=side, edge=edge),
            structure_width=structure.origin.width,
            atr=sample.atr,
            micro=sample.micro,
            local=sample.local,
            outward_reference=outward,
            inward_reference=inward,
            thesis_identity=sample.thesis_identity,
            thesis_invalidation=sample.thesis_invalidation,
            ordinal_for_edge=ordinal,
        )
        encounter = EdgeEncounter(origin)
        self.encounters.append(encounter)
        self._active_encounters[side] = encounter
        if side == UPPER:
            structure.upper_encounters += 1
        else:
            structure.lower_encounters += 1
        return encounter

    def _append_encounter(self, encounter: EdgeEncounter, structure: StructureOrigin,
                          sample: CausalSample) -> None:
        side = encounter.origin.side
        edge = encounter.origin.edge_price
        close_location = _close_location(side, edge, sample.c, sample.tolerance)
        touch = sample.h >= edge if side == UPPER else sample.l <= edge
        inside_excursion, outside_excursion = _boundary_excursions(side, edge, sample)
        midpoint = (structure.low + structure.high) / Decimal(2)
        is_later_candle = sample.index > encounter.origin.start_index
        midpoint_reached = is_later_candle and (
            sample.l <= midpoint if side == UPPER else sample.h >= midpoint)
        opposite_reached = is_later_candle and (
            sample.l <= structure.low if side == UPPER else sample.h >= structure.high)
        events = [f"APPROACH_{side.upper()}"] if not encounter.observations else []
        if touch:
            events.append(f"TOUCH_{side.upper()}")
            if encounter.first_touch_index is None:
                encounter.first_touch_index = sample.index
        if close_location == "OUTSIDE":
            events.append(f"CLOSE_OUTSIDE_{side.upper()}")
        else:
            if close_location == "AT":
                events.append(f"CLOSE_AT_{side.upper()}")
        if touch and close_location != "OUTSIDE":
            events.append(f"CLOSE_INSIDE_AFTER_{side.upper()}_TEST")
        if sample.interaction in EVENTS:
            events.append(sample.interaction)

        had_outside = encounter._had_outside
        reclaimed = had_outside and close_location != "OUTSIDE"
        if reclaimed and encounter.first_reclaim_index is None:
            encounter.first_reclaim_index = sample.index
            events.append(f"RECLAIM_{side.upper()}")
        if (encounter.first_reclaim_index is not None
                and sample.index > encounter.first_reclaim_index and touch
                and encounter.first_return_retest_index is None):
            encounter.first_return_retest_index = sample.index
            events.append("RETURN_RETEST")
        if midpoint_reached and encounter.midpoint_reached_index is None:
            encounter.midpoint_reached_index = sample.index
            encounter.first_move_toward_mid_index = sample.index
            events.append("MIDPOINT_REACHED")
        elif (is_later_candle and inside_excursion > 0
              and encounter.first_move_toward_mid_index is None):
            encounter.first_move_toward_mid_index = sample.index
        if opposite_reached and encounter.opposite_edge_reached_index is None:
            encounter.opposite_edge_reached_index = sample.index
            events.append("OPPOSITE_EDGE_REACHED")
        if (is_later_candle and encounter.outward_reference_reached_index is None
                and self._reference_reached(encounter.origin.outward_reference, sample)):
            encounter.outward_reference_reached_index = sample.index
            events.append("OUTWARD_REFERENCE_REACHED")
        if (is_later_candle and encounter.inward_reference_reached_index is None
                and self._reference_reached(encounter.origin.inward_reference, sample)):
            encounter.inward_reference_reached_index = sample.index
            events.append("INWARD_REFERENCE_REACHED")
        accepted = ((side == UPPER and sample.interaction == "ACCEPTED_ABOVE")
                    or (side == LOWER and sample.interaction == "ACCEPTED_BELOW"))
        if accepted:
            encounter.first_accepted_break_index = sample.index

        observation = EncounterObservation(
            index=sample.index,
            source_ordinal=sample.source_ordinal,
            close_location=close_location,
            events=tuple(dict.fromkeys(event for event in events if event in EVENTS)),
            inside_excursion=inside_excursion,
            outside_excursion=outside_excursion,
        )
        encounter.append(observation)

        if accepted:
            self._finish_encounter(encounter, sample.index, "ACCEPTED_BREAK")
        elif close_location == "OUTSIDE":
            pass
        elif opposite_reached:
            self._finish_encounter(encounter, sample.index, "OPPOSITE_EDGE_REACHED")
        elif midpoint_reached:
            self._finish_encounter(encounter, sample.index, "MIDPOINT_REACHED")
        elif (encounter.first_reclaim_index is not None
              and sample.index > encounter.first_reclaim_index
              and close_location == "INSIDE"):
            last = encounter.observations[-1]
            encounter.observations[-1] = EncounterObservation(
                last.index, last.source_ordinal, last.close_location,
                tuple(dict.fromkeys(last.events + ("HOLD_INSIDE_AFTER_RECLAIM",))),
                last.inside_excursion, last.outside_excursion)
            self._finish_encounter(encounter, sample.index, "RECLAIM_HELD_INSIDE")
        elif (len(encounter.observations) > 1 and not had_outside
              and close_location == "INSIDE"
              and not self._near_edge(sample, structure, side)):
            self._finish_encounter(encounter, sample.index, "MOVED_INSIDE")

    @staticmethod
    def _reference_reached(reference: ReferenceFact | None,
                           sample: CausalSample) -> bool:
        return bool(reference and sample.l <= reference.price <= sample.h)

    def _finish_encounter(self, encounter: EdgeEncounter, index: int,
                          reason: str) -> None:
        if encounter.end_reason is not None:
            return
        encounter.end_index = index
        encounter.end_reason = reason
        if self._active_encounters.get(encounter.origin.side) is encounter:
            del self._active_encounters[encounter.origin.side]

    def _observe_comparison_boundaries(self, structure: StructureEpisode,
                                       sample: CausalSample) -> None:
        for definition in comparison_boundaries(structure.origin):
            key = (definition.boundary_kind, definition.side)
            encounter = self._active_boundary_encounters.get(key)
            if (encounter is None and _boundary_interacts(
                    sample, structure.origin.structure_id, side=definition.side,
                    edge=definition.edge_price, previous=self._last_sample)):
                encounter = self._start_boundary_encounter(
                    structure.origin, definition, sample)
            if encounter is not None:
                self._append_boundary_encounter(encounter, sample)

    def _append_active_boundaries(self, structure: StructureOrigin,
                                  sample: CausalSample) -> None:
        for encounter in tuple(self._active_boundary_encounters.values()):
            if encounter.origin.structure_episode_id == structure.structure_episode_id:
                self._append_boundary_encounter(encounter, sample)

    def _start_boundary_encounter(
            self, structure: StructureOrigin, definition: BoundaryDefinition,
            sample: CausalSample) -> BoundaryEncounter:
        count_key = (definition.boundary_id, definition.side)
        self._boundary_encounter_counts[count_key] += 1
        ordinal = self._boundary_encounter_counts[count_key]
        outward, inward = _directional_references(sample, definition.side)
        encounter_order = FIRST_ENCOUNTER if ordinal == 1 else REPEAT_ENCOUNTER
        origin = BoundaryEncounterOrigin(
            bucket=sample.bucket,
            source_episode_id=sample.source_episode_id,
            encounter_id=f"{definition.boundary_id}:E{ordinal:03d}",
            boundary_kind=definition.boundary_kind,
            boundary_id=definition.boundary_id,
            structure_episode_id=definition.structure_episode_id,
            structure_id=definition.structure_id,
            structure_kind=definition.structure_kind,
            side=definition.side,
            edge_price=definition.edge_price,
            band_low=definition.band_low,
            band_high=definition.band_high,
            structure_width=definition.structure_width,
            start_index=sample.index,
            source_ordinal=sample.source_ordinal,
            price_location=_current_price_location(sample, structure),
            origin_class=_encounter_origin_class(
                self._last_sample, structure.structure_id, side=definition.side,
                edge=definition.edge_price),
            encounter_order=encounter_order,
            ordinal_for_boundary=ordinal,
            atr=sample.atr,
            micro=sample.micro,
            outward_reference=outward,
            inward_reference=inward,
        )
        encounter = BoundaryEncounter(origin)
        self.boundary_encounters.append(encounter)
        self._active_boundary_encounters[
            (definition.boundary_kind, definition.side)] = encounter
        return encounter

    def _append_boundary_encounter(self, encounter: BoundaryEncounter,
                                   sample: CausalSample) -> None:
        """The only response state machine used by both real and ghost boundaries."""

        origin = encounter.origin
        close_location = _close_location(
            origin.side, origin.edge_price, sample.c, sample.tolerance)
        touched = sample.l <= origin.edge_price <= sample.h
        inside_excursion, outside_excursion = _boundary_excursions(
            origin.side, origin.edge_price, sample)
        is_later = sample.index > origin.start_index
        had_outside = encounter._had_outside
        events = []
        if touched:
            events.append("TOUCH")
            if encounter.first_touch_index is None:
                encounter.first_touch_index = sample.index
        events.append(f"CLOSE_{close_location}")
        if close_location == "OUTSIDE" and encounter.first_outside_close_index is None:
            encounter.first_outside_close_index = sample.index
        reclaimed = had_outside and close_location != "OUTSIDE"
        if reclaimed and encounter.first_reclaim_index is None:
            encounter.first_reclaim_index = sample.index
            events.append("RECLAIM")
        if (encounter.first_reclaim_index is not None
                and sample.index > encounter.first_reclaim_index and touched
                and encounter.first_return_retest_index is None):
            encounter.first_return_retest_index = sample.index
            events.append("RETURN_RETEST")
        if is_later and close_location == "INSIDE" and encounter.first_move_away_index is None:
            encounter.first_move_away_index = sample.index
            events.append("MOVE_AWAY_INSIDE")

        observation = BoundaryObservation(
            index=sample.index,
            source_ordinal=sample.source_ordinal,
            close_location=close_location,
            touched=touched,
            events=tuple(events),
            inside_excursion=inside_excursion,
            outside_excursion=outside_excursion,
        )
        encounter.append(observation)

        if (close_location == "OUTSIDE"
                and encounter._consecutive_outside >= BREAK_CLOSES):
            encounter.persistent_outside_index = sample.index
            self._finish_boundary_encounter(
                encounter, sample.index, "PERSISTENT_OUTSIDE")
            return
        if (encounter.first_reclaim_index is not None
                and sample.index > encounter.first_reclaim_index
                and close_location != "OUTSIDE"):
            encounter.remained_inside_after_reclaim_index = sample.index
            if close_location == "INSIDE":
                self._finish_boundary_encounter(
                    encounter, sample.index, "RECLAIM_REMAINED_INSIDE")
            return
        still_interacting = _boundary_interacts(
            sample, origin.structure_id,
            side=origin.side, edge=origin.edge_price, previous=self._last_sample)
        if (is_later and not had_outside and close_location == "INSIDE"
                and not still_interacting):
            self._finish_boundary_encounter(
                encounter, sample.index, "MOVED_INSIDE")

    def _finish_boundary_encounter(self, encounter: BoundaryEncounter,
                                   index: int, reason: str) -> None:
        if encounter.end_reason is not None:
            return
        encounter.end_index = index
        encounter.end_reason = reason
        key = (encounter.origin.boundary_kind, encounter.origin.side)
        if self._active_boundary_encounters.get(key) is encounter:
            del self._active_boundary_encounters[key]

    def _observe_nulls(self, structure: StructureEpisode, sample: CausalSample) -> None:
        self._complete_pending_nulls(sample)
        low = structure.origin.low
        width = structure.origin.width
        levels = (
            ("LOWER_INTERIOR_QUARTER", LOWER, low + width / Decimal(4)),
            ("MIDPOINT", None, low + width / Decimal(2)),
            ("UPPER_INTERIOR_QUARTER", UPPER, low + width * Decimal(3) / Decimal(4)),
        )
        for label, side, level in levels:
            key = (structure.origin.structure_episode_id, label)
            near = sample.l - sample.tolerance <= level <= sample.h + sample.tolerance
            if near and self._null_armed[key]:
                if side == UPPER:
                    interior = sample.c <= level
                elif side == LOWER:
                    interior = sample.c >= level
                else:
                    interior = sample.c <= level
                self._pending_nulls.append(
                    (structure, label, side, sample.index, interior))
                self._null_armed[key] = False
            elif not near:
                self._null_armed[key] = True

    def _complete_pending_nulls(self, sample: CausalSample) -> None:
        keep = []
        for structure, label, side, index, first_interior in self._pending_nulls:
            if sample.index <= index:
                keep.append((structure, label, side, index, first_interior))
                continue
            low, high = structure.origin.low, structure.origin.high
            width = structure.origin.width
            level = {LOWER: low + width / Decimal(4),
                     UPPER: low + width * Decimal(3) / Decimal(4)}.get(
                         side, low + width / Decimal(2))
            if side == UPPER:
                next_interior = sample.c <= level
            elif side == LOWER:
                next_interior = sample.c >= level
            else:
                next_interior = sample.c <= level
            self.null_probes.append(NullProbe(
                structure.origin.structure_episode_id, label, side, index,
                first_interior, next_interior, low <= sample.c <= high))
        self._pending_nulls = keep

    def _update_releases(self, sample: CausalSample) -> None:
        for release_id, release in tuple(self._active_releases.items()):
            direction = release.origin.direction
            distance = ((sample.c - release.origin.broken_edge) if direction == "up"
                        else (release.origin.broken_edge - sample.c))
            state = "HELD" if distance > sample.tolerance else "GIVEBACK"
            release.append(ReleaseObservation(
                sample.index, sample.source_ordinal, state, distance))
            if state == "GIVEBACK":
                release.end_index = sample.index
                release.end_reason = "GIVEBACK"
                del self._active_releases[release_id]

    def _create_releases(self, sample: CausalSample) -> None:
        context = self._active_structure or self._last_context
        if context is None:
            return
        for position, fact in enumerate(sample.releases, start=1):
            side = UPPER if fact.direction == "up" else LOWER
            encounter = next((item for item in reversed(self.encounters)
                              if item.origin.structure_episode_id
                              == context.origin.structure_episode_id
                              and item.origin.side == side
                              and item.end_index == sample.index), None)
            episode_id = (f"{sample.source_episode_id}:{fact.release_id}:"
                          f"{sample.index}:{position}")
            origin = ReleaseOrigin(
                bucket=sample.bucket,
                source_episode_id=sample.source_episode_id,
                release_episode_id=episode_id,
                release_id=fact.release_id,
                structure_episode_id=context.origin.structure_episode_id,
                encounter_id=encounter.origin.encounter_id if encounter else None,
                index=sample.index,
                source_ordinal=sample.source_ordinal,
                scale=fact.scale,
                origin=fact.origin,
                broken_structure_id=fact.broken_id,
                broken_edge=fact.broken_edge,
                broken_low=fact.broken_low,
                broken_high=fact.broken_high,
                broken_kind=fact.broken_kind,
                direction=fact.direction,
                parent_id=fact.parent_id,
                price=fact.price,
                beyond=fact.beyond,
                beyond_atr=fact.beyond_atr,
                location=fact.location,
                route_references=fact.route_references,
            )
            episode = ReleaseEpisode(origin)
            self.releases.append(episode)
            self._active_releases[episode_id] = episode


@dataclass(frozen=True, slots=True)
class StudyConfig:
    history: int = 400


def _micro_context(frame: structural_frame.StructuralFrame) -> MicroContext:
    view = frame.reading.micro
    if view is None:
        return MicroContext("ABSENT")
    events = tuple(view.events)
    state = view.micro_state or "ABSENT"
    for event in ("MICRO_BREAK_UP", "MICRO_BREAK_DOWN", "MICRO_COLLAPSED",
                  "MICRO_CREATED"):
        if event in events:
            state = event.removeprefix("MICRO_")
            break
    return MicroContext(state, view.micro_id, view.micro_low, view.micro_high, events)


def _local_context(frame: structural_frame.StructuralFrame) -> LocalContext:
    local = frame.local
    if local is None:
        return LocalContext(False)
    micro = frame.reading.micro
    relation = "NO_PRODUCTION_MICRO"
    if micro is not None and micro.micro_low is not None and micro.micro_high is not None:
        if local.low <= micro.micro_low and micro.micro_high <= local.high:
            relation = "CONTAINS_MICRO"
        elif micro.micro_low <= local.low and local.high <= micro.micro_high:
            relation = "INSIDE_MICRO"
        else:
            relation = "DISTINCT_FROM_MICRO"
    return LocalContext(True, local.kind, local.low, local.high, local.holder_id, relation)


def _reference_fact(reference) -> ReferenceFact | None:
    if reference is None:
        return None
    return ReferenceFact(reference.label, reference.price, reference.role)


def sample_from_frame(frame: structural_frame.StructuralFrame, candle: Candle, *,
                      bucket: str, source_episode_id: str,
                      source_ordinal: int, tolerance: Decimal,
                      birth_index: int | None = None) -> CausalSample:
    current = frame.map.current
    structure = None if current is None else StructureFact(
        current.id, current.kind, current.low, current.high, current.parent_id,
        frame.thesis.price_location, birth_index)
    identity = thesis_mod.identity_of(frame.thesis)
    releases = tuple(ReleaseFact(
        item.id, item.scale, item.origin, item.broken_id, item.broken_edge,
        item.broken_low, item.broken_high, item.broken_kind, item.direction,
        item.parent_id, item.price, item.beyond, item.beyond_atr, item.location,
        tuple(corridor_item.line() for corridor_item in item.corridor),
    ) for item in frame.release.releases)
    return CausalSample(
        bucket=bucket,
        source_episode_id=source_episode_id,
        source_ordinal=source_ordinal,
        index=frame.index,
        at=frame.at,
        o=candle.o,
        h=candle.h,
        l=candle.l,
        c=candle.c,
        atr=frame.map.atr,
        tolerance=tolerance,
        frontier_state=frame.reading.state,
        interaction=frame.reading.interaction,
        current=structure,
        left_id=frame.left_id,
        micro=_micro_context(frame),
        local=_local_context(frame),
        next_above=_reference_fact(frame.references.up.immediate),
        next_below=_reference_fact(frame.references.down.immediate),
        thesis_identity=str(identity) if identity is not None else None,
        thesis_invalidation=frame.broader_thesis_invalidation,
        releases=releases,
    )


def run_episode(episode: ResearchEpisode, config: StudyConfig) -> ResponseObserver | None:
    candles = episode.candles
    if len(candles) <= config.history:
        return None
    history = candles[:config.history]
    live = candles[config.history:]
    snapshot = build_snapshot(history, SYMBOL)
    frontier = Frontier(snapshot, history)
    locals_by_index: dict[int, structural_frame.LocalStructure] = {}
    birth_by_index: dict[int, int] = {}
    for candle in live:
        reading = frontier.on_candle(candle)
        if frontier.current is not None and reading.node_id == frontier.current.id:
            birth_by_index[reading.index] = frontier.current.start
        candidates = observational_local_candidates(frontier, reading)
        if candidates:
            proposal = min(candidates, key=lambda item: (item.high - item.low, item.kind))
            locals_by_index[reading.index] = structural_frame.LocalStructure(
                id=f"OBS_LOCAL_{reading.index}_{proposal.kind}",
                kind=proposal.kind,
                low=proposal.low,
                high=proposal.high,
                holder_id=reading.node_id,
            )
    frames = structural_frame.observe(snapshot, frontier, locals_by_index=locals_by_index)
    ordinal_by_day = {item.day: item.source_ordinal for item in episode.sessions}
    source_episode_id = f"{episode.bucket}-EP{episode.ordinal:03d}"
    observer = ResponseObserver(episode.bucket, source_episode_id)
    for frame in frames:
        candle = frontier.candles[frame.index]
        if candle.session_date not in ordinal_by_day:
            raise AssertionError("frame crossed its source episode barrier")
        sample = sample_from_frame(
            frame, candle,
            bucket=episode.bucket,
            source_episode_id=source_episode_id,
            source_ordinal=ordinal_by_day[candle.session_date],
            tolerance=tol_at(frontier.candles, frame.index, frontier.tol_atr),
            birth_index=birth_by_index.get(frame.index),
        )
        observer.observe(sample)
    observer.finish()
    return observer


def _distribution(values: Iterable[int | float | Decimal]) -> dict:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(numbers),
        "min": round(min(numbers), 6),
        "median": round(statistics.median(numbers), 6),
        "mean": round(statistics.fmean(numbers), 6),
        "max": round(max(numbers), 6),
    }


def _sequence_counts(encounters: Sequence[EdgeEncounter]) -> tuple[dict, dict]:
    names = (
        "touch_close_inside_next_inside",
        "touch_outside_close_accepted_break",
        "outside_close_reclaim",
        "reclaim_retest_remain_inside",
        "lower_encounter_midpoint_upper_encounter",
    )
    counts = Counter({name: 0 for name in names})
    transitions: dict[str, Counter] = {name: Counter() for name in names}
    by_structure: dict[str, list[EdgeEncounter]] = defaultdict(list)
    for encounter in encounters:
        by_structure[encounter.origin.structure_episode_id].append(encounter)
        events = {event for observation in encounter.observations for event in observation.events}
        first = encounter.observations[0] if encounter.observations else None
        if (first and f"TOUCH_{encounter.origin.side.upper()}" in first.events
                and f"CLOSE_INSIDE_AFTER_{encounter.origin.side.upper()}_TEST" in first.events
                and encounter.next_closed_candle_location in {"INSIDE", "AT"}):
            counts[names[0]] += 1
            transitions[names[0]][encounter.end_reason or "UNRESOLVED"] += 1
        if (f"TOUCH_{encounter.origin.side.upper()}" in events
                and f"CLOSE_OUTSIDE_{encounter.origin.side.upper()}" in events
                and encounter.first_accepted_break_index is not None):
            counts[names[1]] += 1
            transitions[names[1]][encounter.end_reason or "UNRESOLVED"] += 1
        if (f"CLOSE_OUTSIDE_{encounter.origin.side.upper()}" in events
                and encounter.first_reclaim_index is not None):
            counts[names[2]] += 1
            transitions[names[2]][encounter.end_reason or "UNRESOLVED"] += 1
        if (encounter.first_reclaim_index is not None
                and encounter.first_return_retest_index is not None
                and "HOLD_INSIDE_AFTER_RECLAIM" in events):
            counts[names[3]] += 1
            transitions[names[3]][encounter.end_reason or "UNRESOLVED"] += 1
    for sequence in by_structure.values():
        sequence.sort(key=lambda item: item.origin.start_index)
        for pos, lower in enumerate(sequence):
            if lower.origin.side != LOWER or lower.midpoint_reached_index is None:
                continue
            upper = next((item for item in sequence[pos + 1:]
                          if item.origin.side == UPPER
                          and item.origin.start_index >= lower.midpoint_reached_index), None)
            if upper is not None:
                counts[names[4]] += 1
                transitions[names[4]][upper.end_reason or "UNRESOLVED"] += 1
    return dict(counts), {
        name: dict(sorted(counter.items())) for name, counter in transitions.items()
    }


BOUNDARY_METRICS = (
    "next_close_inside",
    "outside_close",
    "reclaim_after_outside",
    "retest_after_reclaim",
    "remain_inside_after_reclaim",
    "persistent_outside",
    "move_away_inside",
)


def _fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": (round(numerator / denominator, 6) if denominator else None),
    }


def _boundary_metric(rows: Sequence[BoundaryEncounter], metric: str) -> tuple[int, int]:
    if metric == "next_close_inside":
        eligible = [item for item in rows if item.next_closed_candle_location is not None]
        return (sum(item.next_closed_candle_location in {"INSIDE", "AT"}
                    for item in eligible), len(eligible))
    if metric == "outside_close":
        return (sum(item.first_outside_close_index is not None for item in rows), len(rows))
    if metric == "reclaim_after_outside":
        eligible = [item for item in rows if item.first_outside_close_index is not None]
        return (sum(item.first_reclaim_index is not None for item in eligible), len(eligible))
    if metric == "retest_after_reclaim":
        eligible = [item for item in rows if item.first_reclaim_index is not None]
        return (sum(item.first_return_retest_index is not None for item in eligible),
                len(eligible))
    if metric == "remain_inside_after_reclaim":
        eligible = [item for item in rows if item.first_reclaim_index is not None]
        return (sum(item.remained_inside_after_reclaim_index is not None
                    for item in eligible), len(eligible))
    if metric == "persistent_outside":
        eligible = [item for item in rows if item.first_outside_close_index is not None]
        return (sum(item.persistent_outside_index is not None for item in eligible),
                len(eligible))
    if metric == "move_away_inside":
        eligible = [item for item in rows if item.next_closed_candle_location is not None]
        return (sum(item.first_move_away_index is not None for item in eligible),
                len(eligible))
    raise KeyError(metric)


def _boundary_rates(rows: Sequence[BoundaryEncounter]) -> dict:
    return {
        metric: _fraction(*_boundary_metric(rows, metric))
        for metric in BOUNDARY_METRICS
    }


def _comparison_rate(real_rows: Sequence[BoundaryEncounter],
                     ghost_rows: Sequence[BoundaryEncounter]) -> dict:
    out = {}
    for metric in BOUNDARY_METRICS:
        real = _fraction(*_boundary_metric(real_rows, metric))
        ghost = _fraction(*_boundary_metric(ghost_rows, metric))
        difference = (None if real["rate"] is None or ghost["rate"] is None
                      else round(real["rate"] - ghost["rate"], 6))
        out[metric] = {"real": real, "ghost": ghost,
                       "real_minus_ghost": difference}
    return out


def _boundary_population(rows: Sequence[BoundaryEncounter]) -> dict:
    return {
        "encounters": len(rows),
        "upper": sum(item.origin.side == UPPER for item in rows),
        "lower": sum(item.origin.side == LOWER for item in rows),
        "from_inside": sum(item.origin.origin_class == FROM_INSIDE for item in rows),
        "from_outside": sum(item.origin.origin_class == FROM_OUTSIDE for item in rows),
        "already_at_edge": sum(item.origin.origin_class == ALREADY_AT_EDGE for item in rows),
        "unknown_origin": sum(item.origin.origin_class == UNKNOWN_ORIGIN for item in rows),
        "first_encounters": sum(item.origin.encounter_order == FIRST_ENCOUNTER
                                for item in rows),
        "repeat_encounters": sum(item.origin.encounter_order == REPEAT_ENCOUNTER
                                 for item in rows),
        "width_points": _distribution(item.origin.structure_width for item in rows),
        "atr": _distribution(item.origin.atr for item in rows),
        "max_inside_excursion_points": _distribution(
            item.max_inside_excursion for item in rows),
        "max_outside_excursion_points": _distribution(
            item.max_outside_excursion for item in rows),
        "max_inside_excursion_atr": _distribution(
            item.max_inside_excursion / item.origin.atr
            for item in rows if item.origin.atr > 0),
        "max_outside_excursion_atr": _distribution(
            item.max_outside_excursion / item.origin.atr
            for item in rows if item.origin.atr > 0),
        "bars_inside": _distribution(item.bars_inside for item in rows),
        "bars_outside": _distribution(item.bars_outside for item in rows),
        "micro_states": dict(sorted(Counter(
            item.origin.micro.state for item in rows).items())),
        "end_reasons": dict(sorted(Counter(
            item.end_reason or "UNRESOLVED" for item in rows).items())),
    }


def _episode_comparison_spread(observers: Sequence[ResponseObserver], *,
                               structure_kind: str) -> dict:
    output = {}
    for metric in BOUNDARY_METRICS:
        real_rates: list[float] = []
        ghost_rates: list[float] = []
        differences: list[float] = []
        real_numerators: list[int] = []
        ghost_numerators: list[int] = []
        for observer in observers:
            rows = [item for item in observer.boundary_encounters
                    if item.origin.structure_kind == structure_kind]
            real_pair = _boundary_metric(
                [item for item in rows if item.origin.boundary_kind == REAL], metric)
            ghost_pair = _boundary_metric(
                [item for item in rows if item.origin.boundary_kind == GHOST], metric)
            real_numerators.append(real_pair[0])
            ghost_numerators.append(ghost_pair[0])
            if real_pair[1]:
                real_rates.append(real_pair[0] / real_pair[1])
            if ghost_pair[1]:
                ghost_rates.append(ghost_pair[0] / ghost_pair[1])
            if real_pair[1] and ghost_pair[1]:
                differences.append(
                    real_pair[0] / real_pair[1] - ghost_pair[0] / ghost_pair[1])
        real_total = sum(real_numerators)
        ghost_total = sum(ghost_numerators)
        output[metric] = {
            "real_source_episode_rates": _distribution(real_rates),
            "ghost_source_episode_rates": _distribution(ghost_rates),
            "real_minus_ghost_source_episode_rates": _distribution(differences),
            "largest_real_episode_numerator_share": (
                round(max(real_numerators, default=0) / real_total, 6)
                if real_total else None),
            "largest_ghost_episode_numerator_share": (
                round(max(ghost_numerators, default=0) / ghost_total, 6)
                if ghost_total else None),
        }
    return output


def _aggregate_boundary_comparison(observers: Sequence[ResponseObserver]) -> dict:
    all_rows = [item for observer in observers for item in observer.boundary_encounters]
    by_kind = {}
    for structure_kind in ("cluster", "range"):
        kind_rows = [item for item in all_rows
                     if item.origin.structure_kind == structure_kind]
        real_rows = [item for item in kind_rows if item.origin.boundary_kind == REAL]
        ghost_rows = [item for item in kind_rows if item.origin.boundary_kind == GHOST]
        strata = []
        for side in SIDES:
            for origin_class in ORIGIN_CLASSES:
                for encounter_order in (FIRST_ENCOUNTER, REPEAT_ENCOUNTER):
                    selected = [item for item in kind_rows
                                if item.origin.side == side
                                and item.origin.origin_class == origin_class
                                and item.origin.encounter_order == encounter_order]
                    if not selected:
                        continue
                    strata.append({
                        "side": side,
                        "origin_class": origin_class,
                        "encounter_order": encounter_order,
                        "primary_origin_stratum": origin_class in {
                            FROM_INSIDE, FROM_OUTSIDE},
                        "real_encounters": sum(
                            item.origin.boundary_kind == REAL for item in selected),
                        "ghost_encounters": sum(
                            item.origin.boundary_kind == GHOST for item in selected),
                        "metrics": _comparison_rate(
                            [item for item in selected if item.origin.boundary_kind == REAL],
                            [item for item in selected if item.origin.boundary_kind == GHOST]),
                    })
        micro = {}
        for state in sorted({item.origin.micro.state for item in kind_rows}):
            selected = [item for item in kind_rows if item.origin.micro.state == state]
            micro[state] = {
                "real_encounters": sum(
                    item.origin.boundary_kind == REAL for item in selected),
                "ghost_encounters": sum(
                    item.origin.boundary_kind == GHOST for item in selected),
                "metrics": _comparison_rate(
                    [item for item in selected if item.origin.boundary_kind == REAL],
                    [item for item in selected if item.origin.boundary_kind == GHOST]),
            }
        origin_classes = {}
        for origin_class in ORIGIN_CLASSES:
            selected = [item for item in kind_rows
                        if item.origin.origin_class == origin_class]
            origin_classes[origin_class] = {
                "real_encounters": sum(
                    item.origin.boundary_kind == REAL for item in selected),
                "ghost_encounters": sum(
                    item.origin.boundary_kind == GHOST for item in selected),
                "metrics": _comparison_rate(
                    [item for item in selected if item.origin.boundary_kind == REAL],
                    [item for item in selected if item.origin.boundary_kind == GHOST]),
            }
        by_kind[structure_kind] = {
            "population": {
                REAL: _boundary_population(real_rows),
                GHOST: _boundary_population(ghost_rows),
            },
            "overall_metrics": _comparison_rate(real_rows, ghost_rows),
            "matched_strata": strata,
            "origin_classes": origin_classes,
            "micro_states": micro,
            "source_episode_spread": _episode_comparison_spread(
                observers, structure_kind=structure_kind),
        }
    return by_kind


SEQUENCE_V2_NAMES = (
    "touch_close_inside_next_inside",
    "outside_close_reclaim",
    "reclaim_retest_remain_inside",
    "lower_encounter_midpoint_later_upper_encounter",
)


def _sequence_v2_pairs(encounters: Sequence[EdgeEncounter]) -> dict[str, tuple[int, int]]:
    pairs: dict[str, tuple[int, int]] = {}
    touch_eligible = []
    outside_eligible = []
    reclaim_eligible = []
    by_structure: dict[str, list[EdgeEncounter]] = defaultdict(list)
    for encounter in encounters:
        by_structure[encounter.origin.structure_episode_id].append(encounter)
        first = encounter.observations[0] if encounter.observations else None
        first_events = set(first.events) if first is not None else set()
        if (first is not None
                and f"TOUCH_{encounter.origin.side.upper()}" in first_events
                and first.close_location != "OUTSIDE"
                and encounter.next_closed_candle_location is not None):
            touch_eligible.append(encounter)
        if any(item.close_location == "OUTSIDE" for item in encounter.observations):
            outside_eligible.append(encounter)
        if encounter.first_reclaim_index is not None:
            reclaim_eligible.append(encounter)
    pairs[SEQUENCE_V2_NAMES[0]] = (
        sum(item.next_closed_candle_location in {"INSIDE", "AT"}
            for item in touch_eligible), len(touch_eligible))
    pairs[SEQUENCE_V2_NAMES[1]] = (
        sum(item.first_reclaim_index is not None for item in outside_eligible),
        len(outside_eligible))
    pairs[SEQUENCE_V2_NAMES[2]] = (
        sum(item.first_return_retest_index is not None
            and any("HOLD_INSIDE_AFTER_RECLAIM" in observation.events
                    for observation in item.observations)
            for item in reclaim_eligible), len(reclaim_eligible))
    lower_denominator = 0
    lower_numerator = 0
    for sequence in by_structure.values():
        sequence.sort(key=lambda item: item.origin.start_index)
        for pos, lower in enumerate(sequence):
            if lower.origin.side != LOWER or lower.midpoint_reached_index is None:
                continue
            lower_denominator += 1
            if any(item.origin.side == UPPER
                   and item.origin.start_index > lower.midpoint_reached_index
                   for item in sequence[pos + 1:]):
                lower_numerator += 1
    pairs[SEQUENCE_V2_NAMES[3]] = (lower_numerator, lower_denominator)
    return pairs


def _aggregate_sequence_rates_v2(observers: Sequence[ResponseObserver]) -> dict:
    episode_pairs = [_sequence_v2_pairs(observer.encounters) for observer in observers]
    output = {}
    for name in SEQUENCE_V2_NAMES:
        numerator = sum(item[name][0] for item in episode_pairs)
        denominator = sum(item[name][1] for item in episode_pairs)
        rates = [item[name][0] / item[name][1]
                 for item in episode_pairs if item[name][1]]
        output[name] = {
            **_fraction(numerator, denominator),
            "source_episode_rate_spread": _distribution(rates),
            "source_episodes_with_denominator": len(rates),
            "largest_episode_numerator_share": (
                round(max((item[name][0] for item in episode_pairs), default=0)
                      / numerator, 6) if numerator else None),
        }
    return output


def aggregate(observers: Sequence[ResponseObserver]) -> dict:
    structures = [item for observer in observers for item in observer.structures]
    encounters = [item for observer in observers for item in observer.encounters]
    releases = [item for observer in observers for item in observer.releases]
    nulls = [item for observer in observers for item in observer.null_probes]
    structure_counts = Counter(item.origin.kind for item in structures)
    end_counts = Counter(item.end_reason or "UNRESOLVED" for item in structures)
    sequence_counts, transitions = _sequence_counts(encounters)

    edge: dict[str, dict] = {}
    for side in SIDES:
        rows = [item for item in encounters if item.origin.side == side]
        edge[side] = {
            "encounters": len(rows),
            "touches": sum(item.first_touch_index is not None for item in rows),
            "origin_close_inside": sum(bool(item.observations)
                                       and item.observations[0].close_location in {"INSIDE", "AT"}
                                       for item in rows),
            "origin_close_at": sum(bool(item.observations)
                                   and item.observations[0].close_location == "AT"
                                   for item in rows),
            "origin_close_outside": sum(bool(item.observations)
                                        and item.observations[0].close_location == "OUTSIDE"
                                        for item in rows),
            "next_close_inside_or_at": sum(item.next_closed_candle_location in {"INSIDE", "AT"}
                                           for item in rows),
            "accepted_breaks": sum(item.first_accepted_break_index is not None for item in rows),
            "reclaims": sum(item.first_reclaim_index is not None for item in rows),
            "retests": sum(item.first_return_retest_index is not None for item in rows),
            "midpoint_reaches": sum(item.midpoint_reached_index is not None for item in rows),
            "opposite_edge_reaches": sum(item.opposite_edge_reached_index is not None
                                         for item in rows),
            "outward_reference_reaches": sum(
                item.outward_reference_reached_index is not None for item in rows),
            "inward_reference_reaches": sum(
                item.inward_reference_reached_index is not None for item in rows),
            "repeated_encounters": sum(item.origin.ordinal_for_edge > 1 for item in rows),
            "bars_inside": _distribution(item.bars_inside for item in rows),
            "bars_outside": _distribution(item.bars_outside for item in rows),
            "max_inside_excursion_points": _distribution(
                item.max_inside_excursion for item in rows),
            "max_outside_excursion_points": _distribution(
                item.max_outside_excursion for item in rows),
            "end_reasons": dict(sorted(Counter(
                item.end_reason or "UNRESOLVED" for item in rows).items())),
        }

    micro: dict[str, dict] = {}
    for state in sorted({item.origin.micro.state for item in encounters}):
        rows = [item for item in encounters if item.origin.micro.state == state]
        micro[state] = {
            "encounters": len(rows),
            "accepted_breaks": sum(item.first_accepted_break_index is not None for item in rows),
            "reclaims": sum(item.first_reclaim_index is not None for item in rows),
            "midpoint_reaches": sum(item.midpoint_reached_index is not None for item in rows),
        }
    local = {
        "present": sum(item.origin.local.present for item in encounters),
        "absent": sum(not item.origin.local.present for item in encounters),
        "relations_to_micro": dict(sorted(Counter(
            item.origin.local.relation_to_micro for item in encounters
            if item.origin.local.present).items())),
    }
    release_counts = Counter(item.origin.scale for item in releases)
    simultaneous = Counter((item.origin.index, item.origin.source_episode_id)
                           for item in releases)
    null_summary = {}
    for label in ("LOWER_INTERIOR_QUARTER", "MIDPOINT", "UPPER_INTERIOR_QUARTER"):
        rows = [item for item in nulls if item.label == label]
        null_summary[label] = {
            "encounters": len(rows),
            "origin_close_on_interior_side": sum(item.close_on_interior_side for item in rows),
            "next_close_on_interior_side": sum(item.next_close_on_interior_side for item in rows),
            "next_close_inside_structure": sum(item.next_close_inside_structure for item in rows),
        }
    return {
        "structure_population": {
            "episodes": len(structures),
            "kinds": dict(sorted(structure_counts.items())),
            "visits": sum(item.visits for item in structures),
            "revisit_episodes": sum(
                item.origin.originating_interaction == "REVISIT" for item in structures),
            "revisit_observations": sum(item.revisits for item in structures),
            "leaving_observations": sum(item.leaving for item in structures),
            "reentries": sum(item.reentries for item in structures),
            "accepted_breaks": sum(item.accepted_break is not None for item in structures),
            "finalisations": sum(item.finalised for item in structures),
            "opposite_edge_traversals": sum(
                item.opposite_edge_reached_index is not None for item in encounters),
            "lifetime_bars": _distribution(item.bars_alive for item in structures),
            "current_bars": _distribution(item.bars_current for item in structures),
            "inside_bars": _distribution(item.bars_price_inside for item in structures),
            "end_reasons": dict(sorted(end_counts.items())),
        },
        "edge_encounter_population": edge,
        "release_subpopulation": {
            "episodes": len(releases),
            "scales": dict(sorted(release_counts.items())),
            "linked_to_encounter": sum(item.origin.encounter_id is not None for item in releases),
            "simultaneous_release_candles": sum(count > 1 for count in simultaneous.values()),
            "simultaneous_releases_preserved": sum(
                count for count in simultaneous.values() if count > 1),
            "givebacks": sum(item.giveback_index is not None for item in releases),
            "held_bars": _distribution(item.bars_held for item in releases),
            "end_reasons": dict(sorted(Counter(
                item.end_reason or "UNRESOLVED" for item in releases).items())),
        },
        "micro_context": micro,
        "local_research_sidecar": local,
        "sequence_counts": sequence_counts,
        "sequence_subsequent_transitions": transitions,
        "sequence_rates_v2": _aggregate_sequence_rates_v2(observers),
        "boundary_comparison_v2": _aggregate_boundary_comparison(observers),
        "null_comparisons": null_summary,
    }


def _r3_v2_comparison(by_bucket: dict[str, dict]) -> dict:
    output = {}
    for name in SEQUENCE_V2_NAMES:
        teach = by_bucket[TEACH]["sequence_rates_v2"][name]
        validate = by_bucket[VALIDATE]["sequence_rates_v2"][name]
        absolute_difference = (
            None if teach["rate"] is None or validate["rate"] is None
            else round(abs(teach["rate"] - validate["rate"]), 6))
        output[name] = {
            "teach": teach,
            "validate_aggregate": validate,
            "absolute_rate_difference": absolute_difference,
        }
    return output


def _sign(value: float | None) -> int | None:
    if value is None:
        return None
    return (value > 0) - (value < 0)


def _r2_kind_decision(by_bucket: dict[str, dict], structure_kind: str) -> dict:
    teach = by_bucket[TEACH]["boundary_comparison_v2"][structure_kind]
    validate = by_bucket[VALIDATE]["boundary_comparison_v2"][structure_kind]
    validate_real = validate["population"][REAL]["encounters"]
    validate_ghost = validate["population"][GHOST]["encounters"]
    if not validate_real or not validate_ghost:
        return {
            "answer": "INSUFFICIENT_POPULATION",
            "basis": "VALIDATE has no matched real/ghost boundary population for this structure kind",
            "overall_directional_repetition": {},
            "matched_primary_strata": {
                "comparable": 0, "same_direction": 0,
                "opposite_direction": 0, "zero_difference": 0},
        }

    directional = {}
    for metric in BOUNDARY_METRICS:
        teach_difference = teach["overall_metrics"][metric]["real_minus_ghost"]
        validate_difference = validate["overall_metrics"][metric]["real_minus_ghost"]
        directional[metric] = {
            "teach_real_minus_ghost": teach_difference,
            "validate_real_minus_ghost": validate_difference,
            "same_direction": (_sign(teach_difference) is not None
                               and _sign(teach_difference) == _sign(validate_difference)),
        }

    validate_strata = {
        (item["side"], item["origin_class"], item["encounter_order"]): item
        for item in validate["matched_strata"] if item["primary_origin_stratum"]
    }
    stratum_summary = Counter({
        "comparable": 0, "same_direction": 0,
        "opposite_direction": 0, "zero_difference": 0})
    for teach_item in teach["matched_strata"]:
        if not teach_item["primary_origin_stratum"]:
            continue
        key = (teach_item["side"], teach_item["origin_class"],
               teach_item["encounter_order"])
        validate_item = validate_strata.get(key)
        if validate_item is None:
            continue
        for metric in BOUNDARY_METRICS:
            left = teach_item["metrics"][metric]["real_minus_ghost"]
            right = validate_item["metrics"][metric]["real_minus_ghost"]
            if left is None or right is None:
                continue
            stratum_summary["comparable"] += 1
            if left == 0 or right == 0:
                stratum_summary["zero_difference"] += 1
            elif _sign(left) == _sign(right):
                stratum_summary["same_direction"] += 1
            else:
                stratum_summary["opposite_direction"] += 1

    all_zero = all(
        item["teach_real_minus_ghost"] == 0
        and item["validate_real_minus_ghost"] == 0
        for item in directional.values())
    if all_zero:
        answer = "NO"
        basis = "all reported aggregate real-minus-ghost rate differences are zero"
    else:
        answer = "INCONCLUSIVE"
        basis = (
            "V2 reports untuned rate differences and source-episode spread, but no "
            "preregistered materiality threshold supports a binary YES; matched origin "
            "strata must be read for directional consistency")
    return {
        "answer": answer,
        "basis": basis,
        "overall_directional_repetition": directional,
        "matched_primary_strata": dict(stratum_summary),
    }


def _gate_results(by_bucket: dict[str, dict], r3_v2: dict) -> dict:
    enough_structure = all(
        by_bucket[bucket]["structure_population"]["episodes"] > 0
        and sum(side["encounters"] for side in
                by_bucket[bucket]["edge_encounter_population"].values()) > 0
        for bucket in (TEACH, VALIDATE))
    r2_cluster = _r2_kind_decision(by_bucket, "cluster")
    r2_range = _r2_kind_decision(by_bucket, "range")
    repeated_families = sum(
        item["teach"]["denominator"] > 0
        and item["validate_aggregate"]["denominator"] > 0
        for item in r3_v2.values())
    ready = r2_cluster["answer"] == "YES" and repeated_families == len(SEQUENCE_V2_NAMES)
    return {
        "STRUCTURAL_LIFECYCLE_OBSERVED": {
            "answer": "YES" if enough_structure else "NO",
            "basis": "descriptive natural-lifecycle structures and encounters exist in both buckets",
        },
        "R2_CLUSTER_EDGE_RESPONSE": r2_cluster,
        "R2_RANGE_EDGE_RESPONSE": r2_range,
        "R3_REPEATABILITY_V2": {
            "answer": "RATES_REPORTED_WITHOUT_BINARY_THRESHOLD",
            "basis": (f"numerator/denominator rates and source-episode spreads are "
                      f"reported for {repeated_families} comparable families; the weak "
                      "shared-nonzero gate is retired"),
        },
        "R4_MICRO": {
            "answer": "INCONCLUSIVE",
            "basis": "real-minus-ghost Micro strata are descriptive and mechanically coupled populations remain possible",
        },
        "READY_FOR_CLUSTER_HYPOTHESIS_BRAIN": {
            "answer": "YES" if ready else "NO",
            "basis": ("cluster R2 and all V2 sequence denominators are supported"
                      if ready else "cluster R2 is not certified YES under V2"),
        },
        "LOCAL_PUBLICATION": {
            "answer": "NO",
            "basis": "LOCAL remains an optional research sidecar",
        },
    }


def run_study(config: StudyConfig | None = None) -> dict:
    config = config or StudyConfig()
    episodes_by_bucket, source_population = load_research_episodes()
    observers_by_bucket: dict[str, list[ResponseObserver]] = {TEACH: [], VALIDATE: []}
    consumption = {}
    for bucket in (TEACH, VALIDATE):
        skipped = 0
        observed_candles = 0
        for episode in episodes_by_bucket[bucket]:
            observer = run_episode(episode, config)
            if observer is None:
                skipped += 1
            else:
                observers_by_bucket[bucket].append(observer)
                observed_candles += len(episode.candles) - config.history
        consumption[bucket] = {
            "source_episodes_available": len(episodes_by_bucket[bucket]),
            "source_episodes_processed": len(observers_by_bucket[bucket]),
            "source_episodes_shorter_than_or_equal_to_history": skipped,
            "history_candles_consumed": config.history * len(observers_by_bucket[bucket]),
            "live_candles_observed": observed_candles,
        }
    by_bucket = {bucket: aggregate(observers_by_bucket[bucket])
                 for bucket in (TEACH, VALIDATE)}
    r3_v2 = _r3_v2_comparison(by_bucket)
    deterministic = {
        "study": "TOPOLOGICALLY_EQUIVALENT_GHOST_BOUNDARY_V2",
        "v1_evidence": {
            "fingerprint": "7d373af2a9e1389e",
            "report": "reports/STRUCTURAL_RESPONSE_AUDIT_V1.md",
            "aggregate": "reports/structural_response_summary_v1.json",
            "status": "PRESERVED_UNCHANGED",
        },
        "config": asdict(config),
        "source_population": source_population,
        "consumption": consumption,
        "buckets": by_bucket,
        "r3_repeatability_v2": r3_v2,
        "validate_output": "AGGREGATE_ONLY",
        "origin_policy": "FROZEN_AT_CAUSAL_CANDLE_FUTURE_APPEND_ONLY",
        "primary_horizon": "NATURAL_STRUCTURAL_LIFECYCLE",
        "fixed_horizon_role": "SECONDARY_SEQUENCE_AND_OCCUPANCY_DESCRIPTION_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "local_published": False,
    }
    fingerprint_source = json.dumps(deterministic, sort_keys=True, default=_json_default)
    deterministic["fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8")).hexdigest()[:16]
    deterministic["decision_gates"] = _gate_results(by_bucket, r3_v2)
    return deterministic


def _count_line(item: dict, keys: Sequence[str]) -> str:
    return " | ".join(f"{key.replace('_', ' ')} {item.get(key, 0)}" for key in keys)


def _rate_text(item: dict) -> str:
    rate = "none" if item["rate"] is None else f"{item['rate']:.4f}"
    return f"{item['numerator']}/{item['denominator']} = {rate}"


def render_report(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    lines = [
        "# Structural Response Audit V2",
        "",
        "Status: EXECUTED. Research-only real-edge versus topologically equivalent ghost-boundary comparison.",
        "",
        f"Fingerprint: `{payload['fingerprint']}`",
        "",
        "## V1 EVIDENCE",
        "",
        f"The reviewed V1 result is preserved unchanged at `{payload['v1_evidence']['report']}` and `{payload['v1_evidence']['aggregate']}` with fingerprint `{payload['v1_evidence']['fingerprint']}`. V1 presence gates are not reused as strong evidence.",
        "",
        "## SEMANTIC REPAIRS",
        "",
        "- Encounter location now comes from the encounter-origin candle.",
        "- Origin class is derived only from a prior same-structure closed candle; no side-to-direction inference remains.",
        "- Wick/range contact and closed-candle side changes use one interaction rule for real and ghost boundaries.",
        "- Outward and inward mapped references remain separate.",
        "- Same-candle OHLC range never claims post-origin ordering.",
        "- Real and ghost comparisons share one boundary response state machine; the production accepted-break label is excluded from primary R2 metrics.",
        "",
        "## STRUCTURE POPULATION",
        "",
    ]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        pop = data["structure_population"]
        lines.append(
            f"- {label}: episodes/visits {pop['episodes']} | cluster {pop['kinds'].get('cluster', 0)} | range {pop['kinds'].get('range', 0)} | revisit episodes {pop['revisit_episodes']} | leaving observations {pop['leaving_observations']} | accepted breaks {pop['accepted_breaks']} | re-entries {pop['reentries']} | opposite-edge traversals {pop['opposite_edge_traversals']} | median life/current/inside {pop['lifetime_bars']['median']}/{pop['current_bars']['median']}/{pop['inside_bars']['median']} bars.")
    lines += ["", "## REAL EDGE POPULATION", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for kind in ("cluster", "range"):
            pop = data["boundary_comparison_v2"][kind]["population"][REAL]
            lines.append(
                f"- {label} {kind}: encounters {pop['encounters']} | upper {pop['upper']} | lower {pop['lower']} | from inside {pop['from_inside']} | from outside {pop['from_outside']} | first {pop['first_encounters']} | repeat {pop['repeat_encounters']}.")
    lines += ["", "## GHOST EDGE POPULATION", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for kind in ("cluster", "range"):
            pop = data["boundary_comparison_v2"][kind]["population"][GHOST]
            lines.append(
                f"- {label} {kind}: encounters {pop['encounters']} | upper {pop['upper']} | lower {pop['lower']} | from inside {pop['from_inside']} | from outside {pop['from_outside']} | first {pop['first_encounters']} | repeat {pop['repeat_encounters']}.")

    for kind, heading in (("cluster", "CLUSTER RESULTS"), ("range", "RANGE RESULTS")):
        lines += ["", f"## {heading}", ""]
        for metric in BOUNDARY_METRICS:
            t = teach["boundary_comparison_v2"][kind]["overall_metrics"][metric]
            v = validate["boundary_comparison_v2"][kind]["overall_metrics"][metric]
            lines.append(
                f"- `{metric}`: TEACH real {_rate_text(t['real'])}, ghost {_rate_text(t['ghost'])}, difference {t['real_minus_ghost']}; VALIDATE aggregate real {_rate_text(v['real'])}, ghost {_rate_text(v['ghost'])}, difference {v['real_minus_ghost']}.")
        if kind == "cluster":
            for metric in ("next_close_inside", "reclaim_after_outside",
                           "remain_inside_after_reclaim"):
                t_spread = teach["boundary_comparison_v2"][kind][
                    "source_episode_spread"][metric]
                v_spread = validate["boundary_comparison_v2"][kind][
                    "source_episode_spread"][metric]
                lines.append(
                    f"- `{metric}` source-episode audit: TEACH largest real numerator share {t_spread['largest_real_episode_numerator_share']} and real-minus-ghost spread {json.dumps(t_spread['real_minus_ghost_source_episode_rates'], sort_keys=True)}; VALIDATE aggregate largest real numerator share {v_spread['largest_real_episode_numerator_share']} and difference spread {json.dumps(v_spread['real_minus_ghost_source_episode_rates'], sort_keys=True)}.")

    lines += ["", "## FROM_INSIDE / FROM_OUTSIDE", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for origin_class in (FROM_INSIDE, FROM_OUTSIDE):
            facts = data["boundary_comparison_v2"]["cluster"][
                "origin_classes"][origin_class]
            next_inside = facts["metrics"]["next_close_inside"]
            reclaim = facts["metrics"]["reclaim_after_outside"]
            remain = facts["metrics"]["remain_inside_after_reclaim"]
            lines.append(
                f"- {label} cluster {origin_class}: real/ghost encounters {facts['real_encounters']}/{facts['ghost_encounters']} | next-inside real {_rate_text(next_inside['real'])}, ghost {_rate_text(next_inside['ghost'])}, difference {next_inside['real_minus_ghost']} | reclaim real {_rate_text(reclaim['real'])}, ghost {_rate_text(reclaim['ghost'])}, difference {reclaim['real_minus_ghost']} | remain-inside-after-reclaim difference {remain['real_minus_ghost']}. Side and first/repeat numerators and denominators remain separate in the aggregate.")

    lines += ["", "## R3 REPEATABILITY V2", ""]
    for name, item in payload["r3_repeatability_v2"].items():
        lines.append(
            f"- `{name}`: TEACH {_rate_text(item['teach'])}; VALIDATE aggregate {_rate_text(item['validate_aggregate'])}; absolute difference {item['absolute_rate_difference']}; TEACH source-episode spread {json.dumps(item['teach']['source_episode_rate_spread'], sort_keys=True)}; VALIDATE aggregate source-episode spread {json.dumps(item['validate_aggregate']['source_episode_rate_spread'], sort_keys=True)}.")

    lines += ["", "## MICRO CONTEXT", "",
              "Micro remains encounter-origin context. Real-minus-ghost metrics are reported by existing state in the machine aggregate; no directional label or decision field is created.", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        states = data["boundary_comparison_v2"]["cluster"]["micro_states"]
        compact = {state: {
            "real": facts["real_encounters"],
            "ghost": facts["ghost_encounters"],
            "next_inside_difference": facts["metrics"]["next_close_inside"][
                "real_minus_ghost"],
            "reclaim_difference": facts["metrics"]["reclaim_after_outside"][
                "real_minus_ghost"],
        } for state, facts in states.items()}
        lines.append(f"- {label}: `{json.dumps(compact, sort_keys=True)}`")

    lines += ["", "## SECONDARY V1 OCCUPANCY PROBES", ""]
    for label in teach["null_comparisons"]:
        t = teach["null_comparisons"][label]
        v = validate["null_comparisons"][label]
        lines.append(
            f"- {label}: TEACH {t['encounters']} encounters; VALIDATE aggregate {v['encounters']}. These are occupancy descriptions, not R2 nulls.")
    lines += ["", "## LIMITATIONS", "",
              "- No post-result materiality threshold is introduced; R2 cannot become YES from non-zero differences alone.",
              "- Encounter observations within a structure/source episode are correlated. Source-episode rate spreads and largest numerator shares are reported without treating encounters as independent.",
              "- VALIDATE contains aggregate distributions only and no timestamps, bands, absolute prices, identities, traces, or session-linked indices.",
              "- Range behavior cannot be certified when its VALIDATE boundary population is absent.",
              "- Natural source-episode boundaries right-censor still-live encounters.",
              "", "## DECISION GATES", ""]
    gate_order = (
        "STRUCTURAL_LIFECYCLE_OBSERVED",
        "R2_CLUSTER_EDGE_RESPONSE",
        "R2_RANGE_EDGE_RESPONSE",
        "R3_REPEATABILITY_V2",
        "R4_MICRO",
        "LOCAL_PUBLICATION",
        "READY_FOR_CLUSTER_HYPOTHESIS_BRAIN",
    )
    for gate in gate_order:
        result = payload["decision_gates"][gate]
        lines.append(f"- **{gate}**: {result['answer']}. {result['basis']}.")
    lines += ["", "## INTEGRITY", "",
              f"- Excluded price sessions converted: {payload['holdout_price_sessions_converted']}.",
              "- Origin facts are frozen at their causal candle; future facts append only.",
              "- Each observer is scoped to one corrected source-contiguous episode.",
              "- Ghost placement is midpoint-symmetric, deterministic, and equal-width before response observation.",
              "- Production BROAD, Micro, release, reference, and thesis semantics are consumed without modification.",
              "- LOCAL publication: NO.", ""]
    return "\n".join(lines)


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value)!r}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=int, default=400)
    parser.add_argument("--json", type=Path,
                        default=Path("reports/structural_response_summary.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("reports/STRUCTURAL_RESPONSE_AUDIT.md"))
    args = parser.parse_args(argv)
    payload = run_study(StudyConfig(history=args.history))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(
        payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "decision_gates": payload["decision_gates"],
        "output": str(args.json),
        "report": str(args.report),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
