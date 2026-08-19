# Structural Truth Certification

Start SHA: `4472a1d9c6fc917902dfc62dc44dc41e192ace8d`

Reproduction:

```bash
python tools/live_structure_truth.py --max-blocks 1 --json reports/structural_truth_summary.json
python -m pytest tests/test_live_structure_truth_audit.py tests/test_frame.py tests/test_release.py tests/test_eye.py tests/test_reactor.py --basetemp C:\Users\hp\Desktop\traderpar\.pytest-tmp
```

This reuses the local research-only audit in `tools/live_structure_truth.py`. It does not
import execution, broker, risk, participation, or trader surfaces.

## Result

The focused causal/observer suite passed: `220 passed`.

The smoke audit covered 1 TEACH block and 1 VALIDATE block:

- TEACH population: 543 sessions, 40,725 M5 candles.
- VALIDATE population: 97 sessions, 7,275 M5 candles.
- Local scan mutates nothing and uses existing detector/currency/containment rules.
- Simultaneous cluster/range was observed and kept as a scale fact, not a ranking fact.

## Gate Answers

- Gate A: INSUFFICIENT EVIDENCE. Focused tests prove determinism and observer immutability; the requested fresh independent-world comparison is not fully implemented yet.
- Gate B: YES for current tested behavior. `Frontier.current` remains the broad live representation and Micro remains subordinate.
- Gate C: YES, evidence of scale loss exists. The smoke audit observed simultaneous current cluster/range and range selection.
- Gate D: INSUFFICIENT EVIDENCE. LOCAL is useful in the smoke audit, but remains research-only and unpublished.
- Gate E: YES in current tests. Micro is carried on readings and cannot leak into the major map.
- Gate F: YES. `StructuralFrame` joins BROAD, optional LOCAL, MICRO, RELEASE, ROUTE, and INVALIDATION without creating a second map.
- Gate G: INSUFFICIENT EVIDENCE. `StructuralFrame` is ready as a perception object, but shadow-trader publication should wait for the stronger fresh-prefix certification.
- Gate H: INSUFFICIENT EVIDENCE. Shadow phase was deliberately not reached.

## Strongest Finding

The existing architecture can now be joined into one causal read-only frame without
importing detector or trader surfaces.

## Strongest Risk

The strong two-world causality audit described in the brief is still incomplete. Current
tests prove prefix equality over existing observers, not fully independent process replay
for every fact.
