# Structural Response Audit

Status: SCHEMA ONLY; NOT EXECUTED.

The corrected source-contiguous perception causality gate passes, so a raw
structural-response ledger is the next single milestone after reviewer approval. This
file defines that future study; it contains no response row or response result.

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
row. Internally, each row also retains `source_episode_id` and
`source_session_ordinal`; no observation window may cross an episode boundary. TEACH may
retain diagnostic rows. VALIDATE output is aggregate-only by event/outcome class and must
not expose timestamps, prices, ids, bands, or session-linked indices. HOLDOUT price data
remains excluded. LOCAL stays out of the production schema until Gate D changes.

## Preconditions

- Consume `reports/fresh_world_causality.json`, require PASS, and match source audit
  fingerprint `7d17cb56c1d9afe3`.
- Require source-contiguous episodes; never reconstruct a bucket-compressed timeline.
- Preserve all simultaneous releases as separate rows linked by candle index.
- Do not rank, score, optimize, or create a shadow component.
- Do not execute until the reviewer approves the corrected certification.
