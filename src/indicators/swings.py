"""
Swing pivots — the one primitive both `levels/` and `structure/` need.

It lives here, in a neutral package, because spec 01 §5 forbids `structure/` from
importing `levels/` and spec 04 repeats the reason: *"it prevents circular reasoning
where a level justifies a structure that justifies the level."* Duplicating the pivot
rule in both would be the same bug wearing a different shape — two copies that drift
apart, and a level book that disagrees with the structure board about where the swing
was.

## The rule (spec 03 §2a)

Candle `i` is a swing high when

    h[i] > h[i-k] … h[i-1]   AND   h[i] > h[i+1] … h[i+k]

with `k` per timeframe: 3 on 1m, 2 on 5m, 2 on 15m.

## Confirmation is the whole no-look-ahead question

*"A swing is not confirmed until `k` candles have closed to its right. Emitting an
unconfirmed swing is a look-ahead bug. Confirmed-only, always."*

So a pivot at index `i` becomes visible at index `i + k`, and the emitting call is the
one that processes candle `i + k` — never earlier. `test_no_lookahead_by_truncation`
(spec 09 §3.3) exists to catch exactly the off-by-one that would leak here.

Strict inequality on both sides is deliberate: a flat double-top produces no pivot. That
is the correct outcome — a level needs a point where price turned, and two equal highs
say the turn has not happened yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models import Candle, Swing, Timeframe

# spec 03 §2a — levels.swing_lookback_bars_{1m,5m,15m}
DEFAULT_K: dict[str, int] = {"1m": 3, "5m": 2, "15m": 2}


@dataclass(frozen=True, slots=True)
class Pivot:
    """A confirmed swing, with the index it sits at — the index matters because
    `departure_speed` and the ladder both count candles from it."""
    index: int
    swing: Swing
    candle: Candle

    @property
    def price(self) -> Decimal:
        return self.swing.price

    @property
    def is_high(self) -> bool:
        return self.swing.kind == "high"


class SwingDetector:
    """Feed closed candles of one timeframe in order; receive confirmed pivots.

        det = SwingDetector("1m", k=3)
        for candle in candles:
            for pivot in det.on_candle(candle):
                ...

    Returns a list because a single candle can confirm at most one pivot per side, and
    a bar that is both a swing high and a swing low (an inside-bar sequence around it)
    is possible, if rare.
    """

    __slots__ = ("tf", "k", "_candles", "_emitted")

    def __init__(self, tf: Timeframe, k: int | None = None) -> None:
        self.tf = tf
        self.k = DEFAULT_K[tf] if k is None else k
        self._candles: list[Candle] = []
        self._emitted: set[tuple[int, str]] = set()

    def on_candle(self, candle: Candle) -> list[Pivot]:
        self._candles.append(candle)
        i = len(self._candles) - 1 - self.k      # the candle now fully confirmed
        if i < self.k:
            return []

        out: list[Pivot] = []
        pivot_candle = self._candles[i]
        left = self._candles[i - self.k:i]
        right = self._candles[i + 1:i + 1 + self.k]

        # Synthetic candles can never be a swing pivot (D-009). A forward-filled
        # zero-range candle is not a place price turned; it is a place price was absent.
        if not pivot_candle.synthetic:
            if (all(pivot_candle.h > c.h for c in left)
                    and all(pivot_candle.h > c.h for c in right)
                    and (i, "high") not in self._emitted):
                self._emitted.add((i, "high"))
                out.append(Pivot(i, Swing(pivot_candle.open_time, pivot_candle.h,
                                          "high", self.tf, confirmed=True), pivot_candle))
            if (all(pivot_candle.l < c.l for c in left)
                    and all(pivot_candle.l < c.l for c in right)
                    and (i, "low") not in self._emitted):
                self._emitted.add((i, "low"))
                out.append(Pivot(i, Swing(pivot_candle.open_time, pivot_candle.l,
                                          "low", self.tf, confirmed=True), pivot_candle))
        return out

    @property
    def confirmation_lag(self) -> int:
        """How many candles behind live a confirmed pivot always is. Worth naming: it
        is why a 15m swing is 30 minutes old the moment it exists, and therefore why
        spec 03 §2a runs detection 15m → 5m → 1m rather than the other way round."""
        return self.k

    def reset(self) -> None:
        self._candles.clear()
        self._emitted.clear()


def find_pivots(candles: list[Candle], tf: Timeframe, k: int | None = None) -> list[Pivot]:
    """Batch form, for tests and tools. Identical results to the streaming detector —
    `test_streaming_matches_batch` pins that, because a batch/stream divergence is how
    a backtest and a live run end up disagreeing about the same day."""
    det = SwingDetector(tf, k)
    out: list[Pivot] = []
    for candle in candles:
        out.extend(det.on_candle(candle))
    return out
