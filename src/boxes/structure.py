"""
The historical structure map — Level B.

`adaptive.py` answers *"is there a cluster or a range in the last N candles?"* and
`mapper.py` streams that answer forward into a frozen box list. Both look at the right
edge of the chart. This module reads the **whole canvas**:

```
1000 candles  =  CANVAS      (history ko segments me todo)
8 -> 75       =  MICROSCOPE  (har segment ke andar structure dhoondo)
```

That separation is the whole point. The previous design used 75 candles as the horizon
when 75 is only the lens; a structure that formed three hundred candles ago was simply
invisible, so the map could never say *"price yahan se nikli thi, aur usse pehle wahan
baithi thi"*.

## The loop

Structures are found first. Whatever lies between two structures is connective tissue.

```
anchor = last candle
  |
  +-- structure mila?  -> uska ASLI start dhoondo (extend_back), emit, anchor = start-1
  +-- nahi mila?       -> peeche chalo jab tak mile; beech ka hissa = MOVE
```

Because the walk is strictly backward and every structure's `end` is the anchor it was
detected at, the segments come out as a **non-overlapping partition of the timeline**.

## No object is justified by a candle after its own end

A structure is detected *at* its `end` using a candle prefix, and `extend_back` only ever
walks backward. So every field produced here is a function of `candles[:end + 1]`.

`role` and `exit` are the exceptions — knowing which way price eventually left is a fact
about later candles. They live in `RETROSPECTIVE_FIELDS`, are computed in a separate pass
(`semantics.py` territory, step 2), and are excluded from the causality test.

## extend_back is the piece that did not exist before

In `mapper.py`, `Box.born` is the candle a structure became **detectable** — always late,
because a structure has to exist before a window can see it. History needs where it
actually **started**, and the failure mode to fear is over-extension:

```
        IMPULSE            CLUSTER
   ----------------+   +--------------+
                   +---+                    <- correct: two objects

   +----------------------------------+
   |      one giant merged box        |     <- over-extended extend_back
   +----------------------------------+
```

That is the exact bug this whole design exists to prevent, one layer down. The defence is
to reuse the repo's own break rule rather than invent a looser one: the walk stops on
**two consecutive closes** outside `[low - tol, high + tol]`. A directional leg cannot
survive that test, because it leaves the band within a couple of candles and never
returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Sequence

from src.boxes.adaptive import MIN_STEP, WINDOWS, Proposal, choose, migration
from src.domain.models import ZERO, Candle

WINDOW_MAX = max(WINDOWS)          # 75 — the microscope never reaches further than this
BREAK_CLOSES = 2                   # structural, same rule as mapper.py
ATR_BARS = 20
COARSE_STEP = 3                    # backward search stride before refinement

STRUCTURE_KINDS = frozenset({"cluster", "range"})
MOVE_KINDS = frozenset({"impulse_up", "impulse_down", "pullback", "transition",
                        "seam", "gap"})

#: A move shorter than the smallest microscope window, that also went nowhere, is below
#: the resolution of anything this system can see. It is the joint between two detections,
#: not a behaviour — on 2026-02-16 eleven such one-candle slivers were being reported as
#: "transition", which is a claim the data does not support. They stay in the partition
#: (coverage must remain exact) under their own name, and the narration skips them.
MIN_MOVE_BARS = min(WINDOWS)

#: Fields that knowingly read candles AFTER the node's own `end`. Everything not listed
#: here is causal — a pure function of `candles[:end + 1]` — and the causality test in
#: `tests/test_structure_map.py` pins that.
RETROSPECTIVE_FIELDS = frozenset({"exit", "role", "parent", "children", "depth",
                                  "location", "position_in_parent"})


# ─────────────────────────────────────────────────────────────────────────────
# measurements
# ─────────────────────────────────────────────────────────────────────────────
def atr_at(candles: Sequence[Candle], index: int, bars: int = ATR_BARS) -> Decimal:
    """Mean candle range over the `bars` real candles ending at `index`.

    Same definition `Mapper.atr` uses, expressed at an arbitrary index so the backward
    scan can ask *"what was volatility like there?"* rather than importing today's.
    """
    lo = max(0, index - bars + 1)
    recent = [k for k in candles[lo:index + 1] if not k.synthetic]
    if not recent:
        return ZERO
    return sum((k.h - k.l for k in recent), ZERO) / len(recent)


def tol_at(candles: Sequence[Candle], index: int, tol_atr: Decimal,
           bars: int = ATR_BARS) -> Decimal:
    return max(atr_at(candles, index, bars) * tol_atr, MIN_STEP)


def rotations_in(candles: Sequence[Candle], start: int, end: int,
                 low: Decimal, high: Decimal) -> list[tuple[str, int, int, Decimal]]:
    """Completed trips between the band's thirds, as `(direction, from_i, to_i, pts)`.

    Same thirds rule as `adaptive.traverses` and `Mapper._update`, but recorded with the
    indices so a rotation can later be attached to the nodes it travelled between.
    """
    width = high - low
    if width <= ZERO:
        return []
    lo_line = low + width / 3
    hi_line = high - width / 3
    out: list[tuple[str, int, int, Decimal]] = []
    state: str | None = None
    anchor: tuple[int, Decimal] | None = None
    for i in range(start, end + 1):
        k = candles[i]
        if k.synthetic:
            continue
        zone = "low" if k.c <= lo_line else "high" if k.c >= hi_line else None
        if zone is None:
            continue
        if state is not None and zone != state and anchor is not None:
            out.append((f"{state}->{zone}", anchor[0], i, abs(k.c - anchor[1])))
        if zone != state:
            state, anchor = zone, (i, k.c)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# extend_back — the true start of a structure
# ─────────────────────────────────────────────────────────────────────────────
def extend_back(candles: Sequence[Candle], low: Decimal, high: Decimal, anchor: int,
                tol: Decimal, *, break_closes: int = BREAK_CLOSES,
                floor: int = 0) -> int:
    """The first candle that belongs to the band `[low, high]`, walking back from `anchor`.

    Membership is **overlap** — the candle traded in the band, `k.l <= hi and k.h >= lo` —
    and the walk stops after `break_closes` consecutive candles that do not touch it at
    all. One candle away is not a boundary; that is why the counter resets.

    ## Why overlap and not the break rule

    The first version used the repo's break rule read backwards — two consecutive *closes*
    outside `[low - tol, high + tol]` — because that is what `mapper.py` uses for a break
    and reusing it added no parameter. Measured on 2026-02-16 it truncated structures to
    **a single candle**, twenty times in one canvas:

        C43 60,287-60,329  candle 524-524      C42 60,287-60,325  candle 523-523
        C41 60,290-60,327  candle 522-522      C40 60,291-60,326  candle 508-521

    That is one shelf reported as four. The cause is that a cluster's band comes from
    `core_band`, which is the tightest band holding **70%** of the window's minutes — a
    value area, not an envelope. Around a third of a cluster's own candles fall outside it
    by construction, so two in a row happens constantly *while price is still sitting
    there*. The break rule is the right test for leaving a frozen box and the wrong test
    for deciding when price began belonging to a band.

    Overlap is the repo's own existing answer to *"was price in this band?"* — the same
    test `adaptive.visits()` uses to count separate stays. A directional leg still fails
    it within a candle or two, because a candle a hundred points below the band does not
    touch it, so the over-extension guard this function exists for is unaffected.

    Never returns below `floor`, and never above `anchor`.
    """
    lo, hi = low - tol, high + tol
    start = anchor
    away = 0
    for i in range(anchor, floor - 1, -1):
        k = candles[i]
        if k.synthetic:
            continue
        if k.l <= hi and k.h >= lo:
            away = 0
            start = i
        else:
            away += 1
            if away >= break_closes:
                break
    return start


def last_touch(candles: Sequence[Candle], low: Decimal, high: Decimal, anchor: int,
               tol: Decimal, *, floor: int = 0, reach: int = WINDOW_MAX) -> int | None:
    """The newest candle at or before `anchor` that traded in `[low, high]`.

    ## Why this is needed — a proposal's anchor is not its end

    `choose()` answers *"is there a structure in the last N candles?"*, **not** *"is price
    in a structure right now?"*. A forty-candle window still dominated by a shelf price
    left eight candles ago returns that shelf. On 2026-02-16 at candle 443, price was
    trading at 60,380-60,409 and the detector correctly reported a cluster at
    60,271-60,309 — a real structure, ending 434, not 443.

    Assuming `end == anchor` turned that into eight consecutive one-candle clusters, one
    per anchor, each re-reporting the same shelf:

        C21 60,271-60,309  candle 443-443      C20 60,272-60,308  candle 442-442
        C19 60,275-60,307  candle 441-441      C18 60,274-60,307  candle 440-440

    So the structure's end is measured, not assumed, and the candles between it and the
    anchor become the move that left it — which is exactly what they were.

    Returns `None` when nothing within `reach` touched the band.
    """
    lo, hi = low - tol, high + tol
    for i in range(anchor, max(floor, anchor - reach) - 1, -1):
        k = candles[i]
        if not k.synthetic and k.l <= hi and k.h >= lo:
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# the raw timeline partition
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Segment:
    """One span of the timeline, before labelling and before nesting.

    `kind` is `"cluster"`, `"range"` or `"move"`. A move is unlabelled here on purpose —
    classifying it needs to know what came before it, which the backward scan does not
    have while it is running.
    """

    kind: str
    start: int
    end: int
    low: Decimal
    high: Decimal
    proposal: Proposal | None = None

    @property
    def bars(self) -> int:
        return self.end - self.start + 1

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def is_structure(self) -> bool:
        return self.kind in STRUCTURE_KINDS


def _span_band(candles: Sequence[Candle], start: int, end: int) -> tuple[Decimal, Decimal]:
    real = [k for k in candles[start:end + 1] if not k.synthetic]
    if not real:
        return ZERO, ZERO
    return min(k.l for k in real), max(k.h for k in real)


def _read_at(candles: Sequence[Candle], anchor: int, *, tol_atr: Decimal,
             min_score: float, first_index: int) -> tuple[Proposal | None, Proposal | None]:
    """`choose()` at one anchor.

    Only the last `WINDOW_MAX` candles are handed over: `choose` reads windows from the
    end of what it is given and never looks further back than 75, so this is the same
    answer as passing the whole prefix — at a fraction of the slicing cost, which matters
    because this runs once per candle of the canvas.
    """
    lo = max(first_index, anchor - WINDOW_MAX + 1)
    atr = atr_at(candles, anchor)
    if atr <= ZERO:
        return None, None
    return choose(candles[lo:anchor + 1], atr, tol_atr=tol_atr, min_score=min_score)


def scan_backward(candles: Sequence[Candle], *, tol_atr: Decimal = Decimal("0.25"),
                  min_score: float = 0.35, first_index: int = 0,
                  coarse_step: int = COARSE_STEP
                  ) -> tuple[list[Segment], list[Segment]]:
    """Partition `candles[first_index:]` into structures and the moves between them.

    Returns `(segments, parents)` in chronological order. `parents` holds the coarser
    range proposals seen alongside a cluster at the same anchor — they are not part of
    the linear chain, they are candidates for the containment tree in step 2.
    """
    n = len(candles)
    if n - first_index < min(WINDOWS):
        return [], []

    segments: list[Segment] = []
    parents: list[Segment] = []
    anchor = n - 1

    while anchor > first_index:
        cluster, rng = _read_at(candles, anchor, tol_atr=tol_atr, min_score=min_score,
                                first_index=first_index)
        pick = cluster or rng

        if pick is not None:
            tol = tol_at(candles, anchor, tol_atr)
            end = last_touch(candles, pick.low, pick.high, anchor, tol,
                             floor=first_index)

            if end is None:
                pick = None                      # band nothing near the anchor touched
            elif end < anchor:
                # The structure finished before the anchor. Hand the candles in between
                # to the move that left it, and re-read at the structure's real end —
                # the proposal taken there is the honest one.
                lo, hi = _span_band(candles, end + 1, anchor)
                segments.append(Segment("move", end + 1, anchor, lo, hi))
                anchor = end
                continue
            else:
                start = extend_back(candles, pick.low, pick.high, anchor, tol,
                                    floor=first_index)
                segments.append(Segment(pick.kind, start, anchor,
                                        pick.low, pick.high, pick))

                # The coarser structure seen at the same anchor is a parent candidate,
                # not a competitor. Recorded with its own extent for step 2's tree.
                if cluster is not None and rng is not None:
                    r_start = extend_back(candles, rng.low, rng.high, anchor, tol,
                                          floor=first_index)
                    parents.append(Segment(rng.kind, r_start, anchor,
                                           rng.low, rng.high, rng))

                anchor = start - 1
                continue

        # No structure here: walk back to the nearest candle that does have one.
        hit = _search_back(candles, anchor, tol_atr=tol_atr, min_score=min_score,
                           first_index=first_index, coarse_step=coarse_step)
        move_start = (hit + 1) if hit is not None else first_index
        if move_start > anchor:                       # degenerate, cannot happen twice
            break
        low, high = _span_band(candles, move_start, anchor)
        segments.append(Segment("move", move_start, anchor, low, high))
        if hit is None:
            break
        anchor = hit

    # The loop stops at `first_index`, so a structure whose start is `first_index + 1`
    # — or any `break` above — leaves the opening candles unclaimed. Nothing may fall off
    # the front: the partition has to tile the canvas exactly, or every layer above is
    # reading a timeline with a hole in it. Real data hid this for five sessions because
    # the oldest structure happened to start at index 0 each time.
    earliest = min((s.start for s in segments), default=len(candles))
    if earliest > first_index:
        lo, hi = _span_band(candles, first_index, earliest - 1)
        segments.append(Segment("move", first_index, earliest - 1, lo, hi))

    segments.reverse()
    parents.reverse()
    return segments, parents


def _search_back(candles: Sequence[Candle], anchor: int, *, tol_atr: Decimal,
                 min_score: float, first_index: int, coarse_step: int) -> int | None:
    """The largest index below `anchor` at which a structure exists, or `None`.

    Strided so the scan is not quadratic, then refined forward inside the stride — the
    refinement matters, because landing three candles early would hand those candles to
    the move instead of to the structure they belong to.
    """
    j = anchor - 1
    hit: int | None = None
    while j > first_index:
        c, r = _read_at(candles, j, tol_atr=tol_atr, min_score=min_score,
                        first_index=first_index)
        if c is not None or r is not None:
            hit = j
            break
        j -= coarse_step

    if hit is None or coarse_step <= 1:
        return hit

    for k in range(min(hit + coarse_step - 1, anchor - 1), hit, -1):
        c, r = _read_at(candles, k, tol_atr=tol_atr, min_score=min_score,
                        first_index=first_index)
        if c is not None or r is not None:
            return k
    return hit


# ─────────────────────────────────────────────────────────────────────────────
# session boundaries — a gap is never an impulse
# ─────────────────────────────────────────────────────────────────────────────
def split_moves_at_sessions(segments: Sequence[Segment],
                            candles: Sequence[Candle]) -> list[Segment]:
    """Cut every move at each overnight boundary and insert a `gap` segment there.

    A structure may span sessions — a shelf built yesterday is the same shelf today. The
    overnight jump itself is not market movement, so it must never be measured as one:
    left inside a move, a 300-point gap reads as a perfect efficiency-ratio impulse.
    """
    out: list[Segment] = []
    for seg in segments:
        if seg.kind != "move":
            out.append(seg)
            continue

        cuts = [i for i in range(seg.start + 1, seg.end + 1)
                if candles[i].session_date != candles[i - 1].session_date]
        if not cuts:
            out.append(seg)
            continue

        # The gap owns exactly the two candles either side of the boundary, and the
        # surrounding moves stop short of them. Letting the pieces share those candles
        # made the partition overlap — 1004 segment-candles over a 1000-candle canvas.
        left = seg.start
        for cut in cuts:
            if cut - 2 >= left:
                lo, hi = _span_band(candles, left, cut - 2)
                out.append(Segment("move", left, cut - 2, lo, hi))
            lo, hi = _span_band(candles, cut - 1, cut)
            out.append(Segment("gap", cut - 1, cut, lo, hi))
            left = cut + 1
        if left <= seg.end:
            lo, hi = _span_band(candles, left, seg.end)
            out.append(Segment("move", left, seg.end, lo, hi))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# move measurement and classification
# ─────────────────────────────────────────────────────────────────────────────
def measure_move(candles: Sequence[Candle], seg: Segment,
                 departed: Segment | None) -> dict[str, float]:
    """Every number a classifier could want, recorded whatever the label turns out to be.

    Storing the raw readings on every move is what makes the impulse rule swappable
    *after* the fact: re-labelling becomes a re-read of these numbers, never a re-scan of
    the candles.
    """
    real = [k for k in candles[seg.start:seg.end + 1] if not k.synthetic]
    if len(real) < 2:
        return {"er": 0.0, "net": 0.0, "net_atr": 0.0, "net_width": 0.0,
                "bars": float(seg.bars), "pts_per_bar": 0.0}

    net = real[-1].c - real[0].c
    atr = atr_at(candles, seg.end)
    width = departed.width if departed is not None else ZERO
    bars = len(real)
    return {
        "er": migration(real),
        "net": float(net),
        "net_atr": float(abs(net) / atr) if atr > ZERO else 0.0,
        "net_width": float(abs(net) / width) if width > ZERO else 0.0,
        "bars": float(bars),
        "pts_per_bar": float(abs(net)) / bars,
    }


@dataclass(frozen=True, slots=True)
class MoveContext:
    """What the classifier is allowed to know: the structure price left, and the last
    impulse before this one. Both are earlier in time, so nothing here is look-ahead."""

    departed: Segment | None
    prev_impulse_dir: str | None
    prev_impulse_origin: Decimal | None


Classifier = Callable[[dict[str, float], MoveContext], str]

IMPULSE_MIN_ER = 0.5      # HYPOTHESIS — see the two failure modes below


def _direction(m: dict[str, float]) -> str:
    return "up" if m["net"] > 0 else "down"


def _is_pullback(m: dict[str, float], ctx: MoveContext) -> bool:
    """Counter-directional to the last impulse, and it did not undo it.

    A retracement that *does* travel past the impulse's origin is not a pullback — the
    move that created the leg has been erased, and calling it a pause would be a lie.
    """
    if ctx.prev_impulse_dir is None:
        return False
    if _direction(m) == ctx.prev_impulse_dir:
        return False
    if ctx.prev_impulse_origin is None or ctx.departed is None:
        return True
    end_price = ctx.departed.low if _direction(m) == "down" else ctx.departed.high
    return (end_price >= ctx.prev_impulse_origin if _direction(m) == "down"
            else end_price <= ctx.prev_impulse_origin)


def er_width(m: dict[str, float], ctx: MoveContext) -> str:
    """DEFAULT — **HYPOTHESIS, not a settled rule.**

    `er >= 0.5` is the natural midpoint of Kaufman's efficiency ratio: more one-way than
    rotational. `abs(net) >= departed.width` uses the box price left as its own ruler,
    which is scale-free and adds no tunable number.

    Two known failure modes, written down so the real-data review looks for them:

        departed range =  10 pts, move = +11 pts   -> passes. Probably not an impulse.
        departed range = 100 pts, move = +90 pts   -> fails.  Probably IS an impulse.

    If either shows up on the Bank Nifty days, the rule changes — that is what the
    Step 4 STOP in the plan exists for.
    """
    big = m["net_width"] >= 1.0 if ctx.departed is not None else m["net_atr"] >= 1.0
    if m["er"] >= IMPULSE_MIN_ER and big:
        return f"impulse_{_direction(m)}"
    return "pullback" if _is_pullback(m, ctx) else "transition"


def er_only(m: dict[str, float], ctx: MoveContext) -> str:
    """Alternative: efficiency alone, no size gate. Fewest parameters, but a ten-point
    drift between two shelves becomes an impulse."""
    if m["er"] >= IMPULSE_MIN_ER:
        return f"impulse_{_direction(m)}"
    return "pullback" if _is_pullback(m, ctx) else "transition"


def er_atr(m: dict[str, float], ctx: MoveContext) -> str:
    """Alternative: the conventional size gate in ATR units. Costs one more tunable
    number, which is why it is not the default."""
    if m["er"] >= IMPULSE_MIN_ER and m["net_atr"] >= 1.0:
        return f"impulse_{_direction(m)}"
    return "pullback" if _is_pullback(m, ctx) else "transition"


CLASSIFIERS: dict[str, Classifier] = {
    "er_width": er_width,
    "er_only": er_only,
    "er_atr": er_atr,
}
DEFAULT_CLASSIFIER = "er_width"


# ─────────────────────────────────────────────────────────────────────────────
# the chain
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Link:
    """A labelled segment of the chain: a structure, or a classified move."""

    id: str
    kind: str
    start: int
    end: int
    low: Decimal
    high: Decimal
    measurements: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)
    window: int = 0
    migration: float = 0.0
    upper_touches: int = 0
    lower_touches: int = 0
    rotations: tuple[tuple[str, int, int, Decimal], ...] = ()
    provisional: bool = False

    @property
    def bars(self) -> int:
        return self.end - self.start + 1

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2

    @property
    def is_structure(self) -> bool:
        return self.kind in STRUCTURE_KINDS

    @property
    def is_impulse(self) -> bool:
        return self.kind.startswith("impulse")

    @property
    def direction(self) -> str | None:
        if self.is_impulse:
            return self.kind.split("_")[1]
        if self.kind in {"pullback", "transition", "gap"}:
            net = self.measurements.get("net", 0.0)
            return "up" if net > 0 else "down" if net < 0 else None
        return None


_PREFIX = {"cluster": "C", "range": "R", "impulse_up": "I", "impulse_down": "I",
           "pullback": "P", "transition": "T", "seam": "S", "gap": "G"}


def label_chain(segments: Sequence[Segment], candles: Sequence[Candle], *,
                classifier: str = DEFAULT_CLASSIFIER) -> list[Link]:
    """Forward pass: name every segment and classify every move.

    Forward, not backward, because a move's label depends on the structure it left and on
    the impulse before it — both earlier in time. Running this direction is what keeps the
    classification causal.
    """
    fn = CLASSIFIERS[classifier]
    counts: dict[str, int] = {}
    out: list[Link] = []
    departed: Segment | None = None
    prev_impulse_dir: str | None = None
    prev_impulse_origin: Decimal | None = None
    structures_since_impulse = 0
    last = len(candles) - 1

    for seg in segments:
        rots: list[tuple[str, int, int, Decimal]] = []
        measurements: dict[str, float] = {}

        if seg.is_structure:
            kind = seg.kind
            rots = rotations_in(candles, seg.start, seg.end, seg.low, seg.high)
            departed = seg
            # impulse -> base -> pullback is one leg. impulse -> base -> base -> base
            # -> move is not: by the third shelf the leg is over, and calling the next
            # counter-move a pullback of it is the same staleness bug one step smaller.
            structures_since_impulse += 1
            if structures_since_impulse > 1:
                prev_impulse_dir = None
                prev_impulse_origin = None
        elif seg.kind == "gap":
            kind = "gap"
            measurements = measure_move(candles, seg, departed)
        else:
            measurements = measure_move(candles, seg, departed)
            if (measurements["bars"] < MIN_MOVE_BARS
                    and measurements["net_atr"] < 1.0):
                # Below resolution. Not classified, and deliberately not allowed to
                # clear the previous impulse — a two-candle seam does not end a leg.
                kind = "seam"
            else:
                ctx = MoveContext(departed, prev_impulse_dir, prev_impulse_origin)
                kind = fn(measurements, ctx)
            if kind.startswith("impulse"):
                prev_impulse_dir = kind.split("_")[1]
                prev_impulse_origin = candles[seg.start].c
                structures_since_impulse = 0
            elif kind != "seam":
                # A pullback answers the impulse that JUST happened. Once another move
                # has come and gone the leg is over, and remembering it produced
                # nonsense: a +344 point run was labelled a pullback against an impulse
                # six hundred candles earlier. A structure in between is fine — that is
                # the normal impulse -> base -> pullback sequence — but a second move
                # is not.
                prev_impulse_dir = None
                prev_impulse_origin = None

        counts[_PREFIX[kind]] = counts.get(_PREFIX[kind], 0) + 1
        link_id = f"{_PREFIX[kind]}{counts[_PREFIX[kind]]:02d}"
        p = seg.proposal
        out.append(Link(
            id=link_id, kind=kind, start=seg.start, end=seg.end,
            low=seg.low, high=seg.high,
            measurements=measurements,
            score=p.score if p else 0.0,
            parts=dict(p.parts) if p else {},
            window=p.window if p else 0,
            migration=p.migration if p else measurements.get("er", 0.0),
            upper_touches=p.upper_touches if p else 0,
            lower_touches=p.lower_touches if p else 0,
            rotations=tuple(rots),
            provisional=seg.end >= last,
        ))
    return out


def build_chain(candles: Sequence[Candle], *, tol_atr: Decimal = Decimal("0.25"),
                min_score: float = 0.35, first_index: int = 0,
                classifier: str = DEFAULT_CLASSIFIER
                ) -> tuple[list[Link], list[Segment]]:
    """Candles in, labelled chronological chain out. Pure function of what it is given."""
    segments, parents = scan_backward(candles, tol_atr=tol_atr, min_score=min_score,
                                      first_index=first_index)
    segments = split_moves_at_sessions(segments, candles)
    return label_chain(segments, candles, classifier=classifier), parents


# ─────────────────────────────────────────────────────────────────────────────
# the chain, read aloud
# ─────────────────────────────────────────────────────────────────────────────
def chain_text(chain: Sequence[Link], candles: Sequence[Candle], *,
               newest_first: bool = True) -> list[str]:
    """The backward story, one line per link. Newest first — that is the direction the
    question is asked in: *"abhi kya hai, aur usse pehle kya tha?"*"""
    rows = list(reversed(chain)) if newest_first else list(chain)
    out: list[str] = []
    for ln in rows:
        when = (f"{candles[ln.start].open_time:%d %b %H:%M}"
                f"-{candles[ln.end].open_time:%H:%M}")
        span = f"candle {ln.start}-{ln.end} ({ln.bars})"
        if ln.is_structure:
            extra = (f"score {ln.score:.2f}  N={ln.window}  "
                     f"{ln.upper_touches}+{ln.lower_touches} touch  "
                     f"{len(ln.rotations)} rot")
            body = f"{float(ln.low):,.0f}-{float(ln.high):,.0f}"
        else:
            m = ln.measurements
            body = f"{m.get('net', 0.0):+,.0f} pts"
            extra = (f"er {m.get('er', 0.0):.2f}  "
                     f"net/atr {m.get('net_atr', 0.0):.2f}  "
                     f"net/width {m.get('net_width', 0.0):.2f}")
        flag = "  <- ABHI" if ln.provisional else ""
        out.append(f"{ln.id:>4}  {ln.kind:<13} {body:>18}  {span:<22} "
                   f"{when:<20} {extra}{flag}")
    return out


__all__ = ["WINDOW_MAX", "BREAK_CLOSES", "RETROSPECTIVE_FIELDS", "STRUCTURE_KINDS",
           "MOVE_KINDS", "IMPULSE_MIN_ER", "CLASSIFIERS", "DEFAULT_CLASSIFIER",
           "Segment", "Link", "MoveContext",
           "atr_at", "tol_at", "rotations_in", "extend_back", "last_touch",
           "scan_backward",
           "split_moves_at_sessions", "measure_move", "label_chain", "build_chain",
           "chain_text"]
