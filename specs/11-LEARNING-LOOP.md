# 11 — THE LEARNING LOOP

> Market ne kya kiya, engine ne kya dekha, aur farak kahan tha.
> Ye spec us farak ko naapne ka tareeka hai — **aur usse seekhne me jo khatra hai,
> usse bachne ka tareeka.**

---

## 1. The idea

Give the engine real data. For every significant move the market actually made, ask:
**did the engine see it, and if not, where exactly did it lose it?**

Then fix the rule that lost it, and check the fix on data you have not looked at.

This is the only honest way a level engine grows. Every threshold in `params.yaml` was
reasoned, not measured. This loop is how they stop being guesses.

## 2. ⚠ The trap — read this before running it once

**This is also exactly how you destroy a trading system.**

Look at a move, notice the engine missed it, add a rule that would have caught it.
Repeat fifty times. You now have a system that explains the past perfectly and has
learned nothing about the future. Every rule was fitted to one specific move that
already happened.

`CLAUDE.md` §8 already warns about this. The loop below is dangerous *precisely because
it feels like progress* — each fix looks obviously correct in hindsight, and hindsight
is the thing being fitted.

**Four disciplines make the difference between learning and memorising. All four are
mandatory. A loop run without them is worse than no loop, because it produces
confidence.**

---

## 3. The four disciplines

### D1 — Split the data BEFORE you look at any of it

```
teach     60%   — you may examine every miss in detail
validate  20%   — you may only run scores here, never read individual misses
holdout   20%   — touched ONCE, at the very end, ever
```

**Split by month, not randomly.** Random splitting leaks regime: a trending week
scattered across all three sets means a rule fitted to that regime scores well
everywhere. Months keep regimes intact.

Write the split to `tests/data_split.yaml` and commit it **before the first run.**

### D2 — A rule needs a mechanism, not a fit

Every proposed rule must answer, in one sentence: **"why does the market do this?"**

- *"Price compresses before an expansion because participants stop disagreeing, and the
  first disagreement moves it"* — a mechanism. Acceptable.
- *"Levels born between 10:15 and 10:45 work better"* — a fit. Delete it.

If the answer describes the data rather than the market, the rule is memorising.

### D3 — Recall is half the score. Measure precision too.

The loop naturally optimises for *"catch more moves."* That is one half of a fraction.

Every new detector creates levels. More levels → more ALERT → more setups → more
trades — the exact failure `CLAUDE.md` and spec 05 are built to prevent. So every rule
must report its cost alongside its benefit:

```
RULE: compression-expansion origin detector
  BENEFIT   moves caught      +3 of 8    (recall 62% → 100%)
  COST      levels/day        +11        (41 → 52)
            ALERT share       +9pp       (19% → 28%)
            setups detected   +6/day     of which 5 went nowhere
            precision         31% → 19%  ← the number that matters
  VERDICT   reject — it catches everything by flagging everything
```

**A detector that fires on every compression will "catch" every move that follows one.
That is not detection, that is arithmetic.**

### D4 — Two rules per iteration, maximum

Change at most two things, then re-score everything. More than two and you cannot
attribute the change, and spec 01 §8's prohibition on tuning more than two parameters
at once applies with equal force here.

---

## 4. The loop

```
1  LABEL      candles → every significant move, mechanically
2  SCORE      each move → where in the funnel the engine lost it
3  BUCKET     group the misses by cause
4  DIAGNOSE   read the biggest bucket only
5  PROPOSE    ≤2 rules, each with a mechanism and a cost estimate
6  VALIDATE   re-score on `validate` — recall up AND precision not down?
7  COMMIT     or discard. Log the decision either way in DECISIONS.md
8  repeat
```

### 4.1 The labeller — no judgement, no AI

```python
def label_moves(candles, min_atr_mult=2.5, max_candles=30, max_retrace=0.35):
    """A MOVE = price travelled >= min_atr_mult × ATR within max_candles,
    without retracing more than max_retrace of the gain along the way.
    Pure arithmetic, fully reproducible, no opinion anywhere."""
```

This must be mechanical. The moment a human or a model picks which moves "count," the
ground truth becomes an opinion and everything downstream measures agreement with that
opinion.

Record for each move: origin candle index, origin price, direction, points, duration,
ATR at origin.

### 4.2 The funnel — this is the whole value

For each labelled move, interrogate the engine's state **at the origin candle**:

```
was any level within tolerance of the origin?     → level recall
was it Grade A?                                   → tradeable recall
was the mode ALERT?                               → attention recall
was a setup detected?                             → setup recall
was a signal emitted?                             → signal recall
```

Five nested questions. The funnel converts *"the engine missed it"* into a specific,
fixable statement like *"the engine had a level four points from the origin and graded
it C."* Those are entirely different problems and only the funnel distinguishes them.

### 4.3 Buckets — read the largest one, ignore the rest

```
time window ke bahar          → not a bug. The system chose not to trade
origin par koi level nahi     → a detector is missing
level tha par Grade A nahi    → grading, not detection
Grade A tha par ALERT nahi    → alert_distance too tight
ALERT tha par setup nahi      → setup conditions
```

**Fix only the biggest bucket, then re-run.** Buckets shift after every change, and
fixing three at once means you cannot tell which fix did what.

---

## 5. First run on real output — and what it found

Run on one session (`prototype/score.py`, 8 labelled moves):

```
DETECTION FUNNEL
  koi level origin ke paas tha      6/8    75%
  wo Grade A tha                    0/8     0%     ← everything dies here
  mode ALERT tha                    4/8    50%
  setup DETECT hua                  0/8     0%

MISS BUCKETS
  [4]  time window ke bahar — correct, not a bug
  [3]  level tha par Grade A nahi — grading
  [1]  origin par koi level nahi — detector missing
```

Read that carefully, because the first run already contradicted the obvious assumption.

**The engine had a level within 4 to 15 points of three move origins — and graded all
of them C.** The problem is not that it cannot find the places the market turns. It
finds them. It then refuses to treat them as tradeable.

So the correct first action is **not to add a detector.** It is to ask why a level four
points from a 85-point move scores Grade C. That is a grading question, and grading is
already the thing that produced Bug 1 in the dry run.

Only **one** miss out of eight was a genuinely absent detector — the 10:34 move, whose
origin shows `pre-ranges [5.3, 7.0, 69.0, ...]` against an ATR of 24.9. Two very quiet
candles, then a 69-point expansion. That is a compression-then-expansion origin, and it
is the one place a new rule might be justified.

**The loop's first output was "fix the rule you have, do not add a new one."** That is
what a well-disciplined loop should mostly say, and it is the opposite of what the loop
feels like it should say.

---

## 6. What to give the model — the practical answer

When asking Claude (or any model) to propose rules from the miss report, give it exactly
this and nothing more:

| Give | Why |
|---|---|
| The **candles** for the teach split only | It cannot fit to what it cannot see |
| The **full decision log** — every candle, mode, gate, level book | Without this it guesses at what the engine knew |
| The **labelled moves** | The ground truth, generated mechanically |
| The **miss report with numeric context** — the 5 candle ranges before each origin, ATR, nearest level and its grade and distance | The raw material for a mechanism |
| The **current `params.yaml`** | So it proposes changes, not reinventions |
| The **bucket counts** | So it works on the biggest problem |

**Never give it:** the validate or holdout data, the outcome of any move it has not
already been shown, or a request to "find what would have worked."

### The prompt discipline

Ask for this, in this shape:

```
Here are 8 misses, bucketed. The largest bucket is "level existed but graded C."

For the largest bucket only, propose at most 2 changes. For each:
  1. the exact arithmetic, as it would appear in params.yaml
  2. why the market behaves this way — one sentence, about the market, not the data
  3. what it would FALSELY flag, and roughly how often
  4. which existing test would break

Do not propose a new detector unless the bucket is "no level at origin."
If the honest answer is that no rule change is justified, say that.
```

That last line matters more than the rest. A model asked to find rules will find rules.
It has to be given permission to say the miss was not fixable — and that permission has
to be explicit, because the default behaviour of any assistant is to be helpful by
producing something.

### What the model is good at here, and what it is not

**Good at:** reading a hundred miss records and spotting that eleven of them share a
numeric signature nobody noticed. That is genuine pattern-finding over more data than a
person will hold in their head.

**Bad at:** knowing whether that signature is a market mechanism or a coincidence in
your sample. It cannot tell those apart. **Only the validate split can**, and only if it
has never seen it.

Use the model to generate hypotheses. Use the held-out data to kill them. Never let the
model do both jobs.

---

## 7. Stopping rules

The loop must have an end, or it becomes a hobby that slowly overfits.

**Stop when any of these is true:**

- Two consecutive iterations produce no rule that survives validation
- Recall on validate stops improving while recall on teach keeps improving — **the
  textbook signature of overfitting, and the moment to stop is the moment you see it**
- The rule count has grown by more than 4 since the loop began
- Precision has fallen below its starting value

**Then, and only once, run the holdout.** Whatever it says is the answer. If holdout
recall is much worse than validate recall, the loop overfitted despite the disciplines,
and the correct response is to revert to the starting rule set — not to run the loop
again with the holdout as the new validate.

---

## 8. Tests

| Test | Expectation |
|---|---|
| `test_labeller_is_deterministic` | Same candles → byte-identical move list |
| `test_labeller_uses_no_future_data_for_origin` | The origin is identified from the move, but the engine snapshot used for scoring is strictly the state at that candle |
| `test_scorer_snapshot_has_no_lookahead` | Funnel scoring reads only `snaps[origin_i]`, never later |
| `test_split_is_by_month` | `data_split.yaml` contains whole months, no overlap |
| `test_holdout_access_is_logged` | Any read of the holdout writes an entry to `DECISIONS.md` |
| `test_precision_reported_with_recall` | No rule proposal is accepted without both numbers |
| `test_rule_budget_enforced` | More than 2 rule changes in one iteration → error |

---

## 9. Tools

```bash
python3 prototype/label.py     # mechanical move labeller
python3 prototype/score.py     # funnel + miss report + buckets
```

Both are working reference implementations. `score.py` produced the output in §5.

---

*The loop's job is not to make the engine catch everything. An engine that catches
everything is an engine that flags everything. Its job is to tell you which of your
guesses were wrong — and, most of the time, to tell you that the rule you already have
is the one that needs fixing.*
