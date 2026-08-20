"""The geometry population study and the replay inspector.

The study is descriptive. These tests pin that: it must report the real kinds, must not
invent a size verdict, must keep VALIDATE aggregate-only, and must select case traces by
structural order rather than by what happened next.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.livemap import geometry as G
from tools.structure_geometry_study import (
    _candle_census,
    _cases,
    _episodes_of,
    _gates,
    _internal_versus_external,
    _population,
    render_markdown,
)
from tools.structure_inspector import render
from tests.test_geometry import _Ref, frame, large, small

TOL = Decimal("0.5")
ABOVE = _Ref("C90", "cluster", 48200, "up", 180, "C90.low")
BELOW = _Ref("C60", "cluster", 47800, "down", 200, "C60.high")


def geometries(frames) -> list[G.StructureGeometry]:
    observer = G.GeometryObserver()
    return [observer.observe(f, tolerance=TOL) for f in frames]


def universe() -> list[G.StructureGeometry]:
    """A compressed cluster, then a spacious range: the two cases side by side."""

    return geometries([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE",
              approaching_lower=True, up=ABOVE, down=BELOW),
        frame(1, "48004", node=small(), up=ABOVE, down=BELOW),
        frame(2, "48014", node=small(), up=ABOVE, down=BELOW),
        frame(3, "48019", node=small(), approaching_upper=True, up=ABOVE, down=BELOW),
        frame(4, "48100", node=large(), location="AT_LOWER_EDGE",
              approaching_lower=True),
        frame(5, "48110", node=large()),
        frame(6, "48120", node=large()),
    ])


def bucket(items) -> dict:
    episodes = _episodes_of("teach-EP001", items)
    return {
        "population": _population(episodes, len(items)),
        "census": _candle_census(items),
        "internal_versus_external": _internal_versus_external(episodes),
    }


# ─────────────────────────────────────────────────────────────────────────────
# population
# ─────────────────────────────────────────────────────────────────────────────
def test_controlling_episodes_are_grouped_per_structure_not_per_candle():
    episodes = _episodes_of("teach-EP001", universe())

    assert [item.structure_id for item in episodes] == ["C77", "R12"]
    assert [item.kind for item in episodes] == ["cluster", "range"]
    assert [item.candles for item in episodes] == [4, 3]
    assert episodes[0].width_points == Decimal(20)
    assert episodes[1].width_points == Decimal(150)


def test_cluster_and_range_are_counted_and_measured_separately():
    population = bucket(universe())["population"]

    assert set(population["by_kind"]) == {"cluster", "range"}
    assert population["by_kind"]["cluster"]["width_points"]["median"] == 20.0
    assert population["by_kind"]["range"]["width_points"]["median"] == 150.0
    assert population["by_kind"]["cluster"]["distinct_structures"] == 1
    assert population["by_kind"]["range"]["distinct_structures"] == 1


def test_internal_room_is_reported_at_the_first_edge_encounter():
    data = bucket(universe())["population"]["by_kind"]["cluster"]
    lower = data["internal_room_at_first_lower_edge_encounter"]

    assert lower["encounters"] == 1
    # price stood at 48000 with the opposite edge at 48020
    assert lower["room_to_opposite_edge_points"]["median"] == 20.0
    assert lower["room_to_midpoint_points"]["median"] == 10.0


def test_the_study_reports_internal_and_external_room_without_ruling_between_them():
    result = bucket(universe())["internal_versus_external"]

    assert result["episodes_with_mapped_room_above"] == 1
    assert result["episodes_where_mapped_room_above_exceeds_internal_width"] == 1
    assert "descriptive only" in result["note"]
    assert "cutoff" in result["note"]


def test_no_size_classification_appears_anywhere_in_the_payload():
    """A width distribution is the deliverable. A width verdict is not."""

    encoded = json.dumps(bucket(universe()), default=str).upper()
    for banned in ("SMALL", "BIG_", "COMPRESSED", "SPACIOUS", "NARROW_", "THRESHOLD"):
        assert banned not in encoded


# ─────────────────────────────────────────────────────────────────────────────
# census
# ─────────────────────────────────────────────────────────────────────────────
def test_the_candle_census_counts_states_roles_and_events():
    census = _candle_census(universe())

    assert census["candles_with_controlling_structure"] == 7
    assert census["internal_space_states"][G.AT_EDGE_DECISION] > 0
    assert census["movement_origin_roles"][G.BROAD_LOWER_EDGE] > 0
    assert census["structural_events"][G.STRUCTURE_BECAME_CONTROLLING] == 1
    assert census["structural_events"][G.CONTROLLING_STRUCTURE_REPLACED] == 1
    assert census["controlling_width_points"]["min"] == 20.0
    assert census["controlling_width_points"]["max"] == 150.0


def test_a_candle_with_no_mapped_reference_is_counted_rather_than_filled_in():
    items = geometries([frame(0, "48010", node=small())])
    census = _candle_census(items)

    assert census["candles_with_reference_above"] == 0
    assert census["candles_with_no_reference_either_side"] == 1
    assert census["external_room_above_edge_points"]["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# case selection
# ─────────────────────────────────────────────────────────────────────────────
def test_cases_are_selected_by_structural_order_and_never_by_outcome():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})

    assert cases["narrowest_controlling_structures"][0]["structure_id"] == "C77"
    assert cases["widest_controlling_structures"][0]["structure_id"] == "R12"
    assert cases["range_kind_structures"][0]["kind"] == "range"
    assert "No future outcome" in cases["selection_rule"]
    assert "profitability" in cases["selection_rule"]


def test_a_case_trace_carries_the_inspector_lines_verbatim():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    narrow = cases["narrowest_controlling_structures"][0]

    assert narrow["lines"][:len(items[0].lines())] == items[0].lines()
    assert any("CONTROLLING" in line for line in narrow["lines"])
    assert any("PROVENANCE" in line for line in narrow["lines"])


# ─────────────────────────────────────────────────────────────────────────────
# gates and report
# ─────────────────────────────────────────────────────────────────────────────
def test_the_gates_are_factual_and_g10_requires_all_of_them():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    gates = _gates(buckets, cases, {"candles": 7, "mismatches": 0})

    assert gates["G1_CONTROLLING_KIND_VISIBLE"]["answer"] == "YES"
    assert gates["G10_READY_FOR_ENTRY_ARCHITECTURE_DISCUSSION"]["answer"] == "YES"
    assert "not readiness to trade" in gates[
        "G10_READY_FOR_ENTRY_ARCHITECTURE_DISCUSSION"]["basis"]


def test_a_disagreeing_anchor_fails_the_provenance_gate():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    gates = _gates(buckets, cases, {"candles": 7, "mismatches": 1})

    assert gates["G6_PROVENANCE_CAUSAL"]["answer"] == "NO"
    assert gates["G10_READY_FOR_ENTRY_ARCHITECTURE_DISCUSSION"]["answer"] == "NO"


def test_the_report_opens_with_the_required_question_and_answers_no_entry_rule():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    payload = {
        "fingerprint": "deadbeefdeadbeef",
        "structure_kinds": ["cluster", "range"],
        "buckets": buckets,
        "teach_case_traces": cases,
        "observational_anchor_vs_brain": {"candles": 7, "mismatches": 0},
        "holdout_price_sessions_converted": 0,
        "gates": _gates(buckets, cases, {"candles": 7, "mismatches": 0}),
    }
    report = render_markdown(payload)

    assert report.startswith("# WHAT STRUCTURES IS THE TRADER ACTUALLY SEEING?")
    assert "Broad is a role, not a size" in report
    assert "HOLDOUT_PRICE_SESSIONS_CONVERTED = 0" in report
    assert "R2_CLUSTER: **INCONCLUSIVE**" in report
    assert "R2_RANGE: **INSUFFICIENT_POPULATION**" in report
    assert "HUMAN REVIEW" in report
    assert "Do not implement either until that decision is preregistered." in report


def test_the_report_is_deterministic():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    payload = {
        "fingerprint": "deadbeefdeadbeef", "structure_kinds": ["cluster", "range"],
        "buckets": buckets, "teach_case_traces": cases,
        "observational_anchor_vs_brain": {"candles": 7, "mismatches": 0},
        "holdout_price_sessions_converted": 0,
        "gates": _gates(buckets, cases, {"candles": 7, "mismatches": 0}),
    }

    assert render_markdown(payload) == render_markdown(payload)


# ─────────────────────────────────────────────────────────────────────────────
# the inspector
# ─────────────────────────────────────────────────────────────────────────────
def test_the_inspector_block_is_deterministic_for_a_candle():
    items = universe()

    assert render(items[0]) == render(items[0])
    assert render(items[0]) == "\n".join(items[0].lines())


def test_the_inspector_refuses_any_bucket_but_teach():
    from tools.structure_inspector import main

    with pytest.raises(SystemExit, match="TEACH-only"):
        main(["--bucket", "validate"])
    with pytest.raises(SystemExit, match="TEACH-only"):
        main(["--bucket", "holdout"])


def test_the_report_survives_a_json_round_trip_byte_for_byte():
    """`sort_keys=True` reorders dicts on the way back in. A renderer that iterates a
    dict in insertion order silently produces a different report from the saved JSON,
    and the artifact stops being reproducible from its own summary."""

    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    payload = {
        "fingerprint": "deadbeefdeadbeef", "structure_kinds": ["cluster", "range"],
        "buckets": buckets, "teach_case_traces": cases,
        "observational_anchor_vs_brain": {"candles": 7, "mismatches": 0},
        "holdout_price_sessions_converted": 0,
        "gates": _gates(buckets, cases, {"candles": 7, "mismatches": 0}),
    }
    reloaded = json.loads(json.dumps(payload, sort_keys=True, default=str))

    assert render_markdown(reloaded) == render_markdown(payload)


def test_the_gates_are_listed_in_numeric_order():
    items = universe()
    episodes = _episodes_of("teach-EP001", items)
    cases = _cases(episodes, {"teach-EP001": items})
    buckets = {"teach": bucket(items), "validate": bucket(items)}
    payload = {
        "fingerprint": "x", "structure_kinds": ["cluster", "range"], "buckets": buckets,
        "teach_case_traces": cases,
        "observational_anchor_vs_brain": {"candles": 7, "mismatches": 0},
        "holdout_price_sessions_converted": 0,
        "gates": _gates(buckets, cases, {"candles": 7, "mismatches": 0}),
    }
    report = render_markdown(payload)
    order = [report.index(f"- G{n}_") for n in range(1, 11)]

    assert order == sorted(order), "G1..G10 must read in numeric order"


def test_an_accepted_release_is_read_from_the_candle_after_the_episode():
    """A release makes the controlling structure None on that very candle, so reading it
    from inside the run made the count structurally always zero."""

    node = small()
    items = geometries([
        frame(0, "48000", node=node, location="AT_LOWER_EDGE", approaching_lower=True,
              up=ABOVE),
        frame(1, "48015", node=node, up=ABOVE),
        frame(2, "48030", node=None, status="ACCEPTED_ABOVE", location="NO_STRUCTURE",
              left=node, left_kind="cluster", up=ABOVE),
    ])
    episodes = _episodes_of("teach-EP001", items)

    assert len(episodes) == 1
    assert episodes[0].last_index == 1               # the release candle is outside it
    assert episodes[0].released_up is True
    population = _population(episodes, len(items))
    assert population["by_kind"]["cluster"][
        "episodes_followed_by_an_accepted_release"] == 1
