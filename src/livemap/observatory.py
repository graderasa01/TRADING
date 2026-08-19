"""The OBSERVATORY — one candle's complete state, as a trader would have seen it.

```
OBSERVATION → RELEASE → THESIS → PARTICIPATION → POSITION → BOUNDARY
                              ↓
                           Frame            ← this module
                              ↓
                    historical replay  |  live feed
```

This module **composes and copies**. It detects nothing, measures nothing, re-derives no
structure, no micro, no route, no release, no thesis and no invalidation, and it invents no
reason. Every field is read off a layer that already owns it. If a fact is absent the frame
says so by carrying `None` — it never substitutes a measurement.

## Why the geometry is captured incrementally, and not read back at the end

A visual tool is the easiest place in the whole system to leak the future, and it leaks in a
way no decision test would catch: `frontier.history()` at the end of a run returns every
node the frontier ever finalised, **including the ones finalised after the candle being
drawn**. Rendering those on candle *k* would show a trader a box that did not exist yet, and
the picture would look better than the system actually is.

So `frames()` drives the frontier candle by candle and freezes the node set at each step.
`test_the_geometry_of_frame_k_is_what_a_fresh_run_to_k_produces` rebuilds a fresh `Frontier`
fed only the first *k* candles and requires the two to be identical.

## Historical and live are the same code path, and that is enforced

`LiveSession` exists so a broker feed and a replay cannot drift into two engines. It holds
no fold of its own: on each candle it appends to the frontier and asks
`reactor.replay(..., upto=k)` for the answer, which the integration stage proved is
prefix-equal to a full run. Keeping a private incremental fold here would be a **second
position fold**, which is exactly what the previous stage established there must never be.
`test_the_live_session_and_the_batch_replay_agree_candle_for_candle` is the guard.

## Nothing here can execute

No broker, no order, no sizing, no risk, no options, no target, no stop. A frame carries the
`ExecutionRequest` the boundary produced, whose `execution_status` is `UNAVAILABLE` under
production's default contract. A paper position is opened only by an explicitly-named
research contract, and every frame carries the contract's name and its `validated` flag so a
rendered position can always be read as the paper position it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Frontier
from src.livemap.interpreter import Interpreter
from src.livemap import boundary as BD
from src.livemap import participation as PE
from src.livemap import position as POS
from src.livemap import postbreak as EP
from src.livemap import reactor as RE
from src.livemap import reference as REF
from src.livemap import release as R
from src.livemap import thesis as TH

# ── §8 REPLAY MODES. What the viewer is allowed to see, never what the engine
#    is allowed to read — the engine only ever sees candles up to the cursor. ──
BLIND = "BLIND"                 # future hidden, system answer hidden
SYSTEM = "SYSTEM"               # future hidden, system answer shown
AUDIT = "AUDIT"                 # system answer shown beside what happened after
MODES = frozenset({BLIND, SYSTEM, AUDIT})

#: What a position on screen actually is. There is no live mode and no live vocabulary.
PAPER = "PAPER"
RESEARCH = "RESEARCH"


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Box:
    """One structure as it stood at a candle. A copy, never a live reference."""

    id: str
    kind: str
    start: int
    end: int | None                 # None while the node is still live
    low: Decimal
    high: Decimal
    parent: str | None
    depth: int
    status: str                     # HISTORICAL | FINALISED | LIVE
    provisional: bool = False


@dataclass(frozen=True, slots=True)
class Geometry:
    """Everything drawable that existed **at this candle**, and nothing that did not."""

    index: int
    boxes: tuple[Box, ...] = ()
    micro_id: str | None = None
    micro_low: Decimal | None = None
    micro_high: Decimal | None = None
    micro_state: str | None = None
    micro_parent: str | None = None
    current_id: str | None = None
    band: tuple[Decimal, Decimal] | None = None
    break_level_up: Decimal | None = None
    break_level_down: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Why:
    """§4 — the reason, machine-readable and human-readable, from existing facts only.

    `codes` are vocabulary members that already exist somewhere in the stack;
    `lines` are those same codes said in English. Nothing here is a new claim, and
    nothing is ranked or weighted.
    """

    action: str
    codes: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    narrative: str = ""


@dataclass(frozen=True, slots=True)
class Frame:
    """One candle, complete. What a trader knew at that moment and what the system said."""

    index: int
    at: datetime
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal

    geometry: Geometry
    context: PE.ParticipationContext
    decision: RE.ParticipationDecision
    state: POS.PositionState
    request: BD.ExecutionRequest | None
    why: Why
    #: §24 — the reference hierarchy for this candle. Built here so historical replay and
    #: the live session cannot end up with two reference engines.
    reference: REF.ReferencePath | None = None
    events: tuple[str, ...] = ()
    contract: str = RE.NoExecution.name
    contract_validated: bool = False

    # ── convenience reads, so a renderer never re-derives ───────────────────
    @property
    def action(self) -> str:
        return self.decision.action

    @property
    def phase(self) -> str:
        return self.state.phase

    @property
    def position(self) -> str:
        return self.state.position_after

    @property
    def execution_status(self) -> str:
        return (self.request.execution_status if self.request is not None
                else self.decision.execution_status)

    @property
    def is_paper(self) -> bool:
        """A position on screen is always paper. There is no live execution path."""
        return self.state.phase != POS.FLAT_PHASE


# ═════════════════════════════════════════════════════════════════════════════
# §4 — THE WHY. Composed, never invented.
# ═════════════════════════════════════════════════════════════════════════════
_REASON_ENGLISH = {
    RE.R_NO_THESIS: "no structural event has set a direction",
    RE.R_WATCHING: "a thesis is live and nothing broke on this candle",
    RE.R_MISSING: "a required fact does not exist",
    RE.R_CONSTRAINED: "a named structural constraint applies",
    RE.R_CANDIDATE: "the context is complete and unobstructed",
    RE.R_THESIS_HOLDS: "the entry thesis is still the published one",
    RE.R_GENERATION_CHANGED: "the thesis identity changed",
    RE.R_IDEA_REVERSED: "the published thesis reversed direction",
    RE.R_THESIS_UNRESOLVED: "the thesis can no longer say which way it points",
    RE.R_NO_EXECUTION: "no validated execution rule exists — a candidate is not an order",
    PE.NO_RELEASE: "nothing broke on this candle",
    PE.NO_THESIS_FACT: "there is no thesis",
    PE.IDEA_UNRESOLVED: "the idea is unresolved",
    PE.NO_INVALIDATION: "the current generation has no invalidation reference",
    PE.NO_PATH: "nothing is mapped ahead of the broken boundary",
    PE.COUNTER_THESIS: "the release is counter to the current idea",
    PE.CONTRADICTION: "the thesis contradicts its own history",
    PE.CONTINUATION: "this continues a generation already live",
    PE.DUPLICATE: "this opportunity has already been counted",
    PE.POSITION_OPEN: "a position is already open on this thesis",
    PE.GAVE_IT_BACK: "price is back inside the structure that broke",
    PE.MULTI_SCALE_UNRESOLVED: "two scales released together",
}

_MANAGEMENT_ENGLISH = {
    POS.THESIS_STILL_VALID: "the entry thesis is unchanged",
    POS.SAME_THESIS_CONTINUATION: "the same thesis is continuing",
    POS.NEW_SAME_THESIS_RELEASE: "a new release on the same thesis",
    POS.MICRO_DEVELOPMENT: "the micro developed",
    POS.ROUTE_CHANGED: "the route now names a different reference",
    POS.CONTRADICTION: "the thesis contradicts its own history",
    POS.THESIS_CHANGED: "the thesis identity changed",
    POS.DIRECTION_CHANGED: "the direction changed",
    POS.THESIS_INVALIDATED: "the entry thesis is invalidated",
}


def why(decision: RE.ParticipationDecision, state: POS.PositionState) -> Why:
    """§4 — why this action, in codes and in English.

    Every code is a vocabulary member that already exists: a `reactor` reason, a
    `participation` constraint or missing fact, or a §16 management member. The English is
    a lookup on that code. **No fact is computed here and no reason is invented.**
    """
    codes: list[str] = list(decision.reasons)
    ev = state.evaluation

    if state.phase in (POS.HOLD, POS.CONTINUATION) and ev is not None:
        # A hold is justified by what did NOT change, so say that first.
        codes = ([RE.R_THESIS_HOLDS] if ev.thesis_generation_same else []) + \
            [m for m in ev.management if m != POS.THESIS_STILL_VALID] + \
            [r for r in decision.reasons if r != RE.R_THESIS_HOLDS]
    elif state.phase == POS.INVALIDATED and ev is not None:
        codes = list(decision.reasons) + [m for m in ev.developments]

    codes = list(dict.fromkeys(codes))

    lines: list[str] = []
    if state.phase in (POS.HOLD, POS.CONTINUATION) and ev is not None:
        ident = state.snapshot.identity if state.snapshot is not None else None
        if ev.thesis_generation_same and ident is not None:
            lines.append(f"same thesis identity — {ident}")
            lines.append(f"same generation ({ident.generation})")
        if ev.direction_same:
            lines.append("same direction")
        if not ev.entry_thesis_invalidated:
            lines.append("invalidation intact")
    elif state.phase == POS.INVALIDATED and ev is not None:
        snap = state.snapshot
        if snap is not None and not ev.thesis_generation_same:
            lines.append(f"thesis identity changed — {snap.identity} → "
                         f"{ev.current_identity or 'none'}")
            lines.append("the original thesis is no longer published")

    for code in codes:
        text = _REASON_ENGLISH.get(code) or _MANAGEMENT_ENGLISH.get(code)
        if text and text not in lines:
            lines.append(text)

    return Why(action=decision.action, codes=tuple(codes), lines=tuple(lines),
               narrative=RE.narrative(decision))


# ═════════════════════════════════════════════════════════════════════════════
# §5 — the event timeline. One line per thing that HAPPENED, never per candle.
# ═════════════════════════════════════════════════════════════════════════════
def events(ctx: PE.ParticipationContext, decision: RE.ParticipationDecision,
           state: POS.PositionState, previous: PE.ParticipationContext | None
           ) -> tuple[str, ...]:
    """What a trader would have written down on this candle. Presence of facts only."""
    out: list[str] = []
    for rel in ctx.all_releases:
        out.append(f"{rel.scale} RELEASE  {rel.boundary} "
                   f"{rel.direction.upper()} @ {float(rel.broken_edge):,.0f}")
    if ctx.simultaneous:
        out.append(f"MULTI-SCALE  {len(ctx.all_releases)} releases, controlling "
                   f"{ctx.controlling_scale}")
    if previous is not None and ctx.thesis_identity != previous.thesis_identity:
        if ctx.thesis_identity is not None:
            out.append(f"{'NEW THESIS' if previous.thesis_identity is None else 'THESIS CHANGE'}"
                       f"  {ctx.thesis_identity}")
    if ctx.opportunity_kind in PE.ENTRY_SHAPED:
        out.append(f"OPPORTUNITY  {ctx.opportunity_kind}")
    if decision.is_candidate:
        out.append(f"PARTICIPATION CANDIDATE  {decision.action.rsplit('_', 1)[-1]}")
    if state.phase == POS.OPEN:
        out.append(f"PAPER POSITION OPEN  {state.snapshot.side}  "
                   f"{state.snapshot.identity}")
    if state.phase == POS.CONTINUATION and state.evaluation is not None:
        out.append("CONTINUATION  " + ", ".join(state.evaluation.developments))
    if state.phase == POS.INVALIDATED:
        out.append(f"EXIT  {state.exit_reason}  {state.position} → FLAT")
    if (previous is not None and ctx.micro_state is not None
            and ctx.micro_state != previous.micro_state):
        out.append(f"MICRO  {ctx.micro_state}")
    return tuple(out)


# ═════════════════════════════════════════════════════════════════════════════
# geometry — frozen at the candle, never read back at the end
# ═════════════════════════════════════════════════════════════════════════════
def _geometry(f: Frontier, snapshot, index: int, reading) -> Geometry:
    """The node set as it stands **right now**, copied out of the live frontier.

    Called inside the candle loop, before any later candle exists. Nothing here filters a
    future node out after the fact — the future node has not been built yet.
    """
    boxes = [Box(id=n.id, kind=n.kind, start=n.start, end=n.end, low=n.low, high=n.high,
                 parent=n.parent, depth=n.depth, status="HISTORICAL",
                 provisional=bool(getattr(n, "provisional", False)))
             for n in snapshot.nodes]
    boxes += [Box(id=n.id, kind=n.kind, start=n.start, end=n.end, low=n.low, high=n.high,
                  parent=n.parent, depth=n.depth, status="FINALISED",
                  provisional=bool(getattr(n, "provisional", False)))
              for n in f.history()]
    cur = f.current
    if cur is not None:
        boxes.append(Box(id=cur.id, kind=cur.kind, start=cur.start, end=None,
                         low=cur.low, high=cur.high, parent=None, depth=0,
                         status="LIVE"))
    m = reading.micro if reading is not None else None
    return Geometry(
        index=index, boxes=tuple(boxes),
        micro_id=m.micro_id if m else None,
        micro_low=m.micro_low if m else None,
        micro_high=m.micro_high if m else None,
        micro_state=m.micro_state if m else None,
        micro_parent=m.parent_id if m else None,
        current_id=reading.node_id if reading is not None else None,
        band=reading.band if reading is not None else None,
        break_level_up=reading.break_level_up if reading is not None else None,
        break_level_down=reading.break_level_down if reading is not None else None)


def geometry_track(snapshot, history: Sequence, live: Sequence, **kw
                   ) -> tuple[Frontier, dict[int, Geometry]]:
    """Replay the frontier candle by candle, freezing the drawable state at each one.

    Returns the completed frontier — byte-identical to `frontier.run()`, because this is
    what `run()` does — and the per-candle geometry that `run()` throws away.
    """
    f = Frontier(snapshot, history, **kw)
    track: dict[int, Geometry] = {}
    for candle in live:
        f.on_candle(candle)
        reading = f.readings[-1] if f.readings else None
        if reading is not None:
            track[reading.index] = _geometry(f, snapshot, reading.index, reading)
    return f, track


# ═════════════════════════════════════════════════════════════════════════════
# HISTORICAL REPLAY
# ═════════════════════════════════════════════════════════════════════════════
def frames(snapshot, history: Sequence, live: Sequence, *,
           execution: RE.ExecutionContract | None = None, **kw) -> list[Frame]:
    """One `Frame` per closed candle, in order. The historical replay.

    The geometry is frozen per candle on the way through; the decision stack then runs on
    the completed frontier, which the integration stage proved is prefix-equal to running
    it at every cut point.
    """
    f, track = geometry_track(snapshot, history, live, **kw)
    return frames_of(snapshot, f, track, execution=execution)


def frames_of(snapshot, f: Frontier, track: dict[int, Geometry], *,
              execution: RE.ExecutionContract | None = None) -> list[Frame]:
    """Assemble frames from an already-replayed frontier and its geometry track."""
    execution = execution if execution is not None else RE.NoExecution()
    decisions = RE.replay(snapshot, f, execution=execution)
    states, _ = POS.lifecycle(snapshot, f, execution=execution)

    # §23 the map states this reference layer reads. `Interpreter._pool` filters
    # `n.end <= index`, so the node set at candle k is already the set that existed at k —
    # the same frozen-per-candle rule the geometry track holds, enforced upstream.
    interp = Interpreter(snapshot, f)
    mapstates = {s.index: s for s in interp.states()}

    out: list[Frame] = []
    previous: PE.ParticipationContext | None = None
    candles = {r.index: c for r, c in zip(f.readings, f.candles[-len(f.readings):])} \
        if len(f.candles) >= len(f.readings) else {}
    for d, st in zip(decisions, states):
        ctx = d.context
        candle = candles.get(d.index)
        req = BD.boundary_of(d, execution=execution,
                             snapshot=st.snapshot if st.phase == POS.OPEN else None)
        ms = mapstates.get(d.index)
        path = None
        if ms is not None:
            pool = interp.pool_at(d.index)
            path = REF.build(ms, {x.id: x for x in pool}, idea=ctx.idea,
                             invalidation_price=ctx.invalidation_price,
                             invalidation_rule=ctx.invalidation, pool=pool)
        out.append(Frame(
            index=d.index, at=d.at,
            o=candle.o if candle else d.price, h=candle.h if candle else d.price,
            l=candle.l if candle else d.price, c=candle.c if candle else d.price,
            geometry=track.get(d.index, Geometry(index=d.index)),
            context=ctx, decision=d, state=st, request=req,
            why=why(d, st), reference=path, events=events(ctx, d, st, previous),
            contract=execution.name, contract_validated=bool(execution.validated)))
        previous = ctx
    return out


# ═════════════════════════════════════════════════════════════════════════════
# LIVE — the same engine, driven one candle at a time
# ═════════════════════════════════════════════════════════════════════════════
class LiveSession:
    """A broker feed and a replay must be the same engine. This is that seam.

    Hand it closed candles one at a time; it returns the frame for each. It keeps **no
    position fold of its own** — `reactor.replay(upto=k)` answers, because the previous
    stage established there is exactly one fold and a private incremental copy here would
    be a second one that could disagree with it.

    The cost is that each candle re-folds the session from its start. On a 5-minute candle
    that is irrelevant, and correctness is not negotiable for the thing that decides whether
    live and replay are the same system.

    **This is market data only.** No order, no broker call, no size. The execution contract
    it is constructed with is `NoExecution` unless a research contract is explicitly named,
    and either way `boundary_of` is where it stops.
    """

    def __init__(self, snapshot, history: Sequence, *,
                 execution: RE.ExecutionContract | None = None, **kw) -> None:
        self.snapshot = snapshot
        self.execution = execution if execution is not None else RE.NoExecution()
        self.frontier = Frontier(snapshot, history, **kw)
        self.track: dict[int, Geometry] = {}
        self.frames: list[Frame] = []

    def on_candle(self, candle) -> Frame | None:
        """One closed candle in, one frame out. `None` if the frontier produced no reading."""
        self.frontier.on_candle(candle)
        if not self.frontier.readings:
            return None
        reading = self.frontier.readings[-1]
        if reading.index in self.track:
            return self.frames[-1] if self.frames else None
        self.track[reading.index] = _geometry(self.frontier, self.snapshot,
                                              reading.index, reading)
        self.frames = frames_of(self.snapshot, self.frontier, self.track,
                                execution=self.execution)
        return self.frames[-1] if self.frames else None

    @property
    def latest(self) -> Frame | None:
        return self.frames[-1] if self.frames else None


# ═════════════════════════════════════════════════════════════════════════════
# §7 — TRADER EYE. The mental checklist, answered from the frame.
# ═════════════════════════════════════════════════════════════════════════════
EYE_QUESTIONS = (
    "WHERE AM I?",
    "WHAT BROKE?",
    "WHICH SCALE?",
    "WHAT IS THE CURRENT THESIS?",
    "WHY PARTICIPATION?",
    "WHY HOLD?",
    "WHAT CHANGED?",
    "WHAT INVALIDATES?",
    "WHAT IS THE NEXT DEVELOPMENT?",
)


def trader_eye(frame: "Frame") -> list[tuple[str, str]]:
    """The nine questions, each answered from a fact the frame already carries.

    Every answer is a restatement. Where the stack has no fact the answer says so — a
    panel that fills a blank with a plausible sentence is the failure this whole
    architecture is built to avoid.
    """
    c, st = frame.context, frame.state

    def p(v, dp=0):
        return "—" if v is None else f"{float(v):,.{dp}f}"

    broke = " · ".join(f"{r.scale} {r.boundary} {r.direction.upper()} "
                            f"@ {p(r.broken_edge)}" for r in c.all_releases)
    if not broke:
        broke = (f"nothing — still holding {c.holding.scale} {c.holding.boundary} "
                 f"from c{c.holding.index}" if c.holding is not None
                 else "nothing structural on this candle")

    scale = c.controlling_scale
    if c.simultaneous:
        scale += f"  ({len(c.all_releases)} releases together: "                  + ", ".join(f"{r.scale}" for r in c.all_releases) + ")"
    if c.release_location is not None:
        scale += f"   {c.release_location} · {c.parent_location}"

    # WHY PARTICIPATION — the outcome and its named reasons, never a judgement
    part = f"{c.participation.replace('PARTICIPATION_', '')}   [{c.opportunity_kind}]"
    if c.reasons:
        part += "   " + ", ".join(c.reasons)
    if frame.decision.is_candidate:
        part = (f"CANDIDATE {frame.decision.action.rsplit('_', 1)[-1]} — " + part
                + f"   execution {frame.execution_status}")
    elif not c.entry_shaped and c.release is not None:
        part += "   (not entry-shaped)"

    # WHY HOLD — only meaningful while positioned; otherwise say there is no position
    if st.phase in (POS.HOLD, POS.CONTINUATION) and st.evaluation is not None:
        hold = "; ".join(frame.why.lines) or "the entry thesis is unchanged"
    elif st.phase == POS.INVALIDATED:
        hold = f"not holding — EXIT: {st.exit_reason}"
    elif st.phase == POS.OPEN:
        hold = "position opened on this candle; nothing to compare against yet"
    else:
        hold = "no position"

    # WHAT CHANGED — the §16 management vocabulary while positioned, the release
    # otherwise. Both are existing facts.
    if st.evaluation is not None:
        changed = ", ".join(st.evaluation.developments) or "nothing since the last candle"
    elif c.all_releases:
        changed = f"{c.opportunity_kind} — " + ", ".join(
            f"{r.scale} {r.boundary}" for r in c.all_releases)
    else:
        changed = c.current_state or "nothing"

    return [
        (EYE_QUESTIONS[0], f"{c.current_location}"
         + (f" {frame.geometry.current_id}" if frame.geometry.current_id else "")
         + (f"   pos {p(c.position_in_current, 2)}"
            if c.position_in_current is not None else "")),
        (EYE_QUESTIONS[1], broke),
        (EYE_QUESTIONS[2], scale),
        (EYE_QUESTIONS[3], f"{c.idea.replace('_IDEA', '')} generation {c.generation} "
                           f"{c.thesis_status}   {c.thesis_identity or '—'}"
         if c.generation else "none — no structural event has set a direction"),
        (EYE_QUESTIONS[4], part),
        (EYE_QUESTIONS[5], hold),
        (EYE_QUESTIONS[6], changed),
        (EYE_QUESTIONS[7], f"{c.invalidation or '—'}"
         + (f"   @ {p(c.invalidation_price)}   {p(c.invalidation_distance)} pts away"
            if c.invalidation_price is not None else "")),
        (EYE_QUESTIONS[8], c.next_expected
         + (f"   — path: next {c.next_reference}, free {p(c.free_to_near)}"
            if c.next_reference is not None else "   — nothing mapped ahead")),
    ]


# ═════════════════════════════════════════════════════════════════════════════
# §12 — the scenarios that must be seen, located on real candles
# ═════════════════════════════════════════════════════════════════════════════
SCENARIOS = {
    "A": "Outer breakout",
    "B": "Inner breakout inside an intact parent",
    "C": "Micro development",
    "D": "Same-structure re-break",
    "E": "Retest",
    "F": "Re-entry after a give-back",
    "G": "Generation change",
    "H": "Long → exit",
    "I": "Short → exit",
    "J": "Same-candle reverse prevention",
    "K": "Large box with an internal cluster",
    "L": "Space inside the box, internal structure breaking",
    "M": "No path ahead",
    "N": "Multi-scale release",
    "O": "Warm-up edge case — a release before any thesis",
}


def _nested(frame: Frame) -> tuple[str, str] | None:
    """A visible box that the **map itself** says sits inside another visible box.

    The K/L question, and it is answered with the map's own `parent`, not by comparing
    two bands here. The first version of this did compare bands — `big.low < small.low
    and small.high < big.high` plus a width ratio — and reported nesting on 284 of 300
    candles, because every live cluster sits numerically inside some warm-up structure
    somewhere. The map publishes 18 genuinely nested nodes in the whole teach sample.
    A layer re-deriving a fact another layer owns gets it wrong; that is the whole reason
    the rule exists.
    """
    visible = {b.id: b for b in frame.geometry.boxes}
    for box in frame.geometry.boxes:
        if box.parent and box.parent in visible:
            return (box.parent, box.id)
    return None


def scenarios(frames_: Sequence[Frame]) -> dict[str, list[int]]:
    """Every candle index that shows each scenario. Empty means it did not occur."""
    hits: dict[str, list[int]] = {k: [] for k in SCENARIOS}
    for i, fr in enumerate(frames_):
        c, st = fr.context, fr.state
        rels = c.all_releases
        if any(r.scale == R.OUTER for r in rels):
            hits["A"].append(fr.index)
        if any(r.scale == R.INNER for r in rels) and c.parent_location in (
                R.INSIDE_PARENT, R.AT_PARENT_EDGE):
            hits["B"].append(fr.index)
        if st.evaluation is not None and st.evaluation.micro_developed:
            hits["C"].append(fr.index)
        if (st.snapshot is not None and st.snapshot.identity is not None
                and any(r.broken_id == st.snapshot.identity.broken_id for r in rels)
                and st.evaluation is not None
                and st.evaluation.thesis_generation_same):
            hits["D"].append(fr.index)
        if c.current_state == EP.RETESTING:
            hits["E"].append(fr.index)
        if any(r.location == R.BACK_INSIDE for r in rels):
            hits["F"].append(fr.index)
        if (st.evaluation is not None and st.snapshot is not None
                and st.evaluation.current_identity is not None
                and st.snapshot.identity is not None
                and st.evaluation.current_identity.broken_id
                == st.snapshot.identity.broken_id
                and st.evaluation.current_identity.generation
                != st.snapshot.identity.generation):
            hits["G"].append(fr.index)
        if fr.decision.action == RE.EXIT_LONG:
            hits["H"].append(fr.index)
        if fr.decision.action == RE.EXIT_SHORT:
            hits["I"].append(fr.index)
        if st.phase == POS.INVALIDATED and c.idea not in ("", TH.NO_IDEA):
            hits["J"].append(fr.index)
        nest = _nested(fr)
        if nest is not None:
            hits["K"].append(fr.index)
            # L is K plus the internal structure actually giving way: an inner or micro
            # release whose OWN parent — `release.parent_id`, not a band comparison — is
            # a box on screen. That is "space inside the box, internal structure breaking".
            visible = {b.id for b in fr.geometry.boxes}
            if any(r.scale in (R.INNER, R.MICRO) and r.parent_id in visible
                   for r in rels):
                hits["L"].append(fr.index)
        if rels and c.next_reference is None:
            hits["M"].append(fr.index)
        if c.simultaneous and c.controlling_scale == R.MULTI_SCALE:
            hits["N"].append(fr.index)
        if rels and c.generation == 0:
            hits["O"].append(fr.index)
    return hits


__all__ = ["BLIND", "SYSTEM", "AUDIT", "MODES", "PAPER", "RESEARCH",
           "Box", "Geometry", "Why", "Frame", "why", "events",
           "geometry_track", "frames", "frames_of", "LiveSession",
           "EYE_QUESTIONS", "trader_eye", "SCENARIOS", "scenarios"]
