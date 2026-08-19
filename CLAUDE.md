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

## 1. THE TWELVE NON-NEGOTIABLES

These are architectural laws. Never override them for convenience.

> **v2 note:** #11 and #12 were added after a live-reality review. #6 was
> rewritten because it described something that cannot be built. Full reasoning
> in `REVIEW-v2.md` at the repo root — read it before touching risk or exits.

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

### 6. Three stop layers — and be honest about which is which

v1 said *"Hard SL — always resting in the system. Never mental."* **That is not
buildable as described, and the document should not have claimed it.** The stop is an
**index** level; the position is an **option**. No broker accepts an index-triggered
stop on an option leg. So v1's "resting hard SL" was in fact a software stop that dies
with the Python process — a mental stop with extra steps.

Build all three layers and never confuse them:

- **L1 — Thesis invalidation (software).** A body close back on the wrong side of the
  trigger level exits at market **immediately**, without waiting for anything else.
  This is the exit that saves the most money.
- **L2 — Index stop (software, tick-evaluated).** When the index touches `sl_index`,
  exit the option at market. **Evaluate on ticks, not only on 1m closes** — a
  close-only stop hands the market up to 59 seconds of free adverse movement, which on
  a 25-point R is most of the R.
- **L3 — Premium backstop (real, resting at the broker).** An SL-M on the option leg
  at `2.0 × R_premium` beyond entry, placed immediately after the entry fill. This is
  a **disaster stop** for a dead process, a lost websocket or a power cut. It is not
  the trading stop and it should essentially never fill. If it ever does, that is an
  incident to investigate, not a normal loss.

Plus an external heartbeat watchdog: no heartbeat for 90 seconds → flatten and alert.
A trading process that can die with a position open and no broker-side protection is
the single largest uncontrolled risk in the whole design.

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

### 11. Cost is a pre-trade GATE, not a post-trade report line

v1 modelled costs and reported them. That is not enough on this instrument.

Bank Nifty weekly options were discontinued on 20 Nov 2024 — **only monthly contracts
exist.** A monthly ATM premium is 3–4× a weekly's, and the round-trip spread plus
slippage on a 25-index-point R works out to **44–64% of R** before brokerage. At 0.50R
of cost the break-even win rate is **50%**, for a setup that realistically wins 35–45%.

So the cost of a specific trade, at the specific quote in front of us, decides whether
that trade can have positive expectancy at all. It must be checked **before** the
order, against the live spread:

```
reject with gate "cost_excessive" if
    modelled_round_trip_cost > 0.25 × R_premium
 OR R_premium < 8 × observed_spread
```

This gate will fire often. **That is the gate working.** Do not tune it down to get
more trades — tune the trade selection up to earn a bigger R.

### 12. Session state survives a restart, or the limits are decorative

The board is reconstructible from candles. **Session state is not.**
`trades_taken`, `consecutive_losses`, `cumulative_r`, the cooldown clock and the
duplicate-attempt registry exist only in memory in v1. A crash at 11:00 after two
losses would restart clean and let the engine lose the day a second time — the exact
scenario the limits exist to prevent, defeated by an unhandled exception.

Persist session state to disk on **every** change. On startup, if a state file exists
for today, resume from it. Starting fresh must require an explicit
`--force-fresh-session` flag and a loud log line. Silent reset is forbidden.

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
  ├─ 5  Guards          → event, gap, time, volatility, session ── fail ⇒ BLOCKED
  ├─ 6  ModeMachine     → WATCH | ALERT | IN | BLOCKED
  │
  ├─ 7  if ALERT:  SetupDetector (A / B / C)   ── none ⇒ Rejection
  ├─ 8            RiskEngine (SL, R bounds)    ── fail ⇒ Rejection
  ├─ 9            SpaceCheck (strong/medium obstacle ÷ R) ── fail ⇒ Rejection
  ├─ 10           OptionsLayer → strike, quote, delta ── no chain ⇒ Rejection
  ├─ 11           CostGate (spread vs R_premium) ── fail ⇒ Rejection   ← v2
  ├─ 12           Sizing → lots                ── size 0 ⇒ Rejection
  │                                            └─ pass ⇒ Signal ⇒ PaperBroker
  │                                                        └─ + premium backstop
  ├─ 13 if IN:    ExitEngine (invalidation → index SL → T1 → trail → time stop)
  └─ 14 Journal   → write Decision + full state snapshot, always
```

**Two things run OUTSIDE this candle loop and must not be folded into it:**

- **Tick-level stop evaluation.** L1 invalidation and L2 index-stop checks run on the
  tick stream, not on candle close. Rule 3 (closed candles only) governs *detection
  and signal generation*. It does not govern *exiting an open position* — waiting for
  a candle close to exit is not discipline, it is latency.
- **The heartbeat watchdog.** A separate process. If the engine stops emitting a
  heartbeat, the watchdog flattens via the broker and alerts.

Modules must be composable and independently testable. No module reaches into
another's internals. Data flows one way, down the list.

---

## 4. REPO LAYOUT

```
banknifty-copilot/
├── CLAUDE.md                  ← this file
├── config/
│   ├── params.yaml            ← every threshold, all marked HYPOTHESIS
│   ├── costs.yaml             ← brokerage/STT/slippage — VERIFY BEFORE USE
│   └── events.yaml            ← blackout calendar (RBI/Budget/bank results)
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
│   ├── state/         board.py  session_store.py                     ← v2
│   ├── guards/        time_guard.py  vol_guard.py  session_guard.py
│   │                  event_guard.py  gap_guard.py        ← v2
│   ├── modes/         machine.py
│   ├── setups/        base.py  flip_retest.py  sweep_reclaim.py  range_break.py
│   ├── risk/          engine.py  space.py  sizing.py  cost_gate.py   ← v2
│   ├── exits/         engine.py  backstop.py  watchdog.py            ← v2
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
| **P2** | Guards + ModeMachine + **event/gap guards** + **session persistence** | Mode transitions correct; BLOCKED latches; kill and restart mid-session → limits survive |
| **P3** | Setups A/B/C detectors | Each detector fires on its golden fixture and stays silent on near-miss fixtures |
| **P4** | RiskEngine + SpaceCheck + sizing | Correct SL/R/size, correct rejections at every bound, ATR-relative bounds verified at 3 ATR levels |
| **P5** | OptionsLayer + PaperBroker + **cost gate** | Simulated fills with realistic slippage; net P&L math verified by hand; cost gate rejects on a wide-spread fixture |
| **P6** | ExitEngine + **backstop + watchdog** | All six exit reasons on fixtures; kill the process with a position open → backstop is resting at the broker |
| **P7** | Journal + daily report | Full decision log incl. rejections; end-of-day report generated |
| **P8** | `KiteFeed` (live data, still paper fills) + **quote logging** | Full session live without crashing; **two weeks of bid/ask logged and slippage recalibrated from measurement** |
| **P8.5** | **Cost verification** | `costs.yaml` filled from the broker's published rates and hand-verified on 3 sample trades. Measured spread replaces the guessed slippage. **If the cost gate now rejects most historical signals, stop and rethink the vehicle before P9.** |
| **P9** | Replay validation, **≥3 years, cross-instrument** | Report by regime, time bucket, expiry vs normal, net of costs — and the **identical ruleset run unchanged on Nifty / FinNifty / Sensex** |

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

**On sample size — the thing that decides whether P9 means anything.** Three trades a
week over six months is ~70 trades. At a 40% win rate the 95% confidence interval on
that win rate is roughly ±12 percentage points. You cannot distinguish a real edge
from luck at that resolution, so a six-month single-instrument P9 is not a test — it
is a coin flip you will over-interpret.

The fix is free and it is the strongest anti-overfitting tool available: **run the
identical, unchanged ruleset on Nifty, FinNifty and Sensex over three years.** Four
instruments × three years is roughly 800–1000 trades. Rules that only work on Bank
Nifty in one six-month window are fitted to that window. Rules that survive
unchanged across four correlated-but-different instruments are probably describing
something real about how these markets move.

This is validation only. The prohibition on multi-instrument scanning *while trading*
(§10 of spec 01) stays — one instrument, traded properly.

This system can lose money. Build it carefully, test it honestly, and size it small.
