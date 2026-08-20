from __future__ import annotations

import ast
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from src.livemap import frame as SF
from tests.test_participation import block
from tests import test_release as release_fixture


def test_structural_frame_imports_no_detector_or_trader_surface():
    source = Path("src/livemap/frame.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden = (
        "src.boxes.adaptive",
        "src.boxes.mapper",
        "src.boxes.structure",
        "src.livemap.trader",
        "src.livemap.reactor",
        "src.livemap.participation",
        "src.broker",
        "src.risk",
    )
    assert not any(name.startswith(forbidden) for name in imports)

    forbidden_source = (
        "adaptive.choose", "read_window", "detector", "threshold", "score",
        "probability", "confidence", "trader", "reactor", "participation",
        "broker", "risk",
    )
    lowered = source.lower()
    assert not any(word in lowered for word in forbidden_source)


def test_structural_frame_joins_existing_objects_without_copying_algorithms():
    snap, frontier = block(0)
    frames = SF.observe(snap, frontier)

    assert frames
    first = frames[0]
    assert first.reading is frontier.readings[0]
    assert first.map.index == first.index
    assert first.eye.index == first.index
    assert first.release.index == first.index
    assert first.references.index == first.index
    assert first.thesis.index == first.index


def test_structural_frame_prefix_causality():
    snap, frontier = block(0)
    full = SF.observe(snap, frontier)
    for k in (full[5].index, full[len(full) // 2].index, full[-2].index):
        cut = SF.observe(snap, frontier, upto=k)
        assert cut == [f for f in full if f.index <= k]


def test_structural_frame_determinism():
    snap, frontier = block(0)
    assert SF.observe(snap, frontier) == SF.observe(snap, frontier)


def test_structural_frame_does_not_mutate_map_or_frontier():
    snap, frontier = block(0)
    before = (
        tuple(n.id for n in snap.nodes),
        tuple(n.id for n in frontier.history()),
        len(frontier.log),
        len(frontier.live_log),
        len(frontier.readings),
    )
    SF.observe(snap, frontier)
    after = (
        tuple(n.id for n in snap.nodes),
        tuple(n.id for n in frontier.history()),
        len(frontier.log),
        len(frontier.live_log),
        len(frontier.readings),
    )
    assert after == before


def test_local_research_input_is_carried_without_mutating_major_map():
    snap, frontier = block(0)
    local = SF.LocalStructure(
        id="LOCAL01", kind="range", low=Decimal("1"), high=Decimal("2"),
        holder_id="HOLDER")
    before = tuple(n.id for n in snap.nodes), tuple(n.id for n in frontier.history())
    frames = SF.observe(snap, frontier, locals_by_index={frontier.readings[0].index: local})
    after = tuple(n.id for n in snap.nodes), tuple(n.id for n in frontier.history())

    assert frames[0].local == local
    assert frames[0].local_low == Decimal("1")
    assert frames[0].local_high == Decimal("2")
    assert frames[0].distance_to_local_low == frames[0].price - Decimal("1")
    assert frames[0].distance_to_local_high == Decimal("2") - frames[0].price
    assert after == before


def test_frame_has_no_selected_local_invalidation_or_broad_substitute():
    snap, frontier = block(0)
    frame = SF.observe(snap, frontier)[0]
    names = {item.name for item in fields(SF.StructuralFrame)}

    assert "local_invalidation" not in names
    assert not any("local_invalidation" in line.lower() for line in frame.lines())
    assert frame.local is None
    assert frame.local_low is None and frame.local_high is None


def test_future_nodes_do_not_appear_in_reference_pool():
    snap, frontier = block(0)
    frames = SF.observe(snap, frontier)
    by_index = {f.index: f for f in frames}
    future_ids = {
        f.index: {n.id for n in frontier.history() if n.end > f.index}
        for f in frames
    }

    for index, frame in by_index.items():
        refs = set()
        for path in (frame.references.up, frame.references.down):
            refs.update(r.structure_id for r in path.references)
        assert not refs & future_ids[index]


def test_release_candle_retains_broken_structure_context_in_frame():
    snap, frontier = block(0)
    frames = SF.observe(snap, frontier)
    release_frames = [f for f in frames if f.release.releases]
    assert release_frames
    for frame in release_frames:
        assert frame.broken_edges
        assert frame.broken_edges == tuple(r.boundary for r in frame.release.releases)
        assert frame.broken_releases == frame.release.releases


def test_multiple_simultaneous_releases_are_all_preserved():
    release_state = release_fixture.drive(
        [115] * 4 + [135, 136],
        release_fixture.snapshot(
            release_fixture.PARENT,
            release_fixture.INNER_NODE,
            release_fixture.ZONE,
        ),
        breaks={5: [release_fixture.break_record(5)]},
        micros={5: release_fixture.micro_view(
            5, events=(release_fixture.MICRO_BREAK_UP,))},
    )[5]
    assert len(release_state.releases) == 3

    snap, frontier = block(0)
    base = SF.observe(snap, frontier)[0]
    frame = SF.build(
        base.reading, base.map, base.eye, release_state,
        base.references, base.thesis,
    )

    assert frame.broken_releases == release_state.releases
    assert frame.broken_edges == tuple(r.boundary for r in release_state.releases)
    assert len(frame.broken_edges) == 3


def test_both_approached_watch_sides_are_preserved_without_priority():
    state = SimpleNamespace(
        status="MOVING",
        break_up=None,
        break_down=None,
        route_above=SimpleNamespace(watch="AT_NEXT_ZONE"),
        route_below=SimpleNamespace(watch="APPROACHING_NEXT_ZONE"),
    )

    assert SF._approached_edges(state) == ("watch.above", "watch.below")
