"""
The map — boxes cut from history once, frozen, and waited on.

## Why the previous design could not work, in the trader's words

> *"ye box dobara jab banenge jab ye toot jaye. baar baar scan karoge to hm break ka
> intezar nahi kar payenge, aur kitni doori par hai wah kuchh bhi samajh nahi aayega,
> kya kahani banani chahiye points se wah bhi nahi samajh aayegi."*

The earlier engine re-derived every box on every candle. That removed all the bookkeeping
problems and destroyed the only thing a plan is made of: **a reference that stays put.**

When the box moves with price, three things stop existing:

* **waiting for a break** — the box widened to contain the candle that broke it
* **distance to a target** — the target moved while price travelled toward it
* **the story** — a new one every minute is not a story

So history is cut **once**, into fixed blocks, and those blocks never move again. Only the
block still forming is alive.

## How the map is built

> *"tum pehle 20-20 candles karke peeche ki market ko scan karo aur box bana do."*

```
... [c-60 .. c-41] [c-40 .. c-21] [c-20 .. c-1] | [current, still forming]
      frozen            frozen         frozen          alive
```

Each block gives one box: its **high and low** (how far price got in those twenty
minutes) and its **cluster** (where inside it price actually sat). Blocks whose price
ranges overlap are then merged into one **zone**, because two adjacent twenty-minute
boxes at the same price are one shelf, not two.

A zone touched by many separate blocks is a shelf price kept returning to. That count is
its strength — the same idea as before, but now it counts *visits over time* rather than
*window sizes*, which is what a trader means by a level being "tested".

Nothing here is re-derived while price sits still. The map changes only when a block
closes, and a block closes every twenty candles — so a target set at 10:20 is still the
same number at 10:38.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import accumulate
from typing import Sequence

from src.domain.models import ZERO, Candle

MIN_STEP = Decimal("0.05")
BLOCK = 20


@dataclass(frozen=True, slots=True)
class Block:
    """One fixed slice of history. Frozen the moment its last candle closes."""
    index: int                     # 0 = oldest block
    first: int                     # candle indices into the stream
    last: int
    low: Decimal
    high: Decimal
    cluster_low: Decimal
    cluster_high: Decimal
    open_: Decimal
    close: Decimal
    alive: bool = False            # the block still forming

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2

    @property
    def direction(self) -> str:
        if self.close > self.open_:
            return "up"
        return "down" if self.close < self.open_ else "flat"


@dataclass
class Zone:
    """Overlapping blocks merged. A shelf, with how many separate visits made it."""
    low: Decimal
    high: Decimal
    blocks: list[int] = field(default_factory=list)
    visits: int = 1
    cluster_low: Decimal | None = None
    cluster_high: Decimal | None = None

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2

    @property
    def strength(self) -> int:
        """Separate visits, not blocks. Twelve consecutive blocks in one shelf is one
        long stay; three visits months apart is a level the market keeps honouring."""
        return self.visits

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high


def _cluster(window: Sequence[Candle], atr: Decimal,
             density_min: Decimal = Decimal("0.5")) -> tuple[Decimal, Decimal]:
    lo = min(k.l for k in window)
    hi = max(k.h for k in window)
    if hi <= lo:
        return lo, hi
    step = max(atr / 10, MIN_STEP) if atr > ZERO else MIN_STEP
    buckets = int((hi - lo) / step) + 1
    if buckets < 2:
        return lo, hi

    def bucket(price: Decimal) -> int:
        return max(0, min(buckets - 1, int((price - lo) / step)))

    delta = [0] * (buckets + 1)
    for k in window:
        delta[bucket(k.l)] += 1
        delta[bucket(k.h) + 1] -= 1
    coverage = list(accumulate(delta[:-1]))
    peak = max(coverage)
    if peak <= 0:
        return lo, hi
    threshold = Decimal(peak) * density_min
    here = coverage.index(peak)
    left = right = here
    while left > 0 and Decimal(coverage[left - 1]) >= threshold:
        left -= 1
    while right < buckets - 1 and Decimal(coverage[right + 1]) >= threshold:
        right += 1
    return lo + step * left, lo + step * (right + 1)


def build_blocks(candles: Sequence[Candle], atr: Decimal,
                 size: int = BLOCK) -> list[Block]:
    """Cut the stream into fixed blocks, oldest first. The final block is `alive`.

    Blocks are aligned to the END of the stream, so the live block always holds exactly
    the most recent candles and every frozen block keeps the same boundaries it had when
    it closed. Aligning from the start would re-cut every block each time a candle
    arrived — the same instability, moved one level down.
    """
    n = len(candles)
    if n == 0:
        return []
    out: list[Block] = []
    edges = list(range(n, 0, -size))[::-1]      # right-aligned block starts
    starts = [max(0, e - size) for e in edges]
    for i, (a, b) in enumerate(zip(starts, edges)):
        window = [k for k in candles[a:b] if not k.synthetic]
        if not window:
            continue
        cl, ch = _cluster(window, atr)
        out.append(Block(index=i, first=a, last=b - 1,
                         low=min(k.l for k in window), high=max(k.h for k in window),
                         cluster_low=cl, cluster_high=ch,
                         open_=window[0].o, close=window[-1].c,
                         alive=(b == n)))
    return out


def shelves(blocks: Sequence[Block], atr: Decimal,
            tolerance_atr: Decimal = Decimal("0.3")) -> list[Zone]:
    """Where many blocks' EDGES land on the same price. That is a shelf.

    ## The bug this replaced

    The first version merged blocks whose ranges overlapped. Over 94 blocks each one
    overlaps its neighbour, so single-linkage chained the lot into **one zone 1,000 points
    wide**, and the story came back "UPAR kuchh nahi" at every candle — price was always
    inside the only zone there was.

    Overlap is the wrong relation. Two blocks overlapping means price passed through the
    same air; it says nothing about a level. What says something is **many blocks stopping
    at the same price** — their highs and lows landing together. So the edges are
    clustered, not the ranges, and a shelf's strength is how many distinct blocks put an
    edge there.
    """
    tol = max(atr * tolerance_atr, MIN_STEP)
    edges: list[tuple[Decimal, int]] = []
    for b in blocks:
        edges.append((b.low, b.index))
        edges.append((b.high, b.index))
    edges.sort()

    zones: list[Zone] = []
    for price, idx in edges:
        if zones and price - zones[-1].high <= tol:
            z = zones[-1]
            z.high = price
            z.blocks.append(idx)
        else:
            zones.append(Zone(low=price, high=price, blocks=[idx]))

    for z in zones:
        members = sorted(set(z.blocks))
        # separate visits: consecutive block numbers are one stay, not several
        z.visits = 1 + sum(1 for a, b in zip(members, members[1:]) if b - a > 1)
    return zones


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Map:
    blocks: list[Block]
    zones: list[Zone]
    close: Decimal
    atr: Decimal

    @property
    def live(self) -> Block | None:
        return self.blocks[-1] if self.blocks and self.blocks[-1].alive else None

    def zone_of(self, price: Decimal) -> Zone | None:
        for z in self.zones:
            if z.contains(price):
                return z
        return None

    def above(self, price: Decimal, min_blocks: int = 2) -> list[Zone]:
        """Shelves above `price`. `min_blocks` is what separates a shelf from one block's
        stray edge — a single block stopping somewhere once is not a level."""
        return [z for z in self.zones
                if z.low > price and len(set(z.blocks)) >= min_blocks]

    def below(self, price: Decimal, min_blocks: int = 2) -> list[Zone]:
        return [z for z in reversed(self.zones)
                if z.high < price and len(set(z.blocks)) >= min_blocks]

    def just_left(self, lookback: int = 6) -> Block | None:
        """The last frozen block whose range no longer contains price — *"abhi price kis
        box se nikal aayi hai"*."""
        for b in reversed(self.blocks[:-1][-lookback:]):
            if not (b.low <= self.close <= b.high):
                return b
        return None

    def drift(self, n: int = 5) -> str:
        """Direction from the last `n` frozen block mids. No indicator, no swing lag."""
        mids = [b.mid for b in self.blocks[-n - 1:-1]]
        if len(mids) < 3:
            return "unknown"
        gap = mids[-1] - mids[0]
        if abs(gap) < self.atr:
            return "flat"
        return "up" if gap > ZERO else "down"


def build_map(candles: Sequence[Candle], atr: Decimal, size: int = BLOCK) -> Map:
    blocks = build_blocks(candles, atr, size)
    return Map(blocks, shelves(blocks, atr), candles[-1].c, atr)


# ─────────────────────────────────────────────────────────────────────────────
# the story — what a trader would say out loud at this candle
# ─────────────────────────────────────────────────────────────────────────────
def story(m: Map, timeframe: str = "1m") -> list[str]:
    """The map read aloud. Every line is a fact from frozen blocks, none of it moves
    until a block closes.

    > *"wah ek real trader ki price action ki kahani honi chahiye"*

    Six sentences, always in the same order, because a story whose shape changes cannot
    be compared to yesterday's:

        1. where am I standing
        2. where did I come from
        3. which way have the last blocks been walking
        4. what is above, and how far
        5. what is below, and how far
        6. the if-then, both sides, written before the candle
    """
    price = m.close
    out: list[str] = []
    live = m.live
    ups_all, downs_all = m.above(price), m.below(price)
    ceiling = ups_all[0] if ups_all else None
    floor = downs_all[0] if downs_all else None

    if ceiling and floor:
        room = ceiling.low - floor.high
        pos = ((price - floor.high) / room * 100) if room > ZERO else Decimal(50)
        where = "upper" if pos > 66 else "lower" if pos < 33 else "middle"
        out.append(f"ABHI       {float(price):,.0f} — {float(floor.high):,.0f} aur "
                   f"{float(ceiling.low):,.0f} ke beech, {where} me ({float(pos):.0f}%), "
                   f"jagah {float(room):,.0f} pts")
    else:
        out.append(f"ABHI       {float(price):,.0f} — ek taraf koi shelf nahi, khuli jagah")

    left = m.just_left()
    if left:
        side = "upar" if price > left.high else "neeche"
        gap = (price - left.high) if price > left.high else (left.low - price)
        out.append(f"AAYA       block #{left.index} ({float(left.low):,.0f}-"
                   f"{float(left.high):,.0f}) se {side} nikli, ab {float(gap):,.0f} pts door")
    else:
        out.append("AAYA       abhi tak kisi frozen block se bahar nahi nikli")

    out.append(f"CHAAL      pichhle 5 block: {m.drift()}"
               + (f"   (live block {float(live.low):,.0f}-{float(live.high):,.0f}, "
                  f"{live.last - live.first + 1} candles)" if live else ""))

    ups = ups_all[:2]
    if ups:
        out.append("UPAR       " + "   phir   ".join(
            f"{float(z.low):,.0f}-{float(z.high):,.0f} "
            f"(+{float(z.low - price):,.0f} pts, {len(set(z.blocks))} blocks / "
            f"{z.strength} visits)" for z in ups))
    else:
        out.append("UPAR       kuchh nahi — is history me price yahan se upar gayi hi nahi")

    downs = downs_all[:2]
    if downs:
        out.append("NEECHE     " + "   phir   ".join(
            f"{float(z.low):,.0f}-{float(z.high):,.0f} "
            f"(-{float(price - z.high):,.0f} pts, {len(set(z.blocks))} blocks / "
            f"{z.strength} visits)" for z in downs))
    else:
        out.append("NEECHE     kuchh nahi")

    if live:
        # Targets are measured from the level that would BREAK, not from where price is
        # standing. The first version took shelves above `price`, so a break of the live
        # block's high at 60,472 was handed a "target" of 60,425 — 47 points BELOW the
        # break. An if-then whose target sits behind the trigger is not a plan.
        up_t = next(iter(m.above(live.high)), None)
        dn_t = next(iter(m.below(live.low)), None)
        out.append(
            f"AGAR UPAR  {float(live.high):,.0f} ke upar band -> "
            + (f"target {float(up_t.low):,.0f}  (+{float(up_t.low - live.high):,.0f} pts, "
               f"{len(set(up_t.blocks))} blocks)" if up_t
               else "khuli jagah — is history me yahan se upar koi shelf nahi"))
        out.append(
            f"AGAR NEECHE {float(live.low):,.0f} ke neeche band -> "
            + (f"target {float(dn_t.high):,.0f}  (-{float(live.low - dn_t.high):,.0f} pts, "
               f"{len(set(dn_t.blocks))} blocks)" if dn_t
               else "khuli jagah — is history me yahan se neeche koi shelf nahi"))
    return out
