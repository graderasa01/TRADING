# REACTIVE PARTICIPATION ENGINE — decision contract and replay

> **Research layer. Nothing was enabled.** No `ENTER_*`, no order, no broker, no sizing,
> no risk, no options, no target, no trailing stop, no ATR stop, no threshold, no score,
> no probability, no confidence. `EXECUTION_STATUS` is `UNAVAILABLE` by default and no
> position is ever opened outside a labelled research contract.
> `split.holdout()` was not called; `HOLDOUT-ACCESS.md` does not exist.
>
> **No production file changed this stage.** `src/livemap/release.py` and
> `tests/test_release.py` are from the previous stage and were not touched.
>
> Prior stages: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) ·
> [`REACTIVE-TRADER.md`](REACTIVE-TRADER.md) ·
> [`PARTICIPATION-CONTEXT.md`](PARTICIPATION-CONTEXT.md)

---

## 1. THE EXACT DECISION CONTRACT

Four closed vocabularies. `__post_init__` enforces every one, and three cross-checks.

```
POSITION            FLAT · LONG · SHORT                        carried, never inferred

ACTION              NO_TRADE · WATCH
                    PARTICIPATION_CANDIDATE_LONG · PARTICIPATION_CANDIDATE_SHORT
                    HOLD_LONG · HOLD_SHORT · EXIT_LONG · EXIT_SHORT

STATUS              ACTIVE · BLOCKED · INVALIDATED · UNAVAILABLE

EXECUTION_STATUS    UNAVAILABLE · PENDING · RESOLVED · NOT_APPLICABLE
```

There is no `ENTER_*` and no `REVERSE`, asserted by
`test_there_is_no_enter_action` and `test_there_is_no_reverse_action`. A candidate while
already in a position raises; `HOLD_LONG` while short raises.

### Participation is not execution

Four axes are kept apart on every candle, because three can be true while the fourth is not:

| axis | owner | this stage |
|---|---|---|
| market development | `ReleaseContext` / `EpisodeState` | observed |
| participation context | `parteye.ParticipationContext` | assembled |
| **execution availability** | `ExecutionContract` | **still shut** |
| position action | `reactor.ParticipationDecision` | decided |

`ExecutionContract` is an injected object, not a flag, so the honest answer is the default
and a research mode must be named in the call where a reader sees it:

```
NoExecution           EXECUTION_STATUS = UNAVAILABLE, never resolves.  DEFAULT.
ImmediateExecution    research only — exercises HOLD/EXIT.  validated = False, always.
```

Measured over teach: **333 candidates, 333 with `EXECUTION_STATUS = UNAVAILABLE`, 0
positions opened.** A candidate is a statement about structure. It is never an order.

---

## 2. FIELD-SOURCE AUDIT

`ParticipationDecision` holds a **reference** to the context, not a copy of its fields —
`test_the_decision_does_not_duplicate_the_context` asserts the two share no field names.

| decision field | source |
|---|---|
| `index` / `at` / `price` | `ParticipationContext`, itself copied from `Reading` / `Candle` |
| `position` / `open_generation` | carried by the fold; updated only from the decision just taken |
| `action` / `status` | this module — the only thing it produces |
| `execution_status` | `ExecutionContract` |
| `reasons` | named constants; every one is the presence or absence of an existing fact |
| `context` | reference |
| `opportunity` | `decision.opportunity_of` + release scale + broken structure + direction |

Everything the context itself carries was audited in
[`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) §2. `test_the_context_still_copies_its_sources`
re-checks it against `thesis.narrate` and `release.observe` on every candle of a real block.

---

## 3. THE PARTICIPATION STATE MACHINE

Presence-of-facts only. Not one branch compares a number to a bound.

```
                            a release on this candle?
                                    │
                    no ─────────────┴───────────── yes
                     │                              │
             thesis alive?                  required facts present?
              │        │                     │              │
            yes       no                   no              yes
              │        │                     │              │
           WATCH   NO_TRADE           PARTICIPATION_    constraint present?
          [ACTIVE] [UNAVAILABLE]       UNAVAILABLE       │           │
                                       NO_TRADE        yes          no
                                      [UNAVAILABLE]      │           │
                                                    CONSTRAINED   AVAILABLE
                                                     NO_TRADE     CANDIDATE
                                                     [BLOCKED]     [ACTIVE]
```

**Missing facts** (→ `UNAVAILABLE`): no release · no thesis · idea unresolved · no
current-generation invalidation · no mapped path beyond the broken boundary.

**Named constraints** (→ `BLOCKED`): counter-thesis direction · unresolved contradiction ·
price back inside the structure that broke · two scales released together · continuation of
a live generation · opportunity already taken · position already open in this generation.

*"The next opposing reference is very close"* is deliberately **not** a constraint. It is
reported as `free_to_near` and gates nothing, because gating it would need a threshold and
no threshold has been earned. `test_a_tiny_path_is_reported_and_never_gated` asserts that
the thinnest quartile of paths still reaches `AVAILABLE`.

---

## 4. THE POSITION-AWARE STATE MACHINE

```
        FLAT ──── candidate + execution resolved ────▶ LONG / SHORT
          ▲                                               │
          │                                               │ generation changed
          │                                               │ idea reversed
          └────────────── EXIT_LONG / EXIT_SHORT ─────────┘ thesis unresolved
                          [INVALIDATED]
```

Four rules, each asserted:

1. **Entry is never considered while in a position** — the first branch of `decide` is the
   position, and a candidate with a non-flat position raises.
2. **An exit candle never also opens** — the transition is applied *after* the decision.
3. **No automatic reversal** — `LONG → SHORT` in one step is impossible; measured over
   teach in the research contract: **0 direct reversals in 2,240 position transitions.**
4. **The invalidation belongs to the current generation** — `exit_check` reads the
   generation first, and `test_a_held_position_always_matches_the_current_generation`
   fails if a position ever survives into a generation that did not open it.

Same-generation continuation is **management information**, never a second entry:
`test_a_same_generation_continuation_never_re_enters`.

---

## 5. THE HUMAN TRADER RENDER

The order is fixed and asserted by `test_the_render_order_is_the_one_the_brief_fixes`:

```
WHAT HAPPENED → WHERE PRICE IS → WHAT THESIS → WHAT PATH → WHAT INVALIDATES
              → WHETHER PARTICIPATION IS POSSIBLE → WHETHER EXECUTION IS AVAILABLE
```

A real candle, unedited:

```
PRICE             45,016.8   2023-08-08 12:15   BANK NIFTY
POSITION          FLAT
THESIS            LONG   generation 1   ACTIVE
NEW DEVELOPMENT   OUTER C05 HIGH RELEASED UP
RELEASE           C05.high   scale = OUTER   broken edge = 44,966   parent = —   [LOG]
RELEASE           C09.high   scale = INNER   broken edge = 44,917   parent = C05   [INNER_SCAN]
                  2 releases on this candle, all kept; controlling scale is MULTI_SCALE
                  — two different scales released together and neither was selected as 'best'
LOCATION          NO_STRUCTURE
                  BEYOND_BROKEN_EDGE   51 pts beyond the broken edge
                  NO_PARENT
MICRO             absent
CURRENT STATE     RETESTING
PATH              next reference = C08   free 5 | depth 106 | far 111
                  far reference = 45,077   INSIDE_NEXT_ZONE   (structure that exists ahead,
                  never a promise)
                  corridor 44,970 C08 near → 45,031 C04 near → 45,076 C04 far
MOVE              0 candles since the generation   55 pts already travelled (1.12 ATR)
INVALIDATION      two closes back through C05's broken edge - the up break is given back
                  44,966   51 pts away
CONTRADICTION     none
OPPORTUNITY       NEW_THESIS
PARTICIPATION     PARTICIPATION_CONSTRAINED   [TWO_SCALES_RELEASED_TOGETHER]
ACTION            NO_TRADE   [BLOCKED]
                  STRUCTURALLY_CONSTRAINED, TWO_SCALES_RELEASED_TOGETHER
EXECUTION         NOT_APPLICABLE
```

And §23's machine-readable trader narrative, generated from those fields alone:

> *"The outer structure C05 released upward through 44,966. An inner cluster C09 released
> upward through 44,917. The long generation 1 is active and the market is retesting. There
> is a mapped path ahead. No contradiction. This is a new structural opportunity. No trade.
> Blocked by: two scales released together."*

`test_the_narrative_never_predicts` forbids *will*, *expect*, *likely*, *target*,
*confidence*. `test_no_invented_stop_appears_anywhere` forbids the whole stop/target
vocabulary from the render — including inside a disclaimer, because an absolute guard is
worth more than a nuanced one.

---

## 6. DECISION CENSUS

| | teach (7,200 candles) | validate (2,400 candles) |
|---|---|---|
| `WATCH` | 5,302 · 73.6% | 1,693 · 70.5% |
| `NO_TRADE` | 1,565 · 21.7% | 568 · 23.7% |
| `PARTICIPATION_CANDIDATE_LONG` | 151 · 2.1% | 73 · 3.0% |
| `PARTICIPATION_CANDIDATE_SHORT` | 182 · 2.5% | 66 · 2.8% |
| **candidates** | **333 · 4.6%** | **139 · 5.8%** |

| STATUS | teach | validate |
|---|---|---|
| `ACTIVE` | 5,635 · 78.3% | 1,832 · 76.3% |
| `UNAVAILABLE` | 1,482 · 20.6% | 564 · 23.5% |
| `BLOCKED` | 83 · 1.2% | 4 · 0.2% |

`EXECUTION_STATUS`: `NOT_APPLICABLE` 6,867, `UNAVAILABLE` 333 — exactly the candidates.

### Why `NO_TRADE` (teach; a candle may name more than one fact)

| named fact | n |
|---|---|
| `NO_CURRENT_GENERATION_INVALIDATION` | 1,353 |
| `NO_RELEASE_ON_THIS_CANDLE` | 1,344 |
| `IDEA_UNRESOLVED` | 1,008 |
| `NO_THESIS` | 345 |
| `NO_MAPPED_PATH_BEYOND_THE_BROKEN_BOUNDARY` | 133 |
| `CONTINUATION_OF_A_LIVE_GENERATION` | 41 |
| `RELEASE_IS_COUNTER_TO_THE_CURRENT_IDEA` | 28 |
| `OPPORTUNITY_ALREADY_TAKEN` | 19 |
| `TWO_SCALES_RELEASED_TOGETHER` | 17 |
| `UNRESOLVED_CONTRADICTION` | 5 |

Every one is a fact that does not exist or a constraint that does. Not one is a number that
was not exceeded.

---

## 7. REAL BANK NIFTY TRACES

Eleven traces in `reactorreplay.out`, each in the order §26 fixes — **WHAT THE SYSTEM
KNEW** (the preceding candles' decision lines), **DECISION CONTEXT**, **WHAT THE SYSTEM
WOULD HAVE SAID**, then **AFTER**. The outcome is printed last, every time, and no outcome
took part in choosing any trace.

| # | shape | what the engine said |
|---|---|---|
| 1 | outer release, clean path | `PARTICIPATION_CANDIDATE_LONG` [ACTIVE], execution `UNAVAILABLE` |
| 2 | outer release, immediate obstacle | `PARTICIPATION_CANDIDATE_SHORT` [ACTIVE] |
| 3 | inner release, parent intact | `PARTICIPATION_CANDIDATE_LONG` — *"still inside C07"* |
| 4 | inner release, poor path | `PARTICIPATION_CANDIDATE_SHORT` — the thin path is reported, not gated |
| 5 | micro release | `NO_TRADE` [BLOCKED] — continuation + counter-thesis |
| 6 | simultaneous outer + inner | `NO_TRADE` [BLOCKED] — `TWO_SCALES_RELEASED_TOGETHER` |
| 7 | re-entry | no release emitted at all; the post-break layer calls it `REENTERING` |
| 8 | same-generation continuation | `NO_TRADE` [BLOCKED] — management information |
| 9 | generation reversal | the new generation's own candidate, never a reversal |
| 10 | already-extended thesis | facts exposed — age, excursion, invalidation distance — and no cutoff |
| 11 | fresh thesis, clean path | `PARTICIPATION_CANDIDATE` |

**Trace 3 is the §10 requirement working.** An inner cluster released upward, the parent had
not broken, price was beyond the inner edge and still inside the parent, the path ran through
the parent, and the engine produced a candidate — without waiting for the outer box.

**Trace 3 also caught a real bug.** The render called two *same-scale* releases
`MULTI_SCALE`. Two inner boundaries giving way together is simultaneity, not multi-scale;
the controlling scale is still `INNER_CONTROLLING`. Fixed, and the render now prints the
actual controlling scale.

**A subtlety worth naming.** In trace 3 the releases are `C01`/`C05` while the invalidation
reads *"two closes back through **C02**'s broken edge"*. That is correct: the invalidation
belongs to the **thesis**, not to the release that happened inside it. A layer that attached
the invalidation to the release would have produced a stop for an idea nobody holds.

---

## 8. TESTS

| suite | n | scope |
|---|---|---|
| `tests/test_release.py` | 38 | release identity, simultaneity, re-entry, route origin, causality, leakage *(previous stage, still green)* |
| `test_parteye.py` | 28 | context assembly, outcome vocabulary, no-threshold, opportunity kinds, position |
| `test_reactor.py` | **45** | the decision contract, execution separation, position machine, causality, determinism, dedup |
| repo suite | **803** | unchanged and green |

`test_reactor.py` is organised around §32's hard-stop conditions, because those are what
the tests exist to catch:

```
§32.1  a decision requires a fact unavailable at that candle   test_a_candidate_never_rests_on_a_missing_fact
§32.2  a future candle changes an earlier decision              test_no_future_candle_changes_an_earlier_decision
§32.3  a repeated release creates duplicate participation       test_a_repeated_release_does_not_create_a_second_candidate
§32.4  same-generation continuation causes re-entry             test_a_same_generation_continuation_never_re_enters
§32.5  opposite generation causes automatic reversal            test_no_automatic_reversal
§32.6  old-generation invalidation applied to a new generation  test_a_held_position_always_matches_the_current_generation
§32.8  an arbitrary threshold is introduced                     test_a_tiny_path_is_reported_and_never_gated
```

**Two bugs the tests caught this stage**, both real:

1. the render dropped the structure id on additional releases, so a multi-scale candle did
   not name both — `test_a_multi_scale_candle_keeps_every_release`;
2. `decide` and the observer fold applied the position transition in different orders, which
   would have dated every entry one candle apart —
   `test_the_engine_and_the_observer_see_the_same_contexts`.

---

## 9. PREFIX CAUSALITY

```
cut points checked 18   mismatches 0
```

`replay(upto=k)` is prefix-equal to a full run truncated at `k`, for the action, the status,
the position, the execution status and the whole context behind them. Checked at 20%, 50%
and 90% of six real blocks, under both execution contracts. **PASS.**

## 10. DETERMINISM

```
blocks re-run 6   identical 6
```

The same stream twice produces the same decisions, object for object. **PASS.**

## 11. DEDUPLICATION

```
releases observed         594
participation candidates  333
duplicate candidates        0
```

| opportunity kind | teach |
|---|---|
| `NEW_THESIS` | 467 |
| `SAME_GENERATION_CONTINUATION_RELEASE` | 42 |
| `NEW_GENERATION_RELEASE` | 22 |
| `SAME_GENERATION_REPEAT` | 19 |

The identity is generation + structural event + scale, all three already causal. A
continuation or a repeat is never entry-shaped, so it cannot become a second candidate.
**PASS.**

---

## 12. PERFORMANCE

Six blocks, 1,800 candles, 5m Bank Nifty. Microseconds per candle.

| stage | median | p95 | max | candles/sec |
|---|---|---|---|---|
| observation (snapshot + frontier) | 2,062.1 | 2,203.8 | 2,203.8 | 488 |
| release context | 22.2 | 104.8 | 353.6 | 30,854 |
| participation context | 15.3 | 26.4 | 194.1 | 58,819 |
| decision | 3.3 | 4.8 | 22.8 | 284,113 |
| **participation + decision** | **18.6** | **31.0** | **207.1** | **48,731** |

By state:

| stage / state | n | median | p95 | max |
|---|---|---|---|---|
| participation context / flat | 1,783 | 15.3 | 25.7 | 194.1 |
| participation context / position active | 454 | 15.9 | 27.0 | 97.3 |
| participation context / multi-scale | 17 | 27.2 | 53.8 | 53.8 |
| decision / flat | 1,783 | 3.3 | 4.7 | 22.8 |
| decision / position active | 454 | 3.7 | 5.6 | 30.4 |
| decision / multi-scale | 17 | 4.3 | 5.7 | 5.7 |

Two honesty notes, both in the output itself:

* `observation` includes the one-off 400-candle snapshot build amortised over the block's
  readings, so it **overstates** the steady-state per-candle cost. The three rows this build
  added are the ones below it.
* `position active` cannot exist under the default contract — no position is ever opened —
  so that row is measured under the research contract. It is the only way the number exists.

The whole of this stage costs **18.6 µs per candle at the median**, against a 5-minute
candle. Multi-scale is the slowest path at 27.2 µs, which is the correct shape: it is the
candle carrying more than one release.

---

## 13. PRODUCTION VS SCRATCHPAD

| production (`src/`, `tests/`) | added by | status |
|---|---|---|
| `src/livemap/release.py` | previous stage | unchanged this stage |
| `tests/test_release.py` | previous stage | unchanged this stage |
| **everything else in `src/`** | — | **untouched** |

| scratchpad (research) | role |
|---|---|
| `thesis.py`, `decision.py` | LIVE THESIS, generations, the decision primitives *(pre-existing)* |
| `parteye.py` | `ParticipationContext`, `sources()`, `Book` — the shared fold |
| `reactor.py` | **this stage** — `ParticipationDecision`, the two state machines, render, narrative |
| `test_parteye.py`, `test_reactor.py` | 73 tests |
| `reactorreplay.py`, `fwd.py` | the replay, traces and reports |

The quarantine is intact: `src/setups/`, `risk/`, `exits/`, `modes/`, `broker/`, `guards/`,
`options/` import neither `livemap` nor anything in the scratchpad, and
`tests/test_livemap_quarantine.py` asserts it in both directions. Nothing in the decision
path can reach a broker, because the decision path is not in `src/` at all.

---

## 14. FACTS THIS LAYER STILL DOES NOT HAVE

Measured, and named on the candles where they were missing (teach):

| | n |
|---|---|
| `NO_THESIS` | 1,698 |
| `NO_CURRENT_GENERATION_INVALIDATION` | 1,353 |
| `NO_RELEASE_ON_THIS_CANDLE` | 1,344 |
| `IDEA_UNRESOLVED` | 1,008 |
| `NO_MAPPED_PATH_BEYOND_THE_BROKEN_BOUNDARY` | 133 |

Structural gaps, none filled by a substitute measurement:

| gap | state |
|---|---|
| validated execution timing | no rule survived teach → validate in six studies |
| micro population | too small at every horizon measured so far — 18 releases in teach |
| inner-scale availability | varies by an order of magnitude between periods; a map property |
| multi-scale resolution | no causal rule exists for which scale matters; `MULTI_SCALE` is reported |
| session state | `trades_taken`, `consecutive_losses`, `cumulative_r` — only a fill writes them |
| htf close proximity | owned by `guards/`, which the quarantine puts out of reach |
| cost, sizing, risk, options | deliberately out of scope for this stage |

---

## 15. WHAT THIS LAYER DOES NOT CLAIM

Stated plainly, because the previous study measured most of them:

1. **A candidate is not profitable.** `PARTICIPATION_AVAILABLE` did **not** predict outcome
   — 46.9% `MFE>MAE` against 50.0% for `CONSTRAINED`. The label is a completeness
   statement, not a quality score.
2. **`CONSTRAINED` is not "bad".** It names a structural constraint, not a worse trade.
3. **No scale is claimed better.** `OUTER` was mechanical/selection-driven; `INNER` and
   `MICRO` remain unmeasurable, not disproven.
4. **A long path is not claimed better.** The `PATH_HIGH` stratum's matched cell had a 95%
   CI of `[−2.7, +44.4]` — it crosses zero.
5. **Execution timing is not solved,** and `EXECUTION_STATUS` says so on every candidate.
6. **The research contract's numbers mean nothing about performance.** `ImmediateExecution`
   assumes away the unsolved problem; `validated` is `False` and stays `False`.
7. **The inner-boundary scan is not validated.** It applies the repo's own two-close rule to
   boundaries the map already published, and that judgement is documented in three places
   rather than hidden.
8. **This is not a strategy.** It is a market eye and a decision contract.

---

## 16. HARD-STOP CONDITIONS (§32)

None were hit.

| # | condition | result |
|---|---|---|
| 1 | a decision needs a fact unavailable at that candle | no — every such candle answers `UNAVAILABLE` and names the fact |
| 2 | a future candle changes an earlier decision | no — 18 cut points, 0 mismatches |
| 3 | a repeated release creates duplicate participation | no — 0 duplicates over 594 releases |
| 4 | same-generation continuation causes automatic re-entry | no — never entry-shaped |
| 5 | opposite generation causes automatic reversal | no — 0 direct reversals |
| 6 | old-generation invalidation applied to a new generation | no — asserted per candle |
| 7 | a new detector became necessary | no |
| 8 | an arbitrary threshold was introduced | no — asserted by the thin-path test |
| 9 | map / frontier / micro / release semantics altered | no — no production file changed |
| 10 | holdout became necessary | no |
| 11 | production order flow became necessary | no |

---

## 17. WHAT HAPPENS NEXT (§31)

`ENTER_*` was **not** activated, and this build is not a reason to activate it. The next
question is a separate one, and it is a measurement, not a feature:

> Does `PARTICIPATION_CANDIDATE` have enough causal stability to justify an execution study?

The engine now produces that dataset — 333 teach and 139 validate candidates, each with a
complete inspectable context, a causal identity and a current-generation invalidation. The
honest prior going in is the one the last study established: the context label does not
predict outcome, and the one well-posed candidate signal (`OUTER × PATH_HIGH`) needs roughly
an order of magnitude more matched pairs before its interval clears zero.

**Stopped here, as instructed.** No broker, no sizing, no options execution, no holdout,
no `ENTER_*`.
