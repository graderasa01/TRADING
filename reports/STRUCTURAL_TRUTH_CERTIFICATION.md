# Structural Truth Certification

Previous reviewed SHA: `2e9958e7e0c274989d1cca4280373d25fd543ff0`

Corrected audit fingerprint: `7d17cb56c1d9afe3`

Corrected fresh-world fingerprint: `f9d1e3d3cafb5470`

## Reproduction

```bash
python tools/live_structure_truth.py --json reports/structural_truth_summary.json
python tools/fresh_world_causality.py --audit-json reports/structural_truth_summary.json --ordinary-per-bucket 8 --json reports/fresh_world_causality.json
```

## SUPERSEDED RESULT

The previous certification independently concatenated all TEACH sessions and all
VALIDATE sessions. Because the committed split is interleaved by month, that deleted
intervening VALIDATE/HOLDOUT time and made non-adjacent source sessions adjacent. Its 58
TEACH blocks, 10 VALIDATE blocks, 83 causal cuts, 24 both-current cases, 24 range
selections, and 0.118% combined prevalence are retained in Git history but are
superseded. Gates A and B were re-opened and are not inherited from that run.

## REPLAY INTEGRITY FIX

The research loader now starts from the chronological source-session index. Every source
day receives an ordinal, date, classification, and split bucket. A research episode is a
maximal run of replayable sessions whose source ordinals are consecutive and whose bucket
does not change. An excluded, abbreviated, failed-gap, or different-bucket source session
ends the episode.

Every 400-history/300-live block is built inside one episode. Runtime invariants reject a
non-consecutive ordinal set, an omitted source session, a split mismatch, or history/live
from different episodes. No calendar-gap threshold is used.

## VALIDATE EXPOSURE CAVEAT

PR #1's superseded certification already emitted case-level VALIDATE structural-event
metadata, including timestamps and candle-linked cuts. That exposure cannot be undone and
the committed split was not changed after seeing it.

All corrected artifacts enforce aggregate-only VALIDATE output. VALIDATE reports contain
counts by event/layer/classification, fingerprints, and pass/fail only. They contain no
VALIDATE timestamp, price, structure id, band, event trace, or session-linked candle
index. TEACH remains the only case-level debugging surface.

## HOLDOUT ACCESS SEMANTICS

`split.holdout()` was not called. `ReplayFeed.source_days()` builds the continuity index
from timestamps only. The price path receives an explicit TEACH/VALIDATE day whitelist,
and filtering happens before Decimal conversion and Candle construction. Therefore zero
HOLDOUT price sessions were converted into research Candles, aggregated, replayed,
inspected, rendered, measured, or passed to `MapSnapshot`, `Frontier`, the local audit,
the fresh-world harness, or `StructuralFrame`.

Underlying file decoders may encounter raw columns while applying the whitelist; this
report does not claim that data files containing HOLDOUT rows were never opened.

## CORRECTED AUDITED POPULATION

| Bucket | Source sessions assigned | Replayable sessions | Eligible episodes | Long enough | M5 candles | Blocks | History | Live | Sessions touched | Unused warm-up/tail |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TEACH | 548 | 543 | 12 | 10 | 40,725 | 52 | 20,800 | 15,600 | 489 | 4,325 |
| VALIDATE | 98 | 97 | 5 | 5 | 7,275 | 9 | 3,600 | 2,700 | 86 | 975 |

All 61 complete episode-local blocks were processed. Short episodes and incomplete tails
remain visible as unused population and are not described as audited.

## Corrected Structural Prevalence

| Bucket | Cluster only | Range only | Both | Neither | Both current | Cluster inside range | Range inside cluster | Selected range | Selected cluster |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TEACH | 2,626 | 14 | 19 | 7,426 | 16 | 19 | 0 | 16 | 0 |
| VALIDATE | 475 | 3 | 4 | 1,422 | 1 | 4 | 0 | 1 | 0 |

Both-current prevalence is 16/15,600 TEACH live candles (0.103%), 1/2,700 VALIDATE
live candles (0.037%), and 17/18,300 combined (0.093%). All 17 selected the enclosing
range. The scale-collapse case is systematic when present but remains rare.

| Bucket | Major births | Revisits | Accepted breaks | Micro create | Micro confirm | Micro break | Micro collapse | Releases | Simultaneous releases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TEACH | 277 | 730 | 777 | 303 | 70 | 47 | 252 | 1,227 | 72 |
| VALIDATE | 50 | 119 | 137 | 38 | 9 | 5 | 33 | 175 | 1 |

| Bucket | Local absent + Micro absent | Local absent + Micro found | Local found + Micro absent | Local found + Micro found |
|---|---:|---:|---:|---:|
| TEACH | 13,637 | 924 | 522 | 517 |
| VALIDATE | 2,448 | 107 | 81 | 64 |

LOCAL research candidates appeared on 1,039/15,600 TEACH live candles (6.66%) and
145/2,700 VALIDATE live candles (5.37%). LOCAL remains observational and unpublished.

## CORRECTED FRESH-WORLD RESULT

World A builds a fresh snapshot/frontier from one episode's fixed history, feeds only
through cut `k`, and captures the complete perception world. World B uses independent
objects, captures immediately at `k`, then continues normally. No finished frontier is
rewound.

For each event type and bucket the harness selects exact first, middle, and last
occurrences where available, or every occurrence when rare, then tests `k-1/k/k+1`.
Ordinary cuts remain spread over the full corrected chronology.

- Event types covered: 26/26 TEACH and 26/26 VALIDATE.
- Event occurrences sampled: 78 TEACH and 76 VALIDATE; 154 total.
- Total distinct causal cuts after neighborhood overlap: 287; 142 TEACH and 145 VALIDATE.
- Mismatch cuts/fields: 0/0 TEACH and 0/0 VALIDATE.
- Future leaks: 0. Identity drift: 0. Bugs: 0. Determinism: PASS.

At every selected cut World B retained the actual `Reading`, `MapState`, `EyeState`,
`ReleaseState`, `ReferencePath`, `LiveThesis`, and `StructuralFrame`. The same objects were
canonicalized before and after future candles. Mutable-reference leaks: 0. Intentionally
mutable `Frontier.current` was compared causally but was not subjected to this immutability
contract.

## Gates

- Gate A, causal perception: **YES** on the corrected source-contiguous universe; 287
  independent-world cuts matched.
- Gate B, BROAD / `Frontier.current`: **YES** for causal live perception. This is not a
  claim that retrospective batch geometry and live lifecycle are identical algorithms.
- Gate C, scale collapse: **CASE EXISTS YES; MATERIAL PRODUCTION CHANGE NO**. All 17
  both-current cases selected range, but combined prevalence is 0.093%.
- Gate D, LOCAL publication: **NO**. LOCAL remains research-only.
- Gate E, Micro subordination: **YES**. Create/confirm/break/collapse neighborhoods were
  causally stable without promoting Micro into map history.
- Gate F, StructuralFrame factual composition: **YES**. Accepted factual joins and plural
  release/approach semantics remain intact.
- Gate G, ready for structural-response study: **YES, READY; NOT EXECUTED**. Only the
  schema is finalized in `reports/STRUCTURAL_RESPONSE_AUDIT.md`.
- Gate H, shadow trader: **NOT REACHED**. No shadow component was built or run.

## Verification

Focused feed/episode/observer/causality/frame suites used an external base temp: **454
passed**. The focused regressions include split compression barriers, observer exclusion,
aggregate-only VALIDATE serialization, multi-occurrence sampling, retained-object
immutability, and corrected fresh-world equality.

Full repository suite used an external base temp: **1,371 passed**.

No `.github/workflows` directory exists in this repository state. These are local pytest
results; no CI verification is claimed.

## Evidence Balance

Strongest positive evidence: all 287 event-targeted and chronology-spread cuts matched
across the complete perception world, while the same seven retained trader-facing object
types stayed immutable after future candles.

Strongest counter-evidence: range selection remained unanimous in all 17 both-current
cases, and the bounded TEACH prefix comparison still contains one `LIVE_SCALE_COLLAPSE`.
The corrected prevalence is only 0.093%, so perception integrity does not by itself justify
a production architecture change.

## Next Single Milestone

Reviewer approval of the finalized raw structural-response ledger schema, followed by one
TEACH/aggregate-only-VALIDATE response study. Do not publish LOCAL and do not build or run
a shadow trader before that review.
