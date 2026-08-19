"""
The Trader Reader — map facts in, watching-state out.

```
MAP  →  TRADER READER  →  TRADE STATE
```

The map describes reality. This interprets it. **It contains no detector of any kind** —
no clustering, no swings, no ranges. Every fact it reads was established by
`boxes/structure.py`, `boxes/frontier.py` and `livemap/interpreter.py`, and if a fact is
not in the `MapState` it is not available here.

## Four families, and nothing else

```
WAIT
BREAKOUT_LONG_CANDIDATE
BREAKOUT_SHORT_CANDIDATE
FAILED_BREAK_CANDIDATE
```

A **candidate is a situation worth examining, not an order.** There is no `ENTRY_READY`
here on purpose: entry needs more evidence than map interpretation alone, and inventing
it now would turn a description into an instruction.

## Location before direction

A trader does not open with *"upar jayega ya neeche?"*. The first question is *"main is
structure ke kahan hoon?"* — and in the interior of a range the honest answer to the
second question is that it has not been asked yet. Direction becomes trade-relevant only
after a **structural event**: never from candle colour, slope, or a run of green candles.

## The structure's own edges define the breakout

```
CURRENT = 60,417-60,452     BREAK_UP = 60,452    BREAK_DOWN = 60,417
NEXT ABOVE = 60,462-60,507  <- a reference. Never a breakout level.
```

## No score

There is deliberately no `trade_score = 83`. Every reason is preserved as a separate
field — `space_points`, `space_atr`, `arrival_direction`, `location`, `revisit`,
`next_reference`, `break_level` — so a human can see exactly which fact carried a
decision. A single number would hide precisely the thing that needs checking.

## Space is reported, not gated

```
break 60,452 -> next 60,698   space 246 pts / 11 ATR
break 60,452 -> next 60,455   space   3 pts / 0.1 ATR
```

Both are mechanically the same breakout and they are obviously not the same event. This
module **records the difference and refuses to rule on it**: a threshold picked now would
be fitted to the handful of examples that suggested it. Replay decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.domain.models import ZERO
from src.livemap.interpreter import MapState

WAIT = "WAIT"
BREAKOUT_LONG = "BREAKOUT_LONG_CANDIDATE"
BREAKOUT_SHORT = "BREAKOUT_SHORT_CANDIDATE"
FAILED_BREAK = "FAILED_BREAK_CANDIDATE"

FAMILIES = frozenset({WAIT, BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK})

#: Location comes first and is answered independently of direction.
LOCATIONS = frozenset({"INTERIOR", "UPPER_EDGE", "LOWER_EDGE", "OUTSIDE_STRUCTURE",
                       "IN_TRANSIT", "FORMING_STRUCTURE"})

#: Nothing in this layer may name an action.
FORBIDDEN = ("BUY", "SELL", "LONG_ENTRY", "SHORT_ENTRY", "ORDER", "SIZE", "STOP_LOSS")


@dataclass(frozen=True, slots=True)
class TraderState:
    """One candle, read as a trader would read it. Every field is evidence."""

    index: int
    at: datetime
    price: Decimal
    family: str
    location: str
    reason: str

    # the structure in play
    structure_id: str | None = None
    structure_low: Decimal | None = None
    structure_high: Decimal | None = None
    parent_id: str | None = None
    position_in_parent: Decimal | None = None
    revisit: bool = False

    # the event
    break_level: Decimal | None = None
    break_direction: str = ""
    failed_side: str = ""
    reentry_level: Decimal | None = None

    # the room ahead — reported, never gated
    next_reference_id: str | None = None
    next_reference_low: Decimal | None = None
    next_reference_high: Decimal | None = None
    space_points: Decimal | None = None
    space_atr: float = 0.0

    # how price got here
    arrival_from: str | None = None
    arrival_direction: str = ""
    transit_bars: int = 0

    interaction: str = ""
    market_state: str = ""

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unknown family {self.family!r}")
        if self.location not in LOCATIONS:
            raise ValueError(f"unknown location {self.location!r}")

    @property
    def is_candidate(self) -> bool:
        return self.family != WAIT

    def lines(self) -> list[str]:
        out = [f"STATE         {self.family}",
               f"LOCATION      {self.location}",
               f"REASON        {self.reason}"]
        if self.structure_id:
            band = ("?" if self.structure_low is None else
                    f"{float(self.structure_low):,.0f}-"
                    f"{float(self.structure_high):,.0f}")
            out.append(f"STRUCTURE     {self.structure_id}  {band}"
                       + (f"   inside {self.parent_id}" if self.parent_id else "")
                       + ("   REVISIT" if self.revisit else ""))
        if self.break_level is not None:
            out.append(f"BREAK_LEVEL   {float(self.break_level):,.0f} "
                       f"({self.break_direction or self.failed_side})")
        if self.next_reference_id and self.next_reference_low is not None:
            band = (f"{float(self.next_reference_low):,.0f}-"
                    f"{float(self.next_reference_high):,.0f}")
            out.append(f"NEXT_REF      {self.next_reference_id}  {band}")
        if self.space_points is not None:
            out.append(f"SPACE         {float(self.space_points):,.0f} pts "
                       f"/ {self.space_atr:.1f} ATR")
        if self.arrival_from:
            out.append(f"ARRIVAL       {self.arrival_from} "
                       f"({self.arrival_direction}), {self.transit_bars} bars transit")
        return out


# ─────────────────────────────────────────────────────────────────────────────
def _location(state: MapState) -> str:
    if state.current is None:
        if state.status == "FORMING":
            return "FORMING_STRUCTURE"
        return "IN_TRANSIT"
    if state.status in {"BREAK_ATTEMPT_UP", "BREAK_ATTEMPT_DOWN"}:
        return "OUTSIDE_STRUCTURE"
    if state.status == "APPROACHING_UPPER":
        return "UPPER_EDGE"
    if state.status == "APPROACHING_LOWER":
        return "LOWER_EDGE"
    return "INTERIOR"


def read(state: MapState) -> TraderState:
    """Deterministic. Four rules, in order, and everything else waits."""
    loc = _location(state)
    common = dict(index=state.index, at=state.at, price=state.price, location=loc,
                  interaction=state.interaction, market_state=state.market_state,
                  arrival_from=state.arrival.from_id,
                  arrival_direction=state.arrival.direction,
                  transit_bars=state.arrival.bars_in_transit)

    # ── accepted beyond an edge — the structure that broke is the one just left ──
    if state.status in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"} and state.left_id:
        up = state.status == "ACCEPTED_ABOVE"
        ref = state.above.next if up else state.below.next
        level = state.left_edge

        # Space is measured from the BREAK LEVEL, not from where price happens to be.
        space = None
        if ref is not None and level is not None:
            space = (ref.low - level) if up else (level - ref.high)
        return TraderState(
            family=BREAKOUT_LONG if up else BREAKOUT_SHORT,
            reason=f"accepted {'above' if up else 'below'} {state.left_id}'s own edge",
            structure_id=state.left_id,
            structure_low=state.left_low, structure_high=state.left_high,
            break_level=level, break_direction="up" if up else "down",
            next_reference_id=ref.id if ref else None,
            next_reference_low=ref.low if ref else None,
            next_reference_high=ref.high if ref else None,
            space_points=space,
            space_atr=float(space / state.atr) if space is not None
            and state.atr > ZERO else 0.0,
            **common)

    # ── went beyond, came back ──────────────────────────────────────────────
    if state.status == "BREAKOUT_FAILED" and state.current is not None:
        c = state.current
        # Which side failed is knowable from where price had to come back from.
        failed_up = state.price <= c.high
        opposite = state.below.next if failed_up else state.above.next
        return TraderState(
            family=FAILED_BREAK,
            reason="break attempt re-entered the structure",
            structure_id=c.id, structure_low=c.low, structure_high=c.high,
            parent_id=c.parent_id, position_in_parent=c.position_in_parent,
            revisit=c.status == "HISTORICAL",
            failed_side="up" if failed_up else "down",
            reentry_level=c.high if failed_up else c.low,
            next_reference_id=opposite.id if opposite else None,
            next_reference_low=opposite.low if opposite else None,
            next_reference_high=opposite.high if opposite else None,
            space_points=(state.space_below if failed_up else state.space_above),
            space_atr=(state.space_below_atr if failed_up else state.space_above_atr),
            **common)

    # ── everything else ─────────────────────────────────────────────────────
    c = state.current
    return TraderState(
        family=WAIT,
        reason={
            "INTERIOR": "range interior — no edge in play",
            "UPPER_EDGE": "at the upper edge, no break yet",
            "LOWER_EDGE": "at the lower edge, no break yet",
            "OUTSIDE_STRUCTURE": "beyond the edge, acceptance not confirmed",
            "IN_TRANSIT": "belonging to no structure",
            "FORMING_STRUCTURE": "a band is forming, not yet confirmed",
        }[loc],
        structure_id=c.id if c else None,
        structure_low=c.low if c else None,
        structure_high=c.high if c else None,
        parent_id=c.parent_id if c else None,
        position_in_parent=c.position_in_parent if c else None,
        revisit=bool(c and c.status == "HISTORICAL"),
        break_level=None,
        next_reference_id=state.above.next.id if state.above.next else None,
        next_reference_low=state.above.next.low if state.above.next else None,
        next_reference_high=state.above.next.high if state.above.next else None,
        space_points=state.space_above, space_atr=state.space_above_atr,
        **common)


def read_all(states: Sequence[MapState]) -> list[TraderState]:
    return [read(s) for s in states]


def compact(t: TraderState) -> str:
    sp = (f"{float(t.space_points):>6,.0f}pts/{t.space_atr:>5.1f}A"
          if t.space_points is not None else "            —")
    lvl = f"{float(t.break_level):,.0f}" if t.break_level is not None else "—"
    return (f"c{t.index:<4} {float(t.price):>9,.1f}  {t.family:<28} "
            f"{t.location:<18} {t.structure_id or '—':<5} {lvl:<9} {sp}")


__all__ = ["WAIT", "BREAKOUT_LONG", "BREAKOUT_SHORT", "FAILED_BREAK", "FAMILIES",
           "LOCATIONS", "FORBIDDEN", "TraderState", "read", "read_all", "compact"]
