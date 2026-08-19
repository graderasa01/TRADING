"""
The forward route — `src/livemap/route.py`.

Three things are guarded here, and the third is the one that would cost money:

1. **The three measurements are consistent.** `FREE_TO_FAR = FREE_TO_NEAR + ZONE_DEPTH`,
   on both sides, with `NEAR` and `FAR` swapping meaning between them.
2. **The corridor is ordered by price, not by label.** A parent range whose near edge
   arrives before its own child's must appear first.
3. **The far edge is never the current breakout level.** A structure breaks at its own
   edge. `test_the_far_edge_is_never_the_current_break_level` reruns the whole Bank Nifty
   fixture asserting exactly that, because a route layer that quietly promotes the next
   zone's far side to a trigger is the single most expensive thing this file could allow.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.frontier import run
from src.boxes.hierarchy import Node
from src.boxes.snapshot import build_snapshot
from src.domain.models import IST, Candle
from src.livemap.interpreter import FORBIDDEN, interpret
from src.livemap.route import (
    WATCH_STATES, ZoneRoute, build_corridor, corridor_line, first_in_price, measure,
    nested_stops, watch_state)

D = Decimal
SPLIT = 90


def node(nid: str, low: float, high: float, kind: str = "cluster") -> Node:
    return Node(id=nid, kind=kind, start=0, end=10, low=D(str(low)), high=D(str(high)))


def route_for(n: Node, edge: float, price: float, *, up: bool, atr: float = 27.0,
              tol: float = 6.75, label: str = "NEXT") -> ZoneRoute:
    return measure(n, D(str(edge)), D(str(price)), up=up, atr=D(str(atr)),
                   tol=D(str(tol)), label=label)


# ─────────────────────────────────────────────────────────────────────────────
# 1. the three measurements
# ─────────────────────────────────────────────────────────────────────────────
def test_the_worked_example_from_the_spec():
    """current upper edge 60,430 · next zone 60,435-60,500 -> 5 / 65 / 70."""
    r = route_for(node("C08", 60435, 60500), 60430, 60432, up=True)
    assert r.near_edge == D("60435")
    assert r.far_edge == D("60500")
    assert r.free_to_near == D("5")
    assert r.zone_depth == D("65")
    assert r.free_to_far == D("70")


def test_five_points_is_a_close_first_contact_not_an_absent_route():
    """The whole reason this module exists: `SPACE = 5` reads as "no room" and is wrong.

    Five points to the first structural decision, sixty-five points of conditional route
    space behind it. A consumer that sees only the 5 cannot tell this from a break with
    five points of room into a wall.
    """
    r = route_for(node("C08", 60435, 60500), 60430, 60432, up=True)
    assert r.free_to_near < r.zone_depth
    assert r.free_to_far == r.free_to_near + r.zone_depth
    assert r.zone_depth_atr > r.free_to_near_atr


def test_short_direction_mirrors_near_and_far():
    """Long: NEAR = low, FAR = high. Short: NEAR = high, FAR = low."""
    z = node("C08", 60300, 60365)
    up = route_for(z, 60290, 60288, up=True)
    down = route_for(z, 60375, 60377, up=False)
    assert (up.near_edge, up.far_edge) == (D("60300"), D("60365"))
    assert (down.near_edge, down.far_edge) == (D("60365"), D("60300"))
    assert up.zone_depth == down.zone_depth == D("65")
    assert up.free_to_near == D("10") and down.free_to_near == D("10")


@pytest.mark.parametrize("up", [True, False])
def test_free_to_far_is_always_the_sum(up):
    z = node("C01", 100, 160)
    r = route_for(z, 90 if up else 170, 95 if up else 165, up=up)
    assert r.free_to_far == r.free_to_near + r.zone_depth
    assert r.free_to_near > 0 and r.zone_depth > 0


def test_the_measurements_are_magnitudes_on_both_sides():
    """Signed distances belong to `Reference`. A trader reading FREE TO FIRST wants a
    length, and a negative length on one side only is how sign bugs hide."""
    a = route_for(node("A", 200, 260), 190, 195, up=True)
    b = route_for(node("B", 100, 160), 170, 165, up=False)
    for r in (a, b):
        assert r.free_to_near > 0 and r.zone_depth > 0 and r.free_to_far > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. the watch ladder — a relation, never a fixed distance
# ─────────────────────────────────────────────────────────────────────────────
def w(price: float, near: float = 60435, far: float = 60500, tol: float = 5.0,
      up: bool = True) -> str:
    return watch_state(D(str(near)), D(str(far)), D(str(price)), up=up, tol=D(str(tol)))


def test_the_full_ladder_upward():
    assert w(60300) == "FAR_FROM_NEXT_ZONE"      # more than one zone-width away
    assert w(60400) == "APPROACHING_NEXT_ZONE"   # within 65 pts of the near edge
    assert w(60433) == "AT_NEXT_ZONE"            # inside the tol skirt
    assert w(60470) == "INSIDE_NEXT_ZONE"        # traversing the depth
    assert w(60498) == "AT_FAR_EDGE"             # the second decision
    assert w(60520) == "BREAK_ATTEMPT_IN_NEXT_ZONE"


def test_the_full_ladder_downward_is_the_mirror():
    down = dict(near=60300, far=60235, up=False)
    assert w(60420, **down) == "FAR_FROM_NEXT_ZONE"
    assert w(60340, **down) == "APPROACHING_NEXT_ZONE"
    assert w(60302, **down) == "AT_NEXT_ZONE"
    assert w(60270, **down) == "INSIDE_NEXT_ZONE"
    assert w(60237, **down) == "AT_FAR_EDGE"
    assert w(60215, **down) == "BREAK_ATTEMPT_IN_NEXT_ZONE"


def test_approach_is_measured_in_zone_widths_not_points():
    """The box as its own ruler — the same rule `Frontier` uses for `LEAVING`.

    At an identical 40-point distance, a wide zone is being approached and a narrow one
    is not. No points constant and no ATR multiple decides this.
    """
    wide = watch_state(D("1000"), D("1100"), D("960"), up=True, tol=D("5"))
    narrow = watch_state(D("1000"), D("1010"), D("960"), up=True, tol=D("5"))
    assert wide == "APPROACHING_NEXT_ZONE"
    assert narrow == "FAR_FROM_NEXT_ZONE"


def test_a_zone_thinner_than_the_skirt_has_no_interior():
    """Honest rather than tidy: a band narrower than the noise tolerance cannot be
    'approached' or 'traversed' in any measurable sense, and no floor is invented to
    pretend otherwise."""
    assert watch_state(D("1000"), D("1002"), D("1001"),
                       up=True, tol=D("5")) == "AT_NEXT_ZONE"


def test_every_watch_state_is_in_the_closed_vocabulary():
    prices = [60100, 60300, 60400, 60433, 60437, 60470, 60498, 60520, 61000]
    assert {w(p) for p in prices} <= WATCH_STATES
    with pytest.raises(ValueError):
        ZoneRoute(id="X", kind="cluster", direction="up", low=D(1), high=D(2),
                  origin_edge=D(0), near_edge=D(1), far_edge=D(2),
                  free_to_near=D(1), zone_depth=D(1), free_to_far=D(2),
                  free_to_near_atr=0.0, zone_depth_atr=0.0, free_to_far_atr=0.0,
                  distance_to_near=D(1), distance_to_near_atr=0.0, watch="GO_LONG")


def test_no_watch_state_names_a_trade():
    for word in FORBIDDEN:
        assert not any(word in s for s in WATCH_STATES)


def test_the_watch_state_reads_price_while_the_free_space_reads_the_edge():
    """Two different questions. Room ahead is a property of the break level; where price
    is standing is a property of the close. Conflating them is the block-map bug."""
    z = node("C08", 60435, 60500)
    far_away = route_for(z, 60430, 60200, up=True)
    at_edge = route_for(z, 60430, 60434, up=True)
    assert far_away.free_to_near == at_edge.free_to_near == D("5")
    assert far_away.watch == "FAR_FROM_NEXT_ZONE"
    assert at_edge.watch == "AT_NEXT_ZONE"


# ─────────────────────────────────────────────────────────────────────────────
# 3. the corridor — ordered by price, not by label
# ─────────────────────────────────────────────────────────────────────────────
def test_case_c_parent_boundary_arrives_before_the_child():
    """current edge 44,033 · R01 44,243-44,757 · C08 44,304-44,334."""
    nodes = [node("C08", 44304, 44334), node("R01", 44243, 44757, "range")]
    stops = build_corridor(nodes, D("44033"), up=True, atr=D("40"))
    assert [(float(s.price), s.ref_id, s.edge) for s in stops] == [
        (44243.0, "R01", "near"),
        (44304.0, "C08", "near"),
        (44334.0, "C08", "far"),
        (44757.0, "R01", "far"),
    ]


def test_the_type_label_would_have_missed_the_parent():
    """`NEXT` is the nearest *cluster* — a type label, not an order. In case C it names
    C08 while price meets R01's boundary 61 points earlier."""
    nodes = [node("C08", 44304, 44334), node("R01", 44243, 44757, "range")]
    first = first_in_price(nodes, D("44033"), up=True)
    assert first.id == "R01"
    r = measure(first, D("44033"), D("44100"), up=True, atr=D("40"), tol=D("10"),
                label="FIRST_IN_PRICE")
    assert r.labels_agree is False
    assert r.free_to_near == D("210")


def test_nested_stops_names_the_parent_child_pair():
    nodes = [node("C08", 44304, 44334), node("R01", 44243, 44757, "range")]
    stops = build_corridor(nodes, D("44033"), up=True, atr=D("40"))
    assert nested_stops(stops) == [("R01", "C08")]


def test_the_corridor_keeps_a_far_edge_whose_near_edge_is_behind():
    """A range price is already standing inside still owns a boundary ahead. `NEXT` and
    `NEXT_MAJOR` never mention it; the corridor must."""
    inside_me = node("R01", 44000, 44700, "range")
    stops = build_corridor([inside_me, node("C08", 44304, 44334)],
                           D("44100"), up=True, atr=D("40"))
    ids = [(s.ref_id, s.edge) for s in stops]
    assert ("R01", "far") in ids
    assert ("R01", "near") not in ids           # 44,000 is behind the origin edge
    assert first_in_price([inside_me], D("44100"), up=True) is None


def test_the_corridor_is_direction_specific():
    nodes = [node("A", 100, 160), node("B", 200, 260)]
    up = build_corridor(nodes, D("90"), up=True, atr=D("10"))
    down = build_corridor(nodes, D("270"), up=False, atr=D("10"))
    assert [s.price for s in up] == [D(100), D(160), D(200), D(260)]
    assert [s.price for s in down] == [D(260), D(200), D(160), D(100)]
    assert [s.edge for s in down[:2]] == ["near", "far"]


def test_the_corridor_is_capped_and_stable():
    nodes = [node(f"C{i:02d}", 100 + 20 * i, 110 + 20 * i) for i in range(12)]
    stops = build_corridor(nodes, D("50"), up=True, atr=D("10"), limit=5)
    assert len(stops) == 5
    assert [float(s.distance) for s in stops] == sorted(float(s.distance)
                                                        for s in stops)
    assert corridor_line(stops).count("·") == 4
    assert corridor_line(()) == "—"


# ─────────────────────────────────────────────────────────────────────────────
# 4. regression: nothing about the break level moved
# ─────────────────────────────────────────────────────────────────────────────
def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=9, minute=15)
    return [Candle("NIFTY BANK", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   D(str(o)), D(str(h)), D(str(l)), D(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path(closes, wick: float = 1.5):
    out, prev = [], closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def sit(price: float, n: int, width: float = 18.0):
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


@pytest.fixture
def banknifty():
    """The same 22460-22480 fixture `test_livemap.py` pins, re-read for the route."""
    closes = (sit(22470, SPLIT + 30, width=20) + ramp(22482, 22550, 25)
              + sit(22560, 45, width=8) + ramp(22572, 22650, 22))
    candles = make(path(closes))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    f = run(snap, candles[:SPLIT], candles[SPLIT:])
    return interpret(snap, f)


def test_the_break_level_is_still_the_structures_own_edge(banknifty):
    for s in banknifty:
        if s.current is None:
            continue
        assert s.break_up == s.current.high
        assert s.break_down == s.current.low


def test_the_far_edge_is_never_the_current_break_level(banknifty):
    """§7 of the request, asserted rather than trusted. The next zone's far edge is a
    conditional second boundary; promoting it to a trigger would be a silent rule change.
    """
    for s in banknifty:
        if s.break_up is None:
            continue
        for r, up in ((s.route_above, True), (s.route_below, False)):
            if r is None:
                continue
            edge = s.break_up if up else s.break_down
            assert r.origin_edge == edge
            assert r.near_edge > edge if up else r.near_edge < edge
            assert r.far_edge != edge


def test_space_is_unchanged_and_the_route_is_purely_additive(banknifty):
    """`space_above` still comes off `above.next`, byte for byte. When the labelled NEXT
    is also the first zone in price order the two agree; when they disagree, that is the
    finding the corridor exists to expose, not a regression."""
    agreed = disagreed = 0
    for s in banknifty:
        if s.above.next is not None:
            assert s.space_above == s.above.next.distance
        if s.below.next is not None:
            assert s.space_below == abs(s.below.next.distance)
        for r, space in ((s.route_above, s.space_above),
                         (s.route_below, s.space_below)):
            if r is None or space is None:
                continue
            if r.labels_agree:
                assert r.free_to_near == space
                agreed += 1
            else:
                disagreed += 1
    assert agreed, "the fixture never exercised the agreeing case"


def test_the_rendered_route_says_nothing_a_trader_could_execute(banknifty):
    for s in banknifty:
        for line in s.lines():
            for word in FORBIDDEN:
                assert word not in line.split(), f"c{s.index}: {line!r}"


def test_the_route_block_is_rendered(banknifty):
    state = next(s for s in banknifty
                 if s.route_above is not None or s.route_below is not None)
    text = "\n".join(state.lines())
    for want in ("NEXT ZONE", "FIRST EDGE", "FAR EDGE", "FREE TO FIRST",
                 "ZONE DEPTH", "FREE TO FAR", "WATCH", "CORRIDOR"):
        assert want in text, f"{want} missing from the rendered state"
    assert "SPACE" in text, "the pre-existing SPACE line was removed"


def test_every_route_on_real_shaped_data_is_internally_consistent(banknifty):
    seen = 0
    for s in banknifty:
        for r in (s.route_above, s.route_below):
            if r is None:
                continue
            seen += 1
            assert r.free_to_far == r.free_to_near + r.zone_depth
            assert r.watch in WATCH_STATES
            assert (r.near_edge < r.far_edge) == (r.direction == "up")
    assert seen > 50, f"only {seen} routes — the fixture is not exercising this"
