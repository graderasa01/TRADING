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
              "is_expiry": false, "atr_bucket": "20-30", "control": "buyers"}
}
```

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
```

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
| P1 | Level book on `full_session.csv` matches the hand-computed `expected.yaml` |
| P2 | Mode split within ±5% of hand-count; limits latch correctly |
| P3 | All golden fixtures fire; all near-miss fixtures silent |
| P4 | Every risk boundary rejects at the right value |
| P5 | Charges verified by hand against the broker's published rates for 3 sample trades |
| P6 | All six exit reasons reproduced on fixtures |
| P7 | Daily report generated; rule audit clean |
| P8 | Five consecutive live sessions with reconciliation PASS and zero crashes |
| P9 | ≥6 months replay, reported by every context cut, **net of costs** |

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
