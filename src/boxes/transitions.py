"""
Structure-to-structure transitions — **measurement only.**

The replay said something uncomfortable: a structural break plus acceptance is close to a
coin flip, and *more* room ahead was not better — the widest-space bucket was the worst
one. So the question changes.

Not *"how far is the next structure?"* but:

```
C1  ────────?────────▶  C2
```

**how did price actually get from one shelf to the next?**

```
C1 60,400-60,430
       60,450  60,465  60,440  60,480  60,500  60,485
C2 60,520-60,550
```

There is no impulse there. The chain labels it a transition and moves on. But price did
travel a hundred points, in a particular way, taking a particular amount of time — and a
trader reading that chart sees a migration, not a nothing. Raw distance threw all of that
away, which may be exactly why raw distance showed no edge.

## What is classified, and out of what

Nothing new is detected here. Every field is read off the existing chain from
`structure.build_chain`, and the transition kind uses labels and measurements that already
exist:

| kind | test |
|---|---|
| `DIRECT` | nothing between the two shelves but seams |
| `GAP` | a session boundary between them |
| `IMPULSE` | the chain already labelled one of the connecting moves an impulse |
| `MIGRATION` | no impulse, but `er >= 0.5` — one-way travel that missed the impulse size gate |
| `ROTATION` | no impulse and `er < 0.5` — price wandered across rather than went |

`0.5` is Kaufman's midpoint, already the repo's one-way/rotational divide in
`adaptive.migration` and `structure.IMPULSE_MIN_ER`. **No new number is introduced, no
threshold is tuned, and nothing here is wired into the map or the Trader Reader.**

## The outcome question

Measured from the moment price **leaves** the destination shelf, in the direction the
transition travelled. Positive means the journey continued; negative means it reversed.
That is the question a trader actually asks on arrival: *"C1 se C2 aa gaye — ab C2 se
aage jayegi ya wapas?"*
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.boxes.adaptive import migration, overlap
from src.boxes.structure import Link, atr_at
from src.domain.models import ZERO, Candle

#: Kaufman's midpoint — already `structure.IMPULSE_MIN_ER`. Reused, not re-chosen.
ONE_WAY_ER = 0.5

KINDS = ("DIRECT", "GAP", "IMPULSE", "MIGRATION", "ROTATION")


@dataclass(frozen=True, slots=True)
class Transition:
    """One journey from a shelf to the next shelf, and what happened after it."""

    src_id: str
    dst_id: str
    src_low: Decimal
    src_high: Decimal
    dst_low: Decimal
    dst_high: Decimal
    dst_kind: str

    kind: str                 # DIRECT | GAP | IMPULSE | MIGRATION | ROTATION
    direction: str            # up | down
    relation: str             # higher | lower | overlapping

    edge_distance: Decimal    # gap between the facing edges; negative if they overlap
    center_distance: Decimal
    distance_atr: float
    bars: int                 # candles spent between the two shelves
    er: float                 # efficiency of the travel
    intermediate: int         # connecting move links, seams excluded
    revisit: bool             # the destination is a shelf price had already been in

    cont5: float | None = None
    cont10: float | None = None
    cont20: float | None = None

    @property
    def label(self) -> str:
        return f"{self.src_id}->{self.dst_id}"


def _relation(src: Link, dst: Link) -> str:
    if overlap((src.low, src.high), (dst.low, dst.high)) > 0:
        return "overlapping"
    return "higher" if dst.low > src.high else "lower"


def _outcome(candles: Sequence[Candle], at: int, direction: str,
             bars: int) -> float | None:
    j = at + bars
    if j >= len(candles):
        return None
    move = float(candles[j].c - candles[at].c)
    return move if direction == "up" else -move


def measure(chain: Sequence[Link], candles: Sequence[Candle]) -> list[Transition]:
    """Every adjacent structure pair in the chain, with the journey between them."""
    idx = [i for i, ln in enumerate(chain) if ln.is_structure]
    out: list[Transition] = []

    for a_pos, b_pos in zip(idx, idx[1:]):
        src, dst = chain[a_pos], chain[b_pos]
        between = [ln for ln in chain[a_pos + 1:b_pos] if ln.kind != "seam"]

        lo, hi = src.end, dst.start
        span = [k for k in candles[lo:hi + 1] if not k.synthetic]
        er = migration(span) if len(span) > 1 else 0.0
        net = candles[hi].c - candles[lo].c
        direction = "up" if net > 0 else "down"

        if any(ln.kind == "gap" for ln in between):
            kind = "GAP"
        elif not between:
            kind = "DIRECT"
        elif any(ln.is_impulse for ln in between):
            kind = "IMPULSE"
        elif er >= ONE_WAY_ER:
            kind = "MIGRATION"
        else:
            kind = "ROTATION"

        edge = (dst.low - src.high) if direction == "up" else (src.low - dst.high)
        atr = atr_at(candles, dst.start)

        # A destination price had already occupied is a different thing from new ground.
        revisit = any(overlap((dst.low, dst.high),
                              (chain[j].low, chain[j].high)) >= 0.5
                      for j in idx if j < a_pos)

        out.append(Transition(
            src_id=src.id, dst_id=dst.id,
            src_low=src.low, src_high=src.high,
            dst_low=dst.low, dst_high=dst.high, dst_kind=dst.kind,
            kind=kind, direction=direction, relation=_relation(src, dst),
            edge_distance=edge, center_distance=dst.mid - src.mid,
            distance_atr=float(abs(edge) / atr) if atr > ZERO else 0.0,
            bars=hi - lo, er=er, intermediate=len(between), revisit=revisit,
            cont5=_outcome(candles, dst.end, direction, 5),
            cont10=_outcome(candles, dst.end, direction, 10),
            cont20=_outcome(candles, dst.end, direction, 20)))
    return out


__all__ = ["ONE_WAY_ER", "KINDS", "Transition", "measure"]
