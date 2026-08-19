"""
The release context — **what exactly broke, at which scale, and what lies beyond it.**

The Participation Context Study measured the hole this module fills. On the candle a
structure releases, the node is finalised and `MapState.current` is already `None`, so
`PRICE_LOCATION` read `NO_STRUCTURE` on 82% of releases; the route was still measured from
the *current* structure's edge rather than from the boundary that actually gave way; and
when an outer and an inner boundary broke on the **same candle** every published field was
identical for the two. A trader cannot answer *"what just broke?"* from that, and neither
could the decision layer.

```
FRONTIER + MAP + MICRO + POST-BREAK
              |
        RELEASE CONTEXT        what broke · which scale · inside what · what is beyond it
              |
        LIVE THESIS            direction, generation, invalidation   (not here)
              |
        PARTICIPATION          is now a sensible place to act        (not here)
```

## A pure consumer, and no third detector

Everything is read off a finished `Frontier` — its readings, its two logs, its candles —
the same shape `eye.py` and `postbreak.py` already take. `Frontier` is not modified and
knows nothing about this module. Living in `src/livemap/` also puts it inside
`test_livemap_quarantine.py` in both directions.

```
OUTER   breaks.from_logs()      authoritative. `frontier.py` records a `break` in exactly
                                one place — the branch where the CURRENT structure's
                                acceptance completes — so a log break IS an outer release.
MICRO   MicroView.events        MICRO_BREAK_UP / MICRO_BREAK_DOWN, already published, with
                                the band still on the view because `micro.py` keeps
                                `_subject` = "the micro this candle was about".
INNER   the one addition        see below.
```

## The one addition, stated plainly

There is no published event for *"a mapped structure inside the current one has released"*.
So this module applies the repo's own two-close transition rule — `BREAK_CLOSES` closes
beyond the edge with the close before the run on the inside, skirted by `tol_at` — to
boundaries **the map already published**.

It creates no structure, mints no band, introduces no number, no score and no threshold,
writes nothing to `_known` / `log` / `live_log` / the historical map, and never changes a
parent. It detects an event on an existing structure with the existing rule. `micro.py` is
the precedent, one level down, and says so: *"MICRO_BREAK  structure.BREAK_CLOSES  two
closes, the same rule."*

Containment is **price containment plus strictly narrower**, not `hierarchy._contains`:
that helper also demands time containment, which is right between two nodes of one
historical scan and meaningless between a frozen node from an hour ago and the live
structure standing over it now.

## Release, not crossing

Up through a structure's high, or down through its low, leaves it. The mirror crossings
walk back **into** it, which the stack already calls `RE_ENTRY`. Counting the two as one
event files a re-entry as a breakout, and the first participation study had to be corrected
mid-flight for exactly that: 441 of 908 crossings were re-entries.

## Simultaneous releases are all kept

`ReleaseState.releases` is a tuple. When an outer and an inner boundary break together both
are emitted with their own broken boundary, their own parent and their own route origin. No
priority order is applied because none has been measured — two scales at once is reported as
`MULTI_SCALE`, not resolved by a guess.

## Causality

`ReleaseObserver` is fed one candle at a time and holds no list of future events, the same
shape `MicroObserver` and `PostBreakObserver` have. `observe(..., upto=k)` is therefore
prefix-equal to `observe(...)[:k+1]`, and `test_release_prefix_causality` pins it. Nothing
here is retrospective: a release record is written on its own candle and never revised.

## What is deliberately absent

No generation, no thesis, no invalidation, no opportunity identity, no position. Those
belong to the thesis and decision worlds; putting them here would give the observation
layer a second copy of the generation and make this module depend on an unvalidated one.
This layer answers *what broke and what is beyond it*, and stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Frontier, Reading
from src.boxes.hierarchy import Node
from src.boxes.micro import MICRO_BREAK_DOWN, MICRO_BREAK_UP
from src.boxes.snapshot import MapSnapshot
from src.boxes.structure import BREAK_CLOSES, STRUCTURE_KINDS, atr_at, tol_at
from src.domain.models import ZERO, Candle
from src.livemap.breaks import from_logs
from src.livemap.route import CorridorStop, ZoneRoute, build_corridor, first_in_price
from src.livemap.route import measure as measure_route

# ── the three observable scales. Categories, never setup names ───────────────
OUTER = "OUTER"
INNER = "INNER"
MICRO = "MICRO"
SCALES = frozenset({OUTER, INNER, MICRO})

# ── where the identity came from, so a reader can audit it ───────────────────
LOG = "LOG"                    # breaks.from_logs — the frontier's own break event
INNER_SCAN = "INNER_SCAN"      # the two-close rule on a mapped inner boundary
MICRO_EVENT = "MICRO_EVENT"    # micro.py's own MICRO_BREAK_*
ORIGINS = frozenset({LOG, INNER_SCAN, MICRO_EVENT})

# ── price against the boundary that broke ────────────────────────────────────
BEYOND_EDGE = "BEYOND_BROKEN_EDGE"
AT_EDGE = "AT_BROKEN_EDGE"
BACK_INSIDE = "BACK_INSIDE_BROKEN_STRUCTURE"
RELEASE_LOCATIONS = frozenset({BEYOND_EDGE, AT_EDGE, BACK_INSIDE})

# ── price against the structure the release happened INSIDE ──────────────────
INSIDE_PARENT = "INSIDE_PARENT"
AT_PARENT_EDGE = "AT_PARENT_EDGE"
BEYOND_PARENT = "BEYOND_PARENT"
NO_PARENT = "NO_PARENT"
PARENT_LOCATIONS = frozenset({INSIDE_PARENT, AT_PARENT_EDGE, BEYOND_PARENT, NO_PARENT})

# ── which existing structural level is controlling price right now ───────────
OUTER_CONTROLLING = "OUTER_CONTROLLING"
INNER_CONTROLLING = "INNER_CONTROLLING"
MICRO_CONTROLLING = "MICRO_CONTROLLING"
MULTI_SCALE = "MULTI_SCALE"
UNRESOLVED = "UNRESOLVED"
CONTROLLING = frozenset({OUTER_CONTROLLING, INNER_CONTROLLING, MICRO_CONTROLLING,
                         MULTI_SCALE, UNRESOLVED})

_CONTROLLING_OF = {OUTER: OUTER_CONTROLLING, INNER: INNER_CONTROLLING,
                   MICRO: MICRO_CONTROLLING}

#: Words this layer may never emit. It describes structure; it does not trade.
FORBIDDEN = ("LONG", "SHORT", "ENTRY", "ENTER", "EXIT", "BUY", "SELL", "TARGET", "SIZE",
             "ORDER", "SCORE", "CONFIDENCE", "PROBABILITY")


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Release:
    """One causal structural release, frozen at the candle it happened on.

    Every field is either a copy of a published fact or arithmetic on published facts.
    There is deliberately no `ends_at`, no outcome, and no thesis: an identity that carries
    the future is the bug `BreakEpisode` was written to avoid.
    """

    id: str                        # "RL01"
    index: int
    at: datetime
    scale: str                     # OUTER | INNER | MICRO
    direction: str                 # up | down
    origin: str                    # LOG | INNER_SCAN | MICRO_EVENT

    # ── §6 what broke, which edge, which structure ──────────────────────────
    broken_id: str
    broken_edge: Decimal
    broken_low: Decimal | None = None
    broken_high: Decimal | None = None
    broken_kind: str = ""

    # ── §9 inside what ──────────────────────────────────────────────────────
    parent_id: str | None = None
    parent_low: Decimal | None = None
    parent_high: Decimal | None = None

    # ── §7 where price is, relative to the release ──────────────────────────
    price: Decimal = ZERO
    beyond: Decimal = ZERO         # signed into the break direction; negative = back inside
    beyond_atr: float = 0.0
    location: str = BEYOND_EDGE
    parent_location: str = NO_PARENT
    #: Where price stood inside the broken structure on the candle before the run began.
    position_before: Decimal | None = None

    # ── §8 the route, measured FROM THE BOUNDARY THAT BROKE ─────────────────
    route: ZoneRoute | None = None
    corridor: tuple[CorridorStop, ...] = ()

    # ── §3 prior structure context ──────────────────────────────────────────
    prior_node_id: str | None = None
    prior_interaction: str = ""
    arrived_from: str | None = None
    arrived_direction: str = ""

    # ── §20 the smallest currently observable behaviour ─────────────────────
    micro_id: str | None = None
    micro_state: str | None = None

    #: The post-break episode live at this candle, when there is one. A copy of the id,
    #: never the episode — the thesis world owns that.
    episode_id: str | None = None

    def __post_init__(self) -> None:
        if self.scale not in SCALES:
            raise ValueError(f"unknown release scale {self.scale!r}")
        if self.direction not in ("up", "down"):
            raise ValueError(f"direction must be up|down, got {self.direction!r}")
        if self.origin not in ORIGINS:
            raise ValueError(f"unknown release origin {self.origin!r}")
        if self.location not in RELEASE_LOCATIONS:
            raise ValueError(f"unknown release location {self.location!r}")
        if self.parent_location not in PARENT_LOCATIONS:
            raise ValueError(f"unknown parent location {self.parent_location!r}")

    @property
    def up(self) -> bool:
        return self.direction == "up"

    @property
    def boundary(self) -> str:
        """The broken boundary, named the way a trader says it: `C09.high`."""
        side = "high" if self.up else "low"
        return f"{self.broken_id}.{side}"

    @property
    def band(self) -> str:
        if self.broken_low is None:
            return "?"
        return f"{float(self.broken_low):,.0f}-{float(self.broken_high):,.0f}"

    def held(self, price: Decimal, tol: Decimal) -> bool:
        """Is price still on the released side of the boundary? `retest.py`'s own sense."""
        return self.past(price) > tol

    def past(self, price: Decimal) -> Decimal:
        """How far `price` sits beyond the broken edge, in the release's own direction."""
        return ((price - self.broken_edge) if self.up
                else (self.broken_edge - price))

    def lines(self) -> list[str]:
        out = [f"RELEASE       {self.id}  {self.scale}  {self.boundary} "
               f"{self.direction.upper()} at {float(self.broken_edge):,.0f}"
               f"   [{self.origin}]"]
        if self.parent_id:
            out.append(f"INSIDE        {self.parent_id}  "
                       f"{float(self.parent_low):,.0f}-{float(self.parent_high):,.0f}"
                       f"   {self.parent_location}")
        out.append(f"LOCATION      {self.location}   "
                   f"{float(self.beyond):+,.0f} pts ({self.beyond_atr:+.2f} ATR) "
                   f"beyond the broken edge")
        if self.route is None:
            out.append("ROUTE         nothing mapped ahead of the broken boundary")
        else:
            r = self.route
            out.append(f"ROUTE         from {float(self.broken_edge):,.0f}: {r.id} "
                       f"{r.band}   free {float(r.free_to_near):,.0f} | depth "
                       f"{float(r.zone_depth):,.0f} | far {float(r.free_to_far):,.0f}"
                       f"   {r.watch}")
        if self.corridor:
            out.append("CORRIDOR      " + " · ".join(s.line() for s in self.corridor[:4]))
        return out


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """One candle's release picture. `releases` is a tuple because §5 forbids choosing."""

    index: int
    at: datetime
    price: Decimal
    #: Releases that happened ON this candle. Empty on most candles.
    releases: tuple[Release, ...] = ()
    #: The newest release still held — price is still beyond its broken edge. This is what
    #: makes a release context outlive the candle it was born on.
    active: Release | None = None
    controlling_scale: str = UNRESOLVED

    def __post_init__(self) -> None:
        if self.controlling_scale not in CONTROLLING:
            raise ValueError(f"unknown controlling scale {self.controlling_scale!r}")

    @property
    def simultaneous(self) -> bool:
        """More than one causal release on this candle — §5's case."""
        return len(self.releases) > 1

    @property
    def scales(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.scale for r in self.releases))

    def of(self, scale: str) -> Release | None:
        return next((r for r in self.releases if r.scale == scale), None)

    def lines(self) -> list[str]:
        out: list[str] = []
        for r in self.releases:
            out.extend(r.lines())
        if not self.releases and self.active is not None:
            out.append(f"HOLDING       {self.active.id} {self.active.scale} "
                       f"{self.active.boundary} still held, "
                       f"{float(self.active.past(self.price)):+,.0f} pts beyond")
        out.append(f"CONTROLLING   {self.controlling_scale}"
                   + ("   (two scales released together — not resolved)"
                      if self.simultaneous else ""))
        return out


# ─────────────────────────────────────────────────────────────────────────────
def _released(closes: Sequence[Decimal], i: int, edge: Decimal, tol: Decimal,
              up: bool, break_closes: int) -> bool:
    """The repo's two-close **transition** rule, applied to a published boundary.

    `break_closes` consecutive closes beyond the edge **and** the close before them on the
    inside — so this is the candle the boundary changed sides, never a restatement of a
    side price has held for twenty candles.
    """
    if i - break_closes < 0:
        return False
    for k in range(i - break_closes + 1, i + 1):
        if not ((closes[k] > edge + tol) if up else (closes[k] < edge - tol)):
            return False
    before = closes[i - break_closes]
    return (before <= edge + tol) if up else (before >= edge - tol)


def _inside(node: Node, low: Decimal, high: Decimal, tol: Decimal) -> bool:
    """Price containment plus strictly narrower. **Not** `hierarchy._contains`.

    That helper also requires time containment, which is correct between two nodes of one
    historical scan and meaningless between a frozen node from an hour ago and the live
    structure standing over it now.
    """
    return (node.low >= low - tol and node.high <= high + tol
            and node.width < (high - low))


def _position(low: Decimal, high: Decimal, price: Decimal) -> Decimal | None:
    width = high - low
    return None if width <= ZERO else (price - low) / width


def _release_location(beyond: Decimal, tol: Decimal) -> str:
    if beyond > tol:
        return BEYOND_EDGE
    if beyond >= -tol:
        return AT_EDGE
    return BACK_INSIDE


def _parent_location(low: Decimal | None, high: Decimal | None, price: Decimal,
                     tol: Decimal) -> str:
    if low is None or high is None:
        return NO_PARENT
    if price > high + tol or price < low - tol:
        return BEYOND_PARENT
    if price >= high - tol or price <= low + tol:
        return AT_PARENT_EDGE
    return INSIDE_PARENT


# ─────────────────────────────────────────────────────────────────────────────
class ReleaseObserver:
    """Fed one candle at a time, exactly as `MicroObserver` and `PostBreakObserver` are.

    It holds the releases it has already seen and **no list of future ones**. That is what
    makes `observe(upto=k)` prefix-equal to a full run.
    """

    __slots__ = ("snapshot", "tol_atr", "break_closes", "history", "_n",
                 "_readings", "_closes", "_candles", "_finalised")

    def __init__(self, snapshot: MapSnapshot, *, tol_atr: Decimal = Decimal("0.25"),
                 break_closes: int = BREAK_CLOSES) -> None:
        self.snapshot = snapshot
        self.tol_atr = tol_atr
        self.break_closes = break_closes
        self.history: list[Release] = []
        self._n = 0
        self._readings: dict[int, Reading] = {}
        self._closes: dict[int, Decimal] = {}
        self._candles: list[Candle] = []
        self._finalised: list[Node] = []

    # ── the map as it is known AT this candle ───────────────────────────────
    def _pool(self, index: int) -> list[Node]:
        """Frozen structures plus live structures already finalised. The interpreter's own
        rule, and the reason a release never sees a node that does not exist yet."""
        return ([n for n in self.snapshot.nodes if n.kind in STRUCTURE_KINDS]
                + [n for n in self._finalised if n.end <= index])

    def _mint(self, **kw) -> Release:
        self._n += 1
        return Release(id=f"RL{self._n:02d}", **kw)

    def _geometry(self, index: int, edge: Decimal, up: bool, price: Decimal,
                  atr: Decimal, tol: Decimal, exclude: Sequence[str]):
        """Route and corridor measured **from the boundary that broke** — §8 and §25.

        `route.py`'s own machinery with a different origin. The structure that just broke
        is excluded from the pool: its far side is behind price now, and offering it as the
        next zone ahead would report a depth price has already traversed.
        """
        pool = [n for n in self._pool(index) if n.id not in exclude]
        first = first_in_price(pool, edge, up=up)
        route = (measure_route(first, edge, price, up=up, atr=atr, tol=tol,
                               label="FIRST_IN_PRICE")
                 if first is not None else None)
        return route, build_corridor(pool, edge, up=up, atr=atr, limit=6)

    # ── the loop ────────────────────────────────────────────────────────────
    def on_candle(self, reading: Reading, candle: Candle, candles: Sequence[Candle],
                  *, breaks: Sequence = (), episode_id: str | None = None,
                  finalised: Sequence[Node] = ()) -> ReleaseState:
        """One candle. `breaks` are the log's break records **at this candle**, if any."""
        i, price = reading.index, candle.c
        self._readings[i] = reading
        self._closes[i] = price
        self._candles = list(candles[:i + 1])
        self._finalised = list(finalised)
        atr = atr_at(candles, i)
        tol = tol_at(candles, i, self.tol_atr)
        prior = self._readings.get(i - self.break_closes)

        common = dict(index=i, at=candle.close_time, price=price,
                      prior_node_id=prior.node_id if prior else None,
                      prior_interaction=prior.interaction if prior else "",
                      arrived_from=reading.arrived_from,
                      arrived_direction=reading.arrived_direction,
                      micro_id=reading.micro.micro_id if reading.micro else None,
                      micro_state=reading.micro.micro_state if reading.micro else None,
                      episode_id=episode_id)
        found: list[Release] = []

        # ── OUTER — the frontier's own break event, not re-derived ──────────
        for brk in breaks:
            if brk.index != i or brk.edge is None:
                continue
            up = brk.direction == "up"
            beyond = (price - brk.edge) if up else (brk.edge - price)
            pos = (_position(brk.low, brk.high, self._closes.get(i - self.break_closes,
                                                                price))
                   if brk.low is not None and brk.high is not None else None)
            route, corridor = self._geometry(i, brk.edge, up, price, atr, tol,
                                             exclude=(brk.structure_id,))
            found.append(self._mint(
                scale=OUTER, direction=brk.direction, origin=LOG,
                broken_id=brk.structure_id, broken_edge=brk.edge,
                broken_low=brk.low, broken_high=brk.high, broken_kind=brk.kind,
                beyond=beyond,
                beyond_atr=float(beyond / atr) if atr > ZERO else 0.0,
                location=_release_location(beyond, tol),
                parent_location=NO_PARENT, position_before=pos,
                route=route, corridor=corridor, **common))

        # ── INNER — the one addition. Boundaries the map already published ──
        #
        # The frame is the current structure as it was known BEFORE the run began; reading
        # it off this candle would use a band the release itself has already changed.
        if prior is not None and prior.band is not None:
            lo, hi = prior.band
            for node in self._pool(i - self.break_closes):
                if node.id == prior.node_id or not _inside(node, lo, hi, tol):
                    continue
                for up, edge in ((True, node.high), (False, node.low)):
                    if not _released(self._closes, i, edge, tol, up, self.break_closes):
                        continue
                    beyond = (price - edge) if up else (edge - price)
                    route, corridor = self._geometry(i, edge, up, price, atr, tol,
                                                     exclude=(node.id,))
                    found.append(self._mint(
                        scale=INNER, direction="up" if up else "down",
                        origin=INNER_SCAN, broken_id=node.id, broken_edge=edge,
                        broken_low=node.low, broken_high=node.high,
                        broken_kind=node.kind,
                        parent_id=prior.node_id, parent_low=lo, parent_high=hi,
                        beyond=beyond,
                        beyond_atr=float(beyond / atr) if atr > ZERO else 0.0,
                        location=_release_location(beyond, tol),
                        parent_location=_parent_location(lo, hi, price, tol),
                        position_before=_position(
                            node.low, node.high,
                            self._closes.get(i - self.break_closes, price)),
                        route=route, corridor=corridor, **common))

        # ── MICRO — micro.py's own event, subordinate and copied ────────────
        m = reading.micro
        if m is not None and m.micro_low is not None and m.micro_high is not None:
            for event, up in ((MICRO_BREAK_UP, True), (MICRO_BREAK_DOWN, False)):
                if event not in m.events:
                    continue
                edge = m.micro_high if up else m.micro_low
                beyond = (price - edge) if up else (edge - price)
                route, corridor = self._geometry(i, edge, up, price, atr, tol,
                                                 exclude=())
                found.append(self._mint(
                    scale=MICRO, direction="up" if up else "down", origin=MICRO_EVENT,
                    broken_id=m.micro_id or "MICRO", broken_edge=edge,
                    broken_low=m.micro_low, broken_high=m.micro_high,
                    broken_kind="micro",
                    parent_id=m.parent_id, parent_low=m.parent_low,
                    parent_high=m.parent_high,
                    beyond=beyond,
                    beyond_atr=float(beyond / atr) if atr > ZERO else 0.0,
                    location=_release_location(beyond, tol),
                    parent_location=_parent_location(m.parent_low, m.parent_high,
                                                     price, tol),
                    position_before=_position(m.micro_low, m.micro_high,
                                              self._closes.get(i - self.break_closes,
                                                               price)),
                    route=route, corridor=corridor, **common))

        self.history.extend(found)
        active = self._active(price, tol)
        return ReleaseState(index=i, at=candle.close_time, price=price,
                            releases=tuple(found), active=active,
                            controlling_scale=self._controlling(found, active))

    def _active(self, price: Decimal, tol: Decimal) -> Release | None:
        """The newest release price has not given back. §11's "still controlling"."""
        for r in reversed(self.history):
            if r.held(price, tol):
                return r
        return None

    def _controlling(self, found: Sequence[Release], active: Release | None) -> str:
        """Which existing structural level is controlling price now — §11.

        No score, no detector, no priority order: two scales releasing together is reported
        as `MULTI_SCALE`, because which of them matters has never been measured.
        """
        scales = {r.scale for r in found}
        if len(scales) > 1:
            return MULTI_SCALE
        if len(scales) == 1:
            return _CONTROLLING_OF[next(iter(scales))]
        if active is not None:
            return _CONTROLLING_OF[active.scale]
        return UNRESOLVED


# ─────────────────────────────────────────────────────────────────────────────
def observe(frontier: Frontier, snapshot: MapSnapshot | None = None, *,
            upto: int | None = None) -> list[ReleaseState]:
    """Every candle's release state, in order. Prefix-causal by construction.

    `episodes` is optional context: when `postbreak.observe` has already run, its episode
    id is copied onto each release so a consumer can join the two without re-deriving
    either. It is a copy of an id and nothing more.
    """
    snap = snapshot if snapshot is not None else frontier.snapshot
    obs = ReleaseObserver(snap, tol_atr=frontier.tol_atr)
    by_index: dict[int, list] = {}
    for brk in from_logs(frontier, snap):
        by_index.setdefault(brk.index, []).append(brk)

    # Episode ids, read off the same finished frontier. Imported lazily so `release.py`
    # stays usable without the post-break layer, and so the two never form a cycle.
    from src.livemap.postbreak import observe as episode_observe
    episodes = {s.index: s.episode.id for s in episode_observe(frontier, snap)}

    finalised = frontier.history()
    out: list[ReleaseState] = []
    for reading in frontier.readings:
        i = reading.index
        if upto is not None and i > upto:
            break
        out.append(obs.on_candle(
            reading, frontier.candles[i], frontier.candles,
            breaks=by_index.get(i, ()), episode_id=episodes.get(i),
            finalised=[n for n in finalised if n.end <= i]))
    return out


def releases(states: Sequence[ReleaseState]) -> list[Release]:
    """Every release, flattened, in candle order."""
    return [r for s in states for r in s.releases]


def simultaneous(states: Sequence[ReleaseState]) -> list[ReleaseState]:
    """The §5 cases — more than one causal release on one candle."""
    return [s for s in states if s.simultaneous]


def compact(state: ReleaseState) -> str:
    """One line per candle, for a scrollable trace."""
    what = " + ".join(f"{r.scale[0]}:{r.boundary}" for r in state.releases) or "—"
    return (f"c{state.index:<4} {float(state.price):>9,.1f}  {what:<34} "
            f"{state.controlling_scale:<18} "
            f"{(state.active.id + ' ' + state.active.scale) if state.active else '—'}")


__all__ = ["OUTER", "INNER", "MICRO", "SCALES", "LOG", "INNER_SCAN", "MICRO_EVENT",
           "ORIGINS", "BEYOND_EDGE", "AT_EDGE", "BACK_INSIDE", "RELEASE_LOCATIONS",
           "INSIDE_PARENT", "AT_PARENT_EDGE", "BEYOND_PARENT", "NO_PARENT",
           "PARENT_LOCATIONS", "OUTER_CONTROLLING", "INNER_CONTROLLING",
           "MICRO_CONTROLLING", "MULTI_SCALE", "UNRESOLVED", "CONTROLLING", "FORBIDDEN",
           "Release", "ReleaseState", "ReleaseObserver", "observe", "releases",
           "simultaneous", "compact"]
