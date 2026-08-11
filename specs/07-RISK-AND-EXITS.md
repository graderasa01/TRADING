# 07 — RISK ENGINE & EXIT ENGINE

> Everything in this file is computed in **index points**, then translated to option
> premium only at the broker boundary. Stops and targets live on the index.

---

# PART 1 — RISK ENGINE

## 1.1 Stop loss placement

```python
sl_buffer = max(
    params.risk.sl_buffer_min_points,          # 10   HYPOTHESIS
    params.risk.sl_buffer_atr_mult * atr_1m,   # 0.25 HYPOTHESIS
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

## 1.2 R bounds — hard rejections

```python
r_points = abs(entry_index - sl_index)

if r_points < params.risk.r_min_points:   # 12   HYPOTHESIS
    return Rejection("r_too_tight", ...)
if r_points > params.risk.r_max_points:   # 35   HYPOTHESIS
    return Rejection("r_too_wide", ...)
```

- **Too tight** — the stop is inside the noise band. It will be hit by random movement
  regardless of whether the read was correct.
- **Too wide** — usually caused by a large trigger candle. The reward needed to justify
  it will not fit inside the available space. Skipping is the correct answer; widening
  the target to make the ratio work is the classic self-deception.

**There is no path that adjusts the stop to satisfy these bounds.** The stop is
determined by structure. If the resulting R is out of bounds, the trade does not exist.

## 1.3 Space check

```python
obstacles = levels.obstacles_above(entry) if long else levels.obstacles_below(entry)
nearest   = obstacles[0]                       # ALL obstacle types, any grade
space_points = abs(nearest.body_edge - entry_index)
space_ratio  = space_points / r_points

if space_ratio < params.risk.min_space_ratio:  # 2.5  HYPOTHESIS
    return Rejection("space_insufficient", ...)
```

The obstacle list includes Grade B and C levels, round numbers, PDH/PDL, day extremes
and the far side of an active range — see spec 03 §9. **The nearest wins, always.**

This is the gate that fails most often, and that is the intended behaviour. A correct
entry into a wall 30 points away is a losing trade with a good-looking chart.

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

Runs on every closed 1m candle while `mode == IN`. Evaluated **in this order** — the
first match wins.

```
1. invalidation      (thesis broken)
2. hard SL           (index touched sl_index)
3. T1                (first 50%)
4. trail             (after T1)
5. time stop
6. force flat 15:15
```

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

## 2.2 Hard SL

Always resting in the system from the moment of fill. In paper, model it as: if
`candle.low <= sl_index` (long), the stop filled at `sl_index` **minus modelled adverse
slippage** — never assume a perfect fill at the stop price.

Never widened. Never cancelled. Never "temporarily disabled." There is no config flag
for this and there must not be one.

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
sl_buffer          max(10, 0.25 × 22) = 10
sl_index           57,093
reclaim close      57,118   ← entry
r_points           25                        ✓ within [12, 35]

obstacles above    57,190 (round-100), 57,240 (PDH), 57,310 (15m supply)
nearest obstacle   57,190
space_points       72
space_ratio        72 / 25 = 2.88            ✓ >= 2.5

t1  = min(57,118 + 1.5×25 = 57,155.5 ,  range top 57,168)  → 57,155.5
t2  = 57,240 (PDH)

sizing: risk_budget ₹5,000, ref_delta 0.52, lot_size 15
  premium_risk_per_lot = 25 × 0.52 × 15 = ₹195
  lots = floor(5000 / 195) = 25 lots
```

Note the sizing output is large because the per-lot risk is small — this is exactly why
`risk_per_trade_rupees` must be set consciously and why the option layer's liquidity
check (spec 08) matters.

---

## 4. Tests that must pass

| Test | Expectation |
|---|---|
| `test_sl_buffer_scales_with_atr` | ATR 60 → buffer 15, not 10 |
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
