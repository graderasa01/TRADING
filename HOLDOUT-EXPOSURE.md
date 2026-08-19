# HOLDOUT EXPOSURE — a standing caveat

> Read this before treating any future holdout run as final proof.
> Split digest at the time of writing: `5a702621fa6703bf` (37 months — teach 27,
> validate 5, holdout 5).

## The two facts, kept apart

```
HOLDOUT EXECUTION    0        split.holdout() has never been called.
                              HOLDOUT-ACCESS.md is empty.

HOLDOUT OBSERVATION  exposed  Aggregate statistics covering the holdout months have
                              already been read.
```

## What happened

The structural research described in `LIVE-FRONTIER.md` — the 1m transition study, the
structure interaction study, the momentum control test, and the first 5m scale
experiment — was run over `ReplayFeed.available_days()`, i.e. **every downloaded
session**. That population includes the five validate months and the five holdout
months.

The split was not consulted, because at the time it was not known to exist. It was found
later, before any holdout call was made.

## What was and was not done to those months

* **No threshold was changed as a result of any measurement.** Every parameter in play
  — `min_score 0.35`, `break_closes 2`, `tol 0.25×ATR`, `IMPULSE_MIN_ER 0.5`,
  `stability_run 3`, the window ladder — predates this research and none of them were
  touched. There was no fitting loop.
* **No individual holdout session was rendered, charted or inspected.** The exposure is
  to pooled statistics only.
* Findings that *did* emerge (the 5m accepted-break effect, the revisit/crossed
  underperformance) were subsequently re-measured on **teach and validate separately**,
  which is the comparison those results should be cited from.

## What this costs

Spec 11's holdout is valuable precisely because nobody has seen what it says. That is no
longer strictly true of these five months: aggregate results containing them have been
looked at. The contamination is mild — observation without adaptation — but it is not
zero, and pretending otherwise would be the exact self-deception the split exists to
prevent.

**Therefore: a future `split.holdout()` run on digest `5a702621fa6703bf` must be
reported as a confirmation, not as a clean out-of-sample proof.** If a genuinely pristine
final test is wanted, it has to come from data downloaded after this date, under a new
split — and a new split invalidates every measurement taken under the old one, so that is
a deliberate decision with a cost, not a formality.
