"""
Reachability — spec 10 §6.

A battery that passes proves nothing. What matters is whether it **catches the bugs it
was written for**, so every test here injects one of the real dry-run failures into the
config and asserts the engine refuses to start.

`prototype/FINDINGS.md` documents four bugs that made the system unable to trade. Three
are catchable before a single candle is processed. The fourth — the R ceiling meeting a
real 69-point sweep — needed a run, and that honest limit is asserted too.
"""

from __future__ import annotations

import copy

import pytest

from src.config.loader import Config, load_config
from src.health.reachability import Reachability, assert_gates_are_reachable, report


@pytest.fixture(scope="module")
def base():
    return load_config(strict=False)


def mutate(cfg: Config, **paths) -> Config:
    """A copy of the config with dotted keys overridden."""
    params = copy.deepcopy(cfg.params)
    for dotted, value in paths.items():
        node = params
        parts = dotted.replace("__", ".").split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return Config(params=params, costs=cfg.costs, events=cfg.events,
                  digest="test", source_dir=cfg.source_dir)


def failures(cfg: Config) -> set[str]:
    return {a.name for a in Reachability(cfg).run() if not a.passed}


# ─────────────────────────────────────────────────────────────────────────────
# the shipped config must pass
# ─────────────────────────────────────────────────────────────────────────────
def test_current_config_is_fully_reachable(base):
    assert assert_gates_are_reachable(base) == []


def test_report_counts_every_assertion(base):
    text, passed, total = report(base)
    assert passed == total >= 12
    assert "REACHABILITY" in text


# ─────────────────────────────────────────────────────────────────────────────
# the four dry-run bugs
# ─────────────────────────────────────────────────────────────────────────────
def test_catches_the_grade_a_bug(base):
    """Bug 1. If Grade A needs a score no kind can reach, nothing is tradeable — and
    the engine returns a clean, confident NO_TRADE on every candle while saying nothing
    is wrong. ALERT was 0% of the dry-run session."""
    broken = mutate(base, **{"levels.grade_a_min_score": 5})
    assert "some_kind_can_reach_grade_a" in failures(broken)
    assert "anchor_can_reach_grade_a" in failures(broken)


def test_catches_the_anchor_contradiction(base):
    """Bug 1's second half. Spec 06 makes Setup B the ONLY permitted setup at an anchor;
    spec 03 requires Grade A to trigger. If an anchor cannot reach Grade A, Setup B can
    never fire at PDH or PDL — the exact locations spec 06 calls most important."""
    broken = mutate(base, **{"levels.grade_a_min_score": 4})
    assert "anchor_can_reach_grade_a" in failures(broken)


def test_catches_the_touch_separation_bug(base):
    """Bug 2. Without separation, price hovering near a zero-pocket level counts three
    touches in three minutes and kills it. PDL died at 09:57 — two minutes before its
    own sweep, the flagship trade of the day."""
    broken = mutate(base, **{"levels.touch_separation_points": 0,
                             "levels.touch_separation_atr_mult": 0})
    assert "touch_separation_positive" in failures(broken)


def test_catches_the_setup_b_window_bug(base):
    """Bug 3. `htf_close_proximity` blocks the last 3 minutes of every 15m candle, and
    Setup B's reclaim goes stale after 2 candles — so by the time the block lifted, the
    setup was gone. Two individually correct rules deleting the setup with the best
    risk-reward in the system.

    Modelled here by removing the exemption and widening the buffer until nothing is
    left: the assertion must notice that a setup has no minute it may fire in.
    """
    broken = mutate(base, **{"time.htf_close_exempt_setups": [],
                             "structure.htf_close_buffer_minutes": 15})
    assert "every_setup_has_a_permitting_window" in failures(broken)


def test_catches_the_r_ceiling_bug(base):
    """Bug 4. v1's flat 35-point ceiling rejected a qualifying Setup B sweep at high
    volatility — filtering out the STRONGEST expression of the setup, and doing it more
    on the days sweeps carry the most information."""
    broken = mutate(base, **{"risk.r_max_points": 35, "risk.r_max_atr_mult": 0.5})
    assert "setup_b_r_is_achievable" in failures(broken)


def test_catches_the_authors_own_entry_cap_bug(base):
    """The bug the spec's own author introduced twenty minutes after writing the spec
    that catches it: cap 1.2 + buffer 0.45 = 1.65, against a ceiling of 1.40. Not
    reachable at ANY volatility, and reading it did not find it."""
    broken = mutate(base, **{"setups.b_entry_max_extreme_atr_mult": 1.2})
    assert "b_entry_cap_fits_under_r_max" in failures(broken)
    assert "setup_b_r_is_achievable" in failures(broken)


# ─────────────────────────────────────────────────────────────────────────────
# the other admissible-input failures
# ─────────────────────────────────────────────────────────────────────────────
def test_catches_inverted_r_bounds(base):
    broken = mutate(base, **{"risk.r_min_points": 80})
    assert "r_min_below_r_max_at_every_atr" in failures(broken)


def test_catches_flapping_dormancy(base):
    """Revival further out than dormancy makes a level sleep and wake on one candle."""
    broken = mutate(base, **{"levels.revival_distance_atr_mult": 30})
    assert "revival_inside_dormancy" in failures(broken)


def test_catches_the_round_number_space_gate(base):
    """REVIEW-v2 §5: letting a 100-mark gate the space check made the gate a coin flip
    on the entry price's last two digits — 37.5% pass at R 25, and 0% at R 40."""
    strengths = dict(base.get("levels.obstacle_strength"))
    strengths["round_100"] = "medium"
    broken = mutate(base, **{"levels.obstacle_strength": strengths})
    assert "space_gate_is_satisfiable" in failures(broken)


def test_catches_round_numbers_counting_against_the_cap(base):
    broken = mutate(base, **{"levels.round_numbers_count_against_cap": True})
    assert "level_cap_leaves_room_for_a_trigger" in failures(broken)


def test_catches_the_journey_gate_being_opened(base):
    """D-011b. The Journey encodes an intuition that has never been measured; wiring it
    into a gate is the most likely way this system acquires a losing rule nobody can
    argue with, because it will feel obviously true."""
    broken = mutate(base, **{"structure.journey_gates_trades": True})
    assert "journey_does_not_gate_trades" in failures(broken)


def test_catches_an_inverted_trading_window(base):
    broken = mutate(base, **{"time.windows_normal": [["11:15", "09:30"]]})
    assert "trading_windows_are_non_empty" in failures(broken)


def test_catches_a_warmup_that_outlasts_the_first_window(base):
    """ATR needs `atr_period` candles. If the first window opens before that, the
    engine is BLOCKED for part of its own trading time and nobody said so."""
    broken = mutate(base, **{"volatility.atr_period": 60})
    assert "warmup_fits_inside_the_session" in failures(broken)


# ─────────────────────────────────────────────────────────────────────────────
# the honest limits
# ─────────────────────────────────────────────────────────────────────────────
def test_a_broken_assertion_counts_as_a_failure(base):
    """A check that raises has not passed. Silent degradation in a startup guard is
    worse than no guard."""
    broken = mutate(base, **{"levels.obstacle_strength": {}})
    assert "space_gate_is_satisfiable" in failures(broken)


def test_reachability_cannot_catch_bug_4_as_it_actually_happened(base):
    """Honest limit, stated as a test so it is not mistaken for coverage.

    The real 09:58 sweep produced R = 69 against a ceiling of 40.7 — not because the
    parameters were unreachable, but because a genuine textbook sweep's geometry
    (30-point wick, 26-point reclaim body) put entry 56 points from the stop. The
    config was reachable; the market was wider than it.

    That is what the P3 detection counts and the P1.5 teaching loop exist for. No
    startup assertion can substitute for running the thing.
    """
    assert assert_gates_are_reachable(base) == []
    cap = base.dec("setups.b_entry_max_extreme_atr_mult")
    buf = base.dec("risk.sl_buffer_atr_mult")
    atr_29 = 29
    modelled_r = float(cap + buf) * atr_29
    assert modelled_r < 69, (
        "the modelled Setup B R is well inside the ceiling; the dry run's real 69-point "
        "R came from candle geometry the config cannot describe")
