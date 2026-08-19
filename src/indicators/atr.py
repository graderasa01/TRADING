"""
ATR — the number every threshold in v2 is expressed against.

`REVIEW-v2.md` §12 made every gate `max(floor_points, atr_mult × ATR)`, so ATR stopped
being one input among many and became the unit the whole system is denominated in. That
makes its definition worth stating precisely rather than leaving to whichever formula a
module happened to reach for.

## The convention, and why (D-012)

**Simple mean of `high - low` over N candles, within a session, no carry across days.**

Not Wilder's true range, not Wilder's smoothing. Three reasons:

  1. It is what `prototype/engine_fixed.py:78` computes, and therefore what every
     threshold in `params.yaml` was reasoned against. Changing the convention silently
     re-scales every gate in the system.
  2. `data/DATA-REPORT.md` §3 measured the difference on three years of real candles:
     the true-range median is **+0.6%** above the plain-range median on Bank Nifty. On a
     1m index series consecutive candles overlap almost always, so the gap term in TR
     contributes nearly nothing.
  3. Session-scoped, because the alternative carries yesterday's 15:29 close into
     today's 09:15 candle. On a gap day that single TR value can be 40× a normal one and
     it would poison ATR for the first 14 minutes — exactly the window spec 05 §1c is
     already treating as untrustworthy.

## Two periods, deliberately

`ATR14` gates volatility and sets alert distance (spec 05). `ATR20` scales the level
engine — launch impulse, base width, departure speed, dormancy (spec 03). The specs use
both and never say they are the same thing, so they are kept separate rather than
quietly unified.

## Warmup returns None, never a default

Spec 01 §9: ATR unavailable → `BLOCKED`. A module that receives `None` must decide what
to do; one that receives a plausible-looking default cannot tell that it is guessing.
`Config.effective()` falls back to the floor, which is the only place a default belongs.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from src.domain.models import Candle

ATR_FAST = 14      # volatility gates, alert distance      — spec 05
ATR_SLOW = 20      # level engine geometry                 — spec 03


class AtrTracker:
    """Rolling mean of candle range over one period, scoped to a session.

    Feed it every closed candle of one timeframe. `value` is `None` until `period`
    candles have arrived, and the tracker must be reset between sessions.
    """

    __slots__ = ("period", "_ranges", "_sum")

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"ATR period must be >= 1, got {period}")
        self.period = period
        self._ranges: deque[Decimal] = deque(maxlen=period)
        self._sum = Decimal(0)

    def update(self, candle: Candle) -> Decimal | None:
        """Synthetic candles are included deliberately.

        A forward-filled minute has zero range, so it pulls ATR down — and that is the
        honest reading: nothing traded, the market really was quiet. Excluding it would
        report the volatility of a market that was not there. D-009 excludes synthetic
        candles from *pattern detection*, which is a different question.
        """
        if len(self._ranges) == self.period:
            self._sum -= self._ranges[0]
        self._ranges.append(candle.range)
        self._sum += candle.range
        return self.value

    @property
    def value(self) -> Decimal | None:
        if len(self._ranges) < self.period:
            return None
        return self._sum / self.period

    @property
    def ready(self) -> bool:
        return len(self._ranges) == self.period

    @property
    def warmup_remaining(self) -> int:
        return max(0, self.period - len(self._ranges))

    def reset(self) -> None:
        self._ranges.clear()
        self._sum = Decimal(0)


class AtrBook:
    """Every ATR the engine needs, updated from one call per closed 1m candle.

    Held together in one object so that no module invents its own period and no two
    modules disagree about what ATR meant on a given candle — which is the kind of
    divergence that never appears in a test and always appears in a report.
    """

    __slots__ = ("fast_1m", "slow_1m", "fast_5m", "_history")

    def __init__(self) -> None:
        self.fast_1m = AtrTracker(ATR_FAST)
        self.slow_1m = AtrTracker(ATR_SLOW)
        self.fast_5m = AtrTracker(ATR_FAST)
        self._history: list[Decimal | None] = []

    def on_1m(self, candle: Candle) -> None:
        self.fast_1m.update(candle)
        self.slow_1m.update(candle)
        # ATR20 at an arbitrary past candle is needed by departure_speed, which is only
        # resolvable `departure_lookahead_candles` after a level is born (spec 03 §3).
        self._history.append(self.slow_1m.value)

    def on_5m(self, candle: Candle) -> None:
        self.fast_5m.update(candle)

    def slow_at(self, index: int) -> Decimal | None:
        """ATR20 as it stood at 1m candle `index`.

        Used for `departure_speed`, which divides by the ATR *at birth* — not by the ATR
        now. Using the current value would make a level's grade drift with volatility
        long after it formed, so a quiet-market level would silently re-grade itself
        during an afternoon expansion.
        """
        if not 0 <= index < len(self._history):
            return None
        return self._history[index]

    @property
    def atr_1m(self) -> Decimal | None:
        return self.fast_1m.value

    @property
    def atr20_1m(self) -> Decimal | None:
        return self.slow_1m.value

    @property
    def atr_5m(self) -> Decimal | None:
        return self.fast_5m.value

    def reset(self) -> None:
        self.fast_1m.reset()
        self.slow_1m.reset()
        self.fast_5m.reset()
        self._history.clear()
