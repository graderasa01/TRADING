"""
The P1 gate's tooling — session selection and the annotation chart.

These are not incidental scripts. The overlap test (spec 09 §3.2b) is the gate that
protects every phase after P1, and it is only as trustworthy as the way its sessions
were chosen. If the days were picked by eye, the test measures memory rather than
method, so the selection's reproducibility is asserted here rather than assumed.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import chart as chart_tool
import select_sessions as sel

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── classification is arithmetic, not judgement ─────────────────────────────
@pytest.mark.parametrize("day,expected", [
    (date(2025, 3, 25), True),    # last Tuesday of March 2025
    (date(2025, 3, 18), False),   # a Tuesday, but not the last
    (date(2025, 3, 26), False),   # Wednesday
    (date(2024, 12, 31), True),   # last Tuesday of December 2024
])
def test_monthly_expiry_detection(day, expected):
    """Bank Nifty is monthly, last Tuesday, since weeklies ended 20 Nov 2024."""
    assert sel.is_monthly_expiry(day) is expected


def test_atr14_of_constant_range_is_that_range():
    class C:
        def __init__(self, h, l):
            self.h, self.l = h, l
    assert sel.atr14([C(120, 100)] * 30) == pytest.approx([20.0] * 17)


def test_buckets_are_disjoint_by_priority():
    """A gap day that also trended must land in exactly one stratum, or the quota
    silently double-counts it."""
    base = {"day": date(2026, 3, 4), "median_atr": 20.0,
            "directionality": 0.9, "day_range": 400.0, "gap_pct": 1.5}
    assert sel.classify(base, atr_cut=99, range_median=500) == "gap"
    assert sel.classify({**base, "gap_pct": 0.1}, atr_cut=99, range_median=500) == "trending"
    assert sel.classify({**base, "gap_pct": 0.1}, atr_cut=10, range_median=500) == "high_vol"
    assert sel.classify({**base, "gap_pct": 0.1, "directionality": 0.1},
                        atr_cut=99, range_median=500) == "ranging"
    assert sel.classify({**base, "day": date(2025, 3, 25), "gap_pct": 5.0},
                        atr_cut=99, range_median=500) == "expiry"


# ── the committed selection ────────────────────────────────────────────────
@pytest.fixture(scope="module")
def selection() -> dict:
    path = REPO_ROOT / "reports" / "charts" / "selection.json"
    if not path.exists():
        pytest.fail("reports/charts/selection.json missing — run tools/select_sessions.py")
    return json.loads(path.read_text(encoding="utf-8"))


def test_selection_meets_the_spec_09_quota(selection):
    """3 trending, 3 ranging, 2 gap, 1 expiry, 1 high-vol — spec 09 §3.2b."""
    counts: dict[str, int] = {}
    for s in selection["sessions"]:
        counts[s["bucket"]] = counts.get(s["bucket"], 0) + 1
    assert counts == sel.P1_OVERLAP_QUOTA
    assert len(selection["sessions"]) == 10


def test_selection_records_its_seed_and_criteria(selection):
    """Reproducibility is the whole defence against cherry-picking. Anyone must be
    able to re-run this and get the same ten days."""
    assert isinstance(selection["seed"], int)
    assert set(selection["criteria"]) >= set(sel.P1_OVERLAP_QUOTA) | {"priority"}
    assert selection["sessions_profiled"] > 700


def test_selected_days_are_unique_and_sorted(selection):
    days = [s["day"] for s in selection["sessions"]]
    assert len(set(days)) == 10 and days == sorted(days)


def test_selection_warns_that_these_days_are_now_contaminated(selection):
    """P1.5's holdout must not reuse a day the trader has already annotated."""
    assert "holdout" in selection["note"]


# ── the chart ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("charts")
    path = chart_tool.render_session("NIFTY BANK", date(2026, 3, 4), out)
    return path.read_text(encoding="utf-8")


def test_chart_is_self_contained(rendered):
    """No CDN, no build step, no server — it must open by double-click, offline."""
    for external in ("<script src=", "<link ", "http://", "https://", "cdn."):
        assert external not in rendered, f"chart references {external!r}"


def test_chart_carries_all_three_timeframes(rendered):
    data = json.loads(rendered.split("const DATA = ")[1].split(";\nconst MARKS")[0])
    assert len(data["tf"]["1m"]) == 375
    assert len(data["tf"]["5m"]) == 75
    assert len(data["tf"]["15m"]) == 25


def test_chart_rows_carry_the_candle_index_and_time(rendered):
    """The index is what the annotation schema references, so it must be in the data
    for every candle — not rendered on every tenth one and inferred for the rest."""
    data = json.loads(rendered.split("const DATA = ")[1].split(";\nconst MARKS")[0])
    first, last = data["tf"]["1m"][0], data["tf"]["1m"][-1]
    assert first[0] == 0 and first[1] == "09:15"
    assert last[0] == 374 and last[1] == "15:29"
    assert all(row[0] == i for i, row in enumerate(data["tf"]["1m"]))


def test_chart_ohlc_matches_the_feed_exactly(rendered):
    from src.feed.replay_feed import ReplayFeed

    data = json.loads(rendered.split("const DATA = ")[1].split(";\nconst MARKS")[0])
    candles = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4)).candles
    for row, candle in zip(data["tf"]["1m"], candles):
        assert (row[2], row[3], row[4], row[5]) == (
            float(candle.o), float(candle.h), float(candle.l), float(candle.c))


def test_chart_is_blank_by_default(rendered):
    """The P1 gate requires the trader to mark levels BEFORE seeing engine output.
    Reverse that and the test measures agreeableness, not agreement."""
    data = json.loads(rendered.split("const DATA = ")[1].split(";\nconst MARKS")[0])
    assert "no engine lines" in rendered
    assert data["engine"] == []


def test_the_yaml_declares_whether_engine_lines_were_visible(tmp_path):
    """`marked_before_engine_output` used to be the hardcoded string `true`, on every
    chart — including one rendered with `--levels`. So a levels chart produced an
    annotation file that swore the trader had not seen the engine's book while the book
    was on screen in front of them, and the P1 gate would have scored it.

    It is now derived from whether any engine level is present.
    """
    from tools.chart import render_session

    blank = render_session("NIFTY BANK", date(2026, 3, 4), tmp_path,
                           with_levels=False).read_text(encoding="utf-8")
    overlaid = render_session("NIFTY BANK", date(2026, 3, 4), tmp_path,
                              with_levels=True).read_text(encoding="utf-8")
    assert "DATA.engine.length ? 'false' : 'true'" in blank
    assert json.loads(blank.split("const DATA = ")[1]
                      .split(";\nconst MARKS")[0])["engine"] == []
    assert json.loads(overlaid.split("const DATA = ")[1]
                      .split(";\nconst MARKS")[0])["engine"] != []


def test_resample_matches_the_aggregator():
    """The chart resamples timeframes itself so it can show 30m or 60m without changing
    what a `Candle` is allowed to be engine-wide. That freedom is only safe while the two
    paths agree on the timeframes they share — otherwise the chart shows one 15m bar and
    the level engine sees another, and every visual check silently means nothing."""
    from src.feed.aggregator import aggregate_all
    from src.feed.replay_feed import ReplayFeed
    from tools.chart import resample

    candles = ReplayFeed("NIFTY BANK").session(date(2026, 3, 4)).candles
    ups = aggregate_all(candles)
    for tf, minutes in (("5m", 5), ("15m", 15)):
        engine = [u.m5 if tf == "5m" else u.m15 for u in ups
                  if (u.m5 if tf == "5m" else u.m15)]
        display = resample(candles, minutes)
        # the final bar of the session may still be open in the aggregator's view
        assert len(display) - len(engine) in (0, 1), tf
        for bar, candle in zip(display, engine):
            assert bar[1] == candle.open_time.strftime("%H:%M"), tf
            assert (bar[2], bar[3], bar[4], bar[5]) == (
                float(candle.o), float(candle.h), float(candle.l), float(candle.c)), tf


def test_extra_timeframes_do_not_touch_the_domain_contract():
    """Spec 04's cardinal rule (15m WHERE / 5m WHAT / 1m WHEN) is a design commitment.
    A 60m chart panel is a look; a 60m timeframe in `TF_MINUTES` would let the engine
    build levels on it, and that is a DECISIONS.md question, not a `--tf` flag."""
    from src.domain.models import TF_MINUTES
    from tools.chart import parse_tfs

    assert set(TF_MINUTES) == {"1m", "5m", "15m"}
    assert [tf for tf, _ in parse_tfs("60m,30m,5m")] == ["60m", "30m", "5m", "1m"]


def test_one_minute_is_always_present_because_marks_are_in_its_index_space():
    from tools.chart import parse_tfs

    assert ("1m", 1) in parse_tfs("15m")
    assert ("1m", 1) in parse_tfs("60m,15m")
