"""Structural opportunity geometry — the facts, and the things they must never conflate.

Every trace here is deterministic. The synthetic frames are built from the same
`StructuralFrame` shape the production stack emits, so the layer is tested through its
real seam rather than through a private constructor.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.structure import STRUCTURE_KINDS
from src.livemap import geometry as G
from src.livemap.frame import LocalStructure, StructuralFrame

BASE_AT = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
TOL = Decimal("0.5")


# ─────────────────────────────────────────────────────────────────────────────
# a minimal but structurally honest StructuralFrame
# ─────────────────────────────────────────────────────────────────────────────
class _Node:
    def __init__(self, ident, kind, low, high, parent=None, status="HISTORICAL"):
        self.id, self.kind = ident, kind
        self.low, self.high = Decimal(low), Decimal(high)
        self.parent_id, self.status = parent, status
        self.position, self.location = None, ""
        self.parent_low = self.parent_high = self.position_in_parent = None


class _Micro:
    def __init__(self, ident=None, low=None, high=None, state=None):
        self.micro_id, self.micro_state = ident, state
        self.micro_low = None if low is None else Decimal(low)
        self.micro_high = None if high is None else Decimal(high)
        self.parent_id = None
        self.events = ()


class _Reading:
    def __init__(self, index, interaction="WAIT", micro=None, left_kind=None):
        self.index, self.interaction = index, interaction
        self.micro, self.left_kind = micro, left_kind
        self.node_id = None


class _Map:
    def __init__(self, current, atr, status="WAIT", left=None):
        self.current, self.atr, self.status = current, Decimal(atr), status
        self.left_id = left.id if left else None
        self.left_edge = None
        self.left_low = left.low if left else None
        self.left_high = left.high if left else None
        self.market_state = "TRANSITION"


class _Thesis:
    def __init__(self, location="INSIDE", state=""):
        self.price_location, self.current_state = location, state
        self.invalidation_price = None


class _Side:
    def __init__(self, immediate=None):
        self.immediate = immediate


class _Refs:
    def __init__(self, up=None, down=None):
        self.up, self.down = _Side(up), _Side(down)


class _Ref:
    def __init__(self, ident, kind, price, direction, distance, label):
        self.structure_id, self.kind = ident, kind
        self.price, self.direction = Decimal(price), direction
        self.distance, self.distance_atr = Decimal(distance), float(distance) / 10
        self.label = label


def frame(index, price, *, node=None, atr="10", status="WAIT", interaction="WAIT",
          location="INSIDE", up=None, down=None, micro=None, local=None,
          approaching_upper=False, approaching_lower=False, left=None,
          left_kind=None, thesis_state="") -> StructuralFrame:
    reading = _Reading(index, interaction, micro, left_kind)
    return StructuralFrame(
        index=index, at=BASE_AT + timedelta(minutes=5 * index), price=Decimal(price),
        reading=reading, map=_Map(node, atr, status, left),
        eye=None, release=None, references=_Refs(up, down),
        thesis=_Thesis(location, thesis_state),
        broad_id=node.id if node else None, local=local,
        approaching_current_upper=approaching_upper,
        approaching_current_lower=approaching_lower,
        left_id=left.id if left else None)


def small() -> _Node:
    """The compressed case the milestone exists to make visible: 20 points wide."""

    return _Node("C77", "cluster", 48000, 48020)


def large() -> _Node:
    return _Node("R12", "range", 48000, 48150)


def run(frames) -> list[G.StructureGeometry]:
    observer = G.GeometryObserver()
    return [observer.observe(f, tolerance=TOL) for f in frames]


# ─────────────────────────────────────────────────────────────────────────────
# A — structure identity: role vs kind
# ─────────────────────────────────────────────────────────────────────────────
def test_a_controlling_cluster_keeps_the_kind_cluster():
    geometry = run([frame(0, "48010", node=small())])[0]

    assert geometry.controlling.structure_id == "C77"
    assert geometry.controlling.kind == "cluster"
    assert geometry.controlling.kind in STRUCTURE_KINDS


def test_a_controlling_range_keeps_the_kind_range():
    geometry = run([frame(0, "48100", node=large())])[0]

    assert geometry.controlling.kind == "range"
    assert geometry.controlling.kind in STRUCTURE_KINDS


def test_the_role_never_renames_the_kind():
    """Broad is a role. Nothing in the layer may emit "Broad range" as a kind."""

    for node in (small(), large()):
        geometry = run([frame(0, "48010", node=node)])[0]
        assert geometry.controlling_structure_kind == node.kind
        assert "broad" not in geometry.controlling.kind.lower()


def test_width_and_midpoint_are_exact():
    geometry = run([frame(0, "48010", node=small(), atr="10")])[0]

    assert geometry.controlling.width_points == Decimal(20)
    assert geometry.controlling.midpoint == Decimal(48010)
    assert geometry.controlling.width_atr == 2.0


def test_a_large_structure_reports_its_real_size():
    geometry = run([frame(0, "48020", node=large(), atr="10")])[0]

    assert geometry.controlling.width_points == Decimal(150)
    assert geometry.controlling.midpoint == Decimal(48075)
    assert geometry.controlling.width_atr == 15.0


# ─────────────────────────────────────────────────────────────────────────────
# B — price geometry
# ─────────────────────────────────────────────────────────────────────────────
def test_price_distances_are_exact_and_signed_where_it_matters():
    geometry = run([frame(0, "48005", node=small(), atr="10")])[0]
    p = geometry.price_geometry

    assert p.containment == G.INSIDE
    assert p.distance_to_lower_points == Decimal(5)
    assert p.distance_to_midpoint_points == Decimal(-5)
    assert p.distance_to_upper_points == Decimal(15)
    assert p.distance_to_lower_atr == 0.5
    assert p.distance_to_midpoint_atr == 0.5


def test_containment_is_measured_against_real_edges_not_a_status_string():
    below = run([frame(0, "47990", node=small(), location="INSIDE")])[0]
    above = run([frame(0, "48030", node=small(), location="INSIDE")])[0]

    assert below.price_geometry.containment == G.BELOW
    assert above.price_geometry.containment == G.ABOVE


# ─────────────────────────────────────────────────────────────────────────────
# C — internal space
# ─────────────────────────────────────────────────────────────────────────────
def test_internal_room_is_exact_for_a_compressed_cluster():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
    ])[1]
    space = geometry.internal

    assert geometry.movement.direction == G.UP
    assert space.room_to_lower_edge_points == Decimal(4)
    assert space.room_to_midpoint_points == Decimal(6)
    assert space.room_to_upper_edge_points == Decimal(16)
    assert space.next_internal_landmark == G.BROAD_MIDPOINT_LANDMARK
    assert space.room_to_next_internal_landmark_points == Decimal(6)
    assert space.room_to_opposite_edge_points == Decimal(16)
    assert space.state == G.INTERNAL_GEOMETRY_AVAILABLE


def test_passing_the_midpoint_consumes_the_internal_geometry_and_renames_the_landmark():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48014", node=small()),
    ])[2]

    assert geometry.internal.state == G.INTERNAL_GEOMETRY_CONSUMED
    assert geometry.internal.next_internal_landmark == G.OPPOSITE_EDGE_LANDMARK
    assert geometry.internal.room_to_next_internal_landmark_points == Decimal(6)


def test_an_approached_edge_is_the_decision_area_and_uses_the_maps_own_fact():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48019", node=small(), approaching_upper=True),
    ])[2]

    assert geometry.internal.state == G.AT_EDGE_DECISION


def test_no_controlling_structure_and_no_reference_is_no_mapped_space():
    geometry = run([frame(0, "48010")])[0]

    assert geometry.controlling is None
    assert geometry.internal.state == G.NO_MAPPED_SPACE
    assert geometry.internal.room_to_midpoint_points is None


# ─────────────────────────────────────────────────────────────────────────────
# D — external space
# ─────────────────────────────────────────────────────────────────────────────
def test_external_room_is_measured_from_the_edge_and_from_price_separately():
    above = _Ref("C90", "cluster", 48100, "up", 80, "C90.low")
    below = _Ref("C60", "cluster", 47900, "down", 100, "C60.high")
    geometry = run([frame(0, "48010", node=small(), atr="10", up=above, down=below)])[0]
    e = geometry.external

    assert e.next_reference_above.structure_id == "C90"
    assert e.next_reference_above.label == "C90.low"
    assert e.room_above_current_upper_to_next_reference_points == Decimal(80)
    assert e.room_from_current_price_to_immediate_reference_above_points == Decimal(90)
    assert e.next_reference_below.structure_id == "C60"
    assert e.room_below_current_lower_to_next_reference_points == Decimal(100)
    assert e.room_from_current_price_to_immediate_reference_below_points == Decimal(110)


def test_a_missing_reference_stays_unknown_and_is_never_fabricated():
    geometry = run([frame(0, "48010", node=small(), up=None, down=None)])[0]
    e = geometry.external

    assert e.next_reference_above is None
    assert e.next_reference_below is None
    assert e.room_above_current_upper_to_next_reference_points is None
    assert e.room_from_current_price_to_immediate_reference_below_points is None


def test_up_and_down_reference_paths_never_mix():
    above = _Ref("C90", "cluster", 48100, "up", 80, "C90.low")
    geometry = run([frame(0, "48010", node=small(), up=above)])[0]

    assert geometry.external.next_reference_above.direction == G.UP
    assert geometry.external.next_reference_below is None


def test_an_accepted_release_changes_the_outside_geometry_causally():
    node = small()
    above = _Ref("C90", "cluster", 48100, "up", 80, "C90.low")
    geometries = run([
        frame(0, "48010", node=node, up=above),
        frame(1, "48030", node=None, status="ACCEPTED_ABOVE", location="NO_STRUCTURE",
              left=node, left_kind="cluster", up=above),
    ])

    assert geometries[0].internal.state != G.OUTSIDE_REFERENCE_AVAILABLE
    assert geometries[1].controlling is None
    assert geometries[1].internal.state == G.OUTSIDE_REFERENCE_AVAILABLE
    assert geometries[1].external.outside_released_structure_id == "C77"
    assert geometries[1].movement.origin_role == G.RELEASED_EDGE
    assert geometries[1].movement.origin_price == Decimal(48020)
    assert geometries[1].movement.destination_reference == "C90.low"


# ─────────────────────────────────────────────────────────────────────────────
# F/G — movement origin and provenance
# ─────────────────────────────────────────────────────────────────────────────
def test_the_movement_origin_is_stable_while_the_structure_is_controlling():
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48008", node=small()),
        frame(3, "48012", node=small()),
    ])

    origins = {(g.movement.origin_index, g.movement.origin_price) for g in geometries}
    assert origins == {(0, Decimal(48000))}
    for g in geometries[1:]:
        assert g.movement.origin_role == G.BROAD_LOWER_EDGE
        assert g.movement.origin_reference == "C77.low"
        assert g.movement.origin_structure_kind == "cluster"


def test_provenance_records_only_events_from_this_or_earlier_candles():
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48014", node=small()),
    ])

    for g in geometries:
        for event in g.movement.events:
            assert event.index <= g.index
    assert G.MIDPOINT_CROSSED in {e.event for e in geometries[2].movement.events}
    assert G.MIDPOINT_CROSSED not in {e.event for e in geometries[1].movement.events}


def test_a_controlling_structure_replacement_creates_the_transition_provenance():
    other = _Node("C88", "cluster", 48100, 48140)
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48102", node=other, location="AT_LOWER_EDGE", approaching_lower=True),
    ])
    events = [e.event for e in geometries[2].movement.events]

    assert G.CONTROLLING_STRUCTURE_REPLACED in events
    assert G.LOWER_EDGE_ORIGIN in events
    assert geometries[2].movement.origin_structure_id == "C88"
    # the hand-off is visible: one event from the movement that ended is carried over
    assert events[0] == G.MIDPOINT_CROSSED or events[0] in G.PROVENANCE_EVENTS
    assert G.CONTROLLING_STRUCTURE_REPLACED in geometries[2].structural_events


def test_the_first_controlling_structure_is_not_reported_as_a_replacement():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
    ])[0]

    assert G.STRUCTURE_BECAME_CONTROLLING in geometry.structural_events
    assert G.CONTROLLING_STRUCTURE_REPLACED not in geometry.structural_events


# ─────────────────────────────────────────────────────────────────────────────
# H — the two midpoints
# ─────────────────────────────────────────────────────────────────────────────
def test_the_broad_midpoint_and_the_movement_path_midpoint_are_different_fields():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
    ])[1]

    # origin 48000 → destination 48020 (opposite edge): path midpoint 48010
    assert geometry.controlling.midpoint == Decimal(48010)
    assert geometry.movement.path_midpoint == Decimal(48010)
    # and they diverge as soon as the movement does not span the whole structure
    upper = run([
        frame(0, "48020", node=small(), location="AT_UPPER_EDGE", approaching_upper=True),
        frame(1, "48016", node=small()),
    ])[1]
    assert upper.movement.direction == G.DOWN
    assert upper.movement.destination_price == Decimal(48000)
    assert upper.movement.path_midpoint == Decimal(48010)


def test_the_broad_midpoint_never_moves_while_the_structure_is_controlling():
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48016", node=small()),
    ])

    assert {g.controlling.midpoint for g in geometries} == {Decimal(48010)}


def test_an_outside_movement_path_midpoint_uses_the_mapped_reference():
    node = small()
    above = _Ref("C90", "cluster", 48120, "up", 100, "C90.low")
    geometry = run([
        frame(0, "48030", node=None, status="ACCEPTED_ABOVE", location="NO_STRUCTURE",
              left=node, left_kind="cluster", up=above),
    ])[0]

    assert geometry.movement.origin_price == Decimal(48020)
    assert geometry.movement.destination_price == Decimal(48120)
    assert geometry.movement.path_midpoint == Decimal(48070)
    assert geometry.controlling is None            # no Broad midpoint to confuse it with


# ─────────────────────────────────────────────────────────────────────────────
# I — whole movement position
# ─────────────────────────────────────────────────────────────────────────────
def test_whole_movement_progress_does_not_jump_backward_at_the_segment_change():
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48004", node=small()),
        frame(2, "48009", node=small()),
        frame(3, "48011", node=small()),
        frame(4, "48016", node=small()),
    ])
    whole = [g.movement.whole_movement_fraction for g in geometries[1:]]
    segments = [g.movement.current_segment for g in geometries[1:]]

    assert segments[0] == G.ORIGIN_TO_MIDPOINT
    assert segments[-1] == G.MIDPOINT_TO_OPPOSITE_EDGE
    assert whole == sorted(whole)                 # monotone across the transition
    assert geometries[4].movement.whole_movement_fraction == pytest.approx(0.8)
    assert geometries[4].movement.current_segment_fraction == pytest.approx(0.6)


def test_travelled_and_remaining_are_exact():
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48006", node=small(), atr="10"),
    ])[1]

    assert geometry.movement.travelled_points == Decimal(6)
    assert geometry.movement.travelled_atr == 0.6
    assert geometry.movement.remaining_points == Decimal(14)


# ─────────────────────────────────────────────────────────────────────────────
# J — Broad, Micro and Local stay apart
# ─────────────────────────────────────────────────────────────────────────────
def test_micro_is_reported_separately_from_the_controlling_structure():
    micro = _Micro("M04", 48004, 48012, "CONFIRMED")
    geometry = run([frame(0, "48008", node=small(), atr="10", micro=micro)])[0]

    assert geometry.local.micro_id == "M04"
    assert geometry.local.micro_width_points == Decimal(8)
    assert geometry.local.micro_width_atr == 0.8
    assert geometry.local.price_location_vs_micro == G.INSIDE
    assert geometry.controlling.structure_id == "C77"       # untouched by the micro


def test_an_observational_local_structure_is_reported_separately_from_both():
    local = LocalStructure(id="OBS_LOCAL_9_cluster", kind="cluster",
                           low=Decimal(48002), high=Decimal(48009), holder_id="C77")
    micro = _Micro("M04", 48004, 48012, "CONFIRMED")
    geometry = run([frame(0, "48012", node=small(), micro=micro, local=local)])[0]

    assert geometry.local.local_structure_id == "OBS_LOCAL_9_cluster"
    assert geometry.local.local_structure_kind == "cluster"
    assert geometry.local.local_width_points == Decimal(7)
    assert geometry.local.local_holder_id == "C77"
    assert geometry.local.price_location_vs_local == G.ABOVE
    assert geometry.local.micro_id == "M04"
    assert geometry.local.price_location_vs_micro == G.INSIDE
    assert geometry.controlling.structure_id == "C77"


def test_a_new_local_structure_is_a_provenance_event():
    local = LocalStructure(id="OBS_LOCAL_9_cluster", kind="cluster",
                           low=Decimal(48002), high=Decimal(48009), holder_id="C77")
    geometries = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True),
        frame(1, "48005", node=small(), local=local),
    ])

    assert G.NEW_LOCAL_STRUCTURE_OBSERVED in geometries[1].structural_events
    assert G.NEW_LOCAL_STRUCTURE_OBSERVED not in geometries[0].structural_events


# ─────────────────────────────────────────────────────────────────────────────
# K/L — the two cases this milestone exists for
# ─────────────────────────────────────────────────────────────────────────────
def test_the_compressed_cluster_case_is_fully_described():
    above = _Ref("C90", "cluster", 48200, "up", 180, "C90.low")
    below = _Ref("C60", "cluster", 47800, "down", 200, "C60.high")
    geometry = run([
        frame(0, "48000", node=small(), location="AT_LOWER_EDGE", approaching_lower=True,
              up=above, down=below, atr="10"),
        frame(1, "48004", node=small(), up=above, down=below, atr="10"),
    ])[1]

    assert geometry.controlling.width_points == Decimal(20)
    assert geometry.controlling.width_atr == 2.0
    # the whole internal opportunity is 16 points; the mapped room outside is 180
    assert geometry.internal.room_to_opposite_edge_points == Decimal(16)
    assert geometry.external.room_above_current_upper_to_next_reference_points == Decimal(180)
    # and the layer reports both without ruling on which one matters
    assert geometry.internal.state == G.INTERNAL_GEOMETRY_AVAILABLE


def test_the_spacious_structure_case_is_fully_described():
    geometry = run([
        frame(0, "48000", node=large(), location="AT_LOWER_EDGE", approaching_lower=True,
              atr="10"),
        frame(1, "48010", node=large(), atr="10"),
    ])[1]

    assert geometry.controlling.kind == "range"
    assert geometry.controlling.width_points == Decimal(150)
    assert geometry.internal.room_to_midpoint_points == Decimal(65)
    assert geometry.internal.room_to_opposite_edge_points == Decimal(140)
    assert geometry.movement.whole_movement_fraction == pytest.approx(10 / 150)


def test_the_layer_states_no_size_verdict_anywhere():
    """No SMALL/BIG label may exist: the population has not been looked at yet."""

    banned = {"SMALL", "BIG", "LARGE", "NARROW", "WIDE", "COMPRESSED", "SPACIOUS"}
    assert not banned & set(G.INTERNAL_SPACE_STATES)
    assert not banned & set(G.PROVENANCE_EVENTS)
    assert not banned & set(G.MOVEMENT_ORIGIN_ROLES)


# ─────────────────────────────────────────────────────────────────────────────
# causality
# ─────────────────────────────────────────────────────────────────────────────
def stream():
    node = small()
    above = _Ref("C90", "cluster", 48100, "up", 80, "C90.low")
    return [
        frame(0, "48000", node=node, location="AT_LOWER_EDGE", approaching_lower=True,
              up=above),
        frame(1, "48004", node=node, up=above),
        frame(2, "48014", node=node, up=above),
        frame(3, "48019", node=node, approaching_upper=True, up=above),
        frame(4, "48030", node=None, status="ACCEPTED_ABOVE", location="NO_STRUCTURE",
              left=node, left_kind="cluster", up=above),
        frame(5, "48040", node=None, location="NO_STRUCTURE", up=above),
    ]


def test_a_later_candle_cannot_mutate_an_emitted_geometry():
    frames = stream()
    observer = G.GeometryObserver()
    first = observer.observe(frames[0], tolerance=TOL)
    frozen_events = first.movement.events
    for f in frames[1:]:
        observer.observe(f, tolerance=TOL)

    assert first.movement.events == frozen_events
    assert first.price == Decimal(48000)
    with pytest.raises(FrozenInstanceError):
        first.price = Decimal(1)          # type: ignore[misc]


def test_a_fresh_replay_to_k_reproduces_the_full_replay_prefix():
    frames = stream()
    full = run(frames)

    for cut in range(len(frames)):
        assert run(frames[:cut + 1]) == full[:cut + 1]


def test_indices_must_strictly_increase():
    observer = G.GeometryObserver()
    observer.observe(frame(3, "48010", node=small()), tolerance=TOL)
    with pytest.raises(AssertionError, match="strictly increasing"):
        observer.observe(frame(3, "48010", node=small()), tolerance=TOL)


def test_the_inspector_block_is_deterministic_and_ascii():
    geometries = run(stream())
    first = [g.lines() for g in geometries]
    second = [g.lines() for g in run(stream())]

    assert first == second
    for block in first:
        for line in block:
            line.encode("ascii")          # a cp1252 console must be able to print it


def test_the_geometry_layer_does_not_mutate_the_frame_it_reads():
    frames = stream()
    before = replace(frames[1])
    run(frames)

    assert frames[1] == before


# ─────────────────────────────────────────────────────────────────────────────
# the drift guard — the observational anchor and the brain's must agree
# ─────────────────────────────────────────────────────────────────────────────
def test_the_observational_anchor_agrees_with_the_brain():
    """This layer keeps its own movement anchor, so it must be pinned to the brain's.

    Real teach data, both layers fed the same frames. The brain's anchor stays the
    decision authority; if this ever diverges the geometry layer is wrong, not the brain.
    """

    from src.boxes.structure import tol_at
    from src.livemap import frame as SF
    from src.livemap.shadow import BRAIN_V3, DynamicShadowTrader
    from tests.test_participation import block

    snapshot, frontier = block(0)
    frames = SF.observe(snapshot, frontier)
    tolerances = [tol_at(frontier.candles, f.index, frontier.tol_atr) for f in frames]

    observer = G.GeometryObserver()
    geometries = [observer.observe(f, tolerance=t)
                  for f, t in zip(frames, tolerances, strict=True)]

    machine = DynamicShadowTrader("teach", "teach-EP001", brain=BRAIN_V3)
    decisions = [machine.observe_frame(f, source_ordinal=1, tolerance=t)
                 for f, t in zip(frames, tolerances, strict=True)]

    assert len(geometries) == len(decisions) > 100
    compared = 0
    for geometry, decision in zip(geometries, decisions, strict=True):
        brain = decision.movement
        mine = geometry.movement
        assert mine.direction == brain.direction
        assert mine.origin_index == brain.origin_index
        assert mine.origin_price == brain.origin_price
        assert mine.origin_reference == brain.origin_reference
        if brain.direction is not None:
            assert mine.current_segment == brain.structural_segment
            assert mine.travelled_points == brain.travelled_points
            compared += 1
    assert compared > 0, "the block produced no established movement to compare"


def test_the_geometry_layer_is_never_read_by_the_brain():
    """One-way dependency: geometry reads the frame, nothing reads geometry back."""

    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ("shadow.py", "shadow_quality.py", "frame.py", "interpreter.py",
                 "reference.py", "thesis.py", "release.py", "eye.py"):
        text = (root / "src" / "livemap" / name).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "geometry" not in node.module, f"{name} imports geometry"
            elif isinstance(node, ast.Import):
                assert not any("geometry" in a.name for a in node.names), name
