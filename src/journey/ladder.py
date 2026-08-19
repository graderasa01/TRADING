"""
The Journey Ladder — spec 04 §6b. A logged prediction that gates nothing.

The Landing Ladder answers *"a move happened — where will the pullback stop?"* Nothing
in v1 answered the other half: **"a level just broke — where is price going?"** v1 made
an axis and stopped thinking.

The trader's model, from `mythinking.md`:

> *"jahan se aaya wahan tak to jayega hi jayega... phir wahan par jayega to kya karega
> wo bhi pata — cluster ya swing."*

Two claims, different in kind. That *what waits there is knowable* is already true —
every destination IS a `Level` with a kind and a grade. That *price returns to where the
move came from* is **an untested hypothesis about market behaviour**, and it is the one
that must be handled carefully, because a strong intuition that has never been measured
is exactly the kind of thing that quietly becomes a rule and then quietly loses money.

## Why this module exists in its own package

D-011b requires that `setups/`, `risk/` and `exits/` never import it, and
`test_journey_never_read_by_the_trading_path` asserts that statically. It cannot live in
`structure/` because it needs the level book, and `structure/` is forbidden to see
`levels/` (spec 01 §5). So: its own package, imported by `state/` and by the journal,
by nothing that can produce a Signal.

`journey_gates_trades` stays `false` until P9 measures the D2 hit rate. Spec 09 §3.2c
scores it. If D2 is reached 70% of the time, *"jahan se aaya wahan tak jayega"* is a real
property of this market and earns the right to drive T2. If it is 45%, it was a
memorable pattern rather than a reliable one — and that answer is worth more, because it
is the one you cannot get by trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from src.config.loader import Config
from src.domain.models import ZERO, Candle, Grade, Level, LevelKind

Direction = Literal["up", "down"]
Outcome = Literal["open", "D1", "D2", "D3", "D4", "stalled", "failed"]


@dataclass(frozen=True, slots=True)
class JourneyRung:
    label: Literal["D1", "D2", "D3", "D4"]
    price: Decimal
    basis: str                       # human-readable: which level, and why
    distance_points: Decimal
    confluence: tuple[str, ...] = ()  # other labels that landed on the same price


@dataclass
class Journey:
    started_at: datetime
    origin_level_id: str
    origin_price: Decimal
    direction: Direction
    break_candle_time: datetime
    invalidation: Decimal            # the axis body_edge — back through = failed
    rungs: list[JourneyRung]
    outcome: Outcome = "open"
    resolved_at: datetime | None = None
    max_progress_points: Decimal = ZERO
    reached: set[str] = field(default_factory=set)
    _stall_candles: int = 0

    @property
    def is_open(self) -> bool:
        return self.outcome == "open"


class JourneyTracker:
    """Creates a Journey on every level break and resolves it on 5m closes."""

    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.journeys: list[Journey] = []

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("structure.journey_enabled", True))

    def on_break(self, broken: Level, axis: Level, candle: Candle, direction: Direction,
                 levels_ahead: list[Level], anchors: list[tuple[Decimal, str]],
                 move_origin: tuple[Decimal, str] | None,
                 broken_range_width: Decimal | None) -> Journey | None:
        """Build the four rungs. Deliberately the mirror of the Landing Ladder."""
        if not self.enabled:
            return None

        here = candle.c
        rungs: list[JourneyRung] = []

        def ahead(price: Decimal) -> bool:
            return price > here if direction == "up" else price < here

        # D1 — the first meeting: nearest untested level ahead, revived ones included
        untested = sorted((lv for lv in levels_ahead if lv.touches == 0 and ahead(lv.body_edge)),
                          key=lambda lv: abs(lv.body_edge - here))
        if untested:
            first = untested[0]
            rungs.append(JourneyRung("D1", first.body_edge,
                                     f"{first.kind.value} {first.grade.value}, untested",
                                     abs(first.body_edge - here)))

        # D2 — "jahan se aaya". THE rung. Spec 09 §3.2c scores this one.
        if move_origin and ahead(move_origin[0]):
            rungs.append(JourneyRung("D2", move_origin[0], move_origin[1],
                                     abs(move_origin[0] - here)))

        # D3 — measured move from the broken range
        if broken_range_width and broken_range_width > ZERO:
            mult = self.cfg.dec("structure.journey_measured_move_mult")
            projected = (axis.body_edge + broken_range_width * mult) if direction == "up" \
                else (axis.body_edge - broken_range_width * mult)
            if ahead(projected):
                rungs.append(JourneyRung("D3", projected,
                                         f"measured move {broken_range_width:.0f} x {mult}",
                                         abs(projected - here)))

        # D4 — the structural wall
        walls = sorted(((p, why) for p, why in anchors if ahead(p)),
                       key=lambda pw: abs(pw[0] - here))
        if walls:
            rungs.append(JourneyRung("D4", walls[0][0], walls[0][1],
                                     abs(walls[0][0] - here)))

        if not rungs:
            return None

        journey = Journey(
            started_at=candle.open_time, origin_level_id=broken.id,
            origin_price=broken.body_edge, direction=direction,
            break_candle_time=candle.open_time, invalidation=axis.body_edge,
            rungs=self._dedupe(sorted(rungs, key=lambda r: r.distance_points)))
        self.journeys.append(journey)
        return journey

    def _dedupe(self, rungs: list[JourneyRung]) -> list[JourneyRung]:
        """*"D2 and D3 frequently land on the same price, and when they do that agreement
        is itself information."* Spec 09 §3.2c reports the hit rate with and without it."""
        tolerance = self.cfg.dec("structure.journey_reached_tolerance_atr_mult") * Decimal(10)
        out: list[JourneyRung] = []
        for rung in rungs:
            match = next((k for k, kept in enumerate(out)
                          if abs(kept.price - rung.price) <= tolerance), None)
            if match is None:
                out.append(rung)
            else:
                kept = out[match]
                out[match] = JourneyRung(kept.label, kept.price, kept.basis,
                                         kept.distance_points,
                                         confluence=kept.confluence + (rung.label,))
        return out

    def on_5m_close(self, candle: Candle, atr20: Decimal | None) -> None:
        """Resolution. Runs on 5m closes only — spec 04 §6b."""
        if not self.enabled:
            return
        tolerance = (self.cfg.dec("structure.journey_reached_tolerance_atr_mult") * atr20) \
            if atr20 else Decimal(5)
        stall_limit = int(self.cfg.get("structure.journey_stall_candles_5m"))
        ttl = timedelta(minutes=int(self.cfg.get("structure.journey_ttl_minutes")))

        for journey in self.journeys:
            if not journey.is_open:
                continue

            progress = (candle.h - journey.origin_price) if journey.direction == "up" \
                else (journey.origin_price - candle.l)
            if progress > journey.max_progress_points:
                journey.max_progress_points = progress
                journey._stall_candles = 0
            else:
                journey._stall_candles += 1

            for rung in journey.rungs:
                if rung.label in journey.reached:
                    continue
                hit = (candle.h >= rung.price - tolerance) if journey.direction == "up" \
                    else (candle.l <= rung.price + tolerance)
                if hit:
                    journey.reached.add(rung.label)
                    for also in rung.confluence:
                        journey.reached.add(also)

            failed = (candle.body_top < journey.invalidation) if journey.direction == "up" \
                else (candle.body_bottom > journey.invalidation)
            if failed:
                self._close(journey, "failed", candle.open_time)
            elif journey._stall_candles >= stall_limit:
                self._close(journey, "stalled", candle.open_time)
            elif candle.open_time - journey.started_at > ttl:
                self._close(journey, self._best(journey), candle.open_time)

    def _best(self, journey: Journey) -> Outcome:
        for label in ("D4", "D3", "D2", "D1"):
            if label in journey.reached:
                return label  # type: ignore[return-value]
        return "stalled"

    def _close(self, journey: Journey, outcome: Outcome, at: datetime) -> None:
        journey.outcome = outcome
        journey.resolved_at = at

    def close_all(self, at: datetime) -> None:
        """End of session. An unresolved journey is closed at whatever it reached — a
        journey left `open` in the journal is a row spec 09 §3.2c cannot score."""
        for journey in self.journeys:
            if journey.is_open:
                self._close(journey, self._best(journey), at)

    # ── reporting ───────────────────────────────────────────────────────────
    def summary(self) -> dict[str, object]:
        """What spec 09 §3.2c wants. Read it plainly and without cushioning."""
        total = len(self.journeys)
        if not total:
            return {"journeys": 0}
        counts = {label: sum(1 for j in self.journeys if label in j.reached)
                  for label in ("D1", "D2", "D3", "D4")}
        confluent = [j for j in self.journeys
                     if any(r.confluence for r in j.rungs)]
        d2_when_confluent = sum(1 for j in confluent if "D2" in j.reached)
        return {
            "journeys": total,
            "reached_pct": {k: round(100 * v / total, 1) for k, v in counts.items()},
            "stalled_pct": round(100 * sum(1 for j in self.journeys
                                           if j.outcome == "stalled") / total, 1),
            "failed_pct": round(100 * sum(1 for j in self.journeys
                                          if j.outcome == "failed") / total, 1),
            "d2_hit_when_confluent_pct": (round(100 * d2_when_confluent / len(confluent), 1)
                                          if confluent else None),
            "confluent_journeys": len(confluent),
        }


def anchor_walls(pdh: Decimal | None, pdl: Decimal | None,
                 day_high: Decimal | None, day_low: Decimal | None,
                 rounds: list[Level]) -> list[tuple[Decimal, str]]:
    """D4 candidates — the structural walls (spec 04 §6b)."""
    out: list[tuple[Decimal, str]] = []
    for price, why in ((pdh, "PDH"), (pdl, "PDL"),
                       (day_high, "day high"), (day_low, "day low")):
        if price is not None:
            out.append((price, why))
    for lv in rounds:
        if lv.kind is LevelKind.ANCHOR and lv.grade is not Grade.C:
            out.append((lv.body_edge, f"round {lv.body_edge:.0f}"))
    return out
