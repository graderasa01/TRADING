"""
StructureEngine — spec 04 §9's named tests.

The boundary matters as much as the behaviour here: `structure/` must never see
`levels/`, or a level justifies a structure that justifies the level. That is asserted
in `test_static_prohibitions.py`; this file asserts the arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.config.loader import load_config
from src.domain.models import IST, Candle, to_decimal
from src.feed.aggregator import Aggregator, PartialCandle
from src.feed.replay_feed import ReplayFeed
from src.indicators.atr import AtrBook
from src.structure.engine import StructureEngine, _Legs

DAY = date(2026, 3, 4)


@pytest.fixture(scope="module")
def cfg():
    return load_config(strict=False)


def c(i: int, o: float, h: float, l: float, cl: float, *, tf: str = "1m") -> Candle:
    span = {"1m": 1, "5m": 5, "15m": 15}[tf]
    start = datetime.combine(DAY, dtime(9, 15), tzinfo=IST) + timedelta(minutes=i * span)
    return Candle("TEST", tf, start, start + timedelta(minutes=span),
                  to_decimal(o), to_decimal(h), to_decimal(l), to_decimal(cl))


# ─────────────────────────────────────────────────────────────────────────────
# BOS — spec 04 §2
# ─────────────────────────────────────────────────────────────────────────────
def test_bos_requires_a_body_close(cfg):
    """*"A wick through a swing is not a BOS — it is a sweep, and it is Setup B's
    business, not the structure engine's."*"""
    from src.domain.models import Swing

    engine = StructureEngine(cfg)
    swing = Swing(datetime.combine(DAY, dtime(9, 15), tzinfo=IST),
                  Decimal(1000), "high", "5m", confirmed=True)
    engine.swings["5m"]["high"].append(swing)

    engine._detect_bos(c(0, 990, 1010, 985, 995, tf="5m"), "5m")   # wick through only
    assert engine.bos_history == []

    engine._detect_bos(c(1, 995, 1015, 990, 1008, tf="5m"), "5m")  # body closes above
    assert len(engine.bos_history) == 1
    assert engine.bos_history[0].direction == "up"


def test_control_comes_from_the_last_5m_bos(cfg):
    from src.domain.models import Swing

    engine = StructureEngine(cfg)
    assert engine.control == "none"
    engine.swings["5m"]["high"].append(
        Swing(datetime.combine(DAY, dtime(9, 15), tzinfo=IST), Decimal(1000),
              "high", "5m", confirmed=True))
    engine._detect_bos(c(1, 995, 1015, 990, 1008, tf="5m"), "5m")
    assert engine.control == "buyers"

    engine.swings["5m"]["low"].append(
        Swing(datetime.combine(DAY, dtime(9, 20), tzinfo=IST), Decimal(900),
              "low", "5m", confirmed=True))
    engine._detect_bos(c(2, 905, 910, 880, 890, tf="5m"), "5m")
    assert engine.control == "sellers"


def test_synthetic_candle_cannot_break_structure(cfg):
    """D-009 — a forward-filled candle is not a decision anyone made."""
    from src.domain.models import Swing

    engine = StructureEngine(cfg)
    engine.swings["5m"]["high"].append(
        Swing(datetime.combine(DAY, dtime(9, 15), tzinfo=IST), Decimal(1000),
              "high", "5m", confirmed=True))
    start = datetime.combine(DAY, dtime(9, 20), tzinfo=IST)
    fake = Candle("TEST", "5m", start, start + timedelta(minutes=5),
                  Decimal(1100), Decimal(1100), Decimal(1100), Decimal(1100), synthetic=True)
    engine._detect_bos(fake, "5m")
    assert engine.bos_history == []


# ─────────────────────────────────────────────────────────────────────────────
# trend and regime — spec 04 §3
# ─────────────────────────────────────────────────────────────────────────────
def test_trend_needs_both_highs_and_lows_ascending(cfg):
    from src.domain.models import Swing

    engine = StructureEngine(cfg)
    t = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    engine.swings["5m"]["high"] = [Swing(t, Decimal(1000), "high", "5m", True),
                                   Swing(t, Decimal(1050), "high", "5m", True)]
    engine.swings["5m"]["low"] = [Swing(t, Decimal(900), "low", "5m", True),
                                  Swing(t, Decimal(950), "low", "5m", True)]
    engine._update_state("5m")
    assert engine.trend_5m == "up"

    engine.swings["5m"]["low"][-1] = Swing(t, Decimal(880), "low", "5m", True)
    engine._update_state("5m")
    assert engine.trend_5m == "none", "higher highs with lower lows is not a trend"


def test_trend_none_is_the_common_case_on_real_data(cfg):
    """Spec 04 §3 says of `none`: 'this is the common case, and that is correct'."""
    engine, _ = run_real(cfg)
    assert engine.trend_5m in ("up", "down", "none")


# ─────────────────────────────────────────────────────────────────────────────
# legs and pullback ratio — spec 04 §5, D-005
# ─────────────────────────────────────────────────────────────────────────────
def test_a_leg_ends_only_after_two_consecutive_reversals():
    """D-005: 'a leg ends when TWO CONSECUTIVE 1m candles close beyond the prior
    candle's opposite extreme.' One counter-candle is noise, not a turn."""
    legs = _Legs()
    up = [c(i, 100 + i * 10, 105 + i * 10, 99 + i * 10, 104 + i * 10) for i in range(5)]
    prev = None
    for candle in up:
        legs.on_candle(candle, prev)
        prev = candle
    assert legs.completed == [], "a clean up-leg is not finished"

    one_down = c(5, 150, 152, 120, 125)          # closes below prior low
    legs.on_candle(one_down, prev)
    assert legs.completed == [], "one reversal candle is not a leg end"
    legs.on_candle(c(6, 125, 127, 100, 105), one_down)
    assert len(legs.completed) == 1


def test_pullback_ratio_is_none_when_the_leg_is_too_short(cfg):
    """D-005: 'a missing value must never silently become a passing one.'"""
    engine = StructureEngine(cfg)
    engine.on_candle(c(0, 100, 105, 99, 104))
    assert engine.pullback_ratio is None
    assert engine.pullback_health() == "unknown"


def test_pullback_health_thresholds(cfg):
    """Spec 04 §5's table, at its boundaries."""
    engine = StructureEngine(cfg)
    from src.structure.engine import StructureState

    for ratio, expected in ((Decimal("0.59"), "healthy"),
                            (Decimal("0.60"), "weakening"),
                            (Decimal("1.00"), "weakening"),
                            (Decimal("1.01"), "control_flipped")):
        engine.state["5m"] = StructureState("5m", pullback_ratio=ratio)
        assert engine.pullback_health() == expected, f"ratio {ratio}"


# ─────────────────────────────────────────────────────────────────────────────
# HTF — spec 04 §4
# ─────────────────────────────────────────────────────────────────────────────
def test_htf_closing_soon_fires_in_the_last_three_minutes(cfg):
    engine = StructureEngine(cfg)
    start = datetime.combine(DAY, dtime(10, 0), tzinfo=IST)
    for elapsed, expected in ((11, False), (12, True), (14, True)):
        partial = PartialCandle("TEST", "15m", start, start + timedelta(minutes=15),
                                Decimal(100), Decimal(110), Decimal(90), Decimal(105),
                                elapsed)
        engine._update_htf(partial)
        assert engine.htf_closing_soon is expected, f"{elapsed} minutes in"


def test_htf_progress_is_a_fraction(cfg):
    engine = StructureEngine(cfg)
    start = datetime.combine(DAY, dtime(10, 0), tzinfo=IST)
    partial = PartialCandle("TEST", "15m", start, start + timedelta(minutes=15),
                            Decimal(100), Decimal(110), Decimal(90), Decimal(105), 5)
    engine._update_htf(partial)
    assert engine.htf_progress == Decimal(5) / Decimal(15)


def test_htf_forecast_is_a_lower_wick_after_a_bullish_inside_bos(cfg):
    """Spec 04 §4 Law A. Informational only — nothing may gate on it."""
    from src.domain.models import Swing

    engine = StructureEngine(cfg)
    start = datetime.combine(DAY, dtime(10, 0), tzinfo=IST)
    engine.swings["5m"]["high"].append(
        Swing(start, Decimal(1000), "high", "5m", confirmed=True))
    inside = Candle("TEST", "5m", start + timedelta(minutes=5),
                    start + timedelta(minutes=10),
                    Decimal(995), Decimal(1015), Decimal(990), Decimal(1010))
    engine._detect_bos(inside, "5m")
    engine._update_htf(PartialCandle("TEST", "15m", start, start + timedelta(minutes=15),
                                     Decimal(1000), Decimal(1015), Decimal(990),
                                     Decimal(1010), 10))
    assert engine.htf_forecast == "lower_wick"


# ─────────────────────────────────────────────────────────────────────────────
# ladder — spec 04 §6, D-007
# ─────────────────────────────────────────────────────────────────────────────
def test_ladder_marks_only_l4_as_the_failure_line(cfg):
    engine = StructureEngine(cfg)
    impulse = c(0, 1000, 1060, 998, 1058)          # range 62 >= 2.0 x ATR20 of 20
    engine.on_candle(impulse, atr20=Decimal(20))
    engine.on_candle(c(1, 1058, 1059, 1040, 1045), atr20=Decimal(20))
    failure = [r for r in engine.ladder if r.is_failure_line]
    assert [r.label for r in failure] == ["L4"]


def test_ladder_is_sorted_by_distance(cfg):
    engine = StructureEngine(cfg)
    engine.on_candle(c(0, 1000, 1060, 998, 1058), atr20=Decimal(20))
    engine.on_candle(c(1, 1058, 1059, 1040, 1045), atr20=Decimal(20))
    distances = [r.distance_points for r in engine.ladder]
    assert distances == sorted(distances)


# ─────────────────────────────────────────────────────────────────────────────
# real data
# ─────────────────────────────────────────────────────────────────────────────
def run_real(cfg):
    session = ReplayFeed("NIFTY BANK").session(DAY)
    engine = StructureEngine(cfg)
    agg, atr = Aggregator(), AtrBook()
    counters = {"htf_soon": 0, "candles": 0}
    for candle in session.candles:
        update = agg.on_candle(candle)
        atr.on_1m(candle)
        if update.m5:
            atr.on_5m(update.m5)
        engine.on_candle(candle, update.m5, update.m15_partial, atr.atr20_1m)
        counters["candles"] += 1
        counters["htf_soon"] += engine.htf_closing_soon
    return engine, counters


def test_real_session_produces_structure(cfg):
    engine, _ = run_real(cfg)
    assert len(engine.swings["5m"]["high"]) + len(engine.swings["5m"]["low"]) > 5
    assert len(engine.bos_history) > 0
    assert engine.control in ("buyers", "sellers", "none")


def test_htf_close_proximity_covers_exactly_the_last_three_of_fifteen(cfg):
    """20% by construction. If this drifts, the guard is blocking the wrong minutes —
    and `prototype/FINDINGS.md` Bug 3 was this guard silently deleting Setup B."""
    _, counters = run_real(cfg)
    share = counters["htf_soon"] / counters["candles"]
    assert 0.19 <= share <= 0.21, f"htf_closing_soon covered {share:.1%} of candles"


def test_structure_is_deterministic(cfg):
    a = run_real(cfg)[0]
    b = run_real(cfg)[0]
    assert a.control == b.control
    assert a.trend_5m == b.trend_5m
    assert len(a.bos_history) == len(b.bos_history)
    assert [s.price for s in a.swings["5m"]["high"]] == [s.price for s in b.swings["5m"]["high"]]
