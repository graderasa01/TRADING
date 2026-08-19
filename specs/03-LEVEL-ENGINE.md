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
`k = params.levels.swing_lookback_bars_1m` (**3**), `..._5m` (**2**), or
`..._15m` (**2**) — HYPOTHESIS.

### ⚠ v2.1 — the 15m rule was missing, and it is the timeframe the map comes from

v1 defined `swing_lookback_bars_1m` and `_5m` only. But:

- `mythinking.md` §1 says the 15m is where levels are drawn: *"15-min: sirf jab 15m
  candle band ho. **Levels + bias.** Map."* The human's 7 lines come from here.
- §7 of this spec awards a grading point for **"HTF confirmed — also detectable on 5m
  or 15m."** With no 15m swing rule, that point could never be earned from a 15m swing.
  Only ANCHORs could claim it.

So v1 built its level book from the two fastest timeframes and then graded levels on a
criterion it had no way to evaluate. Run the same swing-pivot detection on **1m, 5m and
15m**. A level detected on more than one timeframe is the same level — merge by price
proximity (within `wick_cluster_tolerance`) and keep the **highest** `born_tf`, since
that is what "HTF confirmed" means.

**Run order:** 15m first, then 5m, then 1m. A 1m swing that lands inside an existing
15m level's zone does not create a new level — it increments that level's evidence and
may raise its grade. Otherwise the book fills with three copies of the same price.

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

### ⚠ v2.2 — `departure_speed` must be computed for EVERY level kind

v1 defined this formula **only here, inside the LAUNCH section.** TURN, BREAK and ANCHOR
levels therefore had no departure speed at all, and it defaulted to zero.

That looks harmless. It is not — §7 grades levels partly on departure speed, so a
level with no defined departure could never earn that point. A dry run of the full
engine (see `prototype/FINDINGS.md`, Bug 1) showed the consequence:

| level type | untested | departure | HTF | clean | score | grade |
|---|---|---|---|---|---|---|
| TURN (1m swing) | 1 | 0 | 0 | 0 | 1 | C |
| TURN (5m swing) | 1 | 0 | 1 | 0 | 2 | B |
| TURN (15m swing) | 1 | 0 | 1 | 0 | 2 | B |
| ANCHOR PDH/PDL | 1 | 0 | 1 | 0 | 2 | B |
| **LAUNCH** | 1 | 1 | 0 | 1 | **3** | **A** |

**Only LAUNCH levels could ever reach Grade A.** Since a setup may only trigger at a
Grade A level (§7), the entire system could trade at exactly one kind of level. In the
dry run, ALERT mode was **0% of the session** — not one setup was evaluated all day.

It also produces a direct contradiction with spec 06, which states that at
`kind == ANCHOR`, **Setup B is the only permitted setup**. Anchors could not reach
Grade A, so Setup B could never fire at PDH or PDL — the exact locations spec 06 calls
out as most important.

**The fix.** Departure speed is a property of *any* price, not of one detector:

```python
def departure_speed(level_price: Decimal, born_i: int, n: int = 3) -> Decimal:
    """How fast did price run away from this level after it formed?
    Defined for TURN, LAUNCH, BREAK and ANCHOR alike."""
    return abs(candles[born_i + n].c - level_price) / atr20_at(born_i)
```

- **TURN** — measured from the pivot/cluster price. A swing price abandoned quickly is
  a stronger level than one price loitered around. That is the same reasoning as LAUNCH.
- **BREAK** — measured from the axis price after the break.
- **ANCHOR** — PDH/PDL/PDC use the *previous* session's departure from that price; the
  opening range uses the 3 candles after 09:30. If unavailable, score 0 for departure
  but see the clean-formation fix below.

Confirmation is delayed by `n` candles, exactly like a swing. That is correct and it is
not look-ahead: the level simply does not exist until candle `born_i + n` closes.

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

### ⚠ v2.2 — a touch is an EVENT, not a minute. This one killed the flagship trade.

v1's definition is evaluated on every closed 1m candle. Combined with
`max_touches: 3`, and with anchors whose `pocket == 0` (a zone one price wide), the
result is that **price simply lingering near a level counts as three separate tests and
kills it.**

From the dry run (`prototype/FINDINGS.md`, Bug 2), tracing PDL at 57,455:

```
09:15   0 touches   alive
09:55   1 touch     alive     price arrives
09:56   2 touches   alive     still there
09:57   3 touches   DEAD      "exhausted"
09:59              THE SWEEP  — 21-pt pierce, 83% wick, clean reclaim
```

**PDL died two minutes before its own sweep**, because price hovered around it for three
minutes. The single most important level of the day, removed from the book by the clock
rather than by the market. A trader looking at that chart would say *"that is one test
so far."*

**A test and a minute are different things. v1 treated them as the same.**

**The fix — a touch requires separation:**

```python
separation = max(params.levels.touch_separation_points,
                 params.levels.touch_separation_atr_mult * atr20_1m)

inside = candle.l <= zone_high and candle.h >= zone_low

if inside and not level.in_zone:
    level.touches += 1
    level.in_zone = True
elif not inside and (candle.l > zone_high + separation
                     or candle.h < zone_low - separation):
    level.in_zone = False          # price has genuinely left; next entry is a new test
```

`in_zone` is per-level state and must be persisted with the level, including through
dormancy. Price must **leave** by the separation distance before a new touch can be
counted. Hovering is one touch, however long it lasts.

This also fixes the same bug for round numbers, day extremes and every other
zero-pocket level, all of which were dying within minutes of price arriving.

---

## 5. BREAK levels — the axis

### ⚠ v2.2 — only a Grade A or B level may create an axis

The dry run produced **28 breaks in one session**, and at the close **6 of the 8 active
level slots were BREAK axes**, all Grade C — crowding out the TURN and LAUNCH levels the
engine exists to find. Meanwhile exactly **one LAUNCH level** formed all day, the type
this spec calls "the highest-value 1m level."

Every body close through any of ~36 detected TURN levels was creating an axis. But a
Grade C level breaking is not news — a Grade C level is context, and context giving way
is ordinary. Require `broken_level.grade in ("A", "B")` before creating an axis. A
Grade C break still kills the old level; it just does not manufacture a new one.

```yaml
axis_min_broken_grade: "B"
```

---

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

### v2 — round numbers are heavily demoted, and here is the arithmetic

v1 treated every 100-mark as a first-class level: gradeable to A, counting against the
8-level cap, triggering ALERT, and gating the space check. On a 100-point grid that
produces three separate failures:

**1. ALERT never switches off.** With `alert_distance = 20`, price is within 20 points
of *some* 100-mark **40% of the session** — that band is 40 points wide out of every
100. Add real levels on top and ALERT is the majority mode. Spec 05 expects
~70% WATCH / ~25% ALERT and warns that if ALERT exceeds 40% "the system is about to
start over-trading." v1's own round-number rule guarantees that outcome.

**2. The level cap fills with noise.** The cap keeps "the 2 nearest above and 2 nearest
below." Round numbers are the densest thing on the chart, so those four slots are
almost always 100-marks — crowding out the TURN and LAUNCH levels the system was
built to find.

**3. The space gate becomes a lottery on the entry price's last two digits.** Space
must be ≥ 2.5 × R to the *nearest* obstacle. Distance to the next 100-mark is
essentially uniform on [0, 100]:

| R | space required | P(pass) from round numbers alone |
|---|---|---|
| 12 | 30 | 70% |
| 20 | 50 | 50% |
| 25 | 62.5 | **37.5%** |
| 35 | 87.5 | **12.5%** |
| 40+ | 100+ | **0% — mathematically impossible** |

A 25-point-R trade is rejected 62% of the time before any real level is considered,
purely because of where the entry price happens to sit relative to the next hundred.
That is not a filter. It is a coin flip wearing a filter's clothing, and worse, it is
*correlated with R* — so it silently biases the whole system toward tiny stops, which
is exactly where cost drag is worst.

**The v2 rules:**

```yaml
round_number_max_grade: "B"            # can never be a trigger level
round_numbers_can_trigger_alert: false
round_numbers_count_against_cap: false
```

- A 100-mark has no order-flow history behind it — nobody accumulated a position at
  57,300 *because* it was 57,300. It cannot be a Grade A trigger.
- 500 and 1000 multiples are genuinely watched and keep `medium` strength.
- Round numbers remain **obstacles for T1 placement** — that part of v1 was right. A
  target sitting 3 points beyond 57,500 is a bad target.

---

## 6b. OBSTACLE STRENGTH — v2

v1's `obstacles_above/below` returned everything, unweighted, and the space check took
the nearest. That makes a random 100-mark equal to an untested prior-day high.

```python
class ObstacleStrength(StrEnum):
    STRONG = "strong"    # gates space, caps T1
    MEDIUM = "medium"    # gates space, caps T1
    WEAK   = "weak"      # caps T1 only — can never cause a rejection
```

| Obstacle | Strength |
|---|---|
| Grade A level | strong |
| PDH / PDL | strong |
| Day high / day low | strong |
| Opening range H/L | strong |
| Grade B level | medium |
| Round 500 / 1000 | medium |
| Far side of an active range | medium |
| Grade C level | weak |
| Round 100 | weak |
| Price rejected twice in last 60 min | weak |

```python
def space_obstacle(price, direction) -> Level:
    """Nearest obstacle with strength >= params.levels.space_gate_min_strength."""

def t1_obstacle(price, direction) -> Level:
    """Nearest obstacle of ANY strength. Targets respect everything."""
```

Two different questions, two different answers. v1 collapsed them into one and let the
weaker question veto the trade.

**Keep the counterfactual honest:** log both the strength-filtered space *and* the v1
all-obstacles space on every decision. The spec 09 counterfactual study can then
measure directly whether the demotion helped or hurt, instead of anyone assuming.

---

## 7. GRADING

Score each live level 0–4, one point per criterion:

| Criterion | Point awarded when |
|---|---|
| **Untested** | `touches == 0` |
| **Fast departure** | `departure_speed >= min_departure_speed` |
| **HTF confirmed** | also detectable on 5m or 15m, or is an ANCHOR |
| **Clean formation** | either long time-at-price (≥10 candles) OR very fast departure (≥1.5× threshold) — **not the middle**. **v2.2: an ANCHOR always earns this point** — PDH/PDL/PDC are formed over an entire session, which is the longest time-at-price available, and the opening range over 15 minutes |

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
| Distance from price > `dormancy_distance_atr_mult × ATR20_1m` (default 25) | **`"dormant"` — v2.1, was `"irrelevant"` (dead)** |

Dead levels are retained in the journal (they explain past decisions) but removed from
the active book.

---

## 8b. DORMANCY — v2.1. Distance is a reason to remember, not to forget.

v1 killed any level further than 25 × ATR from price, with `death_reason = "irrelevant"`.
Dead levels leave the active book **and the obstacle list**. So the engine deleted a
level *because price had travelled away from it* — and had nothing left when price came
back to meet it.

A trader does the exact opposite. From `mythinking.md`:

> *"iske levels ko yaad rakhunga **recent me daal kar** — jab upar aaya to mujhe yaad
> rahega **meri mulakat kisse ho sakti hai.**"*

Distance is precisely when you file a level away, because that is when you know you will
meet it later. v1 forgot exactly what the human deliberately remembers.

```yaml
dormant_pool_enabled: true
dormancy_distance_atr_mult: 25     # beyond this → sleep
revival_distance_atr_mult: 15      # price returns within this → wake up
dormant_min_grade_at_sleep: "B"    # C-grade levels die properly
dormant_max_age_minutes: 375       # one session
dormant_pool_max: 40
```

**Three states, not two:**

```
ALIVE    ── in the book, gradeable, tradeable, an obstacle
DORMANT  ── out of the book (does not count against the 8-cap),
            not tradeable, but REVIVABLE. Carries its full history.
DEAD     ── exhausted / accepted_through / expired. Never returns.
```

Rules:

1. A level goes dormant on **distance only**. Exhaustion, acceptance and expiry still
   kill outright — those mean the level stopped being real, not that price walked away.
2. A dormant level **revives** when price comes back within `revival_distance`. It
   returns with `born_at`, `touches` and its grade-at-sleep **intact**. It does not come
   back as untested — it has a history, and the grading must say so.
3. Dormant levels **do not** count against `max_active_levels`. The 8-cap is about what
   is in front of you now; the dormant pool is memory.
4. Only levels at grade B or better go dormant. Otherwise the pool becomes a landfill.
5. The pool is capped at 40 and cleared at session end. Overnight, only ANCHORs survive
   — which is correct, and is also what the gap-regime rule already assumes.

**Journal every dormancy and every revival.** A revived level that immediately produces
a strong reaction is direct evidence that this memory is worth keeping; one that price
slices through is evidence it is not. That is measurable, and spec 09 measures it.

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
of the following, each tagged with its strength from §6b:

- every live level (A, B and C)
- day high / day low
- PDH / PDL / PDC
- every round number (100s — `weak`; 500s/1000s — `medium`)
- the far side of the current range, if one is active
- any price rejected ≥2 times in the last 60 minutes

**The space GATE uses the nearest obstacle of strength ≥ medium.**
**T1 placement uses the nearest obstacle of any strength, including weak.**

The original principle is unchanged and still correct: *a 200-point target with a wall
at 30 points is a 30-point trade, and this is the most common way a good entry becomes
a losing trade.* v2 only separates "this is a wall" from "this is a line on a grid" —
see §6b for why treating them alike made the gate fire on the entry price's last two
digits rather than on the trade.

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
| `test_obstacle_nearest_wins` | Distant HTF zone + near round number → nearest returned for T1 |
| `test_grade_a_required` | Setup attempted at Grade B level → rejected with `no_live_level` |
| `test_round_number_never_grade_a` | Round-100 scoring 3 points → grade capped at B |
| `test_round_100_cannot_block_space` | Round-100 at 30 pts, Grade A level at 90 pts, R=25 → space = 90, **passes** |
| `test_round_500_blocks_space` | Round-500 at 30 pts, R=25 → `space_insufficient` |
| `test_round_100_still_caps_t1` | 1.5R target beyond a round-100 → T1 pulled to the round-100 |
| `test_round_numbers_excluded_from_cap` | 20 round numbers + 6 real levels → all 6 real levels survive the cap |
| `test_round_numbers_do_not_trigger_alert` | Price 5 pts from a round-100, no other level → mode stays WATCH |
| `test_both_space_values_logged` | Every decision carries `space_v2` and `space_all_obstacles` |
| `test_15m_swings_detected` | A 15m swing high produces a level with `born_tf == "15m"` |
| `test_same_price_not_duplicated_across_tf` | A price found on 1m, 5m and 15m → **one** level, `born_tf == "15m"` |
| `test_htf_confirmed_point_earnable` | A 15m-born level scores the HTF grading point |
| `test_distance_causes_dormancy_not_death` | Level 30 × ATR away → `dormant`, not `dead`; still in the dormant pool |
| `test_dormant_revives_with_history` | Revived level keeps `touches` and `born_at` — **does not** reset to untested |
| `test_third_touch_survives_dormancy` | Level with 2 touches → dormant → revived → next touch is the 3rd and exhausts it |
| `test_dormant_not_counted_in_cap` | 8 active + 12 dormant → cap still satisfied |
| `test_exhausted_never_goes_dormant` | Exhausted / accepted_through levels die outright, never sleep |
| `test_grade_c_does_not_sleep` | Grade C level beyond the distance → dead, not dormant |
