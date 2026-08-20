"""The Brain V2 audit's own ledgers and gates, on deterministic synthetic replays."""

from __future__ import annotations

import json

import pytest

from src.livemap.shadow import (
    BRAIN_V1,
    BRAIN_V2,
    TEACH,
    VALIDATE,
    DynamicShadowTrader,
)
from src.livemap.shadow_quality import (
    FALSIFICATION_EXIT,
    POSITION_RISK_EXIT,
    build_position_quality,
)
from tools.dynamic_reactive_trader_brain_v2_study import (
    _adverse_overshoot,
    _bucket_quality,
    _brain_delta,
    _loss_gate,
    _v2_gates,
    render_markdown,
)
from tools.dynamic_reactive_trader_quality_study import (
    _fingerprint,
    _repeatability,
)
from tools.dynamic_reactive_trader_study import EpisodeReplay
from tests.test_dynamic_shadow import ref, release, truth


def crossing_replay(bucket: str, episode_id: str, brain: str) -> EpisodeReplay:
    """Enter a lower rotation, close beyond its frozen edge, then rotate up anyway."""

    machine = DynamicShadowTrader(bucket, episode_id, brain=brain)
    stream = (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
              bucket=bucket, source_episode_id=episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=episode_id),
        truth(2, "99", location="BELOW", bucket=bucket, source_episode_id=episode_id),
        truth(3, "110", location="AT_UPPER_EDGE", approaching_upper=True,
              source_end=True, bucket=bucket, source_episode_id=episode_id),
    )
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def falsified_replay(bucket: str, episode_id: str, brain: str) -> EpisodeReplay:
    """Enter a lower rotation and let accepted structural failure end it."""

    machine = DynamicShadowTrader(bucket, episode_id, brain=brain)
    stream = (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
              bucket=bucket, source_episode_id=episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=episode_id),
        truth(2, "98", broad=False, location="NO_STRUCTURE",
              map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
              accepted="down", left=True, releases=(release("down", edge="100"),),
              below=(ref("down", "90"),), source_end=True,
              bucket=bucket, source_episode_id=episode_id),
    )
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def buckets(brain: str) -> dict:
    return {
        TEACH: _bucket_quality((
            crossing_replay(TEACH, "teach-EP001", brain),
            falsified_replay(TEACH, "teach-EP002", brain),
        )),
        VALIDATE: _bucket_quality((
            crossing_replay(VALIDATE, "validate-EP001", brain),
            falsified_replay(VALIDATE, "validate-EP002", brain),
        )),
    }


def payload(v1: dict, v2: dict) -> dict:
    deterministic = {
        "study": "DYNAMIC_REACTIVE_TRADER_BRAIN_V2_AUDIT",
        "brain_under_audit": BRAIN_V2,
        "brain_control": BRAIN_V1,
        "targeted_change": "ROTATION_POSITION_RISK_EXIT",
        "config": {"history": 400},
        "source_population": {},
        "source_episodes_shorter_than_or_equal_to_history": {},
        "frozen_v1_behaviour_fingerprint_expected": "bf497495e394bb87",
        "frozen_v1_behaviour_fingerprint_recomputed": "bf497495e394bb87",
        "frozen_v1_quality_fingerprint_expected": "bf54631ee9c200e9",
        "frozen_v1_quality_fingerprint_recomputed": "bf54631ee9c200e9",
        "frozen_v1_fingerprints_match": True,
        "buckets": v2,
        "v1_control_buckets": v1,
        "brain_v1_vs_v2": {
            bucket: _brain_delta(v1[bucket], v2[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "teach_validate_quality_rates": _repeatability(v2),
        "weakest_hypothesis_family": {"answer": "MIXED", "facts": {}},
        "old_dynamic_architecture_reference": {
            "fingerprint": "bf497495e394bb87",
            "decision_gates": {"D5_NO_AUTOMATIC_REVERSAL": {"answer": "YES"}},
        },
        "structural_research_reference": {
            "fingerprint": "5ebd256debc3e35a",
            "R2_CLUSTER": "INCONCLUSIVE",
            "R2_RANGE": "INSUFFICIENT_POPULATION",
            "R4_MICRO": "INCONCLUSIVE",
            "LOCAL_PUBLICATION": "NO",
        },
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": 0,
        "broker_or_live_execution": False,
        "parameter_optimization": False,
        "score_confidence_probability_ranking": False,
    }
    deterministic["fingerprint"] = _fingerprint(deterministic)
    deterministic["final_quality_gates"] = _v2_gates(v2, v1)
    deterministic["final_pre_production_verdict"] = "HOLD_FOR_TARGETED_BRAIN_FIX"
    return deterministic


def test_the_risk_ledger_counts_only_rotation_position_risk_exits():
    risk = buckets(BRAIN_V2)[TEACH]["position_risk_quality"]

    assert risk["position_risk_exits"] == 1
    assert risk["rotation_position_risk_exits"] == 1
    assert risk["continuation_position_risk_exits"] == 0
    assert risk["exits_that_lagged_their_first_cross"] == 0
    assert risk["overshoot_points"]["median"] == 1.0


def test_v1_produces_no_position_risk_exits_at_all():
    risk = buckets(BRAIN_V1)[TEACH]["position_risk_quality"]

    assert risk["position_risk_exits"] == 0
    assert buckets(BRAIN_V1)[TEACH]["reentry_integrity"][
        "hypotheses_with_consumed_participation"] == 0


def test_the_adverse_ledger_holds_both_exit_kinds_without_merging_their_meanings():
    adverse = buckets(BRAIN_V2)[TEACH]["adverse_exit_ledger"]

    assert adverse["adverse_exits"] == 2
    assert adverse["falsification_exits"] == 1
    assert adverse["position_risk_exits"] == 1
    assert adverse["adverse_exits_with_measured_overshoot"] == 2
    assert adverse["position_risk_exits_that_lagged_their_first_cross"] == 0


def test_accepted_failure_overshoot_is_never_read_from_a_risk_exit():
    positions = {
        item.exit_class: item
        for replay in (crossing_replay(TEACH, "teach-EP001", BRAIN_V2),
                       falsified_replay(TEACH, "teach-EP002", BRAIN_V2))
        for item in build_position_quality(replay.machine)
    }

    risk = positions[POSITION_RISK_EXIT]
    false = positions[FALSIFICATION_EXIT]
    assert risk.falsification_overshoot_points is None
    assert risk.position_risk_exit_overshoot_points is not None
    assert false.position_risk_exit_overshoot_points is None
    assert false.falsification_overshoot_points is not None
    assert _adverse_overshoot(risk) == risk.position_risk_exit_overshoot_points
    assert _adverse_overshoot(false) == false.falsification_overshoot_points


def test_no_hypothesis_instance_ever_opens_a_second_position():
    for brain in (BRAIN_V1, BRAIN_V2):
        for bucket in buckets(brain).values():
            reentry = bucket["reentry_integrity"]
            assert reentry["positions_reopened_by_a_risk_consumed_hypothesis"] == 0
            assert reentry["hypotheses_that_produced_more_than_one_position"] == 0


def test_the_loss_gate_is_the_same_rule_for_both_brains():
    v1, v2 = buckets(BRAIN_V1), buckets(BRAIN_V2)
    gates = _v2_gates(v2, v1)
    loss = gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]

    assert loss["answer"] == _loss_gate(v2)["answer"]
    assert loss["same_rule_recomputed_on_v1"]["answer"] == _loss_gate(v1)["answer"]
    assert "adverse exit" in loss["basis"]


def test_the_loss_gate_fails_on_a_reentry_or_a_lagged_risk_exit():
    v2 = buckets(BRAIN_V2)
    broken = {name: dict(bucket) for name, bucket in v2.items()}
    broken[TEACH] = dict(broken[TEACH])
    broken[TEACH]["reentry_integrity"] = {
        **broken[TEACH]["reentry_integrity"],
        "positions_reopened_by_a_risk_consumed_hypothesis": 1,
    }

    assert _loss_gate(broken)["answer"] == "NO"


def test_q7_is_never_yes_while_any_gate_answers_no():
    v1, v2 = buckets(BRAIN_V1), buckets(BRAIN_V2)
    gates = _v2_gates(v2, v1)
    negative = [name for name, gate in gates.items()
                if name.startswith("Q") and gate["answer"] == "NO"]

    if negative:
        assert gates["Q7_READY_FOR_PRODUCTION_INTEGRATION"]["answer"] != "YES"


def test_validate_output_stays_aggregate_only():
    result = buckets(BRAIN_V2)[VALIDATE]
    encoded = json.dumps(result, sort_keys=True)
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

    walk(result)
    assert "validate-EP001" not in encoded
    assert "2026-" not in encoded


def test_the_audit_is_deterministic_and_the_report_states_what_changed():
    first = payload(buckets(BRAIN_V1), buckets(BRAIN_V2))
    second = payload(buckets(BRAIN_V1), buckets(BRAIN_V2))

    assert first == second
    report = render_markdown(first)
    assert report.startswith("# BRAIN V2 PRE-PRODUCTION QUALITY VERDICT")
    assert "one preregistered rotation position-risk rule" in report
    assert "HOLDOUT_PRICE_SESSIONS_CONVERTED = 0" in report
    assert "R2_CLUSTER: **INCONCLUSIVE**" in report
    assert "## Q3 CONTROL — THE SAME RULE ON V1" in report


def test_holdout_is_rejected_before_any_brain_v2_observation():
    with pytest.raises(ValueError, match="TEACH/VALIDATE"):
        DynamicShadowTrader("holdout", "holdout-EP001", brain=BRAIN_V2)
