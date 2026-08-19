# VISUAL REACTIVE TRADER VALIDATION — the Observatory Dashboard

> One dashboard. Historical replay and live feed drive the **same** production pipeline.
>
> `EXECUTION_STATUS = UNAVAILABLE` · no broker · no order · no sizing · no risk ·
> no target · no trailing stop · `split.holdout()` not called · teach only.
>
> Prior stage: [`INTEGRATION-AND-EXECUTION-BOUNDARY.md`](INTEGRATION-AND-EXECUTION-BOUNDARY.md)

```bash
python tools/dash.py --open
```

---

## 1. ARCHITECTURE

```
                    ONE DASHBOARD  ·  session picker inside the UI
                                   │
              ┌────────────────────┴────────────────────┐
              │   tools/dashboard/server.py             │  stdlib http.server, no new deps
              │     GET  /api/catalog                   │  what can be loaded (teach only)
              │     GET  /api/session?key=&paper=       │  frames, built on demand + cached
              │     POST /api/live/open · GET /poll     │  paced feed → LiveSession
              └────────────────────┬────────────────────┘
                                   │  frames only — the server decides nothing
              ┌────────────────────┴────────────────────┐
              │   src/livemap/observatory.py  PRODUCTION │  Frame · Geometry · Why · events
              │   frames()          LiveSession          │  ONE engine, both modes
              └────────────────────┬────────────────────┘
                                   │
   OBSERVATION → RELEASE → THESIS → IDENTITY → PARTICIPATION → POSITION → BOUNDARY
```

| component | responsibility | facts it reads |
|---|---|---|
| `static/viewport.js` | pan · zoom · crosshair — **extracted from `tools/chart.py`** | none (domain-free, asserted) |
| `static/app.js` ChartCanvas | candles + 10 toggleable layers | `frame.geometry` only |
| TransportBar | session picker · play/pause/step/back · 1×/2×/5×/20× · Blind/System/Audit · Live | — |
| TraderPanel | the nine questions + market / release / thesis / participation / entry-vs-current | `frame.context`, `frame.state` |
| WhyPanel | codes + English + narrative | `frame.why` |
| EventTimeline | candle-by-candle, click freezes that candle | `frame.events` |
| ScenarioNav | A–O jump list | `observatory.scenarios()` |
| `dashboard/feed.py` | `ReplaySource` · `PacedSource` · `KiteSource` (stub) | — |

**Layers:** `boxes · history · micro · OUTER · INNER · MICRO · invalidation · path ·
position · candidates`. OUTER / INNER / MICRO toggle independently, so a multi-scale
candle can be taken apart one scale at a time.

## 2. THE NO-LOOKAHEAD RULE, AND THE BUG IT CAUGHT

A visual layer leaks the future somewhere no decision test looks: **the geometry**.
`frontier.history()` at the end of a run returns every node the frontier ever finalised,
including nodes finalised *after* the candle being drawn.

`observatory.geometry_track()` drives the frontier candle by candle and freezes the node
set at each step. Measured on teach block 0 — what the naive end-of-run read would have
drawn:

| candle | boxes that existed then | boxes an end-of-run read would draw |
|---|---|---|
| c410 | **0** | 6 — `L01 L02 L03 L04 L05 L06` |
| c440 | **1** — `L01` | 6 |
| c500 | **1** — `L01` | 6 |
| c600 | **3** — `L01 L02 L03` | 6 |
| c699 | 6 | 6 |

Five structures would have been drawn onto candle 440 before they existed — **including
`L02`, the structure a position later opens on.** `test_the_geometry_of_frame_k_is_what_a_fresh_run_to_k_produces`
rebuilds a fresh `Frontier` fed only *k* candles and requires equality.

`AUDIT` mode is the single deliberate exception, labelled as future information in the
panel, and it feeds nothing.

## 3. HISTORICAL AND LIVE ARE ONE ENGINE

`LiveSession` keeps **no fold of its own** — it appends the candle to the frontier and asks
`reactor.replay(upto=k)`, which the integration stage proved prefix-equal to a full run. A
private incremental fold here would be the second position fold the previous stage
established must never exist; a test greps the class for one.

| | result |
|---|---|
| `LiveSession` (candle at a time) vs `frames()` (batch), all fields | **identical**, 300/300 |
| a frame is never rewritten by a later candle | **held** |
| `test_the_live_route_and_the_historical_route_agree` | green |

**The broker adapter is not built, and says so.** `KiteSource` raises
`NotImplementedError` naming what it needs (websocket, tick→candle builder, session
calendar, credentials — none exist; `fetch_kite.py` is `historical_data` only). It does
not silently fall back to replay: a live mode that is secretly a replay is worse than no
live mode. `PacedSource` exercises the identical live code path on a wall clock, and the
dashboard cannot tell the difference — which is the point.

## 4. THE NINE QUESTIONS

`WHAT IS THE NEXT DEVELOPMENT?` had no surfaced fact. `thesis.LiveThesis.next_expected`
has been published since the thesis layer was built and was simply not on
`ParticipationContext`, so the panel would have had to invent the answer. **One additive
field**, copied not recomputed — and proved inert: the decision-surface digest over
teach + validate under both contracts is `65c8c919…0dfd09e9` with the field populated and
`65c8c919…0dfd09e9` with it blanked. **Identical.**

## 5. WHAT LOOKING AT IT ACTUALLY FOUND

Three defects that only a picture exposes. All three are fixed.

**1 — The map's own structures were never drawn.** The panel said `C03`, the release said
`inside C03`, the path said `next C06` — and none of those boxes appeared, because their
forming window ended before the visible range. A referenced past structure is now drawn as
a standing price band (`history` shows all of them).

**2 — The price scale was swallowed by a large box.** `R01` in teach block 4 is several
times the height of a 110-candle window; letting it set the band squashed every candle into
the bottom eighth. Candles now anchor the scale and a structure taller than the clamp runs
off the edge, as a price chart always has.

**3 — Two different "parent" facts were rendered with one symbol.** `node.parent` (map
hierarchy) and `release.parent_id` (what the release happened inside) can differ — on the
K/L candle the box reads `C10 ⊂ R01` while the release reads `inside C03`. Both are true
and they are different questions. The chart now writes `⊂` for hierarchy and `inside` for
the release's containing structure.

And one found before the UI existed: the first `scenarios()` decided nesting by comparing
two price bands and reported it on **284 of 300** candles. The map publishes **18** nested
nodes in the whole teach sample. Nesting is now read from `node.parent`. *A layer that
re-derives another layer's fact gets it wrong* — the same rule the last stage enforced on
the opportunity key, caught again here.

## 6. THE FIFTEEN SCENARIOS, LOCATED ON REAL CANDLES

`python tools/observatory.py --find` scans all 24 teach blocks:

| | scenario | blocks | candles | open with |
|---|---|---|---|---|
| A | Outer breakout | 24 | 467 | `--block 0 --paper` c410 |
| B | Inner breakout inside an intact parent | 13 | 64 | `--block 0` c404 |
| C | Micro development | 14 | 138 | `--block 1 --paper` c419 |
| D | Same-structure re-break | 17 | 39 | `--block 0 --paper` c513 |
| E | Retest | 24 | 1,627 | `--block 0` c410 |
| **F** | **Re-entry after a give-back** | **0** | **0** | **NOT PRESENT IN TEACH** |
| G | Generation change | 24 | 125 | `--block 0 --paper` c431 |
| H | Long → exit | 22 | 111 | `--block 0 --paper` c442 |
| I | Short → exit | 23 | 130 | `--block 0 --paper` c431 |
| J | Same-candle reverse prevention | 24 | 241 | `--block 0 --paper` c431 |
| **K** | **Large box with an internal cluster** | **2** | 600 | **`--block 4 --paper` c400** |
| **L** | **Space inside the box, internal structure breaking** | **2** | 25 | **`--block 4 --paper` c406** |
| M | No path ahead | 22 | 133 | `--block 0` c622 |
| N | Multi-scale release | 12 | 23 | `--block 0` c410 |
| O | Warm-up edge case | 4 | 4 | `--block 0` c404 |

Nothing is simulated. A fixture built to make a scenario appear would validate the fixture.

### K / L — your original observation, on screen

Teach block 4, candle 406. The chart draws, in price order:

```
R01                    the large range          (map)
 ├── C06  ⊂ R01        cluster inside it        y 348 → 413
 ├── C03  ⊂ R01        cluster inside it        y 439 → 496
 └── C10  ⊂ R01        cluster inside C03's band  y 462 → 494
```

and the panel answers:

```
WHAT BROKE?                 OUTER C03.high UP @ 44,411 · INNER C10.high UP @ 44,391
WHICH SCALE?                MULTI_SCALE (2 releases together: OUTER, INNER)
                            AT_BROKEN_EDGE · NO_PARENT
WHAT IS THE CURRENT THESIS? LONG generation 1 ACTIVE   C03/GEN1/UP
WHY PARTICIPATION?          CONSTRAINED [NEW_THESIS] TWO_SCALES_RELEASED_TOGETHER
WHY HOLD?                   no position
WHAT CHANGED?               NEW_THESIS — OUTER C03.high, INNER C10.high
WHAT INVALIDATES?           two closes back through C03's broken edge  @ 44,411  1 pt away
WHAT IS THE NEXT DEVELOPMENT?  HOLD_ABOVE_BROKEN_EDGE — path: next C06, free 24
```

An inner cluster giving way inside a parent that is itself inside a larger range, with
room still ahead — and the system **refuses to participate**, naming
`TWO_SCALES_RELEASED_TOGETHER` rather than picking a scale it cannot justify. That is the
honest answer, and it is now visible rather than argued about.

**But K/L appears in only 2 of 24 teach blocks.** The map publishes 18 nested nodes in
7,200 candles. Whatever this behaviour is, this feed rarely presents it — consistent with
the earlier finding that nested structure exists in ~10% of teach occupancy windows. It is
visually verifiable; it is not common.

### F is absent, and that is a finding

`release.location` takes only two of its three values in **teach and validate combined**:
`BEYOND_BROKEN_EDGE` 484/124, `AT_BROKEN_EDGE` 110/41, `BACK_INSIDE_BROKEN_STRUCTURE`
**0/0**. So `participation.GAVE_IT_BACK` — a named constraint in production — **never
fires**.

It is unreachable by construction on two of the three release paths: `_released()` requires
the current close strictly beyond the edge by more than `tol`, and `location` is computed
from that same close, so `beyond < -tol` is contradictory. The outer path uses the break
log's own rule, where it is empirically absent across 9,600 candles.

**Reported, not removed.** Deleting a constraint changes the participation contract, and
that is not this stage's job. It is your call.

## 7. SAFETY

| | |
|---|---|
| routes exposed | `/api/catalog`, `/api/session`, `/api/live/{open,poll,stop}` — and nothing else |
| order / broker / sizing / risk / options imports | **absent** from `tools/dashboard/`, `tools/dash.py`, `src/livemap/observatory.py` |
| order vocabulary in any dashboard file **or** the browser code | **absent** |
| holdout | picker offers teach only; loading a non-teach day raises |
| default session | `NoExecution` — every candle `FLAT`, 0 positions |
| paper session | `ResearchPositionInjector`, `validated = False`, labelled `PAPER` in the pill, the panel and the chart |
| `EXECUTION_STATUS` | `UNAVAILABLE`, shown in a permanent pill |
| the browser derives no production fact | asserted — no band comparison, no identity construction, no route arithmetic |
| `viewport.js` is domain-free | asserted — it may not contain the words thesis, release, identity, participation, position, candle or box |
| external resources | none; the page loads only `/static/` |

## 8. WHAT CHANGED IN PRODUCTION

| file | change |
|---|---|
| `src/livemap/observatory.py` | **new** — `Frame`, `Geometry`, `Why`, `events`, `trader_eye`, `scenarios`, `frames()`, `LiveSession` |
| `src/livemap/participation.py` | **+1 additive field** `next_expected`, copied from `LiveThesis`; proved inert |
| `tools/dashboard/` | **new** — `server.py`, `sessions.py`, `feed.py`, `static/{index.html,app.css,app.js,viewport.js}` |
| `tools/dash.py`, `tools/observatory.py` | **new** — the runner and the static/scenario-finder CLI |
| `tests/test_observatory.py`, `tests/test_dashboard.py` | **new** — 27 + 23 tests |

**Full suite green on the final tree: 1,315 tests** (1,231 before the boundary stage, +34 boundary, +27 observatory, +23 dashboard). The map-story gate
(`test_the_map_story_did_not_move`) is inside that run and is unmoved.

Nothing in `boxes/`, `frontier.py`, `micro.py`, `eye.py`, `postbreak.py`, `release.py`,
`route.py`, `thesis.py`, `reactor.py`, `position.py` or `boundary.py` was modified.

## 9. WHAT THIS STAGE DOES NOT CLAIM

1. **No edge is claimed.** Every position on screen was injected by a named research
   contract. This validates that the picture matches the vocabulary — nothing about
   profitability.
2. **Live market data is not connected.** The live *code path* is exercised and proved
   identical to replay; the Kite adapter is a documented stub.
3. **F was never seen**, so it is unvalidated visually — absent, not passing.
4. **K/L is verifiable but rare** — 2 of 24 blocks.
5. Verification is on teach. Validate was used only for the counters already reported.

---

**Stopped here.** No `ENTER_*`, no execution contract, no broker, no orders, no risk, no
sizing, no targets, no holdout, no new execution hunt.
