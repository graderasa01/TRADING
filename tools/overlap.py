#!/usr/bin/env python3
"""
overlap.py — the P1 gate. Spec 09 §3.2b.

    python tools/overlap.py
    python tools/overlap.py --self-check      # the trader against themselves

## What this scores

> *"If the level engine is wrong, **nothing downstream can be right.** A perfect risk
> engine sizing a perfect setup at the wrong level is a perfect way to lose money."*

```
matched   engine line within max(10 pts, 0.4 x ATR20_1m) of a human line
missed    human drew it, engine has nothing there            <- the dangerous one
invented  engine drew it, human sees nothing there

overlap = matched / (matched + missed)
noise    = invented / total_engine_lines
```

Grade A only. Spec 09: *"Grade B and C are context, and the human does not draw context."*

## Three choices the spec leaves open, and how they are made here

**1. Which book?** The spec says "the engine's active book" without naming a moment. The
closing book is 8 lines; a human marking a full-day chart marks levels that mattered
*during* the day, some of which the engine correctly killed by 14:00. Scoring only the
close would count a correctly-expired level as a miss. So both are reported:

* `AT CLOSE` — the active Grade A book at 15:29. The strict reading.
* `EVER` — every level that was Grade A and active at any point in the session. The
  generous reading, and the fairer comparison against a human's full-day chart.

The truth is between them, and the gap between the two numbers is itself information: a
large gap means the engine finds the right places and then discards them.

**2. Which ATR?** `0.4 x ATR20_1m` needs a moment too. The **median ATR20 across the
session** is used, not the closing value — a day that ends quiet would otherwise get a
tight tolerance applied to levels drawn during its loud hours.

**3. Matching is one-to-one.** Pairs are matched nearest-first, and each line on each side
is used at most once. Without that, one engine line sitting between two human lines
"matches" both and the overlap silently inflates — which matters here precisely because
the engine is known to draw near-duplicates.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.config.loader import load_config  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.p1_pipeline import P1Pipeline  # noqa: E402

ANNOTATION_DIR = REPO_ROOT / "annotations" / "p1_overlap"
RULE = "=" * 74


@dataclass
class Score:
    matched: int = 0
    missed: list[float] = field(default_factory=list)
    invented: list[float] = field(default_factory=list)
    human: int = 0
    engine: int = 0
    tolerance: float = 0.0

    @property
    def overlap(self) -> float:
        denom = self.matched + len(self.missed)
        return self.matched / denom if denom else 0.0

    @property
    def noise(self) -> float:
        return len(self.invented) / self.engine if self.engine else 0.0


def match(human: list[float], engine: list[float], tolerance: float) -> Score:
    """Nearest-first, one-to-one. See the module docstring, choice 3."""
    pairs = sorted(((abs(h - e), i, j) for i, h in enumerate(human)
                    for j, e in enumerate(engine) if abs(h - e) <= tolerance))
    used_h: set[int] = set()
    used_e: set[int] = set()
    score = Score(human=len(human), engine=len(engine), tolerance=tolerance)
    for _, i, j in pairs:
        if i in used_h or j in used_e:
            continue
        used_h.add(i)
        used_e.add(j)
        score.matched += 1
    score.missed = [h for i, h in enumerate(human) if i not in used_h]
    score.invented = [e for j, e in enumerate(engine) if j not in used_e]
    return score


def load_annotations() -> dict[str, list[float]]:
    import yaml

    out: dict[str, list[float]] = {}
    for path in sorted(ANNOTATION_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        key = path.stem
        out[key] = sorted(float(lv["price"]) for lv in (raw.get("levels") or []))
    return out


def engine_book(symbol: str, day: date) -> tuple[list[float], list[float], float]:
    """(grade A at close, grade A ever, median ATR20). Round numbers excluded — spec 03
    §6 demotes them and the human does not draw them as levels."""
    session = ReplayFeed(symbol, on_gap="skip").session(day)
    pipeline = P1Pipeline(load_config(strict=False), session)
    ever: dict[str, float] = {}
    atrs: list[float] = []
    for candle in session.candles:
        pipeline.on_candle(candle)
        board = pipeline.records[-1].board
        if board.atr20_1m:
            atrs.append(float(board.atr20_1m))
        for level in pipeline.levels.book.active():
            if level.grade.value == "A" and not level.is_round_number:
                ever[level.id] = float(level.body_edge)
    at_close = sorted(float(lv.body_edge) for lv in pipeline.levels.book.active()
                      if lv.grade.value == "A" and not lv.is_round_number)
    return at_close, sorted(ever.values()), (statistics.median(atrs) if atrs else 20.0)


def band(overlap: float) -> tuple[str, str]:
    if overlap >= 0.75:
        return "PROCEED", "the arithmetic reproduces the eye"
    if overlap >= 0.60:
        return "PROCEED, documented", "broadly right, tuning needed — read the MISSES"
    if overlap >= 0.40:
        return "STOP", "the engine finds different levels than the human. Diagnose first"
    return "STOP", "the foundation is not the strategy in the specs"


def report(symbol: str) -> int:
    annotations = load_annotations()
    sessions = {k: v for k, v in annotations.items() if "--" not in k}
    totals = {"close": Score(), "ever": Score()}

    print(f"\n{RULE}\nP1 LEVEL-OVERLAP GATE — spec 09 §3.2b\n{RULE}")
    for key, human in sessions.items():
        day = date.fromisoformat(key)
        at_close, ever, atr = engine_book(symbol, day)
        tol = max(10.0, 0.4 * atr)
        a, b = match(human, at_close, tol), match(human, ever, tol)

        print(f"\n{day}   human {len(human):>2} lines   ATR20 median {atr:>5.1f}   "
              f"tolerance +/-{tol:.1f}")
        for name, score in (("at close", a), ("ever  ", b)):
            print(f"    {name}  engine {score.engine:>3}   matched {score.matched:>2}   "
                  f"missed {len(score.missed):>2}   invented {len(score.invented):>3}   "
                  f"overlap {score.overlap * 100:>5.1f}%   noise {score.noise * 100:>5.1f}%")
        if a.missed:
            print(f"    MISSED at close: {', '.join(f'{m:,.0f}' for m in a.missed)}")

        for name, score in (("close", a), ("ever", b)):
            totals[name].matched += score.matched
            totals[name].missed += score.missed
            totals[name].invented += score.invented
            totals[name].human += score.human
            totals[name].engine += score.engine

    print(f"\n{RULE}\nAGGREGATE — {len(sessions)} sessions, "
          f"{totals['close'].human} human lines\n{RULE}")
    for name in ("close", "ever"):
        s = totals[name]
        verdict, why = band(s.overlap)
        print(f"\n  {name.upper():<6} engine lines {s.engine:>4}   matched {s.matched:>3}   "
              f"missed {len(s.missed):>3}   invented {len(s.invented):>4}")
        print(f"         overlap {s.overlap * 100:.1f}%   noise {s.noise * 100:.1f}%")
        print(f"         {verdict} — {why}")
    print()
    return 0


def self_check() -> int:
    """The trader against themselves.

    2025-12-19 was marked twice, by accident. That is an unplanned repeatability test and
    it is worth more than it looks: the overlap gate scores the engine against a human
    ground truth, and **a ground truth is only as sharp as the hand that drew it.** If the
    same person marking the same chart twice agrees with themselves 80% of the time, then
    an engine scoring 80% is at the ceiling, not below it.
    """
    annotations = load_annotations()
    pairs = [(k, k.split("--")[0]) for k in annotations if "--" in k]
    if not pairs:
        print("no repeat markings found", file=sys.stderr)
        return 1
    print(f"\n{RULE}\nSELF-CONSISTENCY — the trader against the trader\n{RULE}")
    for second, first in pairs:
        if first not in annotations:
            continue
        day = date.fromisoformat(first)
        _, _, atr = engine_book("NIFTY BANK", day)
        tol = max(10.0, 0.4 * atr)
        a, b = annotations[first], annotations[second]
        score = match(a, b, tol)
        print(f"\n  {day}   first marking {len(a)} lines   second {len(b)} lines   "
              f"tolerance +/-{tol:.1f}")
        print(f"    agreed on          {score.matched}")
        print(f"    only in the first  {len(score.missed)}  "
              f"{', '.join(f'{m:,.1f}' for m in score.missed) or '-'}")
        print(f"    only in the second {len(score.invented)}  "
              f"{', '.join(f'{m:,.1f}' for m in score.invented) or '-'}")
        union = score.matched + len(score.missed) + len(score.invented)
        print(f"\n    self-agreement     {score.matched / union * 100:.0f}%  "
              f"(agreed / everything either marking drew)")
        print("    -> an engine cannot meaningfully score above this against this "
              "ground truth.")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--self-check", action="store_true",
                    help="score the trader's repeat marking against their first")
    args = ap.parse_args(argv)
    return self_check() if args.self_check else report(args.symbol)


if __name__ == "__main__":
    raise SystemExit(main())
