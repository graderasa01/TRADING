# Structural Response Audit V2

Status: EXECUTED. Research-only real-edge versus topologically equivalent ghost-boundary comparison.

Fingerprint: `5ebd256debc3e35a`

## V1 EVIDENCE

The reviewed V1 result is preserved unchanged at `reports/STRUCTURAL_RESPONSE_AUDIT_V1.md` and `reports/structural_response_summary_v1.json` with fingerprint `7d373af2a9e1389e`. V1 presence gates are not reused as strong evidence.

## SEMANTIC REPAIRS

- Encounter location now comes from the encounter-origin candle.
- Origin class is derived only from a prior same-structure closed candle; no side-to-direction inference remains.
- Wick/range contact and closed-candle side changes use one interaction rule for real and ghost boundaries.
- Outward and inward mapped references remain separate.
- Same-candle OHLC range never claims post-origin ordering.
- Real and ghost comparisons share one boundary response state machine; the production accepted-break label is excluded from primary R2 metrics.

## STRUCTURE POPULATION

- TEACH: episodes/visits 2119 | cluster 2095 | range 24 | revisit episodes 1690 | leaving observations 1346 | accepted breaks 1914 | re-entries 887 | opposite-edge traversals 1722 | median life/current/inside 5.0/4.0/3.0 bars.
- VALIDATE aggregate: episodes/visits 273 | cluster 273 | range 0 | revisit episodes 193 | leaving observations 176 | accepted breaks 248 | re-entries 110 | opposite-edge traversals 270 | median life/current/inside 6.0/5.0/3.0 bars.

## REAL EDGE POPULATION

- TEACH cluster: encounters 5405 | upper 2680 | lower 2725 | from inside 2659 | from outside 342 | first 3418 | repeat 1987.
- TEACH range: encounters 67 | upper 39 | lower 28 | from inside 45 | from outside 3 | first 37 | repeat 30.
- VALIDATE aggregate cluster: encounters 760 | upper 378 | lower 382 | from inside 374 | from outside 58 | first 471 | repeat 289.
- VALIDATE aggregate range: encounters 0 | upper 0 | lower 0 | from inside 0 | from outside 0 | first 0 | repeat 0.

## GHOST EDGE POPULATION

- TEACH cluster: encounters 8053 | upper 4047 | lower 4006 | from inside 1561 | from outside 3422 | first 3772 | repeat 4281.
- TEACH range: encounters 159 | upper 80 | lower 79 | from inside 48 | from outside 81 | first 40 | repeat 119.
- VALIDATE aggregate cluster: encounters 1054 | upper 538 | lower 516 | from inside 194 | from outside 460 | first 500 | repeat 554.
- VALIDATE aggregate range: encounters 0 | upper 0 | lower 0 | from inside 0 | from outside 0 | first 0 | repeat 0.

## CLUSTER RESULTS

- `next_close_inside`: TEACH real 3548/5369 = 0.6608, ghost 3831/8003 = 0.4787, difference 0.182136; VALIDATE aggregate real 509/755 = 0.6742, ghost 516/1049 = 0.4919, difference 0.182275.
- `outside_close`: TEACH real 3171/5405 = 0.5867, ghost 6192/8053 = 0.7689, difference -0.182227; VALIDATE aggregate real 425/760 = 0.5592, ghost 826/1054 = 0.7837, difference -0.22447.
- `reclaim_after_outside`: TEACH real 1017/3171 = 0.3207, ghost 1703/6192 = 0.2750, difference 0.045687; VALIDATE aggregate real 126/425 = 0.2965, ghost 237/826 = 0.2869, difference 0.009546.
- `retest_after_reclaim`: TEACH real 574/1017 = 0.5644, ghost 1019/1703 = 0.5984, difference -0.033951; VALIDATE aggregate real 69/126 = 0.5476, ghost 138/237 = 0.5823, difference -0.034659.
- `remain_inside_after_reclaim`: TEACH real 809/1017 = 0.7955, ghost 1326/1703 = 0.7786, difference 0.016851; VALIDATE aggregate real 105/126 = 0.8333, ghost 182/237 = 0.7679, difference 0.065401.
- `persistent_outside`: TEACH real 2264/3171 = 0.7140, ghost 4906/6192 = 0.7923, difference -0.078343; VALIDATE aggregate real 309/425 = 0.7271, ghost 653/826 = 0.7906, difference -0.063498.
- `move_away_inside`: TEACH real 3500/5369 = 0.6519, ghost 3667/8003 = 0.4582, difference 0.193687; VALIDATE aggregate real 496/755 = 0.6570, ghost 480/1049 = 0.4576, difference 0.199375.
- `next_close_inside` source-episode audit: TEACH largest real numerator share 0.223224 and real-minus-ghost spread {"count": 11, "max": 0.301181, "mean": 0.201556, "median": 0.174683, "min": 0.129731}; VALIDATE aggregate largest real numerator share 0.298625 and difference spread {"count": 5, "max": 0.220809, "mean": 0.17351, "median": 0.172519, "min": 0.082081}.
- `reclaim_after_outside` source-episode audit: TEACH largest real numerator share 0.218289 and real-minus-ghost spread {"count": 11, "max": 0.245421, "mean": 0.072591, "median": 0.04059, "min": -0.043456}; VALIDATE aggregate largest real numerator share 0.293651 and difference spread {"count": 5, "max": 0.083003, "mean": 0.001351, "median": -0.016525, "min": -0.051339}.
- `remain_inside_after_reclaim` source-episode audit: TEACH largest real numerator share 0.227441 and real-minus-ghost spread {"count": 11, "max": 0.080762, "mean": -0.000462, "median": 0.005803, "min": -0.177778}; VALIDATE aggregate largest real numerator share 0.285714 and difference spread {"count": 5, "max": 0.109091, "mean": 0.067566, "median": 0.064912, "min": 0.033333}.

## RANGE RESULTS

- `next_close_inside`: TEACH real 44/67 = 0.6567, ghost 79/159 = 0.4969, difference 0.159861; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `outside_close`: TEACH real 35/67 = 0.5224, ghost 128/159 = 0.8050, difference -0.282643; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `reclaim_after_outside`: TEACH real 10/35 = 0.2857, ghost 42/128 = 0.3281, difference -0.042411; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `retest_after_reclaim`: TEACH real 5/10 = 0.5000, ghost 24/42 = 0.5714, difference -0.071429; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `remain_inside_after_reclaim`: TEACH real 8/10 = 0.8000, ghost 34/42 = 0.8095, difference -0.009524; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `persistent_outside`: TEACH real 27/35 = 0.7714, ghost 96/128 = 0.7500, difference 0.021429; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.
- `move_away_inside`: TEACH real 45/67 = 0.6716, ghost 77/159 = 0.4843, difference 0.187365; VALIDATE aggregate real 0/0 = none, ghost 0/0 = none, difference None.

## FROM_INSIDE / FROM_OUTSIDE

- TEACH cluster FROM_INSIDE_TOWARD_EDGE: real/ghost encounters 2659/1561 | next-inside real 1767/2635 = 0.6706, ghost 1038/1547 = 0.6710, difference -0.000388 | reclaim real 473/1493 = 0.3168, ghost 308/903 = 0.3411, difference -0.024273 | remain-inside-after-reclaim difference -0.025068. Side and first/repeat numerators and denominators remain separate in the aggregate.
- TEACH cluster FROM_OUTSIDE_TOWARD_EDGE: real/ghost encounters 342/3422 | next-inside real 175/331 = 0.5287, ghost 1259/3388 = 0.3716, difference 0.157095 | reclaim real 63/247 = 0.2551, ghost 703/2927 = 0.2402, difference 0.014883 | remain-inside-after-reclaim difference -0.052428. Side and first/repeat numerators and denominators remain separate in the aggregate.
- VALIDATE aggregate cluster FROM_INSIDE_TOWARD_EDGE: real/ghost encounters 374/194 | next-inside real 253/369 = 0.6856, ghost 121/193 = 0.6269, difference 0.058694 | reclaim real 58/207 = 0.2802, ghost 38/123 = 0.3089, difference -0.02875 | remain-inside-after-reclaim difference 0.151543. Side and first/repeat numerators and denominators remain separate in the aggregate.
- VALIDATE aggregate cluster FROM_OUTSIDE_TOWARD_EDGE: real/ghost encounters 58/460 | next-inside real 25/58 = 0.4310, ghost 195/456 = 0.4276, difference 0.003402 | reclaim real 9/45 = 0.2000, ghost 105/382 = 0.2749, difference -0.074869 | remain-inside-after-reclaim difference -0.161904. Side and first/repeat numerators and denominators remain separate in the aggregate.

## R3 REPEATABILITY V2

- `touch_close_inside_next_inside`: TEACH 1729/2431 = 0.7112; VALIDATE aggregate 245/333 = 0.7357; absolute difference 0.024506; TEACH source-episode spread {"count": 11, "max": 0.77193, "mean": 0.688539, "median": 0.714734, "min": 0.526316}; VALIDATE aggregate source-episode spread {"count": 5, "max": 0.790698, "mean": 0.728547, "median": 0.773585, "min": 0.625}.
- `outside_close_reclaim`: TEACH 1211/3135 = 0.3863; VALIDATE aggregate 157/403 = 0.3896; absolute difference 0.003294; TEACH source-episode spread {"count": 11, "max": 0.568627, "mean": 0.401316, "median": 0.382567, "min": 0.304}; VALIDATE aggregate source-episode spread {"count": 5, "max": 0.454545, "mean": 0.376815, "median": 0.422018, "min": 0.272727}.
- `reclaim_retest_remain_inside`: TEACH 110/1211 = 0.0908; VALIDATE aggregate 6/157 = 0.0382; absolute difference 0.052617; TEACH source-episode spread {"count": 11, "max": 0.151163, "mean": 0.088123, "median": 0.087963, "min": 0.0}; VALIDATE aggregate source-episode spread {"count": 5, "max": 0.055556, "mean": 0.039807, "median": 0.044444, "min": 0.0}.
- `lower_encounter_midpoint_later_upper_encounter`: TEACH 1188/2221 = 0.5349; VALIDATE aggregate 182/320 = 0.5687; absolute difference 0.033856; TEACH source-episode spread {"count": 11, "max": 0.634615, "mean": 0.524473, "median": 0.535714, "min": 0.428571}; VALIDATE aggregate source-episode spread {"count": 5, "max": 0.607843, "mean": 0.559453, "median": 0.558442, "min": 0.528302}.

## MICRO CONTEXT

Micro remains encounter-origin context. Real-minus-ghost metrics are reported by existing state in the machine aggregate; no directional label or decision field is created.

- TEACH: `{"ABSENT": {"ghost": 7144, "next_inside_difference": 0.182322, "real": 4965, "reclaim_difference": 0.049862}, "BREAK_DOWN": {"ghost": 2, "next_inside_difference": -0.5, "real": 2, "reclaim_difference": -1.0}, "BREAK_UP": {"ghost": 2, "next_inside_difference": 0.0, "real": 4, "reclaim_difference": 0.0}, "COLLAPSED": {"ghost": 136, "next_inside_difference": 0.155116, "real": 118, "reclaim_difference": 0.066387}, "CONFIRMED": {"ghost": 167, "next_inside_difference": 0.048161, "real": 70, "reclaim_difference": 0.007156}, "CREATED": {"ghost": 254, "next_inside_difference": 0.331496, "real": 95, "reclaim_difference": 0.028509}, "FORMING": {"ghost": 348, "next_inside_difference": 0.188989, "real": 151, "reclaim_difference": -0.012122}}`
- VALIDATE aggregate: `{"ABSENT": {"ghost": 930, "next_inside_difference": 0.170526, "real": 692, "reclaim_difference": 0.005394}, "BREAK_DOWN": {"ghost": 0, "next_inside_difference": null, "real": 1, "reclaim_difference": null}, "BREAK_UP": {"ghost": 2, "next_inside_difference": 0.5, "real": 1, "reclaim_difference": null}, "COLLAPSED": {"ghost": 20, "next_inside_difference": 0.269231, "real": 14, "reclaim_difference": 0.116667}, "CONFIRMED": {"ghost": 31, "next_inside_difference": 0.316129, "real": 15, "reclaim_difference": 0.136904}, "CREATED": {"ghost": 25, "next_inside_difference": 0.326154, "real": 13, "reclaim_difference": -0.368421}, "FORMING": {"ghost": 46, "next_inside_difference": 0.291667, "real": 24, "reclaim_difference": 0.256757}}`

## SECONDARY V1 OCCUPANCY PROBES

- LOWER_INTERIOR_QUARTER: TEACH 2555 encounters; VALIDATE aggregate 349. These are occupancy descriptions, not R2 nulls.
- MIDPOINT: TEACH 2617 encounters; VALIDATE aggregate 329. These are occupancy descriptions, not R2 nulls.
- UPPER_INTERIOR_QUARTER: TEACH 2604 encounters; VALIDATE aggregate 343. These are occupancy descriptions, not R2 nulls.

## LIMITATIONS

- No post-result materiality threshold is introduced; R2 cannot become YES from non-zero differences alone.
- Encounter observations within a structure/source episode are correlated. Source-episode rate spreads and largest numerator shares are reported without treating encounters as independent.
- VALIDATE contains aggregate distributions only and no timestamps, bands, absolute prices, identities, traces, or session-linked indices.
- Range behavior cannot be certified when its VALIDATE boundary population is absent.
- Natural source-episode boundaries right-censor still-live encounters.

## DECISION GATES

- **STRUCTURAL_LIFECYCLE_OBSERVED**: YES. descriptive natural-lifecycle structures and encounters exist in both buckets.
- **R2_CLUSTER_EDGE_RESPONSE**: INCONCLUSIVE. V2 reports untuned rate differences and source-episode spread, but no preregistered materiality threshold supports a binary YES; matched origin strata must be read for directional consistency.
- **R2_RANGE_EDGE_RESPONSE**: INSUFFICIENT_POPULATION. VALIDATE has no matched real/ghost boundary population for this structure kind.
- **R3_REPEATABILITY_V2**: RATES_REPORTED_WITHOUT_BINARY_THRESHOLD. numerator/denominator rates and source-episode spreads are reported for 4 comparable families; the weak shared-nonzero gate is retired.
- **R4_MICRO**: INCONCLUSIVE. real-minus-ghost Micro strata are descriptive and mechanically coupled populations remain possible.
- **LOCAL_PUBLICATION**: NO. LOCAL remains an optional research sidecar.
- **READY_FOR_CLUSTER_HYPOTHESIS_BRAIN**: NO. cluster R2 is not certified YES under V2.

## INTEGRITY

- Excluded price sessions converted: 0.
- Origin facts are frozen at their causal candle; future facts append only.
- Each observer is scoped to one corrected source-contiguous episode.
- Ghost placement is midpoint-symmetric, deterministic, and equal-width before response observation.
- Production BROAD, Micro, release, reference, and thesis semantics are consumed without modification.
- LOCAL publication: NO.
