# STRUCTURAL OPPORTUNITY GEOMETRY — the layer, and how to look at it

> **Observation only.** No entry rule, no width threshold, no score, no probability, no
> ranking, no broker, no position. This milestone makes the machine *see* the geometry it
> had never reported; it decides nothing with it.
>
> Layer: [`src/livemap/geometry.py`](src/livemap/geometry.py).
> Study: [`reports/STRUCTURAL_OPPORTUNITY_GEOMETRY_AUDIT.md`](reports/STRUCTURAL_OPPORTUNITY_GEOMETRY_AUDIT.md).

---

## 0. WHY THIS EXISTS

Brains V1, V2 and V3 all tried to make Broad-rotation participation work by changing
*when* to join a rotation. All three failed, and the last audit closed historical
rotation tuning with `ROTATION_PARTICIPATION_REMAINS_UNPROVEN`.

A question had been skipped: **is the controlling structure even big enough for an
internal edge-to-edge rotation to be a meaningful opportunity?**

The stack could say *"price is in C08"*. It could not say *"C08 is 20 points wide, price
is already two thirds of the way across it, and the next mapped reference above is 180
points away."* Those are different worlds and the machine could not tell them apart.

## 1. BROAD IS A ROLE, NOT A SIZE

This is the correction the whole milestone rests on.

| term | what it is |
|---|---|
| **Broad** / controlling structure | the **role** a node currently plays — the node price is standing in |
| **cluster** / **range** | the node's **kind**, from `boxes.structure.STRUCTURE_KINDS` |

A controlling structure may be 19 points wide or 484. The role says nothing about that.
`StructureGeometry` therefore reports `controlling.kind` verbatim and never emits
"Broad range" as if it were a kind. `test_the_role_never_renames_the_kind` pins it.

## 2. WHAT THE LAYER ANSWERS

Seven questions, and it deliberately stops before the eighth:

```
1  where is price                    PriceGeometry
2  what structure contains it        ControllingStructure
3  how large / spacious it is        width_points · width_atr
4  where the movement came from      MovementProvenance
5  how much internal room remains    InternalSpace
6  how much external room exists     ExternalSpace
7  which edge is the decision area   next_internal_landmark · immediate references
──────────────────────────────────────────────────────────────────────────────
8  should participation occur        NOT ANSWERED HERE
```

## 3. THE TWO MIDPOINTS ARE NOT THE SAME FIELD

```
controlling.midpoint      (low + high) / 2 of the frozen controlling node.
                          Does not move while that node is controlling.

movement.path_midpoint    midway between the FROZEN movement origin and that
                          movement's frozen destination. Exists only when both do.
```

They answer different questions and are never merged. For a rotation that starts at one
edge and targets the opposite one they happen to coincide; for an outside movement from a
released edge toward a mapped reference they do not, and there is no Broad midpoint at
all. `test_the_broad_midpoint_and_the_movement_path_midpoint_are_different_fields`.

## 4. INTERNAL SPACE STATES ARE TOPOLOGY, NOT THRESHOLDS

```
INTERNAL_GEOMETRY_AVAILABLE   inside, direction known, midpoint not yet passed
INTERNAL_GEOMETRY_CONSUMED    inside, direction known, midpoint already passed
AT_EDGE_DECISION              the map itself published this edge as approached
OUTSIDE_REFERENCE_AVAILABLE   price is outside, and a reference is mapped that way
NO_MAPPED_SPACE               nothing mapped ahead
UNKNOWN                       no movement direction established yet
```

Every one is derivable from a fact another layer already emitted. **There is no
`SMALL`/`BIG` state and no width cutoff anywhere**, because the population had never been
looked at and inventing a bound before looking is exactly the mistake the V1–V3 rotation
work already made. `test_the_layer_states_no_size_verdict_anywhere`.

## 5. MOVEMENT PROVENANCE

`MovementProvenance.events` is a compact, immutable chain of things that *happened*, not
a rolling window of candles:

```
STRUCTURE_BECAME_CONTROLLING · CONTROLLING_STRUCTURE_REPLACED
LOWER_EDGE_ORIGIN · UPPER_EDGE_ORIGIN
ACCEPTED_RELEASE_UP · ACCEPTED_RELEASE_DOWN · REENTRY
MIDPOINT_CROSSED · OPPOSITE_EDGE_REACHED · NEW_LOCAL_STRUCTURE_OBSERVED
```

Each event type appears at most once per movement, and one event is carried across a
hand-off so a reader can see where price came from, so the chain stays short by
construction. It reads:

```
c412 CONTROLLING_STRUCTURE_REPLACED C22 (cluster) @ 48,000.0 -> c412 LOWER_EDGE_ORIGIN …
```

### The anchor here is observational

`livemap/shadow.py` keeps its own movement anchor and **that one remains the decision
authority**. This layer never feeds it and never reads it, so a production runtime can
have geometry without constructing a research brain. That freedom is only safe if the
two agree, so agreement is measured rather than assumed:

- `test_the_observational_anchor_agrees_with_the_brain` — real teach block, candle for
  candle;
- the study's `G6_PROVENANCE_CAUSAL` gate — **36,250 TEACH candles, 0 mismatches**.

## 6. BROAD, MICRO AND LOCAL STAY APART

`LocalContext` carries Micro and the observational Local structure in separate fields,
each with its own id, bounds, width and price location, and neither is ever merged into
the controlling structure. Micro remains subordinate and Local remains unpublished
(`LOCAL_PUBLICATION = NO`); this layer describes them and grants them nothing.

## 7. HOW TO LOOK AT IT, CANDLE BY CANDLE

### The dashboard — graphical

```bash
python tools/dash.py
```

Then open `http://127.0.0.1:8765`, pick a teach block, press **Load**, and step with
**Reveal next candle ▸** / **◂** (or the arrow keys). The side panel gained five blocks:

```
Controlling structure   role · kind · id · high / midpoint / low · width pts and ATR
Price geometry          location · containment · distance to low / midpoint / high
Internal space          state · next landmark · room to landmark / midpoint / opposite
External space          immediate reference above and below, from the edge and from price
Movement                direction · origin · origin role · travelled · whole % · segment %
Provenance              the event chain that explains how price got here
Local context           Micro and observational Local, kept apart from the Broad
```

The chart gained a **geometry** layer toggle: the controlling structure's midpoint as a
dashed line labelled with its kind and width, and the movement origin as a dot joined to
the current close. Turn it off in the *Layers* row if it crowds the view.

### The terminal — deterministic and diffable

```bash
python tools/structure_inspector.py --episode 0 --from 120 --to 140
python tools/structure_inspector.py --episode 0 --index 133
python tools/structure_inspector.py --episode 0 --step        # Enter advances one candle
python tools/structure_inspector.py --episode 0 --narrowest 3 # the tightest Broads
python tools/structure_inspector.py --episode 0 --widest 3
```

One block per candle, ASCII only so a Windows console can print it:

```text
2023-08-08 14:45  c440  close 44,996.5
CONTROLLING   C08 cluster 44,970.5 / 45,023.7 / 45,076.9 | width 106.5 pts / 2.37 ATR
PRICE         INSIDE (INSIDE) | to low 26.0 | to mid -27.2 | to high 80.4
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C02.low 528.9 | below C05.high 30.7
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT
PATH MIDPOINT n/a   BROAD MIDPOINT 45,023.7
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    no recorded provenance
```

Both views render the **same** `StructureGeometry` objects — the dashboard builds them in
`observatory.frames_of`, the inspector in `tools/structure_inspector.py`, from the same
`GeometryObserver`. There is no second description of a candle.

**TEACH only.** `--bucket validate` is refused: VALIDATE stays aggregate-only, and a
candle-level trace of it would be a case-level disclosure. HOLDOUT is never loaded.

## 8. THE POPULATION STUDY

```bash
python tools/structure_geometry_study.py
```

Writes `reports/STRUCTURAL_OPPORTUNITY_GEOMETRY_AUDIT.md` and its JSON. It reports width,
internal room and external room distributions **by kind**, a per-candle census, and TEACH
case traces chosen by structural order — narrowest, widest, range-kind, least/most
internal room, release episodes, edge-to-edge episodes. **Never by outcome.**

## 9. WHAT THIS MILESTONE DID NOT DO

- no entry rule, and no change to any hypothesis, participation, risk or exit rule;
- no brain module modified — V1, V2 and V3 fingerprints reproduce unchanged;
- no width threshold defined and none searched for;
- `R2_CLUSTER`, `R2_RANGE`, `R4_MICRO` and `LOCAL_PUBLICATION` unchanged;
- no broker, no live execution, no sizing.

## 10. THE QUESTIONS IT HANDS BACK

1. Which controlling structures actually have meaningful internal room, and is that a
   property of the structure or of where price entered it?
2. When the controlling structure is compressed, does the movement that matters more
   often happen beyond its edge than inside it?
3. Does provenance distinguish price *arriving* into a structure with momentum from price
   *rotating* inside one it has been in for a while?
4. Do local structures form inside the wider controlling structures often enough to carry
   entry and risk themselves?
5. Should the controlling structure define context while a local structure defines entry
   and invalidation?

Answering any of these by fitting a cutoff to this same already-observed data would
repeat the V1–V3 mistake. The next milestone decides *how to model participation*, and it
must be preregistered before it is implemented.
