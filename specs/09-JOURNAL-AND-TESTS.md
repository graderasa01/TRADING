# 09 — JOURNAL, REPORTING & TEST PLAN

The journal is not logging. It is the **output of the system** during the paper phase.
The trades are almost incidental; what you are actually building is a dataset that
answers "which of my rules are real?"

---

# PART 1 — JOURNAL

## 1.1 Three streams

| Stream | File | Written | Purpose |
|---|---|---|---|
| `decisions` | `journal/YYYY-MM-DD/decisions.jsonl` | every candle | the full audit trail |
| `trades` | `journal/YYYY-MM-DD/trades.jsonl` | on round-trip close | performance |
| `snapshots` | `journal/YYYY-MM-DD/snapshots.jsonl` | every ALERT candle + every signal | full board + level book, for replay debugging |

JSON Lines, one object per line, append-only. Never mutate a written line.

## 1.2 Decision row

```json
{
  "ts": "2026-08-11T10:23:00+05:30",
  "mode": "ALERT",
  "index": 57118.35,
  "atr_1m": 22.4,
  "outcome": "rejection",
  "gate": "space_insufficient",
  "setup": "B_sweep_reclaim",
  "level_id": "L_1m_TURN_57100_1014",
  "computed": {
    "pierce_points": 11.5, "wick_ratio": 0.62, "reclaim_points": 7.0,
    "r_points": 25.0, "nearest_obstacle": 57148.0, "space_points": 30.0,
    "space_ratio": 1.20, "min_required": 2.5
  },
  "anticipation": "Price 57118. Active TURN 57100 (A, 1 touch), 18 pts above. IF body close below 57100 → flips to resistance, next support 57042 (76 pts). Control: buyers. Regime: transition.",
  "board_digest": "b3f1a9c2"
}
```

`NoOp` rows are compact — `{ts, mode, index, board_digest}` — but still written every
candle. A gap in the decision stream means the engine missed a candle, and you need to
be able to see that.

## 1.3 Trade row — and the column that matters

```json
{
  "trade_id": "2026-08-11-002",
  "setup": "A_flip_retest",
  "direction": "long",
  "entry": {"ts": "...", "index": 57118.0, "premium": 214.5, "lots": 12, "slippage": 2.0},
  "sl_index": 57093.0, "r_points": 25.0, "risk_rupees": 4680.0,
  "t1_index": 57155.5, "t2_index": 57240.0,
  "space_ratio": 2.88,
  "exits": [
    {"ts": "...", "reason": "t1", "premium": 227.0, "lots": 6},
    {"ts": "...", "reason": "trail", "premium": 241.5, "lots": 6}
  ],
  "gross_pnl": 5040.0,
  "charges_total": 486.0,
  "net_pnl": 4554.0,
  "r_realised": 0.97,
  "cost_drag_pct": 9.6,

  "rules_followed": true,
  "rule_violations": [],

  "context": {"regime": "trending", "time_bucket": "0930-1115",
              "is_expiry": false, "atr_bucket": "20-30", "control": "buyers",

              "_v2_": "──────────────────────────────",
              "instrument": "BANKNIFTY", "gap_day": false, "gap_pct": 0.08,
              "event_tag": null, "days_to_expiry": 19,
              "atr_at_entry": 22.4, "index_level_bucket": "57000-58000"},

  "v2_execution": {
    "observed_spread_at_signal": 1.4,
    "cost_as_fraction_of_r": 0.18,
    "capital_deployed": 324000.0,
    "ref_delta_measured": true,
    "r_realised_vs_planned": 0.97,
    "backstop_placed": true, "backstop_filled": false,
    "stop_eval": "tick"
  },

  "v2_counterfactual": {
    "space_v2": 122.0, "space_v1_all_obstacles": 72.0,
    "r_max_v2": 35.0,  "r_max_v1": 35.0,
    "would_v1_have_taken_this": true
  }
}
```

### v2 — the three fields that matter most in this block

**`r_realised_vs_planned`.** `risk_rupees` is a *model*: `r_points × ref_delta ×
lot_size`. The realised loss also absorbs IV movement, gamma and the exit spread — and
on a stop-out all three move against you together. If this number is systematically
above 1.0 on losers, the `−2R` daily cap is not capping at −2R, and every R in this
journal is wrong. That triggers `r_model_broken` (spec 05 §4b). Without this field,
"the strategy lost" and "the arithmetic underneath the strategy is wrong" look
identical in the P&L.

**`capital_deployed`.** To risk ₹5,000 on a 25-point stop you deploy ~₹3.2 lakh of
monthly ATM premium. That ratio never appears in an R-based report, but it decides
whether the account can hold the position at all.

**`index_level_bucket`.** Bank Nifty was ~35,000 in 2022 and ~57,700 in Aug 2026. Cut
every result by this bucket. If performance correlates with the index level rather than
with the regime, some absolute threshold is still hiding in the logic — v2 normalised
the ones that were found, and this cut is how you find the rest.

### `rules_followed` is computed, never self-reported

```python
def audit_trade(trade, decisions) -> tuple[bool, list[str]]:
    """Re-derive from the decision stream whether every rule held. Checks:
       - entry occurred in an allowed time window
       - mode was ALERT at entry
       - level grade was A
       - r_points within bounds
       - space_ratio >= minimum
       - SL was never widened (compare all sl_index values over the trade's life)
       - breakeven was set within one candle of T1
       - session limits were not exceeded
       - no duplicate attempt at the level
    """
```

Because this is a mechanical system, `rules_followed` should be `true` on every trade.
**A `false` is a bug in the engine**, not a discipline failure — and it must fail the
daily report loudly. This check is how you find out that a refactor quietly broke the
breakeven logic three weeks ago.

---

# PART 2 — REPORTS

## 2.1 Daily report (`reports/YYYY-MM-DD.md`, generated at 15:40)

```
BANK NIFTY CO-PILOT — 11 Aug 2026            MODE: PAPER
================================================================
Session:     ATR range 18–31   Regime: transition   Expiry: no
Mode split:  WATCH 71%  ALERT 24%  IN 5%            ← sanity check
Candles:     375 processed, 0 synthetic, 0 gaps
Reconciliation: PASS (0 mismatches vs official candles)

TRADES (2 of 3 slots used)
  #1  A_flip_retest  long   entry 57118  R 25  →  +0.97R   net ₹4,554
  #2  B_sweep_reclaim short entry 57202  R 19  →  −1.00R   net ₹−3,980
  Net: ₹574     Cost drag: 11.2% of gross

REJECTIONS (41 evaluated in ALERT)
  space_insufficient   17   ← the workhorse gate
  r_too_wide            9
  no_setup              7
  bias_conflict         4
  duplicate_setup       2
  size_zero             1
  htf_close_proximity   1

RULE AUDIT: 2/2 clean
SLIPPAGE: modelled 2.0 / observed 2.4 avg  ← recalibrate if drift persists

WHAT THE ENGINE EXPECTED, AND WHAT HAPPENED
  [3 anticipation lines from the largest moves of the day, with outcome]
```

The mode split and the rejection histogram are the two numbers to read first, before
the P&L. P&L on two trades is noise; the rejection distribution is information.

## 2.2 Weekly review

Group everything by the `context` block:

| Cut | Question it answers |
|---|---|
| by setup (A/B/C) | Is one of the three carrying all the value? Should another be deleted? |
| by time bucket | Is the morning window genuinely better than the afternoon? |
| expiry vs normal | Is the expiry regime worth trading at all? |
| by regime | Does the system only work in `trending`? |
| by ATR bucket | Are the volatility gates set at the right place? |
| by rejection gate | Which gate fires most, and would those trades have won? |

### The counterfactual study — the highest-value analysis here
For every `space_insufficient` and `r_too_wide` rejection, replay forward and record
what the trade *would* have done. If rejected trades win as often as taken ones, the
gate is destroying value rather than protecting it. If they lose more, the gate is real.

This is the only honest way to tune a threshold, and it requires the rejection log —
which is why every rejection is written in full.

#### v2 — make it a scored table for every gate, not a study of two

```
gate_value(g) = mean_R(trades taken) − mean_R(trades g rejected, replayed forward)
```

| Reading | Meaning | Action |
|---|---|---|
| strongly positive | the gate removes losers | keep |
| ≈ zero | the gate removes a random sample | **delete it** — it costs sample size and buys nothing |
| negative | the gate removes winners | delete it, and find out why the reasoning was backwards |

A gate scoring ≈ 0 is not harmless. It shrinks an already-tiny sample, and every
deleted gate is one less parameter to overfit. The bias should be toward deletion.

Run this specifically for the v2 changes, where both the old and new values are logged
on every decision (spec 03 §6b, spec 07 §1.2):

| Comparison | Question |
|---|---|
| `space_v2` vs `space_v1_all_obstacles` | Did demoting round numbers to weak add winners or just add trades? |
| `r_max_v2` vs `r_max_v1` | Are the large-R Setup B sweeps that v1 rejected actually good? |
| `cost_excessive` rejections | Replayed forward and **net of the real spread** — would they have paid? |

The last one is the whole ballgame. If the cost-rejected trades would have been
profitable *after* their actual costs, the gate is too tight. If they would not, the
gate has just told you the vehicle is wrong.

---

### v2 — cross-instrument validation: the strongest test available, and it is free

Six months of Bank Nifty at ~3 trades/week is ~70 trades. At a 40% win rate the 95%
confidence interval on that win rate spans roughly ±12 percentage points. That is not a
test; it is a number you will over-interpret in whichever direction it lands.

**Run the identical, unchanged ruleset on Nifty 50, FinNifty and Sensex, over 3 years.**

- Four instruments × three years ≈ **800–1000 trades**.
- No parameter may be re-tuned per instrument. Same `params.yaml`, same everything. If
  a rule needs different numbers on Nifty, it was fitted to Bank Nifty.
- ATR-normalised thresholds (v2) are what makes this possible at all — v1's absolute
  point thresholds are meaningless on an index trading at a different level, which is
  the same reason they were meaningless across a 3-year Bank Nifty sample.

| Outcome | Reading |
|---|---|
| Works on all four | The rules describe something real about how these markets move |
| Works on Bank Nifty only | Fitted to one instrument in one window. The honest conclusion is no edge |
| Works on none | Clear, cheap, early answer. This is a good outcome — you found out for free |

This is **validation only.** The prohibition on multi-instrument scanning while trading
(spec 01 §10) stands: one instrument, traded properly.

---

### v2 — pre-registered sensitivity grid, instead of one point estimate

A single P9 run gives one number at one parameter combination. That tells you nothing
about whether the result is a plateau or a spike.

**Before running P9**, write down the grid — commit it to the repo, dated. Then run
every combination and look at the *surface*, not the peak:

```yaml
# tests/p9_grid.yaml — WRITTEN AND COMMITTED BEFORE THE FIRST P9 RUN
sweep_wick_ratio:   [0.45, 0.55, 0.65]
min_space_ratio:    [2.0, 2.5, 3.0]
r_max_atr_mult:     [1.2, 1.4, 1.6]
t1_r_multiple:      [1.2, 1.5, 2.0]
```

| Surface shape | Meaning |
|---|---|
| Broad plateau — neighbours all positive | Plausibly real. Take the **centre**, never the peak |
| Single spike surrounded by losses | Noise. There is no edge, only one lucky cell |
| Monotonic toward an edge of the grid | The grid is wrong, or the parameter should not exist |

Pre-registration is what separates this from curve-fitting. Choosing the grid after
seeing results, or extending it toward whatever looked good, is fitting with extra
steps. Spec 01 §8's rule — never tune more than 2 parameters at once — applies to
*tuning*. This is measuring stability, and it is judged on the shape, not the maximum.

**If the plateau is not broad, the correct conclusion is that the system has no
demonstrated edge.** Not "try a fifth parameter."

---

# PART 3 — TEST PLAN

## 3.1 Fixtures — hand-built, hand-verified

`tests/fixtures/` holds small CSV candle sequences with an accompanying
`expected.yaml`. Build these **by hand** from real chart situations, computing the
expected level prices, R, and outcomes manually.

Required fixtures:

| Fixture | Contains |
|---|---|
| `golden_setup_a.csv` | Clean break, retest, higher-low, trigger |
| `golden_setup_b.csv` | Sweep with 11-pt pierce, 62% wick, reclaim next candle |
| `golden_setup_c.csv` | 24-candle compressing range, break, acceptance, retest |
| `near_miss_b_wick.csv` | Identical to golden B but 50% wick → must NOT fire |
| `near_miss_b_pierce.csv` | 6-pt pierce → must NOT fire |
| `near_miss_a_no_hl.csv` | Retest with no higher-low → must NOT fire |
| `breakout_not_sweep.csv` | Big wick but body closes outside → must NOT be Setup B |
| `failed_breakout.csv` | Range break then close back inside → routes to Setup B opposite |
| `launch_inside_5m.csv` | 1m launch base entirely inside one 5m candle body |
| `gap_day.csv` | Missing minutes → synthetic + FeedGapError behaviour |
| `lunch_perfect_setup.csv` | Textbook setup at 12:10 → must be rejected on time |
| `expiry_day.csv` | Expiry windows, halved size, measured delta |
| `full_session.csv` | One complete 375-candle day for integration + determinism |
| `sweep_large_candle.csv` | **v2:** 45-pt sweep candle at ATR 35 → R ≈ 41, must be **accepted** (v1 rejected it as `r_too_wide`) |
| `wide_spread_signal.csv` | **v2:** perfect setup, quoted spread 3.0 prem pts → `cost_excessive` |
| `round_number_trap.csv` | **v2:** valid setup with a round-100 at 30 pts and PDH at 122 pts → must **pass** the space gate |
| `round_number_alert.csv` | **v2:** price hovering near a 100-mark with no real level → mode stays WATCH for the whole fixture |
| `gap_day_open.csv` | **v2:** 0.6% gap → carried levels dead, no entries before 10:00 |
| `event_blackout_day.csv` | **v2:** date present in events.yaml → every candle rejects |
| `restart_midsession/` | **v2:** two-part fixture — run, kill after 2 fills, resume, assert `trades_taken == 2` |
| `nifty_full_session.csv` | **v2:** same engine, different instrument and index level — used for the cross-instrument check |

## 3.2 Test layers

**Unit** — every rule function in isolation. Every threshold tested at the boundary
(one below, exactly at, one above).

**Property-based** (hypothesis library):
```python
def test_sl_always_beyond_extreme(any_candidate, any_atr): ...
def test_r_always_within_bounds_or_rejected(any_candidate): ...
def test_space_ratio_never_below_minimum_in_a_signal(any_signal): ...
def test_lots_never_negative(any_inputs): ...
```

**Integration** — `full_session.csv` end to end, asserting exact trade count, exact
entry/exit prices, and exact net P&L. Any change to any threshold must change this
test's expected values deliberately — that is the point.

**Determinism** — replay the same day twice, assert byte-identical decision streams.

**Static / architectural**:
```python
test_structure_never_imports_levels
test_setups_never_import_options
test_no_live_broker_module
test_no_magic_numbers_in_logic     # regex for numeric literals outside config
test_no_datetime_now_in_engine
test_no_float_in_money_paths
test_gross_never_in_output

# ── v2 ──
test_no_silent_session_counter_reset   # no `trades_taken = 0` outside the fresh path
test_no_sl_widening_path               # sl_index never reassigned outward
test_every_threshold_has_atr_form      # every points threshold has an atr_mult sibling
test_algo_id_on_every_order            # SEBI: orders carry the exchange tag
test_engine_refuses_stale_cost_model   # costs.yaml unverified → startup refusal
test_engine_refuses_stale_event_file   # events.yaml >30 days → startup refusal
```

**v2 — the index-level drift test.** The most important new static-ish test, because it
catches the whole class of bug that v1's absolute thresholds represent:

```python
def test_thresholds_are_index_level_invariant():
    """
    Take full_session.csv. Produce a second copy with every price shifted
    +20,000 points and every range scaled proportionally.
    The decision STREAM (gates fired, setups detected, entries taken) must be
    IDENTICAL — only the absolute prices differ.

    If it is not identical, an absolute point threshold is still hiding in the
    logic, and any multi-year or cross-instrument backtest is silently testing
    a different system at each end of the sample.
    """
```

## 3.2b THE LEVEL-OVERLAP TEST — v2.1. Run this before anything else.

**The problem it solves.** Every phase from P2 onward assumes the level book is
approximately right. Nobody has ever checked. Swing lookback 3, wick-cluster tolerance
5 points, launch impulse 2.0 × ATR, departure speed 1.0 — all guesses. The engine will
confidently draw eight lines every day, and whether they are the *right* eight lines is
completely unknown.

If the level engine is wrong, **nothing downstream can be right.** A perfect risk engine
sizing a perfect setup at the wrong level is a perfect way to lose money. This is the
cheapest possible test of the foundation and it costs half a day.

### Protocol

1. Pick **10 real Bank Nifty sessions** across different regimes — 3 trending, 3
   ranging, 2 gap days, 1 monthly expiry, 1 high-volatility.
2. **The trader marks their levels first, on a clean chart, without seeing the engine's
   output.** This ordering is the whole test. Reverse it and you are measuring
   agreeableness, not agreement.
3. Run P1 over the same sessions. Render the engine's active book with
   `render_levels_chart: true` → `reports/charts/`.
4. Score each session:

```
matched   : engine line within  max(10 pts, 0.4 × ATR20_1m)  of a human line
missed    : human drew it, engine has nothing there          ← the dangerous one
invented  : engine drew it, human sees nothing there

overlap = matched / (matched + missed)
noise   = invented / total_engine_lines
```

Score the **Grade A book only** — Grade B and C are context, and the human does not
draw context.

### How to read the score

| Overlap | Reading | Action |
|---|---|---|
| **≥ 75%** | The arithmetic reproduces the eye | Proceed to P2 |
| **60–75%** | Broadly right, tuning needed | Look at the *misses*, not the score. Proceed with the gaps documented |
| **40–60%** | The engine finds different levels than the human | **Stop.** Diagnose before P2 |
| **< 40%** | The foundation is not the strategy in the specs | **Stop.** Everything downstream is moot |

**The `missed` bucket is the valuable output, not the score.** Every miss is a level the
human's eye found and no rule describes. For each one, the question is always the same:
*"kis number se pata chala?"* — what measurable property made that a level? The answer
becomes a new detection rule, or a changed threshold.

Expect the first run to be noisy in a specific way: the raw detectors are far chattier
than the eye. On a 27-candle sample the wick-cluster rule alone can produce 8 candidate
clusters where a human would draw 2. The human eye filters automatically; the engine
needs the filter written down. That is what grading and the 8-level cap are for — **so
score after the cap, never before it.**

### Deliverable

`reports/level_overlap.md` — per session: the rendered chart with both sets of lines,
the three counts, and a table of every miss with the trader's one-line reason.

Re-run it after any change to `levels:` params. It is the regression test for the
foundation.

---

## 3.2c The Journey hit-rate report — v2.1

The Journey Ladder (spec 04 §6b) writes a prediction on every level break and never acts
on it. This is where those predictions get scored.

```
journeys started (by direction, regime, time bucket, origin grade)
% reaching D1 / D2 / D3 / D4
% stalled  ·  % failed on invalidation
median max_progress ÷ distance to D2
median 5m candles to reach D2
hit rate when D2 and D3 agree (confluence) vs when they do not
```

**D2 is the one that matters** — it is the rung that encodes *"jahan se aaya wahan tak
jayega."* That claim is the trader's core belief about this market and it has never been
measured.

Report it plainly and without cushioning. If D2 hits 70%, it has earned the right to
drive T2 selection and `journey_gates_trades` becomes a real decision. If it hits 45%,
the honest conclusion is that price reaching its origin was a memorable pattern rather
than a reliable one — and knowing that is worth more than a year of feeling it.

Run this from P7 onward, on paper data, long before P9. It needs no capital and no
edge — only breaks, which happen every day.

---

## 3.3 No-look-ahead — the test that protects everything

```python
def test_no_lookahead_by_truncation():
    """
    For every candle index i in the fixture:
      decisions_full[i]  computed with all candles present
      decisions_trunc[i] computed with the feed truncated at i
    These must be identical for all i.
    """
```

If this passes, the paper results are structurally trustworthy. If it fails, nothing
else in the report means anything. Run it in CI on every commit.

## 3.4 Acceptance criteria per build phase

| Phase | Cannot proceed until |
|---|---|
| P0 | Aggregator exact on `full_session.csv`; no-look-ahead test green |
| P1 | Level book matches `expected.yaml` **AND the level-overlap test below scores ≥60%** |
| P2 | Mode split within ±5% of hand-count; limits latch correctly |
| P3 | All golden fixtures fire; all near-miss fixtures silent |
| P4 | Every risk boundary rejects at the right value |
| P5 | Charges verified by hand against the broker's published rates for 3 sample trades; **cost gate rejects `wide_spread_signal.csv`** |
| P6 | All six exit reasons reproduced on fixtures; **process killed with a position open → backstop found resting at the broker** |
| P7 | Daily report generated; rule audit clean |
| P8 | Five consecutive live sessions with reconciliation PASS and zero crashes; **≥2 weeks of bid/ask logged; tick-built vs historical decision-stream divergence measured and stated** |
| P8.5 | **`costs.yaml` verified and `last_verified` set; measured spread replaces guessed slippage; cost gate re-run over all P8 signals.** If most now reject, stop and reconsider the vehicle before spending time on P9 |
| P9 | **≥3 years, four instruments** (BankNifty, Nifty, FinNifty, Sensex), identical params, reported by every context cut, **net of measured costs**, plus the pre-registered sensitivity grid |

## 3.5 What P9 must report — and how to read it honestly

For the whole sample and for every context cut:

```
trades, win rate, avg R (net), median R, profit factor (net),
max drawdown in R, max consecutive losses,
cost drag as % of gross,
distribution of R (not just the mean — the mean hides everything),
trades per month (is this even worth running?)
```

Read it against these standards:

- **Net of costs, or it does not count.** If the edge is gross-only, there is no edge.
- **Consistency across regimes matters more than the headline number.** A system that
  only works in `trending` is a bet on regime, not an edge.
- **Beware a beautiful result.** These thresholds were reasoned, not fitted — if the
  first run looks excellent, suspect a look-ahead leak before celebrating. Re-run the
  truncation test.
- **Sample size.** Three trades a week over six months is roughly 70 trades. That is
  too few to distinguish a real edge from luck with confidence. Treat P9 as a
  *disqualifier* — it can prove the system fails, it cannot prove it works.
- **The honest default conclusion is "not proven."** Proceeding to live after P9 means
  accepting a small, uncertain edge with real money, and the appropriate size for that
  is very small.

If P9 shows no edge after costs, the correct response is to stop or to simplify — not
to add a fourth setup or a ninth filter. Every filter added after seeing the results is
curve-fitting, and it will not survive contact with next month's market.
