"""
Setup A — flip retest. Spec 06.

> *Highest frequency, smallest stop, trades with the trend. The bread and butter.*

A level breaks by body close. Price returns to it. The level holds as the opposite type.
Entry on the first sign the pullback is over.

## Why the stop is small, which is the entire point

```
entry_ref = trigger_candle.close
extreme   = the LOW of the 1m higher-low candle
```

The stop hides behind a **1m** swing that has just proved itself, not behind the 5m
candle's low. Spec 06: *"That is the entire advantage of the drill-down — the same trade
with roughly half the risk."* Taking the 5m low here would roughly double R, which halves
size, which is the difference between a setup worth taking and one that is not.

## A4 is the condition that stops this being a losing pattern

*"The axis HELD: no 1m body has closed below `axis.body_edge - hold_tolerance`."*

Without it, "price came back to the level" describes a failed flip exactly as well as a
successful one — and the failed one is more common. A retest that has already been closed
through is not a retest, it is a level being lost, and entering there is buying the
breakdown.
"""

from __future__ import annotations

from decimal import Decimal

from src.domain.models import LevelKind, LevelSide
from src.setups.base import (
    SETUP_A, Detection, SetupContext, SetupResult, no_synthetic)


def detect_a(ctx: SetupContext) -> SetupResult:
    level = ctx.level

    # A1 — the trigger level must be a BREAK axis, and a fresh one.
    if level.kind is not LevelKind.BREAK:
        return SetupResult(SETUP_A, gate="no_setup",
                           detail=f"{level.id} is a {level.kind.value}, not a BREAK axis")

    since_break = ctx.candles_since(level.born_at)
    max_candles = int(ctx.cfg.get("setups.a_retest_max_candles"))
    if since_break > max_candles:
        return SetupResult(SETUP_A, gate="setup_stale",
                           detail=f"{since_break} candles since the break (max {max_candles})")

    # A2 — direction. An axis works both ways, so the break direction decides the side.
    #      `side` is AXIS on a break level; the direction comes from where price sits.
    candle = ctx.candle
    long_side = candle.c >= level.body_edge
    side = "long" if long_side else "short"

    # A3 — price has returned to the axis.
    retest_tol = ctx.eff("setups.a_retest_tolerance_points",
                         "setups.a_retest_tolerance_atr_mult")
    distance = abs(candle.c - level.body_edge)
    if distance > retest_tol:
        return SetupResult(SETUP_A, gate="no_setup",
                           detail=f"price is {distance:.1f} from the axis "
                                  f"(retest tolerance {retest_tol:.1f})")

    # A4 — the axis HELD. Any body close beyond the tolerance kills the flip outright.
    hold_tol = ctx.eff("setups.a_hold_tolerance_points", "setups.a_hold_tolerance_atr_mult")
    window = ctx.candles[max(0, ctx.index - since_break):ctx.index + 1]
    if long_side:
        broke_back = [k for k in window if k.body_bottom < level.body_edge - hold_tol]
    else:
        broke_back = [k for k in window if k.body_top > level.body_edge + hold_tol]
    if broke_back:
        return SetupResult(SETUP_A, gate="setup_stale",
                           detail=f"a body closed back through the axis at "
                                  f"{broke_back[0].open_time:%H:%M} — the flip failed")

    # A5 — a 1m higher low (mirror: lower high) formed during the retest.
    pivot = _higher_low(window, long_side)
    if pivot is None:
        return SetupResult(SETUP_A, gate="no_setup",
                           detail="no 1m higher low has formed during the retest yet"
                                  if long_side else
                                  "no 1m lower high has formed during the retest yet")

    # A6 — the trigger: this candle closes beyond the previous candle's extreme.
    if ctx.index < 1:
        return SetupResult(SETUP_A, gate="no_setup", detail="no previous candle")
    prev = ctx.candles[ctx.index - 1]
    triggered = candle.c > prev.h if long_side else candle.c < prev.l
    if not triggered:
        return SetupResult(SETUP_A, gate="no_setup",
                           detail=f"close {candle.c} has not cleared the previous "
                                  f"{'high' if long_side else 'low'} "
                                  f"{prev.h if long_side else prev.l}")

    # A7 — the trigger candle must close decisively.
    want = "top" if long_side else "bottom"
    if candle.close_third != want:
        return SetupResult(SETUP_A, gate="no_setup",
                           detail=f"trigger closed in the {candle.close_third} third, "
                                  f"not the {want}")

    # A8 — bias. Counter to the 5m trend at a non-A level is a conflict; preconditions
    #      already guarantee grade A, so this only rejects a genuine counter-trend take.
    if ctx.trend_5m == "down" and long_side:
        return SetupResult(SETUP_A, gate="bias_conflict", detail="long against a 5m downtrend")
    if ctx.trend_5m == "up" and not long_side:
        return SetupResult(SETUP_A, gate="bias_conflict", detail="short against a 5m uptrend")

    used = [pivot, prev, candle]
    synthetic = no_synthetic(ctx, used, SETUP_A)
    if synthetic is not None:
        return synthetic

    return SetupResult(SETUP_A, detection=Detection(
        setup=SETUP_A, side=side, level_id=level.id,
        entry_ref=candle.c,
        extreme=pivot.l if long_side else pivot.h,
        trigger_index=ctx.index,
        evidence={
            "axis": level.body_edge,
            "candles_since_break": since_break,
            "retest_distance": distance,
            "higher_low" if long_side else "lower_high": pivot.l if long_side else pivot.h,
            "trigger_close_third": candle.close_third,
            "trend_5m": ctx.trend_5m,
        }))


def _higher_low(window: list, long_side: bool):
    """The pullback's extreme, and proof price has turned away from it.

    A higher low needs three things: the pullback low, at least one candle after it, and
    a low above it. Returns the candle that MADE the extreme — its low is where the stop
    goes, so the identity of the candle matters, not just the price.
    """
    if len(window) < 3:
        return None
    if long_side:
        extreme_i = min(range(len(window)), key=lambda i: window[i].l)
        if extreme_i >= len(window) - 1:
            return None                       # the low is still being made
        after = window[extreme_i + 1:]
        return window[extreme_i] if all(k.l > window[extreme_i].l for k in after) else None
    extreme_i = max(range(len(window)), key=lambda i: window[i].h)
    if extreme_i >= len(window) - 1:
        return None
    after = window[extreme_i + 1:]
    return window[extreme_i] if all(k.h < window[extreme_i].h for k in after) else None


__all__ = ["detect_a", "LevelSide", "Decimal"]
