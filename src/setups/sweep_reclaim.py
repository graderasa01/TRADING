"""
Setup B — sweep reclaim. Spec 06.

> *Best risk-reward, lowest frequency. Preferred (and mandatory) at ANCHOR levels.*

Price pierces a level with a wick, fails to hold outside, and closes its body back inside.
The stops beyond the level have been cleared, so the path back is clean.

## The geometry problem, which is not a threshold problem

The conditions **force** a wide stop. B3 wants the wick at 55% or more of the candle's
range and B6 wants the close in the top third, so:

```
R = entry - stop = (about 0.70 x candle_range) + sl_buffer
```

`prototype/FINDINGS.md` Bug 4 put a genuine textbook sweep through the whole engine:

```
09:58  B_sweep_reclaim at PDL 57,455  ->  REJECT: r_too_wide
       R = 69.1        allowed 16.0 - 40.7   (ATR 29)
       sweep low 57,434 · reclaim close 57,490 · 56 pts apart · + 13 buffer
```

v1's flat 35-point ceiling and v2's `max(35, 1.40 x ATR)` = 40.7 both rejected it. The
sweep ran 30 points below the level and the reclaim printed a 26-point body — **both of
which are signs of a good sweep.** So the better the sweep, the worse the R. Nudging the
ceiling again does not fix a tension in the setup's own shape.

Spec 06 §v2.2 gives three honest answers and says to pick one deliberately. The default
built here is `pullback`, because it is the system's own discipline applied consistently:
`mythinking.md` §7 — *"hamesha retest par, breakout par nahi"* — which v1 applied to A and
C and forgot for B. A limit entry near the sweep extreme, waiting up to
`b_pullback_wait_candles`; **if the pullback never arrives the trade is missed, and that
is an acceptable cost.**

**All three entries are recorded on every detection regardless of which one is active.**
That is not diagnostics padding — spec 06 says the question should be *"answered with
data instead of argument"*, and the counterfactual can only be run later if the numbers
were written down at the time.

## The one thing that must never be done here

Do not move the stop closer than the sweep wick tip to make R fit. That tip is where the
stops were; inside it you are parked exactly where price is drawn to. If R does not fit,
the answer stays no trade.
"""

from __future__ import annotations

from decimal import Decimal

from src.domain.models import ZERO
from src.setups.base import (
    SETUP_B, Detection, SetupContext, SetupResult, no_synthetic)


def detect_b(ctx: SetupContext) -> SetupResult:
    """Direction is taken from the sweep itself, not from the level's declared side.

    An ANCHOR carries no side and a BREAK axis works both ways, so asking the level which
    way to trade fails on exactly the levels this setup exists for. A pierce below that
    closes back above is a long whatever the level calls itself.
    """
    long_attempt = _attempt(ctx, long_side=True)
    if long_attempt.detection is not None:
        return long_attempt
    short_attempt = _attempt(ctx, long_side=False)
    if short_attempt.detection is not None:
        return short_attempt
    # Report the side that got furthest rather than always the long one.
    return long_attempt if long_attempt.detail >= short_attempt.detail else short_attempt


def _attempt(ctx: SetupContext, *, long_side: bool) -> SetupResult:
    level = ctx.level
    reclaim = ctx.candle
    max_gap = int(ctx.cfg.get("setups.b_reclaim_max_candles"))

    # B7 — the sweep must be this candle or at most `b_reclaim_max_candles` before it.
    pierce_min = ctx.eff("setups.b_sweep_min_pierce_points",
                         "setups.b_sweep_min_pierce_atr_mult")
    wick_ratio = ctx.cfg.dec("setups.b_sweep_wick_ratio")

    sweep = None
    sweep_index = None
    for back in range(0, max_gap + 1):
        j = ctx.index - back
        if j < 0:
            break
        k = ctx.candles[j]
        if k.range <= ZERO:
            continue
        # B2 — the wick pierces the level's TIP, not its body edge. The tip is the
        #      extreme the market has already respected; piercing the body edge is just
        #      trading inside the zone.
        if long_side:
            pierced = level.wick_tip - k.l
            wick_share = k.lower_wick / k.range
        else:
            pierced = k.h - level.wick_tip
            wick_share = k.upper_wick / k.range
        if pierced < pierce_min:
            continue
        # B3 — the wick has to be most of the candle, or it is a breakout, not a sweep.
        if wick_share < wick_ratio:
            continue
        sweep, sweep_index = k, j
        break

    if sweep is None:
        return SetupResult(SETUP_B, gate="no_setup",
                           detail=f"no candle in the last {max_gap + 1} pierced "
                                  f"{level.wick_tip} by {pierce_min:.1f} with a "
                                  f"{float(wick_ratio) * 100:.0f}% wick")

    # B4/B5 — the reclaim: a body close back inside, by a real margin.
    reclaim_min = ctx.eff("setups.b_reclaim_min_points", "setups.b_reclaim_min_atr_mult")
    if long_side:
        reclaimed = reclaim.c - level.body_edge
    else:
        reclaimed = level.body_edge - reclaim.c
    if reclaimed < reclaim_min:
        return SetupResult(SETUP_B, gate="no_setup",
                           detail=f"reclaim is {reclaimed:.1f} beyond the body edge "
                                  f"(need {reclaim_min:.1f})")

    # Spec 06's own table: if the BODY closes outside, this is a breakout, not a sweep.
    # "Do not relabel it. It may become a Setup A or C later, once it retests."
    if long_side and sweep.body_bottom < level.body_edge and sweep is reclaim:
        pass                                  # the sweep candle itself reclaimed — fine
    if long_side and reclaim.body_bottom < level.wick_tip:
        return SetupResult(SETUP_B, gate="no_setup",
                           detail="the reclaim body is still below the level tip — "
                                  "this is a breakdown, not a reclaim")
    if not long_side and reclaim.body_top > level.wick_tip:
        return SetupResult(SETUP_B, gate="no_setup",
                           detail="the reclaim body is still above the level tip — "
                                  "this is a breakout, not a reclaim")

    # B6 — the reclaim must close decisively.
    want = "top" if long_side else "bottom"
    if reclaim.close_third != want:
        return SetupResult(SETUP_B, gate="no_setup",
                           detail=f"reclaim closed in the {reclaim.close_third} third, "
                                  f"not the {want}")

    used = ctx.candles[sweep_index:ctx.index + 1]
    synthetic = no_synthetic(ctx, used, SETUP_B)
    if synthetic is not None:
        return synthetic

    extreme = sweep.l if long_side else sweep.h
    entries = _entries(ctx, extreme, reclaim.c, long_side)
    mode = str(ctx.cfg.get("setups.b_entry_mode"))
    entry_ref = entries.get(mode, entries["reclaim_close"])

    return SetupResult(SETUP_B, detection=Detection(
        setup=SETUP_B, side="long" if long_side else "short", level_id=level.id,
        entry_ref=entry_ref, extreme=extreme, trigger_index=ctx.index,
        evidence={
            "entry_mode": mode,
            # all three, always — spec 06 §v2.2's counterfactual needs them recorded now
            "entry_reclaim_close": entries["reclaim_close"],
            "entry_pullback": entries["pullback"],
            "pullback_wait_candles": int(ctx.cfg.get("setups.b_pullback_wait_candles")),
            "sweep_index": sweep_index,
            "sweep_extreme": extreme,
            "pierce": (level.wick_tip - sweep.l) if long_side else (sweep.h - level.wick_tip),
            "wick_share": (sweep.lower_wick if long_side else sweep.upper_wick) / sweep.range,
            "reclaim_margin": reclaimed,
            "candles_sweep_to_reclaim": ctx.index - sweep_index,
            "r_if_reclaim_close": abs(entries["reclaim_close"] - extreme),
            "r_if_pullback": abs(entries["pullback"] - extreme),
        }))


def _entries(ctx: SetupContext, extreme: Decimal, reclaim_close: Decimal,
             long_side: bool) -> dict[str, Decimal]:
    """The three answers spec 06 §v2.2 puts on the table, computed together.

    `skip_wide` shares `reclaim_close`'s price on purpose — it is the same entry with a
    different willingness to accept the R, and the R ceiling is spec 07's job, not this
    detector's. Deciding it here would put the same rule in two places.
    """
    cap = ctx.cfg.dec("setups.b_entry_max_extreme_atr_mult") * ctx.atr14
    pullback = extreme + cap if long_side else extreme - cap
    # Never worse than simply taking the reclaim: if price already sits inside the cap,
    # the pullback entry is the reclaim close.
    if long_side:
        pullback = min(pullback, reclaim_close)
    else:
        pullback = max(pullback, reclaim_close)
    return {"reclaim_close": reclaim_close, "pullback": pullback,
            "skip_wide": reclaim_close}
