"""
The 1m retest observation — `src/livemap/retest.py`.

This module is measurement, so the tests are about **whether the measurement is honest**,
not about whether the number is good:

* the three cases the request names — direct continuation, retest + re-break, retest +
  failure — each resolve to their own outcome and nothing else;
* the observation starts at the first 1m bar **after** the 5m break candle closed, never
  inside it;
* every sign mirrors, proved by running each fixture upside down;
* nothing here names a trade.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.frontier import Reading
from src.domain.models import IST, Candle
from src.livemap.interpreter import FORBIDDEN
from src.livemap.retest import (
    OUTCOMES, Break, breaks_from, compact, observe, observe_all, tally)

D = Decimal
DAY = date(2025, 3, 4)
OPEN = datetime.combine(DAY, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)


def m1(closes, *, wick: float = 2.0, start: datetime = OPEN) -> list[Candle]:
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Candle("NIFTY BANK", "1m", start + timedelta(minutes=i),
                          start + timedelta(minutes=i + 1),
                          D(str(prev)), D(str(max(prev, c) + wick)),
                          D(str(min(prev, c) - wick)), D(str(c))))
        prev = c
    return out


def flip(closes, pivot: float = 45000.0):
    """The same shape, upside down. Used to prove no sign is hard-coded."""
    return [2 * pivot - c for c in closes]


def brk(direction: str = "up", *, at_minute: int = 20, edge: float = 44500.0,
        low: float = 44450.0, high: float = 44500.0) -> Break:
    return Break(index=4, at=OPEN + timedelta(minutes=at_minute),
                 structure_id="C08", direction=direction, edge=D(str(edge)),
                 low=D(str(low)), high=D(str(high)))


#: Twenty bars of context so ATR — and therefore `tol` — is well defined at the break.
#: They sit **above** the 44,500 edge because that is where a confirmed up-break leaves
#: price: two 5m closes beyond the edge have already happened. Index 20 is the first bar
#: of the aftermath, which is exactly where the observation is allowed to start.
PRE = [44520.0, 44535.0, 44518.0, 44532.0] * 5


def run_up(after, **kw):
    return observe(brk("up"), m1(PRE + after), **kw)


def run_down(after, **kw):
    down = brk("down", edge=45500.0, low=45500.0, high=45550.0)
    return observe(down, m1(flip(PRE) + flip(after)), **kw)


# ─────────────────────────────────────────────────────────────────────────────
# the three cases
# ─────────────────────────────────────────────────────────────────────────────
CONTINUATION = [44560.0, 44610.0, 44660.0, 44720.0, 44790.0] + [44850.0] * 30
HELD = ([44560.0, 44590.0, 44550.0, 44510.0, 44503.0, 44520.0, 44560.0, 44600.0]
        + [44640.0] * 30)
FAILED = [44560.0, 44590.0, 44550.0, 44510.0, 44495.0, 44470.0, 44460.0] + [44455.0] * 30


def test_case_a_direct_continuation_is_no_retest():
    o = run_up(CONTINUATION)
    assert o.outcome == "NO_RETEST"
    assert o.retest_detected is False
    assert o.retest_price is None
    assert o.rebreak_direction == ""
    assert o.extension_pts > 0


def test_case_b_retest_then_rebreak_holds():
    o = run_up(HELD)
    assert o.outcome == "RETEST_HELD"
    assert o.retest_detected is True and o.retest_holds is True
    assert o.retest_fails is False
    assert o.rebreak_direction == "up"
    assert o.resolved_index > o.retest_index
    assert o.bars_to_resolution > o.bars_to_retest


def test_case_c_retest_then_failure():
    o = run_up(FAILED)
    assert o.outcome == "RETEST_FAILED"
    assert o.retest_fails is True and o.retest_holds is False
    assert o.rebreak_direction == "down", "a failed up-break re-enters downward"
    assert o.retest_depth > 0, "price closed back through the edge"


@pytest.mark.parametrize("after,outcome", [(CONTINUATION, "NO_RETEST"),
                                           (HELD, "RETEST_HELD"),
                                           (FAILED, "RETEST_FAILED")])
def test_the_observation_is_symmetric(after, outcome):
    """Same shape, mirrored. If any sign were hard-coded this is where it shows."""
    up, down = run_up(after), run_down(after)
    assert down.outcome == up.outcome == outcome
    assert down.retest_detected == up.retest_detected
    assert down.retest_holds == up.retest_holds
    assert down.retest_fails == up.retest_fails
    if up.retest_detected:
        assert float(down.retest_depth) == pytest.approx(float(up.retest_depth))
        assert float(down.retreat_pts) == pytest.approx(float(up.retreat_pts))


# ─────────────────────────────────────────────────────────────────────────────
# the measurements themselves
# ─────────────────────────────────────────────────────────────────────────────
def test_depth_is_penetration_back_through_the_edge():
    """A retest that only touches the edge from the correct side has zero depth. Depth is
    *how far back inside* price came, not how far it fell."""
    kiss = run_up([44560.0, 44590.0, 44550.0, 44510.0, 44503.0, 44540.0, 44600.0]
                  + [44650.0] * 20)
    assert kiss.retest_detected is True
    assert kiss.retest_depth == 0, "price never traded below 44,500"
    assert kiss.retreat_pts > 0, "but it did give back part of the extension"

    through = run_up(FAILED)
    assert through.retest_depth > 0


def test_the_extension_is_measured_before_the_retest_not_after():
    o = run_up(HELD)
    assert o.extension_index is not None
    assert o.extension_index <= o.retest_index
    # the 44,590 close carries a 44,592 high; the edge is 44,500
    assert float(o.extension_pts) == pytest.approx(92.0)


def test_hold_requires_a_new_extreme_beyond_the_pre_retest_extension():
    """Coming back up to *near* the old high is not a re-break. The bar has to clear it."""
    stalls = run_up([44560.0, 44590.0, 44550.0, 44510.0, 44503.0, 44520.0, 44535.0]
                    + [44540.0] * 40)
    assert stalls.outcome == "RETEST_UNRESOLVED"
    assert stalls.retest_detected is True
    assert stalls.rebreak_direction == ""
    assert stalls.resolved_index is None


def test_failure_uses_the_repos_own_two_close_rule():
    """One close back through the edge is not a failure — the same reason `break_closes`
    is two everywhere else. Two consecutive closes is."""
    one = run_up([44560.0, 44530.0, 44495.0, 44520.0, 44545.0, 44575.0] + [44600.0] * 30)
    assert one.retest_fails is False
    assert one.outcome == "RETEST_HELD"

    two = run_up([44560.0, 44530.0, 44495.0, 44490.0] + [44560.0] * 30)
    assert two.retest_fails is True
    assert two.bars_to_resolution == 3


def test_the_horizon_bounds_the_observation():
    o = run_up(HELD, horizon=3)
    assert o.bars_seen == 3
    assert o.outcome in OUTCOMES
    assert o.resolved_index is None or o.resolved_index < o.start_index + 3


# ─────────────────────────────────────────────────────────────────────────────
# no look-ahead
# ─────────────────────────────────────────────────────────────────────────────
def test_observation_starts_after_the_breaking_candle_closed():
    """The aftermath must not be judged with bars that produced the break."""
    o = run_up(HELD)
    candles = m1(PRE + HELD)
    assert candles[o.start_index].open_time >= o.brk.at
    assert candles[o.start_index - 1].open_time < o.brk.at
    assert o.start_index == 20


def test_a_break_beyond_the_1m_data_returns_nothing():
    late = brk("up", at_minute=9999)
    assert observe(late, m1(PRE + HELD)) is None


# ─────────────────────────────────────────────────────────────────────────────
# lifting breaks off readings — no new detector
# ─────────────────────────────────────────────────────────────────────────────
def readings() -> list[Reading]:
    return [
        Reading(index=0, state="CONFIRMED", interaction="INSIDE"),
        Reading(index=1, state="CONFIRMED", interaction="BREAK_ATTEMPT_UP"),
        Reading(index=2, state="LEAVING", interaction="ACCEPTED_ABOVE",
                left_id="C08", left_edge=D("44500"), left_low=D("44450"),
                left_high=D("44500"), left_kind="cluster"),
        Reading(index=3, state="MOVING", interaction="MOVING"),
        Reading(index=4, state="LEAVING", interaction="ACCEPTED_BELOW",
                left_id="C09", left_edge=D("44300"), left_low=D("44300"),
                left_high=D("44360"), left_kind="cluster"),
        # an acceptance the frontier reported without a structure attached: not a break
        Reading(index=5, state="LEAVING", interaction="ACCEPTED_ABOVE"),
    ]


def test_only_accepted_breaks_with_a_structure_become_breaks():
    m5 = m1([44480.0] * 6)
    got = breaks_from(readings(), m5)
    assert [(b.structure_id, b.direction) for b in got] == [("C08", "up"),
                                                            ("C09", "down")]
    assert got[0].edge == D("44500") and got[0].at == m5[2].close_time


def test_the_break_edge_is_the_structures_own_edge():
    """Lifted straight off the reading. Nothing is re-derived and nothing is re-detected."""
    b = breaks_from(readings(), m1([44480.0] * 6))[0]
    assert b.edge == b.high, "an up-break's edge is the structure's own high"
    b2 = breaks_from(readings(), m1([44480.0] * 6))[1]
    assert b2.edge == b2.low, "a down-break's edge is the structure's own low"


def test_observe_all_and_tally():
    m5 = m1([44480.0] * 6)
    obs = observe_all(readings(), m5, m1(PRE + HELD))
    counts = tally(obs)
    assert sum(counts.values()) == len(obs)
    assert set(counts) == set(OUTCOMES)


def test_a_direction_that_is_not_up_or_down_is_refused():
    with pytest.raises(ValueError):
        Break(index=0, at=OPEN, structure_id="C1", direction="sideways",
              edge=D(1), low=D(1), high=D(2))


# ─────────────────────────────────────────────────────────────────────────────
# still geography
# ─────────────────────────────────────────────────────────────────────────────
def test_the_retest_layer_says_nothing_a_trader_could_execute():
    for after in (CONTINUATION, HELD, FAILED):
        o = run_up(after)
        text = "\n".join(o.lines()) + "\n" + compact(o)
        for word in FORBIDDEN:
            assert word not in text.split(), f"{word!r} in {text!r}"


def test_no_outcome_names_a_trade():
    for word in FORBIDDEN:
        assert not any(word in o for o in OUTCOMES)


def test_an_observation_cannot_both_hold_and_fail():
    o = run_up(HELD)
    with pytest.raises(ValueError):
        type(o)(brk=o.brk, start_index=o.start_index, horizon=o.horizon,
                bars_seen=o.bars_seen, tol=o.tol, retest_holds=True, retest_fails=True)
