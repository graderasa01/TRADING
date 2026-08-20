from __future__ import annotations

import json

from src.livemap.shadow import TEACH, VALIDATE, DynamicShadowTrader
from tests.test_dynamic_shadow import truth
from tools.dynamic_reactive_trader_study import (
    EpisodeReplay,
    _gates,
    _repeatability,
    aggregate,
    render_markdown,
)


def replay(bucket: str, episode_id: str) -> EpisodeReplay:
    machine = DynamicShadowTrader(bucket, episode_id)
    stream = (
        truth(
            0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
            bucket=bucket, source_episode_id=episode_id),
        truth(1, "101", bucket=bucket, source_episode_id=episode_id),
        truth(2, "105", bucket=bucket, source_episode_id=episode_id),
        truth(
            3, "110", location="AT_UPPER_EDGE", approaching_upper=True,
            source_end=True, bucket=bucket, source_episode_id=episode_id),
    )
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def late_replay(bucket: str, episode_id: str) -> EpisodeReplay:
    machine = DynamicShadowTrader(bucket, episode_id)
    stream = (
        truth(
            0, "100", location="AT_LOWER_EDGE", approaching_lower=True,
            bucket=bucket, source_episode_id=episode_id),
        truth(1, "106", bucket=bucket, source_episode_id=episode_id),
        truth(
            2, "108", source_end=True, bucket=bucket,
            source_episode_id=episode_id),
    )
    for item in stream:
        machine.observe_truth(item)
    return EpisodeReplay(bucket, machine, len(stream))


def payload() -> dict:
    teach = aggregate((
        replay(TEACH, "teach-EP001"),
        replay(TEACH, "teach-EP002"),
        late_replay(TEACH, "teach-EP003"),
    ))
    validate = aggregate((
        replay(VALIDATE, "validate-EP001"),
        replay(VALIDATE, "validate-EP002"),
        late_replay(VALIDATE, "validate-EP003"),
    ))
    buckets = {TEACH: teach, VALIDATE: validate}
    return {
        "fingerprint": "test-fingerprint",
        "buckets": buckets,
        "decision_gates": _gates(buckets),
        "teach_validate_descriptive_repeatability": _repeatability(buckets),
        "r2_structural_research_reference": {
            "fingerprint": "r2-fingerprint",
            "R2_CLUSTER": "INCONCLUSIVE",
            "R2_RANGE": "INSUFFICIENT_POPULATION",
            "R4_MICRO": "INCONCLUSIVE",
            "LOCAL_PUBLICATION": "NO",
        },
        "holdout_price_sessions_converted": 0,
    }


def test_aggregate_reports_hypothesis_participation_timing_and_causal_exits():
    result = aggregate((replay(TEACH, "teach-EP001"),))

    assert result["hypothesis_population"]["created"] >= 1
    assert result["participation_population"]["shadow_entries"] == 1
    assert result["participation_population"]["exits"] == 1
    assert result["timing"]["next_reference_already_reached_before_entry"] == 0
    assert result["timing"]["hypothesis_birth_bars_from_movement_origin"]["min"] >= 0
    assert result["stay_with_move"]["positions_reaching_structural_landmark"] == 1
    assert result["stay_with_move"]["exit_after_falsification_violations"] == 0
    assert result["false_switch"]["same_candle_reverse_entries"] == 0


def test_validate_public_aggregate_contains_no_case_level_fields_or_values():
    result = aggregate((replay(VALIDATE, "validate-EP001"),))
    encoded = json.dumps(result, sort_keys=True)
    forbidden_keys = {
        "source_episode_id", "hypothesis_id", "structure_id", "entry_index",
        "exit_index", "timestamp", "at", "price", "band", "trace", "path",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in forbidden_keys
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(result)
    assert "validate-EP001" not in encoded
    assert "2026-" not in encoded
    assert '"100"' not in encoded
    assert '"110"' not in encoded


def test_aggregate_and_gates_are_deterministic_across_fresh_replays():
    first = payload()
    second = payload()

    assert first == second
    assert first["decision_gates"]["D1_MOVEMENT_STATE_CAUSAL"]["answer"] == "YES"
    assert first["decision_gates"]["D2_HYPOTHESIS_LIFECYCLE_CAUSAL"]["answer"] == "YES"
    assert first["decision_gates"]["D3_PARTICIPATION_SEPARATE_FROM_HYPOTHESIS"][
        "answer"] == "YES"
    assert first["decision_gates"]["D4_STRUCTURAL_INVALIDATION_WORKS"]["answer"] == "YES"
    assert first["decision_gates"]["D5_NO_AUTOMATIC_REVERSAL"]["answer"] == "YES"
    assert first["decision_gates"]["D6_SHADOW_TRADER_CAN_FOLLOW_MOVEMENT"][
        "answer"] == "YES"
    assert first["decision_gates"]["D7_READY_FOR_EXECUTION_RESEARCH"]["answer"] == "NO"
    assert first["teach_validate_descriptive_repeatability"][
        "shadow_entries_per_candle"]["absolute_rate_difference"] == 0


def test_report_starts_with_required_plain_language_and_preserves_r2_statuses():
    report = render_markdown(payload())

    assert report.startswith(
        "What this trader currently knows, what it can do, and what it still cannot do.")
    assert "R2_CLUSTER: **INCONCLUSIVE**" in report
    assert "R2_RANGE: **INSUFFICIENT_POPULATION**" in report
    assert "no automatic short" in report
    assert "HOLDOUT_PRICE_SESSIONS_CONVERTED = 0" in report
