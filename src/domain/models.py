"""
Domain models — spec 02, the data contract.

Every rule in this repo is written in terms of these types, so their invariants are
where the system's honesty lives. Three rules from CLAUDE.md §5 are enforced here
rather than documented:

  * `frozen=True` everywhere. A level that can be mutated in place is a level whose
    history cannot be trusted, and the journal's job is to explain past decisions.
  * `Decimal` for every price. Never float. `Decimal(repr(x))` at the loader boundary
    (DECISIONS.md D-014) — never `Decimal(float)`, which expands the binary expansion.
  * Timezone-aware `Asia/Kolkata` timestamps. A naive datetime in a trading system is
    a bug waiting for a DST change or a server move.

Invariants are asserted at construction, not checked by the caller. `prototype/gen.py`
produced two candles with `close > high` — the two deliberately planted sweeps, the
flagship trades of the whole dry run — and nothing noticed for a full session. That is
the class of error `__post_init__` exists to stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

Timeframe = Literal["1m", "5m", "15m"]
BornTimeframe = Literal["1m", "5m", "15m", "1d"]

TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15}

ZERO = Decimal("0")
HALF = Decimal("0.5")


class InvariantError(ValueError):
    """A domain object was constructed in a state that cannot exist in a market."""


def to_decimal(value: Any) -> Decimal:
    """The only sanctioned float → Decimal conversion (D-014).

    `Decimal(57434.05)` is 57434.04999999999745341...; `Decimal(repr(57434.05))` is
    exactly `57434.05`. Since every price reaching this code came from JSON parsed to
    float64, `repr` — the shortest string that round-trips — recovers the decimal the
    exchange actually published.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


# ─────────────────────────────────────────────────────────────────────────────
# Candle
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    tf: Timeframe
    open_time: datetime          # inclusive
    close_time: datetime         # exclusive — visible to the engine only after this
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    volume: int | None = None    # None for a spot index
    synthetic: bool = False      # forward-filled gap; excluded from all detection

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise InvariantError(f"naive datetime on {self.symbol} {self.tf} {self.open_time}")
        if self.close_time <= self.open_time:
            raise InvariantError(f"close_time {self.close_time} <= open_time {self.open_time}")
        expected = timedelta(minutes=TF_MINUTES[self.tf])
        if self.close_time - self.open_time != expected:
            raise InvariantError(
                f"{self.tf} candle spans {self.close_time - self.open_time}, expected {expected}")
        if not (self.l <= self.o <= self.h and self.l <= self.c <= self.h):
            raise InvariantError(
                f"OHLC impossible at {self.open_time:%Y-%m-%d %H:%M}: "
                f"o={self.o} h={self.h} l={self.l} c={self.c}")

    # ── derived ──
    @property
    def range(self) -> Decimal:
        return self.h - self.l

    @property
    def body(self) -> Decimal:
        return abs(self.c - self.o)

    @property
    def upper_wick(self) -> Decimal:
        return self.h - max(self.o, self.c)

    @property
    def lower_wick(self) -> Decimal:
        return min(self.o, self.c) - self.l

    @property
    def is_bull(self) -> bool:
        return self.c > self.o

    @property
    def body_top(self) -> Decimal:
        return max(self.o, self.c)

    @property
    def body_bottom(self) -> Decimal:
        return min(self.o, self.c)

    @property
    def close_position(self) -> Decimal:
        """0.0 = closed at the low, 1.0 = at the high. The most informative number
        on a candle. A zero-range candle has no position; 0.5 is the honest answer."""
        if self.range == ZERO:
            return HALF
        return (self.c - self.l) / self.range

    @property
    def close_third(self) -> Literal["top", "mid", "bottom"]:
        cp = self.close_position
        if cp >= Decimal("0.66"):
            return "top"
        if cp <= Decimal("0.34"):
            return "bottom"
        return "mid"

    @property
    def session_date(self) -> date:
        return self.open_time.date()


# ─────────────────────────────────────────────────────────────────────────────
# Level
# ─────────────────────────────────────────────────────────────────────────────
class LevelKind(StrEnum):
    TURN = "turn"        # price arrived, stopped, reversed
    LAUNCH = "launch"    # price sat, then left fast
    BREAK = "break"      # a level was broken by a body close
    ANCHOR = "anchor"    # externally given: PDH/PDL/PDC, opening range, round numbers


class LevelSide(StrEnum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    AXIS = "axis"        # post-break, works both ways


class Grade(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class LevelState(StrEnum):
    """Three states, not two — spec 03 §8b.

    DORMANT exists because v1 killed a level *because price travelled away from it*,
    and then had nothing left when price came back. Distance is the reason to remember
    a level, not to forget it.
    """
    ALIVE = "alive"
    DORMANT = "dormant"
    DEAD = "dead"


class ObstacleStrength(StrEnum):
    STRONG = "strong"    # gates the space check and caps T1
    MEDIUM = "medium"    # gates the space check and caps T1
    WEAK = "weak"        # caps T1 only — can never cause a rejection


@dataclass(frozen=True, slots=True)
class Level:
    id: str
    kind: LevelKind
    side: LevelSide
    born_at: datetime
    born_tf: BornTimeframe

    # A level is a ZONE, never a line (spec 03 §4)
    body_edge: Decimal       # where the decision was made. ENTRY reference.
    wick_tip: Decimal        # the extreme. STOP reference. Sweeps travel to here.

    departure_speed: Decimal = ZERO   # computed for EVERY kind (spec 03 §3, Bug 1)
    touches: int = 0
    last_touch_at: datetime | None = None
    in_zone: bool = False    # per-level, persists through dormancy (spec 03 §4, Bug 2)
    grade: Grade = Grade.C
    state: LevelState = LevelState.ALIVE
    death_reason: str | None = None
    armed: bool = False      # has price been on this level's defending side yet?
    is_round_number: bool = False
    evidence_tfs: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.born_at.tzinfo is None:
            raise InvariantError(f"naive born_at on level {self.id}")
        if self.touches < 0:
            raise InvariantError(f"negative touches on level {self.id}")

    @property
    def zone_low(self) -> Decimal:
        return min(self.body_edge, self.wick_tip)

    @property
    def zone_high(self) -> Decimal:
        return max(self.body_edge, self.wick_tip)

    @property
    def pocket(self) -> Decimal:
        """Sweep pocket width — the space where stops are parked. Zero for round
        numbers and anchors; every consumer must survive that (spec 03 §6)."""
        return abs(self.wick_tip - self.body_edge)

    @property
    def alive(self) -> bool:
        return self.state is LevelState.ALIVE


# ─────────────────────────────────────────────────────────────────────────────
# Structure
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Swing:
    time: datetime
    price: Decimal
    kind: Literal["high", "low"]
    tf: Timeframe
    confirmed: bool          # only real once k bars have closed to its right


@dataclass(frozen=True, slots=True)
class BreakOfStructure:
    at: datetime
    direction: Literal["up", "down"]
    broken_swing: Swing
    breaking_candle: Candle
    tf: Timeframe


# ─────────────────────────────────────────────────────────────────────────────
# Guards and modes
# ─────────────────────────────────────────────────────────────────────────────
class Mode(StrEnum):
    BLOCKED = "blocked"
    WATCH = "watch"
    ALERT = "alert"
    IN = "in"


@dataclass(frozen=True, slots=True)
class GuardResult:
    passed: bool
    failed_gate: str | None = None
    detail: str | None = None


# The canonical gate vocabulary — spec 02. A fixed vocabulary is what makes the
# rejection log analysable. Never invent a gate string ad hoc; add it here first.
GATES: frozenset[str] = frozenset({
    "time_window", "volatility_floor", "volatility_ceiling",
    "feed_gap", "warmup", "session_max_trades",
    "session_consec_loss", "session_max_loss", "no_live_level",
    "no_setup", "setup_stale", "bias_conflict",
    "r_too_tight", "r_too_wide", "space_insufficient",
    "size_zero", "chain_unavailable", "duplicate_setup",
    "htf_close_proximity", "position_open",
    # v2
    "cost_excessive", "event_blackout", "gap_regime",
    "stale_cost_model", "r_model_broken",
})


# ─────────────────────────────────────────────────────────────────────────────
# Decisions
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoOp:
    mode: Mode
    at: datetime
    board_digest: str


@dataclass(frozen=True, slots=True)
class Rejection:
    gate: str
    detail: str
    at: datetime
    computed: dict[str, Any] = field(default_factory=dict)
    candidate: Any = None       # SetupCandidate — typed in P3

    def __post_init__(self) -> None:
        if self.gate not in GATES:
            raise InvariantError(
                f"unknown gate {self.gate!r}. Add it to GATES in domain/models.py first "
                f"— an ad-hoc gate string makes the rejection log unanalysable.")


__all__ = [
    "IST", "ZERO", "HALF", "TF_MINUTES", "Timeframe", "BornTimeframe",
    "InvariantError", "to_decimal",
    "Candle", "Level", "LevelKind", "LevelSide", "LevelState", "Grade", "ObstacleStrength",
    "Swing", "BreakOfStructure",
    "Mode", "GuardResult", "GATES", "NoOp", "Rejection",
]
