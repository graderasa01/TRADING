#!/usr/bin/env python3
"""
verify_data.py — integrity checks + the ATR measurement that ends the guessing.

    python tools/verify_data.py                       # all instruments under data/
    python tools/verify_data.py --symbols "NIFTY BANK"
    python tools/verify_data.py --report data/DATA-REPORT.md --json data/verify_report.json

This runs BEFORE P0 (KICKOFF.md §1 Task 2). Two jobs:

  1. INTEGRITY — per trading day: candle count vs 375, session boundaries, gaps,
     duplicates, OHLC sanity, holiday cross-check, overnight price continuity.
     Dataset: trading days, coverage, missing months.

  2. MEASUREMENT — the ATR14(1m) distribution against the guessed
     volatility.atr_min_points 12 / atr_max_points 60 in config/params.yaml.
     Those two numbers gate every trade in the system and neither was ever
     measured. This is the first parameter that stops being a hypothesis.

Floats are used throughout. That is deliberate and confined to this tool: these
are measurements, not money. The engine's Decimal rule (CLAUDE.md §5) applies to
src/, and the P0 loader converts via Decimal(repr(x)) — see DECISIONS.md D-014.

ATR convention (DECISIONS.md D-012): simple mean of candle range (high - low)
over `atr_period` candles, computed WITHIN a session, no carry across days. That
is what prototype/engine_fixed.py:78 does and what every threshold in
params.yaml was reasoned against. The Wilder true-range variant is measured too
and printed beside it, so the choice is visible rather than assumed.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import _console  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parent.parent

SESSION_OPEN = dtime(9, 15)
SESSION_LAST_CANDLE = dtime(15, 29)      # 1m candles are stamped at OPEN time
EXPECTED_CANDLES = 375                   # 09:15 .. 15:29 inclusive
GAP_CONTINUITY_FLAG_PCT = 2.0            # overnight gap worth flagging
SHORT_SESSION_MAX = 120                  # below this and off-hours => special session


# ─────────────────────────────────────────────────────────────────────────────
# loading
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Candle:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: int

    @property
    def rng(self) -> float:
        return self.h - self.l


def _read_parquet(path: Path) -> list[Candle]:
    import pyarrow.parquet as pq

    cols = pq.read_table(path).to_pydict()
    out = []
    for ts, o, h, l, c, v in zip(cols["ts"], cols["open"], cols["high"],
                                 cols["low"], cols["close"], cols["volume"]):
        ts = ts if ts.tzinfo else ts.replace(tzinfo=IST)
        out.append(Candle(ts.astimezone(IST), float(o), float(h), float(l), float(c), int(v or 0)))
    return out


def _read_csv(path: Path) -> list[Candle]:
    import csv

    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ts = datetime.fromisoformat(row["ts"])
            ts = ts if ts.tzinfo else ts.replace(tzinfo=IST)
            out.append(Candle(ts.astimezone(IST), float(row["open"]), float(row["high"]),
                              float(row["low"]), float(row["close"]), int(float(row["volume"] or 0))))
    return out


def load_symbol(data_root: Path, symbol: str) -> tuple[list[Candle], list[str]]:
    """Returns (candles sorted by ts, files read). Duplicates are NOT removed —
    finding them is one of the checks."""
    folder = data_root / symbol.replace(" ", "_")
    if not folder.is_dir():
        return [], []
    candles: list[Candle] = []
    files: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.suffix == ".parquet":
            candles.extend(_read_parquet(path))
        elif path.suffix == ".csv":
            candles.extend(_read_csv(path))
        else:
            continue
        files.append(path.name)
    candles.sort(key=lambda c: c.ts)
    return candles, files


def discover_symbols(data_root: Path) -> list[str]:
    if not data_root.is_dir():
        return []
    out = []
    for child in sorted(data_root.iterdir()):
        if child.is_dir() and any(p.suffix in (".parquet", ".csv") for p in child.iterdir()):
            out.append(child.name.replace("_", " "))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# statistics helpers
# ─────────────────────────────────────────────────────────────────────────────
PCTS = [1, 5, 10, 25, 50, 75, 90, 95, 99]


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear interpolation on an already-sorted sequence."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_values[int(k)]
    return sorted_values[lo] * (hi - k) + sorted_values[hi] * (k - lo)


def percentile_rank(sorted_values: Sequence[float], x: float) -> float:
    """What fraction of the distribution lies below x, as a percent."""
    if not sorted_values:
        return float("nan")
    import bisect

    return 100.0 * bisect.bisect_left(sorted_values, x) / len(sorted_values)


def describe(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    out = {"n": len(s), "mean": statistics.fmean(s), "min": s[0], "max": s[-1]}
    for p in PCTS:
        out[f"p{p}"] = percentile(s, p)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────────────────────
def atr_series(day_candles: list[Candle], period: int, wilder: bool = False) -> list[tuple[datetime, float]]:
    """Simple moving average of range over `period` candles, within one session.

    wilder=True uses true range: max(h-l, |h-prev_c|, |prev_c-l|). Still an SMA,
    not Wilder's smoothing — the comparison we care about is TR vs plain range,
    not the smoothing scheme.
    """
    if len(day_candles) < period:
        return []
    ranges: list[float] = []
    prev_close: float | None = None
    for c in day_candles:
        if wilder and prev_close is not None:
            ranges.append(max(c.h - c.l, abs(c.h - prev_close), abs(prev_close - c.l)))
        else:
            ranges.append(c.h - c.l)
        prev_close = c.c
    out = []
    running = sum(ranges[:period])
    out.append((day_candles[period - 1].ts, running / period))
    for i in range(period, len(ranges)):
        running += ranges[i] - ranges[i - period]
        out.append((day_candles[i].ts, running / period))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# per-day integrity
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class DayReport:
    day: date
    count: int
    first: dtime
    last: dtime
    duplicates: list[str] = field(default_factory=list)
    missing_runs: list[tuple[str, str, int]] = field(default_factory=list)
    missing_total: int = 0
    outside_session: int = 0
    ohlc_violations: list[str] = field(default_factory=list)
    zero_range: int = 0
    negative_range: int = 0
    open_gap_pct: float | None = None
    special_session: bool = False       # abbreviated — excluded from every statistic
    special_reason: str = ""
    weekend_full_session: bool = False  # real market held on a weekend — kept, tagged
    day_range: float = 0.0
    day_close: float = 0.0

    @property
    def clean(self) -> bool:
        return (not self.duplicates and not self.missing_runs and not self.ohlc_violations
                and self.negative_range == 0 and self.count == EXPECTED_CANDLES)


def check_day(day: date, candles: list[Candle], prev_close: float | None) -> DayReport:
    by_ts: dict[datetime, int] = defaultdict(int)
    for c in candles:
        by_ts[c.ts] += 1
    duplicates = [ts.strftime("%H:%M") for ts, n in sorted(by_ts.items()) if n > 1]

    unique = sorted({c.ts: c for c in candles}.values(), key=lambda c: c.ts)
    rep = DayReport(day=day, count=len(candles), first=unique[0].ts.time(), last=unique[-1].ts.time(),
                    duplicates=duplicates)

    in_session = [c for c in unique if SESSION_OPEN <= c.ts.time() <= SESSION_LAST_CANDLE]
    rep.outside_session = len(unique) - len(in_session)

    # Two different kinds of unusual day, and conflating them corrupts the data either
    # way (DECISIONS.md D-018). The test is the session's SHAPE, not the calendar, so a
    # future one is classified automatically.
    #
    #   ABBREVIATED -> exclude. Not a real market.
    #     Muhurat, ~60 candles off-hours: 2023-11-12 18:15, 2024-11-01 18:00,
    #       2025-10-21 13:45 — ceremonial, thin, and 2025's sits inside windows_normal
    #     NSE disaster-recovery half-days, 105 candles in two blocks 09:15-09:59 and
    #       11:30-12:29: 2024-03-02, 2024-05-18 — a test of the backup site
    #
    #   FULL SESSION ON A WEEKEND -> keep, but tag. A real market with real liquidity,
    #     held on a Saturday or Sunday for the Union Budget or as a full NSE special
    #     session: 2024-01-20, 2025-02-01, 2026-02-01. Excluding these would break the
    #     overnight-continuity chain and invent a gap on the following Monday. The engine
    #     skips Budget days anyway, via events.yaml — that is a calendar decision, not a
    #     data-integrity one, and the two must not be muddled here.
    #
    # The failure mode of the abbreviated rule is a day whose first 15+ minutes were lost
    # to a feed fault being called "special". That is why every one is listed by name and
    # time in the report rather than silently dropped.
    abbreviated = unique[0].ts.time() > SESSION_OPEN or unique[-1].ts.time() < dtime(15, 0)
    if abbreviated:
        rep.special_session = True
        rep.special_reason = (
            f"off-hours {unique[0].ts:%H:%M}-{unique[-1].ts:%H:%M}, {len(unique)} candles (Muhurat)"
            if unique[0].ts.time() > SESSION_OPEN
            else f"half day, ends {unique[-1].ts:%H:%M}, {len(unique)} candles (NSE DR-site test)"
        )
    elif day.weekday() >= 5:
        rep.weekend_full_session = True

    # gaps inside the session, as runs of consecutive missing minutes
    if in_session and not rep.special_session:
        present = {c.ts.time() for c in in_session}
        cursor = datetime.combine(day, SESSION_OPEN, tzinfo=IST)
        end = datetime.combine(day, SESSION_LAST_CANDLE, tzinfo=IST)
        run_start: dtime | None = None
        run_len = 0
        while cursor <= end:
            t = cursor.time()
            if t not in present:
                run_start = run_start or t
                run_len += 1
            elif run_start is not None:
                rep.missing_runs.append((run_start.strftime("%H:%M"),
                                         (cursor - timedelta(minutes=1)).time().strftime("%H:%M"), run_len))
                run_start, run_len = None, 0
            cursor += timedelta(minutes=1)
        if run_start is not None:
            rep.missing_runs.append((run_start.strftime("%H:%M"),
                                     SESSION_LAST_CANDLE.strftime("%H:%M"), run_len))
        rep.missing_total = sum(r[2] for r in rep.missing_runs)

    for c in unique:
        if not (c.l <= min(c.o, c.c) and max(c.o, c.c) <= c.h):
            if len(rep.ohlc_violations) < 5:
                rep.ohlc_violations.append(
                    f"{c.ts:%H:%M} o{c.o:.2f} h{c.h:.2f} l{c.l:.2f} c{c.c:.2f}")
        if c.rng < 0:
            rep.negative_range += 1
        elif c.rng == 0:
            rep.zero_range += 1

    rep.day_range = max(c.h for c in unique) - min(c.l for c in unique)
    rep.day_close = unique[-1].c
    if prev_close:
        rep.open_gap_pct = 100.0 * (unique[0].o - prev_close) / prev_close
    return rep


# ─────────────────────────────────────────────────────────────────────────────
# per-symbol analysis
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SymbolReport:
    symbol: str
    files: list[str]
    days: list[DayReport]
    atr: list[float]                      # ATR14 over every eligible candle
    atr_wilder: list[float]
    atr_by_year: dict[int, list[float]]
    atr_by_bucket: dict[str, list[float]]
    atr_in_windows: list[float]           # only inside time.windows_normal
    day_median_atr: dict[date, float]
    ranges: list[float]
    price_median: float
    candles: int

    @property
    def first_day(self) -> date | None:
        return self.days[0].day if self.days else None

    @property
    def last_day(self) -> date | None:
        return self.days[-1].day if self.days else None


TIME_BUCKETS: list[tuple[str, dtime, dtime]] = [
    ("09:15-09:30 open", dtime(9, 15), dtime(9, 29)),
    ("09:30-11:15 window A", dtime(9, 30), dtime(11, 14)),
    ("11:15-13:30 lunch", dtime(11, 15), dtime(13, 29)),
    ("13:30-14:45 window B", dtime(13, 30), dtime(14, 44)),
    ("14:45-15:29 close", dtime(14, 45), dtime(15, 29)),
]


def bucket_for(t: dtime) -> str:
    for name, lo, hi in TIME_BUCKETS:
        if lo <= t <= hi:
            return name
    return "outside session"


def in_windows(t: dtime, windows: list[tuple[dtime, dtime]]) -> bool:
    return any(lo <= t <= hi for lo, hi in windows)


def analyse_symbol(symbol: str, candles: list[Candle], files: list[str],
                   period: int, windows: list[tuple[dtime, dtime]]) -> SymbolReport:
    by_day: dict[date, list[Candle]] = defaultdict(list)
    for c in candles:
        by_day[c.ts.date()].append(c)

    days: list[DayReport] = []
    atr_all: list[float] = []
    atr_wilder_all: list[float] = []
    atr_year: dict[int, list[float]] = defaultdict(list)
    atr_bucket: dict[str, list[float]] = defaultdict(list)
    atr_windows: list[float] = []
    day_median: dict[date, float] = {}
    ranges: list[float] = []
    closes: list[float] = []

    prev_close: float | None = None
    for day in sorted(by_day):
        day_candles = sorted({c.ts: c for c in by_day[day]}.values(), key=lambda c: c.ts)
        report = check_day(day, by_day[day], prev_close)
        days.append(report)

        # A special session is measured for integrity but excluded from every statistic
        # and from the overnight-continuity chain (D-018). A Muhurat close is not the
        # reference a normal session gaps from, and its thin ceremonial liquidity would
        # drag the ATR distribution that sets the volatility gate.
        if report.special_session:
            continue

        prev_close = day_candles[-1].c
        closes.append(prev_close)
        ranges.extend(c.rng for c in day_candles)

        series = atr_series(day_candles, period)
        if series:
            values = [v for _, v in series]
            day_median[day] = statistics.median(values)
            atr_all.extend(values)
            atr_year[day.year].extend(values)
            for ts, v in series:
                atr_bucket[bucket_for(ts.time())].append(v)
                if in_windows(ts.time(), windows):
                    atr_windows.append(v)
        atr_wilder_all.extend(v for _, v in atr_series(day_candles, period, wilder=True))

    return SymbolReport(
        symbol=symbol, files=files, days=days, atr=atr_all, atr_wilder=atr_wilder_all,
        atr_by_year=dict(atr_year), atr_by_bucket=dict(atr_bucket), atr_in_windows=atr_windows,
        day_median_atr=day_median, ranges=ranges,
        price_median=statistics.median(closes) if closes else float("nan"),
        candles=len(candles),
    )


# ─────────────────────────────────────────────────────────────────────────────
# calendar cross-check
# ─────────────────────────────────────────────────────────────────────────────
def calendar_cross_check(reports: dict[str, SymbolReport]) -> dict[str, Any]:
    """No offline NSE holiday list is bundled (DECISIONS.md D-013). Instead:
    a weekday absent from EVERY instrument is a suspected holiday; a weekday
    absent from one instrument but present in another is a real hole."""
    per_symbol_days = {s: {d.day for d in r.days} for s, r in reports.items()}
    nse = {s: d for s, d in per_symbol_days.items() if s != "SENSEX"}
    reference = nse or per_symbol_days
    if not reference:
        return {}

    all_days = set().union(*reference.values())
    start, end = min(all_days), max(all_days)
    weekdays = set()
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            weekdays.add(cursor)
        cursor += timedelta(days=1)

    union = set().union(*per_symbol_days.values())
    suspected_holidays = sorted(weekdays - union)
    holes: dict[str, list[str]] = {}
    for symbol, days in per_symbol_days.items():
        missing = sorted(d for d in (union & weekdays) - days if start <= d <= end)
        if missing:
            holes[symbol] = [str(d) for d in missing]
    return {
        "range": [str(start), str(end)],
        "weekdays_in_range": len(weekdays),
        "trading_days_seen": len(union & weekdays),
        "suspected_holidays": [str(d) for d in suspected_holidays],
        "per_symbol_holes": holes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# report
# ─────────────────────────────────────────────────────────────────────────────
def fmt(x: float, nd: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{nd}f}"


def pct_below(sorted_values: Sequence[float], x: float) -> float:
    return percentile_rank(sorted_values, x)


def write_report(reports: dict[str, SymbolReport], calendar: dict[str, Any],
                 params: dict[str, Any], out_path: Path, data_root: Path) -> str:
    vol = params.get("volatility", {})
    atr_min = float(vol.get("atr_min_points", 12))
    atr_max = float(vol.get("atr_max_points", 60))
    period = int(vol.get("atr_period", 14))
    primary = "NIFTY BANK"

    L: list[str] = []
    A = L.append
    A("# DATA REPORT")
    A("")
    A(f"*Generated {datetime.now(IST):%Y-%m-%d %H:%M} IST from `{data_root}` by `tools/verify_data.py`.*")
    A("")
    A("This report exists to answer one question before any engine code is written: "
      f"**are `volatility.atr_min_points {atr_min:g}` and `atr_max_points {atr_max:g}` "
      "in `config/params.yaml` right?** Everything else here is the integrity evidence "
      "that the measurement can be trusted.")
    A("")

    # ── 1. coverage
    A("## 1. Coverage")
    A("")
    A("| instrument | files | first day | last day | trading days | candles | median close |")
    A("|---|---:|---|---|---:|---:|---:|")
    for s, r in reports.items():
        A(f"| {s} | {len(r.files)} | {r.first_day or '—'} | {r.last_day or '—'} | "
          f"{len(r.days)} | {r.candles:,} | {fmt(r.price_median, 0)} |")
    A("")
    if calendar:
        A(f"Range **{calendar['range'][0]} → {calendar['range'][1]}** — "
          f"{calendar['weekdays_in_range']} weekdays, {calendar['trading_days_seen']} with data "
          f"({100.0 * calendar['trading_days_seen'] / max(calendar['weekdays_in_range'], 1):.1f}% "
          "of weekdays; the remainder should be NSE holidays).")
        A("")
        holidays = calendar["suspected_holidays"]
        A(f"**Suspected holidays** (weekday, no data on any instrument): {len(holidays)}. "
          + (", ".join(holidays[:12]) + (" …" if len(holidays) > 12 else "") if holidays else "none"))
        A("")
        if calendar["per_symbol_holes"]:
            A("**Real holes** — days present on another instrument but missing here. "
              "These are download failures, not holidays:")
            A("")
            for s, missing in calendar["per_symbol_holes"].items():
                A(f"- `{s}`: {len(missing)} day(s) — {', '.join(missing[:10])}"
                  + (" …" if len(missing) > 10 else ""))
            A("")
        else:
            A("**Real holes: none.** Every instrument has data on every day that any instrument has data.")
            A("")

    # ── 2. integrity
    A("## 2. Per-day integrity")
    A("")
    A("| instrument | normal days | clean | wrong count | with gaps | duplicates | OHLC violations | special |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    for s, r in reports.items():
        normal = [d for d in r.days if not d.special_session]
        wrong = sum(1 for d in normal if d.count != EXPECTED_CANDLES)
        gapped = sum(1 for d in normal if d.missing_runs)
        dupes = sum(1 for d in normal if d.duplicates)
        bad = sum(1 for d in normal if d.ohlc_violations or d.negative_range)
        special = sum(1 for d in r.days if d.special_session)
        A(f"| {s} | {len(normal)} | {sum(1 for d in normal if d.clean)} | {wrong} | "
          f"{gapped} | {dupes} | {bad} | {special} |")
    A("")

    specials = {d.day: d for r in reports.values() for d in r.days if d.special_session}
    if specials:
        A(f"**Abbreviated sessions — {len(specials)}, excluded from every statistic below "
          "and from the overnight-continuity chain** (DECISIONS.md D-018). Not gaps, not "
          "defects — not a real market:")
        A("")
        A("| day | weekday | window | what it is |")
        A("|---|---|---|---|")
        for day in sorted(specials):
            d = specials[day]
            A(f"| {day} | {day:%a} | {d.first:%H:%M}–{d.last:%H:%M} | {d.special_reason} |")
        A("")
        A("**The engine must skip these too.** `2025-10-21`'s Muhurat window (13:45–14:44) "
          "sits **inside** `time.windows_normal` `[13:30, 14:45]`, so without an explicit "
          "exclusion the engine would treat a one-hour ceremonial session as an ordinary "
          "trading window and never mention it.")
        A("")

    weekend_full = {d.day for r in reports.values() for d in r.days if d.weekend_full_session}
    if weekend_full:
        A(f"**Full sessions held on a weekend — {len(weekend_full)}, KEPT**: "
          + ", ".join(f"{d} ({d:%a})" for d in sorted(weekend_full)) + ". "
          "A complete 09:15–15:29 session with real liquidity, held for the Union Budget "
          "or as an NSE special session. Dropping these would break the overnight chain "
          "and invent a gap on the following Monday. Whether the engine *trades* them is "
          "`config/events.yaml`'s business (Budget is a full-day blackout) — a calendar "
          "decision, not a data-integrity one.")
        A("")

    for s, r in reports.items():
        gapped = [d for d in r.days if d.missing_runs]
        if not gapped:
            continue
        worst = sorted(gapped, key=lambda d: -d.missing_total)[:8]
        A(f"**{s} — worst gap days:**")
        A("")
        A("| day | candles | missing | runs |")
        A("|---|---:|---:|---|")
        for d in worst:
            runs = ", ".join(f"{a}–{b} ({n})" for a, b, n in d.missing_runs[:4])
            A(f"| {d.day} | {d.count} | {d.missing_total} | {runs}{' …' if len(d.missing_runs) > 4 else ''} |")
        A("")

    for s, r in reports.items():
        jumps = [d for d in r.days if d.open_gap_pct is not None and abs(d.open_gap_pct) >= GAP_CONTINUITY_FLAG_PCT]
        A(f"**{s} — overnight gaps ≥ {GAP_CONTINUITY_FLAG_PCT}%:** {len(jumps)}"
          + (" — " + ", ".join(f"{d.day} ({d.open_gap_pct:+.2f}%)" for d in jumps[:8]) if jumps else "")
          + (" …" if len(jumps) > 8 else ""))
        A("")

    # ── 3. THE ATR SECTION
    A("## 3. ATR14(1m) — measured, against the guess")
    A("")
    A(f"ATR convention: simple mean of `high - low` over {period} candles, within a session, "
      "no carry across days (DECISIONS.md D-012 — this is what `prototype/engine_fixed.py` does "
      "and what every threshold in `params.yaml` was reasoned against).")
    A("")

    for s, r in reports.items():
        if not r.atr:
            continue
        srt = sorted(r.atr)
        d = describe(srt)
        A(f"### {s}")
        A("")
        A("| p1 | p5 | p10 | p25 | **p50** | p75 | p90 | p95 | p99 | mean | max |")
        A("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        A("| " + " | ".join(fmt(d[f"p{p}"]) for p in PCTS) + f" | {fmt(d['mean'])} | {fmt(d['max'])} |")
        A("")
        below = pct_below(srt, atr_min)
        above = 100.0 - pct_below(srt, atr_max)
        A(f"- `atr_min_points {atr_min:g}` sits at the **{below:.1f}th percentile** → "
          f"**{below:.1f}%** of candles are blocked by `volatility_floor`")
        A(f"- `atr_max_points {atr_max:g}` sits at the **{100 - above:.1f}th percentile** → "
          f"**{above:.1f}%** of candles are blocked by `volatility_ceiling`")
        A(f"- combined: the volatility gate rejects **{below + above:.1f}%** of all candles")
        if r.atr_in_windows:
            wsrt = sorted(r.atr_in_windows)
            wb = pct_below(wsrt, atr_min)
            wa = 100.0 - pct_below(wsrt, atr_max)
            A(f"- inside `time.windows_normal` only (the candles that can actually trade): "
              f"floor blocks **{wb:.1f}%**, ceiling blocks **{wa:.1f}%**, median ATR **{fmt(percentile(wsrt, 50))}**")
        if r.atr_wilder:
            A(f"- true-range variant median **{fmt(percentile(sorted(r.atr_wilder), 50))}** "
              f"vs plain-range median **{fmt(d['p50'])}** "
              f"({100 * (percentile(sorted(r.atr_wilder), 50) / d['p50'] - 1):+.1f}%) — "
              "the convention choice is worth this much")
        A("")

        if r.atr_by_bucket:
            A("**By time of day** (median ATR14):")
            A("")
            A("| bucket | " + " | ".join(n for n, _, _ in TIME_BUCKETS) + " |")
            A("|---|" + "---:|" * len(TIME_BUCKETS))
            A("| median | " + " | ".join(
                fmt(percentile(sorted(r.atr_by_bucket.get(n, [])), 50)) if r.atr_by_bucket.get(n) else "—"
                for n, _, _ in TIME_BUCKETS) + " |")
            A("")
        if len(r.atr_by_year) > 1:
            A("**By year** (median ATR14 — this is the number that decides whether one "
              "fixed point threshold can span the sample):")
            A("")
            years = sorted(r.atr_by_year)
            A("| year | " + " | ".join(str(y) for y in years) + " |")
            A("|---|" + "---:|" * len(years))
            A("| median | " + " | ".join(fmt(percentile(sorted(r.atr_by_year[y]), 50)) for y in years) + " |")
            A("| p5 | " + " | ".join(fmt(percentile(sorted(r.atr_by_year[y]), 5)) for y in years) + " |")
            A("| p95 | " + " | ".join(fmt(percentile(sorted(r.atr_by_year[y]), 95)) for y in years) + " |")
            A("")

    # ── 4. day-level view
    A("## 4. Day-level volatility — how many whole days the gate removes")
    A("")
    A("A candle-level percentage understates the effect: ATR is persistent, so blocked "
      "candles cluster into blocked days. This counts days by their median ATR14.")
    A("")
    A("| instrument | days | median-ATR < min | median-ATR > max | tradeable days |")
    A("|---|---:|---:|---:|---:|")
    for s, r in reports.items():
        if not r.day_median_atr:
            continue
        vals = list(r.day_median_atr.values())
        dead = sum(1 for v in vals if v < atr_min)
        hot = sum(1 for v in vals if v > atr_max)
        A(f"| {s} | {len(vals)} | {dead} ({100 * dead / len(vals):.1f}%) | "
          f"{hot} ({100 * hot / len(vals):.1f}%) | {len(vals) - dead - hot} |")
    A("")

    # ── 5. cross-instrument
    A("## 5. Cross-instrument — can one point threshold serve all four? (P9)")
    A("")
    A("`CLAUDE.md` §8 requires the identical, unchanged ruleset to run on all four "
      "instruments. `atr_min_points` / `atr_max_points` are **absolute points**, so this "
      "table decides whether that is possible.")
    A("")
    A("| instrument | median close | median ATR14 | ATR as bps of price | % candles below min | % above max |")
    A("|---|---:|---:|---:|---:|---:|")
    for s, r in reports.items():
        if not r.atr:
            continue
        srt = sorted(r.atr)
        med = percentile(srt, 50)
        bps = 10000.0 * med / r.price_median if r.price_median else float("nan")
        A(f"| {s} | {fmt(r.price_median, 0)} | {fmt(med)} | {fmt(bps, 2)} | "
          f"{pct_below(srt, atr_min):.1f}% | {100 - pct_below(srt, atr_max):.1f}% |")
    A("")

    # ── 6. what to put in params.yaml
    A("## 6. What this says to write into `params.yaml`")
    A("")
    pr = reports.get(primary)
    if pr and pr.atr:
        srt = sorted(pr.atr)
        A(f"Measured on **{primary}**, {len(srt):,} ATR observations over {len(pr.days)} sessions:")
        A("")
        A("| candidate | percentile | points |")
        A("|---|---:|---:|")
        for p in (1, 2, 5, 10):
            A(f"| floor | p{p} | {fmt(percentile(srt, p))} |")
        for p in (90, 95, 98, 99):
            A(f"| ceiling | p{p} | {fmt(percentile(srt, p))} |")
        A("")
        A(f"Current guesses: floor **{atr_min:g}** (= p{pct_below(srt, atr_min):.1f}), "
          f"ceiling **{atr_max:g}** (= p{pct_below(srt, atr_max):.1f}).")
        A("")
    A("`atr_min_percentile` / `atr_max_percentile` are still `null`. They should be set "
      "from the table above rather than left as points, because §3's by-year row shows "
      "whether a fixed point value means the same thing across the sample. Filling them "
      "is a decision for the user, not for this tool — the numbers are here, the choice is not made.")
    A("")

    # ── 7. P9 verdict
    A("## 7. Is the P9 plan (3 years × 4 instruments) possible with this data?")
    A("")
    for s, r in reports.items():
        if not r.days:
            A(f"- **{s}**: NO DATA")
            continue
        span_days = (r.last_day - r.first_day).days / 365.25
        verdict = "yes" if span_days >= 2.75 else ("partial" if span_days >= 1.0 else "NO")
        A(f"- **{s}**: {span_days:.1f} years, {len(r.days)} sessions → **{verdict}**")
    A("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(L) + "\n"
    out_path.write_text(text, encoding="utf-8")
    return text


# ─────────────────────────────────────────────────────────────────────────────
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(REPO_ROOT / "data"))
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--params", default=str(REPO_ROOT / "config" / "params.yaml"))
    ap.add_argument("--report", default=None, help="default: <data>/DATA-REPORT.md")
    ap.add_argument("--json", dest="json_out", default=None, help="machine-readable summary")
    args = ap.parse_args(argv)

    data_root = Path(args.data)
    symbols = args.symbols or discover_symbols(data_root)
    if not symbols:
        print(f"no data found under {data_root}\n"
              f"run:  python tools/fetch_kite.py fetch --years 3", file=sys.stderr)
        return 2

    import yaml

    params = yaml.safe_load(Path(args.params).read_text(encoding="utf-8"))
    period = int(params.get("volatility", {}).get("atr_period", 14))
    windows = [(dtime.fromisoformat(a), dtime.fromisoformat(b))
               for a, b in params.get("time", {}).get("windows_normal", [])]

    reports: dict[str, SymbolReport] = {}
    for symbol in symbols:
        candles, files = load_symbol(data_root, symbol)
        if not candles:
            print(f"  {symbol}: no candles", file=sys.stderr)
            continue
        reports[symbol] = analyse_symbol(symbol, candles, files, period, windows)
        r = reports[symbol]
        print(f"  {symbol}: {len(r.days)} days, {r.candles:,} candles, "
              f"{sum(1 for d in r.days if d.clean)} clean", file=sys.stderr)

    if not reports:
        return 2

    calendar = calendar_cross_check(reports)
    report_path = Path(args.report) if args.report else data_root / "DATA-REPORT.md"
    write_report(reports, calendar, params, report_path, data_root)
    print(f"\nwrote {report_path}", file=sys.stderr)

    if args.json_out:
        payload = {
            "generated_at": datetime.now(IST).isoformat(),
            "calendar": calendar,
            "symbols": {
                s: {
                    "days": len(r.days),
                    "candles": r.candles,
                    "clean_days": sum(1 for d in r.days if d.clean),
                    "first_day": str(r.first_day),
                    "last_day": str(r.last_day),
                    "atr": describe(sorted(r.atr)),
                    "atr_in_windows": describe(sorted(r.atr_in_windows)),
                    "range_1m": describe(sorted(r.ranges)),
                    "median_close": r.price_median,
                }
                for s, r in reports.items()
            },
        }
        Path(args.json_out).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"wrote {args.json_out}", file=sys.stderr)

    # exit non-zero if anything structural is broken
    broken = any(d.ohlc_violations or d.negative_range or d.duplicates
                 for r in reports.values() for d in r.days)
    return 1 if broken or calendar.get("per_symbol_holes") else 0


if __name__ == "__main__":
    raise SystemExit(main())
