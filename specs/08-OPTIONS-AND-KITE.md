# 08 — OPTIONS LAYER, KITE ADAPTER, PAPER BROKER

---

# PART 1 — THE CENTRAL RULE

```
SIGNAL ON THE INDEX.  EXECUTE ON THE OPTION.  MONITOR THE STOP ON THE INDEX.
```

Option premium is a distorted, second-hand view of the index: it carries IV, theta, a
wide spread and thin depth away from ATM. Price action read on a premium chart produces
false sweeps, false levels, and stops that trigger on volatility crush rather than on
price. Everything in specs 03–07 operates on Bank Nifty index/futures candles.

**The stop is an index level.** When the index touches `sl_index`, we exit the option at
whatever the market gives us. We never place a premium-based stop, because a premium
stop can trigger while the index thesis is perfectly intact.

---

# PART 2 — STRIKE SELECTION

```python
def select_strike(index_price: Decimal, direction, expiry, chain) -> OptionOrder:
```

## ⚠ v2 — THE INSTRUMENT CHANGED UNDER THIS SPEC. READ FIRST.

Two facts that invalidate parts of v1 as written:

**1. Bank Nifty has no weekly options.** NSE discontinued weekly Nifty Bank derivatives
on **20 November 2024**, following the SEBI framework limiting each exchange to weekly
contracts on a single benchmark index. NSE kept Nifty 50 weeklies. **Bank Nifty is
monthly only, expiring the last Tuesday of the month.** v1's
`expiry_preference: "nearest_weekly"` would resolve to nothing, or worse, to a Nifty
contract. Every "weekly expiry day" rule in v1 (spec 05's expiry window, spec 07's
size multiplier) now applies to **one day a month, not four.**

That is mostly good news — the most hostile regime for a mechanical price-action system
now occurs 12 times a year instead of 50. But on that one day it matters *more*, because
a full month of open interest unwinds into it rather than a week's.

**2. Lot size is 30**, revised down from 35 with effect from the January 2026 series.
It was 15 before November 2024. v1's worked example in spec 07 used 15. **Read it from
the instrument master at startup and assert against config — do not trust any literal
in this repo, including this paragraph.** It has changed three times in two years.

**3. The consequence that matters most.** A monthly ATM premium is 3–4× a weekly's, and
the round-trip cost on a 25-index-point R works out to 44–64% of R. See spec 07 §1.6 —
this is why the cost gate exists and why it is not negotiable.

---

```yaml
options:
  strike_step: 100
  moneyness: "ATM"             # ATM only at this stage
  expiry_preference: "nearest_monthly"      # v2 — weeklies do not exist
  expiry_weekday_expected: "tuesday"        # assertion only; trust the master
  lot_size: 30                              # v2 — VERIFY at startup
  roll_to_next_month_days_before: 2
  min_open_interest: <set from observed data>
  max_spread_pct: 1.5          # (ask-bid)/mid × 100   HYPOTHESIS
  min_depth_lots: 20           # top-of-book must cover our size
  avoid_expiry_day_last_hours: true
  log_capital_deployed: true   # v2
```

Rules:

1. **ATM only.** `strike = round(index_price / 100) * 100`.
   OTM is tempting (cheaper, higher %) but its delta is low and unstable, its spread is
   proportionally huge, and a 25-point index move can leave the premium unchanged. The
   sizing maths in spec 07 assumes a stable, measurable delta — only ATM provides that.
2. **BUY only.** Long CE for a long signal, long PE for a short signal. No selling, no
   spreads, no hedges (CLAUDE.md §6).
3. **Nearest monthly expiry**, resolved from the instrument master — never a hardcoded
   weekday. Exchange expiry schedules have changed before, and did: Bank Nifty lost
   weeklies entirely in Nov 2024 and the monthly expiry day moved to Tuesday.
   `expiry_weekday_expected` is an assertion that alerts on mismatch, not a rule.
   **Stop trading the expiring series 2 days before expiry and roll to the next month**
   — the last two days are where a monthly contract's gamma and pin behaviour distort
   the delta the sizing depends on.
4. **Liquidity gate before the order:** if `spread_pct > max_spread_pct` or
   `depth < min_depth_lots`, return `Rejection("chain_unavailable")`. An illiquid strike
   turns a modelled 3-point slippage into 15.

## Delta

```python
ref_delta = measure_delta(chain, strike, index_price)
```

Preferred: derive empirically from recent 1m moves —
`Δpremium / Δindex` regressed over the last 30 minutes. Fall back to `0.5` for ATM only
if the measurement is unavailable, and **flag it in the journal** when the fallback is
used. Never silently assume 0.5; on expiry day ATM delta moves sharply and the sizing
would be wrong precisely when it matters most.

## Expiry-day handling

Now **one day a month** (last Tuesday), not four. Rules unchanged, importance
concentrated:

- Windows narrow to 10:00–14:00 (spec 05)
- Size × 0.5 (spec 07)
- Delta must be measured, never defaulted
- After 14:00, no new positions; manage only
- **v2:** the two days *before* monthly expiry, the engine has already rolled to the
  next series (`roll_to_next_month_days_before: 2`), so it is trading a ~30-day option
  on expiry day, not a 0-DTE one. This removes most of the pin risk v1 was worried
  about — at the cost of a lower delta and a wider spread on the further contract.
  **Measure both; do not assume the roll is free.**

---

# PART 3 — KITE CONNECT ADAPTER

`src/feed/kite_feed.py` and `src/broker/paper.py`. The adapter's only job is to produce
`Candle` objects and quote snapshots. It contains **no trading logic**.

## 3.1 Connection

- `kiteconnect` official Python client
- Access token refreshes daily — the runner must handle the login flow and fail loudly
  at startup if the token is invalid. Never start a session with a stale token.
- Credentials from environment variables only. **No API key or secret in the repo, in
  config files, or in logs.** Add a pre-commit check for this.

## 3.2 Live data

Subscribe in `FULL` mode to:
- Bank Nifty index (or the current-month future — pick one and keep it consistent
  between replay data and live, or the levels will not match)
- The selected ATM CE and PE (subscribe on entry to ALERT, unsubscribe on return to WATCH)

### Tick → 1m candle
The adapter builds 1m candles from ticks itself rather than polling historical:

```python
class CandleBuilder:
    """Accumulates ticks into a 1m OHLC. Emits on minute rollover, NOT on tick count."""
```

- Emit the candle for minute `M` when the first tick with timestamp `>= M+1min` arrives,
  **or** when a wall-clock timer fires at `M+1min+2s` (whichever first). The timer
  handles thin minutes with no ticks.
- A minute with zero ticks → `synthetic=True` candle at the previous close.
- Two or more consecutive synthetic minutes → `FeedGapError` (spec 01 §3).

### Reconciliation (mandatory)
At `15:35` each day, fetch the official 1m historical candles for the session and diff
them against the locally built candles.

The principle is right and non-negotiable: **without this check you can paper-trade for
a month on subtly wrong candles and never know.** Run it every single day.

#### v2 — but v1's threshold would have failed every day, which is worse than no check

```
v1:  Any OHLC mismatch > 0.05 → mark the day SUSPECT
```

Live 1m candles are built from **websocket snapshots** — Kite streams index quotes at
roughly one per second, not every tick. The true high or low of a minute frequently
occurs between snapshots. On an index that can move 40 points in a minute, missing the
extreme by more than 0.05 points is not an anomaly, it is the expected behaviour of a
snapshot feed.

So v1 would mark **every single day SUSPECT**. An alarm that always fires is an alarm
you learn to ignore, and this is the one check that validates everything else.

```yaml
feed:
  reconcile_tolerance_points: 0.05      # the ideal, kept for reference
  reconcile_tolerance_atr_mult: 0.05    # effective = max(points, mult × ATR)
  reconcile_baseline_days: 5
  reconcile_max_mismatch_rate: 0.02     # >2% of candles mismatching → SUSPECT
```

**Calibrate before you judge.** Run 5 days measuring only — log the distribution of
your feed's OHLC deviation versus the official candles, then set the threshold from
that distribution (e.g. the 99th percentile). A threshold derived from your actual feed
is a real check; a threshold picked from a round number is theatre.

Judge on the **mismatch rate**, not on any single candle. One missed extreme is a
snapshot feed doing what snapshot feeds do. Two percent of candles drifting is a
broken builder.

#### The deeper problem this exposes, which is not solved

```yaml
replay_source: "kite_historical"    # what P9 validates on
live_source:   "tick_built"         # what actually trades
```

These are **two different data sources describing the same minute.** Design goal #1
(spec 01 §1) is that "the paper/replay result must be achievable live." That goal is
only as true as the gap between these two sources, and v1 never measured it.

P8 must quantify it explicitly: for the same session, run the engine on tick-built
candles and on the official historical candles, and **diff the decision streams.** Not
the P&L — the decisions. If the two produce different signals on the same day, the P9
number does not describe the live system, and the report must say so in the header.

This is unlikely to be zero. The honest goal is to measure it, bound it, and state it —
not to claim it away.

## 3.3 Rate limits and resilience

- Respect Kite's published rate limits; centralise all REST calls behind one throttled
  client. Confirm the current limits from the official docs — they change.
- Websocket disconnect → exponential backoff reconnect. While disconnected:
  `BLOCKED` for new entries. If a position is open, **alert loudly** — a paper position
  is fine, but the same code path live would be dangerous, and the habit should be built
  now.
- After reconnect, require 2 clean candles before leaving `BLOCKED`.

---

# PART 4 — PAPER BROKER

`PaperBroker` implements the same `Broker` interface a future live broker would. This is
what makes the eventual live switch a one-line change — and what makes the paper results
meaningful.

## 4.1 Fill model

**Entries (market on candle close):**
```python
fill_premium = ask + entry_slippage        # we cross the spread, always
```
Never fill at mid. Never fill at the last traded price. We are a market taker.

**Exits:**
```python
fill_premium = bid - exit_slippage
```

**Stop fills:** when the index touches `sl_index`, model the exit as
`bid - exit_slippage - stop_gap_extra`. Stops fill worse than limits; a paper engine
that fills stops perfectly will overstate results by exactly the amount that matters.

```yaml
slippage:
  entry_points: 2.0            # premium points   HYPOTHESIS — calibrate from live quotes
  exit_points: 2.0             # HYPOTHESIS
  stop_gap_extra: 1.5          # HYPOTHESIS
  high_vol_multiplier: 2.0     # applied when atr_1m > 40
```

**Calibrate these from real observed quotes during paper trading.** Log the actual
bid/ask at every signal; after two weeks, replace the hypotheses with measured values.
Until then every P&L number carries a large error bar and should be described that way.

## 4.2 Cost model

`config/costs.yaml`, with a `last_verified: YYYY-MM-DD` field.

```yaml
# ⚠ THESE RATES CHANGE. Verify against the broker's current charge list and the
# exchange circulars before trusting any P&L number. Do not treat as settled fact.
costs:
  last_verified: null          # ← must be filled in before the first paper session
  brokerage_per_order: ...     # flat per executed order for options
  stt: ...                     # on the sell side of premium for option buying
  exchange_txn_charge: ...     # % of premium turnover
  sebi_charges: ...
  stamp_duty: ...              # buy side
  gst_pct: 18                  # on (brokerage + txn charges + sebi)
```

Compute charges **per order**, not per round trip — a partial exit at T1 plus a final
exit is three orders, not two.

```python
def total_charges(orders: list[Fill]) -> Decimal
```

### The rule that matters
**`gross_pnl` is never displayed anywhere on its own.** Reports, logs and the daily
summary show `net_pnl`. Add a lint check for `gross` appearing in any formatted output.

### Cost drag reality
At a ~25-point index stop with ATM delta ≈ 0.5, R is roughly 12 premium points. A
4-point round-trip slippage plus charges consumes a meaningful fraction of that. This is
the arithmetic behind the "fewer, larger trades" design and behind the 3-trade cap. The
report must print **cost drag as a percentage of gross** every day so this stays visible.

## 4.3 Paper broker interface

```python
class Broker(Protocol):
    def place_entry(self, order: OptionOrder) -> Fill | None: ...
    def place_exit(self, position: Position, lots: int, reason: str) -> Fill: ...
    def quote(self, tradingsymbol: str) -> Quote: ...

class PaperBroker(Broker):
    """No network writes. Reads live quotes from KiteFeed, simulates fills."""
```

`place_entry` returns `None` if the candidate could not be filled (spread blew out,
no depth). An unfilled signal is journalled and **does not consume a trade slot**.

---

# PART 5 — SAFETY

Because the next phase after this one is live orders, build these habits now:

| Guard | Implementation |
|---|---|
| No live order path exists | `src/broker/live.py` must not exist. CI check. |
| Paper marker on every artefact | Every log line, journal row and report header carries `MODE=PAPER` |
| Credentials never logged | Redaction filter on the logger; pre-commit secret scan |
| Kill file | If `./HALT` exists, the engine refuses to start and exits any open position |
| Startup confirmation | Print the config digest, risk-per-trade, and `PAPER` banner; require an explicit `--i-understand-this-is-paper` flag to run |

**Before any live phase is even planned:** the current SEBI and exchange requirements
for retail algorithmic order placement — including any registration or broker approval
needed for automated strategies — must be confirmed directly with Zerodha and with the
current regulations. That is a prerequisite, not a formality, and it is outside what
this spec covers.

### v2 — the regulatory picture as of August 2026, to be re-confirmed with the broker

SEBI's retail algo trading framework became **fully mandatory on 1 April 2026**. The
parts that touch this design, as currently understood — **verify each with Zerodha
before building against it, this area has moved repeatedly and deadlines were extended
more than once**:

| Requirement | What it means here |
|---|---|
| **10 orders/second threshold** | Below it, per exchange per calendar second, no strategy registration is required. This system places at most a handful of orders a day, so it sits far below. Design so it can never burst above — a retry loop is the realistic way to trip this accidentally. |
| **Algo ID on every order** | Orders placed via API must carry the exchange-assigned identifier / tag. No longer optional. Plumb this through `OptionOrder` now, even in paper, so it is not retrofitted later. |
| **Static IP whitelisting** | API access requires a static IP. Home broadband on a dynamic IP, mobile hotspots and laptop-on-café-wifi will not work. **This is a real infrastructure decision** — a small cloud VM with a static IP, in an Indian region for latency, is the usual answer. Budget for it. |
| **OAuth only, 2FA per session, daily session expiry** | The access token cannot be kept alive across days. The runner must handle a daily login and **fail loudly at startup on a stale token** — which spec 08 §3.1 already requires. |
| **Broker-registered strategies** | Brokers had to register API-based algo products with the exchanges. Whether *your* use case needs a plain-English strategy description filed with the compliance desk depends on the broker and on how they classify it. **Ask them directly, in writing, before P8.** |

Two practical consequences for the build order:

1. **The static IP requirement affects the paper phase too**, because P8 runs live Kite
   data. Sort out the hosting before P8, not before live.
2. **Ask the compliance question early.** The answer determines whether an automated
   live phase is a configuration change or a months-long approval process. Finding that
   out after P9 would be an expensive way to learn it.

None of this changes a single trading rule. It changes where the code runs and what
paperwork precedes it — which is exactly the kind of thing that stalls a project at the
last step if it is left to the last step.

---

## 6. Tests that must pass

| Test | Expectation |
|---|---|
| `test_strike_is_atm` | Index 57,142 → strike 57,100 |
| `test_expiry_is_monthly_not_weekly` | Chain resolution returns the last-Tuesday monthly contract; no weekly Bank Nifty contract is ever selected |
| `test_lot_size_read_from_master` | Config says 30, master says 25 → **master wins**, alert raised |
| `test_rolls_two_days_before_expiry` | 2 days before monthly expiry → next series selected |
| `test_reconcile_tolerance_is_atr_relative` | ATR 40, deviation 1.5 pts → PASS; deviation 4 pts → mismatch |
| `test_reconcile_judges_on_rate_not_single_candle` | 3 mismatches in 375 candles → PASS; 12 → SUSPECT |
| `test_algo_id_present_on_every_order` | Every `OptionOrder` carries a non-empty tag/algo_id field |
| `test_order_rate_below_threshold` | No code path can emit >10 orders in one second, including retries |
| `test_buy_only` | No code path produces a SELL entry |
| `test_illiquid_strike_rejected` | Spread 3% → `chain_unavailable` |
| `test_delta_measured_not_assumed` | Fallback to 0.5 sets a journal flag |
| `test_signal_never_reads_premium_candles` | Static check: `setups/`, `levels/`, `structure/` never import the options module |
| `test_stop_is_index_based` | Premium halving with the index unchanged does not trigger an exit |
| `test_entry_fills_at_ask` | Entry fill > mid, always |
| `test_exit_fills_at_bid` | Exit fill < mid, always |
| `test_stop_fill_worse_than_limit` | Stop fill includes `stop_gap_extra` |
| `test_charges_per_order_not_round_trip` | 3 orders → 3 brokerage charges |
| `test_gross_never_displayed` | Lint: no formatted output contains `gross` |
| `test_unfilled_signal_no_slot` | Failed fill → `trades_taken` unchanged |
| `test_reconciliation_flags_mismatch` | Injected 0.5-point diff → day marked SUSPECT |
| `test_halt_file_stops_engine` | `./HALT` present → refuses to start |
| `test_no_live_broker_module` | `src/broker/live.py` does not exist |
