"""
The frozen map — `CLUSTER-RANGE-MAP.md` §7-§9.

`adaptive.py` proposes on every candle. This module decides what gets **admitted**, and
once something is admitted **it never moves again**.

## The contradiction that is not one

> *"rolling window dynamic rakhenge"*  and  *"map first banayenge phir freeze"*

The scan is dynamic. The map is not.

* Every candle, the scanner proposes.
* A proposal landing on a box already live is the **same box seen again** — discarded.
* A genuinely new proposal is admitted and its edges frozen at birth. They do not move
  when price pushes on them, when the chosen window changes, or when a later scan would
  draw them elsewhere.
## Leaving a box is an event. It is not the box's death.

The first version deleted a box the moment price closed outside it twice. That is what the
plan said, and building it showed the plan was wrong: **if every box dies as soon as price
leaves, there is never anything above or below.** The map collapses to one box — the one
price is standing in — and §8 of `CLUSTER-RANGE-MAP.md`, the entire above/current/below
stack, has nothing to put in it.

The mistake was treating "price left" and "the structure is gone" as one thing. A cluster
at 60,000 that price rose out of is still a real shelf at 60,000; it has become a target
from above instead of a container. So boxes are **never removed**. Each carries a state:

```
holding   price is inside it
left      price has closed outside it twice — the break happened, the box remains
crossed   price later re-entered and came out the far side — the box has been spent
```

`left` is the event a trade is built on; `crossed` is what stops a spent level being
offered as a target forever. Two consecutive closes are required for both, because one
move at candles 34, 35 and 36 was once recorded as three separate breaks.

Because the edges are frozen, three things exist that could not exist before: **a break
that can be waited for**, **a distance that stays the same while price travels toward it**,
and **a story that is still the same story twenty minutes later**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterator, Sequence

from src.boxes.adaptive import Proposal, choose, overlap
from src.domain.models import ZERO, Candle

MIN_STEP = Decimal("0.05")


@dataclass(frozen=True, slots=True)
class Rotation:
    """One completed trip between a box's thirds."""
    direction: str                  # "high->low" | "low->high"
    from_price: Decimal
    to_price: Decimal
    from_i: int
    to_i: int

    @property
    def points(self) -> Decimal:
        return abs(self.to_price - self.from_price)

    @property
    def candles(self) -> int:
        return self.to_i - self.from_i


@dataclass
class Box:
    """An admitted proposal. `low` and `high` are frozen for life."""

    kind: str                       # "cluster" | "range"
    low: Decimal
    high: Decimal
    born: int                       # candle index it was admitted at
    window: int                     # the window length that found it
    score: float
    migration: float
    parts: dict[str, float] = field(default_factory=dict)
    visits: int = 0
    confirmations: int = 0          # times price left and the same structure re-formed
    upper_touches: int = 0
    lower_touches: int = 0
    upper_band: tuple[Decimal, Decimal] | None = None
    lower_band: tuple[Decimal, Decimal] | None = None

    left_at: int | None = None      # candle price finished closing outside on
    left_side: str | None = None    # "up" | "down"
    crossed_at: int | None = None   # came back in and out the far side
    rotations: list[Rotation] = field(default_factory=list)
    last_touch: int = -1

    # break bookkeeping, not part of the box's identity
    _side: str | None = None
    _closes: int = 0
    _rot_state: str | None = None
    _rot_from: tuple[int, Decimal] | None = None

    @property
    def state(self) -> str:
        if self.crossed_at is not None:
            return "crossed"
        return "left" if self.left_at is not None else "holding"

    @property
    def spent(self) -> bool:
        """A crossed box has been traded through and is no longer offered as a target."""
        return self.crossed_at is not None

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high

    def position(self, price: Decimal) -> Decimal | None:
        """0 at the low edge, 1 at the high. Outside [0,1] once price has left."""
        if self.width <= ZERO:
            return None
        return (price - self.low) / self.width

    def label(self) -> str:
        return f"{self.kind} {float(self.low):,.0f}-{float(self.high):,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
class Mapper:
    """Feed it closed candles in order; ask it what the map says."""

    def __init__(self, atr_bars: int = 20, *, tol_atr: Decimal = Decimal("0.25"),
                 min_score: float = 0.35, break_closes: int = 2,
                 same_box_overlap: float = 0.5) -> None:
        self.candles: list[Candle] = []
        self.boxes: list[Box] = []
        self.atr_bars = atr_bars
        self.tol_atr = tol_atr
        self.min_score = min_score
        self.break_closes = break_closes
        self.same_box_overlap = same_box_overlap

    # ── state ───────────────────────────────────────────────────────────────
    @property
    def atr(self) -> Decimal:
        recent = [k for k in self.candles[-self.atr_bars:] if not k.synthetic]
        if not recent:
            return ZERO
        return sum((k.h - k.l for k in recent), ZERO) / len(recent)

    @property
    def tol(self) -> Decimal:
        return max(self.atr * self.tol_atr, MIN_STEP)

    @property
    def close(self) -> Decimal:
        return self.candles[-1].c if self.candles else ZERO

    def live(self, kind: str | None = None) -> list[Box]:
        """Boxes still worth pointing at: everything that has not been traded through."""
        return [b for b in self.boxes
                if not b.spent and (kind is None or b.kind == kind)]

    def holding(self) -> list[Box]:
        return [b for b in self.boxes if b.state == "holding"]

    def broken(self) -> list[Box]:
        return [b for b in self.boxes if b.left_at is not None]

    # ── the loop ────────────────────────────────────────────────────────────
    def on_candle(self, candle: Candle) -> None:
        self.candles.append(candle)
        i = len(self.candles) - 1
        if candle.synthetic:
            return

        tol = self.tol
        for b in self.boxes:
            self._update(b, candle, i, tol)

        atr = self.atr
        if atr <= ZERO or len(self.candles) < 12:
            return
        cluster, rng = choose(self.candles, atr, tol_atr=self.tol_atr,
                              min_score=self.min_score)
        for p in (rng, cluster):        # range first: it is the larger structure
            if p is not None:
                self._admit(p, i, tol)

    def _admit(self, p: Proposal, i: int, tol: Decimal) -> None:
        """A proposal landing on a box already on the map is that box seen again.

        The dedupe is what makes *"box dobara tab banega jab ye toot jaye"* true without
        any explicit rule for it: while the structure holds, every candle re-proposes the
        same edges and every one of them is absorbed. A new box appears only once the
        market has actually built something somewhere else.

        ## Why overlap and not near-equal edges

        The first version absorbed only when **both** edges were within `tol`. Measured on
        real sessions that produced **41 to 48 boxes a day**, twenty of them stacked inside
        a single hundred-point shelf:

            60,388-60,430    60,404-60,425    60,396-60,426    60,385-60,437 ...

        Those are one shelf that the scan re-read at slightly different window lengths. To
        a trader they are the same object; to a `tol` test on each edge they are four. So
        the test is on **overlap as a fraction of the narrower band** — half or more shared
        means the same structure, at any scale, with no dependence on how the edges happen
        to be quantised.

        The absorbed proposal never alters the box. Freezing is absolute: the box records
        that it was seen again (`confirmations`), and nothing else changes.
        """
        for b in self.live(p.kind):
            if overlap((b.low, b.high), (p.low, p.high)) >= self.same_box_overlap:
                b.last_touch = i
                # A re-proposal AFTER price had left is a genuine revisit — the market
                # came back and rebuilt the same structure. That is the `revisit` evidence
                # the window scan structurally cannot see.
                if b.left_at is not None and b.contains(self.close):
                    b.confirmations += 1
                    b.left_at, b.left_side = None, None
                    b._side, b._closes = None, 0
                return
        self.boxes.append(Box(
            kind=p.kind, low=p.low, high=p.high, born=i, window=p.window,
            score=p.score, migration=p.migration, parts=dict(p.parts),
            visits=p.visits, upper_touches=p.upper_touches,
            lower_touches=p.lower_touches,
            upper_band=p.upper_band, lower_band=p.lower_band, last_touch=i))

    def _update(self, b: Box, candle: Candle, i: int, tol: Decimal) -> None:
        c = candle.c

        # ── left / crossed: two consecutive closes outside the same edge ─────
        if b.contains(c):
            b.last_touch = i
            b._side, b._closes = None, 0
        else:
            side = "up" if c > b.high + tol else "down" if c < b.low - tol else None
            if side is None:                       # inside the tolerance skirt
                b._side, b._closes = None, 0
            else:
                b._closes = b._closes + 1 if side == b._side else 1
                b._side = side
                if b._closes >= self.break_closes:
                    if b.left_at is None:
                        b.left_at, b.left_side = i, side
                    elif side != b.left_side and b.crossed_at is None:
                        b.crossed_at = i           # in one side, out the other

        # ── rotation inside the box ─────────────────────────────────────────
        rngw = b.width
        if rngw <= ZERO:
            return
        zone = ("low" if c <= b.low + rngw / 3 else
                "high" if c >= b.high - rngw / 3 else None)
        if zone is None:
            return
        if b._rot_state is not None and zone != b._rot_state and b._rot_from is not None:
            b.rotations.append(Rotation(
                f"{b._rot_state}->{zone}", b._rot_from[1], c, b._rot_from[0], i))
        if zone != b._rot_state:
            b._rot_state, b._rot_from = zone, (i, c)

    # ── what the trader asks ────────────────────────────────────────────────
    def current(self) -> Box | None:
        """The box price is standing in. The tightest one, if several overlap — the
        smallest container is the one whose edges are near enough to trade.

        The `tol` skirt is the same one the break rule uses. Without it a close half a
        point above an edge — the edges are quantised to `ATR/10` buckets, so this happens
        constantly — reported *"kisi box ke andar nahi"* while sitting in the middle of a
        rest, and the break rule disagreed with the map about where price was.
        """
        tol = self.tol
        c = self.close
        inside = [b for b in self.live() if b.low - tol <= c <= b.high + tol]
        return min(inside, key=lambda b: b.width) if inside else None

    def above(self, kind: str | None = None, price: Decimal | None = None) -> list[Box]:
        """Boxes entirely above `price` (default: the close), nearest first.

        `price` exists because the story must measure from the **edge that breaks**, not
        from where price is standing. Asking for boxes above the close while standing
        inside a box returns boxes that overlap it, and the target then sits behind the
        trigger — the exact bug that killed the block map.
        """
        at = self.close if price is None else price
        return sorted((b for b in self.live(kind) if b.low > at), key=lambda b: b.low)

    def below(self, kind: str | None = None, price: Decimal | None = None) -> list[Box]:
        at = self.close if price is None else price
        return sorted((b for b in self.live(kind) if b.high < at), key=lambda b: -b.high)

    def extremes(self) -> tuple[Decimal, Decimal]:
        real = [k for k in self.candles if not k.synthetic]
        if not real:
            return ZERO, ZERO
        return min(k.l for k in real), max(k.h for k in real)

    def just_left(self, lookback: int = 40) -> Box | None:
        """The most recently broken box — *"price yahan se nikli thi"*."""
        i = len(self.candles) - 1
        recent = [b for b in self.boxes
                  if b.left_at is not None and i - b.left_at <= lookback]
        return max(recent, key=lambda b: b.left_at or 0) if recent else None

    def all_rotations(self) -> Iterator[tuple[Box, Rotation]]:
        for b in self.boxes:
            for r in b.rotations:
                yield b, r


def build(candles: Sequence[Candle], **kw) -> Mapper:
    m = Mapper(**kw)
    for c in candles:
        m.on_candle(c)
    return m


# ─────────────────────────────────────────────────────────────────────────────
# the story — §8 and §9
# ─────────────────────────────────────────────────────────────────────────────
def _line(b: Box, price: Decimal, sign: int) -> str:
    edge = b.low if sign > 0 else b.high
    gap = abs(edge - price)
    extra = (f"{b.upper_touches}+{b.lower_touches} touch, {len(b.rotations)} rotation"
             if b.kind == "range" else f"{b.confirmations + 1} baar bani")
    return (f"{float(b.low):,.0f}-{float(b.high):,.0f} "
            f"({'+' if sign > 0 else '-'}{float(gap):,.0f} pts, {extra}, "
            f"score {b.score:.2f}, N={b.window})")


def story(m: Mapper) -> list[str]:
    """The map read aloud. Every number comes from a frozen box, so none of it moves until
    something actually breaks."""
    price = m.close
    out: list[str] = []
    lo, hi = m.extremes()

    here = m.current()
    if here is None:
        out.append(f"ABHI       {float(price):,.0f} — kisi box ke andar nahi, "
                   f"do structures ke beech khaali jagah me")
    else:
        pos = here.position(price)
        out.append(f"ABHI       {float(price):,.0f} — {here.label()} ke andar, "
                   f"{float(pos) * 100:.0f}% upar "
                   f"({len(here.rotations)} rotation, N={here.window}, "
                   f"born candle {here.born})")

    left = m.just_left()
    if left:
        edge = left.high if left.left_side == "up" else left.low
        out.append(f"AAYA       {left.label()} {left.left_side} toota "
                   f"(candle {left.left_at}) — ab {float(abs(price - edge)):,.0f} pts door")

    # Everything above and below is measured from the EDGE that would break, not from the
    # close. Standing inside a box, "above the close" includes the box's own upper half.
    top = here.high if here else price
    bot = here.low if here else price
    for label, boxes, sign in (("UPAR   ", m.above(price=top), 1),
                               ("NEECHE ", m.below(price=bot), -1)):
        if not boxes:
            out.append(f"{label}    kuchh nahi — is taraf koi box nahi")
            continue
        # nearest cluster, then next range — §8
        pick: list[Box] = []
        for kind in ("cluster", "range"):
            nxt = next((b for b in boxes if b.kind == kind), None)
            if nxt is not None:
                pick.append(nxt)
        for b in sorted(pick, key=lambda z: abs(z.mid - price)):
            out.append(f"{label}    {_line(b, price, sign)}")

    out.append(f"DEEWAR     high {float(hi):,.0f} (+{float(hi - price):,.0f})   "
               f"low {float(lo):,.0f} (-{float(price - lo):,.0f})   "
               f"| {len(m.holding())} andar, {len(m.live())} zinda, "
               f"{len(m.broken())} toote, {len(m.boxes)} kul")

    rots = [(b, r) for b, r in m.all_rotations()][-3:]
    if rots:
        out.append("ROTATION   " + "   ".join(
            f"{r.direction} {float(r.points):,.0f}pts/{r.candles}c" for _, r in rots))

    if here is not None:
        ups, dns = m.above(price=here.high), m.below(price=here.low)
        up_t = ups[0] if ups else None
        dn_t = dns[0] if dns else None
        out.append(f"AGAR UPAR  {float(here.high):,.0f} ke upar 2 band -> "
                   + (f"target {float(up_t.low):,.0f} "
                      f"(+{float(up_t.low - here.high):,.0f} pts, {up_t.kind})"
                      if up_t else f"khuli jagah, phir {float(hi):,.0f}"))
        out.append(f"AGAR NEECHE {float(here.low):,.0f} ke neeche 2 band -> "
                   + (f"target {float(dn_t.high):,.0f} "
                      f"(-{float(here.low - dn_t.high):,.0f} pts, {dn_t.kind})"
                      if dn_t else f"khuli jagah, phir {float(lo):,.0f}"))
    return out


__all__ = ["Box", "Rotation", "Mapper", "build", "story"]
