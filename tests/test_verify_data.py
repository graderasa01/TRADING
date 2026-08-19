"""
The verifier is what decides whether the ATR measurement can be trusted, so the
verifier itself needs evidence. These tests plant defects with known answers and
check that each one is found — a verifier that reports "all clean" on a corrupt
dataset is worse than no verifier at all.

Every expected value here is computed by hand from the rule, not from a previous
run of the code (BUILD-BRIEF §5).
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

import pytest

import fetch_kite
import verify_data as V

IST = V.IST


def session(day: date, *, base: float = 50000.0, rng: float = 20.0,
            n: int = 375, drift: float = 0.0) -> list[dict]:
    """A full session of `n` 1m candles, each with range exactly `rng`.

    Constant range makes ATR14 exactly `rng` at every candle — the arithmetic is
    checkable without running the code.
    """
    rows = []
    start = datetime.combine(day, dtime(9, 15), tzinfo=IST)
    for i in range(n):
        mid = base + drift * i
        rows.append({
            "ts": start + timedelta(minutes=i),
            "open": mid,
            "high": mid + rng / 2,
            "low": mid - rng / 2,
            "close": mid,
            "volume": 0,
        })
    return rows


def write(rows: list[dict], root: Path, symbol: str, month: str, fmt: str = "csv") -> None:
    suffix = "parquet" if fmt == "parquet" else "csv"
    path = root / symbol.replace(" ", "_") / f"{month}.{suffix}"
    fetch_kite.write_candles(rows, path, fmt)


D1 = date(2026, 1, 5)   # Monday
D2 = date(2026, 1, 6)
D3 = date(2026, 1, 7)
D4 = date(2026, 1, 8)
D5 = date(2026, 1, 9)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """One clean week on NIFTY 50, the same week on NIFTY BANK with planted defects.

    NIFTY BANK:
      D1  clean, 375 candles, range 20
      D2  4-minute gap 10:00-10:03
      D3  duplicate candle at 09:20  +  one OHLC violation at 09:25
      D4  absent entirely            -> a real hole (NIFTY 50 has it)
      D5  opens 3% above D3's close  -> continuity flag
    D2 is absent from BOTH instruments on 2026-01-12 -> suspected holiday.
    """
    root = tmp_path / "data"

    bank: list[dict] = []
    bank += session(D1)

    d2 = session(D2)
    bank += [r for r in d2 if not (dtime(10, 0) <= r["ts"].time() <= dtime(10, 3))]

    d3 = session(D3)
    d3.append(dict(d3[5]))                       # duplicate 09:20
    d3[10] = {**d3[10], "high": d3[10]["open"] - 5.0}   # high below open: violation
    bank += d3

    bank += session(D5, base=50000.0 * 1.03)     # +3% overnight gap vs D3 close

    nifty: list[dict] = []
    for d in (D1, D2, D3, D4, D5):
        nifty += session(d, base=25000.0, rng=8.0)

    write(bank, root, "NIFTY BANK", "2026-01", fmt="parquet")
    write(nifty, root, "NIFTY 50", "2026-01", fmt="csv")
    return root


def load(root: Path, symbol: str) -> V.SymbolReport:
    candles, files = V.load_symbol(root, symbol)
    assert candles, f"{symbol} loaded nothing"
    return V.analyse_symbol(symbol, candles, files, period=14,
                            windows=[(dtime(9, 30), dtime(11, 15)), (dtime(13, 30), dtime(14, 45))])


# ── round trip ──────────────────────────────────────────────────────────────
def test_parquet_and_csv_round_trip(dataset: Path):
    bank, _ = V.load_symbol(dataset, "NIFTY BANK")
    nifty, _ = V.load_symbol(dataset, "NIFTY 50")
    assert bank[0].ts == datetime.combine(D1, dtime(9, 15), tzinfo=IST)
    assert bank[0].ts.tzinfo is not None and nifty[0].ts.tzinfo is not None
    assert nifty[0].o == 25000.0 and nifty[0].h == 25004.0
    # 5 clean sessions on NIFTY 50
    assert len(nifty) == 5 * 375


def test_discover_symbols(dataset: Path):
    assert V.discover_symbols(dataset) == ["NIFTY 50", "NIFTY BANK"]


# ── integrity ───────────────────────────────────────────────────────────────
def test_clean_day_is_clean(dataset: Path):
    day = {d.day: d for d in load(dataset, "NIFTY BANK").days}[D1]
    assert day.count == 375 and day.clean
    assert day.first == dtime(9, 15) and day.last == dtime(15, 29)
    assert day.missing_total == 0 and not day.duplicates


def test_gap_is_found_with_exact_span(dataset: Path):
    day = {d.day: d for d in load(dataset, "NIFTY BANK").days}[D2]
    assert day.count == 371                      # 375 - 4
    assert day.missing_runs == [("10:00", "10:03", 4)]
    assert day.missing_total == 4
    assert not day.clean


def test_duplicate_and_ohlc_violation_are_found(dataset: Path):
    day = {d.day: d for d in load(dataset, "NIFTY BANK").days}[D3]
    assert day.duplicates == ["09:20"]
    assert len(day.ohlc_violations) == 1 and "09:25" in day.ohlc_violations[0]
    assert not day.clean


def test_overnight_gap_flagged(dataset: Path):
    day = {d.day: d for d in load(dataset, "NIFTY BANK").days}[D5]
    assert day.open_gap_pct == pytest.approx(3.0, abs=0.01)
    assert abs(day.open_gap_pct) >= V.GAP_CONTINUITY_FLAG_PCT


def test_missing_day_is_a_hole_not_a_holiday(dataset: Path):
    reports = {s: load(dataset, s) for s in ("NIFTY BANK", "NIFTY 50")}
    cal = V.calendar_cross_check(reports)
    assert cal["per_symbol_holes"] == {"NIFTY BANK": [str(D4)]}
    assert str(D4) not in cal["suspected_holidays"]


def test_weekday_absent_everywhere_is_a_suspected_holiday(tmp_path: Path):
    root = tmp_path / "data"
    # Mon, Tue, Thu -> Wednesday is missing from both instruments
    for symbol, base in (("NIFTY BANK", 50000.0), ("NIFTY 50", 25000.0)):
        rows: list[dict] = []
        for d in (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 8)):
            rows += session(d, base=base)
        write(rows, root, symbol, "2026-01")
    reports = {s: load(root, s) for s in ("NIFTY BANK", "NIFTY 50")}
    cal = V.calendar_cross_check(reports)
    assert cal["suspected_holidays"] == ["2026-01-07"]
    assert cal["per_symbol_holes"] == {}
    # and the other direction: a clean dataset must exit 0, or "clean" means nothing
    assert V.main(["--data", str(root), "--report", str(tmp_path / "clean.md")]) == 0


# ── ATR — the measurement everything downstream depends on ──────────────────
def test_atr_of_constant_range_is_that_range():
    """Range is 20 on every candle, so ATR14 is 20 at every candle. No tolerance."""
    rows = session(D1, rng=20.0)
    candles = [V.Candle(r["ts"], r["open"], r["high"], r["low"], r["close"], 0) for r in rows]
    series = V.atr_series(candles, 14)
    assert len(series) == 375 - 14 + 1
    assert all(v == pytest.approx(20.0) for _, v in series)
    assert series[0][0] == candles[13].ts        # first ATR is stamped on candle 14


def test_atr_warmup_needs_period_candles():
    rows = session(D1, n=13)
    candles = [V.Candle(r["ts"], r["open"], r["high"], r["low"], r["close"], 0) for r in rows]
    assert V.atr_series(candles, 14) == []


def test_atr_does_not_carry_across_sessions(dataset: Path):
    """Two sessions of 375 give 2x(375-13) observations, not 750-13. A cross-day
    ATR would silently blend an overnight gap into intraday volatility."""
    root = dataset.parent / "twoday"
    rows = session(D1, rng=20.0) + session(D2, rng=40.0)
    write(rows, root, "NIFTY BANK", "2026-01")
    rep = load(root, "NIFTY BANK")
    assert len(rep.atr) == 2 * (375 - 14 + 1)
    assert sorted(set(round(v, 6) for v in rep.atr)) == [20.0, 40.0]


def test_wilder_variant_differs_only_by_overnight_and_tick_gaps():
    """Inside a session with contiguous candles that overlap, true range equals
    the plain range, so both conventions agree. This pins the claim made in the
    report rather than assuming it."""
    rows = session(D1, rng=20.0, drift=0.0)
    candles = [V.Candle(r["ts"], r["open"], r["high"], r["low"], r["close"], 0) for r in rows]
    plain = [v for _, v in V.atr_series(candles, 14)]
    wilder = [v for _, v in V.atr_series(candles, 14, wilder=True)]
    assert plain == pytest.approx(wilder)


def test_percentile_and_rank_are_consistent():
    values = [float(x) for x in range(101)]      # 0..100
    assert V.percentile(values, 50) == pytest.approx(50.0)
    assert V.percentile(values, 5) == pytest.approx(5.0)
    assert V.percentile_rank(values, 12.0) == pytest.approx(12.0 / 101 * 100, abs=0.5)


def test_window_filter_excludes_lunch(dataset: Path):
    rep = load(dataset, "NIFTY 50")
    assert rep.atr_in_windows
    assert len(rep.atr_in_windows) < len(rep.atr)
    assert "11:15-13:30 lunch" in rep.atr_by_bucket


# ── end to end ──────────────────────────────────────────────────────────────
def test_report_renders_and_names_the_defects(dataset: Path, tmp_path: Path):
    import yaml

    params = yaml.safe_load((V.REPO_ROOT / "config" / "params.yaml").read_text(encoding="utf-8"))
    reports = {s: load(dataset, s) for s in ("NIFTY BANK", "NIFTY 50")}
    out = tmp_path / "DATA-REPORT.md"
    text = V.write_report(reports, V.calendar_cross_check(reports), params, out, dataset)
    assert out.exists()
    assert "ATR14(1m) — measured, against the guess" in text
    assert "Real holes" in text and str(D4) in text
    assert "volatility_floor" in text and "volatility_ceiling" in text


def test_exit_code_is_nonzero_when_data_is_broken(dataset: Path, tmp_path: Path):
    rc = V.main(["--data", str(dataset),
                 "--report", str(tmp_path / "r.md"),
                 "--json", str(tmp_path / "r.json")])
    assert rc == 1, "planted duplicates/violations/holes must fail the run"
