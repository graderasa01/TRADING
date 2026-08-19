"""
The scan machine — many rolling windows at once, and the prices they agree on.

## What was wrong with the previous design, in the trader's words

> *"rolling window candles ko chhode nahi"*

The earlier version made each larger box **skip** the candles the smaller one covered, so
that L2 and L3 could not produce the same band. That was backwards, and it threw away the
most useful thing in the whole model.

When a 20-candle window and a 75-candle window land on the same price, that is not a
collapse to be engineered away. **It is two independent scales agreeing**, and agreement
is exactly what makes a price matter. The `skip` deleted the evidence.

## The second thing that was wrong

Each window was treated as producing *one* answer — either a cluster or a span, never
both. But a rolling window gives two, and they mean different things:

* **the cluster** — where price paused inside the window. Where it may pause again.
* **the window's high and low** — how far it got. **The obstacle.** The target.

> *"hmko wah us window me low and high wah kaam ayenge... wah hi hmare target bn jayenge...
> us window me high matlab wah uska rukawat point ho sakta hai."*

So one window emits four prices, not one band.

## What this is

Plain rolling windows, no skipping, at many sizes at once:

```
for N in WINDOWS:
    window = candles[-N:]                  # nothing dropped, ever
    -> cluster_low, cluster_high           # where it paused
    -> window_low,  window_high            # how far it got
```

Every price is then merged with its neighbours, and a level's **strength is the number of
distinct windows that produced it.** No threshold decides which levels matter; the scales
vote, and the count is the answer.

That is also why the window list can be long. A scan at eight sizes is not eight times
the complexity — it is one function called eight times, and the extra sizes make the vote
sharper rather than the model bigger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import accumulate
from typing import Sequence

from src.domain.models import ZERO, Candle

MIN_STEP = Decimal("0.05")

# Roughly doubling, from a couple of candles' rotation to a fortnight of context. Every
# one is a plain `candles[-N:]`.
WINDOWS: tuple[int, ...] = (10, 20, 40, 75, 150, 375, 750, 1875, 3750)


@dataclass(frozen=True, slots=True)
class WindowRead:
    """What one rolling window says. Four prices, two meanings."""
    n: int
    cluster_low: Decimal
    cluster_high: Decimal
    window_low: Decimal
    window_high: Decimal
    has_cluster: bool
    candles: int

    def position(self, price: Decimal) -> Decimal | None:
        """Where price sits between this window's low and high. 0 at the low, 1 at the
        high. This is the window's own answer to *"kahan phase hue hain"*."""
        span = self.window_high - self.window_low
        if span <= ZERO:
            return None
        return (price - self.window_low) / span


@dataclass
class Level:
    """A price several windows agree on. Strength is the count, not a score."""
    price: Decimal
    kind: str                                  # "pause" | "edge"
    windows: list[int] = field(default_factory=list)
    lo: Decimal = ZERO
    hi: Decimal = ZERO

    @property
    def strength(self) -> int:
        return len(set(self.windows))

    @property
    def biggest_window(self) -> int:
        return max(self.windows) if self.windows else 0


def read_window(candles: Sequence[Candle], n: int, atr: Decimal,
                density_min: Decimal = Decimal("0.5")) -> WindowRead | None:
    """One plain rolling window. **Nothing is skipped and nothing is stored.**"""
    window = [k for k in candles[-n:] if not k.synthetic]
    if not window:
        return None

    lo = min(k.l for k in window)
    hi = max(k.h for k in window)
    if hi <= lo:
        return WindowRead(n, lo, hi, lo, hi, False, len(window))

    step = max(atr / 10, MIN_STEP) if atr > ZERO else MIN_STEP
    buckets = int((hi - lo) / step) + 1
    if buckets < 2:
        return WindowRead(n, lo, hi, lo, hi, False, len(window))

    def bucket(price: Decimal) -> int:
        return max(0, min(buckets - 1, int((price - lo) / step)))

    delta = [0] * (buckets + 1)
    for k in window:
        delta[bucket(k.l)] += 1
        delta[bucket(k.h) + 1] -= 1
    coverage = list(accumulate(delta[:-1]))

    peak = max(coverage)
    if peak <= 0:
        return WindowRead(n, lo, hi, lo, hi, False, len(window))

    threshold = Decimal(peak) * density_min
    here = coverage.index(peak)
    left = right = here
    while left > 0 and Decimal(coverage[left - 1]) >= threshold:
        left -= 1
    while right < buckets - 1 and Decimal(coverage[right + 1]) >= threshold:
        right += 1

    return WindowRead(n, lo + step * left, lo + step * (right + 1), lo, hi,
                      True, len(window))


def scan(candles: Sequence[Candle], atr: Decimal,
         windows: Sequence[int] = WINDOWS,
         density_min: Decimal = Decimal("0.5")) -> list[WindowRead]:
    reads = [read_window(candles, n, atr, density_min) for n in windows]
    return [r for r in reads if r is not None]


def levels(reads: Sequence[WindowRead], atr: Decimal,
           tolerance_atr: Decimal = Decimal("0.3")) -> list[Level]:
    """Merge every window's prices into levels, strength = how many windows agree.

    Two windows landing on one price is the whole signal. Nothing here scores, weights or
    ranks by anything except that count — which means there is no parameter deciding
    which levels matter, only the tolerance that decides when two prices are the same one.
    """
    tol = max(atr * tolerance_atr, MIN_STEP)
    raw: list[tuple[Decimal, str, int]] = []
    for r in reads:
        if r.has_cluster:
            raw.append((r.cluster_low, "pause", r.n))
            raw.append((r.cluster_high, "pause", r.n))
        raw.append((r.window_low, "edge", r.n))
        raw.append((r.window_high, "edge", r.n))

    out: list[Level] = []
    for price, kind, n in sorted(raw):
        if out and price - out[-1].hi <= tol:
            lv = out[-1]
            lv.hi = max(lv.hi, price)
            lv.price = (lv.lo + lv.hi) / 2
            lv.windows.append(n)
            if kind == "edge":
                lv.kind = "edge" if lv.kind == "edge" else "both"
        else:
            out.append(Level(price=price, kind=kind, windows=[n], lo=price, hi=price))
    return out


@dataclass
class View:
    """Everything the scan can say at one candle, from candles that have already closed."""
    close: Decimal
    reads: list[WindowRead]
    levels: list[Level]

    def inside(self) -> list[WindowRead]:
        """Which windows' clusters price is standing in — *"abhi kis me phase hain"*."""
        return [r for r in self.reads
                if r.has_cluster and r.cluster_low <= self.close <= r.cluster_high]

    def above(self, min_strength: int = 1) -> list[Level]:
        return [lv for lv in self.levels
                if lv.lo > self.close and lv.strength >= min_strength]

    def below(self, min_strength: int = 1) -> list[Level]:
        return [lv for lv in reversed(self.levels)
                if lv.hi < self.close and lv.strength >= min_strength]

    def next_above(self, min_strength: int = 2) -> Level | None:
        """*"agar nahi milte to next par karte"* — nothing strong enough nearby simply
        means the answer comes from a wider window, which is already in the list."""
        found = self.above(min_strength)
        return found[0] if found else None

    def next_below(self, min_strength: int = 2) -> Level | None:
        found = self.below(min_strength)
        return found[0] if found else None


def view(candles: Sequence[Candle], atr: Decimal,
         windows: Sequence[int] = WINDOWS,
         density_min: Decimal = Decimal("0.5"),
         tolerance_atr: Decimal = Decimal("0.3")) -> View:
    reads = scan(candles, atr, windows, density_min)
    return View(candles[-1].c, reads, levels(reads, atr, tolerance_atr))


# ─────────────────────────────────────────────────────────────────────────────
# what is waiting at a price — the trader's question the scan could not answer
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Pocket:
    """What price did the LAST time it was at this level.

    > *"jo upar high aur low dikh rahe h wanha par box dhundhna chahiye, jisase price jaye
    > to anuman rahe ki kis box ki range ke lagbhag price ghumega"*

    A level says where price may stop. It does not say **how wide the stopping is**, and
    those are different trades: arriving where the market once rotated ninety candles
    across sixty points is a wall; arriving where it passed through in two is air.

    ## The bug this class was born with

    The first version took the min low and max high of **every** candle that had ever
    touched the level. Over a fortnight that is twenty separate visits, and one violent
    bar on any of them stretched the answer to nonsense — every level on 2026-02-16 came
    back as *"rotated 60,258-61,765"*, a 1,500-point pocket, which is not an estimate of
    anything.

    So the band comes from the **most recent visit only** — a contiguous run of bars at
    that price. The full history still contributes the two numbers that belong to it:
    how many separate visits there have been, and how many bars in total. A level tested
    nineteen times is well tested; that is a different fact from how wide it is.
    """
    price: Decimal
    low: Decimal                   # the last visit's range, not all of history's
    high: Decimal
    candles: int                   # bars in the last visit
    total_candles: int             # bars across every visit
    visits: int                    # separated occasions
    last_seen_ago: int | None

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    def verdict(self, atr: Decimal) -> str:
        if self.total_candles == 0:
            return "air — price has never traded here"
        if atr <= ZERO:
            return "unknown"
        wide = self.width / atr
        if self.candles <= 2:
            return f"thin — last visit was {self.candles} bar(s), straight through"
        if self.candles >= 15 and wide >= Decimal("1.5"):
            return f"wall — last visit {self.candles} bars over {float(wide):.1f} x ATR"
        return f"pause — last visit {self.candles} bars over {float(wide):.1f} x ATR"


def pocket_at(candles: Sequence[Candle], price: Decimal, atr: Decimal,
              *, tolerance_atr: Decimal = Decimal("0.25"),
              gap: int = 10, lookback: int = 3750) -> Pocket:
    """The rotation band that formed around `price` the last time price was there."""
    tol = max(atr * tolerance_atr, MIN_STEP)
    window = candles[-lookback:]
    members = [(i, k) for i, k in enumerate(window)
               if not k.synthetic and k.l - tol <= price <= k.h + tol]
    if not members:
        return Pocket(price, price, price, 0, 0, 0, None)

    # Split into visits. A level touched on ninety consecutive candles was visited once;
    # counting that as ninety would make any recent chop look like history.
    visits: list[list] = [[members[0]]]
    for prev, cur in zip(members, members[1:]):
        (visits[-1] if cur[0] - prev[0] <= gap else visits.append([]) or visits[-1]).append(cur)

    last = visits[-1]
    lows = [k.l for _, k in last]
    highs = [k.h for _, k in last]
    return Pocket(price, min(lows), max(highs), len(last), len(members), len(visits),
                  len(window) - 1 - members[-1][0])


def drift(reads: Sequence[WindowRead]) -> tuple[Decimal | None, str]:
    """Direction, read off the cluster centres across scales.

    If the 10-candle rotation sits above the 375-candle rest, price has been climbing away
    from where it last settled. No trend indicator, no swing detection, no confirmation
    lag — the scan already holds every scale, and the *shape* across them is the trend.
    """
    centres = [(r.n, (r.cluster_low + r.cluster_high) / 2) for r in reads if r.has_cluster]
    if len(centres) < 3:
        return None, "unknown"
    fast = sum(c for n, c in centres[:3]) / 3
    slow = sum(c for n, c in centres[-3:]) / 3
    gap = fast - slow
    spans = [r.window_high - r.window_low for r in reads if r.n >= 375]
    scale = max(spans) if spans else ZERO
    if scale <= ZERO:
        return gap, "unknown"
    ratio = gap / scale
    if ratio > Decimal("0.15"):
        return gap, "up — the near scales sit above the far ones"
    if ratio < Decimal("-0.15"):
        return gap, "down — the near scales sit below the far ones"
    return gap, "flat — the scales agree on where price belongs"
