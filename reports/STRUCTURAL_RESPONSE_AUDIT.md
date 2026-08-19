# Structural Response Audit

Status: NOT EXECUTED.

The perception causality gate now passes, so a raw structural-response ledger is the next
single milestone. This file defines that future study; it contains no response result.

## Proposed Row Identity

One row per immutable release record:

```text
bucket
block
release_id
release_candle_index
release_timestamp
scale
origin
broken_structure_id
broken_edge
direction
parent_id
thesis_identity_at_release
reference_path_fingerprint_at_release
```

## Proposed Observations

Record later structural facts without producing a setup label or score:

```text
first candle back inside the broken boundary
first accepted give-back
first mapped reference touched
first mapped reference released
new broad structure identity and candle
Micro create/confirm/break/collapse after release
bars each release remains held
session boundary encountered
end-of-observation reason
```

Every later fact must retain its source candle and must not rewrite the immutable release
row. TEACH and VALIDATE are reported separately. HOLDOUT remains excluded. LOCAL stays out
of the production schema until Gate D changes.

## Preconditions

- Consume `reports/fresh_world_causality.json` and require PASS.
- Preserve all simultaneous releases as separate rows linked by candle index.
- Do not rank, score, optimize, or create a shadow component.
