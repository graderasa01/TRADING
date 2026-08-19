"""
The box engine — stateless. `BOX-MODEL.md`.

One function, called at several window lengths. Nothing is stored between candles, so
there is no birth, no death, no merge, no revival, no cap and no dormancy. Every box on
screen is re-derived from the last N closed candles.

    box = compute_box(candles_up_to_now, n=20, atr=atr20)

## The two decisions inside `compute_box`

**Coverage, not extremes.** `[min low, max high]` over a window is a Donchian channel, and
one spike moves its edge to a price nobody traded. Instead every candle's range votes for
the prices it covers, and the box is the band that most candles voted for. A spike
contributes one vote to a region nobody else touched and moves nothing.

**Threshold relative to the window's own maximum, never absolute.** On a trending session
no price is touched by many candles — coverage is low everywhere. An absolute threshold
finds no band at all on exactly the days that matter most, so the bar is
`density_min x max_coverage`.

## Inner and outer, and which level reads which

`inner` is the dense band — where price worked. `outer` is the extreme of the candles that
touched that band — where the excursions from it reached, which is where the stops are.
These are `body_edge` and `wick_tip` from the level model, applied to a box.

They are not interchangeable and each level reads the pair it needs:

* **L3** reads `inner` — the rotation.
* **L1** reads `outer` — a move's boundary is its extremes, not where it paused.
* **L2** reads both — `inner` is the range's body, `outer` is its sweep zone.

## Cost

Coverage is accumulated with a difference array and one pass of `accumulate`, so a box is
O(window + grid) rather than O(window x grid). Three boxes on 375 candles is a few
million operations, which is why this can run on every candle of a three-year replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import accumulate
from typing import Sequence

from src.domain.models import ZERO, Candle

MIN_STEP = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class Box:
    """A band price is inside. Has no identity and is never stored — the next candle
    produces a new one, and comparing the two is how movement is measured."""
    name: str
    inner_low: Decimal
    inner_high: Decimal
    outer_low: Decimal
    outer_high: Decimal
    window: int                    # candles the box was derived from
    members: int                   # of those, how many touch the inner band
    degenerate: bool = False       # the close sits in no dense band: price is travelling

    @property
    def inner_width(self) -> Decimal:
        return self.inner_high - self.inner_low

    @property
    def outer_width(self) -> Decimal:
        return self.outer_high - self.outer_low

    @property
    def mid(self) -> Decimal:
        return (self.inner_low + self.inner_high) / 2

    def position(self, price: Decimal) -> Decimal | None:
        """Where `price` sits inside the inner band. 0 at the low, 1 at the high, and
        outside [0, 1] when price has left it.

        This is the whole of direction and grading — `BOX-MODEL.md` §4 and §6 — so it is
        deliberately a continuous number and never bucketed here. A threshold applied at
        this point would put a cliff edge under every downstream decision.
        """
        if self.inner_width <= ZERO:
            return None
        return (price - self.inner_low) / self.inner_width


def compute_box(candles: Sequence[Candle], n: int, atr: Decimal,
                *, density_min: Decimal = Decimal("0.5"),
                mode: str = "around_close",
                skip: int = 0,
                name: str = "box") -> Box | None:
    """The last `n` closed candles in, one band out. Reads nothing else.

    ## `mode` — and why one algorithm was not enough

    The first version used the dense band containing the close at every window length.
    Measured on real sessions it was **degenerate 56% of the time at L2 and 60% at L1**,
    with a median inner width of zero. The reason is not a bad threshold: over a long
    window price *moves away* from where it spent the most time, so "the dense band
    containing the close" is usually empty by construction.

    So the three levels are three different questions, and each gets the mode that
    answers it:

    * `around_close` — the dense band the close is inside. **The rotation.** L3.
    * `densest` — the densest band anywhere in the window, close or not. **The
      consolidation price is travelling toward or away from.** L2. It is a target, so it
      has no business requiring price to be inside it.
    * `extremes` — the window's high and low. **A move's boundary is its extremes**, not
      where it paused inside them. L1 and L0.

    Returns `None` only when there are no usable candles. `degenerate` means the close is
    in no dense band — a real answer, not a failure: it says price is travelling.
    """
    # `skip` drops the most recent candles BEFORE the window is taken. L2 uses it to
    # exclude the candles L3 already covers.
    #
    # Without it L2 and L3 collapse. Measured at 12:47 on 2026-02-16:
    #     L3  60,670.4 - 60,719.0
    #     L2  60,663.2 - 60,714.0
    # — one band wearing two names, and no target between them, because the densest band
    # over 75 candles IS the rotation when 20 of those 75 are the rotation. L2 is meant
    # to be the structure price is travelling toward or away FROM, which means it cannot
    # be built out of where price is standing.
    source = candles[:-skip] if skip else candles
    window = [k for k in source[-n:] if not k.synthetic]
    if not window:
        return None

    lo = min(k.l for k in window)
    hi = max(k.h for k in window)
    close = candles[-1].c
    step = max(atr / 10, MIN_STEP) if atr > ZERO else MIN_STEP

    if mode == "extremes":
        return Box(name, lo, hi, lo, hi, len(window), len(window))

    if hi <= lo:
        return Box(name, lo, hi, lo, hi, len(window), len(window), degenerate=True)

    buckets = int((hi - lo) / step) + 1
    if buckets < 2:
        return Box(name, lo, hi, lo, hi, len(window), len(window), degenerate=True)

    def bucket(price: Decimal) -> int:
        return max(0, min(buckets - 1, int((price - lo) / step)))

    # coverage(p) = how many candles span p, via a difference array
    delta = [0] * (buckets + 1)
    for k in window:
        delta[bucket(k.l)] += 1
        delta[bucket(k.h) + 1] -= 1
    coverage = list(accumulate(delta[:-1]))

    peak = max(coverage)
    if peak <= 0:
        return Box(name, lo, hi, lo, hi, len(window), len(window), degenerate=True)
    threshold = Decimal(peak) * density_min

    # `densest` anchors on the peak; `around_close` anchors on where price is now.
    here = bucket(close) if mode == "around_close" else coverage.index(peak)
    if Decimal(coverage[here]) < threshold:
        # Price is in no dense band. Do not invent one: report the close's own bucket as a
        # zero-width band and let the caller see that price is travelling.
        return Box(name, close, close, lo, hi, len(window), 0, degenerate=True)

    left = here
    while left > 0 and Decimal(coverage[left - 1]) >= threshold:
        left -= 1
    right = here
    while right < buckets - 1 and Decimal(coverage[right + 1]) >= threshold:
        right += 1

    inner_low = lo + step * left
    inner_high = lo + step * (right + 1)

    # outer = the extremes of the candles that touch the band. NOT of the whole window —
    # a spike 300 points away would otherwise set the edge a sweep is measured from.
    members = [k for k in window if k.l <= inner_high and k.h >= inner_low]
    if not members:
        members = window
    return Box(name, inner_low, inner_high,
               min(k.l for k in members), max(k.h for k in members),
               len(window), len(members))


LEVELS = ("l3", "l2", "l1r", "l1", "l0r", "l0")


@dataclass(frozen=True, slots=True)
class Stack:
    """Two questions at each scale, plus the rotation.

    **How far did it go** (`extremes`) and **where did it rest** (`densest`) are different
    questions, and the pair is what makes a target: you travel between rests, bounded by
    spans.

    The first version asked only one of them at the big scales — `l1` and `l0` were pure
    extremes, with no structure inside them at all. The cost was measurable: over six
    sessions the median break had its first target at 0.93R and its full target at 6.91R,
    **with nothing between them.** `l1r` and `l0r` are the missing cells of that grid.

    This is six boxes rather than three, and that is not the old 8-level cap returning.
    The cap was a limit on a *search* — the engine found 204 levels and kept 8, so *which*
    eight became the real decision. These six come from a grid: two questions x three
    scales, plus the rotation. The count is structural, not selected.
    """
    l3: Box | None                 # rotation now
    l2: Box | None                 # rest, ~an hour
    l1r: Box | None                # rest, the day
    l1: Box | None                 # span, the day
    l0r: Box | None                # rest, the week
    l0: Box | None                 # span, the week

    def positions(self, price: Decimal) -> dict[str, Decimal | None]:
        return {name: (b.position(price) if b else None)
                for name, b in zip(LEVELS, (self.l3, self.l2, self.l1r,
                                            self.l1, self.l0r, self.l0))}


DEFAULT_WINDOWS = {"l3": 20, "l2": 75, "l1r": 375, "l1": 375, "l0r": 1875, "l0": 1875}
MODES = {"l3": "around_close", "l2": "densest", "l1r": "densest",
         "l1": "extremes", "l0r": "densest", "l0": "extremes"}
# Each REST box looks back past everything the smaller boxes already describe, so no two
# of them can collapse onto the same band. Spans are not skipped: a move's boundary
# includes where price is standing.
SKIPS = {"l3": 0, "l2": 20, "l1r": 95, "l1": 0, "l0r": 470, "l0": 0}


def compute_stack(candles: Sequence[Candle], atr: Decimal,
                  windows: dict[str, int] | None = None,
                  density_min: Decimal = Decimal("0.5"),
                  modes: dict[str, str] | None = None) -> Stack:
    """The whole board for one candle.

    `candles` may — and for L1 and L0 should — reach back across session boundaries. That
    is what removes the warm-up special case: at 09:30 the L1 window still contains
    yesterday, so there is nothing to load and nothing to inherit.
    """
    w = windows or DEFAULT_WINDOWS
    m = modes or MODES
    return Stack(*(compute_box(candles, w[k], atr, density_min=density_min,
                               mode=m[k], skip=SKIPS[k], name=k)
                   for k in LEVELS))
