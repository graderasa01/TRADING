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

```yaml
options:
  strike_step: 100
  moneyness: "ATM"             # ATM only at this stage
  expiry_preference: "nearest_weekly"
  min_open_interest: <set from observed data>
  max_spread_pct: 1.5          # (ask-bid)/mid × 100   HYPOTHESIS
  min_depth_lots: 20           # top-of-book must cover our size
  avoid_expiry_day_last_hours: true
```

Rules:

1. **ATM only.** `strike = round(index_price / 100) * 100`.
   OTM is tempting (cheaper, higher %) but its delta is low and unstable, its spread is
   proportionally huge, and a 25-point index move can leave the premium unchanged. The
   sizing maths in spec 07 assumes a stable, measurable delta — only ATM provides that.
2. **BUY only.** Long CE for a long signal, long PE for a short signal. No selling, no
   spreads, no hedges (CLAUDE.md §6).
3. **Nearest weekly expiry**, resolved from the instrument master — never a hardcoded
   weekday. Exchange expiry schedules have changed before.
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

- Windows narrow to 10:00–14:00 (spec 05)
- Size × 0.5 (spec 07)
- Delta must be measured, never defaulted
- After 14:00, no new positions; manage only

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

```
Any OHLC mismatch > 0.05 → log LOUDLY and mark the day's paper results SUSPECT.
```

Without this check you can paper-trade for a month on subtly wrong candles and never
know. Run it every single day.

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

---

## 6. Tests that must pass

| Test | Expectation |
|---|---|
| `test_strike_is_atm` | Index 57,142 → strike 57,100 |
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
