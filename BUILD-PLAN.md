# BUILD PLAN

> How this gets built, phase by phase, following `BUILD-BRIEF.md` §2 exactly.
> `CLAUDE.md` is what the system is. `BUILD-BRIEF.md` is the working agreement.
> **This file is the schedule** — what happens in what order, what proves each phase
> is done, and what is needed from the trader at each point.
>
> Written 2026-08-12, after the data pipeline and `data/DATA-REPORT.md`.

---

## 0. WHERE WE ARE

Done, before P0, per `KICKOFF.md` §1:

- `tools/fetch_kite.py`, `tools/verify_data.py`, `tools/check_no_secrets.py`
- 3 years × 4 instruments downloaded — 746 normal sessions, ~280k 1m candles each,
  743/746 clean, zero duplicates, zero OHLC violations
- `data/DATA-REPORT.md` — **`atr_min 12` / `atr_max 60` measured and sound on Bank Nifty**
  (p1.4 / p98.5), and shown to be unusable across four instruments as absolute points
- `DECISIONS.md` — D-001…D-018
- 48 tests green, lint clean, secret scan clean, pre-commit hook installed

**Not started: any engine code.** That is correct — `KICKOFF.md` §1 requires the data
report first, and it has now been delivered and read.

---

## 1. FOUR DECISIONS THAT CLOSE BEFORE P0

Not a formality. Each one changes code that gets written in the next phase, and
`BUILD-BRIEF.md` §0 requires them written down *before* that code exists.

### 1.1 The volatility gate's form — **needs the trader**

`DATA-REPORT.md` §5: `atr_min_points 12` blocks 1.4% of Bank Nifty candles and **84.3% of
Nifty 50**. As absolute points these thresholds cannot serve the four-instrument P9 that
`CLAUDE.md` §8 calls the strongest available test. Three options, in `PROGRESS.md`.

**Everything else in this plan is unaffected by the answer** — it changes P9's design and
two lines of `params.yaml`, nothing structural. So it does not block P0. It must be
answered before P4 (where `test_thresholds_are_index_level_invariant` runs) and it must
not be answered by drifting into a default.

### 1.2 L3 backstop vs the paper-only prohibition — **needs the trader**

Spec 07 §2.0 requires a **real SL-M resting at the broker** after every entry fill. P6's
gate is *"kill the process holding a position → an SL-M is found resting at the broker."*
`CLAUDE.md` §6 forbids any live order path and `PaperBroker` is specified as "no network
writes." **P6's gate cannot pass in the paper phase as written.**

Proposal, to be confirmed: build `exits/backstop.py` fully, have `PaperBroker` record the
backstop order in its own book, and restate P6's gate as *"kill the process → the
backstop order is found in the broker's persisted book, and the watchdog flattens."* The
real-order version becomes a P8+ item behind the same prohibition. Logged as D-019 once
agreed.

### 1.3 Cost gate in replay — **decide before P9 is designed, not before P0**

Spec 07 §1.6 computes `spread = quote.ask - quote.bid`, *"observed, not modelled."* A
3-year replay has no quotes. Either P9 runs on a modelled spread — and then its headline
is **not** "net of measured costs" and the report must say so in the header — or option
quote history is needed. D-020.

### 1.4 Three smaller spec gaps — **I decide, you can veto**

Found while reading; each gets a `D-0xx` entry before the code that touches it:

| gap | where | proposed |
|---|---|---|
| ANCHOR `departure_speed` needs the previous session's candles | spec 03 §3 | `ReplayFeed` loads D-1 as warmup context, not just PDH/PDL/PDC |
| `atr20_at(born_i)` undefined for levels born before candle 20 | spec 03 §3 | departure scores 0 until ATR20 exists; the level is not penalised permanently, it is re-graded when ATR arrives |
| spec 05 §2 says "resolve the nearest **weekly** expiry" | spec 05 | leftover v1 text — Bank Nifty is monthly (spec 08). Implement monthly, assert the weekday |

Also: spec 05 §9's `test_mode_distribution_sane` asserts WATCH ≥ 50% without saying on
which baseline. On the whole session a correct engine gives ~28%. The test uses the
**non-BLOCKED** baseline, per spec 05 §6's own v2.2 correction.

---

## 2. THE PHASES

Every phase ends with: **gate green → detection counts printed → `PROGRESS.md` written →
stop and report.** No phase starts the next one. This is `KICKOFF.md` §4 and it is the
rule the dry run proved was necessary.

### P0 — foundation
**Build.** `config/loader.py` (schema-validated, refuses on `risk_per_trade_rupees: null`,
on stale `costs.yaml`, on stale `events.yaml`) · domain models from spec 02, all
`frozen=True`, `Decimal`, tz-aware `Asia/Kolkata`, invariants asserted at construction ·
`feed/replay_feed.py` reading the parquet written by `fetch_kite.py`, applying D-018 ·
`feed/aggregator.py` 1m→5m→15m with the partial/closed type split from spec 01 §4 ·
CI checks: no `src/broker/live.py`, no `datetime.now()` in the engine, no float in money
paths, no magic numbers in logic files.

**Gate.** `test_no_lookahead_by_truncation` (spec 09 §3.3) — for every candle *i*, the
decision computed with the feed truncated at *i* is identical to the decision computed
with the whole day present. Plus the aggregator exact on a real session, plus
`test_replay_skips_abbreviated_sessions` (D-018).

**Needs from you.** Nothing. **Estimate.** 1–2 sessions.

---

### P1 — the level engine ⚠ *the phase everything else stands on*
**Build.**
- `levels/` — four births: TURN (swing pivots on **1m/5m/15m** + wick clusters), LAUNCH
  (impulse + quiet base + departure speed), BREAK axis (only from a Grade A/B level —
  spec 03 §5 v2.2), ANCHOR (PDH/PDL/PDC, opening range, round numbers demoted per §6).
  Zone geometry `body_edge`/`wick_tip`/`pocket`. **Touch counting with separation**
  (Bug 2). **`departure_speed` computed for every kind** (Bug 1). Grading 0–4. Obstacle
  strength strong/medium/weak. Death rules. Dormant pool with revival keeping history
  (D-011d). 8-level cap with the D-006 tie-break. Cross-timeframe dedup (D-011c).
- `structure/` — swings, BOS on body close, trend, regime, `pullback_ratio` (D-005),
  landing ladder, HTF forecast and last-third flag. **Never imports `levels/`.**
- `state/board.py` — the 8 variables, two-step anticipation line, deterministic
  `board_digest` (D-004).
- `journey.py` — D1–D4 ladder, **logged only**, plus the static test proving `setups/`,
  `risk/` and `exits/` never import it (D-011b).
- `tools/chart.py` — production chart renderer. Needed here, not in P1.5, because the
  overlap test cannot be scored without it.

**Gate.** `test_board_is_deterministic` (byte-identical digests across two replays) **and
the level-overlap test ≥ 60%** on your 10 marked sessions (spec 09 §3.2b). ~46 unit tests
from spec 03 §11 and spec 04 §9.

**Needs from you — at the START of P1, not the end.** 10 real Bank Nifty sessions with
your levels marked, **before you see any engine output.** Reverse that order and the test
measures agreeableness, not agreement. I will pick 10 dates from the downloaded data
across regimes and render clean charts with no lines on them.

**Estimate.** 4–6 sessions of build. The gate then waits on you.

---

### P1.5 — the teaching loop ⚠ *slow by design — see §3*
Detailed below because you asked specifically. **Do not expect P2 to start during it.**

---

### P2 — guards, modes, health
**Build.** All 13 guards in spec 05 §1 order · `modes/machine.py` · `state/session_store.py`
persisting on **every** change, resuming on restart, `--force-fresh-session` required to
reset · **`src/health/reachability.py`** — the 12 assertions from spec 10 §3.3, run before
the first candle, engine refuses to start on any failure · health monitor and startup banner.

**Gate.** Restart test — kill after 2 fills, restart, `trades_taken == 2` — **and 12/12
reachability assertions pass.** Build the assertions first; they cost an hour and would
have caught three of the four dry-run bugs before a single candle.

**Needs from you.** `config/events.yaml` (RBI MPC + 5 heavyweight bank results + Budget)
and `session.risk_per_trade_rupees`. The engine refuses to start without both.
**Estimate.** 2–3 sessions.

---

### P3 — the three setups
**Build.** A flip-retest, B sweep-reclaim (with `b_entry_mode: "pullback"` and both
alternatives logged), C range-break-retest. Registry length asserted to be 3.

**Gate.** Golden fixtures fire, near-miss fixtures stay silent, **and the full-session
detection counts are all > 0** (`BUILD-BRIEF.md` §4b):

```
levels born .......... > 20      Grade A reached ... > 0    ← Bug 1
ALERT candles ........ > 0       ← Bug 3
setups DETECTED ...... > 0       ← the number that matters
signals .............. 0 is acceptable
```

If any is zero I stop and diagnose with the funnel in `prototype/score.py` before P4.
**Needs from you.** Real chart fixtures — I will propose candidate dates from the data.
**Estimate.** 3–4 sessions.

---

### P4 — risk · P5 — options and cost gate · P6 — exits
| | gate | needs you |
|---|---|---|
| **P4** risk engine, space, sizing | `test_thresholds_are_index_level_invariant` — shift every price +20,000, the decision stream must be identical | §1.1 answered |
| **P5** options layer, PaperBroker, cost gate | spec 07 §3's worked example returns `cost_excessive`, not a Signal | `config/costs.yaml` + `last_verified` |
| **P6** exits, backstop, watchdog | all six exit reasons on fixtures; the §1.2 restated backstop gate | §1.2 answered |

**Estimate.** 2–3 sessions each.

---

### P7 — journal and reports · P8 — live data · P8.5 — cost verification · P9 — validation
| | gate | needs you |
|---|---|---|
| **P7** | `rules_followed == true` on every trade — a `false` is an engine bug | — |
| **P8** `KiteFeed`, quote logging | 5 clean sessions **and** tick-built vs historical decision-stream divergence measured and written into the report header | static IP host (SEBI, Apr 2026) |
| **P8.5** cost verification | measured spread replaces guesses; cost gate re-run over every P8 signal. **If most now reject, stop and reconsider the vehicle before P9** | 2 weeks of live quotes |
| **P9** replay validation | 3 years × 4 instruments, identical params, pre-registered grid committed **before** the first run | §1.1 and §1.3 answered |

**P8.5 is the cheapest disqualifier in the whole plan — two days of work against P9's
month.** `REVIEW-v2.md` §2 already shows the round trip costing 44–64% of R on a
25-point stop. Do the cheap test first.

---

## 3. P1.5 — THE TEACHING LOOP, IN DETAIL

You asked how you will point at the chart and give a reference for each candle. This is
that mechanism. Specs 12 and 13.

### 3.1 What I build — four tools

**`tools/chart.py` — the annotation chart.** The prototype version prints a candle index
only every 10th candle and has no readout, which is not enough to reference a specific
candle. The production version:

- one standalone HTML file, no server, no external assets — opens by double-click
- **hover crosshair** reporting `candle 76 · 10:31 · O 57650.4 H 57653.8 L 57648.4
  C 57648.8 · cursor 57,649`
- **click anywhere** copies a ready-to-paste YAML stub to the clipboard:
  `- price: 57649` / `candles: [76, 76]`
- engine lines drawn as spec 12 §8 requires: **Grade A solid, B dashed, C dotted** — so
  you see not just what it found but what it considers tradeable
- a **blank mode** (`--no-levels`) for the P1 overlap test, where you must mark first
- window selectable: `python tools/chart.py 2026-03-04 --candles 20 110`

**`tools/ask.py` — per-candle reasoning record (spec 13).** Point at any candle and the
engine prints what it saw, what changed on the board, where its attention was, what it
expected next — and the part that matters most, **"main ye dekh hi nahi sakta"**: the
things it measured but has no rule for. That list is derived from `params.yaml`, not
hardcoded, so it shrinks by itself when a detector is added.

```
python tools/ask.py 2026-03-04 77          # one candle
python tools/ask.py 2026-03-04 75 82       # a group
python tools/ask.py 2026-03-04 swing 57720 # around a swing
```

**`tools/annotate.py` — the pipeline.** Validates the schema, runs the fixed ~30
measurement battery at every annotated location, diagnoses which existing detector came
closest and by how much, cross-checks your stated reason against the measured numbers,
and proposes a change with **benefit and cost together**.

**`tools/regress.py` — the regression harness.** Every proposal is re-run over every
prior annotation. A proposal that kills a `confirmed_good` level is rejected outright.

### 3.2 How a session actually runs

```
1  I render the chart for a session you have not seen
2  You look, and write annotations/2026-03-04.yaml — three buckets
3  I measure, diagnose the near-miss, and cross-check against your reason
4  I propose at most 2 changes, each with mechanism + cost + reachability check
5  Regression over all prior annotations
6  Accept or discard — either way it goes in DECISIONS.md
```

### 3.3 Three rules I will hold you to

**Three buckets, all filled.** `missed` · `false_positive` · `confirmed_good`. An
annotation with an empty `false_positive` bucket is not calibration, it is inflation —
it pushes the engine toward more lines every single session, and more lines means more
ALERT, more setups, more trades. I will tell you when a bucket is empty.

**I get to disagree with you.** You write *"price 4 baar rejected hui"*; I count from the
data and it may say **2**. In that case I say so and stop, rather than quietly encoding
the mistake. Without that, this tool automates your opinion instead of the market.

**Sessions are picked blind and stratified.** 4 trending · 4 ranging · 2 gap · 1 expiry ·
1 high-vol = 12, sampled from the 746 downloaded sessions and **committed before you
annotate any of them**. 8 teach, **4 holdout never annotated**. If overlap is 80% on
teach and 50% on holdout, that is memorisation, and the answer is to revert to the
starting thresholds — not to re-run the loop with the holdout as a new validation set.

### 3.4 When it stops

Two consecutive sessions with no new rule · rule count grown by more than 4 · precision
below its starting value · new `missed` annotations colliding with earlier
`false_positive` ones. Then the holdout is measured **once, ever.**

### 3.5 Why this is slow, and why that is correct

Eight annotated sessions is a week of your time, not mine. Every phase after P1 sits on
the level engine, and **until P1.5 nobody has compared it to a chart.** Every detection
threshold — swing lookback 3, wick cluster 5 points, launch impulse 2.0 × ATR, departure
speed 1.0 — was reasoned, never measured. `prototype/FINDINGS.md` is a complete engine
that never traded; this is the phase that catches that class of failure.

**I will not start P2 to stay busy during it.**

---

## 4. HOW I TEST, EVERY PHASE

- **Fixtures are written from the spec text, by hand, before the code runs.** A fixture
  generated to match my own implementation tests that the code does what the code does.
  When one fails the default assumption is that the **code** is wrong; an `expected.yaml`
  changes only with the spec line that justifies it written down (`BUILD-BRIEF.md` §5).
- Every threshold tested at its boundary — one below, exactly at, one above.
- Static/architectural tests each phase: no live broker module, no `datetime.now()` in
  the engine, no float in money paths, no SL-widening path, `structure/` never imports
  `levels/`, `setups/` never imports the journey module or the options module.
- **No phase closes with a skipped or xfail test.** A phase that is 90% done is not done,
  and in this build the last 10% is usually the part that handles the case that loses money.
- Every phase prints the detection counts from §4b, not just a pass/fail.

---

## 5. WHAT I NEED FROM YOU, AND WHEN

You said you would auto-approve. That works for tool permissions and for the decisions in
§1.4. It cannot work for the rows below — these are **data and judgements only you have**,
and me supplying them would defeat the exact test they exist to run.

| when | what | why it cannot be auto-approved |
|---|---|---|
| **before P4** | the §1.1 volatility-gate answer | changes what P9 can claim |
| **before P6** | the §1.2 backstop answer | changes what P6's gate means |
| **start of P1** | **10 sessions with your levels marked** | must be marked before you see engine output, or it measures agreeableness |
| **before P2** | `session.risk_per_trade_rupees` | deliberately `null` — a conscious choice, per spec 05 §4 |
| **before P2** | `config/events.yaml` dates | engine refuses to start; fail-closed by design |
| **before P5** | `config/costs.yaml` + `last_verified` | a stale cost model produces a profitable backtest and an unprofitable account |
| **P1.5** | **12 annotated sessions**, 8 teach + 4 holdout | the calibration itself |
| **before P8** | a static-IP host | SEBI requirement since April 2026 |

---

## 6. WHAT I WILL NOT DO, INCLUDING IF ASKED

From `CLAUDE.md` §6 and `BUILD-BRIEF.md` §3:

- No `src/broker/live.py`. No live order path at this stage. There is a CI check.
- No averaging down, martingale, or size-up-after-loss.
- No stop-loss widening, no "temporarily disable SL" flag, no config key matching `disable.*sl`.
- No fourth setup — the registry length is asserted to be 3.
- No naked option selling. BUY only.
- No signal computed from option premium price action.
- No metric reported gross of costs.
- No optimisation loop tuning more than 2 parameters at once.
- **No changing `params.yaml` during a candle dialogue**, however obvious it looks in the
  moment. Candidates go to `annotations/candidates/` and through the spec 12 pipeline.
- **No chaining phases.** Each boundary is a decision point about whether to continue.

And one that is mine rather than the constitution's: if a gate would have to be loosened
to make more trades happen, I will show you the number and argue with you first.

---

## 7. THE FAILURE MODE THIS PLAN IS SHAPED AROUND

The most likely way this project fails is not bad code. It is that P0 through P7 all get
built well, every test goes green, the report looks clean — **and the engine never
trades**, and nobody notices for four months. That is exactly what the dry run did: four
interacting bugs, and a clean confident `NO_TRADE` on every candle.

Three things defend against it, and none is optional:

1. **P1's overlap gate** — spec 09 §3.2b
2. **P1.5's teaching loop** — specs 12 and 13
3. **Reachability assertions at every startup** — spec 10 §3.3

Everything else in this plan comes after those three.
