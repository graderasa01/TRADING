"""
Guards — spec 05 §1. They run before any setup detection, they kill most candles, and
they encode the rules that save the most money.

    0. stale_cost_model     REFUSE TO START (not a rejection)
    1. event_blackout       today is in config/events.yaml
    2. gap_regime           gapped > 0.40% and before 10:00
    3. warmup               ATR needs 14 candles
    4. feed_gap             >= 2 missing minutes recently
    5. time_window          inside an allowed window
    6. htf_close_proximity  last 3 min of a 15m candle   ** SETUP-SCOPED, see below **
    7. volatility_floor     ATR14(1m) >= min
    8. volatility_ceiling   ATR14(1m) <= max
    9. session_max_trades   ┐
   10. session_consec_loss  ├ latching — once tripped, BLOCKED for the day
   11. session_max_loss     │
   12. r_model_broken       ┘
   13. position_open        one position at a time

First failure wins. A guard failure is a first-class, fully-logged outcome.

## Guard 6 is not like the others, and that difference is the worst bug in FINDINGS.md

v1 made `htf_close_proximity` set the mode to `BLOCKED`, which meant the **setup
detector never ran**. The dry run planted a textbook sweep-reclaim at PDL; all six of
Setup B's conditions passed at 09:58; and nothing happened, because 09:58 was minute 13
of a 15-minute candle. *"The engine did not reject that trade. It never saw it."*

Then combine that with Setup B's own staleness rule — reclaim within 2 candles — and:

    sweeps form in the last 3 minutes of a 15m candle   (the trader's own observation)
    entries are blocked for exactly those 3 minutes
    by the time the block lifts, the reclaim is 3+ candles old -> setup_stale

**Setup B was structurally unable to trade at the time Setup B most often forms.**

The v2.2 fix (spec 05 §3b) is that the guard's stated reason — *"HTF candles reverse
their shape in their final minutes"* — applies to **continuation** entries. Setup B is
the trade that profits from exactly that reversal; the wick the guard warns about IS the
sweep. So this guard does **not** change the mode. It records which setups it blocks,
and the setup layer consults it. A and C stay blocked in the tail, which is correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time as dtime
from decimal import Decimal
from typing import Any

from src.config.loader import Config
from src.domain.models import GATES, Candle, Mode
from src.state.session_store import SessionState

LATCHING = frozenset({"session_max_trades", "session_consec_loss",
                      "session_max_loss", "r_model_broken"})


@dataclass(frozen=True, slots=True)
class GuardOutcome:
    """The result of the whole battery for one candle."""
    passed: bool
    failed_gate: str | None = None
    detail: str = ""
    blocked_setups: frozenset[str] = frozenset()
    computed: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.failed_gate is not None and self.failed_gate not in GATES:
            raise ValueError(f"unknown gate {self.failed_gate!r} — add it to GATES first")


@dataclass
class SessionContext:
    """Everything the guards need that is not on the board."""
    day: date
    is_expiry: bool = False
    gap_pct: Decimal | None = None
    consecutive_synthetic: int = 0
    position_open: bool = False


class GuardEngine:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._blackout = _load_blackout(cfg)

    # ─────────────────────────────────────────────────────────────────────────
    def evaluate(self, candle: Candle, ctx: SessionContext, state: SessionState,
                 atr_1m: Decimal | None, candles_seen: int,
                 htf_minutes_remaining: int | None) -> GuardOutcome:
        computed: dict[str, Any] = {"atr_1m": atr_1m, "candles_seen": candles_seen}
        clock = candle.open_time.time()

        # 1 — event blackout. A calendar lookup written in advance; no interpretation.
        gate, detail = self._event_blackout(ctx.day, clock)
        if gate:
            return GuardOutcome(False, gate, detail, computed=computed)

        # 2 — gap regime. Carried levels describe a market that no longer exists.
        gate, detail = self._gap_regime(ctx, clock)
        if gate:
            return GuardOutcome(False, gate, detail, computed=computed)

        # 3 — warmup
        period = int(self.cfg.get("volatility.atr_period"))
        if candles_seen < period or atr_1m is None:
            return GuardOutcome(False, "warmup",
                                f"{candles_seen}/{period} candles", computed=computed)

        # 4 — feed gap
        limit = int(self.cfg.get("feed.synthetic_candle_max_consecutive"))
        if ctx.consecutive_synthetic > limit:
            return GuardOutcome(False, "feed_gap",
                                f"{ctx.consecutive_synthetic} consecutive synthetic minutes",
                                computed=computed)

        # 5 — time window
        windows = self.cfg.windows(ctx.is_expiry)
        if not any(lo <= clock <= hi for lo, hi in windows):
            return GuardOutcome(False, "time_window",
                                f"{clock:%H:%M} outside "
                                f"{[(f'{a:%H:%M}', f'{b:%H:%M}') for a, b in windows]}",
                                computed=computed)

        # 6 — htf_close_proximity. SETUP-SCOPED. Does not block the mode. See docstring.
        blocked_setups: frozenset[str] = frozenset()
        buffer_minutes = int(self.cfg.get("structure.htf_close_buffer_minutes"))
        if htf_minutes_remaining is not None and htf_minutes_remaining <= buffer_minutes:
            exempt = set(self.cfg.get("time.htf_close_exempt_setups"))
            blocked_setups = frozenset(
                s for s in ("A_flip_retest", "B_sweep_reclaim", "C_range_break_retest")
                if s not in exempt)
            computed["htf_tail"] = True
            computed["htf_minutes_remaining"] = htf_minutes_remaining

        # 7, 8 — volatility
        atr_min = self.cfg.dec("volatility.atr_min_points")
        atr_max = self.cfg.dec("volatility.atr_max_points")
        if atr_1m < atr_min:
            return GuardOutcome(False, "volatility_floor",
                                f"ATR {atr_1m:.1f} < {atr_min}", computed=computed)
        if atr_1m > atr_max:
            return GuardOutcome(False, "volatility_ceiling",
                                f"ATR {atr_1m:.1f} > {atr_max}", computed=computed)

        # 9-12 — the latching session limits
        gate, detail = self._session_limits(state)
        if gate:
            return GuardOutcome(False, gate, detail, computed=computed)

        # 13 — one position at a time
        if ctx.position_open:
            return GuardOutcome(False, "position_open", "a position is already open",
                                computed=computed)

        return GuardOutcome(True, blocked_setups=blocked_setups, computed=computed)

    # ── 1 ───────────────────────────────────────────────────────────────────
    def _event_blackout(self, day: date, clock: dtime) -> tuple[str | None, str]:
        """*"~75% of the Bank Nifty index sits in five stocks. On their results days the
        index does not respect the level structure the engine spent the morning building;
        it repriced on information, not on order flow at a level. The volatility ceiling
        catches this AFTER the move. The calendar catches it before."*"""
        full, partial = self._blackout
        if day in full:
            return "event_blackout", f"{day} is {full[day]} — full-day blackout"
        if day in partial:
            until, label = partial[day]
            if clock < until:
                return "event_blackout", f"{day} is {label} — blocked until {until:%H:%M}"
        return None, ""

    # ── 2 ───────────────────────────────────────────────────────────────────
    def _gap_regime(self, ctx: SessionContext, clock: dtime) -> tuple[str | None, str]:
        if ctx.gap_pct is None:
            return None, ""
        threshold = self.cfg.dec("gap_regime.gap_pct_threshold")
        until = dtime.fromisoformat(self.cfg.get("gap_regime.no_entries_until"))
        if abs(ctx.gap_pct) > threshold and clock < until:
            return "gap_regime", (f"gapped {ctx.gap_pct:+.2f}% (> {threshold}%), "
                                  f"no entries before {until:%H:%M}")
        return None, ""

    # ── 9-12 ────────────────────────────────────────────────────────────────
    def _session_limits(self, state: SessionState) -> tuple[str | None, str]:
        """*"Once tripped, the session stays BLOCKED for new entries until the next
        trading day."* An open position is still managed to exit normally (D-008)."""
        if state.blocked_reason:
            return state.blocked_reason, f"latched: {state.blocked_detail}"

        if state.trades_taken >= int(self.cfg.get("session.max_trades")):
            return "session_max_trades", f"{state.trades_taken} trades taken"
        if state.consecutive_losses >= int(self.cfg.get("session.max_consecutive_losses")):
            return "session_consec_loss", f"{state.consecutive_losses} consecutive losses"
        if state.cumulative_r <= -self.cfg.dec("session.max_loss_r"):
            return "session_max_loss", f"cumulative {state.cumulative_r:+.2f}R"

        losses = [r for r in state.realised_r_history if r < 0]
        if len(losses) >= 10:
            recent = sorted(abs(r) for r in losses[-10:])
            median = (recent[4] + recent[5]) / 2
            if median > Decimal("1.2"):
                return "r_model_broken", (
                    f"median realised loss {median:.2f}R over the last 10 losses. "
                    f"The -2R cap is not capping at -2R and every r_realised in the "
                    f"journal is wrong. Recalibrate delta, do not widen the budget.")
        return None, ""


def _load_blackout(cfg: Config) -> tuple[dict[date, str], dict[date, tuple[dtime, str]]]:
    """Parse `events.yaml` into two lookups. Fail closed is the loader's job (guard 0)."""
    events = cfg.events
    full: dict[date, str] = {}
    partial: dict[date, tuple[dtime, str]] = {}

    for key in cfg.get("events.blackout_full_day", []):
        for entry in (events.get(key) or []):
            day = entry if isinstance(entry, date) else date.fromisoformat(str(entry))
            full[day] = key

    for key, until in (cfg.get("events.blackout_until", {}) or {}).items():
        cutoff = dtime.fromisoformat(str(until))
        for entry in (events.get(key) or []):
            raw = entry.get("date") if isinstance(entry, dict) else entry
            day = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
            partial[day] = (cutoff, key)
    return full, partial


# ─────────────────────────────────────────────────────────────────────────────
def resolve_mode(outcome: GuardOutcome, position_open: bool,
                 distance_to_active: Decimal | None,
                 alert_distance: Decimal,
                 active_is_round: bool = False) -> Mode:
    """Spec 05 §6. The mode machine, which is four lines because it should be.

    `round_numbers_can_trigger_alert: false` is honoured here: with a 100-point grid and
    a 20-point alert distance, price sits within reach of *some* 100-mark 40% of the
    session by construction, and ALERT would never switch off (REVIEW-v2 §5a).
    """
    if position_open:
        return Mode.IN
    if not outcome.passed:
        return Mode.BLOCKED
    if distance_to_active is None or active_is_round:
        return Mode.WATCH
    return Mode.ALERT if abs(distance_to_active) <= alert_distance else Mode.WATCH
