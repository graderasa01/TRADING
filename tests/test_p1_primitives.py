"""
ATR and swing pivots — the two primitives everything in P1 is built on.

Expected values are computed by hand from the spec text (BUILD-BRIEF §5), not recorded
from a run. Where a real session is used the assertion is on a property that can be
checked independently, never on a remembered number.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.domain.models import IST, Candle, to_decimal
from src.feed.aggregator import aggregate_all
from src.feed.replay_feed import ReplayFeed
from src.indicators.atr import ATR_FAST, ATR_SLOW, AtrBook, AtrTracker
from src.indicators.swings import DEFAULT_K, SwingDetector, find_pivots

DAY = date(2026, 3, 4)


def c(i: int, o: float, h: float, l: float, cl: float, *, synthetic: bool = False,
      tf: str = "1m") -> Candle:
    span = {"1m": 1, "5m": 5, "15m": 15}[tf]
    start = datetime.combine(DAY, dtime(9, 15), tzinfo=IST) + timedelta(minutes=i * span)
    return Candle("TEST", tf, start, start + timedelta(minutes=span),
                  to_decimal(o), to_decimal(h), to_decimal(l), to_decimal(cl),
                  synthetic=synthetic)


def flat(i: int, price: float = 100.0) -> Candle:
    return c(i, price, price, price, price)


# ─────────────────────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────────────────────
def test_atr_is_none_until_the_period_is_full():
    t = AtrTracker(14)
    for i in range(13):
        assert t.update(c(i, 100, 110, 90, 100)) is None
        assert not t.ready
    assert t.warmup_remaining == 1
    assert t.update(c(13, 100, 110, 90, 100)) == Decimal(20)
    assert t.ready


def test_atr_is_the_plain_mean_of_range():
    """D-012: mean of (high - low). Not true range, not Wilder smoothing."""
    t = AtrTracker(3)
    t.update(c(0, 100, 110, 100, 105))     # range 10
    t.update(c(1, 105, 125, 105, 120))     # range 20
    assert t.update(c(2, 120, 150, 120, 140)) == Decimal(20)    # (10+20+30)/3


def test_atr_ignores_the_overnight_gap_by_construction():
    """A true-range ATR would fold yesterday's close into today's first candle. On a
    gap day that single value can dwarf every other and poison the first 14 minutes."""
    t = AtrTracker(2)
    t.update(c(0, 100, 110, 100, 105))                 # range 10
    assert t.update(c(1, 500, 510, 500, 505)) == Decimal(10)   # a 395-pt gap, ignored


def test_atr_rolls_and_forgets():
    t = AtrTracker(2)
    t.update(c(0, 100, 200, 100, 150))     # range 100
    t.update(c(1, 100, 110, 100, 105))     # range 10
    assert t.value == Decimal(55)
    t.update(c(2, 100, 110, 100, 105))     # range 10 — the 100 falls out
    assert t.value == Decimal(10)


def test_synthetic_candles_do_lower_atr():
    """Deliberate: a forward-filled minute really was a minute in which nothing traded.
    D-009 excludes synthetic candles from pattern detection, not from volatility."""
    t = AtrTracker(2)
    t.update(c(0, 100, 120, 100, 110))                       # range 20
    assert t.update(flat(1)) == Decimal(10)                  # (20 + 0) / 2


def test_atr_book_records_history_for_departure_speed():
    """departure_speed divides by the ATR *at birth*, not the ATR now — otherwise a
    level's grade drifts with volatility long after it formed."""
    book = AtrBook()
    for i in range(ATR_SLOW):
        book.on_1m(c(i, 100, 110, 90, 100))                  # range 20 throughout
    for i in range(ATR_SLOW, ATR_SLOW + 5):
        book.on_1m(c(i, 100, 200, 0, 100))                   # range 200 — a vol burst
    assert book.slow_at(ATR_SLOW - 1) == Decimal(20)          # unaffected by the future
    assert book.slow_at(ATR_SLOW - 2) is None                 # still in warmup there
    assert book.atr20_1m > Decimal(20)


def test_atr_book_periods_are_distinct():
    assert (ATR_FAST, ATR_SLOW) == (14, 20)
    book = AtrBook()
    for i in range(15):
        book.on_1m(c(i, 100, 110, 90, 100))
    assert book.atr_1m == Decimal(20)      # 14 is ready
    assert book.atr20_1m is None           # 20 is not


def test_atr_reset_between_sessions():
    book = AtrBook()
    for i in range(20):
        book.on_1m(c(i, 100, 110, 90, 100))
    book.reset()
    assert book.atr_1m is None and book.slow_at(0) is None


# ─────────────────────────────────────────────────────────────────────────────
# swings
# ─────────────────────────────────────────────────────────────────────────────
def test_k_matches_the_spec():
    assert DEFAULT_K == {"1m": 3, "5m": 2, "15m": 2}


def test_swing_needs_right_bars_before_it_is_emitted():
    """Spec 03 §2a: 'Emitting an unconfirmed swing is a look-ahead bug.'

    The pivot sits at index 3; with k=3 it can only appear when index 6 closes.
    """
    highs = [10, 20, 30, 99, 30, 20, 10]
    det = SwingDetector("1m", k=3)
    emitted_at = []
    for i, h in enumerate(highs):
        for _ in det.on_candle(c(i, h - 5, h, h - 10, h - 5)):
            emitted_at.append(i)
    assert emitted_at == [6], "the pivot must appear exactly when its 3rd right bar closes"


def test_pivot_index_points_at_the_pivot_not_at_the_confirmation():
    highs = [10, 20, 30, 99, 30, 20, 10]
    pivots = find_pivots([c(i, h - 5, h, h - 10, h - 5) for i, h in enumerate(highs)], "1m")
    assert len(pivots) == 1
    assert pivots[0].index == 3 and pivots[0].price == Decimal(99)


def test_flat_double_top_produces_no_pivot():
    """Strict inequality both sides. Two equal highs mean the turn has not happened."""
    highs = [10, 20, 99, 99, 20, 10, 5, 5]
    assert not [p for p in find_pivots(
        [c(i, h - 5, h, h - 10, h - 5) for i, h in enumerate(highs)], "1m") if p.is_high]


def test_synthetic_candle_is_never_a_pivot():
    """D-009 — a forward-filled candle is not a place price turned, it is a place
    price was absent."""
    candles = [c(0, 95, 100, 90, 95), c(1, 95, 100, 90, 95), c(2, 95, 100, 90, 95),
               Candle("TEST", "1m",
                      datetime.combine(DAY, dtime(9, 18), tzinfo=IST),
                      datetime.combine(DAY, dtime(9, 19), tzinfo=IST),
                      Decimal(200), Decimal(200), Decimal(200), Decimal(200),
                      synthetic=True),
               c(4, 95, 100, 90, 95), c(5, 95, 100, 90, 95), c(6, 95, 100, 90, 95)]
    assert find_pivots(candles, "1m") == []


def test_both_a_high_and_a_low_can_confirm_on_one_candle():
    """An outside bar surrounded by inside bars is both. Rare, but the return type is
    a list for this reason."""
    body = [(95, 105), (96, 104), (97, 103), (80, 120), (97, 103), (96, 104), (95, 105)]
    pivots = find_pivots([c(i, (l + h) / 2, h, l, (l + h) / 2)
                          for i, (l, h) in enumerate(body)], "1m")
    assert {p.swing.kind for p in pivots} == {"high", "low"}
    assert all(p.index == 3 for p in pivots)


def test_a_pivot_is_emitted_only_once():
    """No (index, kind) may be emitted twice, however many genuine pivots exist.

    This fixture holds two: a high at index 3 and a low at index 6 (lows are
    [0,10,20,89,20,10,0,2,4,6], so index 6 is a V-bottom under spec 03 §2a's
    symmetric definition). Asserting a total of 1 here would be asserting that the
    swing-low rule does not work.
    """
    highs = [10, 20, 30, 99, 30, 20, 10, 12, 14, 16]
    det = SwingDetector("1m", k=3)
    emitted = [(p.index, p.swing.kind)
               for i, h in enumerate(highs)
               for p in det.on_candle(c(i, h - 5, h, h - 10, h - 5))]
    assert len(emitted) == len(set(emitted)), f"duplicate emission: {emitted}"
    assert set(emitted) == {(3, "high"), (6, "low")}


def test_streaming_matches_batch_on_a_real_session():
    """A batch/stream divergence is how a backtest and a live run disagree about the
    same day without either looking wrong."""
    candles = list(ReplayFeed("NIFTY BANK").session(DAY).candles)
    det = SwingDetector("1m")
    streamed = [p for candle in candles for p in det.on_candle(candle)]
    assert streamed == find_pivots(candles, "1m")


def test_confirmation_lag_is_visible():
    """A 15m pivot is 30 minutes old the moment it exists — which is why spec 03 §2a
    runs detection 15m first and lets faster timeframes merge into it."""
    assert SwingDetector("15m").confirmation_lag == 2
    assert SwingDetector("1m").confirmation_lag == 3


@pytest.mark.parametrize("tf,expected_lag_minutes", [("1m", 3), ("5m", 10), ("15m", 30)])
def test_lag_in_wall_clock_minutes(tf, expected_lag_minutes):
    span = {"1m": 1, "5m": 5, "15m": 15}[tf]
    assert SwingDetector(tf).confirmation_lag * span == expected_lag_minutes


def test_real_session_pivot_counts_are_plausible():
    """Not a recorded number — a sanity band. 375 candles with k=3 cannot produce
    hundreds of pivots, and a detector producing none is broken."""
    session = ReplayFeed("NIFTY BANK").session(DAY)
    ups = aggregate_all(list(session.candles))
    counts = {
        "1m": len(find_pivots(list(session.candles), "1m")),
        "5m": len(find_pivots([u.m5 for u in ups if u.m5], "5m")),
        "15m": len(find_pivots([u.m15 for u in ups if u.m15], "15m")),
    }
    assert 10 <= counts["1m"] <= 120
    assert 4 <= counts["5m"] <= 40
    assert 1 <= counts["15m"] <= 14
    assert counts["1m"] > counts["5m"] > counts["15m"], "faster timeframes see more turns"
