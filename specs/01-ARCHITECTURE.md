# 01 — ARCHITECTURE

## 1. Design goals, in priority order

1. **Truthfulness of the backtest.** The paper/replay result must be achievable live.
   Everything else is secondary. This drives the no-look-ahead rule and the
   single-engine rule.
2. **Auditability.** For any candle in history, we must be able to answer "what did
   the engine think, and why did it not trade?"
3. **Testability.** Every rule is a pure function with a fixture.
4. **Replaceability of the broker.** Kite is an adapter, not a dependency.

## 2. The one interface that matters

```python
class Engine:
    def on_candle(self, candle: Candle) -> Decision:
        """Pure. No I/O. No wall-clock reads. Mutates internal state only."""
```

`Feed` implementations differ; `Engine` does not.

```
ReplayFeed  (CSV, historical)  ─┐
KiteFeed    (websocket, live)  ─┼─→ Engine.on_candle() ─→ Decision ─→ Broker + Journal
                                │
(future) LiveFeed              ─┘
```

**Rule:** if you find yourself writing `if self.is_live:` inside the engine, the
design is wrong. Push the difference into the Feed or the Broker.

## 3. Time model

- Session: 09:15:00 → 15:30:00 IST.
- The 1m candle stamped `09:15` covers `[09:15:00, 09:16:00)` and becomes visible to
  the engine at `09:16:00`.
- `Engine.on_candle` receives **only closed candles**. It must assert
  `candle.close_time <= self.now`.
- The engine's `now` is supplied by the Feed. In replay it is the candle's close time.
  In live it is the tick clock. **The engine never calls `datetime.now()`.**

### v2 — the one deliberate exception: exits run on ticks

The closed-candles rule governs **detection and signal generation**. Nothing may see a
forming candle when deciding whether to *enter*. That is the no-look-ahead guarantee
and it is absolute.

**Exiting an open position is a different operation.** There is no future information
involved — only latency. v1 evaluated the index stop on 1m closes, which hands the
market up to 59 seconds of free adverse movement on a 25-point R, and does so worst
exactly when price is moving fastest against you.

```
ENTRY  path : closed candles only.  Engine.on_candle().  No exceptions, ever.
EXIT   path : tick stream.          exits/ engine.       Separate code path.
```

Keep them physically separate — the exit path must not be reachable from
`on_candle`, and `on_candle` must not read ticks. In replay, the exit path is driven by
intra-candle price reconstruction and must fill **worse** than `sl_index`, never at it
(spec 07 §2.2).

The no-look-ahead truncation test (spec 09 §3.3) applies to the entry path. Write a
separate test asserting that the exit path never influences a signal.

### Candle gaps
Bank Nifty 1m data can have missing minutes (no trades, feed hiccup). Policy:
- 1 missing minute → forward-fill a zero-range candle, flag `synthetic=True`,
  and **exclude synthetic candles from all pattern detection** (a synthetic candle can
  never be a sweep, a launch base, or a swing pivot).
- ≥2 consecutive missing minutes → raise `FeedGapError`. In live, this sets
  `BLOCKED` for 15 minutes. Never guess through a gap.

## 4. Aggregation (1m → 5m → 15m)

Built by the `Aggregator`, not fetched separately. Two sources of truth for the same
price is a bug factory.

- 5m candles close at `:00 :05 :10 …` — i.e. the 5m candle stamped `09:15` closes at
  `09:20` and is emitted when the 1m candle stamped `09:19` closes.
- 15m candles close at `:00 :15 :30 :45`.
- Bank Nifty's session start (09:15) aligns cleanly with both. No offset handling
  needed, but assert alignment at startup.

The Aggregator emits:
```python
@dataclass(frozen=True)
class BarUpdate:
    m1: Candle                    # always
    m5: Candle | None             # only on 5m close
    m15: Candle | None            # only on 15m close
    m5_partial: PartialCandle     # forming 5m, for HTF-close-proximity logic only
    m15_partial: PartialCandle
```

**Partials may be used for exactly one purpose:** knowing how far into an HTF candle
we are (the "last third" alert). They must never be used for pattern detection,
level creation, or signals. Enforce with a type distinction, not discipline.

## 5. Module boundaries

| Module | Reads | Writes | Never does |
|---|---|---|---|
| `feed/` | broker / CSV | `Candle` | interpret price |
| `levels/` | candles, ATR | `LevelBook` | look at positions |
| `structure/` | candles | `StructureState` | look at levels |
| `state/` | levels, structure, candles | `StateBoard` | make decisions |
| `guards/` | clock, ATR, session stats | `GuardResult` | look at setups |
| `modes/` | board, guards, position | `Mode` | emit signals |
| `setups/` | board, levels, structure | `SetupCandidate` | compute size |
| `risk/` | candidate, ATR, levels | `SizedSignal` \| `Rejection` | place orders |
| `options/` | signal, chain | `OptionOrder` | change SL logic |
| `broker/` | orders | `Fill` | make decisions |
| `exits/` | position, candles, levels | `ExitOrder` | open positions |
| `journal/` | everything | disk | affect behaviour |

**`structure/` deliberately does not see levels, and `levels/` does not see structure.**
They are combined only in `state/`. This keeps both independently testable and stops
circular reasoning ("this is a level because the structure says so, and the structure
says so because of this level").

## 6. Decision flow — the only three outcomes

```python
Decision = Signal | Rejection | NoOp
```

- `NoOp` — mode is WATCH and nothing is near. Logged compactly (one line).
- `Rejection` — we were in ALERT and evaluated a real candidate, but a gate failed.
  **Logged in full**, with the gate name and every computed value. This is the
  valuable data.
- `Signal` — all gates passed.

There is no "weak signal", "half size", or "watchlist" outcome. Adding one will
quietly destroy the discipline the system exists to enforce.

## 7. Position lifecycle

```
FLAT ──Signal──→ PENDING_ENTRY ──fill──→ IN_POSITION ──┬── invalidation → EXITING
                      │                                 ├── T1 hit → PARTIAL (50%)
                      └── not filled in 2 candles       ├── SL hit → EXITING
                          → CANCELLED (log it)          ├── T2/trail → EXITING
                                                        └── time stop → EXITING
EXITING ──fill──→ FLAT (journal the round trip)
```

Notes:
- **Unfilled entries must be logged.** In paper this is rare, but modelling it keeps
  the paper result honest — a signal you could not get filled on is not a trade.
- After `PARTIAL`, the hard SL for the remainder moves to breakeven. This is
  unconditional and happens in the same tick as the T1 fill, not on the next candle.
- Only one position at a time. No pyramiding, no hedges, no simultaneous CE and PE.

## 8. Configuration

`config/params.yaml` — every threshold. Structure:

```yaml
levels:
  swing_lookback_bars: 3          # HYPOTHESIS — untested
  launch_impulse_atr_mult: 2.0    # HYPOTHESIS
  ...
```

Rules:
- Any numeric literal in a logic file is a bug. Reviewer should reject it.
- Every param carries a `# HYPOTHESIS` comment until validated by a P9 run.
- `config/costs.yaml` carries brokerage, STT, exchange charges, GST, stamp duty and
  the slippage model. **These rates change — they must be confirmed against the
  broker's current published charges before any result is trusted.** Put the date of
  last verification in the file.

## 9. Failure policy

| Failure | Response |
|---|---|
| Feed gap ≥2 min | `BLOCKED` 15 min, alert |
| Websocket disconnect | reconnect w/ backoff; if position open, alert loudly; `BLOCKED` for new entries until 2 clean candles |
| ATR unavailable (< 14 candles) | `BLOCKED` — no trading in the first 14 minutes regardless |
| Option chain fetch fails | reject the signal; do not guess a strike |
| Any unhandled exception in `on_candle` | log full state snapshot, set `BLOCKED`, do not silently continue |
| Clock skew > 2s vs exchange | alert; in live this would be fatal |

**There is no "try to keep going" mode.** A trading system that limps is more
dangerous than one that stops.

## 10. What we are explicitly NOT building

- No ML / model fitting. The rules are the hypothesis; fitting them to the data is how
  you get a beautiful backtest and a losing live account.
- No multi-instrument scanning. One instrument, done properly.
- No news/sentiment input.
- No portfolio or hedging layer.
- No UI beyond a daily HTML/markdown report. Live monitoring is log tailing.
