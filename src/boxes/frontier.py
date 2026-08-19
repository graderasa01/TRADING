"""
The live frontier — `LIVE-FRONTIER.md` §6.

The historical map says where things are. This says **what is happening now**, and turns
"now" into "history" one structure at a time.

```
M001   HISTORICAL MAP    immutable, never touched by a live candle
F001   LIVE FRONTIER     this module — provisional, mutable
LOG    LIVE EVENTS       append-only
```

## Four concepts that must never blur

```
BREAK_LEVEL_UP    = the current structure's OWN high      <- the breakout point
BREAK_LEVEL_DOWN  = the current structure's OWN low
NEXT reference    = the next mapped object, somewhere else entirely
```

A `22460-22480` cluster breaks **above 22480**, not above the next reference at 22560.
Rev 1 of the plan got this wrong and it is the first thing the fixture pins.

## The lifecycle, and what it refuses to do

```
        MOVING ──────────────┐
          ▲                  │  read_window() sees a band, with currency
          │ band no longer   ▼
          │ touched      STRUCTURE_CANDIDATE     provisional
        LEAVING              │  choose() confirms it (stability run + gates)
          ▲                  ▼
          │            CONFIRMED  ── cluster | range, classified independently
          │                  │  two closes beyond an edge
          └──────────────────┘  finalise -> frozen Node, appended to history
```

Three refusals, each of which is a bug that has already happened once in this repo:

**1. `LEAVING` is a state, so a walk is not twenty boxes.** Price going
`22482 22488 22497 22510 22520 22530` produces `LEAVING C41`, not six clusters. The
*"har pause ek box"* failure was fixed twice on the historical side; without an explicit
state it walks straight back in through the live door.

**2. The shelf you just left cannot become the shelf you just found.** The guard is not a
banned state transition — a genuinely new structure at a distance must be free to form
immediately. The guard is **band overlap**: a candidate sharing half or more of its band
with the node just left is that node seen again, and it is refused as a new structure.
Coming back into it is `re_entry`, which is an event, not a birth.

**3. `choose()` returning a band does NOT mean price is there.** Caught on real data:
at candle 443 price was trading at 60,380-60,409 and the detector correctly returned a
shelf at 60,271-60,309 — real, and left eight candles earlier. A forty-candle window is
still dominated by whatever filled it. Currency is checked separately, every time.

## Freezing at confirmation is the no-look-ahead guard

`events.py` exists because *"a breakout candle widens the very box it is breaking, and the
break hides itself."* Here the band is frozen the moment the node is confirmed and is
never recomputed, so the candle that breaks it is always judged against the band as it
stood **before** that candle closed. There is no widening to defend against.

## Acceptance is the existing two-close rule, and nothing more

`ACCEPTED_ABOVE` means `break_closes` consecutive closes beyond the edge — the structural
constant `mapper.py` and `extend_back` already use, chosen because one wick is not a
break. **No new threshold is invented here.** Every raw measurement is recorded alongside
(`closes_beyond`, `max_excursion`, `excursion_atr`, `returned_inside`) so that a measured
definition can replace this one later without re-scanning anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from src.boxes.adaptive import (
    WINDOWS, Proposal, choose, overlap, read_window, touches)
from src.boxes.hierarchy import Node, Rotation
from src.boxes.micro import MicroObserver, MicroView
from src.boxes.snapshot import (
    SAME_NODE_OVERLAP, LiveEvent, LiveEventLog, LiveLog, MapSnapshot)
from src.boxes.structure import (
    BREAK_CLOSES, STRUCTURE_KINDS, atr_at, extend_back, last_touch, rotations_in,
    tol_at)
from src.domain.models import ZERO, Candle

#: How far behind the live candle `last_touch` may sit and still count as "price is here".
#: One candle of slack, because a single spike out of a band is not leaving it — the same
#: reasoning that makes `break_closes` two rather than one.
CURRENCY_SLACK = 1

MOVING = "MOVING"
LEAVING = "LEAVING"
STRUCTURE_CANDIDATE = "STRUCTURE_CANDIDATE"
CONFIRMED = "CONFIRMED"

# ── two vocabularies that used to be one, and were never the same thing ──────
#
# `LiveNode.status` was declared `PROVISIONAL | CONFIRMED | HISTORICAL`, but `_mint`
# always passed `CONFIRMED`, so `PROVISIONAL` was dead on arrival. Meanwhile `Reading`
# computed its own `node_status` as *"HISTORICAL if revisited else PROVISIONAL"* — a
# different question with the same words, which is how the interpreter came to be told
# `PROVISIONAL` about a node the frontier considered confirmed.
#
#     LIVE_STATES    where a live node is in ITS OWN lifecycle
#     MAP_STATUSES   how the map should PRESENT it: is this something history already
#                    knew about, or something the frontier has just built?
#
# `FORMING` is deliberately absent from `LIVE_STATES`: nothing sets it yet. An unused
# member of a closed vocabulary is exactly the dead default this change removes, and
# Phase B adds it when the micro lifecycle actually needs it.
STATUS_CONFIRMED = "CONFIRMED"
CLOSED = "CLOSED"
LIVE_STATES = frozenset({STATUS_CONFIRMED, CLOSED})

PROVISIONAL = "PROVISIONAL"
HISTORICAL = "HISTORICAL"
MAP_STATUSES = frozenset({PROVISIONAL, HISTORICAL})


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LiveNode:
    """A structure forming right now. **Mutable, and never the same object as a frozen
    `Node`** — `finalise()` constructs a new one, so the snapshot cannot be edited through
    a shared reference."""

    id: str
    kind: str                       # cluster | range
    #: FROZEN AT BIRTH. `low` and `high` are assigned once, by `_mint` or `_adopt`, and
    #: never again — `events.py` exists because *"a breakout candle widens the very box it
    #: is breaking, and the break hides itself."* Everything below this line is evidence
    #: and updates freely; these two are geometry and do not.
    low: Decimal
    high: Decimal
    start: int
    end: int
    live_status: str = STATUS_CONFIRMED
    window: int = 0
    score: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)
    migration: float = 0.0
    confirmed_at: int | None = None
    revisited: bool = False        # adopted from history, not newly minted

    # ── live evidence — re-read every candle, never used to decide anything ──
    #
    # These were frozen at mint time: `_mint` copied the Proposal's counts once and no
    # later candle touched them, so a shelf that lived forty candles and defended its
    # edge six times still reported whatever was true on its first. `rotations` was worse
    # — `finalise()` had no such argument at all, so every frontier-built node reached
    # history with `rotations = ()` while the batch scan's nodes carried the full list.
    # The same shelf, described two different ways depending on who found it.
    upper_touches: int = 0
    lower_touches: int = 0
    rotations: tuple[tuple[str, int, int, Decimal], ...] = ()
    time_inside: int = 0           # candles closed within the band
    interactions: int = 0          # candles this node was `current`, inside or out
    #: Where the CONTIGUOUS observation starts. For a minted node that is `start`, which
    #: `extend_back` already walked back over unbroken occupation. For an **adopted** node
    #: it is the candle the revisit began: `_adopt` keeps the original `start` so the
    #: shelf keeps its identity, but measuring evidence from there would count the entire
    #: absence — every excursion and return in between would register as rotation inside a
    #: band price was nowhere near.
    evidence_from: int = 0

    # break bookkeeping — measurements, not gates
    broken_at: int | None = None
    break_direction: str = ""
    closes_beyond: int = 0
    max_excursion: Decimal = ZERO
    returned_inside: bool = False
    _side: str = ""

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def break_level_up(self) -> Decimal:
        return self.high

    @property
    def break_level_down(self) -> Decimal:
        return self.low

    def contains(self, price: Decimal, tol: Decimal = ZERO) -> bool:
        return self.low - tol <= price <= self.high + tol

    @property
    def evidence(self) -> dict[str, float]:
        """What this node accumulated while it was alive. Travels on an event when the
        node itself is not finalised — a revisit never is."""
        return {
            "upper_touches": float(self.upper_touches),
            "lower_touches": float(self.lower_touches),
            "rotations": float(len(self.rotations)),
            "time_inside": float(self.time_inside),
            "interactions": float(self.interactions),
            "max_excursion": float(self.max_excursion),
            "returned_inside": float(self.returned_inside),
        }

    def finalise(self, atr: Decimal) -> Node:
        """Construct a frozen `Node`. The live object is not reused or mutated into one.

        `rotations` is carried across here. It was missing, and its absence meant the live
        map and the batch map described the same shelf with different vocabularies — one
        knowing how many times price crossed it, the other not.
        """
        return Node(
            id=self.id, kind=self.kind, start=self.start, end=self.end,
            low=self.low, high=self.high,
            rotations=tuple(Rotation(d, fi, ti, pts)
                            for d, fi, ti, pts in self.rotations),
            upper_touches=self.upper_touches, lower_touches=self.lower_touches,
            score=self.score, parts=dict(self.parts), window=self.window,
            migration=self.migration,
            measurements={
                "closes_beyond": float(self.closes_beyond),
                "max_excursion": float(self.max_excursion),
                "excursion_atr": float(self.max_excursion / atr) if atr > ZERO else 0.0,
                "returned_inside": float(self.returned_inside),
                "time_inside": float(self.time_inside),
                "interactions": float(self.interactions),
                "rotations_count": float(len(self.rotations)),
            },
            provisional=False)


@dataclass(frozen=True, slots=True)
class Reading:
    """One candle's answer. This is what the interpreter will consume."""

    index: int
    state: str
    interaction: str
    node_id: str | None = None
    node_kind: str | None = None
    #: MAP status — how to present this node, not where it is in its own lifecycle.
    #: `HISTORICAL` means the map already knew about it; `PROVISIONAL` means the frontier
    #: built it. For the node's own lifecycle see `LiveNode.live_status`.
    node_status: str | None = None
    band: tuple[Decimal, Decimal] | None = None
    break_level_up: Decimal | None = None
    break_level_down: Decimal | None = None
    left_id: str | None = None
    left_edge: Decimal | None = None    # the edge it broke through
    left_low: Decimal | None = None     # and its full band — the break's own evidence
    left_high: Decimal | None = None
    left_kind: str | None = None
    # how price got here — the route, not just the location
    arrived_from: str | None = None     # the structure it left to reach this one
    arrived_direction: str = ""         # up | down
    bars_in_transit: int = 0            # candles spent belonging to nothing
    measurements: dict[str, float] = field(default_factory=dict)
    #: The band the frontier is looking at but has not confirmed.
    #:
    #: `_loose_candidate()` computes a whole `Proposal` — band, score, window, touches,
    #: traverses, migration, parts — and the old code threw all of it away, keeping only
    #: the word `STRUCTURE_CANDIDATE`. So `FORMING` said *"something is forming"* and
    #: destroyed *"what"*. It is a **major-structure** candidate: it is the thing that
    #: drives `STRUCTURE_CANDIDATE`, and it is not the Phase B micro candidate, which
    #: lives inside the current structure and will get its own field.
    candidate: Proposal | None = None
    #: What the current node had accumulated at this candle. A snapshot, like every other
    #: field here — reading it back off the live node later would describe every candle
    #: using the last candle's evidence.
    evidence: dict[str, float] = field(default_factory=dict)
    #: What price was doing INSIDE the current structure. `None` on every candle that
    #: belongs to no structure, because there is nothing to be inside of.
    #:
    #: This is a **zoom**, never a second opinion: `MICRO_BREAK` is not `MAJOR_BREAK`, and
    #: nothing here is read by `interpreter.py` or `trader.py`. See `micro.py`.
    micro: MicroView | None = None

    def __post_init__(self) -> None:
        if self.node_status is not None and self.node_status not in MAP_STATUSES:
            raise ValueError(
                f"unknown map status {self.node_status!r}. This field says how to "
                f"present a node, not where it is in its lifecycle — for that see "
                f"LiveNode.live_status.")

    def line(self, candle: Candle) -> str:
        band = (f"{float(self.band[0]):,.0f}-{float(self.band[1]):,.0f}"
                if self.band else "—")
        lv = (f"up {float(self.break_level_up):,.0f} / "
              f"dn {float(self.break_level_down):,.0f}"
              if self.break_level_up is not None else "—")
        return (f"c{self.index:<4} {float(candle.c):>9,.1f}  {self.state:<20} "
                f"{self.interaction:<22} {self.node_id or '—':<5} {band:<20} {lv}")


# ─────────────────────────────────────────────────────────────────────────────
class Frontier:
    """Feed it closed candles after the snapshot; ask it what is forming.

    `on_candle` is **O(75)**. It never re-runs the backward scan — doing that every candle
    would repaint the history the first law forbids rewriting, and would cost 0.4s a
    candle besides.
    """

    def __init__(self, snapshot: MapSnapshot, history: Sequence[Candle], *,
                 tol_atr: Decimal = Decimal("0.25"), min_score: float = 0.35,
                 break_closes: int = BREAK_CLOSES) -> None:
        self.snapshot = snapshot
        #: Two logs, split by ownership. `log` is what price did to the FROZEN map;
        #: `live_log` is what price did to what this frontier built. The second one is
        #: new: `_record` used to drop every event whose node was not in the snapshot,
        #: and live-minted nodes carry about three quarters of all breaks.
        self.log = LiveLog(snapshot)
        self.live_log = LiveEventLog()
        self.candles: list[Candle] = list(history)
        self.tol_atr = tol_atr
        self.min_score = min_score
        self.break_closes = break_closes

        self.state = MOVING
        self.current: LiveNode | None = None
        self.left: LiveNode | None = None
        #: The band being watched but not confirmed. Kept so `FORMING` can say what.
        self.candidate: Proposal | None = None
        #: The zoom. Runs only while a structure is current — the exact complement of
        #: step 3's `if self.current is None`, so the major detector and the micro
        #: observer never look at the same candle. It is handed candles and a parent and
        #: hands back a view; it has no reference to this object and cannot change it.
        self.micro = MicroObserver(tol_atr=tol_atr, min_score=min_score,
                                   break_closes=break_closes)
        self.finalised: list[Node] = []
        self.readings: list[Reading] = []
        self._n = 0
        #: Everything the map already knows about — the frozen snapshot's structures plus
        #: everything this frontier has finalised. A proposal landing on any of them is
        #: that structure seen again, never a new one.
        self._known: list[Node] = [n for n in snapshot.nodes
                                   if n.kind in STRUCTURE_KINDS]
        #: The arrival story: which structure price left to reach the one it is in, which
        #: way it travelled, and how long it belonged to nothing on the way. A location
        #: without a route is half the picture — *"kahan hai"* without *"kaise aaya"*.
        self._from_id: str | None = None
        self._from_dir: str = ""
        self._transit_since: int | None = None

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def _i(self) -> int:
        return len(self.candles) - 1

    def _tol(self) -> Decimal:
        return tol_at(self.candles, self._i, self.tol_atr)

    def _window(self) -> list[Candle]:
        return self.candles[max(0, self._i - max(WINDOWS) + 1):self._i + 1]

    def _band_is_current(self, low: Decimal, high: Decimal, tol: Decimal) -> bool:
        """Is price actually at this band right now?

        Extracted from `_is_current` unchanged so the micro observer can ask the same
        question about a band it has no `Proposal` for. One definition of *"price is
        here"*, used by both layers — the alternative is two, which drift.
        """
        end = last_touch(self.candles, low, high, self._i, tol)
        return end is not None and self._i - end <= CURRENCY_SLACK

    def _is_current(self, p: Proposal, tol: Decimal) -> bool:
        """The three-part currency test — a band alone is not a location."""
        return self._band_is_current(p.low, p.high, tol)

    def _known_match(self, p: Proposal) -> Node | None:
        """The structure this proposal is describing, if the map already has one.

        ## Why this replaced "the shelf just left"

        The first version guarded only against the **immediately previous** shelf, because
        `self.left` was cleared the moment a new structure confirmed. Measured against the
        batch scan over five sessions, **11 of 37 finalised live nodes (30%) were a shelf
        the frontier had already finalised**, re-minted under a new id:

            2025-09-12   L03~L01   L04~L01   L05~L01     one shelf, four structures
            2023-10-04   L03~L01   L05~L01   L06~L04   L07~L04

        That is the *"ek shelf, chaar boxes"* failure — fixed twice on the historical
        side — walking back in through the live door. The guard's principle was right and
        its scope was wrong: it must cover **everything the map already knows**, which is
        the frozen snapshot plus everything this frontier has finalised.

        The same test settles the frozen-territory question. `extend_back` walks backward
        from where a structure was detected and has no idea where `M001` ends, so a live
        node's span could land inside a shelf the frozen map already describes — measured
        at 3 of 37. A proposal landing on frozen territory is not a new structure, so
        there is nothing to clamp and nothing to reclaim: it is `M001`'s node, seen again.
        """
        for node in self._known:
            if overlap((node.low, node.high), (p.low, p.high)) >= SAME_NODE_OVERLAP:
                return node
        return None

    def _mint(self, p: Proposal, tol: Decimal, status: str) -> LiveNode:
        """A genuinely new structure. Only reached when nothing known describes it."""
        self._n += 1
        start = extend_back(self.candles, p.low, p.high, self._i, tol)
        return LiveNode(
            id=f"L{self._n:02d}", kind=p.kind, low=p.low, high=p.high,
            start=start, end=self._i, live_status=status, window=p.window,
            score=p.score, parts=dict(p.parts), migration=p.migration,
            upper_touches=p.upper_touches, lower_touches=p.lower_touches,
            evidence_from=start)

    def _adopt(self, node: Node) -> LiveNode:
        """Price came back to something the map already has. Not a birth — a return.

        The adopted node keeps **the original's id and the original's edges**, so a later
        break is a break of `C20` at `C20`'s own boundary, not of some freshly-minted
        twin. That is what makes *"price revisited C41"* expressible at all, and it is the
        distinction the whole map exists to preserve:

            NEW STRUCTURE   price has formed something new
            REVISIT         price has returned to something historical
            BREAK           price leaves through its own boundary
            RE_ENTRY        price returns into the structure it is standing in
        """
        return LiveNode(
            id=node.id, kind=node.kind, low=node.low, high=node.high,
            start=node.start, end=self._i, live_status=STATUS_CONFIRMED,
            window=node.window, score=node.score, parts=dict(node.parts),
            migration=node.migration, upper_touches=node.upper_touches,
            lower_touches=node.lower_touches, revisited=True,
            evidence_from=self._i)

    def _record(self, kind: str, node_id: str, direction: str = "",
                level: Decimal | None = None, detail: str = "",
                evidence: dict[str, float] | None = None) -> None:
        """Route by ownership: the frozen map's log, or the frontier's own.

        The old version was `if self.snapshot.by_id(node_id) is not None:` with no `else`
        — so every event belonging to a node the frontier had minted was silently
        discarded. It never raised, it never warned, and the live map simply had no
        history of its own work.
        """
        event = LiveEvent(kind, node_id, self._i, self.candles[self._i].close_time,
                          direction, level, detail, dict(evidence or {}))
        if self.snapshot.by_id(node_id) is not None:
            self.log.append(event)
        else:
            self.live_log.append(event)

    def _refresh_evidence(self, node: LiveNode, tol: Decimal) -> None:
        """Re-read the node's own evidence from its own span.

        **This function must never influence anything.** It writes only to counters, and
        nothing in this module reads those counters to make a decision — they exist to be
        carried into `finalise()` and onto events. The moment something branches on
        `node.upper_touches`, Phase A has stopped being Phase A.

        `gap` is `read_window`'s own rule (`max(3, n // 6)`), not a new constant, so a
        touch means here exactly what it means everywhere else in the repo.
        """
        lo = node.evidence_from
        span = self.candles[lo:node.end + 1]
        if len(span) < 2:
            return
        gap = max(3, len(span) // 6)
        node.upper_touches = touches(span, node.high, tol, True, gap)[0]
        node.lower_touches = touches(span, node.low, tol, False, gap)[0]
        node.rotations = tuple(rotations_in(self.candles, lo, node.end,
                                            node.low, node.high))

    # ── the loop ────────────────────────────────────────────────────────────
    def on_candle(self, candle: Candle) -> Reading:
        self.candles.append(candle)
        i = self._i
        tol = self._tol()
        c = candle.c

        interaction = ""
        micro: MicroView | None = None

        # ── 1. what did this candle do to the structure we are standing in? ──
        if self.current is not None and self.current.live_status == STATUS_CONFIRMED:
            node = self.current
            node.interactions += 1
            # The boundary is the boundary. A close past it is a BREAK_ATTEMPT on that
            # candle, whatever happens next.
            #
            # The first version tested `contains(c, tol)`, so a close inside the
            # tolerance skirt was still reported as sitting at the edge. On 2026-02-16:
            #
            #     c807  price 60,511.8   C08 = 60,462-60,507
            #           AT_UPPER_EDGE / APPROACHING_UPPER
            #
            # Price was four points above the boundary and the map said it was
            # approaching it. The skirt was inherited from `mapper.py`, where there is no
            # separate two-close rule; here there is, and using both filters made the
            # attempt invisible. `break_closes` may delay **acceptance** — it must never
            # delay the attempt.
            if node.low <= c <= node.high:
                if node.closes_beyond:
                    node.returned_inside = True
                    interaction = "RE_ENTRY"
                    self._record("re_entry", node.id)
                node.closes_beyond, node._side = 0, ""
                node.end = i
                node.time_inside += 1
                self._refresh_evidence(node, tol)
                if not interaction:
                    near_hi = c >= node.high - tol
                    near_lo = c <= node.low + tol
                    interaction = ("AT_UPPER_EDGE" if near_hi else
                                   "AT_LOWER_EDGE" if near_lo else "INSIDE")
            else:
                side = "up" if c > node.high else "down"
                node.closes_beyond = node.closes_beyond + 1 if side == node._side else 1
                node._side = side
                excursion = (c - node.high) if side == "up" else (node.low - c)
                node.max_excursion = max(node.max_excursion, excursion)

                if node.closes_beyond < self.break_closes:
                    interaction = f"BREAK_ATTEMPT_{side.upper()}"
                else:
                    # Acceptance == the repo's existing two-close rule. Nothing new.
                    interaction = "ACCEPTED_ABOVE" if side == "up" else "ACCEPTED_BELOW"
                    node.broken_at, node.break_direction = i, side
                    node.live_status = CLOSED
                    # A revisited structure is already in history and already known.
                    # Finalising it again would create the duplicate this whole
                    # mechanism exists to prevent.
                    if not node.revisited:
                        frozen = node.finalise(atr_at(self.candles, i))
                        self.finalised.append(frozen)
                        self._known.append(frozen)
                    edge = node.high if side == "up" else node.low
                    self._record("break", node.id, side, edge)
                    # ...but a revisit is never finalised, so without this the whole
                    # visit — how long price stayed, how often it rotated, how many
                    # times it defended an edge — dies here. The snapshot must not be
                    # edited, so the evidence rides on an event in the frontier's own
                    # log instead, alongside the frozen map's untouched `break`.
                    if node.revisited:
                        self.live_log.append(LiveEvent(
                            "break", node.id, i, candle.close_time, side, edge,
                            "revisit ended", node.evidence))
                    self._from_id, self._from_dir = node.id, side
                    self._transit_since = i
                    self.left, self.current = node, None
                    self.state = LEAVING

            # ── the zoom: what happened INSIDE this structure? ───────────────
            #
            # Driven on every candle the node was current when the candle arrived —
            # including the one that broke it, which is precisely the candle whose inside
            # story is most worth having. `node` is still bound after `self.current` is
            # cleared, so `parent_ending` tells the observer its ground has gone: the
            # micro did not break, it lost its floor, and those are different endings.
            #
            # **Nothing below reads what comes back.** The view is carried to the Reading
            # and no further; if a micro count ever influences a major decision, the
            # story-equivalence gate is what catches it.
            micro = self.micro.observe(self.candles, i, node, tol,
                                       self._band_is_current,
                                       parent_ending=self.current is None)

        # ── 2. have we drifted clear of what we left? ───────────────────────
        #
        # Proximity is the departed structure's OWN width, not `tol`.
        #
        # The first version used `tol` and `LEAVING` was degenerate — it lasted zero
        # candles, every time. Acceptance already requires two closes beyond `band + tol`,
        # so by the moment it fires price is *by construction* outside `tol`, and
        # `LEAVING -> MOVING` fired on the same candle it was entered:
        #
        #     c119  22,480.0  CONFIRMED  BREAK_ATTEMPT_UP
        #     c120  22,484.7  MOVING     ACCEPTED_ABOVE      <- LEAVING never observed
        #
        # The box as its own ruler is the same scale-free measure the impulse rule and the
        # anchor layer use, and it makes the state mean something: for a 14-point shelf,
        # price is "still in its neighbourhood" until 14 points clear. That neighbourhood
        # is exactly where a retest happens.
        if self.state == LEAVING and self.left is not None:
            reach = self.left.width
            near = (self.left.low - reach) <= c <= (self.left.high + reach)
            if not near:
                self.state = MOVING
            if not interaction:
                interaction = "LEAVING"

        # ── 3. is something forming here? ───────────────────────────────────
        if self.current is None:
            # `session_aware` — the overnight jump is not movement.
            #
            # A 5m session is exactly 75 candles and `WINDOW_MAX` is 75, so **98.7% of
            # live windows straddle a boundary**. Left in, the gap is measured as a
            # perfect impulse and subtracted from every score: median `+0.03` inflation,
            # `+0.52` at worst, against a `min_score` of 0.35. This is the live mirror of
            # `structure.split_moves_at_sessions()` and it changes nothing else — a
            # structure may still span sessions, because a shelf built yesterday is the
            # same shelf today.
            cluster, rng = choose(self._window(), atr_at(self.candles, i),
                                  tol_atr=self.tol_atr, min_score=self.min_score,
                                  session_aware=True)
            firm = next((p for p in (rng, cluster) if p is not None
                         and self._is_current(p, tol)), None)
            known = self._known_match(firm) if firm is not None else None

            if known is not None and known.low - tol <= c <= known.high + tol:
                # A return, not a birth. Adoption needs price to be back **inside** it:
                # right after a break the band is still the freshest thing in the window,
                # and being near it is `LEAVING`, not a revisit.
                self.current = self._adopt(known)
                self.current.confirmed_at = i
                self.state = CONFIRMED
                interaction = "REVISIT"
                self._record("revisit", known.id)
                self.left = None
                self.candidate = None
            elif firm is not None and known is None:
                self.current = self._mint(firm, tol, STATUS_CONFIRMED)
                self.current.confirmed_at = i
                self._refresh_evidence(self.current, tol)
                self.state = CONFIRMED
                interaction = f"NEW_{firm.kind.upper()}"
                self.left = None
                self.candidate = None
            elif self.state != LEAVING:
                # `LEAVING` is not promoted to a candidate. The path is
                # LEAVING -> MOVING -> STRUCTURE_CANDIDATE, and price must first get
                # clear of what it left. Skipping the middle produced incoherent
                # output on real data — c866 read `state=STRUCTURE_CANDIDATE` while
                # `interaction=LEAVING`, two answers to the same question.
                loose = self._loose_candidate(tol)
                self.candidate = loose
                if loose is not None:
                    self.state = STRUCTURE_CANDIDATE
                    if not interaction:
                        interaction = "FORMING"
                else:
                    self.state = MOVING
                    if not interaction:
                        interaction = "MOVING"

        if not interaction:
            interaction = self.state

        # Every field is snapshotted here rather than read back off the frontier later:
        # `self.current` and `self.left` are the state at the END of a run, so an
        # interpreter walking the readings afterwards would describe every candle using
        # the last candle's structure.
        cur, lf = self.current, self.left
        reading = Reading(
            index=i, state=self.state, interaction=interaction,
            node_id=cur.id if cur else None,
            node_kind=cur.kind if cur else None,
            node_status=("HISTORICAL" if cur.revisited else "PROVISIONAL")
                        if cur else None,
            band=((cur.low, cur.high) if cur else None),
            break_level_up=cur.break_level_up if cur else None,
            break_level_down=cur.break_level_down if cur else None,
            left_id=lf.id if lf else None,
            left_edge=((lf.high if lf.break_direction == "up" else lf.low)
                       if lf else None),
            left_low=lf.low if lf else None,
            left_high=lf.high if lf else None,
            left_kind=lf.kind if lf else None,
            arrived_from=self._from_id if cur else None,
            arrived_direction=self._from_dir if cur else "",
            bars_in_transit=((cur.confirmed_at or i) - self._transit_since
                             if cur and self._transit_since is not None else 0),
            measurements=({"closes_beyond": float(self.current.closes_beyond),
                           "max_excursion": float(self.current.max_excursion)}
                          if self.current else {}),
            candidate=self.candidate,
            evidence=cur.evidence if cur else {},
            micro=micro)
        self.readings.append(reading)
        return reading

    def _loose_candidate(self, tol: Decimal) -> Proposal | None:
        """A band at *some* window, before the stability run has agreed.

        This is what makes `PROVISIONAL` a real stage rather than a formality: `choose()`
        needs three successive windows to concur, so a structure is visible here for a
        while before it is confirmed — *"provisional until the existing adaptive detector
        confirms it."*
        """
        window = self._window()
        atr = atr_at(self.candles, self._i)
        if atr <= ZERO:
            return None
        for n in WINDOWS[:6]:
            cluster, rng = read_window(window, n, atr, tol_atr=self.tol_atr,
                                       min_score=self.min_score, session_aware=True)
            for p in (rng, cluster):
                if (p is not None and self._is_current(p, tol)
                        and self._known_match(p) is None):
                    return p
        return None

    # ── what the caller asks ────────────────────────────────────────────────
    def trace(self) -> list[str]:
        base = len(self.candles) - len(self.readings)
        return [r.line(self.candles[base + k]) for k, r in enumerate(self.readings)]

    def history(self) -> tuple[Node, ...]:
        """Everything the frontier has finalised, ready to append to a rebuild."""
        return tuple(self.finalised)


def run(snapshot: MapSnapshot, history: Sequence[Candle],
        live: Sequence[Candle], **kw) -> Frontier:
    f = Frontier(snapshot, history, **kw)
    for c in live:
        f.on_candle(c)
    return f


__all__ = ["Frontier", "LiveNode", "Reading", "run", "CURRENCY_SLACK",
           "MOVING", "LEAVING", "STRUCTURE_CANDIDATE", "CONFIRMED",
           "PROVISIONAL", "STATUS_CONFIRMED", "HISTORICAL", "CLOSED",
           "LIVE_STATES", "MAP_STATUSES"]
