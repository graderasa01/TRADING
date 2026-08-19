# PROGRESS

## Session 5 — 2026-08-12 — the hypothesis pipeline

**You asked for the mechanism that takes what you see on a chart, checks whether the code
already does it, decides whether it *can* be done, tests it immediately, and judges it —
including telling you when you are wrong and when something is dangerous for you.**

```
306 tests · 0 failed · 0 skipped
ruff clean · secret scan clean
```

### Built

- `tests/data_split.yaml` + `tools/make_split.py` — **spec 11 §D1's split, which did not
  exist.** 37 months → teach 27 / validate 5 / holdout 5, drawn before the first
  measurement, digest-protected against hand editing (D-028).
- `src/learning/split.py` — `holdout()` demands a written reason and appends to
  `HOLDOUT-ACCESS.md`. Spec 11 §8.
- `src/reasoning/vocabulary.py` — 18 capabilities with **derived** status
  (`ACTED_ON` / `PLANNED` / `BLIND_SPOT` / `NOT_BUILT`) plus 5 `UNOBSERVABLE` entries.
- `src/learning/hypothesis.py` + `tools/hypothesis.py` — `vocab` → `new` → `translate` →
  `register` → `measure` → `validate` → `ledger`, each step refused until the one before
  it happened.

### Found — four real things, none visible from reading

1. **The outcome definition manufactured an 8× edge out of a random walk.** `expansion`
   was normalised by the span's own mean range — the quantity the predicate selected on.
   On pure noise: 12.0% vs a 1.5% base, p < 1e-40. Caught by
   `test_reports_no_edge_on_noise`, fixed by normalising against the ATR *before* the
   span (D-029). **This is the bug that would have made every number the tool prints a
   lie, and only a test demanding silence on known-null data could find it.**
2. **`levels.swing_lookback_bars_{1m,5m,15m}` was decorative.** The value lived in
   `params.yaml` *and* as `DEFAULT_K` in `indicators/swings.py`; both engines used the
   Python one. Tuning the config changed nothing — on the swing lookback, which every
   level and every BOS depends on. Wired to config; `test_every_params_key_is_read_
   somewhere` now scans all 130 keys (D-031).
3. **`volume` is unobservable, not a missing detector.** 1,120,535 candles, four
   instruments, **zero** with non-zero volume — Bank Nifty is an index. `record.py` had
   been inviting a detector that could never work (D-030).
4. **The verdict logic called a backwards result a success.** The first real run scored
   4.1% against a 16.5% base — significant and pointing the *opposite* way — and printed
   "SURVIVES teach". Direction is now part of the verdict.

### First real run, on real data

`coil-expansion` — spec 11 §5's own candidate rule, that compression precedes expansion.
543 teach sessions, 185,706 spans:

```
predicate fired  1,093 (0.59%)
YOUR RATE        4.1%      BASE RATE 16.5%      edge -12.4pp      p < 1e-28
VERDICT          CONTRADICTED
```

At this threshold and horizon, compression on Bank Nifty is followed by **less**
expansion than average, not more. Recorded in the ledger as `measured`, not deleted.

### Next

P3 — setups A/B/C. Gate: the detection-count block from BUILD-BRIEF §4b, and
`signals may be zero; detections may not be`.

**Still blocked on you, and now blocking more than before:** the 10 marked charts in
`reports/charts/INDEX.html`. Every month containing one is quarantined into `teach`
(D-028), so those charts are the only thing that turns 27 months of teach data into
something the loop can learn from.

---

## Session 4 — 2026-08-12 (overnight, autonomous, continued)

**P1.5 tooling COMPLETE. P2 gate GREEN.**

```
266 tests · 0 failed · 0 skipped · 0 xfail
ruff clean · secret scan clean
```

### P1.5 — the teaching loop's tools (specs 12 and 13)

| tool | what it does |
|---|---|
| `tools/ask.py` | spec 13's per-candle reasoning record — what it saw, what changed, where its attention was, what it expects, and **what it cannot see** |
| `tools/chart.py --levels` | the engine book overlaid, Grade A solid / B dashed / C dotted (spec 12 §8) |
| `tools/annotate.py` | `new` · `check` · `measure` · `regress` — the full spec 12 pipeline |
| `src/reasoning/record.py` | the blind-spot probes, derived from `params.yaml` |

Three disciplines are **enforced, not trusted**:

**The `false_positive` bucket is mandatory.** `check` fails a session that only lists
missing levels. Spec 12 §3.1: an annotation with an empty `false_positive` bucket *"is
not calibration, it is inflation"* — it pushes the engine toward more lines every
session, and more lines means more ALERT means more trades.

**The engine may disagree with you.** `measure` cross-checks numeric claims in the prose
against the data and stops when they conflict. On a test annotation claiming *"price
yahan 4 baar ruki"*, it answered: **8 separated touches, 21 raw candles touching** — and
refused to go further. Without that the tool *"sirf tumhari galtiyon ko code me likh
dega, extra steps ke saath."* It stays silent when there is no numeric claim to check;
a cross-checker that guesses produces noise, and noise gets ignored.

**Blind spots are derived, not hardcoded.** Each probe names the `params.yaml` keys a
detector for it *would* own; it is a blind spot exactly while none of them exists. Add a
compression detector and the admission retires itself. A test asserts that, and another
asserts that a measurement used only for *grading* (time-at-price) is still a
**detection** blind spot — spec 13's own example.

`chart.py --levels` **refuses** to run on the P1 gate selection, detected from the
file's `purpose` rather than its filename so a renamed copy is caught too.

### P2 — guards, modes, session state, reachability

**Reachability first**, as BUILD-BRIEF §2 demands. 16 assertions, `16/16` on the shipped
config, and — the part that matters — **17 tests that inject the real dry-run bugs and
assert the engine refuses to start**:

```
grade_a_min_score 5           -> some_kind_can_reach_grade_a FAILS   (Bug 1)
grade_a_min_score 4           -> anchor_can_reach_grade_a    FAILS   (Bug 1 + spec 06)
touch_separation 0            -> touch_separation_positive   FAILS   (Bug 2)
htf exemption removed         -> every_setup_has_a_window     FAILS   (Bug 3)
r_max_atr_mult 0.5            -> setup_b_r_is_achievable      FAILS   (Bug 4)
b_entry_max_extreme 1.2       -> b_entry_cap_fits_under_r_max FAILS   (the author's own)
round_100 -> medium           -> space_gate_is_satisfiable    FAILS   (REVIEW-v2 §5)
journey_gates_trades true     -> journey_does_not_gate_trades FAILS   (D-011b)
```

One test states an honest limit rather than coverage:
`test_reachability_cannot_catch_bug_4_as_it_actually_happened`. The real 09:58 sweep gave
R = 69 against a 40.7 ceiling not because the parameters were unreachable, but because a
genuine sweep's geometry was wider than any config could describe. No startup assertion
substitutes for running the thing.

**The Bug 3 fix is structural.** `htf_close_proximity` no longer touches the mode. It
returns which setups it blocks — A and C, never B — so the detector still runs in the
tail. That is the whole of spec 05 §3b: the guard's reason (*HTF candles reverse shape in
their final minutes*) is an argument about continuation entries, and Setup B is the trade
that profits from that reversal.

**Session state survives a restart.** The exact REVIEW-v2 §4 sequence is a test: two
losses, process dies, restart — and `trades_taken 2 / consecutive_losses 2 /
cumulative_r -2.00` comes back off disk. Starting fresh needs `--force-fresh-session`,
and `test_no_silent_counter_reset_path_exists` parses the AST to prove no other path
zeroes a counter.

### P2 gate
```
restart test .......................... PASS
reachability at startup ............... 16/16
htf tail blocks A and C, never B ...... PASS
19 reachability + guard gate tests .... PASS
```

`python tools/startup_check.py` prints the spec 10 §4 banner and **exits 1** — refusing
to start on the three config blockers that are yours to fill. That refusal is the design
working.

### Still blocked on you
Unchanged, and the first row is still the critical path: the 10 marked charts, the
volatility-gate form, the L3 backstop question, `risk_per_trade_rupees`, `events.yaml`.

### Next
P3 — setups A/B/C. Its gate is the detection-count block from BUILD-BRIEF §4b, and
`signals may be zero; detections may not be`.

---

## Session 3 — 2026-08-12 (overnight, autonomous)

**Phase: P1 BUILT. Gate NOT closed — it needs your 10 marked charts.**

That distinction is the whole report. The level engine runs, its internal tests pass,
and it has never been compared to a chart. Until it has, nothing below should be read as
"the level engine is right".

```
197 tests · 0 failed · 0 skipped · 0 xfail
ruff clean · secret scan clean
```

### Built
| module | what |
|---|---|
| `src/indicators/atr.py` | ATR14 + ATR20, session-scoped, history kept so `departure_speed` divides by the ATR **at birth** rather than the ATR now |
| `src/indicators/swings.py` | fractal pivots, confirmed-only. Neutral package so `levels/` and `structure/` share one rule instead of drifting apart |
| `src/levels/detectors.py` | the four births — swing pivot, wick cluster, LAUNCH, round-number grid |
| `src/levels/engine.py` | spec 03 §10's update order, grading, dormancy, the 8-cap, obstacle strength |
| `src/structure/engine.py` | swings, BOS, trend, regime, legs, ladder, HTF forecast. **Never imports `levels/`** |
| `src/journey/ladder.py` | D1–D4, logged only. Its own package so `setups/` can never reach it |
| `src/state/board.py` | the 8 variables, two-step anticipation line, deterministic digest |
| `src/p1_pipeline.py` | steps 1–4 of CLAUDE.md §3 wired together |
| `tools/level_report.py` | spec 10 §3.1/§3.2 health checks over any sample of sessions |

### Seven bugs, all found by running on real sessions

Not one fails a unit test written from the spec text, and not one is visible from
reading the code. They are distribution problems that only appear at scale — the same
class as everything in `prototype/FINDINGS.md`.

| # | bug | measured effect |
|---|---|---|
| 1 | breaks were non-directional | every level broke twice → **523 axes/session** |
| 2 | round numbers sat inside the book | 89% of it Grade B; a full-looking empty book |
| 3 | capped-out levels were frozen | stopped ageing, returned stale when the cap widened |
| 4 | a broken axis minted another axis | **62% of all breaks were axes eating axes** |
| 5 | wick clusters counted extremes, not wicks | spec 03 §2b says "wicks whose TIPS" |
| 6 | acceptance was non-directional | book starved to 2.1 of 8; **dormancy was dead code** |
| 7 | a gap-down open "broke" PDL and PDC | book left with 1 anchor, nearest level 1,231 pts away |

Bug 6 is the one worth reading twice. A support was being killed for having price above
it — which is a healthy untested support. The book ran at 2.1 levels against a cap of 8,
and the dormant pool (spec 03 §8b, the entire v2.1 "level memory" idea) **never
activated once in 30 sessions**. Every run printed `0 sleeps / 0 revivals` and nothing
about that looked wrong.

Bug 7 is Bug 6's cousin and matters most on exactly the days spec 05 §1c was written for.

### Where it stands, measured over 30 random sessions

```
                    first run    now      spec 10 §3.1/§3.2
levels born/session      442      211     —
axis-creating breaks     174       32     need <= 15   ← still 2x over
book at close            2.6      8.0     need >= 2    ok
Grade A reached/session   77       71     need >= 1    ok
LAUNCH levels/session      0     0.07     need >= 1    ← see below
sessions with 0 Grade A    0        0     FAIL if any  ok
largest grade share      91%      59%     need <= 90%  ok
```

Two warnings survive, and **both are deliberately left alone.**

**LAUNCH fires 0.07 times per session.** Measured over 40 sessions: the impulse rule is
fine (7.8 candles/session clear 2.0 × ATR20), but the quiet-base rule at 0.8 × ATR20 sits
at the 5th percentile of what actually precedes an impulse. Raising it to 1.0 would give
1.3/session, to 1.2 would give 2.3. **Not changed** — spec 03 §3 says of that rule *"This
is the correct outcome; do not relax it"*, and whether 0.07 is the rule working or the
threshold being wrong is precisely what P1.5 exists to answer. The full distribution is
in DECISIONS.md.

**Axis-creating breaks at 32 vs spec 10's ceiling of 15.** Down from 174, driven now by
`axis_min_broken_grade: "B"` and by how many levels reach Grade B. That is a threshold
question, not a bug, and it belongs to P1.5.

### New decisions
D-023 (time-at-price window, ATR20 absent at birth) · D-024 (acceptance consecutive **and
directional**) · D-025 (`broken` subsumes `accepted_through` — open, raise at P1.5) ·
D-026 (a broken axis dies, mints nothing) · D-027 (a wick cluster needs an actual wick) ·
plus two OPEN CALIBRATION entries: the LAUNCH base rule, and
`pullback_control_flip_ratio` sitting on the median of its own distribution.

### Blocked on you — unchanged and now the critical path
| what | blocks |
|---|---|
| **mark your levels on the 10 charts** in `reports/charts/INDEX.html` | the P1 gate. Nothing after P1 is trustworthy until this is scored |
| the volatility-gate form (BUILD-PLAN §1.1) | P4, and what P9 can claim |
| the L3 backstop question (BUILD-PLAN §1.2) | what P6's gate means |
| `session.risk_per_trade_rupees` · `config/events.yaml` | P2 startup |

### Next
P1.5 tooling — the chart with engine lines overlaid, `tools/ask.py` (spec 13's per-candle
reasoning record, including "main ye dekh hi nahi sakta"), and the annotation pipeline.
Then P2: guards, ModeMachine, session_store, and the reachability assertions from spec
10 §3.3, which are the cheapest defence in the whole build.

---

## Session 2 — 2026-08-12

**Phase: P0 COMPLETE.** Gate green. Stopped at the boundary, per `KICKOFF.md` §4.

### P0 gate
```
test_no_lookahead_by_truncation ......... PASS   (54 truncation points, real 375-candle session)
aggregator exact on a real session ...... PASS   (75 x 5m, 25 x 15m, each the fold of its own 1m)
test_replay_skips_abbreviated_sessions .. PASS   (D-018, 5 known days)
static prohibitions ..................... PASS   (13 checks)

104 tests, 0 failed, 0 skipped, 0 xfail
```

### Built
- `src/domain/models.py` — spec 02. Frozen, `Decimal`, tz-aware. The `close > high` candle
  from `prototype/gen.py` is now rejected rather than measured.
- `src/config/loader.py` — refuses to start on all three fail-closed conditions at once,
  plus the Setup B reachability constraint `params.yaml` documents inline.
- `src/feed/aggregator.py` — `PartialCandle` is a **separate type** with no `body`,
  wicks or `close_third`, so a detector reaching for a forming candle breaks on the first
  line (spec 01 §4).
- `src/feed/replay_feed.py` — D-014 conversion, D-018 sessions, D-022 gaps, `prev_close`
  and PDH/PDL resolved from the previous session that actually happened.
- `tests/test_static_prohibitions.py` — CLAUDE.md §6 as tests.
- `reports/charts/` — 10 blank sessions chosen mechanically (seed 20260812), quota per
  spec 09 §3.2b, with hover readout and click-to-mark.

---

## Session 1 — 2026-08-11

**Phase:** pre-P0 — the data pipeline (KICKOFF.md §1). No engine code.

### Done
- `tools/fetch_kite.py`, `tools/verify_data.py`, `tools/check_no_secrets.py`,
  `.env.example` (D-017), pre-commit hook installed.
- **The download ran.** 147 months, 0 failures, all four instruments
  (BANKNIFTY 260105, NIFTY 50 256265, FINNIFTY 257801, SENSEX 265). 2023-08-01 →
  2026-08-11, 746 normal sessions and ~280,000 candles each. `data/DATA-REPORT.md`.
- `DECISIONS.md` D-001…D-018.

### Found
- `atr_min 12 / atr_max 60` are **well placed on Bank Nifty** — p1.4 and p98.5.
- As absolute points they block **84.3% of Nifty 50** candles and 65.5% of FinNifty,
  which makes the four-instrument P9 in `CLAUDE.md` §8 impossible as designed.
- `prototype/session.json` has 2 candles with `close > high` — both planted sweeps.
- Tests were reading real credentials; a failing assertion printed the live API key.
