"""HISTORICAL REFERENCE INTELLIGENCE — `src/livemap/reference.py`.

```
no score        no field, and no reason, ranks one reference against another
price order     roles follow the published corridor's order, never a re-sort
identity        every reference keeps its structure id, edge, kind and parent
nesting         map hierarchy, release containment and price-order enclosure stay apart
aggregation     only relations the map publishes; members never lost
causality       a structure that did not exist at k is never a reference at k
one engine      historical and live produce the same ReferencePath
determinism     repeated runs identical
no target       the path is never rendered as a destination
map preserved   the corridor this reads is the published one, extended not replaced
```
"""
from __future__ import annotations

import ast
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from src.boxes.frontier import Frontier, run
from src.boxes.snapshot import build_snapshot
from src.livemap import observatory as OB
from src.livemap import participation as PE
from src.livemap import reference as REF
from src.livemap import route as RT
from src.livemap.interpreter import Interpreter
from tests.test_participation import BARS, HIST, streams
from src.learning.split import load_split
from src.feed.replay_feed import ReplayFeed

SRC = Path(__file__).resolve().parent.parent / "src"
SYMBOL = "NIFTY BANK"


def deep(o):
    if is_dataclass(o) and not isinstance(o, type):
        return (type(o).__name__,) + tuple(deep(getattr(o, f.name)) for f in fields(o))
    if isinstance(o, (list, tuple)):
        return tuple(deep(x) for x in o)
    return o


@pytest.fixture(scope="module")
def world():
    """Teach block 4 — the block that carries the large-range / internal-cluster case."""
    sp = load_split()
    days = ReplayFeed(SYMBOL, on_gap="skip").available_days()
    _m1, m5 = streams(sp.teach(days)[:60])
    blk = m5[4 * BARS:5 * BARS]
    hist, live = blk[:HIST], blk[HIST:]
    snap = build_snapshot(hist, SYMBOL)
    return snap, hist, live, run(snap, hist, live)


@pytest.fixture(scope="module")
def paths(world):
    snap, hist, live, f = world
    interp = Interpreter(snap, f)
    ctxs = {c.index: c for c in PE.eye(snap, f)}
    out = []
    for st in interp.states():
        c = ctxs.get(st.index)
        pool = interp.pool_at(st.index)
        out.append((st, pool, REF.build(
            st, {n.id: n for n in pool},
            idea=c.idea if c else "",
            invalidation_price=c.invalidation_price if c else None,
            invalidation_rule=c.invalidation if c else "", pool=pool)))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# NO SCORE — the heart of the stage
# ═════════════════════════════════════════════════════════════════════════════
def test_no_reference_field_is_a_score():
    assert REF.no_score_fields() == []


def test_no_reason_implies_probability_or_a_target():
    for role, reason in REF.REASON.items():
        low = reason.lower()
        for word in REF.FORBIDDEN_WORDS:
            assert word not in low, f"{role} reason says {word!r}: {reason}"


def test_a_reference_refuses_a_reason_that_promises_something():
    with pytest.raises(ValueError):
        REF.Reference(role=REF.IMMEDIATE, structure_id="C01", edge=RT.NEAR,
                      price=1, kind="cluster", parent_id=None, distance=1,
                      distance_atr=0.1, route_position=0, direction=REF.UP,
                      reason="likely target for this move")


SCORING = ("importance", "priority", "confidence", "probability", "weight", "score",
           "rank", "strength", "quality")
#: The two places the module is *allowed* to name the vocabulary it rejects, because
#: naming it is how they enforce it.
GUARDS = ("no_score_fields", "FORBIDDEN_WORDS")


def test_nothing_in_the_module_computes_a_score():
    """Not a text scan — a text scan fights the module's own guards, which have to name
    what they forbid. This walks the AST and asserts no *name is bound to* and no
    *attribute is read as* a scoring quantity anywhere outside those guards."""
    tree = ast.parse((SRC / "livemap" / "reference.py").read_text(encoding="utf-8"))

    def guarded(node):
        return isinstance(node, ast.FunctionDef) and node.name in GUARDS

    offenders = []
    for node in ast.walk(tree):
        if guarded(node):
            continue
        targets = []
        if isinstance(node, ast.Assign):
            targets = [ast.unparse(x) for x in node.targets]
        elif isinstance(node, ast.AnnAssign):
            targets = [ast.unparse(node.target)]
        elif isinstance(node, ast.Attribute):
            targets = [node.attr]
        elif isinstance(node, ast.arg):
            targets = [node.arg]
        for name in targets:
            if name in GUARDS:
                continue
            if any(w in name.lower() for w in SCORING):
                offenders.append(name)
    assert not offenders, f"reference.py binds a scoring quantity: {sorted(set(offenders))}"


def test_no_arithmetic_combines_references_into_a_ranking():
    """A score can arrive without the word. Multiplication or division of two published
    measurements, or a `sorted(..., key=...)` over anything but the published order, is
    how a ranking sneaks in."""
    src = (SRC / "livemap" / "reference.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div,
                                                               ast.Pow)):
            pytest.fail(f"reference.py combines values arithmetically: "
                        f"{ast.unparse(node)}")
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "sorted":
            pytest.fail(f"reference.py re-sorts: {ast.unparse(node)}")


# ═════════════════════════════════════════════════════════════════════════════
# PRICE ORDER — §4
# ═════════════════════════════════════════════════════════════════════════════
def test_references_follow_the_published_corridor_order(paths):
    """The layer assigns roles; it never re-sorts. Position must be the corridor's."""
    for st, pool, rp in paths:
        for side, up in ((rp.up, True), (rp.down, False)):
            positions = [r.route_position for r in side.references]
            assert positions == sorted(positions), f"c{st.index} re-sorted the corridor"
            dists = [float(r.distance) for r in side.references]
            assert dists == sorted(dists), f"c{st.index} is not in price order"


def test_immediate_is_never_further_than_next_or_major(paths):
    checked = 0
    for st, pool, rp in paths:
        for side in (rp.up, rp.down):
            imm = side.immediate
            if imm is None:
                continue
            for other in (side.next, side.major):
                if other is not None:
                    checked += 1
                    assert imm.distance <= other.distance, (
                        f"c{st.index} {side.direction}: IMMEDIATE {imm.structure_id} at "
                        f"{imm.distance} is beyond {other.role} {other.structure_id}")
    assert checked, "no candle had both an immediate and a next/major"


def test_the_deep_corridor_extends_the_published_one(paths):
    """It must be the SAME corridor read further, not a second one."""
    for st, pool, rp in paths:
        for up, published in ((True, st.above.corridor), (False, st.below.corridor)):
            deep_stops = REF.deep_corridor(st, pool, up=up)
            assert tuple(deep_stops[:len(published)]) == tuple(published), (
                f"c{st.index} {'up' if up else 'down'}: the deep corridor disagrees "
                f"with the published one")


# ═════════════════════════════════════════════════════════════════════════════
# IDENTITY and NESTING — §9, §36
# ═════════════════════════════════════════════════════════════════════════════
def test_every_reference_keeps_its_structure_identity(paths):
    for st, pool, rp in paths:
        known = {n.id for n in pool}
        for side in (rp.up, rp.down):
            for r in side.references:
                assert r.structure_id in known
                assert r.kind in ("cluster", "range")
                assert r.edge in (RT.NEAR, RT.FAR)
                assert r.label.startswith(r.structure_id + ".")


def test_the_parent_on_a_reference_is_the_map_hierarchy(paths):
    """`Reference.parent_id` is `Node.parent` and must never be release containment."""
    for st, pool, rp in paths:
        nodes = {n.id: n for n in pool}
        for side in (rp.up, rp.down):
            for r in side.references:
                assert r.parent_id == nodes[r.structure_id].parent


def test_price_order_enclosure_is_not_the_declared_hierarchy(paths):
    """Three nesting facts, and this asserts two of them are genuinely different."""
    declared = shape = 0
    for st, pool, rp in paths:
        nodes = {n.id: n for n in pool}
        for side in (rp.up, rp.down):
            declared += sum(1 for r in side.references if r.parent_id)
            shape += len(side.enclosures)
            for outer, inner in side.enclosures:
                # the shape does NOT require a declared parent link
                if nodes.get(inner) is not None:
                    pass
    assert shape, "no price-order enclosure in this block — assertion vacuous"
    assert declared != shape, (
        "declared parenthood and price-order enclosure produced the same count; they are "
        "different facts and collapsing them is the error this test exists for")


# ═════════════════════════════════════════════════════════════════════════════
# AGGREGATION — §7 / §8
# ═════════════════════════════════════════════════════════════════════════════
def test_an_area_never_loses_its_members(paths):
    seen = 0
    for st, pool, rp in paths:
        for side in (rp.up, rp.down):
            ids = {r.structure_id for r in side.references}
            for area in side.areas:
                seen += 1
                assert area.id in ids
                assert len(area.members) >= 2, area
                assert {m.structure_id for m in area.members} == {area.id}
                assert area.low == min(m.price for m in area.members)
                assert area.high == max(m.price for m in area.members)
    assert seen, "no structural area formed — assertion vacuous"


def test_only_published_relations_are_aggregated(paths):
    """An area may only group one structure's own edges — nothing else is published as a
    grouping, and inventing a price-proximity rule is what §8 forbids."""
    for st, pool, rp in paths:
        for side in (rp.up, rp.down):
            for area in side.areas:
                assert len({m.structure_id for m in area.members}) == 1


# ═════════════════════════════════════════════════════════════════════════════
# INVALIDATION and CURRENT — §14, §15
# ═════════════════════════════════════════════════════════════════════════════
def test_invalidation_is_copied_from_the_thesis_and_is_not_a_reference(paths, world):
    snap, hist, live, f = world
    ctxs = {c.index: c for c in PE.eye(snap, f)}
    for st, pool, rp in paths:
        c = ctxs.get(st.index)
        if c is None:
            continue
        assert rp.invalidation_price == c.invalidation_price
        assert rp.invalidation_rule == c.invalidation
        for side in (rp.up, rp.down):
            for r in side.references:
                assert r.role != "INVALIDATION"


def test_the_current_structure_is_labelled_not_mixed_in(paths):
    for st, pool, rp in paths:
        if rp.current_id is None:
            continue
        for side in (rp.up, rp.down):
            for r in side.references:
                if r.structure_id == rp.current_id:
                    assert r.role == REF.CURRENT_BOUNDARY, (
                        f"c{st.index}: the current structure appeared as {r.role}")


# ═════════════════════════════════════════════════════════════════════════════
# COUNTER-THESIS — §13
# ═════════════════════════════════════════════════════════════════════════════
def test_the_counter_reference_is_on_the_opposite_side(paths):
    seen = 0
    for st, pool, rp in paths:
        if rp.counter is None:
            continue
        seen += 1
        assert rp.active is not None
        assert rp.counter.direction != rp.active
        assert rp.counter.role == REF.COUNTER_THESIS
    assert seen, "no counter reference in this block — assertion vacuous"


def test_with_no_thesis_neither_path_is_active(paths):
    for st, pool, rp in paths:
        if rp.active is None:
            assert rp.counter is None


# ═════════════════════════════════════════════════════════════════════════════
# CAUSALITY — §23. MapState has never been prefix-tested; assess() ignores it.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("k", [20, 60, 140, 240])
def test_a_structure_that_did_not_exist_yet_is_never_a_reference(world, k):
    """The whole point. Rebuild the map from scratch fed only k candles and require the
    reference path to be identical — a later structure must not be reachable."""
    snap, hist, live, _f = world
    fresh = Frontier(snap, hist)
    for candle in live[:k]:
        fresh.on_candle(candle)
    interp = Interpreter(snap, fresh)
    states = list(interp.states())
    st = states[-1]
    pool = interp.pool_at(st.index)
    got = REF.build(st, {n.id: n for n in pool}, pool=pool)

    full = run(snap, hist, live)
    finterp = Interpreter(snap, full)
    fst = next(s for s in finterp.states() if s.index == st.index)
    fpool = finterp.pool_at(st.index)
    want = REF.build(fst, {n.id: n for n in fpool}, pool=fpool)
    assert deep(got) == deep(want)


def test_no_reference_names_a_structure_finalised_later(paths):
    for st, pool, rp in paths:
        ends = {n.id: n.end for n in pool}
        for side in (rp.up, rp.down):
            for r in side.references:
                assert ends[r.structure_id] <= st.index, (
                    f"c{st.index} references {r.structure_id} which ends at "
                    f"{ends[r.structure_id]}")


# ═════════════════════════════════════════════════════════════════════════════
# ONE ENGINE, DETERMINISM, MAP PRESERVED
# ═════════════════════════════════════════════════════════════════════════════
def test_historical_and_live_produce_the_same_reference_path(world):
    snap, hist, live, _f = world
    batch = OB.frames(snap, list(hist), list(live))
    session = OB.LiveSession(snap, list(hist))
    for candle in live:
        session.on_candle(candle)
    assert len(session.frames) == len(batch)
    for a, b in zip(session.frames, batch):
        assert deep(a.reference) == deep(b.reference), f"c{a.index} diverged"


def test_the_reference_path_is_deterministic(world):
    snap, hist, live, _f = world
    a = OB.frames(snap, list(hist), list(live[:120]))
    b = OB.frames(snap, list(hist), list(live[:120]))
    assert [deep(x.reference) for x in a] == [deep(x.reference) for x in b]


def test_building_references_mutates_no_map(world):
    snap, hist, live, f = world
    interp = Interpreter(snap, f)
    before = [deep(n) for n in interp.pool_at(699)]
    states = list(interp.states())
    for st in states:
        pool = interp.pool_at(st.index)
        REF.build(st, {n.id: n for n in pool}, pool=pool)
    assert [deep(n) for n in interp.pool_at(699)] == before


def test_every_frame_carries_a_reference_path(world):
    snap, hist, live, _f = world
    frames = OB.frames(snap, list(hist), list(live[:80]))
    assert all(fr.reference is not None for fr in frames)
    for fr in frames:
        assert fr.reference.index == fr.index
        assert fr.reference.price == fr.c or fr.reference.price is not None
