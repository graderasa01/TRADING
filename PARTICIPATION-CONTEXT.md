# PARTICIPATION CONTEXT STUDY — measurement report

> **Measurement only.** `src/` unmodified. `decision.py` unmodified. No `ENTER_*`, no
> broker, no order, no sizing, no risk, no exit, no execution routing, no new setup, no new
> detector, no new score, no new probability, no new threshold. `split.holdout()` was not
> called.
>
> Script: `participation.py` (scratchpad). Raw output: `participation.out`.
> Split digest `5a702621fa6703bf` — teach 24 blocks, validate 8 blocks, 5m Bank Nifty,
> 1m forward walk, horizon 75 bars session-bounded.

---

## 0. THE QUESTION, AND THE ANSWER IN ONE LINE

> Given a current valid thesis, does the current market location provide a structurally
> meaningful opportunity to participate **now**?

**C — the apparent effect is mechanical.** The stack *can* assemble the participation
context, and it does so with named missing facts rather than invented numbers. But every
measured advantage of a structural release over another moment in the same thesis is
reproduced by two facts that are true by construction, and the one comparison that would
remove them is too thin to decide anything. For the inner and micro scales the honest
answer is **D**: they are not measurable at all right now, and the reason is the map, not
the market.

---

## 1. WHAT WAS BUILT, AND WHAT IT REUSES

Every field is a copy of a fact the stack already publishes.

```
MAP            build_snapshot                boxes/snapshot.py
FRONTIER       run / Reading                 boxes/frontier.py
MICRO          Reading.micro                 boxes/micro.py
EYE            eye.observe (via thesis.py)   livemap/eye.py
POST-BREAK     postbreak.observe             livemap/postbreak.py
ROUTE          ZoneRoute + corridor          livemap/route.py
LIVE THESIS    thesis.narrate                scratchpad thesis.py
GENERATIONS    thesis.generations            scratchpad thesis.py
DECISION SM    decision.opportunity_of       scratchpad decision.py
```

The only rule applied on top is the repo's own two-close rule (`BREAK_CLOSES` with
`tol_at`), used to say *when a published boundary changed sides*. It is applied identically
at OUTER, INNER and MICRO, which is what makes the three scales comparable instead of three
different definitions of "break".

**One correction was forced during the run.** The first pass counted every boundary
crossing as a release, and the traces immediately showed re-entries filed as breakouts
(`C06.low broke up` while price sat at position 0.12 *inside* C06). A crossing up through a
structure's high, or down through its low, leaves it — that is the release §11 describes.
The mirror crossings walk back inside, which the stack already calls `RE_ENTRY`. They are
now counted and set aside. This removed 441 of 908 teach crossings, and it changed the
OUTER population from 295 to 203.

---

## 2. A. OPPORTUNITY CENSUS

### TEACH

| scale | crossings | re-entries | releases | context complete | duplicates | **opportunities** |
|---|---|---|---|---|---|---|
| OUTER | 606 | 282 | 324 | 204 | 1 | **203** |
| INNER | 200 | 109 | 91 | 38 | 8 | **30** |
| MICRO | 102 | 50 | 52 | 27 | 0 | **27** |
| ALL | 908 | 441 | 467 | 269 | 9 | **260** |

### VALIDATE

| scale | crossings | re-entries | releases | context complete | duplicates | **opportunities** |
|---|---|---|---|---|---|---|
| OUTER | 221 | 111 | 110 | 94 | 0 | **94** |
| INNER | 2 | 0 | 2 | 0 | 0 | **0** |
| MICRO | 21 | 8 | 13 | 8 | 0 | **8** |
| ALL | 244 | 119 | 125 | 102 | 0 | **102** |

### Why a real structural break did not become a candidate

Every rejection is a **named missing fact**, never a bound that was not cleared.

| reason | teach | validate |
|---|---|---|
| `NO_PATH` — no mapped structure ahead in the thesis direction | 151 | 15 |
| `COUNTER_THESIS` — the release points against the current idea | 30 | 4 |
| `IDEA_UNRESOLVED` — `FORMING_NEW_STRUCTURE`, direction unknown | 7 | 3 |
| `CONTRADICTION_UNRESOLVED` — history disagrees with the current state | 7 | 1 |
| `NO_THESIS` — no episode has established a direction | 3 | 0 |
| `DUPLICATE_OF_LIVE_OPPORTUNITY` | 9 | 0 |

`NO_PATH` is the big one: **on 32% of teach releases and 12% of validate releases the stack
publishes no structural reference ahead at all**, so the participation question is
`UNAVAILABLE` by the stack's own rules rather than answerable and negative.

### The duplicate problem, before and after the guard

| | teach | validate |
|---|---|---|
| candles where the decision layer's own eligibility passes | 2,515 | 1,015 |
| distinct thesis generations behind them | 334 | 134 |
| **candles per opportunity, ungated** | **7.5** | **7.6** |
| structural release firings | 467 | 125 |
| after the guard (generation + structural event + scale) | 260 | 102 |
| repeat firings dropped by the guard | 9 | 0 |

Two different duplicate problems, and they need different guards. The 7.5× is the *thesis
restating itself* every candle — `decision.py`'s opportunity identity already collapses it.
The 9 dropped firings are the *same boundary re-breaking inside one generation*, which the
extended identity catches. Neither is large once the two-close transition rule is in place,
because that rule only fires on the candle a boundary changes sides.

### What the candidates look like

```
price location      NO_STRUCTURE 214   INSIDE 23   BELOW 9   ABOVE 9   AT_EDGE 5   (teach)
episode state       EXTENDING 125   RETESTING 111   PAUSING 11   REENTERING 8   ROTATING 5
thesis status       ACTIVE 246   DEVELOPING 14
event created the thesis   205 of 260
```

**82% of participation candidates have `PRICE_LOCATION = NO_STRUCTURE`.** At the moment a
structure releases it is finalised and price belongs to nothing, so `position_in_current`,
`to_upper_edge` and `to_lower_edge` are all `None` on exactly the candle the study needs
them. Half of the core question — *is the current location meaningful?* — is structurally
unavailable at the moment it is asked.

### The move-extension problem, in the stack's own numbers (teach)

```
distance to the CURRENT generation's invalidation   p10 0.21   median 0.94   p90 2.37   max 14.46 ATR
of this thesis's path, already travelled            p10 0.00   median 0.00   p90 2.25   max 14.90 ATR
room beyond the boundary that just broke            p10 0.13   median 0.88   p90 4.04   max 14.40 ATR
```

The invalidation reference is always structural and always belongs to the current
generation — but its **distance is unbounded**. Trace D below is a live short thesis 87
candles old, 14.9 ATR already travelled, whose current-generation invalidation sits 14.5 ATR
away. The thesis is valid and the participation is worthless, and nothing in the stack
distinguishes it from a fresh one except these raw numbers.

---

## 3. B. SAME-THESIS MATCHED COMPARISON

Controls come from the **same episode and the same generation**, carry the **same idea**,
and die on the **same invalidation price**. `NULL_MATCH` additionally holds price-location
class, room ahead (±30%) and room behind (±40%) constant.

### OUTER — 203 teach / 94 validate

| arm | n | MFE | MAE | MFE>MAE | alive% | session% | next% | far% | life | stop | gone |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **teach** EVENT | 203 | 0.99 | 0.99 | 46.8% | 45.3% | 38.4% | 36.9% | 16.3% | 15 | 0.90 | 0.00 |
| NULL_THESIS | 857 | 0.91 | 0.92 | 48.1% | 60.6% | 51.2% | 32.1% | 15.2% | 8 | 1.57 | 2.76 |
| NULL_MATCH | 37 | 0.74 | 0.87 | 40.5% | 54.1% | 35.1% | 21.6% | 13.5% | 11 | 1.01 | 2.12 |
| **validate** EVENT | 94 | 0.85 | 1.16 | 40.4% | 40.4% | 28.7% | 26.6% | 16.0% | 12 | 0.91 | 0.00 |
| NULL_THESIS | 432 | 0.69 | 1.05 | 39.8% | 67.4% | 48.1% | 19.7% | 6.9% | 7 | 1.85 | 3.05 |
| NULL_MATCH | 25 | 0.99 | 1.53 | 36.0% | 56.0% | 36.0% | 12.0% | 4.0% | 23 | 1.54 | 2.45 |

Within-thesis paired (each opportunity against the mean of its **own** controls):

| | teach | validate |
|---|---|---|
| dwin vs NULL_THESIS | +3.3 (n 153) | +6.2 (n 70) |
| dMFE vs NULL_THESIS | +0.45 ATR | +0.50 ATR |
| dwin vs NULL_MATCH | +9.4 (n 23) | +19.2 (n 13) |
| dMFE vs NULL_MATCH | +0.39 ATR | +0.31 ATR |

**The paired statistic is not sampling noise.** Controls are drawn at random up to 12 per
opportunity; re-running teach under three seeds moves OUTER `dwin` between +3.1 and +4.0 and
`dMFE` between +0.45 and +0.46. The median opportunity has only 4 eligible controls and just
33 of 153 hit the cap, so the sample is close to exhaustive and the seed barely matters.
Whatever is wrong with this number, it is not the draw.

### INNER — 30 teach / **0 validate**

Teach: dwin +11.0 (n 26) vs NULL_THESIS, +20.0 (n 9) vs NULL_MATCH, `par%` 58.8 (the parent
edge was reached in 59% of cases where one existed). Per-block 4 blocks, 2 positive.

**Validate produced two inner releases in eight blocks and zero opportunities.**
`INSUFFICIENT_POPULATION`. Nothing about the teach result is confirmable.

### MICRO — 27 teach / 8 validate

Teach: dwin **−1.2** (n 16) vs NULL_THESIS. Validate `INSUFFICIENT_POPULATION`.
Micro is the only scale whose paired effect is negative against its own thesis, and it
cannot be checked.

---

## 4. C. PER-BLOCK STABILITY

| scale | split | blocks | positive | negative | median | worst | best |
|---|---|---|---|---|---|---|---|
| OUTER | teach | 24 | 15 | 9 | +8.5 | −62.5 | +33.3 |
| OUTER | validate | 8 | 6 | 2 | +9.2 | −4.0 | +19.2 |
| INNER | teach | 4 | 2 | 2 | +6.7 | −27.8 | +88.9 |
| INNER | validate | — | — | — | INSUFFICIENT | | |
| MICRO | teach | 2 | 2 | 0 | +6.6 | +2.1 | +11.1 |
| MICRO | validate | — | — | — | INSUFFICIENT | | |

OUTER is the only scale with enough blocks to say anything, and it is positive in 21 of 32
blocks with a worst block of −62.5. INNER rests on four blocks and MICRO on two.

### The path gradient — the actual participation hypothesis

If *room ahead* is what makes a release worth participating in, the gradient must be
monotone and positive in both halves against the room-matched control.

| scale / room beyond | teach dwin_any | val dwin_any | teach dwin_match | val dwin_match | teach n | val n |
|---|---|---|---|---|---|---|
| OUTER / PATH_LOW | −2.9 | +6.0 | 0.0 | 0.0 | 53 | 11 |
| OUTER / PATH_MID | +9.6 | +17.4 | +16.7 | 0.0 | 72 | 32 |
| OUTER / PATH_HIGH | +1.0 | −0.6 | +6.1 | +27.8 | 78 | 51 |

**It is not monotone in either half, and it does not agree between them.** The middle bucket
is best in teach and in validate against the loose control; against the matched control the
ordering reverses. More structural room ahead does not read better, reactively.

---

## 5. D. MECHANICAL EXPLANATIONS

This is where the study lands.

### The control cannot be time-matched, and that is not fixable

```
scale     controls before the event   after   median lag (5m candles)
OUTER                             0     857                        7      (teach)
OUTER                             0     432                        7      (validate)
INNER                            95     183                        5
```

**A release is the first candle of the generation it creates.** 100% of OUTER controls
therefore sit *later* in the same generation. "Event vs control" is unavoidably "bar zero,
tight stop, nothing consumed" against "seven candles later, looser stop, 2.8 ATR already
gone". That is not participation timing being measured — it is the definition of the two
arms.

### The three by-construction differences

| teach | EVENT | NULL_THESIS | NULL_MATCH |
|---|---|---|---|
| stop distance (ATR) | 0.90 | 1.57 | 1.01 |
| path already consumed (ATR) | 0.00 | 2.76 | 2.12 |
| room ahead (ATR) | 0.99 | 0.65 | 2.04 |
| ATR | 47.3 | 51.3 | 48.8 |
| horizon (bars) | 75 | 75 | 75 |

The event arm has a stop 40% tighter and zero consumed path **because it is the release**,
and it has more room ahead **because the corridor origin resets to the boundary just
crossed**. All three are the arm's definition, not its behaviour. The observable consequence
is exactly what a tighter stop mechanically produces: the event dies far more often
(alive 45% vs 61%, session survival 38% vs 51%) while showing more favourable excursion
(dMFE +0.45). That is a stop-distance effect wearing a participation label.

### Selection — what each scale actually selects

| scale | created the thesis | age at candidate | already gone | parent width | stop |
|---|---|---|---|---|---|
| OUTER | 100.0% | 0 | 0.00 | 1.36 | 0.90 |
| INNER | 6.7% | 9 candles | 1.71 | 3.43 | 1.07 |
| MICRO | 0.0% | 0 | 0.00 | 3.24 | 0.94 |

The three scales are not three ways of looking at the same moment. OUTER *is* the thesis's
birth; INNER and MICRO are events inside a thesis some other structure created, and INNER
selects structures 2.5× wider than OUTER does. Comparing them is comparing three different
populations.

### Is the inner scale absent, or unavailable?

```
candles with at least one mapped structure inside the current one
teach      607 of 3,088    19.7%     mean 3.6 inner structures when present
validate    14 of   975     1.4%     mean 1.0
```

**The inner scale is fourteen times rarer in validate — as an offering of the map, before
the market gets a vote.** INNER's collapse from 30 opportunities to 0 is therefore a
property of the map's containment structure across periods, not evidence that inner releases
stopped happening. Until that is understood, no inner-scale result can be validated, and
"the inner cluster is not automatically tradable" cannot even be tested.

### Move extension — does the stack separate "still room" from "already consumed"?

| teach | n | MFE | MAE | MFE>MAE | remaining frac |
|---|---|---|---|---|---|
| OUTER / gone LOW | 160 | 0.99 | 0.99 | 47.5% | 1.00 |
| OUTER / gone HIGH | 43 | 1.01 | 0.99 | 44.2% | 0.48 |
| INNER / gone LOW | 12 | 1.34 | 0.75 | 58.3% | 1.00 |
| INNER / gone HIGH | 9 | 1.21 | 1.64 | 44.4% | 0.02 |

| validate | n | MFE | MAE | MFE>MAE | remaining frac |
|---|---|---|---|---|---|
| OUTER / gone LOW | 70 | 0.96 | 1.13 | 41.4% | 1.00 |
| OUTER / gone HIGH | 24 | 0.35 | 1.24 | 37.5% | 0.11 |

*(remaining frac is EVALUATION ONLY — it uses the rest of the session and never selected or
labelled a candidate.)*

`already_gone` does separate the populations — in validate, releases with a consumed path
produced 0.35 ATR of MFE against 0.96 for fresh ones, with 11% of the path left. So **the
stack does carry the fact that distinguishes "thesis valid + still room" from "thesis valid
+ move already consumed"**: it is `bars_since_break` plus the excursion already made, both
already published. What it does not carry is any reason to prefer one over the other that
survives teach → validate: the teach split shows almost no separation (47.5% vs 44.2%) while
validate shows a large one. One half of the data says the distinction matters and the other
says it does not.

---

## 6. E. REAL TRADER TRACES

Selected on **context only**; each context block was fixed before its outcome was read.
Full renderings are in `participation.out`. Summarised here in the order the brief asks.

**A — outer release, long path.** `L04.high` broke up at 50,764, generation 1 ACTIVE,
`EXTENDING`, next reference C07 at 13.66 ATR, invalidation the broken edge 0.99 ATR away.
Everything the brief calls a good reactive context. → **MFE 0.11 ATR, MAE 1.47, invalidated
after 5 minutes.**

**B — outer release, opposing structure immediately ahead.** `L03.low` broke down at 48,944,
first obstacle 0.02 ATR beyond the boundary — the poorest possible path. → **MFE 4.45 ATR,
both references reached, survived the session.**

A and B are the study in two rows. The context called them in exactly the wrong order.

**C — inner release, parent intact.** `C08.low` broke down inside R01 (width 9.32 ATR),
price mid-parent, parent's far edge 5.66 ATR ahead, thesis 13 candles old with 2.23 ATR
already travelled. → MFE 0.50, MAE 1.16, did not survive the session.

**D — inner release, next reference too close.** `C09.low` broke at 51,153 with the first
obstacle 0.02 ATR beyond it; the thesis was 87 candles old with 14.90 ATR already gone and
its current-generation invalidation 14.46 ATR away. → **MFE 0.17 ATR, MAE 11.00 ATR.** This
is the move-extension failure in its purest form: a valid thesis, a real break, and a
participation context that is worthless — and every fact needed to see that was on the
candle.

**E — micro release.** Population 27 in teach, 8 in validate. The trace renders, the
population does not support a conclusion: `INSUFFICIENT_POPULATION`.

**F — the same location at two scales.** This is the most important trace in the study.
Block 0, candle 410, one candle, two boundaries breaking at once: `C05.high` (OUTER, the
thesis's own structure) and `C09.high` (INNER). The two participation contexts are printed
side by side and they are **identical in every published field**:

```
                                        OUTER          INNER
price location                          NO_STRUCTURE   NO_STRUCTURE
thesis generation                       1              1
free_to_near / zone_depth / free_to_far 0.30/0.92/1.22 0.30/0.92/1.22
corridor stops ahead                    8              8
invalidation distance                   1.15           1.15
already gone                            0.00           0.00
room beyond the broken boundary         0.10           1.01     <- the only difference
event created the thesis                True           False    <- and this
```

Every route and location fact the stack publishes is measured from the **current
structure's** break edge or from price — never from the boundary that actually broke. So the
stack, as it stands, **cannot tell an inner release from an outer release at the same
candle**. The one field that separates them (room beyond the broken boundary) had to be
derived in the study by re-running `build_corridor` from the broken boundary, and the other
is bookkeeping about which structure owns the thesis.

**G — a break the context rejects.** `C01.high` broke up at 44,527 with a real path ahead
and a current-generation invalidation — and generation 3 was `CONFLICTED`, `contradicted =
True`, `next_expected = RESOLVE_CONFLICT`. Rejected as `CONTRADICTION_UNRESOLVED`. The
refusal names a missing fact rather than a number that was not exceeded, which is the
behaviour the brief asks for.

---

## 7. POSITION-AWARE THOUGHT EXPERIMENT

Counting only; nothing was executed.

| | teach | validate |
|---|---|---|
| FLAT — first opportunity of a block | 24 | 8 |
| NEW generation, same idea (a fresh entry, independently earned) | 75 | 18 |
| NEW generation, opposite idea (EXIT first, never an auto-reversal) | 45 | 21 |
| SAME generation, a further release (continuation info, not an entry) | 116 | 55 |

**45% of teach candidates and 54% of validate candidates are further releases inside a
generation that is already live.**
Under the existing decision contract those are not entries — they are continuation or
management information. And the split by scale is total: 0 of 203 OUTER candidates happened
inside someone else's thesis, while 28 of 30 INNER and 27 of 27 MICRO did. So the
inner-versus-outer question is, operationally, *"may a live position be added to or
re-read?"* far more often than it is *"may a new position be opened?"*.

---

## 8. F. CONCLUSION

```
A = reactive participation can be supported by existing context
B = one scale appears promising but needs more evidence
C = apparent effects are mechanical / selection-driven     <- this one
D = existing stack remains descriptive only                <- for INNER and MICRO
```

**One strongest reason:**

> A structural release is, by construction, the first candle of the thesis generation it
> creates. Every same-thesis control must therefore sit later in that generation — 857 of
> 857 OUTER controls in teach, median seven candles later — so the entire measured
> advantage (dMFE +0.45 teach, +0.50 validate) is inseparable from "bar zero with a 0.90 ATR
> structural stop" versus "seven candles later with a 1.57 ATR one". The one comparison that
> removes the confound by matching room ahead and room behind survives on 23 teach and 13
> validate pairs, which is not enough to decide anything — and it is thin precisely because
> the confound is structural, not accidental.

The supporting facts:

* the room-ahead gradient, which is the participation hypothesis itself, is **not monotone
  in either half and disagrees between them**;
* `MFE > MAE` at the release is **46.8% teach / 40.4% validate** — below a coin flip in
  absolute terms, before any cost;
* the release is **invalidated far more often** than another moment in the same thesis
  (alive 45% vs 61%), which is what a tighter stop does mechanically;
* INNER cannot be validated at all, and the reason is that the map offers an inner scale on
  19.7% of teach candles and 1.4% of validate candles;
* MICRO is negative against its own thesis in teach and insufficient in validate.

### What the study nevertheless establishes

These are not effects, they are capabilities, and they held up:

1. **The context assembles.** 260 of 467 teach releases carry a complete participation
   context, and the other 207 are refused by a **named missing fact** — `NO_PATH` 151,
   `COUNTER_THESIS` 30, `CONTRADICTION_UNRESOLVED` 7 — never by an invented threshold.
2. **Invalidation is always current-generation and always structural.** The generation-2
   wording (*"the original break resumes"*) is correct in every rendered trace.
3. **The opportunity identity works.** 7.5 eligible candles per generation collapse to one
   opportunity; the extended identity additionally caught 9 same-boundary re-breaks.
4. **The stack can reject.** Contradiction, counter-thesis and unresolved direction all fire
   on real breaks.

### What is missing, stated as facts rather than as work

* **`PRICE_LOCATION` is `NO_STRUCTURE` on 82% of releases.** The stack cannot answer *"where
  is price inside the relevant structure"* on the candle where the question is asked,
  because the structure has just been finalised.
* **No published field distinguishes an inner release from an outer one** at the same candle
  (trace F). Route and location are measured from the current structure's edge, never from
  the boundary that broke.
* **The inner scale's availability is a map property that varies 14× between periods**, so
  the inner-versus-outer question is currently unanswerable rather than answered.
* **The invalidation distance is unbounded** (max 14.46 ATR): the reference is always
  structurally correct and can be arbitrarily far from price.

None of the above is a recommendation to build anything. Per the brief, the study stops at
the measurement.
