"""
The Trader Decision Layer — observation in, IF/THEN out.

Five layers describe the market and none of them decides anything. `interpreter.py` says
where it stops:

> *"This module emits **what each price is** and lets a layer that knows what the position
> is decide which one invalidates it. That layer does not exist."*

This is that layer. It converts the observation stream into explicit decisions — and, far
more often, into `NO_TRADE` carrying the exact gate that stopped it, which CLAUDE.md §1
calls a successful output and §10 calls the most valuable dataset the system produces.

```
HISTORICAL MAP + LIVE FRONTIER + MICRO + EYE DELTA + POST-BREAK EPISODE + ROUTE
                                    |
                              TradeContext
                                    |
                       bias -> setup -> the gate chain
                                    |
                     TradeIntent   or   Rejection(gate)
```

## Inside the quarantine, deliberately

`test_livemap_quarantine.py` forbids `setups/ risk/ exits/ modes/ broker/ guards/
options/` from importing anything here, because *"this layer has zero outcome validation
whatsoever, and the fastest way for it to start losing money is for something on the
trading path to quietly start importing it."* A decision layer is exactly what that guard
was written against, so this module lives **inside** it and structurally cannot reach a
broker. Its product is the dataset that would justify lifting the quarantine; that lift is
a separate review with evidence attached.

## Phase E decides. It does not observe, and it does not execute.

Every input is an already-computed field of `Reading`, `MapState`, `MicroView`,
`EyeState`, `EpisodeState` or `SideReferences`. Nothing here measures the market. If a
fact is not already in the stream, the answer is that the decision cannot be made — not
that a new detector is needed. That is why three of the gates below are `UNAVAILABLE`
rather than implemented.

## `TradeIntent` is a research hypothesis, not an entry authorization

**It is not an order instruction and not a broker action, and no risk, stop, target, cost
or execution logic may read it as one.** It carries no size, quantity, limit, stop
distance or target; it always carries `unresolved`, the gates that were never evaluated,
so it cannot be read without also being handed what is still missing; and it is
deliberately not named `Signal` — `domain.Signal` is still untyped ("typed in P3") and
this module does not fill that hole.

## Four gate outcomes, and only one of them is PASS

```
PASS         evaluable, and satisfied
REJECT       evaluable, and failed — stops the chain and IS the output
MEASURED     inputs recorded, but no bound is active, so it CANNOT reject
UNAVAILABLE  the upstream fact does not exist — not evaluated, and NEVER a PASS
```

An intent means *"all currently evaluable required gates pass"*, and never a claim about
every gate there is. Reporting an `UNAVAILABLE` gate as a pass would assert a protection
that was never tested.

## Every threshold is null, and that is the design

`config/params.yaml` names them; all are `null`, so the freshness and space gates are
`MEASURED` — they record their inputs for every candidate and reject nothing. The first
teach-only replay therefore reports the distribution over an **unfiltered** population,
which is the only honest basis for choosing a number. `trader.py` already committed to
this: *"Space is reported, not gated… replay decides."*

## `src/setups/` is a cross-check, never a dependency

`A_flip_retest`, `B_sweep_reclaim` and `C_range_break_retest` are **labels for new
hypotheses expressed from this stack**, borrowed because the trader reasons in those
words. `src/setups/` is built on the older P1 stack and is never imported, called or
subclassed here — keeping the two apart is what makes comparing them worth anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.frontier import Frontier, Reading
from src.boxes.snapshot import MapSnapshot
from src.boxes.structure import BREAK_CLOSES
from src.domain.models import ZERO, Rejection
from src.livemap.eye import EyeState
from src.livemap.eye import observe as eye_observe
from src.livemap.interpreter import CorridorStop, Interpreter, MapState, ZoneRoute
from src.livemap.postbreak import REENTERING, RETESTING, EpisodeState
from src.livemap.postbreak import observe as episode_observe

# ── vocabularies, all closed ─────────────────────────────────────────────────
LONG_BIAS = "LONG_BIAS"
SHORT_BIAS = "SHORT_BIAS"
NO_BIAS = "NO_BIAS"
CONFLICTED = "CONFLICTED"
BIAS_VOCABULARY = frozenset({LONG_BIAS, SHORT_BIAS, NO_BIAS, CONFLICTED})

LONG = "long"
SHORT = "short"
SIDES = frozenset({LONG, SHORT})

#: Labels, not imports. See the module docstring.
SETUP_A = "A_flip_retest"
SETUP_B = "B_sweep_reclaim"
SETUP_C = "C_range_break_retest"
SETUPS = frozenset({SETUP_A, SETUP_B, SETUP_C})

PASS = "PASS"
REJECT = "REJECT"
MEASURED = "MEASURED"
UNAVAILABLE = "UNAVAILABLE"
GATE_OUTCOMES = frozenset({PASS, REJECT, MEASURED, UNAVAILABLE})
#: The two that are not a pass and not a rejection. Neither may ever be counted as PASS.
NOT_A_PASS = frozenset({MEASURED, UNAVAILABLE, REJECT})

#: Execution words. Narrower than `interpreter.FORBIDDEN`, which also bans LONG/SHORT —
#: this is the layer where a direction is legitimate. Anything presuming a position is not.
FORBIDDEN = ("ORDER", "SIZE", "LOTS", "QTY", "QUANTITY", "BROKER", "FILL", "MARGIN",
             "PREMIUM", "STRIKE")

#: Gates whose upstream fact does not exist in anything this module may read.
#: Each is a recorded missing upstream fact, discharged by the module that owns it.
UNAVAILABLE_GATES: tuple[tuple[str, str], ...] = (
    ("htf_close_proximity",
     "owned by guards/engine.py, which the quarantine puts out of reach; deriving it "
     "from the clock here would be a new measurement"),
    ("duplicate_setup",
     "needs SessionState.attempted_levels, which only execution writes"),
    ("session_max_trades",
     "needs SessionState.trades_taken, which only a fill writes"),
    ("session_consec_loss",
     "needs SessionState.consecutive_losses, which only a fill writes"),
    ("session_max_loss",
     "needs SessionState.cumulative_r, which only a fill writes"),
)

#: The two situations a trade may be considered in. `EXTENDING` is deliberately absent:
#: CLAUDE.md §2 is *"Takes only 3 setups, always on retest."*
TRADEABLE = frozenset({RETESTING, REENTERING})

HOLDS = "HOLDS"
INVALIDATED = "INVALIDATED"
THESIS_STATES = frozenset({HOLDS, INVALIDATED})

RECLAIMED = "two_closes_back_through_the_broken_edge"
BEYOND_SWEEP = "beyond_the_failed_sweep_extreme"


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Bounds:
    """The numbers, all `None`. Named in `config/params.yaml` under `decide:`.

    `load_config()` deliberately refuses to start until `session.risk_per_trade_rupees`,
    the cost model and the event calendar are set — correct for an engine, and fatal for a
    research layer that has to run on teach data today. So bounds are passed in, and
    `from_config` exists for when the engine can start.
    """

    max_bars_since_break: int | None = None
    min_free_to_near_atr: float | None = None
    min_zone_depth_atr: float | None = None
    min_free_to_far_atr: float | None = None

    @classmethod
    def from_config(cls, cfg) -> "Bounds":
        return cls(
            max_bars_since_break=cfg.get("decide.freshness.max_bars_since_break", None),
            min_free_to_near_atr=cfg.get("decide.space.min_free_to_near_atr", None),
            min_zone_depth_atr=cfg.get("decide.space.min_zone_depth_atr", None),
            min_free_to_far_atr=cfg.get("decide.space.min_free_to_far_atr", None))

    @property
    def space_active(self) -> bool:
        return any(v is not None for v in (self.min_free_to_near_atr,
                                           self.min_zone_depth_atr,
                                           self.min_free_to_far_atr))


@dataclass(frozen=True, slots=True)
class GateResult:
    """One link of the chain. `gate` is a `domain.models.GATES` member, verbatim."""

    gate: str
    outcome: str
    detail: str = ""
    #: What the gate looked at. Populated for `MEASURED` so the distribution can be
    #: reported over an unfiltered population.
    measured: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome not in GATE_OUTCOMES:
            raise ValueError(f"unknown gate outcome {self.outcome!r}")

    @property
    def stopped(self) -> bool:
        return self.outcome == REJECT


@dataclass(frozen=True, slots=True)
class TradeContext:
    """One candle, assembled. A zip of streams that are already index-aligned.

    Nothing here is computed: every field is a copy, and
    `test_the_context_computes_nothing` walks all of them against their sources.
    """

    index: int
    at: datetime
    price: Decimal
    atr: Decimal
    reading: Reading
    map: MapState
    eye: EyeState
    episode: EpisodeState | None = None

    # ── the route stays THREE facts per side, never one ──────────────────────
    #
    # `space_*` is the distance to the nearest *cluster* — a type label. `free_to_near` is
    # the distance to whatever price meets first in price order, and the corridor exists
    # because *"labels lie about order"*: a parent range's near edge can sit in front of
    # its own child's. Collapsing these would throw away the distinction `route.py` was
    # written to preserve.
    route_above: ZoneRoute | None = None
    route_below: ZoneRoute | None = None
    corridor_above: tuple[CorridorStop, ...] = ()
    corridor_below: tuple[CorridorStop, ...] = ()
    space_above: Decimal | None = None
    space_below: Decimal | None = None

    def route(self, side: str) -> ZoneRoute | None:
        """The route a trade on `side` faces."""
        return self.route_above if side == LONG else self.route_below

    def corridor(self, side: str) -> tuple[CorridorStop, ...]:
        return self.corridor_above if side == LONG else self.corridor_below


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """A research hypothesis. **Not an entry authorization, order or broker action.**

    Carries references — prices that already exist as structural facts — and never a
    distance, a target or anything that presumes a position. See the module docstring.
    """

    setup: str
    side: str
    #: The structural price that must hold for the idea to be alive.
    trigger: Decimal
    #: The structural price that ends it, and the rule by which it ends.
    invalidate: Decimal
    invalidate_rule: str
    episode_id: str
    broken_id: str
    #: Gates that were never evaluated. Always present, so an intent cannot be read
    #: without also being handed what is still missing.
    unresolved: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.setup not in SETUPS:
            raise ValueError(f"unknown setup {self.setup!r}")
        if self.side not in SIDES:
            raise ValueError(f"side must be long|short, got {self.side!r}")
        if self.invalidate_rule not in (RECLAIMED, BEYOND_SWEEP):
            raise ValueError(f"unknown rule {self.invalidate_rule!r}")

    #: Stated on the type, so nothing downstream has to infer it.
    executable: bool = False

    def lines(self) -> list[str]:
        return [f"HYPOTHESIS    {self.setup}  {self.side}",
                f"TRIGGER       {float(self.trigger):,.0f}  (a reference, not a level "
                f"to act on)",
                f"INVALIDATE    {float(self.invalidate):,.0f}  by {self.invalidate_rule}",
                f"UNRESOLVED    {', '.join(self.unresolved) or '—'}"]


@dataclass(frozen=True, slots=True)
class Verdict:
    """One candle's decision. Exactly one of `intent` / `rejection` is set."""

    index: int
    at: datetime
    price: Decimal
    bias: str
    gates: tuple[GateResult, ...] = ()
    intent: TradeIntent | None = None
    rejection: Rejection | None = None
    thesis: str | None = None       # for an intent still live from an earlier candle

    def __post_init__(self) -> None:
        if self.bias not in BIAS_VOCABULARY:
            raise ValueError(f"unknown bias {self.bias!r}")
        if (self.intent is None) == (self.rejection is None):
            raise ValueError(
                "exactly one of intent/rejection is required — CLAUDE.md §1: there is no "
                "third option, and a rejection carrying its gate is a successful output")
        if self.thesis is not None and self.thesis not in THESIS_STATES:
            raise ValueError(f"unknown thesis state {self.thesis!r}")

    @property
    def unavailable(self) -> tuple[str, ...]:
        return tuple(g.gate for g in self.gates if g.outcome == UNAVAILABLE)

    @property
    def evaluable(self) -> tuple[GateResult, ...]:
        """The gates that could actually have stopped something."""
        return tuple(g for g in self.gates if g.outcome in (PASS, REJECT))

    def lines(self) -> list[str]:
        out = [f"BIAS          {self.bias}"]
        if self.intent is not None:
            out.append("VERDICT       all currently evaluable required gates pass")
            out.extend(self.intent.lines())
        else:
            out.append(f"VERDICT       NO_TRADE — {self.rejection.gate}")
            if self.rejection.detail:
                out.append(f"REASON        {self.rejection.detail}")
        recorded = [g for g in self.gates if g.outcome == MEASURED]
        if recorded:
            out.append("MEASURED      " + "  ".join(
                f"{g.gate}[" + " ".join(f"{k}={v:,.1f}" for k, v in g.measured.items())
                + "]" for g in recorded))
        if self.unavailable:
            out.append(f"UNRESOLVED    {', '.join(self.unavailable)}  "
                       f"(not evaluated — never a pass)")
        if self.thesis is not None:
            out.append(f"THESIS        {self.thesis}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
# A — context assembly
# ─────────────────────────────────────────────────────────────────────────────
def contexts(frontier: Frontier, snapshot: MapSnapshot | None = None, *,
             upto: int | None = None) -> list[TradeContext]:
    """Zip the streams. No computation, no re-derivation."""
    snap = snapshot if snapshot is not None else frontier.snapshot
    maps = {s.index: s for s in Interpreter(snap, frontier).states()}
    eyes = {e.index: e for e in eye_observe(snap, frontier)}
    eps = {e.index: e for e in episode_observe(frontier, snap)}

    out: list[TradeContext] = []
    for reading in frontier.readings:
        i = reading.index
        if upto is not None and i > upto:
            break
        m = maps[i]
        out.append(TradeContext(
            index=i, at=m.at, price=m.price, atr=m.atr,
            reading=reading, map=m, eye=eyes[i], episode=eps.get(i),
            route_above=m.route_above, route_below=m.route_below,
            corridor_above=m.corridor_above, corridor_below=m.corridor_below,
            space_above=m.space_above, space_below=m.space_below))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# B — directional bias
# ─────────────────────────────────────────────────────────────────────────────
def _opposite(direction: str) -> str:
    return SHORT_BIAS if direction == "up" else LONG_BIAS


def _aligned(direction: str) -> str:
    return LONG_BIAS if direction == "up" else SHORT_BIAS


def conflicts(ctx: TradeContext, leaning: str) -> str:
    """Evidence pointing the other way, from fields that already exist. Empty if none.

    Conflict **never** resolves toward trading — there is no scoring and no tie-break, the
    same refusal `trader.py` makes with *"there is deliberately no `trade_score = 83`"*.
    """
    interaction = ctx.reading.interaction
    if leaning == LONG_BIAS and interaction in ("AT_LOWER_EDGE", "BREAK_ATTEMPT_DOWN"):
        return f"bias is long but price is {interaction}"
    if leaning == SHORT_BIAS and interaction in ("AT_UPPER_EDGE", "BREAK_ATTEMPT_UP"):
        return f"bias is short but price is {interaction}"
    micro = ctx.reading.micro
    if micro is not None:
        if leaning == LONG_BIAS and "MICRO_BREAK_DOWN" in micro.events:
            return "bias is long but the micro just broke down"
        if leaning == SHORT_BIAS and "MICRO_BREAK_UP" in micro.events:
            return "bias is short but the micro just broke up"
    return ""


def bias_of(ctx: TradeContext) -> tuple[str, str]:
    """`(bias, conflict_detail)`, read from the episode's **current** state.

    Never latched. A break that was re-entered and then left again from the same side is a
    break again, so `REENTERING` sets the opposite bias only for as long as it lasts:

        break up -> REENTERING -> back outside
        LONG_BIAS -> SHORT_BIAS -> LONG_BIAS

    `EpisodeState.returned_inside` is a different question — it is the episode's *history*,
    and it is what setup A's A4 condition reads. Bias says which way the market is leaning
    now; `returned_inside` says whether this retest is still trustworthy.
    """
    if ctx.episode is None:
        return NO_BIAS, ""
    direction = ctx.episode.episode.direction
    leaning = (_opposite(direction) if ctx.episode.state == REENTERING
               else _aligned(direction))
    detail = conflicts(ctx, leaning)
    return (CONFLICTED if detail else leaning), detail


# ─────────────────────────────────────────────────────────────────────────────
# C / D — which hypothesis, if any
# ─────────────────────────────────────────────────────────────────────────────
def setup_of(ctx: TradeContext) -> tuple[str, str] | None:
    """`(setup, side)` for the situation, or `None` if it is not a tradeable one.

    Symmetric by construction: `direction` is a parameter and no sign is hard-coded.
    """
    ep = ctx.episode
    if ep is None or ep.state not in TRADEABLE:
        return None
    direction = ep.episode.direction
    if ep.state == REENTERING:
        # the break failed; the structural event is the reclaim, so trade against it
        return SETUP_B, (SHORT if direction == "up" else LONG)
    setup = SETUP_C if ep.episode.kind == "range" else SETUP_A
    return setup, (LONG if direction == "up" else SHORT)


def references(ctx: TradeContext, setup: str) -> tuple[Decimal, Decimal, str]:
    """`(trigger, invalidate, rule)` — structural prices that already exist.

    `interpreter.py` refuses to emit invalidation because *"depending on the setup the real
    invalidation may be a range boundary, a retest low, an anchor, or the last defended
    level."* This layer knows the setup, so it can choose — and it chooses a named price,
    never a distance in points.
    """
    ep = ctx.episode.episode
    edge = ep.broken_edge
    if setup == SETUP_B:
        # the failed sweep's extreme: how far it got beyond the edge, in the break's own
        # direction, which `EpisodeState.max_excursion` already carries as a magnitude
        extreme = (edge + ctx.episode.max_excursion if ep.direction == "up"
                   else edge - ctx.episode.max_excursion)
        return edge, extreme, BEYOND_SWEEP
    return edge, edge, RECLAIMED


# ─────────────────────────────────────────────────────────────────────────────
# F — the gate chain
# ─────────────────────────────────────────────────────────────────────────────
def _unavailable() -> list[GateResult]:
    return [GateResult(g, UNAVAILABLE, detail) for g, detail in UNAVAILABLE_GATES]


def _freshness(ctx: TradeContext, bounds: Bounds) -> GateResult:
    bars = float(ctx.episode.bars_since_break)
    if bounds.max_bars_since_break is None:
        return GateResult("setup_stale", MEASURED,
                          "no bound set — recording only",
                          {"bars_since_break": bars})
    if bars > bounds.max_bars_since_break:
        return GateResult("setup_stale", REJECT,
                          f"{bars:.0f} bars since the break", {"bars_since_break": bars})
    return GateResult("setup_stale", PASS, "", {"bars_since_break": bars})


def _space(ctx: TradeContext, side: str, bounds: Bounds) -> GateResult:
    """Records three numbers. **Never rejects on one of them alone.**

    A thin gap in front of a deep zone and a thin gap in front of open air are completely
    different events, which is the distinction `route.py` exists to preserve.
    """
    route = ctx.route(side)
    measured: dict[str, float] = {"stops_ahead": float(len(ctx.corridor(side)))}
    if route is not None:
        measured.update({
            "free_to_near": float(route.free_to_near),
            "free_to_near_atr": route.free_to_near_atr,
            "zone_depth": float(route.zone_depth),
            "zone_depth_atr": route.zone_depth_atr,
            "free_to_far": float(route.free_to_far)})
    space = ctx.space_above if side == LONG else ctx.space_below
    if space is not None:
        measured["nearest_cluster"] = float(space)

    if not bounds.space_active:
        return GateResult("space_insufficient", MEASURED,
                          "no bound set — recording only", measured)
    # A bound is only ever applied to the whole picture, never to one magnitude.
    if route is None:
        return GateResult("space_insufficient", PASS, "open ahead", measured)
    fails = [
        name for name, value, floor in (
            ("free_to_near", route.free_to_near_atr, bounds.min_free_to_near_atr),
            ("zone_depth", route.zone_depth_atr, bounds.min_zone_depth_atr),
            ("free_to_far", measured.get("free_to_far"), bounds.min_free_to_far_atr))
        if floor is not None and value is not None and value < floor]
    if len(fails) == len([b for b in (bounds.min_free_to_near_atr,
                                      bounds.min_zone_depth_atr,
                                      bounds.min_free_to_far_atr) if b is not None]):
        return GateResult("space_insufficient", REJECT,
                          f"every active bound failed: {', '.join(fails)}", measured)
    return GateResult("space_insufficient", PASS, "", measured)


def decide(ctx: TradeContext, *, bounds: Bounds = Bounds(),
           live: TradeIntent | None = None) -> Verdict:
    """One candle. Pure: same `(ctx, bounds, live)`, same `Verdict`.

    The chain stops at the first `REJECT`, and that rejection **is** the output.
    """
    gates: list[GateResult] = []
    bias, conflict = bias_of(ctx)

    def stop(gate: str, detail: str) -> Verdict:
        gates.append(GateResult(gate, REJECT, detail))
        gates.extend(_unavailable())
        return Verdict(index=ctx.index, at=ctx.at, price=ctx.price, bias=bias,
                       gates=tuple(gates), thesis=_thesis(ctx, live),
                       rejection=Rejection(gate=gate, detail=detail, at=ctx.at,
                                           computed=_computed(gates)))

    # 1 — warmup
    if ctx.atr <= ZERO:
        return stop("warmup", "no ATR yet")
    gates.append(GateResult("warmup", PASS))

    # 2 — a structural event exists
    if ctx.episode is None:
        return stop("no_setup", "no structural event yet — nothing has broken")
    gates.append(GateResult("no_setup", PASS, "an episode exists"))

    # 3 — the situation is tradeable
    chosen = setup_of(ctx)
    if chosen is None:
        return stop("no_setup", f"{ctx.episode.state} is not a retest or a failed break")
    setup, side = chosen
    gates.append(GateResult("no_setup", PASS, f"{setup} {side}"))

    # 4 — bias
    if bias == CONFLICTED:
        return stop("bias_conflict", conflict)
    gates.append(GateResult("bias_conflict", PASS, bias))

    # 5 — A4: the edge was not reclaimed. A and C only; B *is* the reclaim.
    if setup in (SETUP_A, SETUP_C) and ctx.episode.returned_inside:
        return stop("no_setup",
                    "the broken edge was already reclaimed — this is a level being lost, "
                    "not a retest")
    if setup in (SETUP_A, SETUP_C):
        gates.append(GateResult("no_setup", PASS, "A4 holds"))

    # 6 — freshness, and 7 — room ahead. Both recorded; neither rejects while null.
    for gate in (_freshness(ctx, bounds), _space(ctx, side, bounds)):
        if gate.stopped:
            gates.append(gate)
            gates.extend(_unavailable())
            return Verdict(index=ctx.index, at=ctx.at, price=ctx.price, bias=bias,
                           gates=tuple(gates), thesis=_thesis(ctx, live),
                           rejection=Rejection(gate=gate.gate, detail=gate.detail,
                                               at=ctx.at, computed=_computed(gates)))
        gates.append(gate)

    gates.extend(_unavailable())
    trigger, invalidate, rule = references(ctx, setup)
    return Verdict(
        index=ctx.index, at=ctx.at, price=ctx.price, bias=bias, gates=tuple(gates),
        thesis=_thesis(ctx, live),
        intent=TradeIntent(
            setup=setup, side=side, trigger=trigger, invalidate=invalidate,
            invalidate_rule=rule, episode_id=ctx.episode.episode.id,
            broken_id=ctx.episode.episode.broken_id,
            unresolved=tuple(g for g, _ in UNAVAILABLE_GATES)))


def _computed(gates: Sequence[GateResult]) -> dict:
    out: dict[str, float] = {}
    for g in gates:
        out.update(g.measured)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# H — L1 only. L2 needs a position, L3 needs a broker; neither exists.
# ─────────────────────────────────────────────────────────────────────────────
def _thesis(ctx: TradeContext, live: TradeIntent | None) -> str | None:
    """Is an earlier hypothesis still alive? An observation, never an instruction.

    The rule is the repo's own two-close rule (`BREAK_CLOSES`), read off the episode that
    is already counting: `closes_back` for a retest that has been reclaimed, and the sweep
    extreme for a failed break.
    """
    if live is None or ctx.episode is None:
        return None
    if live.invalidate_rule == RECLAIMED:
        return (INVALIDATED if ctx.episode.closes_back >= BREAK_CLOSES else HOLDS)
    up = live.side == LONG
    beyond = (ctx.price > live.invalidate) if not up else (ctx.price < live.invalidate)
    return INVALIDATED if beyond else HOLDS


# ─────────────────────────────────────────────────────────────────────────────
def decide_all(frontier: Frontier, snapshot: MapSnapshot | None = None, *,
               bounds: Bounds = Bounds(), upto: int | None = None) -> list[Verdict]:
    """Fold over a finished frontier. Causal: `upto=k` is prefix-equal to a full run."""
    out: list[Verdict] = []
    live: TradeIntent | None = None
    for ctx in contexts(frontier, snapshot, upto=upto):
        verdict = decide(ctx, bounds=bounds, live=live)
        out.append(verdict)
        if verdict.intent is not None:
            live = verdict.intent
        elif verdict.thesis == INVALIDATED:
            live = None
    return out


def intents(verdicts: Sequence[Verdict]) -> list[Verdict]:
    return [v for v in verdicts if v.intent is not None]


def compact(v: Verdict) -> str:
    """One line per candle, for a scrollable trace."""
    what = (f"{v.intent.setup} {v.intent.side}" if v.intent
            else f"NO_TRADE {v.rejection.gate}")
    return (f"c{v.index:<4} {float(v.price):>9,.1f}  {v.bias:<11} {what:<28} "
            f"{v.thesis or ''}")


def order_shaped_fields() -> list[str]:
    """Any field of `TradeIntent` that presumes a position. Must always be empty."""
    banned = ("size", "qty", "quantity", "lots", "limit", "stop", "target", "price_limit",
              "risk", "reward", "capital")
    return [f.name for f in fields(TradeIntent)
            if any(b in f.name.lower() for b in banned)]


__all__ = ["LONG_BIAS", "SHORT_BIAS", "NO_BIAS", "CONFLICTED", "BIAS_VOCABULARY",
           "LONG", "SHORT", "SIDES", "SETUP_A", "SETUP_B", "SETUP_C", "SETUPS",
           "PASS", "REJECT", "MEASURED", "UNAVAILABLE", "GATE_OUTCOMES", "NOT_A_PASS",
           "FORBIDDEN", "UNAVAILABLE_GATES", "TRADEABLE", "HOLDS", "INVALIDATED",
           "THESIS_STATES", "RECLAIMED", "BEYOND_SWEEP", "Bounds", "GateResult",
           "TradeContext", "TradeIntent", "Verdict", "contexts", "bias_of", "conflicts",
           "setup_of", "references", "decide", "decide_all", "intents", "compact",
           "order_shaped_fields"]
