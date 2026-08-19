# 06 — SETUPS

Three setups. Not four. Every additional setup increases trade frequency, and trade
frequency is the dominant cost and error multiplier in this system.

**Universal preconditions** (checked by `setups/base.py` before any detector runs):

```
mode == ALERT
trigger level.grade == A
level.alive and level.touches < max_touches
no duplicate attempt at this level this session
not within cooldown
all candles involved: synthetic == False
```

If any fail → `no_live_level` / `duplicate_setup` / `no_setup`.

---

## Setup A — FLIP RETEST

*Highest frequency, smallest stop, trades with the trend. The bread and butter.*

### The shape
A level breaks by body close. Price returns to it. The level holds as the opposite
type. Entry on the first sign the pullback is over.

### Conditions — long (mirror for short)

```
A1. A BREAK axis exists (spec 03 §5), created within axis_ttl_minutes (120)
A2. The break was UPWARD: a body closed above the old resistance
A3. Price has returned to within retest_tolerance of axis.body_edge
        retest_tolerance = max(8 pts, 0.5 × ATR14_1m)          # HYPOTHESIS
A4. The axis HELD: no 1m body has closed below axis.body_edge − hold_tolerance
        hold_tolerance = max(5 pts, 0.3 × ATR14_1m)            # HYPOTHESIS
A5. A 1m HIGHER LOW has formed during the retest
        (low[i] > low[i-n], where low[i-n] is the pullback's lowest 1m low)
A6. TRIGGER: the current 1m candle closes ABOVE the previous 1m candle's high
A7. Trigger candle close_third == "top"
A8. Bias filter passes (spec 05 §5)
```

### Geometry
```
entry_ref = trigger_candle.close
extreme   = the 1m higher-low  (the LOW of the higher-low candle)
```

**Why this stop is small:** it hides behind a 1m swing that just proved itself, not
behind the 5m candle's low. That is the entire advantage of the drill-down — the same
trade with roughly half the risk.

### Rejections specific to A
| Condition | Gate |
|---|---|
| Body closed back through the axis before the higher-low | `setup_stale` (axis is dead — the flip failed) |
| More than `retest_max_candles` (default 20) since the break | `setup_stale` |
| Counter to 5m trend at a non-A level | `bias_conflict` |

---

## Setup B — SWEEP RECLAIM

*Best risk-reward, lowest frequency. Preferred (and mandatory) at ANCHOR levels.*

### The shape
Price pierces a level with a wick, fails to hold outside, and closes its body back
inside. The stops beyond the level have been cleared, so the path back is clean.

### Conditions — long at a support level (mirror for short)

```
B1. Trigger level is Grade A
B2. SWEEP candle: a 1m candle whose LOW pierces level.wick_tip by
        >= sweep_min_pierce = max(8 pts, 0.4 × ATR14_1m)        # HYPOTHESIS
B3. That candle's LOWER WICK >= sweep_wick_ratio × candle.range
        sweep_wick_ratio = 0.55                                 # HYPOTHESIS
B4. That candle's BODY closes back above level.body_edge
        — OR the next candle does, within reclaim_max_candles = 2
B5. RECLAIM: body close >= reclaim_min_points above level.body_edge
        reclaim_min_points = max(5 pts, 0.25 × ATR14_1m)        # HYPOTHESIS
B6. Reclaim candle close_third == "top"
B7. Candles between sweep and reclaim <= 2. Candle 3+ → `setup_stale`.
```

### Geometry
```
entry_ref = reclaim_candle.close
extreme   = the sweep candle's LOW (the wick tip of the sweep)
```

### ⚠ v2 — this geometry is what v1's flat R ceiling was deleting

The conditions above **force** a wide stop. B3 requires the wick to be ≥55% of the
candle's range, and B6 requires the close in the top third. So:

```
R  =  entry − SL  =  (≈0.70 × candle_range)  +  sl_buffer
```

Under v1 (`sl_buffer` a flat 10, `r_max` a flat 35), a 40-point sweep candle produced
R = 38 → `r_too_wide`. A 50-point one produced R = 45 → rejected. On Bank Nifty in an
active window, 40–50 point 1m candles are **what a real liquidity sweep at a defended
level looks like.**

So v1 did not filter out bad Setup B trades. It filtered out the strongest ones and
kept only the timid sweeps — and because the ceiling was a flat number, it did this
*more* on high-volatility days, when sweeps carry the most information. Setup B is
described here as "best risk-reward, lowest frequency"; v1's risk engine made it
lowest-frequency for a reason unrelated to the market.

Fixed in spec 07 §1.2: `r_max = min(60, max(35, 1.40 × ATR14_1m))`. Both the old and
new ceilings are logged on every decision so spec 09's counterfactual study can measure
whether this was the right call rather than anyone assuming it.

**Do not "fix" this by moving the stop closer than the sweep wick tip.** The wick tip is
the whole point of the setup — it is where the stops were, and inside it you are parked
exactly where price is drawn to. If the resulting R does not fit, the correct answer
remains no trade.

### ⚠ v2.2 — the ATR-relative ceiling was still not enough. Measured, not reasoned.

The dry run put a genuine textbook sweep through the full engine
(`prototype/FINDINGS.md`, Bug 4):

```
09:58  B_sweep_reclaim at PDL 57,455  →  REJECT: r_too_wide
       R = 69.1        allowed 16.0 – 40.7   (ATR 29)

  sweep low      57,434
  reclaim close  57,490   ← entry
                    56 pts apart
  + sl_buffer    13
  = R            69
```

v2 replaced v1's flat 35 with `max(35, 1.40 × ATR)` = 40.7 here. **The real trade still
came in at 69.** The sweep wick ran 30 points below the level and the reclaim candle
printed a 26-point body — both of which are *signs of a good sweep* — and together they
put entry 56 points from the stop.

So this is not a threshold that needs another nudge. **It is a genuine tension in the
setup's own geometry:** entry at the reclaim close, stop beyond the sweep wick, means
the better the sweep, the worse the R.

### Three honest options. Pick one deliberately; do not let it be decided by accident.

```yaml
setups:
  b_entry_mode: "pullback"          # "reclaim_close" | "pullback" | "skip_wide"
  b_entry_max_extreme_atr_mult: 1.2 # entry must be within this × ATR of the extreme
  b_pullback_wait_candles: 3        # how long to wait for the pullback
```

**1. `reclaim_close`** — v1/v2 behaviour. Enter at the reclaim close, accept the wide R.
With the cost gate this is actually *fine* on cost grounds (a large R makes the fixed
round-trip cost a small fraction of R). The problem is purely that R exceeds the ceiling
and the position size shrinks accordingly. Raising `r_absolute_max_points` would allow
it — but a 69-point stop on a 25-point-typical system is a different strategy, not a
tuning change.

**2. `pullback` — the recommended default.** After a valid reclaim, place a limit entry
within `b_entry_max_extreme_atr_mult × ATR` of the sweep extreme and wait up to
`b_pullback_wait_candles`. In the example above that is an entry near 57,469 instead of
57,490, giving R ≈ 48 — still wide, but inside a 40–56 ceiling on an active day. If the
pullback does not come, **the trade is missed, and that is an acceptable cost.** This is
also what a trader actually does: `mythinking.md` §7 says *"hamesha retest par, breakout
par nahi"* — always on the retest. v1 applied that discipline to Setups A and C and
forgot it for B.

**3. `skip_wide`** — reject anything over the ceiling. Simplest, and it means Setup B
fires very rarely.

**Whichever is chosen, log what the other two would have done.** Every Setup B decision
should carry `entry_reclaim_close`, `entry_pullback`, and whether the pullback arrived
within the wait window. After a few months the counterfactual study answers this with
data instead of argument — which is the only way a question like this should be settled.

### Why a plain rejection is not allowed at ANCHOR levels
The most-watched levels hold the most stops, so they are swept most often. Taking a
rejection at PDH/PDL/day-high without a sweep means being on the wrong side of the
stop hunt. At `kind == ANCHOR`, **Setup B is the only permitted setup.** Enforce in
`setups/base.py`, not by convention.

### Distinguishing a sweep from a real breakout
| | Sweep | Real breakout |
|---|---|---|
| Wick through level | ≥ 8 pts | may be small |
| Body close | **back inside** | **outside** |
| Wick share of range | ≥ 55% | typically < 40% |
| Next candle | returns inside | continues outside |

If B2/B3 pass but the body closes **outside**, this is a breakout, not a sweep.
Do not relabel it. It may become a Setup A or C later, once it retests.

---

## Setup C — RANGE BREAK RETEST

*Lowest frequency. Only after a long, tightening range. Never on the breakout candle.*

### Range definition (also used by the regime engine)

A range is valid only if **all** hold:

```
R1. Formed over >= range_min_candles = 20 (1m)                   # HYPOTHESIS
R2. >= 2 touches at the top AND >= 2 at the bottom
        touch = wick within range_touch_tolerance (5 pts) of the boundary
R3. Width between range_min_width (25) and range_max_width (120) points
R4. No 1m BODY closed outside the range during its formation
```

If these do not hold, **there is no range**, and Setup C cannot exist. The engine must
say so rather than approximating.

### Conditions — long (mirror for short)

```
C1. A valid range exists per R1–R4
C2. Compression: the range's last third is narrower than its first third
        last_third_width <= compression_ratio × first_third_width
        compression_ratio = 0.7                                  # HYPOTHESIS
C3. BREAKOUT: a 1m body closes above range.high
C4. ACCEPTANCE: >= acceptance_candles (2) subsequent 1m bodies close above range.high
        — if price returns inside before this, it is a FAILED BREAKOUT, see below
C5. RETEST: price returns to within retest_tolerance of range.high
C6. TRIGGER: same as A6 — 1m close above previous 1m high, after a higher low
```

**C3 alone is never an entry.** Entry is only at C6, on the retest. Enforce by having
the detector return nothing at C3/C4; there must be no code path from breakout to order.

### Geometry
```
entry_ref = trigger_candle.close
extreme   = the retest low (the 1m higher-low)
```

### Move-size expectation (informational, feeds targets not entries)
```
measured_move = range.width
range_fuel    = range.candle_count / range_min_candles     # >1.0 = longer base
```
Longer and tighter ranges precede larger moves — time in the range is the fuel. This
adjusts **T2 preference only**, never the entry decision, and never overrides the
nearest-obstacle rule.

### Failed breakout — the mirror trade
If C3 occurs and price closes a body **back inside** the range within
`acceptance_candles`, the breakout has failed. This is a **Setup B candidate in the
opposite direction**, with `range.high` as the swept level. Route it through the normal
Setup B detector — do not create a fourth setup for it.

---

## 5. What is explicitly NOT a setup

Hard-code these as non-signals so nobody adds them later:

- ❌ Entry on the breakout candle itself (any setup)
- ❌ Reversal at a level without a sweep, when the level is an ANCHOR
- ❌ Reversal at a level with `touches >= 3`
- ❌ Any entry when `mode != ALERT`
- ❌ Any entry in open space (no level within `alert_distance`)
- ❌ Momentum / continuation entries with no level reference
- ❌ Entry against a live position ("reverse and flip")

---

## 6. Setup output

```python
def detect(board, levels, structure, candles) -> SetupCandidate | Rejection:
```

Every detector must populate `evidence` with **every intermediate value it computed**,
even on rejection:

```python
evidence = {
    "level_id": ..., "level_grade": "A", "level_touches": 1,
    "pierce_points": 11.5, "wick_ratio": 0.62,
    "reclaim_points": 7.0, "candles_since_sweep": 1,
    "higher_low": 57106.0, "trigger_close": 57118.0,
    "pullback_ratio": 0.48, "trend_5m": "up",
}
```

This is what makes the rejection log worth keeping. After a month, grouping rejections
by gate tells you which thresholds are doing real work and which are just blocking
trades that would have won.

---

## 7. Tests that must pass

| Test | Expectation |
|---|---|
| `test_A_fires_on_golden` | Hand-built flip-retest fixture → candidate with correct extreme |
| `test_A_no_entry_on_break_candle` | Breakout candle alone → no candidate |
| `test_A_requires_higher_low` | Retest without a 1m higher-low → `no_setup` |
| `test_A_stale_after_20_candles` | Retest at candle 21 → `setup_stale` |
| `test_A_dead_if_axis_reclaimed` | Body back through axis → `setup_stale` |
| `test_B_needs_8pt_pierce` | 6-pt pierce → `no_setup` |
| `test_B_needs_55pct_wick` | 50% wick → `no_setup` |
| `test_B_body_outside_is_breakout` | Wick + body close outside → **no** Setup B |
| `test_B_reclaim_within_2_candles` | Reclaim on candle 3 → `setup_stale` |
| `test_B_mandatory_at_anchor` | Rejection attempt at PDH without sweep → `no_setup` |
| `test_C_requires_20_candles` | 14-candle range → no range, `no_setup` |
| `test_C_requires_compression` | Range widening into the break → `no_setup` |
| `test_C_never_on_breakout_candle` | Assert no code path from C3 to Signal |
| `test_C_failed_breakout_routes_to_B` | Break then close back inside → Setup B opposite direction |
| `test_evidence_populated_on_rejection` | Every rejection carries a non-empty `evidence` dict |
| `test_only_three_setups_registered` | Registry length == 3 |
