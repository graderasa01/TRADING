"""
Aggregator — 1m → 5m → 15m. Spec 01 §4.

HTF candles are **built**, never fetched. Two sources of truth for the same price is a
bug factory, and the one that bites is subtle: the engine draws a level from a fetched
5m candle whose high differs by a point from the 5m the 1m stream implies, and no test
ever compares them.

## The partial/closed type distinction

Spec 01 §4: *"Partials may be used for exactly one purpose: knowing how far into an HTF
candle we are. They must never be used for pattern detection, level creation, or
signals. Enforce with a type distinction, not discipline."*

So `PartialCandle` is **not** a `Candle` and is not a subclass of one. It deliberately
lacks `body`, `upper_wick`, `lower_wick`, `close_third` and `is_bull` — every property a
detector reaches for. A detector that tries to use a partial does not misbehave subtly;
it raises `AttributeError` on the first line. `close_position` is present because spec 04
§4 Law A needs it for the journalled HTF forecast, which gates nothing.

## Alignment

The session opens at 09:15, which is a multiple of both 5 and 15 minutes past the hour,
so 5m and 15m buckets fall out of plain wall-clock arithmetic with no session-relative
offset. Spec 01 §4 says to assert this rather than assume it, so `Aggregator` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

from src.domain.models import (
    HALF, TF_MINUTES, ZERO, Candle, InvariantError, Timeframe,
)


class AlignmentError(InvariantError):
    """The 1m stream does not align with the HTF grid it is being folded into."""


@dataclass(frozen=True, slots=True)
class PartialCandle:
    """A forming HTF candle. Informational only — see the module docstring.

    Note what is absent: no `body`, no wicks, no `close_third`, no `is_bull`. That
    absence is the enforcement.
    """
    symbol: str
    tf: Timeframe
    open_time: datetime
    close_time: datetime          # when it WILL close
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    candles_so_far: int

    @property
    def progress(self) -> Decimal:
        """0.0 → 1.0 through the HTF candle. Spec 04 §4 Law B."""
        return Decimal(self.candles_so_far) / Decimal(TF_MINUTES[self.tf])

    @property
    def minutes_remaining(self) -> int:
        return TF_MINUTES[self.tf] - self.candles_so_far

    @property
    def close_position(self) -> Decimal:
        """Journalled forecast only (spec 04 §4 Law A). Never gates a trade."""
        rng = self.h - self.l
        if rng == ZERO:
            return HALF
        return (self.c - self.l) / rng


@dataclass(frozen=True, slots=True)
class BarUpdate:
    """What the aggregator emits for every closed 1m candle."""
    m1: Candle                      # always
    m5: Candle | None = None        # only on a 5m close
    m15: Candle | None = None       # only on a 15m close
    m5_partial: PartialCandle | None = None
    m15_partial: PartialCandle | None = None


def bucket_start(ts: datetime, tf: Timeframe) -> datetime:
    minutes = TF_MINUTES[tf]
    return ts.replace(minute=(ts.minute // minutes) * minutes, second=0, microsecond=0)


class _Bucket:
    __slots__ = ("symbol", "tf", "open_time", "o", "h", "l", "c", "volume", "n", "synthetic")

    def __init__(self, candle: Candle, tf: Timeframe) -> None:
        self.symbol = candle.symbol
        self.tf = tf
        self.open_time = bucket_start(candle.open_time, tf)
        self.o = candle.o
        self.h = candle.h
        self.l = candle.l
        self.c = candle.c
        self.volume = candle.volume or 0
        self.n = 1
        self.synthetic = candle.synthetic

    def add(self, candle: Candle) -> None:
        self.h = max(self.h, candle.h)
        self.l = min(self.l, candle.l)
        self.c = candle.c
        self.volume += candle.volume or 0
        self.n += 1
        # D-021: an HTF candle containing any forward-filled minute is itself synthetic.
        # Detection excludes synthetic candles, and a 5m built partly from a price that
        # never traded is not a candle the market made.
        self.synthetic = self.synthetic or candle.synthetic

    @property
    def close_time(self) -> datetime:
        return self.open_time + timedelta(minutes=TF_MINUTES[self.tf])

    def to_partial(self) -> PartialCandle:
        return PartialCandle(self.symbol, self.tf, self.open_time, self.close_time,
                             self.o, self.h, self.l, self.c, self.n)

    def to_candle(self) -> Candle:
        return Candle(self.symbol, self.tf, self.open_time, self.close_time,
                      self.o, self.h, self.l, self.c,
                      None if self.volume == 0 else self.volume, self.synthetic)


class Aggregator:
    """Feed it closed 1m candles in order; it yields a `BarUpdate` for each.

    An HTF candle is emitted on the 1m candle that COMPLETES it — the 5m stamped 09:15
    is emitted when the 1m stamped 09:19 closes, not when 09:20 opens. Waiting for the
    next bucket to open would delay every HTF signal by a minute and, worse, would make
    the last HTF candle of the day never arrive.
    """

    def __init__(self, htf: tuple[Timeframe, ...] = ("5m", "15m")) -> None:
        self.htf = htf
        self._buckets: dict[Timeframe, _Bucket | None] = {tf: None for tf in htf}
        self._last_1m: datetime | None = None
        self.closed: dict[Timeframe, list[Candle]] = {tf: [] for tf in htf}

    def on_candle(self, candle: Candle) -> BarUpdate:
        if candle.tf != "1m":
            raise InvariantError(f"Aggregator consumes 1m candles, got {candle.tf}")
        if self._last_1m is not None and candle.open_time <= self._last_1m:
            raise InvariantError(
                f"1m candles must arrive in strictly increasing order: "
                f"{candle.open_time} after {self._last_1m}")

        emitted: dict[Timeframe, Candle | None] = {tf: None for tf in self.htf}
        partials: dict[Timeframe, PartialCandle | None] = {tf: None for tf in self.htf}

        for tf in self.htf:
            start = bucket_start(candle.open_time, tf)
            bucket = self._buckets[tf]

            if bucket is not None and bucket.open_time != start:
                # A bucket was still open when a candle from a later bucket arrived.
                # That means minutes are missing; the ReplayFeed is responsible for
                # synthetic fill and FeedGapError, so by here it is a bug, not a market
                # event. Emit what we have rather than silently dropping it.
                emitted[tf] = bucket.to_candle()
                self.closed[tf].append(emitted[tf])
                bucket = None

            if bucket is None:
                bucket = _Bucket(candle, tf)
                self._buckets[tf] = bucket
            else:
                bucket.add(candle)

            if bucket.n == TF_MINUTES[tf]:
                closed = bucket.to_candle()
                if emitted[tf] is None:
                    emitted[tf] = closed
                    self.closed[tf].append(closed)
                self._buckets[tf] = None
            else:
                partials[tf] = bucket.to_partial()

        self._last_1m = candle.open_time
        return BarUpdate(
            m1=candle,
            m5=emitted.get("5m"),
            m15=emitted.get("15m"),
            m5_partial=partials.get("5m"),
            m15_partial=partials.get("15m"),
        )

    def assert_alignment(self, first_candle_time: datetime) -> None:
        """Spec 01 §4 — assert, do not assume. If the exchange ever moves the open to
        09:07, every HTF candle silently becomes a different candle."""
        for tf in self.htf:
            if first_candle_time.minute % TF_MINUTES[tf] != 0:
                raise AlignmentError(
                    f"session opens at {first_candle_time:%H:%M}, which is not on the "
                    f"{tf} grid. HTF aggregation would be offset for the whole session.")

    def flush(self) -> dict[Timeframe, Candle | None]:
        """End of session. Returns any incomplete HTF candle without emitting it as
        closed — the 15:15–15:30 15m candle is complete, but a partial one at a
        truncated session is not, and must not be treated as a real candle."""
        out: dict[Timeframe, Candle | None] = {}
        for tf, bucket in self._buckets.items():
            out[tf] = bucket.to_candle() if bucket is not None else None
            self._buckets[tf] = None
        return out


def aggregate_all(candles: Iterator[Candle] | list[Candle],
                  htf: tuple[Timeframe, ...] = ("5m", "15m")) -> list[BarUpdate]:
    agg = Aggregator(htf)
    return [agg.on_candle(c) for c in candles]
