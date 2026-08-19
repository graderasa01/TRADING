"""
The micro observer — what price is doing **inside** the current structure.

```
M001   HISTORICAL MAP    immutable
F001   LIVE FRONTIER     the current structure                     frontier.py
       MICRO OBSERVER    what is happening inside it               this module
```

## The hole this fills

`Frontier`'s step 3 is gated on `if self.current is None`, so the detector runs only while
price belongs to nothing. The moment a structure confirms, the detector switches off and
every candle inside it reports `INSIDE` and nothing else — on real 5m Bank Nifty that is
the majority of all candles. The map could say *"price is in C21"* for forty candles
running and never once say what it did in there.

This module watches that span. It is a **zoom**, not a second opinion:

```
MAJOR STRUCTURE  ->  MICRO  ->  MICRO_BREAK      the zoom
MICRO_BREAK       X   MAJOR_BREAK                 never the same event
```

## Subordinate, and mechanically so

Four rules, none of them a matter of discipline:

```
1  a micro band NEVER enters Frontier._known     it would block a future major mint
2  a micro NEVER reaches finalised, log or live_log
3  a micro NEVER resizes, replaces or overrides its parent
4  a micro NEVER reaches MapState, and therefore never reaches the Trader Reader
```

Rule 4 holds because nothing here is imported by `interpreter.py`. Rules 1-3 hold because
this module has no reference to the frontier at all — it is handed candles, an index, a
parent and two callables, and it hands back one frozen view.

## Not a second detector

> *"It may invoke `adaptive.choose()` / `read_window()` and consume the resulting
> `Proposal` over a bounded sub-window inside the current confirmed structure... What it
> may not do is introduce a new clustering algorithm, a new score, a new threshold, or new
> admission logic."*

Every rule below is an existing one:

```
sub-window bound   the parent's own `window`         the box as its own ruler
span               parent.evidence_from .. i         A3's contiguous-observation start
candidate          adaptive.read_window()            _loose_candidate()'s shape
stability          adaptive.choose()                 the run of 3, untouched
currency           the frontier's own band test      "a band alone is not a location"
MICRO_BREAK        structure.BREAK_CLOSES            two closes, the same rule
MICRO_ROTATING     adaptive.MIN_TRAVERSES            the range detector's rotation gate
micro memory       snapshot.SAME_NODE_OVERLAP        the `_known` rule, scoped
```

**No new number is introduced anywhere in this module.**

## `choose()` returning a band is not confirmation

The detector was built for **major** admission. Reusing it is correct; inheriting its
verdict is not — same detector does not mean same interpretation. A band is a micro only
after the whole chain:

```
Proposal  ->  contained in the parent  ->  currency holds  ->  stability agreed  ->  CONFIRMED
```

A band as wide as its parent **is** the parent, seen again at a smaller window; a band
price is not standing in is a memory, not a location. Both are refused before the word
`CONFIRMED` is used.

## Two bands, deliberately named apart

```
low / high            the CONFIRMED band. Frozen at confirmation, never repainted.
                      This is what MICRO_BREAK is measured against.
span_low / span_high  running extremes of the observation span. Descriptive only.
```

`events.py` exists because *"a breakout candle widens the very box it is breaking, and the
break hides itself."* If a confirmed micro's high could rise with price, price could never
break it — it would merely extend it, and `MICRO_BREAK` would be undetectable by
construction. So `MICRO_HIGH_UPDATED` / `MICRO_LOW_UPDATED` describe a **`FORMING`**
band, which has not frozen yet and legitimately moves as the detector re-reads. After
`MICRO_CONFIRMED` neither event can ever fire again for that micro.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence

from src.boxes.adaptive import (
    MIN_TRAVERSES, STABILITY_RUN, WINDOWS, Proposal, choose, overlap, read_window)
from src.boxes.snapshot import SAME_NODE_OVERLAP
from src.boxes.structure import BREAK_CLOSES, atr_at, rotations_in
from src.domain.models import ZERO, Candle

# ── three closed vocabularies, and why they are three ────────────────────────
#
# A4 split `LiveNode.status` from `Reading.node_status` because one field was answering
# two different questions with the same words. The same care applies here, so the micro's
# *lifecycle*, what price is *doing*, and what just *happened* never share a namespace.
#
#     MICRO_STATES   where a micro is in ITS OWN life
#     MICRO_VIEWS    what price is doing inside the parent, micro or no micro
#     MICRO_EVENTS   the transitions, so Phase C can diff candles instead of re-deriving
#
# `MICRO_STATES` shares the string `CONFIRMED` with `frontier.LIVE_STATES`, and that is
# not the A4 mistake repeating: it is the same question — *has this structure passed
# admission?* — asked of two different objects. `MICRO_VIEWS` and `MICRO_EVENTS` are
# prefixed and disjoint from everything, because `MOVING` on this layer would mean
# "price is moving inside the box" while `frontier.MOVING` means "belonging to no
# structure at all". That one really is two questions sharing a word.
FORMING = "FORMING"
CONFIRMED = "CONFIRMED"
FINALIZED = "FINALIZED"
COLLAPSED = "COLLAPSED"
MICRO_STATES = frozenset({FORMING, CONFIRMED, FINALIZED, COLLAPSED})

MICRO_MOVING = "MICRO_MOVING"
MICRO_ROTATING = "MICRO_ROTATING"
MICRO_RANGE = "MICRO_RANGE"
MICRO_VIEWS = frozenset({MICRO_MOVING, MICRO_ROTATING, MICRO_RANGE})

MICRO_CREATED = "MICRO_CREATED"
MICRO_CONFIRMED = "MICRO_CONFIRMED"
MICRO_HIGH_UPDATED = "MICRO_HIGH_UPDATED"
MICRO_LOW_UPDATED = "MICRO_LOW_UPDATED"
MICRO_BREAK_UP = "MICRO_BREAK_UP"
MICRO_BREAK_DOWN = "MICRO_BREAK_DOWN"
MICRO_COLLAPSED = "MICRO_COLLAPSED"
MICRO_EVENTS = frozenset({MICRO_CREATED, MICRO_CONFIRMED, MICRO_HIGH_UPDATED,
                          MICRO_LOW_UPDATED, MICRO_BREAK_UP, MICRO_BREAK_DOWN,
                          MICRO_COLLAPSED})

#: What the observer needs from its parent. Written out because the parent is deliberately
#: **not** imported — `frontier.py` imports this module, and a type-only import back would
#: make the pair circular for the sake of a name.
#:
#:     id  low  high  width  window  evidence_from  rotations
_PARENT_FIELDS = ("id", "low", "high", "window", "evidence_from", "rotations")


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MicroStructure:
    """A structure forming inside another one. Mutable, like `LiveNode`, and split the
    same way: geometry freezes, evidence does not."""

    id: str                         # "C21.m1" — parent-qualified, never a map id
    parent_id: str
    parent_low: Decimal
    parent_high: Decimal
    #: FROZEN AT CONFIRMATION. While `FORMING` these move as the detector re-reads, which
    #: is what `MICRO_HIGH_UPDATED` / `MICRO_LOW_UPDATED` report. Once `CONFIRMED` they
    #: are never assigned again — see the module docstring.
    low: Decimal
    high: Decimal
    start: int
    end: int
    kind: str = "cluster"           # cluster | range, straight off the Proposal
    state: str = FORMING
    window: int = 0
    score: float = 0.0
    confirmed_at: int | None = None
    #: Rotations inside the MICRO's own band. The parent's own rotations are a different
    #: number over a different band and live on the parent.
    rotations: tuple[tuple[str, int, int, Decimal], ...] = ()
    time_inside: int = 0
    # break bookkeeping — measurements, not gates
    closes_beyond: int = 0
    broken_at: int | None = None
    break_direction: str = ""
    _side: str = ""

    def __post_init__(self) -> None:
        if self.state not in MICRO_STATES:
            raise ValueError(
                f"unknown micro state {self.state!r}. Add it to MICRO_STATES first — an "
                f"ad-hoc state makes the lifecycle unanalysable, the same reason "
                f"`EVENT_KINDS` and `STATUS_VOCABULARY` are closed.")

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def was_confirmed(self) -> bool:
        """Whether this micro was ever admitted. A micro that died while still `FORMING`
        was never a structure, so it is not something to remember — the same reason
        `Frontier._known` holds admitted structures and not candidates."""
        return self.confirmed_at is not None

    def contains(self, price: Decimal) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True, slots=True)
class MicroView:
    """One candle's answer from inside the current structure.

    The field list is chosen to feed Phase C's `DELTA_FROM_PREVIOUS`
    (`price, micro_high, micro_low, position, above_space, micro_state`), so that layer
    reads differences off this rather than re-deriving state.
    """

    index: int
    view: str                        # MICRO_MOVING | MICRO_ROTATING | MICRO_RANGE
    parent_id: str
    parent_low: Decimal
    parent_high: Decimal
    #: The confirmed (or forming) micro, if there is one.
    micro_id: str | None = None
    micro_low: Decimal | None = None
    micro_high: Decimal | None = None
    micro_state: str | None = None
    micro_kind: str | None = None
    #: Running extremes of the observation span — the parent's current visit up to this
    #: candle. Always defined, never breakable, and not to be confused with the micro's
    #: own frozen band above.
    span_low: Decimal | None = None
    span_high: Decimal | None = None
    duration: int = 0                # candles since the micro was born
    #: Rotations inside the **parent's** band this visit, and the direction of the last
    #: one. Read off the parent's own A3 counter rather than recomputed.
    rotations: int = 0
    last_direction: str = ""
    position_in_current: Decimal | None = None
    #: Room to the parent's own edges. Both positive while price is inside; the one price
    #: has closed past goes negative.
    to_upper_edge: Decimal | None = None
    to_lower_edge: Decimal | None = None
    events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.view not in MICRO_VIEWS:
            raise ValueError(f"unknown micro view {self.view!r}")
        if self.micro_state is not None and self.micro_state not in MICRO_STATES:
            raise ValueError(f"unknown micro state {self.micro_state!r}")
        for e in self.events:
            if e not in MICRO_EVENTS:
                raise ValueError(f"unknown micro event {e!r}")

    def line(self) -> str:
        band = ("—" if self.micro_low is None else
                f"{float(self.micro_low):,.0f}-{float(self.micro_high):,.0f}")
        return (f"{self.view:<15} {self.micro_id or '—':<9} {band:<16} "
                f"{self.micro_state or '':<10} rot{self.rotations} "
                f"{' '.join(self.events)}").rstrip()


# ─────────────────────────────────────────────────────────────────────────────
class MicroObserver:
    """Driven once per candle, for as long as a structure is current.

    It holds **one** active micro. A micro cannot itself have a micro: nesting is a
    separate question and is not smuggled in here.
    """

    def __init__(self, *, tol_atr: Decimal = Decimal("0.25"), min_score: float = 0.35,
                 break_closes: int = BREAK_CLOSES) -> None:
        self.tol_atr = tol_atr
        self.min_score = min_score
        self.break_closes = break_closes
        #: Deliberately two names, never one list filtered by state. *"Which one is live
        #: right now?"* must be answerable at a glance, not by scanning states.
        self.active: MicroStructure | None = None
        self.micro_history: list[MicroStructure] = []
        self._parent_id: str | None = None
        self._n = 0
        #: The micro **this candle was about**, which is not always the active one: the
        #: candle a micro breaks or collapses on is the candle it stops being active, and
        #: reporting `None` there would hide the band that just broke behind the event
        #: saying it broke.
        self._subject: MicroStructure | None = None

    # ── the rules, each one borrowed ────────────────────────────────────────
    def _windows(self, parent, span_len: int) -> list[int]:
        """Bounded by the parent's own window — the box as its own ruler, the same
        scale-free measure `LEAVING` uses via `left.width`.

        Fewer than `STABILITY_RUN` of them means `choose()` cannot agree with itself and
        no micro can ever confirm under this parent. That is a fact about a narrow parent,
        not a threshold.
        """
        return [n for n in WINDOWS if n < parent.window and n <= span_len]

    def _contained(self, p: Proposal, parent, tol: Decimal) -> bool:
        """Inside the parent, and strictly narrower than it.

        Without the width test a band that simply **is** the parent, re-found at a smaller
        window, would be admitted as a structure inside itself. `tol` on the edges is the
        repo's own tolerance: `core_band` is built from highs and lows, so a legitimate
        micro sitting on the parent's edge can poke a fraction beyond it.
        """
        return (parent.low - tol <= p.low and p.high <= parent.high + tol
                and p.width < parent.width)

    def _seen(self, p: Proposal) -> bool:
        """The `_known` rule, scoped to this parent's life.

        11 of 37 finalised live nodes were once a shelf the frontier had already
        finalised, re-minted under a new id — the *"ek shelf, chaar boxes"* failure. It
        will happen faster at micro scale, because micro bands are smaller and more
        numerous, so the same overlap test guards it.

        Only micros that were **admitted** count. One that died while still `FORMING` was
        never a structure, so there is nothing to have seen again.
        """
        return any(m.was_confirmed
                   and overlap((m.low, m.high), (p.low, p.high)) >= SAME_NODE_OVERLAP
                   for m in self.micro_history)

    def _admissible(self, p: Proposal | None, parent, tol: Decimal,
                    band_is_current: Callable[[Decimal, Decimal, Decimal], bool]) -> bool:
        """The chain, in order, and no step of it is a number invented here."""
        return (p is not None
                and self._contained(p, parent, tol)
                and band_is_current(p.low, p.high, tol)
                and not self._seen(p))

    # ── detection: the two existing entry points, over a bounded sub-window ──
    def _stable(self, span: Sequence[Candle], windows: list[int], atr: Decimal,
                parent, tol: Decimal, band_is_current) -> Proposal | None:
        """`choose()`'s stability run, untouched, over the sub-window."""
        if len(windows) < STABILITY_RUN:
            return None
        cluster, rng = choose(span, atr, windows=windows, tol_atr=self.tol_atr,
                              min_score=self.min_score, session_aware=True)
        return next((p for p in (rng, cluster)
                     if self._admissible(p, parent, tol, band_is_current)), None)

    def _loose(self, span: Sequence[Candle], windows: list[int], atr: Decimal,
               parent, tol: Decimal, band_is_current) -> Proposal | None:
        """A band at *some* micro window, before the stability run has agreed —
        `_loose_candidate()`'s shape, at a smaller scale."""
        for n in windows:
            cluster, rng = read_window(span, n, atr, tol_atr=self.tol_atr,
                                       min_score=self.min_score, session_aware=True)
            for p in (rng, cluster):
                if self._admissible(p, parent, tol, band_is_current):
                    return p
        return None

    # ── lifecycle bookkeeping ───────────────────────────────────────────────
    def _retire(self, m: MicroStructure) -> None:
        self.micro_history.append(m)
        self._subject = m
        if self.active is m:
            self.active = None

    def _collapse(self, m: MicroStructure, i: int, events: list[str]) -> None:
        m.state, m.end = COLLAPSED, i
        events.append(MICRO_COLLAPSED)
        self._retire(m)

    def _new_parent(self, parent_id: str, i: int, events: list[str]) -> None:
        """A different structure is current, so the previous parent's whole micro story is
        over — including its memory. A5 measured what unbounded memory costs on the major
        layer: adopted bands run to a median age of 156 candles, and 64% of blocked
        proposals are stopped by bands the frontier built itself. Scoping micro memory to
        the parent's life makes that failure mode unreachable without inventing an age
        policy nobody has measured."""
        if self.active is not None:
            self._collapse(self.active, i, events)
        self.micro_history.clear()
        self._parent_id = parent_id
        self._n = 0

    # ── the loop ────────────────────────────────────────────────────────────
    def observe(self, candles: Sequence[Candle], i: int, parent, tol: Decimal,
                band_is_current: Callable[[Decimal, Decimal, Decimal], bool], *,
                parent_ending: bool = False) -> MicroView:
        """One candle, inside `parent`. Returns what was seen; changes nothing outside.

        `band_is_current` is the frontier's own currency test, passed in rather than
        reimplemented, so *"price is actually here"* means the same thing on both layers.
        """
        events: list[str] = []
        if parent.id != self._parent_id:
            self._new_parent(parent.id, i, events)
        # After the parent check, so a micro belonging to the PREVIOUS parent is never
        # described under this one.
        self._subject = None

        price = candles[i].c

        if parent_ending:
            # The parent broke on this candle. Its micro did not break — its ground
            # disappeared, which is a different ending and is recorded as one.
            if self.active is not None:
                self._collapse(self.active, i, events)
            self.micro_history.clear()
            self._parent_id = None
            return self._view(candles, i, parent, price, events)

        m = self.active
        if m is not None:
            m.end = i
            if m.state == CONFIRMED:
                self._drive(m, candles, i, price, events)
            else:
                self._grow(m, candles, i, parent, tol, band_is_current, events)

        if self.active is None:
            self._look(candles, i, parent, tol, band_is_current, events)

        return self._view(candles, i, parent, price, events)

    def _drive(self, m: MicroStructure, candles: Sequence[Candle], i: int,
               price: Decimal, events: list[str]) -> None:
        """A confirmed micro, against **its own** edges. `BREAK_CLOSES`, the same two
        closes the major layer uses, because one wick is not a break at any scale."""
        if m.contains(price):
            m.closes_beyond, m._side = 0, ""
            m.time_inside += 1
            m.rotations = tuple(rotations_in(candles, m.start, i, m.low, m.high))
            return

        side = "up" if price > m.high else "down"
        m.closes_beyond = m.closes_beyond + 1 if side == m._side else 1
        m._side = side
        if m.closes_beyond >= self.break_closes:
            m.state, m.broken_at, m.break_direction = FINALIZED, i, side
            events.append(MICRO_BREAK_UP if side == "up" else MICRO_BREAK_DOWN)
            self._retire(m)

    def _grow(self, m: MicroStructure, candles: Sequence[Candle], i: int, parent,
              tol: Decimal, band_is_current, events: list[str]) -> None:
        """A forming micro: the band is not frozen yet, so it may move, confirm or die."""
        span = candles[parent.evidence_from:i + 1]
        windows = self._windows(parent, len(span))
        atr = atr_at(candles, i)
        if atr <= ZERO or not windows:
            self._collapse(m, i, events)
            return

        firm = self._stable(span, windows, atr, parent, tol, band_is_current)
        if firm is not None:
            self._freeze(m, firm, i, events)
            return

        loose = self._loose(span, windows, atr, parent, tol, band_is_current)
        if loose is None:
            self._collapse(m, i, events)
            return
        if loose.high != m.high:
            m.high = loose.high
            events.append(MICRO_HIGH_UPDATED)
        if loose.low != m.low:
            m.low = loose.low
            events.append(MICRO_LOW_UPDATED)
        m.window, m.score, m.kind = loose.window, loose.score, loose.kind

    def _freeze(self, m: MicroStructure, p: Proposal, i: int,
                events: list[str]) -> None:
        """Admission. After this the band is geometry and never moves again."""
        m.low, m.high = p.low, p.high
        m.window, m.score, m.kind = p.window, p.score, p.kind
        m.state, m.confirmed_at = CONFIRMED, i
        events.append(MICRO_CONFIRMED)

    def _look(self, candles: Sequence[Candle], i: int, parent, tol: Decimal,
              band_is_current, events: list[str]) -> None:
        """Nothing active. Try stability first, exactly as `Frontier` step 3 does — a band
        the run of three already agrees on does not need a candle of `FORMING` to prove
        itself."""
        span = candles[parent.evidence_from:i + 1]
        windows = self._windows(parent, len(span))
        atr = atr_at(candles, i)
        if atr <= ZERO or not windows:
            return

        firm = self._stable(span, windows, atr, parent, tol, band_is_current)
        p = firm or self._loose(span, windows, atr, parent, tol, band_is_current)
        if p is None:
            return

        self._n += 1
        m = MicroStructure(
            id=f"{parent.id}.m{self._n}", parent_id=parent.id,
            parent_low=parent.low, parent_high=parent.high,
            low=p.low, high=p.high, start=i, end=i, kind=p.kind,
            window=p.window, score=p.score)
        events.append(MICRO_CREATED)
        self.active = m
        if firm is not None:
            self._freeze(m, firm, i, events)

    # ── the view ────────────────────────────────────────────────────────────
    def _view(self, candles: Sequence[Candle], i: int, parent, price: Decimal,
              events: list[str]) -> MicroView:
        m = self.active or self._subject
        rots = tuple(parent.rotations)
        span = [k for k in candles[parent.evidence_from:i + 1] if not k.synthetic]

        # MICRO_RANGE means a structure, never merely motion. Rotation alone is
        # MICRO_ROTATING: price moving back and forth is not a smaller box until an
        # actual smaller box has passed the whole admission chain.
        if m is not None and m.state == CONFIRMED:
            view = MICRO_RANGE
        elif len(rots) >= MIN_TRAVERSES:
            view = MICRO_ROTATING
        else:
            view = MICRO_MOVING

        width = parent.high - parent.low
        return MicroView(
            index=i, view=view, parent_id=parent.id,
            parent_low=parent.low, parent_high=parent.high,
            micro_id=m.id if m else None,
            micro_low=m.low if m else None,
            micro_high=m.high if m else None,
            micro_state=m.state if m else None,
            micro_kind=m.kind if m else None,
            span_low=min((k.l for k in span), default=None),
            span_high=max((k.h for k in span), default=None),
            duration=(i - m.start + 1) if m else 0,
            rotations=len(rots),
            last_direction=rots[-1][0] if rots else "",
            position_in_current=((price - parent.low) / width) if width > ZERO else None,
            to_upper_edge=parent.high - price,
            to_lower_edge=price - parent.low,
            events=tuple(events))


__all__ = ["FORMING", "CONFIRMED", "FINALIZED", "COLLAPSED", "MICRO_STATES",
           "MICRO_MOVING", "MICRO_ROTATING", "MICRO_RANGE", "MICRO_VIEWS",
           "MICRO_CREATED", "MICRO_CONFIRMED", "MICRO_HIGH_UPDATED",
           "MICRO_LOW_UPDATED", "MICRO_BREAK_UP", "MICRO_BREAK_DOWN",
           "MICRO_COLLAPSED", "MICRO_EVENTS", "MicroStructure", "MicroView",
           "MicroObserver"]
