from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.livemap.shadow import (
    COMPLETED,
    CONTINUATION_UP,
    DOWN,
    FAILED_UP_RETURN,
    LOWER_ROTATION,
    SHADOW_LONG,
    TEACH,
    UP,
    UPPER_ROTATION,
    DynamicShadowTrader,
    MicroFact,
)
from src.livemap.shadow_quality import (
    ADVERSE_TRANSITION,
    FAILED_RELEASE_REASSESSMENT,
    FALSIFICATION_EXIT,
    NEW_STRUCTURE_REORIENTATION,
    OBJECTIVE_COMPLETION,
    POSSIBLE_SAME_STRUCTURE_CHURN,
    SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION,
    STRUCTURALLY_JUSTIFIED_REASSESSMENT,
    SUPPORTIVE_TRANSITION,
    WAIT_AT_ALREADY_CONSUMED_MOVEMENT,
    WAIT_AVOIDED_FAILED_HYPOTHESIS,
    WAIT_MISSED_SUPPORTIVE_MOVEMENT,
    SideSwitchRecord,
    active_directional_population,
    build_position_quality,
    build_side_switches,
    build_wait_quality,
    classify_side_switch,
    flip_chain_summary,
    movement_progress,
    summarize_alternating_chains,
)
from tests.test_dynamic_shadow import ref, release, truth


def failed_lower_rotation(*, with_progress: bool = False) -> DynamicShadowTrader:
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    if with_progress:
        machine.observe_truth(truth(2, "106"))
        failed_index = 3
    else:
        failed_index = 2
    machine.observe_truth(truth(
        failed_index, "98", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True,
        releases=(release(DOWN, edge="100"),), below=(ref(DOWN, "90"),),
        source_end=True,
    ))
    return machine


def completed_lower_rotation() -> DynamicShadowTrader:
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    machine.observe_truth(truth(2, "106"))
    machine.observe_truth(truth(
        3, "111", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        4, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True))
    return machine


def test_adverse_falsifying_transition_never_counts_as_supportive_landmark():
    quality = build_position_quality(failed_lower_rotation())[0]

    assert quality.supportive_landmarks == ()
    assert ADVERSE_TRANSITION in quality.adverse_landmarks
    assert quality.falsified is True


def test_supportive_transition_and_objective_completion_are_classified_correctly():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    machine.observe_truth(truth(
        2, "111", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),),
        above=(ref(UP, "120"),), source_end=True))

    quality = build_position_quality(machine)[0]
    assert SUPPORTIVE_TRANSITION in quality.supportive_landmarks
    assert quality.objective_reached is True
    assert quality.exit_class == OBJECTIVE_COMPLETION
    assert quality.raw_directional_progress_points_at_exit == Decimal(10)
    assert quality.retained_structural_progress_points_at_exit == Decimal(9)
    assert quality.giveback_from_max_progress_points == 0


def test_max_favorable_retained_and_giveback_are_distinct_and_retained_can_be_negative():
    quality = build_position_quality(failed_lower_rotation(with_progress=True))[0]

    assert quality.max_favorable_structural_progress_points == Decimal(5)
    assert quality.retained_structural_progress_points_at_exit == Decimal(-3)
    assert quality.giveback_from_max_progress_points == Decimal(8)
    assert quality.max_favorable_structural_progress_fraction == pytest.approx(5 / 9)
    assert quality.retained_structural_progress_fraction_at_exit == pytest.approx(-3 / 9)
    assert quality.giveback_from_max_progress_fraction == pytest.approx(8 / 9)


def test_whole_movement_ruler_stays_stable_when_segment_changes_at_midpoint():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    before = machine.observe_truth(truth(1, "104"))
    after = machine.observe_truth(truth(2, "106", source_end=True))

    before_progress = movement_progress(before)
    after_progress = movement_progress(after)
    assert before_progress.whole_available_points == Decimal(10)
    assert after_progress.whole_available_points == Decimal(10)
    assert before_progress.whole_progress_fraction == pytest.approx(0.4)
    assert after_progress.whole_progress_fraction == pytest.approx(0.6)
    assert before_progress.segment_progress_fraction == pytest.approx(0.8)
    assert after_progress.segment_progress_fraction == pytest.approx(0.2)


def test_movement_progress_snapshot_is_frozen_and_prefix_stable():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    decision = machine.observe_truth(truth(1, "104"))
    frozen = movement_progress(decision)
    machine.observe_truth(truth(2, "106", source_end=True))

    assert movement_progress(decision) == frozen
    with pytest.raises(FrozenInstanceError):
        frozen.whole_progress_fraction = 1.0  # type: ignore[misc]


def test_active_directional_denominator_excludes_failed_return_observation_context():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True,
        source_end=True))

    population = active_directional_population(machine)
    assert population["total_hypotheses"] == 3
    assert population["directional_hypotheses"] == 2
    assert population["directional_hypotheses_ever_active"] == 1
    assert population["observational_failed_return_contexts"] == 1
    assert any(item.family == FAILED_UP_RETURN for item in machine.hypothesis_records)


def test_waiting_continuation_that_falsifies_is_an_avoided_failed_hypothesis():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True,
        source_end=True))

    waited = next(item for item in build_wait_quality(machine)
                  if item.family == CONTINUATION_UP)
    assert waited.outcome == WAIT_AVOIDED_FAILED_HYPOTHESIS
    assert waited.final_status == "FALSIFIED"


def test_waiting_continuation_that_reaches_reference_is_missed_supportive_movement():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "120", broad=False, location="NO_STRUCTURE",
        above=(ref(UP, "120"),), source_end=True))

    waited = build_wait_quality(machine)[0]
    assert waited.outcome == WAIT_MISSED_SUPPORTIVE_MOVEMENT
    assert waited.final_status == COMPLETED
    assert "MAPPED_REFERENCE_REACHED" in waited.supportive_landmarks


def test_late_rotation_wait_is_classified_as_already_consumed_movement():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "106"))
    machine.observe_truth(truth(
        2, "110", location="AT_UPPER_EDGE", approaching_upper=True,
        source_end=True))

    waited = next(item for item in build_wait_quality(machine)
                  if item.family == LOWER_ROTATION)
    assert waited.outcome == WAIT_AT_ALREADY_CONSUMED_MOVEMENT
    assert "FIRST_STRUCTURAL_SEGMENT_ALREADY_CONSUMED" in waited.wait_reasons


def test_falsification_overshoot_uses_accepted_close_and_exit_is_still_first_causal():
    quality = build_position_quality(failed_lower_rotation())[0]

    assert quality.invalidation_level == Decimal(100)
    assert quality.first_invalidation_close_cross_index == quality.exit_index
    assert quality.premise_false_at_first_invalidation_cross is True
    assert quality.falsification_overshoot_points == Decimal(2)
    assert quality.falsification_overshoot_atr == 1.0
    assert quality.first_invalidation_cross_overshoot_points == Decimal(2)
    assert quality.additional_overshoot_after_first_cross_points == 0
    assert quality.recovery_after_first_cross_points == 0
    assert quality.exited_on_first_causal_falsification is True
    assert quality.exit_class == FALSIFICATION_EXIT


def test_acceptance_delay_separates_first_cross_from_additional_falsification_overshoot():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    crossed_but_not_false = machine.observe_truth(truth(2, "99"))
    machine.observe_truth(truth(
        3, "98", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True, releases=(release(DOWN, edge="100"),),
        below=(ref(DOWN, "90"),), source_end=True))

    quality = build_position_quality(machine)[0]
    assert crossed_but_not_false.position.state == SHADOW_LONG
    assert quality.first_invalidation_close_cross_index == 2
    assert quality.premise_false_at_first_invalidation_cross is False
    assert quality.first_invalidation_cross_overshoot_points == Decimal(1)
    assert quality.falsification_overshoot_points == Decimal(2)
    assert quality.additional_overshoot_after_first_cross_points == Decimal(1)
    assert quality.recovery_after_first_cross_points == 0


def test_recovery_after_first_cross_is_not_negative_additional_overshoot():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    machine.observe_truth(truth(2, "97"))
    machine.observe_truth(truth(
        3, "98.5", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True, releases=(release(DOWN, edge="100"),),
        below=(ref(DOWN, "90"),), source_end=True))

    quality = build_position_quality(machine)[0]

    assert quality.first_invalidation_cross_overshoot_points == Decimal(3)
    assert quality.falsification_overshoot_points == Decimal("1.5")
    assert quality.additional_overshoot_after_first_cross_points == 0
    assert quality.recovery_after_first_cross_points == Decimal("1.5")


@pytest.mark.parametrize(("facts", "expected"), (
    ({
        "same_structure": True,
        "previous_family": LOWER_ROTATION,
        "previous_exit_reason": "STRUCTURAL_OBJECTIVE_REACHED",
        "new_family": UPPER_ROTATION,
        "opposite_edge_observed": True,
        "accepted_break_observed": False,
        "failed_release_observed": False,
        "controlling_structure_changed": False,
    }, SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION),
    ({
        "same_structure": False,
        "previous_family": LOWER_ROTATION,
        "previous_exit_reason": "CONTROLLING_STRUCTURE_CHANGED",
        "new_family": UPPER_ROTATION,
        "opposite_edge_observed": False,
        "accepted_break_observed": False,
        "failed_release_observed": False,
        "controlling_structure_changed": True,
    }, NEW_STRUCTURE_REORIENTATION),
    ({
        "same_structure": True,
        "previous_family": CONTINUATION_UP,
        "previous_exit_reason": "ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE",
        "new_family": UPPER_ROTATION,
        "opposite_edge_observed": False,
        "accepted_break_observed": False,
        "failed_release_observed": True,
        "controlling_structure_changed": False,
    }, FAILED_RELEASE_REASSESSMENT),
    ({
        "same_structure": True,
        "previous_family": LOWER_ROTATION,
        "previous_exit_reason": "OTHER",
        "new_family": UPPER_ROTATION,
        "opposite_edge_observed": False,
        "accepted_break_observed": False,
        "failed_release_observed": False,
        "controlling_structure_changed": False,
    }, POSSIBLE_SAME_STRUCTURE_CHURN),
    ({
        "same_structure": True,
        "previous_family": LOWER_ROTATION,
        "previous_exit_reason": "OTHER",
        "new_family": CONTINUATION_UP,
        "opposite_edge_observed": False,
        "accepted_break_observed": True,
        "failed_release_observed": False,
        "controlling_structure_changed": False,
    }, STRUCTURALLY_JUSTIFIED_REASSESSMENT),
))
def test_side_switch_structural_classifications(facts, expected):
    assert classify_side_switch(**facts) == expected


def test_same_structure_opposite_edge_rotation_is_found_from_real_shadow_ledger():
    machine = completed_lower_rotation()
    machine.observe_truth(truth(5, "108"))
    machine.observe_truth(truth(6, "107", source_end=True))

    switches = build_side_switches(machine)
    assert len(switches) == 1
    assert switches[0].category == SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION
    assert switches[0].flat_candles_between == 1
    assert switches[0].new_entry_index > switches[0].exit_index


def test_failed_release_reassessment_requires_later_independent_opposite_entry():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    entered = machine.observe_truth(truth(
        1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))
    exited = machine.observe_truth(truth(
        2, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True))
    reversed_later = machine.observe_truth(truth(3, "108"))
    machine.observe_truth(truth(4, "107", source_end=True))

    switches = build_side_switches(machine)
    assert entered.position.state == SHADOW_LONG
    assert exited.position.state == "FLAT"
    assert reversed_later.index > exited.index
    assert switches[0].category == FAILED_RELEASE_REASSESSMENT
    assert switches[0].new_entry_index > switches[0].exit_index


def _switch(exit_index: int, entry_index: int, category: str) -> SideSwitchRecord:
    return SideSwitchRecord(
        "teach-EP001", LOWER_ROTATION, UP, "EXIT", "C01", exit_index,
        entry_index - 1, entry_index, entry_index, 0, UPPER_ROTATION, DOWN,
        "C01", True, ("OPPOSITE_EDGE",), category)


def test_alternating_flip_chain_detection_separates_meaningful_and_possible_churn():
    positions = tuple(
        SimpleNamespace(
            hypothesis_id=f"H{index}", side=(UP if index % 2 else DOWN),
            entry_index=index * 2 - 1, exit_index=index * 2,
        )
        for index in range(1, 5)
    )
    switches = (
        _switch(2, 3, SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION),
        _switch(4, 5, POSSIBLE_SAME_STRUCTURE_CHURN),
        _switch(6, 7, STRUCTURALLY_JUSTIFIED_REASSESSMENT),
    )
    summary = summarize_alternating_chains(
        positions, switches, {f"H{index}": "C01" for index in range(1, 5)})

    assert summary["four_or_more_alternating_chains"] == 1
    assert summary["chains_same_broad_structure"] == 1
    assert summary["chains_with_meaningful_events_between_every_side"] == 0


def test_real_chain_summary_detects_no_same_candle_reversal():
    machine = completed_lower_rotation()
    machine.observe_truth(truth(5, "108"))
    machine.observe_truth(truth(6, "107", source_end=True))

    assert flip_chain_summary(machine)["two_position_alternating_chains"] == 1
    assert all(item.new_entry_index > item.exit_index
               for item in build_side_switches(machine))


def test_micro_confirmation_still_cannot_create_participation_in_quality_audit():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    decision = machine.observe_truth(truth(
        0, "105", micro=MicroFact(
            "CONFIRMED", "M01", Decimal(104), Decimal(106), ("MICRO_CREATED",)),
        source_end=True))

    assert decision.position.state == "FLAT"
    assert not machine.position_episodes
    assert not build_position_quality(machine)
