# BUILD BRIEF — for Claude Code

> Read this **after** `CLAUDE.md` and **before** writing any code.
> `CLAUDE.md` is the constitution — what the system is.
> `REVIEW-v2.md` is the audit — what was wrong in v1 and why it changed.
> **This file is the working agreement** — how to build it, and what to do at every
> point where the specs are silent.

---

## 0. THE ONE RULE THAT MATTERS MOST HERE

The specs are ~4,600 lines and unusually precise. They are also **incomplete in about
a dozen specific places.** At each of those you will have to make a choice.

**Every such choice goes in `DECISIONS.md` before you write the code that depends on
it.** Format:

```markdown
## D-007 — Intra-candle ordering in replay
**Spec is silent:** spec 07 §2 evaluates stops on ticks; replay has only OHLC.
**Chosen:** pessimistic — assume the stop is touched before the target.
**Why:** any other choice makes the backtest better than reality.
**Reversible:** yes, `replay.intracandle_order` in params.yaml.
**Affects:** every backtested trade where both levels are inside one candle.
```

Silent guesses are the failure mode here. A trading system where nobody remembers why
the stop-fill model works the way it does is a system nobody can debug when the paper
results and the live results disagree.

§4 below already lists the known-silent spots with the decision pre-made. Add to it
whenever you find another.

---

## 1. READ ORDER

1. `CLAUDE.md` — twelve non-negotiables, pipeline, prohibitions, build order
2. `REVIEW-v2.md` — what broke in v1; **§Part 2 explains why several thresholds look
   unusual.** Do not "simplify" them back to round numbers
3. **`prototype/FINDINGS.md` — six bugs found by actually running the engine.** Four of
   them made the system unable to trade at all, and none is visible from reading the
   specs. The prototype in `prototype/` is a working reference for what each rule really
   does. Read this before writing the level engine
4. `mythinking.md` — the human routine this mechanises. When a spec seems arbitrary,
   the reason is usually here
5. `specs/10-SELF-DIAGNOSTICS.md` — build the reachability assertions early
6. The spec for the module you are about to build. **Only that one.** Do not build ahead

---

## 2. BUILD ORDER — with the acceptance test that actually gates each phase

Each phase needs green tests before the next begins. The listed test is the one that
matters — not the only one.

| Phase | Build | The gate |
|---|---|---|
| **P0** | config loader, domain models, `ReplayFeed`, `Aggregator` | `test_no_lookahead_by_truncation` green. Nothing downstream means anything until this passes |
| **P1** | LevelEngine (1m/5m/**15m**), dormant pool, StructureEngine, **Journey**, StateBoard | `test_board_is_deterministic` **and the level-overlap test scores ≥60%** (spec 09 §3.2b). This is the gate that protects every phase after it |
| **P1.5** | **TEACHING LOOP — spec 12 + 13.** Chart renderer, per-candle reasoning record incl. blind spots, annotation schema, measurement battery, near-miss diagnosis, regression harness | ≥8 annotated sessions processed; overlap on the 4 **holdout** sessions within 15pp of the teach sessions. **Do not skip and do not defer this.** Every phase after P1 is built on the level engine, and until P1.5 nobody has checked it against a chart |
| **P2** | guards, ModeMachine, **session_store**, **health monitor (spec 10)** | Restart test passes **and all 12 reachability assertions pass at startup**. Build the assertions first — they cost an hour and would have caught three of the four dry-run bugs before a single candle |
| **P3** | setups A/B/C | Golden fixtures fire, near-misses silent, **and the full-session detection count is > 0** — see §4b |
| **P4** | risk engine, space, sizing | `test_thresholds_are_index_level_invariant` — shift all prices +20,000, decision stream must be identical |
| **P5** | options layer, PaperBroker, **cost gate** | Spec 07 §3's worked example returns `cost_excessive`, not a Signal |
| **P6** | exits, **backstop, watchdog** | Kill the process holding a position → an SL-M is found resting at the broker |
| **P7** | journal, daily report | `rules_followed == true` on every trade. A `false` is an engine bug |
| **P8** | `KiteFeed`, quote logging | 5 clean sessions **and** the tick-built vs historical decision-stream divergence measured and written into the report header |
| **P8.5** | cost verification | `costs.yaml` filled and verified; measured spread replaces guesses; cost gate re-run over every P8 signal |
| **P9** | replay validation | 3 years × 4 instruments, identical params, plus the pre-registered grid |

**Stop and report to the user at the end of every phase.** Do not chain P0→P3 in one
run. Each phase is a decision point about whether to continue.

---

## 3. HARD PROHIBITIONS — refuse if asked mid-build

From `CLAUDE.md` §6, restated because these are the ones that get eroded:

- ❌ **No live order path.** `src/broker/live.py` must not exist. Add the CI check in P0
- ❌ No averaging down, martingale, size-up-after-loss
- ❌ No stop-loss widening, no "temporarily disable SL" flag, no config key matching `disable.*sl`
- ❌ No re-entry into the same failed setup more than once per level per session
- ❌ No naked option selling; BUY only
- ❌ No signal computed from option premium price action
- ❌ No metric reported gross of costs
- ❌ No optimisation loop tuning more than 2 parameters at once
- ❌ **No fourth setup.** The registry length is asserted to be 3

If the user asks for any of these mid-build, say no and point at this line. That is what
this file is for.

---

## 4. WHERE THE SPECS ARE SILENT — decisions pre-made

Implement these as written. Each is already logged as a `D-xxx` entry; copy them into
`DECISIONS.md` on day one.

### D-001 — Intra-candle ordering in replay ⚠ highest impact
Spec 07 §2 evaluates the index stop on ticks. Replay has only OHLC, so when both
`sl_index` and `t1_index` fall inside one candle, the order is unknown.

**Do:** always assume the **stop was touched first**. Expose it as
`replay.intracandle_order: "pessimistic"` and make `"optimistic"` available only for
measuring the size of the assumption — never as a default.

**Why it matters:** this single choice can swing a backtest by a large margin, and it
swings it in the flattering direction if you get it wrong.

### D-002 — T1 partial when `lots == 1`
`t1_book_fraction: 0.5` cannot book half of one lot. The specs never address it.

**Do:** if `lots == 1`, **skip the T1 partial entirely** and manage the single lot as a
runner: invalidation, index stop, trail after `1.5R` is exceeded, time stop. Do **not**
exit the whole position at T1 — that removes the runner that pays for the losers.
Journal a `single_lot_no_partial` flag so these trades can be cut separately.

### D-003 — Delta measurement details
Spec 08 says `Δpremium / Δindex` regressed over 30 minutes, without specifying inputs.

**Do:** ordinary least squares on **1-minute mid-price** changes (`(bid+ask)/2`), 30
observations, refit every minute while in ALERT. Require R² ≥ 0.80 and at least 20 valid
observations, otherwise fall back to 0.5 **and set the journal flag**. Never silent.

### D-004 — Decimal quantization for `board_digest`
Determinism is required but no rounding scheme is given.

**Do:** quantize every price to 2 decimal places (`ROUND_HALF_EVEN`) and every ratio to
4 before hashing. Sort dict keys. Hash with `sha256`, keep the first 8 hex chars.

### D-005 — Leg identification for `pullback_ratio`
Spec 04 §5 is loose about what ends a leg.

**Do:** a leg ends when **two consecutive** 1m candles close beyond the prior candle's
opposite extreme. If fewer than 3 candles are in the current leg, `pullback_ratio` is
`None` and the ratio-based bias check is **skipped, not defaulted**. A missing value must
never silently become a passing one.

### D-006 — Level cap tie-breaking
Spec 03 §8's four priority rules can select the same level twice or conflict.

**Do:** deduplicate by `level.id` first, then apply the priorities in order, then break
remaining ties by `grade` (A>B>C), then by `born_at` (newer wins). Deterministic and
documented.

### D-007 — Landing ladder rung selection
Three signals are given; the combining rule is not.

**Do:** the ladder is **informational only** — journal all four rungs and the three
signals, and let no gate consume the "expected rung." Spec 04 says the ladder is not a
prediction; keep it that way in code.

### D-008 — ATR unavailable with a position open
Spec 01 says `BLOCKED` when ATR is unavailable, but that concerns entries.

**Do:** exits **always** run. A blocked engine still manages an open position to exit.
There is no state in which a position is open and unmanaged.

### D-009 — Synthetic candles and the touch counter
Synthetic candles are excluded from "all pattern detection." Touch counting is ambiguous.

**Do:** synthetic candles do **not** increment touch counts and can never be a sweep,
swing, launch base or trigger. They only advance the clock.

### D-010 — Which price feeds the ALERT distance
Not stated whether it is the close or the live index.

**Do:** the **close of the last closed 1m candle**. The engine never reads a forming
candle for mode decisions. Exits are the only tick consumer (spec 01 §3).

### D-011b — Journey Ladder must not touch a trading decision ⚠
Spec 04 §6b adds a `Journey` on every level break — a ranked destination ladder, logged
as a prediction. It encodes the trader's core belief (*"jahan se aaya wahan tak jayega"*),
which has never been measured.

**Do:** `journey_gates_trades: false`, and enforce it structurally — `setups/`, `risk/`
and `exits/` must not import the journey module at all. Add
`test_journey_never_read_by_trading_path` as a static import check in P1.

**Why:** an unmeasured intuition wired into a gate is the single most likely way this
system acquires a losing rule that nobody can argue with, because it will feel obviously
true. Log it for a few months, score it in the P7 report, then decide with data.

### D-011c — Level identity across timeframes
15m detection is new (spec 03 §2a). The same price will now be found on 1m, 5m and 15m.

**Do:** run detection **15m → 5m → 1m**. Before creating a level, check whether its zone
overlaps an existing one within `wick_cluster_tolerance`. If yes, do not create a
duplicate — increment the existing level's evidence, keep the **highest** `born_tf`, and
re-grade. The 8-level cap is meaningless if the same price occupies three slots.

### D-011d — Revived levels are not fresh
A dormant level that wakes up (spec 03 §8b) keeps `born_at`, `touches` and its
grade-at-sleep.

**Do:** never reset `touches` to 0 on revival. A level tested twice before it went
dormant is on its third touch when price returns — and the third touch is where the
system stops taking reversals. Getting this wrong turns a known-exhausted level back
into a Grade A trigger, which is precisely backwards.

### D-011 — Round numbers around a gap
`round_number_grid` covers ±1.5 × day range, which is undefined at 09:15.

**Do:** seed from the **previous day's range** until the current day's range exceeds it,
then switch. Recompute the set at most once per 5m candle — not per 1m — so the level
book does not churn.

---

## 4b. THE P3 GATE — count DETECTION, not trades

Fixtures prove a detector fires on a candle sequence built for it. They do not prove the
detector is **reachable** inside the full pipeline, where guards, modes, grading and the
level cap all run first.

The dry run made this concrete: Setup B's six conditions all passed on a textbook sweep,
and the detector never ran because the mode was `BLOCKED`. A fixture test would have
been green. The system could not trade.

**So P3 does not close on fixtures alone. Run a complete session and count:**

```
levels born ......................... > 20
levels reaching Grade A ............. > 0      ← Bug 1 lived here
candles in ALERT .................... > 0      ← Bug 3 lived here
setups DETECTED (reached evaluate) .. > 0      ← the number that matters
  of which A / B / C ................ each > 0 over ~10 sessions
setups rejected, by gate ............ the histogram
signals ............................. may legitimately be 0
```

**Signals may be zero. Detections may not be.** Zero signals on a session is the system
working. Zero *detections* means the market never reached the part of the engine that
decides — and no amount of building on top of that will help.

If any counter above is zero, **stop and diagnose before P4.** Print this block at the
end of every P3 run and paste it into `PROGRESS.md`.

The prototype in `prototype/` already produces this block. Reuse its shape.

---

## 5. FIXTURES — the trap, stated plainly

Spec 09 requires ~21 hand-built fixtures with hand-computed expected values.

**You cannot create these honestly.** A fixture you generate to match your own
implementation tests that the code does what the code does. It will pass, it will look
like coverage, and it will validate nothing.

**Do this instead:**

1. Build every fixture as a CSV **plus** an `expected.yaml` written from the spec text —
   the level prices, R, gate names and outcomes derived from the *rules*, by hand,
   **before** running the code.
2. When a fixture fails, the default assumption is that **the code is wrong**, not the
   fixture. Only change an `expected.yaml` after writing down which spec line justifies
   the change.
3. Mark every fixture with `source: synthetic` or `source: real_chart`. Print the ratio
   in the P3 acceptance report.
4. **Tell the user which fixtures need real chart data from them.** The golden A/B/C
   fixtures and `full_session.csv` should come from real Bank Nifty sessions the user
   picks. Ask for them; do not invent them.

The honest position: synthetic fixtures verify the code is internally consistent. Only
real ones verify it recognises the pattern it claims to recognise.

---

## 6. WHAT YOU CANNOT PRODUCE — ask the user

Do not stub, mock or fabricate any of these. Stop and ask.

| Needed | For | Note |
|---|---|---|
| `risk_per_trade_rupees` | engine start | Deliberately `null`. The user must choose consciously |
| `costs.yaml` — all rates | engine start | From the broker's current published charges, plus `last_verified` |
| `events.yaml` — dates | engine start | RBI MPC + 5 heavyweight bank results + Budget |
| 1m historical CSVs | P0 replay, P9 | Not in the repo. Kite's historical add-on or a data vendor |
| Kite API key + secret | P8 | Environment variables only. Never in the repo, never logged |
| Static IP / host | P8 | SEBI requires it for API access. A cloud VM decision, not a code decision |
| Real chart fixtures | P3 | See §5 |
| **The trader's own 10 charts, marked up** | **P1 gate** | The level-overlap test (spec 09 §3.2b). The user must mark their levels on 10 real sessions **before** seeing any engine output. Ask for these at the start of P1 — the phase cannot close without them |

---

## 7. TRACEABILITY TO `mythinking.md`

The specs mechanise the routine in `mythinking.md`. Most of it survived the translation.
**Four things did not** — build them, because they come from the user's own document and
three of them are load-bearing.

### ✗ M-1 — The pre-market map does not exist
`mythinking.md` §2 is titled *"asli paisa yahan banta hai"* and lists a 7-point
checklist run before 09:15. **No module produces it.** The engine currently starts cold
at 09:15 with PDH/PDL/PDC and nothing else.

**Build `premarket/map.py`**, run before the session, emitting the 7 points as a
journalled artefact: PDH/PDL/PDC · 3-day regime (M-2) · gap size and direction · expiry
or event flag · the 2 nearest untested 15m levels above and below · two IF-THEN
scenarios · the day's rupee risk cap echoed back. It gates nothing on day one — it is
journalled so the counterfactual study can later measure whether the pre-market read
predicted the day.

### ✗ M-2 — "Last 3 days: trending or ranging?" is missing, and this one is structural
`mythinking.md` §2 calls this *"SABSE BADI DECISION"* — it decides whether the day is
spent hunting breakouts or reversals. The specs have a `regime` variable, but it is
computed from the **last 20 5m candles, intraday**.

Twenty 5m candles is 100 minutes. Starting at 09:15 that is **10:55** — so during the
entire 09:30–11:15 window, which `mythinking.md` §13 calls the *best* window, the regime
read is running on insufficient data and will sit at `transition` most mornings.

**The human solves this before the bell by looking at three days. The engine tries to
solve it during the session and cannot, in exactly the window where it matters most.**

**Build a daily-timeframe regime read** from the last 3–5 daily candles, computed
pre-market, available from the first candle. Journal it alongside the intraday regime.
Do **not** gate trades on it initially — log both, and let the spec 09 counterfactual
study decide whether it carries information.

### ✗ M-3 — The "regime-break candle" rule is missing
`mythinking.md` §6: *"Pehli candle jo pichli 10 se DOUBLE ho → kuch badal gaya. **Board
reset karo.** Purane level shaq ke daayre me."*

The level engine kills levels four ways — touches, acceptance, TTL, distance. **None of
them is "something just changed."** A single candle doubling the prior 10 is the
cheapest available signal that the regime shifted, and the human treats every prior
level as suspect after it.

**Build it as a grade demotion, not a deletion:** on a 1m candle whose range ≥ 2× the
mean range of the prior 10, demote every level born before it by one grade (A→B, B→C)
and set `regime_break_at`. Grade A is required to trigger a setup, so this
automatically suspends trading on stale levels without destroying the book. Levels can
re-earn Grade A by being tested and holding after the break.

### ⚠ M-4 — "Two losses → re-map" was deliberately narrowed to "two losses → stop"
`mythinking.md` §6: *"Meri 2 trade fail ho gayi → **mera din ka read galat hai.** Ya
re-map, ya chart band."* The specs implement only "chart band."

**This is the correct choice and should stay.** "Re-map after two losses" is where
discretion re-enters a mechanical system, and it is the exact behaviour that turns two
losses into five. Keep the hard stop.

But **journal it honestly**: on the second loss, write the state board and what a re-map
*would* have concluded, without acting on it. After a few months that log answers
whether the human's instinct to re-map was information or was tilt.

### ✓ Everything else survived
Three modes and the 70/25/5 split · 1m detection suppressed outside ALERT · the 3-4
minute pause before a 15m close · the opening range · third-touch exhaustion · stop
beyond the wick tip scaled by ATR · size derived from the stop and never the reverse ·
invalidation before the hard stop · time stop · mandatory breakeven at T1 · trailing on
5m rather than 1m · the rule-follow audit column · and the cost honesty of §9, which v2
promoted from a warning into a gate.

The hierarchy in `mythinking.md` §14 — risk cap first, trade count second, cost third,
exits fourth, entry timing fifth, level identification sixth — is respected by the
architecture. The gates that fire earliest and hardest are the ones at the top of that
list. That ordering is the most valuable thing in the whole design, and it should
survive every future change.

---

## 8. END OF EVERY SESSION

Write a short handover in `PROGRESS.md`:

```markdown
## Session N — YYYY-MM-DD
Phase: P2 (guards + modes)
Done: time_guard, vol_guard, event_guard + tests (34 passing)
Not done: session_store persistence — started, not wired
New decisions: D-012 (see DECISIONS.md)
Blocked on: events.yaml is empty — needs RBI dates from the user
Next: session_store, then the restart test
```

Do not mark a phase complete with failing or skipped tests. A phase that is 90% done is
a phase that is not done, and in this build the last 10% is usually the part that
handles the case that loses money.
