#!/usr/bin/env python3
"""
select_sessions.py — pick sessions for the P1 overlap gate, mechanically.

    python tools/select_sessions.py --purpose p1_overlap --out reports/charts/selection.json

Spec 09 §3.2b asks for 10 sessions "across different regimes — 3 trending, 3 ranging,
2 gap days, 1 monthly expiry, 1 high-volatility."

**Why this is a tool and not a judgement call.** If I pick the days, I pick the ones I
noticed, and the ones I noticed are the ones where something happened. That is
survivorship bias, and spec 12 §3.3 names it as the thing that makes a backtest pretty
and a live account ugly. So the classification is arithmetic, the sample is random
within each stratum, and the seed is written into the output — anyone can re-run this
and get the same ten days.

Classification is deliberately engine-free. It uses only OHLC, so it cannot be
contaminated by the level engine it is meant to test.

    expiry     last Tuesday of the month (Bank Nifty is monthly since Nov 2024)
    gap        |open - prev_close| / prev_close x 100 > gap_regime.gap_pct_threshold
    high_vol   session median ATR14 in the top decile of the sample
    trending   |close - open| / day_range >= 0.60   — the day went somewhere
    ranging    |close - open| / day_range <= 0.25 and day range below the median

A day is assigned to exactly one bucket, in that priority order, so the strata are
disjoint and a "trending" day is never secretly also the gap day.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401  (console encoding, see module)

from src.feed.replay_feed import ReplayFeed  # noqa: E402

TREND_MIN = 0.60
RANGE_MAX = 0.25
GAP_PCT = 0.40
HIGH_VOL_PERCENTILE = 90

P1_OVERLAP_QUOTA = {"trending": 3, "ranging": 3, "gap": 2, "expiry": 1, "high_vol": 1}


def is_monthly_expiry(day: date) -> bool:
    """Last Tuesday of the month. Bank Nifty lost weeklies on 20 Nov 2024."""
    if day.weekday() != 1:
        return False
    return (day + timedelta(days=7)).month != day.month


def atr14(candles, period: int = 14) -> list[float]:
    if len(candles) < period:
        return []
    ranges = [float(c.h - c.l) for c in candles]
    out, running = [], sum(ranges[:period])
    out.append(running / period)
    for i in range(period, len(ranges)):
        running += ranges[i] - ranges[i - period]
        out.append(running / period)
    return out


def profile(session) -> dict[str, Any]:
    cs = session.candles
    high = max(float(c.h) for c in cs)
    low = min(float(c.l) for c in cs)
    day_range = high - low
    body = abs(float(cs[-1].c) - float(cs[0].o))
    series = atr14(cs)
    return {
        "day": session.day,
        "open": float(cs[0].o), "close": float(cs[-1].c),
        "high": high, "low": low, "day_range": day_range,
        "directionality": (body / day_range) if day_range else 0.0,
        "median_atr": statistics.median(series) if series else 0.0,
        "gap_pct": float(session.open_gap_pct) if session.open_gap_pct is not None else None,
        "candles": len(cs),
    }


def classify(p: dict[str, Any], atr_cut: float, range_median: float) -> str:
    if is_monthly_expiry(p["day"]):
        return "expiry"
    if p["gap_pct"] is not None and abs(p["gap_pct"]) > GAP_PCT:
        return "gap"
    if p["median_atr"] >= atr_cut:
        return "high_vol"
    if p["directionality"] >= TREND_MIN:
        return "trending"
    if p["directionality"] <= RANGE_MAX and p["day_range"] <= range_median:
        return "ranging"
    return "unclassified"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--seed", type=int, default=20260812)
    ap.add_argument("--from", dest="start", default=None, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--purpose", default="p1_overlap")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "charts" / "selection.json"))
    ap.add_argument("--exclude", default=None, help="a selection.json whose days must not be reused")
    args = ap.parse_args(argv)

    # D-022: sweeping three years must not abort on one 6-minute hole in 2024.
    feed = ReplayFeed(args.symbol, on_gap="skip")
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(f"profiling {args.symbol} ...", file=sys.stderr)
    profiles = [profile(s) for s in feed.sessions(start=start, end=end)]
    profiles = [p for p in profiles if p["candles"] >= 300]        # full sessions only

    atrs = sorted(p["median_atr"] for p in profiles)
    atr_cut = atrs[int(len(atrs) * HIGH_VOL_PERCENTILE / 100)]
    range_median = statistics.median(p["day_range"] for p in profiles)

    buckets: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        buckets[classify(p, atr_cut, range_median)].append(p)

    excluded: set[date] = set()
    if args.exclude and Path(args.exclude).exists():
        prior = json.loads(Path(args.exclude).read_text(encoding="utf-8"))
        excluded = {date.fromisoformat(s["day"]) for s in prior["sessions"]}

    rng = random.Random(args.seed)
    chosen: list[dict[str, Any]] = []
    for bucket, quota in P1_OVERLAP_QUOTA.items():
        pool = [p for p in buckets.get(bucket, []) if p["day"] not in excluded]
        if len(pool) < quota:
            print(f"  WARNING: only {len(pool)} sessions in bucket {bucket!r}, wanted {quota}",
                  file=sys.stderr)
        for p in rng.sample(pool, min(quota, len(pool))):
            chosen.append({**p, "bucket": bucket})
    chosen.sort(key=lambda p: p["day"])

    payload = {
        "purpose": args.purpose,
        "symbol": args.symbol,
        "seed": args.seed,
        "generated_from": [str(profiles[0]["day"]), str(profiles[-1]["day"])],
        "sessions_profiled": len(profiles),
        "criteria": {
            "trending": f"|close-open| / day_range >= {TREND_MIN}",
            "ranging": f"|close-open| / day_range <= {RANGE_MAX} and day_range <= median",
            "gap": f"|open-prev_close| / prev_close x 100 > {GAP_PCT}",
            "expiry": "last Tuesday of the month",
            "high_vol": f"median ATR14 >= p{HIGH_VOL_PERCENTILE} ({atr_cut:.1f})",
            "priority": "expiry > gap > high_vol > trending > ranging",
        },
        "bucket_sizes": {k: len(v) for k, v in sorted(buckets.items())},
        "excluded_from": args.exclude,
        "note": ("These days are now contaminated for holdout purposes — the trader has "
                 "seen them. P1.5's 4 holdout sessions must be selected with --exclude "
                 "pointing at this file."),
        "sessions": [{
            "day": str(p["day"]), "bucket": p["bucket"],
            "open": round(p["open"], 2), "close": round(p["close"], 2),
            "day_range": round(p["day_range"], 1),
            "directionality": round(p["directionality"], 3),
            "median_atr": round(p["median_atr"], 1),
            "gap_pct": None if p["gap_pct"] is None else round(p["gap_pct"], 2),
        } for p in chosen],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{len(chosen)} sessions selected (seed {args.seed}) from {len(profiles)} profiled\n")
    print(f"  {'day':<12} {'bucket':<10} {'range':>7} {'dir':>6} {'ATR':>6} {'gap%':>7}")
    for s in payload["sessions"]:
        print(f"  {s['day']:<12} {s['bucket']:<10} {s['day_range']:>7.1f} "
              f"{s['directionality']:>6.2f} {s['median_atr']:>6.1f} "
              f"{'-' if s['gap_pct'] is None else format(s['gap_pct'], '>7.2f')}")
    print(f"\nbuckets available: {payload['bucket_sizes']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
