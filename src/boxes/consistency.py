"""
Forward frontier vs backward batch — `LIVE-FRONTIER.md` §6.8.

Two procedures read the same market. The batch scan works **backward from now** with the
whole canvas in hand; the frontier works **forward from then**, one closed candle at a
time. They are genuinely different algorithms, and this module measures where they part
company.

## The frontier is not the batch's slave

If they disagree, the answer is **not** "make the frontier reproduce the batch". They
exist for different reasons:

```
BATCH      historical reconstruction   — hindsight is allowed, that is the job
FRONTIER   causal live reconstruction  — hindsight is forbidden, that is the job
```

The goal is narrow and it is the only one worth having: **where both should know the same
causal truth, they must agree.** Handing the live layer hindsight until the numbers match
would "pass" this test by destroying the thing it is testing.

## Causal fields only

`structure.RETROSPECTIVE_FIELDS` already names the split. `exit`, `role`, `parent`,
`depth` and `location` are excluded here, because demanding equality on them is demanding
that the live layer know the future.

```
compared    kind  start  end  low  high  score  window  migration
excluded    exit  role  parent  children  depth  location  position_in_parent
```

## What a divergence is, rather than how big it is

An aggregate "N nodes differ" says nothing actionable. Every pairing is classified:

| verdict | meaning |
|---|---|
| `exact` | identical causal fields |
| `boundary` | within `tol` on price and 2 candles on time — the acceptable case |
| `timing` | same band, different extent — one of them found the structure's start elsewhere |
| `band` | same extent, different edges |
| `structural` | both, and therefore a real disagreement about what is there |
| `unmatched` | one side saw a structure the other did not |

Plus `frozen_overlap`, which is not a divergence at all but an architecture question: a
finalised live node that re-claims territory already inside `M001`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.boxes.adaptive import choose, overlap
from src.boxes.frontier import Frontier
from src.boxes.hierarchy import Node
from src.boxes.snapshot import SAME_NODE_OVERLAP, MapSnapshot
from src.boxes.structure import STRUCTURE_KINDS, WINDOW_MAX, Link, atr_at
from src.domain.models import ZERO, Candle

#: Compared. Everything else on a `Node` is retrospective and deliberately ignored.
CAUSAL_FIELDS = ("kind", "start", "end", "low", "high", "score", "window", "migration")

#: A structure's start is recovered by `extend_back`, which walks candle by candle; being
#: a candle or two out is quantisation, not disagreement. Two is `BREAK_CLOSES` — the
#: repo's existing "one candle is not evidence" constant, not a new number.
TIME_SLACK = 2


@dataclass(frozen=True, slots=True)
class Pairing:
    """One finalised live node, its batch counterpart, and what separates them."""

    verdict: str
    live: Node
    batch: Node | None
    start_shift: int = 0
    end_shift: int = 0
    low_shift: Decimal = Decimal("0")
    high_shift: Decimal = Decimal("0")
    band_overlap: float = 0.0
    frozen_overlap: str | None = None      # id of the M001 node it re-claims, if any

    @property
    def agrees(self) -> bool:
        return self.verdict in {"exact", "boundary"}

    def line(self) -> str:
        if self.batch is None:
            return (f"{self.live.id:<5} {self.verdict:<12} "
                    f"{float(self.live.low):>9,.0f}-{float(self.live.high):<9,.0f} "
                    f"c{self.live.start}-{self.live.end}   (no batch counterpart)")
        return (f"{self.live.id:<5} {self.verdict:<12} "
                f"{float(self.live.low):>9,.0f}-{float(self.live.high):<9,.0f} "
                f"c{self.live.start}-{self.live.end}  vs  {self.batch.id:<5} "
                f"{float(self.batch.low):>9,.0f}-{float(self.batch.high):<9,.0f} "
                f"c{self.batch.start}-{self.batch.end}   "
                f"dt {self.start_shift:+d}/{self.end_shift:+d}  "
                f"dp {float(self.low_shift):+.0f}/{float(self.high_shift):+.0f}  "
                f"ov {self.band_overlap:.2f}"
                + (f"   RECLAIMS {self.frozen_overlap}" if self.frozen_overlap else ""))


def _classify(live: Node, batch: Node, tol: Decimal) -> str:
    ds, de = batch.start - live.start, batch.end - live.end
    dl, dh = batch.low - live.low, batch.high - live.high

    if live.kind != batch.kind:
        return "structural"
    if (ds, de, dl, dh) == (0, 0, 0, 0):
        return "exact"

    time_ok = abs(ds) <= TIME_SLACK and abs(de) <= TIME_SLACK
    band_ok = abs(dl) <= tol and abs(dh) <= tol

    if time_ok and band_ok:
        return "boundary"
    if band_ok:
        return "timing"
    if time_ok:
        return "band"
    return "structural"


def compare(frontier: Frontier, batch: Sequence[Node], tol: Decimal,
            snapshot: MapSnapshot | None = None) -> list[Pairing]:
    """Pair every finalised frontier node with its batch counterpart and classify.

    Matching is structural — the ids are minted independently by two procedures, so `L03`
    and `C21` have no relationship beyond describing the same shelf. Same test
    `mapper.py` and `snapshot.diff` use: same kind, overlapping in time, sharing at least
    half of the narrower band.
    """
    candidates = [n for n in batch if n.kind in STRUCTURE_KINDS]
    taken: set[str] = set()
    out: list[Pairing] = []

    for live in frontier.history():
        best: Node | None = None
        best_ov = 0.0
        for cand in candidates:
            if cand.id in taken or cand.kind != live.kind:
                continue
            if cand.end < live.start or cand.start > live.end:
                continue
            ov = overlap((live.low, live.high), (cand.low, cand.high))
            if ov > best_ov:
                best, best_ov = cand, ov

        reclaims = _reclaimed(live, snapshot) if snapshot is not None else None

        if best is None or best_ov < SAME_NODE_OVERLAP:
            out.append(Pairing("unmatched", live, None, frozen_overlap=reclaims))
            continue

        taken.add(best.id)
        out.append(Pairing(
            _classify(live, best, tol), live, best,
            best.start - live.start, best.end - live.end,
            best.low - live.low, best.high - live.high, best_ov, reclaims))
    return out


def _reclaimed(live: Node, snapshot: MapSnapshot) -> str | None:
    """Does this finalised live node re-claim territory already frozen in `M001`?

    Not a divergence — an architecture question. `extend_back` walks backward from where
    the structure was detected and does not know where the snapshot ends, so a live node's
    start can land inside a shelf the frozen map already describes. Measured before it is
    ruled on.
    """
    for n in snapshot.nodes:
        if n.kind not in STRUCTURE_KINDS:
            continue
        if n.end < live.start or n.start > live.end:
            continue
        if overlap((live.low, live.high), (n.low, n.high)) >= SAME_NODE_OVERLAP:
            return n.id
    return None


# ─────────────────────────────────────────────────────────────────────────────
# causal sequence — test C
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SequenceCheck:
    """Did both sides see `structure -> move -> structure` in the same order?"""

    live_ids: tuple[str, ...]
    batch_ids: tuple[str, ...]
    moves_between_live: int
    moves_between_batch: int

    @property
    def preserved(self) -> bool:
        return (len(self.live_ids) == len(self.batch_ids)
                and self.moves_between_live == self.moves_between_batch)


def sequence(pairings: Sequence[Pairing], chain: Sequence[Link]) -> SequenceCheck:
    matched = [p for p in pairings if p.batch is not None]
    live_ids = tuple(p.live.id for p in matched)
    batch_ids = tuple(p.batch.id for p in matched)

    if len(matched) < 2:
        return SequenceCheck(live_ids, batch_ids, 0, 0)

    lo, hi = matched[0].batch.end, matched[-1].batch.start
    between = [ln for ln in chain
               if not ln.is_structure and ln.kind != "seam"
               and lo <= ln.start and ln.end <= hi]
    return SequenceCheck(live_ids, batch_ids, len(matched) - 1, len(between))


# ─────────────────────────────────────────────────────────────────────────────
# candidate stability — the FORMING flicker, measured not tuned
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Episode:
    start: int
    end: int
    outcome: str            # confirmed | collapsed

    @property
    def bars(self) -> int:
        return self.end - self.start + 1


def candidate_episodes(frontier: Frontier) -> list[Episode]:
    """Every run of `STRUCTURE_CANDIDATE`, and whether it became a structure.

    `FORMING -> MOVING -> FORMING` reads as the engine changing its mind. Before any
    smoothing is added, this says how often it happens and whether the flicker is a
    candidate genuinely dying or one zone being reported intermittently.
    """
    out: list[Episode] = []
    start: int | None = None
    for r in frontier.readings:
        if r.state == "STRUCTURE_CANDIDATE":
            if start is None:
                start = r.index
        elif start is not None:
            out.append(Episode(start, r.index - 1,
                               "confirmed" if r.state == "CONFIRMED" else "collapsed"))
            start = None
    if start is not None:
        out.append(Episode(start, frontier.readings[-1].index, "collapsed"))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# why did the batch not see it? — diagnostic only
# ─────────────────────────────────────────────────────────────────────────────
UNMATCHED_CLASSES = ("batch_skip", "frontier_false_positive", "boundary_diff",
                     "same_structure")


@dataclass(frozen=True, slots=True)
class Unmatched:
    live: Node
    verdict: str
    detail: str = ""


def explain_unmatched(live: Node, chain: Sequence[Link], batch: Sequence[Node],
                      candles: Sequence[Candle], tol: Decimal,
                      already_matched: set[str]) -> Unmatched:
    """Classify a live structure the batch never produced. **Nothing is changed here.**

    ## The hypothesis being tested

    The batch scan is greedy backward: the moment it admits a structure it jumps
    `anchor = start - 1`. A short shelf sitting inside the span it just claimed — or
    inside a stretch it labelled a move — is therefore **never anchored on at all**. The
    detector was never asked about it.

    The frontier has no such blind spot; it meets every shelf as it forms.

    So for each unmatched node this re-runs **the batch's own detector, unchanged, at the
    one anchor the greedy walk skipped**. If the detector finds the shelf there, the batch
    did not disagree — it never looked. That is `batch_skip`, and it means the frontier is
    more granular rather than wrong.

    This is a **diagnostic**. `scan_backward` is not modified, and the historical map is
    not re-partitioned.
    """
    # Already described by a batch node that another live node claimed?
    for n in batch:
        if n.kind not in STRUCTURE_KINDS or n.id not in already_matched:
            continue
        if n.end < live.start or n.start > live.end:
            continue
        if overlap((live.low, live.high), (n.low, n.high)) >= SAME_NODE_OVERLAP:
            return Unmatched(live, "same_structure",
                             f"{n.id} covers it; the batch merged two live shelves")

    # A batch node is there, but the bands only partly agree.
    for n in batch:
        if n.kind not in STRUCTURE_KINDS:
            continue
        if n.end < live.start or n.start > live.end:
            continue
        share = overlap((live.low, live.high), (n.low, n.high))
        if 0.0 < share < SAME_NODE_OVERLAP:
            return Unmatched(live, "boundary_diff",
                             f"{n.id} overlaps only {share:.2f}")

    # Ask the batch's own detector at the anchor the greedy walk jumped over.
    lo = max(0, live.end - WINDOW_MAX + 1)
    atr = atr_at(candles, live.end)
    seen = None
    if atr > ZERO:
        cluster, rng = choose(candles[lo:live.end + 1], atr)
        for p in (rng, cluster):
            if p is not None and overlap((live.low, live.high),
                                         (p.low, p.high)) >= SAME_NODE_OVERLAP:
                seen = p
                break

    if seen is not None:
        owner = next((ln.id for ln in chain
                      if ln.start <= live.end <= ln.end), "?")
        return Unmatched(live, "batch_skip",
                         f"detector finds {float(seen.low):,.0f}-"
                         f"{float(seen.high):,.0f} at c{live.end}; greedy walk had "
                         f"already assigned that span to {owner}")

    return Unmatched(live, "frontier_false_positive",
                     f"the detector sees nothing like it at c{live.end}")


def divergence_stats(pairings: Sequence[Pairing]) -> dict[str, float]:
    """RC4, quantified rather than argued about — is 13% normal or pathological?"""
    matched = [p for p in pairings if p.batch is not None]
    if not matched:
        return {}

    def pct(values: list[float], q: float) -> float:
        s = sorted(values)
        return s[min(int(q * len(s)), len(s) - 1)]

    widths = [float(p.batch.width - p.live.width) for p in matched]
    ends = [abs(p.end_shift) for p in matched]
    edges = [max(abs(float(p.low_shift)), abs(float(p.high_shift))) for p in matched]
    return {
        "n": float(len(matched)),
        "width_median": pct(widths, 0.5), "width_p90": pct(widths, 0.9),
        "width_max": max(widths),
        "end_median": float(pct([float(e) for e in ends], 0.5)),
        "end_p90": float(pct([float(e) for e in ends], 0.9)),
        "end_max": float(max(ends)),
        "edge_median": pct(edges, 0.5), "edge_p90": pct(edges, 0.9),
        "edge_max": max(edges),
    }


__all__ = ["CAUSAL_FIELDS", "TIME_SLACK", "UNMATCHED_CLASSES", "Pairing",
           "SequenceCheck", "Episode", "Unmatched", "compare", "sequence",
           "candidate_episodes", "explain_unmatched", "divergence_stats"]
