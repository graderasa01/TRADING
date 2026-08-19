# Structural Truth Certification

Previous reviewed SHA: `283039e7b8f03bbe5178668c8ebe91b9f7ebdc91`

## Reproduction

```bash
python tools/live_structure_truth.py --json reports/structural_truth_summary.json
python tools/fresh_world_causality.py --audit-json reports/structural_truth_summary.json --ordinary-per-bucket 8 --json reports/fresh_world_causality.json
```

Both tools load only TEACH and VALIDATE. HOLDOUT was not loaded.

## Population

Available and audited population are different machine fields. The available count can no
longer be rendered as the audited count without explicitly reading the wrong key.

| Bucket | Available sessions | Available M5 candles | Blocks processed | History consumed | Live observed | Sessions touched | First / last timestamp |
|---|---:|---:|---:|---:|---:|---:|---|
| TEACH | 543 | 40,725 | 58 | 23,200 | 17,400 | 542 | 2023-08-01 09:20 / 2026-08-10 11:20 |
| VALIDATE | 97 | 7,275 | 10 | 4,000 | 3,000 | 94 | 2024-01-01 09:20 / 2026-03-24 11:20 |

Every complete 400-history/300-live block was processed. The unconsumed tail was not
described as audited.

## Structural Prevalence

| Bucket | Cluster only | Range only | Both detected | Neither | Both current | Cluster inside range | Range inside cluster | Partial | Disjoint | Selected cluster | Selected range |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TEACH | 3,009 | 23 | 25 | 8,433 | 22 | 25 | 0 | 0 | 0 | 0 | 22 |
| VALIDATE | 483 | 0 | 2 | 1,577 | 2 | 2 | 0 | 0 | 0 | 0 | 2 |

The conditional selection rule is systematic in this sample: all 24 both-current cases
selected the enclosing range. The cases are rare: 22/17,400 TEACH live candles (0.126%)
and 2/3,000 VALIDATE live candles (0.067%). This proves the case exists; it does not prove
that a production redesign is material.

| Bucket | Major births | Revisits | Accepted breaks | Micro create | Micro confirm | Micro break | Micro collapse | Releases | Simultaneous releases |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TEACH | 320 | 808 | 880 | 322 | 58 | 35 | 285 | 1,348 | 71 |
| VALIDATE | 55 | 136 | 144 | 41 | 7 | 3 | 38 | 194 | 0 |

## Fresh-World Method

For each cut, World A built a fresh `MapSnapshot` from the fixed historical window, built a
fresh `Frontier`, fed only through the cut, and serialized the complete perception value.
World B started from another fresh snapshot/frontier, fed normally, serialized the value
immediately at the cut, then continued. World B was never reconstructed from a finished
frontier with `upto=k`.

The canonical value includes frozen and causally available structures, emitted cluster and
range proposals, `Reading`, `Frontier.current`, `left`, `candidate`, `MicroView`, `MapState`,
`EyeState`, `ReleaseState`, all simultaneous releases, `ReferencePath`, `LiveThesis`, thesis
identity and invalidation, LOCAL research observations, and `StructuralFrame`.

## Causal Cuts

- Total: 83; TEACH: 40; VALIDATE: 43.
- Ordinary deterministic spread: 16 cuts.
- Six cuts each: major birth, forming-to-confirmed, edge approach, break attempt, accepted
  major break, re-entry, revisit, leaving, new major structure, micro create/confirm/break/
  collapse, LOCAL appearance/disappearance, simultaneous cluster/range, release create/
  held/given-back, reference identity change, route/watch change, thesis birth, generation
  change, thesis invalidation/reversal, and session start.
- Simultaneous release: 3 TEACH cuts. VALIDATE had no simultaneous release in 3,000 observed
  live candles, so no synthetic VALIDATE case was invented.

Every event cut includes `k-1`, `k`, and `k+1` where the block boundary permits it.

## Causality Result

| Result | TEACH | VALIDATE | Total |
|---|---:|---:|---:|
| Mismatch cuts | 0 | 0 | 0 |
| Mismatch fields | 0 | 0 | 0 |
| Future leaks | 0 | 0 | 0 |
| Mutable-reference leaks | 0 | 0 | 0 |
| Identity drift | 0 | 0 | 0 |
| Bugs | 0 | 0 | 0 |

`PRESENTATION_ONLY` and `EXPECTED_LIFECYCLE_DIFFERENCE` were also zero. Determinism: PASS.
Audit fingerprint: `2ac55a9f4cddeede`. Fresh-world fingerprint: `5607fc3e34ef177f`.

The auxiliary batch-snapshot/live-frontier geometry comparison remains separate from this
test. In its bounded simultaneous sample it found one `LIVE_FRONTIER_ONLY` TEACH case. That
is cross-algorithm counter-evidence, not a future leak, and remains visible in the JSON.

## Verification

Focused observer/guard suites:

```bash
python -m pytest tests/test_live_structure_truth_audit.py tests/test_fresh_world_causality.py tests/test_frame.py tests/test_frontier.py tests/test_micro.py tests/test_livemap.py tests/test_livemap_quarantine.py tests/test_eye.py tests/test_release.py tests/test_reference.py tests/test_route.py tests/test_participation.py tests/test_reactor.py tests/test_static_prohibitions.py tests/test_check_no_secrets.py --basetemp C:\Users\hp\Desktop\traderpar\.pytest-focused-certification
```

Result: `416 passed` in 298.42s.

Full repository suite:

```bash
python -m pytest --basetemp C:\Users\hp\Desktop\traderpar\.pytest-full-certification
```

Result: `1362 passed` in 1006.36s. Pytest emitted one known cache-path warning; tests and
their external base temp completed successfully.

## Gates

- Gate A: YES. Cluster/range/live emissions were equal in 83 independent fresh-world cuts.
- Gate B: YES for causal BROAD live perception. `Frontier.current` was stable in every cut;
  this does not claim equivalence to every retrospective batch-snapshot geometry.
- Gate C: CASE EXISTS: YES. PRODUCTION CHANGE JUSTIFIED: NO. Selection was 24/24 range when
  both were current, but both-current prevalence was 0.118% of audited live candles.
- Gate D: NO. LOCAL remains research-only; no production lifecycle identity is certified.
- Gate E: YES. Micro stayed subordinate and was causally stable through create, confirm,
  break, and collapse cuts.
- Gate F: YES. `StructuralFrame` now joins facts without directional local semantics,
  scalar release selection, or approached-side priority.
- Gate G: NOT YET. Causal perception is certified, but the raw structural-response ledger
  remains the next milestone before any shadow work.
- Gate H: NOT REACHED. No shadow component was built or run.

## Evidence Balance

Strongest positive evidence: 83 independent event-targeted cuts matched across the complete
perception world with no blocking mismatch.

Strongest counter-evidence: range selection was unanimous when both scales were current,
and one auxiliary prefix comparison produced live-frontier-only geometry. The measured
prevalence is too small to justify changing production before response behavior is measured.

## Next Milestone

Specify and execute the raw structural-response ledger on TEACH and VALIDATE only. Do not
publish LOCAL and do not begin a shadow component until that ledger is reviewed.
