"""Brain V3 — the post-activation rotation confirmation.

Becoming ACTIVE is the premise forming.  It is not the market agreeing with it.  Brain
V3 asks for one later closed candle that still holds the premise inside the controlling
Broad and continues factual directional progress, and asks for nothing else: no candle
size, no distance, no ATR, no percentage, no shape, no Micro.

Every trace here is deterministic and synthetic.  C01 in the shared fixture is 100-110,
tolerance 0.5, ATR 2, midpoint 105.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.livemap.shadow import (
    ACTIVE,
    BRAIN_V1,
    BRAIN_V2,
    BRAIN_V3,
    COMPLETED,
    ENTER_LONG_SHADOW,
    ENTER_SHORT_SHADOW,
    EXIT,
    FLAT,
    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
    LOWER_ROTATION,
    POSITION_INVALIDATION_LEVEL_CROSSED,
    POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS,
    ROTATION_AWAITING_POST_ACTIVATION_CONFIRMATION,
    SHADOW_LONG,
    SHADOW_SHORT,
    STRESSED,
    TEACH,
    UP,
    UPPER_ROTATION,
    WAIT,
    DynamicShadowTrader,
)
from tests.test_dynamic_shadow import hypothesis, ref, release, truth


def run(stream, *, brain: str = BRAIN_V3) -> DynamicShadowTrader:
    machine = DynamicShadowTrader(TEACH, "teach-EP001", brain=brain)
    for item in stream:
        machine.observe_truth(item)
    return machine


def confirmed(decision, family: str) -> bool:
    return POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS in hypothesis(
        decision, family).confirmation_facts


# ─────────────────────────────────────────────────────────────────────────────
# 1. lower rotation — confirmation required before participation
# ─────────────────────────────────────────────────────────────────────────────
def lower_confirmed() -> tuple:
    return (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "102"),
    )


def test_activation_alone_no_longer_buys_a_lower_rotation():
    machine = run(lower_confirmed())
    activation = machine.decisions[1]

    assert hypothesis(activation, LOWER_ROTATION).state == ACTIVE
    assert confirmed(activation, LOWER_ROTATION) is False
    assert activation.action == WAIT
    assert activation.position.state == FLAT
    assert activation.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
    assert ROTATION_AWAITING_POST_ACTIVATION_CONFIRMATION in activation.participation.reasons


def test_the_next_holding_and_progressing_candle_confirms_and_enters_long():
    machine = run(lower_confirmed())
    entered = machine.decisions[2]

    assert confirmed(entered, LOWER_ROTATION) is True
    assert entered.action == ENTER_LONG_SHADOW
    assert entered.position.state == SHADOW_LONG
    assert entered.position.invalidation_level == Decimal(100)
    assert len(machine.position_episodes) == 0        # still open


def test_v2_enters_on_activation_and_v3_enters_one_candle_later():
    stream = lower_confirmed()
    v2 = run(stream, brain=BRAIN_V2)
    v3 = run(stream, brain=BRAIN_V3)

    assert v2.decisions[1].action == ENTER_LONG_SHADOW
    assert v3.decisions[1].action == WAIT
    assert v3.decisions[2].action == ENTER_LONG_SHADOW
    assert v2.decisions[:1] == v3.decisions[:1]


# ─────────────────────────────────────────────────────────────────────────────
# 2. upper rotation, symmetric
# ─────────────────────────────────────────────────────────────────────────────
def test_upper_rotation_confirmation_is_exactly_symmetric():
    machine = run((
        truth(0, "110", location="AT_UPPER_EDGE", approaching_upper=True),
        truth(1, "109"),
        truth(2, "108"),
    ))
    activation, entered = machine.decisions[1], machine.decisions[2]

    assert hypothesis(activation, UPPER_ROTATION).state == ACTIVE
    assert activation.action == WAIT
    assert confirmed(entered, UPPER_ROTATION) is True
    assert entered.action == ENTER_SHORT_SHADOW
    assert entered.position.state == SHADOW_SHORT
    assert entered.position.invalidation_level == Decimal(110)


# ─────────────────────────────────────────────────────────────────────────────
# 3. activation, then failure before any confirmation
# ─────────────────────────────────────────────────────────────────────────────
def test_a_rotation_that_fails_before_confirming_never_takes_a_position():
    machine = run((
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "99", location="BELOW"),
        truth(3, "98", location="BELOW"),
    ))

    assert not machine.position_episodes
    for decision in machine.decisions:
        assert decision.position.state == FLAT
        assert decision.action not in {ENTER_LONG_SHADOW, ENTER_SHORT_SHADOW}
    assert confirmed(machine.decisions[3], LOWER_ROTATION) is False
    assert hypothesis(machine.decisions[3], LOWER_ROTATION).state == STRESSED


# ─────────────────────────────────────────────────────────────────────────────
# 4. activation, then a valid candle that does not progress
# ─────────────────────────────────────────────────────────────────────────────
def test_a_flat_candle_after_activation_confirms_nothing_and_expires_nothing():
    machine = run((
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "101"),
        truth(3, "102"),
    ))
    stalled, entered = machine.decisions[2], machine.decisions[3]

    assert confirmed(stalled, LOWER_ROTATION) is False
    assert stalled.action == WAIT
    assert ROTATION_AWAITING_POST_ACTIVATION_CONFIRMATION in stalled.participation.reasons
    # no timeout is invented: the very next progressing candle still confirms.
    assert confirmed(entered, LOWER_ROTATION) is True
    assert entered.action == ENTER_LONG_SHADOW


def test_a_candle_that_progresses_but_sits_back_at_the_origin_cannot_confirm():
    machine = run((
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "100.2", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(3, "100.4", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(4, "102"),
    ))
    stressed, entered = machine.decisions[3], machine.decisions[4]

    # candle 3 progresses against candle 2, and is still refused: price is back in the
    # origin area, which the existing lifecycle already calls STRESSED.
    assert hypothesis(stressed, LOWER_ROTATION).state == STRESSED
    assert confirmed(stressed, LOWER_ROTATION) is False
    assert stressed.position.state == FLAT
    # the confirmation is the first *eligible* later candle, not the one right after.
    assert hypothesis(entered, LOWER_ROTATION).state == ACTIVE
    assert confirmed(entered, LOWER_ROTATION) is True
    assert entered.action == ENTER_LONG_SHADOW


# ─────────────────────────────────────────────────────────────────────────────
# 5. activation, then the permitted segment is consumed before confirmation
# ─────────────────────────────────────────────────────────────────────────────
def test_a_rotation_whose_segment_is_consumed_before_confirming_never_enters():
    machine = run((
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "106"),
        truth(3, "107"),
    ))

    assert not machine.position_episodes
    for decision in machine.decisions:
        assert decision.position.state == FLAT
    assert confirmed(machine.decisions[3], LOWER_ROTATION) is False
    assert machine.decisions[2].movement.midpoint_crossed is True
    assert "FIRST_STRUCTURAL_SEGMENT_ALREADY_CONSUMED" in (
        machine.decisions[2].participation.reasons)


def test_a_rotation_that_completes_before_confirming_is_not_rescued():
    machine = run((
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "110", location="AT_UPPER_EDGE", approaching_upper=True),
    ))
    completed = machine.decisions[2]

    assert hypothesis(completed, LOWER_ROTATION).state == COMPLETED
    assert confirmed(completed, LOWER_ROTATION) is False
    assert not machine.position_episodes
    assert completed.position.state == FLAT


# ─────────────────────────────────────────────────────────────────────────────
# 6. Brain V2 risk semantics survive intact on a confirmed entry
# ─────────────────────────────────────────────────────────────────────────────
def confirmed_then_crossed() -> tuple:
    return (
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "102"),
        truth(3, "99", location="BELOW"),
    )


def test_the_v2_rotation_risk_exit_is_unchanged_after_a_confirmed_entry():
    machine = run(confirmed_then_crossed())
    crossed = machine.decisions[3]

    assert crossed.position_before == SHADOW_LONG
    assert crossed.action == EXIT
    assert crossed.position.state == FLAT
    assert POSITION_INVALIDATION_LEVEL_CROSSED in crossed.reasons
    episode = machine.position_episodes[0]
    assert episode.exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED
    assert episode.hypothesis_falsification_index is None
    assert hypothesis(crossed, LOWER_ROTATION).state == STRESSED


def test_the_same_hypothesis_still_cannot_reopen_after_a_risk_exit():
    machine = run((*confirmed_then_crossed(), truth(4, "101"), truth(5, "102")))
    exited = machine.position_episodes[0].hypothesis_id

    for decision in machine.decisions[4:]:
        assert hypothesis(decision, LOWER_ROTATION).hypothesis_id == exited
        assert decision.position.state == FLAT
        assert decision.action == WAIT
        assert "PARTICIPATION_CONSUMED_BY_POSITION_RISK_EXIT" in (
            decision.participation.reasons)
    assert machine.risk_consumed_hypotheses == frozenset({exited})
    assert len(machine.position_episodes) == 1


def test_a_risk_exit_still_returns_to_flat_and_never_to_the_opposite_side():
    machine = run((*confirmed_then_crossed(), truth(4, "98", location="BELOW")))

    for decision in machine.decisions[3:]:
        assert decision.position.state != SHADOW_SHORT
    assert all(item.side == UP for item in machine.position_episodes)


def test_accepted_structural_failure_still_owns_hypothesis_falsification():
    machine = run((
        *confirmed_then_crossed(),
        truth(4, "97", broad=False, location="NO_STRUCTURE",
              map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
              accepted="down", left=True, releases=(release("down", edge="100"),),
              below=(ref("down", "90"),)),
    ))
    falsified = machine.decisions[4]
    record = hypothesis(falsified, LOWER_ROTATION)

    assert record.state == "FALSIFIED"
    assert record.terminal_reason == "ACCEPTED_STRUCTURAL_FAILURE"
    assert machine.position_episodes[0].exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED


# ─────────────────────────────────────────────────────────────────────────────
# 7. continuations are frozen
# ─────────────────────────────────────────────────────────────────────────────
def continuation_stream() -> tuple:
    return (
        truth(0, "112", broad=False, location="NO_STRUCTURE",
              map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
              accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)),
        truth(1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
        truth(2, "109", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
        truth(3, "115", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
        truth(4, "120", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)),
    )


def test_continuation_decisions_are_semantically_identical_under_v2_and_v3():
    stream = continuation_stream()
    v2 = run(stream, brain=BRAIN_V2)
    v3 = run(stream, brain=BRAIN_V3)

    assert v2.decisions == v3.decisions
    assert v2.position_episodes == v3.position_episodes


def test_a_continuation_never_receives_the_rotation_confirmation_fact():
    machine = run(continuation_stream())

    for decision in machine.decisions:
        for item in decision.hypotheses:
            if item.family.startswith("OUTSIDE_CONTINUATION"):
                assert POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS not in (
                    item.confirmation_facts)


# ─────────────────────────────────────────────────────────────────────────────
# 8. causality
# ─────────────────────────────────────────────────────────────────────────────
def test_fresh_replay_is_prefix_equal_at_every_cut():
    stream = (*confirmed_then_crossed(), truth(4, "101"), truth(5, "103"))
    full = run(stream).decisions

    for cut in range(len(stream)):
        assert run(stream[:cut + 1]).decisions == full[:cut + 1]


def test_the_confirmation_never_lands_on_the_activation_candle():
    for stream in (lower_confirmed(), confirmed_then_crossed()):
        machine = run(stream)
        for decision in machine.decisions:
            for item in decision.hypotheses:
                if POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS in item.confirmation_facts:
                    record = next(r for r in machine.hypothesis_records
                                  if r.hypothesis_id == item.hypothesis_id)
                    assert record.first_active_index is not None
                    assert decision.index > record.first_active_index


def test_a_confirmed_rotation_uses_no_information_from_later_candles():
    stream = lower_confirmed()
    # the confirming candle sees exactly what a machine stopped at that candle sees
    truncated = run(stream[:3])
    full = run((*stream, truth(3, "108"), truth(4, "109")))

    assert truncated.decisions[2] == full.decisions[2]


def test_the_brain_version_stays_a_closed_identity():
    with pytest.raises(ValueError, match="unknown brain version"):
        DynamicShadowTrader(TEACH, "teach-EP001", brain="BRAIN_V4")
    assert run(lower_confirmed(), brain=BRAIN_V1).decisions[1].action == ENTER_LONG_SHADOW
