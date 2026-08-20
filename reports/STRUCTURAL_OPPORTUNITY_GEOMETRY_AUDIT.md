# WHAT STRUCTURES IS THE TRADER ACTUALLY SEEING?

Fingerprint: `cb928c40abfff540`.

**Broad is a role, not a size.** The controlling structure is whichever node price is currently standing in; `cluster` and `range` are its kind. This study exists because the stack had never reported how *big* that node usually is, and an internal edge-to-edge rotation only means something if there is somewhere to rotate to.

Nothing here proposes an entry rule, defines a width cutoff, searches for one, or evaluates any outcome. Case traces are chosen by structural order alone.

## THE POPULATION

- TEACH: 36250 closed candles; 2119 controlling-structure episodes over 101 distinct structures; 14675 candles had a controlling structure.
  - **cluster**: 2095/2119 episodes (rate 0.988674); distinct structures 100; candles controlled 14353.
  - **range**: 24/2119 episodes (rate 0.011326); distinct structures 4; candles controlled 322.
- VALIDATE aggregate: 5275 closed candles; 273 controlling-structure episodes over 38 distinct structures; 1879 candles had a controlling structure.
  - **cluster**: 273/273 episodes (rate 1.0); distinct structures 38; candles controlled 1879.
  - **range**: 0/273 episodes (rate 0.0); distinct structures 0; candles controlled 0.

## WIDTH DISTRIBUTIONS

- TEACH cluster: width points n 2095 | min 18.6445 | p25 48.2885 | median 61.968 | p75 88.64 | max 484.3945.
- TEACH cluster: width ATR n 2095 | min 0.206475 | p25 0.886268 | median 1.165175 | p75 1.6 | max 13.730003.
- TEACH range: width points n 24 | min 66.6 | p25 117.7 | median 117.7 | p75 117.7 | max 337.95.
- TEACH range: width ATR n 24 | min 1.349345 | p25 1.790591 | median 2.159991 | p75 2.393493 | max 2.813612.
- TEACH per candle: controlling width points n 14675 | min 18.6445 | p25 53.13 | median 74.26375 | p75 110.2475 | max 484.3945; width ATR n 14675 | min 0.206475 | p25 1.047638 | median 1.454716 | p75 2.251056 | max 16.349489.
- VALIDATE aggregate cluster: width points n 273 | min 33.52125 | p25 55.7515 | median 66.665 | p75 90.8275 | max 389.869.
- VALIDATE aggregate cluster: width ATR n 273 | min 0.424312 | p25 0.9 | median 1.1 | p75 1.5 | max 8.29288.
- VALIDATE aggregate range: width points n 0 | min None | p25 None | median None | p75 None | max None.
- VALIDATE aggregate range: width ATR n 0 | min None | p25 None | median None | p75 None | max None.
- VALIDATE aggregate per candle: controlling width points n 1879 | min 33.52125 | p25 56.61375 | median 67.72025 | p75 129.645 | max 389.869; width ATR n 1879 | min 0.352086 | p25 1.001201 | median 1.313964 | p75 1.915852 | max 9.252854.

## INTERNAL ROOM

- TEACH cluster at the first lower-edge encounter (661 episodes): room to midpoint n 661 | min 2.21675 | p25 21.49 | median 32.11 | p75 52.008 | max 310.883375; room to opposite edge n 661 | min 15.701 | p25 45.87 | median 64.01875 | p75 96.815 | max 455.841.
- TEACH cluster at the first upper-edge encounter (684 episodes): room to midpoint n 684 | min 3.8495 | p25 23.244 | median 34.657688 | p75 54.5875 | max 616.82425; room to opposite edge n 684 | min 17.1325 | p25 49.579 | median 66.82175 | p75 99.85 | max 859.0215.
- TEACH range at the first lower-edge encounter (4 episodes): room to midpoint n 4 | min 48.85 | p25 48.85 | median 90.575 | p75 97.5 | max 190.125; room to opposite edge n 4 | min 82.15 | p25 82.15 | median 151.35 | p75 156.35 | max 359.1.
- TEACH range at the first upper-edge encounter (12 episodes): room to midpoint n 12 | min 45.05 | p25 49.85 | median 62.15 | p75 68.9 | max 106.5; room to opposite edge n 12 | min 78.35 | p25 108.7 | median 121.675 | p75 127.75 | max 165.35.
- TEACH per candle: room to midpoint n 14675 | min 0.0 | p25 2.401 | median 18.41875 | p75 38.86525 | max 813.793125; room to opposite edge n 7518 | min 0.0 | p25 20.78875 | median 44.878875 | p75 74.0375 | max 591.92675.
- VALIDATE aggregate cluster at the first lower-edge encounter (71 episodes): room to midpoint n 71 | min 8.708125 | p25 25.6175 | median 40.53 | p75 66.70625 | max 397.171; room to opposite edge n 71 | min 27.42525 | p25 51.7635 | median 74.43 | p75 119.588 | max 465.97575.
- VALIDATE aggregate cluster at the first upper-edge encounter (98 episodes): room to midpoint n 98 | min 6.555 | p25 21.418 | median 34.765313 | p75 52.4725 | max 300.703875; room to opposite edge n 98 | min 28.02875 | p25 51.219 | median 67.86825 | p75 90.24975 | max 409.369.
- VALIDATE aggregate range at the first lower-edge encounter (0 episodes): room to midpoint n 0 | min None | p25 None | median None | p75 None | max None; room to opposite edge n 0 | min None | p25 None | median None | p75 None | max None.
- VALIDATE aggregate range at the first upper-edge encounter (0 episodes): room to midpoint n 0 | min None | p25 None | median None | p75 None | max None; room to opposite edge n 0 | min None | p25 None | median None | p75 None | max None.
- VALIDATE aggregate per candle: room to midpoint n 1879 | min 0.0 | p25 3.365 | median 19.3345 | p75 41.99 | max 1627.364; room to opposite edge n 862 | min 0.0 | p25 16.806 | median 42.111 | p75 70.84175 | max 1085.02425.

## EXTERNAL ROOM

- TEACH: candles with a mapped reference above 32429; below 34604; neither 0.
- TEACH: room from the upper edge to the next reference n 13098 | min 0.29175 | p25 16.49875 | median 36.45325 | p75 64.07875 | max 960.3425.
- TEACH: room from the lower edge to the next reference n 13986 | min 0.29175 | p25 19.06525 | median 39.501 | p75 80.71275 | max 1257.302.
- TEACH: internal width n 2119 | min 18.6445 | p25 48.2985 | median 62.57375 | p75 88.8355 | max 484.3945; episodes where mapped room above exceeds internal width 467/1897; below 647/2027.
- VALIDATE aggregate: candles with a mapped reference above 4910; below 4153; neither 0.
- VALIDATE aggregate: room from the upper edge to the next reference n 1754 | min 0.12875 | p25 14.841211 | median 57.57825 | p75 172.827 | max 1794.992.
- VALIDATE aggregate: room from the lower edge to the next reference n 1422 | min 0.20875 | p25 17.9685 | median 49.70775 | p75 100.56825 | max 986.3.
- VALIDATE aggregate: internal width n 273 | min 33.52125 | p25 55.7515 | median 66.665 | p75 90.8275 | max 389.869; episodes where mapped room above exceeds internal width 93/251; below 90/221.

## WHAT THE MACHINE SEES ON A CANDLE

- TEACH internal space states: `{"AT_EDGE_DECISION": 1983, "INTERNAL_GEOMETRY_AVAILABLE": 2641, "INTERNAL_GEOMETRY_CONSUMED": 1988, "NO_MAPPED_SPACE": 317, "OUTSIDE_REFERENCE_AVAILABLE": 25448, "UNKNOWN": 3873}`.
- TEACH movement origin roles: `{"BROAD_LOWER_EDGE": 5342, "BROAD_UPPER_EDGE": 5816, "NONE": 2597, "RELEASED_EDGE": 22495}`.
- TEACH movement segments: `{"MIDPOINT_TO_OPPOSITE_EDGE": 3172, "NO_STRUCTURAL_SEGMENT": 6237, "ORIGIN_TO_MIDPOINT": 4346, "OUTSIDE_EDGE_TO_MAPPED_REFERENCE": 22495}`.
- TEACH structural events: `{"ACCEPTED_RELEASE_DOWN": 938, "ACCEPTED_RELEASE_UP": 976, "CONTROLLING_STRUCTURE_REPLACED": 763, "LOWER_EDGE_ORIGIN": 665, "MIDPOINT_CROSSED": 673, "NEW_LOCAL_STRUCTURE_OBSERVED": 1982, "OPPOSITE_EDGE_REACHED": 531, "REENTRY": 545, "STRUCTURE_BECAME_CONTROLLING": 598, "UPPER_EDGE_ORIGIN": 696}`.
- TEACH price containment: `{"ABOVE": 2102, "ABSENT": 21575, "BELOW": 2088, "INSIDE": 10485}`.
- TEACH: candles with a micro 2383; with an observational local structure 1982.
- VALIDATE aggregate internal space states: `{"AT_EDGE_DECISION": 264, "INTERNAL_GEOMETRY_AVAILABLE": 273, "INTERNAL_GEOMETRY_CONSUMED": 212, "NO_MAPPED_SPACE": 76, "OUTSIDE_REFERENCE_AVAILABLE": 3869, "UNKNOWN": 581}`.
- VALIDATE aggregate movement origin roles: `{"BROAD_LOWER_EDGE": 639, "BROAD_UPPER_EDGE": 719, "NONE": 460, "RELEASED_EDGE": 3457}`.
- VALIDATE aggregate movement segments: `{"MIDPOINT_TO_OPPOSITE_EDGE": 376, "NO_STRUCTURAL_SEGMENT": 956, "ORIGIN_TO_MIDPOINT": 486, "OUTSIDE_EDGE_TO_MAPPED_REFERENCE": 3457}`.
- VALIDATE aggregate structural events: `{"ACCEPTED_RELEASE_DOWN": 134, "ACCEPTED_RELEASE_UP": 114, "CONTROLLING_STRUCTURE_REPLACED": 103, "LOWER_EDGE_ORIGIN": 71, "MIDPOINT_CROSSED": 96, "NEW_LOCAL_STRUCTURE_OBSERVED": 254, "OPPOSITE_EDGE_REACHED": 72, "REENTRY": 82, "STRUCTURE_BECAME_CONTROLLING": 66, "UPPER_EDGE_ORIGIN": 98}`.
- VALIDATE aggregate price containment: `{"ABOVE": 265, "ABSENT": 3396, "BELOW": 284, "INSIDE": 1330}`.
- VALIDATE aggregate: candles with a micro 324; with an observational local structure 254.

## MOVEMENT AND PROVENANCE

- TEACH cluster: midpoint crossed in 667/2095 episodes; opposite edge reached in 526; followed by an accepted release 1890; reentry in 539; a local structure formed inside 358; a micro in 295.
- TEACH range: midpoint crossed in 6/24 episodes; opposite edge reached in 5; followed by an accepted release 24; reentry in 6; a local structure formed inside 6; a micro in 5.
- VALIDATE aggregate cluster: midpoint crossed in 96/273 episodes; opposite edge reached in 72; followed by an accepted release 248; reentry in 82; a local structure formed inside 53; a micro in 45.
- VALIDATE aggregate range: midpoint crossed in 0/0 episodes; opposite edge reached in 0; followed by an accepted release 0; reentry in 0; a local structure formed inside 0; a micro in 0.

## THE OBSERVATIONAL ANCHOR AGREES WITH THE BRAIN

- Compared candle-for-candle over 36250 TEACH candles: **0 mismatches**. The brain's anchor remains the decision authority; this layer never feeds it.

## TEACH CASE TRACES

- Selection rule: deterministic structural ordering on width, kind, mapped room and observed structural events, then structure id and first index. No future outcome and no profitability is used to choose a case.

### NARROWEST CONTROLLING STRUCTURES

- `C06` cluster width 18.6445 pts / 0.5364166007336546 ATR over 4 candles; midpoint crossed False; opposite edge reached False; released True.
- `C06` cluster width 18.6445 pts / 0.47183348095659877 ATR over 3 candles; midpoint crossed False; opposite edge reached False; released True.
- `C06` cluster width 18.6445 pts / 0.45516020750686603 ATR over 2 candles; midpoint crossed False; opposite edge reached False; released True.

```text
2023-11-29 12:55  c793  close 44,314.2
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.54 ATR
PRICE         INSIDE (INSIDE) | to low 17.1 | to mid 7.8 | to high 1.5
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above none n/a | below C05.high 52.0
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,306.3
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        STRUCTURE_BECAME_CONTROLLING, UPPER_EDGE_ORIGIN
PROVENANCE    c776 ACCEPTED_RELEASE_UP L05 (cluster) @ 44,129.8 -> c793 STRUCTURE_BECAME_CONTROLLING C06 (cluster) @ 44,315.7 -> c793 UPPER_EDGE_ORIGIN C06 (cluster) @ 44,315.7
2023-11-29 13:00  c794  close 44,303.3
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.54 ATR
PRICE         AT_LOWER_EDGE (INSIDE) | to low 6.3 | to mid -3.0 | to high 12.4
INTERNAL      AT_EDGE_DECISION | next landmark none n/a | to opposite edge n/a
EXTERNAL      above none n/a | below C05.high 41.1
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,306.3
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    c776 ACCEPTED_RELEASE_UP L05 (cluster) @ 44,129.8 -> c793 STRUCTURE_BECAME_CONTROLLING C06 (cluster) @ 44,315.7 -> c793 UPPER_EDGE_ORIGIN C06 (cluster) @ 44,315.7
2023-11-29 13:05  c795  close 44,296.5
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.53 ATR
```

### WIDEST CONTROLLING STRUCTURES

- `C12` cluster width 484.3945 pts / 5.4763234504395015 ATR over 5 candles; midpoint crossed False; opposite edge reached False; released True.
- `C12` cluster width 484.3945 pts / 5.38844763335002 ATR over 8 candles; midpoint crossed False; opposite edge reached False; released True.
- `C12` cluster width 484.3945 pts / 7.279749023143974 ATR over 121 candles; midpoint crossed True; opposite edge reached True; released True.

```text
2024-04-22 10:40  c2266  close 47,684.1
CONTROLLING   C12 cluster 47,274.3 / 47,516.5 / 47,758.7 | width 484.4 pts / 5.48 ATR
PRICE         INSIDE (INSIDE) | to low 409.7 | to mid 167.5 | to high 74.7
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C10.low 123.4 | below C11.low 421.1
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 47,516.5
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        REENTRY
PROVENANCE    c2251 ACCEPTED_RELEASE_UP C12 (cluster) @ 47,758.7 -> c2266 REENTRY C12 (cluster) @ 47,684.1
2024-04-22 10:45  c2267  close 47,750.8
CONTROLLING   C12 cluster 47,274.3 / 47,516.5 / 47,758.7 | width 484.4 pts / 5.35 ATR
PRICE         AT_UPPER_EDGE (INSIDE) | to low 476.5 | to mid 234.3 | to high 7.9
INTERNAL      AT_EDGE_DECISION | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C10.low 56.6 | below C11.low 487.8
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 47,516.5
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    c2251 ACCEPTED_RELEASE_UP C12 (cluster) @ 47,758.7 -> c2266 REENTRY C12 (cluster) @ 47,684.1
2024-04-22 10:50  c2268  close 47,760.2
CONTROLLING   C12 cluster 47,274.3 / 47,516.5 / 47,758.7 | width 484.4 pts / 5.46 ATR
```

### RANGE KIND STRUCTURES

- `R01` range width 337.95 pts / 2.8136122385263813 ATR over 66 candles; midpoint crossed False; opposite edge reached False; released True.
- `L41` range width 125.40 pts / 2.5930521091811416 ATR over 9 candles; midpoint crossed False; opposite edge reached False; released True.
- `L41` range width 125.40 pts / 1.3571061389031682 ATR over 17 candles; midpoint crossed True; opposite edge reached True; released True.

```text
2024-03-12 12:15  c410  close 47,266.1
CONTROLLING   R01 range 47,191.7 / 47,360.6 / 47,529.6 | width 337.9 pts / 2.81 ATR
PRICE         INSIDE (INSIDE) | to low 74.4 | to mid -94.6 | to high 263.6
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C05.low 266.4 | below none n/a
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 47,360.6
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    no recorded provenance
2024-03-12 12:20  c411  close 47,285.3
CONTROLLING   R01 range 47,191.7 / 47,360.6 / 47,529.6 | width 337.9 pts / 2.84 ATR
PRICE         INSIDE (INSIDE) | to low 93.7 | to mid -75.3 | to high 244.3
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C05.low 247.1 | below none n/a
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 47,360.6
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    no recorded provenance
2024-03-12 12:25  c412  close 47,253.7
CONTROLLING   R01 range 47,191.7 / 47,360.6 / 47,529.6 | width 337.9 pts / 3.32 ATR
```

### LEAST INTERNAL ROOM AT LOWER EDGE

- `L06` cluster width 26.9685 pts / 0.393026560279812 ATR over 12 candles; midpoint crossed False; opposite edge reached False; released True.
- `L48` cluster width 28.3880 pts / 0.6162930800542741 ATR over 2 candles; midpoint crossed False; opposite edge reached False; released False.
- `L11` cluster width 35.10750 pts / 0.4914607685308322 ATR over 2 candles; midpoint crossed False; opposite edge reached False; released True.

```text
2023-11-30 11:20  c849  close 44,353.2
CONTROLLING   L06 cluster 44,341.9 / 44,355.4 / 44,368.9 | width 27.0 pts / 0.39 ATR
PRICE         INSIDE (INSIDE) | to low 11.3 | to mid -2.2 | to high 15.7
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above L07.high 82.4 | below C06.high 37.5
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,355.4
LOCAL         micro L07.m1 COLLAPSED (INSIDE) | local none (ABSENT)
EVENTS        CONTROLLING_STRUCTURE_REPLACED, LOWER_EDGE_ORIGIN
PROVENANCE    c846 LOWER_EDGE_ORIGIN L07 (cluster) @ 44,361.9 -> c849 CONTROLLING_STRUCTURE_REPLACED L06 (cluster) @ 44,341.9 -> c849 LOWER_EDGE_ORIGIN L06 (cluster) @ 44,341.9
2023-11-30 11:25  c850  close 44,342.2
CONTROLLING   L06 cluster 44,341.9 / 44,355.4 / 44,368.9 | width 27.0 pts / 0.40 ATR
PRICE         AT_LOWER_EDGE (INSIDE) | to low 0.3 | to mid -13.2 | to high 26.7
INTERNAL      AT_EDGE_DECISION | next landmark none n/a | to opposite edge n/a
EXTERNAL      above L07.high 93.4 | below C06.high 26.5
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,355.4
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    c846 LOWER_EDGE_ORIGIN L07 (cluster) @ 44,361.9 -> c849 CONTROLLING_STRUCTURE_REPLACED L06 (cluster) @ 44,341.9 -> c849 LOWER_EDGE_ORIGIN L06 (cluster) @ 44,341.9
2023-11-30 11:30  c851  close 44,348.3
CONTROLLING   L06 cluster 44,341.9 / 44,355.4 / 44,368.9 | width 27.0 pts / 0.45 ATR
```

### MOST INTERNAL ROOM AT LOWER EDGE

- `C03` cluster width 413.41250 pts / 3.426756739954825 ATR over 2 candles; midpoint crossed False; opposite edge reached False; released True.
- `C06` cluster width 430.4385 pts / 6.269358773622693 ATR over 35 candles; midpoint crossed False; opposite edge reached False; released True.
- `L26` cluster width 231.0315 pts / 2.27443577563929 ATR over 3 candles; midpoint crossed False; opposite edge reached False; released True.

```text
2026-06-05 10:35  c1740  close 54,508.8
CONTROLLING   C03 cluster 54,370.5 / 54,577.2 / 54,783.9 | width 413.4 pts / 3.43 ATR
PRICE         INSIDE (INSIDE) | to low 138.3 | to mid -68.4 | to high 275.1
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C02.high 416.9 | below L06.high 175.0
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 54,577.2
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    no recorded provenance
2026-06-05 10:40  c1741  close 54,328.1
CONTROLLING   C03 cluster 54,370.5 / 54,577.2 / 54,783.9 | width 413.4 pts / 3.19 ATR
PRICE         BELOW (BELOW) | to low -42.4 | to mid -249.1 | to high 455.8
INTERNAL      OUTSIDE_REFERENCE_AVAILABLE | next landmark none n/a | to opposite edge n/a
EXTERNAL      above C02.high 597.6 | below L06.high 5.7
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 54,577.2
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        CONTROLLING_STRUCTURE_REPLACED, LOWER_EDGE_ORIGIN
PROVENANCE    c1741 CONTROLLING_STRUCTURE_REPLACED C03 (cluster) @ 54,370.5 -> c1741 LOWER_EDGE_ORIGIN C03 (cluster) @ 54,370.5
```

### EDGE RELEASE EPISODES

- `C06` cluster width 18.6445 pts / 0.5364166007336546 ATR over 4 candles; midpoint crossed False; opposite edge reached False; released True.
- `C06` cluster width 18.6445 pts / 0.47183348095659877 ATR over 3 candles; midpoint crossed False; opposite edge reached False; released True.
- `C06` cluster width 18.6445 pts / 0.45516020750686603 ATR over 2 candles; midpoint crossed False; opposite edge reached False; released True.

```text
2023-11-29 12:55  c793  close 44,314.2
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.54 ATR
PRICE         INSIDE (INSIDE) | to low 17.1 | to mid 7.8 | to high 1.5
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above none n/a | below C05.high 52.0
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,306.3
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        STRUCTURE_BECAME_CONTROLLING, UPPER_EDGE_ORIGIN
PROVENANCE    c776 ACCEPTED_RELEASE_UP L05 (cluster) @ 44,129.8 -> c793 STRUCTURE_BECAME_CONTROLLING C06 (cluster) @ 44,315.7 -> c793 UPPER_EDGE_ORIGIN C06 (cluster) @ 44,315.7
2023-11-29 13:00  c794  close 44,303.3
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.54 ATR
PRICE         AT_LOWER_EDGE (INSIDE) | to low 6.3 | to mid -3.0 | to high 12.4
INTERNAL      AT_EDGE_DECISION | next landmark none n/a | to opposite edge n/a
EXTERNAL      above none n/a | below C05.high 41.1
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 44,306.3
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    c776 ACCEPTED_RELEASE_UP L05 (cluster) @ 44,129.8 -> c793 STRUCTURE_BECAME_CONTROLLING C06 (cluster) @ 44,315.7 -> c793 UPPER_EDGE_ORIGIN C06 (cluster) @ 44,315.7
2023-11-29 13:05  c795  close 44,296.5
CONTROLLING   C06 cluster 44,297.0 / 44,306.3 / 44,315.7 | width 18.6 pts / 0.53 ATR
```

### INTERNAL EDGE TO EDGE EPISODES

- `L01` cluster width 27.672 pts / 0.8213713268032057 ATR over 5 candles; midpoint crossed True; opposite edge reached True; released True.
- `L48` cluster width 28.3880 pts / 0.8 ATR over 11 candles; midpoint crossed True; opposite edge reached True; released True.
- `L26` cluster width 30.91275 pts / 0.9 ATR over 4 candles; midpoint crossed True; opposite edge reached True; released True.

```text
2023-11-23 12:05  c558  close 43,533.8
CONTROLLING   L01 cluster 43,531.6 / 43,545.4 / 43,559.3 | width 27.7 pts / 0.82 ATR
PRICE         INSIDE (INSIDE) | to low 2.3 | to mid -11.6 | to high 25.4
INTERNAL      UNKNOWN | next landmark none n/a | to opposite edge n/a
EXTERNAL      above L03.low 33.7 | below L02.high 202.8
MOVEMENT      not established | travelled n/a | whole n/a | segment NO_STRUCTURAL_SEGMENT n/a
PATH MIDPOINT n/a   BROAD MIDPOINT 43,545.4
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        STRUCTURE_BECAME_CONTROLLING, LOWER_EDGE_ORIGIN
PROVENANCE    c554 ACCEPTED_RELEASE_DOWN L03 (cluster) @ 43,567.5 -> c558 STRUCTURE_BECAME_CONTROLLING L01 (cluster) @ 43,531.6 -> c558 LOWER_EDGE_ORIGIN L01 (cluster) @ 43,531.6
2023-11-23 12:10  c559  close 43,540.8
CONTROLLING   L01 cluster 43,531.6 / 43,545.4 / 43,559.3 | width 27.7 pts / 0.86 ATR
PRICE         INSIDE (INSIDE) | to low 9.2 | to mid -4.6 | to high 18.5
INTERNAL      INTERNAL_GEOMETRY_AVAILABLE | next landmark BROAD_MIDPOINT 4.6 | to opposite edge 18.5
EXTERNAL      above L03.low 26.7 | below L02.high 209.7
MOVEMENT      UP from L01.low (BROAD_LOWER_EDGE, cluster) @ 43,531.6 | travelled 9.2 | whole 0.333 | segment ORIGIN_TO_MIDPOINT 0.666
PATH MIDPOINT 43,545.4   BROAD MIDPOINT 43,545.4
LOCAL         micro none ABSENT (ABSENT) | local none (ABSENT)
EVENTS        none
PROVENANCE    c554 ACCEPTED_RELEASE_DOWN L03 (cluster) @ 43,567.5 -> c558 STRUCTURE_BECAME_CONTROLLING L01 (cluster) @ 43,531.6 -> c558 LOWER_EDGE_ORIGIN L01 (cluster) @ 43,531.6
2023-11-23 12:15  c560  close 43,524.8
CONTROLLING   L01 cluster 43,531.6 / 43,545.4 / 43,559.3 | width 27.7 pts / 0.91 ATR
```


## HUMAN REVIEW — THE QUESTIONS THIS OPENS

1. Which controlling structures actually have meaningful internal room, and is that a property of the structure or of where price entered it?
2. When the controlling structure is a compressed cluster, does the movement that matters more often happen beyond its edge than inside it?
3. Does movement provenance distinguish price *arriving* into a structure with momentum from price *rotating* inside one it has been in for a while?
4. Do observational local structures form inside the wider controlling structures often enough to carry entry and risk themselves?
5. Should the controlling structure define context while a local structure defines entry and invalidation?

These are not answered here, and answering them by fitting a width cutoff to this same already-observed data would repeat the mistake the V1-V3 rotation work already made.

## PRESERVED RESEARCH STATUS

- R2_CLUSTER: **INCONCLUSIVE**.
- R2_RANGE: **INSUFFICIENT_POPULATION**.
- R4_MICRO: **INCONCLUSIVE**.
- LOCAL_PUBLICATION: **NO**.
- Nothing in this study promotes cluster over range, range over cluster, Micro or Local. A width distribution is not an edge.

## INTEGRITY

- The geometry layer is read-only: it never writes to the map, the frontier, the detectors, the references, the thesis or the brain.
- No brain module was modified by this milestone.
- VALIDATE is aggregate-only; no case traces, IDs, timestamps or prices.
- HOLDOUT_PRICE_SESSIONS_CONVERTED = 0.
- No broker, live money, parameter optimization, score, confidence, probability, ranking, width threshold or entry rule.

## GATES

- G1_CONTROLLING_KIND_VISIBLE: **YES**. cluster and range are reported separately and the role never renames the kind.
- G2_GEOMETRY_CAUSAL: **YES**. one frozen geometry per closed candle; a fresh replay to k reproduces the prefix.
- G3_INTERNAL_SPACE_VISIBLE: **YES**. room to midpoint and to the opposite edge exist wherever a controlling structure does.
- G4_EXTERNAL_SPACE_VISIBLE: **YES**. immediate references above and below are copied, and absent stays absent.
- G5_MOVEMENT_ORIGIN_VISIBLE: **YES**. every established movement names its origin index, price, reference, structure and role.
- G6_PROVENANCE_CAUSAL: **YES**. the provenance chain holds only current-or-earlier events, and the observational movement anchor was compared candle-for-candle against the brain's over 36250 TEACH candles with 0 mismatches.
- G7_LOCAL_BROAD_SEPARATED: **YES**. Broad, Micro and observational Local are separate fields and are never merged.
- G8_REPLAY_HUMAN_INSPECTABLE: **YES**. the dashboard renders the geometry panel per candle and tools/structure_inspector.py prints the same facts candle by candle.
- G9_BRAIN_BEHAVIOUR_UNCHANGED: **YES**. this milestone adds a read-only layer; no brain module was modified and the frozen V1/V2/V3 fingerprints are reproduced by their own study tools.
- G10_READY_FOR_ENTRY_ARCHITECTURE_DISCUSSION: **YES**. enough geometry is visible to design entry architecture. This is not readiness to trade, and no entry rule is proposed here.

## NEXT DECISION

- Use the newly visible structure geometry and replay traces to decide whether participation should be modeled as (a) internal rotation inside genuinely spacious controlling structures, and/or (b) edge release / local-structure participation when the controlling Broad is compressed.
- Do not implement either until that decision is preregistered.
