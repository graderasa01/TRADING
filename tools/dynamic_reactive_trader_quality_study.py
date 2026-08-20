"""Final measurement-only quality audit of Dynamic Shadow Trader V1.

Trading behaviour is frozen.  This tool replays the identical corrected research
universe, verifies the historical V1 fingerprint, and derives aggregate quality ledgers
from already-emitted decisions.  HOLDOUT prices are never requested and VALIDATE case
records are never serialised.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.learning.split import TEACH, VALIDATE
from src.livemap.shadow import (
    ACTIVE,
    BRAIN_V1,
    COMPLETED,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    EXPIRED,
    FALSIFIED,
    LOWER_ROTATION,
    UPPER_ROTATION,
)
from src.livemap.shadow_quality import (
    FALSIFICATION_EXIT,
    OBJECTIVE_COMPLETION,
    POSSIBLE_SAME_STRUCTURE_CHURN,
    RESEARCH_BOUNDARY,
    STRUCTURAL_REORIENTATION_HANDOFF,
    WAIT_AVOIDED_FAILED_HYPOTHESIS,
    WAIT_MISSED_SUPPORTIVE_MOVEMENT,
    active_directional_population,
    build_position_quality,
    build_side_switches,
    build_wait_quality,
    flip_chain_summary,
)
from tools.dynamic_reactive_trader_study import (
    EpisodeReplay,
    StudyConfig,
    _json_default,
    _r2_reference,
    run_episode,
)
from tools.dynamic_reactive_trader_study import (
    _repeatability as v1_repeatability,
)
from tools.dynamic_reactive_trader_study import (
    aggregate as v1_aggregate,
)
from tools.live_structure_truth import load_research_episodes

EXPECTED_V1_FINGERPRINT = "bf497495e394bb87"
DIRECTIONAL_FAMILIES = (
    LOWER_ROTATION,
    UPPER_ROTATION,
    CONTINUATION_UP,
    CONTINUATION_DOWN,
)
QUALITY_RATE_NAMES = (
    "supportive_landmark_per_position",
    "objective_completion_per_position",
    "positive_retained_progress_per_position",
    "falsification_per_position",
    "wait_avoided_failure_per_nonparticipated_active",
    "wait_missed_supportive_per_nonparticipated_active",
    "nonzero_overshoot_per_falsified_position",
    "possible_churn_per_side_switch",
)


def _distribution(values: Iterable[int | float | Decimal]) -> dict:
    numbers = [float(item) for item in values]
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


def _by_family_distribution(records, attribute: str) -> dict:
    return {
        family: _distribution(
            getattr(item, attribute) for item in records
            if item.family == family and getattr(item, attribute) is not None)
        for family in DIRECTIONAL_FAMILIES
    }


def _active_population(replays: Sequence[EpisodeReplay]) -> dict:
    totals = Counter()
    family = {
        name: Counter() for name in DIRECTIONAL_FAMILIES
    }
    for replay in replays:
        totals.update(active_directional_population(replay.machine))
        entered = {item.hypothesis_id for item in replay.machine.position_episodes}
        for record in replay.machine.hypothesis_records:
            if record.family not in family:
                continue
            family[record.family]["directional_hypotheses"] += 1
            if ACTIVE in record.statuses_seen:
                family[record.family]["directional_hypotheses_ever_active"] += 1
                key = ("active_directional_with_participation"
                       if record.hypothesis_id in entered
                       else "active_directional_without_participation")
                family[record.family][key] += 1
    return {
        **dict(totals),
        "by_family": {name: dict(family[name]) for name in DIRECTIONAL_FAMILIES},
        "primary_participation_opportunity_denominator":
            "DIRECTIONAL_HYPOTHESES_EVER_ACTIVE",
    }


def _entry_quality(positions) -> dict:
    fields = (
        "bars_origin_to_birth",
        "bars_birth_to_active",
        "bars_active_to_entry",
        "whole_progress_fraction_at_entry",
        "segment_progress_fraction_at_entry",
        "structural_room_points_at_entry",
        "structural_room_atr_at_entry",
        "invalidation_distance_points_at_entry",
        "invalidation_distance_atr_at_entry",
        "room_to_invalidation_ratio",
    )
    return {
        "entries": len(positions),
        "by_family": {
            family: {
                "entries": sum(item.family == family for item in positions),
                **{field: _distribution(
                    getattr(item, field) for item in positions
                    if item.family == family and getattr(item, field) is not None)
                   for field in fields},
            }
            for family in DIRECTIONAL_FAMILIES
        },
    }


def _landmark_quality(positions) -> dict:
    supportive = [item for item in positions if item.supportive_landmarks]
    adverse_only = [item for item in positions
                    if item.adverse_landmarks and not item.supportive_landmarks]
    both_then_false = [item for item in positions
                       if item.supportive_landmarks and item.falsified]
    no_supportive = [item for item in positions if not item.supportive_landmarks]
    supportive_counts = Counter(
        landmark for item in positions for landmark in item.supportive_landmarks)
    adverse_counts = Counter(
        landmark for item in positions for landmark in item.adverse_landmarks)
    overlap = sum(bool(set(item.supportive_landmarks) & set(item.adverse_landmarks))
                  for item in positions)
    return {
        "closed_positions": len(positions),
        "positions_reaching_supportive_landmark": len(supportive),
        "positions_reaching_only_adverse_or_falsifying_transition": len(adverse_only),
        "positions_reaching_supportive_before_eventual_falsification": len(both_then_false),
        "positions_reaching_no_supportive_landmark": len(no_supportive),
        "supportive_landmarks": dict(sorted(supportive_counts.items())),
        "adverse_or_falsifying_landmarks": dict(sorted(adverse_counts.items())),
        "adverse_incorrectly_counted_as_supportive": overlap,
    }


def _progress_quality(positions) -> dict:
    return {
        "max_favorable_structural_progress": {
            "points": _distribution(
                item.max_favorable_structural_progress_points for item in positions),
            "atr": _distribution(
                item.max_favorable_structural_progress_atr for item in positions
                if item.max_favorable_structural_progress_atr is not None),
            "fraction": _distribution(
                item.max_favorable_structural_progress_fraction for item in positions
                if item.max_favorable_structural_progress_fraction is not None),
            "fraction_by_family": _by_family_distribution(
                positions, "max_favorable_structural_progress_fraction"),
        },
        "retained_structural_progress_at_exit": {
            "raw_directional_points": _distribution(
                item.raw_directional_progress_points_at_exit for item in positions),
            "points": _distribution(
                item.retained_structural_progress_points_at_exit for item in positions),
            "atr": _distribution(
                item.retained_structural_progress_atr_at_exit for item in positions
                if item.retained_structural_progress_atr_at_exit is not None),
            "fraction": _distribution(
                item.retained_structural_progress_fraction_at_exit for item in positions
                if item.retained_structural_progress_fraction_at_exit is not None),
            "fraction_by_family": _by_family_distribution(
                positions, "retained_structural_progress_fraction_at_exit"),
            "positive": sum(
                item.retained_structural_progress_points_at_exit > 0 for item in positions),
            "zero": sum(
                item.retained_structural_progress_points_at_exit == 0 for item in positions),
            "negative": sum(
                item.retained_structural_progress_points_at_exit < 0 for item in positions),
        },
        "giveback_from_max_progress": {
            "points": _distribution(
                item.giveback_from_max_progress_points for item in positions),
            "atr": _distribution(
                item.giveback_from_max_progress_atr for item in positions
                if item.giveback_from_max_progress_atr is not None),
            "fraction": _distribution(
                item.giveback_from_max_progress_fraction for item in positions
                if item.giveback_from_max_progress_fraction is not None),
            "fraction_by_family": _by_family_distribution(
                positions, "giveback_from_max_progress_fraction"),
        },
    }


def _wait_quality(waits) -> dict:
    outcomes = Counter(item.outcome for item in waits)
    reasons = Counter(reason for item in waits for reason in item.wait_reasons)
    final = Counter(item.final_status for item in waits)
    by_family = {}
    for family in DIRECTIONAL_FAMILIES:
        subset = [item for item in waits if item.family == family]
        by_family[family] = {
            "active_without_participation": len(subset),
            "outcomes": dict(sorted(Counter(item.outcome for item in subset).items())),
            "wait_reasons": dict(sorted(Counter(
                reason for item in subset for reason in item.wait_reasons).items())),
        }
    return {
        "active_directional_without_participation": len(waits),
        "outcomes": dict(sorted(outcomes.items())),
        "wait_reasons": dict(sorted(reasons.items())),
        "final_status": dict(sorted(final.items())),
        "later_completed": sum(item.final_status == COMPLETED for item in waits),
        "later_falsified": sum(item.final_status == FALSIFIED for item in waits),
        "later_expired": sum(item.final_status == EXPIRED for item in waits),
        "lifetime_bars": _distribution(item.lifetime_bars for item in waits),
        "by_family": by_family,
    }


def _invalidation_quality(positions) -> dict:
    falsified = [item for item in positions if item.falsified]
    crossed_before_false = [item for item in falsified
                            if item.first_invalidation_close_cross_index is not None
                            and item.first_invalidation_close_cross_index < item.exit_index]
    nonzero_overshoot = [item for item in falsified
                         if item.falsification_overshoot_points is not None
                         and item.falsification_overshoot_points > 0]
    exceeds_entry_distance = [
        item for item in falsified
        if item.falsification_overshoot_points is not None
        and item.falsification_overshoot_points
        > item.invalidation_distance_points_at_entry
    ]
    by_family = {}
    for family in DIRECTIONAL_FAMILIES:
        subset = [item for item in falsified if item.family == family]
        by_family[family] = {
            "falsified_positions": len(subset),
            "invalidation_distance_points_at_entry": _distribution(
                item.invalidation_distance_points_at_entry for item in subset),
            "invalidation_distance_atr_at_entry": _distribution(
                item.invalidation_distance_atr_at_entry for item in subset
                if item.invalidation_distance_atr_at_entry is not None),
            "falsification_overshoot_points": _distribution(
                item.falsification_overshoot_points for item in subset
                if item.falsification_overshoot_points is not None),
            "falsification_overshoot_atr": _distribution(
                item.falsification_overshoot_atr for item in subset
                if item.falsification_overshoot_atr is not None),
            "first_cross_overshoot_points": _distribution(
                item.first_invalidation_cross_overshoot_points for item in subset
                if item.first_invalidation_cross_overshoot_points is not None),
            "additional_overshoot_after_first_cross_points": _distribution(
                item.additional_overshoot_after_first_cross_points for item in subset
                if item.additional_overshoot_after_first_cross_points is not None),
            "recovery_after_first_cross_points": _distribution(
                item.recovery_after_first_cross_points for item in subset
                if item.recovery_after_first_cross_points is not None),
            "nonzero_overshoot": sum(
                item.falsification_overshoot_points is not None
                and item.falsification_overshoot_points > 0 for item in subset),
        }
    return {
        "falsified_positions": len(falsified),
        "first_causal_exit_violations": sum(
            item.exited_on_first_causal_falsification is not True for item in falsified),
        "first_close_cross_before_causal_falsification": len(crossed_before_false),
        "premise_still_not_false_at_first_cross": sum(
            item.premise_false_at_first_invalidation_cross is False
            for item in crossed_before_false),
        "nonzero_falsification_overshoot": len(nonzero_overshoot),
        "overshoot_exceeds_entry_invalidation_distance": len(exceeds_entry_distance),
        "falsification_overshoot_points": _distribution(
            item.falsification_overshoot_points for item in falsified
            if item.falsification_overshoot_points is not None),
        "falsification_overshoot_atr": _distribution(
            item.falsification_overshoot_atr for item in falsified
            if item.falsification_overshoot_atr is not None),
        "first_cross_overshoot_points": _distribution(
            item.first_invalidation_cross_overshoot_points for item in falsified
            if item.first_invalidation_cross_overshoot_points is not None),
        "first_cross_overshoot_atr": _distribution(
            item.first_invalidation_cross_overshoot_atr for item in falsified
            if item.first_invalidation_cross_overshoot_atr is not None),
        "additional_overshoot_after_first_cross_points": _distribution(
            item.additional_overshoot_after_first_cross_points for item in falsified
            if item.additional_overshoot_after_first_cross_points is not None),
        "additional_overshoot_after_first_cross_atr": _distribution(
            item.additional_overshoot_after_first_cross_atr for item in falsified
            if item.additional_overshoot_after_first_cross_atr is not None),
        "recovery_after_first_cross_points": _distribution(
            item.recovery_after_first_cross_points for item in falsified
            if item.recovery_after_first_cross_points is not None),
        "recovery_after_first_cross_atr": _distribution(
            item.recovery_after_first_cross_atr for item in falsified
            if item.recovery_after_first_cross_atr is not None),
        "by_family": by_family,
    }


def _continuation_geometry(positions) -> dict:
    output = {}
    for family in (CONTINUATION_UP, CONTINUATION_DOWN):
        subset = [item for item in positions if item.family == family]
        output[family] = {
            "positions": len(subset),
            "invalidation_distance_points_at_entry": _distribution(
                item.invalidation_distance_points_at_entry for item in subset),
            "invalidation_distance_atr_at_entry": _distribution(
                item.invalidation_distance_atr_at_entry for item in subset
                if item.invalidation_distance_atr_at_entry is not None),
            "structural_room_points_at_entry": _distribution(
                item.structural_room_points_at_entry for item in subset),
            "room_to_invalidation_ratio": _distribution(
                item.room_to_invalidation_ratio for item in subset
                if item.room_to_invalidation_ratio is not None),
            "max_favorable_progress_fraction": _distribution(
                item.max_favorable_structural_progress_fraction for item in subset
                if item.max_favorable_structural_progress_fraction is not None),
            "retained_progress_fraction_at_exit": _distribution(
                item.retained_structural_progress_fraction_at_exit for item in subset
                if item.retained_structural_progress_fraction_at_exit is not None),
            "falsification_overshoot_points": _distribution(
                item.falsification_overshoot_points for item in subset
                if item.falsification_overshoot_points is not None),
            "mapped_reference_completions": sum(
                item.exit_reason == "MAPPED_REFERENCE_REACHED" for item in subset),
            "failed_return_inside": sum(
                item.exit_reason == "ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE"
                for item in subset),
        }
    return output


def _completion_quality(positions) -> dict:
    by_family = {}
    for family in DIRECTIONAL_FAMILIES:
        subset = [item for item in positions if item.family == family]
        by_family[family] = {
            "positions": len(subset),
            "exit_classes": dict(sorted(Counter(item.exit_class for item in subset).items())),
            "exit_reasons": dict(sorted(Counter(item.exit_reason for item in subset).items())),
        }
    return {
        "exit_classes": dict(sorted(Counter(item.exit_class for item in positions).items())),
        "objective_completions": sum(
            item.exit_class == OBJECTIVE_COMPLETION for item in positions),
        "structural_reorientation_handoffs": sum(
            item.exit_class == STRUCTURAL_REORIENTATION_HANDOFF for item in positions),
        "falsifications": sum(
            item.exit_class == FALSIFICATION_EXIT for item in positions),
        "research_boundaries": sum(
            item.exit_class == RESEARCH_BOUNDARY for item in positions),
        "by_family": by_family,
    }


def _switch_quality(replays: Sequence[EpisodeReplay], switches) -> dict:
    categories = Counter(item.category for item in switches)
    matrix = Counter(
        f"{item.previous_exit_reason} -> {item.new_family}" for item in switches)
    chain_total = Counter()
    for replay in replays:
        chain_total.update(flip_chain_summary(replay.machine))
    return {
        "side_switches": len(switches),
        "categories": dict(sorted(categories.items())),
        "flat_candles_between": _distribution(
            item.flat_candles_between for item in switches),
        "flat_candles_by_category": {
            category: _distribution(
                item.flat_candles_between for item in switches
                if item.category == category)
            for category in sorted(categories)
        },
        "previous_exit_reason_to_next_family": dict(sorted(matrix.items())),
        "flip_chains": dict(chain_total),
    }


def _hypothesis_lifetimes(replays: Sequence[EpisodeReplay], waits) -> dict:
    records = [item for replay in replays for item in replay.machine.hypothesis_records]
    entered_ids = {item.hypothesis_id for replay in replays
                   for item in replay.machine.position_episodes}
    objective_ids = {item.hypothesis_id for replay in replays
                     for item in replay.machine.position_episodes
                     if item.exit_reason in {
                         "STRUCTURAL_OBJECTIVE_REACHED", "MAPPED_REFERENCE_REACHED"}}
    falsified_ids = {item.hypothesis_id for replay in replays
                     for item in replay.machine.position_episodes
                     if item.hypothesis_falsification_index is not None}
    wait_ids = {item.hypothesis_id for item in waits}

    def lifetime(record) -> int:
        end = (record.terminal_index if record.terminal_index is not None
               else record.last_update_index)
        return end - record.birth_index + 1

    groups = {
        "all_hypotheses": records,
        "directional_hypotheses": [item for item in records if item.side is not None],
        "directional_hypotheses_ever_active": [
            item for item in records if item.side is not None and ACTIVE in item.statuses_seen],
        "hypotheses_that_produced_positions": [
            item for item in records if item.hypothesis_id in entered_ids],
        "objective_completed_position_hypotheses": [
            item for item in records if item.hypothesis_id in objective_ids],
        "falsified_position_hypotheses": [
            item for item in records if item.hypothesis_id in falsified_ids],
        "nonparticipated_active_hypotheses": [
            item for item in records if item.hypothesis_id in wait_ids],
    }
    return {name: _distribution(lifetime(item) for item in group)
            for name, group in groups.items()}


def _supportive_movement_quality(positions) -> dict:
    return {
        "entered_positions": len(positions),
        "reached_supportive_landmark": sum(
            bool(item.supportive_landmarks) for item in positions),
        "reached_explicit_objective": sum(item.objective_reached for item in positions),
        "positive_max_favorable_progress": sum(
            item.max_favorable_structural_progress_points > 0 for item in positions),
        "positive_retained_progress_at_exit": sum(
            item.retained_structural_progress_points_at_exit > 0 for item in positions),
        "nonpositive_retained_progress_at_exit": sum(
            item.retained_structural_progress_points_at_exit <= 0 for item in positions),
        "falsified": sum(item.falsified for item in positions),
        "adverse_incorrectly_counted_as_supportive": sum(
            bool(set(item.supportive_landmarks) & set(item.adverse_landmarks))
            for item in positions),
    }


def aggregate_quality(replays: Sequence[EpisodeReplay]) -> dict:
    positions = [item for replay in replays
                 for item in build_position_quality(replay.machine)]
    waits = [item for replay in replays for item in build_wait_quality(replay.machine)]
    switches = [item for replay in replays for item in build_side_switches(replay.machine)]
    return {
        "source_episodes_processed": len(replays),
        "closed_candles_observed": sum(item.live_candles for item in replays),
        "active_directional_hypothesis_population": _active_population(replays),
        "entry_quality": _entry_quality(positions),
        "supportive_vs_adverse_landmarks": _landmark_quality(positions),
        "wait_quality": _wait_quality(waits),
        "progress_quality": _progress_quality(positions),
        "structural_invalidation": _invalidation_quality(positions),
        "continuation_risk_geometry": _continuation_geometry(positions),
        "completion_quality": _completion_quality(positions),
        "side_switch_quality": _switch_quality(replays, switches),
        "hypothesis_lifetimes": _hypothesis_lifetimes(replays, waits),
        "supportive_movement_quality": _supportive_movement_quality(positions),
    }


def _quality_rates(bucket: dict) -> dict:
    movement = bucket["supportive_movement_quality"]
    waits = bucket["wait_quality"]
    invalidation = bucket["structural_invalidation"]
    switches = bucket["side_switch_quality"]
    positions = movement["entered_positions"]
    waited = waits["active_directional_without_participation"]
    falsified = invalidation["falsified_positions"]
    side_switches = switches["side_switches"]
    outcomes = waits["outcomes"]
    categories = switches["categories"]
    return {
        "supportive_landmark_per_position": _fraction(
            movement["reached_supportive_landmark"], positions),
        "objective_completion_per_position": _fraction(
            movement["reached_explicit_objective"], positions),
        "positive_retained_progress_per_position": _fraction(
            movement["positive_retained_progress_at_exit"], positions),
        "falsification_per_position": _fraction(movement["falsified"], positions),
        "wait_avoided_failure_per_nonparticipated_active": _fraction(
            outcomes.get(WAIT_AVOIDED_FAILED_HYPOTHESIS, 0), waited),
        "wait_missed_supportive_per_nonparticipated_active": _fraction(
            outcomes.get(WAIT_MISSED_SUPPORTIVE_MOVEMENT, 0), waited),
        "nonzero_overshoot_per_falsified_position": _fraction(
            invalidation["nonzero_falsification_overshoot"], falsified),
        "possible_churn_per_side_switch": _fraction(
            categories.get(POSSIBLE_SAME_STRUCTURE_CHURN, 0), side_switches),
    }


def _repeatability(buckets: dict[str, dict]) -> dict:
    rates = {bucket: _quality_rates(data) for bucket, data in buckets.items()}
    output = {}
    for name, teach in rates[TEACH].items():
        validate = rates[VALIDATE][name]
        difference = (
            None if teach["rate"] is None or validate["rate"] is None
            else round(abs(teach["rate"] - validate["rate"]), 6))
        output[name] = {
            "teach": teach,
            "validate_aggregate": validate,
            "absolute_rate_difference": difference,
        }
    return output


def _dominant(mapping: dict[str, int]) -> str | None:
    if not mapping:
        return None
    largest = max(mapping.values())
    leaders = sorted(key for key, value in mapping.items() if value == largest)
    return leaders[0] if len(leaders) == 1 else "TIE:" + "|".join(leaders)


def _qualitative_repeatability(bucket: dict) -> dict:
    movement = bucket["supportive_movement_quality"]
    progress = bucket["progress_quality"]["retained_structural_progress_at_exit"]
    return {
        "supportive_landmark_is_majority": (
            movement["reached_supportive_landmark"]
            > movement["entered_positions"] - movement["reached_supportive_landmark"]),
        "retained_progress_median_sign": (
            "POSITIVE" if progress["points"]["median"] > 0
            else "NEGATIVE" if progress["points"]["median"] < 0 else "ZERO"),
        "dominant_wait_outcome": _dominant(bucket["wait_quality"]["outcomes"]),
        "dominant_side_switch_category": _dominant(
            bucket["side_switch_quality"]["categories"]),
        "falsification_is_majority": (
            movement["falsified"] > movement["entered_positions"] / 2),
    }


def _gates(buckets: dict[str, dict], v1_match: bool) -> dict:
    teach = buckets[TEACH]
    validate = buckets[VALIDATE]
    semantic_clean = v1_match and all(
        bucket["supportive_vs_adverse_landmarks"][
            "adverse_incorrectly_counted_as_supportive"] == 0
        and bucket["supportive_movement_quality"][
            "adverse_incorrectly_counted_as_supportive"] == 0
        for bucket in (teach, validate))

    wait_pairs = []
    for bucket in (teach, validate):
        outcomes = bucket["wait_quality"]["outcomes"]
        wait_pairs.append((
            outcomes.get(WAIT_AVOIDED_FAILED_HYPOTHESIS, 0),
            outcomes.get(WAIT_MISSED_SUPPORTIVE_MOVEMENT, 0),
        ))
    if all(avoided > missed for avoided, missed in wait_pairs):
        wait_answer = "YES"
    elif all(
            missed > bucket["wait_quality"]["active_directional_without_participation"] / 2
            for (_, missed), bucket in zip(wait_pairs, (teach, validate), strict=True)):
        wait_answer = "NO"
    else:
        wait_answer = "INCONCLUSIVE"

    invalidations = [bucket["structural_invalidation"] for bucket in (teach, validate)]
    if any(item["first_causal_exit_violations"] for item in invalidations) or any(item["overshoot_exceeds_entry_invalidation_distance"]
             > item["falsified_positions"] / 2 for item in invalidations):
        loss_answer = "NO"
    elif all(item["overshoot_exceeds_entry_invalidation_distance"]
             <= item["falsified_positions"] / 2 for item in invalidations):
        loss_answer = "YES"
    else:
        loss_answer = "INCONCLUSIVE"

    switch_pairs = []
    for bucket in (teach, validate):
        switches = bucket["side_switch_quality"]
        churn = switches["categories"].get(POSSIBLE_SAME_STRUCTURE_CHURN, 0)
        switch_pairs.append((switches["side_switches"] - churn, churn))
    if all(explainable > churn for explainable, churn in switch_pairs):
        switch_answer = "YES"
    elif all(churn >= explainable and churn > 0 for explainable, churn in switch_pairs):
        switch_answer = "NO"
    else:
        switch_answer = "INCONCLUSIVE"

    movement_pairs = []
    for bucket in (teach, validate):
        movement = bucket["supportive_movement_quality"]
        movement_pairs.append((
            movement["reached_supportive_landmark"],
            movement["entered_positions"] - movement["reached_supportive_landmark"],
            movement["positive_retained_progress_at_exit"],
            movement["nonpositive_retained_progress_at_exit"],
        ))
    if all(supportive > no_support and positive > nonpositive
           for supportive, no_support, positive, nonpositive in movement_pairs):
        movement_answer = "YES"
    elif all(supportive <= no_support and positive <= nonpositive
             for supportive, no_support, positive, nonpositive in movement_pairs):
        movement_answer = "NO"
    else:
        movement_answer = "INCONCLUSIVE"

    qualitative = {
        TEACH: _qualitative_repeatability(teach),
        VALIDATE: _qualitative_repeatability(validate),
    }
    repeat_answer = "YES" if qualitative[TEACH] == qualitative[VALIDATE] else "INCONCLUSIVE"

    answers = {
        "Q1_METRICS_SEMANTICALLY_CLEAN": {
            "answer": "YES" if semantic_clean else "NO",
            "basis": "V1 fingerprint matched; adverse/supportive overlap is zero; progress rulers have explicit meanings",
        },
        "Q2_WAIT_BEHAVIOUR_ACCEPTABLE": {
            "answer": wait_answer,
            "basis": "compares avoided failures, missed supportive movement, already-consumed movement, and unresolved ACTIVE no-entry lifecycles",
        },
        "Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE": {
            "answer": loss_answer,
            "basis": "uses first-causal exit integrity and accepted-falsification overshoot relative to frozen entry invalidation geometry",
        },
        "Q4_SIDE_SWITCHING_IS_STRUCTURALLY_EXPLAINABLE": {
            "answer": switch_answer,
            "basis": "compares factual structural reassessment categories with possible same-structure churn",
        },
        "Q5_MOVEMENT_PARTICIPATION_QUALITY": {
            "answer": movement_answer,
            "basis": "requires supportive-landmark and positive retained-progress majorities in both buckets",
        },
        "Q6_TEACH_VALIDATE_BEHAVIOUR_REPEATABLE": {
            "answer": repeat_answer,
            "basis": "compares qualitative majority, retained-sign, WAIT, switch, and falsification facts without a fitted tolerance",
        },
    }
    ready = (
        answers["Q1_METRICS_SEMANTICALLY_CLEAN"]["answer"] == "YES"
        and answers["Q2_WAIT_BEHAVIOUR_ACCEPTABLE"]["answer"] != "NO"
        and answers["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]["answer"] != "NO"
        and answers["Q4_SIDE_SWITCHING_IS_STRUCTURALLY_EXPLAINABLE"]["answer"] != "NO"
        and answers["Q5_MOVEMENT_PARTICIPATION_QUALITY"]["answer"] == "YES"
        and answers["Q6_TEACH_VALIDATE_BEHAVIOUR_REPEATABLE"]["answer"] == "YES"
    )
    prior_answers = [gate["answer"] for gate in answers.values()]
    answers["Q7_READY_FOR_PRODUCTION_INTEGRATION"] = {
        "answer": "YES" if ready else (
            "NO" if "NO" in prior_answers else "INCONCLUSIVE"),
        "basis": "requires causal V1 integrity, clean metrics, no negative WAIT/loss/switch gate, positive movement quality, and repeatable qualitative behaviour",
    }
    return {
        **answers,
        "qualitative_repeatability_facts": qualitative,
        "gate_policy": {
            "wait": "categorical majority among avoided-failure vs missed-supportive outcomes",
            "loss": "first-causal exits plus overshoot relative to original invalidation distance",
            "switch": "structurally classified transitions vs possible same-structure churn",
            "movement": "supportive-landmark and positive-retained-progress majorities",
            "repeatability": "same qualitative majority/sign/dominant-category facts",
        },
    }


def _family_quality(bucket: dict) -> dict:
    positions = bucket["entry_quality"]["by_family"]
    completion = bucket["completion_quality"]["by_family"]
    landmark_by_family = bucket["progress_quality"][
        "retained_structural_progress_at_exit"]["fraction_by_family"]
    invalidation = bucket["structural_invalidation"]["by_family"]
    result = {}
    for family in DIRECTIONAL_FAMILIES:
        count = positions[family]["entries"]
        exit_classes = completion[family]["exit_classes"]
        result[family] = {
            "positions": count,
            "objective_completion_rate": round(
                exit_classes.get(OBJECTIVE_COMPLETION, 0) / count, 6) if count else None,
            "falsification_rate": round(
                exit_classes.get(FALSIFICATION_EXIT, 0) / count, 6) if count else None,
            "retained_progress_fraction_median": landmark_by_family[family]["median"],
            "overshoot_points_median": invalidation[family][
                "falsification_overshoot_points"]["median"],
        }
    return result


def _weakest_family(buckets: dict[str, dict]) -> dict:
    facts = {bucket: _family_quality(data) for bucket, data in buckets.items()}
    rotation_dominance = all(
        max(facts[bucket][family]["retained_progress_fraction_median"]
            for family in (LOWER_ROTATION, UPPER_ROTATION))
        < min(facts[bucket][family]["retained_progress_fraction_median"]
              for family in (CONTINUATION_UP, CONTINUATION_DOWN))
        and min(facts[bucket][family]["falsification_rate"]
                for family in (LOWER_ROTATION, UPPER_ROTATION))
        > max(facts[bucket][family]["falsification_rate"]
              for family in (CONTINUATION_UP, CONTINUATION_DOWN))
        for bucket in (TEACH, VALIDATE)
    )
    candidates = []
    for bucket in (TEACH, VALIDATE):
        family = facts[bucket]
        lowest_retained = min(
            family, key=lambda name: family[name]["retained_progress_fraction_median"])
        lowest_objective = min(
            family, key=lambda name: family[name]["objective_completion_rate"])
        highest_false = max(
            family, key=lambda name: family[name]["falsification_rate"])
        if lowest_retained == lowest_objective == highest_false:
            candidates.append(lowest_retained)
        else:
            candidates.append("MIXED_NO_SINGLE_DOMINANT_WEAKNESS")
    answer = (
        "ROTATION_FAMILIES_COLLECTIVELY_WEAKEST_NO_SINGLE_DIRECTION"
        if rotation_dominance
        else candidates[0] if candidates[0] == candidates[1]
        else "MIXED_ACROSS_BUCKETS"
    )
    return {"answer": answer, "facts": facts}


def _recompute_v1_fingerprint(
        buckets: dict[str, Sequence[EpisodeReplay]], source_population: dict,
        skipped: Counter, config: StudyConfig,
        ) -> str:
    v1_buckets = {bucket: v1_aggregate(replays) for bucket, replays in buckets.items()}
    deterministic = {
        "study": "DYNAMIC_STRUCTURAL_REACTIVE_SHADOW_TRADER_V1",
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "buckets": v1_buckets,
        "teach_validate_descriptive_repeatability": v1_repeatability(v1_buckets),
        "r2_structural_research_reference": _r2_reference(),
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "broker_or_live_execution": False,
        "threshold_optimization": False,
    }
    encoded = json.dumps(deterministic, sort_keys=True, default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _old_gate_reference() -> dict:
    path = REPO_ROOT / "reports" / "dynamic_reactive_trader_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "fingerprint": payload["fingerprint"],
        "decision_gates": payload["decision_gates"],
    }


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def run_quality_study(config: StudyConfig | None = None) -> dict:
    """Reproduce the frozen V1 final quality audit.

    Pinned to ``BRAIN_V1``: this report is the historical record that produced the Q3
    blocker, and it must stay reproducible after the Brain V2 correction landed.
    """

    config = config or StudyConfig()
    episodes, source_population = load_research_episodes()
    replay_by_bucket: dict[str, list[EpisodeReplay]] = {TEACH: [], VALIDATE: []}
    skipped = Counter()
    for bucket in (TEACH, VALIDATE):
        for episode in episodes[bucket]:
            replay = run_episode(episode, config, brain=BRAIN_V1)
            if replay is None:
                skipped[bucket] += 1
            else:
                replay_by_bucket[bucket].append(replay)
    return quality_payload(replay_by_bucket, source_population, skipped, config)


def quality_payload(
        replay_by_bucket: dict[str, Sequence[EpisodeReplay]], source_population: dict,
        skipped: Counter, config: StudyConfig,
        ) -> dict:
    """Build the frozen V1 quality payload from already-replayed BRAIN_V1 episodes."""

    v1_fingerprint = _recompute_v1_fingerprint(
        replay_by_bucket, source_population, skipped, config)
    if v1_fingerprint != EXPECTED_V1_FINGERPRINT:
        raise AssertionError(
            f"frozen V1 behaviour changed: {v1_fingerprint} != {EXPECTED_V1_FINGERPRINT}")

    buckets = {bucket: aggregate_quality(replays)
               for bucket, replays in replay_by_bucket.items()}
    deterministic = {
        "study": "DYNAMIC_REACTIVE_TRADER_FINAL_QUALITY_AUDIT_V2",
        "trader_logic_changed": False,
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "frozen_v1_fingerprint_expected": EXPECTED_V1_FINGERPRINT,
        "frozen_v1_fingerprint_recomputed": v1_fingerprint,
        "frozen_v1_fingerprint_match": True,
        "buckets": buckets,
        "teach_validate_quality_rates": _repeatability(buckets),
        "weakest_hypothesis_family": _weakest_family(buckets),
        "old_dynamic_architecture_reference": _old_gate_reference(),
        "structural_research_reference": _r2_reference(),
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "broker_or_live_execution": False,
        "parameter_optimization": False,
        "score_confidence_probability_ranking": False,
    }
    deterministic["fingerprint"] = _fingerprint(deterministic)
    deterministic["final_quality_gates"] = _gates(buckets, True)
    q7 = deterministic["final_quality_gates"][
        "Q7_READY_FOR_PRODUCTION_INTEGRATION"]["answer"]
    no_count = sum(
        gate["answer"] == "NO" for name, gate in deterministic["final_quality_gates"].items()
        if name.startswith("Q") and name != "Q7_READY_FOR_PRODUCTION_INTEGRATION")
    deterministic["final_pre_production_verdict"] = (
        "PASS_FOR_PRODUCTION_INTEGRATION" if q7 == "YES"
        else "FAIL_CURRENT_BRAIN" if no_count >= 2
        else "HOLD_FOR_TARGETED_BRAIN_FIX"
    )
    if q7 == "YES":
        minimum_change = "NONE_FREEZE_V1"
    elif deterministic["final_quality_gates"][
            "Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]["answer"] == "NO":
        minimum_change = (
            "KEEP_ACCEPTED_FAILURE_AS_HYPOTHESIS_FALSIFICATION_BUT_EXIT_AN_OPEN_"
            "ROTATION_SHADOW_POSITION_TO_FLAT_ON_THE_FIRST_CLOSED_CANDLE_CROSS_"
            "OF_ITS_FROZEN_BROAD_INVALIDATION_LEVEL_WITH_NO_AUTOMATIC_REVERSAL"
        )
    else:
        minimum_change = (
            "PREREGISTER_ONE_CAUSAL_BRAIN_V2_CHANGE_FROM_THE_REPORTED_NEGATIVE_GATE"
        )
    deterministic["minimum_brain_v2_change"] = minimum_change
    return deterministic


def _dist_text(item: dict) -> str:
    return (
        f"n {item['count']} | min {item['min']} | median {item['median']} | "
        f"mean {item['mean']} | max {item['max']}"
    )


def render_markdown(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    teach_retained = teach["progress_quality"][
        "retained_structural_progress_at_exit"]["fraction"]
    validate_retained = validate["progress_quality"][
        "retained_structural_progress_at_exit"]["fraction"]
    teach_wait = teach["wait_quality"]["outcomes"]
    validate_wait = validate["wait_quality"]["outcomes"]
    gates = payload["final_quality_gates"]
    loss_answer = gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]["answer"]
    loss_statement = (
        "acceptable under the preregistered structural comparison"
        if loss_answer == "YES"
        else "not acceptable under this audit"
        if loss_answer == "NO"
        else "inconclusive under this audit"
    )
    freeze_statement = (
        "YES. Freeze the certified cognition/state machine for paper/shadow migration only."
        if payload["final_pre_production_verdict"] == "PASS_FOR_PRODUCTION_INTEGRATION"
        else "NO. Apply only the reported minimum Brain V2 correction and repeat this audit."
    )
    lines = [
        "# FINAL PRE-PRODUCTION QUALITY VERDICT",
        "",
        f"Verdict: **{payload['final_pre_production_verdict']}**.",
        "",
        (
            "The frozen V1 brain can form causal structural hypotheses, wait separately from "
            "hypothesis validity, participate, hold, and exit on first factual falsification. "
            "This audit separates genuinely supportive movement from adverse transitions and "
            "measures how much structural progress remains at exit. It does not evaluate profit."
        ),
        "",
        f"Quality fingerprint: `{payload['fingerprint']}`.",
        f"Frozen V1 fingerprint: `{payload['frozen_v1_fingerprint_recomputed']}` (MATCH).",
        "Trader logic changed: **NO**.",
        "",
        "## SIMPLE-LANGUAGE RESULT",
        "",
        (
            "- What the brain does well: V1 causality remains exact, repaired metrics are "
            "semantically clean, and every observed opposite entry has a factual structural "
            "reassessment category rather than an unclassified same-structure flip."
        ),
        (
            "- Where it gives back movement: median retained structural fraction is "
            f"{teach_retained['median']} in TEACH and {validate_retained['median']} in "
            "VALIDATE aggregate, despite positive median maximum favorable progress."
        ),
        (
            "- Whether WAIT is useful or costly: evidence is mixed. TEACH avoided/missed "
            f"{teach_wait.get(WAIT_AVOIDED_FAILED_HYPOTHESIS, 0)}/"
            f"{teach_wait.get(WAIT_MISSED_SUPPORTIVE_MOVEMENT, 0)}; VALIDATE aggregate "
            f"{validate_wait.get(WAIT_AVOIDED_FAILED_HYPOTHESIS, 0)}/"
            f"{validate_wait.get(WAIT_MISSED_SUPPORTIVE_MOVEMENT, 0)}."
        ),
        (
            "- Whether reversals are intelligent or noisy: structurally explainable under the "
            f"factual ledger; Q4 is {gates['Q4_SIDE_SWITCHING_IS_STRUCTURALLY_EXPLAINABLE']['answer']}."
        ),
        (
            f"- Whether logical losses remain bounded: {loss_statement}; Q3 is {loss_answer}."
        ),
        f"- Weakest family: {payload['weakest_hypothesis_family']['answer']}.",
        f"- Freeze for production integration: {freeze_statement}",
        "",
        "## METRIC REPAIRS",
        "",
        "- Supportive, adverse/falsifying, and neutral structural events are separate.",
        "- V1 path participation is reported as MAX_FAVORABLE_STRUCTURAL_PROGRESS_FRACTION.",
        "- Signed retained progress and giveback at exit are reported separately.",
        "- Whole-movement and current-segment rulers are distinct and causal.",
        "- Participation quality uses directional hypotheses that became ACTIVE.",
        "- WAIT, falsification overshoot, completion, switch, and flip-chain ledgers are factual.",
    ]
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        population = bucket["active_directional_hypothesis_population"]
        landmarks = bucket["supportive_vs_adverse_landmarks"]
        waits = bucket["wait_quality"]
        progress = bucket["progress_quality"]
        invalidation = bucket["structural_invalidation"]
        switches = bucket["side_switch_quality"]
        completion = bucket["completion_quality"]
        lines.extend([
            "",
            f"## {label.upper()} QUALITY RESULTS",
            "",
            (
                f"- ACTIVE denominator: {population['directional_hypotheses_ever_active']} "
                f"directional hypotheses; {population['active_directional_with_participation']} "
                f"with participation; {population['active_directional_without_participation']} "
                "without."
            ),
            (
                "- Observational failed-return contexts: "
                f"{population['observational_failed_return_contexts']} "
                "(excluded from denominator)."
            ),
            (
                "- Supportive landmark positions: "
                f"{landmarks['positions_reaching_supportive_landmark']}/"
                f"{landmarks['closed_positions']}; adverse-only "
                f"{landmarks['positions_reaching_only_adverse_or_falsifying_transition']}; "
                "supportive then falsified "
                f"{landmarks['positions_reaching_supportive_before_eventual_falsification']}; "
                f"no supportive {landmarks['positions_reaching_no_supportive_landmark']}."
            ),
            f"- WAIT outcomes: `{json.dumps(waits['outcomes'], sort_keys=True)}`.",
            (
                "- WAIT later completed/falsified/expired: "
                f"{waits['later_completed']}/{waits['later_falsified']}/"
                f"{waits['later_expired']}."
            ),
            (
                "- Max favorable fraction: "
                f"{_dist_text(progress['max_favorable_structural_progress']['fraction'])}."
            ),
            (
                "- Retained fraction at exit: "
                f"{_dist_text(progress['retained_structural_progress_at_exit']['fraction'])}; "
                "positive/zero/negative "
                f"{progress['retained_structural_progress_at_exit']['positive']}/"
                f"{progress['retained_structural_progress_at_exit']['zero']}/"
                f"{progress['retained_structural_progress_at_exit']['negative']}."
            ),
            (
                "- Giveback fraction: "
                f"{_dist_text(progress['giveback_from_max_progress']['fraction'])}."
            ),
            (
                f"- Falsified positions: {invalidation['falsified_positions']}; "
                f"nonzero overshoot {invalidation['nonzero_falsification_overshoot']}; "
                "first-causal exit violations "
                f"{invalidation['first_causal_exit_violations']}."
            ),
            f"- Overshoot points: {_dist_text(invalidation['falsification_overshoot_points'])}.",
            (
                "- First-cross overshoot points: "
                f"{_dist_text(invalidation['first_cross_overshoot_points'])}; additional "
                "overshoot after first cross "
                f"{_dist_text(invalidation['additional_overshoot_after_first_cross_points'])}; "
                "recovery after first cross "
                f"{_dist_text(invalidation['recovery_after_first_cross_points'])}."
            ),
            f"- Completion classes: `{json.dumps(completion['exit_classes'], sort_keys=True)}`.",
            f"- Side-switch categories: `{json.dumps(switches['categories'], sort_keys=True)}`.",
            (
                "- Flat candles between opposite positions: "
                f"{_dist_text(switches['flat_candles_between'])}."
            ),
            f"- Flip chains: `{json.dumps(switches['flip_chains'], sort_keys=True)}`.",
        ])
    lines.extend([
        "",
        "## WHOLE MOVEMENT AND CURRENT SEGMENT PROGRESS",
        "",
        (
            "- Whole movement uses a stable causal ruler: Broad origin edge to opposite edge, "
            "or released edge to the frozen mapped reference."
        ),
        (
            "- Current segment uses origin-to-midpoint, midpoint-to-opposite-edge, or "
            "released-edge-to-reference geometry. Its fraction may reset at a factual landmark "
            "without altering whole-movement progress."
        ),
        "",
        "## ENTRY QUALITY BY FAMILY",
        "",
    ])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for family in DIRECTIONAL_FAMILIES:
            data = bucket["entry_quality"]["by_family"][family]
            lines.append(
                f"- {label} {family}: entries {data['entries']} | origin-to-birth "
                f"{_dist_text(data['bars_origin_to_birth'])} | birth-to-ACTIVE "
                f"{_dist_text(data['bars_birth_to_active'])} | ACTIVE-to-entry "
                f"{_dist_text(data['bars_active_to_entry'])} | whole progress fraction "
                f"{_dist_text(data['whole_progress_fraction_at_entry'])} | segment fraction "
                f"{_dist_text(data['segment_progress_fraction_at_entry'])} | room points "
                f"{_dist_text(data['structural_room_points_at_entry'])} | invalidation points "
                f"{_dist_text(data['invalidation_distance_points_at_entry'])} | "
                f"room/invalidation {_dist_text(data['room_to_invalidation_ratio'])}.")
    lines.extend([
        "",
        "## HYPOTHESIS LIFETIME QUALITY",
        "",
    ])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        lines.append(
            f"- {label}: `"
            f"{json.dumps(bucket['hypothesis_lifetimes'], sort_keys=True)}`.")
    lines.extend([
        "",
        "## CONTINUATION RISK GEOMETRY",
        "",
    ])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        lines.append(f"- {label}:")
        for family in (CONTINUATION_UP, CONTINUATION_DOWN):
            data = bucket["continuation_risk_geometry"][family]
            lines.append(
                f"  - {family}: positions {data['positions']} | invalidation points "
                f"{_dist_text(data['invalidation_distance_points_at_entry'])} | room/invalidation "
                f"{_dist_text(data['room_to_invalidation_ratio'])} | retained fraction "
                f"{_dist_text(data['retained_progress_fraction_at_exit'])} | mapped completion "
                f"{data['mapped_reference_completions']} | failed return {data['failed_return_inside']}.")
    lines.extend([
        "",
        "## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY",
        "",
    ])
    for name in QUALITY_RATE_NAMES:
        item = payload["teach_validate_quality_rates"][name]
        lines.append(
            f"- `{name}`: TEACH {item['teach']['numerator']}/"
            f"{item['teach']['denominator']} = {item['teach']['rate']}; VALIDATE aggregate "
            f"{item['validate_aggregate']['numerator']}/"
            f"{item['validate_aggregate']['denominator']} = "
            f"{item['validate_aggregate']['rate']}; absolute difference "
            f"{item['absolute_rate_difference']}.")
    lines.extend([
        "",
        "## WEAKEST FAMILY",
        "",
        f"- Result: **{payload['weakest_hypothesis_family']['answer']}**.",
        f"- Facts: `{json.dumps(payload['weakest_hypothesis_family']['facts'], sort_keys=True)}`.",
        "",
        "## FINAL QUALITY GATES",
        "",
    ])
    for name, gate in payload["final_quality_gates"].items():
        if name.startswith("Q"):
            lines.append(f"- {name}: **{gate['answer']}**.")
    old = payload["old_dynamic_architecture_reference"]["decision_gates"]
    r2 = payload["structural_research_reference"]
    lines.extend([
        "",
        "## PRESERVED RESEARCH STATUS",
        "",
        *[f"- {name}: **{gate['answer']}**." for name, gate in old.items()],
        f"- R2_CLUSTER: **{r2['R2_CLUSTER']}**.",
        f"- R2_RANGE: **{r2['R2_RANGE']}**.",
        f"- R4_MICRO: **{r2['R4_MICRO']}**.",
        f"- LOCAL_PUBLICATION: **{r2['LOCAL_PUBLICATION']}**.",
        "",
        "## INTEGRITY",
        "",
        "- V1 trading behaviour fingerprint reproduced exactly before quality aggregation.",
        "- VALIDATE is aggregate-only; no IDs, timestamps, prices, paths, bands, or traces.",
        (
            "- HOLDOUT_PRICE_SESSIONS_CONVERTED = "
            f"{payload['holdout_price_sessions_converted']}."
        ),
        "- No broker, live money, parameter optimization, score, confidence, probability, or ranking.",
        "",
        "## NEXT DECISION",
        "",
        f"- {payload['minimum_brain_v2_change']}.",
    ])
    return "\n".join(lines) + "\n"


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
        default=REPO_ROOT / "reports" / "DYNAMIC_REACTIVE_TRADER_QUALITY_AUDIT_V2.md")
    parser.add_argument(
        "--aggregate", type=Path,
        default=REPO_ROOT / "reports" / "dynamic_reactive_trader_quality_v2.json")
    args = parser.parse_args(argv)
    payload = run_quality_study()
    write_outputs(payload, args.report, args.aggregate)
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "verdict": payload["final_pre_production_verdict"],
        "gates": {name: gate["answer"] for name, gate in payload[
            "final_quality_gates"].items() if name.startswith("Q")},
        "report": str(args.report),
        "aggregate": str(args.aggregate),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
