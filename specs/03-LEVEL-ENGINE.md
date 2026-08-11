# 03 — LEVEL ENGINE

> A level is not a line. A level is a **record of where an order imbalance happened.**
> There are exactly four ways one comes into existence. If a line cannot be traced to
> one of them, it does not go on the chart.

---

## 1. The four births

| Kind | What happened | Detection source |
|---|---|---|
| **TURN** | Price arrived, stopped, reversed | swing pivot, or ≥2 wicks at same price |
| **LAUNCH** | Price sat quietly, then left fast | the base preceding an impulse candle |
| **BREAK** | A level was broken by body close | the break point itself |
| **ANCHOR** | Given from outside | PDH/PDL/PDC, opening range, round numbers |

---

## 2. TURN levels

### 2a. Swing pivot
On the given tf, candle `i` is a swing high if:
```
h[i] > h[i-k] … h[i-1]   AND   h[i] > h[i+1] … h[i+k]
```
`k = params.levels.swing_lookback_bars_1m` (**3**) or `..._5m` (**2**) — HYPOTHESIS.

- A swing is **not confirmed** until `k` candles have closed to its right.
  Emitting an unconfirmed swing is a look-ahead bug. Confirmed-only, always.
- `body_edge` = body extreme of the pivot candle (`body_top` for a high).
- `wick_tip` = `h` (for a high) / `l` (for a low).

### 2b. Wick cluster
≥ `params.levels.wick_cluster_min_touches` (**2**) wicks whose tips fall within
`wick_cluster_tolerance_points` (**5** — HYPOTHESIS) of each other, inside a window of
`wick_cluster_window_candles` (**30** 1m candles).

- `wick_tip` = extreme of the cluster
- `body_edge` = the mean of the body extremes of the clustered candles

---

## 3. LAUNCH levels — the highest-value 1m level

This is the level that is **invisible on 5m** because it lives inside a 5m candle's
body. It is the origin of an impulse: someone built a position there, then price left.
When price returns, they defend it.

### Detection
Candle `i` on **1m** is an **impulse candle** if:
```
range[i] >= params.levels.launch_impulse_atr_mult × ATR20_1m     # default 2.0 (HYPOTHESIS)
AND close_position is "top" (bullish impulse) or "bottom" (bearish impulse)
AND not candle.synthetic
```

Its **base** is the preceding `n` candles where `n ∈ [2, 4]`, chosen as the largest `n`
satisfying:
```
combined_range(i-n … i-1) <= params.levels.launch_base_atr_mult × ATR20_1m   # default 0.8
```
If no `n` in `[2,4]` satisfies this, **no LAUNCH level is created** — price did not sit,
it just kept moving. This is the correct outcome; do not relax it.

### Geometry
For a bullish impulse (LAUNCH support):
- `body_edge` = highest body-bottom in the base (the top of where they accumulated)
- `wick_tip`  = lowest low in the base

Mirror for a bearish impulse.

### The speed requirement
```
departure_speed = (price 3 candles after impulse − impulse close) ÷ ATR20_1m
```
A LAUNCH level is only valid if `departure_speed >= params.levels.min_departure_speed`
(default **1.0** — HYPOTHESIS). **Price must have run away from it.** A base that
price drifted slowly away from is not a launch, it is just quiet trading.

### Lifespan
LAUNCH levels born on 1m expire after `params.levels.micro_level_ttl_minutes`
(default **90** — HYPOTHESIS) unless they are also confirmed on 5m/15m. The positions
that created them are closed out by then; the line survives on the chart but the
reason for it does not.

---

## 4. Level geometry — the three parts

```
        ┌──── wick_tip      ← the extreme. Stops are parked here. SL goes BEYOND this.
        │
        │     ~ pocket ~    ← the sweep pocket. Wider pocket = more stops = better trap.
        │
        └──── body_edge     ← the REAL level. Decisions were made here. ENTRY reference.
```

Consequences, enforced in code:
- **Entry never at `wick_tip`.** Entry is referenced to `body_edge`.
- **SL never at `body_edge` or on the line.** SL goes beyond `wick_tip` plus a buffer.
- A "touch" for the touch counter means price entered `[zone_low, zone_high]`, not that
  it crossed a single price.

---

## 5. BREAK levels — the axis

When a live level is broken by a **body close** beyond it (any tf), do three things:

1. Mark the broken level `alive = False`, `death_reason = "broken"`.
2. Create a new `Level(kind=BREAK, side=AXIS)` at the break point:
   - `body_edge` = the broken level's `body_edge`
   - `wick_tip`  = the extreme of the breaking candle's wick on the far side
3. Set `board.axis = this level`.

**The BREAK level is the most important line for the next `params.levels.axis_ttl_minutes`
(default 120 — HYPOTHESIS).** It is simultaneously:
- the S/R flip (where Setup A trades from)
- the invalidation line (body close back through it = the move failed)

After a break, the **other side of the old range becomes irrelevant.** Drop its priority
to C immediately.

---

## 6. ANCHOR levels

Created once at session start (or at 09:30 for the opening range), never by detection:

| Anchor | Value | Notes |
|---|---|---|
| PDH / PDL / PDC | previous session | always Grade A while untested |
| Opening range H/L | 09:15–09:30 extremes | created at 09:30 |
| Round numbers | every 100 pts within ±1.5 × day range | 500/1000 multiples get grade bump |
| Day high / day low | rolling, updated live | always live, never killed |

Round numbers are `body_edge == wick_tip` (they have no pocket). Handle that
degenerate case — `pocket == 0` must not divide by zero anywhere.

---

## 7. GRADING

Score each live level 0–4, one point per criterion:

| Criterion | Point awarded when |
|---|---|
| **Untested** | `touches == 0` |
| **Fast departure** | `departure_speed >= min_departure_speed` |
| **HTF confirmed** | also detectable on 5m or 15m, or is an ANCHOR |
| **Clean formation** | either long time-at-price (≥10 candles) OR very fast departure (≥1.5× threshold) — **not the middle** |

```
score >= 3  → Grade A     tradeable. Setups may trigger here.
score == 2  → Grade B     targets and partial booking only.
score <= 1  → Grade C     context only. Never a trigger.
```

**Hard rule: a setup may only trigger at a Grade A level.** Grade B and C levels are
used for the space check and targets. This one restriction removes most bad trades.

**Visibility paradox — encode this:** the most-watched levels (PDH/PDL, day high/low,
round numbers) produce the strongest reactions *and* the most sweeps, because that is
where the stops are. Therefore at an ANCHOR level, **Setup B (sweep-reclaim) is
preferred and a plain reversal is forbidden.** Do not take a rejection trade at an
anchor without a sweep.

---

## 8. DEATH — pruning is as important as creation

Kill a level when **any** of:

| Condition | `death_reason` |
|---|---|
| `touches >= params.levels.max_touches` (default **3**) | `"exhausted"` |
| Price closed bodies beyond it for ≥ `acceptance_candles` (default **5** on 1m) | `"accepted_through"` |
| Age > TTL (90 min for 1m-born, 120 min for BREAK axis, none for ANCHOR) | `"expired"` |
| Distance from price > `params.levels.relevance_atr_mult × ATR20_1m` (default 25) | `"irrelevant"` |

Dead levels are retained in the journal (they explain past decisions) but removed from
the active book.

### The book cap
```
MAX_ACTIVE_LEVELS = 8
```
If more than 8 survive, keep by this priority and drop the rest to an inactive pool:
1. The 2 nearest above and 2 nearest below current price
2. The current BREAK axis
3. Day high, day low
4. Highest-grade remainder

Eight lines is not a stylistic preference. A level book that grows unbounded will
always find a level near price, which means the ALERT mode never turns off, which
means the system trades constantly. **The cap is a risk control.**

---

## 9. Obstacles — used by the space check

`obstacles_above(price)` / `obstacles_below(price)` return, sorted by distance, **all**
of the following regardless of grade:

- every live level (A, B and C)
- day high / day low
- PDH / PDL / PDC
- every round number (100s)
- the far side of the current range, if one is active
- any price rejected ≥2 times in the last 60 minutes

**The space check uses the NEAREST of these, never the intended target.** A 200-point
target with a wall at 30 points is a 30-point trade. This is the single most common way
a good entry becomes a losing trade.

---

## 10. Update order on each closed 1m candle

```
1. update day_high / day_low
2. age out expired levels
3. update touch counts for every live level intersected by this candle
4. detect and apply BREAKs (kill old, create axis)
5. detect new TURN levels (confirmed swings only)
6. detect new LAUNCH levels (impulse + base + departure speed)
7. detect wick clusters
8. re-grade all live levels
9. apply death rules
10. apply the 8-level cap
11. recompute obstacles_above / obstacles_below
```

Order matters: breaks before births, deaths before the cap.

---

## 11. Tests that must pass

| Test | Expectation |
|---|---|
| `test_swing_needs_right_bars` | A swing is not emitted until k bars close to its right |
| `test_launch_requires_quiet_base` | Impulse with no quiet base → no LAUNCH level |
| `test_launch_requires_departure` | Impulse followed by drift → no LAUNCH level |
| `test_launch_invisible_on_5m` | Fixture where a valid 1m LAUNCH sits inside one 5m candle body → level exists on 1m book |
| `test_break_creates_axis_kills_old` | Body close through support → old level dead, AXIS born at same price |
| `test_wick_touch_counts` | Wick into zone counts as touch; a pass 6 pts away does not |
| `test_third_touch_kills` | 3rd touch → `exhausted`, level no longer tradeable |
| `test_acceptance_kills` | 5 body closes beyond → `accepted_through` |
| `test_cap_keeps_nearest` | 14 candidate levels → exactly 8 kept, nearest 2 each side present |
| `test_round_number_zero_pocket` | Round-number level with pocket 0 does not divide by zero |
| `test_obstacle_nearest_wins` | Distant HTF zone + near round number → nearest returned |
| `test_grade_a_required` | Setup attempted at Grade B level → rejected with `no_live_level` |
