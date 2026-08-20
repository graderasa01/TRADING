from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.livemap.shadow import (
    ACTIVE,
    COMPLETED,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    DOWN,
    ENTER_LONG_SHADOW,
    ENTER_SHORT_SHADOW,
    EXIT,
    FAILED_UP_RETURN,
    FALSIFIED,
    FLAT,
    HOLD,
    HYPOTHESIS_CONFLICT,
    HYPOTHESIS_VALID_BUT_NO_PARTICIPATION,
    LOWER_ROTATION,
    NOT_ESTABLISHED,
    OBSERVING,
    SHADOW_LONG,
    SHADOW_SHORT,
    TEACH,
    UP,
    UPPER_ROTATION,
    WAIT,
    DynamicShadowTrader,
    MarketTruth,
    MicroFact,
    ReferenceFact,
    ReleaseFact,
    StructuralInvalidation,
    market_truth_from_frame,
)

BASE_AT = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)


def ref(direction: str, price: str, structure_id: str = "R02") -> ReferenceFact:
    edge = "low" if direction == UP else "high"
    return ReferenceFact(
        f"{structure_id}.{edge}", structure_id, "IMMEDIATE", direction, Decimal(price))


def release(direction: str, *, structure_id: str = "C01", edge: str = "110") -> ReleaseFact:
    return ReleaseFact(
        "RL01", "OUTER", direction, structure_id, Decimal(edge),
        Decimal(100), Decimal(110), None, "BEYOND_BROKEN_EDGE")


def truth(
        index: int, price: str, *, broad: bool = True,
        location: str = "INSIDE", approaching_lower: bool = False,
        approaching_upper: bool = False, map_status: str = "WAIT",
        interaction: str = "WAIT", accepted: str | None = None,
        left: bool = False, reentry: bool = False,
        releases: tuple[ReleaseFact, ...] = (),
        above: tuple[ReferenceFact, ...] = (),
        below: tuple[ReferenceFact, ...] = (),
        micro: MicroFact | None = None, source_end: bool = False,
        source_episode_id: str = "teach-EP001", bucket: str = TEACH,
        ) -> MarketTruth:
    return MarketTruth(
        bucket=bucket,
        source_episode_id=source_episode_id,
        source_ordinal=10,
        index=index,
        at=BASE_AT + timedelta(minutes=5 * index),
        price=Decimal(price),
        atr=Decimal(2),
        tolerance=Decimal("0.5"),
        broad_id="C01" if broad else None,
        broad_kind="cluster" if broad else None,
        broad_low=Decimal(100) if broad else None,
        broad_high=Decimal(110) if broad else None,
        price_location=location,
        interaction=interaction,
        map_status=map_status,
        approaching_lower=approaching_lower,
        approaching_upper=approaching_upper,
        left_id="C01" if left else None,
        left_edge=(Decimal(110) if accepted == UP else Decimal(100)) if left else None,
        left_low=Decimal(100) if left else None,
        left_high=Decimal(110) if left else None,
        left_kind="cluster" if left else None,
        accepted_direction=accepted,
        reentry=reentry,
        references_above=above,
        references_below=below,
        releases=releases,
        active_release=releases[0] if releases else None,
        micro=micro or MicroFact(),
        source_end=source_end,
    )


def hypothesis(decision, family: str):
    return next(item for item in decision.hypotheses if item.family == family)


def test_lower_rotation_joins_holds_reaches_landmarks_and_exits_on_completion():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")

    first = machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    entered = machine.observe_truth(truth(1, "101"))
    held = machine.observe_truth(truth(2, "104"))
    midpoint = machine.observe_truth(truth(3, "105"))
    upper = machine.observe_truth(truth(
        4, "109", location="AT_UPPER_EDGE", approaching_upper=True))
    completed = machine.observe_truth(truth(
        5, "110", location="AT_UPPER_EDGE", approaching_upper=True))

    assert hypothesis(first, LOWER_ROTATION).state == OBSERVING
    assert first.action == WAIT and first.position.state == FLAT
    assert entered.action == ENTER_LONG_SHADOW
    assert entered.position.state == SHADOW_LONG
    assert held.action == HOLD
    assert midpoint.movement.midpoint_crossed
    assert upper.action == HOLD
    assert hypothesis(completed, LOWER_ROTATION).state == COMPLETED
    assert completed.action == EXIT and completed.position.state == FLAT
    assert len(machine.position_episodes) == 1
    episode = machine.position_episodes[0]
    assert "BROAD_MIDPOINT_REACHED" in episode.landmarks_reached
    assert episode.exit_reason == "STRUCTURAL_OBJECTIVE_REACHED"
    assert episode.path_participation_fraction == 1.0


def test_failed_lower_rotation_exits_first_and_never_automatically_reverses():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    entered = machine.observe_truth(truth(1, "101"))
    failed = machine.observe_truth(truth(
        2, "98", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True,
        releases=(release(DOWN, edge="100"),), below=(ref(DOWN, "90"),)))

    assert entered.action == ENTER_LONG_SHADOW
    assert hypothesis(failed, LOWER_ROTATION).state == FALSIFIED
    assert failed.action == EXIT
    assert failed.position_before == SHADOW_LONG
    assert failed.position.state == FLAT
    assert hypothesis(failed, CONTINUATION_DOWN).state == ACTIVE
    assert failed.position.state != SHADOW_SHORT
    episode = machine.position_episodes[0]
    assert episode.exited_on_first_falsification is True
    assert episode.hypothesis_falsification_index == failed.index


def test_independent_down_continuation_can_enter_only_on_a_later_candle():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    exit_decision = machine.observe_truth(truth(
        2, "98", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_BELOW", interaction="ACCEPTED_BELOW",
        accepted=DOWN, left=True,
        releases=(release(DOWN, edge="100"),), below=(ref(DOWN, "90"),)))
    later = machine.observe_truth(truth(
        3, "97", broad=False, location="NO_STRUCTURE",
        releases=(), below=(ref(DOWN, "90"),)))

    assert exit_decision.action == EXIT and exit_decision.position.state == FLAT
    assert later.action == ENTER_SHORT_SHADOW
    assert later.position.state == SHADOW_SHORT
    assert later.position.hypothesis_id != exit_decision.position.hypothesis_id


def test_upper_rotation_is_the_symmetric_shadow_lifecycle():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    observed = machine.observe_truth(truth(
        0, "110", location="AT_UPPER_EDGE", approaching_upper=True))
    entered = machine.observe_truth(truth(1, "109"))
    machine.observe_truth(truth(2, "105"))
    completed = machine.observe_truth(truth(
        3, "100", location="AT_LOWER_EDGE", approaching_lower=True))

    assert hypothesis(observed, UPPER_ROTATION).state == OBSERVING
    assert entered.action == ENTER_SHORT_SHADOW
    assert completed.action == EXIT
    assert hypothesis(completed, UPPER_ROTATION).state == COMPLETED


def test_outside_continuation_requires_acceptance_then_later_hold_and_progress():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    accepted = machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    entered = machine.observe_truth(truth(
        1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))
    completed = machine.observe_truth(truth(
        2, "120", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))

    assert hypothesis(accepted, CONTINUATION_UP).state == ACTIVE
    assert accepted.movement.midpoint_crossed is None
    assert accepted.movement.opposite_edge_reached is None
    assert accepted.action == WAIT
    assert accepted.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
    assert entered.action == ENTER_LONG_SHADOW
    assert completed.action == EXIT
    assert hypothesis(completed, CONTINUATION_UP).state == COMPLETED
    episode = machine.position_episodes[0]
    assert "BROAD_MIDPOINT_REACHED" not in episode.landmarks_reached
    assert "OPPOSITE_BROAD_EDGE_REACHED" not in episode.landmarks_reached
    assert "NEXT_STRUCTURAL_REFERENCE_REACHED" in episode.landmarks_reached


def test_failed_continuation_creates_context_but_not_an_automatic_short():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))
    reentered = machine.observe_truth(truth(
        2, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True))

    assert reentered.action == EXIT
    assert reentered.position.state == FLAT
    assert hypothesis(reentered, CONTINUATION_UP).state == FALSIFIED
    failed_context = hypothesis(reentered, FAILED_UP_RETURN)
    assert failed_context.side is None and failed_context.state == OBSERVING
    assert hypothesis(reentered, UPPER_ROTATION).state == OBSERVING


def test_failed_return_context_completes_only_after_independent_opposite_premise():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))
    reentered = machine.observe_truth(truth(
        2, "109", map_status="BREAKOUT_FAILED", interaction="RE_ENTRY",
        location="AT_UPPER_EDGE", approaching_upper=True, reentry=True))
    independent = machine.observe_truth(truth(3, "108"))

    assert hypothesis(reentered, FAILED_UP_RETURN).state == OBSERVING
    assert hypothesis(independent, UPPER_ROTATION).state == ACTIVE
    failed_context = hypothesis(independent, FAILED_UP_RETURN)
    assert failed_context.state == COMPLETED
    assert failed_context.terminal_reason == "INDEPENDENT_OPPOSITE_HYPOTHESIS_ESTABLISHED"


def test_new_controlling_structure_completes_old_outside_continuation():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "112", broad=False, location="NO_STRUCTURE",
        map_status="ACCEPTED_ABOVE", interaction="ACCEPTED_ABOVE",
        accepted=UP, left=True, releases=(release(UP),), above=(ref(UP, "120"),)))
    machine.observe_truth(truth(
        1, "113", broad=False, location="NO_STRUCTURE", above=(ref(UP, "120"),)))
    changed = replace(
        truth(2, "114"),
        broad_id="C02",
        broad_low=Decimal(112),
        broad_high=Decimal(116),
    )
    completed = machine.observe_truth(changed)

    continuation = hypothesis(completed, CONTINUATION_UP)
    assert continuation.state == COMPLETED
    assert continuation.terminal_reason == "NEW_CONTROLLING_STRUCTURE_ESTABLISHED"
    assert completed.action == EXIT and completed.position.state == FLAT


def test_late_rotation_remains_flat_after_midpoint_is_already_crossed():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    late = machine.observe_truth(truth(1, "106"))

    assert hypothesis(late, LOWER_ROTATION).state == ACTIVE
    assert late.movement.midpoint_crossed
    assert late.participation.status == HYPOTHESIS_VALID_BUT_NO_PARTICIPATION
    assert "FIRST_STRUCTURAL_SEGMENT_ALREADY_CONSUMED" in late.participation.reasons
    assert late.action == WAIT and late.position.state == FLAT


def test_incompatible_active_hypotheses_force_wait_without_selection():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    late = machine.observe_truth(truth(1, "106"))
    machine._create_record(
        family=UPPER_ROTATION,
        side=DOWN,
        truth=late.market,
        premise=("SYNTHETIC_INDEPENDENT_UPPER_PREMISE",),
        origin=ReferenceFact("C01.high", "C01", "BROAD_UPPER_EDGE", DOWN, Decimal(110)),
        destination=ReferenceFact("C01.low", "C01", "BROAD_LOWER_EDGE", DOWN, Decimal(100)),
        invalidation=StructuralInvalidation(
            "C01", "accepted structural failure above controlling Broad",
            Decimal(110), UP),
        structure_id="C01",
        state=ACTIVE,
    )
    conflict = machine.observe_truth(truth(2, "106"))

    assert conflict.participation.status == HYPOTHESIS_CONFLICT
    assert conflict.action == WAIT and conflict.position.state == FLAT


def test_micro_confirmation_alone_never_creates_hypothesis_or_position():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    decision = machine.observe_truth(truth(
        0, "105", micro=MicroFact(
            "CONFIRMED", "M01", Decimal(104), Decimal(106), ("MICRO_CREATED",))))

    assert not decision.hypotheses
    assert decision.position.state == FLAT
    assert decision.action != ENTER_LONG_SHADOW
    assert decision.action != ENTER_SHORT_SHADOW


def test_unestablished_movement_does_not_invent_unreached_landmark_facts():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    decision = machine.observe_truth(truth(
        0,
        "105",
        broad=False,
        location="NO_STRUCTURE",
        source_end=True,
    ))

    assert decision.movement.phase == NOT_ESTABLISHED
    assert decision.movement.midpoint_crossed is None
    assert decision.movement.opposite_edge_approached is None
    assert decision.movement.opposite_edge_reached is None


def test_source_end_expires_hypothesis_and_exits_open_shadow_position():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    machine.observe_truth(truth(1, "101"))
    ended = machine.observe_truth(truth(2, "103", source_end=True))

    assert ended.action == EXIT
    assert ended.position.state == FLAT
    assert hypothesis(ended, LOWER_ROTATION).state == "EXPIRED"
    assert machine.position_episodes[0].exit_reason == "SOURCE_EPISODE_BOUNDARY"


def test_emitted_history_is_frozen_and_future_candles_do_not_mutate_it():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    first = machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    frozen_hypothesis = hypothesis(first, LOWER_ROTATION)
    machine.observe_truth(truth(1, "101"))
    machine.observe_truth(truth(2, "105"))

    assert frozen_hypothesis.state == OBSERVING
    assert frozen_hypothesis.confirmation_facts == ()
    with pytest.raises(FrozenInstanceError):
        frozen_hypothesis.state = ACTIVE  # type: ignore[misc]


def test_fresh_world_reconstruction_is_prefix_equal_at_selected_cuts():
    stream = [
        truth(0, "100", location="AT_LOWER_EDGE", approaching_lower=True),
        truth(1, "101"),
        truth(2, "104"),
        truth(3, "105"),
        truth(4, "109", location="AT_UPPER_EDGE", approaching_upper=True),
        truth(5, "110", location="AT_UPPER_EDGE", approaching_upper=True),
    ]
    full_machine = DynamicShadowTrader(TEACH, "teach-EP001")
    full = [full_machine.observe_truth(item) for item in stream]

    for cut in (0, 2, 4):
        fresh = DynamicShadowTrader(TEACH, "teach-EP001")
        prefix = [fresh.observe_truth(item) for item in stream[:cut + 1]]
        assert prefix == full[:cut + 1]


def test_bucket_source_and_monotonic_barriers_are_hard_failures():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(0, "105"))
    with pytest.raises(AssertionError, match="source episode barrier"):
        machine.observe_truth(truth(
            1, "105", source_episode_id="validate-EP001", bucket="validate"))
    with pytest.raises(AssertionError, match="strictly increasing"):
        machine.observe_truth(truth(0, "105"))
    with pytest.raises(ValueError, match="TEACH/VALIDATE"):
        DynamicShadowTrader("holdout", "holdout-EP001")


def test_structural_frame_adapter_copies_facts_without_mutating_frame():
    from src.livemap.frame import observe
    from tests.test_participation import block

    snapshot, frontier = block(0)

    frame = observe(snapshot, frontier)[0]
    before = frame
    converted = market_truth_from_frame(
        frame, bucket=TEACH, source_episode_id="teach-EP001",
        source_ordinal=1, tolerance=Decimal(1))

    assert converted.index == frame.index
    assert converted.price == frame.price
    assert converted.interaction == frame.reading.interaction
    assert converted.micro.state == (
        frame.reading.micro.micro_state if frame.reading.micro is not None else "ABSENT")
    assert frame == before


def test_every_shadow_entry_has_factual_invalidation_and_no_numeric_selection_fields():
    machine = DynamicShadowTrader(TEACH, "teach-EP001")
    machine.observe_truth(truth(
        0, "100", location="AT_LOWER_EDGE", approaching_lower=True))
    entered = machine.observe_truth(truth(1, "101"))

    assert entered.position.invalidation_structure_id == "C01"
    assert entered.position.invalidation_level == Decimal(100)
    field_names = set(entered.participation.__dataclass_fields__)
    assert not field_names.intersection({
        "score", "confidence", "probability", "rank", "weight", "priority"})
