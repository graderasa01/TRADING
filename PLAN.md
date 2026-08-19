# PLAN — what gets built next, and how it gets checked

> Rewritten after the trader reviewed 10 sessions with the engine's book overlaid and
> accepted the levels. The previous version of this file argued for three level-engine
> fixes; two of those arguments were **measured and found wrong**, and the third was
> overruled by the person whose eye the gate exists to reproduce. Both facts are kept
> below rather than deleted — a plan that quietly drops its own retracted claims teaches
> nothing.

---

## 0. Where the build stands

| | |
|---|---|
| **Built and green** | P0 feed/config/models · P1 levels + structure + board · P2 guards, modes, session state, reachability |
| **Tools** | `chart.py` (zoom/pan/replay/zones) · `overlap.py` (P1 gate) · `level_report.py` · `hypothesis.py` · `annotate.py` · `startup_check.py` |
| **Tests** | 335 passing, 0 skipped · ruff clean · secret scan clean |
| **Next** | **P3 — setups A / B / C** |

### P1's gate — closed by the trader, and the number that disagreed

Spec 09 §3.2b makes the trader's eye the ground truth, and the trader has looked at 10
sessions with the book overlaid and said the levels are right. **That closes P1.**

The numeric score disagreed, and it is recorded here rather than buried:

```
overlap, Grade A book AT CLOSE, 9 marked sessions   17.2%
overlap, Grade A EVER during the session            89.1%   (noise 91.4%)
```

Three reasons the low number is the weaker evidence, in order of how much they matter:

1. **It scored the closing book against a full-day chart.** A level correctly killed at
   14:00 counts as a miss. 69% of the trader's lines *were* found by the engine and then
   died — mostly `broken` (31%) and `expired` (22%), which are the engine doing its job.
2. **The 89% figure is not a rescue either.** It matched 662 engine lines against 64
   human ones. Anything drawing 10x as many lines will "match" almost everything — spec
   11 §D3: *"that is not detection, that is arithmetic."*
3. **The ground truth is 80% repeatable.** 2025-12-19 was marked twice by accident, and
   the two markings agreed with each other 80% of the time. No score against this
   reference means much above that.

**What was measured and found wrong along the way**, kept as a record of how much
theorising survives contact with the data:

| claim | measurement | verdict |
|---|---|---|
| the lines cluster near the close | book spans 95% of the day's range | **wrong** |
| the 8-cap is the real selector | 1 of 64 human lines lost to the cap | **wrong** |
| the 90-minute TTL is too short | TTL 375 → overlap *fell* 17.2% → 15.6% | **wrong** |
| near-duplicate lines are a dedup bug | merge is implemented per D-011c; tolerance is `max(5 pts, 0.20 × ATR)` and two lines 11 pts apart are correctly distinct | **not a bug — a guess** |
| Setup A depends on LAUNCH levels | spec 06 A1 reads a **BREAK axis**; LAUNCH is a level *kind*, not a setup input | **wrong** |

The one genuinely open item is unchanged and is a trading judgement, not an engineering
one: **LAUNCH fires 0.08 per session against spec 10 §3.1's `>= 1` floor.**
`launch_base_atr_mult` at 0.8 gives 0.07; 1.0 / 1.2 / 1.5 give 1.32 / 2.27 / 3.70. Spec
03 §3 says *"this is the correct outcome; do not relax it."* Left alone.

---

## 1. P3 — setups A / B / C

Three. Not four. `test_registry_length_is_three` asserts it, because *"every additional
setup increases trade frequency, and trade frequency is the dominant cost and error
multiplier in this system."*

### 1.1 `setups/base.py` — the preconditions, checked before any detector runs

```
mode == ALERT
trigger level.grade == A
level.alive  and  level.touches < max_touches
no duplicate attempt at this level this session
not within cooldown
every candle involved: synthetic == False
setup not in GuardOutcome.blocked_setups          (spec 05 guard 6)
```

Plus one rule that must live in code, not convention:

> **At `kind == ANCHOR`, Setup B is the only permitted setup.**

Because the most-watched levels hold the most stops, so they are swept most often.
Taking a plain rejection at PDH/PDL without a sweep is standing on the wrong side of the
stop hunt.

### 1.2 Setup A — flip retest
*Highest frequency, smallest stop, trades with the trend.*

A BREAK axis exists within `axis_ttl_minutes` · the break was directional · price
returned within `retest_tolerance = max(8, 0.5 × ATR14)` · the axis **held** · a 1m
higher low formed · the trigger candle closed above the previous 1m high · trigger
`close_third == "top"` · bias filter passes.

`entry = trigger.close`, `extreme = the higher-low candle's low`. The stop hides behind a
1m swing that just proved itself — that is the whole point of the drill-down.

Rejections: `setup_stale` if the body closed back through the axis before the higher low,
or more than `retest_max_candles` (20) since the break; `bias_conflict` against the 5m
trend at a non-A level.

### 1.3 Setup B — sweep reclaim
*Best risk-reward, lowest frequency. Mandatory at ANCHOR levels.*

Sweep pierces `wick_tip` by `>= max(8, 0.4 × ATR14)` · wick `>= 0.55 ×` range · body
closes back inside within 2 candles · reclaim `>= max(5, 0.25 × ATR14)` beyond
`body_edge` · reclaim `close_third == "top"`.

`entry = reclaim.close`, `extreme = the sweep candle's low`.

**The known tension, already measured, must be built with all three answers logged.**
`prototype/FINDINGS.md` Bug 4: a textbook sweep at PDL produced `R = 69.1` against an
allowed 16.0–40.7 and was rejected. The conditions *force* a wide stop — B3 and B6
together mean `R ≈ 0.70 × candle_range + buffer`, so **the better the sweep, the worse
the R.** That is geometry, not a threshold to nudge.

Build `b_entry_mode: "pullback"` (the spec's recommended default: a limit entry within
`1.2 × ATR` of the sweep extreme, waiting up to 3 candles; if the pullback never comes
the trade is missed and that is acceptable) — **and log `entry_reclaim_close`,
`entry_pullback`, and whether the pullback arrived, on every Setup B decision.** After a
few months spec 09's counterfactual study settles this with data instead of argument.

Never move the stop closer than the sweep wick tip. That tip is where the stops were.

### 1.4 Setup C — range break retest
*Lowest frequency. Never on the breakout candle.*

Range valid only if formed over `>= 20` candles · `>= 2` touches top **and** bottom ·
width between 25 and 120 points · **no 1m body closed outside during formation**.
Then: break by body close, then retest — never the breakout candle itself.

### 1.5 The gate — BUILD-BRIEF §4b

Fixtures prove a detector fires on a sequence built for it. They do **not** prove it is
reachable inside the full pipeline, where guards, modes, grading and the cap all run
first. The dry run made this concrete: Setup B's six conditions all passed on a textbook
sweep and the detector never ran, because the mode was `BLOCKED`. A fixture test would
have been green.

So P3 closes on a full-session run, not on fixtures:

```
levels born ......................... > 20
levels reaching Grade A ............. > 0
candles in ALERT .................... > 0
setups DETECTED (reached evaluate) .. > 0
  of which A / B / C ................ each > 0 over ~10 sessions
setups rejected, by gate ............ the histogram
signals ............................. may legitimately be 0
```

**Signals may be zero. Detections may not be.** Any zero → stop and diagnose before P4.

---

## 2. The fixture problem — and what I need from you

`BUILD-BRIEF.md` §5 states it plainly, and I am not going to work around it:

> *"You cannot create these honestly. A fixture you generate to match your own
> implementation tests that the code does what the code does."*

So every fixture is written as a CSV **plus** an `expected.yaml` derived from the spec
text by hand **before** the code runs, and when one fails the default assumption is that
the code is wrong. Each is tagged `source: synthetic` or `source: real_chart`, and the
ratio is printed in the P3 report.

**What I am asking you for — the golden A/B/C fixtures, from real sessions you pick.**
Now that the chart replays candle by candle, this is much easier than it was: scrub to
the moment, and give me the date and candle index.

| I need | one clear real example of |
|---|---|
| **A** | a level breaking by body close, price returning, holding, and going |
| **B** | a wick piercing a level, body closing back inside, price leaving |
| **C** | a tight range, a body close outside it, and a retest of the edge |
| **near-miss A/B/C** | three that *look* like the above and should NOT fire |

The near-misses matter more than the golden ones. A detector that fires on its own
fixture proves nothing; one that stays silent on something that looks right is the only
evidence it is discriminating.

---

## 3. After P3 — the order, and what closes each phase

| phase | build | closes when |
|---|---|---|
| **P4** risk | SL from the extreme, R bounds `r_max = min(60, max(35, 1.40 × ATR14))`, space check, sizing from the stop | `test_thresholds_are_index_level_invariant` — shift every price +20,000 and the decision stream must be byte-identical |
| **P5** options + **cost gate** | strike, quote, delta, PaperBroker, and the pre-trade cost gate | spec 07 §3's worked example returns `cost_excessive`, **not** a Signal |
| **P6** exits | L1 invalidation, L2 index stop on ticks, L3 premium backstop, watchdog | kill the process holding a position → an SL-M is found resting at the broker |
| **P7** journal | every decision incl. rejections, daily report | `rules_followed == true` on every trade; a `false` is an engine bug |
| **P8** live feed | `KiteFeed`, quote logging, still paper fills | 5 clean sessions **and** tick-built vs historical decision-stream divergence measured and in the report header |
| **P8.5** cost verification | `costs.yaml` from published rates, hand-verified on 3 trades | measured spread replaces the guess. **If most historical signals now reject, stop and reconsider the vehicle before P9** |
| **P9** validation | 3 years × 4 instruments, identical params, pre-registered grid | a positive net-of-cost result across regimes — or an honest no |

**P8.5 is the cheapest disqualifier in the whole plan.** `REVIEW-v2.md` §2 already shows
the round trip costing 44–64% of R on a 25-point stop, which puts break-even near a 50%
win rate for a setup that realistically wins 35–45%. Two days of work there can save a
month of P9.

---

## 4. How every step gets verified

Your standing rule, now the standing rule:

1. **Run it on real sessions** — never one day, never a fixture alone.
2. **Print the distribution** against spec 10 §3.1's floors and ceilings.
3. **Render the chart** and look at it — replay it slowly if the question is *why*.
4. **Only then** write the next logic.

For P3 specifically that means every detection gets rendered with its trigger candle
marked, so a detection can be *looked at* rather than counted. A detector firing 40 times
a day is as much a failure as one firing zero times, and only the chart shows which.

---

## 5. Still blocked on you

| when | what | why it cannot be auto-approved |
|---|---|---|
| **P3** | golden + near-miss fixtures from real sessions (§2) | a fixture I invent tests my implementation against itself |
| **before P4** | the volatility-gate form (BUILD-PLAN §1.1) | changes what P9 can claim |
| **before P4** | `session.risk_per_trade_rupees` — deliberately `null` | the engine refuses to start; spec 05 §4 says forcing the decision to be conscious is the point |
| **before P4** | `config/events.yaml` dates | fail-closed by design |
| **before P5** | `config/costs.yaml` + `last_verified` | a stale cost model produces a profitable backtest and an unprofitable account |
| **before P6** | the L3 backstop answer (BUILD-PLAN §1.2) | changes what P6's gate means |
| **before P8** | a static-IP host | SEBI requirement since April 2026 |

Two of these — `risk_per_trade_rupees` and `events.yaml` — are what `startup_check.py`
refuses to start without today. That refusal is the design working, not a bug.
