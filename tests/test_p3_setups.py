"""
P3 — the three setups. Spec 06.

No golden fixtures here, and that is a deliberate, recorded choice. `BUILD-BRIEF.md` §5:

> *"You cannot create these honestly. A fixture you generate to match your own
> implementation tests that the code does what the code does."*

The trader declined to hand-pick fixtures and asked to verify on the chart by replaying
real sessions instead. So what is tested here is the part that can be checked without a
ground truth — **the structural rules**, the ones that must hold whatever the market did:
the registry length, the ANCHOR restriction, the absence of a code path from breakout to
entry, and the shape of every result. Whether a detection is *right* is answered by
`tools/setup_report.py` plus the chart, and any detection the trader confirms becomes a
`source: real_chart` regression fixture from that point on.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.config.loader import load_config
from src.domain.models import (
    IST, Candle, Grade, Level, LevelKind, LevelSide, Mode)
from src.guards.engine import GuardOutcome
from src.setups.base import (
    SETUP_A, SETUP_B, SETUP_C, SetupContext, SetupResult, build_registry,
    evaluate, preconditions)
from src.state.board import StateBoard
from src.state.session_store import SessionState

DAY = date(2026, 3, 4)


def candles(spec, day: date = DAY) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)
    out = []
    for i, (o, h, low, c) in enumerate(spec):
        t = start + timedelta(minutes=i)
        out.append(Candle("NIFTY BANK", "1m", t, t + timedelta(minutes=1),
                          Decimal(str(o)), Decimal(str(h)), Decimal(str(low)), Decimal(str(c))))
    return out


def level(kind=LevelKind.TURN, grade=Grade.A, touches=0, body="100", wick="98",
          side=LevelSide.SUPPORT) -> Level:
    return Level(id="L1", kind=kind, side=side,
                 born_at=datetime.combine(DAY, datetime.min.time(), tzinfo=IST)
                 .replace(hour=9, minute=20),
                 born_tf="1m", body_edge=Decimal(body), wick_tip=Decimal(wick),
                 grade=grade, touches=touches)


def board(price="100", atr="20") -> StateBoard:
    return StateBoard(
        at=datetime.combine(DAY, datetime.min.time(), tzinfo=IST).replace(hour=10),
        index=Decimal(price), day_high=None, day_low=None,
        opening_range_high=None, opening_range_low=None, pdh=None, pdl=None, pdc=None,
        last_swing_high_5m=None, last_swing_low_5m=None,
        active_level=None, distance_to_active=None, last_decision_candle=None,
        control="none", regime="none", atr_1m=Decimal(atr), atr20_1m=Decimal(atr),
        atr_5m=None, trend_5m="none", levels_above=(), levels_below=(),
        obstacles_above=(), obstacles_below=(), htf_closing_soon=False,
        htf_progress=Decimal(0), htf_forecast="", pullback_ratio=None,
        pullback_health="", ladder=())


def ctx(**kw) -> SetupContext:
    base = dict(
        candles=candles([(100, 101, 99, 100)] * 30), index=29, board=board(),
        level=level(), cfg=load_config(strict=False),
        guard=GuardOutcome(passed=True), state=SessionState(trading_date=DAY),
        mode=Mode.ALERT, trend_5m="none")
    base.update(kw)
    return SetupContext(**base)


# ─────────────────────────────────────────────────────────────────────────────
# the structural rules
# ─────────────────────────────────────────────────────────────────────────────
def test_registry_length_is_three():
    """Spec 06's first line, and `CLAUDE.md` §6's last prohibition. *"Every additional
    setup increases trade frequency, and trade frequency is the dominant cost and error
    multiplier in this system."* The assertion is the enforcement."""
    assert len(build_registry()) == 3
    assert set(build_registry()) == {SETUP_A, SETUP_B, SETUP_C}


def test_anchor_levels_admit_only_setup_b():
    """Spec 06: *"At `kind == ANCHOR`, Setup B is the only permitted setup. Enforce in
    `setups/base.py`, not by convention."*

    The most-watched levels hold the most stops, so they are swept most often. A plain
    rejection at PDH/PDL without a sweep is standing where the stop hunt is aimed.
    """
    anchor = ctx(level=level(kind=LevelKind.ANCHOR))
    assert preconditions(anchor, SETUP_A).gate == "no_setup"
    assert preconditions(anchor, SETUP_C).gate == "no_setup"
    assert preconditions(anchor, SETUP_B) is None


def test_every_result_is_a_detection_or_a_gate_never_both():
    """Spec 01 §1: a `Decision` is a Signal or a Rejection carrying the exact gate that
    failed. There is no third option and there is no 'maybe'."""
    with pytest.raises(ValueError):
        SetupResult(SETUP_A)
    with pytest.raises(ValueError):
        SetupResult(SETUP_A, detection=object(), gate="no_setup")


def test_evaluate_asks_every_setup_and_keeps_every_answer():
    """Returning only the first hit would make the rejection histogram meaningless, and
    spec 01 §10 calls that histogram the most valuable dataset the system produces."""
    results = evaluate(ctx())
    assert len(results) == 3
    assert {r.setup for r in results} == {SETUP_A, SETUP_B, SETUP_C}
    assert all(r.detection is not None or r.gate for r in results)


# ─────────────────────────────────────────────────────────────────────────────
# the preconditions, one gate at a time
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kw,gate", [
    (dict(mode=Mode.WATCH), "no_live_level"),
    (dict(mode=Mode.BLOCKED), "no_live_level"),
    (dict(level=level(grade=Grade.B)), "no_live_level"),
    (dict(level=level(grade=Grade.C)), "no_live_level"),
    (dict(level=level(touches=3)), "no_live_level"),
    (dict(guard=GuardOutcome(passed=True, blocked_setups=frozenset({SETUP_A}))), "no_setup"),
])
def test_preconditions_reject_with_the_right_gate(kw, gate):
    assert preconditions(ctx(**kw), SETUP_A).gate == gate


def test_a_duplicate_attempt_is_refused():
    """`CLAUDE.md` §6: no re-entry into the same failed setup more than once per level
    per session."""
    state = SessionState(trading_date=DAY).with_attempt("L1", SETUP_A)
    assert preconditions(ctx(state=state), SETUP_A).gate == "duplicate_setup"
    assert preconditions(ctx(state=state), SETUP_B) is None, "only that setup is barred"


def test_cooldown_blocks_every_setup():
    state = SessionState(trading_date=DAY).with_result(Decimal("-1"), 20, 10)
    blocked = ctx(state=state, index=25)
    assert all(preconditions(blocked, s).gate == "no_setup"
               for s in (SETUP_A, SETUP_B, SETUP_C))


def test_preconditions_pass_when_everything_is_in_order():
    assert preconditions(ctx(), SETUP_B) is None


# ─────────────────────────────────────────────────────────────────────────────
# Setup C — the rule that must not exist in prose only
# ─────────────────────────────────────────────────────────────────────────────
def test_no_code_path_from_breakout_to_detection():
    """Spec 06: *"C3 alone is never an entry. Entry is only at C6, on the retest. Enforce
    by having the detector return nothing at C3/C4; **there must be no code path from
    breakout to order.**"*

    Checked by reading the source rather than by a fixture: a detection built anywhere
    other than after the trigger check is the failure this is guarding against, and a
    candle sequence can only ever show that it did not happen *this time*.
    """
    import inspect

    from src.setups import range_break

    source = inspect.getsource(range_break.detect_c)
    build = source.index("Detection(")
    trigger = source.index("triggered = ")
    close_third = source.index("close_third")
    assert trigger < build, "the trigger check must run before a Detection is built"
    assert close_third < build, "the close-third check must run before a Detection is built"
    assert source.count("Detection(") == 1, "exactly one place may construct a detection"


def test_a_failed_breakout_is_not_relabelled_as_setup_c():
    """Spec 06: a breakout that closes back inside within `acceptance_candles` is a Setup
    B candidate in the opposite direction — *"do not create a fourth setup for it."*"""
    import inspect

    from src.setups import range_break

    source = inspect.getsource(range_break.detect_c)
    assert 'gate="setup_stale"' in source
    assert "failed breakout" in source


def test_range_requires_every_one_of_r1_to_r4():
    """*"If these do not hold, there is no range, and Setup C cannot exist. The engine
    must say so rather than approximating."*"""
    from src.setups.range_break import find_range

    c = ctx(candles=candles([(100, 101, 99, 100)] * 10), index=9)
    assert find_range(c, c.candles, 9) is None, "10 candles cannot satisfy R1 (>= 20)"

    flat = ctx(candles=candles([(100, 100.5, 99.5, 100)] * 40), index=39)
    assert find_range(flat, flat.candles, 39) is None, "a 1-point band fails R3 (min width)"


# ─────────────────────────────────────────────────────────────────────────────
# Setup B — the counterfactual the spec asks to be recorded
# ─────────────────────────────────────────────────────────────────────────────
def test_setup_b_records_all_three_entries_whichever_mode_is_active():
    """Spec 06 §v2.2 gives three answers to the wide-R tension and says the choice should
    be *"answered with data instead of argument"*. That is only possible later if all
    three numbers were written down at the time, on every decision."""
    import inspect

    from src.setups import sweep_reclaim

    source = inspect.getsource(sweep_reclaim)
    for field in ("entry_reclaim_close", "entry_pullback", "pullback_wait_candles",
                  "r_if_reclaim_close", "r_if_pullback"):
        assert field in source, f"{field} must be logged on every Setup B decision"


def test_setup_b_never_moves_the_stop_inside_the_sweep_wick():
    """*"Do not 'fix' this by moving the stop closer than the sweep wick tip. The wick tip
    is the whole point of the setup — it is where the stops were."*

    The detection's `extreme` must be the sweep candle's own extreme, never a shrunken
    version of it chosen to make R fit.
    """
    import inspect

    from src.setups import sweep_reclaim

    source = inspect.getsource(sweep_reclaim._attempt)
    assert "extreme = sweep.l if long_side else sweep.h" in source


def test_setup_b_takes_direction_from_the_sweep_not_the_level():
    """An ANCHOR carries no side and a BREAK axis works both ways — asking the level
    which way to trade fails on exactly the levels this setup exists for."""
    import inspect

    from src.setups import sweep_reclaim

    source = inspect.getsource(sweep_reclaim.detect_b)
    assert "long_side=True" in source and "long_side=False" in source


# ─────────────────────────────────────────────────────────────────────────────
# no look-ahead
# ─────────────────────────────────────────────────────────────────────────────
def test_no_detector_reads_past_its_own_index():
    """`CLAUDE.md` §3: the single most common way a backtest lies. The context is handed
    `candles[:index + 1]`, so a detector reaching forward gets an IndexError rather than
    a plausible number — but the slice is only safe while nothing re-derives the full
    session, so this pins the contract."""
    full = candles([(100, 101, 99, 100)] * 50)
    c = ctx(candles=full[:31], index=30)
    assert len(c.candles) == c.index + 1
    for result in evaluate(c):
        assert result.detection is None or result.detection.trigger_index <= c.index
