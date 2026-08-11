# Bank Nifty Price Action Co-Pilot

A rules-based, indicator-free price action engine for Bank Nifty.
**Current stage: paper trading** — live Kite data in, simulated fills out, no real orders.

---

## What it does

Reads 1-minute Bank Nifty **index** candles and, on every closed candle:

1. maintains a level book (max 8 lines, born four ways, graded A/B/C, pruned when dead)
2. maintains a structure board (swings, break of structure, trend, regime)
3. maintains the 8 state variables a trader holds in working memory
4. runs guards (time window, volatility, session limits)
5. sits in `WATCH` ~70% of the session and does nothing
6. wakes to `ALERT` only when price nears a Grade A level
7. evaluates exactly three setups — flip retest, sweep reclaim, range break retest
8. sizes from the stop, checks space to the **nearest** obstacle, and emits a signal
9. or — far more often — emits `NO_TRADE` with the exact gate that failed

Maximum 3 trades a day. Stops for the day after 2 consecutive losses or −2R.

---

## The rules it encodes

```
15m says WHERE.  5m says WHAT.  1m says WHEN and WHERE THE STOP GOES.
1m is never allowed to set direction.
```

```
Signal on the index.  Execute on the option.  Monitor the stop on the index.
```

```
The default answer is NO TRADE. Every rejection is logged with its reason —
that log is the most valuable thing this system produces.
```

---

## For Claude Code — start here

1. Read **`CLAUDE.md`** in full. It is the constitution: ten non-negotiables, the
   pipeline, the repo layout, prohibitions, and the phased build order.
2. Read the spec for the module you are about to build. Do not build ahead of the phase.
3. Every threshold comes from `config/params.yaml`. A numeric literal in a logic file
   is a bug.
4. Write the tests listed at the bottom of each spec **before** wiring the module in.

### Specs

| File | Covers |
|---|---|
| `specs/01-ARCHITECTURE.md` | pipeline, time model, module boundaries, failure policy |
| `specs/02-DATA-CONTRACT.md` | every dataclass, the canonical rejection-gate vocabulary |
| `specs/03-LEVEL-ENGINE.md` | TURN / LAUNCH / BREAK / ANCHOR, zones, grading, pruning |
| `specs/04-STRUCTURE-AND-STATE.md` | swings, BOS, regime, HTF nesting laws, landing ladder |
| `specs/05-GUARDS-AND-MODES.md` | time and volatility gates, session limits, mode machine |
| `specs/06-SETUPS.md` | Setup A / B / C, exact trigger conditions, what is *not* a setup |
| `specs/07-RISK-AND-EXITS.md` | stop placement, R bounds, space check, sizing, six exits |
| `specs/08-OPTIONS-AND-KITE.md` | ATM selection, Kite adapter, paper fills, cost model |
| `specs/09-JOURNAL-AND-TESTS.md` | journal schema, reports, fixtures, acceptance criteria |

### Build phases

`P0` models + feed + aggregator → `P1` levels + structure + board → `P2` guards + modes
→ `P3` setups → `P4` risk → `P5` options + paper broker → `P6` exits → `P7` journal
→ `P8` live Kite feed (still paper fills) → `P9` six-month replay validation

Each phase needs green tests before the next begins.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export KITE_API_KEY=...          # never commit these
export KITE_API_SECRET=...

# set risk_per_trade_rupees in config/params.yaml — the engine will not start without it
# fill in costs.yaml and set last_verified

python run_paper.py --i-understand-this-is-paper
```

Create a file named `HALT` in the repo root to stop the engine at any time.

---

## Before you trust any number

- Every parameter in `config/params.yaml` is a **hypothesis**, not a measurement.
- Every rate in `config/costs.yaml` must be verified against the broker's current
  published charges. They change.
- Slippage values are guesses until calibrated against observed quotes.
- The no-look-ahead truncation test must be green, or nothing else means anything.
- Daily candle reconciliation must PASS, or that day's results are marked SUSPECT.

## Before anyone thinks about live

P9 must show an edge **net of costs**, consistent across regimes and time buckets. Note
that ~3 trades/week over 6 months is roughly 70 trades — too few to distinguish an edge
from luck with confidence. P9 can disqualify the system; it cannot prove it works.

Separately, the current SEBI and exchange requirements for retail algorithmic order
placement must be confirmed directly with the broker before any automated live
execution. That is a prerequisite, not a formality.

If P9 shows no edge after costs, the correct response is to stop or simplify — not to
add a fourth setup. Filters added after seeing results are curve-fitting and will not
survive next month's market.

---

**This system can lose money. Build it carefully, test it honestly, size it small.**
