"""Brain V3 final historical audit — one extra factual proof before a rotation entry.

The Brain V2 audit (`8e2d85d387843a57`) returned
``Q5_MOVEMENT_PARTICIPATION_QUALITY = NO``.  Bounding the loss did not make rotation
participation worth having, and the evidence pointed at rotation *entry* rather than
rotation exit: rotations joined on the first factual move away from the origin edge.

Brain V3 keeps every Brain V2 rule and adds exactly one: a rotation hypothesis may not
be participated in merely because it first became ACTIVE.  It must additionally show
``POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS`` — one later closed candle that still holds
the premise inside the controlling Broad and continues factual directional progress.

Three frozen fingerprints are verified from the current source tree before any V3 number
is computed:

* ``bf497495e394bb87`` — V1 trading behaviour,
* ``bf54631ee9c200e9`` — the V1 final quality audit,
* ``8e2d85d387843a57`` — the Brain V2 audit.

If any fails to reproduce, this tool refuses to produce a V3 verdict.

## This is the last historical development attempt

The rule is preregistered as "the first later closed candle that satisfies the facts".
No waiting period is searched over, no candle-size, distance, ATR, percentage, shape,
volume or Micro condition exists, and no historical threshold is fitted.  The gates are
the ones the V1 and V2 audits already used — ``_gates`` for Q1/Q2/Q4/Q5/Q6 and the V2
repaired loss rule for Q3 — so this audit cannot grade V3 on a rule invented for V3.

The decisive question this tool exists to answer is not "did entries go down".  It is:
**for the rotations V3 refuses, what did V2 actually get from them?**  That comparison is
reported first and in full, because entry reduction is not automatically good.

No broker, no live execution, no sizing, no score, no confidence, no probability, no
ranking.  HOLDOUT prices are never requested and VALIDATE stays aggregate-only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.learning.split import TEACH, VALIDATE
from src.livemap.shadow import (
    ACTIVE,
    BRAIN_V1,
    BRAIN_V2,
    BRAIN_V3,
    COMPLETED,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    FALSIFIED,
    LOWER_ROTATION,
    POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS,
    ROTATION_FAMILIES,
    UPPER_ROTATION,
)
from tools.dynamic_reactive_trader_brain_v2_study import (
    EXPECTED_V1_QUALITY_FINGERPRINT,
    _bucket_quality_with_positions,
    _brain_delta,
    _loss_gate,
    _replay_universe,
    brain_v2_payload,
)
from tools.dynamic_reactive_trader_quality_study import (
    EXPECTED_V1_FINGERPRINT,
    QUALITY_RATE_NAMES,
    _dist_text,
    _fingerprint,
    _gates,
    _old_gate_reference,
    _repeatability,
    _weakest_family,
    quality_payload,
)
from tools.dynamic_reactive_trader_study import (
    EpisodeReplay,
    StudyConfig,
    _json_default,
    _r2_reference,
)
from tools.live_structure_truth import load_research_episodes

EXPECTED_BRAIN_V2_FINGERPRINT = "8e2d85d387843a57"

SUPPORTIVE_CONFIRMATIONS = frozenset({
    "BROAD_MIDPOINT_REACHED", "OPPOSITE_BROAD_EDGE_REACHED"})

FILTERED_LATER_FALSIFIED = "LATER_FALSIFIED"
FILTERED_LATER_COMPLETED = "LATER_COMPLETED_WITHOUT_ENTRY"
FILTERED_SEGMENT_CONSUMED = "SEGMENT_CONSUMED_WITHOUT_ENTRY"
FILTERED_UNRESOLVED = "UNRESOLVED"


def _distribution(values: Iterable[int | float | Decimal | None]) -> dict:
    numbers = [float(item) for item in values if item is not None]
    if not numbers:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(numbers),
        "min": round(min(numbers), 6),
        "median": round(statistics.median(numbers), 6),
        "mean": round(statistics.fmean(numbers), 6),
        "max": round(max(numbers), 6),
    }


def _fraction(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Compact per-hypothesis facts, extracted before the replays are released.
# ═════════════════════════════════════════════════════════════════════════════
def _hypothesis_facts(
        replays: Sequence[EpisodeReplay], positions: Sequence) -> dict[str, dict]:
    """One flat record per hypothesis, joining its lifecycle with its position if any."""

    by_hypothesis = {item.hypothesis_id: item for item in positions}
    out: dict[str, dict] = {}
    for replay in replays:
        for record in replay.machine.hypothesis_records:
            position = by_hypothesis.get(record.hypothesis_id)
            confirmations = tuple(record.confirmations)
            out[record.hypothesis_id] = {
                "family": record.family,
                "side": record.side,
                "structure_id": record.structure_id,
                "birth_index": record.birth_index,
                "first_active_index": record.first_active_index,
                "ever_active": ACTIVE in record.statuses_seen,
                "final_state": record.state,
                "terminal_reason": record.terminal_reason,
                "rotation_confirmed": (
                    POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS in confirmations),
                "supportive_movement": bool(
                    set(confirmations) & SUPPORTIVE_CONFIRMATIONS),
                "entered": position is not None,
                "entry_index": position.entry_index if position else None,
                "exit_index": position.exit_index if position else None,
                "exit_class": position.exit_class if position else None,
                "exit_reason": position.exit_reason if position else None,
                "bars_active_to_entry": (
                    position.bars_active_to_entry if position else None),
                "supportive_landmarks": (
                    bool(position.supportive_landmarks) if position else None),
                "objective_reached": position.objective_reached if position else None,
                "max_favorable_fraction": (
                    position.max_favorable_structural_progress_fraction
                    if position else None),
                "retained_fraction": (
                    position.retained_structural_progress_fraction_at_exit
                    if position else None),
                "retained_points": (
                    position.retained_structural_progress_points_at_exit
                    if position else None),
                "giveback_fraction": (
                    position.giveback_from_max_progress_fraction if position else None),
                "whole_progress_at_entry": (
                    position.whole_progress_fraction_at_entry if position else None),
                "segment_progress_at_entry": (
                    position.segment_progress_fraction_at_entry if position else None),
                "risk_overshoot_points": (
                    position.position_risk_exit_overshoot_points if position else None),
                "active_bars": (
                    position.exit_index - position.entry_index if position else None),
            }
    return out


def _position_summary(facts: Iterable[dict]) -> dict:
    items = list(facts)
    retained = [item["retained_fraction"] for item in items]
    return {
        "positions": len(items),
        "exit_classes": dict(sorted(Counter(
            item["exit_class"] for item in items if item["exit_class"]).items())),
        "supportive_landmark": sum(bool(item["supportive_landmarks"]) for item in items),
        "objective_reached": sum(bool(item["objective_reached"]) for item in items),
        "max_favorable_fraction": _distribution(
            item["max_favorable_fraction"] for item in items),
        "retained_fraction": _distribution(retained),
        "retained_positive": sum(
            1 for item in items
            if item["retained_points"] is not None and item["retained_points"] > 0),
        "retained_zero": sum(
            1 for item in items
            if item["retained_points"] is not None and item["retained_points"] == 0),
        "retained_negative": sum(
            1 for item in items
            if item["retained_points"] is not None and item["retained_points"] < 0),
        "giveback_fraction": _distribution(item["giveback_fraction"] for item in items),
        "active_bars": _distribution(item["active_bars"] for item in items),
        "bars_active_to_entry": _distribution(
            item["bars_active_to_entry"] for item in items),
        "whole_progress_at_entry": _distribution(
            item["whole_progress_at_entry"] for item in items),
        "segment_progress_at_entry": _distribution(
            item["segment_progress_at_entry"] for item in items),
        "position_risk_overshoot_points": _distribution(
            item["risk_overshoot_points"] for item in items),
    }


def _classify_filtered(fact: dict) -> str:
    """What the refused rotation hypothesis went on to do, from its own lifecycle."""

    if fact["final_state"] == FALSIFIED:
        return FILTERED_LATER_FALSIFIED
    if fact["final_state"] == COMPLETED:
        return FILTERED_LATER_COMPLETED
    if fact["supportive_movement"]:
        return FILTERED_SEGMENT_CONSUMED
    return FILTERED_UNRESOLVED


def _filtered_rotation_ledger(v2_facts: dict, v3_facts: dict) -> dict:
    """The decisive comparison: what V2 got from the rotations V3 refuses.

    Entry reduction on its own says nothing.  Only the outcome of the removed
    participation says whether the extra proof filtered weak entries or missed good
    movement, so both halves are reported: V2's realised positions on the filtered
    hypotheses, and the same hypotheses' later lifecycle under V3.
    """

    v2_entered = {key for key, item in v2_facts.items()
                  if item["family"] in ROTATION_FAMILIES and item["entered"]}
    v3_entered = {key for key, item in v3_facts.items()
                  if item["family"] in ROTATION_FAMILIES and item["entered"]}
    filtered = sorted(v2_entered - v3_entered)
    admitted = sorted(v3_entered - v2_entered)
    common = sorted(v2_entered & v3_entered)

    later = [v3_facts[key] for key in filtered]
    classes = Counter(_classify_filtered(item) for item in later)
    by_family = {}
    for family in (LOWER_ROTATION, UPPER_ROTATION):
        subset = [key for key in filtered if v2_facts[key]["family"] == family]
        by_family[family] = {
            "filtered": len(subset),
            "v2_outcome": _position_summary(v2_facts[key] for key in subset),
            "later_outcomes": dict(sorted(Counter(
                _classify_filtered(v3_facts[key]) for key in subset).items())),
        }
    return {
        "rotation_entries_v2": len(v2_entered),
        "rotation_entries_v3": len(v3_entered),
        "filtered_out_by_v3": len(filtered),
        "newly_admitted_by_v3": len(admitted),
        "entered_under_both": len(common),
        "entered_later_under_v3": sum(
            v3_facts[key]["entry_index"] > v2_facts[key]["entry_index"]
            for key in common),
        "entry_delay_bars": _distribution(
            v3_facts[key]["entry_index"] - v2_facts[key]["entry_index"]
            for key in common),
        "what_v2_got_from_the_filtered_hypotheses": _position_summary(
            v2_facts[key] for key in filtered),
        "what_v2_got_from_the_retained_hypotheses": _position_summary(
            v2_facts[key] for key in common),
        "what_v3_got_from_the_retained_hypotheses": _position_summary(
            v3_facts[key] for key in common),
        "what_v3_got_from_the_newly_admitted": _position_summary(
            v3_facts[key] for key in admitted),
        "filtered_hypothesis_later_outcomes": dict(sorted(classes.items())),
        "filtered_hypotheses_with_supportive_movement_missed": sum(
            item["supportive_movement"] for item in later),
        "filtered_hypotheses_that_never_confirmed": sum(
            not item["rotation_confirmed"] for item in later),
        "by_family": by_family,
    }


def _rotation_confirmation_ledger(facts: dict) -> dict:
    """Every rotation hypothesis that ever became ACTIVE, and what waiting did to it."""

    by_family = {}
    for family in (LOWER_ROTATION, UPPER_ROTATION):
        subset = [item for item in facts.values()
                  if item["family"] == family and item["ever_active"]]
        confirmed = [item for item in subset if item["rotation_confirmed"]]
        unconfirmed = [item for item in subset if not item["rotation_confirmed"]]
        by_family[family] = {
            "active_rotation_hypotheses": len(subset),
            "received_confirmation": len(confirmed),
            "confirmed_and_entered": sum(item["entered"] for item in confirmed),
            "confirmed_but_blocked_by_another_gate": sum(
                not item["entered"] for item in confirmed),
            "never_confirmed": len(unconfirmed),
            "never_confirmed_outcomes": dict(sorted(Counter(
                _classify_filtered(item) for item in unconfirmed).items())),
            "confirmation_bars_after_activation": _distribution(
                item["bars_active_to_entry"] for item in confirmed if item["entered"]),
        }
    total = [item for item in facts.values()
             if item["family"] in ROTATION_FAMILIES and item["ever_active"]]
    confirmed_total = [item for item in total if item["rotation_confirmed"]]
    return {
        "active_rotation_hypotheses": len(total),
        "received_confirmation": len(confirmed_total),
        "confirmation_rate": _fraction(len(confirmed_total), len(total)),
        "confirmed_and_entered": sum(item["entered"] for item in confirmed_total),
        "never_confirmed": len(total) - len(confirmed_total),
        "never_confirmed_outcomes": dict(sorted(Counter(
            _classify_filtered(item) for item in total
            if not item["rotation_confirmed"]).items())),
        "by_family": by_family,
    }


def _rotation_family_quality(facts: dict) -> dict:
    """Lower and upper rotations reported separately, never averaged together."""

    return {
        family: _position_summary(
            item for item in facts.values()
            if item["family"] == family and item["entered"])
        for family in (LOWER_ROTATION, UPPER_ROTATION)
    }


def _continuation_invariance(v2_facts: dict, v3_facts: dict) -> dict:
    """Continuations are frozen. Any difference here is a finding, not a footnote."""

    def entered(facts: dict, family: str) -> set[str]:
        return {key for key, item in facts.items()
                if item["family"] == family and item["entered"]}

    differences: dict[str, dict] = {}
    identical = True
    for family in (CONTINUATION_UP, CONTINUATION_DOWN):
        v2_ids, v3_ids = entered(v2_facts, family), entered(v3_facts, family)
        common = v2_ids & v3_ids
        moved = [key for key in sorted(common)
                 if (v2_facts[key]["entry_index"], v2_facts[key]["exit_index"],
                     v2_facts[key]["exit_reason"])
                 != (v3_facts[key]["entry_index"], v3_facts[key]["exit_index"],
                     v3_facts[key]["exit_reason"])]
        differences[family] = {
            "entries_v2": len(v2_ids),
            "entries_v3": len(v3_ids),
            "entered_only_under_v2": len(v2_ids - v3_ids),
            "entered_only_under_v3": len(v3_ids - v2_ids),
            "entered_under_both": len(common),
            "common_entries_with_a_different_entry_exit_or_reason": len(moved),
            "retained_fraction_v2": _distribution(
                v2_facts[key]["retained_fraction"] for key in sorted(v2_ids)),
            "retained_fraction_v3": _distribution(
                v3_facts[key]["retained_fraction"] for key in sorted(v3_ids)),
            "exit_reasons_v2": dict(sorted(Counter(
                v2_facts[key]["exit_reason"] for key in sorted(v2_ids)
                if v2_facts[key]["exit_reason"]).items())),
            "exit_reasons_v3": dict(sorted(Counter(
                v3_facts[key]["exit_reason"] for key in sorted(v3_ids)
                if v3_facts[key]["exit_reason"]).items())),
        }
        if (v2_ids != v3_ids) or moved:
            identical = False
    return {"identical": identical, "by_family": differences}


def _hypothesis_population_invariance(v2_facts: dict, v3_facts: dict) -> dict:
    """The two brains must see the same market, or the comparison is not a comparison.

    Hypothesis creation and lifecycle read only market facts, never the position, so the
    populations should be identical.  That is asserted rather than assumed, because the
    whole filtered-rotation analysis matches hypotheses by identity across the brains.
    """

    v2_ids, v3_ids = set(v2_facts), set(v3_facts)
    shared = v2_ids & v3_ids
    mismatched = [
        key for key in sorted(shared)
        if (v2_facts[key]["family"], v2_facts[key]["birth_index"],
            v2_facts[key]["final_state"], v2_facts[key]["terminal_reason"],
            v2_facts[key]["first_active_index"])
        != (v3_facts[key]["family"], v3_facts[key]["birth_index"],
            v3_facts[key]["final_state"], v3_facts[key]["terminal_reason"],
            v3_facts[key]["first_active_index"])
    ]
    return {
        "hypotheses_v2": len(v2_ids),
        "hypotheses_v3": len(v3_ids),
        "identity_symmetric_difference": len(v2_ids ^ v3_ids),
        "lifecycle_mismatches": len(mismatched),
        "identical": not (v2_ids ^ v3_ids) and not mismatched,
    }


def _v3_gates(v3_buckets: dict, v2_buckets: dict, v1_buckets: dict) -> dict:
    """The V1/V2 gate definitions, unchanged, applied to Brain V3.

    Q1/Q2/Q4/Q5/Q6 come from the frozen `_gates` used by the V1 quality audit.  Q3 is
    the Brain V2 repaired loss rule, recomputed here on all three brains so its answer
    for V3 can be read next to an answer it already gives for V1 (NO) and V2 (YES).
    Nothing in this function was written for Brain V3.
    """

    gates = _gates(v3_buckets, True)
    loss = _loss_gate(v3_buckets)
    gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"] = {
        "answer": loss["answer"],
        "basis": (
            "every adverse exit — accepted falsification or position risk — measured "
            "beyond its own frozen invalidation level against the distance it risked "
            "at entry, plus first-causal, first-cross and no-reentry integrity"
        ),
        "facts": loss["per_bucket"],
        "same_rule_recomputed_on_v1": _loss_gate(v1_buckets),
        "same_rule_recomputed_on_v2": _loss_gate(v2_buckets),
    }
    ready = (
        gates["Q1_METRICS_SEMANTICALLY_CLEAN"]["answer"] == "YES"
        and gates["Q2_WAIT_BEHAVIOUR_ACCEPTABLE"]["answer"] != "NO"
        and gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]["answer"] != "NO"
        and gates["Q4_SIDE_SWITCHING_IS_STRUCTURALLY_EXPLAINABLE"]["answer"] != "NO"
        and gates["Q5_MOVEMENT_PARTICIPATION_QUALITY"]["answer"] == "YES"
        and gates["Q6_TEACH_VALIDATE_BEHAVIOUR_REPEATABLE"]["answer"] == "YES"
    )
    prior = [gate["answer"] for name, gate in gates.items()
             if name.startswith("Q") and name != "Q7_READY_FOR_PRODUCTION_INTEGRATION"]
    gates["Q7_READY_FOR_PRODUCTION_INTEGRATION"] = {
        "answer": "YES" if ready else ("NO" if "NO" in prior else "INCONCLUSIVE"),
        "basis": (
            "requires reproducible V1 and V2 integrity, clean metrics, no negative "
            "WAIT/loss/switch gate, positive movement quality, and repeatable "
            "qualitative behaviour"
        ),
    }
    return gates


def run_brain_v3_study(config: StudyConfig | None = None) -> dict:
    config = config or StudyConfig()
    episodes, source_population = load_research_episodes()

    v1_replays, skipped = _replay_universe(episodes, config, brain=BRAIN_V1)
    frozen = quality_payload(v1_replays, source_population, skipped, config)
    if frozen["fingerprint"] != EXPECTED_V1_QUALITY_FINGERPRINT:
        raise AssertionError(
            f"frozen V1 quality audit changed: {frozen['fingerprint']} != "
            f"{EXPECTED_V1_QUALITY_FINGERPRINT}")
    v1_buckets = {bucket: _bucket_quality_with_positions(replays)[0]
                  for bucket, replays in v1_replays.items()}
    del v1_replays

    v2_replays, v2_skipped = _replay_universe(episodes, config, brain=BRAIN_V2)
    if v2_skipped != skipped:
        raise AssertionError("the brains did not read the same research universe")
    v2_buckets: dict[str, dict] = {}
    v2_facts: dict[str, dict] = {}
    for bucket, replays in v2_replays.items():
        aggregated, positions = _bucket_quality_with_positions(replays)
        v2_buckets[bucket] = aggregated
        v2_facts[bucket] = _hypothesis_facts(replays, positions)
    v2_payload = brain_v2_payload(
        v1_buckets, v2_buckets, frozen, source_population, skipped, config)
    if v2_payload["fingerprint"] != EXPECTED_BRAIN_V2_FINGERPRINT:
        raise AssertionError(
            f"frozen Brain V2 audit changed: {v2_payload['fingerprint']} != "
            f"{EXPECTED_BRAIN_V2_FINGERPRINT}")
    del v2_replays

    v3_replays, v3_skipped = _replay_universe(episodes, config, brain=BRAIN_V3)
    if v3_skipped != skipped:
        raise AssertionError("the brains did not read the same research universe")
    v3_buckets: dict[str, dict] = {}
    v3_facts: dict[str, dict] = {}
    for bucket, replays in v3_replays.items():
        aggregated, positions = _bucket_quality_with_positions(replays)
        v3_buckets[bucket] = aggregated
        v3_facts[bucket] = _hypothesis_facts(replays, positions)
    del v3_replays

    deterministic = {
        "study": "DYNAMIC_REACTIVE_TRADER_BRAIN_V3_FINAL_AUDIT",
        "brain_under_audit": BRAIN_V3,
        "brain_control": BRAIN_V2,
        "targeted_change": (
            "A_ROTATION_HYPOTHESIS_MAY_NOT_BE_PARTICIPATED_IN_ON_ITS_ACTIVATION_"
            "CANDLE_IT_MUST_FIRST_SHOW_ONE_LATER_CLOSED_CANDLE_THAT_HOLDS_THE_"
            "PREMISE_INSIDE_THE_CONTROLLING_BROAD_AND_CONTINUES_FACTUAL_DIRECTIONAL_"
            "PROGRESS_WITH_NO_OTHER_CONDITION"
        ),
        "final_historical_development_attempt": True,
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "frozen_v1_behaviour_fingerprint_expected": EXPECTED_V1_FINGERPRINT,
        "frozen_v1_behaviour_fingerprint_recomputed": frozen[
            "frozen_v1_fingerprint_recomputed"],
        "frozen_v1_quality_fingerprint_expected": EXPECTED_V1_QUALITY_FINGERPRINT,
        "frozen_v1_quality_fingerprint_recomputed": frozen["fingerprint"],
        "frozen_brain_v2_fingerprint_expected": EXPECTED_BRAIN_V2_FINGERPRINT,
        "frozen_brain_v2_fingerprint_recomputed": v2_payload["fingerprint"],
        "frozen_fingerprints_match": True,
        "buckets": v3_buckets,
        "v2_control_buckets": v2_buckets,
        "brain_v2_vs_v3": {
            bucket: _brain_delta(v2_buckets[bucket], v3_buckets[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        # `_brain_delta` names its arms positionally ("v1" = left, "v2" = right) so the
        # Brain V2 audit it also builds keeps fingerprint 8e2d85d387843a57.  Here the
        # left arm is Brain V2 and the right arm is Brain V3.
        "brain_v2_vs_v3_arm_names": {"v1": BRAIN_V2, "v2": BRAIN_V3},
        "filtered_rotation_ledger": {
            bucket: _filtered_rotation_ledger(v2_facts[bucket], v3_facts[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "rotation_confirmation_ledger": {
            bucket: _rotation_confirmation_ledger(v3_facts[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "rotation_family_quality": {
            bucket: {
                "v2": _rotation_family_quality(v2_facts[bucket]),
                "v3": _rotation_family_quality(v3_facts[bucket]),
            }
            for bucket in (TEACH, VALIDATE)
        },
        "continuation_invariance": {
            bucket: _continuation_invariance(v2_facts[bucket], v3_facts[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "hypothesis_population_invariance": {
            bucket: _hypothesis_population_invariance(
                v2_facts[bucket], v3_facts[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "teach_validate_quality_rates": _repeatability(v3_buckets),
        "weakest_hypothesis_family": _weakest_family(v3_buckets),
        "old_dynamic_architecture_reference": _old_gate_reference(),
        "structural_research_reference": _r2_reference(),
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "broker_or_live_execution": False,
        "parameter_optimization": False,
        "score_confidence_probability_ranking": False,
    }
    deterministic["fingerprint"] = _fingerprint(deterministic)
    deterministic["final_quality_gates"] = _v3_gates(
        v3_buckets, v2_buckets, v1_buckets)
    q5 = deterministic["final_quality_gates"][
        "Q5_MOVEMENT_PARTICIPATION_QUALITY"]["answer"]
    q7 = deterministic["final_quality_gates"][
        "Q7_READY_FOR_PRODUCTION_INTEGRATION"]["answer"]
    negative = sum(
        gate["answer"] == "NO"
        for name, gate in deterministic["final_quality_gates"].items()
        if name.startswith("Q") and name != "Q7_READY_FOR_PRODUCTION_INTEGRATION")
    deterministic["final_historical_verdict"] = (
        "PASS_FOR_PRODUCTION_INTEGRATION" if q7 == "YES"
        else "FAIL_CURRENT_BRAIN" if negative >= 2
        else "ROTATION_PARTICIPATION_REMAINS_UNPROVEN_STOP_HISTORICAL_TUNING"
    )
    deterministic["further_historical_tuning_authorized"] = False
    deterministic["blocking_gates"] = sorted(
        name for name, gate in deterministic["final_quality_gates"].items()
        if name.startswith("Q") and gate["answer"] != "YES"
        and name != "Q7_READY_FOR_PRODUCTION_INTEGRATION"
    ) if q7 != "YES" else []
    deterministic["q5_answer"] = q5
    return deterministic


def render_markdown(payload: dict) -> str:
    gates = payload["final_quality_gates"]
    verdict = payload["final_historical_verdict"]
    lines = [
        "# BRAIN V3 FINAL HISTORICAL VERDICT",
        "",
        f"Verdict: **{verdict}**.",
        "",
        (
            "Brain V3 keeps every Brain V2 rule and adds exactly one: a rotation "
            "hypothesis may not be participated in on its activation candle. It must "
            "first show `POST_ACTIVATION_INSIDE_HOLD_AND_PROGRESS` — one later closed "
            "candle that still holds the premise inside the controlling Broad and "
            "continues factual directional progress. No candle size, distance, ATR, "
            "percentage, shape, volume or Micro condition is involved, and the waiting "
            "period is not searched over."
        ),
        "",
        f"Brain V3 audit fingerprint: `{payload['fingerprint']}`.",
        (
            "Frozen V1 behaviour fingerprint: "
            f"`{payload['frozen_v1_behaviour_fingerprint_recomputed']}` (MATCH)."
        ),
        (
            "Frozen V1 quality fingerprint: "
            f"`{payload['frozen_v1_quality_fingerprint_recomputed']}` (MATCH)."
        ),
        (
            "Frozen Brain V2 fingerprint: "
            f"`{payload['frozen_brain_v2_fingerprint_recomputed']}` (MATCH)."
        ),
        "",
        "This is the last historical development attempt on this research universe.",
        "",
        "## THE DECISIVE COMPARISON",
        "",
        (
            "Entry reduction is not automatically good. The question is what Brain V2 "
            "actually got from the rotations Brain V3 refuses."
        ),
        "",
    ]
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        led = payload["filtered_rotation_ledger"][bucket]
        got = led["what_v2_got_from_the_filtered_hypotheses"]
        lines.extend([
            f"### {label}",
            "",
            (
                f"- Rotation entries: V2 {led['rotation_entries_v2']} -> V3 "
                f"{led['rotation_entries_v3']}. Filtered out by V3 "
                f"**{led['filtered_out_by_v3']}**; newly admitted by V3 "
                f"{led['newly_admitted_by_v3']}; entered under both "
                f"{led['entered_under_both']} (later under V3 "
                f"{led['entered_later_under_v3']}, delay "
                f"{_dist_text(led['entry_delay_bars'])})."
            ),
            (
                f"- What V2 got from the {led['filtered_out_by_v3']} filtered "
                f"hypotheses: exit classes "
                f"`{json.dumps(got['exit_classes'], sort_keys=True)}`; supportive "
                f"landmark {got['supportive_landmark']}/{got['positions']}; objective "
                f"reached {got['objective_reached']}/{got['positions']}; retained "
                f"fraction {_dist_text(got['retained_fraction'])}; retained "
                f"positive/zero/negative {got['retained_positive']}/"
                f"{got['retained_zero']}/{got['retained_negative']}; max favorable "
                f"{_dist_text(got['max_favorable_fraction'])}."
            ),
            (
                "- Those same hypotheses' later lifecycle under V3: "
                f"`{json.dumps(led['filtered_hypothesis_later_outcomes'], sort_keys=True)}`; "
                "supportive movement missed "
                f"{led['filtered_hypotheses_with_supportive_movement_missed']}; never "
                f"confirmed {led['filtered_hypotheses_that_never_confirmed']}."
            ),
            (
                "- What V2 got from the retained hypotheses: retained fraction "
                f"{_dist_text(led['what_v2_got_from_the_retained_hypotheses']['retained_fraction'])}; "
                "what V3 got from the same: "
                f"{_dist_text(led['what_v3_got_from_the_retained_hypotheses']['retained_fraction'])}."
            ),
            "",
        ])
        for family, data in led["by_family"].items():
            summary = data["v2_outcome"]
            lines.append(
                f"- {label} {family}: filtered {data['filtered']}; V2 exit classes "
                f"`{json.dumps(summary['exit_classes'], sort_keys=True)}`; V2 retained "
                f"fraction {_dist_text(summary['retained_fraction'])}; later outcomes "
                f"`{json.dumps(data['later_outcomes'], sort_keys=True)}`.")
        lines.append("")
    lines.extend(["## ENTRY POPULATION", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v2_vs_v3"][bucket]
        # `_brain_delta` labels its two arms "v1"/"v2" by position, not by brain name.
        # Here the left arm is Brain V2 and the right arm is Brain V3; the delta is
        # reused verbatim so the Brain V2 payload it also builds keeps its fingerprint.
        lines.append(
            f"- {label}: closed positions V2 {delta['closed_positions']['v1']} -> V3 "
            f"{delta['closed_positions']['v2']} (change "
            f"{delta['closed_positions']['change']}).")
        lines.append(
            f"- {label} entries by family V2: "
            f"`{json.dumps(delta['entries_by_family']['v1'], sort_keys=True)}`; V3: "
            f"`{json.dumps(delta['entries_by_family']['v2'], sort_keys=True)}`.")
        lines.append(
            f"- {label} active directional population V2: "
            f"`{json.dumps(delta['active_directional_population']['v1'], sort_keys=True)}`; "
            f"V3: `{json.dumps(delta['active_directional_population']['v2'], sort_keys=True)}`.")
    lines.extend(["", "## ROTATION CONFIRMATION LEDGER", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        led = payload["rotation_confirmation_ledger"][bucket]
        lines.append(
            f"- {label}: ACTIVE rotation hypotheses {led['active_rotation_hypotheses']}; "
            f"received confirmation {led['received_confirmation']} (rate "
            f"{led['confirmation_rate']['rate']}); confirmed and entered "
            f"{led['confirmed_and_entered']}; never confirmed {led['never_confirmed']}.")
        lines.append(
            f"- {label} never-confirmed outcomes: "
            f"`{json.dumps(led['never_confirmed_outcomes'], sort_keys=True)}`.")
        for family, data in led["by_family"].items():
            lines.append(
                f"  - {family}: active {data['active_rotation_hypotheses']}; confirmed "
                f"{data['received_confirmation']}; entered "
                f"{data['confirmed_and_entered']}; blocked elsewhere "
                f"{data['confirmed_but_blocked_by_another_gate']}; never confirmed "
                f"{data['never_confirmed']} "
                f"`{json.dumps(data['never_confirmed_outcomes'], sort_keys=True)}`.")
    lines.extend(["", "## ROTATION QUALITY BY FAMILY", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        for family in (LOWER_ROTATION, UPPER_ROTATION):
            for brain in ("v2", "v3"):
                data = payload["rotation_family_quality"][bucket][brain][family]
                lines.append(
                    f"- {label} {family} {brain.upper()}: positions {data['positions']} | "
                    f"supportive {data['supportive_landmark']} | objective "
                    f"{data['objective_reached']} | exit classes "
                    f"`{json.dumps(data['exit_classes'], sort_keys=True)}` | max "
                    f"favorable {_dist_text(data['max_favorable_fraction'])} | retained "
                    f"{_dist_text(data['retained_fraction'])} | retained +/0/- "
                    f"{data['retained_positive']}/{data['retained_zero']}/"
                    f"{data['retained_negative']} | giveback "
                    f"{_dist_text(data['giveback_fraction'])} | active bars "
                    f"{_dist_text(data['active_bars'])} | ACTIVE-to-entry "
                    f"{_dist_text(data['bars_active_to_entry'])} | whole progress at "
                    f"entry {_dist_text(data['whole_progress_at_entry'])} | segment "
                    f"progress at entry {_dist_text(data['segment_progress_at_entry'])} | "
                    f"risk overshoot "
                    f"{_dist_text(data['position_risk_overshoot_points'])}.")
    lines.extend(["", "## CONTINUATION INVARIANCE", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        inv = payload["continuation_invariance"][bucket]
        lines.append(f"- {label}: identical **{inv['identical']}**.")
        # sorted, so a report rendered from the saved JSON is byte-identical to the one
        # rendered in memory: `sort_keys=True` reorders this mapping on the round trip.
        for family, data in sorted(inv["by_family"].items()):
            lines.append(
                f"  - {family}: entries V2 {data['entries_v2']} -> V3 "
                f"{data['entries_v3']}; only-V2 {data['entered_only_under_v2']}; "
                f"only-V3 {data['entered_only_under_v3']}; both "
                f"{data['entered_under_both']}; differing entry/exit/reason "
                f"{data['common_entries_with_a_different_entry_exit_or_reason']}; "
                f"retained V2 {_dist_text(data['retained_fraction_v2'])}; retained V3 "
                f"{_dist_text(data['retained_fraction_v3'])}.")
    lines.extend(["", "## HYPOTHESIS POPULATION INVARIANCE", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        inv = payload["hypothesis_population_invariance"][bucket]
        lines.append(
            f"- {label}: hypotheses V2 {inv['hypotheses_v2']} / V3 "
            f"{inv['hypotheses_v3']}; identity differences "
            f"{inv['identity_symmetric_difference']}; lifecycle mismatches "
            f"{inv['lifecycle_mismatches']}; identical **{inv['identical']}**.")
    lines.extend(["", "## WAIT, SWITCHING, LOSS AND PROGRESS", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v2_vs_v3"][bucket]
        v3_bucket = payload["buckets"][bucket]
        lines.append(
            f"- {label} WAIT outcomes V2 "
            f"`{json.dumps(delta['wait_outcomes']['v1'], sort_keys=True)}`; V3 "
            f"`{json.dumps(delta['wait_outcomes']['v2'], sort_keys=True)}`.")
        lines.append(
            f"- {label} side switches V2 {delta['side_switches']['v1']['count']} -> V3 "
            f"{delta['side_switches']['v2']['count']}; categories V3 "
            f"`{json.dumps(delta['side_switches']['v2']['categories'], sort_keys=True)}`; "
            f"flip chains V3 "
            f"`{json.dumps(delta['side_switches']['v2']['flip_chains'], sort_keys=True)}`.")
        lines.append(
            f"- {label} retained fraction V2 "
            f"{_dist_text(delta['retained_progress_fraction']['v1'])}; V3 "
            f"{_dist_text(delta['retained_progress_fraction']['v2'])}; retained sign V3 "
            f"`{json.dumps(delta['retained_progress_sign']['v2'], sort_keys=True)}`.")
        lines.append(
            f"- {label} max favorable V2 "
            f"{_dist_text(delta['max_favorable_progress_fraction']['v1'])}; V3 "
            f"{_dist_text(delta['max_favorable_progress_fraction']['v2'])}; giveback V3 "
            f"{_dist_text(delta['giveback_fraction']['v2'])}.")
        lines.append(
            f"- {label} supportive landmark positions V2 "
            f"{delta['supportive_landmark_positions']['v1']} -> V3 "
            f"{delta['supportive_landmark_positions']['v2']}; objective completions "
            f"{delta['objective_completions']['v1']} -> "
            f"{delta['objective_completions']['v2']}.")
        risk = v3_bucket["position_risk_quality"]
        reentry = v3_bucket["reentry_integrity"]
        lines.append(
            f"- {label} V3 position risk exits {risk['position_risk_exits']} "
            f"(rotation {risk['rotation_position_risk_exits']}, continuation "
            f"{risk['continuation_position_risk_exits']}); lagged "
            f"{risk['exits_that_lagged_their_first_cross']}; overshoot "
            f"{_dist_text(risk['overshoot_points'])}; reopened by a risk-consumed "
            f"hypothesis **{reentry['positions_reopened_by_a_risk_consumed_hypothesis']}**.")
    lines.extend(["", "## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY", ""])
    for name in QUALITY_RATE_NAMES:
        item = payload["teach_validate_quality_rates"][name]
        lines.append(
            f"- `{name}`: TEACH {item['teach']['numerator']}/"
            f"{item['teach']['denominator']} = {item['teach']['rate']}; VALIDATE "
            f"aggregate {item['validate_aggregate']['numerator']}/"
            f"{item['validate_aggregate']['denominator']} = "
            f"{item['validate_aggregate']['rate']}; absolute difference "
            f"{item['absolute_rate_difference']}.")
    loss = gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]
    lines.extend([
        "",
        "## WEAKEST FAMILY",
        "",
        f"- Result: **{payload['weakest_hypothesis_family']['answer']}**.",
        "",
        "## Q3 CONTROL — THE SAME RULE ON ALL THREE BRAINS",
        "",
        f"- V1: **{loss['same_rule_recomputed_on_v1']['answer']}**.",
        f"- V2: **{loss['same_rule_recomputed_on_v2']['answer']}**.",
        f"- V3: **{loss['answer']}**.",
        f"- V3 facts: `{json.dumps(loss['facts'], sort_keys=True)}`.",
        "",
        "## FINAL QUALITY GATES",
        "",
    ])
    for name, gate in gates.items():
        if name.startswith("Q"):
            lines.append(f"- {name}: **{gate['answer']}**.")
    old = payload["old_dynamic_architecture_reference"]["decision_gates"]
    r2 = payload["structural_research_reference"]
    lines.extend([
        "",
        "## PRESERVED RESEARCH STATUS",
        "",
        *[f"- {name}: **{gate['answer']}**." for name, gate in old.items()],
        f"- R2_CLUSTER: **{r2['R2_CLUSTER']}**.",
        f"- R2_RANGE: **{r2['R2_RANGE']}**.",
        f"- R4_MICRO: **{r2['R4_MICRO']}**.",
        f"- LOCAL_PUBLICATION: **{r2['LOCAL_PUBLICATION']}**.",
        "- This milestone does not promote edge superiority or change those conclusions.",
        "",
        "## INTEGRITY",
        "",
        "- All three frozen fingerprints were reproduced from the current source tree "
        "before any V3 number was computed.",
        "- All brains read one identical set of causal frames per source episode.",
        "- Gate definitions are the ones the V1 and V2 audits already used; none was "
        "written for Brain V3.",
        "- VALIDATE is aggregate-only; no IDs, timestamps, prices, paths, bands, or traces.",
        (
            "- HOLDOUT_PRICE_SESSIONS_CONVERTED = "
            f"{payload['holdout_price_sessions_converted']}."
        ),
        "- No broker, live money, parameter optimization, score, confidence, "
        "probability, or ranking.",
        "",
        "## NEXT DECISION",
        "",
    ])
    if verdict == "PASS_FOR_PRODUCTION_INTEGRATION":
        lines.append(
            "- FREEZE_BRAIN_V3_SEMANTICS_AND_MIGRATE_THEM_INTO_THE_PRODUCTION_PAPER_"
            "SHADOW_COGNITION_PATH_WITHOUT_BROKER_SIZING_OR_LIVE_EXECUTION.")
    else:
        lines.append(
            "- Rotation participation remains unproven on the observed historical "
            "research universe. Blocking gates: "
            f"{', '.join(payload['blocking_gates']) or 'NONE_BUT_A_REQUIRED_GATE_IS_NOT_YES'}.")
        lines.append(
            "- STOP historical tuning. No Brain V4, no second confirmation candle, no "
            "ATR/edge-distance/Micro/reward-risk filter, no best family subset. The "
            "future of rotation participation must be decided by a separately "
            "preregistered forward or research design, not by another pass over this "
            "same already-observed data.")
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict, report: Path, aggregate: Path) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    aggregate.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(payload), encoding="utf-8")
    aggregate.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=REPO_ROOT / "reports" / "DYNAMIC_REACTIVE_TRADER_BRAIN_V3_FINAL_AUDIT.md")
    parser.add_argument(
        "--aggregate", type=Path,
        default=REPO_ROOT / "reports" / "dynamic_reactive_trader_brain_v3_final.json")
    args = parser.parse_args(argv)
    payload = run_brain_v3_study()
    write_outputs(payload, args.report, args.aggregate)
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "verdict": payload["final_historical_verdict"],
        "gates": {name: gate["answer"] for name, gate in payload[
            "final_quality_gates"].items() if name.startswith("Q")},
        "report": str(args.report),
        "aggregate": str(args.aggregate),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
