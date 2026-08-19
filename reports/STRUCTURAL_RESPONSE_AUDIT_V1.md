# Structural Response Audit

Status: EXECUTED. Research-only structural lifecycle observation; no production map changes.

Fingerprint: `7d373af2a9e1389e`

Primary observations run from causal structure availability to a natural structural or source-episode end. Fixed next-candle facts are secondary sequence/null descriptions only.

## STRUCTURE POPULATION

- TEACH: episodes/visits 2119 | cluster 2095 | range 24 | revisit episodes 1690 | leaving observations 1346 | accepted breaks 1914 | re-entries 887 | opposite-edge traversals 518 | median life/current/inside 5.0/4.0/3.0 bars.
- VALIDATE aggregate: episodes/visits 273 | cluster 273 | range 0 | revisit episodes 193 | leaving observations 176 | accepted breaks 248 | re-entries 110 | opposite-edge traversals 80 | median life/current/inside 6.0/5.0/3.0 bars.

## EDGE ENCOUNTER POPULATION

- TEACH upper: encounters 2133 | touches 2056 | origin close inside 991 | origin close at 991 | origin close outside 1142 | accepted breaks 976 | reclaims 584 | retests 211 | midpoint reaches 932 | opposite edge reaches 253 | repeated encounters 700.
- TEACH lower: encounters 2117 | touches 2047 | origin close inside 993 | origin close at 993 | origin close outside 1124 | accepted breaks 938 | reclaims 628 | retests 253 | midpoint reaches 905 | opposite edge reaches 265 | repeated encounters 684.
- VALIDATE aggregate upper: encounters 269 | touches 260 | origin close inside 130 | origin close at 130 | origin close outside 139 | accepted breaks 114 | reclaims 77 | retests 24 | midpoint reaches 131 | opposite edge reaches 44 | repeated encounters 78.
- VALIDATE aggregate lower: encounters 278 | touches 271 | origin close inside 136 | origin close at 136 | origin close outside 142 | accepted breaks 134 | reclaims 80 | retests 30 | midpoint reaches 124 | opposite edge reaches 36 | repeated encounters 92.

An exact inside close may also be within the existing edge tolerance, so `origin close at` is a subset of `origin close inside`; outside takes precedence.

## RELEASE SUBPOPULATION

- TEACH: episodes 2604 | scales {"INNER": 150, "MICRO": 61, "OUTER": 2393} | linked edge encounters 1949 | simultaneous releases preserved 113 | givebacks 2492 | median held bars 3.0.
- VALIDATE aggregate: episodes 335 | scales {"INNER": 8, "MICRO": 9, "OUTER": 318} | linked edge encounters 252 | simultaneous releases preserved 8 | givebacks 307 | median held bars 3.0.

## MICRO CONTEXT

Micro is recorded only at broad-edge encounter origin. The aggregate strata are:

- TEACH: `{"ABSENT": {"accepted_breaks": 1707, "encounters": 3865, "midpoint_reaches": 1734, "reclaims": 1117}, "BREAK_DOWN": {"accepted_breaks": 3, "encounters": 3, "midpoint_reaches": 0, "reclaims": 1}, "BREAK_UP": {"accepted_breaks": 5, "encounters": 6, "midpoint_reaches": 0, "reclaims": 1}, "COLLAPSED": {"accepted_breaks": 82, "encounters": 134, "midpoint_reaches": 26, "reclaims": 28}, "CONFIRMED": {"accepted_breaks": 37, "encounters": 54, "midpoint_reaches": 7, "reclaims": 15}, "CREATED": {"accepted_breaks": 24, "encounters": 66, "midpoint_reaches": 26, "reclaims": 14}, "FORMING": {"accepted_breaks": 56, "encounters": 122, "midpoint_reaches": 44, "reclaims": 36}}`
- VALIDATE aggregate: `{"ABSENT": {"accepted_breaks": 218, "encounters": 492, "midpoint_reaches": 239, "reclaims": 148}, "BREAK_DOWN": {"accepted_breaks": 0, "encounters": 1, "midpoint_reaches": 0, "reclaims": 0}, "COLLAPSED": {"accepted_breaks": 8, "encounters": 15, "midpoint_reaches": 6, "reclaims": 3}, "CONFIRMED": {"accepted_breaks": 8, "encounters": 10, "midpoint_reaches": 1, "reclaims": 3}, "CREATED": {"accepted_breaks": 4, "encounters": 9, "midpoint_reaches": 4, "reclaims": 0}, "FORMING": {"accepted_breaks": 10, "encounters": 20, "midpoint_reaches": 5, "reclaims": 3}}`

No directional Micro label or decision field was created.

## LOCAL RESEARCH SIDECAR

- TEACH: present 340 | absent 3910 | relations to production Micro `{"CONTAINS_MICRO": 75, "DISTINCT_FROM_MICRO": 48, "INSIDE_MICRO": 5, "NO_PRODUCTION_MICRO": 212}`.
- VALIDATE aggregate: present 41 | absent 506 | relations to production Micro `{"CONTAINS_MICRO": 10, "DISTINCT_FROM_MICRO": 6, "NO_PRODUCTION_MICRO": 25}`.

LOCAL remains unpublished and is not required by the primary ledgers.

## SEQUENCE COUNTS

- `touch_close_inside_next_inside`: TEACH 840 | VALIDATE aggregate 109.
- `touch_outside_close_accepted_break`: TEACH 1914 | VALIDATE aggregate 248.
- `outside_close_reclaim`: TEACH 1212 | VALIDATE aggregate 157.
- `reclaim_retest_remain_inside`: TEACH 110 | VALIDATE aggregate 6.
- `lower_encounter_midpoint_upper_encounter`: TEACH 579 | VALIDATE aggregate 79.

Subsequent natural end transitions are retained in the machine-readable aggregate.

## NULL COMPARISONS

- LOWER_INTERIOR_QUARTER: TEACH encounters 2555, next close on defined interior side 1512; VALIDATE aggregate encounters 349, next close on defined interior side 211.
- MIDPOINT: TEACH encounters 2617, next close on defined interior side 1304; VALIDATE aggregate encounters 329, next close on defined interior side 160.
- UPPER_INTERIOR_QUARTER: TEACH encounters 2604, next close on defined interior side 1594; VALIDATE aggregate encounters 343, next close on defined interior side 215.

The quarter and midpoint levels are mechanically derived with no tuned offset. They are useful occupancy references, but they are not fair topological substitutes for an edge: an edge separates inside from outside while an interior level does not. R2 is therefore left inconclusive.

## COUNTER-EVIDENCE

- Interior pseudo-levels are structurally confounded with edge comparisons.
- VALIDATE observed no range episodes; cross-bucket repetition is therefore cluster-dominated.
- The outside-close to accepted-break sequence partly restates the upstream two-close rule and is not independent evidence.
- Encounter paths include multiple natural end reasons; no single response exhausts the population.
- Micro and LOCAL strata are observational and do not establish added information by themselves.

## LIMITATIONS

- The first 400 candles of each corrected source episode establish the frozen map and are not response observations.
- Source episodes with no candle beyond that history are skipped rather than joined across a barrier.
- VALIDATE is emitted only as aggregate counts and distributions; no timestamp, band, price, structure identity, trace, or session-linked index is written.
- The natural source-episode boundary right-censors still-live ledgers.

## DECISION GATES

- **R1_STRUCTURAL_RESPONSE_EXISTS**: YES. natural-lifecycle structure and edge responses were observed in both buckets.
- **R2_EDGE_RESPONSE_EXISTS**: INCONCLUSIVE. interior pseudo-levels are deterministic but not topologically equivalent to boundaries.
- **R3_RESPONSE_IS_REPEATABLE**: YES. shared non-zero sequence families: 5.
- **R4_MICRO_ADDS_INFORMATION**: INCONCLUSIVE. Micro strata are descriptive and no untuned separation criterion was introduced.
- **R5_READY_FOR_HYPOTHESIS_BRAIN**: NO. R2 is not supported; R5 requires R1-R3.
- **LOCAL_PUBLICATION**: NO. LOCAL remains an optional research sidecar.

## INTEGRITY

- Excluded price sessions converted: 0.
- Origin facts are frozen at their causal candle; future facts append only.
- Each observer is scoped to one corrected source-contiguous episode.
- Production BROAD, Micro, release, reference, and thesis semantics are consumed without modification.
- LOCAL publication: NO.
