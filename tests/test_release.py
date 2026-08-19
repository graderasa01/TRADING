"""
The release context — `src/livemap/release.py`.

The Participation Context Study named four holes and this layer exists to close them, so
the tests are organised around them rather than around the code's shape:

```
§6   WHAT BROKE          identity survives the candle the structure is finalised on
§5   WHICH SCALE         an outer and an inner boundary breaking together stay two records
§7   WHERE IS PRICE      relative to the boundary that broke, not to the current node
§25  WHAT IS AHEAD       the route origin is the broken boundary, and the fixture proves
                         it by making the two answers numerically different
```

Plus the three invariants every observer in this repo has to hold: prefix causality,
determinism, and no leakage back into the map it reads.

The hand-built fixtures drive `ReleaseObserver` directly. That is deliberate — the real
frontier produces outer releases readily and inner ones only when the map happens to hold a
contained node, so a suite built only on replay would leave the inner and simultaneous
paths untested on the days they matter.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.boxes.frontier import Reading
from src.boxes.hierarchy import Node
from src.boxes.micro import MICRO_BREAK_DOWN, MICRO_BREAK_UP, MicroView
from src.boxes.snapshot import MapSnapshot
from src.domain.models import Candle
from src.livemap import release as R
from src.livemap.breaks import BreakRecord
from src.livemap.release import (
    INNER, INNER_SCAN, LOG, MICRO, MICRO_EVENT, MULTI_SCALE, OUTER, Release,
    ReleaseObserver, ReleaseState, observe, releases, simultaneous)

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2025, 3, 4, 9, 15, tzinfo=IST)

# ── the §25 fixture, chosen so the two possible answers cannot coincide ──────
#
#     P   100-130      the current live structure
#     I   110-120      a mapped structure inside it
#     Z   140-150      the next zone above
#
# An inner release through I.high measured from 120 has 20 points of free space.
# The same release measured from the CURRENT structure's edge, 130, has 10.
# One fixture, two numbers, and the test can tell which one the code used.
PARENT = Node(id="P", kind="cluster", start=0, end=5, low=Decimal(100),
              high=Decimal(130))
INNER_NODE = Node(id="I", kind="cluster", start=1, end=4, low=Decimal(110),
                  high=Decimal(120))
ZONE = Node(id="Z", kind="cluster", start=0, end=4, low=Decimal(140),
            high=Decimal(150))
BELOW = Node(id="B", kind="cluster", start=0, end=4, low=Decimal(60),
             high=Decimal(70))


def snapshot(*nodes: Node) -> MapSnapshot:
    return MapSnapshot(version="M001", symbol="TEST", built_at=START,
                       built_at_index=5, first_index=0, nodes=tuple(nodes),
                       relations=())


def candles(closes) -> list[Candle]:
    """Tight candles, so `tol_at` stays well under the 10-point gaps in the fixture.

    A fat ATR would swallow the distinction the §25 fixture exists to make, which would
    turn a real assertion into a coin flip.
    """
    out = []
    for i, c in enumerate(closes):
        px = Decimal(str(c))
        out.append(Candle("TEST", "5m", START + timedelta(minutes=5 * i),
                          START + timedelta(minutes=5 * (i + 1)),
                          px, px + 1, px - 1, px))
    return out


def reading(i: int, node_id: str | None = "P",
            band: tuple[Decimal, Decimal] | None = (Decimal(100), Decimal(130)),
            micro: MicroView | None = None, interaction: str = "INSIDE") -> Reading:
    return Reading(index=i, state="CONFIRMED", interaction=interaction,
                   node_id=node_id, node_kind="cluster", node_status="HISTORICAL",
                   band=band, micro=micro)


def micro_view(i: int, events=(), low=Decimal(112), high=Decimal(118)) -> MicroView:
    return MicroView(index=i, view="MICRO_RANGE", parent_id="P",
                     parent_low=Decimal(100), parent_high=Decimal(130),
                     micro_id="P.m1", micro_low=low, micro_high=high,
                     micro_state="CONFIRMED", micro_kind="cluster", events=tuple(events))


def drive(closes, snap: MapSnapshot, *, breaks=None, micros=None,
          bands=None, node_ids=None) -> list[ReleaseState]:
    """Feed the observer one candle at a time. `breaks[i]` / `micros[i]` are per-candle."""
    ks = candles(closes)
    obs = ReleaseObserver(snap)
    out = []
    for i, k in enumerate(ks):
        band = bands[i] if bands else (Decimal(100), Decimal(130))
        nid = node_ids[i] if node_ids else "P"
        rd = reading(i, node_id=nid, band=band,
                     micro=(micros or {}).get(i))
        out.append(obs.on_candle(rd, k, ks, breaks=(breaks or {}).get(i, ())))
    return out


def break_record(i: int, structure_id="P", direction="up", edge=Decimal(130),
                 low=Decimal(100), high=Decimal(130)) -> BreakRecord:
    return BreakRecord(index=i, at=START + timedelta(minutes=5 * i),
                       structure_id=structure_id, direction=direction, edge=edge,
                       low=low, high=high, kind="cluster", source="frozen",
                       interaction="ACCEPTED_ABOVE")


# ═════════════════════════════════════════════════════════════════════════════
# §23 — release identity
# ═════════════════════════════════════════════════════════════════════════════
def test_an_outer_release_is_taken_from_the_break_log_not_re_derived():
    """`frontier.py` writes a `break` event in exactly one place — the branch where the
    CURRENT structure's acceptance completes. So a log break IS an outer release, and
    re-scanning the band for it would be a second opinion on a settled fact."""
    states = drive([115] * 4 + [135, 136], snapshot(PARENT, ZONE),
                   breaks={5: [break_record(5)]})
    rel = releases(states)
    assert len(rel) == 1
    r = rel[0]
    assert (r.scale, r.origin, r.direction) == (OUTER, LOG, "up")
    assert r.broken_id == "P" and r.broken_edge == Decimal(130)
    assert r.boundary == "P.high"


def test_an_inner_release_names_the_inner_structure_and_its_parent():
    """§6: broken structure, broken edge, scale and parent — all four, causally."""
    states = drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE))
    rel = releases(states)
    assert len(rel) == 1
    r = rel[0]
    assert (r.scale, r.origin) == (INNER, INNER_SCAN)
    assert r.broken_id == "I" and r.broken_edge == Decimal(120)
    assert r.boundary == "I.high"
    assert r.parent_id == "P" and (r.parent_low, r.parent_high) == (Decimal(100),
                                                                   Decimal(130))
    assert r.index == 5


def test_a_micro_release_is_copied_from_micros_own_event():
    """`micro.py` already applies `BREAK_CLOSES` to the micro band and keeps `_subject`
    so the band survives on the candle it broke. This layer reads that, and adds nothing."""
    states = drive([115] * 5 + [119], snapshot(PARENT),
                   micros={5: micro_view(5, events=(MICRO_BREAK_UP,))})
    rel = releases(states)
    assert len(rel) == 1
    r = rel[0]
    assert (r.scale, r.origin, r.direction) == (MICRO, MICRO_EVENT, "up")
    assert r.broken_id == "P.m1" and r.broken_edge == Decimal(118)
    assert r.broken_kind == "micro" and r.parent_id == "P"


def test_a_downward_micro_release_uses_the_micro_low():
    states = drive([115] * 5 + [110], snapshot(PARENT),
                   micros={5: micro_view(5, events=(MICRO_BREAK_DOWN,))})
    r = releases(states)[0]
    assert r.direction == "down" and r.broken_edge == Decimal(112)


def test_outer_and_inner_release_on_the_same_candle_stay_two_records():
    """§5. The study's trace F is this case, and the old stack collapsed it into one."""
    states = drive([115] * 4 + [135, 136], snapshot(PARENT, INNER_NODE, ZONE),
                   breaks={5: [break_record(5)]})
    state = states[5]
    assert state.simultaneous
    assert set(state.scales) == {OUTER, INNER}
    outer, inner = state.of(OUTER), state.of(INNER)
    assert outer.broken_id == "P" and outer.broken_edge == Decimal(130)
    assert inner.broken_id == "I" and inner.broken_edge == Decimal(120)
    assert outer.id != inner.id


def test_inner_and_micro_release_on_the_same_candle_stay_two_records():
    states = drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE),
                   micros={5: micro_view(5, events=(MICRO_BREAK_UP,))})
    state = states[5]
    assert state.simultaneous and set(state.scales) == {INNER, MICRO}


def test_all_three_scales_can_release_on_one_candle():
    states = drive([115] * 4 + [135, 136], snapshot(PARENT, INNER_NODE, ZONE),
                   breaks={5: [break_record(5)]},
                   micros={5: micro_view(5, events=(MICRO_BREAK_UP,))})
    state = states[5]
    assert set(state.scales) == {OUTER, INNER, MICRO}
    assert state.controlling_scale == MULTI_SCALE, (
        "two scales at once has never been measured, so choosing one would be a guess")


def test_a_reentry_is_never_a_release():
    """Up through the high leaves the structure. Down through the high walks back INTO it.

    The first participation study counted both and had to be corrected mid-flight: 441 of
    908 crossings were re-entries, and the outer population fell from 295 to 203.
    """
    # price starts above I, closes back down through I.high into the band
    down = drive([125] * 4 + [115, 115], snapshot(PARENT, INNER_NODE, ZONE))
    assert releases(down) == []
    # and the mirror: up through I.low, from below
    up = drive([105] * 4 + [115, 115], snapshot(PARENT, INNER_NODE, BELOW))
    assert releases(up) == []


def test_the_same_boundary_releasing_twice_produces_two_records():
    """The observation layer records what happened. Deciding that the second one is not a
    new opportunity is the decision layer's job, and it cannot do it if this layer has
    already thrown the event away."""
    closes = [115] * 4 + [125, 125] + [115] * 3 + [125, 125]
    rel = releases(drive(closes, snapshot(PARENT, INNER_NODE, ZONE)))
    assert len(rel) == 2
    assert rel[0].broken_id == rel[1].broken_id == "I"
    assert rel[0].id != rel[1].id and rel[0].index != rel[1].index


def test_a_release_carries_no_fact_from_the_future():
    """No `ends_at`, no outcome, no MFE — the mistake `BreakEpisode` was written to avoid."""
    banned = ("ends_at", "end", "outcome", "result", "mfe", "mae", "success", "won",
              "held_until", "invalidated_at")
    assert [f.name for f in fields(Release) if f.name in banned] == []


def test_a_release_is_frozen():
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    with pytest.raises(FrozenInstanceError):
        r.broken_edge = Decimal(999)


# ═════════════════════════════════════════════════════════════════════════════
# §24 — release-relative location
# ═════════════════════════════════════════════════════════════════════════════
def test_price_inside_the_parent_at_an_inner_release():
    """The case the old stack could not express: `PRICE_LOCATION` said `NO_STRUCTURE`
    while price was in fact still inside the parent, above the inner edge."""
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.location == R.BEYOND_EDGE
    assert r.parent_location == R.INSIDE_PARENT
    assert r.beyond == Decimal(5)


def test_price_beyond_the_parent_at_an_inner_release():
    r = releases(drive([115] * 4 + [135, 136], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.scale == INNER and r.parent_location == R.BEYOND_PARENT


def test_price_at_the_parent_edge_is_its_own_answer():
    r = releases(drive([115] * 4 + [129.9, 130], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.parent_location == R.AT_PARENT_EDGE


def test_an_outer_release_reports_no_parent_rather_than_guessing_one():
    """The structure that broke IS the outer one. Inventing a parent for it would be the
    hierarchy this layer is forbidden to detect."""
    r = releases(drive([115] * 4 + [135, 136], snapshot(PARENT, ZONE),
                       breaks={5: [break_record(5)]}))[0]
    assert r.parent_location == R.NO_PARENT and r.parent_id is None


def test_position_before_the_release_comes_from_the_candle_before_the_run():
    """Where price stood inside the structure it was about to leave — 115 in a 110-120
    band is the middle, and it is read from candle `i - BREAK_CLOSES`."""
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.position_before == Decimal("0.5")


def test_the_release_survives_the_current_structure_being_replaced():
    """§24's last case. On the candle after the release the frontier may hold a different
    node, or none — the release record must not depend on it."""
    bands = [(Decimal(100), Decimal(130))] * 6 + [None] * 2
    node_ids = ["P"] * 6 + [None] * 2
    states = drive([115] * 4 + [125, 125, 126, 127], snapshot(PARENT, INNER_NODE, ZONE),
                   bands=bands, node_ids=node_ids)
    born = releases(states)[0]
    assert states[7].releases == () and states[7].active is born
    assert states[7].active.parent_id == "P", "the parent identity outlives the node"


# ═════════════════════════════════════════════════════════════════════════════
# §25 — the route is measured from the boundary that broke
# ═════════════════════════════════════════════════════════════════════════════
def test_the_inner_route_origin_is_the_inner_boundary_not_the_current_edge():
    """The fixture makes the two answers different on purpose: 20 points from I.high,
    10 points from P.high. This is the exact defect the study found."""
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.route is not None
    assert r.route.origin_edge == Decimal(120), "origin must be the broken boundary"
    assert r.route.free_to_near == Decimal(20)
    assert r.route.free_to_near != Decimal(10), "10 would be the current structure's edge"
    assert r.route.id == "Z"
    assert r.route.zone_depth == Decimal(10) and r.route.free_to_far == Decimal(30)


def test_the_outer_route_origin_is_the_outer_boundary():
    r = releases(drive([115] * 4 + [135, 136], snapshot(PARENT, ZONE),
                       breaks={5: [break_record(5)]}))[0]
    assert r.route.origin_edge == Decimal(130) and r.route.free_to_near == Decimal(10)


def test_the_micro_route_origin_is_the_micro_boundary():
    states = drive([115] * 5 + [119], snapshot(PARENT, ZONE),
                   micros={5: micro_view(5, events=(MICRO_BREAK_UP,))})
    r = releases(states)[0]
    assert r.route.origin_edge == Decimal(118) and r.route.free_to_near == Decimal(22)


def test_two_scales_releasing_together_get_two_different_routes():
    """Trace F of the study had one route for both. That is what this pins shut."""
    state = drive([115] * 4 + [135, 136], snapshot(PARENT, INNER_NODE, ZONE),
                  breaks={5: [break_record(5)]})[5]
    outer, inner = state.of(OUTER), state.of(INNER)
    assert outer.route.origin_edge == Decimal(130)
    assert inner.route.origin_edge == Decimal(120)
    assert outer.route.free_to_near != inner.route.free_to_near


def test_the_structure_that_just_broke_is_not_offered_as_the_zone_ahead():
    """Its far side is behind price now; reporting it as the next zone would hand back a
    depth price has already traversed."""
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE)))[0]
    assert r.route.id != "I"
    assert all(s.ref_id != "I" for s in r.corridor)


def test_a_release_with_nothing_mapped_ahead_says_so_rather_than_inventing_a_zone():
    r = releases(drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE)))[0]
    assert r.route is None


# ═════════════════════════════════════════════════════════════════════════════
# §11 — controlling scale
# ═════════════════════════════════════════════════════════════════════════════
def test_the_controlling_scale_is_the_scale_that_just_released():
    states = drive([115] * 4 + [125, 125], snapshot(PARENT, INNER_NODE, ZONE))
    assert states[5].controlling_scale == R.INNER_CONTROLLING


def test_a_held_release_keeps_controlling_after_its_own_candle():
    states = drive([115] * 4 + [125, 125, 126], snapshot(PARENT, INNER_NODE, ZONE))
    assert states[6].releases == ()
    assert states[6].controlling_scale == R.INNER_CONTROLLING
    assert states[6].active.broken_id == "I"


def test_control_is_unresolved_once_price_gives_the_release_back():
    states = drive([115] * 4 + [125, 125] + [113] * 3,
                   snapshot(PARENT, INNER_NODE, ZONE))
    assert states[-1].active is None
    assert states[-1].controlling_scale == R.UNRESOLVED


def test_control_is_unresolved_before_anything_has_released():
    states = drive([115] * 4, snapshot(PARENT, INNER_NODE, ZONE))
    assert all(s.controlling_scale == R.UNRESOLVED for s in states)


# ═════════════════════════════════════════════════════════════════════════════
# §26 / §27 — causality, determinism, leakage
# ═════════════════════════════════════════════════════════════════════════════
def real_frontier():
    from tests.test_frontier_evidence import SHAPES, frontier_for
    return frontier_for(SHAPES["walkthrough"])


def test_prefix_causality_on_real_candles():
    """`observe(upto=k)` is prefix-equal to a full run truncated at k. If a later candle
    could change an earlier release, every measurement built on this layer would be a
    backtest lying to itself."""
    f = real_frontier()
    full = observe(f)
    for k in (f.readings[3].index, f.readings[len(full) // 2].index,
              f.readings[-2].index):
        upto = observe(f, upto=k)
        assert upto == [s for s in full if s.index <= k]


def test_no_later_candle_rewrites_an_earlier_release():
    f = real_frontier()
    full = observe(f)
    born = {r.id: r for s in full for r in s.releases}
    for k in (s.index for s in full):
        for state in observe(f, upto=k):
            for r in state.releases:
                assert r == born[r.id], f"{r.id} was rewritten by a later candle"


def test_determinism():
    f = real_frontier()
    assert observe(f) == observe(f)


def test_the_observer_never_writes_back_into_the_map():
    """§37.7 and §37.8. This layer reads the frontier and the snapshot; if it could add a
    node or an event to either, a release would become part of the historical map."""
    f = real_frontier()
    before = (len(f.log), len(f.live_log), [n.id for n in f.history()],
              tuple(n.id for n in f.snapshot.nodes))
    states = observe(f)
    after = (len(f.log), len(f.live_log), [n.id for n in f.history()],
             tuple(n.id for n in f.snapshot.nodes))
    assert before == after
    ids = {r.id for r in releases(states)}
    assert not ids & set(before[3]), "a release id reached the map"


def test_release_ids_are_unique_and_ordered():
    f = real_frontier()
    rel = releases(observe(f))
    assert len({r.id for r in rel}) == len(rel)
    assert [r.index for r in rel] == sorted(r.index for r in rel)


def test_the_layer_never_emits_a_trading_word():
    """`interpreter.py` and `decide.py` both carry this guard; the release layer is
    observation and has even less business naming a trade."""
    f = real_frontier()
    for state in observe(f):
        text = " ".join(state.lines()).upper()
        for word in R.FORBIDDEN:
            assert word not in text, f"{word!r} leaked into a release render"


def test_every_release_scale_and_origin_is_in_the_closed_vocabulary():
    f = real_frontier()
    for r in releases(observe(f)):
        assert r.scale in R.SCALES and r.origin in R.ORIGINS
        assert r.location in R.RELEASE_LOCATIONS
        assert r.parent_location in R.PARENT_LOCATIONS


def test_an_unknown_scale_is_refused():
    with pytest.raises(ValueError, match="unknown release scale"):
        Release(id="RL01", index=0, at=START, scale="NANO", direction="up",
                origin=LOG, broken_id="X", broken_edge=Decimal(1))


def test_an_unknown_controlling_scale_is_refused():
    with pytest.raises(ValueError, match="unknown controlling scale"):
        ReleaseState(index=0, at=START, price=Decimal(1), controlling_scale="MAYBE")


def test_a_real_replay_produces_outer_releases_and_no_crashes():
    """The synthetic fixtures drive the inner and micro paths; this proves the log path
    works on candles the frontier actually produced."""
    f = real_frontier()
    rel = releases(observe(f))
    assert rel and all(r.scale == OUTER for r in rel)
    assert all(r.origin == LOG for r in rel)
    assert all(r.broken_edge is not None for r in rel)


def test_simultaneous_helper_only_returns_multi_release_candles():
    states = drive([115] * 4 + [135, 136], snapshot(PARENT, INNER_NODE, ZONE),
                   breaks={5: [break_record(5)]})
    assert [s.index for s in simultaneous(states)] == [5]
    assert all(len(s.releases) > 1 for s in simultaneous(states))
