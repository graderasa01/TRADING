# THE ADAPTIVE CLUSTER-RANGE MAPPER — plan

> Replaces `src/boxes/map.py` (fixed 20-candle blocks) and `src/boxes/multi.py`.
> The heat map built before this was deleted at the trader's instruction; one piece of it
> survives inside §4.1 and is credited there.

---

## 0. THE ONE SENTENCE

Scan backwards from now at many window lengths, take the **smallest window in which a
cluster or a range is already stable**, freeze what it found, and let future candles be
judged against the frozen thing instead of moving it.

This produces an **evidence stream**, not a signal. It never says BUY or SELL. It says:
*here is what is above you, here is what you are standing in, here is what is below you,
and here is how price has been rotating between them.*

---

## 1. WHAT WAS WRONG BEFORE, IN ONE LINE EACH

| Old design | Why it failed |
|---|---|
| Fixed 20-candle blocks (`map.py`) | A block boundary is an accident of counting. Shift the stream by one candle and every "level" moves. |
| Re-derive every candle (`engine.py`) | The box widened to contain the candle that broke it, so a break could never be waited for. |
| Multi-window scan, no state (`scan.py`) | Same problem: no reference stayed put, so distance-to-target changed while price travelled toward it. |
| Heat map | Answered *"where has price spent time"*. That is a distribution, not a structure — it cannot tell a two-sided range from a slow trend, and it has no boundaries to break. |

**The common failure: none of them had an object that stays still and waits to be broken.**

---

## 2. THE PIPELINE

```
                 CANDLES (1m, closed only)
                    │
                    ↓
          ADAPTIVE ROLLING WINDOW          §3
          N = 8,10,12,15,18,22,27,33,40,50,60,75
          pick the SMALLEST N that is already stable
                    │
          ┌─────────┴─────────┐
          ↓                   ↓
    CLUSTER DETECTOR      RANGE DETECTOR    §4, §5
    occupancy             upper touches x2
    revisit               lower touches x2
    compression           rotation
    reaction              compression
          │  − migration        │  − migration       §6
          └─────────┬───────────┘
                    ↓
             ADMIT & FREEZE                 §7
        (already-live box? then nothing)
                    ↓
        ┌───────────┼───────────┐
        ↓           ↓           ↓
     CLUSTER      RANGE      EXTREME
       BOX         BOX         ZONE
        └───────────┼───────────┘
                    ↓
          ABOVE / CURRENT / BELOW           §8
          + HIGH→LOW / LOW→HIGH rotations   §9
```

---

## 3. THE ADAPTIVE WINDOW — "smallest stable", not "largest available"

Candidate lengths, roughly geometric so the scan is cheap and the coverage is even:

```
8, 10, 12, 15, 18, 22, 27, 33, 40, 50, 60, 75
```

For every N the detector runs on `candles[-N:]` and returns a proposal or nothing.

**A proposal is only usable if it is stable.** Stability means: the same kind of box, with
both edges within `tol`, is also proposed by the **next two larger windows**.

```
N =  8  → nothing
N = 10  → cluster 60,412-60,448
N = 12  → cluster 60,410-60,451     agrees
N = 15  → cluster 60,414-60,449     agrees        ← run of 3 starts at N=10
N = 18  → cluster 60,390-60,505     drifted
```

→ **choose N = 10.** The smallest window that had already found the thing.

Two reasons this rule matters more than it looks:

1. **It stops the giant box.** The old failure — price walking 100→110 and the engine
   drawing one 10-point-wide box over the whole walk — cannot happen, because a walk never
   produces the *same* boundaries at three successive window lengths. Each expansion adds
   more walk and moves the edges.
2. **It removes the window-length parameter entirely.** There is no "correct" N to guess.
   The market picks it, and it picks a different one at 09:30 than at 14:00.

If no run of three agrees at any N, **the answer is no box**. That is a real answer, and it
is the correct one during a trend.

---

## 4. CLUSTER BOX — acceptance

> *"Price repeatedly kis jagah wapas aa raha hai?"*

The **core** is the tightest contiguous price band holding at least half of the window's
minutes. Its edges are the cluster's edges.

### 4.1 Minutes, not candle-counts

Time-at-price is measured with **each candle contributing exactly 1.0**, spread evenly over
the prices it covered:

```
weight per price bucket = 1 / (buckets the candle spans)
```

This is the one idea kept from the deleted heat map, and it was kept because it was
measured, not because it was liked. Plain coverage — *"how many candles span this price"* —
gives a 120-point candle twenty-four times the vote of a 5-point candle, so the busiest
band comes back as the one where price was moving **fastest**. Exactly backwards.

### 4.2 The four measurements, each 0..1

| | definition | null (random walk) |
|---|---|---|
| **occupancy** | `max(0, 1 − 2 × core_width / range)` | 0 — a uniform window's half-minutes band is half its range |
| **revisit** | `min(1, (visits − 1) / 2)`; visits are separate stays, ≥`gap` candles apart | 0 — one stay is not a revisit |
| **compression** | `1 − range / Σ(candle ranges)` | ~0 for a one-way move |
| **reaction** | `min(1, wick_rejections / 4)` — high within `tol` of the edge, close back inside | 0 |

**Hard gate (the trader's own rule, not a tuned number): `visits ≥ 2`.** One stay is a
pause, not a cluster.

---

## 5. RANGE BOX — two-sided auction

> *"Range tabhi valid hai jab price uske andar rotate kar raha ho."*

A range is **not** a wide cluster. It is two boundaries that have each been defended, with
price travelling between them.

### 5.1 Hard gates — all three required

```
upper touches ≥ 2      distinct approaches within tol of the window high
lower touches ≥ 2      distinct approaches within tol of the window low
traverses     ≥ 2      full trips between the bottom third and the top third
```

A "distinct" touch means price left the boundary by more than `tol` and came back. Ten
consecutive candles grinding the high is **one** touch.

A "traverse" is a trip from the lower third of the range to the upper third or back. This
is the measurement that separates the two windows the trader wrote down:

```
100 → 109 → 102 → 108 → 101 → 110      4 traverses   → RANGE
100 → 102 → 104 → 106 → 108 → 110      0 traverses   → NOT A RANGE
```

Both have the same high and the same low. Only rotation tells them apart.

### 5.2 The four measurements, each 0..1

| | definition |
|---|---|
| **upper** | `min(1, (upper_touches − 1) / 2)` |
| **lower** | `min(1, (lower_touches − 1) / 2)` |
| **rotation** | `min(1, traverses / 3)` |
| **compression** | as §4.2 |

---

## 6. THE MIGRATION PENALTY — the anti-giant-box rule

```
migration = |close_last − close_first| / Σ|close_i − close_{i−1}|
```

Kaufman's efficiency ratio. **1.0 is a perfect staircase; 0 is pure rotation.** It has no
parameters and no units, and it is subtracted from both scores:

```
cluster_score = mean(occupancy, revisit, compression, reaction) − migration
range_score   = mean(upper, lower, rotation, compression)       − migration
```

Both land in `[−1, +1]`.

### Why a mean and not a weighted sum

The trader's sketch was `Occupancy + Revisit + Compression + Reaction − Migration`. Summing
quantities with different units means choosing four weights, and a threshold on the sum is
a fifth number — five free parameters on a dataset this size is how a model gets fitted to
noise. `CLAUDE.md` §6 forbids tuning more than two at once.

So every component is normalised to `0..1` against a stated null, and they are combined
with **equal weights**. That leaves exactly **one** tunable number per box type — the
score threshold — and every component is reported alongside the score, so which one is
carrying a decision is always visible.

**`min_score = 0.35` is a starting hypothesis and nothing more.** It is written in
`params.yaml`, marked HYPOTHESIS, and has not been validated against any outcome.

---

## 7. FREEZE — how a dynamic scan produces a static map

These two requirements look contradictory and are not:

> *"rolling window dynamic rakhenge"* and *"map first banayenge phir freeze"*

The resolution is that **the scan is dynamic; the map is not.**

* The scanner runs on **every** candle and proposes boxes continuously.
* A proposal whose edges fall within `tol` of a box already live in the map is **discarded** —
  it is the same box seen again, not a new one.
* A genuinely new proposal is **admitted, and its edges are frozen at birth.** They never
  move again for the rest of the box's life. Not when price pushes on them, not when the
  window changes, not when a later scan would draw them differently.
* A box **dies** only on a break: **two consecutive closes** beyond an edge by more than
  `tol`, where the candle before the first of them closed inside. One wick is not a break;
  the two-close rule is what stopped the same move being counted three times before.
* A dead box stays on the chart and in history — *"price yahan se nikli thi"* — but stops
  being a target.

So: distance-to-target is a real distance, a break is a real event, and the story told at
10:20 is still the same story at 10:38.

---

## 8. THE MAP HANDED TO THE TRADER

```
              ┌────────────┐
              │ HIGH ZONE  │   the extreme — how far it has ever got
              └────────────┘
              ┌────────────┐
              │   RANGE    │   next range above
              └────────────┘
              ┌────────────┐
              │  CLUSTER   │   nearest cluster above
              └────────────┘
                    ●          CURRENT — which box price is standing in, and where in it
              ┌────────────┐
              │  CLUSTER   │
              └────────────┘
              ┌────────────┐
              │   RANGE    │
              └────────────┘
              ┌────────────┐
              │ LOW ZONE   │
              └────────────┘
```

Six things above and below, no more: nearest cluster, next range, extreme zone. The engine
does not predict which one gets hit. It states the distances and lets the trader judge.

---

## 9. THE ROTATION MAP

Every traverse recorded as it completes:

```
10:04   60,812 → 60,648      HIGH → LOW    164 pts,  22 candles
11:35   60,648 → 60,790      LOW  → HIGH   142 pts,  41 candles
13:12   60,790 → 60,655      HIGH → LOW    135 pts,  18 candles
```

This is the structure a simple support/resistance list cannot show: how big the swings
are, how long they take, and whether they are getting smaller.

---

## 10. PARAMETERS — the complete list

| name | value | status |
|---|---|---|
| `windows` | 8…75, 12 lengths | structural — geometric coverage |
| `stability_run` | 3 | the trader's rule ("2-3 successive expansions") |
| `tol` | `0.25 × ATR20` | volatility-relative, never fixed points |
| `min_score` | 0.35 | **HYPOTHESIS — unvalidated** |
| `visit_gap` | `max(3, N // 6)` | window-relative |
| `break_closes` | 2 | structural — one wick is not a break |
| touch/traverse minimums | 2 / 2 / 2 | the trader's own rules |

One genuinely tunable number. Everything else is either the trader's stated rule, a
structural convention, or scaled by volatility.

---

## 11. WHAT THIS DOES NOT DO — read before believing the chart

1. **Nothing here has been measured against an outcome.** The last time boxes were tested
   end-to-end the answer was **19% win, −0.265R gross, −1.220R net over 790 trades**, and
   position-based grading was *inverted* — the "best" bucket was the worst. That test was
   on the old stateless engine, so it does not condemn this design, but it does mean this
   design starts at zero evidence, not at "probably better".
2. **`min_score` will want tuning, and tuning it is how this dies.** It must be set once
   from reasoning, then left alone while outcomes are measured — otherwise the score is
   fitted to the sample it was read on.
3. **A map that looks right is not a map that pays.** The previous two designs also looked
   right on a chart. The only thing that settles it is a measured, cost-inclusive result on
   days that were not looked at while building.
