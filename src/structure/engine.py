"""
StructureEngine — spec 04. Who is in control, and how fast.

**This module never imports `levels/`.** Spec 01 §5 and spec 04's opening line make that
a hard boundary, and the reason is worth restating because it looks like an
inconvenience: it *prevents circular reasoning where a level justifies a structure that
justifies the level.* The two are joined only in `state/board.py`, and a static test
enforces it.

What it produces:

    swings      confirmed sequences on 1m and 5m
    BOS         body close beyond the last confirmed swing — never a wick
    control     buyers / sellers, from the last 5m BOS
    trend       from the swing sequence
    regime      trending / ranging / transition
    pullback    the speed comparison, spec 04 §5
    ladder      where a pullback can land, written BEFORE it happens
    htf         progress through the forming 15m candle, and its shape forecast

## The one thing here that gates a trade, and the several that do not

Only `pullback_ratio` reaches a gate (`bias_conflict`, spec 05 §5). The landing ladder,
the HTF forecast and the regime are **journalled and nothing else** — D-007 keeps the
ladder informational, and spec 04 §4 says of the forecast "it must never gate a trade —
it is a forecast of a candle, not of price."

That restraint is the point. `mythinking.md` §14 puts entry timing fifth and level
identification sixth in what decides the outcome; a module that predicts candle shapes
is not where the money is, and wiring it into a gate is how it starts costing money.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from src.config.loader import Config
from src.domain.models import ZERO, BreakOfStructure, Candle, Swing
from src.indicators.swings import SwingDetector

Trend = Literal["up", "down", "none"]
Regime = Literal["trending", "ranging", "transition"]
Control = Literal["buyers", "sellers", "none"]


@dataclass(frozen=True, slots=True)
class LadderRung:
    """Spec 04 §6. Four prices where a pullback can stop, written before it starts."""
    label: Literal["L1", "L2", "L3", "L4"]
    price: Decimal
    distance_points: Decimal
    is_failure_line: bool = False


@dataclass(frozen=True, slots=True)
class StructureState:
    tf: Literal["1m", "5m"]
    last_swing_high: Swing | None = None
    last_swing_low: Swing | None = None
    prev_swing_high: Swing | None = None
    prev_swing_low: Swing | None = None
    last_bos: BreakOfStructure | None = None
    trend: Trend = "none"
    regime: Regime = "transition"
    impulse_atr: Decimal = ZERO
    pullback_atr: Decimal = ZERO
    pullback_ratio: Decimal | None = None


class _Legs:
    """Leg identification for `pullback_ratio` — D-005.

    Spec 04 §5 is loose about what ends a leg, so the rule is fixed here: a leg ends when
    **two consecutive** 1m candles close beyond the prior candle's opposite extreme. If
    fewer than 3 candles are in the current leg, `pullback_ratio` is `None` and the
    ratio-based check is **skipped, not defaulted** — a missing value must never silently
    become a passing one.
    """

    __slots__ = ("direction", "current", "completed", "_against")

    def __init__(self) -> None:
        self.direction: Literal["up", "down", None] = None
        self.current: list[Candle] = []
        self.completed: list[tuple[str, list[Candle]]] = []
        self._against = 0

    def on_candle(self, candle: Candle, prev: Candle | None) -> None:
        if prev is None:
            self.current = [candle]
            return
        if self.direction is None:
            self.direction = "up" if candle.c >= prev.c else "down"
            self.current.append(candle)
            return

        reversed_now = (candle.c < prev.l) if self.direction == "up" else (candle.c > prev.h)
        self._against = self._against + 1 if reversed_now else 0
        self.current.append(candle)

        if self._against >= 2:
            self.completed.append((self.direction, self.current[:-2]))
            self.direction = "down" if self.direction == "up" else "up"
            self.current = self.current[-2:]
            self._against = 0

    @staticmethod
    def mean_range(candles: list[Candle]) -> Decimal:
        real = [k for k in candles if not k.synthetic]
        if not real:
            return ZERO
        return sum(k.range for k in real) / len(real)

    def ratio(self) -> tuple[Decimal, Decimal, Decimal | None]:
        """(impulse_atr, pullback_atr, ratio). Ratio is None when the current leg is
        too short to describe — D-005."""
        if not self.completed or len(self.current) < 3:
            return ZERO, ZERO, None
        impulse = self.mean_range(self.completed[-1][1])
        pullback = self.mean_range(self.current)
        if impulse <= ZERO:
            return impulse, pullback, None
        return impulse, pullback, pullback / impulse


class StructureEngine:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        # k comes from config, not from swings.DEFAULT_K. Both engines must use the same
        # lookback or `levels/` and `structure/` disagree about where a swing is — and a
        # hardcoded default silently ignores anyone tuning params.yaml (CLAUDE.md §9).
        self._det = {tf: SwingDetector(tf, k=int(config.get(f"levels.swing_lookback_bars_{tf}")))
                     for tf in ("1m", "5m")}
        self._legs = _Legs()

        self.swings: dict[str, dict[str, list[Swing]]] = {
            tf: {"high": [], "low": []} for tf in ("1m", "5m")}
        self.bos_history: list[BreakOfStructure] = []
        self.state: dict[str, StructureState] = {
            "1m": StructureState("1m"), "5m": StructureState("5m")}

        self.candles_1m: list[Candle] = []
        self.candles_5m: list[Candle] = []
        self._prev_1m: Candle | None = None
        self.last_impulse: Candle | None = None
        self.ladder: list[LadderRung] = []
        self.htf_progress: Decimal = ZERO
        self.htf_closing_soon: bool = False
        self.htf_forecast: Literal["body", "upper_wick", "lower_wick", "doji"] = "doji"
        self.pullback_over: bool = False

    # ─────────────────────────────────────────────────────────────────────────
    def on_candle(self, candle: Candle, m5: Candle | None = None,
                  m15_partial=None, atr20: Decimal | None = None) -> None:
        self.candles_1m.append(candle)
        self._legs.on_candle(candle, self._prev_1m)
        self._prev_1m = candle

        for pivot in self._det["1m"].on_candle(candle):
            self.swings["1m"][pivot.swing.kind].append(pivot.swing)
        if m5 is not None:
            self.candles_5m.append(m5)
            for pivot in self._det["5m"].on_candle(m5):
                self.swings["5m"][pivot.swing.kind].append(pivot.swing)
            self._detect_bos(m5, "5m")

        self._update_state("1m")
        self._update_state("5m")
        self._update_ladder(candle, atr20)
        self._update_htf(m15_partial)
        self.pullback_over = self._pullback_over_signal()

    # ── BOS — spec 04 §2 ────────────────────────────────────────────────────
    def _detect_bos(self, candle: Candle, tf: Literal["1m", "5m"]) -> None:
        """*"Body close only. A wick through a swing is not a BOS — it is a sweep, and
        it is Setup B's business, not the structure engine's."*"""
        if candle.synthetic:
            return
        highs, lows = self.swings[tf]["high"], self.swings[tf]["low"]
        if highs and candle.body_top > highs[-1].price:
            self._record_bos(candle, highs[-1], "up", tf)
        elif lows and candle.body_bottom < lows[-1].price:
            self._record_bos(candle, lows[-1], "down", tf)

    def _record_bos(self, candle: Candle, swing: Swing,
                    direction: Literal["up", "down"], tf: Literal["1m", "5m"]) -> None:
        bos = BreakOfStructure(at=candle.open_time, direction=direction,
                               broken_swing=swing, breaking_candle=candle, tf=tf)
        self.bos_history.append(bos)

    # ── trend and regime — spec 04 §3 ───────────────────────────────────────
    def _update_state(self, tf: Literal["1m", "5m"]) -> None:
        highs, lows = self.swings[tf]["high"], self.swings[tf]["low"]
        impulse, pullback, ratio = self._legs.ratio()
        bos_here = [b for b in self.bos_history if b.tf == tf]

        trend: Trend = "none"
        if len(highs) >= 2 and len(lows) >= 2:
            rising = highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price
            falling = highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price
            trend = "up" if rising else ("down" if falling else "none")

        self.state[tf] = StructureState(
            tf=tf,
            last_swing_high=highs[-1] if highs else None,
            last_swing_low=lows[-1] if lows else None,
            prev_swing_high=highs[-2] if len(highs) >= 2 else None,
            prev_swing_low=lows[-2] if len(lows) >= 2 else None,
            last_bos=bos_here[-1] if bos_here else None,
            trend=trend,
            regime=self._regime(bos_here),
            impulse_atr=impulse, pullback_atr=pullback, pullback_ratio=ratio)

    def _regime(self, bos: list[BreakOfStructure]) -> Regime:
        """Spec 04 §3. `transition` is the common case and that is correct.

        BUILD-BRIEF §7 M-2 records the real limitation: 20 5m candles is 100 minutes, so
        from 09:15 this read is only meaningful after **10:55** — through the whole of
        `mythinking.md` §13's best window. The daily-timeframe regime that fixes it is a
        pre-market artefact and is not this module's job; both get journalled and spec 09
        decides which carries information.
        """
        lookback = int(self.cfg.get("structure.regime_lookback_5m"))
        recent = [b for b in bos if b.tf == "5m"][-lookback:]
        if len(recent) >= 2:
            directions = {b.direction for b in recent[-2:]}
            if len(directions) == 1 and len({b.direction for b in recent}) == 1:
                return "trending"
            if len({b.direction for b in recent}) > 1:
                return "ranging"
        return "transition"

    # ── the landing ladder — spec 04 §6, D-007 informational only ───────────
    def _update_ladder(self, candle: Candle, atr20: Decimal | None) -> None:
        """Reduces four hundred possible prices to four, then lets the 1m candles say
        which. It is **not** a prediction and nothing consumes the "expected rung"."""
        if atr20 is None or atr20 <= ZERO:
            return
        mult = self.cfg.dec("levels.launch_impulse_atr_mult")
        if not candle.synthetic and candle.range >= mult * atr20:
            self.last_impulse = candle

        impulse = self.last_impulse
        if impulse is None:
            self.ladder = []
            return

        up = impulse.close_third == "top"
        mid = (impulse.h + impulse.l) / 2
        origin = impulse.o
        rungs = [
            LadderRung("L1", mid, abs(candle.c - mid)),
            LadderRung("L4", origin, abs(candle.c - origin), is_failure_line=True),
        ]
        # L2 (the axis) and L3 (the sweep zone) reference the level book, which this
        # module is forbidden to see. state/board.py fills them in — spec 01 §5.
        self.ladder = sorted(rungs, key=lambda r: r.distance_points)
        self._ladder_direction: Literal["up", "down"] = "up" if up else "down"

    def _pullback_over_signal(self) -> bool:
        """Spec 04 §6: *"a 1m candle closes ABOVE the previous 1m candle's high, after a
        1m higher-low has formed."* This is what Setup A consumes as its trigger."""
        if len(self.candles_1m) < 2:
            return False
        lows = self.swings["1m"]["low"]
        if len(lows) < 2 or lows[-1].price <= lows[-2].price:
            return False
        return self.candles_1m[-1].c > self.candles_1m[-2].h

    # ── HTF — spec 04 §4 ────────────────────────────────────────────────────
    def _update_htf(self, partial) -> None:
        """Law B: the last third. Consumed by the `htf_close_proximity` guard.

        `partial` is a `PartialCandle` — a different type from `Candle` precisely so it
        cannot reach a detector (spec 01 §4). It is used here for progress and for the
        journalled forecast, and for nothing else.
        """
        if partial is None:
            self.htf_progress = ZERO
            self.htf_closing_soon = False
            return
        self.htf_progress = partial.progress
        buffer_minutes = int(self.cfg.get("structure.htf_close_buffer_minutes"))
        self.htf_closing_soon = partial.minutes_remaining <= buffer_minutes

        # Law A — an HTF wick is an LTF structure break. Informational; journalled.
        inside = [b for b in self.bos_history if b.at >= partial.open_time]
        if not inside:
            cp = partial.close_position
            self.htf_forecast = "body" if (cp >= Decimal("0.8") or cp <= Decimal("0.2")) else "doji"
        elif inside[-1].direction == "up":
            self.htf_forecast = "lower_wick"
        else:
            self.htf_forecast = "upper_wick"

    # ── read-only accessors ─────────────────────────────────────────────────
    @property
    def control(self) -> Control:
        """Board variable 7 — from the last 5m BOS (spec 04 §2)."""
        five = [b for b in self.bos_history if b.tf == "5m"]
        if not five:
            return "none"
        return "buyers" if five[-1].direction == "up" else "sellers"

    @property
    def trend_5m(self) -> Trend:
        return self.state["5m"].trend

    @property
    def regime(self) -> Regime:
        return self.state["5m"].regime

    @property
    def pullback_ratio(self) -> Decimal | None:
        return self.state["5m"].pullback_ratio

    def pullback_health(self) -> Literal["healthy", "weakening", "control_flipped", "unknown"]:
        """Spec 04 §5's table. `unknown` when the ratio is None — the bias check is then
        SKIPPED, not defaulted to passing (D-005)."""
        ratio = self.pullback_ratio
        if ratio is None:
            return "unknown"
        if ratio < self.cfg.dec("structure.pullback_healthy_ratio"):
            return "healthy"
        if ratio > self.cfg.dec("structure.pullback_control_flip_ratio"):
            return "control_flipped"
        return "weakening"
