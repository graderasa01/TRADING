# Local Scale Audit

Reproduction:

```bash
python tools/live_structure_truth.py --max-blocks 1 --json reports/structural_truth_summary.json
```

The LOCAL scan is research-only. It reuses `adaptive.choose`, existing windows, existing
tolerance, existing currency checks, and containment under the active `Frontier.current`.
It does not mutate `Frontier._known`, `MapSnapshot`, live logs, historical map, or finalised
history.

## Smoke Matrix

From `reports/structural_truth_summary.json`:

- LOCAL yes / MICRO yes: 25
- LOCAL yes / MICRO no: 16
- LOCAL no / MICRO yes: 29
- LOCAL no / MICRO no: 530

LOCAL was found on 41 candles. Production Micro was confirmed on 14 candles. Relations
between LOCAL and Micro among LOCAL examples:

- same: 20
- overlapping: 5
- absent: 16

## Examples

- TEACH 2023-08-08 14:10: LOCAL 44,954.712-44,997.742 while Micro absent.
- TEACH 2023-08-09 13:45: LOCAL 44,605.9345-44,656.765 same as `L02.m1`.
- TEACH 2023-08-10 13:20: LOCAL 44,619.53775-44,662.17175 same as `L02.m1`.

## Conclusion

LOCAL appears to carry information not always present in Micro, and Micro can be present
when LOCAL is absent. It should remain research-only until lifecycle start/keep/end rules
are proven across a broader audit.
