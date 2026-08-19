"""
Break, direction, stop and target — all from candles that have already closed.

## The problem that had to be solved first

A box is re-derived on every candle, so at candle `i` the box **already contains candle
`i`**. A breakout candle widens the very box it is breaking, and the break hides itself:
by the time you look, the box has grown to swallow it.

So every event is judged against the box **as it stood before this candle closed**:

```
prior = compute_stack(candles[:i], atr)      # what the engine knew a minute ago
event = detect(prior, candles[i], i)         # what this candle did to it
```

That is also how a person sees it — *the box was there, and this candle closed above it.*
It uses no future data, and there is nothing to store: `candles[:i]` is a slice.

## Three events, never collapsed into two

| event | test against the prior box |
|---|---|
| **touch** | the wick reached the outer edge, the close stayed inside |
| **sweep** | the wick went beyond the outer edge, the close came back inside the inner band |
| **break** | the close finished beyond the outer edge |

A sweep is not a failed break and a break is not a large touch. Setup B exists entirely
in the difference.

## Where the stop goes, and why it is not negotiable

Beyond the **opposite outer edge of the box that broke**. That edge is where the
excursions from this rotation reached, which is where the stops are parked. Inside it you
are standing exactly where price is drawn to.

## Where the target comes from

Not from a multiple of R, and not from a guess. The candidate targets are **the structural
edges that already exist above and below** — L2's band, L1's extremes, L0's ceiling and
floor. Two are reported for every event:

* `first_target` — the nearest edge in the break's direction. The checkpoint.
* `full_target` — the far edge of the widest box price is crossing. The trader's rule:
  *"sabse niche se upar ja rahe h to pura pullback box, na ki range box ke upar wala."*

Both, always, because a plan with one number in it cannot tell you whether it was reached
early or missed late.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.boxes.engine import Box, Stack
from src.domain.models import ZERO, Candle


@dataclass(frozen=True, slots=True)
class BoxEvent:
    kind: str                     # break | sweep | touch
    direction: str                # up | down
    index: int
    entry: Decimal
    stop: Decimal
    r: Decimal
    first_target: Decimal | None
    full_target: Decimal | None
    first_name: str = ""
    full_name: str = ""
    pos_l1: Decimal | None = None
    pos_l2: Decimal | None = None
    alignment: str = ""

    @property
    def r_to_first(self) -> Decimal | None:
        if self.first_target is None or self.r <= ZERO:
            return None
        return abs(self.first_target - self.entry) / self.r

    @property
    def r_to_full(self) -> Decimal | None:
        if self.full_target is None or self.r <= ZERO:
            return None
        return abs(self.full_target - self.entry) / self.r


def _edges(stack: Stack) -> list[tuple[str, Decimal]]:
    """Every structural price the stack knows about, from boxes that are not L3.

    L3 is excluded on purpose: it is the thing being broken, so its own edges cannot also
    be the destination.
    """
    out: list[tuple[str, Decimal]] = []
    for name, box in (("L2", stack.l2), ("L1r", stack.l1r), ("L1", stack.l1),
                      ("L0r", stack.l0r), ("L0", stack.l0)):
        if box is None or (box.degenerate and box.inner_width <= ZERO):
            continue
        out.append((f"{name}.low", box.outer_low))
        out.append((f"{name}.high", box.outer_high))
    return out


def _widest_crossed(stack: Stack, price: Decimal, up: bool) -> tuple[str, Decimal] | None:
    """The far edge of the widest box price is currently inside.

    This is the trader's target rule. If price is inside L1 and travelling up, the
    destination is L1's high — L2's edge on the way is a checkpoint where a new rotation
    will form, not the destination.
    """
    for name, box in (("L0", stack.l0), ("L1", stack.l1), ("L2", stack.l2)):
        if box is None:
            continue
        if box.outer_low <= price <= box.outer_high:
            edge = box.outer_high if up else box.outer_low
            if (edge - price if up else price - edge) > ZERO:
                return f"{name}.{'high' if up else 'low'}", edge
    return None


def detect(prior: Stack, candle: Candle, index: int,
           *, previous: Candle | None = None,
           touch_tol: Decimal | None = None) -> BoxEvent | None:
    """What this candle did to the box that existed before it. `None` when nothing did.

    `prior` MUST be built from `candles[:index]`. Passing the stack that already contains
    this candle is the one way to make this function lie, and it will lie quietly —
    the breakout candle will have widened the box past its own close.
    """
    box: Box | None = prior.l3
    if box is None or candle.synthetic:
        return None

    span = box.outer_high - box.outer_low
    tol = touch_tol if touch_tol is not None else span / 10

    up = candle.c > box.outer_high
    down = candle.c < box.outer_low

    if up or down:
        # A break is a TRANSITION, not a state. Once price is outside, every following
        # candle is also outside, and the first version fired on all of them: candles
        # 34, 35, 36 on 2026-02-16 were one move reported three times, and 57-60 four.
        #
        # The transition is checkable without storing anything — the previous candle must
        # have closed INSIDE the box this one closed outside of.
        if previous is not None and not (box.outer_low <= previous.c <= box.outer_high):
            return None
        kind, direction = "break", ("up" if up else "down")
        stop = box.outer_low if up else box.outer_high
    elif candle.h > box.outer_high and candle.c <= box.inner_high:
        kind, direction = "sweep", "down"          # swept the top, rejected -> short bias
        stop = candle.h
    elif candle.l < box.outer_low and candle.c >= box.inner_low:
        kind, direction = "sweep", "up"
        stop = candle.l
    elif candle.h >= box.outer_high - tol or candle.l <= box.outer_low + tol:
        kind = "touch"
        direction = "down" if candle.h >= box.outer_high - tol else "up"
        stop = box.outer_high if direction == "down" else box.outer_low
    else:
        return None

    entry = candle.c
    r = abs(entry - stop)
    going_up = direction == "up"

    ahead = [(n, p) for n, p in _edges(prior)
             if (p - entry if going_up else entry - p) > ZERO]
    ahead.sort(key=lambda pair: abs(pair[1] - entry))
    first_name, first = ahead[0] if ahead else ("", None)

    widest = _widest_crossed(prior, entry, going_up)
    full_name, full = widest if widest else (first_name, first)

    pos_l1 = prior.l1.position(entry) if prior.l1 else None
    pos_l2 = prior.l2.position(entry) if prior.l2 else None
    return BoxEvent(kind, direction, index, entry, stop, r,
                    first, full, first_name, full_name,
                    pos_l1, pos_l2, _alignment(pos_l1, pos_l2, going_up))


def _alignment(pos_l1: Decimal | None, pos_l2: Decimal | None, up: bool) -> str:
    """Where in the stack this happened — which is the whole of grading.

    `BOX-MODEL.md` §6. Position is continuous, so this label is a *description* of two
    numbers that are always reported alongside it, never a replacement for them. Anything
    downstream that needs a finer distinction should read `pos_l1` and `pos_l2`.
    """
    if pos_l1 is None:
        return "unknown"
    base = (pos_l1 < Decimal("0.25")) if up else (pos_l1 > Decimal("0.75"))
    extended = (pos_l1 > Decimal("0.75")) if up else (pos_l1 < Decimal("0.25"))
    away = None
    if pos_l2 is not None:
        away = (pos_l2 > 1) if up else (pos_l2 < 0)

    if base:
        return "from the base of the move"          # the trader's best case
    if extended and away:
        return "extended, and already past the consolidation"
    if extended:
        return "extended"
    return "mid-move"
