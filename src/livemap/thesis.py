"""
thesis.py — the LIVE THESIS. Design demonstration on real Bank Nifty 5m.

**Observation only. No orders, no sizing, no broker, no entry logic, no threshold, no
score, no new detector.** Promoted from the research scratchpad after validation; this file
is now the canonical LiveThesis and the scratchpad copy is superseded reference material.
Future fixes belong here, so the research and production paths cannot diverge.

One thesis per closed candle, rebuilt from scratch each time out of facts the stack
already publishes.

## The correction this version exists for

The first draft inferred a direction before any structural event: it read
`position_in_current >= 0.5` and decided price was heading for the upper edge. **That is
wrong.** Before a break, position is *location*, not direction. So:

```
LOCATION    position_in_current, distance to BOTH edges, which third   -- no direction
MOVEMENT    Eye deltas, edge pressure on BOTH sides, approach counts on BOTH sides,
            micro last_direction                                        -- no direction
IDEA        only from a structural event the stack already recorded (an accepted break,
            read through the episode's CURRENT state). Otherwise NO_IDEA / UNRESOLVED.
```

## Facts and interpretation are different things

`location_facts` and `movement_facts` are **neutral named observations**, copied and never
editorial: *"spent its time in the upper third"*, not *"heading up"*. `supporting` /
`conflicting` carry only relationships that are **definitional** to the stated thesis —
*"the broken edge has never been closed back through"* supports *"the break holds"* by
definition, not by opinion.

Nothing encodes `spent_far = bullish`. The one measured relationship the studies found —
where price spent its pre-break time — is reported as a **fact**, never as evidence for a
direction: its effect was on path completion, it was 6-12 points, and it is not a rule.

## Causality

Every field is computed from the current candle and earlier. `DURABILITY` is decided from
what has **already** happened — never from a future non-retest, a future outcome, or a
future excursion. `test_thesis.py` pins this with a prefix-causality test.

## No score, ever

No total, no probability, no confidence. `TRUST` is `UNRESOLVED` and `__post_init__`
refuses anything else until a calibration study exists.
"""
from __future__ import annotations

import statistics as S
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.boxes.adaptive import MIN_TOUCHES, STABILITY_RUN, WINDOWS
from src.boxes.frontier import Frontier
from src.boxes.snapshot import MapSnapshot
from src.livemap.eye import observe as eye_observe
from src.livemap.interpreter import Interpreter
from src.livemap.postbreak import (
    EXTENDING, FORMING_NEW_STRUCTURE, PAUSING, REENTERING, RETESTING, ROTATING,
    observe as episode_observe)

# ── the directional idea. Only a structural EVENT may produce one ────────────
LONG_IDEA, SHORT_IDEA, NO_IDEA, IDEA_UNRESOLVED = (
    "LONG_IDEA", "SHORT_IDEA", "NO_IDEA", "UNRESOLVED")
IDEAS = frozenset({LONG_IDEA, SHORT_IDEA, NO_IDEA, IDEA_UNRESOLVED})

#: The CURRENT episode state decides the idea. The original break direction never survives
#: on its own, and **location appears nowhere in this table** — that is the whole point.
IDEA_FROM_STATE = {
    EXTENDING: "with", PAUSING: "with", ROTATING: "with", RETESTING: "with",
    REENTERING: "against", FORMING_NEW_STRUCTURE: "unresolved",
}

# ── what would confirm or clarify. Not a prediction, not a score ─────────────
#
# The brief listed six by example. `HOLD_BELOW_BROKEN_EDGE` is the symmetric completion of
# `HOLD_ABOVE_BROKEN_EDGE` — the same one-sided-name completion Phase C made for
# `space_above` / `space_below`. Nothing else was added.
HOLD_ABOVE = "HOLD_ABOVE_BROKEN_EDGE"
HOLD_BELOW = "HOLD_BELOW_BROKEN_EDGE"
CONTINUE = "CONTINUE_TOWARD_NEXT_REFERENCE"
WAIT_1M = "WAIT_FOR_1M_CONFIRMATION"
RESOLVE = "RESOLVE_CONFLICT"
NO_EVENT = "NO_CLEAR_NEXT_EVENT"
DEVELOPMENTS = frozenset({HOLD_ABOVE, HOLD_BELOW, CONTINUE, WAIT_1M,
                          RESOLVE, NO_EVENT})
#
# `RECLAIM_BROKEN_EDGE` was removed. On real data it fired on 302 candles and **every
# single one** was `REENTERING` with the edge already lost — it named an event that had
# already happened and presented it as the next expected development. The existing
# vocabulary already carried the correct forward semantics: after an up break is
# reclaimed, what would confirm the new state is price **holding below** that edge, which
# is `HOLD_BELOW_BROKEN_EDGE`. A vocabulary member that only ever describes the past is
# the dead member A4 deleted, so it is gone rather than repurposed.

# ── where PRICE is. A current structure is not the same as being inside it ───
INSIDE = "INSIDE"
AT_UPPER = "AT_UPPER_EDGE"
AT_LOWER = "AT_LOWER_EDGE"
ABOVE = "ABOVE"
BELOW = "BELOW"
NO_STRUCTURE = "NO_STRUCTURE"
PRICE_LOCATIONS = frozenset({INSIDE, AT_UPPER, AT_LOWER, ABOVE, BELOW, NO_STRUCTURE})

# ── is the thesis still standing? Separate from which way it points ─────────
ACTIVE = "ACTIVE"
DEVELOPING = "DEVELOPING"      # a reversal idea that has not yet proven anything
CONFLICTED = "CONFLICTED"
INVALIDATED = "INVALIDATED"
STATUS_UNRESOLVED = "UNRESOLVED"
NO_THESIS = "NO_THESIS"
STATUSES = frozenset({ACTIVE, DEVELOPING, CONFLICTED, INVALIDATED,
                      STATUS_UNRESOLVED, NO_THESIS})

# ── THESIS GENERATIONS ───────────────────────────────────────────────────────
#
# One episode can hold several theses in sequence, and a single status field cannot
# describe two of them at once. On real data this produced a reading that looks like a
# contradiction:
#
#     BROKE C13 down | REENTERING | LONG_IDEA | INVALIDATED | HOLD_ABOVE_BROKEN_EDGE
#
# Two stories were being flattened into one:
#
#     generation 1   C13 broke DOWN  -> SHORT thesis  -> INVALIDATED by the reclaim
#     generation 2   price reclaimed -> LONG idea     -> DEVELOPING, unproven
#
# A decision layer reading `INVALIDATED` next to `LONG_IDEA` could conclude "the long
# idea is dead" when in fact the *short* one is, and a long one has just been born. For
# an automatic trader that confusion is the dangerous kind, so the generations are now
# separate fields and the old thesis can never silently become the new one.


@dataclass(frozen=True, slots=True)
class ThesisIdentity:
    """**Which thesis is this?** The single authoritative answer, measured not assumed.

    Immutable and hashable, and consumed by every layer that needs the question answered —
    `ParticipationContext`, `TradeThesisSnapshot`, `PositionEvaluation`, `reactor.exit_check`
    and the position lifecycle. There is deliberately one of these; an identity computed
    separately in each module is how two layers start disagreeing about the same candle.

    ## What is in it, and why — from a real-data audit over teach and validate

    ```
    broken structure   the structure whose break created the thesis
    generation         which generation of that break's story this is
    direction          the break's own direction
    ```

    **The break index is excluded.** The same structure re-breaks at the same generation
    with the same direction and the same invalidation — 176 teach groups and 59 validate
    groups do exactly that. Including it would report a thesis change every time, which is
    the mistake this audit found: 35 of 70 held candles in one block looked changed and
    every one was `L02` re-breaking with the invalidation unmoved.

    **The direction is required.** Without it, `(structure, generation)` collapses two
    genuinely different theses into one: 98 teach groups and 39 validate groups carried
    **two different ideas and two different invalidations** under a single key — `L02`
    generation 1 broke up (invalidation 44,650.93) and also broke down (44,567.27). Adding
    the direction takes both counts to **zero** in both halves.

    **The invalidation is excluded, and that is a measurement not a preference.** Inside
    one `(structure, generation, direction)` group the invalidation reference never varies
    — zero groups with two invalidations, teach and validate. It is therefore *derivable
    from* the identity rather than a component of it, and putting it in would add nothing
    while making the identity move whenever the reference was recomputed.
    """

    broken_id: str
    generation: int
    direction: str                  # up | down — the break's own

    def __str__(self) -> str:
        return f"{self.broken_id}/GEN{self.generation}/{self.direction.upper()}"


def identity_of(thesis) -> ThesisIdentity | None:
    """The one identity function. `None` when no thesis has established a direction."""
    if thesis.generation == 0 or not thesis.broken_id or not thesis.break_direction:
        return None
    return ThesisIdentity(broken_id=thesis.broken_id, generation=thesis.generation,
                          direction=thesis.break_direction)


def generations(seq) -> tuple[int, bool]:
    """`(generation, break_is_working)` from the episode's own state history.

    Causal: `seq` is the episode's states from the break up to and including the current
    candle, and nothing later. A generation ends when price crosses between "the break is
    working" and "the break has been given back" — which is exactly `REENTERING`
    appearing or disappearing.

    `FORMING_NEW_STRUCTURE` is neutral and carries the current generation forward: a new
    structure forming is not price reclaiming an edge, and counting it as a flip would
    invent a generation nobody observed.
    """
    gen, working = 1, True
    for s in seq:
        if s.state == FORMING_NEW_STRUCTURE:
            continue
        w = s.state != REENTERING
        if w != working:
            gen, working = gen + 1, w
    return gen, working

# ── durability. Decided from what has ALREADY happened. Never a direction ────
NOT_YET_RETESTED = "NOT_YET_RETESTED"
ALREADY_RETESTED = "EDGE_ALREADY_RETESTED"
EDGE_LOST = "EDGE_LOST"
NO_EPISODE = "NO_EPISODE"
DURABILITY = frozenset({NOT_YET_RETESTED, ALREADY_RETESTED, EDGE_LOST, NO_EPISODE})

TRUST_UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class LiveThesis:
    """One candle's whole story. Rebuilt every candle; nothing carried by inertia."""

    index: int
    at: datetime
    price: Decimal

    # ── LOCATION. No direction is implied by any of these. ──────────────────
    location: str = ""
    #: Where PRICE is, which is not the same question as which structure is current.
    #: 26.6% of candles with a current node had price already beyond one of its edges.
    price_location: str = NO_STRUCTURE
    structure_id: str | None = None
    band: tuple[Decimal, Decimal] | None = None
    position_in_current: Decimal | None = None
    to_upper_edge: Decimal | None = None
    to_lower_edge: Decimal | None = None
    location_facts: tuple[str, ...] = ()
    # ── MOVEMENT. What moved, on both sides. Not a heading. ─────────────────
    movement_facts: tuple[str, ...] = ()
    # what broke or changed
    changed: tuple[str, ...] = ()
    broken_id: str | None = None
    broken_edge: Decimal | None = None
    break_direction: str = ""
    bars_since_break: int | None = None
    # where price came from
    arrived_from: str | None = None
    arrived_direction: str = ""
    bars_in_transit: int = 0
    # what price built inside the current structure
    internal: tuple[str, ...] = ()
    # what price is doing now — the PRIMARY state
    current_state: str = ""
    # the directional idea, and the event that produced it
    idea: str = NO_IDEA
    idea_because: str = ""
    #: Status of the CURRENT generation's idea — never of an older one.
    thesis_status: str = NO_THESIS
    #: Which generation of thesis this episode is on. 1 = the original break thesis.
    generation: int = 0
    #: The ORIGINAL break thesis, kept separate so it can never be mistaken for the
    #: current idea. `break_thesis_status` is `INVALIDATED` from generation 2 onward.
    break_thesis: str = NO_IDEA
    break_thesis_status: str = NO_THESIS
    #: The generation immediately before this one, and its status. `None` at generation 1.
    previous_idea: str | None = None
    previous_idea_status: str | None = None
    #: Neutral observations. NOT conflicts — a state's own defining condition belongs
    #: here, never in `conflicting`.
    observations: tuple[str, ...] = ()
    # references ahead
    next_ref: str | None = None
    free_to_near: Decimal | None = None
    zone_depth: Decimal | None = None
    free_to_far: Decimal | None = None
    corridor: tuple[str, ...] = ()
    # evidence — only relationships DEFINITIONAL to the stated thesis
    supporting: tuple[str, ...] = field(default_factory=tuple)
    conflicting: tuple[str, ...] = field(default_factory=tuple)
    # invalidation, as an existing structural price
    invalidation: str = ""
    invalidation_price: Decimal | None = None
    #: The structural path that is OBSERVED to be available. Not a target, not a
    #: forecast, and deliberately not called "CAN GO" — that wording reads as a promise.
    path_ahead: tuple[str, ...] = ()
    # what would confirm or clarify. Driven by `current_state` first.
    next_expected: str = NO_EVENT
    #: A genuine unresolved directional contradiction — see `contradiction()`. Reported
    #: separately so a consumer can see WHY the development is RESOLVE_CONFLICT.
    contradicted: bool = False
    # context, deliberately apart from direction
    durability: str = NO_EPISODE
    trust: str = TRUST_UNRESOLVED

    def __post_init__(self) -> None:
        if self.idea not in IDEAS:
            raise ValueError(f"unknown idea {self.idea!r}")
        if self.next_expected not in DEVELOPMENTS:
            raise ValueError(f"unknown development {self.next_expected!r}")
        if self.price_location not in PRICE_LOCATIONS:
            raise ValueError(f"unknown price location {self.price_location!r}")
        if self.thesis_status not in STATUSES:
            raise ValueError(f"unknown thesis status {self.thesis_status!r}")
        if self.durability not in DURABILITY:
            raise ValueError(f"unknown durability {self.durability!r}")
        if self.trust != TRUST_UNRESOLVED:
            raise ValueError("TRUST stays UNRESOLVED until a calibration study exists")

    def lines(self) -> list[str]:
        def p(v, dp=0):
            return "-" if v is None else f"{float(v):,.{dp}f}"
        out = [f"PRICE           {float(self.price):,.1f}",
               f"PRICE LOCATION  {self.price_location}",
               f"CURRENT STRUCT  {self.location}"]
        if self.band:
            out.append(f"                {self.structure_id} {p(self.band[0])}-"
                       f"{p(self.band[1])}   pos {p(self.position_in_current, 2)}   "
                       f"to upper {p(self.to_upper_edge)}   "
                       f"to lower {p(self.to_lower_edge)}")
        for f_ in self.location_facts:
            out.append(f"                . {f_}")
        out.append("MOVEMENT        " + (self.movement_facts[0]
                                         if self.movement_facts else "-"))
        for f_ in self.movement_facts[1:]:
            out.append(f"                . {f_}")
        out.append(f"CHANGED         {' | '.join(self.changed) or 'nothing'}")
        if self.broken_id:
            out.append(f"BROKE           {self.broken_id} at {p(self.broken_edge)} "
                       f"({self.break_direction}), {self.bars_since_break} candles ago")
        out.append("CAME FROM       "
                   + (f"{self.arrived_from} ({self.arrived_direction}), "
                      f"{self.bars_in_transit} candles transit"
                      if self.arrived_from else "-"))
        out.append(f"BUILT INSIDE    {' | '.join(self.internal) or '-'}")
        out.append(f"CURRENT STATE   {self.current_state}")
        if self.generation:
            out.append(f"BREAK THESIS    {self.break_thesis} "
                       f"[{self.break_thesis_status}]   (generation 1)")
        if self.previous_idea:
            out.append(f"PREVIOUS IDEA   {self.previous_idea} "
                       f"[{self.previous_idea_status}]")
        out.append(f"CURRENT IDEA    {self.idea}"
                   + (f"   (generation {self.generation})" if self.generation else ""))
        out.append(f"IDEA STATUS     {self.thesis_status}"
                   + (f"   {self.idea_because}" if self.idea_because else ""))
        out.append(f"SUPPORTING      {' | '.join(self.supporting) or '-'}")
        out.append(f"OBSERVATIONS    {' | '.join(self.observations) or '-'}")
        out.append(f"CONFLICTING     {' | '.join(self.conflicting) or '-'}")
        out.append(f"NEXT EXPECTED   {self.next_expected}"
                   + ("   (history contradicts the current state)"
                      if self.contradicted else ""))
        out.append(f"INVALIDATION    {self.invalidation or '-'}"
                   + (f"   ({p(self.invalidation_price)})"
                      if self.invalidation_price is not None else ""))
        out.append("ROUTE           "
                   + (f"{self.next_ref}   free {p(self.free_to_near)} | depth "
                      f"{p(self.zone_depth)} | far {p(self.free_to_far)}"
                      if self.next_ref else "kuchh nahi"))
        if self.corridor:
            out.append(f"                corridor {' -> '.join(self.corridor)}")
        out.append("PATH AHEAD      "
                   + (" -> ".join(self.path_ahead) or "-")
                   + "   (observed structure, not a target)")
        out.append(f"DURABILITY      {self.durability}")
        out.append(f"TRUST           {self.trust}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
def _third(pos: float) -> str:
    """The repo's own thirds. A statement about WHERE, never about where next."""
    return ("lower third" if pos < 1 / 3 else
            "upper third" if pos > 2 / 3 else "middle third")


def _inside(readings, node_id, i, node_window) -> tuple[str, ...]:
    """What price built inside the structure it is standing in.

    **Direction-free.** Approaches are counted to BOTH edges and reported separately, and
    the time-spent statement names a third rather than an edge. The earlier version took
    an `up_side` argument inferred from position; removing that inference is the point.
    """
    lo = i
    while (lo - 1 >= 0 and readings.get(lo - 1)
           and readings[lo - 1].node_id == node_id):
        lo -= 1
    facts: list[str] = []
    positions: list[float] = []
    up_app = dn_app = 0
    up_prev = dn_prev = False
    view = None
    confirmed = False
    for k in range(lo, i + 1):
        r = readings.get(k)
        if r is None:
            continue
        at_up = r.interaction == "AT_UPPER_EDGE"
        at_dn = r.interaction == "AT_LOWER_EDGE"
        if at_up and not up_prev:
            up_app += 1
        if at_dn and not dn_prev:
            dn_app += 1
        up_prev, dn_prev = at_up, at_dn
        if r.micro is None:
            continue
        view = r.micro.view
        if r.micro.micro_state == "CONFIRMED":
            confirmed = True
        if r.micro.position_in_current is not None:
            positions.append(float(r.micro.position_in_current))

    if view:
        facts.append(view.replace("MICRO_", "micro ").lower())
    if confirmed:
        facts.append("a confirmed micro formed")
    if positions:
        facts.append(f"spent its time in the {_third(S.median(positions))}")
    for label, n in (("upper", up_app), ("lower", dn_app)):
        if n >= MIN_TOUCHES:
            facts.append(f"{n} separate approaches to the {label} edge")
        elif n == 1:
            facts.append(f"one approach to the {label} edge")
    windows = len([n for n in WINDOWS if n < node_window]) if node_window else 0
    if windows < STABILITY_RUN:
        facts.append("parent too narrow to hold a micro")
    facts.append(f"{i - lo + 1} candles inside")
    return tuple(facts)


def _movement(eye, reading) -> tuple[str, ...]:
    """MOVEMENT — what moved. Both sides, always, and never a heading."""
    if eye is None:
        return ()
    out: list[str] = []
    d = eye.delta("price")
    if d is not None and d.change is not None:
        out.append(f"price {float(d.change):+,.1f} this candle")
    elif d is not None and d.reason:
        out.append(f"price delta refused ({d.reason})")
    for side, ep in (("upper", eye.upper), ("lower", eye.lower)):
        if ep is None:
            continue
        bit = f"{side} edge {float(ep.distance):,.0f} away"
        if ep.closing:
            bit += f", closing {ep.closing} candles running"
        if ep.touches:
            bit += f", {ep.touches} touches"
        out.append(bit)
    m = reading.micro
    if m is not None and m.last_direction:
        out.append(f"micro last direction {m.last_direction}")
    if m is not None and m.rotations:
        out.append(f"{m.rotations} rotations inside the parent this visit")
    return tuple(out)


def contradiction(ep_state, idea) -> bool:
    """Is there a genuine, unresolved DIRECTIONAL contradiction?

    ## The correction this function exists for

    The first version returned `RESOLVE_CONFLICT` whenever `conflicting` was non-empty,
    and on real replay that swallowed 44% of all candles. The reason was double counting:
    most "conflicts" were restatements of the state itself. `PAUSING` produced the
    conflicting fact *"no new extreme this candle"* — which is not evidence against
    `PAUSING`, it is the **definition** of `PAUSING`.

    > A conflict means *"there is evidence that disagrees with the current thesis"*.
    > It does not mean *"the market has entered a conflict state"*.

    So a contradiction is narrower, and it is the episode's own **history** disagreeing
    with its own **current state**: the broken edge has already been closed back through
    at least once, and yet the current state claims the break is working. Both things are
    true, they cannot both be the whole story, and nothing in the stack resolves it.

    No score, no weighting, no threshold — one boolean off two existing causal fields.
    """
    if ep_state is None or idea not in (LONG_IDEA, SHORT_IDEA):
        return False
    return bool(ep_state.returned_inside) and ep_state.state in (EXTENDING, RETESTING)


def status_of(ep_state, idea, contradicted: bool, generation: int) -> str:
    """The status of the **current generation's** idea. Never of an older one.

    Generation 1 is the break thesis and can be `ACTIVE` or `CONFLICTED`. Generation 2+
    is a reversal born from a reclaim: it is `DEVELOPING` — it exists, it has a direction,
    and it has proven nothing yet. `INVALIDATED` is never the current generation's status,
    because the moment a generation is invalidated the next one begins; the invalidated
    one is reported as `previous_idea_status`.
    """
    if ep_state is None:
        return NO_THESIS
    if ep_state.state == FORMING_NEW_STRUCTURE or idea == IDEA_UNRESOLVED:
        return STATUS_UNRESOLVED
    if contradicted:
        return CONFLICTED
    return ACTIVE if generation == 1 else DEVELOPING


def price_location(reading, state) -> str:
    """Where PRICE is. A node stays current while price is already past one of its edges,
    and calling that "inside" was wrong on 26.6% of candles with a current structure."""
    cur = state.current
    if cur is None:
        return NO_STRUCTURE
    if reading.interaction == AT_UPPER:
        return AT_UPPER
    if reading.interaction == AT_LOWER:
        return AT_LOWER
    if cur.position is not None:
        if float(cur.position) > 1:
            return ABOVE
        if float(cur.position) < 0:
            return BELOW
    return INSIDE


def development(ep_state, idea, has_route, contradicted: bool) -> str:
    """What would confirm or clarify the thesis.

    **The current episode state is primary.** `RESOLVE_CONFLICT` is the named exception,
    not the default, and it is reached only through `contradiction()` above. A pure
    function of four already-decided fields: no measurement, no threshold, no lookahead.
    """
    if ep_state is None:
        return NO_EVENT
    if contradicted:
        return RESOLVE
    state = ep_state.state
    if state == REENTERING:
        # The reclaim has ALREADY happened — that is what REENTERING means. What would
        # confirm the new situation is price HOLDING on the far side of the edge it just
        # came back through, which is the mirror of the original break's direction.
        return HOLD_BELOW if ep_state.episode.direction == "up" else HOLD_ABOVE
    if state == EXTENDING:
        return CONTINUE if has_route else WAIT_1M
    if state == RETESTING:
        return HOLD_ABOVE if ep_state.episode.direction == "up" else HOLD_BELOW
    if state in (PAUSING, ROTATING):
        return WAIT_1M
    return NO_EVENT


def read(reading, state, eye, ep_state, readings, nodes,
         ep_prefix=()) -> LiveThesis:
    """One candle. Everything recomputed; nothing carried by inertia."""
    cur = state.current
    sup: list[str] = []
    con: list[str] = []

    loc_facts: list[str] = []
    to_up = to_dn = None
    if cur is not None:
        location = f"{cur.id} {cur.band}"
        to_up, to_dn = cur.high - state.price, state.price - cur.low
        if cur.position is not None:
            loc_facts.append(f"standing in the {_third(float(cur.position))}")
        if cur.parent_id:
            loc_facts.append(f"which sits inside {cur.parent_id}")
    elif ep_state is not None:
        side = "above" if ep_state.episode.direction == "up" else "below"
        location = f"outside {ep_state.episode.broken_id}, {side} its broken edge"
    else:
        location = "belonging to no structure"

    internal: tuple[str, ...] = ()
    if cur is not None and reading.node_id:
        node = nodes.get(reading.node_id)
        internal = _inside(readings, reading.node_id, reading.index,
                           node.window if node else 0)

    ep = ep_state.episode if ep_state else None
    gen, working = (0, True)
    break_thesis = prev_idea = prev_status = None
    if ep_state is not None:
        current_state = ep_state.state
        gen, working = generations(ep_prefix)
        up = ep.direction == "up"
        break_thesis = LONG_IDEA if up else SHORT_IDEA
        with_break = LONG_IDEA if up else SHORT_IDEA
        against = SHORT_IDEA if up else LONG_IDEA
        if ep_state.state == FORMING_NEW_STRUCTURE:
            idea = IDEA_UNRESOLVED
            because = "a new structure is forming after the break"
        else:
            idea = with_break if working else against
            because = (f"{ep.broken_id} broke {ep.direction} and its edge still holds"
                       if working else
                       f"{ep.broken_id}'s edge was reclaimed; this is the reversal idea")
        if gen > 1:
            prev_idea = with_break if (gen % 2 == 0) else against
            prev_status = INVALIDATED
    else:
        current_state = reading.interaction
        idea = NO_IDEA
        because = "no structural event has established a direction"

    if ep_state is not None and idea in (LONG_IDEA, SHORT_IDEA):
        if not ep_state.returned_inside:
            sup.append("broken edge has never been closed back through")
        else:
            con.append("broken edge has been reclaimed at least once")
        if ep_state.state == EXTENDING:
            sup.append("making new extremes beyond the broken edge")
        if ep_state.state == RETESTING and not ep_state.returned_inside:
            sup.append("at the broken edge and still holding it")
        # NOTE: PAUSING / ROTATING / REENTERING contribute NOTHING here. Each is a
        # restatement of `current_state`, not evidence against it. `PAUSING` means "no new
        # extreme"; filing that as a conflict says the same thing twice and makes one of
        # the two a lie. It is a neutral OBSERVATION instead — see `obs` below.
        pass

    obs: list[str] = []
    if ep_state is not None and ep_state.state == PAUSING:
        obs.append("no new extreme beyond the broken edge yet")
    if ep_state is not None and ep_state.state == ROTATING:
        obs.append("rotating between the post-break extremes")

    up_idea = idea == LONG_IDEA
    route = state.route_above if up_idea else state.route_below
    side_refs = state.above if up_idea else state.below
    corridor = tuple(f"{s.ref_id}.{s.edge} {float(s.price):,.0f}"
                     for s in (side_refs.corridor or ())[:3])

    # ── invalidation belongs to the CURRENT generation ──────────────────────
    #
    # The price is the same structural level for every generation, but the SENSE is not.
    # Generation 1 dies when price gives the break back; a reversal generation dies when
    # the original break direction RESUMES. Wording generation 2 like generation 1 was the
    # one semantic bug this audit found — 381 candles carrying the dead thesis's
    # invalidation as though it were the live one's.
    inval, inval_px = "", None
    if ep is not None and idea in (LONG_IDEA, SHORT_IDEA):
        inval_px = ep.broken_edge
        if gen == 1:
            inval = (f"two closes back through {ep.broken_id}'s broken edge - "
                     f"the {ep.direction} break is given back")
        else:
            resumes = "above" if ep.direction == "up" else "below"
            inval = (f"two closes {resumes} {ep.broken_id}'s edge again - this "
                     f"generation-{gen} reversal fails and the original "
                     f"{ep.direction} break resumes")
    elif cur is not None:
        inval = f"either of {cur.id}'s own edges, by two closes"

    dest: tuple[str, ...] = ()
    if route is not None:
        dest = (f"near {float(route.near_edge):,.0f}",
                f"through {float(route.zone_depth):,.0f} pts",
                f"far {float(route.far_edge):,.0f}")

    if ep_state is None:
        dur = NO_EPISODE
    elif ep_state.returned_inside:
        dur = EDGE_LOST
    elif ep_state.state == RETESTING:
        dur = ALREADY_RETESTED
    else:
        dur = NOT_YET_RETESTED

    changed = tuple(t.field for t in eye.transitions) if eye else ()
    if eye is not None and eye.session_start:
        changed = ("new session",) + changed

    return LiveThesis(
        index=reading.index, at=state.at, price=state.price,
        location=location, structure_id=cur.id if cur else None,
        band=(cur.low, cur.high) if cur else None,
        position_in_current=cur.position if cur else None,
        to_upper_edge=to_up, to_lower_edge=to_dn,
        location_facts=tuple(loc_facts), movement_facts=_movement(eye, reading),
        changed=changed,
        broken_id=ep.broken_id if ep else None,
        broken_edge=ep.broken_edge if ep else None,
        break_direction=ep.direction if ep else "",
        bars_since_break=(ep_state.index - ep.break_index) if ep_state else None,
        arrived_from=reading.arrived_from, arrived_direction=reading.arrived_direction,
        bars_in_transit=reading.bars_in_transit,
        internal=internal, current_state=current_state, idea=idea,
        idea_because=because,
        price_location=price_location(reading, state),
        thesis_status=status_of(ep_state, idea, contradiction(ep_state, idea), gen),
        generation=gen,
        break_thesis=break_thesis or NO_IDEA,
        break_thesis_status=(NO_THESIS if not gen else
                             ACTIVE if gen == 1 else INVALIDATED),
        previous_idea=prev_idea, previous_idea_status=prev_status,
        next_ref=route.id if route else None,
        free_to_near=route.free_to_near if route else None,
        zone_depth=route.zone_depth if route else None,
        free_to_far=route.free_to_far if route else None,
        corridor=corridor,
        supporting=tuple(dict.fromkeys(sup)), conflicting=tuple(dict.fromkeys(con)),
        observations=tuple(dict.fromkeys(obs)),
        invalidation=inval, invalidation_price=inval_px, path_ahead=dest,
        next_expected=development(ep_state, idea, route is not None,
                                  contradiction(ep_state, idea)),
        contradicted=contradiction(ep_state, idea),
        durability=dur, trust=TRUST_UNRESOLVED)


def narrate(snapshot: MapSnapshot, frontier: Frontier) -> list[LiveThesis]:
    interp = Interpreter(snapshot, frontier)
    states = {s.index: s for s in interp.states()}
    eyes = {e.index: e for e in eye_observe(snapshot, frontier)}
    ep_states = list(episode_observe(frontier))
    eps = {s.index: s for s in ep_states}
    #: Each candle gets its episode's states UP TO AND INCLUDING itself, never further.
    prefix: dict[int, tuple] = {}
    seen: dict[str, list] = {}
    for s in ep_states:
        bucket = seen.setdefault(s.episode.id, [])
        bucket.append(s)
        prefix[s.index] = tuple(bucket)
    readings = {r.index: r for r in frontier.readings}
    nodes = {n.id: n for n in list(snapshot.nodes) + list(frontier.history())}
    return [read(r, states[r.index], eyes.get(r.index), eps.get(r.index),
                 readings, nodes, prefix.get(r.index, ()))
            for r in frontier.readings if r.index in states]


__all__ = ["ThesisIdentity", "identity_of", "LiveThesis", "read", "narrate", "development", "contradiction",
           "status_of", "price_location", "PRICE_LOCATIONS", "STATUSES", "IDEA_FROM_STATE", "IDEAS",
           "DEVELOPMENTS", "DURABILITY", "TRUST_UNRESOLVED"]
