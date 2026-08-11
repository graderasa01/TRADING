# BANK NIFTY PRICE ACTION CO-PILOT — CONSTITUTION

> This file is loaded on every session. Read it fully before writing any code.
> Detailed specs live in `specs/`. Build order is at the bottom of this file.

---

## 0. WHAT THIS IS

A rules-based, indicator-free price action engine for Bank Nifty. It reads **1-minute
index candles**, maintains a level book and a structure board, and emits **at most 3
trade signals per day** — or, far more often, `NO_TRADE` with the exact reason.

**Current build stage: PAPER TRADING.**
Live Kite websocket data in, simulated fills out. **No real orders are placed. Do not
write any code path that can place a live order.** The `LiveBroker` class must not
exist yet.

---

## 1. THE TEN NON-NEGOTIABLES

These are architectural laws. Never override them for convenience.

### 1. Default output is `NO_TRADE`
Every candle produces a `Decision`. A `Decision` is either a `Signal` or a
`Rejection` carrying the **exact gate that failed**. There is no third option, and
there is no "maybe." A rejection is a successful, correct output — log it, never
suppress it.

### 2. Signal on the INDEX, execute on the OPTION
All price action — levels, structure, sweeps, stops, targets — is computed on the
**Bank Nifty index (or futures) 1m candles**. Never on option premium.
Option premium is distorted by IV, theta and thin books; price action read on a
premium chart is noise. The option is only the **vehicle**.
Stop-loss and targets are monitored in **index points** and translated to premium
only at order time.

### 3. Closed candles only — zero look-ahead
A candle is visible to the engine only after its close timestamp has passed. The
engine must never read `high`/`low`/`close` of the candle currently forming.
Any function that receives future data must fail an assertion.
**This is the single most common way a backtest lies.** Guard it in code, not in
comments.

### 4. One engine, many feeds
`Engine.on_candle(candle) -> Decision` is a **pure function of (state, candle)**.
The only difference between replay, paper and live is which `Feed` calls it.
If paper trading and backtesting ever run different logic, the system is worthless.

### 5. Size comes from the stop, never the reverse
```
lots = floor(risk_budget_rupees / (R_points × delta × lot_size))
```
Never widen a stop to fit a desired size. If the computed size is 0 lots, the answer
is **no trade**, not a wider stop.

### 6. Two exits, and the second one matters more
- **Hard SL** — always resting in the system. Never mental.
- **Thesis invalidation** — a body close back on the wrong side of the trigger level
  exits at market **immediately**, without waiting for the hard SL.

### 7. Hard session limits, enforced by the engine
Max 3 trades/day. Stop after 2 consecutive losses. Stop at −2R cumulative.
These are engine-level kill switches, not suggestions. Once tripped, the engine
returns `BLOCKED` for the rest of the session.

### 8. Costs are modelled from day one
Every paper trade is recorded **net of** slippage, brokerage, STT, exchange charges
and GST. A gross-profit number is never displayed anywhere. If the edge only exists
before costs, it does not exist.

### 9. Every threshold is a named, tunable config value
No magic numbers in logic files. All thresholds live in `config/params.yaml` with a
comment stating it is an **unvalidated hypothesis**. Tuning happens on data, not
on vibes — and every tuning run must be recorded.

### 10. The journal logs rejections too
The most valuable dataset this system produces is **why it did not trade**. Log every
rejection with its gate. After a month this tells you which gate is doing real work
and which is just noise.

---

## 2. THE MENTAL MODEL THE CODE IMPLEMENTS

The engine is a human trader's routine, mechanised. Keep this mapping in your head
while writing every module:

| Human behaviour | Module |
|---|---|
| Remembers 8 things about the day | `state/board.py` |
| Draws ~7 lines on the chart, erases dead ones | `levels/engine.py` |
| Knows if control is with buyers or sellers | `structure/engine.py` |
| Refuses to trade at lunch / in dead volatility | `guards/` |
| Sits in WATCH mode 70% of the day | `modes/machine.py` |
| Wakes up when price nears a level | `modes/machine.py` (ALERT) |
| Writes IF-THEN before the candle forms | `planner/anticipation.py` |
| Takes only 3 setups, always on retest | `setups/` |
| Puts the stop beyond the wick, not on the line | `risk/engine.py` |
| Exits the moment the thesis breaks | `exits/engine.py` |
| Logs whether rules were followed | `journal/` |

**Cardinal rule of the timeframes:**
> 15m says **WHERE**. 5m says **WHAT**. 1m says **WHEN** and **WHERE THE STOP GOES**.
> 1m is never allowed to set direction. If 1m could flip bias, the system would flip
> twenty times a day.

---

## 3. PIPELINE — the order of operations on every closed 1m candle

```
1m candle closes
  │
  ├─ 1  Aggregator      → update 5m / 15m partials; emit closed HTF candles
  ├─ 2  LevelEngine     → birth / test / grade / kill levels
  ├─ 3  StructureEngine → swings, BOS, trend, regime
  ├─ 4  StateBoard      → update the 8 variables
  ├─ 5  Guards          → time, volatility, session limits   ── fail ⇒ BLOCKED
  ├─ 6  ModeMachine     → WATCH | ALERT | IN | BLOCKED
  │
  ├─ 7  if ALERT:  SetupDetector (A / B / C)   ── none ⇒ Rejection
  ├─ 8            RiskEngine (SL, R bounds)    ── fail ⇒ Rejection
  ├─ 9            SpaceCheck (obstacle / R)    ── fail ⇒ Rejection
  ├─ 10           OptionsLayer → strike, size  ── size 0 ⇒ Rejection
  │                                            └─ pass ⇒ Signal ⇒ PaperBroker
  ├─ 11 if IN:    ExitEngine (invalidation → T1 → trail → time stop)
  └─ 12 Journal   → write Decision + full state snapshot, always
```

Modules must be composable and independently testable. No module reaches into
another's internals. Data flows one way, down the list.

---

## 4. REPO LAYOUT

```
banknifty-copilot/
├── CLAUDE.md                  ← this file
├── config/
│   ├── params.yaml            ← every threshold, all marked HYPOTHESIS
│   └── costs.yaml             ← brokerage/STT/slippage — VERIFY BEFORE USE
├── specs/                     ← read the relevant spec before writing a module
│   ├── 01-ARCHITECTURE.md
│   ├── 02-DATA-CONTRACT.md
│   ├── 03-LEVEL-ENGINE.md
│   ├── 04-STRUCTURE-AND-STATE.md
│   ├── 05-GUARDS-AND-MODES.md
│   ├── 06-SETUPS.md
│   ├── 07-RISK-AND-EXITS.md
│   ├── 08-OPTIONS-AND-KITE.md
│   └── 09-JOURNAL-AND-TESTS.md
├── src/
│   ├── feed/          aggregator.py  kite_feed.py  replay_feed.py
│   ├── levels/        engine.py  models.py
│   ├── structure/     engine.py  swings.py
│   ├── state/         board.py
│   ├── guards/        time_guard.py  vol_guard.py  session_guard.py
│   ├── modes/         machine.py
│   ├── setups/        base.py  flip_retest.py  sweep_reclaim.py  range_break.py
│   ├── risk/          engine.py  space.py  sizing.py
│   ├── exits/         engine.py
│   ├── options/       chain.py  strike_select.py
│   ├── broker/        paper.py  base.py          ← NO live.py at this stage
│   ├── journal/       writer.py  schema.py
│   └── engine.py      ← the orchestrator implementing §3
├── tests/
│   ├── fixtures/      hand-built candle sequences with expected outcomes
│   └── test_*.py
└── run_paper.py       ← entry point
```

---

## 5. CODING RULES

- **Python 3.11+.** `dataclass(frozen=True)` for all domain models. Type hints everywhere.
- **Pure functions in the hot path.** `on_candle` must not perform I/O. Journal writes
  are queued and flushed by the caller.
- **All money and price as `Decimal` or int-paise.** Never float for money.
- **All timestamps timezone-aware, `Asia/Kolkata`.** No naive datetimes anywhere.
- **No `print`.** Structured logging only, JSON lines.
- **Fail loudly.** A missing level, a gap in candles, a stale tick → raise. Silent
  degradation in a trading system is how accounts die.
- Every module gets unit tests **before** it is wired into the pipeline.

---

## 6. HARD PROHIBITIONS

Do not write, and refuse if asked mid-build:

- ❌ Any live order placement path (this stage is paper only)
- ❌ Averaging down, martingale, or size-up-after-loss logic
- ❌ Stop-loss widening, or a "temporarily disable SL" flag
- ❌ Re-entry into the same failed setup more than once per level per session
- ❌ Naked option selling
- ❌ Any signal computed from option premium price action
- ❌ Any backtest/paper metric reported gross of costs
- ❌ Optimisation loops that tune more than 2 parameters at once (overfitting)

---

## 7. BUILD ORDER — do not skip ahead

Each phase must have passing tests before the next begins.

| Phase | Build | Done when |
|---|---|---|
| **P0** | Config loader, domain models, `ReplayFeed` from CSV, aggregator | 1m CSV → correct 5m/15m candles, no look-ahead, tests green |
| **P1** | LevelEngine + StructureEngine + StateBoard | Given a fixture day, the level book and board match hand-computed expectations |
| **P2** | Guards + ModeMachine | Mode transitions correct across a full fixture day; BLOCKED latches properly |
| **P3** | Setups A/B/C detectors | Each detector fires on its golden fixture and stays silent on near-miss fixtures |
| **P4** | RiskEngine + SpaceCheck + sizing | Correct SL/R/size, correct rejections at every bound |
| **P5** | OptionsLayer + PaperBroker + cost model | Simulated fills with realistic slippage; net P&L math verified by hand |
| **P6** | ExitEngine | Invalidation, T1, trail, time stop all fire correctly on fixtures |
| **P7** | Journal + daily report | Full decision log incl. rejections; end-of-day report generated |
| **P8** | `KiteFeed` (live data, still paper fills) | Runs a full session live without crashing, decisions logged |
| **P9** | Replay validation on ≥6 months of 1m data | Report by regime, by time bucket, expiry vs non-expiry, net of costs |

**Only after P9 produces a positive net-of-cost result across multiple regimes should
live execution even be discussed** — and that is a separate decision requiring its own
review, including the current SEBI/exchange requirements for retail algo order
placement, which must be confirmed with the broker.

---

## 8. HONEST FRAMING — keep this in mind while building

Every number in `params.yaml` is a **starting hypothesis**, not a discovered truth.
The wick-percentage, the 2.5× space ratio, the 90-minute level age — all of it was
reasoned from market structure, none of it was measured. The purpose of P9 is to find
out which of these are real and which are decoration.

Expect the honest outcome: most days produce **zero trades**, roughly half of taken
trades lose, and the entire edge — if there is one — lives in the size of winners
versus losers plus the discipline of the session limits. If the P9 report shows the
edge disappearing once costs are subtracted, the correct response is to stop, not to
add another filter.

This system can lose money. Build it carefully, test it honestly, and size it small.
