# REACTIVE TRADER — Stage 1 build + Stage 2 study

> **Observation only.** No `ENTER_*`, no broker, no order executor, no sizing, no risk, no
> exit engine, no threshold, no score, no probability. `EXECUTION_STATUS` is `UNAVAILABLE`
> on every candle and every candidate is a `TRADE_CANDIDATE` trace.
> `split.holdout()` was not called; `HOLDOUT-ACCESS.md` does not exist.
>
> Field audit and design record: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md).
> Prior diagnostic: [`PARTICIPATION-CONTEXT.md`](PARTICIPATION-CONTEXT.md).

---

## 0. THE TWO ANSWERS

**Stage 1 succeeded.** The four holes the diagnostic named are closed, and the closure is
demonstrated on the exact candle that exposed them.

**Stage 2 answers `C` — mechanical / selection-driven** — for OUTER, and `D` — still
descriptive only — for INNER and MICRO.

The purpose of Stage 1 was *"to make the test valid, not to find an edge"*. It made the test
valid. The test then said no.

---

## 1. WHAT WAS BUILT

| surface | what | lines |
|---|---|---|
| `src/livemap/release.py` | **new** — the release context, inside the existing quarantine | 1 new file |
| `tests/test_release.py` | **new** — 38 tests | 1 new file |
| *(nothing else in `src/`)* | no existing production file was modified | — |
| scratchpad `parteye.py` | `ParticipationContext`, the market eye, the human trader view | research |
| scratchpad `test_parteye.py` | 28 tests | research |
| scratchpad `marketeye.py` | census, market eye render, traces A–K | research |
| scratchpad `reactive2.py` | the Stage 2 study | research |

`thesis.py` and `decision.py` stay in the scratchpad. A release record carries **no**
generation, thesis, invalidation, opportunity identity or position: putting them on it
would give the observation world a second copy of the generation and make a production
module depend on an unvalidated one. The participation layer composes the two.

### The one thing that is not a copy

`OUTER` comes from `breaks.from_logs()` and `MICRO` from `micro.py`'s own
`MICRO_BREAK_UP/DOWN`. Both were already published. There is no published event for *"a
mapped structure inside the current one has released"*, so `release.py` applies the repo's
own two-close transition rule, with the repo's own `tol_at` skirt, to boundaries the map
already published. It creates no structure, introduces no number, and writes nothing back.
`micro.py` is the precedent one level down. This is stated in the module docstring, in the
audit, and here, because it is the only place a reader has to take a judgement on trust.

---

## 2. STAGE 1 — THE FOUR HOLES, AND THEIR CLOSURE

### Hole 1 — *what exactly broke?*

| | before | after |
|---|---|---|
| release identity | inferred from the current structure after the fact | recorded on the release candle: `broken_id`, `broken_edge`, `broken_low/high`, `broken_kind`, `scale`, `parent_id`, `origin` |

### Hole 2 — *where is price?*

`PRICE_LOCATION` reads `NO_STRUCTURE` on a release candle because the node has just been
finalised. Measured over the real sample:

| | teach | validate | the five audit sessions |
|---|---|---|---|
| release-relative location available | **554 / 554 · 100%** | **165 / 165 · 100%** | **8 / 8 · 100%** |
| old `PRICE_LOCATION` (non-`NO_STRUCTURE`) | 178 / 554 · 32% | 45 / 165 · 27% | 0 / 8 · **0%** |

The old field answers the question on a third of releases and on **none** of the audit
sessions' releases. The release-relative one answers it on every release, and separately
reports whether price is inside, at the edge of, or beyond the **parent**.

### Hole 3 — *what is ahead?*

The route origin is now the boundary that broke. The dedicated fixture makes the two
possible answers numerically different and the test asserts which one the code used:

```
P  100-130   the current structure        an inner release through I.high, measured
I  110-120   a mapped structure inside     from 120, has 20 points of free space
Z  140-150   the next zone                 from the CURRENT edge, 130, it has 10
price 125
```

`test_the_inner_route_origin_is_the_inner_boundary_not_the_current_edge`.

### Hole 4 — *outer and inner on the same candle*

The diagnostic's trace F: block 0, candle 410, `C05.high` (outer) and `C09.high` (inner)
breaking together, **every published field identical**. The same candle now reads:

| | OUTER | INNER |
|---|---|---|
| broken boundary | `C05.high` | `C09.high` |
| broken edge | 44,966 | 44,917 |
| parent | — | `C05` |
| route origin | 44,966 | 44,917 |
| free_to_near | **5** | **54** |
| free_to_far | 111 | 160 |
| beyond the edge | +51 | +100 |
| parent location | `NO_PARENT` | `BEYOND_PARENT` |

Both are kept. `controlling_scale` is `MULTI_SCALE`, not a guess — 30 such candles in
teach, 25 of them carrying two readings whose release-relative room differs by a median of
**0.22 ATR**, the number the old stack reported as 0.00 for both.

### Release, not crossing

A crossing up through a high or down through a low leaves the structure. The mirror
crossings walk back in, which the stack already calls `RE_ENTRY`. The layer refuses them
structurally (`test_a_reentry_is_never_a_release`), and trace G shows a real one: candle
431, `REENTERING`, generation flipped 1→2, **0 releases emitted**.

---

## 3. STAGE 1 — CENSUS

| | teach | validate |
|---|---|---|
| candles read | 7,200 | 2,400 |
| candles carrying a release | 554 | 165 |
| releases | **594** — OUTER 467, INNER 109, MICRO 18 | **165** — OUTER 160, INNER 2, MICRO 3 |
| simultaneous-release candles | 30 | 0 |

**Opportunity kind** (teach): `NEW_THESIS` 467, `SAME_GENERATION_CONTINUATION` 42,
`NEW_GENERATION_RELEASE` 22, `SAME_GENERATION_REPEAT` 19.

**Participation** (teach): `AVAILABLE` 333, `UNAVAILABLE` 138, `CONSTRAINED` 83.

**Missing facts, named** (teach): no mapped path beyond the broken boundary 133, no
current-generation invalidation 9, idea unresolved 5, no thesis 4.

**Named constraints** (teach): continuation of a live generation 41, counter-thesis 28,
opportunity already taken 19, two scales released together 17, unresolved contradiction 5.

Nothing is hidden behind an average and no unavailable context is suppressed.

### Position-aware behaviour (synthetic measurement mode, teach)

```
entries 261    exits 254    direct reversals 0
```

Zero is asserted, not observed: §17 has no `REVERSE`, and
`test_synthetic_mode_never_reverses_in_one_candle` fails the run if one ever appears.

---

## 4. STAGE 2 — THE RE-RUN

Same-generation controls, same idea, same invalidation price. Room ahead is measured from
the **candle's own close for both arms** when matching — a control has no broken boundary,
and measuring the event from its boundary and the control from its close would hand the two
arms different rulers. The release-relative route is used where it belongs: describing and
stratifying the event.

### Populations

| | teach | validate |
|---|---|---|
| OUTER candidates | **463** | **159** |
| INNER candidates | **64** | **0** |
| MICRO candidates | 8 | 2 |

Set aside in teach: counter-thesis 34, duplicate 16, no thesis 9.

### OUTER

| arm | n | MFE | MAE | MFE>MAE | alive% | sess% | next% | far% | stop | gone |
|---|---|---|---|---|---|---|---|---|---|---|
| **teach** EVENT | 463 | 0.82 | 0.81 | 46.2% | 37.8% | 29.2% | 49.7% | 25.3% | 0.61 | 0.00 |
| NULL_THESIS | 1755 | 0.93 | 0.93 | 48.0% | 62.5% | 50.3% | — | — | 1.76 | 2.88 |
| NULL_MATCH | 112 | 0.95 | 0.92 | 44.6% | 55.4% | 42.0% | — | — | 1.18 | 2.19 |
| **validate** EVENT | 159 | 0.69 | 0.84 | 40.9% | 33.3% | 25.8% | 37.7% | 25.4% | 0.66 | 0.00 |
| NULL_THESIS | 647 | 0.76 | 0.99 | 40.8% | 65.2% | 47.1% | — | — | 1.70 | 3.00 |
| NULL_MATCH | 35 | 0.86 | 0.74 | 51.4% | 54.3% | 25.7% | — | — | 1.37 | 2.40 |

| paired | teach | validate |
|---|---|---|
| dwin vs NULL_THESIS | +9.0 (n 304) | +6.2 (n 99) |
| dMFE vs NULL_THESIS | +0.47 ATR | +0.73 ATR |
| dwin vs NULL_MATCH | +4.7 (n 65) | +2.4 (n 21) |
| per-block positive | 19 of 24 | 5 of 8 |

### INNER — 64 teach, **0 validate**

Teach: dwin +4.5 vs NULL_THESIS, **−8.7** vs NULL_MATCH, per-block 5 of 8 positive.
Validate produced two inner releases and zero candidates. `INSUFFICIENT_POPULATION`.

### MICRO — 8 teach, 2 validate

`micro.py`'s own `MICRO_BREAK` event is far rarer than the first study's rescan of the micro
band suggested (18 releases in teach, not 52). Using the published event is correct and the
population is what it is. `INSUFFICIENT_POPULATION` in both halves.

---

## 5. THE RELEASE-RELATIVE PATH GRADIENT — the one real finding, and why it is not enough

Now measured from the boundary that actually broke, which the first study could not do:

| OUTER / room ahead | teach dwin_any | val dwin_any | teach dwin_match | val dwin_match | teach n | val n |
|---|---|---|---|---|---|---|
| PATH_LOW | +1.2 | +2.2 | −23.2 | — | 105 | 15 |
| PATH_MID | +12.5 | +0.9 | −2.8 | −12.5 | 120 | 73 |
| **PATH_HIGH** | **+15.0** | **+15.7** | **+20.8** | **+22.2** | 111 | 50 |

This is the first time in this line of work that a stratum has been positive in **all four
cells**, including against the room-and-stop-matched control. Against teach the gradient is
monotone in both controls. It is the closest thing to a signal these studies have produced,
and it exists only because Stage 1 supplied the correct origin.

**It still does not survive two checks.**

**Check 1 — the matched cell is not distinguishable from zero.**

```
PATH_HIGH matched cell:  n 24   dwin +20.8   sd 58.8   SE 12.0   95% CI [−2.7, +44.4]
```

The interval crosses zero. The validate cell is n 9, which is worse. Four positive cells
resting on 24 and 9 paired events is a pattern, not evidence.

**Check 2 — the matched control is a biased subsample, and the bias is structural.**

A matched control exists for only **65 of 463 OUTER events (14%)**, and those events are not
typical releases:

| | median stop | median room | median MFE |
|---|---|---|---|
| events that could be matched (65) | **1.02 ATR** | 1.37 | 1.13 |
| events that could not (398) | **0.55 ATR** | 0.75 | 0.70 |

Matching succeeds precisely when the release's invalidation happens to sit about twice as
far away as usual — which is when a release stops looking like a release and starts looking
like a mid-generation candle. So the only comparison that removes the confound can only be
run on the 14% of releases where the confound is already weakest.

---

## 6. MECHANICAL EXPLANATIONS

**The by-construction asymmetry is unchanged by Stage 1, and it was always the point.**

| teach | EVENT | NULL_THESIS | NULL_MATCH |
|---|---|---|---|
| stop distance (ATR) | 0.61 | 1.76 | 1.18 |
| path already consumed (ATR) | 0.00 | 2.88 | 2.19 |
| ATR | 46.9 | 51.3 | 49.6 |
| horizon (bars) | 75 | 75 | 75 |

```
controls drawn BEFORE the event   0 of 1755   (teach)      0 of 647   (validate)
median lag                        7 candles later          7 candles later
```

A release is the first candle of the generation it creates. Every same-thesis control must
therefore sit later, with a looser stop and part of the move already gone. Stage 1 fixed
*which facts exist*; it could not fix *what the two arms are*, and nothing can, because the
asymmetry is the definition of a release.

The observable consequence is exactly what a tighter stop mechanically produces: the event
shows more favourable excursion (dMFE +0.47 / +0.73) while being invalidated far more often
(alive 37.8% vs 62.5%). That is a stop-distance effect wearing a participation label.

**Absolute performance, before any cost.** `MFE > MAE` at the release is **46.2% teach /
40.9% validate**. Below a coin flip. `CLAUDE.md` §11 puts the round trip on monthly Bank
Nifty options at 44–64% of a 25-point R.

**The Stage 1 participation label does not predict outcome, and should not be read as if it
did.**

| teach | n | MFE | MAE | MFE>MAE |
|---|---|---|---|---|
| OUTER / `AVAILABLE` | 320 | 0.78 | 0.81 | 46.9% |
| OUTER / `CONSTRAINED` | 16 | 0.85 | 0.84 | 50.0% |

`AVAILABLE` is a statement about *facts being present and unobstructed*. It is not a
quality score, it does not behave like one, and §31 already said it must not be read as
`ENTER`.

**INNER availability is still a map property, not a market one.** 109 inner releases in
teach, 2 in validate. The `INNER_SCAN` requires a mapped node price-contained in the current
live band; how often the map offers one varies by an order of magnitude between periods.
Until that is understood, inner tradeability stays **unanswerable**, exactly as the
diagnostic said — not disproven.

---

## 7. TRACES

Eleven traces (A–K) are rendered in `marketeye.out`, each with `BEFORE` and the full context
block printed before any outcome. Two are worth quoting here, because between them they are
the study.

**A — outer release, longest corridor beyond the boundary, `AVAILABLE`, generation 1,
`EXTENDING`, invalidation 0.99 ATR away.** → MFE 0.11 ATR, MAE 1.47, invalidated after 5
minutes.

**B — outer release with the first obstacle 0.02 ATR beyond the boundary — the poorest
possible path.** → MFE 4.45 ATR, both references reached, survived the session.

The context called them in the wrong order. One pair proves nothing, which is why the
gradient was measured over 463 candidates instead — and the gradient's own verdict is §5.

---

## 8. VERIFICATION GATES (§37)

| # | gate | status |
|---|---|---|
| 1 | major-map story causally stable, additive fields only | **pass** — no existing `src/` file modified |
| 2 | full test suite passes | **pass** — 803 tests green |
| 3 | new release-context tests pass | **pass** — 38 in `tests/test_release.py`, 28 in `test_parteye.py` |
| 4 | prefix causality | **pass** — `observe(upto=k) == observe()[:k+1]`, release and participation |
| 5 | determinism | **pass** — same stream twice, identical |
| 6 | no look-ahead | **pass** — no later candle rewrites an earlier release |
| 7 | no micro leakage into the major map | **pass** — logs, history and snapshot byte-identical after `observe()` |
| 8 | no release leakage into the historical map | **pass** — same assertion; no release id reaches the map |
| 9 | no duplicate entries from one opportunity | **pass** — asserted on the synthetic fold |
| 10 | no automatic reversal | **pass** — 0 direct reversals over 261 synthetic entries, asserted |
| 11 | current-generation invalidation always used | **pass** — present on every directional thesis; generation-2 wording asserted |
| 12 | `src/setups/` independent | **pass** — imports neither `livemap` nor `release`; quarantine test covers `release.py` automatically |
| 13 | holdout untouched | **pass** — `HOLDOUT-ACCESS.md` absent; the audit day `2025-09-12` was **refused by name** for being in a holdout month |
| 14 | `EXECUTION_STATUS` honest | **pass** — `UNAVAILABLE` on every candle |

No §36 hard-stop condition was hit. The nearest was §36.3/§36.8 — whether the inner scan is
a second detector. It is documented in three places and applies an existing rule to existing
boundaries, but it is the one item in this build a reviewer should form their own opinion
on.

---

## 9. CONCLUSION

```
A = reactive participation supported
B = one scale promising
C = mechanical / selection                    <- OUTER
D = descriptive only                          <- INNER and MICRO
```

**One strongest reason:** the release is the first candle of the generation it creates, so
no same-thesis control can be time-matched to it — 0 of 1,755 teach controls and 0 of 647
validate controls precede their event. Every measured advantage therefore remains
inseparable from "bar zero with a 0.61 ATR structural stop" versus "seven candles later with
a 1.76 ATR one", and the only comparison that removes the confound can be built for **14%**
of releases — the 14% whose stop is already twice as far away as a typical release's.

### What genuinely changed

Stage 1 delivered what it promised, and the deliverable is a *representation*, not an edge:

1. the broken boundary, its scale and its parent are recorded causally on the release candle;
2. price location relative to the release is available on **100%** of releases, against 32% for the field that used to answer it;
3. the route is measured from the boundary that broke — proved by a fixture where the two answers differ;
4. simultaneous releases stay separate objects, with `MULTI_SCALE` instead of a guess;
5. re-entries are structurally not releases;
6. continuation and repeat releases are named and never become second entries.

That is the market eye the brief asked for, and a trader can read one candle and answer
every question in §1.

### What the next study needs, stated as a requirement rather than a plan

The `OUTER × PATH_HIGH` cell is the first well-posed candidate this work has produced. To
move it from *pattern* to *evidence* it needs a matched population large enough for its
confidence interval to clear zero — roughly an order of magnitude more matched pairs than
the 24 available now. That is a data-volume problem (the identical ruleset on Nifty,
FinNifty and Sensex, as `CLAUDE.md` §8 already prescribes), not another observation layer.

**Stopped here, as instructed.** No broker integration, no order executor, no holdout.
