"""
P1.5 tooling — the teaching loop (spec 12) and the candle dialogue (spec 13).

The disciplines these tools enforce ARE the tools, so the disciplines are what is
tested: the three-bucket rule, the engine's right to disagree with the trader, the
blind-spot list being derived rather than hardcoded, and the refusal to contaminate the
P1 gate by showing engine lines before the levels are marked.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import annotate
import chart as chart_tool
from src.config.loader import load_config
from src.feed.replay_feed import ReplayFeed
from src.p1_pipeline import P1Pipeline
from src.reasoning.record import PROBES, measure

DAY = date(2026, 3, 4)
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cfg():
    return load_config(strict=False)


@pytest.fixture(scope="module")
def records(cfg):
    return P1Pipeline(cfg, ReplayFeed("NIFTY BANK").session(DAY)).run()


@pytest.fixture(scope="module")
def pipeline(cfg):
    p = P1Pipeline(cfg, ReplayFeed("NIFTY BANK").session(DAY))
    p.run()
    return p


def args(**kw):
    return type("Args", (), kw)


# ─────────────────────────────────────────────────────────────────────────────
# spec 13 — the reasoning record
# ─────────────────────────────────────────────────────────────────────────────
def test_a_record_exists_for_every_candle(cfg, records):
    for index in (0, 100, 374):
        r = measure(cfg, records, index)
        assert r.saw and r.expectation and r.attention


def test_the_record_uses_no_future_data(cfg, records):
    """Spec 13 §7. A reasoning record built from the future is a record of hindsight."""
    truncated = P1Pipeline(cfg, ReplayFeed("NIFTY BANK").session(DAY))
    for record in records[:121]:
        truncated.on_candle(record.candle)
    assert measure(cfg, truncated.records, 120).saw == measure(cfg, records, 120).saw


def test_blind_spots_are_derived_from_params_not_hardcoded(cfg):
    """Spec 13 §2.1: *"Naya detector banao, wo line list se apne aap hat jaayegi."*"""
    compression = next(p for p in PROBES if p.name == "compression")
    assert compression.is_blind_spot(cfg), "no compression detector exists yet"

    class WithDetector:
        def get(self, key, default=None):
            return 0.5 if key == "levels.compression_ratio_max" else cfg.get(key, default)

    assert not compression.is_blind_spot(WithDetector()), \
        "adding the detector's config key must retire the admission by itself"


def test_a_grading_input_is_still_a_detection_blind_spot(cfg):
    """`clean_formation_min_candles` reads time-at-price when SCORING a level; no
    detector uses it to FIND one. Spec 13's own worked example."""
    probe = next(p for p in PROBES if p.name == "time_at_price")
    assert cfg.get("levels.clean_formation_min_candles", None) is not None
    assert probe.is_blind_spot(cfg)


def test_some_candles_have_blind_spots_and_some_do_not(cfg, records):
    """A list that fires on every candle is noise; one that never fires is decoration."""
    hits = sum(1 for i in range(0, 375, 5) if measure(cfg, records, i).blind_spots)
    assert 0 < hits < 75


# ─────────────────────────────────────────────────────────────────────────────
# spec 12 §3.1 — three buckets, all of them
# ─────────────────────────────────────────────────────────────────────────────
def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "2026-03-04.yaml"
    path.write_text('session: "2026-03-04"\nannotator: "t"\n' + body, encoding="utf-8")
    return path


def test_check_fails_when_false_positive_is_empty(tmp_path, capsys):
    """*"Ek annotation jisme false_positive khaali hai, wo calibration nahi hai — wo
    inflation hai."* It would push the engine toward more lines every session."""
    path = write(tmp_path, 'missed:\n  - price: 100\n    why: "x"\n'
                           "false_positive: []\nconfirmed_good: []\n")
    assert annotate.cmd_check(args(file=str(path))) == 1
    assert "inflation" in capsys.readouterr().out


def test_check_passes_when_all_three_buckets_are_filled(tmp_path):
    path = write(tmp_path,
                 'missed:\n  - price: 100\n    why: "x"\n'
                 'false_positive:\n  - price: 200\n    why: "y"\n'
                 'confirmed_good:\n  - price: 300\n    note: "z"\n')
    assert annotate.cmd_check(args(file=str(path))) == 0


def test_missing_measurable_lowers_confidence_rather_than_failing(tmp_path, capsys):
    """Spec 12 §4: not being able to write it *"apne aap me jaankari hai"* — it may be
    a memory rather than a rule, so it is recorded, not rejected."""
    path = write(tmp_path,
                 'missed:\n  - price: 100\n    why: "felt like a level"\n'
                 'false_positive:\n  - price: 200\n    why: "y"\n'
                 'confirmed_good:\n  - price: 300\n    note: "z"\n')
    assert annotate.cmd_check(args(file=str(path))) == 0
    assert "confidence: low" in capsys.readouterr().out


def test_why_is_required(tmp_path):
    path = write(tmp_path, "missed:\n  - price: 100\n"
                           'false_positive:\n  - price: 200\n    why: "y"\n'
                           'confirmed_good:\n  - price: 300\n    note: "z"\n')
    assert annotate.cmd_check(args(file=str(path))) == 1


# ─────────────────────────────────────────────────────────────────────────────
# spec 12 §3.2 — the engine may disagree
# ─────────────────────────────────────────────────────────────────────────────
def test_the_engine_contradicts_a_wrong_touch_count(pipeline):
    """*"Iske bina tool sirf tumhari galtiyon ko code me likh dega, extra steps ke
    saath."*"""
    m = annotate.battery(pipeline, Decimal("58528"), 160, 170)
    conflicts = annotate.cross_check(
        {"why": "price yahan 4 baar ruki", "measurable": ""}, m)
    assert conflicts and "the data says" in conflicts[0]


def test_no_conflict_when_the_claim_matches_the_data(pipeline):
    m = annotate.battery(pipeline, Decimal("58528"), 160, 170)
    truthful = {"why": f"price yahan {m.values['separated_touches']} baar ruki",
                "measurable": ""}
    assert annotate.cross_check(truthful, m) == []


def test_cross_check_stays_silent_without_a_numeric_claim(pipeline):
    """A cross-checker that guesses produces noise, and noise trains the trader to
    ignore the one time it is right."""
    m = annotate.battery(pipeline, Decimal("58528"), 160, 170)
    assert annotate.cross_check({"why": "it looked strong", "measurable": ""}, m) == []


# ─────────────────────────────────────────────────────────────────────────────
# spec 12 §5 — the fixed battery and the near-miss
# ─────────────────────────────────────────────────────────────────────────────
def test_measurement_battery_is_fixed(pipeline):
    """The same measurements every time, or annotations cannot be compared — and
    comparison across sessions is what separates a rule from a memory."""
    a = annotate.battery(pipeline, Decimal("58528"), 160, 170)
    b = annotate.battery(pipeline, Decimal("58700"), 100, 110)
    assert set(a.values) == set(b.values)
    assert len(a.values) >= 12


def test_battery_counts_separated_touches_not_raw_candles(pipeline):
    """The engine's own touch rule (spec 03 §4 v2.2) — hovering is one touch."""
    m = annotate.battery(pipeline, Decimal("58528"), 160, 170)
    assert m.values["separated_touches"] <= m.values["candles_touching_price"]


def test_near_miss_names_the_closest_detector_and_the_shortfall(pipeline, cfg):
    """Spec 12 §5 step 2 — *"Ye sabse valuable output hai."* "Missed by 0.15 x ATR" is
    a threshold change; "no detector was close" is the only honest reason for a new one."""
    diagnosis = annotate.diagnose(pipeline, cfg, Decimal("58528"), 160, 170)
    assert {"LAUNCH", "WICK_CLUSTER", "SWING_PIVOT"} <= set(diagnosis)
    if "shortfall_atr" in diagnosis.get("LAUNCH", {}):
        assert diagnosis["LAUNCH"]["shortfall_atr"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# the P1 gate must not be contaminated
# ─────────────────────────────────────────────────────────────────────────────
def test_engine_lines_are_refused_on_the_p1_gate_selection(capsys):
    """Spec 09 §3.2b. Detected from the file's `purpose`, so a renamed copy is caught."""
    selection = REPO_ROOT / "reports" / "charts" / "selection.json"
    assert json.loads(selection.read_text(encoding="utf-8"))["purpose"] == "p1_overlap"
    assert chart_tool._is_p1_gate_selection(str(selection)) is True
    assert chart_tool.main(["--selection", str(selection), "--levels"]) == 2
    assert "agreeableness" in capsys.readouterr().err


def test_charts_are_blank_unless_levels_is_asked_for(tmp_path):
    path = chart_tool.render_session("NIFTY BANK", DAY, tmp_path, with_levels=False)
    assert '"engine":[]' in path.read_text(encoding="utf-8").replace(" ", "")


def test_levels_overlay_carries_grades_and_omits_round_numbers(tmp_path):
    path = chart_tool.render_session("NIFTY BANK", DAY, tmp_path, with_levels=True)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text.split("const DATA = ")[1].split(";\nconst MARKS")[0])
    assert data["engine"], "the overlay must carry the book"
    for lv in data["engine"]:
        assert {g for _, g in lv["grades"]} <= {"A", "B", "C"}
        assert not lv.get("is_round_number")
    assert "solid = Grade A" in text


def test_every_level_carries_its_own_history(tmp_path):
    """The overlay used to be `{price, grade, kind, touches}` for the closing book, drawn
    as a line across the whole session. Three questions had no answer on that chart, and
    each one is a thing a trader asks out loud: *when did this line appear*, *which
    candles made it*, and *how wide is it*. All three were already in `Level`; the chart
    was discarding them."""
    path = chart_tool.render_session("NIFTY BANK", DAY, tmp_path, with_levels=True)
    data = json.loads(path.read_text(encoding="utf-8")
                      .split("const DATA = ")[1].split(";\nconst MARKS")[0])
    n1m = len(data["tf"]["1m"])
    for lv in data["engine"]:
        assert 0 <= lv["born"] < n1m
        assert lv["died"] is None or lv["born"] <= lv["died"] < n1m
        assert lv["zlo"] <= lv["body"] <= lv["zhi"]
        assert lv["zlo"] <= lv["wick"] <= lv["zhi"]
        assert all(j <= lv["born"] for j in lv["source"]), \
            "a level cannot be built from a candle that had not closed yet"
        assert lv["grades"] and lv["grades"][0][0] == lv["born"]
        assert lv["died"] is None or lv["why_died"]


def test_timeline_series_are_change_points_only(tmp_path):
    """375 candles x 175 levels x 3 series per candle would be most of the file. The
    chart only ever asks 'what was it at candle N', so only changes are stored."""
    path = chart_tool.render_session("NIFTY BANK", DAY, tmp_path, with_levels=True)
    data = json.loads(path.read_text(encoding="utf-8")
                      .split("const DATA = ")[1].split(";\nconst MARKS")[0])
    for lv in data["engine"]:
        for key in ("grades", "touches", "shown"):
            series = lv[key]
            indices = [i for i, _ in series]
            assert indices == sorted(indices), f"{key} is out of order"
            values = [v for _, v in series]
            assert all(a != b for a, b in zip(values, values[1:])), \
                f"{key} repeats a value — that is not a change point"


def test_the_overlay_never_reaches_past_the_window(tmp_path):
    """`--candles A B` must truncate what the engine was shown, not just what is drawn."""
    full = chart_tool.level_timeline("NIFTY BANK", DAY, None)
    cut = chart_tool.level_timeline("NIFTY BANK", DAY, 120)
    assert all(lv["born"] <= 120 for lv in cut)
    assert len(cut) < len(full)
