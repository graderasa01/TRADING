"""
The Live Map Interpreter — `LIVE-FRONTIER.md` §7.

One structured state per closed candle:

```
BANKNIFTY 1m   PRICE = 22558

CURRENT       C42  22556-22564         status PROVISIONAL
BREAK LEVELS  up 22564   down 22556    <- C42's OWN edges
ABOVE         NEXT       R4   22610-22700   +46 pts
              NEXT_MAJOR A9   22840          +276 pts
BELOW         NEXT       C41  22460-22480    -76 pts
INTERACTION   APPROACHING_UPPER
REFERENCES    C42.high 22564 · C42.low 22556 · C41.high 22480 · canvas low 22150
STATUS        WAIT
```

## Three rules this module exists to hold

**1. The break level is the current structure's own edge.** A `22460-22480` cluster
breaks above `22480`. `22560` is the next structural *reference* — a place to look at,
never a boundary and never a promised target. An earlier draft of the plan confused the
two and it is the first thing the fixtures pin.

**2. A live structure is never dressed as a historical one.** The one frontier false
positive found across five sessions was a shelf at the canvas right edge (16 Feb,
c966-997) that the batch scan never saw — it was still forming. So a structure the
frontier minted and has not yet left is reported `PROVISIONAL`; only a structure adopted
from the frozen map is `HISTORICAL`. Standing in something is not the same as knowing
what it was.

**3. `STATUS` is observational.** `WAIT`, `APPROACHING_UPPER`, `BREAK_ATTEMPT_UP`,
`ACCEPTED_ABOVE`, `BREAKOUT_FAILED`. Never `LONG`, `SHORT`, `ENTRY`, a size or a stop —
`STATUS_VOCABULARY` is closed and `__post_init__` enforces it, the same way `GATES` is
closed in `domain/models.py`.

## References, not invalidation

An earlier draft emitted `INVALIDATION: current cluster low`. That is prescriptive and
often wrong — depending on the setup the real invalidation may be a range boundary, a
retest low, an anchor, or the last defended level. This module emits **what each price
is** and lets a layer that knows what the position is decide which one invalidates it.
That layer does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.anchors import Anchor
from src.boxes.frontier import Frontier, Reading
from src.boxes.hierarchy import Node
from src.boxes.snapshot import MapSnapshot
from src.boxes.structure import STRUCTURE_KINDS, atr_at, tol_at
from src.domain.models import ZERO
from src.livemap.route import CorridorStop, ZoneRoute, build_corridor, corridor_line
from src.livemap.route import measure as measure_route

#: Closed vocabulary. Every one of these describes where price is or what it just did.
#: Nothing here is an instruction.
STATUS_VOCABULARY = frozenset({
    "WAIT",                 # inside a structure, away from its edges
    "APPROACHING_UPPER",
    "APPROACHING_LOWER",
    "BREAK_ATTEMPT_UP",
    "BREAK_ATTEMPT_DOWN",
    "ACCEPTED_ABOVE",
    "ACCEPTED_BELOW",
    "BREAKOUT_FAILED",      # left, then closed back inside
    "REVISIT",              # returned to a structure the map already had
    "IN_TRANSIT",           # travelling, belonging to nothing
    "FORMING",              # a provisional band, not yet confirmed
    "LEAVING",
})

#: Words that must never appear in an interpreter output. Guarded by a test.
FORBIDDEN = ("LONG", "SHORT", "ENTRY", "EXIT", "BUY", "SELL", "STOP", "TARGET", "SIZE")

PROVISIONAL = "PROVISIONAL"
HISTORICAL = "HISTORICAL"


@dataclass(frozen=True, slots=True)
class Reference:
    """A structural price, and what it is. Not a target."""

    id: str
    kind: str                    # cluster | range | anchor | extreme
    low: Decimal
    high: Decimal
    distance: Decimal            # from the edge that would break, signed
    distance_atr: float
    age: int                     # candles since it ended; 0 for a live one
    note: str = ""

    @property
    def band(self) -> str:
        if self.low == self.high:
            return f"{float(self.low):,.0f}"
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"


@dataclass(frozen=True, slots=True)
class SideReferences:
    """Direction-specific and ordered. Never one flat list — a flat list sorted by
    distance mixes the sides, and the first consumer that forgets to filter gets a
    downside object offered as an upside reference."""

    next: Reference | None = None
    next_major: Reference | None = None
    extended: Reference | None = None
    #: The full route into the zone price meets first **in price order**, which is not
    #: always `next` — `next` is the nearest *cluster*, a type label. Additive: the three
    #: fields above are untouched, and `space_above` / `space_below` still come off
    #: `next`, exactly as before.
    route: ZoneRoute | None = None
    #: Every structural boundary ahead, ordered by actual price. This is what survives
    #: when a parent boundary arrives before its own child's.
    corridor: tuple[CorridorStop, ...] = ()

    def all(self) -> list[Reference]:
        return [r for r in (self.next, self.next_major, self.extended) if r]


@dataclass(frozen=True, slots=True)
class Current:
    """Where price is standing — **and what it is standing inside of.**

    `CURRENT C03` alone throws away the containment the historical layer worked to build.
    A cluster in the upper third of a big range and the same cluster sitting alone are
    different places, and the parent is what tells them apart.
    """

    id: str
    kind: str
    low: Decimal
    high: Decimal
    status: str                  # PROVISIONAL | HISTORICAL
    position: Decimal | None     # 0 at the low edge, 1 at the high
    location: str                # "upper third" …
    parent_id: str | None = None
    parent_low: Decimal | None = None
    parent_high: Decimal | None = None
    position_in_parent: Decimal | None = None

    @property
    def band(self) -> str:
        return f"{float(self.low):,.0f}-{float(self.high):,.0f}"

    @property
    def parent_band(self) -> str:
        if self.parent_low is None:
            return ""
        return f"{float(self.parent_low):,.0f}-{float(self.parent_high):,.0f}"


@dataclass(frozen=True, slots=True)
class Arrival:
    """How price got here. A location without a route is half the picture."""

    from_id: str | None = None
    direction: str = ""              # up | down
    bars_in_transit: int = 0

    def describe(self) -> str:
        if not self.from_id:
            return "—"
        way = {"up": "upar se", "down": "neeche se"}.get(self.direction, "")
        return (f"{self.from_id} chhod kar {way} aayi, "
                f"{self.bars_in_transit} candles transit").strip()


#: Descriptive, never a signal. Each one names what the market is doing, not what to do.
MARKET_STATES = frozenset({
    "RANGE_INTERIOR",      # inside a structure, away from its edges
    "RANGE_EDGE",          # at an edge, no break yet
    "BREAKOUT",            # accepted beyond an edge
    "BREAKOUT_FAILURE",    # went beyond, closed back inside
    "REVISIT",             # returned to a structure the map already had
    "TRENDING_MOVE",       # in transit, travelling one way
    "PULLBACK",            # in transit, against the direction it arrived by
    "TRANSITION",          # in transit, going nowhere in particular
    "FORMING",             # a provisional band, not yet confirmed
})


@dataclass(frozen=True, slots=True)
class MapState:
    """What the map sees, on one closed candle."""

    index: int
    at: datetime
    price: Decimal
    current: Current | None
    break_up: Decimal | None
    break_down: Decimal | None
    above: SideReferences
    below: SideReferences
    interaction: str
    references: tuple[Reference, ...] = ()
    status: str = "WAIT"
    arrival: Arrival = Arrival()
    market_state: str = "TRANSITION"
    #: Room before the next structure, measured from the edge that would break. **Not a
    #: target.** A break with 5 points of room and a break with 101 points of room are
    #: completely different events, and a map that reports only *which* zone is next,
    #: never *how far*, cannot tell them apart.
    space_above: Decimal | None = None
    space_below: Decimal | None = None
    space_above_atr: float = 0.0
    space_below_atr: float = 0.0
    #: The structure price has just left, and the edge it went through. On the acceptance
    #: candle `current` is already `None` — the node has been finalised — so without these
    #: the one candle that matters most cannot say **which** structure broke or **where**.
    left_id: str | None = None
    left_edge: Decimal | None = None
    left_low: Decimal | None = None
    left_high: Decimal | None = None
    atr: Decimal = ZERO

    def __post_init__(self) -> None:
        if self.status not in STATUS_VOCABULARY:
            raise ValueError(
                f"unknown status {self.status!r}. Add it to STATUS_VOCABULARY first — "
                f"and if it names a trade rather than a location, it does not belong "
                f"in this layer at all.")
        if self.market_state not in MARKET_STATES:
            raise ValueError(f"unknown market state {self.market_state!r}")

    # ── the route: additive readings of the same geometry ────────────────────
    #
    # `space_above` answers *"how far to the first thing?"* and stops there. These answer
    # the two questions that follow it: how deep is that thing, and where is its far side.
    # Nothing above changed to make room for them.
    @property
    def route_above(self) -> ZoneRoute | None:
        return self.above.route

    @property
    def route_below(self) -> ZoneRoute | None:
        return self.below.route

    @property
    def corridor_above(self) -> tuple[CorridorStop, ...]:
        return self.above.corridor

    @property
    def corridor_below(self) -> tuple[CorridorStop, ...]:
        return self.below.corridor

    def lines(self) -> list[str]:
        out = [f"PRICE         {float(self.price):,.1f}"]
        if self.current is None:
            out.append("CURRENT       — kisi structure ke andar nahi")
        else:
            c = self.current
            pos = f"{float(c.position) * 100:.0f}% upar" if c.position is not None else ""
            if c.parent_id:
                out.append(f"CURRENT       {c.parent_id}  {c.parent_band}   (parent)")
                out.append(f"                └── {c.id}  {c.band}   status {c.status}   "
                           f"{c.location} {pos}".rstrip())
            else:
                out.append(f"CURRENT       {c.id}  {c.band}   status {c.status}   "
                           f"{c.location} {pos}".rstrip())
        if self.break_up is not None:
            out.append(f"BREAK LEVELS  up {float(self.break_up):,.0f}   "
                       f"down {float(self.break_down):,.0f}")
        for label, side in (("ABOVE", self.above), ("BELOW", self.below)):
            refs = side.all()
            if not refs:
                out.append(f"{label:<13} kuchh nahi")
                continue
            names = ("NEXT", "NEXT_MAJOR", "EXTENDED")
            for name, r in zip(names, (side.next, side.next_major, side.extended)):
                if r is None:
                    continue
                out.append(f"{label if r is refs[0] else '':<13} {name:<11} "
                           f"{r.id:<5} {r.band:<18} {float(r.distance):+,.0f} pts "
                           f"({r.distance_atr:+.1f} ATR){'  ' + r.note if r.note else ''}")
        sa = (f"{float(self.space_above):,.0f} pts ({self.space_above_atr:.1f} ATR)"
              if self.space_above is not None else "khuli jagah")
        sb = (f"{float(self.space_below):,.0f} pts ({self.space_below_atr:.1f} ATR)"
              if self.space_below is not None else "khuli jagah")
        out.append(f"SPACE         upar {sa}   neeche {sb}")
        for heading, side in (("ROUTE ABOVE", self.above), ("ROUTE BELOW", self.below)):
            if side.route is None:
                out.append(f"{heading:<14}NEXT ZONE     — us taraf kuchh nahi")
            else:
                out.extend(side.route.lines(heading))
            if side.corridor:
                out.append(f"{'':<14}CORRIDOR      {corridor_line(side.corridor)}")
        out.append(f"ARRIVAL       {self.arrival.describe()}")
        out.append(f"INTERACTION   {self.interaction}")
        if self.references:
            out.append("REFERENCES    " + " · ".join(
                f"{r.id} {r.band}{' ' + r.note if r.note else ''}"
                for r in self.references))
        out.append(f"MARKET STATE  {self.market_state}")
        out.append(f"STATUS        {self.status}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
_STATUS_FROM_INTERACTION = {
    "INSIDE": "WAIT",
    "AT_UPPER_EDGE": "APPROACHING_UPPER",
    "AT_LOWER_EDGE": "APPROACHING_LOWER",
    "BREAK_ATTEMPT_UP": "BREAK_ATTEMPT_UP",
    "BREAK_ATTEMPT_DOWN": "BREAK_ATTEMPT_DOWN",
    "ACCEPTED_ABOVE": "ACCEPTED_ABOVE",
    "ACCEPTED_BELOW": "ACCEPTED_BELOW",
    "RE_ENTRY": "BREAKOUT_FAILED",
    "REVISIT": "REVISIT",
    "LEAVING": "LEAVING",
    "MOVING": "IN_TRANSIT",
    "FORMING": "FORMING",
}


def _status(reading: Reading) -> str:
    if reading.interaction.startswith("NEW_"):
        return "FORMING"
    return _STATUS_FROM_INTERACTION.get(reading.interaction, "IN_TRANSIT")


def _market_state(status: str, current: Current | None, arrival: Arrival,
                  reading: Reading) -> str:
    """What the market is doing — descriptive, never an instruction.

    Derived from the state already established rather than measured afresh, so it can
    never disagree with `STATUS`. A future decision layer may ignore it entirely and read
    the raw fields; it exists because *"RANGE_INTERIOR"* and *"BREAKOUT_FAILURE"* are the
    words a trader actually thinks in.
    """
    if status in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"}:
        return "BREAKOUT"
    if status == "BREAKOUT_FAILED":
        return "BREAKOUT_FAILURE"
    if status == "REVISIT":
        return "REVISIT"
    if status == "FORMING":
        return "FORMING"
    if current is not None:
        if status in {"APPROACHING_UPPER", "APPROACHING_LOWER",
                      "BREAK_ATTEMPT_UP", "BREAK_ATTEMPT_DOWN"}:
            return "RANGE_EDGE"
        return "RANGE_INTERIOR"

    # Travelling. One-way or against the leg it arrived by?
    net = reading.measurements.get("net", 0.0)
    if arrival.direction and net:
        going = "up" if net > 0 else "down"
        if going != arrival.direction:
            return "PULLBACK"
    if status == "LEAVING":
        return "TRANSITION"
    return "TRENDING_MOVE" if arrival.direction else "TRANSITION"


def _third(pos: Decimal | None) -> str:
    """Where in the band price is standing — or that it is not standing in it.

    Position runs outside `[0, 1]` the moment price closes beyond an edge, which is a
    normal `BREAK_ATTEMPT` and not yet a break. Reporting that as *"upper third, 122%"*
    read as though price were inside the structure when it was already above it.
    """
    if pos is None:
        return ""
    if pos > 1:
        return "beyond the upper edge"
    if pos < 0:
        return "beyond the lower edge"
    if pos < Decimal("0.34"):
        return "lower third"
    if pos > Decimal("0.66"):
        return "upper third"
    return "middle"


class Interpreter:
    """Frozen map + live frontier -> one readable state per closed candle.

    Anchors are optional because they are still measurement-only. When they are admitted
    this fills the `EXTENDED` bucket with them; until then it falls back to the canvas
    extreme, and says so.
    """

    def __init__(self, snapshot: MapSnapshot, frontier: Frontier, *,
                 anchors: Sequence[Anchor] = ()) -> None:
        self.snapshot = snapshot
        self.frontier = frontier
        self.anchors = list(anchors)

    # ── references ──────────────────────────────────────────────────────────
    def _pool(self, index: int) -> list[Node]:
        """Everything the map knows at this candle: frozen structures + finalised live."""
        return ([n for n in self.snapshot.nodes if n.kind in STRUCTURE_KINDS]
                + [n for n in self.frontier.history() if n.end <= index])

    def pool_at(self, index: int) -> list[Node]:
        """`_pool` in public, because another layer needs the SAME causally-filtered set.

        `livemap/reference.py` builds a deeper corridor than the eight stops
        `SideReferences.corridor` carries — the audit found the enclosing range boundary
        sitting at corridor position 30 of 35 on the K/L candle, so the one reference that
        makes "the parent is still intact" readable was truncated away. Rebuilding the pool
        there would be a second causal filter that could disagree with this one, and
        `n.end <= index` is exactly the rule that keeps a future structure out. So it is
        published rather than copied.

        Additive: nothing that already existed reads this, and no output moved.
        """
        return self._pool(index)

    def _side(self, index: int, edge: Decimal, up: bool, atr: Decimal,
              exclude: str | None, price: Decimal, tol: Decimal) -> SideReferences:
        """Measured from the **edge that would break**, not from the close.

        Measuring from the close while standing inside a structure puts the reference
        behind the trigger — the bug that killed the block map, and the reason
        `mapper.above()` already takes an explicit price.

        `price` and `tol` arrived with the route layer and are used only there: the
        distances are still anchored on the break edge, but *where price is standing
        relative to the next zone* is a different question and needs the close to answer.
        """
        known = [n for n in self._pool(index) if n.id != exclude]
        pool = [n for n in known if (n.low > edge if up else n.high < edge)]
        pool.sort(key=lambda n: (n.low - edge) if up else (edge - n.high))

        def ref(n: Node) -> Reference:
            gap = (n.low - edge) if up else (n.high - edge)
            return Reference(n.id, n.kind, n.low, n.high, gap,
                             float(gap / atr) if atr > ZERO else 0.0,
                             max(0, index - n.end))

        nxt = next((n for n in pool if n.kind == "cluster"), None)
        major = next((n for n in pool if n.kind == "range"), None)
        if nxt is None and pool:
            nxt = pool[0]
        if major is nxt:
            major = None

        ext: Reference | None = None
        side_anchors = [a for a in self.anchors
                        if (a.price > edge if up else a.price < edge)]
        if side_anchors:
            a = min(side_anchors, key=lambda a: abs(a.price - edge))
            gap = a.price - edge
            ext = Reference(a.id, "anchor", a.price, a.price, gap,
                            float(gap / atr) if atr > ZERO else 0.0,
                            max(0, index - a.index), a.role)
        else:
            real = [k for k in self.frontier.candles[:index + 1] if not k.synthetic]
            if real:
                v = max(k.h for k in real) if up else min(k.l for k in real)
                if (v > edge) if up else (v < edge):
                    gap = v - edge
                    ext = Reference("EXT", "extreme", v, v, gap,
                                    float(gap / atr) if atr > ZERO else 0.0, 0,
                                    "canvas extreme (no anchors admitted)")

        # `pool` is already ordered by near-edge distance, so `pool[0]` is the zone price
        # meets first **in price order**. That is deliberately not `nxt`: `nxt` is the
        # nearest *cluster*, and a parent range can sit in front of it.
        route: ZoneRoute | None = None
        if pool:
            first = pool[0]
            label = ("NEXT" if first is nxt else
                     "NEXT_MAJOR" if first is major else "FIRST_IN_PRICE")
            route = measure_route(first, edge, price, up=up, atr=atr, tol=tol,
                                  label=label)

        return SideReferences(ref(nxt) if nxt else None,
                              ref(major) if major else None, ext,
                              route=route,
                              corridor=build_corridor(known, edge, up=up, atr=atr))

    # ── the state ───────────────────────────────────────────────────────────
    def read(self, reading: Reading) -> MapState:
        i = reading.index
        candle = self.frontier.candles[i]
        price = candle.c
        atr = atr_at(self.frontier.candles, i)

        # Everything comes off the reading, which snapshotted the frontier's state at
        # this candle. Reading it back off the live frontier would describe every candle
        # using the last candle's structure.
        current: Current | None = None
        if reading.node_id is not None and reading.band is not None:
            low, high = reading.band
            width = high - low
            pos = (price - low) / width if width > ZERO else None
            par = self._parent_of(reading.node_id)
            ppos = None
            if par is not None and par.width > ZERO:
                ppos = (price - par.low) / par.width
            current = Current(reading.node_id, reading.node_kind or "cluster",
                              low, high, reading.node_status or PROVISIONAL,
                              pos, _third(pos),
                              par.id if par else None,
                              par.low if par else None,
                              par.high if par else None, ppos)

        edge_up = current.high if current else price
        edge_dn = current.low if current else price
        exclude = current.id if current else None

        refs: list[Reference] = []
        if current is not None:
            refs.append(Reference(f"{current.id}.high", current.kind,
                                  current.high, current.high, current.high - price,
                                  float((current.high - price) / atr) if atr > ZERO
                                  else 0.0, 0, "upper edge"))
            refs.append(Reference(f"{current.id}.low", current.kind,
                                  current.low, current.low, current.low - price,
                                  float((current.low - price) / atr) if atr > ZERO
                                  else 0.0, 0, "lower edge"))
        if reading.left_id is not None and reading.left_edge is not None:
            edge = reading.left_edge
            refs.append(Reference(f"{reading.left_id}.edge",
                                  reading.left_kind or "cluster", edge, edge,
                                  edge - price,
                                  float((edge - price) / atr) if atr > ZERO else 0.0,
                                  0, "last defended"))

        tol = tol_at(self.frontier.candles, i, self.frontier.tol_atr)
        above = self._side(i, edge_up, True, atr, exclude, price, tol)
        below = self._side(i, edge_dn, False, atr, exclude, price, tol)
        sa = above.next.distance if above.next else None
        sb = abs(below.next.distance) if below.next else None
        arrival = Arrival(reading.arrived_from, reading.arrived_direction,
                          reading.bars_in_transit)
        status = _status(reading)

        return MapState(
            index=i, at=candle.close_time, price=price, current=current,
            break_up=current.high if current else None,
            break_down=current.low if current else None,
            above=above, below=below,
            interaction=reading.interaction,
            references=tuple(refs),
            status=status,
            arrival=arrival,
            market_state=_market_state(status, current, arrival, reading),
            space_above=sa, space_below=sb,
            space_above_atr=float(sa / atr) if sa is not None and atr > ZERO else 0.0,
            space_below_atr=float(sb / atr) if sb is not None and atr > ZERO else 0.0,
            left_id=reading.left_id, left_edge=reading.left_edge,
            left_low=reading.left_low, left_high=reading.left_high, atr=atr)

    def _parent_of(self, node_id: str) -> Node | None:
        node = self.snapshot.by_id(node_id)
        if node is None or node.parent is None:
            return None
        return self.snapshot.by_id(node.parent)

    def states(self) -> list[MapState]:
        return [self.read(r) for r in self.frontier.readings]


def interpret(snapshot: MapSnapshot, frontier: Frontier, *,
              anchors: Sequence[Anchor] = ()) -> list[MapState]:
    return Interpreter(snapshot, frontier, anchors=anchors).states()


def _ref_short(r: Reference | None) -> str:
    return f"{r.id} {float(r.distance):+,.0f}" if r else "—"


def compact(state: MapState) -> str:
    """One line per candle, for a scrollable trace."""
    cur = (f"{state.current.id} {state.current.band} [{state.current.status[:4]}]"
           if state.current else "—")
    lv = (f"up {float(state.break_up):,.0f}/dn {float(state.break_down):,.0f}"
          if state.break_up is not None else "—")
    up = _ref_short(state.above.next)
    dn = _ref_short(state.below.next)
    return (f"c{state.index:<4} {float(state.price):>9,.1f}  {state.status:<18} "
            f"{cur:<28} {lv:<24} ^{up:<13} v{dn}")


def _route_short(r: ZoneRoute | None) -> str:
    if r is None:
        return "—"
    return (f"{r.id} free {float(r.free_to_near):,.0f} depth "
            f"{float(r.zone_depth):,.0f} {r.watch}")


def compact_route(state: MapState) -> str:
    """One line per candle for the route, kept separate from `compact` so the existing
    trace shape is not disturbed."""
    return (f"c{state.index:<4} {float(state.price):>9,.1f}  "
            f"^ {_route_short(state.route_above):<52} "
            f"v {_route_short(state.route_below)}")


__all__ = ["STATUS_VOCABULARY", "MARKET_STATES", "FORBIDDEN", "PROVISIONAL",
           "HISTORICAL", "Reference", "SideReferences", "Current", "Arrival",
           "MapState", "Interpreter", "interpret", "compact", "compact_route"]
