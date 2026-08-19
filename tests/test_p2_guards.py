"""
Guards, the mode machine and session persistence — spec 05 §9.

Two tests here carry more weight than the rest:

`test_htf_tail_blocks_a_and_c_but_never_b` is `prototype/FINDINGS.md` Bug 3, the worst
one found: six of six Setup B conditions passed on a textbook sweep and the detector
never ran, because the guard had set the mode to BLOCKED.

`test_session_state_survives_a_restart` is `REVIEW-v2.md` §4: four losses on a day
capped at two, because the kill switch lived only in memory.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal

import pytest

from src.config.loader import Config, load_config
from src.domain.models import IST, Candle, Mode, to_decimal
from src.guards.engine import GuardEngine, SessionContext, resolve_mode
from src.state.session_store import SessionState, SessionStore

DAY = date(2026, 3, 4)


@pytest.fixture(scope="module")
def cfg():
    return load_config(strict=False)


@pytest.fixture(scope="module")
def guards(cfg):
    return GuardEngine(cfg)


def candle_at(hh: int, mm: int) -> Candle:
    t = datetime.combine(DAY, dtime(hh, mm), tzinfo=IST)
    return Candle("X", "1m", t, t + timedelta(minutes=1),
                  to_decimal(100), to_decimal(110), to_decimal(90), to_decimal(105))


def fresh() -> SessionState:
    return SessionState(trading_date=DAY)


def run(guards, hh=10, mm=30, atr=Decimal(25), state=None, ctx=None,
        candles_seen=100, htf_remaining=10):
    return guards.evaluate(candle_at(hh, mm), ctx or SessionContext(day=DAY),
                           state or fresh(), atr, candles_seen, htf_remaining)


def with_params(cfg: Config, **paths) -> Config:
    params = copy.deepcopy(cfg.params)
    for dotted, value in paths.items():
        node = params
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return Config(params, cfg.costs, cfg.events, "test", cfg.source_dir)


# ─────────────────────────────────────────────────────────────────────────────
# THE ONE THAT MATTERS — Bug 3
# ─────────────────────────────────────────────────────────────────────────────
def test_htf_tail_blocks_a_and_c_but_never_b(guards):
    """Spec 05 §3b v2.2.

    *"Sweeps form in the last 3 minutes of a 15m candle (the trader's own observation);
    entries are blocked for exactly those 3 minutes; by the time the block lifts the
    reclaim is 3+ candles old -> setup_stale."* Setup B was structurally unable to trade
    at the time Setup B most often forms.

    The guard's own reason — HTF candles reverse shape in their final minutes — is an
    argument about CONTINUATION entries. Setup B is the trade that profits from that
    reversal; the wick the guard warns about IS the sweep.
    """
    outcome = run(guards, htf_remaining=2)
    assert outcome.passed, "the tail must NOT block the mode — the detector has to run"
    assert outcome.blocked_setups == frozenset({"A_flip_retest", "C_range_break_retest"})
    assert "B_sweep_reclaim" not in outcome.blocked_setups


def test_outside_the_tail_no_setup_is_blocked(guards):
    assert run(guards, htf_remaining=10).blocked_setups == frozenset()


def test_the_tail_never_produces_a_blocked_mode(guards):
    """The mode is what decides whether the detector runs at all."""
    outcome = run(guards, htf_remaining=1)
    mode = resolve_mode(outcome, position_open=False,
                        distance_to_active=Decimal(5), alert_distance=Decimal(30))
    assert mode is Mode.ALERT


# ─────────────────────────────────────────────────────────────────────────────
# guard order and the individual gates — spec 05 §1
# ─────────────────────────────────────────────────────────────────────────────
def test_warmup_blocks_the_first_candles(guards):
    assert run(guards, candles_seen=13).failed_gate == "warmup"
    assert run(guards, candles_seen=13, atr=None).failed_gate == "warmup"
    assert run(guards, candles_seen=14).passed


def test_volatility_floor_and_ceiling(guards):
    assert run(guards, atr=Decimal(9)).failed_gate == "volatility_floor"
    assert run(guards, atr=Decimal(71)).failed_gate == "volatility_ceiling"
    assert run(guards, atr=Decimal(12)).passed, "the floor is inclusive"
    assert run(guards, atr=Decimal(60)).passed, "the ceiling is inclusive"


def test_no_entry_before_0930_or_at_lunch(guards):
    assert run(guards, 9, 22).failed_gate == "time_window"
    assert run(guards, 12, 10).failed_gate == "time_window"
    assert run(guards, 14, 50).failed_gate == "time_window"
    assert run(guards, 9, 30).passed and run(guards, 13, 30).passed


def test_expiry_window_is_narrower(cfg):
    guards = GuardEngine(cfg)
    normal = SessionContext(day=DAY, is_expiry=False)
    expiry = SessionContext(day=DAY, is_expiry=True)
    assert run(guards, 9, 45, ctx=normal).passed
    assert run(guards, 9, 45, ctx=expiry).failed_gate == "time_window"
    assert run(guards, 10, 30, ctx=expiry).passed


def test_feed_gap_blocks(guards, cfg):
    limit = int(cfg.get("feed.synthetic_candle_max_consecutive"))
    ok = SessionContext(day=DAY, consecutive_synthetic=limit)
    bad = SessionContext(day=DAY, consecutive_synthetic=limit + 1)
    assert run(guards, ctx=ok).passed
    assert run(guards, ctx=bad).failed_gate == "feed_gap"


def test_gap_regime_blocks_until_1000(guards):
    """Spec 05 §1c: after a large gap, carried levels describe a market that no longer
    exists — price never traded through the intervening range."""
    gapped = SessionContext(day=DAY, gap_pct=Decimal("0.60"))
    assert run(guards, 9, 45, ctx=gapped).failed_gate == "gap_regime"
    assert run(guards, 10, 15, ctx=gapped).passed
    small = SessionContext(day=DAY, gap_pct=Decimal("0.20"))
    assert run(guards, 9, 45, ctx=small).passed


def test_position_open_blocks_new_entries(guards):
    ctx = SessionContext(day=DAY, position_open=True)
    assert run(guards, ctx=ctx).failed_gate == "position_open"


def test_event_blackout_full_day(cfg):
    events = dict(cfg.events)
    events["rbi_mpc"] = [DAY]
    guards = GuardEngine(Config(cfg.params, cfg.costs, events, "t", cfg.source_dir))
    assert run(guards, 10, 30).failed_gate == "event_blackout"


def test_event_blackout_partial_lifts_at_1115(cfg):
    events = dict(cfg.events)
    events["heavyweight_bank_results"] = [{"date": DAY, "symbol": "HDFCBANK"}]
    guards = GuardEngine(Config(cfg.params, cfg.costs, events, "t", cfg.source_dir))
    assert run(guards, 10, 40).failed_gate == "event_blackout"
    assert run(guards, 13, 30).passed, "normal windows resume after the cutoff"


# ─────────────────────────────────────────────────────────────────────────────
# latching — spec 05 §4
# ─────────────────────────────────────────────────────────────────────────────
def test_session_max_trades_latches(guards):
    state = fresh().with_fill().with_fill().with_fill()
    assert run(guards, state=state).failed_gate == "session_max_trades"


def test_two_consecutive_losses_latch(guards):
    state = (fresh().with_fill().with_result(Decimal(-1), 10, 3)
             .with_fill().with_result(Decimal(-1), 40, 3))
    assert run(guards, state=state).failed_gate == "session_consec_loss"


def test_a_win_resets_the_consecutive_counter_but_not_the_cap(guards):
    state = (fresh().with_fill().with_result(Decimal(-1), 10, 3)
             .with_fill().with_result(Decimal("1.5"), 40, 3))
    assert state.consecutive_losses == 0
    assert state.trades_taken == 2
    assert run(guards, state=state).passed


def test_cumulative_loss_cap(guards):
    state = fresh().with_fill().with_result(Decimal("-2.0"), 10, 3)
    assert run(guards, state=state).failed_gate == "session_max_loss"


def test_r_model_broken_latches_on_realised_losses(guards):
    """Spec 05 §4b. *"If real losses are systematically 1.3R when the model says 1.0R,
    the -2R daily cap is actually a -2.6R cap and every r_realised in the journal is
    wrong."* The response is to fix delta measurement, never to widen the budget."""
    state = fresh()
    for _ in range(10):
        state = state.with_result(Decimal("-1.35"), 0, 0)
    state = SessionState(trading_date=DAY, realised_r_history=state.realised_r_history)
    assert run(guards, state=state).failed_gate == "r_model_broken"


def test_a_latched_state_cannot_be_unlatched():
    """Spec 05 §9 asks for a verification that no un-block path exists. The absence of
    an `unlatch` method IS that verification."""
    state = fresh().latched("session_consec_loss", "two losses")
    assert not hasattr(state, "unlatch")
    assert state.latched("session_max_trades", "x").blocked_reason == "session_consec_loss"


def test_duplicate_attempt_registry():
    state = fresh().with_attempt("L001", "B_sweep_reclaim")
    assert state.has_attempted("L001", "B_sweep_reclaim")
    assert not state.has_attempted("L001", "A_flip_retest")


def test_cooldown_after_an_exit():
    state = fresh().with_result(Decimal(1), candle_index=100, cooldown_candles=3)
    assert state.in_cooldown(102) and not state.in_cooldown(103)


# ─────────────────────────────────────────────────────────────────────────────
# the mode machine — spec 05 §6
# ─────────────────────────────────────────────────────────────────────────────
def test_mode_transitions(guards):
    passed = run(guards)
    blocked = run(guards, atr=Decimal(5))
    assert resolve_mode(blocked, False, Decimal(5), Decimal(30)) is Mode.BLOCKED
    assert resolve_mode(passed, True, Decimal(5), Decimal(30)) is Mode.IN
    assert resolve_mode(passed, False, Decimal(5), Decimal(30)) is Mode.ALERT
    assert resolve_mode(passed, False, Decimal(90), Decimal(30)) is Mode.WATCH
    assert resolve_mode(passed, False, None, Decimal(30)) is Mode.WATCH


def test_a_round_number_never_triggers_alert(guards):
    """REVIEW-v2 §5a: on a 100-point grid with a 20-point alert distance, price is
    within reach of SOME 100-mark 40% of the session by construction. ALERT would never
    switch off and the location discipline collapses."""
    passed = run(guards)
    assert resolve_mode(passed, False, Decimal(3), Decimal(30),
                        active_is_round=True) is Mode.WATCH


def test_position_open_wins_over_a_failed_guard(guards):
    """D-008: exits ALWAYS run. There is no state in which a position is open and
    unmanaged."""
    blocked = run(guards, atr=Decimal(5))
    assert resolve_mode(blocked, True, Decimal(5), Decimal(30)) is Mode.IN


# ─────────────────────────────────────────────────────────────────────────────
# persistence — CLAUDE.md §12, REVIEW-v2 §4
# ─────────────────────────────────────────────────────────────────────────────
def test_session_state_survives_a_restart(tmp_path):
    """The exact REVIEW-v2 §4 sequence: two losses, process dies, supervisor restarts.
    Without persistence the engine comes back with a clean slate and loses the day a
    second time — the precise scenario the limits exist to prevent."""
    path = tmp_path / "session.json"
    store = SessionStore(path)
    state = store.load_or_create(DAY)
    state = store.save(state.with_fill().with_result(Decimal(-1), 10, 3))
    state = store.save(state.with_fill().with_result(Decimal(-1), 40, 3))

    reborn = SessionStore(path)
    resumed = reborn.load_or_create(DAY)
    assert resumed.trades_taken == 2
    assert resumed.consecutive_losses == 2
    assert resumed.cumulative_r == Decimal(-2)
    assert "RESUMED" in reborn.resume_banner()


def test_a_new_day_starts_clean_without_a_flag(tmp_path):
    path = tmp_path / "session.json"
    store = SessionStore(path)
    store.save(store.load_or_create(DAY).with_fill().with_fill())
    tomorrow = SessionStore(path).load_or_create(date(2026, 3, 5))
    assert tomorrow.trades_taken == 0, "a new day is not a reset"


def test_fresh_start_on_the_same_day_requires_the_flag(tmp_path):
    path = tmp_path / "session.json"
    store = SessionStore(path)
    store.save(store.load_or_create(DAY).with_fill())
    assert SessionStore(path).requires_explicit_fresh(DAY) is True
    assert SessionStore(path, force_fresh=True).requires_explicit_fresh(DAY) is False
    forced = SessionStore(path, force_fresh=True).load_or_create(DAY)
    assert forced.trades_taken == 0


def test_every_change_reaches_disk(tmp_path):
    """*"Write on every change, synchronously, before the next candle is processed.
    Not at end of day, not on a timer."*"""
    path = tmp_path / "session.json"
    store = SessionStore(path)
    state = store.load_or_create(DAY)
    for expected in (1, 2, 3):
        state = store.save(state.with_fill())
        assert json.loads(path.read_text(encoding="utf-8"))["trades_taken"] == expected


def test_attempted_levels_and_history_round_trip(tmp_path):
    path = tmp_path / "session.json"
    store = SessionStore(path)
    state = store.load_or_create(DAY)
    state = store.save(state.with_attempt("L001", "B_sweep_reclaim")
                       .with_result(Decimal("-1.25"), 10, 3))
    back = SessionStore(path).load_or_create(DAY)
    assert back.has_attempted("L001", "B_sweep_reclaim")
    assert back.realised_r_history == (Decimal("-1.25"),)
    assert isinstance(back.cumulative_r, Decimal)


def test_latched_block_survives_a_restart(tmp_path):
    path = tmp_path / "session.json"
    store = SessionStore(path)
    store.save(store.load_or_create(DAY).latched("session_consec_loss", "two losses"))
    assert SessionStore(path).load_or_create(DAY).blocked_reason == "session_consec_loss"


def test_no_silent_counter_reset_path_exists():
    """Spec 09 §3.2's `test_no_silent_session_counter_reset`.

    Parsed, not grepped. A regex over source lines fires on the module docstring, which
    quotes REVIEW-v2 §4's failure sequence verbatim — `trades_taken = 0, ...` — and a
    check that cannot tell a description of the bug from the bug is a check that gets
    silenced. Only a real assignment counts.

    And only inside a function body: a dataclass field default (`trades_taken: int = 0`
    at class level) is the legitimate DEFINITION of a fresh session, not a reset of a
    live one. Flagging that would make the check unpassable and therefore worthless.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "src" / "state"
              / "session_store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    counters = {"trades_taken", "consecutive_losses", "cumulative_r"}

    for function in [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = getattr(target, "attr", getattr(target, "id", None))
                if name not in counters:
                    continue
                value = getattr(node, "value", None)
                if isinstance(value, ast.Constant) and value.value in (0, "0"):
                    raise AssertionError(
                        f"{function.name}() line {node.lineno}: a bare counter reset. "
                        f"Starting fresh must go through --force-fresh-session.")


# ─────────────────────────────────────────────────────────────────────────────
# the startup sequence — spec 10 §4
# ─────────────────────────────────────────────────────────────────────────────
def test_startup_refuses_while_the_config_is_incomplete(cfg, tmp_path):
    """All three blockers at once. Discovering them one run at a time loses a morning."""
    from src.health.startup import startup

    result = startup(cfg, DAY, SessionStore(tmp_path / "s.json"))
    assert not result.may_start
    assert len(result.blockers) == 3
    assert "REFUSING TO START" in result.banner
    assert "16/16 assertions pass" in result.banner


def test_startup_refuses_on_a_failed_reachability_assertion(cfg, tmp_path):
    """Spec 10 §6's `test_startup_refuses_on_failed_assertion`."""
    from src.health.startup import startup

    broken = with_params(cfg, **{"levels.grade_a_min_score": 5})
    result = startup(broken, DAY, SessionStore(tmp_path / "s.json"))
    assert not result.may_start
    assert any("reachability" in b for b in result.blockers)


def test_startup_refuses_when_a_session_file_exists_without_the_flag(cfg, tmp_path):
    """CLAUDE.md §12 — silently resetting a kill switch is forbidden."""
    from src.health.startup import startup

    path = tmp_path / "s.json"
    store = SessionStore(path)
    store.save(store.load_or_create(DAY).with_fill())
    result = startup(cfg, DAY, SessionStore(path))
    assert any("force-fresh-session" in b for b in result.blockers)
    assert SessionStore(path, force_fresh=True).requires_explicit_fresh(DAY) is False


def test_startup_reports_every_assertion_even_when_green(cfg, tmp_path):
    """Spec 10 §2: *"Every check reports even when green. A dashboard that only shows
    problems teaches you nothing about what normal looks like."*"""
    from src.health.startup import startup

    banner = startup(cfg, DAY, SessionStore(tmp_path / "s.json")).banner
    for name in ("some_kind_can_reach_grade_a", "setup_b_r_is_achievable",
                 "every_setup_has_a_permitting_window", "journey_does_not_gate_trades"):
        assert name in banner
