"""
LevelEngine — spec 03 §11's named tests, plus a regression for every bug the first
runs on real data exposed.

Six bugs were found by running the engine over 30 real sessions. Not one of them fails
a unit test written from the spec text alone, and not one is visible from reading the
code — they are all distribution problems that only appear at scale. Each has a test
here named for what it protects, because the next refactor will not remember them.

    1  breaks were non-directional      -> every level broke twice, 523 axes/session
    2  round numbers sat in the book    -> 89% Grade B, a full-looking empty book
    3  capped-out levels were frozen    -> they stopped ageing and came back stale
    4  an axis breaking made an axis    -> 62% of all breaks were axes eating axes
    5  clusters counted extremes        -> spec 03 §2b says "wicks whose TIPS"
    6  acceptance was non-directional   -> book starved to 2; dormancy unreachable

Expected values are computed by hand from the spec text (BUILD-BRIEF §5).
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.config.loader import load_config
from src.domain.models import IST, Candle, Grade, LevelKind, LevelSide, to_decimal
from src.feed.aggregator import Aggregator
from src.feed.replay_feed import ReplayFeed
from src.indicators.atr import AtrBook
from src.levels.detectors import find_wick_clusters, round_numbers
from src.levels.engine import LevelEngine

DAY = date(2026, 3, 4)
SYMBOL = "TEST"


@pytest.fixture(scope="module")
def cfg():
    return load_config(strict=False)


def c(i: int, o: float, h: float, l: float, cl: float, *, synthetic: bool = False) -> Candle:
    start = datetime.combine(DAY, dtime(9, 15), tzinfo=IST) + timedelta(minutes=i)
    return Candle(SYMBOL, "1m", start, start + timedelta(minutes=1),
                  to_decimal(o), to_decimal(h), to_decimal(l), to_decimal(cl),
                  synthetic=synthetic)


def drive(engine: LevelEngine, candles: list[Candle], atr20: float | None = 20.0) -> None:
    """Feed candles with a fixed ATR so thresholds are predictable by hand."""
    agg = Aggregator()
    for candle in candles:
        update = agg.on_candle(candle)
        engine.on_candle(candle, None if atr20 is None else to_decimal(atr20),
                         update.m5, update.m15)


def quiet(n: int, start: int = 0, price: float = 1000.0) -> list[Candle]:
    """Candles that create no pivots and touch nothing — filler."""
    return [c(start + k, price, price + 1, price - 1, price) for k in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# geometry — spec 03 §4
# ─────────────────────────────────────────────────────────────────────────────
def test_zone_and_pocket_geometry():
    from src.domain.models import Level

    lv = Level(id="x", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
               born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
               body_edge=Decimal(100), wick_tip=Decimal(90))
    assert (lv.zone_low, lv.zone_high, lv.pocket) == (Decimal(90), Decimal(100), Decimal(10))


def test_round_number_zero_pocket_does_not_divide_by_zero(cfg):
    """Spec 03 §6: round numbers are body_edge == wick_tip. Every consumer must
    survive pocket == 0."""
    engine = LevelEngine(cfg, SYMBOL, Decimal(1100), Decimal(900), Decimal(1000))
    drive(engine, quiet(30))
    rounds = [lv for lv in engine.book.rounds.values()]
    assert rounds, "the round-number grid must produce levels"
    assert all(lv.pocket == 0 for lv in rounds)
    assert engine.obstacles(Decimal(1000), "up") is not None


def test_round_number_grid_arithmetic():
    assert round_numbers(Decimal(950), Decimal(1250), 100) == \
        [Decimal(1000), Decimal(1100), Decimal(1200)]
    assert round_numbers(Decimal(1000), Decimal(1000), 100) == [Decimal(1000)]
    assert round_numbers(Decimal(1250), Decimal(950), 100) == []


# ─────────────────────────────────────────────────────────────────────────────
# BUG 5 regression — wick clusters need actual wicks
# ─────────────────────────────────────────────────────────────────────────────
def test_wick_cluster_requires_a_real_wick():
    """Spec 03 §2b: "wicks whose TIPS fall within tolerance". A candle that closed at
    its high has no upper wick, so there was no rejection at that price."""
    # A candle has TWO wicks, so a fixture must silence the side it is not testing.
    # open == low leaves no lower wick; close == high leaves no upper wick.
    no_upper = [c(0, 89, 100, 89, 100), c(1, 89, 100, 89, 100)]
    assert find_wick_clusters(no_upper, 1, min_touches=2,
                              tolerance=Decimal(5), window=30) == []

    # same highs, but now each leaves a wick above the body and none below
    with_upper = [c(0, 89, 100, 89, 95), c(1, 89, 100, 89, 95)]
    clusters = find_wick_clusters(with_upper, 1, min_touches=2,
                                  tolerance=Decimal(5), window=30)
    assert [x.side for x in clusters] == [LevelSide.RESISTANCE]
    assert clusters[0].wick_tip == Decimal(100)


def test_wick_cluster_body_edge_is_the_mean_of_body_extremes():
    """Spec 03 §2b: 'body_edge = the mean of the body extremes of the clustered
    candles'. Bodies top at 95 and 97 -> 96."""
    candles = [c(0, 89, 100, 89, 95), c(1, 89, 100, 89, 97)]
    cluster = next(x for x in find_wick_clusters(candles, 1, min_touches=2,
                                                 tolerance=Decimal(5), window=30)
                   if x.side is LevelSide.RESISTANCE)
    assert cluster.body_edge == Decimal(96)


def test_wick_cluster_respects_the_window():
    candles = [c(0, 89, 100, 89, 95)] + quiet(40, 1, 500) + [c(41, 89, 100, 89, 95)]
    assert find_wick_clusters(candles, 41, min_touches=2,
                              tolerance=Decimal(5), window=30) == []


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1 regression — breaks are directional
# ─────────────────────────────────────────────────────────────────────────────
def test_support_breaks_downward_only(cfg):
    """A support with price ABOVE it is a healthy untested support, not a broken one.

    Checking both directions on every level made each break twice — once going past and
    once coming back — which manufactured 523 axes in a single session.
    """
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    support = Level(id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
                    born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST),
                    born_tf="1m", body_edge=Decimal(1000), wick_tip=Decimal(995),
                    grade=Grade.A)
    engine.book.live["S"] = support
    engine.candles.append(c(0, 1050, 1055, 1045, 1052))
    engine._breaks(engine.candles[0], 0, Decimal(20))     # body entirely ABOVE -> arms it
    assert "S" in engine.book.live, "price above a support must not break it"
    assert engine.book.live["S"].armed, "price on the defending side arms the level"

    engine.candles.append(c(1, 990, 992, 980, 985))       # body entirely BELOW
    engine._breaks(engine.candles[1], 1, Decimal(20))
    assert "S" not in engine.book.live
    assert engine.book.dead["S"].death_reason == "broken"


def test_resistance_breaks_upward_only(cfg):
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["R"] = Level(
        id="R", kind=LevelKind.TURN, side=LevelSide.RESISTANCE,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(1005), grade=Grade.A)
    engine.candles.append(c(0, 950, 955, 945, 952))
    engine._breaks(engine.candles[0], 0, Decimal(20))
    assert "R" in engine.book.live, "price below a resistance must not break it"


def test_break_creates_axis_and_kills_the_old_level(cfg):
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), grade=Grade.A)
    engine.candles.append(c(0, 1010, 1015, 1005, 1012))   # price defends it first: arms
    engine._breaks(engine.candles[0], 0, Decimal(20))
    engine.candles.append(c(1, 990, 992, 975, 980))
    engine._breaks(engine.candles[1], 1, Decimal(20))
    axes = [lv for lv in engine.book.live.values() if lv.kind is LevelKind.BREAK]
    assert len(axes) == 1
    assert axes[0].body_edge == Decimal(1000), "the axis sits at the broken body_edge"
    assert axes[0].side is LevelSide.AXIS
    assert engine.axis_id == axes[0].id


def test_grade_c_break_kills_without_creating_an_axis(cfg):
    """Spec 03 §5 v2.2 (Bug 5): a Grade C level breaking is not news."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), grade=Grade.C)
    engine.candles.append(c(0, 1010, 1015, 1005, 1012))   # arms
    engine._breaks(engine.candles[0], 0, Decimal(20))
    engine.candles.append(c(1, 990, 992, 975, 980))
    engine._breaks(engine.candles[1], 1, Decimal(20))
    assert "S" not in engine.book.live
    assert not [lv for lv in engine.book.live.values() if lv.kind is LevelKind.BREAK]


# ─────────────────────────────────────────────────────────────────────────────
# BUG 4 regression — an axis that fails does not mint another axis
# ─────────────────────────────────────────────────────────────────────────────
def test_broken_axis_dies_as_flip_failed_and_makes_no_new_axis(cfg):
    """Spec 03 §5 calls the axis "the invalidation line (body close back through it =
    the move failed)". Minting a fresh axis there re-arms, on every oscillation, the one
    level that just proved unreliable. Measured: 62% of all breaks were axes eating axes.
    """
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["AX"] = Level(
        id="AX", kind=LevelKind.BREAK, side=LevelSide.AXIS,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(990), grade=Grade.A, armed=True)
    engine.axis_id = "AX"
    engine.candles.append(c(0, 985, 988, 975, 980))       # closes back through
    engine._breaks(engine.candles[0], 0, Decimal(20))

    assert engine.book.dead["AX"].death_reason == "flip_failed"
    assert not [lv for lv in engine.book.live.values() if lv.kind is LevelKind.BREAK]
    assert engine.axis_id is None


# ─────────────────────────────────────────────────────────────────────────────
# BUG 6 regression — acceptance is directional
# ─────────────────────────────────────────────────────────────────────────────
def test_price_sitting_above_a_support_is_not_acceptance(cfg):
    """Non-directional acceptance emptied the book to ~2 levels a session and made the
    dormant pool unreachable — every level died before it could travel far enough to
    sleep, and every run reported '0 sleeps / 0 revivals'."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    support = Level(id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
                    born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST),
                    born_tf="1m", body_edge=Decimal(1000), wick_tip=Decimal(995))
    engine.candles = [c(k, 1050, 1055, 1045, 1052) for k in range(6)]
    assert engine._accepted_through(support, 5, 5) is False

    engine.candles = [c(k, 950, 955, 945, 952) for k in range(6)]
    assert engine._accepted_through(support, 5, 5) is True


def test_acceptance_requires_consecutive_closes(cfg):
    """D-024. Five scattered closes describe price passing by; five in a row describe
    price having moved on."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    support = Level(id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
                    born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST),
                    born_tf="1m", body_edge=Decimal(1000), wick_tip=Decimal(995))
    engine.candles = [c(0, 950, 955, 945, 952), c(1, 950, 955, 945, 952),
                      c(2, 1050, 1055, 1045, 1052),          # one candle back above
                      c(3, 950, 955, 945, 952), c(4, 950, 955, 945, 952)]
    assert engine._accepted_through(support, 4, 5) is False


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2 regression — touches are events, not minutes
# ─────────────────────────────────────────────────────────────────────────────
def test_hovering_is_one_touch_not_three(cfg):
    """Spec 03 §4 v2.2. In the dry run PDL died at 09:57 from three minutes of
    hovering — two minutes before its own sweep, the flagship trade of the day."""
    engine = LevelEngine(cfg, SYMBOL, pdl=Decimal(1000))
    engine.candles.append(c(0, 1001, 1002, 999, 1001))
    engine._seed_anchors(engine.candles[0], 0, Decimal(20))
    pdl_id = next(k for k, v in engine.book.live.items() if v.body_edge == Decimal(1000))

    for k in range(3):                                    # three minutes in the zone
        candle = c(k, 1001, 1002, 999, 1001)
        engine.candles.append(candle)
        engine._touches(candle, k, Decimal(20))
    assert engine.book.live[pdl_id].touches == 1


def test_a_new_touch_needs_separation_first(cfg):
    """Price must LEAVE by max(8 pts, 0.6 x ATR) before the next entry counts."""
    engine = LevelEngine(cfg, SYMBOL, pdl=Decimal(1000))
    engine.candles.append(c(0, 1001, 1002, 999, 1001))
    engine._seed_anchors(engine.candles[0], 0, Decimal(20))
    pdl_id = next(k for k, v in engine.book.live.items() if v.body_edge == Decimal(1000))

    for candle in (c(0, 1001, 1002, 999, 1001),        # touch 1
                   c(1, 1004, 1005, 1003, 1004),       # away, but only 3 pts — not enough
                   c(2, 1001, 1002, 999, 1001),        # back in: still touch 1
                   c(3, 1030, 1032, 1028, 1030),       # genuinely gone (30 pts > 12)
                   c(4, 1001, 1002, 999, 1001)):       # back in: touch 2
        engine.candles.append(candle)
        engine._touches(candle, len(engine.candles) - 1, Decimal(20))
    assert engine.book.live[pdl_id].touches == 2


def test_third_touch_exhausts_the_level(cfg):
    """Spec 03 §8: touches >= max_touches (3) -> exhausted."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), touches=3)
    engine.candles.append(c(0, 1000, 1001, 999, 1000))
    engine._deaths(engine.candles[0], 0, Decimal(20))
    assert engine.book.dead["S"].death_reason == "exhausted"


def test_synthetic_candle_does_not_count_a_touch(cfg):
    """D-009: synthetic candles only advance the clock."""
    engine = LevelEngine(cfg, SYMBOL, pdl=Decimal(1000))
    engine.candles.append(c(0, 1001, 1002, 999, 1001))
    engine._seed_anchors(engine.candles[0], 0, Decimal(20))
    pdl_id = next(k for k, v in engine.book.live.items() if v.body_edge == Decimal(1000))
    fake = c(1, 1000, 1000, 1000, 1000, synthetic=True)
    engine.candles.append(fake)
    engine._touches(fake, 1, Decimal(20))
    assert engine.book.live[pdl_id].touches == 0


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2 regression — round numbers live outside the book
# ─────────────────────────────────────────────────────────────────────────────
def test_round_numbers_are_not_in_the_book(cfg):
    """Spec 03 §6: never Grade A, never triggers ALERT, never counts against the cap.
    Keeping ~30 of them in the book made 89% of it Grade B and reported a full book on
    a session whose real book held two levels."""
    engine = LevelEngine(cfg, SYMBOL, Decimal(1100), Decimal(900), Decimal(1000))
    drive(engine, quiet(30))
    assert engine.book.rounds, "round numbers must still exist as obstacles"
    assert all(not lv.is_round_number for lv in engine.book.live.values())
    assert all(lv.grade is not Grade.A for lv in engine.book.rounds.values())


def test_round_numbers_do_not_count_against_the_cap(cfg):
    engine = LevelEngine(cfg, SYMBOL, Decimal(1500), Decimal(500), Decimal(1000))
    drive(engine, quiet(40))
    assert len(engine.book.rounds) > 8
    assert len(engine.book.active()) <= 8


# ─────────────────────────────────────────────────────────────────────────────
# grading — spec 03 §7
# ─────────────────────────────────────────────────────────────────────────────
def test_anchor_can_reach_grade_a(cfg):
    """Spec 03 §7 v2.2 and spec 10 §3.3. Bug 1: if an ANCHOR cannot be Grade A then
    Setup B — which spec 06 makes the ONLY permitted setup at an anchor — can never
    fire at PDH or PDL, the exact locations spec 06 calls most important."""
    engine = LevelEngine(cfg, SYMBOL, Decimal(1200), Decimal(800), Decimal(1000))
    drive(engine, quiet(30, price=1000))
    anchors = [lv for lv in engine.book.live.values() if lv.kind is LevelKind.ANCHOR]
    assert anchors, "PDH/PDL/PDC must be created"
    assert any(lv.grade is Grade.A for lv in anchors), \
        "an untested anchor scores untested + HTF + clean = 3 = Grade A"


def test_touched_anchor_drops_below_grade_a(cfg):
    engine = LevelEngine(cfg, SYMBOL, pdl=Decimal(1000))
    engine.candles.append(c(0, 1001, 1002, 999, 1001))
    engine._seed_anchors(engine.candles[0], 0, Decimal(20))
    pdl_id = next(k for k, v in engine.book.live.items() if v.body_edge == Decimal(1000))
    engine._regrade(0)
    assert engine.book.live[pdl_id].grade is Grade.A
    engine._touches(engine.candles[0], 0, Decimal(20))
    engine._regrade(0)
    assert engine.book.live[pdl_id].grade is Grade.B, "untested point is lost on a touch"


def test_round_number_can_never_be_grade_a(cfg):
    """Spec 03 §6: a 100-mark has no order-flow history behind it."""
    engine = LevelEngine(cfg, SYMBOL, Decimal(1100), Decimal(900), Decimal(1000))
    drive(engine, quiet(30))
    assert all(lv.grade is not Grade.A for lv in engine.book.rounds.values())


# ─────────────────────────────────────────────────────────────────────────────
# the cap — spec 03 §8b + D-006
# ─────────────────────────────────────────────────────────────────────────────
def test_cap_keeps_the_nearest_two_each_side(cfg):
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    born = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    for k, price in enumerate([900, 940, 960, 980, 1020, 1040, 1060, 1100, 1140, 1180]):
        side = LevelSide.SUPPORT if price < 1000 else LevelSide.RESISTANCE
        engine.book.live[f"L{k}"] = Level(id=f"L{k}", kind=LevelKind.TURN, side=side,
                                          born_at=born, born_tf="1m",
                                          body_edge=Decimal(price), wick_tip=Decimal(price),
                                          grade=Grade.C)
    engine._apply_cap(c(0, 1000, 1001, 999, 1000))
    active = {lv.body_edge for lv in engine.book.active()}
    assert len(active) == 8
    for must in (980, 960, 1020, 1040):
        assert Decimal(must) in active, f"{must} is one of the nearest two on its side"


def test_capped_out_levels_still_age_and_die(cfg):
    """A level outside the cap is inactive for ALERT, not frozen. Freezing let it
    survive by being ignored and reappear stale when the cap widened."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    born = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    for k in range(12):
        engine.book.live[f"L{k}"] = Level(
            id=f"L{k}", kind=LevelKind.TURN, side=LevelSide.SUPPORT, born_at=born,
            born_tf="1m", body_edge=Decimal(500 + k), wick_tip=Decimal(500 + k),
            grade=Grade.C, touches=3)
    engine.candles.append(c(0, 1000, 1001, 999, 1000))
    engine._apply_cap(engine.candles[0])
    assert len(engine.book.active()) == 8 and len(engine.book.live) == 12
    engine._deaths(engine.candles[0], 0, Decimal(20))
    assert engine.book.live == {}, "every exhausted level dies, capped-out or not"


# ─────────────────────────────────────────────────────────────────────────────
# dormancy — spec 03 §8b, D-011d
# ─────────────────────────────────────────────────────────────────────────────
def test_distance_causes_dormancy_not_death(cfg):
    from src.domain.models import Level, LevelState

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), grade=Grade.A, touches=2)
    far = c(0, 1600, 1605, 1595, 1600)                  # 600 pts = 30 x ATR20
    engine.candles.append(far)
    engine._dormancy(far, 0, Decimal(20))
    assert "S" not in engine.book.live
    assert engine.book.dormant["S"].state is LevelState.DORMANT


def test_revived_level_keeps_its_touches(cfg):
    """D-011d. A level tested twice before it slept is on its THIRD touch when price
    returns — and the third touch is where the system stops taking reversals. Resetting
    it turns a known-exhausted level back into a Grade A trigger, precisely backwards."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), grade=Grade.A, touches=2)
    far = c(0, 1600, 1605, 1595, 1600)
    engine.candles.append(far)
    engine._dormancy(far, 0, Decimal(20))
    back = c(1, 1050, 1055, 1045, 1050)                 # within 15 x ATR20
    engine.candles.append(back)
    engine._dormancy(back, 1, Decimal(20))
    assert engine.book.live["S"].touches == 2
    assert engine.book.live["S"].born_at == datetime.combine(DAY, dtime(9, 15), tzinfo=IST)


def test_grade_c_dies_rather_than_sleeping(cfg):
    """Spec 03 §8b rule 4: otherwise the pool becomes a landfill."""
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.TURN, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1m",
        body_edge=Decimal(1000), wick_tip=Decimal(995), grade=Grade.C)
    far = c(0, 1600, 1605, 1595, 1600)
    engine.candles.append(far)
    engine._dormancy(far, 0, Decimal(20))
    assert engine.book.dead["S"].death_reason == "irrelevant"
    assert not engine.book.dormant


def test_revival_distance_is_inside_dormancy_distance(cfg):
    """spec 10 §3.3 reachability: otherwise levels flap awake and asleep."""
    assert cfg.dec("levels.revival_distance_atr_mult") < \
        cfg.dec("levels.dormancy_distance_atr_mult")


# ─────────────────────────────────────────────────────────────────────────────
# obstacles — spec 03 §6b and §9
# ─────────────────────────────────────────────────────────────────────────────
def test_round_100_cannot_gate_space_but_still_caps_t1(cfg):
    """Spec 03 §6b. v1 let a 100-mark veto trades, which made the space gate a coin
    flip on the entry price's last two digits."""
    engine = LevelEngine(cfg, SYMBOL, Decimal(1400), Decimal(600), Decimal(1000))
    drive(engine, quiet(30, price=1000))
    t1 = engine.t1_obstacle(Decimal(1030), "up")
    space = engine.space_obstacle(Decimal(1030), "up")
    assert t1 is not None and t1.price == Decimal(1100)
    assert space is None or space.price != Decimal(1100) or space.strength.value != "weak"
    assert not (t1.gates_space and t1.strength.value == "weak")


def test_obstacles_are_sorted_by_distance(cfg):
    engine = LevelEngine(cfg, SYMBOL, Decimal(1400), Decimal(600), Decimal(1000))
    drive(engine, quiet(30, price=1000))
    ups = engine.obstacles(Decimal(1000), "up")
    assert ups == sorted(ups, key=lambda o: o.price - Decimal(1000))
    assert all(o.price > Decimal(1000) for o in ups)


# ─────────────────────────────────────────────────────────────────────────────
# integration on real data
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real_run(cfg):
    session = ReplayFeed("NIFTY BANK").session(DAY)
    engine = LevelEngine(cfg, "NIFTY BANK", session.pdh, session.pdl, session.pdc)
    agg, atr = Aggregator(), AtrBook()
    grade_a_ever = set()
    for candle in session.candles:
        update = agg.on_candle(candle)
        atr.on_1m(candle)
        if update.m5:
            atr.on_5m(update.m5)
        engine.on_candle(candle, atr.atr20_1m, update.m5, update.m15)
        grade_a_ever |= {lv.id for lv in engine.book.grade_a()}
    return engine, grade_a_ever


def test_real_session_reaches_grade_a(real_run):
    """spec 10 §3.1 `grade_a_exists` is a FAIL, not a warn: with no Grade A level no
    setup can ever trigger. This is Bug 1, and it made ALERT 0% of the dry-run session."""
    _, grade_a_ever = real_run
    assert len(grade_a_ever) > 0


def test_real_session_fills_the_book(real_run):
    engine, _ = real_run
    assert 2 <= len(engine.book.active()) <= 8


def test_real_session_produces_every_level_kind(real_run):
    engine, _ = real_run
    kinds = {e["kind"] for e in engine.events if e["event"] == "born"}
    assert {"turn", "break", "anchor"} <= kinds


def test_no_level_outlives_its_ttl(real_run):
    """Spec 03 §8: 90 min for 1m-born, 120 for a BREAK axis, none for an ANCHOR."""
    engine, _ = real_run
    now = engine.candles[-1].open_time
    for lv in engine.book.live.values():
        if lv.kind is LevelKind.ANCHOR:
            continue
        limit = timedelta(minutes=120 if lv.kind is LevelKind.BREAK else 90)
        if lv.born_tf == "1m" or lv.kind is LevelKind.BREAK:
            assert now - lv.born_at <= limit, f"{lv.id} outlived its TTL"


def test_engine_is_deterministic(cfg):
    """Two runs over the same candles must produce an identical book. Without this,
    `test_board_is_deterministic` cannot hold and the paper result will not match live."""
    def run():
        session = ReplayFeed("NIFTY BANK").session(DAY)
        engine = LevelEngine(cfg, "NIFTY BANK", session.pdh, session.pdl, session.pdc)
        agg, atr = Aggregator(), AtrBook()
        for candle in session.candles:
            update = agg.on_candle(candle)
            atr.on_1m(candle)
            if update.m5:
                atr.on_5m(update.m5)
            engine.on_candle(candle, atr.atr20_1m, update.m5, update.m15)
        return [(lv.id, lv.body_edge, lv.grade, lv.touches) for lv in engine.book.active()]

    assert run() == run()


# ─────────────────────────────────────────────────────────────────────────────
# arming — a gap does not break a level
# ─────────────────────────────────────────────────────────────────────────────
def test_a_level_price_gapped_over_is_not_broken(cfg):
    """Spec 05 §1c: *"a gap does not erase yesterday's decision points — it just means
    we arrived at them from a different direction."*

    On 2026-03-04 the session gapped down through PDL. Without arming, the very first
    candle "broke" both PDL and PDC before the market had done anything, leaving the
    book with one anchor and the nearest live level 1,231 points away.
    """
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["PDL"] = Level(
        id="PDL", kind=LevelKind.ANCHOR, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1d",
        body_edge=Decimal(1000), wick_tip=Decimal(1000), grade=Grade.A)
    opened_below = c(0, 950, 955, 945, 952)
    engine.candles.append(opened_below)
    engine._breaks(opened_below, 0, Decimal(20))
    assert "PDL" in engine.book.live, "a gap-down open must not break PDL"
    assert not engine.book.live["PDL"].armed


def test_an_armed_level_breaks_normally(cfg):
    from src.domain.models import Level

    engine = LevelEngine(cfg, SYMBOL)
    engine.book.live["S"] = Level(
        id="S", kind=LevelKind.ANCHOR, side=LevelSide.SUPPORT,
        born_at=datetime.combine(DAY, dtime(9, 15), tzinfo=IST), born_tf="1d",
        body_edge=Decimal(1000), wick_tip=Decimal(1000), grade=Grade.A)
    for k, candle in enumerate((c(0, 1010, 1015, 1005, 1012),    # arms
                                c(1, 990, 995, 985, 988))):      # then breaks
        engine.candles.append(candle)
        engine._breaks(candle, k, Decimal(20))
    assert engine.book.dead["S"].death_reason == "broken"
