"""HISTORICAL REFERENCE INTELLIGENCE — which few references matter *now*.

```
MapState.above.corridor  ┐
MapState.below.corridor  ├─ already published, already ordered by price
Node.parent / Node.kind  │
LiveThesis.idea          ┘
          ↓
    ReferencePath            ← this module: ROLES, not scores
          ↓
  IMMEDIATE · NEXT · MAJOR · FAR · COUNTER_THESIS
```

## There is no score in this file, and that is the design

No `importance`, no `strength`, no `confidence`, no `priority`, no weight, no probability,
no ML ranking, no coefficient, and **no ATR cutoff invented here**. A reference is not
*better* than another; it has a different **structural role in the current path**, and each
role has a definition that can be read off published facts and checked by hand.

`test_no_reference_field_is_a_score` asserts it against the dataclass, and
`test_no_reason_implies_probability` asserts it against the English.

## Nearest is not most important

`IMMEDIATE` is *the first distinct mapped boundary in price order* — a statement about
order, not worth. A small child edge can be `IMMEDIATE` while the `MAJOR` boundary that
actually changes the map context sits far behind it. Both are reported, separately, with
their distances intact. Collapsing them into one "best level" is what this layer exists to
avoid.

## What is aggregated, and what is deliberately not

§7 asks for nearby boundaries to be presented as one structural area. Measured over teach
and validate before building anything, adjacent corridor stops relate like this:

```
                                    teach     validate
same structure (its own near+far)   19.8%      27.9%
siblings (same declared parent)      1.8%       1.6%
parent/child                         0.4%       1.1%
UNRELATED by any published fact     78.0%      69.4%
```

**587 teach pairs sit at exactly the same price and not one of them is related by any
published fact.** So the existing facts can define an area for *one structure's own two
edges* and for declared kin, and they cannot define one for the other three quarters.
§8 says report that rather than invent a clustering threshold, so only the relations the
map already publishes are aggregated here, and the rest are reported as a gap in
`HISTORICAL-REFERENCES.md`. A price-distance rule invented to tidy the chart would be a
threshold nobody earned.

## Three different nesting facts, kept apart

```
Node.parent            MAP HIERARCHY        declared containment    18 nodes in teach
Release.parent_id      EVENT CONTAINMENT    what a release happened inside
route.nested_stops()   PRICE-ORDER SHAPE    outer.near < inner.near < inner.far < outer.far
```

The last one is a corridor ordering shape and fires on 3,014 teach pairs — two orders of
magnitude more often than declared parenthood. They are three questions and this module
never renders them with one word.

## Roles are a view, never a label on the structure

A structure is not "an IMMEDIATE". It *is* immediate on this candle, in this direction,
from this price. `C03` that was `IMMEDIATE` becomes `behind price` the moment price crosses
it and `C12` takes the role. Nothing is written back to the map — `build()` is a pure
function of `(mapstate, nodes, thesis direction)` and mutates nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence

from src.livemap import route as RT
from src.livemap import thesis as TH

# ── §6 ROLES. Closed, and every member has a structural definition below ─────
IMMEDIATE = "IMMEDIATE"
NEXT = "NEXT"
MAJOR = "MAJOR"
FAR = "FAR"
COUNTER_THESIS = "COUNTER_THESIS"
CURRENT_BOUNDARY = "CURRENT_BOUNDARY"
PARENT_BOUNDARY = "PARENT_BOUNDARY"
NESTED_BOUNDARY = "NESTED_BOUNDARY"
ROLES = frozenset({IMMEDIATE, NEXT, MAJOR, FAR, COUNTER_THESIS, CURRENT_BOUNDARY,
                   PARENT_BOUNDARY, NESTED_BOUNDARY})

#: §16 what the chart draws without being asked. The rest stays available behind a toggle;
#: nothing is deleted, only de-prioritised.
PRIMARY_ROLES = frozenset({CURRENT_BOUNDARY, IMMEDIATE, NEXT, MAJOR})
SECONDARY_ROLES = frozenset({FAR, COUNTER_THESIS, PARENT_BOUNDARY, NESTED_BOUNDARY})

#: §29 the deterministic reason for each role. Read as *"why is this here?"*. No word in
#: any of these implies a probability, a target or a recommendation.
REASON = {
    IMMEDIATE: "first distinct mapped boundary in price order along this path",
    NEXT: "next distinct structure after the immediate boundary",
    MAJOR: "broader enclosing structural boundary — a range edge, or the parent of a "
           "nearer boundary",
    FAR: "beyond the near path; not the boundary price meets next",
    COUNTER_THESIS: "nearest mapped boundary against the current thesis direction",
    CURRENT_BOUNDARY: "an edge of the structure price is standing inside",
    PARENT_BOUNDARY: "an edge of the structure that contains the current structure",
    NESTED_BOUNDARY: "its declared map parent is also a boundary on this path",
}

#: §30. The route is a path, never a destination. Asserted against every reason string.
FORBIDDEN_WORDS = ("target", "likely", "expected to", "probability", "strong", "weak",
                   "confidence", "score", "should reach", "will reach", "profit")

UP, DOWN = "up", "down"


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Reference:
    """One structural boundary, with the role it plays in the path **right now**.

    Every field is a copy of a published fact or a role/reason derived from them. There is
    deliberately no numeric field that ranks this against another reference.
    """

    role: str
    structure_id: str
    edge: str                       # near | far — `route.NEAR` / `route.FAR`
    price: Decimal
    kind: str                       # cluster | range
    parent_id: str | None           # Node.parent — MAP HIERARCHY, not release containment
    distance: Decimal               # magnitude from the corridor's origin edge
    distance_atr: float
    route_position: int             # index in the published corridor, price order
    direction: str                  # up | down — which path this belongs to
    reason: str
    area_id: str | None = None      # set when this stop is part of a structural area

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown reference role {self.role!r}")
        if self.edge not in (RT.NEAR, RT.FAR):
            raise ValueError(f"unknown edge {self.edge!r}")
        if self.direction not in (UP, DOWN):
            raise ValueError(f"unknown direction {self.direction!r}")
        low = self.reason.lower()
        for word in FORBIDDEN_WORDS:
            if word in low:
                raise ValueError(
                    f"a reference reason may not contain {word!r} — a reference is a "
                    f"path fact, never a target or a probability: {self.reason!r}")

    @property
    def label(self) -> str:
        """`C03.low` / `C03.high` — which physical edge this is.

        `build_corridor` pairs `(NEAR, node.low), (FAR, node.high)` going **up** and the
        reverse going down, so travelling up you meet a structure's low first. Writing it
        the other way round labels every reference with the wrong edge, which is exactly
        the kind of mistake a chart makes look correct.
        """
        near_side = "low" if self.direction == UP else "high"
        far_side = "high" if self.direction == UP else "low"
        return f"{self.structure_id}.{near_side if self.edge == RT.NEAR else far_side}"

    def line(self) -> str:
        return (f"{self.role:<17}{self.structure_id:<7}{self.edge:<6}"
                f"{float(self.price):>10,.0f}{float(self.distance):>8,.0f} pts   "
                f"{self.kind}"
                + (f"  ⊂ {self.parent_id}" if self.parent_id else ""))


@dataclass(frozen=True, slots=True)
class StructuralArea:
    """Boundaries that the map itself says belong together, presented as one thing.

    **Only relations the map publishes.** Today that is a single structure's own two edges;
    the measured alternative — grouping by price proximity — would need a threshold this
    project has not earned and would merge unrelated structures three quarters of the time.
    Members are preserved in full so no identity is lost (§7).
    """

    id: str
    low: Decimal
    high: Decimal
    members: tuple[Reference, ...]
    reason: str

    @property
    def band(self) -> str:
        return f"{float(self.low):,.0f}–{float(self.high):,.0f}"

    def line(self) -> str:
        return (f"{self.id:<10}{self.band:<20}"
                + " · ".join(m.label for m in self.members))


@dataclass(frozen=True, slots=True)
class DirectionalPath:
    """One side of the map, in price order, with roles assigned."""

    direction: str
    references: tuple[Reference, ...] = ()
    areas: tuple[StructuralArea, ...] = ()
    #: `route.nested_stops()` output — the PRICE-ORDER enclosure shape, which is not the
    #: declared hierarchy and is never rendered as if it were.
    enclosures: tuple[tuple[str, str], ...] = ()

    def _first(self, role: str) -> Reference | None:
        return next((r for r in self.references if r.role == role), None)

    @property
    def immediate(self) -> Reference | None:
        return self._first(IMMEDIATE)

    @property
    def next(self) -> Reference | None:
        return self._first(NEXT)

    @property
    def major(self) -> Reference | None:
        return self._first(MAJOR)

    @property
    def far(self) -> tuple[Reference, ...]:
        return tuple(r for r in self.references if r.role == FAR)

    @property
    def primary(self) -> tuple[Reference, ...]:
        return tuple(r for r in self.references if r.role in PRIMARY_ROLES)

    def lines(self) -> list[str]:
        head = f"{self.direction.upper()} PATH"
        if not self.references:
            return [f"{head:<12}nothing mapped ahead"]
        return [f"{head:<12}"] + [f"  {r.line()}" for r in self.references]


@dataclass(frozen=True, slots=True)
class ReferencePath:
    """Both directions, the active one named, and the invalidation kept separate.

    §14: `invalidation_price` is **copied from the thesis**, which owns it. This layer
    never recomputes it and never lets a historical cluster stand in for it.
    """

    index: int
    at: datetime
    price: Decimal
    up: DirectionalPath
    down: DirectionalPath
    #: `up` | `down` | `None` — the current thesis's own direction, copied. `None` means
    #: no thesis has set one, and then neither path is "the" path.
    active: str | None = None
    current_id: str | None = None
    current_boundaries: tuple[Reference, ...] = ()
    counter: Reference | None = None
    invalidation_price: Decimal | None = None
    invalidation_rule: str = ""

    @property
    def active_path(self) -> DirectionalPath | None:
        return {UP: self.up, DOWN: self.down}.get(self.active or "")

    @property
    def counter_path(self) -> DirectionalPath | None:
        return {UP: self.down, DOWN: self.up}.get(self.active or "")

    def lines(self) -> list[str]:
        out = [f"PRICE         {float(self.price):,.1f}   c{self.index}"
               f"   current {self.current_id or '—'}"]
        out.append(f"ACTIVE PATH   {self.active or 'none — no thesis direction'}")
        for ref in self.current_boundaries:
            out.append(f"  {ref.line()}")
        out.extend(self.up.lines())
        out.extend(self.down.lines())
        if self.counter is not None:
            out.append("COUNTER")
            out.append(f"  {self.counter.line()}")
        out.append("INVALIDATION  "
                   + ("—" if self.invalidation_price is None
                      else f"{float(self.invalidation_price):,.1f}   "
                           f"{self.invalidation_rule}"))
        return out


# ═════════════════════════════════════════════════════════════════════════════
# §10 the discovery pipeline. No scoring stage, no weighting stage.
# ═════════════════════════════════════════════════════════════════════════════
def _areas(stops: Sequence[RT.CorridorStop], direction: str,
           nodes: Mapping[str, object]) -> dict[str, StructuralArea]:
    """Group the boundaries the map already says are one thing.

    A structure contributing both its edges to this path is one structural area spanning
    them — that is `ZoneRoute`'s near-edge/far-edge story, restated per structure. Nothing
    else is grouped, because nothing else is published as a grouping.
    """
    by_id: dict[str, list[RT.CorridorStop]] = {}
    for s in stops:
        by_id.setdefault(s.ref_id, []).append(s)
    out: dict[str, StructuralArea] = {}
    for ref_id, members in by_id.items():
        if len(members) < 2:
            continue
        prices = [m.price for m in members]
        out[ref_id] = StructuralArea(
            id=ref_id, low=min(prices), high=max(prices), members=(),
            reason="one structure contributing both of its edges to this path")
    return out


def _major_id(stops: Sequence[RT.CorridorStop], nodes: Mapping[str, object]) -> str | None:
    """Which structure is the broader one. **Published facts only.**

    Two published ways a boundary is broader, checked in order:

    1. its node is a `range` — the map's own word for the enclosing kind;
    2. its node is the declared `parent` of a nearer boundary's node.

    If neither holds anywhere on this path there is no MAJOR, and the path says so rather
    than promoting the furthest stop to fill the slot.
    """
    seen: list[str] = []
    for s in stops:
        node = nodes.get(s.ref_id)
        if node is not None and getattr(node, "kind", None) == "range":
            return s.ref_id
        if any(getattr(nodes.get(prev), "parent", None) == s.ref_id for prev in seen):
            return s.ref_id
        seen.append(s.ref_id)
    return None


def _side(stops: Sequence[RT.CorridorStop], direction: str,
          nodes: Mapping[str, object], *, current_id: str | None,
          current_parent: str | None) -> DirectionalPath:
    """Assign a role to every published corridor stop, in the published order."""
    if not stops:
        return DirectionalPath(direction=direction)

    areas = _areas(stops, direction, nodes)
    major_id = _major_id(stops, nodes)

    refs: list[Reference] = []
    immediate_id: str | None = None
    next_id: str | None = None
    members: dict[str, list[Reference]] = {}

    for position, s in enumerate(stops):
        node = nodes.get(s.ref_id)
        parent = getattr(node, "parent", None) if node is not None else None

        # ── the role, first match wins, and the order IS the definition ──────
        if s.ref_id == current_id:
            role = CURRENT_BOUNDARY
        elif current_parent is not None and s.ref_id == current_parent:
            role = PARENT_BOUNDARY
        elif immediate_id is None:
            role, immediate_id = IMMEDIATE, s.ref_id
        elif s.ref_id == immediate_id:
            # the immediate structure's own second edge — same area, not a new decision
            role = IMMEDIATE
        elif s.ref_id == major_id:
            role = MAJOR
        elif next_id is None:
            role, next_id = NEXT, s.ref_id
        elif s.ref_id == next_id:
            role = NEXT
        elif parent is not None and any(parent == r.structure_id for r in refs):
            role = NESTED_BOUNDARY
        else:
            role = FAR

        ref = Reference(
            role=role, structure_id=s.ref_id, edge=s.edge, price=s.price,
            kind=s.kind, parent_id=parent, distance=s.distance,
            distance_atr=s.distance_atr, route_position=position,
            direction=direction, reason=REASON[role],
            area_id=s.ref_id if s.ref_id in areas else None)
        refs.append(ref)
        if ref.area_id:
            members.setdefault(ref.area_id, []).append(ref)

    filled = tuple(
        StructuralArea(id=a.id, low=a.low, high=a.high,
                       members=tuple(members.get(a.id, ())), reason=a.reason)
        for a in areas.values())
    return DirectionalPath(direction=direction, references=tuple(refs),
                           areas=filled,
                           enclosures=tuple(RT.nested_stops(stops)))


#: How deep to read the already-ordered corridor. **Not a threshold and not a ranking
#: cut** — `build_corridor` returns boundaries in price order and `SideReferences.corridor`
#: shows the first eight of them. The audit found the enclosing range boundary at position
#: 30 of 35 on the mandatory K/L candle, so eight is a presentation depth that hides the
#: one reference §20 requires. Reading the whole ordered list removes a cut rather than
#: adding one; the roles then decide what is primary, and `PRIMARY_ROLES` decides what the
#: chart draws.
DEPTH = 64


def deep_corridor(mapstate, pool: Sequence, *, up: bool) -> tuple:
    """The published corridor, read to the bottom instead of to the eighth stop.

    Uses `route.build_corridor`, the repo's own function, from the repo's own origin edge
    (`current.high`/`current.low`, else price — exactly `interpreter._side`'s rule) over
    the repo's own causally-filtered pool. It is the same corridor, not a second one, and
    `test_the_deep_corridor_extends_the_published_one` pins that its first eight stops are
    identical to `SideReferences.corridor`.
    """
    current = mapstate.current
    origin = (current.high if up else current.low) if current is not None         else mapstate.price
    exclude = current.id if current is not None else None
    known = [n for n in pool if n.id != exclude]
    return RT.build_corridor(known, origin, up=up, atr=mapstate.atr, limit=DEPTH)


def build(mapstate, nodes: Mapping[str, object], *, idea: str = TH.NO_IDEA,
          invalidation_price: Decimal | None = None,
          invalidation_rule: str = "",
          pool: Sequence | None = None) -> ReferencePath:
    """One candle's reference hierarchy. Pure function of already-published facts.

    `mapstate` is `interpreter.MapState` — its `above`/`below` corridors are already
    ordered by actual price, which is why no ordering happens here (§4, §11). `nodes` is
    the id→`Node` map of structures that exist **at this candle**; passing a later node set
    is what would leak the future, and the observatory's frozen-per-candle geometry is
    where it comes from.
    """
    current_id = mapstate.current.id if mapstate.current is not None else None
    current_parent = (mapstate.current.parent_id
                      if mapstate.current is not None else None)

    up_stops = (deep_corridor(mapstate, pool, up=True) if pool is not None
                else mapstate.above.corridor)
    down_stops = (deep_corridor(mapstate, pool, up=False) if pool is not None
                  else mapstate.below.corridor)

    up = _side(up_stops, UP, nodes,
               current_id=current_id, current_parent=current_parent)
    down = _side(down_stops, DOWN, nodes,
                 current_id=current_id, current_parent=current_parent)

    active = (UP if idea == TH.LONG_IDEA else
              DOWN if idea == TH.SHORT_IDEA else None)

    counter = None
    if active is not None:
        other = down if active == UP else up
        first = other.immediate
        if first is not None:
            counter = Reference(
                role=COUNTER_THESIS, structure_id=first.structure_id, edge=first.edge,
                price=first.price, kind=first.kind, parent_id=first.parent_id,
                distance=first.distance, distance_atr=first.distance_atr,
                route_position=first.route_position, direction=first.direction,
                reason=REASON[COUNTER_THESIS], area_id=first.area_id)

    current_boundaries = tuple(r for r in (up.references + down.references)
                               if r.role in (CURRENT_BOUNDARY, PARENT_BOUNDARY))

    return ReferencePath(
        index=mapstate.index, at=mapstate.at, price=mapstate.price,
        up=up, down=down, active=active, current_id=current_id,
        current_boundaries=current_boundaries, counter=counter,
        invalidation_price=invalidation_price, invalidation_rule=invalidation_rule)


# ═════════════════════════════════════════════════════════════════════════════
def no_score_fields() -> list[str]:
    """§17 / §36 — every field name that could hold a rank. Must stay empty."""
    banned = ("score", "weight", "importance", "strength", "confidence", "priority",
              "probability", "rank", "quality")
    out = []
    for cls in (Reference, StructuralArea, DirectionalPath, ReferencePath):
        out += [f"{cls.__name__}.{f.name}" for f in fields(cls)
                if any(b in f.name.lower() for b in banned)]
    return out


__all__ = ["DEPTH", "deep_corridor", "IMMEDIATE", "NEXT", "MAJOR", "FAR", "COUNTER_THESIS", "CURRENT_BOUNDARY",
           "PARENT_BOUNDARY", "NESTED_BOUNDARY", "ROLES", "PRIMARY_ROLES",
           "SECONDARY_ROLES", "REASON", "FORBIDDEN_WORDS", "UP", "DOWN",
           "Reference", "StructuralArea", "DirectionalPath", "ReferencePath",
           "build", "no_score_fields"]
