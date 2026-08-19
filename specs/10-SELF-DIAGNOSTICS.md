# 10 — SELF-DIAGNOSTICS

> A silent engine and a healthy engine look identical from the outside.
> This spec exists so they stop looking identical.

---

## 1. Why this exists

The v1 engine was broken in four independent ways at once (`prototype/FINDINGS.md`):

- no TURN or ANCHOR level could ever reach Grade A, so no setup could ever trigger
- levels died within three minutes of price arriving, killing the day's best level
  two minutes before its own sweep
- the HTF-tail guard silently prevented Setup B from ever being *evaluated*
- the R ceiling rejected the setup's own best expression

**It never complained about any of it.** Every candle it returned a clean, confident
`NO_TRADE`, exactly as the constitution requires. The daily report would have shown
zero trades and a tidy rejection histogram, and the honest-sounding conclusion would
have been *"quiet market, the system is being disciplined."*

That conclusion would have been wrong for four months, and nothing in specs 01–09 could
have told you.

**A system whose correct output is usually "nothing" cannot distinguish "nothing to do"
from "unable to do anything."** That is the failure mode this spec addresses, and on a
system built around restraint it is the most dangerous one there is.

This is also what "smart" means here. Not more setups, not cleverer entries — the
overfitting warning in `CLAUDE.md` §8 stands. Smart means **the engine knows when it is
not working.**

---

## 2. The health monitor

Runs at end of session, writes to the daily report, and maintains a rolling window
across sessions in `state/health.json`.

```python
@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: Literal["ok", "warn", "fail"]
    observed: Any
    expected: str
    meaning: str          # what it means in plain language if this is failing
```

Every check reports even when green. A dashboard that only shows problems teaches you
nothing about what normal looks like.

---

## 3. The checks

### 3.1 Pipeline liveness — did each stage do anything at all?

| Check | Fails when | What it means |
|---|---|---|
| `levels_born` | < 5 levels created in a session | Detectors are not firing. Check ATR, check swing confirmation |
| `grade_a_exists` | **zero Grade A levels all session** | **Nothing is tradeable. This is Bug 1.** No setup can trigger, ever |
| `alert_reached` | ALERT is 0% of non-BLOCKED candles | Either no Grade A levels, or `alert_distance` is too tight |
| `setups_detected` | zero setups **evaluated** in 5 sessions | Detectors unreachable. **Count detection, not trades** |
| `each_setup_alive` | any of A/B/C never fires in 20 sessions | That setup is structurally dead — Bug 3 was exactly this |
| `launch_levels` | < 1 LAUNCH level per session on average | The "highest-value 1m level" detector is not working |

`grade_a_exists` and `setups_detected` are **fail**, not warn. If either trips, the
engine writes a loud banner at the top of the daily report:

```
⚠ ENGINE MAY BE BROKEN — zero setups evaluated in 5 sessions.
  This is not a quiet market. Nothing reached the detector.
  Do not interpret today's zero trades as discipline.
```

### 3.2 Distribution sanity — is any single thing dominating?

| Check | Fails when | What it means |
|---|---|---|
| `mode_split` | ALERT > 60% of non-BLOCKED | Level book too crowded — check the 8-cap and grading |
| `single_gate_dominance` | one gate is > 70% of all rejections | That gate is the system. Is it doing real work, or is it a bug? |
| `grade_distribution` | > 90% of levels are one grade | Grading is not discriminating — likely an undefined input, as in Bug 1 |
| `level_kind_balance` | one `kind` is > 60% of the book | Bug 5: BREAK axes filled 6 of 8 slots |
| `break_rate` | > 15 axis-creating breaks per session | Axis threshold too loose |

### 3.3 Arithmetic reachability — can a gate ever pass?

The most valuable class of check, and the one that would have caught three of the four
bugs. Run these as **startup assertions**, before a single candle is processed.

```python
def assert_gates_are_reachable(params) -> list[str]:
    """
    For each gate, construct the most favourable input the rules permit and
    verify the gate can pass. A gate that cannot pass under ANY admissible
    input is a bug in the config, not a strict filter.
    """
```

Required assertions:

| Assertion | Catches |
|---|---|
| Some level kind can score ≥ `grade_a_min_score` | **Bug 1** |
| An ANCHOR can reach Grade A | **Bug 1 + the spec 06 contradiction** — spec 06 makes Setup B mandatory at anchors; if anchors cannot be Grade A, Setup B can never fire there |
| A qualifying Setup B candle exists with `r_min ≤ R ≤ r_max` at ATR 15, 25 and 40 | **Bug 4** |
| `r_min < r_max` at every ATR in `[atr_min, atr_max]` | inverted bounds |
| `revival_distance < dormancy_distance` | levels flapping awake and asleep |
| `min_space_ratio × r_max` is achievable given obstacle density | the round-number problem from REVIEW-v2 §5 |
| Every setup has at least one time window where its guards permit it | **Bug 3** |
| `touch_separation > 0` whenever `max_touches` is finite | **Bug 2** |

The last two deserve emphasis. Bug 3 was two individually correct rules that combined to
make a setup unreachable. **Reachability is a property of the whole rule set, not of any
one rule**, which is why no amount of reading the specs found it and one dry run did.

### 3.4 Model drift — are the assumptions still true?

| Check | Fails when | What it means |
|---|---|---|
| `slippage_drift` | observed > 1.5 × modelled over 20 fills | The cost model is stale; every P&L number downstream is wrong |
| `r_realised_vs_planned` | median loss > 1.2R over 10 losses | `r_model_broken` (spec 05 §4b) — the delta model is wrong |
| `delta_fallback_rate` | > 20% of signals use the 0.5 fallback | Delta measurement is failing; sizing is guesswork |
| `reconciliation_rate` | > 2% candle mismatch | The candle builder is drifting from official data |
| `atr_regime_shift` | session ATR outside the trailing 60-day 5–95 percentile | Not a fault — tag the day so the review can cut by it |

---

## 4. The startup banner

Print before the first candle, every session. If any reachability assertion fails,
**refuse to start.**

```
BANK NIFTY CO-PILOT          MODE: PAPER
config digest    a91f3c22        risk/trade  ₹5,000
costs verified   2026-08-04      events      2026-08-10  (1 day old)

REACHABILITY      12/12 assertions pass
HEALTH (last 5 sessions)
  levels born        avg 41       ok
  Grade A levels     avg  6       ok
  setups detected     11 total    ok
  A / B / C fired      4 / 5 / 2  ok
  ALERT share         31% of non-BLOCKED   ok
  top gate           space_insufficient 38%   ok
```

Five sessions of history in six lines. If any line is empty or zero, that is visible
immediately, on every start, without anyone remembering to look.

---

## 5. What this must NOT become

- ❌ **Not auto-tuning.** The monitor reports and refuses to start. It never adjusts a
  threshold. A system that widens its own gates because it is not trading enough will
  find plenty of trades, and all of them will be bad.
- ❌ **Not a trade filter.** No health metric may enter a trading decision. Health is
  about the engine; gates are about the market.
- ❌ **Not a reason to relax a gate.** If `space_insufficient` is 70% of rejections, the
  finding is *"this gate is doing all the work — is it real?"*, and the answer comes
  from the counterfactual study in spec 09, not from lowering the ratio.

The monitor answers exactly one question: **is the engine capable of doing its job right
now?** Whether it *should* trade is the rest of the system's business.

---

## 6. Tests that must pass

| Test | Expectation |
|---|---|
| `test_reachability_catches_grade_a_bug` | Set `departure_speed = 0` for TURN/ANCHOR → the "some kind can reach Grade A" assertion **fails at startup** |
| `test_reachability_catches_setup_b_r_bug` | Flat `r_max = 35` with ATR 40 → the Setup B reachability assertion fails |
| `test_reachability_catches_guard_conflict` | Setup B not exempt from the HTF tail, with `b_reclaim_max_candles: 2` → the "every setup has a permitting window" assertion fails |
| `test_reachability_catches_touch_bug` | `touch_separation = 0` with finite `max_touches` → fails |
| `test_zero_detection_raises_banner` | 5 sessions, no setup evaluated → the loud banner appears in the report |
| `test_health_never_changes_a_param` | Static: no health module writes to config |
| `test_health_not_imported_by_setups` | Static: `setups/`, `risk/`, `exits/` do not import health |
| `test_startup_refuses_on_failed_assertion` | Any reachability failure → the engine does not start |
| `test_all_checks_report_when_green` | A healthy session still prints all check lines |

---

## 7. Build order

Build this in **P2**, immediately after the guards — not at the end.

Its entire value is catching mistakes *while* the rest is being built. Written at P7 it
would document four bugs that had already been shipped, tested against, and reasoned
around for months.

The reachability assertions in §3.3 cost about an hour. They would have caught three of
the four bugs before a single candle was processed.
