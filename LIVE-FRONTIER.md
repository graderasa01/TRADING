# LIVE MAP FRONTIER + STRUCTURE LIFECYCLE — plan (rev 2)

> Builds on `CLUSTER-RANGE-MAP.md` (local detector) and the historical layer in
> `src/boxes/structure.py`, `hierarchy.py`, `anchors.py`.
> Sources: `ideas/Second_idea_add_in_first_idea.md`,
> `ideas/first_idea_make_better_with_second_thinking.md`, plus the rev-1 review.

---

## 0. FOUR CONCEPTS THAT MUST NEVER BLUR

Rev 1 of this plan blurred the first two and produced a wrong worked example. They are
listed first so it cannot happen again.

| concept | what it is |
|---|---|
| **Structure boundary** | the current structure's own edge. **This is the breakout point.** |
| **Next structural reference** | the next mapped object in that direction. A place to look at — **never** a boundary to break, and never a promised target. |
| **Live frontier** | structure forming in the market right now, provisional until confirmed |
| **Historical map** | what price has already left behind, immutable |

```
BREAK_LEVEL_UP    = current structure's own high
BREAK_LEVEL_DOWN  = current structure's own low
NEXT reference    = somewhere else entirely
```

---

## 1. THE ONE SENTENCE

The historical map says **where things are**; live candles say **what is happening now**;
a rolling frontier turns "now" into "history" one structure at a time — and the decision
layer is not built here.

---

## 2. WHERE THE WORK ACTUALLY STANDS

Built and green (13 new tests + 367 suite, ruff clean, coverage exactly 1000/1000 on five
real sessions):

| module | what it does | admitted to the map? |
|---|---|---|
| `structure.py` | backward scan, `extend_back`, `last_touch`, move classifier, seams, gaps | **yes** — the chain is the map |
| `hierarchy.py` | containment tree, event graph, semantics | **yes** for the tree/graph |
| `hierarchy.py` (survey) | child-zone parent-range candidates | **no** — measurement only |
| `anchors.py` | swing/origin anchors from the shared `swings.py` | **no** — measurement only |

**Three rules are still unvalidated hypotheses and the Step 4 STOP has not been passed:**
the impulse gate (`er >= 0.5`), the parent-range criteria (shelf-width separation,
`alternations >= 2`), and the anchor displacement rule.

The frontier therefore consumes the map through the `Node` contract, never through the
admission rules. Admission can change afterwards without touching frontier code. What
*will* change is how rich the answers are: if parents and anchors stay unadmitted,
ABOVE/BELOW is clusters-only and the reference list is thin.

---

## 3. THE PRECEDENT THIS PLAN COPIES

`src/journey/ladder.py` already solved the governance half of this problem, for the same
kind of idea — a strong trader intuition that had never been measured:

* it lives in **its own package** so `setups/`, `risk/` and `exits/` cannot import it;
* `test_journey_never_read_by_the_trading_path` asserts that **statically**;
* `journey_gates_trades` stays `false` until P9 measures the hit rate;
* its docstring says the quiet part out loud — *"a strong intuition that has never been
  measured is exactly the kind of thing that quietly becomes a rule and then quietly
  loses money."*

So this plan does not invent a governance model. It reuses the repo's.

---

## 4. ARCHITECTURE

```
                       BANK NIFTY 1m closed candles
                                   │
                       FROZEN HISTORICAL MAP  (M001)
                   clusters / ranges / anchors / moves
                                   │
                                   +
                            LIVE FRONTIER  (F001)
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
          LOCATION             STRUCTURE              EVENT
          where price is       cluster / range        break · retest
                               forming                re-entry · failure
              └────────────────────┼────────────────────┘
                                   ▼
                            CURRENT CONTEXT
                         ABOVE / CURRENT / BELOW
                                   │
                     NEXT STRUCTURAL REFERENCES
                                   │
        ═══════════════════════════╪═══════════════════  QUARANTINE LINE
                                   ▼
                    DECISION LAYER — NOT BUILT HERE
```

**Three laws.**

1. **The historical map is never rewritten backwards.** Live state is `M001 + F001`.
   An explicit rebuild produces `M002`. A live candle never mutates `M001`.
2. **No third detector.** Live structures are found by `adaptive.choose()` and bounded by
   `structure.extend_back` / `last_touch` — the same code the historical scan uses.
   Anchors already follow this rule with `swings.py`; the frontier follows it too.
3. **Live and frozen objects are never the same instance.** `LiveNode` is mutable and
   lives in `F001`; finalising **constructs a new frozen `Node`**. Sharing one instance
   would make the immutable snapshot mutable through a back door.

---

## 5. PHASE A — `snapshot.py`, the freeze that was planned and never built

```python
@dataclass(frozen=True, slots=True)
class MapSnapshot:
    version: str            # rendered "M001 @ i=1000 · 16 Feb 15:29 IST", never bare
    symbol: str
    built_at: datetime
    built_at_index: int
    first_index: int
    nodes: tuple[Node, ...]
    relations: tuple[Relation, ...]
```

* immutable by construction — `frozen=True` and tuples throughout;
* `LiveEvent(kind, node_id, index, direction, level)` accumulates in a **separate
  append-only** list;
* `diff(M001, M002)` reports which nodes survived, moved or vanished;
* **a snapshot is "the map as observed when built at index `i`", not a claim about the
  market forever.**

---

## 6. PHASE B — the frontier

### 6.1 Lifecycle and events are different things

Rev 1 put `BROKEN` inside the lifecycle. It does not belong there: a break is something
that **happens to** a structure, not something a structure **is**.

```
LIFECYCLE                 EVENTS (recorded against a node, never a status)
PROVISIONAL               BREAK
     ↓                    RETEST
CONFIRMED                 RE_ENTRY
     ↓                    FAILURE
HISTORICAL                TOUCH · ACCEPTANCE
```

```
C42
  status      = HISTORICAL
  broken_at   = 1034
  direction   = UP
```

### 6.2 The state machine — and why cluster does not become range

```
                 MOVING
                   │
                   ├──── price is leaving a confirmed structure ──▶ LEAVING
                   │
                   ▼
          STRUCTURE_CANDIDATE          a provisional band, not yet a box
                   │
                   ▼   adaptive.choose() confirms
                   │   AND last_touch says price is actually HERE
               CONFIRMED
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
     CLUSTER               RANGE
  cluster evidence      range evidence, established INDEPENDENTLY
        └──────────┬──────────┘
                   ▼  price leaves and stays away
              HISTORICAL
```

**`LIVE_CLUSTER → LIVE_RANGE` is deleted.** A cluster becoming a range by seniority is
exactly the conflation the whole historical layer exists to prevent — it is why
`traverses` and `migration` were written, and why a 1,400-span survey rejected 1,395.
A live range needs its own two-sided evidence, or it is not a range.

### 6.2a `CONFIRMED` — the exact contract

**The frontier does not classify.** `adaptive.read_window()` fills two independent slots,
and `choose()` returns the smallest stable window for each. The frontier reads the slot;
it never decides a kind. That is law 2 applied to classification as well as to detection.

| | gate — all of it already exists, none of it is re-implemented |
|---|---|
| **CONFIRMED_CLUSTER** | `choose()` cluster slot non-`None` — which already means `core_band` found a band, `mean(occupancy, compression, reaction) − migration >= min_score`, and the same band held across `STABILITY_RUN` successive windows — **plus** §6.4 currency |
| **CONFIRMED_RANGE** | `choose()` range slot non-`None` — which already means `upper_touches >= 2` **and** `lower_touches >= 2` **and** `traverses >= 2`, then `mean(upper, lower, rotation, compression) − migration >= min_score`, stable across `STABILITY_RUN` — **plus** §6.4 currency |

**If both slots come back non-`None`, they are two separate live objects, not one object
with two labels.** Their containment relationship is `hierarchy.assign_tree`'s job, exactly
as on the historical side. A cluster is never evidence toward a range, in either
direction.

### 6.3 `LEAVING` is a state, not twenty new boxes

```
22460-22480 cluster
price: 22482 22488 22497 22510 22520 22530 22540 22550
```

Every one of those candles must **not** produce a box. The frontier reports:

```
CURRENT FRONTIER: LEAVING C41
```

Without an explicit `LEAVING` state the *"har pause ek box"* failure comes straight back
on the live side, having been fixed twice on the historical side.

**`LEAVING` never goes straight to a structure.** The full path is mandatory, and the
state machine must have no edge that skips it:

```
LEAVING              price is out of the old band but still near it
   │  the old node's band is no longer touched
   ▼
MOVING               travelling, belonging to nothing
   │  choose() returns a proposal AND §6.4 currency holds
   ▼
STRUCTURE_CANDIDATE  provisional band
   │  §6.2a gates
   ▼
CONFIRMED
```

`LEAVING → STRUCTURE_CANDIDATE` and `LEAVING → CONFIRMED` are **forbidden transitions**
and get an explicit test. Without that, the engine can leave one shelf and immediately
declare the next one, which is the same leak wearing a different name.

### 6.4 `choose()` returning something is NOT "price is here"

This is the bug already caught once on real data: at candle 443 price was trading at
60,380-60,409 and the detector correctly returned a shelf at 60,271-60,309 — a real
structure price had **left eight candles earlier**. A forty-candle window is still
dominated by the shelf that filled it.

So the frontier requires three things before calling anything current:

```
detected band          from adaptive.choose()
+ last_touch           the newest candle that actually traded in it
+ current contact      last_touch is at or adjacent to the live candle
```

Two of three is not enough, and this gets its own test.

### 6.5 Anchors are candidates first

An anchor's significance is decided by what happens **after** it. At the moment a low
prints, nothing is known.

```
ANCHOR_CANDIDATE  ──displacement exceeds the departed shelf's width──▶ CONFIRMED
                                                                          ↓
                                                                      HISTORICAL
```

The 59,861 low on 16 Feb is exactly this case: worthless at the time, one of the most
important prices on the chart 70 candles later.

### 6.6 Cost rule

`on_candle()` must be **O(75)**, never O(1000). Re-running the backward scan every candle
would repaint the history law 1 forbids rewriting.

### 6.7 The corrected Bank Nifty walkthrough — the Phase B fixture

```
CURRENT CLUSTER   22460 ───────── 22480

22472   INSIDE_CURRENT_CLUSTER
22479   AT_UPPER_EDGE
22481   BREAK_ATTEMPT_UP        BREAK_LEVEL = 22480   ← the structure's OWN edge
22491   still BREAK_ATTEMPT_UP  acceptance is NOT defined yet — see §6.7a

        map: NEXT STRUCTURAL REFERENCE = 22560   (a reference, not a boundary)

22560   AT_NEXT_REFERENCE
        22556 22562 22559 22564 22558 22563
        LIVE_CLUSTER_CANDIDATE = 22556-22564     provisional
        → adaptive detector confirms → LIVE_CLUSTER_01

        breaks above 22564  →  BREAK_LEVEL = 22564, direction UP
                               look up the next reference again

        falls back below 22560  →  RE_ENTRY / FAILURE of that interaction,
                                   NOT a new breakout
```

Downside is the mirror: `price < 22460` is `BREAK_ATTEMPT_DOWN`.

### 6.7a ACCEPTANCE is deliberately left undefined

Rev 1's walkthrough had `22491 → ACCEPTED_ABOVE`, which quietly assumed a rule. There
isn't one, and inventing a threshold now would be the exact failure `CLUSTER-RANGE-MAP.md`
§11 warns about — a number fitted to the sample it was read on.

Consider:

```
22480 boundary   22481 crossed   22490 above   22479 back inside
```

Clearly not acceptance. But *how far*, and *for how many closes*, is not knowable from
first principles.

So Phase B **records the measurements and applies no gate**:

```
closes_beyond      how many consecutive closes finished past the edge
max_excursion      furthest travel beyond it, in points and in ATR
returned_inside    did a close come back within the band
bars_since_break
```

`ACCEPTED_ABOVE` / `ACCEPTED_BELOW` do not exist as states in Phase B. **The Step 2
fixture asserts the state sequence and the break level — `22480`, not `22500` — and must
not depend on any acceptance threshold.** The definition is written at Step 4, from the
recorded distributions on real days.

### 6.8 The test that decides whether this layer is honest

**Finalise-consistency.** Run the frontier forward over candles 800→1000 and finalise
everything. Separately run the batch historical scan over 0→1000. Compare.

**Compare CAUSAL fields only.** The batch scan has 1000 candles of hindsight; the frontier
has none. `structure.RETROSPECTIVE_FIELDS` already names the split — `exit`, `role`,
`parent`, `depth`, `location` are excluded, `kind`/`start`/`end`/`low`/`high`/`score` are
compared. Demanding equality on retrospective fields would be demanding that the live
layer know the future, and it would be "passed" by quietly leaking hindsight into it.

`swings.py` carries the same pin — *"a batch/stream divergence is how a backtest and a
live run end up disagreeing about the same day."*

**If they diverge, the plan is to report the divergence and its size, not to tune one
side until it matches the other.**

---

## 7. PHASE C — the Live Map Interpreter

Per closed candle, a structured state:

```
CURRENT:      C41  22460-22480        LOCATION:  upper third
BREAK_LEVELS: up 22480   down 22460   ← the current structure's own edges

ABOVE:        NEXT        C42  22556-22564   +80 pts
              NEXT_MAJOR  R4   22610-22700  +135 pts
              EXTENDED    A9   22840        +365 pts
BELOW:        NEXT        C40  22380-22405   -60 pts
              NEXT_MAJOR  R2   22200-22300  -180 pts
              EXTENDED    A8   22150        -310 pts

INTERACTION:  approaching_upper
REFERENCES:   C41.low 22460 · C41.high 22480 · retest band 22470-22480 · A8 22150
STATUS:       WAIT
```

### 7.1 References, not targets

Renamed from rev 1's `T1/T2/T3`, which read as promises:

```
NEXT         nearest structural object in that direction
NEXT_MAJOR   the next parent-scale object
EXTENDED     anchor / extreme
```

The map says *"the next mapped structural reference is 22560"*. It never says
*"target = 22560"*. Whether a reference is a viable target is a decision-layer question,
and the map has no basis for it.

**References are direction-specific ordered buckets, never one flat list.** A flat list
sorted by distance mixes the two sides, and the first consumer that forgets to filter gets
a downside object offered as an upside reference:

```python
@dataclass(frozen=True, slots=True)
class SideReferences:
    next: Node | None
    next_major: Node | None
    extended: Node | None

context.above.next        # 22556-22564
context.above.next_major  # 22610-22700
context.above.extended    # 22840
context.below.next        # 22380-22405
```

Each bucket is measured from the **edge that would break** — `current.high` going up,
`current.low` going down — not from the close. Measuring from the close while standing
inside a structure puts the reference behind the trigger, which is the exact bug that
killed the block map (`mapper.above()` already carries this rule and its reasoning).

### 7.2 `INVALIDATION` is not the interpreter's call

Rev 1 emitted `INVALIDATION: current cluster low`. That is prescriptive and often wrong —
depending on the setup the real invalidation may be the range boundary, the retest low, a
structural anchor, or the last defended level.

The interpreter emits a **`REFERENCES` list** with what each price is. Which one
invalidates a position is decided by a layer that knows what the position is — and that
layer does not exist yet.

### 7.3 Interaction vocabulary

```
APPROACH · TOUCH · REJECTION · ACCEPTANCE · BREAK · RETEST · RE_ENTRY ·
CONTINUATION · FAILURE
```

Judged against the map **as it stood before this candle closed** — the
`prior = f(candles[:i])` discipline already written and justified in
`src/boxes/events.py`, which exists because *"a breakout candle widens the very box it is
breaking, and the break hides itself."* `events.py` already distinguishes
`touch` / `sweep` / `break`; that vocabulary is extended here, not replaced.

### 7.4 Why this does not merge into `journey/ladder.py`

`JourneyRung` (`D1..D4`) is the same idea over `Level` objects from `levels/engine.py`;
this is over map `Node`s. Merging would make `journey/` depend on `boxes/`, and
`journey/`'s entire point is import isolation. Two independent answers to *"where is price
going"* is useful evidence; collapsing them early destroys it. They are compared in the
replay log instead.

### 7.5 What the interpreter may never emit

`STATUS` is a description of location and interaction only — `WAIT`,
`APPROACHING_UPPER_ZONE`, `BREAK_ATTEMPT_UP`, `ACCEPTED_ABOVE`, `BREAKOUT_FAILED`.
Never `LONG`, `SHORT`, `ENTRY`, a size, or a stop price.

---

## 8. PHASE D — quarantine and replay log

* the interpreter lives in its own package, `src/livemap/`;
* `test_livemap_never_read_by_the_trading_path` statically asserts that `setups/`,
  `risk/`, `exits/`, `modes/` and `broker/` do not import it — mirroring
  `test_journey_never_read_by_the_trading_path`;
* config flag `livemap_gates_trades: false`, marked **HYPOTHESIS**, that nothing reads.

The replay log, four columns:

```
MAP STATE  |  LIVE STATE  |  WHAT WOULD I DO  |  WHAT HAPPENED
```

`WHAT WOULD I DO` is a **read-only** shadow evaluator. It places no orders and gates
nothing. That comparison — not a chart that looks right — is what decides whether the map
improves decision quality.

`CLAUDE.md` §11 applies from the first run: on monthly Bank Nifty options the round trip
is 44-64% of a 25-point R, so a shadow evaluator that looks profitable gross may be
worthless. Costs go in the log from day one.

---

## 9. BUILD ORDER

| step | deliverable | gate |
|---|---|---|
| 1 | `snapshot.py` — `MapSnapshot`, `LiveEvent`, `diff()` | immutability + append-only tests green |
| 2 | `frontier.py` — lifecycle, `LEAVING`, candidate→confirmed, cluster/range classified independently | §6.7 walkthrough as a fixture; §6.4 three-part currency test |
| 3 | **finalise-consistency on causal fields** | divergence measured and reported |
| **STOP** | **review** | the previous STOP is still open — impulse / parent-range / anchor verdicts land here, before the interpreter is shaped around them |
| 4 | `src/livemap/interpreter.py` — LOCATION · INTERACTION · REFERENCES | per-candle state block on real days |
| 5 | quarantine test + `livemap_gates_trades: false` | static import assertion green |
| 6 | replay log + a rendered map film of a live session | four columns, costs included |

Step 3 ends the turn with the divergence number in hand.

---

## 10. WHAT THIS PLAN DOES NOT DO

* **No entry, no exit, no sizing, no order path.** `CLAUDE.md` §6 forbids a live order
  path at this stage.
* **It settles no threshold.** The impulse gate, the parent-range criteria and the anchor
  rule stay hypotheses; changing them later touches no frontier or interpreter code.
* **It promises no target.** Every forward-looking price is a *reference*.
* **It proves nothing about profitability.** `CLUSTER-RANGE-MAP.md` §11 stands: the last
  end-to-end box test was 19% win / −1.220R net over 790 trades.
* **A live frontier that agrees with history is only self-consistency.** It shows the two
  layers describe the same market. It does not show the description is useful.
