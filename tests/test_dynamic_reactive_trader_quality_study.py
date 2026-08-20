from __future__ import annotations

import json

import pytest

from src.livemap.shadow import TEACH, VALIDATE, DynamicShadowTrader
from tests.test_dynamic_shadow import truth
from tools.dynamic_reactive_trader_quality_study import (
    EpisodeReplay,
    _fingerprint,
    _gates,
    _repeatability,
    aggregate_quality,
    render_markdown,
)


def replay(bucket: str, source_episode_id: str) -> EpisodeReplay:
    machine = DynamicShadowTrader(bucket, source_episode_id)
    stream = (
        truth(
            0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
            bucket=bucket, source_episode_id=source_episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=source_episode_id),
        truth(2, "106", bucket=bucket, source_episode_id=source_episode_id),
        truth(
            3, "110", location="AT_UPPER_EDGE", approaching_upper=True,
            source_end=True, bucket=bucket, source_episode_id=source_episode_id),
    )
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def buckets() -> dict:
    return {
        TEACH: aggregate_quality((replay(TEACH, "teach-EP001"),)),
        VALIDATE: aggregate_quality((replay(VALIDATE, "validate-EP001"),)),
    }


def payload() -> dict:
    quality_buckets = buckets()
    deterministic = {
        "study": "DYNAMIC_REACTIVE_TRADER_FINAL_QUALITY_AUDIT_V2",
        "trader_logic_changed": False,
        "buckets": quality_buckets,
        "teach_validate_quality_rates": _repeatability(quality_buckets),
        "weakest_hypothesis_family": {
            "answer": "MIXED_NO_SINGLE_FAMILY",
            "facts": {},
        },
        "old_dynamic_architecture_reference": {
            "fingerprint": "bf497495e394bb87",
            "decision_gates": {
                "D1_MOVEMENT_STATE_CAUSAL": {"answer": "YES"},
            },
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
        "frozen_v1_fingerprint_expected": "bf497495e394bb87",
        "frozen_v1_fingerprint_recomputed": "bf497495e394bb87",
        "frozen_v1_fingerprint_match": True,
    }
    deterministic["fingerprint"] = _fingerprint(deterministic)
    deterministic["final_quality_gates"] = _gates(quality_buckets, True)
    deterministic["final_pre_production_verdict"] = "PASS_FOR_PRODUCTION_INTEGRATION"
    deterministic["minimum_brain_v2_change"] = "NONE_FREEZE_V1"
    return deterministic


def test_quality_aggregate_repairs_supportive_progress_and_active_denominator():
    result = buckets()[TEACH]

    population = result["active_directional_hypothesis_population"]
    landmarks = result["supportive_vs_adverse_landmarks"]
    progress = result["progress_quality"]
    assert population["primary_participation_opportunity_denominator"] == (
        "DIRECTIONAL_HYPOTHESES_EVER_ACTIVE")
    assert landmarks["positions_reaching_supportive_landmark"] == 1
    assert landmarks["adverse_incorrectly_counted_as_supportive"] == 0
    assert progress["max_favorable_structural_progress"]["fraction"]["median"] == 1
    assert progress["retained_structural_progress_at_exit"]["fraction"]["median"] == 1
    assert progress["giveback_from_max_progress"]["fraction"]["median"] == 0


def test_validate_quality_output_is_aggregate_only_and_contains_no_case_values():
    result = buckets()[VALIDATE]
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
    assert '"100"' not in encoded
    assert '"110"' not in encoded


def test_fresh_replays_and_quality_fingerprint_are_deterministic():
    first = payload()
    second = payload()

    assert first == second
    first_without_runtime = dict(first)
    second_without_runtime = dict(second)
    assert _fingerprint(first_without_runtime) == _fingerprint(second_without_runtime)
    assert first["frozen_v1_fingerprint_match"] is True


def test_quality_gates_use_repaired_metrics_not_old_d6_presence():
    gates = payload()["final_quality_gates"]

    assert gates["Q1_METRICS_SEMANTICALLY_CLEAN"]["answer"] == "YES"
    assert gates["Q5_MOVEMENT_PARTICIPATION_QUALITY"]["answer"] == "YES"
    assert gates["gate_policy"]["movement"].startswith("supportive-landmark")


def test_report_starts_with_required_verdict_and_preserves_research_statuses():
    report = render_markdown(payload())

    assert report.startswith("# FINAL PRE-PRODUCTION QUALITY VERDICT")
    assert "Trader logic changed: **NO**" in report
    assert "R2_CLUSTER: **INCONCLUSIVE**" in report
    assert "R2_RANGE: **INSUFFICIENT_POPULATION**" in report
    assert "HOLDOUT_PRICE_SESSIONS_CONVERTED = 0" in report


def test_holdout_bucket_is_rejected_before_any_quality_observation():
    with pytest.raises(ValueError, match="TEACH/VALIDATE"):
        DynamicShadowTrader("holdout", "holdout-EP001")
