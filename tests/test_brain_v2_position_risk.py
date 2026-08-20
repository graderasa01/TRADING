"""Brain V2 — the targeted rotation position-risk correction.

Every trace here is deterministic and synthetic.  The point of the correction is that
**market hypothesis falsification and open-position risk are two different events**, so
each test states which of the two it is asserting.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from src.livemap.shadow import (
    ACTIVE,
    BRAIN_V1,
    BRAIN_V2,
    CONTINUATION_UP,
    DOWN,
    ENTER_LONG_SHADOW,
    ENTER_SHORT_SHADOW,
    EXIT,
    FALSIFIED,
    FLAT,
    HOLD,
    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
    LOWER_ROTATION,
    PARTICIPATION_CONSUMED_BY_POSITION_RISK,
    POSITION_INVALIDATION_LEVEL_CROSSED,
    SHADOW_LONG,
    SHADOW_SHORT,
    STRESSED,
    TEACH,
    UP,
    UPPER_ROTATION,
    WAIT,
    DynamicShadowTrader,
    crossed_invalidation,
)
from src.livemap.shadow_quality import POSITION_RISK_EXIT, build_position_quality
from tests.test_dynamic_shadow import hypothesis, ref, release, truth

# C01 in the shared fixture is 100-110, tolerance 0.5, ATR 2.
LOWER_EDGE = Decimal(100)
UPPER_EDGE = Decimal(110)


def lower_rotation_crossing() -> tuple:
    """Enter a lower-area rotation long, then close one point below its frozen edge."""

    return (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "99", location="BELOW"),
    )


def upper_rotation_crossing() -> tuple:
    return (
        truth(0, "110", location="AT_UPPER_EDGE", approaching_upper=True),
        truth(1, "109"),
        truth(2, "111", location="ABOVE"),
    )


def run(stream, *, brain: str = BRAIN_V2) -> DynamicShadowTrader:
    machine = DynamicShadowTrader(TEACH, "teach-EP001", brain=brain)
    for item in stream:
        machine.observe_truth(item)
    return machine


# ─────────────────────────────────────────────────────────────────────────────
# the predicate itself
# ─────────────────────────────────────────────────────────────────────────────
def test_the_adverse_crossing_predicate_has_no_invented_tolerance():
    assert crossed_invalidation(Decimal("99.9"), LOWER_EDGE, UP) is True
    assert crossed_invalidation(LOWER_EDGE, LOWER_EDGE, UP) is True
    assert crossed_invalidation(Decimal("100.1"), LOWER_EDGE, UP) is False
    assert crossed_invalidation(Decimal("110.1"), UPPER_EDGE, DOWN) is True
    assert crossed_invalidation(UPPER_EDGE, UPPER_EDGE, DOWN) is True
    assert crossed_invalidation(Decimal("109.9"), UPPER_EDGE, DOWN) is False


# ─────────────────────────────────────────────────────────────────────────────
# 1. lower rotation early risk exit
# ─────────────────────────────────────────────────────────────────────────────
def test_lower_rotation_long_exits_on_the_first_closed_candle_beyond_its_edge():
    machine = run(lower_rotation_crossing())
    entered, crossed = machine.decisions[1], machine.decisions[2]

    assert entered.action == ENTER_LONG_SHADOW
    assert entered.position.invalidation_level == LOWER_EDGE
    assert crossed.position_before == SHADOW_LONG
    assert crossed.action == EXIT
    assert crossed.position.state == FLAT
    assert POSITION_INVALIDATION_LEVEL_CROSSED in crossed.reasons
    assert "OPEN_POSITION_RISK_IS_NOT_HYPOTHESIS_FALSIFICATION" in crossed.reasons

    episode = machine.position_episodes[0]
    assert episode.exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED
    assert episode.exit_index == 2


def test_a_position_risk_exit_does_not_falsify_the_market_hypothesis():
    machine = run(lower_rotation_crossing())
    crossed = machine.decisions[2]
    record = hypothesis(crossed, LOWER_ROTATION)

    assert record.state == STRESSED
    assert record.state != FALSIFIED
    assert record.terminal_reason is None
    assert machine.position_episodes[0].hypothesis_falsification_index is None
    assert machine.position_episodes[0].exited_on_first_falsification is None


def test_the_risk_exit_lands_on_the_first_measured_invalidation_cross():
    machine = run(lower_rotation_crossing())
    quality = build_position_quality(machine)[0]

    assert quality.position_risk_exit is True
    assert quality.exit_class == POSITION_RISK_EXIT
    assert quality.first_invalidation_close_cross_index == quality.exit_index
    assert quality.position_risk_exit_overshoot_points == Decimal(1)
    assert quality.falsified is False
    assert quality.falsification_overshoot_points is None
    assert quality.hypothesis_status_at_position_risk_exit == STRESSED


# ─────────────────────────────────────────────────────────────────────────────
# 2. upper rotation, symmetric
# ─────────────────────────────────────────────────────────────────────────────
def test_upper_rotation_short_exits_symmetrically_without_being_falsified():
    machine = run(upper_rotation_crossing())
    entered, crossed = machine.decisions[1], machine.decisions[2]

    assert entered.action == ENTER_SHORT_SHADOW
    assert entered.position.invalidation_level == UPPER_EDGE
    assert crossed.position_before == SHADOW_SHORT
    assert crossed.action == EXIT
    assert crossed.position.state == FLAT
    assert hypothesis(crossed, UPPER_ROTATION).state == STRESSED
    assert machine.position_episodes[0].exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED


# ─────────────────────────────────────────────────────────────────────────────
# 3. the same hypothesis instance can never reopen a position
# ─────────────────────────────────────────────────────────────────────────────
def test_the_same_hypothesis_cannot_reopen_a_position_after_a_risk_exit():
    stream = (*lower_rotation_crossing(), truth(3, "101"), truth(4, "102"))
    machine = run(stream)
    crossed = machine.decisions[2]
    exited_id = crossed.position_before and machine.position_episodes[0].hypothesis_id

    for decision in machine.decisions[3:]:
        record = hypothesis(decision, LOWER_ROTATION)
        assert record.hypothesis_id == exited_id
        assert record.state == ACTIVE          # the hypothesis recovered ...
        assert decision.action == WAIT         # ... and still cannot participate
        assert decision.position.state == FLAT
        assert decision.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
        assert PARTICIPATION_CONSUMED_BY_POSITION_RISK in decision.participation.reasons

    assert machine.risk_consumed_hypotheses == frozenset({exited_id})
    assert len(machine.position_episodes) == 1


def test_a_recovered_hypothesis_that_completes_still_completes_normally():
    stream = (
        *lower_rotation_crossing(),
        truth(3, "101"),
        truth(4, "110", location="AT_UPPER_EDGE", approaching_upper=True),
    )
    machine = run(stream)
    completed = machine.decisions[4]

    assert hypothesis(completed, LOWER_ROTATION).state == "COMPLETED"
    assert hypothesis(completed, LOWER_ROTATION).terminal_reason == (
        "STRUCTURAL_OBJECTIVE_REACHED")
    assert completed.position.state == FLAT
    assert len(machine.position_episodes) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. a genuinely new hypothesis identity may participate
# ─────────────────────────────────────────────────────────────────────────────
def test_a_new_structural_premise_creates_a_new_identity_that_may_participate():
    later = replace(
        truth(3, "95", location="AT_LOWER_EDGE", approaching_lower=True),
        broad_id="C02", broad_low=Decimal(95), broad_high=Decimal(105))
    inside = replace(truth(4, "97"), broad_id="C02",
                     broad_low=Decimal(95), broad_high=Decimal(105))
    machine = run((*lower_rotation_crossing(), later, inside))

    old = machine.position_episodes[0]
    reoriented = machine.decisions[3]
    entered = machine.decisions[4]
    by_structure = {item.structure_id: item for item in reoriented.hypotheses
                    if item.family == LOWER_ROTATION}

    assert by_structure["C01"].state == FALSIFIED
    assert by_structure["C01"].terminal_reason == "CONTROLLING_STRUCTURE_CHANGED"
    assert by_structure["C02"].state == "OBSERVING"
    assert entered.action == ENTER_LONG_SHADOW
    assert entered.position.hypothesis_id != old.hypothesis_id
    assert entered.position.invalidation_level == Decimal(95)
    assert len(machine.position_episodes) == 1          # the new one is still open


# ─────────────────────────────────────────────────────────────────────────────
# 5. no automatic reversal, and no hypothesis is invented by the exit
# ─────────────────────────────────────────────────────────────────────────────
def test_a_risk_exit_returns_to_flat_and_never_to_the_opposite_side():
    machine = run((*lower_rotation_crossing(), truth(3, "98", location="BELOW")))

    for decision in machine.decisions[2:]:
        assert decision.position.state != SHADOW_SHORT
    assert machine.decisions[2].position.state == FLAT
    assert all(item.side == UP for item in machine.position_episodes)


def test_a_risk_exit_creates_no_new_hypothesis_on_its_own_candle():
    machine = run(lower_rotation_crossing())
    before = {item.hypothesis_id for item in machine.decisions[1].hypotheses}
    after = {item.hypothesis_id for item in machine.decisions[2].hypotheses}

    assert before == after


# ─────────────────────────────────────────────────────────────────────────────
# 6. accepted failure still owns hypothesis falsification
# ─────────────────────────────────────────────────────────────────────────────
def test_accepted_structural_failure_still_falsifies_the_hypothesis_afterwards():
    failure = truth(
        3, "97", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True,
        releases=(release(DOWN, edge="100"),), below=(ref(DOWN, "90"),))
    machine = run((*lower_rotation_crossing(), failure))
    falsified = machine.decisions[3]
    record = hypothesis(falsified, LOWER_ROTATION)

    assert record.state == FALSIFIED
    assert record.terminal_reason == "ACCEPTED_STRUCTURAL_FAILURE"
    assert falsified.action != EXIT                 # the position left two candles ago
    assert len(machine.position_episodes) == 1
    assert machine.position_episodes[0].exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED


# ─────────────────────────────────────────────────────────────────────────────
# 7. continuations are untouched
# ─────────────────────────────────────────────────────────────────────────────
def continuation_crossing() -> tuple:
    """An outside continuation long whose close falls back through the released edge."""

    return (
        truth(0, "112", broad=False, location="NO_STRUCTURE",
              map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
              accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)),
        truth(1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
        truth(2, "109", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
    )


def test_continuation_geometry_is_not_touched_by_the_rotation_risk_rule():
    machine = run(continuation_crossing())
    crossed = machine.decisions[2]
    position = machine.decisions[1].position

    assert crossed_invalidation(
        crossed.market.price, position.invalidation_level, UP) is True
    assert crossed.action == HOLD
    assert crossed.position.state == SHADOW_LONG
    assert hypothesis(crossed, CONTINUATION_UP).state == ACTIVE
    assert not machine.position_episodes


def test_continuation_traces_are_identical_under_both_brains():
    stream = continuation_crossing()

    assert run(stream, brain=BRAIN_V1).decisions == run(stream, brain=BRAIN_V2).decisions


# ─────────────────────────────────────────────────────────────────────────────
# 8. V1 is frozen, and V2 is prefix-equal to it until the corrected candle
# ─────────────────────────────────────────────────────────────────────────────
def test_v1_keeps_holding_through_the_crossing_candle():
    machine = run(lower_rotation_crossing(), brain=BRAIN_V1)

    assert machine.decisions[2].action == HOLD
    assert machine.decisions[2].position.state == SHADOW_LONG
    assert not machine.position_episodes
    assert machine.risk_consumed_hypotheses == frozenset()


def test_v2_is_prefix_equal_to_v1_before_the_corrected_candle():
    stream = lower_rotation_crossing()
    v1 = run(stream, brain=BRAIN_V1)
    v2 = run(stream, brain=BRAIN_V2)

    assert v1.decisions[:2] == v2.decisions[:2]
    assert v1.decisions[2] != v2.decisions[2]


def test_a_rotation_that_never_crosses_behaves_identically_under_both_brains():
    stream = (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "104"),
        truth(3, "105"),
        truth(4, "109", location="AT_UPPER_EDGE", approaching_upper=True),
        truth(5, "110", location="AT_UPPER_EDGE", approaching_upper=True),
    )
    v1 = run(stream, brain=BRAIN_V1)
    v2 = run(stream, brain=BRAIN_V2)

    assert v1.decisions == v2.decisions
    assert v1.position_episodes == v2.position_episodes
    assert v2.position_episodes[0].exit_reason == "STRUCTURAL_OBJECTIVE_REACHED"


# ─────────────────────────────────────────────────────────────────────────────
# 9. fresh-world causality survives the new rule
# ─────────────────────────────────────────────────────────────────────────────
def test_fresh_replay_is_prefix_equal_across_the_risk_exit():
    stream = (*lower_rotation_crossing(), truth(3, "101"), truth(4, "102"))
    full = run(stream).decisions

    for cut in range(len(stream)):
        fresh = run(stream[:cut + 1]).decisions
        assert fresh == full[:cut + 1]


def test_the_brain_version_is_a_closed_identity_not_a_parameter():
    import pytest

    with pytest.raises(ValueError, match="unknown brain version"):
        DynamicShadowTrader(TEACH, "teach-EP001", brain="tuned")
