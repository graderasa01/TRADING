#!/usr/bin/env python3
"""
traderreplay.py — what actually happened after each Trader Reader candidate.

    python tools/traderreplay.py
    python tools/traderreplay.py --days 2026-02-16 2024-12-18 --split 400

**This is observation, not backtesting.** No orders, no sizing, no costs, no win rate.
It records what price did over the next 5, 10 and 20 candles after each candidate, so the
rules can be judged against market behaviour before a single threshold is chosen.

## What it is looking for

* after an accepted upside break, how often did price continue rather than come straight
  back?
* did a breakout with a lot of room behave differently from one with almost none?
* did a failed break reverse, or just return to the interior and break again later?
* how much of the session is `WAIT`, and is that a lot or a little?

## What it deliberately does not do

No threshold is tuned here and no rule is changed to improve a number. The point is the
**distribution**, and the fastest way to destroy it is to start fitting to it. A move of
+30 points is also not a profit: on monthly Bank Nifty options the round trip is 44-64%
of a 25-point R (`CLAUDE.md` §11), so any of this that survives still has to survive
costs afterwards.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.anchors import build_anchors  # noqa: E402
from src.boxes.frontier import run  # noqa: E402
from src.boxes.snapshot import build_snapshot  # noqa: E402
from src.boxes.structure import build_chain  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.livemap.interpreter import Interpreter  # noqa: E402
from src.livemap.trader import (  # noqa: E402
    BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK, WAIT, read_all)

DEFAULT_DAYS = ["2026-02-16", "2025-09-12", "2024-12-18", "2024-09-06", "2023-10-04"]
HORIZONS = (5, 10, 20)


def load(symbol: str, day: date, n: int = 1000):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-5:]
    out = []
    for s in feed.sessions(days=days):
        out.extend(s.candles)
    return out[-n:]


def outcome(candles, index: int, direction: str, bars: int) -> float | None:
    """Points gained in the candidate's own direction. `None` if the canvas ends first."""
    j = index + bars
    if j >= len(candles):
        return None
    move = float(candles[j].c - candles[index].c)
    return move if direction != "down" else -move


def collect(symbol: str, days: list[str], split: int) -> list[dict]:
    rows: list[dict] = []
    for iso in days:
        candles = load(symbol, date.fromisoformat(iso))
        snap = build_snapshot(candles[:split], symbol)
        chain, _ = build_chain(candles[:split])
        anchors = build_anchors(chain, candles[:split])
        f = run(snap, candles[:split], candles[split:])
        states = read_all(Interpreter(snap, f, anchors=anchors).states())

        for t in states:
            row = {"day": iso, "index": t.index, "family": t.family,
                   "location": t.location, "space": t.space_points,
                   "space_atr": t.space_atr, "revisit": t.revisit,
                   "arrival": t.arrival_direction,
                   "direction": t.break_direction or t.failed_side}
            if t.is_candidate:
                d = t.break_direction or ("down" if t.failed_side == "up" else "up")
                for h in HORIZONS:
                    row[f"h{h}"] = outcome(candles, t.index, d, h)
            rows.append(row)
    return rows


def _summary(values: list[float]) -> str:
    if not values:
        return "     —"
    med = statistics.median(values)
    pos = sum(1 for v in values if v > 0)
    return f"{med:+7.0f} pts   {100 * pos / len(values):3.0f}% positive"


def report(rows: list[dict]) -> list[str]:
    out: list[str] = []
    fam = Counter(r["family"] for r in rows)
    total = len(rows)
    out.append(f"{total} candles read")
    for name in (WAIT, BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK):
        out.append(f"  {fam[name]:>5}  {100 * fam[name] / total:5.1f}%  {name}")
    cands = [r for r in rows if r["family"] != WAIT]
    out.append(f"  {len(cands):>5}  {100 * len(cands) / total:5.1f}%  candidates in all")

    out.append("")
    out.append("what happened next, by family")
    out.append(f"{'family':<30} {'n':>4}  " +
               "  ".join(f"{'+' + str(h):>26}" for h in HORIZONS))
    for name in (BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK):
        group = [r for r in cands if r["family"] == name]
        cells = []
        for h in HORIZONS:
            vals = [r[f"h{h}"] for r in group if r.get(f"h{h}") is not None]
            cells.append(f"{_summary(vals):>26}")
        out.append(f"{name:<30} {len(group):>4}  " + "  ".join(cells))

    out.append("")
    out.append("does SPACE matter? breakout candidates bucketed by room ahead")
    buckets = defaultdict(list)
    for r in cands:
        if r["family"] not in (BREAKOUT_LONG, BREAKOUT_SHORT):
            continue
        a = r["space_atr"] or 0.0
        key = ("no reference" if r["space"] is None else
               "< 0.5 ATR" if a < 0.5 else
               "0.5 - 2 ATR" if a < 2 else
               "2 - 6 ATR" if a < 6 else "> 6 ATR")
        buckets[key].append(r)
    order = ["< 0.5 ATR", "0.5 - 2 ATR", "2 - 6 ATR", "> 6 ATR", "no reference"]
    out.append(f"{'space':<16} {'n':>4}  " +
               "  ".join(f"{'+' + str(h):>26}" for h in HORIZONS))
    for key in order:
        group = buckets.get(key, [])
        if not group:
            continue
        cells = []
        for h in HORIZONS:
            vals = [r[f"h{h}"] for r in group if r.get(f"h{h}") is not None]
            cells.append(f"{_summary(vals):>26}")
        out.append(f"{key:<16} {len(group):>4}  " + "  ".join(cells))

    out.append("")
    out.append("did arrival direction or a revisit matter?")
    for label, pick in (("arrived up", lambda r: r["arrival"] == "up"),
                        ("arrived down", lambda r: r["arrival"] == "down"),
                        ("revisit", lambda r: r["revisit"]),
                        ("first visit", lambda r: not r["revisit"])):
        group = [r for r in cands if pick(r) and r.get("h10") is not None]
        if group:
            vals = [r["h10"] for r in group]
            out.append(f"  {label:<14} {len(group):>4}   {_summary(vals)}")

    spaces = [float(r["space"]) for r in cands if r["space"] is not None]
    if spaces:
        spaces.sort()
        out.append("")
        out.append(f"space distribution over {len(spaces)} candidates: "
                   f"min {spaces[0]:.0f}  p25 {spaces[len(spaces) // 4]:.0f}  "
                   f"median {statistics.median(spaces):.0f}  "
                   f"p75 {spaces[3 * len(spaces) // 4]:.0f}  max {spaces[-1]:.0f} pts")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--days", nargs="+", default=DEFAULT_DAYS)
    ap.add_argument("--split", type=int, default=400)
    args = ap.parse_args(argv)

    rows = collect(args.symbol, args.days, args.split)
    for line in report(rows):
        print(line)
    print("\nNo orders, no sizing, no costs. A point move is not a profit — "
          "CLAUDE.md §11 still applies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
