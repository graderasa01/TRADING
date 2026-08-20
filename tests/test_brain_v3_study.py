"""The Brain V3 final audit's ledgers and gates, on deterministic synthetic replays.

The ledger that matters most is `_filtered_rotation_ledger`: it must be able to say what
Brain V2 actually got from the rotations Brain V3 refuses, because an entry count on its
own cannot distinguish a filter that removed weak participation from one that missed
good movement.
"""

from __future__ import annotations

import json

import pytest

from src.livemap.shadow import (
    BRAIN_V1,
    BRAIN_V2,
    BRAIN_V3,
    LOWER_ROTATION,
    TEACH,
    VALIDATE,
    DynamicShadowTrader,
)
from src.livemap.shadow_quality import OBJECTIVE_COMPLETION, POSITION_RISK_EXIT
from tools.dynamic_reactive_trader_brain_v2_study import (
    _bucket_quality_with_positions,
    _brain_delta,
    _loss_gate,
)
from tools.dynamic_reactive_trader_brain_v3_study import (
    FILTERED_LATER_COMPLETED,
    FILTERED_LATER_FALSIFIED,
    _continuation_invariance,
    _filtered_rotation_ledger,
    _hypothesis_facts,
    _hypothesis_population_invariance,
    _rotation_confirmation_ledger,
    _rotation_family_quality,
    _v3_gates,
    render_markdown,
)
from tools.dynamic_reactive_trader_quality_study import _fingerprint, _repeatability
from tools.dynamic_reactive_trader_study import EpisodeReplay
from tests.test_dynamic_shadow import ref, release, truth


def episode(bucket: str, episode_id: str, brain: str, stream) -> EpisodeReplay:
    machine = DynamicShadowTrader(bucket, episode_id, brain=brain)
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def weak_rotation(bucket: str, episode_id: str) -> tuple:
    """V2 joins on activation and is stopped out; V3 never confirms, so never joins."""

    return (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
              bucket=bucket, source_episode_id=episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=episode_id),
        truth(2, "99", location="BELOW", bucket=bucket, source_episode_id=episode_id),
        truth(3, "97", broad=False, location="NO_STRUCTURE",
              map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
              accepted="down", left=True, releases=(release("down", edge="100"),),
              below=(ref("down", "90"),), source_end=True,
              bucket=bucket, source_episode_id=episode_id),
    )


def strong_rotation(bucket: str, episode_id: str) -> tuple:
    """Both brains join; V3 one candle later, and the rotation reaches its objective."""

    return (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
              bucket=bucket, source_episode_id=episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=episode_id),
        truth(2, "102", bucket=bucket, source_episode_id=episode_id),
        truth(3, "110", location="AT_UPPER_EDGE", approaching_upper=True,
              source_end=True, bucket=bucket, source_episode_id=episode_id),
    )


def universe(brain: str) -> tuple[dict, dict]:
    buckets: dict[str, dict] = {}
    facts: dict[str, dict] = {}
    for bucket, prefix in ((TEACH, "teach"), (VALIDATE, "validate")):
        replays = (
            episode(bucket, f"{prefix}-EP001", brain, weak_rotation(bucket, f"{prefix}-EP001")),
            episode(bucket, f"{prefix}-EP002", brain, strong_rotation(bucket, f"{prefix}-EP002")),
        )
        aggregated, positions = _bucket_quality_with_positions(replays)
        buckets[bucket] = aggregated
        facts[bucket] = _hypothesis_facts(replays, positions)
    return buckets, facts


def test_the_filtered_ledger_reports_what_v2_got_from_the_refused_rotations():
    _, v2_facts = universe(BRAIN_V2)
    _, v3_facts = universe(BRAIN_V3)
    ledger = _filtered_rotation_ledger(v2_facts[TEACH], v3_facts[TEACH])

    assert ledger["rotation_entries_v2"] == 2
    assert ledger["rotation_entries_v3"] == 1
    assert ledger["filtered_out_by_v3"] == 1
    assert ledger["newly_admitted_by_v3"] == 0
    assert ledger["entered_under_both"] == 1

    got = ledger["what_v2_got_from_the_filtered_hypotheses"]
    assert got["positions"] == 1
    assert got["exit_classes"] == {POSITION_RISK_EXIT: 1}
    assert got["retained_negative"] == 1
    assert got["objective_reached"] == 0


def test_the_filtered_ledger_also_reports_the_refused_hypotheses_later_lifecycle():
    _, v2_facts = universe(BRAIN_V2)
    _, v3_facts = universe(BRAIN_V3)
    ledger = _filtered_rotation_ledger(v2_facts[TEACH], v3_facts[TEACH])

    assert ledger["filtered_hypothesis_later_outcomes"] == {FILTERED_LATER_FALSIFIED: 1}
    assert ledger["filtered_hypotheses_that_never_confirmed"] == 1


def test_a_refused_rotation_that_later_completes_is_reported_as_missed_movement():
    """The ledger must be able to say the filter was wrong, not only that it was right."""

    v2_facts = {"H": {"family": LOWER_ROTATION, "entered": True, "entry_index": 1,
                      "exit_class": OBJECTIVE_COMPLETION, "exit_reason": "X",
                      "supportive_landmarks": True, "objective_reached": True,
                      "max_favorable_fraction": 1.0, "retained_fraction": 1.0,
                      "retained_points": 9, "giveback_fraction": 0.0,
                      "active_bars": 3, "bars_active_to_entry": 0,
                      "whole_progress_at_entry": 0.1, "segment_progress_at_entry": 0.2,
                      "risk_overshoot_points": None}}
    v3_facts = {"H": {"family": LOWER_ROTATION, "entered": False, "entry_index": None,
                      "final_state": "COMPLETED", "supportive_movement": True,
                      "rotation_confirmed": False}}
    ledger = _filtered_rotation_ledger(v2_facts, v3_facts)

    assert ledger["filtered_out_by_v3"] == 1
    assert ledger["filtered_hypothesis_later_outcomes"] == {FILTERED_LATER_COMPLETED: 1}
    assert ledger["filtered_hypotheses_with_supportive_movement_missed"] == 1
    assert ledger["what_v2_got_from_the_filtered_hypotheses"]["objective_reached"] == 1
    assert ledger["what_v2_got_from_the_filtered_hypotheses"]["retained_positive"] == 1


def test_the_confirmation_ledger_separates_confirmed_from_never_confirmed():
    _, v3_facts = universe(BRAIN_V3)
    ledger = _rotation_confirmation_ledger(v3_facts[TEACH])

    assert ledger["active_rotation_hypotheses"] == 2
    assert ledger["received_confirmation"] == 1
    assert ledger["confirmed_and_entered"] == 1
    assert ledger["never_confirmed"] == 1
    assert ledger["never_confirmed_outcomes"] == {FILTERED_LATER_FALSIFIED: 1}


def test_v2_never_receives_the_rotation_confirmation_fact():
    _, v2_facts = universe(BRAIN_V2)
    ledger = _rotation_confirmation_ledger(v2_facts[TEACH])

    assert ledger["received_confirmation"] == 0
    assert ledger["confirmed_and_entered"] == 0


def test_lower_and_upper_rotations_are_reported_separately():
    _, v3_facts = universe(BRAIN_V3)
    quality = _rotation_family_quality(v3_facts[TEACH])

    assert set(quality) == {"ROTATION_FROM_LOWER_AREA", "ROTATION_FROM_UPPER_AREA"}
    assert quality["ROTATION_FROM_LOWER_AREA"]["positions"] == 1
    assert quality["ROTATION_FROM_UPPER_AREA"]["positions"] == 0


def test_the_hypothesis_population_is_identical_across_brains():
    """The filtered ledger matches hypotheses by identity, so this must hold."""

    _, v2_facts = universe(BRAIN_V2)
    _, v3_facts = universe(BRAIN_V3)

    for bucket in (TEACH, VALIDATE):
        invariance = _hypothesis_population_invariance(v2_facts[bucket], v3_facts[bucket])
        assert invariance["identical"] is True
        assert invariance["identity_symmetric_difference"] == 0
        assert invariance["lifecycle_mismatches"] == 0


def test_continuation_invariance_reports_identical_when_nothing_moved():
    _, v2_facts = universe(BRAIN_V2)
    _, v3_facts = universe(BRAIN_V3)

    assert _continuation_invariance(v2_facts[TEACH], v3_facts[TEACH])["identical"] is True


def test_continuation_invariance_reports_a_difference_rather_than_hiding_it():
    v2_facts = {"C": {"family": "OUTSIDE_CONTINUATION_UP", "entered": True,
                      "entry_index": 3, "exit_index": 6, "exit_reason": "A",
                      "retained_fraction": 0.5}}
    v3_facts = {"C": {"family": "OUTSIDE_CONTINUATION_UP", "entered": True,
                      "entry_index": 4, "exit_index": 6, "exit_reason": "A",
                      "retained_fraction": 0.4}}
    result = _continuation_invariance(v2_facts, v3_facts)

    assert result["identical"] is False
    assert result["by_family"]["OUTSIDE_CONTINUATION_UP"][
        "common_entries_with_a_different_entry_exit_or_reason"] == 1


def test_the_v3_gates_reuse_the_frozen_definitions_and_grade_all_three_brains():
    v1_buckets, _ = universe(BRAIN_V1)
    v2_buckets, _ = universe(BRAIN_V2)
    v3_buckets, _ = universe(BRAIN_V3)
    gates = _v3_gates(v3_buckets, v2_buckets, v1_buckets)
    loss = gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]

    assert loss["answer"] == _loss_gate(v3_buckets)["answer"]
    assert loss["same_rule_recomputed_on_v1"]["answer"] == _loss_gate(v1_buckets)["answer"]
    assert loss["same_rule_recomputed_on_v2"]["answer"] == _loss_gate(v2_buckets)["answer"]
    for number in (1, 2, 3, 4, 5, 6, 7):
        assert any(name.startswith(f"Q{number}_") for name in gates)


def test_q7_is_never_yes_while_any_earlier_gate_answers_no():
    v1_buckets, _ = universe(BRAIN_V1)
    v2_buckets, _ = universe(BRAIN_V2)
    v3_buckets, _ = universe(BRAIN_V3)
    gates = _v3_gates(v3_buckets, v2_buckets, v1_buckets)
    negative = [name for name, gate in gates.items()
                if name.startswith("Q") and gate["answer"] == "NO"]

    if negative:
        assert gates["Q7_READY_FOR_PRODUCTION_INTEGRATION"]["answer"] != "YES"


def test_validate_output_stays_aggregate_only():
    v3_buckets, v3_facts = universe(BRAIN_V3)
    _, v2_facts = universe(BRAIN_V2)
    serialised = {
        "bucket": v3_buckets[VALIDATE],
        "filtered": _filtered_rotation_ledger(v2_facts[VALIDATE], v3_facts[VALIDATE]),
        "confirmation": _rotation_confirmation_ledger(v3_facts[VALIDATE]),
        "rotation": _rotation_family_quality(v3_facts[VALIDATE]),
        "continuation": _continuation_invariance(v2_facts[VALIDATE], v3_facts[VALIDATE]),
        "population": _hypothesis_population_invariance(
            v2_facts[VALIDATE], v3_facts[VALIDATE]),
    }
    encoded = json.dumps(serialised, sort_keys=True, default=str)
    forbidden = {
        "source_episode_id", "hypothesis_id", "structure_id", "entry_index",
        "exit_index", "timestamp", "at", "price", "band", "trace", "path",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in forbidden
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(serialised)
    assert "validate-EP" not in encoded
    assert "2026-" not in encoded


def test_the_audit_is_deterministic_and_the_report_states_the_stop_rule():
    v1_buckets, _ = universe(BRAIN_V1)
    v2_buckets, v2_facts = universe(BRAIN_V2)
    v3_buckets, v3_facts = universe(BRAIN_V3)

    def payload() -> dict:
        deterministic = {
            "study": "DYNAMIC_REACTIVE_TRADER_BRAIN_V3_FINAL_AUDIT",
            "brain_under_audit": BRAIN_V3,
            "brain_control": BRAIN_V2,
            "targeted_change": "ROTATION_POST_ACTIVATION_CONFIRMATION",
            "final_historical_development_attempt": True,
            "config": {"history": 400},
            "source_population": {},
            "source_episodes_shorter_than_or_equal_to_history": {},
            "frozen_v1_behaviour_fingerprint_expected": "bf497495e394bb87",
            "frozen_v1_behaviour_fingerprint_recomputed": "bf497495e394bb87",
            "frozen_v1_quality_fingerprint_expected": "bf54631ee9c200e9",
            "frozen_v1_quality_fingerprint_recomputed": "bf54631ee9c200e9",
            "frozen_brain_v2_fingerprint_expected": "8e2d85d387843a57",
            "frozen_brain_v2_fingerprint_recomputed": "8e2d85d387843a57",
            "frozen_fingerprints_match": True,
            "buckets": v3_buckets,
            "v2_control_buckets": v2_buckets,
            "brain_v2_vs_v3": {
                bucket: _brain_delta(v2_buckets[bucket], v3_buckets[bucket])
                for bucket in (TEACH, VALIDATE)},
            "brain_v2_vs_v3_arm_names": {"v1": BRAIN_V2, "v2": BRAIN_V3},
            "filtered_rotation_ledger": {
                bucket: _filtered_rotation_ledger(v2_facts[bucket], v3_facts[bucket])
                for bucket in (TEACH, VALIDATE)},
            "rotation_confirmation_ledger": {
                bucket: _rotation_confirmation_ledger(v3_facts[bucket])
                for bucket in (TEACH, VALIDATE)},
            "rotation_family_quality": {
                bucket: {"v2": _rotation_family_quality(v2_facts[bucket]),
                         "v3": _rotation_family_quality(v3_facts[bucket])}
                for bucket in (TEACH, VALIDATE)},
            "continuation_invariance": {
                bucket: _continuation_invariance(v2_facts[bucket], v3_facts[bucket])
                for bucket in (TEACH, VALIDATE)},
            "hypothesis_population_invariance": {
                bucket: _hypothesis_population_invariance(
                    v2_facts[bucket], v3_facts[bucket])
                for bucket in (TEACH, VALIDATE)},
            "teach_validate_quality_rates": _repeatability(v3_buckets),
            "weakest_hypothesis_family": {"answer": "MIXED", "facts": {}},
            "old_dynamic_architecture_reference": {
                "fingerprint": "bf497495e394bb87",
                "decision_gates": {"D5_NO_AUTOMATIC_REVERSAL": {"answer": "YES"}}},
            "structural_research_reference": {
                "fingerprint": "5ebd256debc3e35a",
                "R2_CLUSTER": "INCONCLUSIVE",
                "R2_RANGE": "INSUFFICIENT_POPULATION",
                "R4_MICRO": "INCONCLUSIVE",
                "LOCAL_PUBLICATION": "NO"},
            "validate_output": "AGGREGATE_ONLY",
            "holdout_price_sessions_converted": 0,
            "broker_or_live_execution": False,
            "parameter_optimization": False,
            "score_confidence_probability_ranking": False,
        }
        deterministic["fingerprint"] = _fingerprint(deterministic)
        deterministic["final_quality_gates"] = _v3_gates(
            v3_buckets, v2_buckets, v1_buckets)
        deterministic["final_historical_verdict"] = (
            "ROTATION_PARTICIPATION_REMAINS_UNPROVEN_STOP_HISTORICAL_TUNING")
        deterministic["blocking_gates"] = ["Q5_MOVEMENT_PARTICIPATION_QUALITY"]
        deterministic["further_historical_tuning_authorized"] = False
        deterministic["q5_answer"] = "NO"
        return deterministic

    first, second = payload(), payload()
    assert first == second

    report = render_markdown(first)
    assert report.startswith("# BRAIN V3 FINAL HISTORICAL VERDICT")
    assert "last historical development attempt" in report
    assert "## THE DECISIVE COMPARISON" in report
    assert "HOLDOUT_PRICE_SESSIONS_CONVERTED = 0" in report
    assert "R2_CLUSTER: **INCONCLUSIVE**" in report
    assert "No Brain V4" in report


def test_holdout_is_rejected_before_any_brain_v3_observation():
    with pytest.raises(ValueError, match="TEACH/VALIDATE"):
        DynamicShadowTrader("holdout", "holdout-EP001", brain=BRAIN_V3)
