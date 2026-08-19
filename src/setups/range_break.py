"""
Setup C — range break retest. Spec 06.

> *Lowest frequency. Only after a long, tightening range. Never on the breakout candle.*

## The rule with teeth: C3 is never an entry

> *"Entry is only at C6, on the retest. Enforce by having the detector return nothing at
> C3/C4; **there must be no code path from breakout to order.**"*

So the breakout is not a state this detector can emit from. It is a fact it looks up on
its way to asking whether a retest has happened, and a run that reaches C3 and stops
returns a rejection like every other non-firing candle. `test_no_path_from_breakout_to_
detection` exists because "we only enter on the retest" is the kind of rule that survives
in prose and quietly dies in code.

## A range is a strict object, not a description

```
R1. formed over >= range_min_candles (20)
R2. >= 2 touches at the top AND >= 2 at the bottom
R3. width between range_min_width (25) and range_max_width (120)
R4. NO 1m body closed outside the range during its formation
```

Spec 06: *"If these do not hold, **there is no range**, and Setup C cannot exist. The
engine must say so rather than approximating."* R4 is the one that does the work — drop
it and any sideways drift becomes a "range", which is how a low-frequency setup turns
into a high-frequency one without anybody changing a threshold.

## The failed breakout is not a fourth setup

If the breakout closes back inside within `acceptance_candles`, that is a **Setup B
candidate in the opposite direction** with `range.high` as the swept level — routed
through the normal Setup B detector. Spec 06 is explicit: *"do not create a fourth setup
for it."* The registry length assertion enforces the same thing from the other side.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.domain.models import ZERO, Candle
from src.setups.base import (
    SETUP_C, Detection, SetupContext, SetupResult, no_synthetic)
from src.setups.flip_retest import _higher_low


@dataclass(frozen=True)
class Range:
    lo: int
    hi: int
    low: Decimal
    high: Decimal

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def candle_count(self) -> int:
        return self.hi - self.lo + 1


def find_range(ctx: SetupContext, candles: Sequence[Candle], end: int) -> Range | None:
    """The longest window ending at `end` that satisfies R1-R4, or nothing.

    Longest rather than first: *"time in the range is the fuel"* (spec 06's move-size
    note), so if 40 candles qualify there is no reason to report 20.
    """
    min_candles = int(ctx.cfg.get("setups.c_range_min_candles"))
    min_width = ctx.eff("setups.c_range_min_width_points",
                        "setups.c_range_min_width_atr_mult")
    max_width = ctx.eff("setups.c_range_max_width_points",
                        "setups.c_range_max_width_atr_mult")
    touch_tol = ctx.eff("setups.c_range_touch_tolerance_points",
                        "setups.c_range_touch_tolerance_atr_mult")

    best: Range | None = None
    for start in range(max(0, end - 120), end - min_candles + 2):
        window = candles[start:end + 1]
        if len(window) < min_candles:
            continue
        high = max(k.h for k in window)
        low = min(k.l for k in window)
        width = high - low
        if not (min_width <= width <= max_width):
            continue
        # R2 — the boundaries must have been respected more than once each.
        top = sum(1 for k in window if k.h >= high - touch_tol)
        bottom = sum(1 for k in window if k.l <= low + touch_tol)
        if top < 2 or bottom < 2:
            continue
        # R4 — no BODY outside. Wicks may pierce; bodies may not.
        if any(k.body_top > high or k.body_bottom < low for k in window):
            continue
        best = Range(start, end, low, high)
    return best


def detect_c(ctx: SetupContext) -> SetupResult:
    candles = ctx.candles
    acceptance = int(ctx.cfg.get("setups.c_acceptance_candles"))
    max_since = int(ctx.cfg.get("setups.a_retest_max_candles"))

    # Walk back to find the last candle that could have ENDED a range, then check whether
    # what followed is a breakout-acceptance-retest. The range must end before the break.
    for break_i in range(ctx.index - 1, max(0, ctx.index - max_since) - 1, -1):
        rng = find_range(ctx, candles, break_i - 1)
        if rng is None:
            continue

        # C2 — compression. A range that widens into its break is not a coil.
        third = max(1, rng.candle_count // 3)
        first = candles[rng.lo:rng.lo + third]
        last = candles[rng.hi - third + 1:rng.hi + 1]
        first_w = max(k.h for k in first) - min(k.l for k in first)
        last_w = max(k.h for k in last) - min(k.l for k in last)
        ratio = ctx.cfg.dec("setups.c_compression_ratio")
        if first_w <= ZERO or last_w > ratio * first_w:
            continue

        breakout = candles[break_i]
        up = breakout.body_bottom > rng.high
        down = breakout.body_top < rng.low
        if not (up or down):
            continue

        # C4 — acceptance. Returning inside before this is a FAILED breakout, which spec
        # 06 routes to Setup B in the opposite direction — never to an entry here.
        after = candles[break_i + 1:break_i + 1 + acceptance]
        if len(after) < acceptance:
            continue
        held = all(k.body_bottom > rng.high for k in after) if up else \
            all(k.body_top < rng.low for k in after)
        if not held:
            return SetupResult(SETUP_C, gate="setup_stale",
                               detail=f"breakout at candle {break_i} closed back inside "
                                      f"within {acceptance} candles — failed breakout, "
                                      f"a Setup B candidate the other way")

        # C5 — the retest.
        edge = rng.high if up else rng.low
        tol = ctx.eff("setups.a_retest_tolerance_points",
                      "setups.a_retest_tolerance_atr_mult")
        candle = ctx.candle
        if abs(candle.c - edge) > tol:
            return SetupResult(SETUP_C, gate="no_setup",
                               detail=f"price is {abs(candle.c - edge):.1f} from the "
                                      f"broken edge {edge} (tolerance {tol:.1f})")

        # C6 — same trigger as A: a higher low, then a close beyond the previous extreme.
        window = candles[break_i + 1:ctx.index + 1]
        pivot = _higher_low(list(window), up)
        if pivot is None:
            return SetupResult(SETUP_C, gate="no_setup",
                               detail="no higher low has formed on the retest yet")
        prev = candles[ctx.index - 1]
        triggered = candle.c > prev.h if up else candle.c < prev.l
        if not triggered:
            return SetupResult(SETUP_C, gate="no_setup",
                               detail="the retest has not triggered yet")
        want = "top" if up else "bottom"
        if candle.close_third != want:
            return SetupResult(SETUP_C, gate="no_setup",
                               detail=f"trigger closed in the {candle.close_third} third")

        used = [pivot, prev, candle, breakout]
        synthetic = no_synthetic(ctx, used, SETUP_C)
        if synthetic is not None:
            return synthetic

        return SetupResult(SETUP_C, detection=Detection(
            setup=SETUP_C, side="long" if up else "short", level_id=ctx.level.id,
            entry_ref=candle.c, extreme=pivot.l if up else pivot.h,
            trigger_index=ctx.index,
            evidence={
                "range_low": rng.low, "range_high": rng.high, "range_width": rng.width,
                "range_candles": rng.candle_count,
                "compression": (last_w / first_w) if first_w > ZERO else None,
                "breakout_index": break_i,
                "acceptance_candles": acceptance,
                # informational only — spec 06 says this adjusts T2 preference, never entry
                "measured_move": rng.width,
                "range_fuel": Decimal(rng.candle_count) /
                              int(ctx.cfg.get("setups.c_range_min_candles")),
            }))

    return SetupResult(SETUP_C, gate="no_setup",
                       detail="no valid range with a break, acceptance and retest")
