# Structural Response Audit

Status: not promoted beyond existing evidence ledgers.

The current turn did not add a scored response model, threshold, probability, or detector
modification. Existing release, eye, and frame tests verify that later candles do not
rewrite release records, confirmed frame facts, or observer outputs.

Reproduction:

```bash
python -m pytest tests/test_release.py tests/test_eye.py tests/test_frame.py --basetemp C:\Users\hp\Desktop\traderpar\.pytest-tmp
```

Next required measurement is a raw response ledger for causally frozen cluster/range/local
/micro boundaries: first future touch, defended touches, accepted break, bars to break,
re-entry, excursion, adverse excursion, opposite-edge reach, revisit, and spend/traverse
where applicable. No PnL or score should be added to that ledger.
