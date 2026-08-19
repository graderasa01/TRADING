# PROMOTION + REACTIVE EXECUTION STUDY v2

> **Part I — promoted.** The validated reactive participation engine now lives in
> `src/livemap/`. One implementation; the scratchpad re-exports it.
> **Part II — measured.** No execution event earned the right to an execution contract.
>
> `EXECUTION_STATUS = UNAVAILABLE` · no `ENTER_*` · no broker · no order · no sizing ·
> no risk · no threshold · no score · `split.holdout()` not called.
>
> Prior stages: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) ·
> [`REACTIVE-TRADER.md`](REACTIVE-TRADER.md) ·
> [`REACTIVE-PARTICIPATION-ENGINE.md`](REACTIVE-PARTICIPATION-ENGINE.md)

---

# PART I — PROMOTION

## 1. WHAT MOVED

| production module | lines | what it owns |
|---|---|---|
| `src/livemap/thesis.py` | 674 | `LiveThesis`, generations, contradiction, invalidation wording |
| `src/livemap/participation.py` | 591 | `ParticipationContext`, `sources()`, `Book`, `eye()`, `opportunity_of` |
| `src/livemap/reactor.py` | 523 | `ParticipationDecision`, `exit_check`, `ExecutionContract`, `decide`, `replay`, `render`, `narrative` |

| production tests | functions | covers |
|---|---|---|
| `tests/test_participation.py` | 25 | context assembly, outcome vocabulary, no-threshold, opportunity kinds |
| `tests/test_reactor.py` | 45 | the decision contract, execution separation, position machine, causality |
| `tests/test_participation_safety.py` | 11 (17 cases) | the §14 hard guarantees |
| `tests/test_release.py` | 38 | release identity *(previous stage, unchanged)* |

**No redesign.** The contract, both state machines, the render order and the narrative are
byte-for-byte the validated ones. The promotion changed imports and nothing else, which is
why the ported tests pass unmodified.

### One implementation, verified

```python
>>> import parteye as PE, reactor as RE          # the scratchpad names
>>> PE.ParticipationContext is src.livemap.participation.ParticipationContext
True
>>> RE.ParticipationDecision is src.livemap.reactor.ParticipationDecision
True
>>> RE.decide is src.livemap.reactor.decide
True
```

The scratchpad modules are now re-export shims carrying a `SUPERSEDED` banner and a
`do not add code here` instruction. There is one implementation, so the research and live
paths cannot diverge.

### Promotion fidelity, checked rather than assumed

`thesis.py` was promoted by a text transform, so I loaded the original scratchpad copy
side-by-side with the production one and compared their output candle by candle:

```
candles 300   fields compared 24   identical 300/300
```

Twenty-four fields including `idea`, `generation`, `thesis_status`, `invalidation`,
`invalidation_price`, `price_location`, the route triple, `corridor`, `supporting`,
`conflicting` and `observations`. The promoted module is behaviourally identical to the
one that was validated.

The engine as a whole was checked the same way: the production replay reproduces the
pre-promotion action counts exactly (teach `NO_TRADE` 76 / `WATCH` 209 / candidates 15 on
the smoke block; 5,302 / 1,565 / 333 over full teach), under both execution contracts.

### Three deliberate choices

1. **`decide.py` was not made the owner.** It is a different, older contract — bias →
   setup → gate chain, with `SETUP_A/B/C` labels and its own 30-odd tests. Rewriting it
   into this contract would have been the redesign §1 forbids. The new engine is a separate
   module, and neither imports the other.
2. **`decision.py`'s `ENTER_*` vocabulary was left behind.** The research module carries
   `ENTER_LONG` / `ENTER_SHORT` and a synthetic path that emits them. §2 forbids that in
   production, so only the primitives came across: `exit_check` and `opportunity_of` are
   promoted with their reasoning, the order vocabulary is not.
   `test_the_engine_carries_no_order_vocabulary` asserts it against the source.
3. **`eye()` lost its `synthetic` mode.** The observer view now carries no position, and
   the position-aware fold exists only in `reactor.replay`. Two folds applying the
   transition in different orders is precisely how a research path and a live path start
   disagreeing about the same day — a bug the previous stage's tests had already caught
   once.

## 2. THE CONTRACT, UNCHANGED

```
POSITION            FLAT · LONG · SHORT
ACTION              NO_TRADE · WATCH · PARTICIPATION_CANDIDATE_LONG/SHORT
                    HOLD_LONG/SHORT · EXIT_LONG/SHORT
STATUS              ACTIVE · BLOCKED · INVALIDATED · UNAVAILABLE
EXECUTION_STATUS    UNAVAILABLE · PENDING · RESOLVED · NOT_APPLICABLE
```

No `ENTER_*`, no `REVERSE`, no `BUY`, no `SELL`, no `ORDER` — asserted statically. The
default `ExecutionContract` is `NoExecution`, whose `validated` attribute is `False` and
whose `resolves()` returns `False` unconditionally.

## 3. GATES

| gate | result |
|---|---|
| map-story gate (`test_the_map_story_did_not_move`) | **green** — structure formation, break timing, node and micro geometry, release semantics and thesis history all unmoved |
| full repository suite | **green — 1,178 tests**, run twice to completion after promotion |
| quarantine (`test_livemap_quarantine.py`) | **green** — it globs `src/livemap/`, so the three new modules are covered the moment they exist |
| lint over the engine and its tests | **clean** (three pre-existing repo-wide findings in `adaptive.py`, `multi.py` and `test_adaptive_map.py` are untouched by this promotion) |

## 4. HARD SAFETY GUARANTEES (§14)

| guarantee | how it is held |
|---|---|
| candidate cannot reach a broker | static import audit: no engine module imports `broker`, `risk`, `sizing`, `options`, `setups`, `exits`, `modes`, `guards`, `journal` |
| candidate cannot become an order | source audit for `ENTER_*`, `place_order`, `modify_order`, `cancel_order`, `lot_size`, `quantity` — outside prose |
| candidate cannot create size or risk | field audit of both dataclasses for `size`/`qty`/`lots`/`risk`/`margin`/`premium`/`strike`/`limit`/`stop`/`target` |
| candidate cannot touch the holdout | the engine never imports the split at all; the shared test helper is teach-only |
| candidate cannot mutate the observation | before/after deep comparison of readings, both logs, history, snapshot, candles, releases, thesis **and route** after three full replays |
| candidate cannot auto-reverse | 0 direct `LONG↔SHORT` transitions, asserted |
| candidate cannot duplicate | one opportunity identity authorises at most one candidate, asserted |
| candidate cannot use future data | prefix causality asserted in the production suite at three cut points per module, under both execution contracts, plus an explicit "no later candle rewrites an earlier decision" test |
| candidate cannot use an old generation | `exit_check` reads the generation first, asserted per candle |

## 5. PRODUCTION REPLAY (§11)

Run from `src/` only — `prodreplay.py` imports nothing from the scratchpad, so an
incomplete promotion would have failed to start.

| ACTION | teach (7,200 candles) | validate (2,400) |
|---|---|---|
| `WATCH` | 5,302 · 73.6% | 1,693 · 70.5% |
| `NO_TRADE` | 1,565 · 21.7% | 568 · 23.7% |
| `PARTICIPATION_CANDIDATE_LONG` | 151 · 2.1% | 73 · 3.0% |
| `PARTICIPATION_CANDIDATE_SHORT` | 182 · 2.5% | 66 · 2.8% |
| `HOLD_LONG` / `HOLD_SHORT` | 0 / 0 | 0 / 0 |
| `EXIT_LONG` / `EXIT_SHORT` | 0 / 0 | 0 / 0 |

`HOLD` and `EXIT` are zero because no position is ever opened under the default contract.
That is the contract working, not a gap.

`STATUS`: `ACTIVE` 5,635 · `UNAVAILABLE` 1,482 · `BLOCKED` 83.
`EXECUTION_STATUS`: `NOT_APPLICABLE` 6,867 · `UNAVAILABLE` 333 — exactly the candidates.

**Candidates by release scale (teach): `OUTER` 320, `INNER` 10, `MICRO` 3.** Inner
participation while the parent is intact is not merely representable — it happens, and
`test_inner_participation_is_possible_while_the_parent_is_intact` asserts it on real
candles.

### Context / rejection reasons (teach)

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

**Candidates are 4.6% of teach candles and 5.8% of validate candles. That is a rate of
structural opportunity and not a win probability** — the previous study measured that the
context label does not predict outcome (46.9% vs 50.0%).

## 6. TRACES (§12)

All eleven render in `prodreplay.out`, each as **known facts → participation decision →
later outcome**, outcome always last. The set is unchanged from the validated one: outer
release with a clean path and with an immediate obstacle; inner release with the parent
intact and with a poor path; micro; simultaneous outer + inner; re-entry; same-generation
continuation; generation reversal; already-extended thesis; fresh thesis.

## 7. PERFORMANCE (§13)

Six blocks, 1,800 candles, production modules. Microseconds per candle.

| stage | median | p95 | max | candles/sec |
|---|---|---|---|---|
| participation | 47.5 | 80.4 | 296.7 | 19,162 |
| decision | 10.0 | 15.4 | 79.5 | 90,601 |
| **participation + decision** | **57.6** | **94.9** | **329.0** | **15,816** |

| stage / state | n | median | p95 | max |
|---|---|---|---|---|
| participation / flat | 1,783 | 47.4 | 79.3 | 296.7 |
| participation / position active | 458 | 48.1 | 76.9 | 265.4 |
| participation / multi-scale | 17 | 81.2 | 133.6 | 133.6 |
| participation / inner release | 39 | 79.4 | 107.3 | 157.1 |
| participation / micro release | 2 | 82.5 | 87.4 | 87.4 |
| decision / flat | 1,783 | 10.0 | 15.3 | 79.5 |
| decision / position active | 458 | 11.0 | 14.1 | 30.6 |
| decision / multi-scale | 17 | 13.0 | 17.9 | 17.9 |
| decision / inner release | 39 | 13.0 | 17.2 | 17.9 |
| decision / micro release | 2 | 13.2 | 14.4 | 14.4 |

Two notes. `position active` is measured under the research contract, because no position
exists under the default one. And the pre-promotion figure in the last report (15.3 µs)
is **not** comparable to the 47.5 µs here — I re-measured three consecutive passes on the
promoted code and got 47.3 / 45.2 / 46.8 µs, so the production number is stable and the
earlier one was measured differently. Either way this is ~16,000 candles per second
against a five-minute candle.

---

# PART II — REACTIVE EXECUTION STUDY v2

## 8. THE QUESTION, AND WHY THE COMPARISON IS FAIR THIS TIME

> Does a `PARTICIPATION_CANDIDATE` contain enough causal information to identify an
> economically useful **execution moment**?

Every earlier study foundered on one confound: a release is bar zero of the generation it
creates, so a same-thesis control necessarily sat later, with a looser stop and part of the
move gone. **Here that confound is the subject rather than the contaminant.** Both arms are
the *same candidate*, so §16's dimensions hold by construction:

| dimension | matched? |
|---|---|
| same generation | yes — the arms are one opportunity |
| same release scale | yes |
| same direction | yes |
| same opportunity class | yes |
| same route context | yes — the candidate's own route |
| same position state | yes — flat at the candidate |
| **same structural age** | **no — this is the variable under test** |

Six of seven match exactly; the seventh is what is being measured. Every arm walks to the
**same terminal candle** and dies on the **same** current-generation invalidation, so
waiting costs window rather than being handed a fresh one.

## 9. THE EVENTS — frozen before any outcome was read

Every one is a state the stack already publishes, taken at its first occurrence after the
candidate, inside the same generation. Nothing was invented and nothing was chosen after
seeing its result.

| event | published by | teach fire rate |
|---|---|---|
| `AT_CANDIDATE` | the contract's own moment | 100% |
| `RETESTING` | `postbreak.py` | 74.2% |
| `EXTENDING` | `postbreak.py` | 46.8% |
| `PAUSING` | `postbreak.py` | 44.4% |
| `NEXT_RELEASE` | `release.py` | 20.1% |
| `AT_NEXT_ZONE` | `route.py` | 2.4% |
| `MICRO_CONFIRMED` | `micro.py` | 1.8% |
| `MICRO_ALIGNED` | `micro.py` | 0.3% |

`RETESTING` and `PAUSING` appear as **published states being measured**, not as a retest or
pause requirement smuggled back into the engine. The engine has neither.

## 10. RESULT — paired against the candidate itself

333 teach candidates, 139 validate.

| event | teach dwin | 95% CI | validate dwin | 95% CI | same sign |
|---|---|---|---|---|---|
| `EXTENDING` | **−22.4** | [−30.1, −14.8] | **−11.7** | [−21.9, −1.5] | yes |
| `PAUSING` | **−13.5** | [−21.6, −5.4] | **−16.7** | [−28.3, −5.0] | yes |
| `NEXT_RELEASE` | −10.4 | [−26.1, +5.2] | −19.2 | [−41.0, +2.6] | yes |
| `RETESTING` | +6.5 | [−0.8, +13.7] | +10.9 | [−1.1, +22.9] | yes |
| `MICRO_CONFIRMED` | +33.3 (n 6) | [−8.0, +74.7] | n 0 | — | — |
| `AT_NEXT_ZONE` | −25.0 (n 8) | — | n 1 | — | — |

**Four events are negative and three of those are stable.** `EXTENDING` and `PAUSING` are
negative in both halves with confidence intervals excluding zero: **waiting for the market
to extend, or to pause, is measurably worse than acting at the candidate.** That is a
decisive negative result, and it independently confirms what the old
`B_PAUSE_THEN_EXTEND` study got wrong.

## 11. THE ONE POSITIVE EVENT IS ARITHMETIC — §19

`RETESTING` is the only event positive and same-signed in both halves. It fails on
inspection.

| `RETESTING` vs the candidate | teach | validate |
|---|---|---|
| dwin (`MFE>MAE`) | **+6.5** | **+10.9** |
| dMFE | **−0.13** | **−0.10** |
| distance to invalidation | **−0.22 ATR** | **−0.26 ATR** |
| median MFE | −0.34 | −0.49 |
| next reference reached | **−15.9 pp** | **−22.3 pp** |
| alive at the horizon | **−13.7 pp** | **−17.7 pp** |

Every absolute quantity is worse. The entry sits closer to the invalidation, so MFE and MAE
shrink together and the ratio crosses the line slightly more often — while capturing less
of the move, reaching the structural references far less, and dying far more. **That is a
smaller slice of the same move, not a better moment.**

The §19 checks confirm it:

* **not explained by route distance** — dwin is flat across route terciles (+6.0 / +8.6 /
  +4.8), so it is not a room effect. It is also not a gradient, so there is nothing to read.
* **dominated by one block** — teach per-block: 24 blocks, 12 positive, 6 negative, median
  **+2.1**; dropping the single most extreme block, the median falls to **+0.0** over 23
  blocks. §19 says the result must not be dominated by one block. It is.
* **generation age could not be tested** — the age cuts came out at 0 / 0 because outer
  releases are bar zero of the generation they create (245 candidates at age-low, 2 at
  age-high). This dimension is **unresolved**, and I am reporting that rather than
  manufacturing a stratification.

## 12. CLASSIFICATION (§19)

```
A = strong enough to design an execution contract
B = promising but insufficient
C = mechanical / selection effect
D = contradicted
```

| event | verdict |
|---|---|
| `EXTENDING` | **D — contradicted.** Negative in both halves, both CIs exclude zero. |
| `PAUSING` | **D — contradicted.** Same. |
| `NEXT_RELEASE` | **D — contradicted.** Negative in both halves. |
| `RETESTING` | **C — mechanical.** The gain is entry-location arithmetic; every absolute quantity falls; per-block dominance fails. |
| `MICRO_CONFIRMED`, `MICRO_ALIGNED`, `AT_NEXT_ZONE` | **insufficient population** — 6, 1 and 8 in teach; 0, 0 and 1 in validate. |

**No event reaches A or B. No execution contract is earned.**

The strongest single statement this study supports is a negative one, and it is worth
having: **the three obvious "wait for confirmation" rules are not neutral, they are
harmful.** Acting at the candidate beats waiting for extension by 22 points of win rate in
teach and 12 in validate, and beats waiting for a pause by 14 and 17.

## 13. WHAT THIS MEANS FOR THE SEQUENCE

```
production participation   ← done, this report
        ↓
execution study            ← done, this report: no rule earned
        ↓
validated execution rule   ← NOT reached
        ↓
execution contract         ← not started
        ↓
risk / sizing review       ← not started
        ↓
broker                     ← not started
```

`EXECUTION_STATUS` stays `UNAVAILABLE`. The engine keeps emitting
`PARTICIPATION_CANDIDATE_*` and keeps refusing to turn one into an order, which is now the
measured position rather than a placeholder: the candidate moment is the best of the
moments the stack can currently name, and none of the alternatives improved on it.

## 14. WHAT REMAINS UNAVAILABLE

* a validated execution rule — six studies, none survived;
* micro-scale anything — 3 candidates in teach, 0–2 events in validate;
* the generation-age dimension of the execution question — degenerate under the current
  candidate population, and honestly unresolved;
* inner-scale stability across periods — 10 teach candidates, still a map property;
* session state, cost, sizing, risk, options — out of scope by design.

**Stopped here, as instructed.** No live orders, no broker, no holdout, no thresholds, no
score, no setup. The reactive architecture is exactly as validated.
