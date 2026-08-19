# DECISIONS

Every place the specs are silent and a choice had to be made. **Written before the code
that depends on it**, per `BUILD-BRIEF.md` §0.

`D-001` … `D-011d` are copied verbatim in substance from `BUILD-BRIEF.md` §4 — they were
pre-made by the user and are implemented as written. `D-012` onward are new.

| id | subject | phase | reversible |
|---|---|---|---|
| D-001 | intra-candle ordering in replay | P0/P9 | yes |
| D-002 | T1 partial when `lots == 1` | P6 | yes |
| D-003 | delta measurement | P5 | yes |
| D-004 | Decimal quantization for `board_digest` | P1 | yes |
| D-005 | leg identification for `pullback_ratio` | P1 | yes |
| D-006 | level cap tie-breaking | P1 | yes |
| D-007 | landing ladder rung selection | P1 | yes |
| D-008 | ATR unavailable with a position open | P2 | no |
| D-009 | synthetic candles and the touch counter | P1 | yes |
| D-010 | which price feeds the ALERT distance | P2 | yes |
| D-011 | round numbers around a gap | P1 | yes |
| D-011b | Journey Ladder must not touch a trading decision | P1 | **no** |
| D-011c | level identity across timeframes | P1 | yes |
| D-011d | revived levels are not fresh | P1 | no |
| D-012 | ATR convention: mean range, within session | **data** | yes |
| D-013 | trading calendar by cross-instrument inference | **data** | yes |
| D-014 | candle storage precision | **data** | yes |
| D-015 | access token cache lives outside the repo | **data** | yes |
| D-016 | monthly request chunking + partial-month refetch | **data** | yes |
| D-017 | credentials file lives outside the repo, enforced in code | **data** | no |
| D-018 | abbreviated sessions excluded, full weekend sessions kept | **data** | yes |
| D-021 | an HTF candle built from a filled minute is synthetic | P0 | yes |
| D-022 | feed gap raises for a named day, skips during a sweep | P0 | yes |

---

## D-001 — Intra-candle ordering in replay ⚠ highest impact
**Spec is silent:** spec 07 §2 evaluates the index stop on ticks; replay has only OHLC, so
when both `sl_index` and `t1_index` fall inside one candle the order is unknown.
**Chosen:** always assume the **stop was touched first**. Exposed as
`replay.intracandle_order: "pessimistic"`; `"optimistic"` exists only to measure the size
of the assumption and is never a default.
**Why:** any other choice makes the backtest better than reality, and it swings it in the
flattering direction.
**Affects:** every backtested trade where both levels are inside one candle.

## D-002 — T1 partial when `lots == 1`
**Spec is silent:** `t1_book_fraction: 0.5` cannot book half of one lot.
**Chosen:** if `lots == 1`, skip the T1 partial entirely and manage the single lot as a
runner — invalidation, index stop, trail after 1.5R is exceeded, time stop. Do **not** exit
the whole position at T1. Journal a `single_lot_no_partial` flag.
**Why:** exiting the whole position at T1 removes the runner that pays for the losers.

## D-003 — Delta measurement details
**Spec is silent:** spec 08 says `Δpremium / Δindex` regressed over 30 minutes, no inputs given.
**Chosen:** OLS on 1-minute **mid-price** changes (`(bid+ask)/2`), 30 observations, refit
every minute while in ALERT. Require R² ≥ 0.80 and ≥ 20 valid observations; otherwise fall
back to 0.5 **and set the journal flag**. Never silent.

## D-004 — Decimal quantization for `board_digest`
**Spec is silent:** determinism is required, no rounding scheme given.
**Chosen:** quantize every price to 2 dp (`ROUND_HALF_EVEN`) and every ratio to 4 before
hashing. Sort dict keys. `sha256`, first 8 hex chars.

## D-005 — Leg identification for `pullback_ratio`
**Spec is silent:** spec 04 §5 is loose about what ends a leg.
**Chosen:** a leg ends when **two consecutive** 1m candles close beyond the prior candle's
opposite extreme. With fewer than 3 candles in the current leg, `pullback_ratio` is `None`
and the ratio-based bias check is **skipped, not defaulted**.
**Why:** a missing value must never silently become a passing one.

## D-006 — Level cap tie-breaking
**Spec is silent:** spec 03 §8's four priority rules can select the same level twice.
**Chosen:** deduplicate by `level.id`, apply the priorities in order, break remaining ties
by `grade` (A>B>C), then `born_at` (newer wins).

## D-007 — Landing ladder rung selection
**Spec is silent:** three signals given, no combining rule.
**Chosen:** the ladder is **informational only** — journal all four rungs and the three
signals; no gate may consume the "expected rung."

## D-008 — ATR unavailable with a position open
**Spec is ambiguous:** spec 01 says `BLOCKED` when ATR is unavailable, but that concerns entries.
**Chosen:** exits **always** run. A blocked engine still manages an open position to exit.
There is no state in which a position is open and unmanaged.
**Reversible:** no.

## D-009 — Synthetic candles and the touch counter
**Spec is silent:** synthetic candles are excluded from "all pattern detection"; touch
counting is ambiguous.
**Chosen:** synthetic candles do **not** increment touch counts and can never be a sweep,
swing, launch base or trigger. They only advance the clock.

## D-010 — Which price feeds the ALERT distance
**Spec is silent:** close or live index?
**Chosen:** the **close of the last closed 1m candle**. The engine never reads a forming
candle for mode decisions. Exits are the only tick consumer.

## D-011 — Round numbers around a gap
**Spec is silent:** `round_number_grid` covers ±1.5 × day range, undefined at 09:15.
**Chosen:** seed from the **previous day's range** until the current day's range exceeds it,
then switch. Recompute at most once per 5m candle, not per 1m, so the book does not churn.

## D-011b — Journey Ladder must not touch a trading decision ⚠
**Chosen:** `journey_gates_trades: false`, enforced structurally — `setups/`, `risk/` and
`exits/` must not import the journey module at all. `test_journey_never_read_by_trading_path`
is a static import check added in P1.
**Why:** an unmeasured intuition wired into a gate is the most likely way this system
acquires a losing rule nobody can argue with, because it will feel obviously true.
**Reversible:** not without a P9 measurement first.

## D-011c — Level identity across timeframes
**Chosen:** run detection **15m → 5m → 1m**. Before creating a level, check whether its zone
overlaps an existing one within `wick_cluster_tolerance`. If yes, do not duplicate —
increment the existing level's evidence, keep the **highest** `born_tf`, re-grade.
**Why:** the 8-level cap is meaningless if one price occupies three slots.

## D-011d — Revived levels are not fresh
**Chosen:** never reset `touches` to 0 on revival. A dormant level keeps `born_at`,
`touches` and its grade-at-sleep.
**Why:** a level tested twice before sleeping is on its third touch when price returns, and
the third touch is where the system stops taking reversals. Resetting turns a known-exhausted
level back into a Grade A trigger — precisely backwards.

---

# New decisions

## D-012 — ATR convention: simple mean of candle range, within a session
**Spec is silent:** specs 03/05/07 say `ATR14_1m` and `ATR20_1m` everywhere and never define
them. Wilder's true range, Wilder's smoothing, plain range, EMA and cross-day carry all
produce different numbers, and every threshold in `params.yaml` is expressed as a multiple
of this undefined quantity.

**Chosen:** `ATR_n = mean(high - low)` over the last `n` **closed 1m candles of the current
session**. No true-range term, no Wilder smoothing, no carry across the overnight gap. The
first ATR of a day is stamped on candle `n` (09:28 for n=14); before that ATR is `None` and
the `warmup` gate fires.

**Why:**
1. It is what `prototype/engine_fixed.py:78` computes, so it is the convention under which
   every number in `prototype/FINDINGS.md` and every threshold in `params.yaml` was reasoned.
   Silently switching conventions now would invalidate all of them at once.
2. Cross-day carry would blend the overnight gap into a measure of *intraday* volatility,
   and the vol gate exists to describe how the current session is moving.
3. Inside a session, consecutive 1m index candles overlap almost always, so the true-range
   term equals the plain range on the large majority of candles. `tools/verify_data.py`
   measures both and prints the difference in `DATA-REPORT.md` §3, so the size of this
   assumption is reported rather than assumed.

**Affects:** the volatility guard, every `*_atr_mult` threshold, level grading, sizing.
**Reversible:** yes — `volatility.atr_method` would need adding to `params.yaml`, and every
`*_atr_mult` re-derived. Cheap now, expensive after P4.

## D-013 — Trading calendar by cross-instrument inference, not a bundled holiday list
**Spec is silent:** KICKOFF §1 Task 2 asks for a holiday cross-check; no NSE holiday list
exists in the repo and none is bundled.

**Chosen:** classify every missing weekday by whether it is missing *everywhere*:
- absent from **all** instruments → **suspected holiday**
- absent from one instrument but present in another → **real hole**, i.e. a download failure

**Why:** a hardcoded holiday list is a second source of truth that rots every year and is
itself unverified. The four instruments share one NSE/BSE calendar, so they cross-check each
other for free — and the distinction that actually matters (holiday vs failed download) is
exactly what this produces. A published NSE list can be dropped in later as a third check;
it is not needed to make the download trustworthy.

**Limitation, stated plainly:** with a single instrument this degrades to "every missing
weekday is a suspected holiday" and detects nothing. It only works because the fetch covers
four instruments. If BSE/SENSEX is inaccessible, the NSE three still cross-check.

## D-014 — Candle storage precision: float64 on disk, `Decimal(repr(x))` at load
**Spec is silent:** spec 02 requires `Decimal` prices; nothing says how candles are stored.

**Chosen:** store `float64` in parquet (and the shortest round-trip repr in CSV). The P0
loader converts with `Decimal(repr(x))`, never `Decimal(x)`.

**Why:** the Kite API delivers JSON numbers that are already parsed to float64 before any
code here sees them, so a decimal string on disk would be no more faithful than the float —
it would only look more faithful. `repr` of a float64 is the shortest string that round-trips,
so `Decimal(repr(x))` recovers exactly the decimal the exchange published for any value with
≤17 significant digits, which covers every index price. `Decimal(x)` on a float would instead
expand the binary representation (`Decimal(57434.05)` → `57434.049999999...`) and is
forbidden in the loader.

**Affects:** P0 `ReplayFeed`. Add `test_replay_loader_uses_repr_not_float` in P0.

## D-015 — The daily access token is cached outside the repo
**Spec is silent:** `CLAUDE.md` §4 and KICKOFF say credentials come from environment
variables only. Kite access tokens expire daily, so a fetch spanning a re-login needs the
token somewhere; an env var alone forces a manual export on every login.

**Chosen:** `KITE_API_KEY` / `KITE_API_SECRET` are **environment only, never persisted**.
The derived access token is written to `~/.banknifty-copilot/kite_token.json` (override with
`BNC_TOKEN_DIR`), mode 600 where the OS supports it, alongside an 8-char SHA of the API key
so a token from a different key is rejected rather than used. `KITE_ACCESS_TOKEN` in the
environment always wins. Nothing secret is ever written into the repo, the manifest, or a
log line.

**Why:** the token is short-lived (dies 06:00 IST the next morning) and is not the credential
that can be used to mint new sessions — the secret is. Keeping the path outside the repo
means no `.gitignore` rule can be deleted by accident and expose it.

**Windows addendum — the registry is read as a second source for the variables themselves.**
`[Environment]::SetEnvironmentVariable(name, value, 'User')` and `setx` write to
`HKCU\Environment`, but any process already running keeps its inherited copy of the old
environment and passes that stale copy to every child it spawns. A credential set at 14:00
is therefore invisible to a shell whose parent started at 13:00, and the usual remedy is to
restart the terminal — or, here, the agent driving the download.

**Do:** read `os.environ` first; on Windows, fall back to reading the User-scope value out of
the registry (`winreg`, `HKCU\Environment`). This is still an environment variable — the
durable store is being read instead of the inherited snapshot. No file inside the repo is
ever consulted and nothing is written.

`fetch_kite.py check` reports which source each credential came from, prints only its length
and an 8-char SHA-256 prefix, and greps the whole repo for the literal values so a leak is
caught by the tool rather than by a `git push`.

## D-023 — `time_at_price` is measured over a window ending at birth
**Spec is silent:** spec 03 §7 awards the clean-formation point for "long time-at-price
(≥10 candles)" without saying over what window, or by what test.

**Chosen:** count the candles in a window of `2 × clean_formation_min_candles` ending at
the level's birth candle whose range intersects `[zone_low, zone_high]`. Synthetic
candles do not count.

**Why:** the measure has to stay local to the level's formation. A level is clean because
price *worked* at that price when it formed, not because price happened to revisit an
hour later — and an unbounded window would let any level eventually earn the point just
by surviving.

**Also decided here:** when a level is born before ATR20 exists (the first 20 candles of
a session), `departure_speed` scores 0 rather than the level being discarded. Discarding
would delete every level formed in the opening 20 minutes, including the opening range —
which spec 03 §6 creates at 09:30 and `mythinking.md` §3 calls *"aksar din ka sabse achha
level"*.

## D-024 — Acceptance is CONSECUTIVE and DIRECTIONAL
**Spec is silent on both halves:** spec 03 §8 says a level dies when "price closed bodies
beyond it for ≥ `acceptance_candles`", without saying whether the closes must be
consecutive, or which direction counts as "beyond".

**Chosen:** consecutive, and only in the direction that invalidates the level. A SUPPORT
is accepted through by bodies closing BELOW it, a RESISTANCE by bodies closing ABOVE it,
an AXIS by either.

**Why consecutive:** five scattered closes over an hour describe price passing by; five
in a row describe price having moved on.

**Why directional — and what it cost to get wrong.** The first implementation killed a
support because price spent five candles ABOVE it, which is a healthy untested support.
Measured over 30 real sessions before the fix: the active book held **2.1 levels against
a cap of 8**, and the dormant pool — spec 03 §8b, the entire v2.1 "level memory" idea —
**never activated once**, because every level died of false acceptance long before it
could travel 25 × ATR away and go dormant. Every run printed "0 sleeps / 0 revivals" and
nothing about that looked wrong. After the fix the book fills to 8.0 and dormancy runs
0.5 sleeps per session.

## D-028 — Contamination is inherited by the whole month, not just the marked day
**Spec is silent:** spec 11 §D1 mandates a month-based 60/20/20 split. `selection.json`'s
own note asks only that the ten *days* rendered for the P1 overlap gate be excluded from
holdout. Those two rules disagree and nothing said which wins.

**Chosen:** any month containing a session the trader has already seen goes to `teach`,
whole. Ten months, so `teach` ends up at 27 of 37 months and `validate`/`holdout` at 5 each
rather than the nominal 60/20/20.

**Why:** §D1 blocks by month because regime is a month-scale property — a trending week
scattered across three sets lets a rule fitted to that regime score well everywhere.
Excluding only 2026-07-21 while keeping 2026-07-14 in holdout leaks exactly the thing the
month blocks exist to contain: having seen one July chart tells you what July felt like.

The cost is a smaller validate set, and it falls in the safe direction — it makes
certifying a rule **harder**. The alternative puts months the trader has studied into
holdout, which makes certification easier while the report looks identical.

**Assignment rule, fixed before it was run:** remaining months by chronological index
mod 5 → `{0,1,2}` teach, `{3}` validate, `{4}` holdout. No seed, nothing to tune, and
dealing by position rather than by block means validate and holdout each span 2023–2026
instead of one era. `tests/data_split.yaml` carries a digest of the assignment; hand-editing
the month lists makes every measurement citing that digest refuse to load.

**Reversible:** no, and deliberately. `tools/make_split.py` refuses to overwrite without
`--force`, because a split redrawn after a result is a tuned parameter.

## D-029 — Outcomes are measured against the ATR *before* the span
**Spec is silent:** spec 11 §4.1 defines the move labeller but not how a hypothesis's
"what happened next" is normalised.

**Chosen:** every outcome (`continuation`, `reversal`, `expansion`, `quiet`) is measured in
units of the ATR20 ending on the candle **before** the span begins — never in units of the
span's own range.

**Why — this was a bug, not a preference.** The first version asked whether the next
candles averaged more than `k × the span's own mean range`. `test_reports_no_edge_on_noise`
ran it on a pure random walk and got:

```
predicate  span_compression <= 0.7
YOUR RATE  12.0%      BASE RATE 1.5%      lift 8.1x      p < 1e-40
```

An eight-fold edge, on data containing no edge at all. The outcome was normalised by the
same quantity the predicate selected on: choose quiet spans and "the next candles are twice
as loud as this span" is nearly free, because the denominator is what you selected for.
That is regression to the mean wearing a discovery's clothes.

Normalising against the pre-span ATR makes the question the one a trader actually means —
*"after a quiet stretch, does it get louder than it was **before** the stretch?"* — and the
same predicate then correctly reports no edge on noise.

**What this implies about everything else here:** the tool was only caught because a test
existed that demanded silence on data with a known answer. `test_finds_a_planted_edge`
and its matched null are not schema tests; they are the only reason any number this tool
prints can be believed.

## D-030 — `volume` is unobservable, not a missing detector
**Observed, not decided.** `record.py` listed a `volume_spike` probe whose admission was
*"mere paas koi volume rule nahi hai"* — which reads as an invitation to build one.

Measured across every downloaded file, four instruments, **1,120,535 one-minute candles:
zero with non-zero volume.** NIFTY BANK is an index; Kite reports volume 0 for it, always.

So volume, absorption, order flow, spread and OI are not gaps in the detector set. They are
outside what these candles can express, and no amount of building reaches them. They now
live in `vocabulary.UNOBSERVABLE`, where `tools/hypothesis.py translate` **stops** rather
than proposing work, and `test_unobservable_are_actually_unobservable` re-counts against the
real parquet so the claim cannot silently rot if the feed ever changes.

The four-way distinction the registry now draws — `ACTED_ON` / `PLANNED` / `BLIND_SPOT` /
`NOT_BUILT`, plus `UNOBSERVABLE` — exists because the honest answer to *"can you build
this?"* has more than two values, and the differences between them are worth days.

## D-031 — Every key in params.yaml must be read by `src/`, or named as pending a phase
**Observed, not decided.** Building the capability registry surfaced that
`levels.swing_lookback_bars_{1m,5m,15m}` sat in `params.yaml` while
`indicators/swings.py` held `DEFAULT_K = {"1m": 3, "5m": 2, "15m": 2}` in Python, and both
engines constructed `SwingDetector(tf)` without passing `k`. **Tuning the config changed
nothing.**

That is worse than a magic number. A magic number is visibly untunable; this looked tunable,
so it would have been tuned, and the run afterwards would have been attributed to a change
that never happened — on the swing lookback, which every level and every BOS depends on.

Both engines now read `k` from config. `test_every_params_key_is_read_somewhere` scans every
leaf key and fails on any the source never reads, with an allowlist naming the phase each
pending key waits for (`setups.` → P3, `risk.` → P4, and so on). That list may shrink and
must never grow. `test_key_coverage_matcher_actually_catches_a_hardcoded_default` shows the
check failing on the exact shape of the bug, because a guard nobody has seen fail is not
known to work.

## D-025 — `broken` subsumes `accepted_through` for directional levels (open)
**Observed, not decided.** With acceptance made directional (D-024), a single body close
beyond a level already kills it as `broken` (spec 03 §5), so it can never survive to
accumulate five. Measured over 30 sessions: `accepted_through` fires **0.1 times per
session**, against `broken` at 123.

The two rules genuinely overlap, and spec 03 §5 (v2) appears to supersede spec 03 §8's
acceptance row (v1). The rule is left in place — it still fires on AXIS levels, which
break in both directions — and this is recorded rather than resolved, because deciding
what acceptance is *for* is a question about the trader's model, not about the code.

**Raise at P1.5.**

## D-026 — A broken BREAK axis dies; it does not mint a new axis
**Spec is ambiguous:** spec 03 §5 says a body close beyond any live level creates an
axis, and separately calls the axis "the invalidation line (body close back through it =
the move failed)". Applied literally, an axis breaking creates another axis.

**Chosen:** a BREAK level broken back through dies with `death_reason = "flip_failed"`
and creates nothing. Spec 06's Setup A already rejects on exactly this condition with
`setup_stale` ("axis is dead — the flip failed").

**Why:** minting a fresh axis there re-arms, on every oscillation, the one level that
just proved unreliable. Measured over 10 sessions before the fix: **1504 of 2417 breaks
(62%) were axes breaking axes** — a self-sustaining generator. Axis-creating breaks fell
from 174 to 61 per session after this and D-024 together.

This is the same shape as `prototype/FINDINGS.md` Bug 5: two individually sensible rules
combining to manufacture levels.

## D-027 — A wick cluster requires an actual wick
**Spec fidelity, not a threshold.** Spec 03 §2b says "≥2 **wicks whose tips** fall within
tolerance". The first implementation used each candle's high/low regardless of whether a
wick existed there.

**Chosen:** a candle only contributes to the upper-side cluster if `upper_wick > 0`, and
to the lower side if `lower_wick > 0`.

**Why:** a candle that closed at its high was not refused at that price. Counting it
turns "price was rejected here twice" into "price reached here twice", which is a
different and much weaker claim. 9.6% of Bank Nifty 1m candles have no upper wick and
7.8% none below.

## OPEN CALIBRATION — LAUNCH fires 0.07 times per session
**Not a decision. A measurement, recorded so it is not silently tuned away.**

Spec 03 §3 calls LAUNCH "the highest-value 1m level"; spec 10 §3.1 treats fewer than one
per session as a health warning. Measured over 40 real sessions:

```
impulse candles (range >= 2.0 x ATR20)          7.8 / session   — the impulse rule is fine
of which the close is decisive                  7.1 / session
tightest base of n in [2,4], as a share of ATR20:
    p5 0.78   p10 0.89   p25 1.07   p50 1.47
launch_base_atr_mult 0.8  ->  0.47 candidates / session   (current)
                     1.0  ->  1.32
                     1.2  ->  2.27
                     1.5  ->  3.70
```

After the `min_departure_speed` filter the surviving rate is **0.07 per session**.

**Deliberately not changed.** Spec 03 §3 says of the base rule: *"This is the correct
outcome; do not relax it."* Whether 0.07/session is the rule working or the threshold
being wrong is exactly the question `specs/12-TEACHING-LOOP.md` exists to answer, and it
needs the trader's annotations — not an engineer's judgement at 2am. The numbers are here
so the conversation starts from measurement.

## OPEN CALIBRATION — `pullback_control_flip_ratio` sits at the median of its own distribution
**Not a decision. A measurement.** Spec 04 §5 declares control to have changed when
`pullback_atr / impulse_atr > 1.0`. Measured over 20 real sessions:

```
pullback_ratio   p25 0.85    p50 0.97    p75 1.11
resulting split  healthy 3.5%  ·  weakening 45.5%  ·  control_flipped 39.7%
```

The threshold lands almost exactly on the median, so the "control has changed" reading is
essentially a coin flip on which side of the median the current leg falls — and
`healthy`, the state that *favours* Setup A, is reachable only 3.5% of the time.

This is the shape `REVIEW-v2.md` §5 caught in the round-number space gate: *"not a filter,
a coin flip wearing a filter's clothing."* It is less severe here, because `bias_conflict`
only applies to continuation setups at non-Grade-A levels, so the effective firing rate
will be far below 39.7%.

**Deliberately not changed.** Recorded for the spec 09 counterfactual study, which scores
`gate_value(bias_conflict)` directly, and for P1.5. Re-measure once P3 reports how often
the gate actually fires on candidates rather than on candles.

## D-021 — An HTF candle containing any filled minute is itself synthetic
**Spec is silent:** spec 01 §3 forward-fills a single missing minute as a `synthetic`
candle and excludes synthetic candles from all detection (D-009). It never says what
happens to the 5m and 15m candles built on top of one.

**Chosen:** an aggregated candle inherits `synthetic = True` if **any** of its
constituent 1m candles was filled.

**Why:** a 5m candle whose high came from a price that never traded is not a candle the
market made. Left unmarked it can become a 5m swing pivot, and therefore a TURN level,
and therefore — via the "HTF confirmed" grading point — a Grade A trigger. The whole
point of excluding synthetic candles is defeated one timeframe up.

**Cost, stated:** one filled minute taints a whole 15m candle, so it is conservative.
With three gap days in three years this costs almost nothing; if the live tick-built
feed produces more fills, revisit rather than loosen silently.

## D-022 — A feed gap raises for a named day, skips during a sweep
**Spec is ambiguous:** spec 01 §3 says ≥2 consecutive missing minutes raise
`FeedGapError`, and that in live this sets `BLOCKED` for 15 minutes. It does not say
what a three-year replay should do when one day in 2024 has a six-minute hole — and a
bare raise aborts the whole P9 run.

**Chosen:** `ReplayFeed(on_gap=...)`.
- `"raise"` (default) whenever a specific day was requested. If you named the day, you
  need to know it is unusable rather than receive silence.
- `"skip"` for anything sweeping the dataset — the P9 replay, the session profiler.
  The day is recorded in `feed.skipped` with its reason, never dropped quietly.

`prev_close` **is** advanced across a skipped gap day, unlike an abbreviated session
(D-018): the market did trade that day, we simply cannot replay it honestly, so the
next day's overnight gap is still measured against a real close.

**Scope:** this is the replay answer only. P2's `feed_gap` guard implements the live
15-minute block, and at that point the more faithful option — replay the day but keep
the engine BLOCKED across the hole — becomes available and should be reconsidered.

**Affects:** 3 days of 746 on Bank Nifty (0.4%): 2023-08-07, 2024-04-23, 2025-12-15.

## D-018 — Abbreviated sessions are excluded; full weekend sessions are kept
**Spec is silent:** spec 02 defines a session as 09:15–15:30 and nothing addresses the days
that are not one. The download found eight such days in three years, and they are two
different things that must not be treated alike.

**Excluded — 5 abbreviated sessions.** Not a real market:

| day | window | what |
|---|---|---|
| 2023-11-12 Sun | 18:15–19:14 | Muhurat, 60 candles |
| 2024-03-02 Sat | 09:15–12:29 | NSE disaster-recovery site test, 105 candles in two blocks |
| 2024-05-18 Sat | 09:15–12:29 | NSE disaster-recovery site test |
| 2024-11-01 Fri | 18:00–18:59 | Muhurat |
| 2025-10-21 Tue | 13:45–14:44 | Muhurat |

**Kept — 3 full sessions that happen to fall on a weekend**: 2024-01-20 (Sat),
2025-02-01 (Sat), 2026-02-01 (Sun). A complete 09:15–15:29 session with real liquidity,
held for the Union Budget or as an NSE special session.

**The rule is the session's shape, not the calendar,** so a future one is classified without
a code change: abbreviated if the first candle is after 09:15 or the last before 15:00.

**Why the split matters in both directions:**
- Including the abbreviated days drags the ATR distribution that sets the volatility gate,
  on ceremonial liquidity that no strategy can trade.
- Excluding the full weekend days breaks the overnight-continuity chain and **invents** a
  gap on the following Monday. The first version of this rule excluded all eight and
  promptly produced a phantom −2.05% gap on 2026-02-02. Whether the engine *trades* a
  Budget day is `events.yaml`'s business — a calendar decision, not a data-integrity one,
  and merging the two would have hidden the error.

**The specific hazard this catches:** 2025-10-21's Muhurat session runs **13:45–14:44**,
entirely inside `time.windows_normal` `[13:30, 14:45]`. Without an explicit exclusion the
engine treats a one-hour ceremonial session as an ordinary afternoon window, and says
nothing about it.

**Affects:** P0's `ReplayFeed` must apply the same rule and must not silently skip —
`tests/` gets `test_replay_skips_abbreviated_sessions` and
`test_replay_keeps_full_weekend_sessions` in P0.

## D-017 — The credentials file lives outside the repo, and that is enforced in code
**The user asked** for a `.env` in the repo to paste the key and secret into, so the
download could be run without touching PowerShell. **The specs say no**, in four separate
places: `CLAUDE.md` §4, `KICKOFF` §1, `BUILD-BRIEF` §6 and spec 08 §3.1 — *"No API key or
secret in the repo, in config files, or in logs."*

**Chosen:** give the ergonomics, move the location. One file, paste once, forget — at
`~/.banknifty-copilot/.env` (override with `BNC_ENV_FILE`), which is the same directory
the access-token cache already uses under D-015. `.env.example` **is** committed to the
repo, holds only placeholders, and documents the copy command. Credential lookup order:

```
1. process environment
2. Windows user environment (registry)   ← D-015 addendum
3. the credentials file above
```

Three enforcement points, because a rule stated in four documents was still about to be
broken by the person who wrote it:

- `assert_env_file_outside_repo()` raises `CredentialInRepo` if the configured path
  resolves inside the repo — the loader refuses rather than warns.
- `fetch_kite.py check` reports any `.env`-shaped file sitting in the repo root.
- `tools/check_no_secrets.py` scans file **contents** for the live credential values and
  for credential-shaped assignments, and installs as a git pre-commit hook
  (`--install`), which is what spec 08 §3.1 asked for.

**Why not just gitignore it:** a `.gitignore` entry is one `git add -f`, one folder zip,
one editor backup and one careless edit away from failing, and it fails silently. A path
outside the repo cannot fail that way. The convenience is identical.

**Two real bugs this decision surfaced, both found by building the check rather than
writing it down:**

1. `.gitignore` contained `**/*secret*`, which matched `tools/check_no_secrets.py`. The
   secret scanner would never have been committed, the pre-commit hook would have existed
   only on this machine, and nothing would have looked wrong. Filename wildcards were
   removed — they buy nothing (a key pasted into `notes.md` is not called "secret") and
   they cost this. Content scanning is the real check.
2. The first shape regex flagged `access_token = load_access_token(api_key)` — ordinary
   code. A scanner with false positives is bypassed with `--no-verify`, which is worse
   than no scanner. The value pattern now requires an unbroken run of ≥16 lowercase
   alphanumerics containing a digit, which is what a Kite credential looks like and what
   an identifier never does.

**Reversible:** yes, but the enforcement is deliberately not a config flag.

## D-016 — One request per calendar month, partial months always refetched
**Spec is silent:** KICKOFF names the 60-day-per-request limit and the output layout
`data/{SYMBOL}/{YYYY-MM}.parquet` but not how to chunk.

**Chosen:** one request per calendar month. A month is ≤ 31 days, comfortably inside the
60-day limit, and it makes the file layout fall out of the chunking with no reassembly step.
The manifest records `month_complete`; a month whose last day is still in the future is
**always refetched**, so today's partial file cannot be mistaken for a finished one.

**Why:** the alternative — maximal 60-day requests — halves the request count (148 → ~80 for
3 years × 4 instruments) but forces a split-and-merge step whose bugs would be invisible,
because a wrongly-split month still looks like a valid file. At 2.5 req/s the saving is
about thirty seconds of wall clock, once. Correctness of resume is worth more than that.

**Rate limit:** the historical endpoint allows 3 req/s (kite.trade exceptions doc, verified
2026-08-11). The throttle default is 2.5 and refuses to be configured above 3.
