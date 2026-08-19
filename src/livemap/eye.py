"""
The per-candle live eye — what **changed** since the previous candle.

Every layer before this one restates the world each candle:

```
c412  60,462-60,507  INSIDE  MICRO_ROTATING  space above 246 pts
c413  60,462-60,507  INSIDE  MICRO_ROTATING  space above 241 pts
```

Two readings, and the fact a trader actually wants — *price is closing on the upper edge,
five points a candle, third candle running* — is in neither. It is recoverable only by
diffing them by hand, which means every consumer does it again, slightly differently. This
module does that diff once.

## It reads. It does not compute, and it does not decide.

Every value here is either **copied** from a `Reading` or a `MapState`, or is the
arithmetic difference between two such copies. There is no detector, no pool scan, no
threshold and no ranking. `position_in_micro` is the single computed value, and it is the
same arithmetic `Interpreter` already uses for `Current.position`, pointed at the micro's
own band.

That is why this module adds one file and modifies none: the major map cannot move,
because nothing that builds it is touched.

## A sibling of the Trader Reader, never a layer above it

```
Frontier ─► Reading ─┬─► Interpreter ─► MapState ─► Trader Reader ─► TraderState
                     │                     │
                     └─────────────────────┴─► Eye ─► EyeState        ← this module
```

`trader.py` reads `MapState`, which has no micro field, so a micro observation still
cannot reach the trading path. `retest.py` set this precedent exactly: a sibling consumer
of `Reading` with its own frozen observation type and its own closed vocabulary.

## Four ways a delta lies, refused in the type

```
1  None is not zero      space_above is None when there is nothing above — "khuli jagah".
                         246 -> None is not -246. It is not a number at all.
2  first is not flat     the first candle has no previous. Fabricating zeros would put a
                         measurement where there is none.
3  the subject moved     when the parent changes, position_in_current is measured against
                         a different band. Subtracting compares position in C21 with
                         position in R01. The values are still reported; only the
                         subtraction is refused.
4  the day ended         15:25 -> 09:15 is a gap, not a candle's worth of movement. Same
                         rule A' applied to `migration()`, applied here.
```

## The session boundary, measured

`A'` neutralised the overnight gap for `migration()` — *"the overnight jump itself is not
market movement, so it must never be measured as one"* — and the same exposure existed
here, unguarded, because this layer did not exist when `A'` was written. Over 29 replay
blocks:

```
delta across a session boundary   n=103    median 153.4 pts   p90 398.7   max 1,762.0
delta intraday                    n=8,568  median  17.9 pts   p90  55.8   max   355.6
```

The gap read as **8.6x a typical candle's move**, and 41 `closing` runs spanned a
boundary — so an overnight jump could extend, or entirely manufacture, a run that reads as
sustained pressure against an edge.

A boundary now refuses the subtraction and resets the run. **It is not converted to zero**:
a flat delta would claim price did not move, which is a different lie from the one being
fixed. The session is `Candle.session_date`, the same field `adaptive.migration(
session_aware=True)` compares — one definition of "a new day", not two.

## Edge pressure introduces no new words

The frontier already names the rungs — `INSIDE`, `AT_UPPER_EDGE`, `BREAK_ATTEMPT_UP` —
and `route.watch_state()` already has an approach ladder for the next zone. A fifth
vocabulary describing the same geometry is the collision A4 spent a phase untangling.

So edge pressure here is **measurements and their change**, and the rung stays the
frontier's own `interaction`. There is deliberately no `pressure = 0.87`: a single number
would hide exactly the fact that needs checking, which is `trader.py`'s own stated reason
for having no score.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.anchors import Anchor
from src.boxes.frontier import Frontier, Reading
from src.boxes.snapshot import MapSnapshot
from src.domain.models import ZERO, Candle
from src.livemap.interpreter import Interpreter, MapState

#: The locked `DELTA_FROM_PREVIOUS` shape, in order:
#:
#:     price  micro_high  micro_low  position  above_space  micro_state
#:
#: `position_in_micro` and `space_below` complete the two that were named one-sided; each
#: sits beside its partner, and the locked six keep their relative order so a consumer
#: written against the original list still reads them in the sequence it expects.
DELTA_FIELDS = ("price", "micro_high", "micro_low", "position_in_current",
                "position_in_micro", "space_above", "space_below", "micro_state")

#: Which subject each delta belongs to. A delta is only comparable while its subject keeps
#: its identity — this table is what makes rule 3 above mechanical rather than remembered.
#: `price` belongs to no structure, so it is always comparable.
_SUBJECT = {"price": None,
            "micro_high": "micro", "micro_low": "micro",
            "position_in_micro": "micro", "micro_state": "micro",
            "position_in_current": "node", "space_above": "node",
            "space_below": "node"}

#: Every state whose change is worth naming. All of them already exist upstream; none is
#: invented here.
TRACKED = ("state", "interaction", "market_state", "status", "node_id",
           "micro_view", "micro_state", "micro_id")

DIRECTIONS = frozenset({"up", "down", "flat", ""})
SIDES = frozenset({"upper", "lower"})

#: Why a subtraction was refused. Closed, and named rather than flagged: *"the previous
#: candle was yesterday"* and *"the box changed"* are different facts about the market and
#: a single boolean cannot tell a consumer which one it is looking at.
#:
#: Precedence, outermost first — a candle can satisfy several and reports the first:
#:
#:     NO_PREVIOUS       there is no earlier candle at all
#:     SESSION_BOUNDARY  the earlier candle was a different session
#:     SUBJECT_CHANGED   the parent or the micro is not the one it was
#:     MISSING_VALUE     one side is None
#:
#: `NO_PREVIOUS` and `MISSING_VALUE` leave `comparable` **True**: the two values are of the
#: same thing, one of them simply is not there. The other two set it `False`, because the
#: numbers describe different worlds.
COMPARABLE = ""
NO_PREVIOUS = "no_previous"
SESSION_BOUNDARY = "session_boundary"
SUBJECT_CHANGED = "subject_changed"
MISSING_VALUE = "missing_value"
REASONS = frozenset({COMPARABLE, NO_PREVIOUS, SESSION_BOUNDARY, SUBJECT_CHANGED,
                     MISSING_VALUE})
#: The two that mean *"these numbers are not about the same world"*.
INCOMPARABLE = frozenset({SESSION_BOUNDARY, SUBJECT_CHANGED})


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Delta:
    """One value and how it changed. Never a rating."""

    name: str
    before: Decimal | str | None = None
    after: Decimal | str | None = None
    #: `None` whenever the subtraction would be a lie — no previous candle, either side
    #: missing, the value is a word, or the subject changed underneath.
    change: Decimal | None = None
    direction: str = ""
    comparable: bool = True
    #: Why, when there is no `change`. Empty exactly when the subtraction stands.
    reason: str = COMPARABLE

    def __post_init__(self) -> None:
        if self.name not in DELTA_FIELDS:
            raise ValueError(
                f"unknown delta {self.name!r}. Add it to DELTA_FIELDS first — an ad-hoc "
                f"field makes the stream unanalysable, the same reason `TRACKED` and "
                f"`STATUS_VOCABULARY` are closed.")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"unknown direction {self.direction!r}")
        if self.change is not None and self.direction == "":
            raise ValueError("a measured change must say which way it went")
        if self.reason not in REASONS:
            raise ValueError(f"unknown reason {self.reason!r}")
        if (self.reason == COMPARABLE) != (self.change is not None):
            raise ValueError(
                f"{self.name}: a refused subtraction must say why, and a measured one "
                f"must not — reason {self.reason!r} with change {self.change!r}")
        if self.comparable != (self.reason not in INCOMPARABLE):
            raise ValueError(
                f"{self.name}: comparable={self.comparable} contradicts reason "
                f"{self.reason!r}")

    @property
    def moved(self) -> bool:
        return self.change is not None and self.change != 0

    def text(self) -> str:
        if self.change is None:
            return ""
        return f"{self.name} {float(self.change):+,.2f}".rstrip("0").rstrip(".")


@dataclass(frozen=True, slots=True)
class Transition:
    """A named state that is not what it was."""

    field: str
    before: str | None
    after: str | None

    def __post_init__(self) -> None:
        if self.field not in TRACKED:
            raise ValueError(f"untracked field {self.field!r}")

    def text(self) -> str:
        return f"{self.field} {self.before or '—'} → {self.after or '—'}"


@dataclass(frozen=True, slots=True)
class EdgePressure:
    """One side of the **current structure's own** boundary.

    `edge` is copied from `MapState.break_up` / `break_down`, never chosen here, so the
    rule that *"a 22460-22480 cluster breaks above 22480"* cannot be re-broken in this
    layer. The next reference is somewhere else entirely and is not an edge.

    Every field but `closing` is copied from upstream. `closing` is a tally over this
    module's own sequence — a count, in the same category as A3's `time_inside`, and
    **nothing reads it to make a decision.**
    """

    side: str
    edge: Decimal
    #: Signed. Positive is room still there; negative means price has closed beyond it,
    #: which is a `BREAK_ATTEMPT` and not yet a break.
    distance: Decimal
    distance_atr: float
    #: Consecutive candles this distance shrank. Resets to 0 the first candle it does not,
    #: and whenever the structure underneath changes.
    closing: int = 0
    touches: int = 0            # A3's live counter, off Reading.evidence
    closes_beyond: float = 0.0  # off Reading.measurements
    max_excursion: float = 0.0  # off Reading.measurements

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"unknown side {self.side!r}")

    def text(self) -> str:
        run = f"  closing {self.closing}" if self.closing else ""
        return (f"{self.side:<5} {float(self.distance):>8,.0f} pts "
                f"({self.distance_atr:+.1f} ATR)  touches {self.touches}{run}")


@dataclass(frozen=True, slots=True)
class EyeState:
    """One candle, read as a difference from the one before it."""

    index: int
    at: datetime
    price: Decimal
    #: No previous candle. Every `change` is `None`, and that is not the same as flat.
    first: bool = False
    #: `Candle.session_date` — the same field A′ compares. Carried so a consumer can group
    #: the stream by day without going back to the candles.
    session_date: date | None = None
    #: The previous candle was a different session. Every delta on this candle is refused
    #: with `SESSION_BOUNDARY` and every `closing` run restarts. The candle **after** this
    #: one compares normally, against this one.
    session_start: bool = False
    deltas: tuple[Delta, ...] = ()
    #: Empty when nothing changed — which is a fact, not a gap. *"The market did the same
    #: thing again"* is information a per-candle eye exists to report.
    transitions: tuple[Transition, ...] = ()
    upper: EdgePressure | None = None
    lower: EdgePressure | None = None
    # ── carried, not recomputed ──────────────────────────────────────────────
    node_id: str | None = None
    micro_id: str | None = None
    micro_view: str | None = None
    micro_state: str | None = None
    micro_low: Decimal | None = None
    micro_high: Decimal | None = None
    position_in_current: Decimal | None = None
    position_in_micro: Decimal | None = None
    space_above: Decimal | None = None
    space_below: Decimal | None = None
    space_above_atr: float = 0.0
    space_below_atr: float = 0.0
    watch_above: str | None = None
    watch_below: str | None = None
    interaction: str = ""
    state: str = ""
    market_state: str = ""
    status: str = ""
    #: The parent or the micro is not the one it was. Every delta whose subject moved is
    #: `comparable=False` on this candle.
    subject_changed: bool = False

    def __post_init__(self) -> None:
        if len(self.deltas) not in (0, len(DELTA_FIELDS)):
            raise ValueError(
                f"deltas must carry the whole DELTA_FIELDS set or none of it, got "
                f"{len(self.deltas)}. A partial set makes positional reads wrong.")
        if self.deltas and tuple(d.name for d in self.deltas) != DELTA_FIELDS:
            raise ValueError("deltas must be in DELTA_FIELDS order")

    def delta(self, name: str) -> Delta | None:
        return next((d for d in self.deltas if d.name == name), None)

    @property
    def moved(self) -> tuple[Delta, ...]:
        return tuple(d for d in self.deltas if d.moved)

    def lines(self) -> list[str]:
        out = [f"PRICE         {float(self.price):,.1f}"]
        if self.first:
            out.append("DELTA         — pehli candle, koi previous nahi")
        elif self.session_start:
            out.append("DELTA         — naya session, pichhli candle kal ki thi")
        else:
            moved = [d.text() for d in self.moved]
            out.append("DELTA         " + ("  ".join(moved) if moved else "kuchh nahi badla"))
        for ep in (self.upper, self.lower):
            if ep is not None:
                out.append(f"EDGE          {ep.text()}")
        pos = []
        if self.position_in_current is not None:
            pos.append(f"current {float(self.position_in_current) * 100:.0f}%")
        if self.position_in_micro is not None:
            pos.append(f"micro {float(self.position_in_micro) * 100:.0f}%")
        if pos:
            out.append("POSITION      " + "  ".join(pos))
        sa = ("khuli jagah" if self.space_above is None else
              f"{float(self.space_above):,.0f} pts ({self.space_above_atr:.1f} ATR)")
        sb = ("khuli jagah" if self.space_below is None else
              f"{float(self.space_below):,.0f} pts ({self.space_below_atr:.1f} ATR)")
        out.append(f"SPACE         upar {sa}   neeche {sb}")
        if self.micro_view:
            micro = f"{self.micro_view}"
            if self.micro_id:
                micro += f"  {self.micro_id} {self.micro_state}"
            out.append(f"MICRO         {micro}")
        out.append("CHANGED       " + (" · ".join(t.text() for t in self.transitions)
                                       or "—"))
        if self.subject_changed:
            out.append("SUBJECT       badal gaya — is candle ke deltas comparable nahi")
        return out


# ─────────────────────────────────────────────────────────────────────────────
def _delta(name: str, before, after, *, reason: str) -> Delta:
    """Subtract, or refuse to and say why. The four refusals from the docstring.

    `reason` arrives already resolved for the whole candle (no previous / session boundary
    / subject changed); this adds only the per-field one, `MISSING_VALUE`, and it is last
    in precedence because a value that is absent *and* from yesterday is from yesterday.
    """
    if reason == COMPARABLE and (before is None or after is None
                                 or isinstance(before, str) or isinstance(after, str)):
        reason = MISSING_VALUE
    if reason != COMPARABLE:
        return Delta(name, before, after, None, "", reason not in INCOMPARABLE, reason)
    change = after - before
    way = "flat" if change == 0 else ("up" if change > 0 else "down")
    return Delta(name, before, after, change, way, True, COMPARABLE)


def _position(price: Decimal, low: Decimal | None,
              high: Decimal | None) -> Decimal | None:
    """0 at the low edge, 1 at the high. **Not clamped.**

    `_third()` learned this the hard way: position runs outside `[0, 1]` the moment price
    closes beyond an edge, which is a normal `BREAK_ATTEMPT`, and clamping it to 1.0 reads
    as though price were still inside.
    """
    if low is None or high is None or high - low <= ZERO:
        return None
    return (price - low) / (high - low)


def _values(eye: EyeState) -> dict:
    """Everything a delta is taken over, read off the state that reported it.

    `EyeState` deliberately carries no back-reference to the `Reading` it came from — a
    state that can reach back into the frontier is a state that describes every candle
    using the last candle's world, which is the bug every layer here snapshots its fields
    to avoid. So each value a delta needs is a field, and the previous candle's numbers
    come from the previous candle's own state.
    """
    return {"price": eye.price,
            "micro_high": eye.micro_high, "micro_low": eye.micro_low,
            "position_in_current": eye.position_in_current,
            "position_in_micro": eye.position_in_micro,
            "space_above": eye.space_above, "space_below": eye.space_below,
            "micro_state": eye.micro_state}


def _pressure(side: str, edge: Decimal | None, price: Decimal, state: MapState,
              reading: Reading, previous: EdgePressure | None,
              same_subject: bool) -> EdgePressure | None:
    if edge is None:
        return None
    distance = (edge - price) if side == "upper" else (price - edge)
    closing = 0
    if same_subject and previous is not None and distance < previous.distance:
        closing = previous.closing + 1
    key = "upper_touches" if side == "upper" else "lower_touches"
    return EdgePressure(
        side=side, edge=edge, distance=distance,
        distance_atr=float(distance / state.atr) if state.atr > ZERO else 0.0,
        closing=closing,
        touches=int(reading.evidence.get(key, 0)),
        closes_beyond=float(reading.measurements.get("closes_beyond", 0.0)),
        max_excursion=float(reading.measurements.get("max_excursion", 0.0)))


def read(previous: EyeState | None, reading: Reading, state: MapState,
         candle: Candle) -> EyeState:
    """One candle against the one before it. Pure: same inputs, same output.

    `candle` is here for one field — `session_date`, the same one
    `adaptive.migration(session_aware=True)` compares. Deriving the session from
    `MapState.at` instead would work for this instrument and would be a second definition
    of "a new day" waiting to disagree with the first.
    """
    m = reading.micro
    micro_id = m.micro_id if m else None
    node_id = reading.node_id
    price = state.price
    position_in_micro = _position(price, m.micro_low if m else None,
                                  m.micro_high if m else None)

    same_session = (previous is not None
                    and previous.session_date == candle.session_date)
    session_start = previous is not None and not same_session
    same_node = previous is not None and previous.node_id == node_id and same_session
    same_micro = previous is not None and previous.micro_id == micro_id and same_session
    subject_changed = (previous is not None and same_session
                       and not (same_node and same_micro))

    # Precedence: no previous candle, then a new day, then a new box.
    whole_candle = (NO_PREVIOUS if previous is None else
                    SESSION_BOUNDARY if session_start else COMPARABLE)

    now = {"price": price,
           "micro_high": m.micro_high if m else None,
           "micro_low": m.micro_low if m else None,
           "position_in_current": m.position_in_current if m else None,
           "position_in_micro": position_in_micro,
           "space_above": state.space_above, "space_below": state.space_below,
           "micro_state": m.micro_state if m else None}
    was = _values(previous) if previous is not None else {}
    kept = {None: True, "node": same_node, "micro": same_micro}
    deltas = tuple(
        _delta(name, was.get(name), now[name],
               reason=whole_candle if whole_candle != COMPARABLE
               else COMPARABLE if kept[_SUBJECT[name]] else SUBJECT_CHANGED)
        for name in DELTA_FIELDS)

    fields_now = {"state": reading.state, "interaction": reading.interaction,
                  "market_state": state.market_state, "status": state.status,
                  "node_id": node_id, "micro_view": m.view if m else None,
                  "micro_state": m.micro_state if m else None, "micro_id": micro_id}
    transitions = ()
    if previous is not None:
        was_fields = {"state": previous.state, "interaction": previous.interaction,
                      "market_state": previous.market_state, "status": previous.status,
                      "node_id": previous.node_id, "micro_view": previous.micro_view,
                      "micro_state": previous.micro_state, "micro_id": previous.micro_id}
        transitions = tuple(Transition(f, was_fields[f], fields_now[f])
                            for f in TRACKED if was_fields[f] != fields_now[f])

    return EyeState(
        index=reading.index, at=state.at, price=price, first=previous is None,
        deltas=deltas, transitions=transitions,
        session_date=candle.session_date, session_start=session_start,
        # `same_node` already carries `same_session`, so a run cannot continue across a
        # boundary: 41 of them did before this guard, and an overnight jump could
        # manufacture what read as sustained pressure on an edge.
        upper=_pressure("upper", state.break_up, price, state, reading,
                        previous.upper if previous else None, same_node),
        lower=_pressure("lower", state.break_down, price, state, reading,
                        previous.lower if previous else None, same_node),
        node_id=node_id, micro_id=micro_id,
        micro_view=m.view if m else None, micro_state=m.micro_state if m else None,
        micro_low=m.micro_low if m else None, micro_high=m.micro_high if m else None,
        position_in_current=m.position_in_current if m else None,
        position_in_micro=position_in_micro,
        space_above=state.space_above, space_below=state.space_below,
        space_above_atr=state.space_above_atr, space_below_atr=state.space_below_atr,
        watch_above=state.route_above.watch if state.route_above else None,
        watch_below=state.route_below.watch if state.route_below else None,
        interaction=reading.interaction, state=reading.state,
        market_state=state.market_state, status=state.status,
        subject_changed=subject_changed)


def read_all(readings: Sequence[Reading], states: Sequence[MapState],
             candles: Sequence[Candle]) -> list[EyeState]:
    """Index-aligned by construction — `Interpreter.states()` is built from `readings`.

    `candles` is the frontier's **full** stream (history + live), indexed by
    `Reading.index`, so a reading's own candle is `candles[r.index]`.
    """
    if len(readings) != len(states):
        raise ValueError(f"{len(readings)} readings against {len(states)} states")
    out: list[EyeState] = []
    previous: EyeState | None = None
    for reading, state in zip(readings, states):
        previous = read(previous, reading, state, candles[reading.index])
        out.append(previous)
    return out


def observe(snapshot: MapSnapshot, frontier: Frontier, *,
            anchors: Sequence[Anchor] = ()) -> list[EyeState]:
    """Mirrors `interpreter.interpret()`."""
    interpreter = Interpreter(snapshot, frontier, anchors=anchors)
    return read_all(frontier.readings, interpreter.states(), frontier.candles)


def compact(eye: EyeState) -> str:
    """One line per candle, for a scrollable trace."""
    d = eye.delta("price")
    move = f"{float(d.change):+,.1f}" if d and d.change is not None else "—"
    up = (f"{float(eye.upper.distance):>6,.0f}"
          f"{'/' + str(eye.upper.closing) if eye.upper.closing else ''}"
          if eye.upper else "—")
    dn = (f"{float(eye.lower.distance):>6,.0f}"
          f"{'/' + str(eye.lower.closing) if eye.lower.closing else ''}"
          if eye.lower else "—")
    pos = (f"{float(eye.position_in_current) * 100:>4.0f}%"
           if eye.position_in_current is not None else "   —")
    changed = ",".join(t.field for t in eye.transitions) or "—"
    return (f"c{eye.index:<4} {float(eye.price):>9,.1f} {move:>8}  "
            f"^{up:<9} v{dn:<9} {pos}  {eye.micro_view or '—':<15} {changed}")


__all__ = ["DELTA_FIELDS", "TRACKED", "DIRECTIONS", "SIDES", "REASONS", "INCOMPARABLE",
           "COMPARABLE", "NO_PREVIOUS", "SESSION_BOUNDARY", "SUBJECT_CHANGED",
           "MISSING_VALUE", "Delta", "Transition", "EdgePressure", "EyeState",
           "read", "read_all", "observe", "compact"]
