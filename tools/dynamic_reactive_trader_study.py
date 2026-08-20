"""Causal replay study for the dynamic structural reactive shadow trader.

The study consumes the corrected source-contiguous TEACH/VALIDATE episodes and emits
aggregate research geometry.  HOLDOUT prices are never requested.  VALIDATE decisions
remain in memory only long enough to aggregate and are never serialised case by case.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes.frontier import Frontier
from src.boxes.snapshot import build_snapshot
from src.boxes.structure import tol_at
from src.learning.split import TEACH, VALIDATE
from src.livemap import frame as structural_frame
from src.livemap.shadow import (
    ACTIVE,
    BRAIN_V1,
    COMPLETED,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    ENTER_LONG_SHADOW,
    ENTER_SHORT_SHADOW,
    EXIT,
    EXPIRED,
    FALSIFIED,
    HOLD,
    HYPOTHESIS_CONFLICT,
    HYPOTHESIS_FAMILIES,
    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
    NO_ACTIVE_HYPOTHESIS,
    OBSERVING,
    STRESSED,
    WAIT,
    DynamicShadowTrader,
)
from tools.live_structure_truth import (
    ResearchEpisode,
    load_research_episodes,
    observational_local_candidates,
)

SYMBOL = "NIFTY BANK"


@dataclass(frozen=True, slots=True)
class StudyConfig:
    history: int = 400


@dataclass(frozen=True, slots=True)
class EpisodeReplay:
    bucket: str
    machine: DynamicShadowTrader
    live_candles: int


@dataclass(frozen=True, slots=True)
class EpisodeFrames:
    """One source episode's causal frames, built once and replayable by any brain.

    Frame construction is the expensive half of this study and is entirely independent
    of the brain reading it, so a brain comparison must not rebuild it twice: doing so
    would also risk the two arms disagreeing for a reason that has nothing to do with
    the brains.
    """

    bucket: str
    source_episode_id: str
    frames: tuple
    source_ordinals: tuple[int, ...]
    tolerances: tuple[Decimal, ...]


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


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


def _fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


def build_episode_frames(
        episode: ResearchEpisode, config: StudyConfig) -> EpisodeFrames | None:
    """Build the causal StructuralFrames of one source episode, brain-independent."""

    candles = episode.candles
    if len(candles) <= config.history:
        return None
    history = candles[:config.history]
    live = candles[config.history:]
    snapshot = build_snapshot(history, SYMBOL)
    frontier = Frontier(snapshot, history)
    locals_by_index: dict[int, structural_frame.LocalStructure] = {}
    for candle in live:
        reading = frontier.on_candle(candle)
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
    source_episode_id = f"{episode.bucket}-EP{episode.ordinal:03d}"
    source_ordinal_by_day = {item.day: item.source_ordinal for item in episode.sessions}
    ordinals: list[int] = []
    tolerances: list[Decimal] = []
    for frame in frames:
        candle = frontier.candles[frame.index]
        if candle.session_date not in source_ordinal_by_day:
            raise AssertionError("dynamic replay crossed its source episode barrier")
        ordinals.append(source_ordinal_by_day[candle.session_date])
        tolerances.append(tol_at(frontier.candles, frame.index, frontier.tol_atr))
    return EpisodeFrames(
        bucket=episode.bucket,
        source_episode_id=source_episode_id,
        frames=tuple(frames),
        source_ordinals=tuple(ordinals),
        tolerances=tuple(tolerances),
    )


def replay_frames(prepared: EpisodeFrames, *, brain: str) -> EpisodeReplay:
    """Read one prepared source episode with exactly one brain version."""

    machine = DynamicShadowTrader(
        prepared.bucket, prepared.source_episode_id, brain=brain)
    last = len(prepared.frames) - 1
    for position, frame in enumerate(prepared.frames):
        machine.observe_frame(
            frame,
            source_ordinal=prepared.source_ordinals[position],
            tolerance=prepared.tolerances[position],
            source_end=position == last,
        )
    return EpisodeReplay(prepared.bucket, machine, len(prepared.frames))


def run_episode(
        episode: ResearchEpisode, config: StudyConfig, *, brain: str,
        ) -> EpisodeReplay | None:
    prepared = build_episode_frames(episode, config)
    if prepared is None:
        return None
    return replay_frames(prepared, brain=brain)


def _status_population(replays: Sequence[EpisodeReplay]) -> tuple[dict, list]:
    records = [record for replay in replays for record in replay.machine.hypothesis_records]
    family = Counter(record.family for record in records)
    final = Counter(record.state for record in records)
    ever = Counter()
    for record in records:
        for status in record.statuses_seen:
            ever[status] += 1
    lifetime = [
        (record.terminal_index if record.terminal_index is not None
         else record.last_update_index) - record.birth_index + 1
        for record in records
    ]
    return ({
        "created": len(records),
        "by_family": {name: family.get(name, 0) for name in sorted(HYPOTHESIS_FAMILIES)},
        "final_status": dict(sorted(final.items())),
        "ever_reached_status": dict(sorted(ever.items())),
        "lifetime_bars": _distribution(lifetime),
    }, records)


def _participation_population(replays: Sequence[EpisodeReplay], records: Sequence) -> dict:
    decisions = [decision for replay in replays for decision in replay.machine.decisions]
    positions = [episode for replay in replays for episode in replay.machine.position_episodes]
    entered_ids = {item.hypothesis_id for item in positions}
    actions = Counter(item.action for item in decisions)
    statuses = Counter(item.participation.status for item in decisions)
    by_family = Counter(item.family for item in positions)
    exits = Counter(item.exit_reason for item in positions)
    records_by_id = {item.hypothesis_id: item for item in records}
    entry_decisions = [
        decision for decision in decisions
        if decision.action in {ENTER_LONG_SHADOW, ENTER_SHORT_SHADOW}
    ]
    entry_release_same_candle = sum(bool(item.market.releases) for item in entry_decisions)
    entry_birth_same_candle = sum(
        records_by_id[item.position.hypothesis_id].birth_index == item.index
        for item in entry_decisions if item.position.hypothesis_id is not None)
    continuation_on_acceptance = sum(
        item.market.accepted_break
        and item.position.family in {CONTINUATION_UP, CONTINUATION_DOWN}
        for item in entry_decisions)
    return {
        "hypotheses_without_participation": sum(
            record.hypothesis_id not in entered_ids for record in records),
        "shadow_entries": actions[ENTER_LONG_SHADOW] + actions[ENTER_SHORT_SHADOW],
        "long_entries": actions[ENTER_LONG_SHADOW],
        "short_entries": actions[ENTER_SHORT_SHADOW],
        "holds": actions[HOLD],
        "exits": actions[EXIT],
        "waits": actions[WAIT],
        "actions": dict(sorted(actions.items())),
        "participation_states": dict(sorted(statuses.items())),
        "entries_by_family": {name: by_family.get(name, 0)
                              for name in sorted(HYPOTHESIS_FAMILIES)},
        "exit_reasons": dict(sorted(exits.items())),
        "entries_on_any_release_candle": entry_release_same_candle,
        "entries_on_hypothesis_birth_candle": entry_birth_same_candle,
        "continuation_entries_on_acceptance_candle": continuation_on_acceptance,
    }


def _timing(replays: Sequence[EpisodeReplay]) -> dict:
    birth_relative: list[int] = []
    entry_after_birth: list[int] = []
    consumed_points: list[Decimal] = []
    consumed_atr: list[float] = []
    room_points: list[Decimal] = []
    room_atr: list[float] = []
    invalidation_points: list[Decimal] = []
    invalidation_atr: list[float] = []
    invalidation_points_by_family: dict[str, list[Decimal]] = defaultdict(list)
    invalidation_atr_by_family: dict[str, list[float]] = defaultdict(list)
    midpoint_before = 0
    midpoint_applicable = 0
    reference_before = 0
    entries = 0
    for replay in replays:
        decisions = {item.index: item for item in replay.machine.decisions}
        records = {item.hypothesis_id: item for item in replay.machine.hypothesis_records}
        for position in replay.machine.position_episodes:
            entries += 1
            entry = decisions[position.entry_index]
            record = records[position.hypothesis_id]
            birth = decisions[record.birth_index]
            if birth.movement.origin_index is not None:
                birth_relative.append(record.birth_index - birth.movement.origin_index)
            entry_after_birth.append(position.entry_index - record.birth_index)
            p = entry.participation
            if p.movement_consumed_points is not None:
                consumed_points.append(p.movement_consumed_points)
            if p.movement_consumed_atr is not None:
                consumed_atr.append(p.movement_consumed_atr)
            if p.structural_room_points is not None:
                room_points.append(p.structural_room_points)
            if p.structural_room_atr is not None:
                room_atr.append(p.structural_room_atr)
            if p.invalidation_distance_points is not None:
                invalidation_points.append(p.invalidation_distance_points)
                invalidation_points_by_family[position.family].append(
                    p.invalidation_distance_points)
            if p.invalidation_distance_atr is not None:
                invalidation_atr.append(p.invalidation_distance_atr)
                invalidation_atr_by_family[position.family].append(
                    p.invalidation_distance_atr)
            midpoint_applicable += int(
                p.midpoint_crossed_before_participation is not None)
            midpoint_before += int(
                p.midpoint_crossed_before_participation is True)
            reference_before += int(p.next_reference_already_reached)
    return {
        "entries": entries,
        "hypothesis_birth_bars_from_movement_origin": _distribution(birth_relative),
        "participation_bars_after_hypothesis_birth": _distribution(entry_after_birth),
        "midpoint_already_crossed_before_entry": midpoint_before,
        "entries_with_broad_midpoint_applicable": midpoint_applicable,
        "next_reference_already_reached_before_entry": reference_before,
        "movement_consumed_points_at_entry": _distribution(consumed_points),
        "movement_consumed_atr_at_entry": _distribution(consumed_atr),
        "structural_room_points_at_entry": _distribution(room_points),
        "structural_room_atr_at_entry": _distribution(room_atr),
        "invalidation_distance_points_at_entry": _distribution(invalidation_points),
        "invalidation_distance_atr_at_entry": _distribution(invalidation_atr),
        "invalidation_distance_points_at_entry_by_family": {
            family: _distribution(invalidation_points_by_family.get(family, ()))
            for family in sorted(HYPOTHESIS_FAMILIES)
        },
        "invalidation_distance_atr_at_entry_by_family": {
            family: _distribution(invalidation_atr_by_family.get(family, ()))
            for family in sorted(HYPOTHESIS_FAMILIES)
        },
    }


def _stay_with_move(replays: Sequence[EpisodeReplay]) -> dict:
    positions = [episode for replay in replays for episode in replay.machine.position_episodes]
    landmark_counts = Counter(
        landmark for item in positions for landmark in item.landmarks_reached)
    with_landmark = sum(bool(item.landmarks_reached) for item in positions)
    falsified = [item for item in positions if item.hypothesis_falsification_index is not None]
    fractions = [item.path_participation_fraction for item in positions
                 if item.path_participation_fraction is not None]
    falsified_bars_by_family: dict[str, list[int]] = defaultdict(list)
    for item in falsified:
        falsified_bars_by_family[item.family].append(
            item.exit_index - item.entry_index + 1)
    return {
        "closed_shadow_positions": len(positions),
        "bars_position_remained_active": _distribution(
            item.exit_index - item.entry_index + 1 for item in positions),
        "positions_reaching_structural_landmark": with_landmark,
        "landmarks_reached": dict(sorted(landmark_counts.items())),
        "structural_path_available_at_entry": _distribution(
            item.structural_path_available_at_entry for item in positions),
        "structural_path_traversed_while_valid": _distribution(
            item.structural_path_traversed_while_valid for item in positions),
        "path_participation_fraction": _distribution(fractions),
        "positions_falsified": len(falsified),
        "exited_on_first_causal_falsification": sum(
            item.exited_on_first_falsification is True for item in falsified),
        "exit_after_falsification_violations": sum(
            item.exited_on_first_falsification is not True for item in falsified),
        "distance_entry_to_falsification": _distribution(
            item.distance_entry_to_falsification
            for item in falsified if item.distance_entry_to_falsification is not None),
        "falsified_position_bars_by_family": {
            family: _distribution(falsified_bars_by_family.get(family, ()))
            for family in sorted(HYPOTHESIS_FAMILIES)
        },
    }


def _opposite(side: str) -> str:
    return "down" if side == "up" else "up"


def _false_switch(replays: Sequence[EpisodeReplay]) -> dict:
    immediate_opposite_hypothesis = 0
    exit_without_opposite = 0
    independent_reverse_entries = 0
    same_candle_reverse_entries = 0
    side_flips = 0
    for replay in replays:
        decisions = replay.machine.decisions
        positions = sorted(replay.machine.position_episodes, key=lambda item: item.entry_index)
        position_by_exit = {item.exit_index: item for item in positions}
        for offset, decision in enumerate(decisions):
            if decision.action != EXIT:
                continue
            closed = position_by_exit[decision.index]
            opposite = _opposite(closed.side)
            live_opposite = any(
                item.side == opposite and item.state in {ACTIVE, OBSERVING, STRESSED}
                for item in decision.hypotheses)
            immediate_opposite_hypothesis += int(live_opposite)
            following = decisions[offset + 1] if offset + 1 < len(decisions) else None
            if following is None or not any(
                    item.side == opposite and item.state in {ACTIVE, OBSERVING, STRESSED}
                    for item in following.hypotheses):
                exit_without_opposite += 1
            same_candle_reverse_entries += int(
                decision.position.state != "FLAT" and decision.position_before != "FLAT")
        for previous, current in pairwise(positions):
            if previous.side != current.side:
                side_flips += 1
                if current.entry_index > previous.exit_index:
                    independent_reverse_entries += 1
                if current.entry_index == previous.exit_index:
                    same_candle_reverse_entries += 1
    return {
        "exit_with_opposite_hypothesis_already_visible": immediate_opposite_hypothesis,
        "exit_followed_by_no_opposite_hypothesis": exit_without_opposite,
        "independent_reverse_entries_on_later_candle": independent_reverse_entries,
        "same_candle_reverse_entries": same_candle_reverse_entries,
        "raw_position_side_flips": side_flips,
    }


def _episode_spread(replays: Sequence[EpisodeReplay]) -> dict:
    entries = []
    landmarks = []
    waits = []
    entry_total = 0
    largest = 0
    for replay in replays:
        decisions = replay.machine.decisions
        episode_entries = sum(
            item.action in {ENTER_LONG_SHADOW, ENTER_SHORT_SHADOW} for item in decisions)
        episode_landmarks = sum(
            bool(item.landmarks_reached) for item in replay.machine.position_episodes)
        episode_waits = sum(item.action == WAIT for item in decisions)
        entries.append(episode_entries)
        landmarks.append(episode_landmarks)
        waits.append(episode_waits)
        entry_total += episode_entries
        largest = max(largest, episode_entries)
    return {
        "source_episodes": len(replays),
        "source_episodes_with_entry": sum(item > 0 for item in entries),
        "source_episodes_with_landmark_participation": sum(item > 0 for item in landmarks),
        "entries_per_source_episode": _distribution(entries),
        "landmark_positions_per_source_episode": _distribution(landmarks),
        "waits_per_source_episode": _distribution(waits),
        "largest_source_episode_entry_share": (
            round(largest / entry_total, 6) if entry_total else None),
    }


def aggregate(replays: Sequence[EpisodeReplay]) -> dict:
    hypothesis_population, records = _status_population(replays)
    participation = _participation_population(replays, records)
    decisions = [decision for replay in replays for decision in replay.machine.decisions]
    timing = _timing(replays)
    stay = _stay_with_move(replays)
    false_switch = _false_switch(replays)
    closed_candles = sum(item.live_candles for item in replays)
    micro_entry = Counter(
        decision.market.micro.state for decision in decisions
        if decision.action in {ENTER_LONG_SHADOW, ENTER_SHORT_SHADOW})
    family = hypothesis_population["by_family"]
    largest_family = max(family.values(), default=0)
    return {
        "source_episodes_processed": len(replays),
        "closed_candles_observed": closed_candles,
        "hypothesis_population": hypothesis_population,
        "participation_population": participation,
        "timing": timing,
        "stay_with_move": stay,
        "false_switch": false_switch,
        "micro_context_at_entry": dict(sorted(micro_entry.items())),
        "source_episode_spread": _episode_spread(replays),
        "descriptive_rates": {
            "hypotheses_created_per_candle": _fraction(
                hypothesis_population["created"], closed_candles),
            "shadow_entries_per_candle": _fraction(
                participation["shadow_entries"], closed_candles),
            "valid_but_wait_per_candle": _fraction(
                sum(item.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
                    for item in decisions), closed_candles),
            "landmark_positions_per_closed_position": _fraction(
                stay["positions_reaching_structural_landmark"],
                stay["closed_shadow_positions"]),
            "falsified_positions_per_closed_position": _fraction(
                stay["positions_falsified"], stay["closed_shadow_positions"]),
            "side_flips_per_closed_position": _fraction(
                false_switch["raw_position_side_flips"],
                stay["closed_shadow_positions"]),
        },
        "counter_evidence": {
            "valid_but_wait_candles": sum(
                item.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
                for item in decisions),
            "conflict_wait_candles": sum(
                item.participation.status == HYPOTHESIS_CONFLICT for item in decisions),
            "no_active_hypothesis_candles": sum(
                item.participation.status == NO_ACTIVE_HYPOTHESIS for item in decisions),
            "entries_after_midpoint": timing[
                "midpoint_already_crossed_before_entry"],
            "entries_at_reached_reference": timing[
                "next_reference_already_reached_before_entry"],
            "entries_on_any_release_candle": participation[
                "entries_on_any_release_candle"],
            "entries_on_hypothesis_birth_candle": participation[
                "entries_on_hypothesis_birth_candle"],
            "continuation_entries_on_acceptance_candle": participation[
                "continuation_entries_on_acceptance_candle"],
            "largest_hypothesis_family_share": (
                round(largest_family / hypothesis_population["created"], 6)
                if hypothesis_population["created"] else None),
        },
    }


def _repeatability(buckets: dict[str, dict]) -> dict:
    output = {}
    for name in buckets[TEACH]["descriptive_rates"]:
        teach = buckets[TEACH]["descriptive_rates"][name]
        validate = buckets[VALIDATE]["descriptive_rates"][name]
        difference = (
            None if teach["rate"] is None or validate["rate"] is None
            else round(abs(teach["rate"] - validate["rate"]), 6)
        )
        output[name] = {
            "teach": teach,
            "validate_aggregate": validate,
            "absolute_rate_difference": difference,
        }
    return output


def _r2_reference() -> dict:
    source = REPO_ROOT / "reports" / "structural_response_summary.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    gates = payload["decision_gates"]
    return {
        "fingerprint": payload["fingerprint"],
        "R2_CLUSTER": gates["R2_CLUSTER_EDGE_RESPONSE"]["answer"],
        "R2_RANGE": gates["R2_RANGE_EDGE_RESPONSE"]["answer"],
        "R4_MICRO": gates["R4_MICRO"]["answer"],
        "LOCAL_PUBLICATION": gates["LOCAL_PUBLICATION"]["answer"],
    }


def _gates(buckets: dict[str, dict]) -> dict:
    teach = buckets[TEACH]
    validate = buckets[VALIDATE]
    both = (teach, validate)
    d1 = all(item["closed_candles_observed"] > 0 for item in both)
    d2 = all(
        item["hypothesis_population"]["created"] > 0
        and item["hypothesis_population"]["ever_reached_status"].get(ACTIVE, 0) > 0
        and sum(item["hypothesis_population"]["final_status"].get(status, 0)
                for status in (COMPLETED, FALSIFIED, EXPIRED)) > 0
        for item in both)
    d3 = all(item["counter_evidence"]["valid_but_wait_candles"] > 0 for item in both)
    d4 = all(
        item["participation_population"]["shadow_entries"] > 0
        and item["stay_with_move"]["exit_after_falsification_violations"] == 0
        for item in both)
    d5 = all(item["false_switch"]["same_candle_reverse_entries"] == 0 for item in both)
    follow = all(
        item["participation_population"]["shadow_entries"] > 0
        and item["stay_with_move"]["positions_reaching_structural_landmark"] > 0
        and item["stay_with_move"]["closed_shadow_positions"] > 0
        and item["stay_with_move"]["exit_after_falsification_violations"] == 0
        and item["source_episode_spread"]["source_episodes_with_entry"] > 1
        and item["source_episode_spread"][
            "source_episodes_with_landmark_participation"] > 1
        for item in both)
    return {
        "D1_MOVEMENT_STATE_CAUSAL": {
            "answer": "YES" if d1 else "NO",
            "basis": "immutable closed-candle movement states were emitted inside every source barrier",
        },
        "D2_HYPOTHESIS_LIFECYCLE_CAUSAL": {
            "answer": "YES" if d2 else "NO",
            "basis": "hypotheses were born, updated, and terminally classified from current-or-prior facts",
        },
        "D3_PARTICIPATION_SEPARATE_FROM_HYPOTHESIS": {
            "answer": "YES" if d3 else "NO",
            "basis": "both buckets contain active hypotheses that remained flat for structural reasons",
        },
        "D4_STRUCTURAL_INVALIDATION_WORKS": {
            "answer": "YES" if d4 else "NO",
            "basis": "every entry carried factual invalidation and no exit lagged a first falsification",
        },
        "D5_NO_AUTOMATIC_REVERSAL": {
            "answer": "YES" if d5 else "NO",
            "basis": "same-candle opposite shadow entry after exit is absent",
        },
        "D6_SHADOW_TRADER_CAN_FOLLOW_MOVEMENT": {
            "answer": "YES" if follow else "INCONCLUSIVE",
            "basis": (
                "entries followed causal hypothesis formation, structural landmarks were reached, "
                "exits were causal, and behaviour appeared in multiple source episodes in both buckets"
                if follow else
                "one or more required movement-following facts did not repeat across multiple source episodes"
            ),
        },
        "D7_READY_FOR_EXECUTION_RESEARCH": {
            "answer": "NO",
            "basis": "this remains a research-only shadow machine without execution, costs, or unseen-forward study",
        },
    }


def run_study(config: StudyConfig | None = None) -> dict:
    """Reproduce the frozen V1 audit.  This report is historical evidence: it is pinned
    to ``BRAIN_V1`` on purpose so that fingerprint ``bf497495e394bb87`` stays
    reproducible from the current source tree."""

    config = config or StudyConfig()
    episodes, source_population = load_research_episodes()
    by_bucket: dict[str, list[EpisodeReplay]] = {TEACH: [], VALIDATE: []}
    skipped = Counter()
    for bucket in (TEACH, VALIDATE):
        for episode in episodes[bucket]:
            replay = run_episode(episode, config, brain=BRAIN_V1)
            if replay is None:
                skipped[bucket] += 1
            else:
                by_bucket[bucket].append(replay)
    buckets = {bucket: aggregate(by_bucket[bucket]) for bucket in (TEACH, VALIDATE)}
    deterministic = {
        "study": "DYNAMIC_STRUCTURAL_REACTIVE_SHADOW_TRADER_V1",
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "buckets": buckets,
        "teach_validate_descriptive_repeatability": _repeatability(buckets),
        "r2_structural_research_reference": _r2_reference(),
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "broker_or_live_execution": False,
        "threshold_optimization": False,
    }
    fingerprint_source = json.dumps(
        deterministic, sort_keys=True, default=_json_default)
    deterministic["fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8")).hexdigest()[:16]
    deterministic["decision_gates"] = _gates(buckets)
    return deterministic


def _dist_text(item: dict) -> str:
    return (
        f"n {item['count']} | min {item['min']} | median {item['median']} | "
        f"mean {item['mean']} | max {item['max']}"
    )


def render_markdown(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    r2 = payload["r2_structural_research_reference"]
    lines = [
        "What this trader currently knows, what it can do, and what it still cannot do.",
        "",
        "# Dynamic Reactive Trader Audit",
        "",
        "Status: EXECUTED. Research-only causal shadow participation; no broker or live execution.",
        "",
        f"Fingerprint: `{payload['fingerprint']}`",
        "",
        "## PLAIN-LANGUAGE RESULT",
        "",
        (
            "The shadow machine can locate price in Broad geometry, maintain explicit structural "
            "hypotheses, wait when a valid premise has no usable structural room, join some moves, "
            "hold while the premise remains intact, and exit on completion or first causal "
            "falsification. It does not know future movement, does not infer a trade from an edge "
            "touch or Micro event, and does not establish readiness for execution research."
        ),
        "",
        "## ARCHITECTURE",
        "",
        "- `MarketTruth`: immutable facts copied from StructuralFrame; it never chooses an action.",
        "- `MovementState`: origin, landmarks, causal progress, remaining geometry, Micro and release context.",
        "- Hypothesis Brain: zero or more stable, explicit lifecycle records without selection weights.",
        "- `ParticipationState`: separate answer for whether structural room remains available.",
        "- `ShadowPositionState`: FLAT/SHADOW_LONG/SHADOW_SHORT research state with factual invalidation only.",
        "",
        "## LIFECYCLE TRACE",
        "",
        "```text",
        "NO_HYPOTHESIS",
        "-> OBSERVING_LOWER_AREA",
        "-> ROTATION_HYPOTHESIS_ACTIVE",
        "-> VALID_BUT_WAIT",
        "-> SHADOW_LONG",
        "-> HOLD",
        "-> MIDPOINT_REACHED",
        "-> HOLD",
        "-> APPROACHING_UPPER_REFERENCE",
        "-> HYPOTHESIS_COMPLETED",
        "-> EXIT",
        "-> FLAT",
        "```",
        "",
        "```text",
        "ROTATION_ACTIVE",
        "-> SHADOW_LONG",
        "-> STRUCTURAL_FAILURE_BELOW",
        "-> FALSIFIED",
        "-> EXIT",
        "-> FLAT",
        "-> no automatic short",
        "```",
        "",
        "## HYPOTHESIS POPULATION",
        "",
    ]
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        hyp = data["hypothesis_population"]
        lines.append(
            f"- {label}: created {hyp['created']} | families {json.dumps(hyp['by_family'], sort_keys=True)} "
            f"| ever reached {json.dumps(hyp['ever_reached_status'], sort_keys=True)} | "
            f"final states {json.dumps(hyp['final_status'], sort_keys=True)} | lifetime "
            f"{_dist_text(hyp['lifetime_bars'])}.")
    lines.extend(["", "## SHADOW PARTICIPATION POPULATION", ""])
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        part = data["participation_population"]
        lines.append(
            f"- {label}: entries {part['shadow_entries']} | long {part['long_entries']} | "
            f"short {part['short_entries']} | holds {part['holds']} | exits {part['exits']} | "
            f"waits {part['waits']} | hypotheses without participation "
            f"{part['hypotheses_without_participation']}.")
        lines.append(
            f"- {label} entries by family: `{json.dumps(part['entries_by_family'], sort_keys=True)}`.")
        lines.append(
            f"- {label} exit reasons: `{json.dumps(part['exit_reasons'], sort_keys=True)}`.")
    lines.extend(["", "## MOVEMENT PARTICIPATION", ""])
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        timing = data["timing"]
        stay = data["stay_with_move"]
        lines.append(
            f"- {label}: entry after hypothesis birth {_dist_text(timing['participation_bars_after_hypothesis_birth'])}; "
            f"hypothesis birth from movement origin "
            f"{_dist_text(timing['hypothesis_birth_bars_from_movement_origin'])}; "
            f"room at entry {_dist_text(timing['structural_room_points_at_entry'])}; "
            f"movement consumed {_dist_text(timing['movement_consumed_points_at_entry'])}.")
        lines.append(
            f"- {label}: invalidation distance at entry "
            f"{_dist_text(timing['invalidation_distance_points_at_entry'])}; by family "
            f"`{json.dumps(timing['invalidation_distance_points_at_entry_by_family'], sort_keys=True)}`.")
        lines.append(
            f"- {label}: {stay['positions_reaching_structural_landmark']}/"
            f"{stay['closed_shadow_positions']} closed shadow positions reached at least one "
            f"structural landmark; path fraction {_dist_text(stay['path_participation_fraction'])}.")
    lines.extend(["", "## INVALIDATION AND EXIT", ""])
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        stay = data["stay_with_move"]
        lines.append(
            f"- {label}: falsified positions {stay['positions_falsified']} | first-causal-candle "
            f"exits {stay['exited_on_first_causal_falsification']} | lag violations "
            f"{stay['exit_after_falsification_violations']} | entry-to-falsification distance "
            f"{_dist_text(stay['distance_entry_to_falsification'])}.")
        lines.append(
            f"- {label} falsified-position lifetime by family: "
            f"`{json.dumps(stay['falsified_position_bars_by_family'], sort_keys=True)}`.")
    lines.extend(["", "## FALSE SWITCH AND REVERSAL", ""])
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        switch = data["false_switch"]
        lines.append(f"- {label}: `{json.dumps(switch, sort_keys=True)}`.")
    lines.extend(["", "## COUNTER-EVIDENCE", ""])
    for label, data in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        counter = data["counter_evidence"]
        lines.append(
            f"- {label}: valid-but-wait candles {counter['valid_but_wait_candles']} | conflict "
            f"waits {counter['conflict_wait_candles']} | no-active-hypothesis candles "
            f"{counter['no_active_hypothesis_candles']} | entries after midpoint "
            f"{counter['entries_after_midpoint']} | entries at reached reference "
            f"{counter['entries_at_reached_reference']} | entries on any release candle "
            f"{counter['entries_on_any_release_candle']} | entries on hypothesis birth "
            f"candle {counter['entries_on_hypothesis_birth_candle']} | continuation entries "
            f"on acceptance candle {counter['continuation_entries_on_acceptance_candle']} | "
            f"largest family share "
            f"{counter['largest_hypothesis_family_share']}.")
        lines.append(
            f"- {label} source-episode spread: `"
            f"{json.dumps(data['source_episode_spread'], sort_keys=True)}`.")
    lines.extend(["", "## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY", ""])
    for name, item in payload["teach_validate_descriptive_repeatability"].items():
        lines.append(
            f"- `{name}`: TEACH {item['teach']['numerator']}/"
            f"{item['teach']['denominator']} = {item['teach']['rate']}; VALIDATE aggregate "
            f"{item['validate_aggregate']['numerator']}/"
            f"{item['validate_aggregate']['denominator']} = "
            f"{item['validate_aggregate']['rate']}; absolute difference "
            f"{item['absolute_rate_difference']}.")
    lines.extend([
        "",
        "## MICRO AND REFERENCES",
        "",
        (
            "Micro is copied as subordinate movement context and cannot create a hypothesis or "
            "shadow position by itself. Up/down reference paths remain distinct. Rotation uses "
            "Broad midpoint and opposite edge; outside continuation uses the immediate mapped "
            "reference published in its direction."
        ),
        f"- TEACH Micro state at entry: `{json.dumps(teach['micro_context_at_entry'], sort_keys=True)}`.",
        (
            f"- VALIDATE aggregate Micro state at entry: "
            f"`{json.dumps(validate['micro_context_at_entry'], sort_keys=True)}`."
        ),
        "",
        "## PRIOR STRUCTURAL RESEARCH",
        "",
        f"- Structural-response fingerprint: `{r2['fingerprint']}`.",
        f"- R2_CLUSTER: **{r2['R2_CLUSTER']}**.",
        f"- R2_RANGE: **{r2['R2_RANGE']}**.",
        f"- R4_MICRO: **{r2['R4_MICRO']}**.",
        f"- LOCAL_PUBLICATION: **{r2['LOCAL_PUBLICATION']}**.",
        "- This milestone does not promote edge superiority or change those conclusions.",
        "",
        "## DECISION GATES",
        "",
    ])
    for name, result in payload["decision_gates"].items():
        lines.append(f"- **{name}**: {result['answer']}. {result['basis']}.")
    lines.extend([
        "",
        "## PRIVACY AND INTEGRITY",
        "",
        "- VALIDATE is aggregate-only: no timestamps, prices, IDs, bands, traces, session-linked indices, or paths.",
        f"- HOLDOUT_PRICE_SESSIONS_CONVERTED = {payload['holdout_price_sessions_converted']}.",
        "- Every source episode closes its still-live hypotheses and shadow position at its own boundary.",
        "- No broker, order submission, sizing, leverage, parameter search, or detector tuning exists here.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(payload: dict, report: Path, aggregate: Path) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    aggregate.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(payload), encoding="utf-8")
    aggregate.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=Path("reports/DYNAMIC_REACTIVE_TRADER_AUDIT.md"))
    parser.add_argument(
        "--aggregate", type=Path,
        default=Path("reports/dynamic_reactive_trader_summary.json"))
    args = parser.parse_args(argv)
    payload = run_study()
    write_outputs(payload, args.report, args.aggregate)
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "decision_gates": payload["decision_gates"],
        "report": str(args.report),
        "aggregate": str(args.aggregate),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
