"""Brain V2 audit — the identical research universe, one corrected rule.

The final V1 quality audit (`bf54631ee9c200e9`) returned
``Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE = NO`` and named exactly one minimum change:
keep ``ACCEPTED_STRUCTURAL_FAILURE`` as the hypothesis falsification event, but return an
open **rotation** shadow position to FLAT on the first closed candle that closes at or
beyond its own frozen Broad invalidation level, with no automatic reversal.

This tool replays the same TEACH/VALIDATE source episodes twice — once with ``BRAIN_V1``
and once with ``BRAIN_V2`` — so the comparison is between two brains reading one
universe, not between two universes.

Two frozen fingerprints are verified before anything else is reported:

* ``bf497495e394bb87`` — V1 trading behaviour,
* ``bf54631ee9c200e9`` — the V1 final quality audit.

If either fails to reproduce, this tool refuses to produce a V2 verdict.

## The Q3 rule used here, stated before the numbers

V1's Q3 measured accepted-falsification overshoot over *falsified* positions.  Under V2 a
rotation leaves before falsification, so that population no longer contains the events
Q3 exists to judge, and reusing it unchanged would hand V2 a free YES.  The repaired rule
keeps V1's structure and repairs only the population:

1. every adverse exit — ``FALSIFICATION`` **or** ``POSITION_RISK_EXIT`` — is counted;
2. each one's overshoot is measured beyond **its own** frozen invalidation level;
3. the gate fails if more than half of them overshoot further than the distance that
   position originally risked at entry;
4. it also fails on any exit that lagged its own first causal trigger, on any position
   risk exit that lagged its own first closed-candle cross, and on any second position
   opened by a hypothesis instance whose participation a risk exit already consumed.

The same rule is recomputed on the V1 buckets and reported.  If it does not still answer
NO for V1, the rule was rigged and the V2 answer means nothing.

No broker, no live execution, no sizing, no score, no confidence, no probability, no
ranking, no threshold search, no parameter optimization.  HOLDOUT prices are never
requested and VALIDATE stays aggregate-only.
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
    BRAIN_V1,
    BRAIN_V2,
    CONTINUATION_DOWN,
    CONTINUATION_UP,
    POSITION_INVALIDATION_LEVEL_CROSSED,
    ROTATION_FAMILIES,
)
from src.livemap.shadow_quality import (
    FALSIFICATION_EXIT,
    POSITION_RISK_EXIT,
    build_position_quality,
)
from tools.dynamic_reactive_trader_quality_study import (
    DIRECTIONAL_FAMILIES,
    EXPECTED_V1_FINGERPRINT,
    QUALITY_RATE_NAMES,
    _dist_text,
    _fingerprint,
    _gates,
    _old_gate_reference,
    _repeatability,
    _weakest_family,
    aggregate_quality,
    quality_payload,
)
from tools.dynamic_reactive_trader_study import (
    EpisodeReplay,
    StudyConfig,
    _json_default,
    _r2_reference,
    build_episode_frames,
    replay_frames,
)
from tools.live_structure_truth import load_research_episodes

EXPECTED_V1_QUALITY_FINGERPRINT = "bf54631ee9c200e9"

ADVERSE_EXIT_CLASSES = frozenset({FALSIFICATION_EXIT, POSITION_RISK_EXIT})


def _distribution(values: Iterable[int | float | Decimal]) -> dict:
    numbers = [float(item) for item in values]
    if not numbers:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(numbers),
        "min": round(min(numbers), 6),
        "median": round(statistics.median(numbers), 6),
        "mean": round(statistics.fmean(numbers), 6),
        "max": round(max(numbers), 6),
    }


def _adverse_overshoot(record) -> Decimal | None:
    """One position's travel beyond its own frozen invalidation level at exit."""

    if record.falsified:
        return record.falsification_overshoot_points
    if record.position_risk_exit:
        return record.position_risk_exit_overshoot_points
    return None


def _adverse_overshoot_atr(record) -> float | None:
    if record.falsified:
        return record.falsification_overshoot_atr
    if record.position_risk_exit:
        return record.position_risk_exit_overshoot_atr
    return None


def _adverse_exit_ledger(positions) -> dict:
    """The population Q3 judges: every exit that ended exposure adversely."""

    adverse = [item for item in positions if item.exit_class in ADVERSE_EXIT_CLASSES]
    measured = [(item, _adverse_overshoot(item)) for item in adverse]
    measured = [(item, value) for item, value in measured if value is not None]
    exceeds = [item for item, value in measured
               if value > item.invalidation_distance_points_at_entry]
    lagged_risk = [
        item for item in positions
        if item.position_risk_exit
        and item.first_invalidation_close_cross_index != item.exit_index
    ]
    by_family = {}
    for family in DIRECTIONAL_FAMILIES:
        subset = [(item, value) for item, value in measured if item.family == family]
        by_family[family] = {
            "adverse_exits": len(subset),
            "overshoot_points": _distribution(value for _, value in subset),
            "overshoot_atr": _distribution(
                _adverse_overshoot_atr(item) for item, _ in subset
                if _adverse_overshoot_atr(item) is not None),
            "overshoot_exceeds_entry_invalidation_distance": sum(
                value > item.invalidation_distance_points_at_entry
                for item, value in subset),
        }
    return {
        "adverse_exits": len(adverse),
        "adverse_exits_with_measured_overshoot": len(measured),
        "falsification_exits": sum(
            item.exit_class == FALSIFICATION_EXIT for item in adverse),
        "position_risk_exits": sum(
            item.exit_class == POSITION_RISK_EXIT for item in adverse),
        "overshoot_points": _distribution(value for _, value in measured),
        "overshoot_atr": _distribution(
            _adverse_overshoot_atr(item) for item, _ in measured
            if _adverse_overshoot_atr(item) is not None),
        "overshoot_exceeds_entry_invalidation_distance": len(exceeds),
        "position_risk_exits_that_lagged_their_first_cross": len(lagged_risk),
        "by_family": by_family,
    }


def _position_risk_ledger(positions) -> dict:
    """Everything factual about the new exit, kept apart from falsification."""

    risk = [item for item in positions if item.position_risk_exit]
    by_family = {}
    for family in DIRECTIONAL_FAMILIES:
        subset = [item for item in risk if item.family == family]
        by_family[family] = {
            "position_risk_exits": len(subset),
            "overshoot_points": _distribution(
                item.position_risk_exit_overshoot_points for item in subset
                if item.position_risk_exit_overshoot_points is not None),
            "overshoot_atr": _distribution(
                item.position_risk_exit_overshoot_atr for item in subset
                if item.position_risk_exit_overshoot_atr is not None),
            "bars_open": _distribution(
                item.bars_open_before_position_risk_exit for item in subset
                if item.bars_open_before_position_risk_exit is not None),
            "overshoot_exceeds_entry_invalidation_distance": sum(
                item.position_risk_exit_overshoot_points is not None
                and item.position_risk_exit_overshoot_points
                > item.invalidation_distance_points_at_entry
                for item in subset),
        }
    return {
        "position_risk_exits": len(risk),
        "rotation_position_risk_exits": sum(
            item.family in ROTATION_FAMILIES for item in risk),
        "continuation_position_risk_exits": sum(
            item.family in {CONTINUATION_UP, CONTINUATION_DOWN} for item in risk),
        "overshoot_points": _distribution(
            item.position_risk_exit_overshoot_points for item in risk
            if item.position_risk_exit_overshoot_points is not None),
        "overshoot_atr": _distribution(
            item.position_risk_exit_overshoot_atr for item in risk
            if item.position_risk_exit_overshoot_atr is not None),
        "bars_open": _distribution(
            item.bars_open_before_position_risk_exit for item in risk
            if item.bars_open_before_position_risk_exit is not None),
        "exits_that_lagged_their_first_cross": sum(
            item.first_invalidation_close_cross_index != item.exit_index
            for item in risk),
        "hypothesis_status_at_exit": dict(sorted(Counter(
            item.hypothesis_status_at_position_risk_exit or "UNKNOWN"
            for item in risk).items())),
        "retained_progress_fraction_at_exit": _distribution(
            item.retained_structural_progress_fraction_at_exit for item in risk
            if item.retained_structural_progress_fraction_at_exit is not None),
        "positions_entered_already_beyond_invalidation": sum(
            item.entered_already_beyond_invalidation for item in positions),
        "by_family": by_family,
    }


def _reentry_integrity(replays: Sequence[EpisodeReplay], positions) -> dict:
    """After a risk exit, the same hypothesis instance must never open again."""

    consumed: set[str] = set()
    reopened = 0
    for replay in replays:
        risk_exit_index: dict[str, int] = {}
        for episode in replay.machine.position_episodes:
            if episode.exit_reason == POSITION_INVALIDATION_LEVEL_CROSSED:
                risk_exit_index[episode.hypothesis_id] = episode.exit_index
        consumed.update(replay.machine.risk_consumed_hypotheses)
        for episode in replay.machine.position_episodes:
            first = risk_exit_index.get(episode.hypothesis_id)
            if first is not None and episode.entry_index > first:
                reopened += 1
        if set(risk_exit_index) - set(replay.machine.risk_consumed_hypotheses):
            raise AssertionError("a risk exit did not consume its own participation")
    counted = Counter(item.hypothesis_id for item in positions)
    return {
        "hypotheses_with_consumed_participation": len(consumed),
        "positions_reopened_by_a_risk_consumed_hypothesis": reopened,
        "hypotheses_that_produced_more_than_one_position": sum(
            value > 1 for value in counted.values()),
    }


def _brain_delta(v1: dict, v2: dict) -> dict:
    """Every V1-vs-V2 number this audit is required to report, side by side."""

    def movement(bucket: dict) -> dict:
        return bucket["supportive_movement_quality"]

    def progress(bucket: dict) -> dict:
        return bucket["progress_quality"]

    def entries(bucket: dict) -> dict:
        return {
            family: bucket["entry_quality"]["by_family"][family]["entries"]
            for family in DIRECTIONAL_FAMILIES
        }

    return {
        "closed_positions": {
            "v1": movement(v1)["entered_positions"],
            "v2": movement(v2)["entered_positions"],
            "change": movement(v2)["entered_positions"] - movement(v1)["entered_positions"],
        },
        "entries_by_family": {"v1": entries(v1), "v2": entries(v2)},
        "exit_classes": {
            "v1": v1["completion_quality"]["exit_classes"],
            "v2": v2["completion_quality"]["exit_classes"],
        },
        "exit_reasons_by_family": {
            "v1": {family: v1["completion_quality"]["by_family"][family]["exit_reasons"]
                   for family in DIRECTIONAL_FAMILIES},
            "v2": {family: v2["completion_quality"]["by_family"][family]["exit_reasons"]
                   for family in DIRECTIONAL_FAMILIES},
        },
        "falsified_positions": {
            "v1": v1["structural_invalidation"]["falsified_positions"],
            "v2": v2["structural_invalidation"]["falsified_positions"],
        },
        "falsification_overshoot_points": {
            "v1": v1["structural_invalidation"]["falsification_overshoot_points"],
            "v2": v2["structural_invalidation"]["falsification_overshoot_points"],
        },
        "supportive_landmark_positions": {
            "v1": movement(v1)["reached_supportive_landmark"],
            "v2": movement(v2)["reached_supportive_landmark"],
        },
        "objective_completions": {
            "v1": movement(v1)["reached_explicit_objective"],
            "v2": movement(v2)["reached_explicit_objective"],
        },
        "max_favorable_progress_fraction": {
            "v1": progress(v1)["max_favorable_structural_progress"]["fraction"],
            "v2": progress(v2)["max_favorable_structural_progress"]["fraction"],
        },
        "retained_progress_fraction": {
            "v1": progress(v1)["retained_structural_progress_at_exit"]["fraction"],
            "v2": progress(v2)["retained_structural_progress_at_exit"]["fraction"],
        },
        "retained_progress_sign": {
            "v1": {
                key: progress(v1)["retained_structural_progress_at_exit"][key]
                for key in ("positive", "zero", "negative")},
            "v2": {
                key: progress(v2)["retained_structural_progress_at_exit"][key]
                for key in ("positive", "zero", "negative")},
        },
        "retained_progress_fraction_by_family": {
            "v1": progress(v1)["retained_structural_progress_at_exit"][
                "fraction_by_family"],
            "v2": progress(v2)["retained_structural_progress_at_exit"][
                "fraction_by_family"],
        },
        "giveback_fraction": {
            "v1": progress(v1)["giveback_from_max_progress"]["fraction"],
            "v2": progress(v2)["giveback_from_max_progress"]["fraction"],
        },
        "wait_outcomes": {
            "v1": v1["wait_quality"]["outcomes"],
            "v2": v2["wait_quality"]["outcomes"],
        },
        "active_directional_population": {
            "v1": {
                key: v1["active_directional_hypothesis_population"][key]
                for key in (
                    "directional_hypotheses",
                    "directional_hypotheses_ever_active",
                    "active_directional_with_participation",
                    "active_directional_without_participation",
                    "observational_failed_return_contexts")},
            "v2": {
                key: v2["active_directional_hypothesis_population"][key]
                for key in (
                    "directional_hypotheses",
                    "directional_hypotheses_ever_active",
                    "active_directional_with_participation",
                    "active_directional_without_participation",
                    "observational_failed_return_contexts")},
        },
        "side_switches": {
            "v1": {
                "count": v1["side_switch_quality"]["side_switches"],
                "categories": v1["side_switch_quality"]["categories"],
                "flip_chains": v1["side_switch_quality"]["flip_chains"],
                "flat_candles_between": v1["side_switch_quality"]["flat_candles_between"],
            },
            "v2": {
                "count": v2["side_switch_quality"]["side_switches"],
                "categories": v2["side_switch_quality"]["categories"],
                "flip_chains": v2["side_switch_quality"]["flip_chains"],
                "flat_candles_between": v2["side_switch_quality"]["flat_candles_between"],
            },
        },
        "continuation_risk_geometry": {
            "v1": v1["continuation_risk_geometry"],
            "v2": v2["continuation_risk_geometry"],
        },
    }


def _loss_gate(buckets: dict[str, dict]) -> dict:
    """The repaired Q3, applied identically to whichever brain is passed in."""

    facts = {}
    verdicts = []
    for name, bucket in buckets.items():
        adverse = bucket["adverse_exit_ledger"]
        risk = bucket["position_risk_quality"]
        reentry = bucket["reentry_integrity"]
        invalidation = bucket["structural_invalidation"]
        total = adverse["adverse_exits_with_measured_overshoot"]
        exceeds = adverse["overshoot_exceeds_entry_invalidation_distance"]
        integrity_broken = (
            invalidation["first_causal_exit_violations"] > 0
            or adverse["position_risk_exits_that_lagged_their_first_cross"] > 0
            or reentry["positions_reopened_by_a_risk_consumed_hypothesis"] > 0
        )
        facts[name] = {
            "adverse_exits_with_measured_overshoot": total,
            "overshoot_exceeds_entry_invalidation_distance": exceeds,
            "half_of_adverse_exits": total / 2 if total else 0,
            "first_causal_exit_violations": invalidation["first_causal_exit_violations"],
            "position_risk_exits_that_lagged_their_first_cross": adverse[
                "position_risk_exits_that_lagged_their_first_cross"],
            "positions_reopened_by_a_risk_consumed_hypothesis": reentry[
                "positions_reopened_by_a_risk_consumed_hypothesis"],
            "position_risk_exits": risk["position_risk_exits"],
            "integrity_broken": integrity_broken,
        }
        if integrity_broken or (total and exceeds > total / 2):
            verdicts.append("NO")
        elif total and exceeds <= total / 2:
            verdicts.append("YES")
        else:
            verdicts.append("INCONCLUSIVE")
    answer = (
        "NO" if "NO" in verdicts
        else "YES" if all(item == "YES" for item in verdicts)
        else "INCONCLUSIVE"
    )
    return {"answer": answer, "per_bucket": facts}


def _v2_gates(buckets: dict[str, dict], v1_buckets: dict[str, dict]) -> dict:
    gates = _gates(buckets, True)
    loss = _loss_gate(buckets)
    control = _loss_gate(v1_buckets)
    gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"] = {
        "answer": loss["answer"],
        "basis": (
            "every adverse exit — accepted falsification or position risk — measured "
            "beyond its own frozen invalidation level against the distance it risked "
            "at entry, plus first-causal, first-cross and no-reentry integrity"
        ),
        "facts": loss["per_bucket"],
        "same_rule_recomputed_on_v1": {
            "answer": control["answer"],
            "per_bucket": control["per_bucket"],
            "meaning": (
                "the repaired rule must still answer NO for V1; if it does not, the "
                "rule was rigged and the V2 answer is worthless"
            ),
        },
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
            "requires reproducible V1 integrity, clean metrics, no negative WAIT/loss/"
            "switch gate, positive movement quality, and repeatable qualitative behaviour"
        ),
    }
    return gates


def _bucket_quality_with_positions(
        replays: Sequence[EpisodeReplay]) -> tuple[dict, list]:
    """Aggregate one bucket and hand back the position records it already built.

    Building the position ledger is the expensive half of this analysis, so a caller
    that also needs the records reuses these rather than rebuilding them.
    """

    bucket = aggregate_quality(replays)
    positions = [item for replay in replays
                 for item in build_position_quality(replay.machine)]
    bucket["position_risk_quality"] = _position_risk_ledger(positions)
    bucket["adverse_exit_ledger"] = _adverse_exit_ledger(positions)
    bucket["reentry_integrity"] = _reentry_integrity(replays, positions)
    return bucket, positions


def _bucket_quality(replays: Sequence[EpisodeReplay]) -> dict:
    return _bucket_quality_with_positions(replays)[0]


def _replay_universe(
        episodes: dict, config: StudyConfig, *, brain: str,
        ) -> tuple[dict[str, list[EpisodeReplay]], Counter]:
    """One full pass over the research universe with exactly one brain.

    The frames of each source episode are built, read once and released before the next
    episode starts.  Two sequential passes cost one extra frame build and keep only one
    brain's decision history alive at a time; holding both would multiply the largest
    object in this study — the per-candle hypothesis snapshots — by two.
    """

    replays: dict[str, list[EpisodeReplay]] = {TEACH: [], VALIDATE: []}
    skipped = Counter()
    for bucket in (TEACH, VALIDATE):
        for episode in episodes[bucket]:
            prepared = build_episode_frames(episode, config)
            if prepared is None:
                skipped[bucket] += 1
                continue
            replays[bucket].append(replay_frames(prepared, brain=brain))
            del prepared
    return replays, skipped


def run_brain_v2_study(config: StudyConfig | None = None) -> dict:
    config = config or StudyConfig()
    episodes, source_population = load_research_episodes()

    v1_replays, skipped = _replay_universe(episodes, config, brain=BRAIN_V1)
    frozen = quality_payload(v1_replays, source_population, skipped, config)
    if frozen["fingerprint"] != EXPECTED_V1_QUALITY_FINGERPRINT:
        raise AssertionError(
            f"frozen V1 quality audit changed: {frozen['fingerprint']} != "
            f"{EXPECTED_V1_QUALITY_FINGERPRINT}")
    v1_buckets = {bucket: _bucket_quality(replays)
                  for bucket, replays in v1_replays.items()}
    del v1_replays

    v2_replays, v2_skipped = _replay_universe(episodes, config, brain=BRAIN_V2)
    if v2_skipped != skipped:
        raise AssertionError("the two brains did not read the same research universe")
    v2_buckets = {bucket: _bucket_quality(replays)
                  for bucket, replays in v2_replays.items()}
    del v2_replays

    return brain_v2_payload(
        v1_buckets, v2_buckets, frozen, source_population, skipped, config)


def brain_v2_payload(
        v1_buckets: dict[str, dict], v2_buckets: dict[str, dict], frozen: dict,
        source_population: dict, skipped: Counter, config: StudyConfig,
        ) -> dict:
    """Build the Brain V2 audit payload from already-aggregated buckets.

    Extracted so a later brain can reproduce fingerprint ``8e2d85d387843a57`` from the
    same code that produced it, rather than from a second copy of the same dictionary.
    """

    deterministic = {
        "study": "DYNAMIC_REACTIVE_TRADER_BRAIN_V2_AUDIT",
        "brain_under_audit": BRAIN_V2,
        "brain_control": BRAIN_V1,
        "targeted_change": (
            "KEEP_ACCEPTED_FAILURE_AS_HYPOTHESIS_FALSIFICATION_BUT_EXIT_AN_OPEN_"
            "ROTATION_SHADOW_POSITION_TO_FLAT_ON_THE_FIRST_CLOSED_CANDLE_CROSS_"
            "OF_ITS_FROZEN_BROAD_INVALIDATION_LEVEL_WITH_NO_AUTOMATIC_REVERSAL"
        ),
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "frozen_v1_behaviour_fingerprint_expected": EXPECTED_V1_FINGERPRINT,
        "frozen_v1_behaviour_fingerprint_recomputed": frozen[
            "frozen_v1_fingerprint_recomputed"],
        "frozen_v1_quality_fingerprint_expected": EXPECTED_V1_QUALITY_FINGERPRINT,
        "frozen_v1_quality_fingerprint_recomputed": frozen["fingerprint"],
        "frozen_v1_fingerprints_match": True,
        "buckets": v2_buckets,
        "v1_control_buckets": v1_buckets,
        "brain_v1_vs_v2": {
            bucket: _brain_delta(v1_buckets[bucket], v2_buckets[bucket])
            for bucket in (TEACH, VALIDATE)
        },
        "teach_validate_quality_rates": _repeatability(v2_buckets),
        "weakest_hypothesis_family": _weakest_family(v2_buckets),
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
    deterministic["final_quality_gates"] = _v2_gates(v2_buckets, v1_buckets)
    q7 = deterministic["final_quality_gates"][
        "Q7_READY_FOR_PRODUCTION_INTEGRATION"]["answer"]
    negative = sum(
        gate["answer"] == "NO"
        for name, gate in deterministic["final_quality_gates"].items()
        if name.startswith("Q") and name != "Q7_READY_FOR_PRODUCTION_INTEGRATION")
    deterministic["final_pre_production_verdict"] = (
        "PASS_FOR_PRODUCTION_INTEGRATION" if q7 == "YES"
        else "FAIL_CURRENT_BRAIN" if negative >= 2
        else "HOLD_FOR_TARGETED_BRAIN_FIX"
    )
    return deterministic


def render_markdown(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    gates = payload["final_quality_gates"]
    verdict = payload["final_pre_production_verdict"]
    lines = [
        "# BRAIN V2 PRE-PRODUCTION QUALITY VERDICT",
        "",
        f"Verdict: **{verdict}**.",
        "",
        (
            "Brain V2 keeps every V1 rule and adds exactly one: an open ROTATION shadow "
            "position returns to FLAT on the first closed candle that closes at or beyond "
            "its own frozen Broad invalidation level. The market hypothesis is not "
            "falsified by that exit, participation for that hypothesis instance is "
            "consumed, and no reversal is created. Continuations are untouched."
        ),
        "",
        f"Brain V2 audit fingerprint: `{payload['fingerprint']}`.",
        (
            "Frozen V1 behaviour fingerprint: "
            f"`{payload['frozen_v1_behaviour_fingerprint_recomputed']}` (MATCH)."
        ),
        (
            "Frozen V1 quality fingerprint: "
            f"`{payload['frozen_v1_quality_fingerprint_recomputed']}` (MATCH)."
        ),
        "Trader logic changed: **YES — one preregistered rotation position-risk rule**.",
        "",
        "## WHAT CHANGED, IN ONE PARAGRAPH",
        "",
        (
            "V1 kept an open position alive until its hypothesis received an accepted "
            "structural failure, so the market could cross the position's own frozen "
            "boundary and the position kept waiting. V2 separates the two events: "
            "`ACCEPTED_STRUCTURAL_FAILURE` still owns hypothesis falsification, and the "
            "new `POSITION_INVALIDATION_LEVEL_CROSSED` owns open-position risk."
        ),
        "",
        "## POSITION POPULATION",
        "",
    ]
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        lines.append(
            f"- {label}: closed positions V1 {delta['closed_positions']['v1']} -> V2 "
            f"{delta['closed_positions']['v2']} (change "
            f"{delta['closed_positions']['change']}).")
        lines.append(
            f"- {label} entries by family V1: "
            f"`{json.dumps(delta['entries_by_family']['v1'], sort_keys=True)}`.")
        lines.append(
            f"- {label} entries by family V2: "
            f"`{json.dumps(delta['entries_by_family']['v2'], sort_keys=True)}`.")
        lines.append(
            f"- {label} active directional population V1: "
            f"`{json.dumps(delta['active_directional_population']['v1'], sort_keys=True)}`; "
            f"V2: `{json.dumps(delta['active_directional_population']['v2'], sort_keys=True)}`.")
    lines.extend(["", "## ROTATION POSITION RISK EXITS", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        risk = bucket["position_risk_quality"]
        lines.append(
            f"- {label}: position risk exits {risk['position_risk_exits']} "
            f"(rotation {risk['rotation_position_risk_exits']}, continuation "
            f"{risk['continuation_position_risk_exits']}); exits that lagged their first "
            f"closed-candle cross {risk['exits_that_lagged_their_first_cross']}.")
        lines.append(
            f"- {label}: position exit overshoot points "
            f"{_dist_text(risk['overshoot_points'])}; ATR "
            f"{_dist_text(risk['overshoot_atr'])}; bars open "
            f"{_dist_text(risk['bars_open'])}.")
        lines.append(
            f"- {label}: hypothesis status at the risk exit "
            f"`{json.dumps(risk['hypothesis_status_at_exit'], sort_keys=True)}`.")
        lines.append(
            f"- {label}: positions already beyond their frozen invalidation at entry "
            f"{risk['positions_entered_already_beyond_invalidation']}.")
        lines.append(
            f"- {label} by family: `{json.dumps({family: {'position_risk_exits': data['position_risk_exits'], 'overshoot_points': data['overshoot_points'], 'overshoot_exceeds_entry_invalidation_distance': data['overshoot_exceeds_entry_invalidation_distance']} for family, data in risk['by_family'].items()}, sort_keys=True)}`.")
    lines.extend(["", "## SAME-HYPOTHESIS RE-ENTRY", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        reentry = bucket["reentry_integrity"]
        lines.append(
            f"- {label}: hypotheses with consumed participation "
            f"{reentry['hypotheses_with_consumed_participation']}; positions reopened by "
            f"a risk-consumed hypothesis "
            f"**{reentry['positions_reopened_by_a_risk_consumed_hypothesis']}**; "
            f"hypotheses that produced more than one position "
            f"{reentry['hypotheses_that_produced_more_than_one_position']}.")
    lines.extend(["", "## HYPOTHESIS FALSIFICATION (SEPARATE FROM POSITION RISK)", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        lines.append(
            f"- {label}: falsified positions V1 {delta['falsified_positions']['v1']} -> "
            f"V2 {delta['falsified_positions']['v2']}.")
        lines.append(
            f"- {label}: accepted-failure overshoot points V1 "
            f"{_dist_text(delta['falsification_overshoot_points']['v1'])}.")
        lines.append(
            f"- {label}: accepted-failure overshoot points V2 "
            f"{_dist_text(delta['falsification_overshoot_points']['v2'])}.")
        lines.append(
            f"- {label}: exit classes V1 "
            f"`{json.dumps(delta['exit_classes']['v1'], sort_keys=True)}`; V2 "
            f"`{json.dumps(delta['exit_classes']['v2'], sort_keys=True)}`.")
    lines.extend(["", "## STRUCTURAL PROGRESS, RETAINED AND GIVEN BACK", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        lines.append(
            f"- {label} max favorable fraction: V1 "
            f"{_dist_text(delta['max_favorable_progress_fraction']['v1'])}; V2 "
            f"{_dist_text(delta['max_favorable_progress_fraction']['v2'])}.")
        lines.append(
            f"- {label} retained fraction at exit: V1 "
            f"{_dist_text(delta['retained_progress_fraction']['v1'])}; V2 "
            f"{_dist_text(delta['retained_progress_fraction']['v2'])}.")
        lines.append(
            f"- {label} retained sign V1 "
            f"`{json.dumps(delta['retained_progress_sign']['v1'], sort_keys=True)}`; V2 "
            f"`{json.dumps(delta['retained_progress_sign']['v2'], sort_keys=True)}`.")
        lines.append(
            f"- {label} giveback fraction: V1 "
            f"{_dist_text(delta['giveback_fraction']['v1'])}; V2 "
            f"{_dist_text(delta['giveback_fraction']['v2'])}.")
        lines.append(
            f"- {label} retained fraction by family V2: "
            f"`{json.dumps(delta['retained_progress_fraction_by_family']['v2'], sort_keys=True)}`.")
    lines.extend(["", "## WAIT BEHAVIOUR", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        lines.append(
            f"- {label}: WAIT outcomes V1 "
            f"`{json.dumps(delta['wait_outcomes']['v1'], sort_keys=True)}`; V2 "
            f"`{json.dumps(delta['wait_outcomes']['v2'], sort_keys=True)}`.")
    lines.extend(["", "## SIDE SWITCHING", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        lines.append(
            f"- {label}: switches V1 {delta['side_switches']['v1']['count']} -> V2 "
            f"{delta['side_switches']['v2']['count']}.")
        lines.append(
            f"- {label}: categories V1 "
            f"`{json.dumps(delta['side_switches']['v1']['categories'], sort_keys=True)}`; "
            f"V2 `{json.dumps(delta['side_switches']['v2']['categories'], sort_keys=True)}`.")
        lines.append(
            f"- {label}: flip chains V2 "
            f"`{json.dumps(delta['side_switches']['v2']['flip_chains'], sort_keys=True)}`; "
            f"flat candles between "
            f"{_dist_text(delta['side_switches']['v2']['flat_candles_between'])}.")
    lines.extend(["", "## CONTINUATIONS (UNCHANGED BY CONSTRUCTION)", ""])
    for label, bucket in (("TEACH", TEACH), ("VALIDATE aggregate", VALIDATE)):
        delta = payload["brain_v1_vs_v2"][bucket]
        for family in (CONTINUATION_UP, CONTINUATION_DOWN):
            v1 = delta["continuation_risk_geometry"]["v1"][family]
            v2 = delta["continuation_risk_geometry"]["v2"][family]
            lines.append(
                f"- {label} {family}: positions V1 {v1['positions']} -> V2 "
                f"{v2['positions']}; retained fraction V1 "
                f"{_dist_text(v1['retained_progress_fraction_at_exit'])}; V2 "
                f"{_dist_text(v2['retained_progress_fraction_at_exit'])}.")
    lines.extend(["", "## ADVERSE EXIT LEDGER — THE Q3 POPULATION", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        adverse = bucket["adverse_exit_ledger"]
        lines.append(
            f"- {label}: adverse exits {adverse['adverse_exits']} "
            f"(falsification {adverse['falsification_exits']}, position risk "
            f"{adverse['position_risk_exits']}); overshoot beyond the frozen level "
            f"{_dist_text(adverse['overshoot_points'])}; exceeding the distance risked at "
            f"entry {adverse['overshoot_exceeds_entry_invalidation_distance']}; ATR "
            f"{_dist_text(adverse['overshoot_atr'])}.")
    lines.extend(["", "## ENTRY QUALITY BY FAMILY", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for family in DIRECTIONAL_FAMILIES:
            data = bucket["entry_quality"]["by_family"][family]
            lines.append(
                f"- {label} {family}: entries {data['entries']} | ACTIVE-to-entry "
                f"{_dist_text(data['bars_active_to_entry'])} | whole progress fraction "
                f"{_dist_text(data['whole_progress_fraction_at_entry'])} | room points "
                f"{_dist_text(data['structural_room_points_at_entry'])} | invalidation "
                f"points {_dist_text(data['invalidation_distance_points_at_entry'])}.")
    lines.extend(["", "## TEACH / VALIDATE DESCRIPTIVE REPEATABILITY", ""])
    for name in QUALITY_RATE_NAMES:
        item = payload["teach_validate_quality_rates"][name]
        lines.append(
            f"- `{name}`: TEACH {item['teach']['numerator']}/"
            f"{item['teach']['denominator']} = {item['teach']['rate']}; VALIDATE aggregate "
            f"{item['validate_aggregate']['numerator']}/"
            f"{item['validate_aggregate']['denominator']} = "
            f"{item['validate_aggregate']['rate']}; absolute difference "
            f"{item['absolute_rate_difference']}.")
    loss = gates["Q3_STRUCTURAL_LOSS_BEHAVIOUR_ACCEPTABLE"]
    lines.extend([
        "",
        "## WEAKEST FAMILY",
        "",
        f"- Result: **{payload['weakest_hypothesis_family']['answer']}**.",
        f"- Facts: `{json.dumps(payload['weakest_hypothesis_family']['facts'], sort_keys=True)}`.",
        "",
        "## Q3 CONTROL — THE SAME RULE ON V1",
        "",
        (
            "- The repaired Q3 rule recomputed on the V1 control replay answers "
            f"**{loss['same_rule_recomputed_on_v1']['answer']}**."
        ),
        (
            "- V1 facts: `"
            f"{json.dumps(loss['same_rule_recomputed_on_v1']['per_bucket'], sort_keys=True)}`."
        ),
        f"- V2 facts: `{json.dumps(loss['facts'], sort_keys=True)}`.",
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
        "- Both frozen V1 fingerprints were reproduced from the current source tree "
        "before any V2 number was computed.",
        "- Both brains read one identical set of causal frames per source episode.",
        "- VALIDATE is aggregate-only; no IDs, timestamps, prices, paths, bands, or traces.",
        (
            "- HOLDOUT_PRICE_SESSIONS_CONVERTED = "
            f"{payload['holdout_price_sessions_converted']}."
        ),
        "- No broker, live money, parameter optimization, score, confidence, probability, "
        "or ranking.",
        "",
        "## NEXT DECISION",
        "",
    ])
    if verdict == "PASS_FOR_PRODUCTION_INTEGRATION":
        lines.append(
            "- FREEZE_BRAIN_V2_SEMANTICS_AND_MIGRATE_THEM_INTO_THE_PRODUCTION_PAPER_"
            "SHADOW_COGNITION_PATH_WITHOUT_BROKER_SIZING_OR_LIVE_EXECUTION.")
    else:
        negative = [name for name, gate in gates.items()
                    if name.startswith("Q") and gate["answer"] == "NO"]
        lines.append(
            "- DO_NOT_MIGRATE. Blocking gates: "
            f"{', '.join(negative) if negative else 'NONE_BUT_A_REQUIRED_GATE_IS_NOT_YES'}.")
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
        default=REPO_ROOT / "reports" / "DYNAMIC_REACTIVE_TRADER_BRAIN_V2_AUDIT.md")
    parser.add_argument(
        "--aggregate", type=Path,
        default=REPO_ROOT / "reports" / "dynamic_reactive_trader_brain_v2_summary.json")
    args = parser.parse_args(argv)
    payload = run_brain_v2_study()
    write_outputs(payload, args.report, args.aggregate)
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "verdict": payload["final_pre_production_verdict"],
        "gates": {name: gate["answer"] for name, gate in payload[
            "final_quality_gates"].items() if name.startswith("Q")},
        "report": str(args.report),
        "aggregate": str(args.aggregate),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
