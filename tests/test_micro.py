"""
The micro observer — `src/boxes/micro.py`.

`Frontier`'s step 3 is gated on `if self.current is None`, so for as long as price belongs
to a structure the detector is switched off and every candle reports `INSIDE`. This layer
watches that span. It is a **zoom**, and the tests are mostly attempts to prove it is only
that:

```
MAJOR STRUCTURE  ->  MICRO  ->  MICRO_BREAK      the zoom
MICRO_BREAK       X   MAJOR_BREAK                 never the same event
```

Four locks were attached to this layer's approval and each has a test named for it:

```
L1  the span never reaches before the parent's CURRENT visit
L2  MICRO_RANGE requires a structure; rotation alone is MICRO_ROTATING
L3  choose() returning a band is not confirmation
L4  the same candles replay to the same micro story
```
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

import pytest

from src.boxes.adaptive import MIN_TRAVERSES, WINDOWS, Proposal
from src.boxes.micro import (
    COLLAPSED, CONFIRMED, FINALIZED, FORMING, MICRO_CONFIRMED, MICRO_CREATED,
    MICRO_EVENTS, MICRO_HIGH_UPDATED, MICRO_LOW_UPDATED, MICRO_MOVING, MICRO_RANGE,
    MICRO_ROTATING, MICRO_STATES, MICRO_VIEWS, MicroObserver, MicroStructure, MicroView)
from src.boxes.frontier import LIVE_STATES, MAP_STATUSES
from src.livemap.interpreter import Interpreter, MapState
from tests.test_frontier_evidence import SHAPES, frontier_for, ramp, sit

TOL = Decimal("5")


def zig(lo: float, hi: float, leg: int, n: int):
    """A wide band price crosses hard, with no rest at either end.

    This exists because **every `sit()` shelf confirms at window 8** — `choose()` returns
    the smallest stable window, and a tight rest is stable immediately. A parent with
    `window == 8` has no smaller window left to look inside it, so it can never hold a
    micro, and a fixture built from `sit()` alone would test the observer against nothing.
    A hard zigzag is unreadable at 8-12 candles (it is pure migration there) and resolves
    only as a wide range, which is the parent this layer needs.
    """
    out: list[float] = []
    for k in range(n):
        out += ramp(lo, hi, leg) if k % 2 == 0 else ramp(hi, lo, leg)
    return out


#: Three endings of the same story: a wide frozen range, revisited, with a tight shelf
#: forming inside it. No one shape reaches every state, so there are three.
#:
#:     HELD    the micro confirms and is still standing at the end
#:     BROKE   the micro breaks ITS OWN edge while the parent holds       -> FINALIZED
#:     ENDED   price leaps clear of the parent, taking the live micro with it -> COLLAPSED
#:
#: `ENDED` leaps rather than ramps on purpose: a micro is inside its parent, so a gradual
#: exit breaks the micro's edge first and there is no live micro left for the parent's
#: break to collapse. Only a move fast enough to clear both inside `BREAK_CLOSES` puts a
#: confirmed micro and a parent break on the same candle.
WIDE_HELD = zig(22400, 22600, 15, 7) + sit(22500, 60, 12)
WIDE_BROKE = zig(22400, 22600, 15, 7) + sit(22500, 45, 12) + ramp(22512, 22560, 12)
WIDE_ENDED = zig(22400, 22600, 15, 7) + sit(22500, 45, 12) + [22700, 22760, 22820]


@pytest.fixture
def wide():
    return frontier_for(WIDE_BROKE)


@pytest.fixture
def held():
    return frontier_for(WIDE_HELD)


@pytest.fixture
def ended():
    return frontier_for(WIDE_ENDED)


#: Every shape this module runs the whole-suite invariants over: the frontier's own five,
#: plus the three wide-parent endings. The invariants that must hold everywhere are
#: parametrized across all eight rather than checked on one convenient fixture.
SHAPE_OR_WIDE = dict(SHAPES, held=WIDE_HELD, broke=WIDE_BROKE, ended=WIDE_ENDED)


def micros(f):
    return [r for r in f.readings if r.micro is not None]


def events_of(f, kind):
    return [r for r in f.readings if r.micro and kind in r.micro.events]


# ─────────────────────────────────────────────────────────────────────────────
# a stub parent, so the observer can be driven without a frontier
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class StubParent:
    """Only the six attributes `micro.py` documents itself as needing."""

    id: str = "P01"
    low: Decimal = Decimal("22400")
    high: Decimal = Decimal("22600")
    window: int = 40
    evidence_from: int = 0
    rotations: tuple = ()

    @property
    def width(self) -> Decimal:
        return self.high - self.low


def proposal(low: float, high: float, window: int = 12) -> Proposal:
    return Proposal("cluster", Decimal(str(low)), Decimal(str(high)), window, 0.5, 0.1)


def always_current(low, high, tol) -> bool:
    return True


def never_current(low, high, tol) -> bool:
    return False


# ─────────────────────────────────────────────────────────────────────────────
# the vocabularies
# ─────────────────────────────────────────────────────────────────────────────
def test_the_vocabularies_are_closed():
    assert MICRO_STATES == {FORMING, CONFIRMED, FINALIZED, COLLAPSED}
    assert MICRO_VIEWS == {MICRO_MOVING, MICRO_ROTATING, MICRO_RANGE}
    with pytest.raises(ValueError):
        MicroStructure(id="P01.m1", parent_id="P01", parent_low=Decimal(1),
                       parent_high=Decimal(2), low=Decimal(1), high=Decimal(2),
                       start=0, end=0, state="DRIFTING")


def test_the_micro_views_never_collide_with_the_frontiers_words():
    """A4 split two vocabularies that were sharing words while asking different questions.
    `MOVING` on this layer would mean *"price is moving inside the box"* while
    `frontier.MOVING` means *"belonging to no structure at all"* — the same trap."""
    from src.boxes import frontier as F
    frontier_words = {F.MOVING, F.LEAVING, F.STRUCTURE_CANDIDATE, F.CONFIRMED, F.CLOSED}
    assert not (MICRO_VIEWS & frontier_words)
    assert not (MICRO_EVENTS & frontier_words)


def test_confirmed_is_shared_on_purpose_and_nothing_else_is():
    """`MICRO_STATES` and `LIVE_STATES` both contain `CONFIRMED`, and that is one question
    — *has this structure passed admission?* — asked of two different objects. Every other
    member must be distinct, or the A4 confusion is back."""
    assert MICRO_STATES & LIVE_STATES == {CONFIRMED}
    assert not MICRO_STATES & (MAP_STATUSES - {CONFIRMED})
    assert not MICRO_VIEWS & LIVE_STATES
    assert not MICRO_VIEWS & MAP_STATUSES


def test_a_view_refuses_an_unknown_event():
    with pytest.raises(ValueError):
        MicroView(index=0, view=MICRO_MOVING, parent_id="P01",
                  parent_low=Decimal(1), parent_high=Decimal(2), events=("MICRO_JUMPED",))


# ─────────────────────────────────────────────────────────────────────────────
# L3 — choose() returning a band is not confirmation
# ─────────────────────────────────────────────────────────────────────────────
def test_l3_a_band_as_wide_as_its_parent_is_the_parent():
    """Without the width test, a band that simply **is** the parent — re-found at a
    smaller window — would be admitted as a structure inside itself."""
    obs = MicroObserver()
    parent = StubParent()
    assert not obs._contained(proposal(22400, 22600), parent, TOL)
    assert not obs._contained(proposal(22390, 22610), parent, TOL)
    assert obs._contained(proposal(22480, 22520), parent, TOL)


def test_l3_a_band_outside_the_parent_is_refused():
    obs = MicroObserver()
    parent = StubParent()
    assert not obs._contained(proposal(22300, 22380), parent, TOL)
    assert not obs._contained(proposal(22550, 22700), parent, TOL)


def test_l3_a_band_price_is_not_standing_in_is_refused():
    """Currency is a separate question from geometry. *"choose() returning a band does NOT
    mean price is there"* — the same rule the frontier applies to a major proposal."""
    obs = MicroObserver()
    parent = StubParent()
    p = proposal(22480, 22520)
    assert obs._admissible(p, parent, TOL, always_current)
    assert not obs._admissible(p, parent, TOL, never_current)


def test_l3_the_chain_refuses_at_every_link():
    obs = MicroObserver()
    parent = StubParent()
    assert not obs._admissible(None, parent, TOL, always_current)
    assert not obs._admissible(proposal(22400, 22600), parent, TOL, always_current)
    assert not obs._admissible(proposal(22480, 22520), parent, TOL, never_current)
    assert obs._admissible(proposal(22480, 22520), parent, TOL, always_current)


def test_l3_a_confirmed_micro_is_not_minted_twice_under_one_parent():
    """The `_known` rule, scoped. 11 of 37 finalised live nodes were once a shelf the
    frontier had already finalised, re-minted under a new id; micro bands are smaller and
    more numerous, so it would happen faster here."""
    obs = MicroObserver()
    m = MicroStructure(id="P01.m1", parent_id="P01", parent_low=Decimal("22400"),
                       parent_high=Decimal("22600"), low=Decimal("22480"),
                       high=Decimal("22520"), start=0, end=5, state=FINALIZED,
                       confirmed_at=2)
    obs.micro_history.append(m)
    assert obs._seen(proposal(22482, 22518))
    assert not obs._seen(proposal(22560, 22580))


def test_a_micro_that_never_confirmed_is_not_remembered():
    """One that died while still `FORMING` was never a structure, so there is nothing to
    have seen again — the same reason `_known` holds admitted structures, not candidates."""
    obs = MicroObserver()
    obs.micro_history.append(MicroStructure(
        id="P01.m1", parent_id="P01", parent_low=Decimal("22400"),
        parent_high=Decimal("22600"), low=Decimal("22480"), high=Decimal("22520"),
        start=0, end=5, state=COLLAPSED))
    assert not obs._seen(proposal(22482, 22518))


def test_the_micro_windows_are_bounded_by_the_parents_own(held):
    """The box as its own ruler, the same scale-free measure `LEAVING` uses via
    `left.width`. A parent found at window 8 has nothing smaller to look inside it."""
    obs = MicroObserver()
    assert obs._windows(StubParent(window=8), 100) == []
    assert obs._windows(StubParent(window=15), 100) == [8, 10, 12]
    assert obs._windows(StubParent(window=40), 100) == [w for w in WINDOWS if w < 40]
    # and the span bounds it too — 20 candles cannot be read at 27
    assert obs._windows(StubParent(window=40), 20) == [8, 10, 12, 15, 18]


# ─────────────────────────────────────────────────────────────────────────────
# L2 — MICRO_RANGE means a structure, not motion
# ─────────────────────────────────────────────────────────────────────────────
def test_l2_rotation_alone_never_becomes_micro_range(wide, held):
    for f in (wide, held):
        for r in micros(f):
            if r.micro.view == MICRO_RANGE:
                assert r.micro.micro_state == CONFIRMED, (
                    f"c{r.index}: MICRO_RANGE with micro_state="
                    f"{r.micro.micro_state!r} — price moving back and forth is not a "
                    f"smaller box")


def test_l2_a_rotating_parent_without_a_micro_reads_micro_rotating():
    """Drawn from the frontier's own fixture shapes, where price crosses its parent's
    thirds repeatedly and no smaller structure ever confirms — the exact case that must
    not be dressed up as `MICRO_RANGE`."""
    rotating = [r for closes in SHAPES.values() for r in micros(frontier_for(closes))
                if r.micro.view == MICRO_ROTATING]
    assert rotating, "no candle ever rotated inside its parent"
    for r in rotating:
        assert r.micro.rotations >= MIN_TRAVERSES
        assert r.micro.micro_state != CONFIRMED, (
            f"c{r.index}: a confirmed micro must read MICRO_RANGE, not MICRO_ROTATING")


def test_l2_a_confirmed_micro_reads_micro_range(wide):
    ranged = [r for r in micros(wide) if r.micro.view == MICRO_RANGE]
    assert ranged, "the fixture never confirmed a micro"
    for r in ranged:
        assert r.micro.micro_id is not None
        assert r.micro.micro_low is not None and r.micro.micro_high is not None


def test_micro_moving_is_the_absence_of_the_other_two(wide, held, ended):
    for f in (wide, held, ended):
        for r in micros(f):
            if r.micro.view == MICRO_MOVING:
                assert r.micro.rotations < MIN_TRAVERSES
                assert r.micro.micro_state != CONFIRMED


# ─────────────────────────────────────────────────────────────────────────────
# L1 — the span is the parent's current visit
# ─────────────────────────────────────────────────────────────────────────────
def test_l1_an_adopted_parents_evidence_starts_at_the_revisit(wide):
    revisit = [r for r in wide.readings if r.interaction == "REVISIT"]
    assert revisit, "the fixture never revisited anything"
    node = wide.current or wide.left
    assert node is not None and node.revisited
    assert node.evidence_from == revisit[-1].index
    assert node.evidence_from > node.start


def test_l1_the_span_never_reaches_before_the_parents_current_visit(wide):
    """A micro built from candles before the visit would be a structure assembled out of a
    period price was somewhere else entirely. `span_low`/`span_high` are read straight off
    that span, so recomputing them from the revisit candle proves the boundary held."""
    revisit = [r.index for r in wide.readings if r.interaction == "REVISIT"]
    assert revisit
    start = revisit[-1]
    checked = 0
    for r in micros(wide):
        if r.index < start or r.micro.span_low is None:
            continue
        real = [k for k in wide.candles[start:r.index + 1] if not k.synthetic]
        assert r.micro.span_low == min(k.l for k in real), f"c{r.index}: span reached back"
        assert r.micro.span_high == max(k.h for k in real)
        checked += 1
    assert checked > 5, f"only {checked} candles were checked — the assertion barely ran"


# ─────────────────────────────────────────────────────────────────────────────
# L4 — determinism
# ─────────────────────────────────────────────────────────────────────────────
def story(f) -> list:
    return [(r.index, r.micro.view, r.micro.micro_id, r.micro.micro_state,
             r.micro.micro_low, r.micro.micro_high, r.micro.duration,
             r.micro.rotations, r.micro.events)
            for r in f.readings if r.micro is not None]


@pytest.mark.parametrize("name", list(SHAPES) + ["held", "broke", "ended"])
def test_l4_micro_replay_is_deterministic(name):
    closes = SHAPE_OR_WIDE[name]
    assert story(frontier_for(closes)) == story(frontier_for(closes)), (
        f"{name}: two runs over the same candles told different micro stories")


# ─────────────────────────────────────────────────────────────────────────────
# the lifecycle
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(SHAPES) + ["held", "broke", "ended"])
def test_the_observer_runs_exactly_while_a_structure_is_current(name):
    """A structure is current when a candle **arrives** exactly when the previous reading
    reported one, because `self.current` at the end of candle k-1 is that reading's
    `node_id`. Stated that way it also covers the two edge candles: a node born in step 3
    has no inside yet, and a node broken in step 1 does — the candle it broke on is the
    candle its inside story is most worth having.
    """
    closes = {"held": WIDE_HELD, "broke": WIDE_BROKE,
              "ended": WIDE_ENDED}.get(name) or SHAPES[name]
    f = frontier_for(closes)
    previous = None
    for r in f.readings:
        assert (r.micro is not None) == (previous is not None), (
            f"c{r.index}: previous node {previous!r}, interaction={r.interaction}, "
            f"micro={'set' if r.micro else 'None'}")
        previous = r.node_id


def test_a_confirmed_micro_band_is_never_repainted(wide, held):
    """The one thing this layer must not do. If a confirmed micro's high could rise with
    price, price could never break it — it would merely extend it, and `MICRO_BREAK` would
    be undetectable by construction."""
    for f in (wide, held):
        first: dict[str, tuple] = {}
        for r in micros(f):
            m = r.micro
            if m.micro_id is None or m.micro_state != CONFIRMED:
                continue
            band = (m.micro_low, m.micro_high)
            first.setdefault(m.micro_id, band)
            assert band == first[m.micro_id], (
                f"c{r.index}: {m.micro_id} was repainted from {first[m.micro_id]} "
                f"to {band}")


def test_the_band_only_moves_while_it_is_forming(wide, held):
    for f in (wide, held):
        confirmed_at: dict[str, int] = {}
        for r in micros(f):
            m = r.micro
            if m.micro_id is None:
                continue
            if MICRO_CONFIRMED in m.events:
                confirmed_at[m.micro_id] = r.index
            moved = {MICRO_HIGH_UPDATED, MICRO_LOW_UPDATED} & set(m.events)
            if moved:
                assert m.micro_id not in confirmed_at, (
                    f"c{r.index}: {sorted(moved)} after {m.micro_id} was confirmed")
                assert m.micro_state == FORMING


def test_a_micro_is_created_before_it_is_confirmed(wide, held):
    for f in (wide, held):
        for r in micros(f):
            if MICRO_CONFIRMED in r.micro.events:
                assert (MICRO_CREATED in r.micro.events
                        or any(x.micro and x.micro.micro_id == r.micro.micro_id
                               and MICRO_CREATED in x.micro.events
                               for x in f.readings[:r.index]))


def test_a_micro_that_breaks_its_own_edge_is_finalized(wide):
    broke = events_of(wide, "MICRO_BREAK_UP") + events_of(wide, "MICRO_BREAK_DOWN")
    assert broke, "the fixture never broke a micro"
    for r in broke:
        assert r.micro.micro_state == FINALIZED, (
            f"c{r.index}: broke its own edge but reports {r.micro.micro_state!r}")
        # the band that broke is still reported ON the candle it broke — hiding it behind
        # the event announcing it would leave the break with no level
        assert r.micro.micro_low is not None and r.micro.micro_high is not None


def test_a_micro_whose_parent_ends_collapses_rather_than_breaks(ended):
    """Its ground disappeared. That is a different ending from breaking its own edge, and
    collapsing the two would make *"the micro broke"* and *"the micro evaporated"*
    indistinguishable.

    The parent's break is processed first, so a candle that clears both is the parent's
    break and the micro's collapse — never a second breakout.
    """
    accepted = [r for r in ended.readings
                if r.interaction in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"}]
    assert accepted, "the fixture's parent never broke"
    collapsed = [r for r in accepted if "MICRO_COLLAPSED" in (r.micro.events if r.micro
                                                              else ())]
    assert collapsed, "no live micro was standing when its parent broke"
    for r in collapsed:
        assert r.micro.micro_state == COLLAPSED
        assert "MICRO_BREAK_UP" not in r.micro.events
        assert "MICRO_BREAK_DOWN" not in r.micro.events


def test_micro_memory_dies_with_its_parent(ended):
    """A5 measured what unbounded memory costs on the major layer — adopted bands run to a
    median age of 156 candles, and 64% of blocked proposals are stopped by bands the
    frontier built itself. Scoping micro memory to the parent's life makes that
    unreachable here without inventing an age policy nobody has measured."""
    assert ended.left is not None, "the fixture's parent never ended"
    assert [r for r in ended.readings if r.micro and r.micro.micro_id], (
        "no micro was ever built, so there was no memory to clear")
    assert ended.micro.active is None
    assert ended.micro.micro_history == []


def test_every_micro_id_is_parent_qualified(wide, held):
    for f in (wide, held):
        for r in micros(f):
            if r.micro.micro_id is None:
                continue
            assert r.micro.micro_id.startswith(f"{r.micro.parent_id}.m"), (
                f"{r.micro.micro_id} could be mistaken for a map node id")


# ─────────────────────────────────────────────────────────────────────────────
# MICRO_BREAK is not MAJOR_BREAK
# ─────────────────────────────────────────────────────────────────────────────
def test_a_micro_break_leaves_the_parents_break_levels_alone(wide):
    """`parent 22400-22600, micro 22490-22510, price > 22510` is `MICRO_BREAK_UP` with the
    parent's `break_up` still `22600`. Rule 2 of the locked design, as arithmetic."""
    broke = events_of(wide, "MICRO_BREAK_UP") + events_of(wide, "MICRO_BREAK_DOWN")
    assert broke
    for r in broke:
        assert r.break_level_up == r.micro.parent_high
        assert r.break_level_down == r.micro.parent_low
        assert r.micro.micro_high < r.micro.parent_high
        assert r.micro.micro_low > r.micro.parent_low


def test_a_micro_break_is_not_an_interaction(wide):
    """The parent's own interaction vocabulary must not learn a micro word — a micro break
    reaching `ACCEPTED_ABOVE` is precisely the confusion this layer exists to avoid."""
    broke = events_of(wide, "MICRO_BREAK_UP") + events_of(wide, "MICRO_BREAK_DOWN")
    assert broke
    for r in broke:
        assert not r.interaction.startswith("ACCEPTED")
        assert "MICRO" not in r.interaction
        assert "MICRO" not in r.state


# ─────────────────────────────────────────────────────────────────────────────
# the four structural rules
# ─────────────────────────────────────────────────────────────────────────────
def all_micro_ids(f) -> set[str]:
    return ({r.micro.micro_id for r in micros(f) if r.micro.micro_id}
            | {m.id for m in f.micro.micro_history}
            | ({f.micro.active.id} if f.micro.active else set()))


@pytest.mark.parametrize("name", list(SHAPES) + ["held", "broke", "ended"])
def test_no_micro_ever_reaches_the_major_map(name):
    """Rules 1-3: a micro band in `_known` would block a future major mint; a micro in
    `finalised` would enter history as a structure; a micro in either log would make the
    live record unreadable."""
    f = frontier_for(SHAPE_OR_WIDE[name])
    ids = all_micro_ids(f)
    assert not ids & {n.id for n in f._known}
    assert not ids & {n.id for n in f.finalised}
    assert not ids & {e.node_id for e in f.log}
    assert not ids & {e.node_id for e in f.live_log}


def test_rule_four_the_map_state_has_no_micro_field(wide):
    """A micro must never reach the Trader Reader. It cannot, because it never reaches the
    layer the Trader Reader reads."""
    names = {fl.name for fl in fields(MapState)}
    assert not any("micro" in n for n in names), sorted(names)
    states = Interpreter(wide.snapshot, wide).states()
    assert states
    for s in states:
        assert "MICRO" not in " ".join(s.lines()).upper()


def test_rule_four_the_trader_reader_cannot_see_a_micro():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src" / "livemap" / "trader.py"
    assert "micro" not in src.read_text(encoding="utf-8").lower()


# ─────────────────────────────────────────────────────────────────────────────
# the view agrees with the layer above it
# ─────────────────────────────────────────────────────────────────────────────
def test_position_in_current_agrees_with_the_interpreter(wide):
    """The frontier owns price and the parent band, so this is a live fact and Phase C
    needs it without an Interpreter. Pinned to the Interpreter's own answer so the two
    cannot drift into two different definitions of the same number."""
    states = {s.index: s for s in Interpreter(wide.snapshot, wide).states()}
    checked = 0
    for r in micros(wide):
        s = states[r.index]
        if s.current is None or s.current.position is None:
            continue
        assert r.micro.position_in_current == s.current.position, f"c{r.index}"
        checked += 1
    assert checked > 20, f"only {checked} candles compared"


def test_the_edges_are_the_parents_own(wide):
    for r in micros(wide):
        price = wide.candles[r.index].c
        assert r.micro.to_upper_edge == r.micro.parent_high - price
        assert r.micro.to_lower_edge == price - r.micro.parent_low
