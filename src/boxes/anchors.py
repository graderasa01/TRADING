"""
Structural anchors — the third evidence stream. **Measurement mode only.**

`structure.py` finds where price *stayed*. `hierarchy.py` finds what those shelves add up
to. Neither of them can answer the question a chart review made obvious:

> price niche gayi, wahan koi cluster nahi bana, phir us low se upar aayi aur upar
> clusters/range banaye. To wo low kya hai?

It is not a cluster, and it must not be turned into one — `adaptive.py`'s acceptance rule
is correct and is not touched here. A place price visited once is a pause, not a shelf.

But **cluster rejected is not the same as information rejected.** That low is where a
move launched from, and when price comes back to it a trader wants to know:

    "yahan se pehle strong upward displacement start hua tha."

```
                         C4
                    +---------+
                    | CLUSTER |
                    +---------+
                         ^
                         |
                  IMPULSE UP
                         |
    ORIGIN LOW  o--------+
      60,200
```

So the map carries three kinds of evidence, not two:

```
STRUCTURE   cluster, range          where price stayed
MOVE        impulse, pullback...    how it travelled
ANCHOR      swing high/low, origin  where it launched from and terminated
```

## No second swing brain

Anchors come from `src/indicators/swings.py` — the same confirmed-pivot detector
`levels/` and `structure/` already share, at the same `k`, with the same no-look-ahead
confirmation lag. This module **selects** among those pivots; it does not detect any.
A private swing engine here would be a second opinion about where price turned, and two
opinions that drift apart is exactly the bug `swings.py` exists in a neutral package to
prevent.

## Displacement, but deliberately not efficiency

A move earns an anchor when it travelled further than the shelf it left is thick —
`net_width >= 1`, the same scale-free ruler the impulse rule uses, with the shelf as its
own measure.

The efficiency half of the impulse rule is **not** applied. That is the point. On
2026-02-16 the morning ran +326 points over 70 candles at `er 0.28` and is correctly
*not* an impulse — it was choppy. The low it launched from is still one of the most
important prices on the chart. Whether a move was tidy and whether its origin matters are
different questions, and conflating them is what made that low invisible.

Nothing here is admitted to `build_map()`, and nothing here is a signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.boxes.structure import Link
from src.domain.models import Candle
from src.indicators.swings import find_pivots

#: A move must travel further than the shelf it left is thick. Same ruler as the impulse
#: rule's size half — the box is its own measure, so there is no number to tune.
MIN_DISPLACEMENT_RATIO = 1.0

ANCHOR_KINDS = frozenset({"swing_low", "swing_high"})
ANCHOR_ROLES = frozenset({"impulse_origin", "impulse_destination", "both"})


@dataclass(frozen=True, slots=True)
class Anchor:
    """A price that mattered because of what happened *from* it, not what sat *on* it."""

    id: str
    kind: str                      # swing_low | swing_high
    role: str                      # impulse_origin | impulse_destination | both
    index: int
    price: Decimal
    moves: tuple[str, ...]         # the move links that make it matter
    displacement: Decimal          # the largest of those moves, in points
    er: float                      # that move's efficiency — reported, never gated on
    from_pivot: bool               # False if no confirmed pivot was near enough
    covered_by: str | None = None  # the structure it sits inside, if any

    @property
    def uncovered(self) -> bool:
        """The interesting ones. A structure already speaks for the prices inside it;
        an anchor with nothing around it is a reference that would otherwise vanish."""
        return self.covered_by is None


def _pick(pivots, lo: int, hi: int, want_high: bool):
    """The most extreme confirmed pivot in `[lo, hi]`, or `None`."""
    inside = [p for p in pivots if lo <= p.index <= hi and p.is_high == want_high]
    if not inside:
        return None
    return max(inside, key=lambda p: p.price) if want_high \
        else min(inside, key=lambda p: p.price)


def find_anchors(chain: Sequence[Link], candles: Sequence[Candle], *,
                 k: int = 3, min_ratio: float = MIN_DISPLACEMENT_RATIO) -> list[Anchor]:
    """Origins and destinations of every move that actually went somewhere.

    `k` is passed straight to the shared `find_pivots`; it is not redefined here.
    """
    pivots = find_pivots(list(candles), "1m", k)
    found: dict[int, dict] = {}

    for ln in chain:
        if ln.kind in {"seam", "gap"} or ln.is_structure:
            continue
        m = ln.measurements
        ratio = m.get("net_width") or m.get("net_atr", 0.0)
        if ratio < min_ratio:
            continue
        up = m.get("net", 0.0) > 0

        for want_high, role, lo, hi in (
                (not up, "impulse_origin", max(0, ln.start - k), ln.end),
                (up, "impulse_destination", ln.start, min(len(candles) - 1, ln.end + k))):
            p = _pick(pivots, lo, hi, want_high)
            if p is not None:
                index, price, real = p.index, p.price, True
            else:
                # No confirmed pivot near enough — fall back to the extreme candle so the
                # reference is not lost, and say so rather than pretending it is a pivot.
                seg = range(max(0, lo), min(len(candles), hi + 1))
                if not seg:
                    continue
                index = (max(seg, key=lambda i: candles[i].h) if want_high
                         else min(seg, key=lambda i: candles[i].l))
                price = candles[index].h if want_high else candles[index].l
                real = False

            slot = found.setdefault(index, {
                "kind": "swing_high" if want_high else "swing_low",
                "price": price, "moves": [], "roles": set(),
                "disp": Decimal("0"), "er": 0.0, "from_pivot": real})
            slot["moves"].append(ln.id)
            slot["roles"].add(role)
            d = abs(Decimal(str(m.get("net", 0.0))))
            if d > slot["disp"]:
                slot["disp"], slot["er"] = d, m.get("er", 0.0)

    out: list[Anchor] = []
    for n, (index, s) in enumerate(sorted(found.items()), start=1):
        role = "both" if len(s["roles"]) > 1 else next(iter(s["roles"]))
        out.append(Anchor(f"A{n:02d}", s["kind"], role, index, s["price"],
                          tuple(s["moves"]), s["disp"], s["er"], s["from_pivot"]))
    return out


def mark_coverage(anchors: Sequence[Anchor], chain: Sequence[Link]) -> list[Anchor]:
    """Tag each anchor with the structure containing it, if any.

    An anchor inside a cluster is already described by that cluster. An **uncovered**
    anchor is the case this module exists for: a price that matters with no box on it.
    """
    from dataclasses import replace
    out = []
    for a in anchors:
        holder = next((ln.id for ln in chain
                       if ln.is_structure and ln.low <= a.price <= ln.high), None)
        out.append(replace(a, covered_by=holder))
    return out


def build_anchors(chain: Sequence[Link], candles: Sequence[Candle], **kw) -> list[Anchor]:
    return mark_coverage(find_anchors(chain, candles, **kw), chain)


def nearest(anchors: Sequence[Anchor], price: Decimal, above: bool) -> Anchor | None:
    """The closest anchor on one side — what ABOVE/CURRENT/BELOW would carry.

    Not wired into any output yet. It exists so the shape of the eventual answer is
    visible while the evidence is still being judged.
    """
    side = [a for a in anchors if (a.price > price if above else a.price < price)]
    return min(side, key=lambda a: abs(a.price - price)) if side else None


__all__ = ["Anchor", "ANCHOR_KINDS", "ANCHOR_ROLES", "MIN_DISPLACEMENT_RATIO",
           "find_anchors", "mark_coverage", "build_anchors", "nearest"]
