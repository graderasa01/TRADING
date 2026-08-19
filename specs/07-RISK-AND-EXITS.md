# 07 — RISK ENGINE & EXIT ENGINE

> Everything in this file is computed in **index points**, then translated to option
> premium only at the broker boundary. Stops and targets live on the index.

---

# PART 1 — RISK ENGINE

## 1.1 Stop loss placement

```python
sl_buffer = max(
    params.risk.sl_buffer_min_points,          # v2: 6   (was 10)
    params.risk.sl_buffer_atr_mult * atr_1m,   # v2: 0.45 (was 0.25)
)

# long
sl_index = candidate.extreme - sl_buffer
# short
sl_index = candidate.extreme + sl_buffer
```

`candidate.extreme` is the **wick tip** of the sweep (Setup B) or the **low of the 1m
higher-low** (Setups A and C).

Two rules encoded here:

1. **Never on the level.** The level is exactly where everyone else's stop is, which is
   exactly where price is drawn to. The stop goes beyond the wick that already cleared
   those stops.
2. **Buffer scales with volatility.** A flat 10 points is correct on a quiet day and
   suicidal on a 60-ATR day. The ATR term handles that automatically.

**v2 correction — in v1 the ATR term never fired.** `max(10, 0.25 × ATR)` only exceeds
10 when ATR > 40, and Bank Nifty 1m ATR14 sits in the 15–35 band for the large majority
of tradeable minutes:

| ATR14_1m | v1 buffer | which term won |
|---|---|---|
| 15 | 10.0 | flat 10 |
| 25 | 10.0 | flat 10 |
| 35 | 10.0 | flat 10 |
| 40 | 10.0 | flat 10 (tie) |
| 50 | 12.5 | ATR |

So the claim above was false roughly 95% of the time — v1 shipped a flat 10-point
buffer with an ATR expression decorating it. v2 uses `max(6, 0.45 × ATR)`, which gives
6.8 / 11.3 / 15.8 / 22.5 across the same rows and actually adapts. The floor drops to 6
only so that it never becomes the binding term in the normal range; it is a dead-market
guard, not the operating value.

## 1.2 R bounds — hard rejections

```python
r_points = abs(entry_index - sl_index)

# v2 — bounds are ATR-relative. Points are floors, not the operating values.
r_min = max(params.risk.r_min_points,      # 12
            params.risk.r_min_atr_mult * atr_1m)      # 0.55
r_max = min(params.risk.r_absolute_max_points,        # 60 — never exceed
            max(params.risk.r_max_points,             # 35
                params.risk.r_max_atr_mult * atr_1m)) # 1.40

if r_points < r_min:  return Rejection("r_too_tight", ...)
if r_points > r_max:  return Rejection("r_too_wide", ...)
```

- **Too tight** — the stop is inside the noise band. It will be hit by random movement
  regardless of whether the read was correct.
- **Too wide** — usually caused by a large trigger candle. The reward needed to justify
  it will not fit inside the available space. Skipping is the correct answer; widening
  the target to make the ratio work is the classic self-deception.

**There is no path that adjusts the stop to satisfy these bounds.** The stop is
determined by structure. If the resulting R is out of bounds, the trade does not exist.

### v2 — why the flat 35-point ceiling had to go: it deleted Setup B

Trace the geometry of a *qualifying* Setup B sweep candle (spec 06 §B2–B6). It must
pierce by ≥8 points, its wick must be ≥55% of its range, and it must close in the top
third. So the close sits around `low + 0.70 × range`, and:

```
R  =  entry − SL  =  (0.70 × range)  +  sl_buffer
```

With v1's buffer of 10:

| sweep candle range | v1 R | v1 verdict |
|---|---|---|
| 20 | 24.0 | OK |
| 25 | 27.5 | OK |
| 30 | 31.0 | OK |
| 40 | 38.0 | **r_too_wide — rejected** |
| 50 | 45.0 | **r_too_wide — rejected** |

A 40–50 point 1m candle is not unusual on Bank Nifty in an active window — it is what a
real liquidity sweep at a defended level *looks like*. So v1's ceiling was not filtering
out bad trades; it was filtering out **the strongest expression of the setup**, keeping
only the small, timid sweeps. And note the ceiling was flat, so this happened *more*
on high-volatility days, when the sweeps are most meaningful.

Worse, the bias is systematic in the wrong direction. Combined with the cost gate
(§1.6), small-R trades are exactly the ones where cost eats the most of R. v1's two
gates pushed in opposite directions: `r_too_wide` forced R small, cost drag punished
small R.

v2's ceiling of `max(35, 1.40 × ATR)` gives 35 on a quiet 20-ATR day and 56 on a fast
40-ATR day, with a hard absolute cap of 60. The space gate still scales with R
automatically — it is a ratio — so a bigger R must earn proportionally bigger space.

**Log both R bounds on every decision** (`r_max_v1`, `r_max_v2`) so the spec 09
counterfactual study can measure whether this change helped, rather than anyone
assuming it did.

## 1.3 Space check

```python
# v2 — the space GATE uses obstacles of strength >= medium (spec 03 §6b).
#      T1 placement separately respects obstacles of ANY strength, incl. weak.
nearest = levels.space_obstacle(entry_index, direction)   # strength >= medium
space_points = abs(nearest.body_edge - entry_index)
space_ratio  = space_points / r_points

if space_ratio < params.risk.min_space_ratio:  # 2.5  HYPOTHESIS
    return Rejection("space_insufficient", ...)

# always logged for the counterfactual study
computed["space_v1_all_obstacles"] = abs(levels.t1_obstacle(entry_index, direction).body_edge - entry_index)
```

The gating obstacle list includes Grade A and B levels, PDH/PDL, day extremes, 500/1000
round numbers and the far side of an active range. **The nearest of those wins, always.**

This is the gate that fails most often, and that is the intended behaviour. A correct
entry into a wall 30 points away is a losing trade with a good-looking chart.

**v2 — why weak obstacles no longer gate.** v1 included every 100-point round number.
Distance to the next 100-mark is essentially uniform on [0,100], so a 25-point R needed
62.5 points of clear air against a mean available gap of 50 — a 37.5% pass rate driven
entirely by the last two digits of the entry price, and 0% for any R ≥ 40. The gate was
rejecting trades for a reason unrelated to the trade. Full arithmetic in spec 03 §6.

---

## 1.6 The COST GATE — v2, and the most consequential addition

Everything above is about whether the *trade* is good. This gate asks whether the
*execution* can be good enough for the trade to matter.

### Why this is not optional on this instrument

Bank Nifty weekly options were discontinued on **20 November 2024**. Only **monthly**
contracts exist, expiring the **last Tuesday** of the month. A monthly ATM premium is
3–4× a weekly's, and the spread scales with it.

Working from the design's own numbers — R = 25 index points, ATM delta 0.5:

```
R in premium points ........................... 12.5

round-trip slippage, spec's own assumption ....  5.5 prem pts  =  44% of R
round-trip slippage, realistic monthly ATM ....  8.0 prem pts  =  64% of R
round-trip slippage, fast/wide market ......... 13.0 prem pts  = 104% of R
```

Feeding that into the T1-at-1.5R-plus-runner exit scheme:

| cost | avg win | avg loss | break-even win rate |
|---|---|---|---|
| 0.10R | +1.90R | −1.10R | **36.7%** |
| 0.30R | +1.70R | −1.30R | **43.3%** |
| 0.50R | +1.50R | −1.50R | **50.0%** |

This style of setup realistically wins 35–45%. At 0.50R of cost the system is at or
below break-even *before a single bad read*. Cost is therefore not a reporting line —
it is the dominant term in the expectancy equation, and it varies trade by trade with
the live spread. So it must be a gate, checked against the actual quote.

### The gate

```python
r_premium   = r_points * ref_delta
spread      = quote.ask - quote.bid                        # observed, not modelled
cost_prem   = spread + slip.entry + slip.exit + slip.stop_gap_extra
charges_r   = estimated_charges(lots) / (r_premium * lot_size * lots)

if (cost_prem / r_premium) > params.risk.max_cost_as_fraction_of_r:   # 0.25
    return Rejection("cost_excessive", ...)
if r_premium < params.risk.min_r_premium_to_spread_ratio * spread:    # 8.0
    return Rejection("cost_excessive", ...)
```

Both conditions are checked. The first is the economically meaningful one; the second
is a fast sanity check that catches a blown-out spread even if the slippage model is
stale.

**Expect this gate to reject often, and expect it to reject small-R trades hardest.**
That is correct: cost is fixed per round trip, so it shrinks as a share of R only when
R grows. This gate is the mechanical form of the design's own conclusion in
`mythinking.md` §9 — *"kam aur badi trade, zyada aur chhoti se behtar hai"* — fewer,
larger trades beat more, smaller ones, because cost per trade is fixed while mistakes
multiply with frequency.

**Do not tune this gate down to get more trades.** If it rejects nearly everything, the
honest readings in order of likelihood are: (1) R is too small for this vehicle, take
setups with more room; (2) the spread genuinely is that bad and monthly ATM options are
the wrong vehicle for a 25-point stop; (3) the slippage model is stale — go measure it.

### The escape hatch you should know exists, and its price

If measured costs land above ~0.35R persistently, the vehicle is the problem, not the
strategy. Bank Nifty **futures** cost roughly 3 index points round trip on the same
trade — about **12% of R** — because there is no delta divisor and the spread is 1–2
points, and the index stop can then rest as a real SL-M order at the broker, which
resolves the L2/L3 problem in §2 entirely. The price is margin (~₹2 lakh per lot versus
~₹60k–1.5L of premium outlay) and an uncapped gap loss.

This is not a recommendation to switch — it is the number to compare against when P8.5
reports the measured spread. Make that decision on data, not now.

## 1.4 Targets

```python
t1_index = nearer_of(
    entry ± params.risk.t1_r_multiple * r_points,   # 1.5  HYPOTHESIS
    opposite_side_of_active_range,
    nearest_grade_B_or_better_obstacle,
)

t2_index = nearest_HTF_zone_beyond_t1                # the runner's destination
```

T1 books **50%** and moves the stop on the remainder to breakeven, in the same event,
not on the next candle.

Rationale for `1.5R` rather than "the immediate minor swing high": on 1m the immediate
swing is often only 12–18 points, which books half the position below 1R. After costs
that half-trade is close to a scratch, and it caps the winner that has to pay for
every loser.

## 1.5 Position sizing — the only correct direction of causation

```python
risk_budget = params.session.risk_per_trade_rupees      # must be set explicitly

# index points → option premium points
premium_risk_per_lot = r_points * ref_delta * lot_size

lots = floor(risk_budget / premium_risk_per_lot)

if lots < 1:
    return Rejection("size_zero", ...)
```

- `ref_delta` comes from the options layer (spec 08). ATM ≈ 0.5, but it is **measured,
  not assumed**.
- If `lots == 0`, the answer is no trade. It is never "take one lot anyway."
- **Never solve this equation for `r_points`.** Sizing consumes the stop; it never
  produces it. A reviewer should reject any code where `r_points` appears on the left
  of an assignment after this point.

### Expiry-day size reduction
```yaml
risk:
  expiry_size_multiplier: 0.5     # HYPOTHESIS
```
Premium decay and pin behaviour make expiry-day outcomes fatter-tailed in both
directions. Halve the size; do not widen the stop to compensate.

---

# PART 2 — EXIT ENGINE

Evaluated **in this order** — the first match wins.

```
1. invalidation      (thesis broken)          ── on 1m close
2. index SL          (index touched sl_index) ── ON TICKS, not on close   ← v2
3. T1                (first 50%)              ── on ticks
4. trail             (after T1)               ── on 5m close
5. time stop                                  ── on 5m close
6. force flat 15:15                           ── on clock
```

## 2.0 — v2: the stop architecture, stated honestly

CLAUDE.md v1 §6 said *"Hard SL — always resting in the system. Never mental."*
**That was not implementable and the document should not have claimed it.** The stop is
an **index** level. The position is an **option**. No broker accepts an index-triggered
stop on an option leg. v1's hard SL was a software stop that dies with the process,
described as though it were resting at the exchange — the most dangerous kind of
documentation error, because it stops you from building the thing that was missing.

Three layers, and never confuse them:

| Layer | What | Where it lives | Fires |
|---|---|---|---|
| **L1** | Thesis invalidation | software, 1m close | often — this is the money-saver |
| **L2** | Index stop at `sl_index` | software, **tick-evaluated** | sometimes |
| **L3** | Premium backstop SL-M | **resting at the broker** | ~never; if it does, investigate |

### L2 must be evaluated on ticks, not on candle closes

v1 ran the entire exit engine on closed 1m candles. On a 25-point R that hands the
market up to 59 seconds of free adverse movement — frequently most of the R, and by
construction it is worst exactly when price is moving fastest against you.

**This does not violate the no-look-ahead rule.** CLAUDE.md §3 governs *detection and
signal generation* — the engine must not see a forming candle when deciding to enter.
Exiting an open position is a different operation: there is no future information
involved, only latency. Keep the tick path in `exits/`, and keep it out of `on_candle`.

In paper and replay, model L2 as: if `candle.low <= sl_index` (long), fill at
`sl_index` **minus** adverse slippage **plus** `stop_gap_extra`. Never at `sl_index`
exactly. A paper engine that fills stops perfectly overstates results by precisely the
amount that decides whether the system is viable.

### L3 — the backstop that actually rests at the broker

```yaml
exits:
  premium_backstop_enabled: true
  premium_backstop_r_multiple: 2.0
```

Immediately after the entry fill, place a real SL-M on the option leg at
`entry_premium − 2.0 × R_premium` (for a long option). Then:

- If L1 or L2 exits normally → **cancel L3 in the same event.** An orphaned backstop
  order is its own hazard.
- If the process dies, the machine loses power, or the websocket never comes back →
  L3 is the only thing standing between you and an unmanaged position.
- L3 filling is an **incident**, not a normal loss. It means all software protection
  failed. Journal it with a distinct exit reason and review it.

L3 is deliberately far away. It is not a wider stop — it is a different instrument
serving a different purpose. Placing it close would let premium noise (an IV crush with
the index thesis intact) exit a good trade, which is precisely the failure mode spec 08
Part 1 exists to prevent.

### The heartbeat watchdog

```yaml
exits:
  heartbeat_timeout_seconds: 90
```

A **separate process**. The engine writes a heartbeat every candle. If the watchdog
sees no heartbeat for 90 seconds during market hours, it flattens any open position
through the broker and alerts. In the paper phase it only alerts — but build it now,
because the habit and the plumbing are what matter, and the phase after this one places
real orders.

A trading process that can die holding a position, with nothing resting at the broker
and nothing watching it, is the largest uncontrolled risk in the entire design. It is
larger than any entry-rule question in specs 03–06.

## 2.1 Invalidation — the most important exit

```python
# long
if candle.body_bottom < trigger_level.body_edge - hold_tolerance:
    exit_market(reason="invalidation")
```

A **body close** back on the wrong side of the trigger level means the reason for the
trade no longer exists. Exit immediately at market, even if the hard SL is 15 points
further away.

This exit fires **before** the hard SL is reached, by design. It converts a full-R loss
into a partial-R loss on the trades where the read was wrong but the noise had not yet
reached the stop. Over a sample this matters more than any entry refinement.

It also fires on winners that stop working. That is correct and not a bug.

## 2.2 Index SL (L2)

Evaluated on **ticks** from the moment of fill — see §2.0 for why close-only evaluation
gives away most of a 25-point R. In paper, model it as: if `candle.low <= sl_index`
(long), the stop filled at `sl_index` **minus modelled adverse slippage minus
`stop_gap_extra`** — never assume a perfect fill at the stop price.

Never widened. Never cancelled. Never "temporarily disabled." There is no config flag
for this and there must not be one.

Backed at all times by the L3 premium backstop resting at the broker (§2.0). L2 is the
trading stop; L3 is the disaster stop. Both exist because neither alone is sufficient:
L2 cannot survive a dead process, and L3 cannot express an index-based thesis.

## 2.3 T1 and breakeven

```python
if long and candle.high >= t1_index:
    book(50%)
    position.sl_index = entry_index          # breakeven, unconditional
    position.t1_done = True
```

Breakeven is set in the same event as the T1 fill. There is no "let it breathe a bit
longer" branch.

## 2.4 Trail (remainder only, after T1)

```
Trail below each new confirmed 5m higher-low (long) / above each 5m lower-high (short).
```

**5m, not 1m.** Trailing on 1m exits nearly every runner during normal pullbacks — it
converts the trade that is supposed to pay for the losers into another scratch. This is
the most commonly self-inflicted damage in this style of system.

## 2.5 Time stop

```yaml
exits:
  time_stop_candles: 5           # 5m candles, HYPOTHESIS
  progress_threshold_r: 0.3
```

```python
if candles_since_entry_5m >= 5 and max_favourable_r < 0.3:
    exit_market(reason="time_stop")
```

A trade that has not moved is already a losing trade — it simply has not appeared in
the P&L yet. It is consuming a session slot, attention, and the option's time value.
Release it.

## 2.6 Force flat

At `15:15` any open position exits at market, reason `eod`. Unconditional.

---

## 3. Worked example (index points)

```
Setup B long at a Grade A support, ATR14_1m = 22

sweep wick low     57,103
sl_buffer          v2: max(6, 0.45 × 22) = 9.9        (v1 would give a flat 10)
sl_index           57,093.1
reclaim close      57,118   ← entry

r_points           24.9
  r_min            max(12, 0.55 × 22) = 12.1          ✓
  r_max            min(60, max(35, 1.40 × 22)) = 35   ✓

obstacles above    57,190 (round-100  → WEAK, does not gate)
                   57,240 (PDH        → STRONG, gates)
                   57,310 (15m supply → STRONG)
space obstacle     57,240                             ← v1 would have used 57,190
space_points       122
space_ratio        122 / 24.9 = 4.90                  ✓ >= 2.5
  (v1: 72 / 25 = 2.88 — also passed here, but see spec 03 §6 for how often
   the weak-obstacle rule turned a good trade into space_insufficient)

t1  = min(57,118 + 1.5×24.9 = 57,155.4 , range top 57,168, round-100 57,190)
    → 57,155.4          ← weak obstacles still cap T1, and should
t2  = 57,240 (PDH)

── v2 COST GATE ────────────────────────────────────────────────
ref_delta          0.52 (measured, not assumed)
r_premium          24.9 × 0.52 = 12.9 premium points
observed spread    1.4 premium points        ← from the live quote, not modelled
cost_prem          1.4 + 2.0 + 2.0 + 1.5 = 6.9
  cost / r_premium = 6.9 / 12.9 = 0.535  >  0.25   ✗  REJECT — cost_excessive
  r_premium / spread = 12.9 / 1.4 = 9.2  >  8.0    ✓

VERDICT: Rejection("cost_excessive")
```

**Read that last block carefully — the textbook trade from v1's own worked example
does not survive the cost gate.** Every structural gate passed. It failed on execution
economics: 53% of R goes to crossing the spread twice plus the stop gap, which puts the
break-even win rate above 50%.

This is the single most important thing the v2 review surfaced. It is not an argument
that the strategy is wrong — the level read may be excellent. It is that **a 25-point
index stop is too small a target to pay for a monthly ATM option round trip.** The two
honest responses are to take setups with materially more room (larger R, same risk
budget, fewer trades), or to change the vehicle. Both are decisions for P8.5, on
measured spreads rather than the guessed numbers above.

For completeness, sizing if the gate had passed (lot size **30**, not v1's 15 —
Bank Nifty's lot size changed to 30 from the January 2026 series; verify against the
instrument master at startup regardless):

```
premium_risk_per_lot = 24.9 × 0.52 × 30 = ₹388
lots = floor(5000 / 388) = 12 lots
premium outlay at ₹900 ATM monthly = 12 × 30 × 900 = ₹324,000
```

Note the last line. To risk ₹5,000 you deploy roughly ₹3.2 lakh of premium. That ratio
is a property of buying options and it must be logged on every trade
(`options.log_capital_deployed`), because it determines whether the account can even
hold three concurrent-day positions and it never appears in an R-based P&L.

---

## 4. Tests that must pass

| Test | Expectation |
|---|---|
| `test_sl_buffer_scales_with_atr` | **v2:** ATR 25 → buffer 11.25, not 10. The ATR term must bind in the NORMAL range, not only above ATR 40 |
| `test_r_max_scales_with_atr` | ATR 40 → r_max 56; ATR 15 → r_max 35; ATR 60 → r_max 60 (absolute cap) |
| `test_setup_b_large_sweep_accepted` | 45-pt sweep candle at ATR 35 → R ≈ 41, **accepted** (v1 rejected it) |
| `test_r_absolute_cap_holds` | ATR 80 → r_max 60, not 112 |
| `test_cost_gate_rejects_wide_spread` | Spread 3.0 prem pts, r_premium 12 → `cost_excessive` |
| `test_cost_gate_uses_observed_not_modelled_spread` | Modelled spread 1.0, quoted 4.0 → gate uses 4.0 |
| `test_cost_gate_both_conditions` | Each condition failing alone → `cost_excessive` |
| `test_cost_gate_favours_larger_r` | Same spread, R doubled → gate passes |
| `test_worked_example_v1_now_rejected` | Spec §3 worked example → `cost_excessive`, not a Signal |
| `test_space_ignores_weak_obstacles` | Round-100 at 30 pts, PDH at 122 pts, R=25 → space 122, passes |
| `test_t1_still_respects_weak_obstacles` | 1.5R target beyond a round-100 → T1 pulled back |
| `test_stop_evaluated_on_ticks` | Tick through `sl_index` mid-candle → exit at that tick, not at candle close |
| `test_backstop_placed_after_fill` | Entry fill → SL-M resting at `2.0 × R_premium` beyond entry |
| `test_backstop_cancelled_on_normal_exit` | L1 invalidation exit → backstop cancelled in the same event |
| `test_backstop_fill_is_flagged_incident` | L3 fill → distinct exit reason, alert raised |
| `test_watchdog_flattens_on_dead_heartbeat` | No heartbeat 91s with a position open → flatten + alert |
| `test_capital_deployed_logged` | Every trade row carries premium outlay |
| `test_sl_never_at_level` | `sl_index` always beyond `extreme`, never equal to `body_edge` |
| `test_r_too_tight_rejected` | R = 9 → `r_too_tight` |
| `test_r_too_wide_rejected` | R = 40 → `r_too_wide` |
| `test_no_path_adjusts_sl_to_fit_r` | Static check: `sl_index` never reassigned after computation |
| `test_space_uses_nearest_obstacle` | HTF zone 200 pts away, round number 30 pts away → space = 30 → rejected |
| `test_space_includes_grade_c` | A Grade C level nearer than the target still counts as an obstacle |
| `test_t1_prefers_nearer` | 1.5R beyond range top → T1 = range top |
| `test_size_zero_rejects` | Budget too small for one lot → `size_zero` |
| `test_sizing_never_alters_r` | R identical before and after sizing |
| `test_expiry_halves_size` | Expiry flag → lots halved |
| `test_invalidation_before_hard_sl` | Body close through level with SL 15 pts away → exit reason `invalidation` |
| `test_invalidation_on_winner` | Winner that closes back through level → exits, no special case |
| `test_t1_sets_breakeven_same_event` | After T1 fill, `sl_index == entry_index` immediately |
| `test_trail_uses_5m_not_1m` | 1m pullback below a 1m swing does not trail the stop |
| `test_time_stop_fires` | 5 flat 5m candles, max 0.2R → `time_stop` |
| `test_force_flat_1515` | Position open at 15:15 → exit `eod` |
| `test_no_sl_disable_flag_exists` | Static check: no config key matching `disable.*sl` |
| `test_stop_fill_includes_slippage` | Paper stop fill is worse than `sl_index`, never equal |
