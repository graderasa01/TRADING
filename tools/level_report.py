#!/usr/bin/env python3
"""
level_report.py — run the level engine over sessions and print what it built.

    python tools/level_report.py --day 2026-03-04
    python tools/level_report.py --selection reports/charts/selection.json
    python tools/level_report.py --sample 40 --seed 7

This is the P1 equivalent of the detection-count block `BUILD-BRIEF.md` §4b requires
from P3 onward, and it exists for the same reason: **a level engine that silently builds
the wrong book looks exactly like one that builds the right book.**

`prototype/FINDINGS.md` is a complete engine that never traded, and four of its six bugs
were only visible as a distribution — 6 of 8 slots filled with Grade C axes, zero Grade A
levels all session, one LAUNCH level in a day. None of them fails a unit test. All of
them are obvious in this table.

The thresholds checked here are spec 10 §3.1's pipeline-liveness checks, pulled forward
from P2 because they are useful the moment there is a book to check.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401  (console encoding, see module)

from src.config.loader import load_config  # noqa: E402
from src.domain.models import Grade  # noqa: E402
from src.feed.aggregator import Aggregator  # noqa: E402
from src.feed.replay_feed import ReplayFeed, Session  # noqa: E402
from src.indicators.atr import AtrBook  # noqa: E402
from src.levels.engine import LevelEngine  # noqa: E402

# spec 10 §3.1 — pipeline liveness. `fail` means the engine cannot do its job.
CHECKS = [
    ("levels_born", "levels created", lambda s: s["born"], 5, "warn",
     "Detectors are not firing. Check ATR and swing confirmation."),
    ("grade_a_exists", "Grade A levels", lambda s: s["grade_a_ever"], 1, "FAIL",
     "Nothing is tradeable. This is Bug 1 — no setup can ever trigger."),
    ("launch_levels", "LAUNCH levels", lambda s: s["kinds"].get("launch", 0), 1, "warn",
     "The 'highest-value 1m level' detector is not working."),
    ("book_not_starved", "levels alive at close", lambda s: s["alive_non_round"], 2, "warn",
     "The book emptied — the cap or the death rules are too aggressive."),
]

# spec 10 §3.2 — distribution sanity. These are ceilings, not floors: something is
# dominating. Bug 5 lived here (BREAK axes filled 6 of 8 slots).
CEILINGS = [
    ("break_rate", "axis-creating breaks", lambda s: s["kinds"].get("break", 0), 15,
     "The axis threshold is too loose — every body close is manufacturing a level."),
    ("kind_dominance", "largest kind share %", lambda s: s["kind_share_max"], 60,
     "One detector is the book. Bug 5 was BREAK axes at 75% of the slots."),
    ("grade_dominance", "largest grade share %", lambda s: s["grade_share_max"], 90,
     "Grading is not discriminating — likely an undefined input, as in Bug 1."),
]


def run_session(cfg, session: Session) -> dict[str, Any]:
    engine = LevelEngine(cfg, session.symbol, session.pdh, session.pdl, session.pdc)
    agg, atr = Aggregator(), AtrBook()
    grade_a_ever: set[str] = set()
    grade_history: Counter[str] = Counter()

    for candle in session.candles:
        update = agg.on_candle(candle)
        atr.on_1m(candle)
        if update.m5:
            atr.on_5m(update.m5)
        engine.on_candle(candle, atr.atr20_1m, update.m5, update.m15)
        for lv in engine.book.active():
            grade_history[lv.grade.value] += 1
            if lv.grade is Grade.A:
                grade_a_ever.add(lv.id)

    born = [e for e in engine.events if e["event"] == "born"]
    alive = engine.book.active()
    non_round = [lv for lv in alive if not lv.is_round_number]
    kinds = Counter(e["kind"] for e in born)
    grades = Counter(grade_history)
    return {
        "kind_share_max": 100 * max(kinds.values()) / max(sum(kinds.values()), 1),
        "grade_share_max": 100 * max(grades.values()) / max(sum(grades.values()), 1),
        "day": session.day,
        "born": len(born),
        "kinds": dict(Counter(e["kind"] for e in born)),
        "tfs": dict(Counter(e["tf"] for e in born)),
        "alive": len(alive),
        "alive_non_round": len(non_round),
        "alive_kinds": dict(Counter(lv.kind.value for lv in non_round)),
        "grades_now": dict(Counter(lv.grade.value for lv in alive)),
        "grade_candle_share": dict(grade_history),
        "grade_a_ever": len(grade_a_ever),
        "grade_a_now": sum(1 for lv in alive if lv.grade is Grade.A),
        "deaths": dict(Counter(e["reason"] for e in engine.events if e["event"] == "died")),
        "dormant_sleeps": sum(1 for e in engine.events if e["event"] == "dormant"),
        "revivals": sum(1 for e in engine.events if e["event"] == "revived"),
        "launch_near_miss": dict(Counter(
            e["reason"] for e in engine.events if e["event"] == "launch_near_miss")),
        "engine": engine,
    }


def print_one(stats: dict[str, Any]) -> None:
    print(f"\n{'=' * 66}\n{stats['day']}   levels born {stats['born']}\n{'=' * 66}")
    print(f"  by kind         {stats['kinds']}")
    print(f"  by timeframe    {stats['tfs']}")
    print(f"  alive at close  {stats['alive']}  (non-round {stats['alive_non_round']})")
    print(f"    kinds         {stats['alive_kinds']}")
    print(f"    grades        {stats['grades_now']}")
    print(f"  Grade A ever    {stats['grade_a_ever']}   now {stats['grade_a_now']}")
    print(f"  deaths          {stats['deaths']}")
    print(f"  dormancy        {stats['dormant_sleeps']} sleeps / {stats['revivals']} revivals")
    if stats["launch_near_miss"]:
        print(f"  launch missed   {stats['launch_near_miss']}")

    engine = stats["engine"]
    book = sorted(engine.book.active(), key=lambda x: -x.body_edge)
    if book:
        print("\n  BOOK AT CLOSE")
        for lv in book[:14]:
            tag = " round" if lv.is_round_number else ""
            print(f"    {lv.body_edge:>10,.1f}  {lv.kind.value:<7} {lv.born_tf:<4} "
                  f"grade {lv.grade.value}  t{lv.touches}  dep {lv.departure_speed:>5.2f}{tag}")


def print_aggregate(all_stats: list[dict[str, Any]]) -> int:
    n = len(all_stats)
    total = Counter()
    for s in all_stats:
        total["born"] += s["born"]
        total["grade_a_ever"] += s["grade_a_ever"]
        total["alive_non_round"] += s["alive_non_round"]
        for k, v in s["kinds"].items():
            total[f"kind_{k}"] += v

    print(f"\n{'=' * 66}\nAGGREGATE — {n} sessions\n{'=' * 66}")
    print(f"  levels born / session      {total['born'] / n:>7.1f}")
    for kind in ("turn", "launch", "break", "anchor"):
        share = total[f"kind_{kind}"] / max(total['born'], 1) * 100
        print(f"    {kind:<8}                 {total[f'kind_{kind}'] / n:>7.1f}  ({share:4.1f}%)")
    print(f"  Grade A reached / session  {total['grade_a_ever'] / n:>7.1f}")
    print(f"  book at close / session    {total['alive_non_round'] / n:>7.1f}  (cap 8)")
    sessions_without_a = sum(1 for s in all_stats if s["grade_a_ever"] == 0)
    print(f"  sessions with ZERO Grade A {sessions_without_a:>7}  of {n}")

    print("\n  spec 10 §3.1 liveness (per-session averages)")
    failed = 0
    for _, label, get, threshold, severity, meaning in CHECKS:
        avg = sum(get(s) for s in all_stats) / n
        ok = avg >= threshold
        mark = "ok  " if ok else ("FAIL" if severity == "FAIL" else "warn")
        print(f"    {mark}  {label:<24} {avg:>7.2f}  (need >= {threshold})")
        if not ok:
            print(f"          -> {meaning}")
            if severity == "FAIL":
                failed += 1

    for _, label, get, ceiling, meaning in CEILINGS:
        avg = sum(get(s) for s in all_stats) / n
        ok = avg <= ceiling
        print(f"    {'ok  ' if ok else 'warn'}  {label:<24} {avg:>7.2f}  (need <= {ceiling})")
        if not ok:
            print(f"          -> {meaning}")
    return failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day")
    ap.add_argument("--selection")
    ap.add_argument("--sample", type=int, help="N random sessions")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--quiet", action="store_true", help="aggregate only")
    args = ap.parse_args(argv)

    cfg = load_config(strict=False)
    feed = ReplayFeed(args.symbol, on_gap="skip")

    if args.day:
        days = [date.fromisoformat(args.day)]
    elif args.selection:
        payload = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        days = [date.fromisoformat(s["day"]) for s in payload["sessions"]]
    elif args.sample:
        available = feed.available_days()
        days = sorted(random.Random(args.seed).sample(available, min(args.sample, len(available))))
    else:
        ap.error("give --day, --selection or --sample")

    all_stats = []
    for session in feed.sessions(days=days):
        stats = run_session(cfg, session)
        all_stats.append(stats)
        if not args.quiet:
            print_one(stats)

    if not all_stats:
        print("no sessions ran", file=sys.stderr)
        return 2
    failed = print_aggregate(all_stats)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
