# 02 — DATA CONTRACT

All models are `@dataclass(frozen=True)`. All prices are `Decimal`. All timestamps are
timezone-aware `Asia/Kolkata`. Bank Nifty index ticks in 0.05 but for level maths we
work in whole points; keep `Decimal` anyway to avoid float drift in P&L.

---

## Candle

```python
@dataclass(frozen=True)
class Candle:
    symbol: str                 # "BANKNIFTY-I" (index/future) — never an option
    tf: Literal["1m", "5m", "15m"]
    open_time: datetime         # inclusive
    close_time: datetime        # exclusive; candle is visible only after this
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    volume: int | None          # None for spot index
    synthetic: bool = False     # forward-filled gap; excluded from all detection

    # ---- derived, computed once at construction ----
    @property
    def range(self) -> Decimal:        return self.h - self.l
    @property
    def body(self) -> Decimal:         return abs(self.c - self.o)
    @property
    def upper_wick(self) -> Decimal:   return self.h - max(self.o, self.c)
    @property
    def lower_wick(self) -> Decimal:   return min(self.o, self.c) - self.l
    @property
    def is_bull(self) -> bool:         return self.c > self.o
    @property
    def body_top(self) -> Decimal:     return max(self.o, self.c)
    @property
    def body_bottom(self) -> Decimal:  return min(self.o, self.c)

    @property
    def close_position(self) -> Decimal:
        """0.0 = closed at low, 1.0 = closed at high. The single most informative
        number on a candle. Guard against range == 0."""
        if self.range == 0: return Decimal("0.5")
        return (self.c - self.l) / self.range

    @property
    def close_third(self) -> Literal["top", "mid", "bottom"]:
        cp = self.close_position
        return "top" if cp >= Decimal("0.66") else "bottom" if cp <= Decimal("0.34") else "mid"
```

**Invariants (assert at construction):** `l <= o,c <= h`; `close_time > open_time`;
`close_time - open_time` matches `tf`.

---

## Level

```python
class LevelKind(StrEnum):
    TURN   = "turn"      # price arrived, stopped, reversed  → swing pivot / wick cluster
    LAUNCH = "launch"    # price sat, then left fast         → base before an impulse
    BREAK  = "break"     # a level was broken by body close  → the break point itself
    ANCHOR = "anchor"    # externally given: PDH/PDL/PDC, opening range, round numbers

class LevelSide(StrEnum):
    SUPPORT = "support"; RESISTANCE = "resistance"; AXIS = "axis"   # AXIS = post-break, works both ways

class Grade(StrEnum):
    A = "A"; B = "B"; C = "C"

@dataclass(frozen=True)
class Level:
    id: str
    kind: LevelKind
    side: LevelSide
    born_at: datetime
    born_tf: Literal["1m", "5m", "15m", "1d"]

    # A level is a ZONE, never a line — see spec 03 §4
    body_edge: Decimal      # the real level: where the decision was made. ENTRY reference.
    wick_tip: Decimal       # the extreme. STOP reference. Sweeps travel to here.

    departure_speed: Decimal   # points moved in the 3 candles after birth, ÷ ATR at birth
    touches: int = 0
    last_touch_at: datetime | None = None
    grade: Grade = Grade.C
    alive: bool = True
    death_reason: str | None = None

    @property
    def zone_low(self) -> Decimal:  return min(self.body_edge, self.wick_tip)
    @property
    def zone_high(self) -> Decimal: return max(self.body_edge, self.wick_tip)
    @property
    def pocket(self) -> Decimal:
        """Sweep pocket width — the space where stops are parked."""
        return abs(self.wick_tip - self.body_edge)
```

---

## StructureState

```python
@dataclass(frozen=True)
class Swing:
    time: datetime
    price: Decimal
    kind: Literal["high", "low"]
    tf: Literal["1m", "5m"]
    confirmed: bool          # a swing is only real once N bars have passed on its right

@dataclass(frozen=True)
class StructureState:
    tf: Literal["1m", "5m"]
    last_swing_high: Swing | None
    last_swing_low: Swing | None
    prev_swing_high: Swing | None
    prev_swing_low: Swing | None
    last_bos: BreakOfStructure | None       # direction + level + time
    trend: Literal["up", "down", "none"]
    regime: Literal["trending", "ranging", "transition"]
    impulse_atr: Decimal        # avg range of last impulse leg — for speed comparison
    pullback_atr: Decimal       # avg range of current pullback — see spec 04 §5
```

---

## StateBoard — the 8 things a trader holds in working memory

```python
@dataclass(frozen=True)
class StateBoard:
    # 1
    day_high: Decimal; day_high_at: datetime
    day_low:  Decimal; day_low_at:  datetime
    # 2
    opening_range_high: Decimal | None      # 09:15–09:30, set at 09:30
    opening_range_low:  Decimal | None
    # 3
    pdh: Decimal; pdl: Decimal; pdc: Decimal
    # 4
    last_swing_high_5m: Swing | None
    last_swing_low_5m:  Swing | None
    # 5
    active_level: Level | None              # nearest live level to current price
    distance_to_active: Decimal | None      # signed, in points
    # 6
    last_decision_candle: Candle | None     # most recent impulse ≥ impulse_atr_mult × ATR
    last_decision_origin: Level | None      # its LAUNCH level
    # 7
    control: Literal["buyers", "sellers", "none"]   # from last BOS on 5m
    # 8
    regime: Literal["trending", "ranging", "transition"]

    # context, not part of the 8 but needed downstream
    atr_1m: Decimal; atr_5m: Decimal
    levels_above: list[Level]     # sorted ascending, nearest first
    levels_below: list[Level]     # sorted descending, nearest first
```

**The board must be reconstructible from candles alone.** No hidden accumulated state.
This makes replay deterministic and lets you snapshot/restore mid-session.

---

## Guards and Mode

```python
@dataclass(frozen=True)
class GuardResult:
    passed: bool
    failed_gate: str | None      # "time_window" | "volatility" | "session_limit" | ...
    detail: str | None

class Mode(StrEnum):
    BLOCKED = "blocked"   # a guard failed; nothing may happen
    WATCH   = "watch"     # no level near; engine idles
    ALERT   = "alert"     # price within alert_distance of a live level
    IN      = "in"        # position open
```

---

## Setup candidate → Signal

```python
@dataclass(frozen=True)
class SetupCandidate:
    setup: Literal["A_flip_retest", "B_sweep_reclaim", "C_range_break_retest"]
    direction: Literal["long", "short"]
    trigger_level: Level          # the level this trade is ABOUT — invalidation reference
    trigger_candle: Candle
    entry_ref: Decimal            # index price the entry is based on
    extreme: Decimal              # wick tip / swing point the stop hides behind
    evidence: dict[str, Any]      # every intermediate value, for the journal

@dataclass(frozen=True)
class Signal:
    candidate: SetupCandidate
    entry_index: Decimal
    sl_index: Decimal
    r_points: Decimal
    t1_index: Decimal
    t2_index: Decimal
    nearest_obstacle: Level
    space_points: Decimal
    space_ratio: Decimal          # space ÷ r_points
    option: OptionOrder
    lots: int
    risk_rupees: Decimal
    created_at: datetime

@dataclass(frozen=True)
class Rejection:
    gate: str                     # EXACTLY which gate failed — see below for the list
    detail: str
    candidate: SetupCandidate | None
    computed: dict[str, Any]      # every value computed before the failure
    at: datetime
```

### Canonical gate names — use these strings verbatim, nothing else

```
time_window          volatility_floor      volatility_ceiling
feed_gap             warmup                session_max_trades
session_consec_loss  session_max_loss      no_live_level
no_setup             setup_stale           bias_conflict
r_too_tight          r_too_wide            space_insufficient
size_zero            chain_unavailable     duplicate_setup
htf_close_proximity  position_open

── v2 additions ──
cost_excessive       event_blackout        gap_regime
stale_cost_model     r_model_broken
```

A fixed vocabulary is what makes the rejection log analysable. Never invent a new
gate string ad hoc — add it to this list first.

### The v2 gates, and why each exists

| Gate | Fires when | Why it was added |
|---|---|---|
| `cost_excessive` | modelled round-trip cost > 25% of `R_premium`, **or** `R_premium < 8 ×` observed spread | Bank Nifty has monthly options only since Nov 2024. Round-trip cost on a 25-index-point R is 44–64% of R, which pushes break-even win rate to ~50%. Cost has to be checked against the live quote *before* the order, not reported after. |
| `event_blackout` | today is in `config/events.yaml` | ~75% of the index is five stocks. On their results days, and on RBI policy days, the level structure does not hold. This is a calendar lookup, not news interpretation. |
| `gap_regime` | open gapped > 0.40% and it is before 10:00 | Every carried 1m/5m level assumes price continuity. After a gap those levels describe a market that no longer exists. Only PDH/PDL/PDC and the opening range survive. |
| `stale_cost_model` | `costs.yaml last_verified` is null or > 90 days old | A stale cost model produces a profitable-looking backtest and an unprofitable account. Refusing to start is the correct response. |
| `r_model_broken` | median realised loss > 1.2R over the last 10 losing trades | `risk_rupees` is computed from a *modelled* delta. If real losses systematically exceed 1.0R — IV crush, gamma, spread on the way out — then the −2R daily cap is not capping at −2R and every R number in the journal is wrong. Latches for the day. |

`r_model_broken` deserves emphasis: it is the check that tells you the difference
between "the strategy lost" and "the arithmetic underneath the strategy is wrong."
Without it those two look identical in the P&L.

---

## Option order and fill

```python
@dataclass(frozen=True)
class OptionOrder:
    tradingsymbol: str            # e.g. "BANKNIFTY26AUG57100CE"
    strike: int
    opt_type: Literal["CE", "PE"]
    expiry: date
    lot_size: int
    lots: int
    side: Literal["BUY"]          # BUY only — see CLAUDE.md §6
    ref_premium: Decimal          # premium observed at signal time
    ref_delta: Decimal            # used for sizing; see spec 08

@dataclass(frozen=True)
class Fill:
    order_id: str
    at: datetime
    premium: Decimal              # after modelled slippage
    lots: int
    slippage_points: Decimal
    charges: Decimal              # full, itemised in journal
    is_paper: bool = True
```

---

## Position and Trade

```python
@dataclass
class Position:                   # mutable — the only mutable model
    signal: Signal
    entry_fill: Fill
    remaining_lots: int
    sl_index: Decimal             # moves to breakeven after T1
    t1_done: bool
    highest_favourable_index: Decimal
    candles_since_entry: int
    candles_since_progress: int   # drives the time stop

@dataclass(frozen=True)
class Trade:                      # the completed round trip — the journal row
    signal: Signal
    entry: Fill
    exits: list[Fill]
    exit_reason: Literal["t1_t2", "trail", "hard_sl", "invalidation", "time_stop", "eod"]
    gross_pnl: Decimal
    charges_total: Decimal
    net_pnl: Decimal              # THE number. gross is never displayed alone.
    r_realised: Decimal           # net_pnl ÷ risk_rupees
    rules_followed: bool          # see spec 09 — auto-computed, not self-reported
    rule_violations: list[str]
```

---

## Decision — what `on_candle` returns

```python
Decision = Signal | Rejection | NoOp | ExitOrder

@dataclass(frozen=True)
class NoOp:
    mode: Mode
    at: datetime
    board_digest: str      # short hash of the board, so the journal can compress
```

Every decision is journalled. `NoOp` compactly, everything else in full.
