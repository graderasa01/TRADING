"""
P0 gate — spec 09 §3.3 and BUILD-BRIEF §2.

`test_no_lookahead_by_truncation` is the one that matters. If it passes, the paper
results are structurally trustworthy; if it fails, nothing else in any report means
anything. Everything else here exists to make its result believable.

Expected values are computed by hand from the spec text, not from a previous run
(BUILD-BRIEF §5). Where a real session is used, the assertion is against arithmetic
that can be checked independently — a 5m high is the max of five 1m highs, and that
is asserted directly rather than against a recorded number.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.domain.models import IST, Candle, InvariantError, to_decimal
from src.feed import replay_feed as replay_feed_mod
from src.feed.aggregator import (
    Aggregator, AlignmentError, PartialCandle, aggregate_all, bucket_start,
)
from src.feed.replay_feed import FeedGapError, ReplayFeed, classify_session

SYMBOL = "TEST"
DAY = date(2026, 3, 4)


def c(minute_offset: int, o: float, h: float, l: float, cl: float,
      *, synthetic: bool = False, tf: str = "1m") -> Candle:
    start = datetime.combine(DAY, dtime(9, 15), tzinfo=IST) + timedelta(minutes=minute_offset)
    span = {"1m": 1, "5m": 5, "15m": 15}[tf]
    return Candle(SYMBOL, tf, start, start + timedelta(minutes=span),
                  to_decimal(o), to_decimal(h), to_decimal(l), to_decimal(cl),
                  synthetic=synthetic)


# ─────────────────────────────────────────────────────────────────────────────
# domain invariants
# ─────────────────────────────────────────────────────────────────────────────
def test_close_above_high_is_rejected():
    """prototype/gen.py:39 built exactly this candle — the planted 09:57 sweep, with
    close 57464 above high 57457 — and the whole dry run measured it without noticing."""
    with pytest.raises(InvariantError, match="OHLC impossible"):
        c(0, 57453.15, 57457.15, 57434.0, 57464.0)


def test_naive_datetime_is_rejected():
    t = datetime(2026, 3, 4, 9, 15)      # no tzinfo
    with pytest.raises(InvariantError, match="naive"):
        Candle(SYMBOL, "1m", t, t + timedelta(minutes=1),
               Decimal(1), Decimal(2), Decimal(0), Decimal(1))


def test_candle_span_must_match_its_timeframe():
    t = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    with pytest.raises(InvariantError, match="spans"):
        Candle(SYMBOL, "5m", t, t + timedelta(minutes=1),
               Decimal(1), Decimal(2), Decimal(0), Decimal(1))


def test_decimal_conversion_uses_repr_not_float():
    """D-014. Decimal(57434.05) is 57434.0499999...; the loader must not produce that."""
    assert to_decimal(57434.05) == Decimal("57434.05")
    assert str(to_decimal(57434.05)) == "57434.05"
    assert to_decimal(57434.05) != Decimal(57434.05)


def test_close_position_and_third_by_hand():
    # range 20, close 4 above low -> 0.20 -> bottom third
    assert c(0, 100, 110, 90, 94).close_position == Decimal("0.2")
    assert c(0, 100, 110, 90, 94).close_third == "bottom"
    # close 16 above low -> 0.80 -> top
    assert c(0, 100, 110, 90, 106).close_third == "top"
    # exactly 0.66 is the boundary and counts as top (spec 02)
    assert c(0, 100, 200, 100, 166).close_position == Decimal("0.66")
    assert c(0, 100, 200, 100, 166).close_third == "top"


def test_zero_range_candle_does_not_divide_by_zero():
    flat = c(0, 100, 100, 100, 100)
    assert flat.range == 0 and flat.close_position == Decimal("0.5")


# ─────────────────────────────────────────────────────────────────────────────
# aggregator
# ─────────────────────────────────────────────────────────────────────────────
def test_bucket_boundaries():
    t = lambda hh, mm: datetime.combine(DAY, dtime(hh, mm), tzinfo=IST)  # noqa: E731
    assert bucket_start(t(9, 15), "5m") == t(9, 15)
    assert bucket_start(t(9, 19), "5m") == t(9, 15)
    assert bucket_start(t(9, 20), "5m") == t(9, 20)
    assert bucket_start(t(9, 29), "15m") == t(9, 15)
    assert bucket_start(t(9, 30), "15m") == t(9, 30)


def test_5m_emitted_on_the_candle_that_completes_it():
    """Spec 01 §4: the 5m stamped 09:15 closes at 09:20 and is emitted when the 1m
    stamped 09:19 closes — not when 09:20 opens."""
    ups = aggregate_all([c(i, 100 + i, 105 + i, 95 + i, 102 + i) for i in range(5)])
    assert [u.m5 for u in ups[:4]] == [None, None, None, None]
    assert ups[4].m5 is not None
    assert ups[4].m1.open_time.minute == 19


def test_5m_ohlc_is_exactly_the_fold_of_its_1m_candles():
    ones = [c(0, 100, 120, 90, 110), c(1, 110, 130, 105, 115),
            c(2, 115, 118, 80, 85), c(3, 85, 95, 84, 92), c(4, 92, 99, 91, 97)]
    m5 = aggregate_all(ones)[4].m5
    assert m5.o == ones[0].o == 100          # first open
    assert m5.h == 130                       # max high
    assert m5.l == 80                        # min low
    assert m5.c == ones[-1].c == 97          # last close
    assert m5.open_time == ones[0].open_time
    assert m5.close_time == ones[-1].close_time


def test_15m_is_three_5m_and_arrives_with_it():
    ups = aggregate_all([c(i, 100, 110, 90, 100) for i in range(15)])
    assert sum(u.m5 is not None for u in ups) == 3
    assert ups[14].m15 is not None and ups[14].m5 is not None
    assert sum(u.m15 is not None for u in ups) == 1


def test_partial_is_not_a_candle_and_lacks_detection_properties():
    """Spec 01 §4: 'Enforce with a type distinction, not discipline.' A detector that
    reaches for a partial must break loudly on the first line, not behave subtly."""
    up = aggregate_all([c(0, 100, 110, 90, 105), c(1, 105, 115, 100, 108)])[1]
    p = up.m5_partial
    assert isinstance(p, PartialCandle) and not isinstance(p, Candle)
    for forbidden in ("body", "upper_wick", "lower_wick", "close_third", "is_bull",
                      "body_top", "body_bottom", "range"):
        assert not hasattr(p, forbidden), f"PartialCandle must not expose {forbidden}"
    assert p.candles_so_far == 2
    assert p.progress == Decimal("0.4")           # 2 of 5
    assert p.minutes_remaining == 3


def test_partial_is_absent_on_the_closing_candle():
    ups = aggregate_all([c(i, 100, 110, 90, 100) for i in range(5)])
    assert ups[3].m5_partial is not None
    assert ups[4].m5_partial is None, "a closed candle has no partial"


def test_htf_candle_is_synthetic_if_any_minute_was_filled():
    """D-021 — detection excludes synthetic candles, and a 5m built partly from a
    price that never traded is not a candle the market made."""
    ones = [c(0, 100, 110, 90, 100), c(1, 100, 100, 100, 100, synthetic=True),
            c(2, 100, 110, 90, 100), c(3, 100, 110, 90, 100), c(4, 100, 110, 90, 100)]
    assert aggregate_all(ones)[4].m5.synthetic is True


def test_out_of_order_candles_are_rejected():
    agg = Aggregator()
    agg.on_candle(c(5, 100, 110, 90, 100))
    with pytest.raises(InvariantError, match="increasing order"):
        agg.on_candle(c(3, 100, 110, 90, 100))


def test_alignment_is_asserted_not_assumed():
    agg = Aggregator()
    agg.assert_alignment(datetime.combine(DAY, dtime(9, 15), tzinfo=IST))   # ok
    with pytest.raises(AlignmentError):
        agg.assert_alignment(datetime.combine(DAY, dtime(9, 7), tzinfo=IST))


# ─────────────────────────────────────────────────────────────────────────────
# session classification — D-018
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("day,first,last,expected", [
    (date(2026, 3, 4), dtime(9, 15), dtime(15, 29), "normal"),
    (date(2025, 10, 21), dtime(13, 45), dtime(14, 44), "abbreviated"),   # Muhurat
    (date(2024, 3, 2), dtime(9, 15), dtime(12, 29), "abbreviated"),      # NSE DR test
    (date(2023, 11, 12), dtime(18, 15), dtime(19, 14), "abbreviated"),   # Muhurat
    (date(2026, 2, 1), dtime(9, 15), dtime(15, 29), "weekend_full"),     # Budget Sunday
])
def test_session_classification(day, first, last, expected):
    assert classify_session(day, first, last)[0] == expected


def test_muhurat_window_would_fall_inside_a_trading_window():
    """The concrete hazard D-018 exists for: 2025-10-21's session is 13:45-14:44,
    entirely inside time.windows_normal [13:30, 14:45]."""
    assert dtime(13, 30) <= dtime(13, 45) and dtime(14, 44) <= dtime(14, 45)
    assert classify_session(date(2025, 10, 21), dtime(13, 45), dtime(14, 44))[0] == "abbreviated"


# ─────────────────────────────────────────────────────────────────────────────
# gap policy — spec 01 §3
# ─────────────────────────────────────────────────────────────────────────────
def test_one_missing_minute_is_forward_filled_as_synthetic(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    base = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    minutes = [0, 1, 3]                                   # 09:16 missing
    folder = tmp_path / "GAP_ONE"
    folder.mkdir()
    pq.write_table(pa.table({
        "ts": pa.array([base + timedelta(minutes=m) for m in minutes],
                       type=pa.timestamp("s", tz="Asia/Kolkata")),
        "open": [100.0] * 3, "high": [110.0] * 3, "low": [90.0] * 3,
        "close": [105.0] * 3, "volume": [0] * 3,
    }), folder / "2026-03.parquet")

    feed = ReplayFeed("GAP ONE", tmp_path, skip_abbreviated=False)
    candles, synth = feed._to_candles(DAY, feed._raw_by_day(None, None)[DAY])
    assert len(candles) == 4 and synth == 1
    filled = candles[2]
    assert filled.synthetic and filled.range == 0
    assert filled.o == filled.h == filled.l == filled.c == candles[1].c


def test_two_missing_minutes_raise_rather_than_guess(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    base = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)
    folder = tmp_path / "GAP_TWO"
    folder.mkdir()
    pq.write_table(pa.table({
        "ts": pa.array([base, base + timedelta(minutes=3)],
                       type=pa.timestamp("s", tz="Asia/Kolkata")),
        "open": [100.0] * 2, "high": [110.0] * 2, "low": [90.0] * 2,
        "close": [105.0] * 2, "volume": [0] * 2,
    }), folder / "2026-03.parquet")

    feed = ReplayFeed("GAP TWO", tmp_path, skip_abbreviated=False)
    with pytest.raises(FeedGapError, match="2 consecutive"):
        feed._to_candles(DAY, feed._raw_by_day(None, None)[DAY])


def test_session_day_whitelist_reaches_price_conversion(tmp_path, monkeypatch):
    folder = tmp_path / "TEST"
    folder.mkdir()
    source = folder / "source.csv"
    source.write_text("placeholder", encoding="utf-8")
    seen: list[frozenset[date] | None] = []
    at = datetime.combine(DAY, dtime(9, 15), tzinfo=IST)

    def fake_read(_path, _symbol, *, wanted_days=None):
        seen.append(wanted_days)
        return [(at, Decimal(100), Decimal(101), Decimal(99), Decimal(100), 0)]

    monkeypatch.setattr(replay_feed_mod, "_read_file", fake_read)
    feed = ReplayFeed(SYMBOL, tmp_path, skip_abbreviated=False, fill_gaps=False)

    sessions = list(feed.sessions(days=[DAY]))

    assert len(sessions) == 1
    assert seen == [frozenset({DAY})]


# ─────────────────────────────────────────────────────────────────────────────
# THE GATE — spec 09 §3.3
# ─────────────────────────────────────────────────────────────────────────────
def test_no_lookahead_by_truncation():
    """For every candle i, the aggregator's output at i must be identical whether the
    rest of the day exists or not.

    This is the single most common way a backtest lies. It is run on a real 375-candle
    session rather than a fixture, because the bug it catches is a slice or an index
    that reaches one element too far — which a short fixture will not exercise.
    """
    session = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4))
    candles = list(session.candles)
    assert len(candles) == 375

    full = aggregate_all(candles)

    def signature(u):
        return (u.m1.open_time,
                None if u.m5 is None else (u.m5.open_time, u.m5.o, u.m5.h, u.m5.l, u.m5.c),
                None if u.m15 is None else (u.m15.open_time, u.m15.o, u.m15.h, u.m15.l, u.m15.c),
                None if u.m5_partial is None else (u.m5_partial.candles_so_far, u.m5_partial.h),
                None if u.m15_partial is None else (u.m15_partial.candles_so_far, u.m15_partial.h))

    for i in range(0, len(candles), 7):          # every 7th, ~54 truncation points
        truncated = aggregate_all(candles[: i + 1])
        assert signature(truncated[i]) == signature(full[i]), (
            f"candle {i} ({candles[i].open_time:%H:%M}) differs when the future is absent")


def test_replay_is_deterministic_across_two_reads():
    a = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4)).candles
    b = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4)).candles
    assert a == b


def test_real_session_folds_to_75_and_25():
    session = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4))
    ups = aggregate_all(list(session.candles))
    m5 = [u.m5 for u in ups if u.m5]
    m15 = [u.m15 for u in ups if u.m15]
    assert (len(m5), len(m15)) == (75, 25)
    # every 5m is exactly the fold of its own five 1m candles
    for k, bar in enumerate(m5):
        window = session.candles[k * 5:(k + 1) * 5]
        assert bar.o == window[0].o
        assert bar.h == max(x.h for x in window)
        assert bar.l == min(x.l for x in window)
        assert bar.c == window[-1].c


def test_replay_skips_abbreviated_sessions():
    """D-018 on the real dataset — the five known days must not be yielded."""
    feed = ReplayFeed("NIFTY BANK")
    days = set(feed.available_days())
    for excluded in (date(2023, 11, 12), date(2024, 3, 2), date(2024, 5, 18),
                     date(2024, 11, 1), date(2025, 10, 21)):
        assert excluded not in days, f"{excluded} is abbreviated and must be skipped"


def test_replay_keeps_full_weekend_sessions():
    days = set(ReplayFeed("NIFTY BANK").available_days())
    for kept in (date(2024, 1, 20), date(2025, 2, 1), date(2026, 2, 1)):
        assert kept in days, f"{kept} is a full session and must be kept"


def test_prev_close_is_resolved_for_a_single_session():
    """Without this the gap_regime guard sees no gap on every day it is handed."""
    session = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4))
    assert session.prev_close is not None
    assert session.open_gap_pct is not None
