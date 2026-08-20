# Local Scale Audit

Reproduction:

```bash
python tools/live_structure_truth.py --json reports/structural_truth_summary.json
```

LOCAL is a research observation only. It reuses the existing structure machinery beneath
the active broad structure and does not mutate the snapshot, frontier history, known-node
pool, or logs. It is not published by production code.

## Population

The audit observed all complete blocks: 17,400 TEACH live candles and 3,000 VALIDATE live
candles. HOLDOUT was not loaded.

## LOCAL / Micro Matrix

| Bucket | LOCAL absent / Micro absent | LOCAL absent / Micro found | LOCAL found / Micro absent | LOCAL found / Micro found |
|---|---:|---:|---:|---:|
| TEACH | 15,342 | 874 | 662 | 522 |
| VALIDATE | 2,772 | 89 | 58 | 81 |
| Total | 18,114 | 963 | 720 | 603 |

LOCAL appeared on 1,323/20,400 observed live candles (6.49%). LOCAL and Micro disagreed on
presence for 1,683 candles. Among LOCAL-found candles, geometry relation to Micro was:
423 same, 176 overlapping, 4 different, and 720 with no Micro geometry.

Micro lifecycle totals were 363 creates, 65 confirms, 38 breaks, and 323 collapses. Those
are production Micro events; LOCAL still has no independently certified birth, continuity,
identity, or retirement lifecycle.

## Causal Coverage

Fresh-world cuts included LOCAL appearance and disappearance in both TEACH and VALIDATE,
with `k-1/k/k+1` around each event. All LOCAL research values matched between independent
worlds. This certifies causal observation, not production ownership.

## Conclusion

LOCAL contains information not reducible to Micro presence, but Gate D remains NO. A
candidate that is causally observable is not automatically a publishable market object.
Production publication must wait for a measured lifecycle and the response-ledger study.
