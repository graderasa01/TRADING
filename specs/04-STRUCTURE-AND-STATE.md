# 04 — STRUCTURE ENGINE & STATE BOARD

`structure/` never imports from `levels/`. It sees only candles. This is deliberate —
it prevents circular reasoning where a level justifies a structure that justifies the
level. The two are joined only in `state/board.py`.

---

## 1. Swings

Same fractal definition as spec 03 §2a, but tracked as a *sequence*, not as levels.

- **5m**: `k = 2` (confirmed 2 bars right)
- **1m**: `k = 3` (confirmed 3 bars right)

Maintain the last 4 swing highs and last 4 swing lows per tf. Only confirmed swings
enter the sequence.

---

## 2. Break of Structure (BOS)

```
Bullish BOS (5m):  a 5m candle closes its BODY above the last confirmed swing high
Bearish BOS (5m):  a 5m candle closes its BODY below the last confirmed swing low
```

**Body close only.** A wick through a swing is not a BOS — it is a sweep, and it is
Setup B's business, not the structure engine's.

```python
@dataclass(frozen=True)
class BreakOfStructure:
    at: datetime
    direction: Literal["up", "down"]
    broken_swing: Swing
    breaking_candle: Candle
    tf: Literal["1m", "5m"]
```

### `control` (board variable 7)
```
last BOS on 5m is "up"    → control = "buyers"
last BOS on 5m is "down"  → control = "sellers"
no BOS yet this session   → control = "none"
```

---

## 3. Trend and Regime

**Trend (5m):**
```
"up"    : last two confirmed swing highs ascending AND last two swing lows ascending
"down"  : both descending
"none"  : anything else  ← this is the common case, and that is correct
```

**Regime:**
| Regime | Condition |
|---|---|
| `trending` | last 2 BOS are same direction AND no opposing BOS in the last `regime_lookback` (default 20) 5m candles |
| `ranging` | ≥2 opposing BOS within the lookback, OR a valid range is active (spec 06 §4) |
| `transition` | everything else |

Regime is consumed by the bias filter (spec 06 §5) and by the daily report. It is not
itself a trade filter.

---

## 4. The nesting law — HTF shape from LTF structure

This is the drill-down logic, encoded. Two facts the engine must expose:

### Law A — an HTF wick is an LTF structure break
```python
def htf_candle_forecast(m15_partial, m5_structure) -> Literal["body", "upper_wick", "lower_wick", "doji"]:
    """
    The forming HTF candle will close in the direction of the LAST LTF structure
    break that occurred inside it.
    """
```
Implementation: track BOS events whose timestamps fall inside the current 15m partial.
- No BOS inside → `"body"` if the partial's `close_position` is extreme, else `"doji"`
- Last inside-BOS is up, and partial opened above current price → `"lower_wick"` forming
- Mirror for `"upper_wick"`

This is **informational only**. It feeds the journal and the anticipation line. It must
never gate a trade — it is a forecast of a candle, not of price.

### Law B — the last third
```python
def htf_progress(now, partial) -> Decimal:   # 0.0 → 1.0
```
When `htf_progress >= params.structure.htf_last_third` (default **0.66**) on the 15m
partial, the engine sets `board.htf_closing_soon = True`.

**Consumed by:** the `htf_close_proximity` gate (spec 05) — no new entries in the last
`htf_close_buffer_minutes` (default **3**) of a 15m candle. HTF candles reverse their
shape in their final minutes; entering there means entering just before the wick.

---

## 5. Speed comparison — the control test

The most reliable read of who is in control, and it is pure arithmetic.

```python
impulse_atr  = mean(candle.range for candles in the last completed impulse leg)
pullback_atr = mean(candle.range for candles in the current pullback leg)

pullback_ratio = pullback_atr / impulse_atr
```

| Ratio | Meaning | Effect |
|---|---|---|
| `< 0.6` | Healthy pullback. Impulse side still in control. | Setup A favoured |
| `0.6 – 1.0` | Weakening. | No effect; log it |
| `> 1.0` | Pullback candles bigger than impulse candles — **control has changed** | `bias_conflict` gate fires against continuation setups |

Leg identification: a leg ends when a 1m candle closes beyond the prior candle's
extreme in the opposite direction, twice consecutively. Keep it simple and mechanical;
do not build wave counting.

---

## 6. The Landing Ladder

When an impulse completes, precompute where a pullback can stop. This is written
**before** the pullback happens — that is the entire point.

```python
def landing_ladder(impulse: Candle, axis: Level | None, levels: LevelBook) -> list[LadderRung]:
```

Rungs, in order of likelihood (nearest first):

| Rung | Price | Meaning |
|---|---|---|
| **L1** | impulse midpoint (`(h+l)/2`) | shallow — strongest trend holds here |
| **L2** | the BREAK axis / broken level `body_edge` | **primary** landing zone, Setup A fires here |
| **L3** | axis `wick_tip` − sweep buffer | sweep zone, Setup B fires here |
| **L4** | impulse candle's origin (`o` or the LAUNCH base low) | **below this, the move failed** |

```python
@dataclass(frozen=True)
class LadderRung:
    label: Literal["L1","L2","L3","L4"]
    price: Decimal
    distance_points: Decimal
    is_failure_line: bool     # True only for L4
```

### Which rung will it reach? — read from the 1m pullback
Three signals, all computed on the pullback candles:

1. **Size** — `pullback_ratio < 0.6` → expect L1/L2. `> 1.0` → expect L3/L4.
2. **Legs** — one leg → shallow. A 1m lower-high followed by a second leg → one rung deeper.
3. **First lower wick** — first pullback candle with `lower_wick > 40% of range` and
   `close_third == "top"` → sellers exhausting, the floor is close.

**Pullback-over signal (the earliest confirmation):**
```
a 1m candle closes ABOVE the previous 1m candle's high, after a 1m higher-low has formed
```
This is the trigger condition Setup A consumes.

The ladder is **not a prediction**. Its job is to reduce four hundred possible prices to
four, then let the 1m candles say which one.

---

## 6b. The JOURNEY LADDER — v2.1. The largest idea missing from v1.

The Landing Ladder answers *"a move happened — where will the pullback stop?"*
Nothing in v1 answered the other half: **"a level just broke — where is price going?"**

v1 handles a break by creating an AXIS (spec 03 §5) and then stops thinking. The axis is
a flip line and an invalidation line. It is not a destination. So the engine breaks a
level and forms no expectation at all about what happens next.

The human's model, from `mythinking.md`:

> *"jahan se aaya wahan tak to jayega hi jayega... phir wahan par jayega to kya karega
> wo bhi pata — cluster ya swing."*

Two claims, and they are different in kind:

| Claim | Status |
|---|---|
| *Price returns to where the move came from* | **A hypothesis about market behaviour. Untested.** |
| *What waits there is knowable — a cluster, a swing, an anchor* | **Already true in the engine.** Every destination IS a `Level` with a `kind` and a `grade`. `levels_above` / `levels_below` already carry this |

The second half is built. The first half is not, and it is the one that must be handled
carefully — because a strong intuition that has never been measured is exactly the kind
of thing that quietly becomes a rule and then quietly loses money.

**So it is built as a logged prediction, never as a gate.**

```python
@dataclass(frozen=True)
class JourneyRung:
    label: Literal["D1","D2","D3","D4"]
    price: Decimal
    basis: str                      # human-readable: which level, why
    distance_points: Decimal

@dataclass(frozen=True)
class Journey:
    started_at: datetime
    origin_level: Level             # the level that broke
    direction: Literal["up","down"]
    break_candle: Candle
    invalidation: Decimal           # the axis body_edge — back through = failed
    rungs: list[JourneyRung]        # D1 nearest → D4 furthest
    # resolved later, by the journey tracker:
    outcome: Literal["open","D1","D2","D3","D4","stalled","failed"] | None
    resolved_at: datetime | None
    max_progress_points: Decimal
```

### The rungs — deliberately the mirror of the Landing Ladder

For a break **upward** (mirror for down):

| Rung | Price | Meaning |
|---|---|---|
| **D1** | nearest untested level above, **including revived dormant levels** | the first meeting |
| **D2** | origin of the last down-move — the LAUNCH base, or the swing high the sellers came from | **"jahan se aaya"** — the human's primary target |
| **D3** | break point + (`broken range width` × `journey_measured_move_mult`) | measured move |
| **D4** | next ANCHOR — PDH, day high, round 500 | the structural wall |

Rungs are sorted by distance and **deduplicated** — D2 and D3 frequently land on the
same price, and when they do that agreement is itself information. Log it as
`confluence: ["D2","D3"]`.

### How it resolves

The journey tracker runs on 5m closes:

- price trades through a rung ± `journey_reached_tolerance` → record that rung reached
- no progress for `journey_stall_candles_5m` (6) → `stalled`
- body close back through `invalidation` → `failed`
- `journey_ttl_minutes` (120) elapses → close it at whatever rung was reached

### ⚠ The gate that must stay shut

```yaml
journey_gates_trades: false     # MUST remain false until P9 measures it
```

Nothing in `setups/`, `risk/` or `exits/` may read a `Journey` while this is false. Add
a static test asserting it. The Journey is written to the journal and to the daily
report, and that is all it does on day one.

### What P9 must report about it

For every journey, cut by direction, regime, time bucket and origin-level grade:

```
journeys started
% reaching D1 · D2 · D3 · D4
% stalled · % failed (invalidation)
median max_progress as a fraction of the D2 distance
median time-to-D2 in 5m candles
hit rate when D2 and D3 agree (confluence) vs when they do not
```

**Read it honestly.** If D2 is reached 70% of the time, *"jahan se aaya wahan tak jayega"*
is a real, measured property of this market and it should drive T2 selection — and
possibly a bias filter. If it is reached 45% of the time, it is a comfortable story that
feels true because the times it worked are the ones you remember.

Either answer is worth having, and the second one is worth more, because it is the one
you cannot get by trading.

**Note what this does to the space check.** If D2 turns out to be real, the *nearest
obstacle* rule (spec 07 §1.3) is still correct — you still have to get past the wall in
between. The journey tells you where the trade is going; the space check tells you
whether it can get out of the driveway. They answer different questions and neither
replaces the other.

---

## 7. StateBoard update order

On every closed 1m candle, after the level engine has run:

```
1.  day_high / day_low                         (var 1)
2.  opening range — freeze at 09:30            (var 2)
3.  PDH/PDL/PDC — loaded once at startup       (var 3)
4.  5m swings (only on 5m close)               (var 4)
5.  active_level = nearest live level; distance_to_active   (var 5)
6.  last_decision_candle + its LAUNCH origin   (var 6)
7.  control from last 5m BOS                   (var 7)
8.  regime                                     (var 8)
9.  atr_1m (14), atr_5m (14)
10. levels_above / levels_below (sorted)
11. htf_closing_soon, htf_candle_forecast
12. pullback_ratio, active ladder (if an impulse is live)
13. board_digest = stable hash of the above
```

### Reconstructibility test
```python
def test_board_is_deterministic():
    """Replaying the same candles must produce byte-identical board_digest
    at every step. No wall clock, no dict ordering, no float."""
```
If this test cannot pass, the paper result will not match a live run, and the whole
exercise is pointless.

---

## 8. The anticipation line

Produced every candle, journalled, and shown in the daily report. This is the "IF-THEN
before the candle" written mechanically.

```python
def anticipation(board: StateBoard) -> str:
    """
    Template, filled from the board — no free text:

    "Price {p}. Active {level.kind} {level.body_edge} ({level.grade}, {level.touches} touches),
     {d} pts {above|below}.
     IF body close {above} {level.body_edge} → next obstacle {obs_up.body_edge} ({space_up} pts).
     IF body close {below} {level.body_edge} → flips to resistance, next support
     {obs_down.body_edge} ({space_down} pts).
     Control: {control}. Regime: {regime}. Mode: {mode}."
    """
```

Deliberately mechanical. It exists so that after a losing day you can read what the
engine expected *before* each candle, not what it concluded after.

### v2.1 — extend it to two steps, because that is how the read actually runs

v1's line looks one step ahead: *"IF body close above X → next obstacle Y."* The human
chains it further — break, then the meeting, then what happens at the meeting:

> *"usko todta hai to last neeche low tak... phir wahan par jayega to kya karega wo bhi
> pata — cluster ya swing."*

The second step costs nothing, because the destination is already a `Level` whose kind,
grade and touch count the engine knows:

```
"Price 57118. Active TURN 57100 (A, 1 touch), 18 pts above.
 IF body close below 57100 → flips to resistance. First meeting: LAUNCH 57042
   (B, 0 touches, 76 pts) — untested base, expect a reaction, not a stop.
 IF that gives way → D2 57960 [origin of the 10:20 up-move], 158 pts.
 Control: sellers. Regime: transition. Mode: ALERT."
```

Two steps, no further. Three-step chains are storytelling — each step multiplies the
uncertainty of the last, and a template that produces a confident-sounding four-step
narrative will be read as a forecast no matter how many disclaimers surround it.

Both steps come from data already on the board. Nothing new is computed, and nothing is
predicted — the line states what is *there*, conditionally.

---

## 9. Tests that must pass

| Test | Expectation |
|---|---|
| `test_bos_requires_body_close` | Wick through swing → no BOS |
| `test_swing_sequence_trend` | Ascending HH/HL fixture → `trend == "up"` |
| `test_regime_ranging_on_opposing_bos` | Two opposing BOS in lookback → `ranging` |
| `test_htf_forecast_lower_wick` | 15m partial with a late bullish 5m BOS → forecast `lower_wick` |
| `test_htf_last_third_flag` | At 10:12 inside the 10:00 15m candle → `htf_closing_soon` True |
| `test_pullback_ratio_flips_control` | Pullback candles larger than impulse → ratio > 1.0 |
| `test_ladder_ordering` | L1 nearer than L2 nearer than L3 nearer than L4 for a long |
| `test_ladder_failure_line` | Only L4 has `is_failure_line == True` |
| `test_pullback_over_signal` | Higher-low then close above prior high → signal fires exactly once |
| `test_board_is_deterministic` | Identical digests across two replays of the same day |
| `test_structure_never_imports_levels` | Static check: `structure/` has no import from `levels/` |
| `test_journey_created_on_break` | Body close through a Grade A level → a `Journey` with 4 ranked rungs |
| `test_journey_d2_is_move_origin` | D2 equals the LAUNCH base / swing the prior move came from |
| `test_journey_rungs_deduplicated` | D2 and D3 at the same price → one rung, `confluence: ["D2","D3"]` |
| `test_journey_includes_revived_levels` | A dormant level inside the path appears as D1 |
| `test_journey_resolves_stalled` | 6 flat 5m candles → outcome `stalled` |
| `test_journey_resolves_failed` | Body close back through the axis → outcome `failed` |
| `test_journey_never_read_by_trading_path` | **Static:** `setups/`, `risk/`, `exits/` do not import the journey module |
| `test_anticipation_is_two_steps` | The line names the first meeting **and** what waits beyond it — and stops there |
