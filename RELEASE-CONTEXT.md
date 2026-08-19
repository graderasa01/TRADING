# RELEASE CONTEXT — field audit and design record

> Stage 1 of the reactive-trader build. **Observation only.** No entry, no order, no sizing,
> no risk, no exit engine, no threshold, no score. `EXECUTION_STATUS` stays `UNAVAILABLE`.
>
> Production surface: `src/livemap/release.py` — **one new file, inside the existing
> quarantine.** No existing file in `src/` was modified. The plan had allowed for a public
> `pool()` accessor on `interpreter.py`; it turned out not to be needed, because the pool
> rule is two lines and `release.py` states it with the reason attached.

---

## 1. WHY THIS LAYER EXISTS

The Participation Context Study found the stack could not answer, at the candle it matters:

```
WHAT EXACTLY BROKE?          the current structure is finalised on the release candle
WHICH SCALE BROKE?           outer and inner boundaries can break on the SAME candle
WHERE IS PRICE NOW?          PRICE_LOCATION = NO_STRUCTURE on 82% of releases
WHAT PATH REMAINS?           route is measured from the CURRENT edge, not the broken one
```

Trace F of that study is the case in one line: at block 0 candle 410, `C05.high` (outer) and
`C09.high` (inner) broke together and **every published field was identical** for the two.
This layer makes those two readings different, causally, on the candle itself.

---

## 2. §22 FIELD AUDIT

For every field the brief asks for: source, causality, and whether it is a copy.

| field | source | causal at the candle | copy or derived |
|---|---|---|---|
| `release_id` | assigned in observation order, `RL01…` | yes | new label |
| `index` / `at` / `price` | `Reading.index`, `Candle.close_time`, `Candle.c` | yes | copy |
| `scale` | which of the three sources emitted it | yes | new label |
| `direction` | `BreakRecord.direction` / scan side / `MICRO_BREAK_UP\|DOWN` | yes | copy |
| `broken_id` | `BreakRecord.structure_id` / `Node.id` / `MicroView.micro_id` | yes | copy |
| `broken_edge` | `BreakRecord.edge` / `Node.high\|low` / `MicroView.micro_high\|low` | yes | copy |
| `broken_low` / `broken_high` | `BreakRecord.low/high` / `Node.low/high` / `MicroView.micro_low/high` | yes | copy |
| `broken_kind` | `BreakRecord.kind` / `Node.kind` / `micro` | yes | copy |
| `parent_id/low/high` | `Reading.node_id` + `Reading.band` (outer parent of an inner release); `MicroView.parent_*` for micro | yes | copy |
| `position_before` | close at `i−BREAK_CLOSES` against the broken band | yes | arithmetic on prior candles |
| `beyond` / `beyond_atr` | `price − broken_edge`, signed into the break direction; `atr_at` | yes | arithmetic, `retest.py`'s own sense |
| `location` | `beyond` against `tol_at` | yes | derived label |
| `parent_location` | price against the parent band and `tol_at` | yes | derived label |
| `route` | `route.measure(first_in_price(pool, broken_edge), origin=broken_edge)` | yes | **existing machinery, new origin** |
| `corridor` | `route.build_corridor(pool, broken_edge)` | yes | **existing machinery, new origin** |
| `next_ref` / `far_ref` | `ZoneRoute.near_edge` / `far_edge` | yes | copy |
| `prior_node_id` / `prior_interaction` | `Reading` at `i−BREAK_CLOSES` | yes | copy |
| `arrived_from` / `arrived_direction` | `Reading.arrived_from`, `.arrived_direction` | yes | copy |
| `micro_state` / `micro_id` | `Reading.micro.micro_state`, `.micro_id` | yes | copy |
| `episode_id` | `EpisodeState.episode.id` | yes | copy |
| `origin` | `LOG` / `INNER_SCAN` / `MICRO_EVENT` — provenance of the identity | yes | new label |
| `controlling_scale` | derived from which releases exist and which are still held | yes | derived label |

**Fields deliberately NOT put on `Release`, because they belong to another world (§2 —
one thesis world):**

| field the brief lists | where it lives instead |
|---|---|
| `generation_id`, `generation_status` | `thesis.py` — joined at the participation layer |
| `thesis_at_release`, `thesis_status` | `thesis.py` |
| `current_generation_invalidation`, `invalidation_distance` | `thesis.py` (`invalidation_price`) |
| `opportunity_identity`, `position_state` | `decision.py` |

Putting a thesis field on a release record would make `src/livemap/release.py` depend on
the unvalidated thesis layer, and would give the observation world two copies of the
generation. The `ParticipationContext` composes the two; the release record stays a pure
structural observation.

---

## 3. THE THREE RELEASE SOURCES

```
OUTER   breaks.from_logs()          authoritative, already causal
MICRO   MicroView.events            MICRO_BREAK_UP / MICRO_BREAK_DOWN, already published
INNER   the one addition            see §4
```

**OUTER is not re-derived.** `frontier.py` records a `break` event in exactly one place —
the branch where `closes_beyond >= break_closes` for the structure that is current — so
every log break *is* an outer release by construction, and `breaks.from_logs()` already
resolves its geometry. The earlier study's own two-close rescan of the current band is
therefore dropped in favour of the log.

**MICRO is not re-derived.** `micro.py` already applies `BREAK_CLOSES` to the micro band and
emits `MICRO_BREAK_UP` / `MICRO_BREAK_DOWN`, and it deliberately keeps `_subject` — *"the
micro this candle was about"* — so the band that broke is still on the view on the break
candle. This layer reads the event and copies the band.

---

## 4. THE ONE ADDITION, STATED PLAINLY

There is no published event for *"a mapped structure inside the current one has released"*.
It is the fact the whole study said was missing, and it is the only thing here that is not a
copy.

```
boundaries    mapped nodes already in the map, price-contained in the current live band
rule          structure.BREAK_CLOSES consecutive closes beyond the edge, with the close
              before the run on the inside — the repo's own two-close transition rule
skirt         structure.tol_at(candles, i, frontier.tol_atr) — the repo's own
```

**What it does not do:** it creates no structure, mints no band, adds no score, adds no
threshold, adds no number, writes nothing to `_known`, `log`, `live_log` or the historical
map, and never changes a parent. It detects an *event on a structure the map already
published*, with the rule the map already uses.

The precedent is `micro.py`, which does exactly this one level down and says so:
`MICRO_BREAK  structure.BREAK_CLOSES  two closes, the same rule`.

**Containment is price-only, and that is deliberate.** `hierarchy._contains` also demands
time containment (`outer.start <= inner.start and inner.end <= outer.end`), which is correct
between two nodes of one historical scan and meaningless between a frozen node from an hour
ago and the live structure standing over it now. Price containment plus *strictly narrower*
is the honest test here, and it is applied with the existing `tol_at` skirt.

---

## 5. RELEASE, NOT CROSSING

A crossing **up through a structure's high** or **down through its low** leaves it: that is a
release. The mirror crossings walk back in, which the stack already calls `RE_ENTRY`.

The first Participation study counted both as releases and had to be corrected mid-flight —
441 of 908 teach crossings were re-entries, and the outer population fell from 295 to 203.
`release.py` therefore refuses inward crossings structurally, and
`test_a_reentry_is_never_a_release` pins it.

---

## 6. SIMULTANEOUS RELEASES (§5)

`ReleaseState.releases` is a **tuple**, never one record. When an outer and an inner boundary
break on the same candle both are emitted, both keep their own broken boundary, their own
parent and their own route origin. No priority order is applied, because none has been
measured. When two or more scales release together, `controlling_scale` is `MULTI_SCALE`
rather than a guess.

---

## 7. CONTROLLING SCALE (§11)

Derived from existing facts only — no score, no detector:

```
>= 2 scales released on this candle          MULTI_SCALE
exactly one scale released on this candle    that scale
no release this candle, but the newest       that release's scale
  release is still held (price still beyond
  its broken edge by more than tol)
otherwise                                    UNRESOLVED
```

"Still held" is `Release.beyond(price) > tol`, which is `retest.py`'s own sense of *outside*.

---

## 8. WHAT STAYS OUT

* no entry, no `ENTER_*`, no order, no broker, no sizing, no risk, no exit engine;
* no threshold, no score, no probability, no confidence, no ranking;
* no new clustering, no new micro detector, no second map, no second thesis engine;
* no write to `Frontier`, `MapSnapshot`, `log`, `live_log` or `_known`;
* `src/setups/` untouched and still independent; `split.holdout()` untouched.
