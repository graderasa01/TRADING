# TRADE THESIS SNAPSHOT + POSITION LIFECYCLE

> **Position lifecycle ready. Execution remains `UNAVAILABLE`.**
>
> No `ENTER_*` · no broker · no order · no sizing · no risk · no options · no target ·
> no trailing stop · no time stop · `split.holdout()` not called.
>
> Prior stages: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) ·
> [`REACTIVE-TRADER.md`](REACTIVE-TRADER.md) ·
> [`REACTIVE-PARTICIPATION-ENGINE.md`](REACTIVE-PARTICIPATION-ENGINE.md) ·
> [`REACTIVE-PARTICIPATION-PROMOTION.md`](REACTIVE-PARTICIPATION-PROMOTION.md)

---

## 1. THE AUDIT, FIRST (§4)

Before writing anything I mapped what already exists, because §4's real question is whether
a second vocabulary is about to be invented.

| concept | canonical owner | verdict |
|---|---|---|
| position state | `participation.FLAT/LONG/SHORT`, `POSITIONS` | **reuse** — the only position-state vocabulary in `src/` |
| trade *side* | `decide.LONG="long"` / `SHORT="short"`, `SIDES` | **a different concept** — which side a *hypothesis* is on, lowercase, on the older setup-labelled contract. Not a position. |
| generation | `thesis.LiveThesis.generation`, `generations()` | reuse |
| invalidation | `thesis.invalidation` + `invalidation_price`, applied by `reactor.exit_check` | reuse |
| opportunity identity | `participation.opportunity_of()` | reuse (§22) |
| participation action | `reactor.ACTIONS` — already carries `HOLD_*` / `EXIT_*` | reuse |
| exit reasons | `reactor.R_GENERATION_CHANGED` / `R_IDEA_REVERSED` / `R_THESIS_UNRESOLVED` | reuse (§19 — no redundant reasons) |
| position **lifecycle** | `frontier.LIVE_STATES`, `micro.MICRO_STATES`, `SessionState` | **none is one** — the genuine gap |

`reactor.replay` already carried a position and emitted `HOLD`/`EXIT`. What was missing was
memory: nothing recorded *why* a position existed, nothing compared the entry thesis against
the current market, and there was no timeline. No second position vocabulary was needed and
none was created.

## 2. WHAT WAS BUILT

| file | lines | role |
|---|---|---|
| `src/livemap/position.py` | **new, 555** | `TradeThesisSnapshot`, `PositionEvaluation`, `PositionState`, `PositionRecord`, `ResearchPositionInjector`, `lifecycle()`, `render()` |
| `tests/test_position.py` | **new, 45 tests** | snapshot, lifecycle, generation, continuation, same-candle, separation, causality, determinism, safety |
| `src/livemap/participation.py` | **+1 field** | `ParticipationContext.thesis_id` — see §3 |

Everything else in `src/` is untouched. There is still exactly **one** position fold —
`reactor.replay` — and the lifecycle reads it rather than running a second one
(`test_the_lifecycle_agrees_with_the_decision_stream`).

## 3. §29 — A MISSING FACT, STOPPED ON AND REPORTED

Building the thesis-vs-current comparison surfaced a defect worth naming.

**`generation` is an integer, and the integer does not identify a thesis.** Two consecutive
episodes are *both* generation 1. On block 0 candle 442 a long opened on `L01` was compared
against a market whose thesis was now `C08` — and the delta reported *"same generation"*
across a complete thesis change. The exit itself was correct (`exit_check` caught it on the
direction, `IDEA_REVERSED`), but the comparison a trader reads was wrong.

The identity already existed as `opportunity_of(thesis)`; it simply was not exposed on
candles without a release, which is most of them. So one additive field:

```python
ParticipationContext.thesis_id   # = opportunity_of(thesis)
```

That is an existing pure function's output surfaced per candle — not a new observer, not a
new measurement, and no behaviour changed.

**Then the first fix over-corrected, and the data said so.** Comparing the full triple
`(structure, break candle, generation)` reported a thesis change on **35 of 70** held
candles in one block. Every one of them was the same structure `L02` re-breaking: same
direction, same generation, **invalidation still at 44,651**. The break candle is
opportunity bookkeeping, not thesis identity. So the comparison is:

```python
thesis_key(thesis_id) == (broken structure, generation)
```

which took the same block from 35 spurious changes to 5 real ones, and correctly flags
`L01`→`C08` and `C08` gen 1→2 as genuine.

**A residual, reported rather than fixed.** `reactor.exit_check` keys on the generation
*integer* and the direction, so a different structure breaking the same way at the same
generation number holds the position. Measured over teach:

| | n | with a changed thesis |
|---|---|---|
| exit candles | 236 | 177 · 75% |
| held candles | 1,890 | **261 · 13.8%** |

So roughly one held candle in seven is running under a thesis it was not opened on. The
evaluation now always says so — `test_a_thesis_change_under_a_held_position_is_always_reported`
forces those candles to `CONTINUATION` rather than a quiet `HOLD`. **I did not change
`exit_check`**: it is the validated contract and §19 says to preserve its causality. This
is a finding for the next stage, not a change smuggled into this one.

## 4. THE SNAPSHOT CONTRACT (§5, §6)

Frozen at the open, never updated, holding only frozen objects.

```
opportunity_id · side · opened_at · opened_index · opened_price
thesis_id · generation · idea · thesis_status · current_state_at_open · broken_structure_id
releases (references) · release
invalidation_reference · invalidation_rule · invalidation_direction
next_reference_at_open · far_reference_at_open
free_to_near_at_open · zone_depth_at_open · free_to_far_at_open · corridor_at_open
```

**Releases are referenced, not copied** (§5). A `Release` already carries the boundary, the
parent, both locations, the route and the corridor; re-copying it would create a second
version of the same fact, free to drift from the first. `release_scale`, `broken_edge`,
`parent_structure_id`, `release_location` and `parent_location` are properties that read
through to it.

`invalidation_direction` is `TWO_CLOSES_BELOW` for a long and `TWO_CLOSES_ABOVE` for a
short — a label over the rule the thesis already carries, not a new rule.

**Immutability is proved on real data**, not asserted: the test walks the rest of the block,
requires that the market actually developed afterwards, and compares the snapshot to an
independent copy taken at the open.

## 5. THE LIFECYCLE STATE MACHINE (§8)

```
        FLAT ──── research position injected ────▶ OPEN
                                                    │
                            ┌───────────────────────┤
                            ▼                       ▼
                          HOLD ◀────────────▶ CONTINUATION
                            │                       │
                            └──────────┬────────────┘
                                       ▼
                                  INVALIDATED  ──▶ FLAT
                                (record: EXITED)
```

One phase per candle; `EXITED` is the record's terminal, not a phase. Exit reasons are
`reactor.exit_check`'s own three, reused verbatim.

## 6. THESIS vs CURRENT MARKET (§7, §16)

`PositionEvaluation` compares without modifying either, and every field is a relationship
between existing facts:

```
thesis_generation_same · direction_same · generation_changed
new_release_same_generation · new_release_new_generation
entry_thesis_invalidated · contradiction_present · path_changed · path_unobserved
```

`path_unobserved` exists because the release-relative route is measured from a boundary
that broke, so it exists **only** on a candle that carried a release. Calling its absence a
change made almost every candle a `CONTINUATION` and hid the developments that were real —
caught by reading the first trace, fixed, and pinned by
`test_an_absent_route_is_not_reported_as_a_changed_one`.

## 7. THE TRADER RENDER — a real trace, unedited

```
ENTRY THESIS      LONG   generation 1   opened c437 2023-08-08 14:30 at 45,020.3
                  release OUTER L01.high at 44,991   parent —   [LOG]
                  state at open RETESTING   release location BEYOND_BROKEN_EDGE   NO_PARENT
                  path at open: next C04   free 40 | depth 45 | far 85
                  invalidation 44,991   TWO_CLOSES_BELOW
                  two closes back through L01's broken edge - the up break is given back

CURRENT MARKET, EACH CANDLE
cand      price POS   PHASE         ACTION                        EXIT REASON      AFTER
c437   45,020.3 FLAT  OPEN          PARTICIPATION_CANDIDATE_LONG                   LONG
c438   45,013.8 LONG  HOLD          HOLD_LONG                                      LONG
c439   45,016.8 LONG  CONTINUATION  HOLD_LONG                                      LONG
c440   44,996.5 LONG  HOLD          HOLD_LONG                                      LONG
c441   44,929.5 LONG  HOLD          HOLD_LONG                                      LONG
c442   44,949.0 LONG  INVALIDATED   EXIT_LONG                     IDEA_REVERSED    FLAT

  c439  14:40   CONTINUATION
    CURRENT MARKET    generation 1 of L01   LONG   RETESTING
                      new release INNER C04.low at 45,031
                      micro absent   location INSIDE   path next L01 free 40
    THESIS DELTA      new same-generation release, path changed
                      entry thesis invalidated: no
    POSITION ACTION   HOLD_LONG
    POSITION AFTER    LONG

  c442  14:55   INVALIDATED
    CURRENT MARKET    generation 1 of C08   SHORT   RETESTING
    THESIS DELTA      thesis changed, direction changed, path changed
                      entry thesis invalidated: YES
    POSITION ACTION   EXIT_LONG   IDEA_REVERSED
    POSITION AFTER    FLAT
```

This is §12's case working: an **inner** release arrived inside the live generation at c439,
the position **held**, and the entry thesis block still reads `path at open: next C04 free
40` while the market has moved on. The trader can see why the position exists and what the
market is doing now, separately.

## 8. REAL-DATA CENSUS (teach, 7,200 candles, 244 research positions)

| phase | n | share |
|---|---|---|
| `FLAT` | 4,830 | 67.1% |
| `HOLD` | 1,546 | 21.5% |
| `CONTINUATION` | 344 | 4.8% |
| `OPEN` | 244 | 3.4% |
| `INVALIDATED` | 236 | 3.3% |

Exit reasons: `GENERATION_CHANGED` 141, `IDEA_REVERSED` 95. **No other reason exists** — no
stop, no target, no timer.

Developments while positioned: thesis changed 438 · direction changed 232 · path changed 73
· new same-generation release 72 · release under a new generation 68 · contradiction 18.

Bars held: median **6**, min 1, max 100, 8 still open at a block end.
Entry scale `OUTER` 236 / `INNER` 5 / `MICRO` 3; side SHORT 130 / LONG 114.

## 9. TRACES A–G (§26)

All render in `poslife.out`, each as **entry thesis → current market each candle → thesis
delta → action → position after**.

| | shape | outcome |
|---|---|---|
| A | LONG, same-generation continuation | held through the development |
| B | LONG, inner release + development, still holding | quoted in §7 |
| C | LONG, generation reversal | `EXIT_LONG` / `GENERATION_CHANGED` |
| D | SHORT, generation reversal | `EXIT_SHORT` / `GENERATION_CHANGED` |
| E | same-candle generation change | **236 exits checked; every one left the position `FLAT` on its own candle and none opened an opposite position on that candle** |
| F | position surviving several developments | held |
| G | position reaching its structural invalidation | `IDEA_REVERSED` |

## 10. PERFORMANCE (§27)

Six blocks, 1,800 candles. Microseconds.

| stage | median | p95 | max | n |
|---|---|---|---|---|
| snapshot creation | 17.90 | 51.50 | 63.00 | 55 |
| position evaluation | 14.90 | 21.80 | 164.10 | 513 |
| lifecycle transition | 0.80 | 1.30 | 9.80 | 1,800 |
| render | 13.70 | 23.00 | 118.70 | 513 |

| stage / state | median | p95 | max | n |
|---|---|---|---|---|
| evaluation / flat | 15.40 | 37.20 | 38.00 | 55 |
| evaluation / position active | 14.80 | 20.40 | 164.10 | 402 |
| evaluation / generation change | 15.60 | 20.30 | 42.20 | 54 |
| evaluation / multi-scale | 16.30 | 16.90 | 16.90 | 2 |
| evaluation / continuation-heavy | 15.50 | 26.40 | 42.20 | 162 |
| transition / flat | 1.20 | 2.00 | 20.30 | 1,329 |
| transition / position active | 1.50 | 2.00 | 17.30 | 402 |
| transition / generation change | 1.50 | 2.40 | 2.70 | 54 |
| transition / multi-scale | 1.30 | 2.10 | 2.10 | 15 |

The whole lifecycle costs about **15 µs on a candle carrying a position** and under 2 µs
otherwise, against a five-minute candle.

## 11. SAFETY GUARANTEES

| guarantee | how |
|---|---|
| production cannot fabricate a position | default `NoExecution`; measured over all teach blocks: **0 positions opened**, every candle `FLAT` |
| research injection is explicit and isolated | `ResearchPositionInjector` **must** be handed specific opportunity ids and **raises if constructed empty** — there is no "open everything" mode, and it is the default nowhere |
| no order path | static import audit: no `broker`, `risk`, `sizing`, `options`, `guards`, `orders`, `exits`, `modes`, `setups` |
| no order-shaped field | field audit across all three dataclasses |
| no invented stop | exit reasons are exactly the three structural ones; render forbids `target`/`trailing`/`atr stop`/`size` |
| snapshot immutable | frozen dataclass, frozen members, proved against a real replay |
| no same-candle exit-and-open | asserted, both directions; 236 exits checked in the traces |
| one opportunity, one open | asserted |
| no auto-reversal | a new generation never opens; the next candle is `FLAT` |
| observation untouched | before/after deep comparison of readings, logs, history, snapshot, releases, thesis |
| map-story gate | green |
| full suite | green |

## 12. WHAT THIS STAGE DOES NOT CLAIM

1. **Execution is not validated.** `EXECUTION_STATUS` stays `UNAVAILABLE`. Every position in
   every number above exists because the harness injected it.
2. **The 244 research positions are not a backtest.** No cost, no sizing, no slippage, and
   no claim about profitability — the execution study found no rule that earned a contract.
3. **`bars held: median 6` is not a holding-period recommendation.** It is what the
   structural invalidation happened to produce on injected positions.
4. **The lifecycle does not improve entries.** It is memory, not edge.

## 13. STILL UNAVAILABLE

* a validated execution rule — six studies, none survived;
* thesis identity inside `exit_check` — it keys on the generation integer, so 13.8% of held
  candles run under a thesis they were not opened on (§3). Visible now, not yet acted on;
* micro-scale anything — 3 injected positions in teach;
* inner-scale stability across periods — 5 injected positions in teach;
* session state, cost, sizing, risk, options — out of scope by design.

---

**`POSITION LIFECYCLE READY`.** Not `EXECUTION VALIDATED`.

Stopped here: no `ENTER_*`, no broker, no order execution, no sizing, no risk, no targets,
no trailing stops, no holdout, no new setup.
