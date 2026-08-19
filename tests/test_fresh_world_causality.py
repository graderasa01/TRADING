from __future__ import annotations

from pathlib import Path

from src.learning.split import TEACH, VALIDATE
from tests.test_participation import HIST, block
from tools.fresh_world_causality import (
    REQUIRED_EVENTS,
    canonical_json,
    primitive_only,
    run_prefix_world,
    run_streaming_world,
    select_cuts,
)
from tools.live_structure_truth import Block


def real_block(bucket: str = TEACH) -> Block:
    _snapshot, frontier = block(0)
    return Block(
        bucket=bucket,
        ordinal=1,
        start_index=0,
        history=tuple(frontier.candles[:HIST]),
        live=tuple(frontier.candles[HIST:]),
    )


def test_fresh_independent_prefix_world_equals_immediate_streaming_capture():
    sample = real_block()
    cut = HIST + 8

    prefix = run_prefix_world(sample, cut)
    streaming, changed = run_streaming_world(sample, [cut])

    assert prefix == streaming[cut]
    assert changed == []
    assert primitive_only(prefix)
    assert canonical_json(prefix) == canonical_json(streaming[cut])


def test_captured_candle_cannot_mutate_after_future_candles():
    sample = real_block()
    cut = HIST + 5

    captured, changed = run_streaming_world(sample, [cut])
    frozen = canonical_json(captured[cut])

    assert changed == []
    assert canonical_json(captured[cut]) == frozen


def test_complete_capture_contains_every_certified_perception_layer():
    sample = real_block()
    truth = run_prefix_world(sample, HIST + 3)

    required = {
        "frozen_snapshot_structures",
        "causally_available_structures",
        "cluster_proposal",
        "range_proposal",
        "frontier_reading",
        "frontier_current",
        "frontier_left",
        "frontier_candidate",
        "micro_view",
        "map_state",
        "eye_state",
        "release_state",
        "simultaneous_releases",
        "reference_path",
        "live_thesis",
        "thesis_identity",
        "thesis_invalidation",
        "structural_frame",
    }
    assert required <= set(truth)


def test_event_cut_selection_includes_neighbourhood_and_both_populations():
    teach = real_block(TEACH)
    validate = Block(
        bucket=VALIDATE,
        ordinal=1,
        start_index=0,
        history=teach.history,
        live=teach.live,
    )
    event = REQUIRED_EVENTS[0]
    event_catalog = {
        TEACH: {event: [{"block": 1, "index": HIST + 10}]},
        VALIDATE: {event: [{"block": 1, "index": HIST + 20}]},
    }

    cuts = select_cuts(
        {TEACH: [teach], VALIDATE: [validate]},
        event_catalog,
        ordinary_per_bucket=1,
    )

    teach_indices = {cut.index for cut in cuts
                     if cut.bucket == TEACH and event in cut.events}
    validate_indices = {cut.index for cut in cuts
                        if cut.bucket == VALIDATE and event in cut.events}
    assert teach_indices == {HIST + 9, HIST + 10, HIST + 11}
    assert validate_indices == {HIST + 19, HIST + 20, HIST + 21}


def test_causality_harness_never_loads_holdout():
    source = Path("tools/fresh_world_causality.py").read_text(encoding="utf-8")
    assert "HOLDOUT" not in source
