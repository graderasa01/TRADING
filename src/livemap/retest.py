"""
The 1m retest — the next observable event after a 5m structural break.

```
5m break
   |  1m move away
   |  1m returns toward the broken 5m edge
RETEST
   +-- holds -> 1m re-break in the break's direction
   +-- fails -> 1m re-entry back through the edge
```

**This is not an entry rule and it contains no detector.** There is no 1m structure
engine here, no clustering, no swings. The 5m break is taken from `Frontier` readings
that production code already produces; everything after it is read directly off 1m
candles. If a fact is not in the candle stream it is not available.

## What is recorded, and what is refused

```
retest_detected   retest_price   retest_depth
retest_holds      retest_fails   rebreak_direction
```

Not recorded: entry, stop, target, size, expectancy, win rate. Those need outcome
validation this module does not have and is not the place to invent.

## Every rule reused, none introduced

```
break            two closes beyond the structure's OWN edge   frontier.BREAK_CLOSES
contact          price trades back to edge +/- tol            structure.tol_at
failure          BREAK_CLOSES closes back through the edge     frontier.BREAK_CLOSES
hold             a new extreme beyond the pre-contact extension
horizon          WINDOW_MAX bars                              structure.WINDOW_MAX
```

The horizon is the one number with a choice in it, and it is an **observation window,
not a rule**: `WINDOW_MAX` is 75, already in the repo as *"the microscope never reaches
further than this"*, and 75 one-minute bars is 75 minutes after a 5m break. Widening it
changes what you see, never what the map says. It is a parameter for exactly that reason.

## Symmetry

An up-break's edge is the broken structure's high; a down-break's is its low. Everything
below mirrors on `up`, and `test_the_retest_observation_is_symmetric` runs the same
fixture upside down to prove no sign was hard-coded.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Reading
from src.boxes.structure import BREAK_CLOSES, WINDOW_MAX, tol_at
from src.domain.models import ZERO, Candle

#: Closed. Four ways an observation can end, and none of them is an instruction.
OUTCOMES = frozenset({
    "NO_RETEST",           # price never came back within the horizon
    "RETEST_HELD",         # came back, then made a new extreme in the break's direction
    "RETEST_FAILED",       # came back and closed through the edge, back inside
    "RETEST_UNRESOLVED",   # came back, did neither before the horizon ran out
})

ACCEPTED = {"ACCEPTED_ABOVE": "up", "ACCEPTED_BELOW": "down"}


@dataclass(frozen=True, slots=True)
class Break:
    """A confirmed 5m structural boundary break. Lifted from a `Reading`, not re-derived."""

    index: int                  # index into the 5m stream
    at: datetime                # close time of the 5m candle that accepted
    structure_id: str
    direction: str              # up | down
    edge: Decimal               # the structure's OWN broken edge
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise ValueError(f"direction must be up|down, got {self.direction!r}")

    @property
    def band(self) -> str:
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"


@dataclass(frozen=True, slots=True)
class RetestObservation:
    """One 5m break, watched on 1m. Every field is a measurement."""

    brk: Break
    start_index: int            # first 1m bar after the break, in the 1m stream
    horizon: int                # 1m bars watched
    bars_seen: int
    tol: Decimal

    #: How far price got beyond the edge before it came back — or in total, if it never did.
    extension_pts: Decimal = ZERO
    extension_index: int | None = None

    retest_detected: bool = False
    retest_index: int | None = None
    retest_at: datetime | None = None
    retest_price: Decimal | None = None
    #: Penetration back **through** the broken edge, into the structure. Zero when price
    #: only touched the edge from the correct side.
    retest_depth: Decimal = ZERO
    #: From the extension extreme back to the retest extreme. How much was given back.
    retreat_pts: Decimal = ZERO
    bars_to_retest: int | None = None

    retest_holds: bool = False
    retest_fails: bool = False
    rebreak_direction: str = ""
    resolved_index: int | None = None
    resolved_price: Decimal | None = None
    bars_to_resolution: int | None = None

    outcome: str = "NO_RETEST"

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}")
        if self.retest_holds and self.retest_fails:
            raise ValueError("a retest cannot both hold and fail")

    def lines(self) -> list[str]:
        b = self.brk
        out = [f"5m BREAK      {b.structure_id}  {b.band}  {b.direction} through "
               f"{float(b.edge):,.0f}   {b.at:%d %b %H:%M}",
               f"1m EXTENSION  {float(self.extension_pts):,.1f} pts beyond the edge",
               f"1m RETEST     {'yes' if self.retest_detected else 'no'}"]
        if self.retest_detected:
            out[-1] += (f"   at {float(self.retest_price):,.1f} after "
                        f"{self.bars_to_retest} bars")
            out.append(f"1m DEPTH      {float(self.retest_depth):,.1f} pts back through "
                       f"the edge   (gave back {float(self.retreat_pts):,.1f})")
        if self.rebreak_direction:
            out.append(f"1m RE-BREAK   {self.rebreak_direction} at "
                       f"{float(self.resolved_price):,.1f}, "
                       f"{self.bars_to_resolution} bars after the break")
        out.append(f"OUTCOME       {self.outcome}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
def breaks_from(readings: Sequence[Reading], m5: Sequence[Candle]) -> list[Break]:
    """Every accepted 5m break in a frontier run.

    `Reading.index` indexes into the frontier's own candle list, so `m5` must be the
    **full** 5m stream the frontier was given (history + live), not just the live tail.
    """
    out: list[Break] = []
    for r in readings:
        direction = ACCEPTED.get(r.interaction)
        if direction is None or r.left_id is None or r.left_edge is None:
            continue
        if r.left_low is None or r.left_high is None:
            continue
        out.append(Break(index=r.index, at=m5[r.index].close_time,
                         structure_id=r.left_id, direction=direction,
                         edge=r.left_edge, low=r.left_low, high=r.left_high))
    return out


def _first_after(m1: Sequence[Candle], at: datetime) -> int | None:
    """The first 1m bar that opens at or after the 5m break candle closed.

    Anything earlier is inside the breaking candle itself, and reading it would be
    look-ahead's mirror image: judging the aftermath with bars that produced the break.
    """
    times = [k.open_time for k in m1]
    i = bisect.bisect_left(times, at)
    return i if i < len(m1) else None


def observe(brk: Break, m1: Sequence[Candle], *, horizon: int = WINDOW_MAX,
            tol_atr: Decimal = Decimal("0.25"),
            break_closes: int = BREAK_CLOSES) -> RetestObservation | None:
    """Watch one 5m break on the 1m stream. Returns `None` if 1m data does not reach it."""
    start = _first_after(m1, brk.at)
    if start is None:
        return None

    up = brk.direction == "up"
    edge = brk.edge
    tol = tol_at(m1, start, tol_atr)
    end = min(start + horizon, len(m1))
    bars = end - start
    if bars <= 0:
        return None

    def beyond(v: Decimal) -> Decimal:
        """How far `v` sits past the edge, in the break's direction. Negative = inside."""
        return (v - edge) if up else (edge - v)

    # ── phase 1: the move away, and the first return to the edge ────────────
    ext_pts, ext_index, ext_price = ZERO, None, None
    contact = None
    for j in range(start, end):
        k = m1[j]
        far = beyond(k.h if up else k.l)
        if ext_price is None or far > ext_pts:
            ext_pts, ext_index, ext_price = far, j, (k.h if up else k.l)
        # contact = price trades back into the edge's own tolerance skirt
        if beyond(k.l if up else k.h) <= tol:
            contact = j
            break

    common = dict(brk=brk, start_index=start, horizon=horizon, bars_seen=bars, tol=tol,
                  extension_pts=ext_pts, extension_index=ext_index)

    if contact is None:
        return RetestObservation(outcome="NO_RETEST", **common)

    # ── phase 2: how deep, and which way it resolves ────────────────────────
    deepest = m1[contact].l if up else m1[contact].h
    closes_back = 0
    holds = fails = False
    resolved_index: int | None = None
    resolved_price: Decimal | None = None

    for j in range(contact, end):
        k = m1[j]
        deepest = min(deepest, k.l) if up else max(deepest, k.h)

        # failure: the repo's own acceptance rule, applied to the return leg
        inside = (k.c < edge) if up else (k.c > edge)
        closes_back = closes_back + 1 if inside else 0
        if closes_back >= break_closes:
            fails, resolved_index, resolved_price = True, j, k.c
            break

        # hold: a new extreme beyond everything made before the retest began
        if ext_price is not None and ((k.h > ext_price) if up else (k.l < ext_price)):
            holds, resolved_index = True, j
            resolved_price = k.h if up else k.l
            break

    outcome = ("RETEST_FAILED" if fails else
               "RETEST_HELD" if holds else "RETEST_UNRESOLVED")
    rebreak = ("" if resolved_index is None else
               ("down" if up else "up") if fails else brk.direction)
    depth = max(ZERO, -beyond(deepest))
    retreat = (ext_price - deepest) if up else (deepest - ext_price)

    return RetestObservation(
        retest_detected=True, retest_index=contact, retest_at=m1[contact].close_time,
        retest_price=deepest, retest_depth=depth,
        retreat_pts=max(ZERO, retreat), bars_to_retest=contact - start,
        retest_holds=holds, retest_fails=fails, rebreak_direction=rebreak,
        resolved_index=resolved_index, resolved_price=resolved_price,
        bars_to_resolution=None if resolved_index is None else resolved_index - start,
        outcome=outcome, **common)


def observe_all(readings: Sequence[Reading], m5: Sequence[Candle],
                m1: Sequence[Candle], **kw) -> list[RetestObservation]:
    out = []
    for brk in breaks_from(readings, m5):
        o = observe(brk, m1, **kw)
        if o is not None:
            out.append(o)
    return out


def tally(obs: Sequence[RetestObservation]) -> dict[str, int]:
    """Counts by outcome. A count, not a hit rate — the denominator matters and a ratio
    printed here would be read as a win rate by the first person who saw it."""
    counts = {k: 0 for k in sorted(OUTCOMES)}
    for o in obs:
        counts[o.outcome] += 1
    return counts


def compact(o: RetestObservation) -> str:
    b = o.brk
    r = f"{float(o.retest_price):>9,.1f}" if o.retest_price is not None else "        —"
    d = f"{float(o.retest_depth):>6,.1f}" if o.retest_detected else "     —"
    return (f"{b.at:%d %b %H:%M}  {b.structure_id:<5} {b.direction:<4} "
            f"{float(b.edge):>9,.1f}  ext {float(o.extension_pts):>6,.1f}  "
            f"retest {r}  depth {d}  {o.outcome}")


__all__ = ["OUTCOMES", "Break", "RetestObservation", "breaks_from", "observe",
           "observe_all", "tally", "compact"]
