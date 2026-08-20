"""Measurement-only quality ledgers for the frozen Dynamic Shadow Trader V1.

The functions in this module consume already-emitted shadow decisions and position
episodes.  They do not participate in the V1 state machine and cannot alter hypothesis,
entry, invalidation, exit, or reversal behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from src.domain.models import ZERO
from src.livemap.shadow import (
    ACTIVE,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    DOWN,
    FALSIFIED,
    HYPOTHESIS_CONFLICT,
    LOWER_ROTATION,
    MIDPOINT_TO_OPPOSITE_EDGE,
    ORIGIN_TO_MIDPOINT,
    OUTSIDE_EDGE_TO_MAPPED_REFERENCE,
    POSITION_ACTIVE,
    POSITION_RISK_EXIT_REASONS,
    UP,
    UPPER_ROTATION,
    DynamicShadowTrader,
    ShadowDecision,
    crossed_invalidation,
)

SUPPORTIVE_BROAD_MIDPOINT = "BROAD_MIDPOINT_REACHED"
SUPPORTIVE_OPPOSITE_EDGE = "OPPOSITE_BROAD_EDGE_REACHED"
SUPPORTIVE_MAPPED_REFERENCE = "NEXT_STRUCTURAL_REFERENCE_REACHED"
SUPPORTIVE_TRANSITION = "SUPPORTIVE_ACCEPTED_STRUCTURAL_TRANSITION"
ADVERSE_TRANSITION = "ADVERSE_ACCEPTED_STRUCTURAL_TRANSITION"

SUPPORTIVE_LANDMARKS = frozenset({
    SUPPORTIVE_BROAD_MIDPOINT,
    SUPPORTIVE_OPPOSITE_EDGE,
    SUPPORTIVE_MAPPED_REFERENCE,
    SUPPORTIVE_TRANSITION,
})

OBJECTIVE_COMPLETION = "OBJECTIVE_COMPLETION"
STRUCTURAL_REORIENTATION_HANDOFF = "STRUCTURAL_REORIENTATION_HANDOFF"
FALSIFICATION_EXIT = "FALSIFICATION"
POSITION_RISK_EXIT = "POSITION_RISK_EXIT"
RESEARCH_BOUNDARY = "RESEARCH_BOUNDARY"
OTHER_EXIT = "OTHER"

WAIT_AVOIDED_FAILED_HYPOTHESIS = "WAIT_AVOIDED_FAILED_HYPOTHESIS"
WAIT_MISSED_SUPPORTIVE_MOVEMENT = "WAIT_MISSED_SUPPORTIVE_MOVEMENT"
WAIT_AT_ALREADY_CONSUMED_MOVEMENT = "WAIT_AT_ALREADY_CONSUMED_MOVEMENT"
WAIT_UNRESOLVED = "WAIT_UNRESOLVED"

STRUCTURALLY_JUSTIFIED_REASSESSMENT = "STRUCTURALLY_JUSTIFIED_REASSESSMENT"
SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION = "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION"
NEW_STRUCTURE_REORIENTATION = "NEW_STRUCTURE_REORIENTATION"
FAILED_RELEASE_REASSESSMENT = "FAILED_RELEASE_REASSESSMENT"
POSSIBLE_SAME_STRUCTURE_CHURN = "POSSIBLE_SAME_STRUCTURE_CHURN"


@dataclass(frozen=True, slots=True)
class MovementProgress:
    index: int
    direction: str | None
    whole_origin: Decimal | None
    whole_destination: Decimal | None
    whole_available_points: Decimal | None
    whole_progress_points: Decimal | None
    whole_progress_atr: float | None
    whole_progress_fraction: float | None
    current_segment: str
    segment_origin: Decimal | None
    segment_destination: Decimal | None
    segment_available_points: Decimal | None
    segment_progress_points: Decimal | None
    segment_progress_atr: float | None
    segment_progress_fraction: float | None


@dataclass(frozen=True, slots=True)
class PositionQualityRecord:
    source_episode_id: str
    hypothesis_id: str
    family: str
    side: str
    structure_id: str
    entry_index: int
    exit_index: int
    movement_origin_index: int | None
    hypothesis_birth_index: int
    hypothesis_active_index: int | None
    bars_origin_to_birth: int | None
    bars_birth_to_active: int | None
    bars_active_to_entry: int | None
    whole_progress_fraction_at_entry: float | None
    segment_progress_fraction_at_entry: float | None
    structural_room_points_at_entry: Decimal
    structural_room_atr_at_entry: float | None
    invalidation_level: Decimal
    invalidation_distance_points_at_entry: Decimal
    invalidation_distance_atr_at_entry: float | None
    room_to_invalidation_ratio: float | None
    supportive_landmarks: tuple[str, ...]
    adverse_landmarks: tuple[str, ...]
    neutral_structural_changes: tuple[str, ...]
    objective_reached: bool
    max_favorable_structural_progress_points: Decimal
    max_favorable_structural_progress_atr: float | None
    max_favorable_structural_progress_fraction: float | None
    raw_directional_progress_points_at_exit: Decimal
    retained_structural_progress_points_at_exit: Decimal
    retained_structural_progress_atr_at_exit: float | None
    retained_structural_progress_fraction_at_exit: float | None
    giveback_from_max_progress_points: Decimal
    giveback_from_max_progress_atr: float | None
    giveback_from_max_progress_fraction: float | None
    first_invalidation_close_cross_index: int | None
    premise_false_at_first_invalidation_cross: bool | None
    first_invalidation_cross_overshoot_points: Decimal | None
    first_invalidation_cross_overshoot_atr: float | None
    entered_already_beyond_invalidation: bool
    position_risk_exit: bool
    position_risk_exit_overshoot_points: Decimal | None
    position_risk_exit_overshoot_atr: float | None
    bars_open_before_position_risk_exit: int | None
    hypothesis_status_at_position_risk_exit: str | None
    falsified: bool
    falsification_overshoot_points: Decimal | None
    falsification_overshoot_atr: float | None
    additional_overshoot_after_first_cross_points: Decimal | None
    additional_overshoot_after_first_cross_atr: float | None
    recovery_after_first_cross_points: Decimal | None
    recovery_after_first_cross_atr: float | None
    exited_on_first_causal_falsification: bool | None
    exit_reason: str
    exit_class: str


@dataclass(frozen=True, slots=True)
class WaitQualityRecord:
    source_episode_id: str
    hypothesis_id: str
    family: str
    structure_id: str
    birth_index: int
    active_index: int
    terminal_index: int
    lifetime_bars: int
    wait_reasons: tuple[str, ...]
    final_status: str
    terminal_reason: str | None
    supportive_landmarks: tuple[str, ...]
    outcome: str


@dataclass(frozen=True, slots=True)
class SideSwitchRecord:
    source_episode_id: str
    previous_family: str
    previous_side: str
    previous_exit_reason: str
    previous_structure_id: str
    exit_index: int
    new_hypothesis_birth_index: int
    new_hypothesis_active_index: int | None
    new_entry_index: int
    flat_candles_between: int
    new_family: str
    new_side: str
    new_structure_id: str
    same_broad_structure: bool
    structural_events: tuple[str, ...]
    category: str


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator <= ZERO:
        return None
    return float(numerator / denominator)


def _atr_ratio(value: Decimal | None, atr: Decimal) -> float | None:
    if value is None or atr <= ZERO:
        return None
    return float(value / atr)


def _directional(origin: Decimal, price: Decimal, side: str) -> Decimal:
    return price - origin if side == UP else origin - price


def movement_progress(decision: ShadowDecision) -> MovementProgress:
    """Expose stable whole-movement and local-segment rulers for one decision."""

    movement = decision.movement
    direction = movement.direction
    origin = movement.origin_price
    whole_destination: Decimal | None = None
    segment_origin: Decimal | None = None
    segment_destination: Decimal | None = None

    if direction is not None and origin is not None:
        if movement.structural_segment == OUTSIDE_EDGE_TO_MAPPED_REFERENCE:
            whole_destination = (
                movement.next_reference.price if movement.next_reference is not None else None)
            segment_origin = origin
            segment_destination = whole_destination
        else:
            whole_destination = (
                movement.broad_high if direction == UP else movement.broad_low)
            if movement.structural_segment == ORIGIN_TO_MIDPOINT:
                segment_origin = origin
                segment_destination = movement.broad_midpoint
            elif movement.structural_segment == MIDPOINT_TO_OPPOSITE_EDGE:
                segment_origin = movement.broad_midpoint
                segment_destination = whole_destination

    whole_available = (
        None if origin is None or whole_destination is None
        else abs(whole_destination - origin))
    whole_progress = (
        None if direction is None or origin is None
        else max(ZERO, _directional(origin, decision.market.price, direction)))
    segment_available = (
        None if segment_origin is None or segment_destination is None
        else abs(segment_destination - segment_origin))
    segment_progress = (
        None if direction is None or segment_origin is None
        else max(ZERO, _directional(segment_origin, decision.market.price, direction)))

    return MovementProgress(
        index=decision.index,
        direction=direction,
        whole_origin=origin,
        whole_destination=whole_destination,
        whole_available_points=whole_available,
        whole_progress_points=whole_progress,
        whole_progress_atr=_atr_ratio(whole_progress, decision.market.atr),
        whole_progress_fraction=_ratio(whole_progress, whole_available),
        current_segment=movement.structural_segment,
        segment_origin=segment_origin,
        segment_destination=segment_destination,
        segment_available_points=segment_available,
        segment_progress_points=segment_progress,
        segment_progress_atr=_atr_ratio(segment_progress, decision.market.atr),
        segment_progress_fraction=_ratio(segment_progress, segment_available),
    )


def _snapshot(decision: ShadowDecision, hypothesis_id: str):
    return next((item for item in decision.hypotheses
                 if item.hypothesis_id == hypothesis_id), None)


def _first_state_index(
        machine: DynamicShadowTrader, hypothesis_id: str, state: str,
        ) -> int | None:
    for decision in machine.decisions:
        snapshot = _snapshot(decision, hypothesis_id)
        if snapshot is not None and snapshot.state == state:
            return decision.index
    return None


def _exit_class(reason: str, falsified: bool) -> str:
    if falsified:
        return FALSIFICATION_EXIT
    if reason in POSITION_RISK_EXIT_REASONS:
        return POSITION_RISK_EXIT
    if reason in {"STRUCTURAL_OBJECTIVE_REACHED", "MAPPED_REFERENCE_REACHED"}:
        return OBJECTIVE_COMPLETION
    if reason in {
            "NEW_CONTROLLING_STRUCTURE_ESTABLISHED",
            "NEW_STRUCTURAL_TRANSITION",
            "CONTROLLING_STRUCTURE_CHANGED",
            }:
        return STRUCTURAL_REORIENTATION_HANDOFF
    if reason == "SOURCE_EPISODE_BOUNDARY":
        return RESEARCH_BOUNDARY
    return OTHER_EXIT


#: One definition of the adverse crossing, shared with the state machine so the
#: measurement and the corrected exit can never drift apart.
_crossed_invalidation = crossed_invalidation


def _overshoot(price: Decimal, level: Decimal, side: str) -> Decimal:
    return max(ZERO, level - price if side == UP else price - level)


def build_position_quality(
        machine: DynamicShadowTrader,
        ) -> tuple[PositionQualityRecord, ...]:
    """Build post-hoc position metrics without feeding anything back to V1."""

    decisions = {item.index: item for item in machine.decisions}
    records = {item.hypothesis_id: item for item in machine.hypothesis_records}
    output: list[PositionQualityRecord] = []
    for episode in machine.position_episodes:
        record = records[episode.hypothesis_id]
        entry = decisions[episode.entry_index]
        exit_decision = decisions[episode.exit_index]
        entry_progress = movement_progress(entry)
        active_index = _first_state_index(machine, episode.hypothesis_id, ACTIVE)
        birth_decision = decisions[record.birth_index]
        movement_origin_index = birth_decision.movement.origin_index
        entry_atr = entry.market.atr

        supportive = set(episode.landmarks_reached) & {
            SUPPORTIVE_BROAD_MIDPOINT,
            SUPPORTIVE_OPPOSITE_EDGE,
            SUPPORTIVE_MAPPED_REFERENCE,
        }
        adverse: set[str] = set()
        neutral: set[str] = set()
        first_cross: int | None = None
        false_at_cross: bool | None = None
        first_cross_overshoot: Decimal | None = None
        for decision in machine.decisions:
            if not episode.entry_index <= decision.index <= episode.exit_index:
                continue
            if first_cross is None and _crossed_invalidation(
                    decision.market.price, record.invalidation.level, episode.side):
                first_cross = decision.index
                first_cross_overshoot = _overshoot(
                    decision.market.price, record.invalidation.level, episode.side)
                snapshot = _snapshot(decision, episode.hypothesis_id)
                false_at_cross = snapshot is not None and snapshot.state == FALSIFIED
            if decision.market.accepted_break:
                if decision.market.accepted_direction == episode.side:
                    supportive.add(SUPPORTIVE_TRANSITION)
                elif decision.market.accepted_direction in {UP, DOWN}:
                    adverse.add(ADVERSE_TRANSITION)

        falsified = episode.hypothesis_falsification_index is not None
        if falsified:
            adverse.add(f"FALSIFYING_{episode.exit_reason}")
        elif episode.exit_reason in {
                "NEW_CONTROLLING_STRUCTURE_ESTABLISHED",
                "NEW_STRUCTURAL_TRANSITION",
                "CONTROLLING_STRUCTURE_CHANGED",
                }:
            neutral.add(episode.exit_reason)

        raw_retained = _directional(
            episode.entry_price, episode.exit_price, episode.side)
        maximum = episode.structural_path_traversed_while_valid
        invalidation_distance = episode.invalidation_distance_at_entry
        room = episode.structural_path_available_at_entry
        retained = min(raw_retained, room)
        giveback = maximum - retained
        overshoot = (
            _overshoot(exit_decision.market.price, record.invalidation.level, episode.side)
            if falsified else None)
        overshoot_change = (
            None if overshoot is None or first_cross_overshoot is None
            else overshoot - first_cross_overshoot)
        additional_overshoot = (
            None if overshoot_change is None else max(overshoot_change, Decimal(0)))
        recovery_after_cross = (
            None if overshoot_change is None else max(-overshoot_change, Decimal(0)))
        objective = episode.exit_reason in {
            "STRUCTURAL_OBJECTIVE_REACHED", "MAPPED_REFERENCE_REACHED"}
        risk_exit = episode.exit_reason in POSITION_RISK_EXIT_REASONS
        risk_overshoot = (
            _overshoot(exit_decision.market.price, record.invalidation.level, episode.side)
            if risk_exit else None)
        risk_status = (
            _snapshot(exit_decision, episode.hypothesis_id).state
            if risk_exit and _snapshot(exit_decision, episode.hypothesis_id) is not None
            else None)

        output.append(PositionQualityRecord(
            source_episode_id=episode.source_episode_id,
            hypothesis_id=episode.hypothesis_id,
            family=episode.family,
            side=episode.side,
            structure_id=record.structure_id,
            entry_index=episode.entry_index,
            exit_index=episode.exit_index,
            movement_origin_index=movement_origin_index,
            hypothesis_birth_index=record.birth_index,
            hypothesis_active_index=active_index,
            bars_origin_to_birth=(
                None if movement_origin_index is None
                else record.birth_index - movement_origin_index),
            bars_birth_to_active=(
                None if active_index is None else active_index - record.birth_index),
            bars_active_to_entry=(
                None if active_index is None else episode.entry_index - active_index),
            whole_progress_fraction_at_entry=entry_progress.whole_progress_fraction,
            segment_progress_fraction_at_entry=entry_progress.segment_progress_fraction,
            structural_room_points_at_entry=room,
            structural_room_atr_at_entry=_atr_ratio(room, entry_atr),
            invalidation_level=record.invalidation.level,
            invalidation_distance_points_at_entry=invalidation_distance,
            invalidation_distance_atr_at_entry=_atr_ratio(
                invalidation_distance, entry_atr),
            room_to_invalidation_ratio=_ratio(room, invalidation_distance),
            supportive_landmarks=tuple(sorted(supportive)),
            adverse_landmarks=tuple(sorted(adverse)),
            neutral_structural_changes=tuple(sorted(neutral)),
            objective_reached=objective,
            max_favorable_structural_progress_points=maximum,
            max_favorable_structural_progress_atr=_atr_ratio(maximum, entry_atr),
            max_favorable_structural_progress_fraction=episode.path_participation_fraction,
            raw_directional_progress_points_at_exit=raw_retained,
            retained_structural_progress_points_at_exit=retained,
            retained_structural_progress_atr_at_exit=_atr_ratio(retained, entry_atr),
            retained_structural_progress_fraction_at_exit=_ratio(retained, room),
            giveback_from_max_progress_points=giveback,
            giveback_from_max_progress_atr=_atr_ratio(giveback, entry_atr),
            giveback_from_max_progress_fraction=_ratio(giveback, room),
            first_invalidation_close_cross_index=first_cross,
            premise_false_at_first_invalidation_cross=false_at_cross,
            first_invalidation_cross_overshoot_points=first_cross_overshoot,
            first_invalidation_cross_overshoot_atr=_atr_ratio(
                first_cross_overshoot, entry_atr),
            entered_already_beyond_invalidation=_crossed_invalidation(
                episode.entry_price, record.invalidation.level, episode.side),
            position_risk_exit=risk_exit,
            position_risk_exit_overshoot_points=risk_overshoot,
            position_risk_exit_overshoot_atr=_atr_ratio(risk_overshoot, entry_atr),
            bars_open_before_position_risk_exit=(
                episode.exit_index - episode.entry_index if risk_exit else None),
            hypothesis_status_at_position_risk_exit=risk_status,
            falsified=falsified,
            falsification_overshoot_points=overshoot,
            falsification_overshoot_atr=_atr_ratio(overshoot, entry_atr),
            additional_overshoot_after_first_cross_points=additional_overshoot,
            additional_overshoot_after_first_cross_atr=_atr_ratio(
                additional_overshoot, entry_atr),
            recovery_after_first_cross_points=recovery_after_cross,
            recovery_after_first_cross_atr=_atr_ratio(
                recovery_after_cross, entry_atr),
            exited_on_first_causal_falsification=episode.exited_on_first_falsification,
            exit_reason=episode.exit_reason,
            exit_class=_exit_class(episode.exit_reason, falsified),
        ))
    return tuple(output)


def build_wait_quality(machine: DynamicShadowTrader) -> tuple[WaitQualityRecord, ...]:
    """Classify ACTIVE directional hypotheses that never received participation."""

    entered = {item.hypothesis_id for item in machine.position_episodes}
    output: list[WaitQualityRecord] = []
    for record in machine.hypothesis_records:
        if record.side is None or ACTIVE not in record.statuses_seen:
            continue
        if record.hypothesis_id in entered:
            continue
        active_index = _first_state_index(machine, record.hypothesis_id, ACTIVE)
        if active_index is None:
            continue
        reasons: set[str] = set()
        for decision in machine.decisions:
            if decision.index < active_index:
                continue
            snapshot = _snapshot(decision, record.hypothesis_id)
            if snapshot is None or snapshot.state != ACTIVE:
                continue
            participation = decision.participation
            if participation.hypothesis_id == record.hypothesis_id:
                reasons.update(participation.reasons)
            elif participation.status == HYPOTHESIS_CONFLICT:
                reasons.add("HYPOTHESIS_CONFLICT")
            elif participation.status == POSITION_ACTIVE:
                reasons.add("EXISTING_SHADOW_POSITION_ACTIVE")
        if not reasons:
            reasons.add("NO_INDIVIDUAL_PARTICIPATION_REASON_EXPOSED")

        supportive = set(record.confirmations) & {
            SUPPORTIVE_BROAD_MIDPOINT,
            SUPPORTIVE_OPPOSITE_EDGE,
            "MAPPED_REFERENCE_REACHED",
        }
        consumed = bool(reasons & {
            "FIRST_STRUCTURAL_SEGMENT_ALREADY_CONSUMED",
            "ALREADY_AT_STRUCTURAL_DECISION_POINT",
        })
        if consumed:
            outcome = WAIT_AT_ALREADY_CONSUMED_MOVEMENT
        elif supportive or record.terminal_reason in {
                "STRUCTURAL_OBJECTIVE_REACHED", "MAPPED_REFERENCE_REACHED"}:
            outcome = WAIT_MISSED_SUPPORTIVE_MOVEMENT
        elif record.state == FALSIFIED:
            outcome = WAIT_AVOIDED_FAILED_HYPOTHESIS
        else:
            outcome = WAIT_UNRESOLVED

        terminal_index = (
            record.terminal_index if record.terminal_index is not None
            else record.last_update_index)
        output.append(WaitQualityRecord(
            source_episode_id=machine.source_episode_id,
            hypothesis_id=record.hypothesis_id,
            family=record.family,
            structure_id=record.structure_id,
            birth_index=record.birth_index,
            active_index=active_index,
            terminal_index=terminal_index,
            lifetime_bars=terminal_index - record.birth_index + 1,
            wait_reasons=tuple(sorted(reasons)),
            final_status=record.state,
            terminal_reason=record.terminal_reason,
            supportive_landmarks=tuple(sorted(supportive)),
            outcome=outcome,
        ))
    return tuple(output)


def classify_side_switch(
        *, same_structure: bool, previous_family: str, previous_exit_reason: str,
        new_family: str, opposite_edge_observed: bool,
        accepted_break_observed: bool, failed_release_observed: bool,
        controlling_structure_changed: bool,
        ) -> str:
    """Classify a side change using only factual structural events."""

    if (previous_family in {CONTINUATION_UP, CONTINUATION_DOWN}
            and (failed_release_observed
                 or previous_exit_reason == "ACCEPTED_RETURN_INSIDE_RELEASED_STRUCTURE")):
        return FAILED_RELEASE_REASSESSMENT
    if not same_structure or controlling_structure_changed:
        return NEW_STRUCTURE_REORIENTATION
    if (new_family in {LOWER_ROTATION, UPPER_ROTATION}
            and opposite_edge_observed):
        return SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION
    if accepted_break_observed or failed_release_observed or opposite_edge_observed:
        return STRUCTURALLY_JUSTIFIED_REASSESSMENT
    return POSSIBLE_SAME_STRUCTURE_CHURN


def build_side_switches(machine: DynamicShadowTrader) -> tuple[SideSwitchRecord, ...]:
    records = {item.hypothesis_id: item for item in machine.hypothesis_records}
    positions = sorted(machine.position_episodes, key=lambda item: item.entry_index)
    output: list[SideSwitchRecord] = []
    for previous, current in pairwise(positions):
        if previous.side == current.side:
            continue
        old_record = records[previous.hypothesis_id]
        new_record = records[current.hypothesis_id]
        active_index = _first_state_index(machine, current.hypothesis_id, ACTIVE)
        between = [
            item for item in machine.decisions
            if previous.exit_index <= item.index <= current.entry_index
        ]
        accepted = any(item.market.accepted_break for item in between)
        failed_release = any(item.market.reentry for item in between)
        broad_ids = {item.market.broad_id for item in between
                     if item.market.broad_id is not None}
        controlling_changed = (
            old_record.structure_id != new_record.structure_id or len(broad_ids) > 1)
        new_birth = next(
            item for item in machine.decisions if item.index == new_record.birth_index)
        expected_edge = "AT_UPPER_EDGE" if previous.side == UP else "AT_LOWER_EDGE"
        opposite_edge = (
            "OPPOSITE_BROAD_EDGE_REACHED" in previous.landmarks_reached
            or new_birth.market.price_location == expected_edge
        )
        same = old_record.structure_id == new_record.structure_id
        events: list[str] = []
        if opposite_edge:
            events.append("OPPOSITE_EDGE")
        if accepted:
            events.append("ACCEPTED_BREAK")
        if failed_release:
            events.append("FAILED_RELEASE_REENTRY")
        if controlling_changed:
            events.append("CONTROLLING_STRUCTURE_CHANGED")
        if new_record.family in {LOWER_ROTATION, UPPER_ROTATION}:
            events.append("INDEPENDENT_ROTATION_PREMISE")
        category = classify_side_switch(
            same_structure=same,
            previous_family=previous.family,
            previous_exit_reason=previous.exit_reason,
            new_family=current.family,
            opposite_edge_observed=opposite_edge,
            accepted_break_observed=accepted,
            failed_release_observed=failed_release,
            controlling_structure_changed=controlling_changed,
        )
        output.append(SideSwitchRecord(
            source_episode_id=machine.source_episode_id,
            previous_family=previous.family,
            previous_side=previous.side,
            previous_exit_reason=previous.exit_reason,
            previous_structure_id=old_record.structure_id,
            exit_index=previous.exit_index,
            new_hypothesis_birth_index=new_record.birth_index,
            new_hypothesis_active_index=active_index,
            new_entry_index=current.entry_index,
            flat_candles_between=max(0, current.entry_index - previous.exit_index - 1),
            new_family=current.family,
            new_side=current.side,
            new_structure_id=new_record.structure_id,
            same_broad_structure=same,
            structural_events=tuple(events),
            category=category,
        ))
    return tuple(output)


def flip_chain_summary(machine: DynamicShadowTrader) -> dict[str, int]:
    """Count maximal alternating position runs without a bar-count churn threshold."""

    records = {item.hypothesis_id: item for item in machine.hypothesis_records}
    positions = sorted(machine.position_episodes, key=lambda item: item.entry_index)
    return summarize_alternating_chains(
        positions,
        build_side_switches(machine),
        {key: value.structure_id for key, value in records.items()},
    )


def summarize_alternating_chains(
        positions, switches: tuple[SideSwitchRecord, ...],
        structures_by_hypothesis: dict[str, str],
        ) -> dict[str, int]:
    """Summarize maximal alternating runs from a factual position/switch ledger."""

    switch_by_pair = {(item.exit_index, item.new_entry_index): item
                      for item in switches}
    runs: list[list] = []
    current: list = []
    for position in positions:
        if not current:
            current = [position]
        elif current[-1].side != position.side:
            current.append(position)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = [position]
    if len(current) >= 2:
        runs.append(current)

    output = {
        "two_position_alternating_chains": 0,
        "three_position_alternating_chains": 0,
        "four_or_more_alternating_chains": 0,
        "chains_same_broad_structure": 0,
        "chains_with_meaningful_events_between_every_side": 0,
    }
    for run in runs:
        if len(run) == 2:
            output["two_position_alternating_chains"] += 1
        elif len(run) == 3:
            output["three_position_alternating_chains"] += 1
        else:
            output["four_or_more_alternating_chains"] += 1
        structure_ids = {structures_by_hypothesis[item.hypothesis_id] for item in run}
        output["chains_same_broad_structure"] += int(len(structure_ids) == 1)
        pairs = pairwise(run)
        meaningful = all(
            switch_by_pair[(left.exit_index, right.entry_index)].category
            != POSSIBLE_SAME_STRUCTURE_CHURN
            for left, right in pairs
        )
        output["chains_with_meaningful_events_between_every_side"] += int(meaningful)
    return output


def active_directional_population(machine: DynamicShadowTrader) -> dict[str, int]:
    records = machine.hypothesis_records
    directional = [item for item in records if item.side is not None]
    active = [item for item in directional if ACTIVE in item.statuses_seen]
    entered = {item.hypothesis_id for item in machine.position_episodes}
    return {
        "total_hypotheses": len(records),
        "directional_hypotheses": len(directional),
        "directional_hypotheses_ever_active": len(active),
        "active_directional_with_participation": sum(
            item.hypothesis_id in entered for item in active),
        "active_directional_without_participation": sum(
            item.hypothesis_id not in entered for item in active),
        "observational_failed_return_contexts": sum(
            item.side is None for item in records),
    }


__all__ = [
    "ADVERSE_TRANSITION",
    "FAILED_RELEASE_REASSESSMENT",
    "FALSIFICATION_EXIT",
    "NEW_STRUCTURE_REORIENTATION",
    "OBJECTIVE_COMPLETION",
    "POSITION_RISK_EXIT",
    "POSSIBLE_SAME_STRUCTURE_CHURN",
    "RESEARCH_BOUNDARY",
    "SAME_STRUCTURE_OPPOSITE_EDGE_ROTATION",
    "STRUCTURALLY_JUSTIFIED_REASSESSMENT",
    "STRUCTURAL_REORIENTATION_HANDOFF",
    "SUPPORTIVE_LANDMARKS",
    "SUPPORTIVE_TRANSITION",
    "WAIT_AT_ALREADY_CONSUMED_MOVEMENT",
    "WAIT_AVOIDED_FAILED_HYPOTHESIS",
    "WAIT_MISSED_SUPPORTIVE_MOVEMENT",
    "WAIT_UNRESOLVED",
    "MovementProgress",
    "PositionQualityRecord",
    "SideSwitchRecord",
    "WaitQualityRecord",
    "active_directional_population",
    "build_position_quality",
    "build_side_switches",
    "build_wait_quality",
    "classify_side_switch",
    "flip_chain_summary",
    "movement_progress",
    "summarize_alternating_chains",
]
