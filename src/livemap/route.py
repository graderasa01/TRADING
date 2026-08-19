"""
The forward route — what actually stands between price and the next decision.

`interpreter.py` already answers *"what is the next structure?"* and *"how far is it?"*.
Those two answers are not enough, and the gap between them is the bug this module fixes.

```
SPACE  = current edge -> nearest edge          <- one number, and it hides two events
ROUTE  = free space -> NEAR EDGE -> depth -> FAR EDGE
```

## Why one number is not enough

```
current upper edge   60,430
next zone            60,435 - 60,500

FREE_TO_NEAR_EDGE     5 pts
ZONE_DEPTH           65 pts
FREE_TO_FAR_EDGE     70 pts
```

Read as `SPACE = 5`, that is *"no room, forget it"*. It is nothing of the sort. It says
**the first structural contact is five points away** — and behind that contact sits a
sixty-five point corridor which becomes route space only *after* price is accepted inside
the zone. Those are two different questions arriving at two different times, and a single
`SPACE` field cannot ask either one properly.

## What each edge means to a trader

```
NEAR_EDGE   the first structural decision. Where the interaction happens.
FAR_EDGE    a conditional second boundary. Relevant only once price has accepted
            inside the zone and traversed it. NEVER a promised target.
```

The sequence, and nothing in it is skippable:

```
CURRENT
   |  FREE_TO_NEAR_EDGE
NEAR_EDGE
   |  acceptance inside the next zone?
   +-- no  -> rejection / reassessment
   +-- yes -> ZONE_DEPTH -> FAR_EDGE -> break of the far edge is THAT ZONE'S OWN breakout
```

The last line is the boundary rule restated: a structure breaks at **its own** edge. The
next zone's far edge is never the current structure's breakout level, and
`test_the_far_edge_is_never_the_current_break_level` pins it.

## The watch ladder is a relation, not a threshold

No points constant and no ATR multiple is invented here. The ladder is built out of two
rulers the repo already uses everywhere:

```
tol       tol_at(candles, i, tol_atr)   the same skirt `AT_UPPER_EDGE` uses
reach     the zone's OWN width          the same ruler `Frontier` uses for LEAVING
```

*"The box as its own ruler"* is already how `frontier.py` decides when price has drifted
clear of what it left. Applied forward it says: a sixty-five point zone is being
approached from sixty-five points away; a ten point zone is not. That is scale-free,
volatility-aware, and it introduces no number that can be tuned.

```
FAR_FROM_NEXT_ZONE           further than one zone-width from the near edge   -> watch
APPROACHING_NEXT_ZONE        within one zone-width                            -> prepare
AT_NEXT_ZONE                 within tol of the near edge                      -> observe
INSIDE_NEXT_ZONE             past the near edge, traversing the depth         -> observe
AT_FAR_EDGE                  within tol of the far edge                       -> observe
BREAK_ATTEMPT_IN_NEXT_ZONE   beyond the far edge — the zone's own breakout attempt
```

A zone thinner than `tol` has no `APPROACHING` rung, because a band narrower than the
noise skirt cannot be approached in any measurable sense. That is honest rather than
tidy, and inventing a floor to make it tidy is exactly the tuning this file refuses.

## The corridor exists because labels lie about order

`NEXT` and `NEXT_MAJOR` are **type** labels: `NEXT` is the nearest cluster, `NEXT_MAJOR`
the nearest range. Neither says which boundary price meets first. A parent range whose
near edge sits below its own child's near edge is meeting price first, and a consumer
reading only the labels walks straight past it:

```
current edge            44,033
44,243   R01 near      <- price meets the PARENT boundary first
44,304   C08 near
44,334   C08 far
44,757   R01 far
```

So the corridor is emitted **ordered by actual price**, every boundary of every known
structure ahead, each tagged with whose edge it is and whether it is that structure's
near or far side. `ZoneRoute.label` records whether the first zone in price order was in
fact the one the type labels called `NEXT`; when it says `FIRST_IN_PRICE`, the labels and
the order disagree and the corridor is the thing to read.

Nothing here gates, scores or ranks. It measures.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from src.boxes.hierarchy import Node
from src.domain.models import ZERO

NEAR, FAR = "near", "far"

#: Closed, and enforced in `__post_init__` the same way `STATUS_VOCABULARY` is. Every one
#: of these names where price is relative to the next zone. None of them is an
#: instruction — `FAR_FROM_NEXT_ZONE` is not "do not trade", it is "price is not there".
WATCH_STATES = frozenset({
    "NO_NEXT_ZONE",
    "FAR_FROM_NEXT_ZONE",
    "APPROACHING_NEXT_ZONE",
    "AT_NEXT_ZONE",
    "INSIDE_NEXT_ZONE",
    "AT_FAR_EDGE",
    "BREAK_ATTEMPT_IN_NEXT_ZONE",
})

#: Which reference bucket the first-in-price zone turned out to be. `FIRST_IN_PRICE` is
#: the interesting one: it means the type labels and the price order disagree.
ROUTE_LABELS = frozenset({"NEXT", "NEXT_MAJOR", "FIRST_IN_PRICE"})


@dataclass(frozen=True, slots=True)
class CorridorStop:
    """One structural boundary ahead, in price order. Not a target."""

    price: Decimal
    ref_id: str
    kind: str                   # cluster | range
    edge: str                   # near | far
    distance: Decimal           # magnitude, from the origin edge
    distance_atr: float

    def __post_init__(self) -> None:
        if self.edge not in (NEAR, FAR):
            raise ValueError(f"edge must be {NEAR!r} or {FAR!r}, got {self.edge!r}")

    def line(self) -> str:
        return f"{float(self.price):,.0f} {self.ref_id} {self.edge}"


@dataclass(frozen=True, slots=True)
class ZoneRoute:
    """The three measurements a single directional zone owes a trader.

    `free_to_near`, `zone_depth` and `free_to_far` are **magnitudes**; `direction` says
    which way they point. That matches the existing `space_above` / `space_below` pair,
    which are also magnitudes, and it keeps `FREE_TO_FAR = FREE_TO_NEAR + ZONE_DEPTH` true
    on both sides instead of only on one.
    """

    id: str
    kind: str
    direction: str              # up | down — the direction of travel toward the zone
    low: Decimal
    high: Decimal

    #: Where the measuring starts: the CURRENT structure's own break edge. Not price.
    #: Measuring room from the close while standing inside a structure puts the reference
    #: behind the trigger — the bug that killed the block map.
    origin_edge: Decimal
    near_edge: Decimal
    far_edge: Decimal

    free_to_near: Decimal
    zone_depth: Decimal
    free_to_far: Decimal
    free_to_near_atr: float
    zone_depth_atr: float
    free_to_far_atr: float

    #: From PRICE, not from the origin edge. Positive means still to travel; negative
    #: means price is already past the near edge. This is what the watch ladder reads.
    distance_to_near: Decimal
    distance_to_near_atr: float
    watch: str
    label: str = "NEXT"

    def __post_init__(self) -> None:
        if self.watch not in WATCH_STATES:
            raise ValueError(
                f"unknown watch state {self.watch!r}. Add it to WATCH_STATES first — and "
                f"if it names a trade rather than a distance, it does not belong here.")
        if self.label not in ROUTE_LABELS:
            raise ValueError(f"unknown route label {self.label!r}")

    @property
    def band(self) -> str:
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"

    @property
    def labels_agree(self) -> bool:
        """False when the nearest boundary in price order is not the labelled `NEXT`."""
        return self.label != "FIRST_IN_PRICE"

    def lines(self, heading: str = "ROUTE") -> list[str]:
        pad = " " * 14
        return [
            f"{heading:<14}NEXT ZONE     {self.id}  {self.band}  ({self.kind})"
            + ("" if self.labels_agree else "   [first in price, not NEXT]"),
            f"{pad}FIRST EDGE    {float(self.near_edge):,.0f}",
            f"{pad}FAR EDGE      {float(self.far_edge):,.0f}   conditional — only "
            f"after acceptance inside",
            f"{pad}FREE TO FIRST {float(self.free_to_near):,.0f} pts "
            f"({self.free_to_near_atr:.1f} ATR)",
            f"{pad}ZONE DEPTH    {float(self.zone_depth):,.0f} pts "
            f"({self.zone_depth_atr:.1f} ATR)",
            f"{pad}FREE TO FAR   {float(self.free_to_far):,.0f} pts "
            f"({self.free_to_far_atr:.1f} ATR)",
            f"{pad}WATCH         {self.watch}",
        ]


# ─────────────────────────────────────────────────────────────────────────────
def watch_state(near_edge: Decimal, far_edge: Decimal, price: Decimal, *,
                up: bool, tol: Decimal) -> str:
    """Where price stands on the ladder. Built from `tol` and the zone's own width only.

    The rungs are checked from most-progressed backwards, so a zone thinner than twice
    `tol` resolves to `AT_NEXT_ZONE` rather than `AT_FAR_EDGE`: first contact is the
    event, and a band narrower than the skirt has no meaningful interior.
    """
    depth = abs(far_edge - near_edge)
    reach = max(depth, tol)

    # Positive = not reached yet, in the direction of travel.
    d_near = (near_edge - price) if up else (price - near_edge)
    d_far = (far_edge - price) if up else (price - far_edge)

    if d_far < -tol:
        return "BREAK_ATTEMPT_IN_NEXT_ZONE"
    if d_near > reach:
        return "FAR_FROM_NEXT_ZONE"
    if d_near > tol:
        return "APPROACHING_NEXT_ZONE"
    if d_near >= -tol:
        return "AT_NEXT_ZONE"
    if abs(d_far) <= tol:
        return "AT_FAR_EDGE"
    return "INSIDE_NEXT_ZONE"


def measure(node: Node, origin_edge: Decimal, price: Decimal, *, up: bool,
            atr: Decimal, tol: Decimal, label: str = "NEXT") -> ZoneRoute:
    """One zone, fully measured. Pure arithmetic — no selection, no ranking."""
    near = node.low if up else node.high
    far = node.high if up else node.low

    free_near = (near - origin_edge) if up else (origin_edge - near)
    depth = abs(far - near)
    free_far = free_near + depth

    def per_atr(v: Decimal) -> float:
        return float(v / atr) if atr > ZERO else 0.0

    d_near = (near - price) if up else (price - near)
    return ZoneRoute(
        id=node.id, kind=node.kind, direction="up" if up else "down",
        low=node.low, high=node.high,
        origin_edge=origin_edge, near_edge=near, far_edge=far,
        free_to_near=free_near, zone_depth=depth, free_to_far=free_far,
        free_to_near_atr=per_atr(free_near), zone_depth_atr=per_atr(depth),
        free_to_far_atr=per_atr(free_far),
        distance_to_near=d_near, distance_to_near_atr=per_atr(d_near),
        watch=watch_state(near, far, price, up=up, tol=tol), label=label)


def first_in_price(nodes: Sequence[Node], origin_edge: Decimal, *,
                   up: bool) -> Node | None:
    """The zone whose NEAR edge price meets first. Order, not type.

    Only zones lying wholly beyond the origin edge qualify: a structure price is already
    standing inside has no near edge ahead to travel to, and calling its far side a "next
    zone" would report a depth price has already partly traversed. Its far boundary is
    still real, and it appears in the corridor.
    """
    ahead = [n for n in nodes
             if ((n.low > origin_edge) if up else (n.high < origin_edge))]
    if not ahead:
        return None
    return min(ahead, key=lambda n: (n.low - origin_edge) if up
               else (origin_edge - n.high))


def build_corridor(nodes: Iterable[Node], origin_edge: Decimal, *, up: bool,
                   atr: Decimal, limit: int = 8) -> tuple[CorridorStop, ...]:
    """Every structural boundary ahead of the origin edge, **ordered by actual price**.

    A structure contributes whichever of its two edges lie ahead — so a parent range that
    already contains price still contributes its far boundary, which is a real obstacle
    that `NEXT` / `NEXT_MAJOR` would never mention.
    """
    stops: list[CorridorStop] = []
    for n in nodes:
        pairs = ((NEAR, n.low), (FAR, n.high)) if up else ((NEAR, n.high), (FAR, n.low))
        for edge, price in pairs:
            if (price <= origin_edge) if up else (price >= origin_edge):
                continue
            gap = (price - origin_edge) if up else (origin_edge - price)
            stops.append(CorridorStop(
                price=price, ref_id=n.id, kind=n.kind, edge=edge, distance=gap,
                distance_atr=float(gap / atr) if atr > ZERO else 0.0))
    stops.sort(key=lambda s: (s.distance, s.ref_id, s.edge))
    seen: set[tuple[str, str]] = set()
    out: list[CorridorStop] = []
    for s in stops:
        key = (s.ref_id, s.edge)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return tuple(out[:limit])


def corridor_line(stops: Sequence[CorridorStop]) -> str:
    return " · ".join(s.line() for s in stops) if stops else "—"


def nested_stops(stops: Sequence[CorridorStop]) -> list[tuple[str, str]]:
    """Pairs `(outer, inner)` where an outer structure's near edge is met first but its
    far edge comes last — the parent-before-child shape. Diagnostic only."""
    order = {(s.ref_id, s.edge): k for k, s in enumerate(stops)}
    ids = sorted({s.ref_id for s in stops})
    out: list[tuple[str, str]] = []
    for a in ids:
        for b in ids:
            if a == b:
                continue
            keys = [(a, NEAR), (b, NEAR), (b, FAR), (a, FAR)]
            if all(k in order for k in keys) and \
                    [order[k] for k in keys] == sorted(order[k] for k in keys):
                out.append((a, b))
    return out


__all__ = ["WATCH_STATES", "ROUTE_LABELS", "NEAR", "FAR", "CorridorStop", "ZoneRoute",
           "watch_state", "measure", "first_in_price", "build_corridor",
           "corridor_line", "nested_stops"]
