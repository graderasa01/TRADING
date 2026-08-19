"""
The PARTICIPATION CONTEXT and the MARKET EYE.

**Observation only.** No `ENTER_*`, no broker, no order, no sizing, no risk, no exit
engine, no threshold, no score, no probability, no confidence, no ranking. Promoted from
the research scratchpad after validation; this file is canonical and the scratchpad copy
re-exports it, so the two cannot diverge.
`EXECUTION_STATUS` stays `UNAVAILABLE` and the layer emits a `TRADE_CANDIDATE` trace, never
an order. `split.holdout()` is not called.

```
OBSERVATION            frontier · map · micro · eye
    |
RELEASE CONTEXT        src/livemap/release.py      what broke, which scale, what is beyond
    |
LIVE THESIS            thesis.py                   direction, generation, invalidation
    |
PARTICIPATION CONTEXT  this module                 is the context whole and unobstructed
    |
DECISION / POSITION    livemap/reactor.py          FLAT | LONG | SHORT, and the contract
```

## Three worlds, still three

This module **composes**; it detects nothing. It re-derives no structure, no micro, no
route, no break, no thesis, no generation and no invalidation. Where a fact is missing the
answer is `UNAVAILABLE` and the missing fact is named.

## The semantic outcome is presence-of-facts, never a threshold

```
PARTICIPATION_AVAILABLE     every required fact exists and no structural constraint applies
PARTICIPATION_CONSTRAINED   every required fact exists, and a NAMED constraint applies
PARTICIPATION_UNAVAILABLE   a required fact does not exist
```

Every constraint is the presence or absence of an existing fact — a contradiction, a
counter-thesis direction, a duplicate opportunity, an open position in the same generation,
price already back inside the structure that broke. **None of them is a comparison against
a number.** In particular *"the next opposing reference is very close"* is reported as
`free_to_near` and is deliberately **not** a constraint: turning it into one would need a
threshold, and no threshold has been earned.

`AVAILABLE` does not mean ENTER. It means the context is complete and unobstructed. The
decision contract still has the last word, and its execution gate is still shut.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.boxes.structure import atr_at, tol_at
from src.domain.models import ZERO
from src.livemap import release as R
from src.livemap import thesis as TH
from src.livemap.interpreter import Interpreter
from src.livemap.postbreak import observe as episode_observe

# ── POSITION — carried by the decision layer, never inferred from the market ──
#
# Promoted alongside the contract rather than imported from the research `decision.py`:
# that module also carries an `ENTER_*` vocabulary, and production must not have one.
FLAT, LONG, SHORT = "FLAT", "LONG", "SHORT"
POSITIONS = frozenset({FLAT, LONG, SHORT})


def opportunity_of(t) -> tuple | None:
    """The causal identity of the opportunity a candle belongs to.

    The structure that broke, the candle it broke on, and the generation — all three
    already on the thesis, none invented here. Measured before this existed, one thesis
    authorised a stream of entries: 297 duplicates in teach, 113 in validate.
    """
    if t.generation == 0 or t.broken_id is None or t.bars_since_break is None:
        return None
    return (t.broken_id, t.index - t.bars_since_break, t.generation)

# ── §13 the semantic outcome ─────────────────────────────────────────────────
AVAILABLE = "PARTICIPATION_AVAILABLE"
CONSTRAINED = "PARTICIPATION_CONSTRAINED"
UNAVAILABLE = "PARTICIPATION_UNAVAILABLE"
OUTCOMES = frozenset({AVAILABLE, CONSTRAINED, UNAVAILABLE})

# ── §12 opportunity identity ─────────────────────────────────────────────────
NEW_THESIS = "NEW_THESIS"
NEW_GENERATION_RELEASE = "NEW_GENERATION_RELEASE"
SAME_GENERATION_CONTINUATION = "SAME_GENERATION_CONTINUATION_RELEASE"
SAME_GENERATION_REPEAT = "SAME_GENERATION_REPEAT"
NO_OPPORTUNITY = "NO_OPPORTUNITY"
OPPORTUNITIES = frozenset({NEW_THESIS, NEW_GENERATION_RELEASE,
                           SAME_GENERATION_CONTINUATION, SAME_GENERATION_REPEAT,
                           NO_OPPORTUNITY})
#: The two that may be considered for a NEW entry. The other two are continuation or
#: management information — §12 and §17, and the decision contract already says so.
ENTRY_SHAPED = frozenset({NEW_THESIS, NEW_GENERATION_RELEASE})

# ── missing facts (UNAVAILABLE) — never a bound that was not cleared ─────────
NO_RELEASE = "NO_RELEASE_ON_THIS_CANDLE"
NO_THESIS_FACT = "NO_THESIS"
IDEA_UNRESOLVED = "IDEA_UNRESOLVED"
NO_INVALIDATION = "NO_CURRENT_GENERATION_INVALIDATION"
NO_PATH = "NO_MAPPED_PATH_BEYOND_THE_BROKEN_BOUNDARY"

# ── named constraints (CONSTRAINED) — all presence-of-fact, no numbers ───────
COUNTER_THESIS = "RELEASE_IS_COUNTER_TO_THE_CURRENT_IDEA"
CONTRADICTION = "UNRESOLVED_CONTRADICTION"
CONTINUATION = "CONTINUATION_OF_A_LIVE_GENERATION"
DUPLICATE = "OPPORTUNITY_ALREADY_TAKEN"
POSITION_OPEN = "POSITION_ALREADY_OPEN_ON_THIS_THESIS"
GAVE_IT_BACK = "PRICE_IS_BACK_INSIDE_THE_STRUCTURE_THAT_BROKE"
MULTI_SCALE_UNRESOLVED = "TWO_SCALES_RELEASED_TOGETHER"

EXEC_UNAVAILABLE = "UNAVAILABLE"
TRADE_CANDIDATE = "TRADE_CANDIDATE"


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ParticipationContext:
    """One candle, composed. Every field is a copy from a layer that already owns it."""

    index: int
    at: datetime
    price: Decimal

    # ── THESIS ──────────────────────────────────────────────────────────────
    idea: str = TH.NO_IDEA
    generation: int = 0
    thesis_status: str = TH.NO_THESIS
    current_state: str = ""
    #: What the thesis says it is waiting for next — `thesis.LiveThesis.next_expected`,
    #: published since the thesis layer was built and simply not surfaced here until the
    #: observatory needed to answer "what is the next development?". Copied, never
    #: recomputed: `thesis.development()` owns the rule and this is its output.
    next_expected: str = TH.NO_EVENT
    contradicted: bool = False
    break_thesis: str = TH.NO_IDEA
    break_thesis_status: str = TH.NO_THESIS

    # ── RELEASE ─────────────────────────────────────────────────────────────
    release: R.Release | None = None
    all_releases: tuple[R.Release, ...] = ()
    release_scale: str | None = None
    controlling_scale: str = R.UNRESOLVED
    simultaneous: bool = False
    #: The release still held from an earlier candle, when nothing broke on this one.
    holding: R.Release | None = None

    # ── LOCATION — two of them, and they are different questions ────────────
    current_location: str = TH.NO_STRUCTURE
    release_location: str | None = None
    parent_location: str | None = None
    position_in_current: Decimal | None = None

    # ── PATH — measured from the boundary that broke ────────────────────────
    free_to_near: Decimal | None = None
    zone_depth: Decimal | None = None
    free_to_far: Decimal | None = None
    next_reference: str | None = None
    far_reference: Decimal | None = None
    corridor: tuple[str, ...] = ()
    watch: str | None = None

    # ── MOVE CONSUMPTION — §10, descriptive, no cutoff ──────────────────────
    bars_since_break: int | None = None
    excursion_travelled: Decimal | None = None
    excursion_atr: float | None = None
    beyond_release: Decimal | None = None
    beyond_release_atr: float | None = None

    # ── INVALIDATION — current generation, always ───────────────────────────
    invalidation: str = ""
    invalidation_price: Decimal | None = None
    invalidation_distance: Decimal | None = None
    invalidation_distance_atr: float | None = None

    # ── MICRO — subordinate, never a signal ─────────────────────────────────
    micro_id: str | None = None
    micro_state: str | None = None
    micro_view: str | None = None
    micro_rotations: int = 0
    micro_last_direction: str = ""

    # ── OPPORTUNITY and POSITION ────────────────────────────────────────────
    #: **Which thesis this candle belongs to** — `thesis.identity_of()`, the one
    #: authoritative answer. Audited over teach and validate: the generation integer alone
    #: cannot see 14% of thesis transitions, and `opportunity_of` cannot stand in because
    #: its break-index field moves when a structure re-breaks without the thesis changing.
    thesis_identity: TH.ThesisIdentity | None = None
    #: The identity of the OPPORTUNITY, which is a different question and keeps the break
    #: index precisely because a re-break is a new opportunity on the same thesis.
    opportunity: tuple | None = None
    opportunity_kind: str = NO_OPPORTUNITY
    #: The position **before** this candle's decision — `decision.Decision.position`'s own
    #: convention. Reading it as "the position after" would date every entry one candle late.
    position: str = FLAT
    open_identity: TH.ThesisIdentity | None = None

    # ── the outcome, and why ────────────────────────────────────────────────
    participation: str = UNAVAILABLE
    reasons: tuple[str, ...] = field(default_factory=tuple)
    execution_status: str = EXEC_UNAVAILABLE

    def __post_init__(self) -> None:
        if self.participation not in OUTCOMES:
            raise ValueError(f"unknown participation outcome {self.participation!r}")
        if self.opportunity_kind not in OPPORTUNITIES:
            raise ValueError(f"unknown opportunity kind {self.opportunity_kind!r}")
        if self.position not in POSITIONS:
            raise ValueError(f"unknown position {self.position!r}")

    @property
    def entry_shaped(self) -> bool:
        """Would the decision contract even consider this a NEW opportunity?"""
        return self.opportunity_kind in ENTRY_SHAPED

    # ── §14 / §33 the human trader view ─────────────────────────────────────
    def render(self, symbol: str = "BANK NIFTY") -> list[str]:
        def p(v, dp=0):
            return "—" if v is None else f"{float(v):,.{dp}f}"

        out = [f"MARKET            {symbol}",
               f"PRICE             {float(self.price):,.1f}"
               f"   {self.at:%Y-%m-%d %H:%M}"]

        if self.generation:
            out.append(f"ACTIVE THESIS     {self.idea.replace('_IDEA', '')} — "
                       f"generation {self.generation} — {self.thesis_status}")
        else:
            out.append("ACTIVE THESIS     none — no structural event has set a direction")

        if self.release is not None:
            r = self.release
            out.append(f"WHAT JUST HAPPENED{'':<1} {r.scale} {r.broken_id} "
                       f"{r.boundary.split('.')[1]} broke "
                       f"{r.direction.upper()} at {float(r.broken_edge):,.0f}")
            if self.simultaneous:
                others = [x for x in self.all_releases if x is not r]
                out.append("                  also on this candle: "
                           + " · ".join(f"{x.scale} {x.boundary}" for x in others)
                           + "   (both kept — neither is resolved away)")
            out.append(f"PARENT            {r.parent_id or '—'}"
                       + (f"  {p(r.parent_low)}-{p(r.parent_high)}"
                          if r.parent_low is not None else ""))
        elif self.holding is not None:
            out.append(f"WHAT JUST HAPPENED{'':<1} nothing — still holding "
                       f"{self.holding.scale} {self.holding.boundary} from candle "
                       f"{self.holding.index}")
        else:
            out.append("WHAT JUST HAPPENED nothing structural on this candle")

        out.append(f"CURRENT SCALE     {self.controlling_scale}")
        out.append(f"CURRENT LOCATION  {self.current_location}"
                   + (f"   pos {p(self.position_in_current, 2)}"
                      if self.position_in_current is not None else ""))
        if self.release_location is not None:
            out.append(f"                  {self.release_location}"
                       f"   {p(self.beyond_release)} pts "
                       f"({self.beyond_release_atr:+.2f} ATR) beyond it")
            out.append(f"                  {self.parent_location}")
        out.append("MICRO             "
                   + (f"{self.micro_id} {self.micro_state} {self.micro_view or ''}"
                      f"   {self.micro_rotations} rotations"
                      f"   last {self.micro_last_direction or '—'}"
                      if self.micro_id else "absent"))

        if self.next_reference is not None:
            out.append(f"PATH              next reference {self.next_reference}"
                       f"   free {p(self.free_to_near)} | depth {p(self.zone_depth)} "
                       f"| far {p(self.free_to_far)}   {self.watch or ''}")
            out.append("                  measured from the boundary that broke, "
                       "not from the current edge")
            if self.corridor:
                out.append("                  corridor "
                           + " → ".join(self.corridor[:3]))
        else:
            out.append("PATH              nothing mapped ahead of the broken boundary")

        age = "—" if self.bars_since_break is None else str(self.bars_since_break)
        out.append(f"MOVE CONSUMPTION  {age} candles since the thesis broke"
                   f"   {p(self.excursion_travelled)} pts already travelled"
                   + (f" ({self.excursion_atr:.2f} ATR)"
                      if self.excursion_atr is not None else ""))
        out.append(f"INVALIDATION      {self.invalidation or '—'}")
        if self.invalidation_price is not None:
            out.append(f"                  {p(self.invalidation_price)}"
                       f"   {p(self.invalidation_distance)} pts away"
                       + (f" ({self.invalidation_distance_atr:.2f} ATR)"
                          if self.invalidation_distance_atr is not None else ""))
        out.append(f"CURRENT DEVELOPMENT {self.current_state}")
        out.append(f"CONTRADICTION     {'YES' if self.contradicted else 'none'}")
        out.append(f"OPPORTUNITY       {self.opportunity_kind}")
        out.append(f"PARTICIPATION     {self.participation}"
                   + (f"   [{', '.join(self.reasons)}]" if self.reasons else ""))
        out.append(f"POSITION          {self.position}"
                   + (f"   opened on thesis {self.open_identity}"
                      if self.open_identity else ""))
        out.append(f"EXECUTION         {self.execution_status}"
                   + ("   — no validated 1m execution rule exists; this is a "
                      f"{TRADE_CANDIDATE}, not an order"
                      if self.execution_status == EXEC_UNAVAILABLE else ""))
        return out

    # ── §15 the market eye, one line per candle ─────────────────────────────
    def line(self) -> str:
        what = (" + ".join(f"{x.scale[0]}:{x.boundary}" for x in self.all_releases)
                or ("~" + self.holding.boundary if self.holding else "—"))
        part = {AVAILABLE: "AVAIL", CONSTRAINED: "CONSTR",
                UNAVAILABLE: "UNAVAIL"}[self.participation]
        return (f"c{self.index:<4} {float(self.price):>9,.1f} "
                f"{self.idea.replace('_IDEA', ''):<6}g{self.generation:<2}"
                f"{self.current_state:<18}{what:<26}"
                f"{self.controlling_scale.replace('_CONTROLLING', ''):<12}"
                f"{self.current_location:<15}"
                f"{(self.micro_state or '—'):<10}"
                f"{self.opportunity_kind.replace('SAME_GENERATION_', 'SG_'):<26}"
                f"{part:<8}{self.position}")


EYE_HEAD = (f"{'cand':<5}{'price':>10} {'IDEA':<6}{'GEN':<3}{'STATE':<18}"
            f"{'RELEASE':<26}{'SCALE':<12}{'LOCATION':<15}{'MICRO':<10}"
            f"{'OPPORTUNITY':<26}{'PART':<8}POS")


# ─────────────────────────────────────────────────────────────────────────────
def _opportunity_kind(rel, t, seen_generations, seen_boundaries) -> str:
    """§12. Derived from the generation and the boundary — no new fact invented.

    A release inside a generation that has already produced one is **continuation**, and a
    release of the same boundary in the same generation is a **repeat**. Neither is a new
    entry, which is what the decision contract already says with `OPPORTUNITY_ALREADY_TAKEN`.
    """
    if rel is None or t.generation == 0:
        return NO_OPPORTUNITY
    gen_key = opportunity_of(t)
    boundary = (gen_key, rel.scale, rel.broken_id, rel.direction)
    if boundary in seen_boundaries:
        return SAME_GENERATION_REPEAT
    if gen_key in seen_generations:
        return SAME_GENERATION_CONTINUATION
    #: A release that is itself the thesis's own break is the thesis being born.
    return NEW_THESIS if t.generation == 1 and rel.broken_id == t.broken_id \
        else NEW_GENERATION_RELEASE


def assess(t, rstate, ep, ms, atr, tol, *, position=FLAT, open_identity=None,
           used=frozenset(), seen_generations=frozenset(),
           seen_boundaries=frozenset()) -> ParticipationContext:
    """One candle. Pure function of the layers handed in — nothing is measured here."""
    rel = None
    if rstate.releases:
        # §5: never resolve a simultaneous pair away. The one carried in `release` is the
        # one aligned with the current idea when exactly one is; otherwise the first, and
        # `all_releases` keeps every one of them either way.
        aligned = [x for x in rstate.releases
                   if (x.direction == "up") == (t.idea == TH.LONG_IDEA)]
        rel = aligned[0] if len(aligned) == 1 else rstate.releases[0]

    route = rel.route if rel is not None else None
    inval_dist = (abs(t.price - t.invalidation_price)
                  if t.invalidation_price is not None else None)

    ctx = dict(
        index=t.index, at=t.at, price=t.price,
        idea=t.idea, generation=t.generation, thesis_status=t.thesis_status,
        current_state=t.current_state, next_expected=t.next_expected,
        contradicted=t.contradicted,
        break_thesis=t.break_thesis, break_thesis_status=t.break_thesis_status,
        release=rel, all_releases=tuple(rstate.releases),
        release_scale=rel.scale if rel else None,
        controlling_scale=rstate.controlling_scale,
        simultaneous=rstate.simultaneous,
        holding=rstate.active if not rstate.releases else None,
        current_location=t.price_location,
        release_location=rel.location if rel else None,
        parent_location=rel.parent_location if rel else None,
        position_in_current=t.position_in_current,
        free_to_near=route.free_to_near if route else None,
        zone_depth=route.zone_depth if route else None,
        free_to_far=route.free_to_far if route else None,
        next_reference=route.id if route else None,
        far_reference=route.far_edge if route else None,
        corridor=tuple(s.line() for s in (rel.corridor if rel else ())[:4]),
        watch=route.watch if route else None,
        bars_since_break=t.bars_since_break,
        excursion_travelled=ep.max_excursion if ep is not None else None,
        excursion_atr=(float(ep.max_excursion / atr)
                       if ep is not None and atr > ZERO else None),
        beyond_release=rel.beyond if rel else None,
        beyond_release_atr=rel.beyond_atr if rel else None,
        invalidation=t.invalidation, invalidation_price=t.invalidation_price,
        invalidation_distance=inval_dist,
        invalidation_distance_atr=(float(inval_dist / atr)
                                   if inval_dist is not None and atr > ZERO else None),
        position=position, open_identity=open_identity,
        execution_status=EXEC_UNAVAILABLE)

    # ── micro, copied off the reading the thesis already read ───────────────
    m = getattr(rstate, "micro_view", None)
    if m is not None:
        ctx.update(micro_id=m.micro_id, micro_state=m.micro_state, micro_view=m.view,
                   micro_rotations=m.rotations, micro_last_direction=m.last_direction)

    identity = TH.identity_of(t)          # computed once per candle, used twice below
    ctx["thesis_identity"] = identity
    kind = _opportunity_kind(rel, t, seen_generations, seen_boundaries)
    ctx["opportunity_kind"] = kind
    ctx["opportunity"] = (opportunity_of(t), rel.scale, rel.broken_id,
                          rel.direction) if rel is not None else None

    # ── UNAVAILABLE — a required fact does not exist ────────────────────────
    missing: list[str] = []
    if rel is None:
        missing.append(NO_RELEASE)
    if t.generation == 0 or t.idea == TH.NO_IDEA:
        missing.append(NO_THESIS_FACT)
    elif t.idea == TH.IDEA_UNRESOLVED:
        missing.append(IDEA_UNRESOLVED)
    if t.invalidation_price is None:
        missing.append(NO_INVALIDATION)
    if rel is not None and route is None:
        missing.append(NO_PATH)
    if missing:
        return ParticipationContext(participation=UNAVAILABLE,
                                    reasons=tuple(missing), **ctx)

    # ── CONSTRAINED — every fact exists, and a NAMED constraint applies ─────
    #
    # Every one of these is the presence or absence of an existing fact. None is a
    # comparison against a number: `free_to_near` being small is reported, never gated,
    # because no threshold has been earned.
    limits: list[str] = []
    if (rel.direction == "up") != (t.idea == TH.LONG_IDEA):
        limits.append(COUNTER_THESIS)
    if t.contradicted:
        limits.append(CONTRADICTION)
    if rel.location == R.BACK_INSIDE:
        limits.append(GAVE_IT_BACK)
    if rstate.simultaneous and rstate.controlling_scale == R.MULTI_SCALE:
        limits.append(MULTI_SCALE_UNRESOLVED)
    if kind == SAME_GENERATION_REPEAT:
        limits.append(DUPLICATE)
    elif kind == SAME_GENERATION_CONTINUATION:
        limits.append(CONTINUATION)
    if ctx["opportunity"] is not None and ctx["opportunity"][0] in used:
        limits.append(DUPLICATE)
    if position != FLAT and open_identity == identity:
        limits.append(POSITION_OPEN)

    return ParticipationContext(
        participation=CONSTRAINED if limits else AVAILABLE,
        reasons=tuple(dict.fromkeys(limits)), **ctx)


# ─────────────────────────────────────────────────────────────────────────────
class _RState:
    """A `ReleaseState` plus the micro view of the same candle, so `assess` can copy the
    micro without re-reading the frontier. A carrier, not a layer."""

    __slots__ = ("releases", "active", "controlling_scale", "simultaneous",
                 "micro_view", "index")

    def __init__(self, rs: R.ReleaseState, micro_view) -> None:
        self.index = rs.index
        self.releases = rs.releases
        self.active = rs.active
        self.controlling_scale = rs.controlling_scale
        self.simultaneous = rs.simultaneous
        self.micro_view = micro_view


@dataclass(frozen=True)
class Sources:
    """Everything one candle needs, assembled once. A carrier, not a layer.

    Extracted so the observer and the decision engine cannot drift: both fold over the
    same list, and neither re-reads the frontier.
    """

    index: int
    thesis: object
    rstate: object
    episode: object
    mapstate: object
    atr: Decimal
    tol: Decimal


def sources(snapshot, frontier, *, upto: int | None = None) -> list[Sources]:
    """Zip the layers, once, in candle order. No computation, no re-derivation."""
    theses = {t.index: t for t in TH.narrate(snapshot, frontier)}
    rstates = {s.index: s for s in R.observe(frontier, snapshot, upto=upto)}
    eps = {s.index: s for s in episode_observe(frontier, snapshot)}
    states = {s.index: s for s in Interpreter(snapshot, frontier).states()}
    micros = {r.index: r.micro for r in frontier.readings}
    candles = frontier.candles

    out: list[Sources] = []
    for reading in frontier.readings:
        i = reading.index
        if upto is not None and i > upto:
            break
        t, rs = theses.get(i), rstates.get(i)
        if t is None or rs is None:
            continue
        out.append(Sources(index=i, thesis=t, rstate=_RState(rs, micros.get(i)),
                           episode=eps.get(i), mapstate=states.get(i),
                           atr=atr_at(candles, i),
                           tol=tol_at(candles, i, frontier.tol_atr)))
    return out


class Book:
    """The carried state a fold needs: what has already been seen, and the position.

    Updated **only** from the decision just taken, never from the market — which is what
    makes the fold a pure function of `(carried state, candle)` and therefore prefix-causal.
    """

    __slots__ = ("position", "open_identity", "used", "generations", "boundaries")

    def __init__(self) -> None:
        self.position = FLAT
        self.open_identity: TH.ThesisIdentity | None = None
        self.used: set = set()
        self.generations: set = set()
        self.boundaries: set = set()

    def gen_key(self, t) -> tuple | None:
        """The opportunity's generation key — `opportunity_of()`, never recomputed.

        This used to build the tuple itself, and so did `_opportunity_kind`. Three
        calculations of one identity is how two layers start disagreeing about the same
        candle, and the two local copies guarded the null case differently
        (`bars_since_break or 0` against an explicit `is None`). Audited over teach and
        validate the divergent branch never fired — 0 differences in 9,600 candles — so
        collapsing them onto the canonical function is behaviour-preserving here and
        removes the way it could stop being so.
        """
        return opportunity_of(t)

    def record(self, ctx, src) -> None:
        """Remember the releases this candle carried, so a repeat can be named."""
        key = self.gen_key(src.thesis)
        if ctx.release is None or key is None:
            return
        self.generations.add(key)
        for x in src.rstate.releases:
            self.boundaries.add((key, x.scale, x.broken_id, x.direction))

    def assess(self, src) -> ParticipationContext:
        return assess(src.thesis, src.rstate, src.episode, src.mapstate, src.atr,
                      src.tol, position=self.position,
                      open_identity=self.open_identity,
                      used=frozenset(self.used),
                      seen_generations=frozenset(self.generations),
                      seen_boundaries=frozenset(self.boundaries))


def eye(snapshot, frontier, *, upto: int | None = None) -> list[ParticipationContext]:
    """The market eye — one `ParticipationContext` per closed candle, in order.

    The observer view: it carries **no position**, so every context is assessed flat. The
    position-aware fold is `reactor.replay`, and there is deliberately only one of it —
    two folds applying the transition in different orders is how a research path and a
    live path start disagreeing about the same day.
    """
    out: list[ParticipationContext] = []
    book = Book()
    for src in sources(snapshot, frontier, upto=upto):
        ctx = book.assess(src)
        out.append(ctx)
        book.record(ctx, src)
    return out


def census(contexts) -> dict:
    """§28. Named counts, and nothing hidden behind an average."""
    rel = [c for c in contexts if c.release is not None]
    out = {
        "candles": len(contexts),
        "candles with a release": len(rel),
        "releases total": sum(len(c.all_releases) for c in contexts),
        "simultaneous candles": sum(1 for c in contexts if c.simultaneous),
        "by scale": dict(Counter(x.scale for c in contexts for x in c.all_releases)),
        "by origin": dict(Counter(x.origin for c in contexts for x in c.all_releases)),
        "opportunity kind": dict(Counter(c.opportunity_kind for c in rel)),
        "participation": dict(Counter(c.participation for c in rel)),
        "controlling scale": dict(Counter(c.controlling_scale for c in contexts)),
        "release location": dict(Counter(c.release_location for c in rel)),
        "parent location": dict(Counter(c.parent_location for c in rel)),
        "current location at a release": dict(Counter(c.current_location for c in rel)),
    }
    missing: Counter = Counter()
    for c in rel:
        if c.participation == UNAVAILABLE:
            missing.update(c.reasons)
    out["missing facts"] = dict(missing)
    limits: Counter = Counter()
    for c in rel:
        if c.participation == CONSTRAINED:
            limits.update(c.reasons)
    out["named constraints"] = dict(limits)
    return out


__all__ = ["FLAT", "LONG", "SHORT", "POSITIONS", "opportunity_of",
           "Sources", "sources", "Book", "AVAILABLE", "CONSTRAINED", "UNAVAILABLE", "OUTCOMES", "NEW_THESIS",
           "NEW_GENERATION_RELEASE", "SAME_GENERATION_CONTINUATION",
           "SAME_GENERATION_REPEAT", "NO_OPPORTUNITY", "OPPORTUNITIES", "ENTRY_SHAPED",
           "ParticipationContext", "assess", "eye", "census", "EYE_HEAD",
           "EXEC_UNAVAILABLE", "TRADE_CANDIDATE"]
