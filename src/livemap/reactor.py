"""
The REACTIVE PARTICIPATION ENGINE — the decision contract, and nothing else.

**No `ENTER_*`, no order, no broker, no sizing, no risk, no options, no
target, no trailing stop, no ATR stop, no threshold, no score, no probability, no
confidence.** Promoted from the research scratchpad after validation; this file is
canonical and the scratchpad copy re-exports it, so the two cannot diverge.
`EXECUTION_STATUS` is `UNAVAILABLE` by default and the engine emits a
`PARTICIPATION_CANDIDATE_*`, which is **not** an entry. `split.holdout()` is not called.

```
OBSERVATION -> RELEASE -> THESIS -> PARTICIPATION CONTEXT -> THIS -> HOLD / EXIT
```

## Participation is not execution, and the two are never collapsed

Four things are kept apart on every candle, because three of them can be true while the
fourth is not:

```
MARKET DEVELOPMENT       what the market did            ReleaseContext / EpisodeState
PARTICIPATION CONTEXT    whether the context is whole   livemap/participation.py
EXECUTION AVAILABILITY   whether timing is solved       ExecutionContract   <- still shut
POSITION ACTION          what to do about a position    this module
```

The engine may say `PARTICIPATION_CANDIDATE_LONG` and, on the same candle, `EXECUTION_STATUS
= UNAVAILABLE`. That is the honest state of the evidence: four 1m-trigger studies and two
participation studies produced no validated execution rule, and the last one found that
`PARTICIPATION_AVAILABLE` **did not predict outcome** (46.9% vs 50.0%). So a candidate is a
statement about structure, never about edge.

## The engine decides nothing about the market

Every input is an already-computed field. Nothing here measures, detects, re-derives or
scores. If a fact is missing the answer is `NO_TRADE` with the missing fact named, never a
substitute measurement.

## Position first, and entry is never considered while in

A candle that exits cannot also open. There is no `REVERSE`: a dead generation produces
`EXIT_LONG`, the next candle is `FLAT`, and a new opposite generation must earn its own
candidate independently. One hidden action would let a dead idea authorise a new position.

## The invalidation always belongs to the CURRENT generation

`exit_check` reads the **thesis identity** first — the broken structure, the generation and
the direction, audited over real data to be exactly the components that matter. A position
opened under a thesis that is no longer the published one is not a position in the current
thesis, and the old thesis's invalidation wording is never applied to a new one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.livemap import participation as PE
from src.livemap import release as R
from src.livemap import thesis as TH
from src.livemap.participation import FLAT, LONG, POSITIONS, SHORT

# ── ACTION — closed. No ENTER_*, and deliberately no REVERSE ─────────────────
NO_TRADE = "NO_TRADE"
WATCH = "WATCH"
CANDIDATE_LONG = "PARTICIPATION_CANDIDATE_LONG"
CANDIDATE_SHORT = "PARTICIPATION_CANDIDATE_SHORT"
HOLD_LONG = "HOLD_LONG"
HOLD_SHORT = "HOLD_SHORT"
EXIT_LONG = "EXIT_LONG"
EXIT_SHORT = "EXIT_SHORT"
ACTIONS = frozenset({NO_TRADE, WATCH, CANDIDATE_LONG, CANDIDATE_SHORT,
                     HOLD_LONG, HOLD_SHORT, EXIT_LONG, EXIT_SHORT})
CANDIDATES = frozenset({CANDIDATE_LONG, CANDIDATE_SHORT})

# ── STATUS — what the contract itself is doing ───────────────────────────────
ACTIVE = "ACTIVE"
BLOCKED = "BLOCKED"
INVALIDATED = "INVALIDATED"
UNAVAILABLE = "UNAVAILABLE"
STATUSES = frozenset({ACTIVE, BLOCKED, INVALIDATED, UNAVAILABLE})

# ── EXECUTION — a separate axis, and still shut ──────────────────────────────
EXEC_UNAVAILABLE = "UNAVAILABLE"
EXEC_PENDING = "PENDING"
EXEC_RESOLVED = "RESOLVED"
EXEC_NA = "NOT_APPLICABLE"
EXEC_STATES = frozenset({EXEC_UNAVAILABLE, EXEC_PENDING, EXEC_RESOLVED, EXEC_NA})

# ── reasons. Every one names an existing fact, never a bound ─────────────────
R_NO_THESIS = "NO_THESIS"
R_WATCHING = "THESIS_LIVE_NO_NEW_DEVELOPMENT"
R_MISSING = "REQUIRED_FACT_UNAVAILABLE"
R_CONSTRAINED = "STRUCTURALLY_CONSTRAINED"
R_CANDIDATE = "CONTEXT_COMPLETE_AND_UNOBSTRUCTED"
R_THESIS_HOLDS = "THESIS_HOLDS"
R_GENERATION_CHANGED = "GENERATION_CHANGED"
R_IDEA_REVERSED = "IDEA_REVERSED"
R_THESIS_UNRESOLVED = "THESIS_UNRESOLVED"
R_NO_EXECUTION = "NO_VALIDATED_EXECUTION_RULE_EXISTS"


# ═════════════════════════════════════════════════════════════════════════════
# The execution axis. Separate by construction, not by discipline.
# ═════════════════════════════════════════════════════════════════════════════
class ExecutionContract:
    """Whether execution timing is solved. **It is not.**

    Kept as an injected object rather than a flag so that the honest answer is the default
    and a research mode has to be asked for by name, in the call, where a reader sees it.
    """

    name = "abstract"
    validated = False

    def status(self, ctx) -> str:
        raise NotImplementedError

    def resolves(self, ctx) -> bool:
        raise NotImplementedError


class NoExecution(ExecutionContract):
    """The honest default. Four 1m-trigger studies and two participation studies produced
    no rule that survived teach -> validate, so timing is unresolved and the engine says
    so instead of inventing one."""

    name = "NoExecution"
    validated = False

    def status(self, ctx) -> str:
        return EXEC_UNAVAILABLE

    def resolves(self, ctx) -> bool:
        return False


class ImmediateExecution(ExecutionContract):
    """**Research only.** Assumes timing resolves at the candidate candle.

    It exists to exercise `HOLD` / `EXIT` and the position-aware rules, and it is not a strategy. `validated` is `False`
    and stays `False`; anything that reports performance from this mode is reporting an
    assumption.
    """

    name = "ImmediateExecution(research)"
    validated = False

    def status(self, ctx) -> str:
        return EXEC_RESOLVED

    def resolves(self, ctx) -> bool:
        return True


# ═════════════════════════════════════════════════════════════════════════════
def exit_check(position: str, open_identity, thesis) -> tuple[bool, str]:
    """Should an open position be closed? **Thesis identity first.**

    ## Why identity and not the generation integer

    `LiveThesis` publishes exactly one thesis per candle — the current episode's, at its
    current generation. If that thesis has a different identity from the one the position
    was opened on, the entry thesis is no longer published, no longer evaluated, and can
    never be reported alive again by anything in the stack. Continuing to hold is holding
    on a thesis the system has stopped tracking.

    The previous version compared `thesis.generation`, an integer. Audited over teach and
    validate, **14% of candle-to-candle thesis transitions carry an equal generation
    integer** — `L01` generation 1 giving way to `C08` generation 1 — so an integer
    comparison cannot see them at all. On real data that left 13.8% of held candles running
    under a thesis they were not opened on.

    ## What did NOT change

    A thesis *identity* change is not the same as a route change, a new inner release, a
    micro development or the same structure re-breaking. `ThesisIdentity` deliberately
    excludes the break index for exactly that reason, so those all remain `HOLD` — measured,
    not hoped: 176 teach groups re-break inside one identity.

    `IDEA_REVERSED` is kept as the *reason* whenever the direction is what changed, because
    that is what a trader needs to read; it is now a classification of an identity change
    rather than a separate branch.
    """
    identity = TH.identity_of(thesis)
    want = TH.LONG_IDEA if position == LONG else TH.SHORT_IDEA
    if identity != open_identity:
        return True, (R_IDEA_REVERSED if thesis.idea != want else R_GENERATION_CHANGED)
    if thesis.thesis_status == TH.STATUS_UNRESOLVED:
        return True, R_THESIS_UNRESOLVED
    return False, R_THESIS_HOLDS


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ParticipationDecision:
    """One candle's decision. Holds a reference to the context, never a copy of it."""

    index: int
    at: datetime
    price: Decimal
    #: The position **before** this candle's decision.
    position: str
    action: str
    status: str
    execution_status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    #: The context this decision was taken on. Not duplicated — §4.
    context: PE.ParticipationContext | None = None
    open_identity: TH.ThesisIdentity | None = None
    #: The causal opportunity identity, when this candle carried one.
    opportunity: tuple | None = None

    def __post_init__(self) -> None:
        if self.position not in POSITIONS:
            raise ValueError(f"unknown position {self.position!r}")
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.execution_status not in EXEC_STATES:
            raise ValueError(f"unknown execution status {self.execution_status!r}")
        if self.action in (HOLD_LONG, EXIT_LONG) and self.position != LONG:
            raise ValueError(f"{self.action} while {self.position}")
        if self.action in (HOLD_SHORT, EXIT_SHORT) and self.position != SHORT:
            raise ValueError(f"{self.action} while {self.position}")
        if self.action in CANDIDATES and self.position != FLAT:
            raise ValueError("a participation candidate requires a flat position — "
                             "entry is never considered while in")

    @property
    def is_candidate(self) -> bool:
        return self.action in CANDIDATES

    @property
    def would_execute(self) -> bool:
        """A candidate whose execution axis is resolved. False under `NoExecution`, which
        is the point: the structural answer and the timing answer are separate."""
        return self.is_candidate and self.execution_status == EXEC_RESOLVED

    def line(self) -> str:
        c = self.context
        return (f"c{self.index:<4} {float(self.price):>9,.1f} {self.position:<6}"
                f"{(c.idea.replace('_IDEA', '') if c else '—'):<6}"
                f"g{(c.generation if c else 0):<2}"
                f"{(c.current_state if c else ''):<18}"
                f"{self.action:<30}{self.status:<13}{self.execution_status:<14}"
                f"{(self.reasons[0] if self.reasons else ''):<40}")


HEAD = (f"{'cand':<5}{'price':>10} {'POS':<6}{'IDEA':<6}{'GEN':<3}{'STATE':<18}"
        f"{'ACTION':<30}{'STATUS':<13}{'EXECUTION':<14}REASON")


# ═════════════════════════════════════════════════════════════════════════════
# The state machine
# ═════════════════════════════════════════════════════════════════════════════
def decide(ctx: PE.ParticipationContext, thesis, *,
           execution: ExecutionContract) -> ParticipationDecision:
    """One candle. Pure function of `(context, thesis, execution contract)`.

    The order is §29's, and the first branch that applies **is** the answer:

    ```
    1  in a position?      exit if the current generation no longer supports it, else hold
    2  flat, no thesis?    NO_TRADE
    3  flat, nothing new?  WATCH
    4  flat, fact missing? NO_TRADE, naming the fact
    5  flat, constrained?  NO_TRADE, naming the constraint
    6  flat, complete?     PARTICIPATION_CANDIDATE, and the execution axis answers apart
    ```
    """
    common = dict(index=ctx.index, at=ctx.at, price=ctx.price, position=ctx.position,
                  context=ctx, open_identity=ctx.open_identity,
                  opportunity=ctx.opportunity)

    # ── 1 — holding something. Entry is not considered while in. ────────────
    if ctx.position != FLAT:
        leave, reason = exit_check(ctx.position, ctx.open_identity, thesis)
        if leave:
            return ParticipationDecision(
                action=EXIT_LONG if ctx.position == LONG else EXIT_SHORT,
                status=INVALIDATED, execution_status=EXEC_NA,
                reasons=(reason,), **common)
        return ParticipationDecision(
            action=HOLD_LONG if ctx.position == LONG else HOLD_SHORT,
            status=ACTIVE, execution_status=EXEC_NA,
            reasons=(R_THESIS_HOLDS,), **common)

    # ── 2 — flat, and nothing has established a direction ───────────────────
    if ctx.generation == 0 or ctx.idea not in (TH.LONG_IDEA, TH.SHORT_IDEA):
        return ParticipationDecision(action=NO_TRADE, status=UNAVAILABLE,
                                     execution_status=EXEC_NA,
                                     reasons=(R_NO_THESIS,) + ctx.reasons, **common)

    # ── 3 — flat, a thesis is live, and nothing broke on this candle ────────
    if ctx.release is None:
        return ParticipationDecision(action=WATCH, status=ACTIVE,
                                     execution_status=EXEC_NA,
                                     reasons=(R_WATCHING,), **common)

    # ── 4 / 5 — a release happened; the context says whether it is usable ───
    if ctx.participation == PE.UNAVAILABLE:
        return ParticipationDecision(action=NO_TRADE, status=UNAVAILABLE,
                                     execution_status=EXEC_NA,
                                     reasons=(R_MISSING,) + ctx.reasons, **common)
    if ctx.participation == PE.CONSTRAINED:
        return ParticipationDecision(action=NO_TRADE, status=BLOCKED,
                                     execution_status=EXEC_NA,
                                     reasons=(R_CONSTRAINED,) + ctx.reasons, **common)

    # ── 6 — the context is complete and unobstructed ────────────────────────
    #
    # `entry_shaped` is the opportunity identity talking: a continuation or a repeat is
    # management information, and `parteye` has already constrained it above. This is a
    # belt-and-braces refusal, not a second rule.
    if not ctx.entry_shaped:
        return ParticipationDecision(action=NO_TRADE, status=BLOCKED,
                                     execution_status=EXEC_NA,
                                     reasons=(R_CONSTRAINED, ctx.opportunity_kind),
                                     **common)

    status = execution.status(ctx)
    reasons = (R_CANDIDATE,) if status == EXEC_RESOLVED else (R_CANDIDATE, R_NO_EXECUTION)
    return ParticipationDecision(
        action=CANDIDATE_LONG if ctx.idea == TH.LONG_IDEA else CANDIDATE_SHORT,
        status=ACTIVE, execution_status=status, reasons=reasons, **common)


def replay(snapshot, frontier, *, execution: ExecutionContract | None = None,
           upto: int | None = None) -> list[ParticipationDecision]:
    """Fold the engine over a session. Prefix-causal: `upto=k` is prefix-equal to a full run.

    The carried state is `(position, open generation, what has been seen)` and nothing else,
    and it is updated **from the decision just taken** — never from the market.
    """
    execution = execution if execution is not None else NoExecution()
    out: list[ParticipationDecision] = []
    book = PE.Book()

    for src in PE.sources(snapshot, frontier, upto=upto):
        ctx = book.assess(src)
        d = decide(ctx, src.thesis, execution=execution)
        out.append(d)
        book.record(ctx, src)

        # ── the transition, applied after the decision, never before ────────
        if d.action in (EXIT_LONG, EXIT_SHORT):
            book.position, book.open_identity = FLAT, None
        elif d.would_execute:
            book.position = LONG if d.action == CANDIDATE_LONG else SHORT
            book.open_identity = ctx.thesis_identity
            if ctx.opportunity is not None:
                book.used.add(ctx.opportunity[0])
    return out


# ═════════════════════════════════════════════════════════════════════════════
# §22 — the human trader render, in the order the brief fixes
# ═════════════════════════════════════════════════════════════════════════════
def render(d: ParticipationDecision, symbol: str = "BANK NIFTY") -> list[str]:
    """WHAT HAPPENED -> WHERE PRICE IS -> WHAT THESIS -> WHAT PATH -> WHAT INVALIDATES
    -> WHETHER PARTICIPATION IS POSSIBLE -> WHETHER EXECUTION IS AVAILABLE."""
    c = d.context

    def p(v, dp=0):
        return "—" if v is None else f"{float(v):,.{dp}f}"

    out = [f"PRICE             {float(d.price):,.1f}   {d.at:%Y-%m-%d %H:%M}   {symbol}",
           f"POSITION          {d.position}"
           + (f"   opened on thesis {d.open_identity}"
              if d.open_identity else "")]

    if c is None:
        out.append(f"ACTION            {d.action}   [{d.status}]")
        return out

    out.append("THESIS            "
               + (f"{c.idea.replace('_IDEA', '')}   generation {c.generation}   "
                  f"{c.thesis_status}" if c.generation
                  else "none — no structural event has set a direction"))

    if c.all_releases:
        first = c.all_releases[0]
        out.append(f"NEW DEVELOPMENT   {first.scale} {first.broken_id} "
                   f"{first.boundary.split('.')[1].upper()} RELEASED "
                   f"{first.direction.upper()}")
        for rec in c.all_releases:
            # The boundary is named on EVERY line, not only the first: §11 requires the
            # decision to explain what happened at each scale, and a second release that
            # loses its structure id has not been explained.
            out.append(f"RELEASE           {rec.boundary}   scale = {rec.scale}   "
                       f"broken edge = {float(rec.broken_edge):,.0f}   "
                       f"parent = {rec.parent_id or '—'}   [{rec.origin}]")
        if c.simultaneous:
            # Two releases on one candle is simultaneity. It is only MULTI_SCALE when the
            # two are at DIFFERENT scales — two inner boundaries giving way together is
            # still INNER_CONTROLLING, and saying otherwise would misreport the scale.
            out.append(f"                  {len(c.all_releases)} releases on this "
                       f"candle, all kept; controlling scale is "
                       f"{c.controlling_scale}"
                       + ("  — two different scales released together and neither was "
                          "selected as 'best'"
                          if c.controlling_scale == R.MULTI_SCALE else ""))
    elif c.holding is not None:
        out.append(f"NEW DEVELOPMENT   none — still holding {c.holding.scale} "
                   f"{c.holding.boundary} from candle {c.holding.index}")
    else:
        out.append("NEW DEVELOPMENT   none on this candle")

    out.append(f"LOCATION          {c.current_location}"
               + (f"   pos {p(c.position_in_current, 2)}"
                  if c.position_in_current is not None else ""))
    if c.release_location is not None:
        out.append(f"                  {c.release_location}   "
                   f"{p(c.beyond_release)} pts beyond the broken edge")
        out.append(f"                  {c.parent_location}")
    out.append("MICRO             "
               + (f"{c.micro_state} {c.micro_view or ''}   {c.micro_rotations} rotations"
                  f"   last {c.micro_last_direction or '—'}"
                  if c.micro_id else "absent"))
    out.append(f"CURRENT STATE     {c.current_state}")

    if c.next_reference is not None:
        out.append(f"PATH              next reference = {c.next_reference}   "
                   f"free {p(c.free_to_near)} | depth {p(c.zone_depth)} | far "
                   f"{p(c.free_to_far)}")
        # The word the guard forbids does not appear even in the disclaimer — an absolute
        # check is worth more than a nuanced one, and §12 bans the vocabulary outright.
        out.append(f"                  far reference = {p(c.far_reference)}   "
                   f"{c.watch or ''}   (structure that exists ahead, never a promise)")
        if c.corridor:
            out.append("                  corridor " + " → ".join(c.corridor[:3]))
    else:
        out.append("PATH              nothing mapped ahead of the broken boundary")

    age = "—" if c.bars_since_break is None else str(c.bars_since_break)
    out.append(f"MOVE              {age} candles since the generation   "
               f"{p(c.excursion_travelled)} pts already travelled"
               + (f" ({c.excursion_atr:.2f} ATR)"
                  if c.excursion_atr is not None else ""))
    out.append(f"INVALIDATION      {c.invalidation or '—'}")
    if c.invalidation_price is not None:
        out.append(f"                  {p(c.invalidation_price)}   "
                   f"{p(c.invalidation_distance)} pts away")
    out.append(f"CONTRADICTION     {'YES' if c.contradicted else 'none'}")
    out.append(f"OPPORTUNITY       {c.opportunity_kind}")
    out.append(f"PARTICIPATION     {c.participation}"
               + (f"   [{', '.join(c.reasons)}]" if c.reasons else ""))
    out.append(f"ACTION            {d.action}   [{d.status}]")
    out.append(f"                  {', '.join(d.reasons)}")
    out.append(f"EXECUTION         {d.execution_status}"
               + ("   — no validated execution rule exists; a candidate is not an order"
                  if d.execution_status == EXEC_UNAVAILABLE else ""))
    return out


def narrative(d: ParticipationDecision) -> str:
    """§23 — the same facts as one machine-generated English sentence.

    Composed strictly from fields already on the decision. It is a readable restatement,
    never an extra claim, and it never says a word about what price will do next.
    """
    c = d.context
    if c is None:
        return "No context on this candle."
    bits: list[str] = []
    if c.all_releases:
        for rec in c.all_releases:
            where = ("the outer structure" if rec.scale == R.OUTER else
                     "an inner cluster" if rec.scale == R.INNER else "a micro")
            bits.append(f"{where} {rec.broken_id} released "
                        f"{'upward' if rec.up else 'downward'} through "
                        f"{float(rec.broken_edge):,.0f}")
        if c.parent_location == R.INSIDE_PARENT:
            bits.append(f"price is beyond the broken edge but still inside "
                        f"{c.all_releases[0].parent_id}")
        elif c.parent_location == R.BEYOND_PARENT:
            bits.append("price is beyond the parent as well")
    elif c.holding is not None:
        bits.append(f"nothing new broke; {c.holding.boundary} from candle "
                    f"{c.holding.index} is still held")
    else:
        bits.append("nothing structural happened on this candle")

    if c.generation:
        bits.append(f"the {c.idea.replace('_IDEA', '').lower()} generation "
                    f"{c.generation} is {c.thesis_status.lower()} and the market is "
                    f"{c.current_state.lower().replace('_', ' ')}")
    else:
        bits.append("no generation has established a direction")

    bits.append("there is a mapped path ahead" if c.next_reference is not None
                else "no structure is mapped ahead of the broken boundary")
    bits.append("no contradiction" if not c.contradicted
                else "the thesis contradicts its own history")
    if c.opportunity_kind != PE.NO_OPPORTUNITY:
        bits.append({PE.NEW_THESIS: "this is a new structural opportunity",
                     PE.NEW_GENERATION_RELEASE: "this is a new generation's opportunity",
                     PE.SAME_GENERATION_CONTINUATION:
                         "this continues an opportunity already live",
                     PE.SAME_GENERATION_REPEAT:
                         "this repeats an opportunity already counted"}[
                             c.opportunity_kind])
    tail = {NO_TRADE: "No trade.", WATCH: "Watching.",
            CANDIDATE_LONG: "A long participation candidate.",
            CANDIDATE_SHORT: "A short participation candidate.",
            HOLD_LONG: "Holding the long.", HOLD_SHORT: "Holding the short.",
            EXIT_LONG: "Exiting the long.", EXIT_SHORT: "Exiting the short."}[d.action]
    exec_tail = ("" if d.execution_status in (EXEC_NA, EXEC_RESOLVED)
                 else " Execution timing remains unavailable.")
    # A narrative that says "No trade" without saying why is not inspectable, which is the
    # one thing §23 asks this render to be.
    said = [r for r in d.reasons if r not in (R_CONSTRAINED, R_MISSING, R_CANDIDATE,
                                              R_NO_EXECUTION)]
    if d.action == NO_TRADE and said:
        word = "Blocked by" if d.status == BLOCKED else "Missing"
        tail += f" {word}: {', '.join(sorted(set(said))).lower().replace('_', ' ')}."

    def sentence(s: str) -> str:
        return (s[0].upper() + s[1:] + ".") if s else ""
    return " ".join(sentence(b) for b in bits) + f" {tail}{exec_tail}"


__all__ = ["FLAT", "LONG", "SHORT", "POSITIONS", "NO_TRADE", "WATCH", "CANDIDATE_LONG",
           "CANDIDATE_SHORT", "HOLD_LONG", "HOLD_SHORT", "EXIT_LONG", "EXIT_SHORT",
           "ACTIONS", "CANDIDATES", "ACTIVE", "BLOCKED", "INVALIDATED", "UNAVAILABLE",
           "STATUSES", "EXEC_UNAVAILABLE", "EXEC_PENDING", "EXEC_RESOLVED", "EXEC_NA",
           "EXEC_STATES", "ExecutionContract", "NoExecution", "ImmediateExecution",
           "ParticipationDecision", "decide", "replay", "render", "narrative", "HEAD",
           "exit_check", "replay_contexts", "R_GENERATION_CHANGED", "R_IDEA_REVERSED",
           "R_THESIS_UNRESOLVED", "R_THESIS_HOLDS", "R_NO_EXECUTION", "R_WATCHING",
           "R_MISSING", "R_CONSTRAINED", "R_CANDIDATE", "R_NO_THESIS"]


def replay_contexts(decisions) -> list:
    """The contexts behind a run, for a consumer that wants the observation only."""
    return [d.context for d in decisions]
