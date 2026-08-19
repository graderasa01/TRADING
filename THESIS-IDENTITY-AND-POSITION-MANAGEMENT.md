# THESIS IDENTITY INTEGRITY + REACTIVE POSITION MANAGEMENT

> **PART I — THESIS IDENTITY INTEGRITY: PASS**
> **PART II — REACTIVE POSITION MANAGEMENT: PASS**
>
> `EXECUTION_STATUS = UNAVAILABLE` · no `ENTER_*` · no broker · no order · no sizing ·
> no risk · no options · no target · no trailing stop · `split.holdout()` not called.
>
> Prior stages: [`RELEASE-CONTEXT.md`](RELEASE-CONTEXT.md) ·
> [`REACTIVE-TRADER.md`](REACTIVE-TRADER.md) ·
> [`REACTIVE-PARTICIPATION-ENGINE.md`](REACTIVE-PARTICIPATION-ENGINE.md) ·
> [`REACTIVE-PARTICIPATION-PROMOTION.md`](REACTIVE-PARTICIPATION-PROMOTION.md) ·
> [`POSITION-LIFECYCLE.md`](POSITION-LIFECYCLE.md)

---

# PART I — THESIS IDENTITY INTEGRITY

## 1. THE AUDIT (§2) — and the rule I was told to assume turned out to be wrong

§2B said re-measure `(structure, generation)` before locking it. **Doing so refuted it.**

Scanned over teach and validate, grouping every directional-thesis candle by candidate
identity components:

| | teach | validate |
|---|---|---|
| `(structure, generation)` groups | 462 | 124 |
| …of those, groups whose **break index moved** | 186 | 57 |
| …of those, groups carrying **two different ideas** | **98** | **39** |
| …of those, groups carrying **two different invalidations** | **98** | **39** |
| candle-to-candle thesis transitions | 669 | 217 |
| …transitions where the generation **integer was equal** | **95 · 14.2%** | **31 · 14.3%** |

`(structure, generation)` is **too loose**. `L02` generation 1 broke *up* (invalidation
44,650.93) and also broke *down* (44,567.27); both collapse to one key. Adding the
direction takes both counts to **zero** in both halves:

| grouping | groups | two ideas | two invalidations | break index moved |
|---|---|---|---|---|
| `(structure, generation)` | 462 / 124 | 98 / 39 | 98 / 39 | 186 / 57 |
| **`(structure, generation, direction)`** | 560 / 163 | **0 / 0** | **0 / 0** | 176 / 59 |

### The three answers §2 asked for

**A — what defines identity:** the broken structure, the generation and the direction.

**B — the break index must not:** confirmed, and it still moves inside 176 teach / 59
validate identity groups. Including it would report a thesis change on every re-break —
the exact error the previous stage caught (35 of 70 held candles, every one `L02`
re-breaking with the invalidation unmoved).

**C — the invalidation must not:** measured, not preferred. Inside one
`(structure, generation, direction)` group the invalidation reference **never varies** —
zero groups with two invalidations, both halves. It is *derivable from* identity, so
including it would add nothing and would make identity move whenever the reference was
recomputed.

## 2. ONE AUTHORITATIVE FUNCTION (§4)

```python
# src/livemap/thesis.py
@dataclass(frozen=True, slots=True)
class ThesisIdentity:
    broken_id: str
    generation: int
    direction: str          # up | down

def identity_of(thesis) -> ThesisIdentity | None
```

Immutable and hashable. It is the **single** identity source, consumed by
`ParticipationContext.thesis_identity`, `TradeThesisSnapshot.identity`,
`PositionEvaluation.current_identity`, `reactor.exit_check` and `position.lifecycle`. The
previous stage's local `position.thesis_key()` was **deleted** — §4 allows one calculation,
and a second one is how two layers start disagreeing about the same candle.

`opportunity_of()` is untouched and still keeps the break index, because *"is this a new
opportunity?"* and *"is this the same thesis?"* are different questions and a re-break is a
new opportunity on the same thesis.

## 3. `exit_check` NOW USES THE CORRECT SEMANTICS (§5)

```python
identity = TH.identity_of(thesis)
if identity != open_identity:
    return True, (R_IDEA_REVERSED if thesis.idea != want else R_GENERATION_CHANGED)
if thesis.thesis_status == TH.STATUS_UNRESOLVED:
    return True, R_THESIS_UNRESOLVED
return False, R_THESIS_HOLDS
```

**§3 said prove this is the correct causal rule rather than asserting it.** The proof:
`LiveThesis` publishes exactly one thesis per candle — the current episode's. If that
thesis has a different identity from the one the position was opened on, the entry thesis
is no longer published, no longer evaluated, and can never be reported alive again by
anything in the stack. Continuing to hold is holding on a thesis the system has stopped
tracking, which is precisely the silent mismatch §6 requires to be zero.

**And §3's must-NOT-exit case is preserved.** Same structure, same generation, same
direction, different route or a new inner release → identity unchanged → `HOLD`. Measured:
176 teach identity groups re-break inside one identity and none of them exits.

**No new reason was invented (§19 of the prior stage).** `IDEA_REVERSED` is now the
*classification* of an identity change where the direction is what moved;
`GENERATION_CHANGED` covers the rest; `THESIS_UNRESOLVED` is unchanged. The field that used
to hold a generation integer is renamed `open_identity` throughout, because it no longer
holds a generation.

## 4. §6 RESIDUAL — the number that decides Part I

| | teach | validate |
|---|---|---|
| held candles | 1,679 | 736 |
| same-thesis candles | **1,679** | **736** |
| same-thesis continuation | 83 | 17 |
| true thesis changes | 181 | 72 |
| false thesis changes | **0** | **0** |
| **SILENT THESIS MISMATCH** | **0** *(was 261)* | **0** |
| false HOLD | **0** | **0** |
| false EXIT | **0** | **0** |
| automatic reversals | **0** | **0** |
| duplicate openings | **0** | **0** |
| candidate while positioned | **0** | **0** |

Exit reasons (teach): `IDEA_REVERSED` 148, `THESIS_UNRESOLVED` 60, `GENERATION_CHANGED` 33.

### Two FAILs that were my measurement, not the contract

The first run reported `false EXIT = 60` and `duplicate openings = 3`. I checked both
before touching production, and both were bugs in the audit script:

* **`false EXIT`** — all 60 were `THESIS_UNRESOLVED` exits, where the identity is unchanged
  but the thesis stopped being able to say which way it points (`FORMING_NEW_STRUCTURE` →
  idea `UNRESOLVED`). That is a legitimate validated exit reason. Re-measured with the
  correct definition — *identity unchanged **and** the thesis still resolved* — the count
  is **0**, and unresolved-thesis exits are now reported in their own row.
* **`duplicate openings`** — **0 within any block**. The three were the same
  `(structure, break candle, generation)` tuple recurring in *different* blocks, because
  candle indices restart per block and my audit accumulated across them.

## 5. IDENTITY TRACES (§7)

| | case | result |
|---|---|---|
| A | same structure + generation, repeated break | `L02/GEN1/UP == L02/GEN1/UP`, opportunity `('L02',507,1) → ('L02',513,1)` — **same thesis, new opportunity** |
| B | same generation integer, different structure | `C05/GEN1/UP != C08/GEN1/DOWN`, integer 1 on both sides — **the transition the integer cannot see** |
| C | generation change | `C08/GEN1/DOWN → C08/GEN2/DOWN` — thesis transition |
| D | same thesis + new inner release | `L01/GEN1/UP` unchanged, `INNER C04.low` released → `CONTINUATION`, `HOLD_LONG` |
| E | same thesis + micro development | identity unchanged → no false thesis change |
| F | true invalidation | entry thesis no longer published → `EXIT` |
| G | opposite thesis | `EXIT`, `FLAT`, no same-candle reverse |

---

# PART II — REACTIVE POSITION MANAGEMENT

## 6. THE MANAGEMENT VOCABULARY (§16)

Closed, and every member is the presence of an existing fact:

```
THESIS_STILL_VALID · SAME_THESIS_CONTINUATION · NEW_SAME_THESIS_RELEASE
MICRO_DEVELOPMENT · ROUTE_CHANGED · CONTRADICTION
THESIS_CHANGED · DIRECTION_CHANGED · THESIS_INVALIDATED
```

**No weights, no scores, no `weak`/`strong`** — asserted by a test that scans the vocabulary
itself. `ROUTE_CHANGED` covers what §16 lists as both *route changed* and *path changed*:
they are one observation — the release-relative route now names a different reference — and
two words for one fact is the redundancy these vocabularies keep refusing.

`MICRO_DEVELOPMENT` required one additive snapshot field, `micro_state_at_open`, so a micro
change is a *development* rather than a reconstruction from current state.

## 7. LIFECYCLE CENSUS (teach, 7,200 candles, 249 research positions)

| phase | n | share |
|---|---|---|
| `FLAT` | 5,031 | 69.9% |
| `HOLD` | 1,487 | 20.7% |
| `INVALIDATED` | 241 | 3.3% |
| `OPEN` | 249 | 3.5% |
| `CONTINUATION` | 192 | 2.7% |

Developments while positioned: `THESIS_INVALIDATED` 241 · `DIRECTION_CHANGED` 208 ·
`THESIS_CHANGED` 181 · `MICRO_DEVELOPMENT` 138 · `NEW_SAME_THESIS_RELEASE` 70.

Exits are **only ever** `IDEA_REVERSED` (148), `THESIS_UNRESOLVED` (60) or
`GENERATION_CHANGED` (33). No stop, no target, no timer — §17 and §27 hold.

## 8. TRACES A–H (§21)

All render in `poslife.out`. Trace H is the §15 proof, on real candles:

```
exit at c431 14:00   IDEA_REVERSED   position SHORT -> FLAT
  entry thesis was   C08/GEN1/DOWN
  market now         C08/GEN2/DOWN
  next open          c437  (6 candles later)  L01/GEN1/UP
  flat in between    True   (5 candles)

exit at c442 14:55   IDEA_REVERSED   position LONG -> FLAT
  entry thesis was   L01/GEN1/UP
  market now         C08/GEN1/DOWN          <- the integer could not see this
  next open          none within 8 candles

checked 241 exits. Every one went FLAT on its own candle; a new
opportunity is only ever taken on a LATER candle, and only from flat.
```

## 9. PERFORMANCE (§23)

1,800 candles. Microseconds.

| stage | median | p95 | max | candles/sec |
|---|---|---|---|---|
| thesis identity | 1.20 | 2.30 | 24.80 | 678,912 |
| position evaluation | 5.80 | 10.10 | 21.50 | 158,429 |
| lifecycle transition | 21.80 | 39.80 | 149.60 | 40,553 |
| render | 22.60 | 38.10 | 111.30 | 40,086 |

| stage / state | median | p95 | max |
|---|---|---|---|
| identity / flat · position active · generation change · multi-scale | 1.20 · 1.40 · 1.40 · 1.60 | 2.30 · 2.20 · 2.30 · 4.60 | 24.80 · 15.60 · 2.70 · 4.60 |
| evaluation / position active · continuation-heavy · generation change · multi-scale | 5.80 · 6.00 · 5.95 · 7.10 | 10.10 · 9.00 · 10.10 · 7.20 | 21.50 · 11.40 · 11.40 · 7.20 |
| transition / flat · position active | 20.70 · 25.30 | 38.10 · 41.10 | 149.60 · 104.20 |

The identity function — the thing added this stage and called on every candle — costs
**1.2 µs**, about 679,000 candles a second, against a five-minute candle.

## 10. DECISION GATE (§28)

| | teach + validate | |
|---|---|---|
| silent thesis mismatch | **0** | PASS |
| false HOLD | **0** | PASS |
| false EXIT | **0** | PASS |
| false thesis changes | **0** | PASS |
| automatic reversals | **0** | PASS |
| duplicate openings | **0** | PASS |
| candidate while positioned | **0** | PASS |
| prefix causality | identity, evaluation, lifecycle, action, position-after | PASS |
| determinism | two full runs identical | PASS |
| map-story gate | identical | PASS |
| full suite | green — 1,231 tests, run on the final tree | PASS |

```
THESIS IDENTITY INTEGRITY:      PASS
REACTIVE POSITION MANAGEMENT:   PASS
```

## 11. WHAT CHANGED IN PRODUCTION

| file | change |
|---|---|
| `src/livemap/thesis.py` | **+`ThesisIdentity`, +`identity_of()`** — the canonical answer |
| `src/livemap/participation.py` | `thesis_id` → `thesis_identity`; `open_generation` → `open_identity`; the position-open constraint compares identity |
| `src/livemap/reactor.py` | `exit_check` keys on identity; `open_identity` carried and rendered |
| `src/livemap/position.py` | snapshot carries `identity` + `micro_state_at_open`; evaluation compares identities; **local `thesis_key()` deleted**; §16 management vocabulary; §18 `THESIS RELATION` render |
| `tests/test_position.py` | 53 tests |
| `tests/test_reactor.py`, `tests/test_participation.py` | integer comparisons replaced by identity |

Nothing in `boxes/`, `frontier.py`, `micro.py`, `eye.py`, `postbreak.py`, `release.py` or
`route.py` was touched (§29). No missing fact needed inventing — the identity components
were all already published.

## 12. WHAT THIS STAGE DOES NOT CLAIM

1. **Execution is still not validated.** Every position in every number here was injected by
   `ResearchPositionInjector`, which must be handed specific opportunity ids and raises if
   constructed empty. Under the default contract, **0 positions open**.
2. **The lifecycle is memory, not edge.** Correct thesis attribution does not make a
   candidate profitable; the execution study found no rule that earned a contract.
3. **`bars held` is not a holding-period recommendation.**
4. **The identity rule is measured on this data**, teach and validate under one split
   digest. It is not a theorem.

## 13. STILL UNAVAILABLE

* a validated execution rule — six studies, none survived;
* micro-scale and inner-scale populations — 3 and 5 injected positions in teach;
* session state, cost, sizing, risk, options — out of scope by design.

---

**Stopped here.** No `ENTER_*`, no execution contract, no broker, no risk, no sizing, no
targets, no trailing stops, no holdout, no new setup, no entry hunt.
