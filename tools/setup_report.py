#!/usr/bin/env python3
"""
setup_report.py — the P3 gate. BUILD-BRIEF §4b.

    python tools/setup_report.py --sample 10 --seed 424242
    python tools/setup_report.py --day 2026-02-16 --verbose

## Why fixtures do not close P3

> *"Fixtures prove a detector fires on a candle sequence built for it. They do not prove
> the detector is **reachable** inside the full pipeline, where guards, modes, grading and
> the level cap all run first."*

`prototype/FINDINGS.md` made that concrete: Setup B's six conditions all passed on a
textbook sweep at PDL, and the detector never ran, because the mode was `BLOCKED`. A
fixture test would have been green. The system could not trade, and nothing looked wrong.

So this runs whole sessions through the real pipeline — aggregator, levels, structure,
board, guards, mode machine, then the setups — and counts where things stopped.

```
levels born ......................... > 20
levels reaching Grade A ............. > 0
candles in ALERT .................... > 0
setups DETECTED (reached evaluate) .. > 0
  of which A / B / C ................ each > 0 over ~10 sessions
setups rejected, by gate ............ the histogram
signals ............................. may legitimately be 0
```

**Signals may be zero. Detections may not be.** A zero in any other row means the market
never reached the part of the engine that decides, and nothing built on top of that will
help.

## What this is NOT measuring

Nothing here says a detection was *correct*. A detector firing forty times a day passes
every count in this block and is just as broken as one firing zero times. That question
is answered by rendering the detections on the chart and looking at them, which is what
`--chart` writes out.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.config.loader import load_config  # noqa: E402
from src.domain.models import Mode  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.guards.engine import GuardEngine, SessionContext, resolve_mode  # noqa: E402
from src.p1_pipeline import P1Pipeline  # noqa: E402
from src.setups.base import SetupContext, evaluate  # noqa: E402
from src.state.session_store import SessionState  # noqa: E402

RULE = "=" * 74


@dataclass
class Counts:
    sessions: int = 0
    candles: int = 0
    levels_born: int = 0
    grade_a: int = 0
    modes: Counter = field(default_factory=Counter)
    evaluated: int = 0                    # candles where the setup layer actually ran
    detections: Counter = field(default_factory=Counter)
    gates: Counter = field(default_factory=Counter)
    detail: list[dict[str, Any]] = field(default_factory=list)


def run_session(cfg, session, counts: Counts, *, collect: bool = False) -> None:
    pipeline = P1Pipeline(cfg, session)
    guards = GuardEngine(cfg)
    state = SessionState(trading_date=session.day)
    sctx = SessionContext(day=session.day, gap_pct=session.open_gap_pct)
    seen_a: set[str] = set()
    born: set[str] = set()

    for i, candle in enumerate(session.candles):
        pipeline.on_candle(candle)
        record = pipeline.records[-1]
        board = record.board
        counts.candles += 1

        born |= set(record.new_levels)
        for level in pipeline.levels.book.active():
            if level.grade.value == "A":
                seen_a.add(level.id)

        outcome = guards.evaluate(candle, sctx, state, board.atr_1m, i + 1, None)
        alert_distance = cfg.effective("modes.alert_distance_points",
                                       "modes.alert_distance_atr_mult", board.atr_1m)
        active = board.active_level
        mode = resolve_mode(outcome, position_open=False,
                            distance_to_active=board.distance_to_active,
                            alert_distance=alert_distance,
                            active_is_round=bool(active and active.is_round_number))
        counts.modes[mode.value.upper()] += 1
        if not outcome.passed:
            counts.gates[f"guard:{outcome.failed_gate}"] += 1

        if mode is not Mode.ALERT or active is None:
            continue

        # Every Grade A level within reach, not only the nearest one.
        #
        # `board.active_level` is the nearest level of ANY grade — that is what the mode
        # machine keys off (spec 05 §6) and it is correct there. But feeding only that
        # level to the setups means a nearer Grade C line hides a tradeable Grade A line
        # sitting a few points behind it, and every detector returns `no_live_level`. On
        # the first run that was 1,306 of 1,454 evaluations: the mode said wake up, and
        # the only level it offered could never be traded. That is `prototype/FINDINGS.md`
        # Bug 3's exact shape, arriving from a different direction.
        price = board.index
        candidates = [lv for lv in board.levels_above + board.levels_below
                      if abs(lv.body_edge - price) <= alert_distance
                      and lv.grade.value == "A" and not lv.is_round_number]
        if not candidates:
            counts.gates["no Grade A level within alert_distance"] += 1
            continue

        counts.evaluated += 1
        results = []
        for level in sorted(candidates, key=lambda lv: abs(lv.body_edge - price)):
            ctx = SetupContext(
                candles=session.candles[:i + 1], index=i, board=board, level=level,
                cfg=cfg, guard=outcome, state=state, mode=mode,
                trend_5m=getattr(board.trend_5m, "value", str(board.trend_5m)))
            results += evaluate(ctx)
        for result in results:
            if result.detection is not None:
                counts.detections[result.setup] += 1
                if collect:
                    counts.detail.append({
                        "day": str(session.day), "candle": i,
                        "time": candle.open_time.strftime("%H:%M"),
                        "setup": result.setup, "side": result.detection.side,
                        "level": result.detection.level_id,
                        "entry": float(result.detection.entry_ref),
                        "extreme": float(result.detection.extreme),
                        "r_points": abs(float(result.detection.entry_ref
                                              - result.detection.extreme)),
                        "evidence": {k: (float(v) if isinstance(v, Decimal) else v)
                                     for k, v in result.detection.evidence.items()},
                    })
            else:
                counts.gates[f"{result.setup}:{result.gate}"] += 1

    counts.levels_born += len(born)
    counts.grade_a += len(seen_a)
    counts.sessions += 1


def report(counts: Counts) -> int:
    n = max(1, counts.sessions)
    print(f"\n{RULE}\nP3 DETECTION GATE — BUILD-BRIEF §4b\n{counts.sessions} sessions, "
          f"{counts.candles:,} candles\n{RULE}\n")

    rows = [
        ("levels born", counts.levels_born / n, "> 20", counts.levels_born / n > 20),
        ("levels reaching Grade A", counts.grade_a / n, "> 0", counts.grade_a > 0),
        ("candles in ALERT", counts.modes["ALERT"] / n, "> 0", counts.modes["ALERT"] > 0),
        ("setup layer reached", counts.evaluated / n, "> 0", counts.evaluated > 0),
        ("setups DETECTED", sum(counts.detections.values()) / n, "> 0",
         sum(counts.detections.values()) > 0),
    ]
    ok = True
    for label, value, need, passed in rows:
        ok &= passed
        print(f"  {'ok  ' if passed else 'FAIL'}  {label:<28} {value:>8.2f} / session"
              f"   (need {need})")

    print(f"\n  by setup, over {counts.sessions} sessions")
    for setup in ("A_flip_retest", "B_sweep_reclaim", "C_range_break_retest"):
        hits = counts.detections[setup]
        passed = hits > 0
        ok &= passed
        print(f"  {'ok  ' if passed else 'FAIL'}  {setup:<28} {hits:>8}   (need > 0)")

    print("\n  mode share")
    total = sum(counts.modes.values()) or 1
    for mode, hits in counts.modes.most_common():
        print(f"        {mode:<12} {hits / total * 100:>6.1f}%")

    print("\n  where it stopped — the histogram spec 09 §3 asks for")
    for gate, hits in counts.gates.most_common(18):
        print(f"        {gate:<44} {hits:>7,}")

    print("\n  signals                       0   (P3 has no risk engine — "
          "signals are P4 onward, and may legitimately be 0)")

    print(f"\n{RULE}")
    if ok:
        print("  GATE PASSED — every counter is above its floor.\n"
              "  This says the pipeline is REACHABLE. It says nothing about whether the\n"
              "  detections are RIGHT — render them and look.")
    else:
        print("  GATE FAILED — a zero above means the market never reached the part of\n"
              "  the engine that decides. Stop and diagnose before P4.")
    print(RULE + "\n")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day")
    ap.add_argument("--selection")
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--seed", type=int, default=424242)
    ap.add_argument("--chart", help="write the detections to this JSON for the chart")
    args = ap.parse_args(argv)

    cfg = load_config(strict=False)
    feed = ReplayFeed(args.symbol, on_gap="skip")

    if args.day:
        days = [date.fromisoformat(args.day)]
    elif args.selection:
        payload = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        days = [date.fromisoformat(s["day"]) for s in payload["sessions"]]
    else:
        available = feed.available_days()
        random.Random(args.seed).shuffle(available)
        days = sorted(available[:args.sample])

    counts = Counts()
    for session in feed.sessions(days=days):
        run_session(cfg, session, counts, collect=bool(args.chart) or bool(args.day))

    code = report(counts)

    if counts.detail:
        print("  DETECTIONS")
        for hit in counts.detail[:25]:
            print(f"    {hit['day']}  c{hit['candle']:>3} {hit['time']}  "
                  f"{hit['setup']:<22} {hit['side']:<5} entry {hit['entry']:>10,.1f}  "
                  f"stop-side {hit['extreme']:>10,.1f}  R {hit['r_points']:>5.1f} pts")
        if len(counts.detail) > 25:
            print(f"    ... and {len(counts.detail) - 25} more")
        print()
    if args.chart:
        Path(args.chart).parent.mkdir(parents=True, exist_ok=True)
        Path(args.chart).write_text(json.dumps(counts.detail, indent=1), encoding="utf-8")
        print(f"  wrote {args.chart}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
