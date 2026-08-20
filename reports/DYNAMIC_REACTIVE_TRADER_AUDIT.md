What this trader currently knows, what it can do, and what it still cannot do.

# Dynamic Reactive Trader Audit

Status: EXECUTED. Research-only causal shadow participation; no broker or live execution.

Fingerprint: `bf497495e394bb87`

## PLAIN-LANGUAGE RESULT

The shadow machine can locate price in Broad geometry, maintain explicit structural hypotheses, wait when a valid premise has no usable structural room, join some moves, hold while the premise remains intact, and exit on completion or first causal falsification. It does not know future movement, does not infer a trade from an edge touch or Micro event, and does not establish readiness for execution research.

## ARCHITECTURE

- `MarketTruth`: immutable facts copied from StructuralFrame; it never chooses an action.
- `MovementState`: origin, landmarks, causal progress, remaining geometry, Micro and release context.
- Hypothesis Brain: zero or more stable, explicit lifecycle records without selection weights.
- `ParticipationState`: separate answer for whether structural room remains available.
- `ShadowPositionState`: FLAT/SHADOW_LONG/SHADOW_SHORT research state with factual invalidation only.

## LIFECYCLE TRACE

```text
NO_HYPOTHESIS
-> OBSERVING_LOWER_AREA
-> ROTATION_HYPOTHESIS_ACTIVE
-> VALID_BUT_WAIT
-> SHADOW_LONG
-> HOLD
-> MIDPOINT_REACHED
-> HOLD
-> APPROACHING_UPPER_REFERENCE
-> HYPOTHESIS_COMPLETED
-> EXIT
-> FLAT
```

```text
ROTATION_ACTIVE
-> SHADOW_LONG
-> STRUCTURAL_FAILURE_BELOW
-> FALSIFIED
-> EXIT
-> FLAT
-> no automatic short
```

## HYPOTHESIS POPULATION

- TEACH: created 5515 | families {"FAILED_DOWN_RELEASE_RETURN_INSIDE": 197, "FAILED_UP_RELEASE_RETURN_INSIDE": 232, "OUTSIDE_CONTINUATION_DOWN": 895, "OUTSIDE_CONTINUATION_UP": 921, "ROTATION_FROM_LOWER_AREA": 1622, "ROTATION_FROM_UPPER_AREA": 1648} | ever reached {"ACTIVE": 2775, "COMPLETED": 2966, "EXPIRED": 4, "FALSIFIED": 2545, "OBSERVING": 3699, "STRESSED": 1168} | final states {"COMPLETED": 2966, "EXPIRED": 4, "FALSIFIED": 2545} | lifetime n 5515 | min 2.0 | median 3.0 | mean 5.240617 | max 105.0.
- VALIDATE aggregate: created 746 | families {"FAILED_DOWN_RELEASE_RETURN_INSIDE": 38, "FAILED_UP_RELEASE_RETURN_INSIDE": 33, "OUTSIDE_CONTINUATION_DOWN": 128, "OUTSIDE_CONTINUATION_UP": 106, "ROTATION_FROM_LOWER_AREA": 217, "ROTATION_FROM_UPPER_AREA": 224} | ever reached {"ACTIVE": 356, "COMPLETED": 400, "EXPIRED": 4, "FALSIFIED": 342, "OBSERVING": 512, "STRESSED": 146} | final states {"COMPLETED": 400, "EXPIRED": 4, "FALSIFIED": 342} | lifetime n 746 | min 2.0 | median 3.0 | mean 5.705094 | max 60.0.

## SHADOW PARTICIPATION POPULATION

- TEACH: entries 1190 | long 578 | short 612 | holds 5956 | exits 1190 | waits 13429 | hypotheses without participation 4325.
- TEACH entries by family: `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": 0, "FAILED_UP_RELEASE_RETURN_INSIDE": 0, "OUTSIDE_CONTINUATION_DOWN": 329, "OUTSIDE_CONTINUATION_UP": 289, "ROTATION_FROM_LOWER_AREA": 289, "ROTATION_FROM_UPPER_AREA": 283}`.
- TEACH exit reasons: `{"ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE": 113, "ACCEPTED_STRUCTURAL_FAILURE": 284, "CONTROLLING_STRUCTURE_CHANGED": 38, "MAPPED_REFERENCE_REACHED": 272, "NEW_CONTROLLING_STRUCTURE_ESTABLISHED": 233, "SOURCE_EPISODE_BOUNDARY": 1, "STRUCTURAL_OBJECTIVE_REACHED": 249}`.
- VALIDATE aggregate: entries 143 | long 75 | short 68 | holds 934 | exits 143 | waits 2047 | hypotheses without participation 603.
- VALIDATE aggregate entries by family: `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": 0, "FAILED_UP_RELEASE_RETURN_INSIDE": 0, "OUTSIDE_CONTINUATION_DOWN": 40, "OUTSIDE_CONTINUATION_UP": 48, "ROTATION_FROM_LOWER_AREA": 27, "ROTATION_FROM_UPPER_AREA": 28}`.
- VALIDATE aggregate exit reasons: `{"ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE": 20, "ACCEPTED_STRUCTURAL_FAILURE": 33, "CONTROLLING_STRUCTURE_CHANGED": 3, "MAPPED_REFERENCE_REACHED": 35, "NEW_CONTROLLING_STRUCTURE_ESTABLISHED": 33, "STRUCTURAL_OBJECTIVE_REACHED": 19}`.

## MOVEMENT PARTICIPATION

- TEACH: entry after hypothesis birth n 1190 | min 1.0 | median 1.0 | mean 1.944538 | max 26.0; hypothesis birth from movement origin n 1190 | min 0.0 | median 0.0 | mean 0.889076 | max 54.0; room at entry n 1190 | min 8.447 | median 58.031 | mean 89.948993 | max 1157.742; movement consumed n 1190 | min 0.0 | median 24.869 | mean 44.301784 | max 573.56.
- TEACH: invalidation distance at entry n 1190 | min 0.0075 | median 24.869 | mean 44.312576 | max 573.56; by family `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "FAILED_UP_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "OUTSIDE_CONTINUATION_DOWN": {"count": 329, "max": 451.584, "mean": 68.419521, "median": 52.49225, "min": 7.201}, "OUTSIDE_CONTINUATION_UP": {"count": 289, "max": 573.56, "mean": 76.913666, "median": 52.7185, "min": 8.92425}, "ROTATION_FROM_LOWER_AREA": {"count": 289, "max": 88.148, "mean": 14.338775, "median": 12.80875, "min": 0.0075}, "ROTATION_FROM_UPPER_AREA": {"count": 283, "max": 55.345, "mean": 13.604198, "median": 11.59475, "min": 0.045}}`.
- TEACH: 856/1190 closed shadow positions reached at least one structural landmark; path fraction n 1190 | min 0.0 | median 0.52012 | mean 0.49897 | max 1.0.
- VALIDATE aggregate: entry after hypothesis birth n 143 | min 1.0 | median 1.0 | mean 1.902098 | max 7.0; hypothesis birth from movement origin n 143 | min 0.0 | median 0.0 | mean 0.797203 | max 27.0; room at entry n 143 | min 13.45625 | median 61.172 | mean 147.060559 | max 1739.11; movement consumed n 143 | min 0.287 | median 37.393 | mean 79.510037 | max 1323.133.
- VALIDATE aggregate: invalidation distance at entry n 143 | min 0.287 | median 37.393 | mean 79.510037 | max 1323.133; by family `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "FAILED_UP_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "OUTSIDE_CONTINUATION_DOWN": {"count": 40, "max": 1323.133, "mean": 100.629488, "median": 58.40175, "min": 11.63}, "OUTSIDE_CONTINUATION_UP": {"count": 48, "max": 1073.72175, "mean": 133.118547, "median": 71.1635, "min": 10.5575}, "ROTATION_FROM_LOWER_AREA": {"count": 27, "max": 48.25, "mean": 16.416944, "median": 11.586, "min": 0.287}, "ROTATION_FROM_UPPER_AREA": {"count": 28, "max": 64.34, "mean": 18.278857, "median": 12.5645, "min": 0.814}}`.
- VALIDATE aggregate: 94/143 closed shadow positions reached at least one structural landmark; path fraction n 143 | min 0.0 | median 0.40044 | mean 0.466283 | max 1.0.

## INVALIDATION AND EXIT

- TEACH: falsified positions 435 | first-causal-candle exits 435 | lag violations 0 | entry-to-falsification distance n 435 | min 3.05 | median 52.55 | mean 69.623218 | max 570.05.
- TEACH falsified-position lifetime by family: `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "FAILED_UP_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "OUTSIDE_CONTINUATION_DOWN": {"count": 57, "max": 25.0, "mean": 6.298246, "median": 5.0, "min": 2.0}, "OUTSIDE_CONTINUATION_UP": {"count": 56, "max": 15.0, "mean": 5.875, "median": 5.0, "min": 2.0}, "ROTATION_FROM_LOWER_AREA": {"count": 164, "max": 39.0, "mean": 6.506098, "median": 5.0, "min": 3.0}, "ROTATION_FROM_UPPER_AREA": {"count": 158, "max": 57.0, "mean": 6.924051, "median": 4.0, "min": 3.0}}`.
- VALIDATE aggregate: falsified positions 56 | first-causal-candle exits 56 | lag violations 0 | entry-to-falsification distance n 56 | min 10.7 | median 58.975 | mean 89.483929 | max 703.1.
- VALIDATE aggregate falsified-position lifetime by family: `{"FAILED_DOWN_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "FAILED_UP_RELEASE_RETURN_INSIDE": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "OUTSIDE_CONTINUATION_DOWN": {"count": 9, "max": 12.0, "mean": 6.333333, "median": 6.0, "min": 3.0}, "OUTSIDE_CONTINUATION_UP": {"count": 11, "max": 46.0, "mean": 10.454545, "median": 6.0, "min": 3.0}, "ROTATION_FROM_LOWER_AREA": {"count": 19, "max": 17.0, "mean": 7.947368, "median": 5.0, "min": 3.0}, "ROTATION_FROM_UPPER_AREA": {"count": 17, "max": 8.0, "mean": 4.588235, "median": 4.0, "min": 3.0}}`.

## FALSE SWITCH AND REVERSAL

- TEACH: `{"exit_followed_by_no_opposite_hypothesis": 687, "exit_with_opposite_hypothesis_already_visible": 650, "independent_reverse_entries_on_later_candle": 561, "raw_position_side_flips": 561, "same_candle_reverse_entries": 0}`.
- VALIDATE aggregate: `{"exit_followed_by_no_opposite_hypothesis": 83, "exit_with_opposite_hypothesis_already_visible": 71, "independent_reverse_entries_on_later_candle": 83, "raw_position_side_flips": 83, "same_candle_reverse_entries": 0}`.

## COUNTER-EVIDENCE

- TEACH: valid-but-wait candles 5816 | conflict waits 0 | no-active-hypothesis candles 14485 | entries after midpoint 0 | entries at reached reference 0 | entries on any release candle 3 | entries on hypothesis birth candle 0 | continuation entries on acceptance candle 0 | largest family share 0.298821.
- TEACH source-episode spread: `{"entries_per_source_episode": {"count": 11, "max": 249.0, "mean": 108.181818, "median": 80.0, "min": 8.0}, "landmark_positions_per_source_episode": {"count": 11, "max": 186.0, "mean": 77.818182, "median": 57.0, "min": 6.0}, "largest_source_episode_entry_share": 0.209244, "source_episodes": 11, "source_episodes_with_entry": 11, "source_episodes_with_landmark_participation": 11, "waits_per_source_episode": {"count": 11, "max": 2879.0, "mean": 1220.818182, "median": 891.0, "min": 58.0}}`.
- VALIDATE aggregate: valid-but-wait candles 1083 | conflict waits 0 | no-active-hypothesis candles 2008 | entries after midpoint 0 | entries at reached reference 0 | entries on any release candle 0 | entries on hypothesis birth candle 0 | continuation entries on acceptance candle 0 | largest family share 0.300268.
- VALIDATE aggregate source-episode spread: `{"entries_per_source_episode": {"count": 5, "max": 38.0, "mean": 28.6, "median": 29.0, "min": 20.0}, "landmark_positions_per_source_episode": {"count": 5, "max": 26.0, "mean": 18.8, "median": 19.0, "min": 14.0}, "largest_source_episode_entry_share": 0.265734, "source_episodes": 5, "source_episodes_with_entry": 5, "source_episodes_with_landmark_participation": 5, "waits_per_source_episode": {"count": 5, "max": 514.0, "mean": 409.4, "median": 352.0, "min": 331.0}}`.

## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY

- `hypotheses_created_per_candle`: TEACH 5515/36250 = 0.152138; VALIDATE aggregate 746/5275 = 0.141422; absolute difference 0.010716.
- `shadow_entries_per_candle`: TEACH 1190/36250 = 0.032828; VALIDATE aggregate 143/5275 = 0.027109; absolute difference 0.005719.
- `valid_but_wait_per_candle`: TEACH 5816/36250 = 0.160441; VALIDATE aggregate 1083/5275 = 0.205308; absolute difference 0.044867.
- `landmark_positions_per_closed_position`: TEACH 856/1190 = 0.719328; VALIDATE aggregate 94/143 = 0.657343; absolute difference 0.061985.
- `falsified_positions_per_closed_position`: TEACH 435/1190 = 0.365546; VALIDATE aggregate 56/143 = 0.391608; absolute difference 0.026062.
- `side_flips_per_closed_position`: TEACH 561/1190 = 0.471429; VALIDATE aggregate 83/143 = 0.58042; absolute difference 0.108991.

## MICRO AND REFERENCES

Micro is copied as subordinate movement context and cannot create a hypothesis or shadow position by itself. Up/down reference paths remain distinct. Rotation uses Broad midpoint and opposite edge; outside continuation uses the immediate mapped reference published in its direction.
- TEACH Micro state at entry: `{"ABSENT": 1128, "COLLAPSED": 8, "CONFIRMED": 5, "FINALIZED": 1, "FORMING": 48}`.
- VALIDATE aggregate Micro state at entry: `{"ABSENT": 135, "COLLAPSED": 1, "CONFIRMED": 2, "FORMING": 5}`.

## PRIOR STRUCTURAL RESEARCH

- Structural-response fingerprint: `5ebd256debc3e35a`.
- R2_CLUSTER: **INCONCLUSIVE**.
- R2_RANGE: **INSUFFICIENT_POPULATION**.
- R4_MICRO: **INCONCLUSIVE**.
- LOCAL_PUBLICATION: **NO**.
- This milestone does not promote edge superiority or change those conclusions.

## DECISION GATES

- **D1_MOVEMENT_STATE_CAUSAL**: YES. immutable closed-candle movement states were emitted inside every source barrier.
- **D2_HYPOTHESIS_LIFECYCLE_CAUSAL**: YES. hypotheses were born, updated, and terminally classified from current-or-prior facts.
- **D3_PARTICIPATION_SEPARATE_FROM_HYPOTHESIS**: YES. both buckets contain active hypotheses that remained flat for structural reasons.
- **D4_STRUCTURAL_INVALIDATION_WORKS**: YES. every entry carried factual invalidation and no exit lagged a first falsification.
- **D5_NO_AUTOMATIC_REVERSAL**: YES. same-candle opposite shadow entry after exit is absent.
- **D6_SHADOW_TRADER_CAN_FOLLOW_MOVEMENT**: YES. entries followed causal hypothesis formation, structural landmarks were reached, exits were causal, and behaviour appeared in multiple source episodes in both buckets.
- **D7_READY_FOR_EXECUTION_RESEARCH**: NO. this remains a research-only shadow machine without execution, costs, or unseen-forward study.

## PRIVACY AND INTEGRITY

- VALIDATE is aggregate-only: no timestamps, prices, IDs, bands, traces, session-linked indices, or paths.
- HOLDOUT_PRICE_SESSIONS_CONVERTED = 0.
- Every source episode closes its still-live hypotheses and shadow position at its own boundary.
- No broker, order submission, sizing, leverage, parameter search, or detector tuning exists here.
