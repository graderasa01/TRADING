from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from src.livemap import frame as SF
from tests.test_participation import block


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
    assert after == before


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
        assert frame.broken_edge is not None
        assert frame.release.releases[0].broken_id in frame.broken_edge
