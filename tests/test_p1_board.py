"""
StateBoard and the Journey Ladder — spec 04 §7, §8 and §6b.

`test_board_is_deterministic` is the one that matters: *"If this test cannot pass, the
paper result will not match a live run, and the whole exercise is pointless."*
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.config.loader import load_config
from src.domain.models import IST, Candle, Grade, Level, LevelKind, LevelSide, to_decimal
from src.feed.replay_feed import ReplayFeed
from src.journey.ladder import JourneyTracker, anchor_walls
from src.p1_pipeline import P1Pipeline
from src.state.board import q_price, q_ratio

DAY = date(2026, 3, 4)


@pytest.fixture(scope="module")
def cfg():
    return load_config(strict=False)


@pytest.fixture(scope="module")
def run(cfg):
    session = ReplayFeed("NIFTY BANK").session(DAY)
    pipeline = P1Pipeline(cfg, session)
    return pipeline, pipeline.run()


def c(i: int, o: float, h: float, l: float, cl: float, tf: str = "5m") -> Candle:
    span = {"1m": 1, "5m": 5}[tf]
    start = datetime.combine(DAY, dtime(9, 15), tzinfo=IST) + timedelta(minutes=i * span)
    return Candle("TEST", tf, start, start + timedelta(minutes=span),
                  to_decimal(o), to_decimal(h), to_decimal(l), to_decimal(cl))


# ─────────────────────────────────────────────────────────────────────────────
# D-004 quantization
# ─────────────────────────────────────────────────────────────────────────────
def test_quantization_is_half_even_to_two_places():
    """D-004. ROUND_HALF_EVEN, unlike half-up, does not bias a long run of ties upward —
    and a digest built on a biased rounding is a digest that drifts."""
    assert q_price(Decimal("57434.055")) == "57434.06"
    assert q_price(Decimal("57434.045")) == "57434.04"      # half to even
    assert q_price(None) is None
    assert q_ratio(Decimal("0.123456")) == "0.1235"


# ─────────────────────────────────────────────────────────────────────────────
# the board
# ─────────────────────────────────────────────────────────────────────────────
def test_board_is_deterministic(cfg):
    """Spec 04 §7. Two replays of the same day, byte-identical digests at every step."""
    def digests():
        session = ReplayFeed("NIFTY BANK").session(DAY)
        return [r.board.board_digest for r in P1Pipeline(cfg, session).run()]

    first, second = digests(), digests()
    assert first == second
    assert len(first) == 375


def test_digest_changes_when_the_board_changes(run):
    """A digest that never changes is not a digest. 375 candles must not collapse into
    a handful of hashes."""
    _, records = run
    assert len({r.board.board_digest for r in records}) > 300


def test_board_carries_all_eight_variables(run):
    _, records = run
    board = records[-1].board
    assert board.day_high is not None and board.day_low is not None
    assert board.pdh is not None and board.pdl is not None and board.pdc is not None
    assert board.control in ("buyers", "sellers", "none")
    assert board.regime in ("trending", "ranging", "transition")
    assert board.atr_1m is not None


def test_opening_range_is_set_at_0930_and_not_before(run):
    _, records = run
    before = [r for r in records if r.candle.open_time.time() < dtime(9, 30)]
    after = [r for r in records if r.candle.open_time.time() >= dtime(9, 31)]
    assert all(r.board.opening_range_high is None for r in before)
    assert all(r.board.opening_range_high is not None for r in after)
    assert after[0].board.opening_range_high > after[0].board.opening_range_low


def test_active_level_is_the_nearest_one(run):
    _, records = run
    for record in records[::25]:
        board = record.board
        if board.active_level is None:
            continue
        candidates = board.levels_above + board.levels_below
        nearest = min(abs(lv.body_edge - board.index) for lv in candidates)
        assert abs(board.active_level.body_edge - board.index) == nearest


def test_distance_to_active_is_signed(run):
    """Positive means the level is above. The mode machine needs the sign in P2."""
    _, records = run
    for record in records[::25]:
        board = record.board
        if board.active_level is None:
            continue
        expected = board.active_level.body_edge - board.index
        assert board.distance_to_active == expected


# ─────────────────────────────────────────────────────────────────────────────
# the anticipation line — spec 04 §8
# ─────────────────────────────────────────────────────────────────────────────
def test_anticipation_is_two_steps_and_stops(run):
    """*"Three-step chains are storytelling — each step multiplies the uncertainty of
    the last."*"""
    _, records = run
    lines = [r.anticipation for r in records if r.board.active_level is not None]
    assert lines
    for line in lines[::40]:
        assert line.count("IF body close") <= 2
        assert "Control:" in line and "Regime:" in line


def test_anticipation_looks_beyond_the_level_not_beyond_the_price(run):
    """A line that says "IF body close above 60,178 -> first meeting 58,997" names a
    destination on the wrong side of its own condition."""
    _, records = run
    for record in records:
        board, line = record.board, record.anticipation
        if board.active_level is None or "first meeting" not in line:
            continue
        beyond = line.split("first meeting ")[1].split(" ")[0].replace(",", "")
        assert Decimal(beyond) > board.active_level.body_edge


def test_anticipation_never_names_the_active_level_as_its_own_destination(run):
    """The level is legitimately named three times — as the subject and in both IF
    conditions, which is spec 04 §8's template exactly. What it must never be is the
    answer to its own question: "IF close below 59,148 -> next support 59,148"."""
    _, records = run
    for record in records[::10]:
        board, line = record.board, record.anticipation
        if board.active_level is None:
            continue
        level_price = board.active_level.body_edge
        for marker in ("first meeting ", "next support "):
            if marker not in line:
                continue
            named = Decimal(line.split(marker)[1].split(" ")[0].replace(",", ""))
            assert named != level_price, f"the level is its own {marker.strip()}"


# ─────────────────────────────────────────────────────────────────────────────
# the journey ladder — spec 04 §6b
# ─────────────────────────────────────────────────────────────────────────────
def test_journey_rungs_are_ordered_and_deduplicated(cfg):
    tracker = JourneyTracker(cfg)
    axis = Level(id="AX", kind=LevelKind.BREAK, side=LevelSide.AXIS,
                 born_at=datetime.combine(DAY, dtime(10, 0), tzinfo=IST), born_tf="5m",
                 body_edge=Decimal(1000), wick_tip=Decimal(990), grade=Grade.A)
    target = Level(id="T", kind=LevelKind.TURN, side=LevelSide.RESISTANCE,
                   born_at=datetime.combine(DAY, dtime(9, 30), tzinfo=IST), born_tf="5m",
                   body_edge=Decimal(1040), wick_tip=Decimal(1045), grade=Grade.A)
    journey = tracker.on_break(
        broken=axis, axis=axis, candle=c(0, 1000, 1010, 995, 1005), direction="up",
        levels_ahead=[target],
        anchors=[(Decimal(1200), "PDH")],
        move_origin=(Decimal(1100), "origin of the 09:40 5m move"),
        broken_range_width=Decimal(100))
    assert journey is not None
    labels = [r.label for r in journey.rungs]
    assert labels[0] == "D1"
    distances = [r.distance_points for r in journey.rungs]
    assert distances == sorted(distances)
    # D2 (1100) and D3 (1000 + 100 = 1100) land on the same price -> confluence
    merged = [r for r in journey.rungs if r.confluence]
    assert merged and set(merged[0].confluence) == {"D3"}


def test_journey_resolves_failed_on_a_close_back_through_the_axis(cfg):
    tracker = JourneyTracker(cfg)
    axis = Level(id="AX", kind=LevelKind.BREAK, side=LevelSide.AXIS,
                 born_at=datetime.combine(DAY, dtime(10, 0), tzinfo=IST), born_tf="5m",
                 body_edge=Decimal(1000), wick_tip=Decimal(990), grade=Grade.A)
    tracker.on_break(broken=axis, axis=axis, candle=c(0, 1000, 1010, 995, 1005),
                     direction="up", levels_ahead=[],
                     anchors=[(Decimal(1200), "PDH")], move_origin=None,
                     broken_range_width=None)
    tracker.on_5m_close(c(1, 995, 998, 960, 965), Decimal(20))   # body back below 1000
    assert tracker.journeys[0].outcome == "failed"


def test_journey_resolves_stalled(cfg):
    tracker = JourneyTracker(cfg)
    axis = Level(id="AX", kind=LevelKind.BREAK, side=LevelSide.AXIS,
                 born_at=datetime.combine(DAY, dtime(10, 0), tzinfo=IST), born_tf="5m",
                 body_edge=Decimal(1000), wick_tip=Decimal(990), grade=Grade.A)
    tracker.on_break(broken=axis, axis=axis, candle=c(0, 1000, 1010, 995, 1005),
                     direction="up", levels_ahead=[],
                     anchors=[(Decimal(1200), "PDH")], move_origin=None,
                     broken_range_width=None)
    stall = int(cfg.get("structure.journey_stall_candles_5m"))
    for k in range(stall + 1):
        tracker.on_5m_close(c(k + 1, 1005, 1008, 1002, 1004), Decimal(20))
    assert tracker.journeys[0].outcome == "stalled"


def test_journey_summary_reports_d2_plainly(run):
    """Spec 09 §3.2c: *"D2 is the one that matters... Report it plainly and without
    cushioning."* It is measured, never acted on, until P9 says otherwise."""
    pipeline, _ = run
    summary = pipeline.journeys.summary()
    assert summary["journeys"] > 0
    assert set(summary["reached_pct"]) == {"D1", "D2", "D3", "D4"}
    assert 0 <= summary["reached_pct"]["D2"] <= 100


def test_no_journey_is_left_open_at_session_end(run):
    """A journey still `open` in the journal is a row spec 09 §3.2c cannot score."""
    pipeline, _ = run
    assert all(not j.is_open for j in pipeline.journeys.journeys)


def test_journey_gating_is_off(cfg):
    """D-011b. This must stay false until P9 measures the D2 hit rate — an unmeasured
    intuition wired into a gate is the most likely way this system acquires a losing
    rule that nobody can argue with, because it will feel obviously true."""
    assert cfg.get("structure.journey_gates_trades") is False


def test_anchor_walls_include_the_session_extremes():
    walls = anchor_walls(Decimal(1200), Decimal(900), Decimal(1150), Decimal(950), [])
    assert {why for _, why in walls} == {"PDH", "PDL", "day high", "day low"}


# ─────────────────────────────────────────────────────────────────────────────
# the pipeline end to end
# ─────────────────────────────────────────────────────────────────────────────
def test_pipeline_produces_a_record_for_every_candle(run):
    _, records = run
    assert len(records) == 375
    assert [r.index for r in records] == list(range(375))


def test_pipeline_records_births_and_deaths(run):
    _, records = run
    assert sum(len(r.new_levels) for r in records) > 20
    assert sum(len(r.dead_levels) for r in records) > 0
