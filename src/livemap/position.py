"""
The trade thesis snapshot and the position lifecycle.

A reactive trader does not forget why a position exists after the entry candle. It carries
a thesis — *"I am participating because this structural event created this generation, at
this scale, with this parent, this broken boundary, this path and this invalidation"* — and
then asks the same question on every later candle: **is that thesis still alive?**

```
ParticipationDecision      what to do about a candle
        |
TradeThesisSnapshot        WHY the position exists. Frozen at the open, forever.
        |
PositionEvaluation         the entry thesis against the current market
        |
PositionState              FLAT · OPEN · HOLD · CONTINUATION · INVALIDATED
```

## This layer detects nothing and decides nothing about the market

It consumes `reactor.replay`'s decision stream and the contexts behind it. It re-derives no
structure, no micro, no route, no release, no thesis, no generation and no invalidation, and
it introduces no measurement. There is exactly one position fold in this repository —
`reactor.replay` — and this module reads it rather than running a second one.

## The snapshot is the point, and it never changes

The market keeps moving: the micro develops, an inner boundary releases, the route is
remeasured, a new generation is born. **None of that may touch the snapshot.** It is what
was known at the moment the position began, and the system must be able to answer *"why
does this position exist?"* without reconstructing it from later state.

`TradeThesisSnapshot` is frozen, holds only frozen objects, and
`test_a_snapshot_cannot_be_changed_by_the_market_moving_on` walks a real replay to prove it.

## Position is not market direction

A position exists **only** because a position-open event was explicitly provided. The market
may read `LONG_IDEA` while the position is `FLAT`, and `SHORT_IDEA` while the position is
still `LONG` — until the structural invalidation closes it. The two worlds are kept apart
deliberately, and a test asserts both cases occur on real data.

## Nothing here can open a position by itself

Production's default execution contract is `NoExecution`, which never resolves, so
`lifecycle()` run normally yields `FLAT` on every candle. A research position is opened only
by `ResearchPositionInjector`, which **must be handed the specific opportunity ids** to
open — it cannot be constructed to open everything, and it is not the default anywhere.

**No `ENTER_*`, no broker, no order, no sizing, no risk, no options, no target, no trailing
stop, no time stop, no profit lock.** The structural invalidation the thesis already carries
is the only thing that closes a position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from src.livemap import reactor as RE
from src.livemap import release as R
from src.livemap import thesis as TH
from src.livemap.participation import FLAT, LONG, POSITIONS, SHORT

# ── §8 the lifecycle. One phase per candle; `EXITED` is the record's terminal ─
FLAT_PHASE = "FLAT"
OPEN = "OPEN"
HOLD = "HOLD"
CONTINUATION = "CONTINUATION"
INVALIDATED = "INVALIDATED"
EXITED = "EXITED"
PHASES = frozenset({FLAT_PHASE, OPEN, HOLD, CONTINUATION, INVALIDATED})
RECORD_STATES = frozenset({OPEN, EXITED})

#: How the current generation kills a position. These are `reactor.exit_check`'s own
#: reasons, reused verbatim — §19 forbids a second vocabulary describing the same event.
EXIT_REASONS = frozenset({RE.R_GENERATION_CHANGED, RE.R_IDEA_REVERSED,
                          RE.R_THESIS_UNRESOLVED})

# ── §16 MANAGEMENT — what developed around a live position ──────────────────
#
# A closed vocabulary of existing facts. **No weights, no scores, no "weak"/"strong".**
# `ROUTE_CHANGED` covers what §16 lists as both "route changed" and "path changed": they
# are the same observation — the release-relative route now names a different reference —
# and two words for one fact is the redundancy the reason vocabularies keep refusing.
THESIS_STILL_VALID = "THESIS_STILL_VALID"
SAME_THESIS_CONTINUATION = "SAME_THESIS_CONTINUATION"
NEW_SAME_THESIS_RELEASE = "NEW_SAME_THESIS_RELEASE"
MICRO_DEVELOPMENT = "MICRO_DEVELOPMENT"
ROUTE_CHANGED = "ROUTE_CHANGED"
CONTRADICTION = "CONTRADICTION"
THESIS_CHANGED = "THESIS_CHANGED"
DIRECTION_CHANGED = "DIRECTION_CHANGED"
THESIS_INVALIDATED = "THESIS_INVALIDATED"
MANAGEMENT = frozenset({THESIS_STILL_VALID, SAME_THESIS_CONTINUATION,
                        NEW_SAME_THESIS_RELEASE, MICRO_DEVELOPMENT, ROUTE_CHANGED,
                        CONTRADICTION, THESIS_CHANGED, DIRECTION_CHANGED,
                        THESIS_INVALIDATED})

#: Which way price has to close for the entry thesis to die. A label over the rule the
#: thesis already carries, not a new rule: a long dies below its reference, a short above.
DIES_BELOW = "TWO_CLOSES_BELOW"
DIES_ABOVE = "TWO_CLOSES_ABOVE"


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class TradeThesisSnapshot:
    """**Why this position exists.** Frozen at the open and never updated.

    Releases are held as references to the frozen `Release` objects rather than copied
    field by field — they already carry the boundary, the parent, both locations, the route
    and the corridor, and re-copying them would create a second version of the same fact
    that could drift from the first.
    """

    opportunity_id: tuple
    side: str                       # LONG | SHORT — the position, not a market bias
    opened_at: datetime
    opened_index: int
    opened_price: Decimal

    # ── the thesis that produced it ─────────────────────────────────────────
    #: The thesis's own identity — `thesis.ThesisIdentity`, the single authoritative
    #: answer. Not a local tuple: §4 allows exactly one identity source, and a second
    #: calculation here is how two layers start disagreeing about the same candle.
    identity: TH.ThesisIdentity | None
    generation: int
    idea: str                       # LONG_IDEA | SHORT_IDEA
    thesis_status: str
    current_state_at_open: str
    #: The structure whose break created this thesis. Read off `identity`, which is why
    #: it is the thesis's and not the release's — for an inner release those differ, and
    #: the release's own is on `release.broken_id`.
    broken_structure_id: str | None

    # ── the release(s) that were the causal event. References, not copies. ──
    releases: tuple[R.Release, ...] = ()
    #: The one the decision was taken on. Always a member of `releases`.
    release: R.Release | None = None

    # ── the invalidation, as the current generation defined it AT THE OPEN ──
    invalidation_reference: Decimal | None = None
    invalidation_rule: str = ""
    invalidation_direction: str = ""

    # ── the path as it stood at the open ────────────────────────────────────
    micro_state_at_open: str | None = None
    next_reference_at_open: str | None = None
    far_reference_at_open: Decimal | None = None
    free_to_near_at_open: Decimal | None = None
    zone_depth_at_open: Decimal | None = None
    free_to_far_at_open: Decimal | None = None
    corridor_at_open: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.side not in (LONG, SHORT):
            raise ValueError(f"a position side must be {LONG}|{SHORT}, got {self.side!r}")
        if self.invalidation_direction not in ("", DIES_BELOW, DIES_ABOVE):
            raise ValueError(f"unknown invalidation direction "
                             f"{self.invalidation_direction!r}")
        if self.release is not None and self.release not in self.releases:
            raise ValueError("the decision's release must be one of the snapshot's")

    @property
    def release_scale(self) -> str | None:
        return self.release.scale if self.release is not None else None

    @property
    def broken_edge(self) -> Decimal | None:
        return self.release.broken_edge if self.release is not None else None

    @property
    def parent_structure_id(self) -> str | None:
        return self.release.parent_id if self.release is not None else None

    @property
    def release_location(self) -> str | None:
        return self.release.location if self.release is not None else None

    @property
    def parent_location(self) -> str | None:
        return self.release.parent_location if self.release is not None else None

    @classmethod
    def of(cls, decision: RE.ParticipationDecision) -> "TradeThesisSnapshot":
        """Freeze the reason a position is being opened, off the decision that opened it."""
        c = decision.context
        if c is None or not decision.is_candidate:
            raise ValueError("a snapshot may only be taken from a participation candidate")
        long = c.idea == TH.LONG_IDEA
        return cls(
            opportunity_id=c.opportunity, side=LONG if long else SHORT,
            opened_at=decision.at, opened_index=decision.index,
            opened_price=decision.price,
            identity=c.thesis_identity,
            generation=c.generation, idea=c.idea, thesis_status=c.thesis_status,
            current_state_at_open=c.current_state,
            broken_structure_id=(c.thesis_identity.broken_id
                                 if c.thesis_identity else None),
            releases=c.all_releases, release=c.release,
            invalidation_reference=c.invalidation_price,
            invalidation_rule=c.invalidation,
            invalidation_direction=DIES_BELOW if long else DIES_ABOVE,
            micro_state_at_open=c.micro_state,
            next_reference_at_open=c.next_reference,
            far_reference_at_open=c.far_reference,
            free_to_near_at_open=c.free_to_near, zone_depth_at_open=c.zone_depth,
            free_to_far_at_open=c.free_to_far, corridor_at_open=c.corridor)

    def lines(self) -> list[str]:
        def p(v, dp=0):
            return "—" if v is None else f"{float(v):,.{dp}f}"
        out = [f"ENTRY THESIS      {self.side}   generation {self.generation}   "
               f"opened c{self.opened_index} {self.opened_at:%Y-%m-%d %H:%M} "
               f"at {p(self.opened_price, 1)}"]
        for rel in self.releases:
            out.append(f"                  release {rel.scale} {rel.boundary} at "
                       f"{p(rel.broken_edge)}   parent {rel.parent_id or '—'}   "
                       f"[{rel.origin}]")
        out.append(f"                  state at open {self.current_state_at_open}   "
                   f"release location {self.release_location}   "
                   f"{self.parent_location}")
        out.append(f"                  path at open: next {self.next_reference_at_open}   "
                   f"free {p(self.free_to_near_at_open)} | depth "
                   f"{p(self.zone_depth_at_open)} | far {p(self.free_to_far_at_open)}")
        out.append(f"                  invalidation {p(self.invalidation_reference)}   "
                   f"{self.invalidation_direction}")
        out.append(f"                  {self.invalidation_rule or '—'}")
        out.append(f"                  thesis identity {self.identity}")
        return out


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class PositionEvaluation:
    """The entry thesis against the current market. **Relationships, not measurements.**

    Every field is a comparison of two facts that already exist. Nothing here reads price
    except through what the observation stack already published about it.
    """

    index: int
    at: datetime
    price: Decimal

    # ── the current market, copied ──────────────────────────────────────────
    current_generation: int
    current_identity: TH.ThesisIdentity | None
    current_idea: str
    current_state: str
    current_scale: str | None
    current_releases: tuple[R.Release, ...] = ()
    current_micro_state: str | None = None
    current_next_reference: str | None = None
    current_free_to_near: Decimal | None = None
    current_invalidation: Decimal | None = None
    current_location: str = TH.NO_STRUCTURE
    current_contradiction: bool = False

    # ── the delta, per §7 ───────────────────────────────────────────────────
    thesis_generation_same: bool = True
    direction_same: bool = True
    generation_changed: bool = False
    new_release_same_generation: bool = False
    new_release_new_generation: bool = False
    entry_thesis_invalidated: bool = False
    contradiction_present: bool = False
    #: The route is measured from a boundary that broke, so it exists only on a candle that
    #: carried a release. Absence is **not** a change — reporting it as one made almost
    #: every candle a CONTINUATION and hid the developments that were real.
    path_changed: bool = False
    path_unobserved: bool = False

    micro_developed: bool = False

    @property
    def management(self) -> tuple[str, ...]:
        """§16 — what developed around the position, from the closed vocabulary.

        Every member is the presence of an existing fact. Nothing is weighted and nothing
        is ranked; a consumer reading this gets what happened, not how much it matters.
        """
        out: list[str] = []
        if self.generation_changed:
            out.append(THESIS_CHANGED)
        if not self.direction_same:
            out.append(DIRECTION_CHANGED)
        if self.new_release_same_generation:
            out.append(NEW_SAME_THESIS_RELEASE)
        if self.micro_developed:
            out.append(MICRO_DEVELOPMENT)
        if self.path_changed:
            out.append(ROUTE_CHANGED)
        if self.contradiction_present:
            out.append(CONTRADICTION)
        if self.entry_thesis_invalidated:
            out.append(THESIS_INVALIDATED)
        elif not out:
            out.append(THESIS_STILL_VALID)
        elif not self.generation_changed and self.direction_same:
            out.insert(0, SAME_THESIS_CONTINUATION)
        return tuple(out)

    @property
    def developments(self) -> tuple[str, ...]:
        """The management members that describe a CHANGE, so a caller can ask *"did
        anything happen?"* without treating `THESIS_STILL_VALID` as an event."""
        return tuple(m for m in self.management
                     if m not in (THESIS_STILL_VALID, SAME_THESIS_CONTINUATION))

    def lines(self) -> list[str]:
        def p(v, dp=0):
            return "—" if v is None else f"{float(v):,.{dp}f}"
        out = [f"CURRENT MARKET    identity {self.current_identity or '—'}   "
               f"{self.current_idea.replace('_IDEA', '')}   {self.current_state}"]
        for rel in self.current_releases:
            out.append(f"                  new release {rel.scale} {rel.boundary} at "
                       f"{p(rel.broken_edge)}")
        out.append(f"                  micro {self.current_micro_state or 'absent'}   "
                   f"location {self.current_location}   "
                   + ("path not re-measured this candle — no release-relative route "
                      "without a release"
                      if self.path_unobserved else
                      f"path next {self.current_next_reference} "
                      f"free {p(self.current_free_to_near)}"))
        out.append(f"                  invalidation now {p(self.current_invalidation)}")
        out.append("THESIS RELATION   "
                   + ("identity unchanged" if self.thesis_generation_same
                      else "identity CHANGED"))
        out.append(f"                  direction "
                   f"{'unchanged' if self.direction_same else 'CHANGED'}   "
                   f"generation {self.current_generation}   "
                   f"entry thesis invalidated "
                   f"{'YES' if self.entry_thesis_invalidated else 'no'}")
        out.append(f"                  management: {', '.join(self.management)}")
        return out


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class PositionState:
    """One candle of the lifecycle. Exactly one phase, always."""

    index: int
    at: datetime
    price: Decimal
    phase: str
    position: str                   # the position BEFORE this candle's action
    action: str                     # the reactor's action, copied
    snapshot: TradeThesisSnapshot | None = None
    evaluation: PositionEvaluation | None = None
    exit_reason: str | None = None
    #: The position AFTER this candle's action, so a reader never has to infer it.
    position_after: str = FLAT

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ValueError(f"unknown lifecycle phase {self.phase!r}")
        if self.position not in POSITIONS or self.position_after not in POSITIONS:
            raise ValueError("unknown position")
        if self.exit_reason is not None and self.exit_reason not in EXIT_REASONS:
            raise ValueError(f"unknown exit reason {self.exit_reason!r}")
        if self.phase == INVALIDATED and self.position_after != FLAT:
            raise ValueError("an invalidated position must be flat afterwards")
        if self.phase == OPEN and self.snapshot is None:
            raise ValueError("an open carries its thesis snapshot")

    def lines(self) -> list[str]:
        out = [f"POSITION          {self.position}"
               + (f" → {self.position_after}" if self.position_after != self.position
                  else "")]
        if self.snapshot is not None:
            out.extend(self.snapshot.lines())
        if self.evaluation is not None:
            out.extend(self.evaluation.lines())
        out.append(f"POSITION ACTION   {self.action}   [{self.phase}]"
                   + (f"   {self.exit_reason}" if self.exit_reason else ""))
        return out

    def line(self) -> str:
        return (f"c{self.index:<4} {float(self.price):>9,.1f} {self.position:<6}"
                f"{self.phase:<14}{self.action:<30}"
                f"{(self.exit_reason or ''):<22}{self.position_after}")


HEAD = (f"{'cand':<5}{'price':>10} {'POS':<6}{'PHASE':<14}{'ACTION':<30}"
        f"{'EXIT REASON':<22}AFTER")


@dataclass
class PositionRecord:
    """One research position, from open to exit, with its causal timeline.

    The timeline is append-only: `test_the_timeline_never_rewrites_history` replays prefixes
    and checks that an entry, once written, is never changed.
    """

    snapshot: TradeThesisSnapshot
    state: str = OPEN
    closed_at: datetime | None = None
    closed_index: int | None = None
    exit_reason: str | None = None
    timeline: list[tuple[int, datetime, str, str]] = field(default_factory=list)

    def note(self, index: int, at: datetime, phase: str, detail: str) -> None:
        self.timeline.append((index, at, phase, detail))

    @property
    def bars_held(self) -> int | None:
        if self.closed_index is None:
            return None
        return self.closed_index - self.snapshot.opened_index

    def lines(self) -> list[str]:
        out = [f"POSITION RECORD   {self.snapshot.side}  generation "
               f"{self.snapshot.generation}  opened c{self.snapshot.opened_index}  "
               f"{self.state}"
               + (f"  closed c{self.closed_index} ({self.exit_reason})"
                  if self.closed_index is not None else "")]
        for index, at, phase, detail in self.timeline:
            out.append(f"    c{index:<5} {at:%H:%M}  {phase:<14} {detail}")
        return out


# ═════════════════════════════════════════════════════════════════════════════
# §9 / §31 — the only way a position is ever opened, and it is explicit
# ═════════════════════════════════════════════════════════════════════════════
class ResearchPositionInjector(RE.ExecutionContract):
    """Opens a research position on **named opportunities only**.

    §31: research injection must be explicit and isolated, never a flag inside the live
    path. So this is not a mode — it is an object that has to be handed the exact
    opportunity ids it may open, and it **cannot be constructed empty**. There is no way to
    ask it to open everything, and it is the default nowhere.

    Opening a position here is a *measurement device for the lifecycle*. It is not evidence
    that live entry should happen: the execution study measured no rule that earned one, so
    `validated` is `False` and stays `False`.
    """

    name = "ResearchPositionInjector"
    validated = False

    def __init__(self, opportunities: Iterable[tuple]) -> None:
        ids = frozenset(opportunities)
        if not ids:
            raise ValueError(
                "a research injector must be given the specific opportunities it may "
                "open. An empty injector would silently behave like NoExecution, and an "
                "'open everything' mode is what §31 forbids.")
        self.opportunities = ids

    def status(self, ctx) -> str:
        return (RE.EXEC_RESOLVED if ctx.opportunity in self.opportunities
                else RE.EXEC_UNAVAILABLE)

    def resolves(self, ctx) -> bool:
        return ctx.opportunity in self.opportunities


def candidates_in(decisions: Sequence[RE.ParticipationDecision]) -> list[tuple]:
    """Every opportunity a run offered. What an injector is chosen from."""
    return [d.opportunity for d in decisions
            if d.is_candidate and d.opportunity is not None]


# ═════════════════════════════════════════════════════════════════════════════
def evaluate(snapshot: TradeThesisSnapshot, decision: RE.ParticipationDecision,
             *, invalidated: bool) -> PositionEvaluation:
    """Compare the entry thesis with the current market. Neither is modified.

    `invalidated` comes from `reactor.exit_check`, which is the validated rule and applies
    the **current** generation's invalidation — never the dead generation's wording.
    """
    c = decision.context
    gen_same = c.thesis_identity == snapshot.identity
    dir_same = c.idea == snapshot.idea
    new_release = bool(c.all_releases)
    return PositionEvaluation(
        index=decision.index, at=decision.at, price=decision.price,
        current_generation=c.generation, current_identity=c.thesis_identity,
        current_idea=c.idea,
        current_state=c.current_state, current_scale=c.release_scale,
        current_releases=c.all_releases, current_micro_state=c.micro_state,
        current_next_reference=c.next_reference,
        current_free_to_near=c.free_to_near,
        current_invalidation=c.invalidation_price,
        current_location=c.current_location, current_contradiction=c.contradicted,
        thesis_generation_same=gen_same, direction_same=dir_same,
        generation_changed=not gen_same,
        new_release_same_generation=new_release and gen_same,
        new_release_new_generation=new_release and not gen_same,
        entry_thesis_invalidated=invalidated,
        contradiction_present=c.contradicted,
        micro_developed=(c.micro_state is not None
                         and c.micro_state != snapshot.micro_state_at_open),
        path_changed=(c.next_reference is not None
                      and c.next_reference != snapshot.next_reference_at_open),
        path_unobserved=c.next_reference is None)


def lifecycle(snapshot, frontier, *, execution: RE.ExecutionContract | None = None,
              upto: int | None = None) -> tuple[list[PositionState],
                                                list[PositionRecord]]:
    """One `PositionState` per candle, plus the records. Prefix-causal and deterministic.

    The decision stream is `reactor.replay`'s — this walks it and never runs a second
    position fold, so the lifecycle and the contract cannot disagree about where a position
    was. Under the default contract nothing opens and every candle is `FLAT`.
    """
    decisions = RE.replay(snapshot, frontier, execution=execution, upto=upto)
    states: list[PositionState] = []
    records: list[PositionRecord] = []
    live: PositionRecord | None = None

    for d in decisions:
        before = d.position
        after = before
        phase = FLAT_PHASE
        snap = evaluation = None
        reason = None

        if d.action in (RE.EXIT_LONG, RE.EXIT_SHORT):
            # §14: the current generation's own rule closed it. The reason is the
            # reactor's, copied — this layer does not re-decide the exit.
            reason = next((r for r in d.reasons if r in EXIT_REASONS), None)
            phase, after = INVALIDATED, FLAT
            snap = live.snapshot if live else None
            evaluation = evaluate(snap, d, invalidated=True) if snap else None
            if live is not None:
                live.state, live.closed_at = EXITED, d.at
                live.closed_index, live.exit_reason = d.index, reason
                live.note(d.index, d.at, INVALIDATED,
                          f"{reason} — exiting the {live.snapshot.side.lower()}")
                live = None

        elif d.action in (RE.HOLD_LONG, RE.HOLD_SHORT) and live is not None:
            snap = live.snapshot
            evaluation = evaluate(snap, d, invalidated=False)
            # §20: a position never exits merely because the market developed. A
            # development is reported, and the position keeps running.
            phase = CONTINUATION if evaluation.developments else HOLD
            if phase == CONTINUATION:
                live.note(d.index, d.at, CONTINUATION,
                          ", ".join(evaluation.developments))

        elif d.would_execute:
            snap = TradeThesisSnapshot.of(d)
            phase = OPEN
            after = snap.side
            live = PositionRecord(snapshot=snap)
            live.note(d.index, d.at, OPEN,
                      f"{snap.release_scale} {snap.release.boundary if snap.release else ''}"
                      f" · generation {snap.generation}")
            records.append(live)

        states.append(PositionState(
            index=d.index, at=d.at, price=d.price, phase=phase, position=before,
            action=d.action, snapshot=snap, evaluation=evaluation,
            exit_reason=reason, position_after=after))
    return states, records


def render(state: PositionState, symbol: str = "BANK NIFTY") -> list[str]:
    """§16 — the trader-readable comparison of entry thesis against current market."""
    out = [f"PRICE             {float(state.price):,.1f}   "
           f"{state.at:%Y-%m-%d %H:%M}   {symbol}"]
    out.extend(state.lines())
    return out


def active(states: Sequence[PositionState]) -> list[PositionState]:
    return [s for s in states if s.phase != FLAT_PHASE]


__all__ = ["MANAGEMENT", "THESIS_STILL_VALID", "SAME_THESIS_CONTINUATION",
           "NEW_SAME_THESIS_RELEASE", "MICRO_DEVELOPMENT", "ROUTE_CHANGED",
           "CONTRADICTION", "THESIS_CHANGED", "DIRECTION_CHANGED",
           "THESIS_INVALIDATED", "FLAT_PHASE", "OPEN", "HOLD", "CONTINUATION", "INVALIDATED", "EXITED",
           "PHASES", "RECORD_STATES", "EXIT_REASONS", "DIES_BELOW", "DIES_ABOVE",
           "FLAT", "LONG", "SHORT", "POSITIONS", "TradeThesisSnapshot",
           "PositionEvaluation", "PositionState", "PositionRecord",
           "ResearchPositionInjector", "candidates_in", "evaluate", "lifecycle",
           "render", "active", "HEAD"]
