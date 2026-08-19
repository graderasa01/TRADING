# INTEGRATION AUDIT + PRODUCTION REPLAY + EXECUTION BOUNDARY

> **INTEGRATION PASS**
>
> Reactive trader core is production-coherent.
> Execution boundary is explicit.
> Execution remains `UNAVAILABLE`.
>
> No `ENTER_*` · no broker · no order · no sizing · no risk · no options · no target ·
> no trailing stop · `split.holdout()` not called · 0 live positions opened.
>
> Prior stages: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) ·
> [`REACTIVE-TRADER.md`](REACTIVE-TRADER.md) ·
> [`REACTIVE-PARTICIPATION-ENGINE.md`](REACTIVE-PARTICIPATION-ENGINE.md) ·
> [`REACTIVE-PARTICIPATION-PROMOTION.md`](REACTIVE-PARTICIPATION-PROMOTION.md) ·
> [`POSITION-LIFECYCLE.md`](POSITION-LIFECYCLE.md) ·
> [`THESIS-IDENTITY-AND-POSITION-MANAGEMENT.md`](THESIS-IDENTITY-AND-POSITION-MANAGEMENT.md)

Sample: the established teach/validate blocks — **teach 24 blocks / 7,200 candles**,
**validate 8 blocks / 2,400 candles**, 5m Bank Nifty, production modules only. No
scratchpad implementation is imported anywhere in this stage.

---

# PART I — INTEGRATION AUDIT

## 1. ARCHITECTURE — the real production path

| module | owns | immutable |
|---|---|---|
| `boxes/frontier.py`, `boxes/micro.py` | the reading, the map, the micro | yes |
| `src/livemap/release.py` | `ReleaseState` — what broke, which scale, what is beyond | yes |
| `src/livemap/interpreter.py`, `route.py` | the release-relative route | yes |
| `src/livemap/postbreak.py` | the episode / excursion | yes |
| `src/livemap/thesis.py` | `LiveThesis`, **`ThesisIdentity`**, `identity_of()` | yes |
| `src/livemap/participation.py` | `ParticipationContext`, `opportunity_of()`, `Sources`, `Book` | context yes, `Book` **no — it is the carried state** |
| `src/livemap/reactor.py` | `decide()`, `exit_check()`, **`replay()` — the one fold** | decision yes |
| `src/livemap/position.py` | `TradeThesisSnapshot`, `PositionEvaluation`, `PositionState`, `lifecycle()` | snapshot/evaluation/state yes, `PositionRecord` append-only |
| `src/livemap/boundary.py` | **new** — `ExecutionRequest`, where the reactive trader stops | yes |

**Ownership of each state:**

| fact | single owner | created at |
|---|---|---|
| thesis identity | `thesis.identity_of()` | every candle with a generation |
| opportunity identity | `participation.opportunity_of()` | every candle with a release + generation |
| position state | `reactor.Book.position`, transitioned only in `reactor.replay` | after the decision, never before |
| generation | `thesis.generations()` | the episode's own state history |
| invalidation | `thesis.invalidation` / `invalidation_price` | the **current** generation, always |
| release identity | `release.Release` | the candle the boundary gave way |
| current thesis | `thesis.narrate()` — exactly one per candle | — |
| entry thesis snapshot | `position.TradeThesisSnapshot.of()` | frozen at the open, forever |
| exit decision | `reactor.exit_check()` | one definition, one call site |
| position becomes FLAT | `reactor.replay` on the EXIT candle | that candle |
| a new opportunity becomes visible | `reactor.decide` branch 6, only when `position == FLAT` | a **later** candle |

## 2. ONE CANDLE, END TO END (§1)

`teach0 c428`, the first research open in the sample:

```
CANDLE                  c428  2023-08-08 13:45  close 44,959.20
 ↓ boxes/frontier.py
READING / FRONTIER      current NO_STRUCTURE   micro absent
 ↓ src/livemap/release.py
RELEASE CONTEXT         1 release   OUTER C08.low down at 44,970   OUTER_CONTROLLING
 ↓ src/livemap/thesis.py
LIVE THESIS             SHORT_IDEA  generation 1  ACTIVE  state RETESTING
                        invalidation: two closes back through C08's broken edge @ 44,970.49
 ↓ thesis.identity_of()          — THE single identity source
THESIS IDENTITY         C08/GEN1/DOWN
 ↓ src/livemap/participation.py
PARTICIPATION CONTEXT   PARTICIPATION_AVAILABLE   reasons ()
                        opportunity (('C08', 428, 1), 'OUTER', 'C08', 'down')
                        kind NEW_THESIS   entry-shaped True
 ↓ src/livemap/reactor.py decide()  — the ONLY decision site
PARTICIPATION DECISION  PARTICIPATION_CANDIDATE_SHORT  [ACTIVE]
                        position BEFORE this candle FLAT   open_identity None
 ↓ src/livemap/position.py
TRADE THESIS SNAPSHOT   SHORT opened c428 on C08/GEN1/DOWN   FROZEN
POSITION EVALUATION     none — nothing to compare against on the open candle
POSITION LIFECYCLE      phase OPEN   position FLAT → SHORT
 ↓ src/livemap/boundary.py
EXECUTION BOUNDARY      EXECUTION_STATUS = UNAVAILABLE   NO_EXECUTION_CONTRACT
                        NO ORDER · NO POSITION · NO SIZE · NO RISK
```

No new state machine was created.

## 3. SINGLE SOURCE OF TRUTH (§2) — one finding, fixed at source

Static AST scan of the reactive surface plus the production sources it consumes:

| fact | definitions | construction sites | call sites | verdict |
|---|---|---|---|---|
| `ThesisIdentity` | 1 (`thesis.py:138`) | **1** (`thesis.py:185`) | `participation.py:400`, `reactor.py:185` | **clean** |
| exit decision | 1 (`reactor.exit_check`) | — | **1** (`reactor.decide`) | **clean** |
| position transition fold | — | — | **1** (`reactor.replay`) | **clean** |
| `thesis_key` local duplicate | **0** | — | — | deleted last stage, still gone |
| opportunity generation key | 1 (`opportunity_of`) | **3 → 1** | 3 | **was a violation** |

### The finding

`opportunity_of()` is the canonical opportunity key. Two other sites computed the same
tuple by hand, and **both guarded the null case differently**:

```python
participation.py:78   (t.broken_id, t.index - t.bars_since_break,      t.generation)  # canonical
participation.py:332  (t.broken_id, t.index - (t.bars_since_break or 0), t.generation)  # _opportunity_kind
participation.py:528  (t.broken_id, t.index - (t.bars_since_break or 0), t.generation)  # Book.gen_key
```

This is §2's named stop condition — *opportunity tuple reconstruction* — and §27's
condition 3, one layer silently reconstructing another layer's fact.

**Measured before touching anything.** Over 9,600 real candles the divergent branch never
fires: `bars_since_break is None` occurs 345 teach / 211 validate times, and in **0** of
them is a generation live. The three calculations agreed everywhere.

| | teach | validate |
|---|---|---|
| thesis candles | 7,200 | 2,400 |
| `bars_since_break` is `None` | 345 | 211 |
| …with `generation != 0` **and** `broken_id` set | **0** | **0** |
| `_opportunity_kind` key ≠ `opportunity_of` | **0** | **0** |
| `Book.gen_key` key ≠ `opportunity_of` | **0** | **0** |

**Fixed at source, not patched around.** Both sites now call `opportunity_of()`. The whole
teach + validate pipeline under both contracts is **byte-identical** before and after —
SHA-256 of every `PositionState` and `ParticipationDecision` field:
`650c8a8b…f20d9a88` on both sides. The static scan now reports **1** site computing the
tuple and 3 call sites of the canonical function.

### The other direction, also checked

`identity_of()` is called from two places — `participation.assess` (which publishes
`ctx.thesis_identity`) and `reactor.exit_check` (which recomputes it from the thesis).
Two call sites of one function is not two calculations, but it is the mildest form of the
same pattern, so it was measured rather than assumed:

| | teach | validate |
|---|---|---|
| `ctx.thesis_identity` ≠ `identity_of(thesis)` | **0** | **0** |
| `snapshot.identity` ≠ context identity at the open | **0** | **0** |
| `evaluation.current_identity` ≠ context identity | **0** | **0** |

## 4. ONE POSITION FOLD (§3)

There is exactly one. `reactor.replay` carries `Book.position` and applies the transition
**after** the decision; `position.lifecycle` walks that decision stream and never runs a
second fold. The three public production entry points were executed over the same candles
and compared:

| | teach | validate |
|---|---|---|
| `position.lifecycle` vs `reactor.replay` — position/action mismatches | **0** | **0** |
| `participation.eye` vs `reactor.replay` — full context mismatches (all 60 fields) | **0** | **0** |

`participation.eye` deliberately carries no position, so it is only comparable under the
default contract — which is where it is compared, and where it is identical field for field.

## 5. CANDLE ORDER — HARD INVARIANT (§4)

| | teach | validate |
|---|---|---|
| same-candle reverse (EXIT not leaving FLAT) | **0** | **0** |
| a candle that both exits and enters | **0** | **0** |
| candidate emitted while positioned | **0** | **0** |
| OPEN from a non-FLAT position | **0** | **0** |
| reopen on the exit candle | **0** | **0** |

`EXIT candle ≠ ENTRY candle`, on 341 real exits.

## 6. ENTRY THESIS vs CURRENT MARKET (§5)

Every research position's `snapshot_at_open` was captured, the block replayed to the end,
and the snapshot compared again field by field including nested frozen `Release` objects.

| | teach | validate |
|---|---|---|
| positions audited | 249 | 102 |
| `snapshot_at_open` ≠ `snapshot_after_full_replay` | **0** | **0** |

The market moved underneath every one of them — 241 teach positions saw a
`THESIS_INVALIDATED`, 208 a `DIRECTION_CHANGED`, 138 a `MICRO_DEVELOPMENT` — and the
snapshot did not move.

## 7. THESIS IDENTITY INTEGRATION (§6)

Canonical and unchanged: `ThesisIdentity(broken_id, generation, direction)`. No generation
integer standing alone; no break index inside identity. `opportunity_of()` still keeps the
break index, because *"is this a new opportunity?"* and *"is this the same thesis?"* are
different questions.

**The required real-data case — same structure, same generation, same direction, new break
index:** 38 instances in teach. One of them, verbatim:

```
position opened on L02/GEN1/UP at c507
c513: OUTER L02.high re-broke
  entry opportunity  ('L02', 507, 1)
  new opportunity    ('L02', 513, 1)          <- moved
  SAME THESIS        L02/GEN1/UP == L02/GEN1/UP
  action             HOLD_LONG   phase CONTINUATION   LONG → LONG
```

**Different structure, same generation integer, same direction:** follows the measured
semantics — identity differs, so the position exits. 125 teach instances of a same-structure
generation move, all exits.

## 8. RELEASE → THESIS → POSITION (§7) — traces A–H

All eight are real candles. Reading order is left to right and carries no future
information before the action column.

| | case | result |
|---|---|---|
| **A** | outer release → new thesis → candidate → LONG | c437 `OUTER L01.high` → `L01/GEN1/UP` → `NEW_THESIS` → OPEN → **HOLD** |
| **B** | inner release inside an intact parent | c434 `INNER C04.low`, parent unbroken → `NEW_GENERATION_RELEASE` → OPEN → **HOLD** |
| **C** | micro development, same thesis | `C08/GEN1/DOWN` unchanged across c417–c421 → **HOLD_SHORT**, phase CONTINUATION |
| **D** | same-structure re-break | `L02` re-breaks at c513 → new opportunity, identity unchanged → **HOLD** |
| **E** | genuine thesis change | c442 `L01/GEN1/UP` → `C08/GEN1/DOWN` → **EXIT_LONG**, LONG → FLAT |
| **F** | generation change | c431 `C08/GEN1/DOWN` → `C08/GEN2/DOWN` → **EXIT_SHORT**, SHORT → FLAT |
| **G** | opposite thesis on the exit candle | c431 exits, c432–c436 **WATCH while FLAT** — no reverse |
| **H** | exit → later fresh candidate | exit c431 → flat c432–c436 → **new open c437, 6 candles later, from FLAT** |

---

# PART II — PRODUCTION REPLAY

## 9. ACTION CENSUS (§9) — production modules only

| ACTION | teach default | teach research | validate default | validate research |
|---|---|---|---|---|
| `NO_TRADE` | 1,565 | 1,457 | 568 | 539 |
| `WATCH` | 5,302 | 3,574 | 1,693 | 923 |
| `PARTICIPATION_CANDIDATE_LONG` | 151 | 117 | 73 | 53 |
| `PARTICIPATION_CANDIDATE_SHORT` | 182 | 132 | 66 | 49 |
| `HOLD_LONG` | **0** | 780 | **0** | 375 |
| `HOLD_SHORT` | **0** | 899 | **0** | 361 |
| `EXIT_LONG` | **0** | 111 | **0** | 51 |
| `EXIT_SHORT` | **0** | 130 | **0** | 49 |
| **TOTAL** | **7,200** | **7,200** | **2,400** | **2,400** |

The default-contract candidate counts — 333 teach, 139 validate — reproduce the
independently-measured promotion-stage figures exactly.

## 10. LIFECYCLE CENSUS (§9)

| phase | teach | | validate | |
|---|---|---|---|---|
| `FLAT` | 5,031 | 69.9% | 1,462 | 60.9% |
| `HOLD` | 1,487 | 20.7% | 697 | 29.0% |
| `INVALIDATED` | 241 | 3.3% | 100 | 4.2% |
| `OPEN` | 249 | 3.5% | 102 | 4.2% |
| `CONTINUATION` | 192 | 2.7% | 39 | 1.6% |
| **TOTAL** | **7,200** | | **2,400** | |

`FLAT + OPEN + HOLD + CONTINUATION + INVALIDATED` covers **every candle exactly once** in
both halves. **Phases outside the model: 0.** No silent states.

Exit reasons are only ever the three validated ones — teach `IDEA_REVERSED` 148 /
`THESIS_UNRESOLVED` 60 / `GENERATION_CHANGED` 33; validate 63 / 28 / 9. No stop, no target,
no timer.

## 11. CROSS-LAYER CONSISTENCY COUNTERS (§10)

| counter | teach | validate |
|---|---|---|
| release exists but thesis missing | **4** — explained below | 0 |
| thesis exists but thesis identity missing | 0 | 0 |
| candidate exists but opportunity identity missing | 0 | 0 |
| position exists without `TradeThesisSnapshot` | 0 | 0 |
| position exists with no identity | 0 | 0 |
| HOLD under changed thesis | 0 | 0 |
| EXIT with unchanged resolved thesis | 0 | 0 |
| candidate while position active | 0 | 0 |
| duplicate candidate | 0 | 0 |
| duplicate open | 0 | 0 |
| same-candle reverse | 0 | 0 |
| old-generation invalidation | 0 | 0 |
| snapshot mutation | 0 | 0 |
| **default contract executed** | **0** | **0** |
| **default contract carried a position** | **0** | **0** |

### The 4, explained rather than waved past

All four are an inner or micro boundary giving way in the **first 20 candles after the
400-candle warm-up**, before the episode machine has a generation for anything:

```
teach0  c404  INNER C09.high up      generation 0  NO_IDEA  -> NO_TRADE
teach3  c418  INNER C11.low down     generation 0  NO_IDEA  -> NO_TRADE   (thesis born c419)
teach12 c418  MICRO C09.m2.high up   generation 0  NO_IDEA  -> NO_TRADE
teach18 c420  MICRO L01.m1.low down  generation 0  NO_IDEA  -> NO_TRADE   (thesis born c421)
```

A release is a structural event; a thesis needs an *episode*. At a warm-up boundary the
first can exist before the second. Every one resolves to `NO_TRADE` naming `NO_THESIS` and
`NO_CURRENT_GENERATION_INVALIDATION` — the fact is missing and the system says which fact.
The opportunity tuple on these candles carries a `None` head, and **it can never enter the
duplicate registry**: reaching `Book.used` requires a candidate, a candidate requires
`PARTICIPATION_AVAILABLE`, and that requires a generation. Measured: 4 such contexts, **0**
became a candidate, **0** reached `used`. This is a replay warm-up artefact, not a live
path — in live running the warm-up is the session history.

## 12. STATE ACCOUNTING (§11)

| | teach | validate |
|---|---|---|
| every OPEN → exactly one active position | 249 opens, 249 records | 102 / 102 |
| every EXIT → exactly one transition to FLAT | 241 exits, **0** not FLAT | 100, **0** |
| every active position → exactly one frozen snapshot | **0** without | **0** |
| every candidate → exactly one opportunity identity | **0** without | **0** |
| every opportunity → at most one open position | **0** reopened | **0** |
| opposite generation cannot directly reverse | **0** same-candle reverses | **0** |
| new opportunity after exit only from FLAT on a later candle | **0** violations | **0** |

## 13. PREFIX CAUSALITY, END TO END (§12)

`production_replay(upto=k)` against `full_production_replay()[:k+1]`, comparing **every**
output field — release, thesis, thesis identity, participation, opportunity, snapshot,
position evaluation, action, position after, and both boundary views — **21 fields per row**.

| cut | teach mismatches | validate mismatches |
|---|---|---|
| k = 25 | **0** | **0** |
| k = 50 | **0** | **0** |
| k = 100 | **0** | **0** |
| k = 200 | **0** | **0** |
| k = 400 | **0** | **0** |
| rows compared | 9,096 | 3,032 |

**Total mismatches: 0.**

## 14. DETERMINISM (§13)

The complete pipeline run twice, under both the default and the research contract:

| | rows compared | differences |
|---|---|---|
| teach | 14,400 | **0** |
| validate | 4,800 | **0** |

100% identical.

## 15. MAP-STORY GATE (§14)

`test_the_map_story_did_not_move` — **green**. Structure formation, break timing, node
geometry, micro geometry, release semantics and thesis history all unmoved. The fixture was
not touched and the gate was not weakened.

**Full suite: 1,265 passed**, run on the final tree (1,231 before this stage + 34 new
boundary tests).

## 16. PERFORMANCE (§15) — the integrated path, measured directly

6 teach blocks, 1,800 candles. One timer around
`assess → decide → evaluate → lifecycle phase`, **not** a sum of separately-measured medians.

| stage (µs) | median | p95 | max | candles/sec |
|---|---|---|---|---|
| assess (participation context) | 17.15 | 29.10 | 236.70 | 58,309 |
| decide (reactor) | 3.80 | 6.50 | 49.00 | 263,158 |
| evaluate (position vs market) | 0.10 | 5.70 | 17.10 | — |
| lifecycle phase | 2.40 | 5.40 | 25.70 | 416,667 |
| **INTEGRATED candle** | **24.70** | **44.50** | **258.10** | **40,486** |

| integrated candle, by state | n | median | p95 | max |
|---|---|---|---|---|
| `FLAT` | 1,366 | 23.10 | 38.90 | 258.10 |
| `POSITION_ACTIVE` | 434 | 31.35 | 48.60 | 147.70 |
| `MULTI_SCALE` | 12 | 37.15 | 65.40 | 65.40 |
| `INNER_RELEASE` | 59 | 37.20 | 57.80 | 70.70 |
| `MICRO_RELEASE` | 3 | 38.90 | 41.80 | 41.80 |
| `GENERATION_CHANGE` | 38 | 36.90 | 57.00 | 59.20 |
| `CONTINUATION_HEAVY` | 82 | 34.25 | 50.00 | 72.00 |

`evaluate`'s 0.10 µs median is honest but misleading on its own: 1,366 of 1,800 candles are
`FLAT`, where there is nothing to evaluate. The `POSITION_ACTIVE` row is the number that
matters, and it is 31 µs for the whole candle.

**Against the previously measured layer costs:** the prior stage measured identity 1.20 µs,
evaluation 5.80 µs and lifecycle transition 21.80 µs *in separate runs*. The integrated
path is 24.70 µs, which is **not** their sum — as §15 warned it would not be. The
observation zip is the real cost and it is not in this table: a full `lifecycle()` call
including `sources()` runs at ~1,000 candles/sec, because the replay harness rebuilds
`narrate` / `observe` / `Interpreter` from scratch on every call. That is a replay
property, not a live one; live observation is incremental. Against a 5-minute candle,
40,486 reactive candles/sec is not a constraint.

---

# PART III — EXECUTION BOUNDARY CONTRACT

## 17. THE BOUNDARY OBJECT (§17)

New production module `src/livemap/boundary.py`, 34 tests in `tests/test_boundary.py`.

```python
@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    opportunity_id · thesis_identity · position_side · decision_action
    decision_index · decision_timestamp
    execution_status · execution_reason · disposition
    contract · contract_validated
    trade_thesis_snapshot        # a REFERENCE, None in production
```

It carries **no** quantity, lots, size, margin, premium, strike, limit price, stop price,
target or broker order id. `__post_init__` rejects any field whose name matches the
forbidden vocabulary, and a test asserts the same about the class. `creates_an_order` is a
property returning `False`, so a caller asking the question gets the answer from the object
rather than from a comment.

It means *"the reactive trader has reached the boundary where an external execution
contract may decide whether and how to execute."* It does not mean *"place this order."*

## 18. BOUNDARY VOCABULARY (§18)

Two axes, deliberately not one.

```
EXECUTION_STATUS   UNAVAILABLE | PENDING | RESOLVED | NOT_APPLICABLE   reactor.EXEC_*
DISPOSITION        NO_EXECUTION_CONTRACT | AWAITING_EXECUTION_CONTRACT
                   | EXECUTION_CONTRACT_RESOLVED                       boundary's own
```

The status axis **reuses `reactor.EXEC_*` verbatim** — §2 applied to this stage's own new
code, and a test asserts the boundary never restates those four string literals. The
disposition is genuinely new and maps one-to-one from the status, so the two cannot drift
apart in a caller's head.

The disposition constants are named `NO_CONTRACT` / `AWAITING_CONTRACT` /
`CONTRACT_RESOLVED` rather than the obvious `RESOLVED`, because `reactor.EXEC_RESOLVED`
already owns that word on the other axis. The first draft used `RESOLVED` and its own test
caught it.

With `NoExecution`, `EXECUTION_STATUS = UNAVAILABLE` always. **No fake resolver was
written.** `PENDING` and `RESOLVED` exist as vocabulary a future contract may use.

## 19. PARTICIPATION CANNOT BYPASS THE BOUNDARY (§19)

Static import audit over the **whole** reactive side — `thesis.py`, `release.py`,
`participation.py`, `reactor.py`, `position.py`, `boundary.py`:

| forbidden | found |
|---|---|
| `broker` | **absent** |
| `orders` / `order` | **absent** |
| `risk` | **absent** |
| `sizing` / `size` | **absent** |
| `options` | **absent** |
| `setups`, `exits`, `modes`, `guards`, `journal` | **absent** |
| `learning` / `split` (the holdout) | **absent** |

`src/broker/live.py` does not exist. No `place_order` / `modify_order` / `cancel_order`
call exists anywhere in `src/`. The reactive layer does not know a split exists, so it
cannot spend one.

## 20. LIFECYCLE CANNOT BYPASS THE BOUNDARY (§20)

`HOLD` and `EXIT` never reach `boundary_of()` — asserted on every candle of a positioned
replay. Only `PARTICIPATION_CANDIDATE_*` arrives, and `ExecutionRequest.__post_init__`
raises if constructed with any other action.

**Production default, both halves: 0 positions opened, 0 orders, 0 sizes, 0 risk.** The
research injector remains the only way a position exists, it cannot be constructed empty,
and it is the default nowhere.

## 21. BOUNDARY CENSUS (§21)

| | teach | validate |
|---|---|---|
| **PRODUCTION — `NoExecution`** | | |
| boundary requests | 333 | 139 |
| by execution status | `UNAVAILABLE: 333` | `UNAVAILABLE: 139` |
| by disposition | `NO_EXECUTION_CONTRACT: 333` | `NO_EXECUTION_CONTRACT: 139` |
| research resolutions | **0** | **0** |
| orders created | **0** | **0** |
| positions opened | **0** | **0** |
| **RESEARCH — `ResearchPositionInjector`** | | |
| boundary requests | 249 | 102 |
| by disposition | `EXECUTION_CONTRACT_RESOLVED: 249` | `102` |
| research resolutions | 249 (all flagged) | 102 |
| orders created | **0** | **0** |

## 22. BOUNDARY TRACE (§22) — and the research trace, kept apart

**Production:**

```
MARKET                  c428 2023-08-08 13:45  44,959.2
 ↓
RELEASE                 OUTER C08.low down at 44,970
 ↓
THESIS                  SHORT_IDEA generation 1 ACTIVE   C08/GEN1/DOWN
 ↓
PARTICIPATION_CANDIDATE_SHORT
 ↓
ExecutionBoundary       contract NoExecution   validated False
EXECUTION_STATUS        UNAVAILABLE
DISPOSITION             NO_EXECUTION_CONTRACT
                        NO_VALIDATED_EXECUTION_RULE_EXISTS
                        NO ORDER · NO POSITION · NO SIZE · NO RISK
 ↓
NO ORDER                creates_an_order = False
NO POSITION             lifecycle records under NoExecution = 0
```

**Research — a different path, and the object says so:**

```
PARTICIPATION_CANDIDATE_SHORT   c428
 ↓
ResearchPositionInjector        validated = False   9 named opportunities
 ↓
TradeThesisSnapshot             SHORT  C08/GEN1/DOWN  FROZEN at c428
 ↓
HOLD          c429  HOLD_SHORT
HOLD          c430  HOLD_SHORT
INVALIDATED   c431  EXIT_SHORT   IDEA_REVERSED

the same candle at the boundary:
  EXECUTION_STATUS  RESOLVED       DISPOSITION  EXECUTION_CONTRACT_RESOLVED
  is_research = True   contract_validated = False   creates_an_order = False
  "RESEARCH resolution — an unvalidated contract answered. This is not
   evidence that live entry should happen."
```

## 23. RESEARCH vs LIVE SEPARATION (§23)

No boolean flag hidden in the decision path. The contract is an injected object, named in
the call, and every request carries the contract's name and its `validated` flag —
`is_research` is true whenever a `RESOLVED` came from an unvalidated contract. A test
asserts **no contract in the repository is validated**: `NoExecution`, `ImmediateExecution`
and `ResearchPositionInjector` are all `validated = False`.

## 24. BOUNDARY TESTS (§24)

34 tests, all green: purity (no broker/order/risk/sizing/options import anywhere upstream,
no split), candidate isolation (cannot create a position, an order, a size, a broker
action), `NoExecution` (every candidate `UNAVAILABLE`, none `RESOLVED`, no order-shaped
payload), lifecycle (`HOLD`/`EXIT` stay inside, injection explicit), prefix causality at
k = 25/50/100/200, determinism, and non-mutation of the decisions it reads.

---

# PART IV — FINAL DECISION

## 25. HARD STOP CONDITIONS (§27)

| # | condition | result |
|---|---|---|
| 1 | two independent position folds | **no** — one, `reactor.replay` |
| 2 | two thesis identity calculations | **no** — one construction site |
| 3 | one layer silently reconstructs another's fact | **found, fixed at source, byte-identical** |
| 4 | same-candle exit/reverse | **no** — 0 in 341 exits |
| 5 | old thesis controls current position | **no** — 0 HOLD under a changed thesis |
| 6 | candidate opens a production position | **no** — 0 under the default contract |
| 7 | broker/risk/sizing dependency in the reactive layer | **no** |
| 8 | prefix causality fails | **no** — 0 mismatches, 21 fields, 5 cut points |
| 9 | determinism fails | **no** — 0 differences |
| 10 | map-story changes | **no** — gate green, fixture untouched |
| 11 | order-shaped data in the execution boundary | **no** — structurally refused |
| 12 | holdout touched | **no** — `split.holdout()` not called; the reactive layer cannot import the split |

Condition 3 was a genuine violation, reported above with its source, measured to be
non-divergent on 9,600 candles, and eliminated by collapsing the two local copies onto the
canonical function — not by working around it. The proof that this changed nothing is a
byte-identical pipeline digest over teach and validate under both contracts.

## 26. WHAT CHANGED IN PRODUCTION

| file | change |
|---|---|
| `src/livemap/boundary.py` | **new** — `ExecutionRequest`, `boundary_of()`, `requests()`, `census()`, the disposition vocabulary |
| `tests/test_boundary.py` | **new** — 34 tests |
| `src/livemap/participation.py` | `_opportunity_kind` and `Book.gen_key` now call `opportunity_of()` — the §2 duplicate removed |

Nothing else in `src/` was modified. `boxes/`, `frontier.py`, `micro.py`, `eye.py`,
`postbreak.py`, `release.py`, `route.py`, `thesis.py`, `reactor.py` and `position.py` are
untouched. No fixture was regenerated and no gate was weakened.

## 27. WHAT THIS DOES NOT CLAIM

1. **Execution is not validated.** Every position in every number here was injected by
   `ResearchPositionInjector`. Under the production contract, 0 positions open.
2. **This is not an edge measurement.** Coherent thesis attribution does not make a
   candidate profitable; six execution studies found no rule that earned a contract, and
   `EXTENDING`, `PAUSING` and `NEXT_RELEASE` were rejected. Nothing here revisits them.
3. **The counters are measured on this data** — teach and validate under one split digest.
   They are not theorems.
4. **`bars held` is not a holding-period recommendation.**
5. Micro-scale and inner-scale position populations remain tiny (3 and 10 teach
   candidates); no claim is made about them.

## 28. FINAL ARCHITECTURE AFTER THIS STAGE

```
                    MARKET
                       ↓
                 OBSERVATION          boxes/frontier.py · micro.py
                       ↓
                   RELEASE            livemap/release.py
                       ↓
                  LIVE THESIS         livemap/thesis.py
                       ↓
                THESIS IDENTITY       thesis.identity_of()      ← one source
                       ↓
                PARTICIPATION         livemap/participation.py
                       ↓
              TRADE THESIS SNAPSHOT   livemap/position.py       ← frozen forever
                       ↓
             CURRENT MARKET EVALUATION
                       ↓
              POSITION MANAGEMENT     reactor.replay            ← one fold
                ↙               ↘
              HOLD             EXIT
                                  ↓
                                FLAT
                                  ↓
                         NEW OPPORTUNITY  (later candle, from FLAT only)
                                  ↓
                       EXECUTION BOUNDARY  livemap/boundary.py
                                  ↓
                       UNAVAILABLE (NOW)
```

---

```
INTEGRATION PASS
```

**Reactive trader core is production-coherent.
Execution boundary is explicit.
Execution remains UNAVAILABLE.**

Not execution-ready. Not live-trading-ready. Not profitable. Not a validated trader.

**Stopped here.** No `ENTER_*`, no execution contract, no broker, no orders, no risk, no
sizing, no targets, no trailing stops, no holdout, no new execution hunt.
