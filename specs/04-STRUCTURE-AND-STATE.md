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
