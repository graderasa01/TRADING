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
from src.boxes.structure import tol_at
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

EVENTS = frozenset({
    "APPROACH_UPPER", "APPROACH_LOWER", "TOUCH_UPPER", "TOUCH_LOWER",
    "CLOSE_INSIDE_AFTER_UPPER_TEST", "CLOSE_INSIDE_AFTER_LOWER_TEST",
    "CLOSE_AT_UPPER", "CLOSE_AT_LOWER", "CLOSE_OUTSIDE_UPPER",
    "CLOSE_OUTSIDE_LOWER", "RECLAIM_UPPER", "RECLAIM_LOWER",
    "HOLD_INSIDE_AFTER_RECLAIM", "BREAK_ATTEMPT_UP", "BREAK_ATTEMPT_DOWN",
    "ACCEPTED_ABOVE", "ACCEPTED_BELOW", "RE_ENTRY", "MIDPOINT_REACHED",
    "OPPOSITE_EDGE_REACHED", "REVISIT", "LEFT_STRUCTURE", "RETURN_RETEST",
    "NEXT_REFERENCE_REACHED",
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
    approach_direction: str
    structure_width: Decimal
    atr: Decimal
    micro: MicroContext
    local: LocalContext
    next_above: ReferenceFact | None
    next_below: ReferenceFact | None
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
    next_reference_reached_index: int | None = None
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
        self.releases: list[ReleaseEpisode] = []
        self.null_probes: list[NullProbe] = []
        self._active_structure: StructureEpisode | None = None
        self._active_encounters: dict[str, EdgeEncounter] = {}
        self._active_releases: dict[str, ReleaseEpisode] = {}
        self._latest_structure_by_id: dict[str, StructureEpisode] = {}
        self._structure_counts: Counter[str] = Counter()
        self._encounter_counts: Counter[tuple[str, str]] = Counter()
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

    def _near_edge(self, sample: CausalSample, origin: StructureOrigin,
                   side: str) -> bool:
        if side == UPPER:
            return (sample.c >= origin.high - sample.tolerance
                    or sample.interaction in {"AT_UPPER_EDGE", "BREAK_ATTEMPT_UP"})
        return (sample.c <= origin.low + sample.tolerance
                or sample.interaction in {"AT_LOWER_EDGE", "BREAK_ATTEMPT_DOWN"})

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
        approach = "up" if side == UPPER else "down"
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
            price_location=structure.origin.initial_price_location,
            approach_direction=approach,
            structure_width=structure.origin.width,
            atr=sample.atr,
            micro=sample.micro,
            local=sample.local,
            next_above=sample.next_above,
            next_below=sample.next_below,
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
        inside_excursion = max(
            Decimal(0), edge - sample.l if side == UPPER else sample.h - edge)
        outside_excursion = max(
            Decimal(0), sample.h - edge if side == UPPER else edge - sample.l)
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
        if (is_later_candle and self._reference_reached(encounter.origin, sample)
                and encounter.next_reference_reached_index is None):
            encounter.next_reference_reached_index = sample.index
            events.append("NEXT_REFERENCE_REACHED")
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
    def _reference_reached(origin: EncounterOrigin, sample: CausalSample) -> bool:
        refs = tuple(ref for ref in (origin.next_above, origin.next_below) if ref is not None)
        return any(sample.l <= ref.price <= sample.h for ref in refs)

    def _finish_encounter(self, encounter: EdgeEncounter, index: int,
                          reason: str) -> None:
        if encounter.end_reason is not None:
            return
        encounter.end_index = index
        encounter.end_reason = reason
        if self._active_encounters.get(encounter.origin.side) is encounter:
            del self._active_encounters[encounter.origin.side]

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


def _distribution(values: Iterable[int | Decimal]) -> dict:
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
            "next_reference_reaches": sum(item.next_reference_reached_index is not None
                                           for item in rows),
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
        "null_comparisons": null_summary,
    }


def _gate_results(by_bucket: dict[str, dict]) -> dict:
    shared_sequences = [name for name in by_bucket[TEACH]["sequence_counts"]
                        if by_bucket[TEACH]["sequence_counts"][name] > 0
                        and by_bucket[VALIDATE]["sequence_counts"][name] > 0]
    enough_structure = all(
        by_bucket[bucket]["structure_population"]["episodes"] > 0
        and sum(side["encounters"] for side in
                by_bucket[bucket]["edge_encounter_population"].values()) > 0
        for bucket in (TEACH, VALIDATE))
    return {
        "R1_STRUCTURAL_RESPONSE_EXISTS": {
            "answer": "YES" if enough_structure else "NO",
            "basis": "natural-lifecycle structure and edge responses were observed in both buckets",
        },
        "R2_EDGE_RESPONSE_EXISTS": {
            "answer": "INCONCLUSIVE",
            "basis": "interior pseudo-levels are deterministic but not topologically equivalent to boundaries",
        },
        "R3_RESPONSE_IS_REPEATABLE": {
            "answer": "YES" if shared_sequences else "NO",
            "basis": f"shared non-zero sequence families: {len(shared_sequences)}",
        },
        "R4_MICRO_ADDS_INFORMATION": {
            "answer": "INCONCLUSIVE",
            "basis": "Micro strata are descriptive and no untuned separation criterion was introduced",
        },
        "R5_READY_FOR_HYPOTHESIS_BRAIN": {
            "answer": "NO",
            "basis": "R2 is not supported; R5 requires R1-R3",
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
    deterministic = {
        "study": "STRUCTURE_LIFECYCLE_RESPONSE_V1",
        "config": asdict(config),
        "source_population": source_population,
        "consumption": consumption,
        "buckets": by_bucket,
        "validate_output": "AGGREGATE_ONLY",
        "origin_policy": "FROZEN_AT_CAUSAL_CANDLE_FUTURE_APPEND_ONLY",
        "primary_horizon": "NATURAL_STRUCTURAL_LIFECYCLE",
        "fixed_horizon_role": "SECONDARY_NULL_DESCRIPTION_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "local_published": False,
    }
    fingerprint_source = json.dumps(deterministic, sort_keys=True, default=_json_default)
    deterministic["fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8")).hexdigest()[:16]
    deterministic["decision_gates"] = _gate_results(by_bucket)
    return deterministic


def _count_line(item: dict, keys: Sequence[str]) -> str:
    return " | ".join(f"{key.replace('_', ' ')} {item.get(key, 0)}" for key in keys)


def render_report(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    lines = [
        "# Structural Response Audit",
        "",
        "Status: EXECUTED. Research-only structural lifecycle observation; no production map changes.",
        "",
        f"Fingerprint: `{payload['fingerprint']}`",
        "",
        "Primary observations run from causal structure availability to a natural structural or source-episode end. Fixed next-candle facts are secondary sequence/null descriptions only.",
        "",
        "## STRUCTURE POPULATION",
        "",
    ]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        pop = data["structure_population"]
        lines.append(
            f"- {label}: episodes/visits {pop['episodes']} | cluster {pop['kinds'].get('cluster', 0)} | range {pop['kinds'].get('range', 0)} | revisit episodes {pop['revisit_episodes']} | leaving observations {pop['leaving_observations']} | accepted breaks {pop['accepted_breaks']} | re-entries {pop['reentries']} | opposite-edge traversals {pop['opposite_edge_traversals']} | median life/current/inside {pop['lifetime_bars']['median']}/{pop['current_bars']['median']}/{pop['inside_bars']['median']} bars.")
    lines += ["", "## EDGE ENCOUNTER POPULATION", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for side in SIDES:
            edge = data["edge_encounter_population"][side]
            lines.append(f"- {label} {side}: " + _count_line(edge, (
                "encounters", "touches", "origin_close_inside", "origin_close_at",
                "origin_close_outside", "accepted_breaks", "reclaims", "retests",
                "midpoint_reaches", "opposite_edge_reaches", "repeated_encounters")) + ".")
    lines += ["", "An exact inside close may also be within the existing edge tolerance, so `origin close at` is a subset of `origin close inside`; outside takes precedence."]
    lines += ["", "## RELEASE SUBPOPULATION", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        release = data["release_subpopulation"]
        lines.append(f"- {label}: episodes {release['episodes']} | scales {json.dumps(release['scales'], sort_keys=True)} | linked edge encounters {release['linked_to_encounter']} | simultaneous releases preserved {release['simultaneous_releases_preserved']} | givebacks {release['givebacks']} | median held bars {release['held_bars']['median']}.")
    lines += ["", "## MICRO CONTEXT", "",
              "Micro is recorded only at broad-edge encounter origin. The aggregate strata are:", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        compact = {
            state: {
                "encounters": facts["encounters"],
                "accepted_breaks": facts["accepted_breaks"],
                "reclaims": facts["reclaims"],
                "midpoint_reaches": facts["midpoint_reaches"],
            }
            for state, facts in data["micro_context"].items()
        }
        lines.append(f"- {label}: `{json.dumps(compact, sort_keys=True)}`")
    lines += ["", "No directional Micro label or decision field was created.", "",
              "## LOCAL RESEARCH SIDECAR", ""]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        local = data["local_research_sidecar"]
        lines.append(f"- {label}: present {local['present']} | absent {local['absent']} | relations to production Micro `{json.dumps(local['relations_to_micro'], sort_keys=True)}`.")
    lines += ["", "LOCAL remains unpublished and is not required by the primary ledgers.", "",
              "## SEQUENCE COUNTS", ""]
    for name in teach["sequence_counts"]:
        lines.append(f"- `{name}`: TEACH {teach['sequence_counts'][name]} | VALIDATE aggregate {validate['sequence_counts'][name]}.")
    lines += ["", "Subsequent natural end transitions are retained in the machine-readable aggregate.", "",
              "## NULL COMPARISONS", ""]
    for label in teach["null_comparisons"]:
        t = teach["null_comparisons"][label]
        v = validate["null_comparisons"][label]
        lines.append(f"- {label}: TEACH encounters {t['encounters']}, next close on defined interior side {t['next_close_on_interior_side']}; VALIDATE aggregate encounters {v['encounters']}, next close on defined interior side {v['next_close_on_interior_side']}.")
    lines += ["", "The quarter and midpoint levels are mechanically derived with no tuned offset. They are useful occupancy references, but they are not fair topological substitutes for an edge: an edge separates inside from outside while an interior level does not. R2 is therefore left inconclusive.", "",
              "## COUNTER-EVIDENCE", "",
              "- Interior pseudo-levels are structurally confounded with edge comparisons.",
              "- VALIDATE observed no range episodes; cross-bucket repetition is therefore cluster-dominated.",
              "- The outside-close to accepted-break sequence partly restates the upstream two-close rule and is not independent evidence.",
              "- Encounter paths include multiple natural end reasons; no single response exhausts the population.",
              "- Micro and LOCAL strata are observational and do not establish added information by themselves.",
              "", "## LIMITATIONS", "",
              "- The first 400 candles of each corrected source episode establish the frozen map and are not response observations.",
              "- Source episodes with no candle beyond that history are skipped rather than joined across a barrier.",
              "- VALIDATE is emitted only as aggregate counts and distributions; no timestamp, band, price, structure identity, trace, or session-linked index is written.",
              "- The natural source-episode boundary right-censors still-live ledgers.",
              "", "## DECISION GATES", ""]
    gate_order = (
        "R1_STRUCTURAL_RESPONSE_EXISTS",
        "R2_EDGE_RESPONSE_EXISTS",
        "R3_RESPONSE_IS_REPEATABLE",
        "R4_MICRO_ADDS_INFORMATION",
        "R5_READY_FOR_HYPOTHESIS_BRAIN",
        "LOCAL_PUBLICATION",
    )
    for gate in gate_order:
        result = payload["decision_gates"][gate]
        lines.append(f"- **{gate}**: {result['answer']}. {result['basis']}.")
    lines += ["", "## INTEGRITY", "",
              f"- Excluded price sessions converted: {payload['holdout_price_sessions_converted']}.",
              "- Origin facts are frozen at their causal candle; future facts append only.",
              "- Each observer is scoped to one corrected source-contiguous episode.",
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
