# BRAIN V2 PRE-PRODUCTION QUALITY VERDICT

Verdict: **HOLD_FOR_TARGETED_BRAIN_FIX**.

Brain V2 keeps every V1 rule and adds exactly one: an open ROTATION shadow position returns to FLAT on the first closed candle that closes at or beyond its own frozen Broad invalidation level. The market hypothesis is not falsified by that exit, participation for that hypothesis instance is consumed, and no reversal is created. Continuations are untouched.

Brain V2 audit fingerprint: `8e2d85d387843a57`.
Frozen V1 behaviour fingerprint: `bf497495e394bb87` (MATCH).
Frozen V1 quality fingerprint: `bf54631ee9c200e9` (MATCH).
Trader logic changed: **YES — one preregistered rotation position-risk rule**.

## WHAT CHANGED, IN ONE PARAGRAPH

V1 kept an open position alive until its hypothesis received an accepted structural failure, so the market could cross the position's own frozen boundary and the position kept waiting. V2 separates the two events: `ACCEPTED_STRUCTURAL_FAILURE` still owns hypothesis falsification, and the new `POSITION_INVALIDATION_LEVEL_CROSSED` owns open-position risk.

## POSITION POPULATION

- TEACH: closed positions V1 1190 -> V2 1190 (change 0).
- TEACH entries by family V1: `{"OUTSIDE_CONTINUATION_DOWN": 329, "OUTSIDE_CONTINUATION_UP": 289, "ROTATION_FROM_LOWER_AREA": 289, "ROTATION_FROM_UPPER_AREA": 283}`.
- TEACH entries by family V2: `{"OUTSIDE_CONTINUATION_DOWN": 329, "OUTSIDE_CONTINUATION_UP": 289, "ROTATION_FROM_LOWER_AREA": 289, "ROTATION_FROM_UPPER_AREA": 283}`.
- TEACH active directional population V1: `{"active_directional_with_participation": 1190, "active_directional_without_participation": 1585, "directional_hypotheses": 5086, "directional_hypotheses_ever_active": 2775, "observational_failed_return_contexts": 429}`; V2: `{"active_directional_with_participation": 1190, "active_directional_without_participation": 1585, "directional_hypotheses": 5086, "directional_hypotheses_ever_active": 2775, "observational_failed_return_contexts": 429}`.
- VALIDATE aggregate: closed positions V1 143 -> V2 143 (change 0).
- VALIDATE aggregate entries by family V1: `{"OUTSIDE_CONTINUATION_DOWN": 40, "OUTSIDE_CONTINUATION_UP": 48, "ROTATION_FROM_LOWER_AREA": 27, "ROTATION_FROM_UPPER_AREA": 28}`.
- VALIDATE aggregate entries by family V2: `{"OUTSIDE_CONTINUATION_DOWN": 40, "OUTSIDE_CONTINUATION_UP": 48, "ROTATION_FROM_LOWER_AREA": 27, "ROTATION_FROM_UPPER_AREA": 28}`.
- VALIDATE aggregate active directional population V1: `{"active_directional_with_participation": 143, "active_directional_without_participation": 213, "directional_hypotheses": 675, "directional_hypotheses_ever_active": 356, "observational_failed_return_contexts": 71}`; V2: `{"active_directional_with_participation": 143, "active_directional_without_participation": 213, "directional_hypotheses": 675, "directional_hypotheses_ever_active": 356, "observational_failed_return_contexts": 71}`.

## ROTATION POSITION RISK EXITS

- TEACH: position risk exits 386 (rotation 386, continuation 0); exits that lagged their first closed-candle cross 0.
- TEACH: position exit overshoot points n 386 | min 0.008 | median 13.13125 | mean 25.942285 | max 495.834; ATR n 386 | min 0.000215 | median 0.282123 | mean 0.545554 | max 12.53123; bars open n 386 | min 1.0 | median 2.0 | mean 3.199482 | max 41.0.
- TEACH: hypothesis status at the risk exit `{"STRESSED": 386}`.
- TEACH: positions already beyond their frozen invalidation at entry 1.
- TEACH by family: `{"OUTSIDE_CONTINUATION_DOWN": {"overshoot_exceeds_entry_invalidation_distance": 0, "overshoot_points": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "position_risk_exits": 0}, "OUTSIDE_CONTINUATION_UP": {"overshoot_exceeds_entry_invalidation_distance": 0, "overshoot_points": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "position_risk_exits": 0}, "ROTATION_FROM_LOWER_AREA": {"overshoot_exceeds_entry_invalidation_distance": 109, "overshoot_points": {"count": 195, "max": 495.834, "mean": 28.118162, "median": 14.25625, "min": 0.053}, "position_risk_exits": 195}, "ROTATION_FROM_UPPER_AREA": {"overshoot_exceeds_entry_invalidation_distance": 103, "overshoot_points": {"count": 191, "max": 426.637, "mean": 23.72084, "median": 12.3, "min": 0.008}, "position_risk_exits": 191}}`.
- VALIDATE aggregate: position risk exits 41 (rotation 41, continuation 0); exits that lagged their first closed-candle cross 0.
- VALIDATE aggregate: position exit overshoot points n 41 | min 2.57875 | median 12.4505 | mean 42.527226 | max 567.957; ATR n 41 | min 0.043008 | median 0.263101 | mean 0.661808 | max 5.649346; bars open n 41 | min 1.0 | median 2.0 | mean 3.146341 | max 15.0.
- VALIDATE aggregate: hypothesis status at the risk exit `{"STRESSED": 41}`.
- VALIDATE aggregate: positions already beyond their frozen invalidation at entry 0.
- VALIDATE aggregate by family: `{"OUTSIDE_CONTINUATION_DOWN": {"overshoot_exceeds_entry_invalidation_distance": 0, "overshoot_points": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "position_risk_exits": 0}, "OUTSIDE_CONTINUATION_UP": {"overshoot_exceeds_entry_invalidation_distance": 0, "overshoot_points": {"count": 0, "max": null, "mean": null, "median": null, "min": null}, "position_risk_exits": 0}, "ROTATION_FROM_LOWER_AREA": {"overshoot_exceeds_entry_invalidation_distance": 10, "overshoot_points": {"count": 20, "max": 567.957, "mean": 48.84245, "median": 10.625125, "min": 2.57875}, "position_risk_exits": 20}, "ROTATION_FROM_UPPER_AREA": {"overshoot_exceeds_entry_invalidation_distance": 11, "overshoot_points": {"count": 21, "max": 243.76975, "mean": 36.512726, "median": 15.398, "min": 2.915}, "position_risk_exits": 21}}`.

## SAME-HYPOTHESIS RE-ENTRY

- TEACH: hypotheses with consumed participation 386; positions reopened by a risk-consumed hypothesis **0**; hypotheses that produced more than one position 0.
- VALIDATE aggregate: hypotheses with consumed participation 41; positions reopened by a risk-consumed hypothesis **0**; hypotheses that produced more than one position 0.

## HYPOTHESIS FALSIFICATION (SEPARATE FROM POSITION RISK)

- TEACH: falsified positions V1 435 -> V2 113.
- TEACH: accepted-failure overshoot points V1 n 435 | min 0.0 | median 30.0335 | mean 46.421801 | max 540.335.
- TEACH: accepted-failure overshoot points V2 n 113 | min 0.0 | median 21.076 | mean 30.533408 | max 182.624.
- TEACH: exit classes V1 `{"FALSIFICATION": 435, "OBJECTIVE_COMPLETION": 521, "RESEARCH_BOUNDARY": 1, "STRUCTURAL_REORIENTATION_HANDOFF": 233}`; V2 `{"FALSIFICATION": 113, "OBJECTIVE_COMPLETION": 457, "POSITION_RISK_EXIT": 386, "RESEARCH_BOUNDARY": 1, "STRUCTURAL_REORIENTATION_HANDOFF": 233}`.
- VALIDATE aggregate: falsified positions V1 56 -> V2 20.
- VALIDATE aggregate: accepted-failure overshoot points V1 n 56 | min 0.1425 | median 32.455375 | mean 60.506491 | max 665.707.
- VALIDATE aggregate: accepted-failure overshoot points V2 n 20 | min 0.1425 | median 32.9935 | mean 47.609413 | max 150.0505.
- VALIDATE aggregate: exit classes V1 `{"FALSIFICATION": 56, "OBJECTIVE_COMPLETION": 54, "STRUCTURAL_REORIENTATION_HANDOFF": 33}`; V2 `{"FALSIFICATION": 20, "OBJECTIVE_COMPLETION": 49, "POSITION_RISK_EXIT": 41, "STRUCTURAL_REORIENTATION_HANDOFF": 33}`.

## STRUCTURAL PROGRESS, RETAINED AND GIVEN BACK

- TEACH max favorable fraction: V1 n 1190 | min 0.0 | median 0.52012 | mean 0.49897 | max 1.0; V2 n 1190 | min 0.0 | median 0.346167 | mean 0.447562 | max 1.0.
- TEACH retained fraction at exit: V1 n 1190 | min -17.906228 | median -0.035563 | mean -0.206573 | max 1.0; V2 n 1190 | min -17.906228 | median -0.127628 | mean -0.186095 | max 1.0.
- TEACH retained sign V1 `{"negative": 605, "positive": 584, "zero": 1}`; V2 `{"negative": 669, "positive": 520, "zero": 1}`.
- TEACH giveback fraction: V1 n 1190 | min 0.0 | median 0.158302 | mean 0.705542 | max 18.250186; V2 n 1190 | min 0.0 | median 0.231705 | mean 0.633656 | max 18.250186.
- TEACH retained fraction by family V2: `{"OUTSIDE_CONTINUATION_DOWN": {"count": 329, "max": 1.0, "mean": -0.235539, "median": 0.227814, "min": -17.906228}, "OUTSIDE_CONTINUATION_UP": {"count": 289, "max": 1.0, "mean": -0.3046, "median": 0.046274, "min": -13.376608}, "ROTATION_FROM_LOWER_AREA": {"count": 289, "max": 1.0, "mean": -0.116375, "median": -0.304898, "min": -7.650517}, "ROTATION_FROM_UPPER_AREA": {"count": 283, "max": 1.0, "mean": -0.078794, "median": -0.240031, "min": -5.627477}}`.
- VALIDATE aggregate max favorable fraction: V1 n 143 | min 0.0 | median 0.40044 | mean 0.466283 | max 1.0; V2 n 143 | min 0.0 | median 0.297458 | mean 0.429958 | max 1.0.
- VALIDATE aggregate retained fraction at exit: V1 n 143 | min -4.892209 | median -0.154116 | mean -0.218337 | max 1.0; V2 n 143 | min -4.761434 | median -0.174794 | mean -0.190049 | max 1.0.
- VALIDATE aggregate retained sign V1 `{"negative": 80, "positive": 63, "zero": 0}`; V2 `{"negative": 85, "positive": 58, "zero": 0}`.
- VALIDATE aggregate giveback fraction: V1 n 143 | min 0.0 | median 0.242967 | mean 0.68462 | max 5.126041; V2 n 143 | min 0.0 | median 0.255113 | mean 0.620007 | max 4.761434.
- VALIDATE aggregate retained fraction by family V2: `{"OUTSIDE_CONTINUATION_DOWN": {"count": 40, "max": 1.0, "mean": -0.18574, "median": 0.070438, "min": -3.434147}, "OUTSIDE_CONTINUATION_UP": {"count": 48, "max": 1.0, "mean": 0.010061, "median": -0.01569, "min": -3.21842}, "ROTATION_FROM_LOWER_AREA": {"count": 27, "max": 1.0, "mean": -0.343737, "median": -0.358072, "min": -3.89384}, "ROTATION_FROM_UPPER_AREA": {"count": 28, "max": 1.0, "mean": -0.39105, "median": -0.346818, "min": -4.761434}}`.

## WAIT BEHAVIOUR

- TEACH: WAIT outcomes V1 `{"WAIT_AT_ALREADY_CONSUMED_MOVEMENT": 593, "WAIT_AVOIDED_FAILED_HYPOTHESIS": 333, "WAIT_MISSED_SUPPORTIVE_MOVEMENT": 403, "WAIT_UNRESOLVED": 256}`; V2 `{"WAIT_AT_ALREADY_CONSUMED_MOVEMENT": 652, "WAIT_AVOIDED_FAILED_HYPOTHESIS": 322, "WAIT_MISSED_SUPPORTIVE_MOVEMENT": 363, "WAIT_UNRESOLVED": 248}`.
- VALIDATE aggregate: WAIT outcomes V1 `{"WAIT_AT_ALREADY_CONSUMED_MOVEMENT": 75, "WAIT_AVOIDED_FAILED_HYPOTHESIS": 51, "WAIT_MISSED_SUPPORTIVE_MOVEMENT": 52, "WAIT_UNRESOLVED": 35}`; V2 `{"WAIT_AT_ALREADY_CONSUMED_MOVEMENT": 78, "WAIT_AVOIDED_FAILED_HYPOTHESIS": 49, "WAIT_MISSED_SUPPORTIVE_MOVEMENT": 51, "WAIT_UNRESOLVED": 35}`.

## SIDE SWITCHING

- TEACH: switches V1 561 -> V2 561.
- TEACH: categories V1 `{"FAILED_RELEASE_REASSESSMENT": 208, "NEW_STRUCTURE_REORIENTATION": 199, "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION": 19, "STRUCTURALLY_JUSTIFIED_REASSESSMENT": 135}`; V2 `{"FAILED_RELEASE_REASSESSMENT": 208, "NEW_STRUCTURE_REORIENTATION": 199, "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION": 15, "STRUCTURALLY_JUSTIFIED_REASSESSMENT": 139}`.
- TEACH: flip chains V2 `{"chains_same_broad_structure": 71, "chains_with_meaningful_events_between_every_side": 294, "four_or_more_alternating_chains": 69, "three_position_alternating_chains": 77, "two_position_alternating_chains": 148}`; flat candles between n 561 | min 0.0 | median 12.0 | mean 23.702317 | max 263.0.
- VALIDATE aggregate: switches V1 83 -> V2 83.
- VALIDATE aggregate: categories V1 `{"FAILED_RELEASE_REASSESSMENT": 29, "NEW_STRUCTURE_REORIENTATION": 32, "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION": 2, "STRUCTURALLY_JUSTIFIED_REASSESSMENT": 20}`; V2 `{"FAILED_RELEASE_REASSESSMENT": 29, "NEW_STRUCTURE_REORIENTATION": 32, "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION": 2, "STRUCTURALLY_JUSTIFIED_REASSESSMENT": 20}`.
- VALIDATE aggregate: flip chains V2 `{"chains_same_broad_structure": 5, "chains_with_meaningful_events_between_every_side": 32, "four_or_more_alternating_chains": 10, "three_position_alternating_chains": 8, "two_position_alternating_chains": 14}`; flat candles between n 83 | min 0.0 | median 9.0 | mean 25.915663 | max 262.0.

## CONTINUATIONS (UNCHANGED BY CONSTRUCTION)

- TEACH OUTSIDE_CONTINUATION_UP: positions V1 289 -> V2 289; retained fraction V1 n 289 | min -13.376608 | median 0.046274 | mean -0.3046 | max 1.0; V2 n 289 | min -13.376608 | median 0.046274 | mean -0.3046 | max 1.0.
- TEACH OUTSIDE_CONTINUATION_DOWN: positions V1 329 -> V2 329; retained fraction V1 n 329 | min -17.906228 | median 0.227814 | mean -0.235539 | max 1.0; V2 n 329 | min -17.906228 | median 0.227814 | mean -0.235539 | max 1.0.
- VALIDATE aggregate OUTSIDE_CONTINUATION_UP: positions V1 48 -> V2 48; retained fraction V1 n 48 | min -3.21842 | median -0.01569 | mean 0.010061 | max 1.0; V2 n 48 | min -3.21842 | median -0.01569 | mean 0.010061 | max 1.0.
- VALIDATE aggregate OUTSIDE_CONTINUATION_DOWN: positions V1 40 -> V2 40; retained fraction V1 n 40 | min -3.434147 | median 0.070438 | mean -0.18574 | max 1.0; V2 n 40 | min -3.434147 | median 0.070438 | mean -0.18574 | max 1.0.

## ADVERSE EXIT LEDGER — THE Q3 POPULATION

- TEACH: adverse exits 499 (falsification 113, position risk 386); overshoot beyond the frozen level n 499 | min 0.0 | median 15.241 | mean 26.981958 | max 495.834; exceeding the distance risked at entry 244; ATR n 499 | min 0.0 | median 0.302486 | mean 0.564951 | max 12.53123.
- VALIDATE aggregate: adverse exits 61 (falsification 20, position risk 41); overshoot beyond the frozen level n 61 | min 0.1425 | median 16.587 | mean 44.193516 | max 567.957; exceeding the distance risked at entry 30; ATR n 61 | min 0.004127 | median 0.306776 | mean 0.679413 | max 5.649346.

## ENTRY QUALITY BY FAMILY

- TEACH ROTATION_FROM_LOWER_AREA: entries 289 | ACTIVE-to-entry n 289 | min 0.0 | median 0.0 | mean 0.380623 | max 10.0 | whole progress fraction n 289 | min 0.00023 | median 0.169213 | mean 0.165518 | max 0.385055 | room points n 289 | min 23.4635 | median 61.312 | mean 73.813494 | max 429.4705 | invalidation points n 289 | min 0.0075 | median 12.80875 | mean 14.338775 | max 88.148.
- TEACH ROTATION_FROM_UPPER_AREA: entries 283 | ACTIVE-to-entry n 283 | min 0.0 | median 0.0 | mean 0.289753 | max 13.0 | whole progress fraction n 283 | min 0.0 | median 0.157784 | mean 0.161522 | max 0.418789 | room points n 283 | min 24.99625 | median 62.36125 | mean 72.335332 | max 474.5715 | invalidation points n 283 | min 0.045 | median 11.59475 | mean 13.604198 | max 55.345.
- TEACH OUTSIDE_CONTINUATION_UP: entries 289 | ACTIVE-to-entry n 289 | min 1.0 | median 2.0 | mean 1.913495 | max 8.0 | whole progress fraction n 289 | min 0.0 | median 0.491945 | mean 0.492309 | max 0.921626 | room points n 289 | min 8.447 | median 51.49675 | mean 95.354456 | max 858.063 | invalidation points n 289 | min 8.92425 | median 52.7185 | mean 76.913666 | max 573.56.
- TEACH OUTSIDE_CONTINUATION_DOWN: entries 329 | ACTIVE-to-entry n 329 | min 1.0 | median 2.0 | mean 2.015198 | max 26.0 | whole progress fraction n 329 | min 0.023107 | median 0.486657 | mean 0.476477 | max 0.931964 | room points n 329 | min 10.32 | median 52.25675 | mean 114.525426 | max 1157.742 | invalidation points n 329 | min 7.201 | median 52.49225 | mean 68.419521 | max 451.584.
- VALIDATE aggregate ROTATION_FROM_LOWER_AREA: entries 27 | ACTIVE-to-entry n 27 | min 0.0 | median 0.0 | mean 0.407407 | max 6.0 | whole progress fraction n 27 | min 0.004268 | median 0.19389 | mean 0.190955 | max 0.356473 | room points n 27 | min 33.655 | median 57.735 | mean 70.086157 | max 190.08775 | invalidation points n 27 | min 0.287 | median 11.586 | mean 16.416944 | max 48.25.
- VALIDATE aggregate ROTATION_FROM_UPPER_AREA: entries 28 | ACTIVE-to-entry n 28 | min 0.0 | median 0.0 | mean 0.25 | max 4.0 | whole progress fraction n 28 | min 0.016638 | median 0.187374 | mean 0.179698 | max 0.342092 | room points n 28 | min 36.7335 | median 56.429125 | mean 77.180348 | max 220.6675 | invalidation points n 28 | min 0.814 | median 12.5645 | mean 18.278857 | max 64.34.
- VALIDATE aggregate OUTSIDE_CONTINUATION_UP: entries 48 | ACTIVE-to-entry n 48 | min 1.0 | median 1.0 | mean 1.8125 | max 7.0 | whole progress fraction n 48 | min 0.024468 | median 0.457382 | mean 0.455745 | max 0.926585 | room points n 48 | min 13.45625 | median 88.59375 | mean 223.460599 | max 1739.11 | invalidation points n 48 | min 10.5575 | median 71.1635 | mean 133.118547 | max 1073.72175.
- VALIDATE aggregate OUTSIDE_CONTINUATION_DOWN: entries 40 | ACTIVE-to-entry n 40 | min 1.0 | median 1.0 | mean 1.675 | max 5.0 | whole progress fraction n 40 | min 0.085565 | median 0.416815 | mean 0.431709 | max 0.957047 | room points n 40 | min 16.88 | median 72.665625 | mean 156.254381 | max 901.907 | invalidation points n 40 | min 11.63 | median 58.40175 | mean 100.629488 | max 1323.133.

## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY

- `supportive_landmark_per_position`: TEACH 562/1190 = 0.472269; VALIDATE aggregate 64/143 = 0.447552; absolute difference 0.024717.
- `objective_completion_per_position`: TEACH 457/1190 = 0.384034; VALIDATE aggregate 49/143 = 0.342657; absolute difference 0.041377.
- `positive_retained_progress_per_position`: TEACH 520/1190 = 0.436975; VALIDATE aggregate 58/143 = 0.405594; absolute difference 0.031381.
- `falsification_per_position`: TEACH 113/1190 = 0.094958; VALIDATE aggregate 20/143 = 0.13986; absolute difference 0.044902.
- `wait_avoided_failure_per_nonparticipated_active`: TEACH 322/1585 = 0.203155; VALIDATE aggregate 49/213 = 0.230047; absolute difference 0.026892.
- `wait_missed_supportive_per_nonparticipated_active`: TEACH 363/1585 = 0.229022; VALIDATE aggregate 51/213 = 0.239437; absolute difference 0.010415.
- `nonzero_overshoot_per_falsified_position`: TEACH 112/113 = 0.99115; VALIDATE aggregate 20/20 = 1.0; absolute difference 0.00885.
- `possible_churn_per_side_switch`: TEACH 0/561 = 0.0; VALIDATE aggregate 0/83 = 0.0; absolute difference 0.0.

## WEAKEST FAMILY

- Result: **MIXED_NO_SINGLE_DOMINANT_WEAKNESS**.
- Facts: `{"teach": {"OUTSIDE_CONTINUATION_DOWN": {"falsification_rate": 0.173252, "objective_completion_rate": 0.477204, "overshoot_points_median": 21.46475, "positions": 329, "retained_progress_fraction_median": 0.227814}, "OUTSIDE_CONTINUATION_UP": {"falsification_rate": 0.193772, "objective_completion_rate": 0.397924, "overshoot_points_median": 20.6125, "positions": 289, "retained_progress_fraction_median": 0.046274}, "ROTATION_FROM_LOWER_AREA": {"falsification_rate": 0.0, "objective_completion_rate": 0.32526, "overshoot_points_median": null, "positions": 289, "retained_progress_fraction_median": -0.304898}, "ROTATION_FROM_UPPER_AREA": {"falsification_rate": 0.0, "objective_completion_rate": 0.321555, "overshoot_points_median": null, "positions": 283, "retained_progress_fraction_median": -0.240031}}, "validate": {"OUTSIDE_CONTINUATION_DOWN": {"falsification_rate": 0.225, "objective_completion_rate": 0.425, "overshoot_points_median": 33.537, "positions": 40, "retained_progress_fraction_median": 0.070438}, "OUTSIDE_CONTINUATION_UP": {"falsification_rate": 0.229167, "objective_completion_rate": 0.375, "overshoot_points_median": 29.571, "positions": 48, "retained_progress_fraction_median": -0.01569}, "ROTATION_FROM_LOWER_AREA": {"falsification_rate": 0.0, "objective_completion_rate": 0.259259, "overshoot_points_median": null, "positions": 27, "retained_progress_fraction_median": -0.358072}, "ROTATION_FROM_UPPER_AREA": {"falsification_rate": 0.0, "objective_completion_rate": 0.25, "overshoot_points_median": null, "positions": 28, "retained_progress_fraction_median": -0.346818}}}`.

## Q3 CONTROL — THE SAME RULE ON V1

- The repaired Q3 rule recomputed on the V1 control replay answers **NO**.
- V1 facts: `{"teach": {"adverse_exits_with_measured_overshoot": 435, "first_causal_exit_violations": 0, "half_of_adverse_exits": 217.5, "integrity_broken": false, "overshoot_exceeds_entry_invalidation_distance": 300, "position_risk_exits": 0, "position_risk_exits_that_lagged_their_first_cross": 0, "positions_reopened_by_a_risk_consumed_hypothesis": 0}, "validate": {"adverse_exits_with_measured_overshoot": 56, "first_causal_exit_violations": 0, "half_of_adverse_exits": 28.0, "integrity_broken": false, "overshoot_exceeds_entry_invalidation_distance": 39, "position_risk_exits": 0, "position_risk_exits_that_lagged_their_first_cross": 0, "positions_reopened_by_a_risk_consumed_hypothesis": 0}}`.
- V2 facts: `{"teach": {"adverse_exits_with_measured_overshoot": 499, "first_causal_exit_violations": 0, "half_of_adverse_exits": 249.5, "integrity_broken": false, "overshoot_exceeds_entry_invalidation_distance": 244, "position_risk_exits": 386, "position_risk_exits_that_lagged_their_first_cross": 0, "positions_reopened_by_a_risk_consumed_hypothesis": 0}, "validate": {"adverse_exits_with_measured_overshoot": 61, "first_causal_exit_violations": 0, "half_of_adverse_exits": 30.5, "integrity_broken": false, "overshoot_exceeds_entry_invalidation_distance": 30, "position_risk_exits": 41, "position_risk_exits_that_lagged_their_first_cross": 0, "positions_reopened_by_a_risk_consumed_hypothesis": 0}}`.

## FINAL QUALITY GATES

- Q1_METRICS_SEMANTICALLY_CLEAN: **YES**.
- Q2_WAIT_BEHAVIOUR_ACCEPTABLE: **INCONCLUSIVE**.
- Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE: **YES**.
- Q4_SIDE_SWITCHING_IS_STRUCTURALLY_EXPLAINABLE: **YES**.
- Q5_MOVEMENT_PARTICIPATION_QUALITY: **NO**.
- Q6_TEACH_VALIDATE_BEHAVIOUR_REPEATABLE: **INCONCLUSIVE**.
- Q7_READY_FOR_PRODUCTION_INTEGRATION: **NO**.

## PRESERVED RESEARCH STATUS

- D1_MOVEMENT_STATE_CAUSAL: **YES**.
- D2_HYPOTHESIS_LIFECYCLE_CAUSAL: **YES**.
- D3_PARTICIPATION_SEPARATE_FROM_HYPOTHESIS: **YES**.
- D4_STRUCTURAL_INVALIDATION_WORKS: **YES**.
- D5_NO_AUTOMATIC_REVERSAL: **YES**.
- D6_SHADOW_TRADER_CAN_FOLLOW_MOVEMENT: **YES**.
- D7_READY_FOR_EXECUTION_RESEARCH: **NO**.
- R2_CLUSTER: **INCONCLUSIVE**.
- R2_RANGE: **INSUFFICIENT_POPULATION**.
- R4_MICRO: **INCONCLUSIVE**.
- LOCAL_PUBLICATION: **NO**.
- This milestone does not promote edge superiority or change those conclusions.

## INTEGRITY

- Both frozen V1 fingerprints were reproduced from the current source tree before any V2 number was computed.
- Both brains read one identical set of causal frames per source episode.
- VALIDATE is aggregate-only; no IDs, timestamps, prices, paths, bands, or traces.
- HOLDOUT_PRICE_SESSIONS_CONVERTED = 0.
- No broker, live money, parameter optimization, score, confidence, probability, or ranking.

## NEXT DECISION

- DO_NOT_MIGRATE. Blocking gates: Q5_MOVEMENT_PARTICIPATION_QUALITY, Q7_READY_FOR_PRODUCTION_INTEGRATION.
