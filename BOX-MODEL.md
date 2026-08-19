# THE BOX MODEL

> Price is never *near* something. Price is always **inside** three boxes at once.
> Break the small one to reach the middle one's edge. Break that to reach the big one's.

---

## 0. The mistake this document made twice, and the rule that fixes it

The first two drafts treated a box as an **object with an identity** — born, extended,
merged, frozen, woken, counted, capped. Each draft produced a new list of problems:

- when a break is annulled, revive the old box or merge it?
- how does a merged box avoid growing through chop?
- how many frozen boxes are kept before the count explodes?
- what happens to a box price gapped past?
- when exactly does a woken box become tradeable?

**All five are the same problem.** They are the level engine's disease in new clothes: 204
objects, death rules, a dormant pool, and a cap to hold back the flood. Answering them one
at a time produces five more parameters and a state machine nobody can audit.

A trader does not maintain a registry of boxes. They look at the chart **now** and ask
three questions — where did price come from, where is it stuck, where can it go — and
answer them again on the next candle, from what is on the screen.

> **THE RULE: boxes are DERIVED from the last N candles on every candle. They are never
> stored, never merged, never revived, never killed.**

There is no box identity, so there is nothing to maintain. Every problem in the list above
does not get solved — it stops existing.

This is what *"box hmko last candles se banani hoti"* means, taken literally.

---

## 1. One function, three lookbacks

```
box(candles, N) -> inner_low, inner_high, outer_low, outer_high
```

The same computation at three window sizes gives the three boxes:

| box | window | what it is |
|---|---|---|
| **L3** overlapping | short — tens of candles | where price is rotating right now |
| **L2** range | medium — a session's worth | the range price is working inside |
| **L1** pullback | long — crosses sessions | the move being retraced or extended |

Nothing else distinguishes them. Not a different algorithm, not a promotion rule, not a
graduation threshold. **One function, three numbers.**

### Why the box is a density band, not a high–low channel

The naive version — `[min low, max high]` over N candles — is a Donchian channel, and it
is wrong for the same reason a single spike ruins it: one candle poking out moves the edge
to somewhere price never traded.

The box is instead **the band where the most candles have been**:

```
for the last N candles, build a histogram of touched price
inner band = the contiguous region where candle coverage stays above density_min
outer band = the extreme wicks of those same candles
```

Two consequences, and both are the reason this survives real data:

**An excursion does not sever the box.** Price drops out, comes back, and the walk-back is
not broken — because there is no walk-back. The spike simply contributes one candle to a
region nobody else touched, and the dense band stays where price actually worked. This is
the *"price niche bhi aati to dobara upar bhi jati h"* case, and it needs no annulment
rule, no reclaim window, no `failed_break` record. **It is just what the candles look
like.**

**Inner and outer are the band and the wicks** — which is exactly `body_edge` and
`wick_tip`, the geometry the level engine already uses, applied to a box instead of a
line. So §3's three events survive unchanged.

### Where stability comes from, now that nothing freezes

Earlier drafts needed frozen boxes because a live edge cannot be a target — a running
extreme says only that price reached where price has already reached.

Stateless boxes solve this without a freeze mechanism: **stability comes from window
length.** L1 computed over several hundred candles barely moves when one new candle
arrives; it is dominated by history. It is *effectively* frozen without any code that
freezes it, and it is honest, because it reads only closed candles.

So the rule becomes simply: **targets come from the wider boxes, invalidation from the
narrow one.** No two states, no REFERENCE/TRADEABLE distinction, no waking.

### Memory is lookback

The one thing statelessness appears to lose is history — *"this edge was broken and
reclaimed at 11:04."*

It does not lose it. **Anything the engine should remember, it remembers by looking back
far enough to see it.** The candles that made that defence are inside L2's window, so the
density band still shows the edge. When they age out of the window, the market has stopped
caring too.

---

## 2. What this answers that the earlier drafts could not

| earlier problem | now |
|---|---|
| break annulled — revive or merge? | no boxes to revive. The candles are simply re-read |
| merged envelope grows through chop | nothing accumulates; each candle recomputes |
| how many frozen boxes kept? | none. Three boxes, always |
| price gapped past a box | recompute from the candles you have |
| woken box: reference or tradeable? | no waking. A box is whatever the window shows |
| **the first hour of the session** | **the lookback crosses the session boundary.** At 09:30, L1's window still contains yesterday. Nothing to load, nothing to inherit |
| the 8-level cap, grading score, dormant pool, five death rules | none of them exist |

The first-hour problem dissolving is worth stating plainly: there is no warm-up special
case, no *"load yesterday's frozen boxes"* mechanism, and no rule for what to do before
enough candles exist. **The window simply reaches back into yesterday**, which is what a
trader's eye does when they open the chart in the morning.

---

## 3. Boundaries are bands — three distinct events

| event | test |
|---|---|
| **touch** | price entered the band, no body close beyond `outer` |
| **sweep** | wick beyond `outer`, body closes back inside `inner` |
| **break** | body closes beyond `outer` |

A sweep is not a failed break and a break is not a big touch. Collapsing them is what
loses Setup B.

---

## 4. Direction and trend — derived, not computed

```
pos(box) = (close - box.inner_low) / (box.inner_high - box.inner_low)
```

Three numbers, one per box. Their configuration is the state:

| L1 | L2 | L3 | reading |
|---|---|---|---|
| high | high | breaking up | trend up, continuation |
| low | low | breaking up | reversal from the base of the big move |
| mid | mid | rotating | no direction — the state to sit out |
| high | low | breaking down | a pullback inside an up leg |

**Trend** is L1 and L2 agreeing. **Momentum** is L3. **Chop** is disagreement. This
replaces `control`, `trend_5m` and `regime` as separately-computed variables.

---

## 5. Targets, and where the move came from

> **The target is the far edge of the widest box price is currently traversing.** Edges
> below it are checkpoints, not destinations.

The trader's rule, unchanged:

> *"hm sabse niche se upar ja rahe h to hm ek pura pullback box hi banayenge us pure down
> move ka, na ki range box ke upar wala box."*

Statelessly, "where the move came from" is not a flag to record — it is `pos(L1)`. If
`pos(L1)` was near 0 and is rising, price is crossing L1 bottom-to-top, and L1's far edge
is the target. L2's edge is a checkpoint where a new L3 will form.

**Both sides are always planned.** Every candle holds two sentences: *if it breaks up,
target X; if it breaks down, target Y.* Writing both in advance is what stops the second
being invented afterwards.

---

## 6. Grade is position, not a score

Not every valid break is the same trade. The trader's rule does this better than a 0–4
score because it is visible on the chart:

| where L3 sits when it breaks up | grade | target |
|---|---|---|
| near the **low of both L1 and L2** | **best** | L1's far edge — the whole move |
| **middle of L2**, with L1 and L2 floors below | good | L2's high |
| anywhere else | scalp | L2's high, and only if the space check passes |

Mirror for shorts. Because grade is now `pos(L1)` and `pos(L2)` — two continuous numbers —
**it does not need a threshold.** The earlier draft's `edge_zone_pct` cliff, where a break
at 26% of box height was a scalp and 24% was a full-target trade, is gone. Position is a
gradient and grade can be one too.

---

## 7. L0 — the daily context

A wider window still: where the move on the daily is running.

It is not a fourth live box; it is the same function with the longest lookback.

**L0 sets the far targets. It does not grant or withhold permission.** That restriction is
the mirror of the cardinal rule: *"1m is never allowed to set direction"* stops the system
flipping twenty times a day, and the opposite failure is just as real — a daily downtrend
three sessions into a retrace would veto every long while the structure that actually pays
says up. L0 contributes the far boundary in each direction and never produces a rejection
on its own.

---

## 8. The three setups survive

| setup | in box terms |
|---|---|
| **A — flip retest** | break of an edge, then retest of it from the other side |
| **B — sweep reclaim** | wick beyond `outer`, body closes back inside `inner` |
| **C — range break retest** | the same as A, at L2 instead of L3 |

The trading logic does not change. Only spec 03 does.

**Open, not decided:** if A and C are one rule at two scales, they may be one
parameterised detector. `BUILD-BRIEF` §3 forbids a *fourth* setup, never fewer. Decide
after the model runs, not now.

---

## 9. The honest ledger

### What is still a guess

| parameter | what it controls |
|---|---|
| `density_min` | how much coverage makes a band. **The one genuinely new number** |
| `N3` / `N2` / `N1` | the three windows. More intuitive than the parameters they replace — "the last ten candles", "the last hour", "the last day" |
| L0's window | the daily context's lookback |

Three windows and one density. That is the whole parameter set, against the level engine's
grading weights, cap, TTLs, dormancy distances and death thresholds.

### What is genuinely at risk, and must be measured before this is built

**1. Flicker.** A density band over a rolling window can jump when the window rolls off an
old candle. If L2's edge moves 30 points because one candle aged out, every target moves
with it and the engine is unstable. **This is the single biggest risk in the design** and
it is directly measurable: run the boxes over real sessions and plot how far each edge
moves per candle. A stable box should barely move; a flickering one is unusable.

**2. Boxes are structure, not edge.** Everything here describes the market well. Describing
it well and profiting from it are different, and only §10 separates them.

**3. No-look-ahead, everywhere.** Every window reads closed candles at or before the
current one. There is no confirmed-pivot lag, because there are no pivots — which also
removes the *"L1 is always k candles late"* problem the earlier draft had to confess to.

---

## 10. The one claim that decides whether this is worth building

Structure is not edge. The testable claim:

> **When price body-closes out of L3 in the direction of the L1/L2 alignment, it reaches
> the next wider box's edge — before returning inside L3 — more often than chance.**

One hypothesis, one pre-registered prediction, one run over 27 months of `teach` data with
its base rate attached. `tools/hypothesis.py` exists for exactly this shape of question.

If it holds, build the box engine with confidence. If it does not, this is a very good way
of *describing* the market and not a way of trading it — and one day of measurement will
have saved a month of building.
