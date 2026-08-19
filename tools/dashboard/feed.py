"""Where candles come from. **Market data only — never an order path.**

```
FeedSource                     abstract: "give me the next closed candle"
  ReplaySource                 candles already on disk, delivered as fast as asked
  PacedSource                  the same candles, delivered on a wall clock (simulated live)
  KiteSource                   NOT BUILT — the seam a broker websocket plugs into
```

The point of this file is that the dashboard's live mode and its historical mode differ
**only in which of these is attached**. Everything downstream — `LiveSession`, the frame,
the panel — is the same object either way, which is the rule the previous stage locked:
one production pipeline, two feeds.

`KiteSource` is deliberately a stub that raises. A broker adapter needs credentials, a
websocket, a tick→candle builder and a session/holiday calendar; writing an untested one
here and calling the live mode "done" would be the exact dishonesty this project keeps
refusing. It is `NotImplementedError` with the reason, not a silent fallback to replay.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Iterator, Sequence

from src.feed.aggregator import Aggregator
from src.feed.replay_feed import ReplayFeed

SYMBOL = "NIFTY BANK"


def m5_of(days: Sequence[date], symbol: str = SYMBOL) -> list:
    """Closed 5m candles for these sessions, from the aggregator's own output."""
    out = []
    for session in ReplayFeed(symbol, on_gap="skip").sessions(days=days):
        agg = Aggregator(htf=("5m",))
        for candle in session.candles:
            update = agg.on_candle(candle)
            if update.m5 is not None:
                out.append(update.m5)
    return out


class FeedSource:
    """One closed candle at a time, in order. Nothing else."""

    name = "abstract"
    live = False

    def candles(self) -> Iterator:
        raise NotImplementedError


class ReplaySource(FeedSource):
    """Candles from disk, as fast as the consumer asks for them."""

    name = "replay"
    live = False

    def __init__(self, candles: Sequence) -> None:
        self._candles = list(candles)

    def candles(self) -> Iterator:
        yield from self._candles


class PacedSource(FeedSource):
    """The same candles on a wall clock — a simulated live feed.

    It exists so the live code path can be exercised end to end without a broker: the
    dashboard's live mode drives `LiveSession` from this exactly as it would from a
    websocket. It is **not** a market simulator and it invents no price.
    """

    name = "paced(simulated-live)"
    live = True

    def __init__(self, candles: Sequence, *, seconds: float = 1.0) -> None:
        self._candles = list(candles)
        self.seconds = seconds

    def candles(self) -> Iterator:
        for candle in self._candles:
            time.sleep(self.seconds)
            yield candle


class KiteSource(FeedSource):
    """The broker seam. **Not built.**

    Live market data needs a Kite websocket, a tick→1m→5m builder, a session calendar and
    credentials, none of which exist in this repository (`tools/fetch_kite.py` is
    historical `historical_data` only, and `src/feed/` has no websocket). This raises
    rather than quietly falling back to replay, because a live mode that is secretly a
    replay is worse than no live mode.

    When it is built, it changes nothing downstream: it yields closed 5m candles and
    `LiveSession` consumes them exactly as `PacedSource`'s are consumed today.

    **Market data only.** Even when built, this class must never place, modify or cancel
    an order — `tests/test_dashboard.py` asserts that no order vocabulary appears here.
    """

    name = "kite(not built)"
    live = True

    def candles(self) -> Iterator:
        raise NotImplementedError(
            "A live Kite market-data feed is not built. It needs a websocket, a "
            "tick-to-candle builder, a session calendar and credentials — none of which "
            "exist in this repo yet (fetch_kite.py is historical-only).\n"
            "Use --live to drive the identical code path from a PacedSource instead; the "
            "dashboard cannot tell the difference, which is the point.\n"
            "This is market data only. No order path exists at either end.")


__all__ = ["SYMBOL", "m5_of", "FeedSource", "ReplaySource", "PacedSource", "KiteSource"]
