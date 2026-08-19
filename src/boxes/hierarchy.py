"""
The containment tree and the event graph — plan §5 and §6.

`structure.py` produces a **chain**: a flat, exact partition of the canvas into shelves
and the moves between them. That is a timeline. It is not yet a map, because it cannot
answer *"ye cluster kis range ke andar hai?"* or *"is shelf ko kis impulse ne banaya?"*.

Two different things are built here, and keeping them apart is the point:

```
CONTAINMENT is a tree            CAUSALITY is a graph

RANGE R1                         R1 --broken_by-->       I4
 |-- CLUSTER C1                  I4 --originated_from--> C3
 |-- CLUSTER C2                  I4 --created-->         R2
 +-- CLUSTER C3
```

A tree alone cannot hold *"R1 se nikalkar I4 ne R2 banaya"*, and that sentence is the
whole of the trader's story.

## Where parent ranges come from — the finding that shaped this module

The obvious source was the microscope: `choose()` returns a range proposal alongside a
cluster, so stash it and use it as the parent. Measured on five real Bank Nifty canvases
that produced **zero ranges, every single day**:

```
2026-02-16 cluster=24   2025-09-12 cluster=26   2024-12-18 cluster=25
2024-09-06 cluster=25   2023-10-04 cluster=25        ranges = 0, always
```

That is not Bank Nifty refusing to range. It is that the range gates — two distinct
touches of each edge, two traverses, stable across three window lengths — cannot be met
inside a **75-candle** window on 1m data, where the window's high is usually one spike.

The gates are not the problem and they are **not loosened here.** The source was wrong.
A parent range is a property of a *larger span*, so candidates are built from the chain's
own structures and validated by the same `read_window()` gates, unchanged:

```
C1  I1  C2  I2  C3  I3  C4
+-------- span --------+
        |
        v
  read_window() over the whole span
        |
   two-sided rotation?  --no--> no parent. Containment alone never creates a range.
        |yes
        v
      RANGE R1 -- C1, C2, C3, C4
```

So `100 110 120 130 140 150` still produces nothing, however many clusters sit along it,
and `100 -> 130 -> 105 -> 128 -> 110 -> 132` produces a range — which is the distinction
the whole repo is built on, applied one scale up.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Sequence

from src.boxes.adaptive import migration, read_window
from src.boxes.structure import (
    STRUCTURE_KINDS, Link, atr_at, build_chain, rotations_in)
from src.domain.models import ZERO, Candle

MAX_SPAN_MIGRATION = 0.5   # a one-way span is a trend, not a range — cheap pre-filter
MIN_CHILDREN = 2           # a parent with one child is that child


# ─────────────────────────────────────────────────────────────────────────────
# nodes, relations
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Rotation:
    """One completed trip between a band's thirds, with the nodes it travelled between."""

    direction: str                 # "high->low" | "low->high"
    from_i: int
    to_i: int
    points: Decimal
    from_node: str | None = None
    to_node: str | None = None

    @property
    def bars(self) -> int:
        return self.to_i - self.from_i


@dataclass(frozen=True, slots=True)
class Relation:
    """A typed edge. The graph these form is what `narrate.py` walks to tell the story."""

    src: str
    kind: str                      # contains | broken_by | originated_from | created
                                   # | rotated_to
    dst: str
    at: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Node:
    """A chain link plus everything the map knows about where it sits and how it came to be.

    Fields split into two classes, and the split is enforced by
    `structure.RETROSPECTIVE_FIELDS` and tested:

      CAUSAL         a pure function of `candles[:end + 1]` — kind, start, end, low,
                     high, score, window, migration, origin, rotations, measurements
      RETROSPECTIVE  knowingly reads later candles — exit, role, parent, children,
                     depth, location, position_in_parent

    `role` needs to know which way price eventually left, which is a fact about the
    future of a completed structure. Legitimate — it is what a person reads off a chart —
    but never to be mistaken for something the engine knew at the time.
    """

    id: str
    kind: str
    start: int
    end: int
    low: Decimal
    high: Decimal

    parent: str | None = None
    children: tuple[str, ...] = ()
    depth: int = 0

    origin: str | None = None          # CAUSAL — the move that led into it
    exit: str | None = None            # RETROSPECTIVE
    role: str = "active"               # RETROSPECTIVE
    location: str = ""                 # RETROSPECTIVE
    position_in_parent: Decimal | None = None

    rotations: tuple[Rotation, ...] = ()
    upper_touches: int = 0
    lower_touches: int = 0
    score: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)
    window: int = 0
    migration: float = 0.0
    measurements: dict[str, float] = field(default_factory=dict)

    spans_sessions: bool = False
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

    def contains_price(self, price: Decimal) -> bool:
        return self.low <= price <= self.high

    def label(self) -> str:
        return f"{self.kind} {float(self.low):,.0f}-{float(self.high):,.0f}"


# ─────────────────────────────────────────────────────────────────────────────
# parent ranges, from spans
# ─────────────────────────────────────────────────────────────────────────────
def validate_range(candles: Sequence[Candle], start: int, end: int, *,
                   tol_atr: Decimal = Decimal("0.25"), min_score: float = 0.35):
    """The existing range detector, run over a whole span. Gates unchanged.

    Returns the range proposal or `None`. `None` is the common answer and it is the
    correct one — most spans that contain several clusters are drifts, not auctions.
    """
    n = end - start + 1
    if n < 12:
        return None
    atr = atr_at(candles, end)
    if atr <= ZERO:
        return None
    window = candles[start:end + 1]
    if migration(window) > MAX_SPAN_MIGRATION:     # cheap reject before the real work
        return None
    _, rng = read_window(window, n, atr, tol_atr=tol_atr, min_score=min_score)
    return rng


def find_parent_ranges(chain: Sequence[Link], candles: Sequence[Candle], *,
                       tol_atr: Decimal = Decimal("0.25"), min_score: float = 0.35,
                       min_children: int = MIN_CHILDREN) -> list[Node]:
    """Spans bounded by two of the chain's own structures, largest first, validated.

    Candidates are anchored on structures rather than on arbitrary candle indices,
    because a range's edges are where price turned — and where price turned is exactly
    what a shelf is. That also keeps the search at `O(structures^2)` (~300 spans on a
    typical canvas) instead of `O(candles^2)`.

    Accepted parents never overlap partially: a span that passes is taken whole, and the
    search then recurses **inside** it for a smaller range, and on the remainders either
    side. Partially overlapping ranges are not a thing a chart can show.
    """
    idx = [i for i, ln in enumerate(chain) if ln.is_structure]
    out: list[Node] = []
    counter = [0]

    def search(lo: int, hi: int, max_bars: int | None) -> None:
        inner = [i for i in idx if lo <= i <= hi]
        if len(inner) < min_children:
            return

        cands: list[tuple[int, int, int]] = []
        for ai in range(len(inner)):
            for bi in range(ai + min_children - 1, len(inner)):
                a, b = inner[ai], inner[bi]
                bars = chain[b].end - chain[a].start + 1
                if max_bars is None or bars < max_bars:
                    cands.append((-bars, a, b))
        cands.sort()                                   # widest span first

        for _, a, b in cands:
            start, end = chain[a].start, chain[b].end
            rng = validate_range(candles, start, end, tol_atr=tol_atr,
                                 min_score=min_score)
            if rng is None:
                continue
            counter[0] += 1
            out.append(Node(
                id=f"R{counter[0]:02d}", kind="range", start=start, end=end,
                low=rng.low, high=rng.high,
                rotations=tuple(Rotation(d, fi, ti, pts) for d, fi, ti, pts
                                in rotations_in(candles, start, end,
                                                rng.low, rng.high)),
                upper_touches=rng.upper_touches, lower_touches=rng.lower_touches,
                score=rng.score, parts=dict(rng.parts), window=rng.window,
                migration=rng.migration,
                spans_sessions=_spans_sessions(candles, start, end),
                provisional=end >= len(candles) - 1))
            search(a, b, end - start + 1)              # a smaller range inside this one
            search(lo, a - 1, max_bars)
            search(b + 1, hi, max_bars)
            return

    search(0, len(chain) - 1, None)
    out.sort(key=lambda n: (n.start, -n.bars))
    return out


def _spans_sessions(candles: Sequence[Candle], start: int, end: int) -> bool:
    return candles[start].session_date != candles[end].session_date


# ─────────────────────────────────────────────────────────────────────────────
# the tree
# ─────────────────────────────────────────────────────────────────────────────
def _link_to_node(ln: Link, candles: Sequence[Candle]) -> Node:
    return Node(
        id=ln.id, kind=ln.kind, start=ln.start, end=ln.end, low=ln.low, high=ln.high,
        rotations=tuple(Rotation(d, fi, ti, pts)
                        for d, fi, ti, pts in ln.rotations),
        upper_touches=ln.upper_touches, lower_touches=ln.lower_touches,
        score=ln.score, parts=dict(ln.parts), window=ln.window, migration=ln.migration,
        measurements=dict(ln.measurements),
        spans_sessions=_spans_sessions(candles, ln.start, ln.end),
        provisional=ln.provisional)


def _contains(outer: Node, inner: Node, tol: Decimal) -> bool:
    """Time containment **and** price containment **and** strictly finer.

    All three, because a big box that merely spans a small one in time is not its parent
    — it has to hold it in price as well, or the word "inside" means nothing.
    """
    if outer.id == inner.id:
        return False
    if not (outer.start <= inner.start and inner.end <= outer.end):
        return False
    if not (inner.low >= outer.low - tol and inner.high <= outer.high + tol):
        return False
    return inner.width < outer.width


def assign_tree(nodes: Sequence[Node], tol: Decimal) -> list[Node]:
    """Parent = the **smallest** node that contains it. Recursive by construction, so
    `RANGE -> CLUSTER -> micro-cluster` needs no depth limit and no special case."""
    parent_of: dict[str, str | None] = {}
    for n in nodes:
        holders = [o for o in nodes if _contains(o, n, tol)]
        parent_of[n.id] = min(holders, key=lambda o: o.width).id if holders else None

    kids: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        p = parent_of[n.id]
        if p is not None:
            kids[p].append(n.id)

    by_id = {n.id: n for n in nodes}

    def depth_of(nid: str, seen: frozenset[str] = frozenset()) -> int:
        p = parent_of.get(nid)
        if p is None or p in seen:
            return 0
        return 1 + depth_of(p, seen | {nid})

    out: list[Node] = []
    for n in nodes:
        p = parent_of[n.id]
        pos: Decimal | None = None
        location = ""
        if p is not None:
            par = by_id[p]
            if par.width > ZERO:
                pos = (n.mid - par.low) / par.width
                third = ("lower third" if pos < Decimal("0.34")
                         else "upper third" if pos > Decimal("0.66") else "middle")
                location = f"inside {p}, {third}"
        out.append(replace(n, parent=p, children=tuple(sorted(kids[n.id])),
                           depth=depth_of(n.id), position_in_parent=pos,
                           location=location))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# semantics — origin, exit, role
# ─────────────────────────────────────────────────────────────────────────────
_ROLE = {
    ("up", "up"): "continuation_base",
    ("up", "down"): "reversal_top",
    ("down", "down"): "continuation_base",
    ("down", "up"): "reversal_bottom",
}


def apply_semantics(nodes: Sequence[Node], chain: Sequence[Link]) -> list[Node]:
    """`origin`, `exit` and `role` for every structure, from its neighbours in the chain.

    `origin` is causal — the move before it already happened. `exit` and `role` are
    retrospective and are marked as such wherever they are shown.
    """
    order = [ln.id for ln in chain]
    pos = {lid: i for i, lid in enumerate(order)}
    by_id = {ln.id: ln for ln in chain}

    def neighbour(lid: str, step: int) -> Link | None:
        i = pos.get(lid)
        if i is None:
            return None
        j = i + step
        while 0 <= j < len(order):
            ln = by_id[order[j]]
            if ln.kind != "seam":          # seams are joints, not events
                return ln
            j += step
        return None

    out: list[Node] = []
    for n in nodes:
        if not n.is_structure or n.id not in pos:
            out.append(n)
            continue
        before = neighbour(n.id, -1)
        after = neighbour(n.id, +1)
        origin = before.id if before is not None and not before.is_structure else None
        exit_id = after.id if after is not None and not after.is_structure else None

        # `active` means one thing only: nothing has happened after it yet. The first
        # version let it also be the fall-through for "none of the branches matched",
        # and eighteen of twenty-four finished clusters reported themselves as still
        # live — the map claiming the whole canvas was the present moment.
        if after is None:
            role = "active"
        elif (before is not None and before.is_impulse
              and after.direction is not None):
            role = _ROLE.get((before.kind.split("_")[1], after.direction), "pause")
        elif after.is_structure:
            # Price stepped straight onto the next shelf with nothing measurable in
            # between — a shift, not a break.
            role = "shifted"
        else:
            role = "pause"

        out.append(replace(n, origin=origin, exit=exit_id, role=role))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# the event graph
# ─────────────────────────────────────────────────────────────────────────────
def build_relations(nodes: Sequence[Node], chain: Sequence[Link],
                    candles: Sequence[Candle]) -> list[Relation]:
    """Typed edges. The tree is materialised here too, so one traversal sees everything."""
    by_id = {n.id: n for n in nodes}
    rels: list[Relation] = []

    for n in nodes:
        for kid in n.children:
            rels.append(Relation(n.id, "contains", kid, by_id[kid].start))

    for n in nodes:
        if not n.is_structure:
            continue
        if n.origin:
            rels.append(Relation(n.id, "originated_from", n.origin, n.start))
            rels.append(Relation(n.origin, "created", n.id, n.start))
        if n.exit:
            mv = by_id.get(n.exit)
            side = mv.measurements.get("net", 0.0) if mv else 0.0
            rels.append(Relation(n.id, "broken_by", n.exit, n.end,
                                 "up" if side > 0 else "down"))

    # rotations inside a parent, resolved to the children they travelled between
    for n in nodes:
        if n.kind != "range" or not n.children:
            continue
        for direction, fi, ti, pts in rotations_in(candles, n.start, n.end,
                                                   n.low, n.high):
            src = _node_at(nodes, fi, n.id)
            dst = _node_at(nodes, ti, n.id)
            if src and dst and src != dst:
                rels.append(Relation(src, "rotated_to", dst, ti,
                                     f"{direction} {float(pts):,.0f} pts / {ti - fi}c"))
    return rels


def _node_at(nodes: Sequence[Node], index: int, parent_id: str) -> str | None:
    """The narrowest child of `parent_id` covering `index`."""
    hits = [n for n in nodes
            if n.parent == parent_id and n.start <= index <= n.end]
    return min(hits, key=lambda n: n.width).id if hits else None


# ─────────────────────────────────────────────────────────────────────────────
# the whole thing
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class StructureMap:
    """The chain, the tree and the graph over one canvas of closed candles."""

    nodes: tuple[Node, ...]
    relations: tuple[Relation, ...]
    chain: tuple[Link, ...]
    n_candles: int

    def by_id(self, nid: str) -> Node | None:
        return next((n for n in self.nodes if n.id == nid), None)

    def structures(self) -> list[Node]:
        return [n for n in self.nodes if n.is_structure]

    def roots(self) -> list[Node]:
        return sorted((n for n in self.nodes if n.parent is None and n.is_structure),
                      key=lambda n: n.start)

    def children_of(self, nid: str) -> list[Node]:
        return sorted((n for n in self.nodes if n.parent == nid), key=lambda n: n.start)

    def edges(self, kind: str) -> list[Relation]:
        return [r for r in self.relations if r.kind == kind]


def build_map(candles: Sequence[Candle], *, tol_atr: Decimal = Decimal("0.25"),
              min_score: float = 0.35, classifier: str = "er_width") -> StructureMap:
    """Candles in, map out. A pure function of the prefix it is handed."""
    chain, _ = build_chain(candles, tol_atr=tol_atr, min_score=min_score,
                           classifier=classifier)
    parents = find_parent_ranges(chain, candles, tol_atr=tol_atr, min_score=min_score)

    tol = max(atr_at(candles, len(candles) - 1) * tol_atr, Decimal("0.05"))
    nodes = [_link_to_node(ln, candles) for ln in chain] + list(parents)
    nodes = assign_tree(nodes, tol)
    nodes = apply_semantics(nodes, chain)
    relations = build_relations(nodes, chain, candles)
    return StructureMap(tuple(nodes), tuple(relations), tuple(chain), len(candles))


# ─────────────────────────────────────────────────────────────────────────────
# the tree, printed
# ─────────────────────────────────────────────────────────────────────────────
def tree_text(m: StructureMap, candles: Sequence[Candle]) -> list[str]:
    """The hierarchy as a chart-shaped outline, oldest first."""
    out: list[str] = []

    def draw(n: Node, prefix: str, joint: str, child_prefix: str) -> None:
        when = f"{candles[n.start].open_time:%d %b %H:%M}"
        extra = (f"{n.upper_touches}+{n.lower_touches} touch, {len(n.rotations)} rot"
                 if n.kind == "range" else f"score {n.score:.2f}, N={n.window}")
        role = "[ACTIVE]" if n.role == "active" else f"[{n.role}]"
        out.append(f"{prefix}{joint}{n.id}  {n.kind:<7} "
                   f"{float(n.low):>9,.0f}-{float(n.high):<9,.0f} "
                   f"c{n.start}-{n.end} ({n.bars})  {when}  {extra}  {role}")
        kids = [k for k in m.children_of(n.id) if k.is_structure]
        for i, kid in enumerate(kids):
            last = i == len(kids) - 1
            draw(kid, child_prefix, "+-- " if last else "|-- ",
                 child_prefix + ("    " if last else "|   "))

    for r in m.roots():
        draw(r, "", "", "")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# MEASUREMENT ONLY — the child-zone reading of a parent span
# ─────────────────────────────────────────────────────────────────────────────
# Nothing below this line creates a node, and `build_map` does not call any of it.
#
# ## Why a measuring instrument and not a rule
#
# Applying the raw range gates to long spans admitted **3 of ~1,400** candidate spans
# across five sessions, uniformly across every span size. Two separate things were going
# on, and only one of them was a bug:
#
#   * `upper_touches`/`lower_touches` came back as 1 because `tol = 0.25 x ATR` is ~8% of
#     a 75-candle window's range but **0.35-0.7%** of a 900-candle span's — a knife edge
#     on the single extreme candle. That is a scale artefact.
#   * `traverses` came back as 1 even after correcting the tolerance. That is **not** an
#     artefact: at canvas scale price visits each extreme once, so the raw-candle
#     thirds test is honestly reporting "not a two-sided auction".
#
# The conclusion is not that Bank Nifty has no ranges. It is that a parent range is a
# statement about **where the child structures sit**, not about whether raw price
# retouched a three-day extreme twice:
#
#        parent envelope
#   +-------------------------+
#   |   C1              C4    |     HIGH zone
#   |    ^               ^    |
#   |    |               |    |
#   |    v               v    |
#   |       C2      C3        |     LOW zone
#   +-------------------------+
#
# So `traverses` is not deleted — it is **re-expressed one level up**, as alternation
# between child zones rather than between thirds of the raw span.
#
# This code answers *"how many spans would satisfy that?"* and nothing else. No span is
# labelled, no RANGE is admitted, and the map is unchanged until the numbers have been
# looked at.

MIN_ZONE_CHILDREN = 3      # L-H-L is the shortest sequence that is two-sided
MIN_ALTERNATIONS = 2       # UNVALIDATED — the shape of the claim, not a tuned number


@dataclass(frozen=True, slots=True)
class ZoneReading:
    """One candidate span, measured. `verdict` is a description, never a label."""

    start: int
    end: int
    children: tuple[str, ...]
    split: Decimal
    low_zone: tuple[Decimal, Decimal]
    high_zone: tuple[Decimal, Decimal]
    separation: Decimal
    separation_ratio: float      # gap / the thicker zone — scale-free, nothing to tune
    shelf_ratio: float           # gap / a typical shelf's own width — the second reading
    sequence: str                # "LHLH" in chronological order
    alternations: int
    envelope: tuple[Decimal, Decimal]
    net: Decimal
    migration: float
    bounded: bool
    verdict: str

    @property
    def bars(self) -> int:
        return self.end - self.start + 1

    @property
    def passes(self) -> bool:
        return self.verdict == "candidate"


def read_child_zones(chain: Sequence[Link], candles: Sequence[Candle],
                     a: int, b: int) -> ZoneReading | None:
    """Measure one span, bounded by chain structures `a`..`b`. `None` if too few children.

    The zone split is the **largest gap** between consecutive child mid-prices — the
    market's own dividing line rather than a chosen level. Separation is then judged
    against the zones' own thickness, so a 20-point separation between two 5-point
    shelves counts and a 20-point separation between two 60-point shelves does not.
    That ratio is scale-free and adds no tunable number.
    """
    kids = [ln for ln in chain[a:b + 1] if ln.is_structure]
    if len(kids) < MIN_ZONE_CHILDREN:
        return None

    start, end = chain[a].start, chain[b].end
    mids = sorted((k.mid, k.id) for k in kids)
    gaps = [(mids[i + 1][0] - mids[i][0], i) for i in range(len(mids) - 1)]
    widest, at = max(gaps)
    split = (mids[at][0] + mids[at + 1][0]) / 2

    low = [k for k in kids if k.mid <= split]
    high = [k for k in kids if k.mid > split]
    low_zone = (min(k.low for k in low), max(k.high for k in low))
    high_zone = (min(k.low for k in high), max(k.high for k in high))
    thickest = max(low_zone[1] - low_zone[0], high_zone[1] - high_zone[0])
    gap = high_zone[0] - low_zone[1]
    ratio = float(gap / thickest) if thickest > ZERO else 0.0

    # Second reading of the same separation. `thickest` is the **union** of every child
    # in a zone, so a span holding twenty scattered shelves has a 300-point "zone" that
    # no gap can exceed — the test then rejects for crowding rather than for shape.
    # Measuring the gap against a typical *individual* shelf asks the question the way a
    # person would: are these two groups further apart than a shelf is thick?
    widths = sorted(k.width for k in kids)
    typical = widths[len(widths) // 2]
    shelf_ratio = float(gap / typical) if typical > ZERO else 0.0

    seq = "".join("L" if k.mid <= split else "H" for k in kids)
    alternations = sum(1 for x, y in zip(seq, seq[1:]) if x != y)

    envelope = (min(k.low for k in kids), max(k.high for k in kids))
    real = [k for k in candles[start:end + 1] if not k.synthetic]
    net = (real[-1].c - real[0].c) if len(real) > 1 else ZERO
    mig = migration(real)
    bounded = abs(net) <= (envelope[1] - envelope[0])

    if ratio < 1.0:
        verdict = f"zones not separated (gap/thickness {ratio:.2f})"
    elif alternations < MIN_ALTERNATIONS:
        verdict = f"no alternation ({seq})"
    elif not bounded:
        verdict = f"unbounded (net {float(net):+,.0f})"
    elif mig > MAX_SPAN_MIGRATION:
        verdict = f"migrating ({mig:.2f})"
    else:
        verdict = "candidate"

    return ZoneReading(start, end, tuple(k.id for k in kids), split,
                       low_zone, high_zone, gap, ratio, shelf_ratio, seq, alternations,
                       envelope, net, mig, bounded, verdict)


def survey_parent_candidates(chain: Sequence[Link], candles: Sequence[Candle]
                             ) -> list[ZoneReading]:
    """Every structure-bounded span, measured. Reporting only — nothing is admitted."""
    idx = [i for i, ln in enumerate(chain) if ln.is_structure]
    out: list[ZoneReading] = []
    for ai, a in enumerate(idx):
        for b in idx[ai + MIN_ZONE_CHILDREN - 1:]:
            r = read_child_zones(chain, candles, a, b)
            if r is not None:
                out.append(r)
    return out


@dataclass(frozen=True, slots=True)
class ZoneTransition:
    """One trip between the two child zones — the rotation, told between shelves.

    This is what `rotated_to` should mean at canvas scale: not *"a close crossed a third
    of the raw span"* but *"price left this shelf and arrived at that one"*.
    """

    direction: str                 # "LOW->HIGH" | "HIGH->LOW"
    from_id: str
    to_id: str
    from_price: Decimal
    to_price: Decimal
    from_i: int
    to_i: int

    @property
    def points(self) -> Decimal:
        return abs(self.to_price - self.from_price)

    @property
    def bars(self) -> int:
        return self.to_i - self.from_i


def zone_transitions(reading: ZoneReading, chain: Sequence[Link]) -> list[ZoneTransition]:
    """Every LOW<->HIGH trip inside a candidate, with the shelves it ran between."""
    by_id = {ln.id: ln for ln in chain}
    kids = [by_id[cid] for cid in reading.children if cid in by_id]
    out: list[ZoneTransition] = []
    for a, b in zip(kids, kids[1:]):
        za = "LOW" if a.mid <= reading.split else "HIGH"
        zb = "LOW" if b.mid <= reading.split else "HIGH"
        if za != zb:
            out.append(ZoneTransition(f"{za}->{zb}", a.id, b.id, a.mid, b.mid,
                                      a.end, b.start))
    return out


@dataclass(frozen=True, slots=True)
class Selection:
    """A candidate plus what happened to it. `reason` is the whole point of this type."""

    reading: ZoneReading
    reason: str          # accepted | accepted-nested | rejected-* …
    depth: int = 0


def select_non_overlapping(readings: Sequence[ZoneReading], chain: Sequence[Link], *,
                           min_alternations: int = MIN_ALTERNATIONS,
                           use_shelf_ratio: bool = True) -> list[Selection]:
    """Widest first; accept if disjoint from everything accepted, or strictly nested.

    **Report only.** Nothing here is admitted to a map, and the criteria are named so the
    rejection reason for every single candidate can be read off:

        accepted                a top-level parent
        accepted-nested         strictly inside an accepted one, with fewer children
        rejected-separation     the two zones are not further apart than a shelf is thick
        rejected-no-alternation the children never flip LOW <-> HIGH enough
        rejected-unbounded      price ended outside the envelope it started in
        rejected-migrating      the span is a one-way walk
        rejected-overlap        it partially overlaps an already-accepted candidate
        rejected-duplicate      nested but describing the same shelves

    Partial overlap is refused rather than merged because two ranges that half-cover each
    other is not a thing a chart can show, and the trader has to be able to point at one.

    ## What counts as a *different* nested range

    Time containment plus "fewer children" is not enough. Measured on 2026-02-16 it
    accepted ten parents that were all the same range with one child shaved off each end:

        c0-955  c0-922  c0-884  c0-856  c38-856  c41-856  c55-856  c92-856 ...

    Identical LOW zone, identical HIGH zone, identical two transitions. A shorter window
    onto one auction is not a second auction. So a nested candidate is admitted only if
    it carries **a rotation its ancestor does not** — the transitions are the range's
    identity, and a subset of them describes the same thing.
    """
    out: list[Selection] = []
    accepted: list[ZoneReading] = []
    trans_of = {id(r): {(t.from_id, t.to_id) for t in zone_transitions(r, chain)}
                for r in readings}

    for r in sorted(readings, key=lambda z: (-z.bars, z.start)):
        ratio = r.shelf_ratio if use_shelf_ratio else r.separation_ratio
        if ratio < 1.0:
            out.append(Selection(r, "rejected-separation"))
            continue
        if r.alternations < min_alternations:
            out.append(Selection(r, "rejected-no-alternation"))
            continue
        if not r.bounded:
            out.append(Selection(r, "rejected-unbounded"))
            continue
        if r.migration > MAX_SPAN_MIGRATION:
            out.append(Selection(r, "rejected-migrating"))
            continue

        depth, clash = 0, False
        for a in accepted:
            nested = a.start <= r.start and r.end <= a.end
            disjoint = r.end < a.start or r.start > a.end
            if nested:
                if not (trans_of[id(r)] - trans_of[id(a)]):
                    out.append(Selection(r, "rejected-duplicate"))
                    clash = True
                    break
                depth = max(depth, 1)
            elif not disjoint:
                out.append(Selection(r, "rejected-overlap"))
                clash = True
                break
        if clash:
            continue

        accepted.append(r)
        out.append(Selection(r, "accepted-nested" if depth else "accepted", depth))
    return out


__all__ = ["Node", "Relation", "Rotation", "StructureMap", "MAX_SPAN_MIGRATION",
           "validate_range", "find_parent_ranges", "assign_tree", "apply_semantics",
           "build_relations", "build_map", "tree_text",
           "MIN_ZONE_CHILDREN", "MIN_ALTERNATIONS", "ZoneReading", "ZoneTransition",
           "Selection", "read_child_zones", "survey_parent_candidates",
           "zone_transitions", "select_non_overlapping"]
