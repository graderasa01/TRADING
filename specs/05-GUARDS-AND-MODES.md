# 05 — GUARDS & MODE MACHINE

Guards run **before** any setup detection. They are cheap, they kill most candles, and
they encode the rules that save the most money. A guard failure is a first-class,
fully-logged outcome.

---

## 1. Guard order (fail fast, first failure wins)

```
0. stale_cost_model  — costs.yaml unverified or >90 days old  ── REFUSE TO START
1. event_blackout    — today is in config/events.yaml          ← v2
2. gap_regime        — gapped >0.40% and before 10:00          ← v2
3. warmup            — need 14 candles for ATR, plus 5m/15m alignment
4. feed_gap          — ≥2 missing minutes recently
5. time_window       — inside an allowed trading window
6. htf_close_proximity — not in the last 3 min of a 15m candle  **(v2.2: Setup B exempt — see §3b)**
7. volatility_floor  — ATR14(1m) >= min
8. volatility_ceiling— ATR14(1m) <= max
9. session_max_trades
10. session_consec_loss
11. session_max_loss
12. r_model_broken   — realised losses exceeding modelled R    ← v2
13. position_open    — one position at a time
```

Guards 9–12 are **latching**: once tripped, the session stays `BLOCKED` for new entries
until the next trading day. An open position is still managed to exit normally.

Guard 0 is not a rejection, it is a **startup refusal**. The engine will not run with
an unverified cost model, because on this instrument the cost model decides whether
any trade can be positive-expectancy (spec 07 §1.6).

---

## 1b. Event blackout (`event_blackout`) — v2

The prohibition on news input stands: the engine never reads, parses or reacts to
news. This guard is a **date lookup in a file written in advance**. No forecast, no
interpretation, no curve-fitting risk — RBI MPC dates are published for the full
financial year and results dates weeks ahead.

**Why it is needed.** Roughly 75% of the Bank Nifty index sits in five stocks —
HDFC Bank, ICICI Bank, SBI, Axis, Kotak. On their results days the index does not
respect the level structure the engine spent the morning building; it repriced on
information, not on order flow at a level. The volatility ceiling catches this *after*
the move has happened. The calendar catches it before.

```
full-day blackout       : rbi_mpc, union_budget, unscheduled RBI action
blocked until 11:15     : heavyweight bank results
blocked until 10:00     : the Indian session following a US FOMC decision
tagged but not blocked  : monthly expiry, US CPI, index rebalance
```

**Fail closed.** Missing calendar file, or `last_updated` older than 30 days → refuse
to start. A stale calendar is worse than none: it produces confidence that the check
is running when it is not.

The `tagged_only` list matters as much as the blackout list. Those days are traded
normally but tagged into the journal `context` block, so the weekly review can cut
performance by them. If the data later shows one is bad, promote it. **Do not promote
on a hunch, and do not add anything to the blackout list after seeing a bad day** —
that is curve-fitting with extra steps.

---

## 1c. Gap regime (`gap_regime`) — v2

Every carried 1m and 5m level encodes "price traded here, and someone defended it."
After a large gap, price never traded through the intervening range at all — those
levels describe a market that no longer exists. v1 would happily detect a "flip
retest" of a level price gapped straight over.

```yaml
gap_regime:
  gap_pct_threshold: 0.40      # |open − prev_close| ÷ prev_close × 100
  action: "anchors_only"
  no_entries_until: "10:00"
```

On a gap day:
- **Kill** every carried level of kind TURN, LAUNCH and BREAK. `death_reason = "gapped_over"`.
- **Keep** PDH, PDL, PDC and (from 09:30) the opening range. These survive because a
  gap does not erase yesterday's decision points — it just means we arrived at them
  from a different direction.
- **No entries before 10:00**, regardless of the normal window.
- The day is tagged `gap_up` / `gap_down` in the journal context block.

Rebuild the level book from the current session's candles only. The engine is
effectively starting fresh with three anchors, which is the honest description of what
it knows.

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

## 3b. ⚠ v2.2 — `htf_close_proximity` must exempt Setup B. This was the worst bug found.

The dry run (`prototype/FINDINGS.md`, Bug 3) planted a textbook sweep-reclaim at PDL and
then checked every Setup B condition at the reclaim candle, 09:58:

```
B1 level Grade A?              A       PASS
B1 level alive?                alive   PASS
B2 pierce 21 ≥ 12?                     PASS
B3 lower wick 83% ≥ 55%?               PASS
B5 reclaim 35 ≥ 7?                     PASS
B6 close in top third?  (top)          PASS
Mode: PDL 35 pts away, alert distance 44   PASS
```

**Six of six conditions passed, and nothing happened.**

09:58 is minute 43 of the session. The 15m candle 09:45–10:00 was at position 13 of 15,
so `htf_close_proximity` fired, the mode was `BLOCKED` rather than `ALERT`, and **the
setup detector never ran.** The engine did not reject that trade. It never saw it.

### Why this is structural, not a coincidence

From `mythinking.md` §6, the trader's own observation:

> *"15m candle band hone se 3-4 min pehle — **wick yahin banti hai.** Naya trade nahi
> kholta, **2 min rukta hu.**"*

He says the wick forms there, so he **waits two minutes and then acts.** v1 translated
that into *"entries are blocked for three minutes."* Those are different rules.

Now combine it with Setup B's staleness rule (spec 06, B7): *"candles between sweep and
reclaim ≤ 2; candle 3+ → `setup_stale`."*

```
sweeps form in the last 3 minutes of a 15m candle   (the trader's own observation)
entries are blocked for exactly those 3 minutes
by the time the block lifts, the reclaim is 3+ candles old → setup_stale
```

**Setup B is structurally unable to trade at the time Setup B most often forms.** Two
rules, each individually sensible, that together delete the setup with the best
risk-reward in the system.

### The fix

The guard's stated reason is that *"HTF candles reverse their shape in their final
minutes; entering there means entering just before the wick."* That reasoning applies to
**continuation** entries. Setup B is not a continuation entry — **it is the trade that
profits from exactly that reversal.** The wick the guard warns about is the sweep Setup B
is built to catch.

```yaml
htf_close_buffer_minutes: 3
htf_close_exempt_setups: ["B_sweep_reclaim"]     # v2.2
```

- **Setups A and C** (flip retest, range break retest) remain blocked in the tail. They
  are continuation trades and the original reasoning holds for them exactly.
- **Setup B** may fire in the tail, but only at a Grade A level with all of B1–B7
  satisfied. It is already the most heavily gated setup in the system.
- Journal a `htf_tail_entry: true` flag on any trade taken in the tail, so spec 09's
  weekly review can cut performance by it. **If tail entries underperform, this exemption
  gets reversed on evidence** — but it must not be left in place unmeasured, and it must
  not have been an accident in the first place.

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
    trading_date: date
    trades_taken: int
    consecutive_losses: int
    cumulative_r: Decimal
    blocked_reason: str | None          # latches for the day
    cooldown_until_candle: int | None
    attempted_levels: set[tuple[str, str]]   # (level_id, setup) — duplicate registry
    realised_r_history: list[Decimal]        # for the r_model_broken check
```

A trade counts against `trades_taken` **on fill**, not on signal. A cancelled entry does
not consume a slot but is journalled.

`risk_per_trade_rupees` has **no default value on purpose.** The engine refuses to start
without it being set explicitly in config. Forcing that decision to be conscious is the
point.

### v2 — this state must be persisted, or the limits are decorative

Everything above lives **only in memory** in v1. Consider the sequence the limits exist
to prevent:

```
09:47  trade 1 fills, loses          → consecutive_losses = 1
10:31  trade 2 fills, loses          → consecutive_losses = 2 → BLOCKED for the day
10:58  unhandled exception, process dies
11:02  supervisor restarts the engine
       → trades_taken = 0, consecutive_losses = 0, BLOCKED cleared
11:20  trade 3 fills, loses
12:05  trade 4 fills, loses          → "2 consecutive losses" → BLOCKED again
```

Four losses on a day capped at two. The kill switch was defeated by a restart, which is
precisely the condition under which you most want it working. Note also that spec 01 §9
*mandates* a restart-adjacent path — "any unhandled exception in `on_candle` → snapshot
state, set BLOCKED" — so this is a designed-in code path, not a hypothetical.

```yaml
session:
  state_file: "state/session_state.json"
  on_restart: "resume"        # resume | refuse
```

Requirements:

1. **Write on every change**, synchronously, before the next candle is processed. Not
   at end of day, not on a timer.
2. **On startup**, load the file. If `trading_date == today`, resume from it and log
   loudly what was resumed.
3. **Starting fresh requires `--force-fresh-session`** plus a loud log line. Silent
   reset is forbidden. There must be no code path that quietly zeroes these counters.
4. **The board is rebuilt from candles; session state is loaded from disk.** Keep these
   two mechanisms separate and do not try to infer session state from the journal — the
   journal is append-only and may be mid-write when the process died.
5. On the first candle after a resume, **reconcile against the broker**: if the engine
   thinks it is flat but the broker reports a position, alert and do not trade.

---

## 4b. `r_model_broken` — v2

`risk_rupees` is computed as `r_points × ref_delta × lot_size`. That is a *model*. On
an option the realised loss also absorbs IV movement, gamma, and the spread on the way
out — and on a stop-out, all three move against you at once.

If real losses are systematically 1.3R when the model says 1.0R, then:
- the `−2R` daily cap is actually a `−2.6R` cap,
- every `r_realised` in the journal is wrong,
- and the P9 report will conclude the strategy failed when the arithmetic underneath it
  failed.

```python
if len(losses) >= 10 and median(abs(r) for r in recent_losses) > 1.2:
    block("r_model_broken")
```

Latches for the day and raises an alert. The correct response is to recalibrate delta
measurement and slippage — **not** to widen the risk budget so the numbers match.

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

### Expected time distribution — v2.2, restated on the correct baseline

v1 said *"roughly 70% WATCH / 25% ALERT / 5% IN"* — a target that leaves out `BLOCKED`
entirely, and `BLOCKED` is always the largest bucket. The dry run measured:

```
BLOCKED  52%      ← time windows alone block 182 of 375 candles
WATCH    28%
ALERT    20%
IN        0%
```

The v1 target was unreachable by construction, and worse, the accompanying warning
(*"if ALERT exceeds ~40% the system is about to over-trade"*) was calibrated against a
baseline that does not exist. Measured against the whole session, ALERT would never
approach 40%, so the alarm could never fire.

**Measure the split over non-BLOCKED candles only:**

```
of the candles the engine is allowed to act on:
    WATCH ~60%   ALERT ~35%   IN ~5%

warning threshold: ALERT > 60% of non-BLOCKED candles for several days
                   → the level book is too crowded; check the 8-cap and grading
```

Print **both** numbers in the daily report — the whole-session split shows how much of
the day the guards remove, and the non-BLOCKED split shows whether the level book is
sane. They answer different questions and v1 conflated them.

**v2 — v1 could not have hit this distribution.** With round numbers eligible to
trigger ALERT on a 100-point grid and `alert_distance = 20`, price is within 20 points
of *some* 100-mark for 40% of the session by construction — before a single real level
is added. The target of 25% ALERT was unreachable and the "system is about to start
over-trading" warning would have been permanently true. Fixed by
`round_numbers_can_trigger_alert: false` (spec 03 §6).

### v2 — how much time is actually tradeable, counted honestly

Worth writing down, because it is smaller than it feels and it drives the sample-size
problem in spec 09:

```
session                                   375 min
− outside the two windows (0915-0930,
  1115-1330, 1445-1530)                  −195 min
= inside windows                          180 min
− last 3 min of each 15m candle (~20%)    −36 min
= eligible entry minutes                 ~144 min/day
```

Of those ~144 minutes the engine must also be in ALERT (~25%), which leaves roughly
**35 minutes a day** in which a signal can occur at all. Three trades a day is a cap
that will rarely bind; the realistic outcome remains most days at zero trades. This is
the design working as intended — but it is also why six months of single-instrument
data cannot validate anything (CLAUDE.md §8).

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
| `test_event_blackout_full_day` | RBI MPC date in events.yaml → every candle rejects `event_blackout` |
| `test_event_blackout_partial` | Bank results date, 10:40 → blocked; 11:30 → allowed |
| `test_missing_calendar_refuses_start` | events.yaml absent → engine refuses to start |
| `test_stale_calendar_refuses_start` | `last_updated` 45 days old → refuses to start |
| `test_gap_kills_carried_levels` | 0.6% gap → all TURN/LAUNCH/BREAK dead, PDH/PDL/PDC alive |
| `test_gap_blocks_until_1000` | Gap day 09:45 → `gap_regime`; 10:15 → allowed |
| `test_small_gap_no_regime_change` | 0.2% gap → levels survive, normal windows |
| `test_session_state_survives_restart` | 2 fills → kill process → restart → `trades_taken == 2` |
| `test_fresh_session_requires_flag` | State file for today exists, no flag → refuses to start |
| `test_no_silent_counter_reset` | Static check: no assignment of `trades_taken = 0` outside the explicit fresh-session path |
| `test_broker_position_reconcile_on_resume` | Engine flat, broker holds a position → alert, no trading |
| `test_r_model_broken_latches` | 10 losses with median 1.35R → `r_model_broken`, latched |
| `test_stale_cost_model_refuses_start` | `costs.yaml last_verified: null` → refuses to start |
