# 05 — GUARDS & MODE MACHINE

Guards run **before** any setup detection. They are cheap, they kill most candles, and
they encode the rules that save the most money. A guard failure is a first-class,
fully-logged outcome.

---

## 1. Guard order (fail fast, first failure wins)

```
1. warmup            — need 14 candles for ATR, plus 5m/15m alignment
2. feed_gap          — ≥2 missing minutes recently
3. time_window       — inside an allowed trading window
4. htf_close_proximity — not in the last 3 min of a 15m candle
5. volatility_floor  — ATR14(1m) >= min
6. volatility_ceiling— ATR14(1m) <= max
7. session_max_trades
8. session_consec_loss
9. session_max_loss
10. position_open    — one position at a time
```

Guards 7–9 are **latching**: once tripped, the session stays `BLOCKED` for new entries
until the next trading day. An open position is still managed to exit normally.

---

## 2. Time windows

```yaml
time:
  windows_normal:
    - ["09:30", "11:15"]
    - ["13:30", "14:45"]
  windows_expiry:
    - ["10:00", "14:00"]
  no_new_entries_after: "14:45"
  force_flat_at: "15:15"
  opening_range_end: "09:30"
```

Reasoning, so nobody "optimises" these away later:

| Excluded | Why |
|---|---|
| 09:15–09:30 | Gap fill, overnight order flow, algo rebalancing. Structure is not real yet. This window builds the opening range instead. |
| 11:15–13:30 | Lunch compression. Ranges form and fail; reclaim setups have a materially worse outcome. Levels are still updated, no entries taken. |
| 14:45–15:15 | Closing volatility and widening option spreads. Manage only. |
| Expiry, outside 10:00–14:00 | Weekly expiry is a different regime — pin risk, collapsing premium, violent unwinds. Narrower window, and see spec 08 for the size reduction. |

`force_flat_at 15:15` is unconditional. Any open position is exited at market. Never
carry an intraday paper position past this.

### Expiry detection
Read from the instrument master (spec 08), not from a hardcoded weekday — expiry day
has been changed by the exchange before and may change again. Resolve the nearest
weekly expiry from the option chain and compare to today's date.

---

## 3. Volatility gates

```yaml
volatility:
  atr_min_points: 12      # HYPOTHESIS
  atr_max_points: 60      # HYPOTHESIS
  atr_period: 14
  atr_tf: "1m"
```

- **Below min** — the market is dead. Sweeps are meaningless, levels are not being
  defended by anyone, and a 12-point stop is inside the noise band. `volatility_floor`.
- **Above max** — event/news volatility. Levels from the calm regime are void, spreads
  widen, and the slippage model is no longer valid. `volatility_ceiling`.

Both are hard gates, not size adjustments. Do not add a "trade smaller in high vol"
path — it is the beginning of the end of a rules system.

---

## 4. Session limits

```yaml
session:
  max_trades: 3
  max_consecutive_losses: 2
  max_loss_r: 2.0            # cumulative, in R
  risk_per_trade_rupees: <user sets this>   # required, no default
```

```python
class SessionState:
    trades_taken: int
    consecutive_losses: int
    cumulative_r: Decimal
    blocked_reason: str | None    # latches for the day
```

A trade counts against `trades_taken` **on fill**, not on signal. A cancelled entry does
not consume a slot but is journalled.

`risk_per_trade_rupees` has **no default value on purpose.** The engine refuses to start
without it being set explicitly in config. Forcing that decision to be conscious is the
point.

---

## 5. The bias filter (`bias_conflict`)

Not a guard — it runs inside setup evaluation, but it belongs conceptually here.

```
REJECT a LONG continuation setup if:
    structure.trend == "down"  on 5m
    AND the trigger level is NOT a Grade A support/demand level
    AND pullback_ratio < 1.0    (i.e. sellers still in control)

Mirror for SHORT.
```

Counter-trend setups taken in open space are the largest loss bucket in this style of
trading. They are permitted **only** at a Grade A level, where there is a reason for
price to turn.

---

## 6. Mode machine

```
                ┌──────────────────────────────────────────┐
                │                                          │
   guard fail   ▼                                          │
  ┌────────► BLOCKED ─── next session / guard clears ──────┘
  │
  │  no live level within alert_distance
  ├────────► WATCH ◄──────────────────────┐
  │            │                          │
  │            │ price within             │ price leaves
  │            │ alert_distance           │ alert_distance
  │            ▼                          │
  ├────────► ALERT ───────────────────────┘
  │            │
  │            │ Signal + fill
  │            ▼
  └────────►  IN ──── flat ────► WATCH (or BLOCKED if a limit tripped)
```

```yaml
modes:
  alert_distance_points: 20     # HYPOTHESIS
  alert_distance_atr_mult: 1.5  # use max(points, atr_mult × ATR14) — adapts to volatility
```

### What each mode is allowed to do

| Mode | Level book | Setup detection | Orders | 1m detail logging |
|---|---|---|---|---|
| `BLOCKED` | update | **no** | exit-only | compact |
| `WATCH` | update | **no** | none | compact |
| `ALERT` | update | **yes** | entry allowed | **full** |
| `IN` | update | **no** | exit only | **full** |

**Setup detection does not run in WATCH.** This is not an optimisation — it is the
mechanism that enforces "no trades in open space." If a setup could fire in WATCH, the
entire location discipline collapses.

**Setup detection does not run in IN.** One position at a time, no reversals on the same
candle, no pyramiding.

### Expected time distribution
Roughly 70% WATCH / 25% ALERT / 5% IN. The daily report prints the actual split. If
ALERT exceeds ~40% of the session for several days, the level book is too crowded —
check the 8-level cap and the grading, because the system is about to start
over-trading.

---

## 7. Duplicate suppression

```yaml
setups:
  max_attempts_per_level_per_session: 1
  cooldown_candles_after_exit: 3
```

- The **same setup type at the same level** may be attempted **once** per session. A
  second attempt returns `duplicate_setup`. Re-entering a level that already failed you
  is how one bad read becomes three losses.
- After any exit, no new entry for 3 candles (`cooldown`). This prevents revenge
  re-entry on the very next candle, which is a behavioural failure the code can simply
  remove.

---

## 8. Kill switches beyond the session limits

| Trigger | Action |
|---|---|
| 3 consecutive `FeedGapError` | `BLOCKED` for the day, alert |
| Realised slippage > 2× modelled, 3 times | `BLOCKED`, alert — the cost model is wrong and every number downstream is now untrustworthy |
| Engine exception in `on_candle` | snapshot state, `BLOCKED`, alert |
| Wall-clock drift vs exchange > 2s | alert; log on every candle until resolved |
| Paper P&L diverges from hand-recompute at EOD | fail the daily report loudly |

---

## 9. Tests that must pass

| Test | Expectation |
|---|---|
| `test_no_entry_before_0930` | Candle at 09:22 with a perfect setup → `time_window` |
| `test_lunch_blocked` | Perfect setup at 12:10 → `time_window`; levels still updated |
| `test_expiry_window_narrower` | Expiry day 09:45 → blocked; 10:30 → allowed |
| `test_force_flat_1515` | Open position at 15:15 → market exit, reason `eod` |
| `test_warmup_blocks_first_14` | Candles 1–14 → `warmup` |
| `test_vol_floor_and_ceiling` | ATR 9 → `volatility_floor`; ATR 71 → `volatility_ceiling` |
| `test_htf_proximity_blocks` | 10:13 inside the 10:00 15m candle → `htf_close_proximity` |
| `test_session_limits_latch` | After 3 fills → `session_max_trades` for the rest of the day, even if a later setup is perfect |
| `test_consec_loss_latches` | Two losses → blocked; a subsequent win cannot un-block (it can't happen — verify no path exists) |
| `test_no_setup_detection_in_watch` | Setup detector is never invoked while mode == WATCH |
| `test_one_position_only` | Signal while IN → `position_open` |
| `test_duplicate_setup_blocked` | Same setup, same level, second time → `duplicate_setup` |
| `test_cooldown_after_exit` | Entry attempt 2 candles after an exit → rejected |
| `test_bias_conflict_open_space` | Long setup in a 5m downtrend at a Grade B level → `bias_conflict` |
| `test_mode_distribution_sane` | Full fixture day → WATCH share ≥ 50% |
