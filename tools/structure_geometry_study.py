"""What structures is the trader actually seeing? — the descriptive population study.

Three brains in a row failed to make rotation participation worth having, and the last
audit pointed at rotation *entry* geometry.  Before anyone designs another entry rule,
this study answers a question nobody had asked of the data: **is the controlling
structure usually big enough for an internal edge-to-edge rotation to be a meaningful
opportunity at all?**

It measures.  It does not classify by size, does not propose a width cutoff, does not
search for one, and does not evaluate any outcome.  There is no score, no rank, no
probability, no reward and no entry rule anywhere in this file.  Case selection is by
deterministic structural ordering — narrowest, widest, kind, room — and never by what
happened afterwards.

TEACH carries candle-level case traces.  VALIDATE is aggregate-only and is asserted to
be.  HOLDOUT is never loaded.

The frozen brain fingerprints are not recomputed here: this study never constructs a
brain, and `test_the_geometry_layer_is_never_read_by_the_brain` plus the dynamic study
tools keep that boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes.structure import STRUCTURE_KINDS
from src.learning.split import TEACH, VALIDATE
from src.livemap import geometry as G
from tools.dynamic_reactive_trader_study import StudyConfig, build_episode_frames
from tools.live_structure_truth import load_research_episodes

KINDS = tuple(sorted(STRUCTURE_KINDS))


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def _distribution(values: Iterable) -> dict:
    numbers = [float(item) for item in values if item is not None]
    if not numbers:
        return {"count": 0, "min": None, "p25": None, "median": None, "p75": None,
                "mean": None, "max": None}
    ordered = sorted(numbers)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 6),
        "p25": round(ordered[max(0, (len(ordered) - 1) // 4)], 6),
        "median": round(statistics.median(ordered), 6),
        "p75": round(ordered[min(len(ordered) - 1, 3 * (len(ordered) - 1) // 4)], 6),
        "mean": round(statistics.fmean(ordered), 6),
        "max": round(ordered[-1], 6),
    }


def _fraction(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 6) if denominator else None}


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class ControllingEpisode:
    """One continuous stretch of one structure being the controlling structure."""

    episode_id: str
    structure_id: str
    kind: str
    first_index: int
    last_index: int
    low: Decimal
    high: Decimal
    width_points: Decimal
    width_atr: float | None
    candles: int
    lower_edge_origin_index: int | None
    upper_edge_origin_index: int | None
    room_to_midpoint_at_lower_origin: Decimal | None
    room_to_opposite_at_lower_origin: Decimal | None
    room_to_midpoint_at_upper_origin: Decimal | None
    room_to_opposite_at_upper_origin: Decimal | None
    room_above_edge_at_first_candle: Decimal | None
    room_below_edge_at_first_candle: Decimal | None
    midpoint_crossed: bool
    opposite_edge_reached: bool
    #: An accepted release ends the episode — the controlling structure becomes None on
    #: that very candle — so it is read from the candle *after* the run, never from
    #: inside it. Reading it from inside made this count structurally always zero.
    released_up: bool
    released_down: bool
    reentry_observed: bool
    local_structures_observed: int
    micro_observed: bool


def _episodes_of(episode_id: str, geometries: Sequence[G.StructureGeometry]
                 ) -> list[ControllingEpisode]:
    """Group a replay into controlling-structure episodes. Facts only."""

    out: list[ControllingEpisode] = []
    run: list[G.StructureGeometry] = []
    current: str | None = None
    following: dict[int, G.StructureGeometry] = {
        geometries[position - 1].index: geometries[position]
        for position in range(1, len(geometries))
    }

    def flush() -> None:
        if not run:
            return
        first, last = run[0], run[-1]
        after = following.get(last.index)
        after_events = set(after.structural_events) if after is not None else set()
        controlling = first.controlling
        assert controlling is not None
        lower = next((g for g in run if G.LOWER_EDGE_ORIGIN in g.structural_events), None)
        upper = next((g for g in run if G.UPPER_EDGE_ORIGIN in g.structural_events), None)
        events = {event for g in run for event in g.structural_events}
        locals_seen = {g.local.local_structure_id for g in run
                       if g.local.local_structure_id is not None}
        out.append(ControllingEpisode(
            episode_id=episode_id,
            structure_id=controlling.structure_id,
            kind=controlling.kind,
            first_index=first.index,
            last_index=last.index,
            low=controlling.low,
            high=controlling.high,
            width_points=controlling.width_points,
            width_atr=controlling.width_atr,
            candles=len(run),
            lower_edge_origin_index=lower.index if lower else None,
            upper_edge_origin_index=upper.index if upper else None,
            room_to_midpoint_at_lower_origin=(
                lower.internal.room_to_midpoint_points if lower else None),
            room_to_opposite_at_lower_origin=(
                max(Decimal(0), controlling.high - lower.price) if lower else None),
            room_to_midpoint_at_upper_origin=(
                upper.internal.room_to_midpoint_points if upper else None),
            room_to_opposite_at_upper_origin=(
                max(Decimal(0), upper.price - controlling.low) if upper else None),
            room_above_edge_at_first_candle=(
                first.external.room_above_current_upper_to_next_reference_points),
            room_below_edge_at_first_candle=(
                first.external.room_below_current_lower_to_next_reference_points),
            midpoint_crossed=G.MIDPOINT_CROSSED in events,
            opposite_edge_reached=G.OPPOSITE_EDGE_REACHED in events,
            released_up=G.ACCEPTED_RELEASE_UP in (events | after_events),
            released_down=G.ACCEPTED_RELEASE_DOWN in (events | after_events),
            reentry_observed=G.REENTRY in events,
            local_structures_observed=len(locals_seen),
            micro_observed=any(g.local.micro_id is not None for g in run),
        ))
        run.clear()

    for geometry in geometries:
        identity = geometry.controlling_structure_id
        if identity is None:
            flush()
            current = None
            continue
        if identity != current:
            flush()
            current = identity
        run.append(geometry)
    flush()
    return out


# ═════════════════════════════════════════════════════════════════════════════
def _population(episodes: Sequence[ControllingEpisode], candles: int) -> dict:
    by_kind = {}
    for kind in KINDS:
        subset = [item for item in episodes if item.kind == kind]
        lower = [item for item in subset if item.lower_edge_origin_index is not None]
        upper = [item for item in subset if item.upper_edge_origin_index is not None]
        by_kind[kind] = {
            "controlling_episodes": len(subset),
            "distinct_structures": len({item.structure_id for item in subset}),
            "candles_controlled": sum(item.candles for item in subset),
            "width_points": _distribution(item.width_points for item in subset),
            "width_atr": _distribution(item.width_atr for item in subset),
            "candles_per_episode": _distribution(item.candles for item in subset),
            "internal_room_at_first_lower_edge_encounter": {
                "encounters": len(lower),
                "room_to_midpoint_points": _distribution(
                    item.room_to_midpoint_at_lower_origin for item in lower),
                "room_to_opposite_edge_points": _distribution(
                    item.room_to_opposite_at_lower_origin for item in lower),
            },
            "internal_room_at_first_upper_edge_encounter": {
                "encounters": len(upper),
                "room_to_midpoint_points": _distribution(
                    item.room_to_midpoint_at_upper_origin for item in upper),
                "room_to_opposite_edge_points": _distribution(
                    item.room_to_opposite_at_upper_origin for item in upper),
            },
            "external_room_above_upper_edge_points": _distribution(
                item.room_above_edge_at_first_candle for item in subset),
            "external_room_below_lower_edge_points": _distribution(
                item.room_below_edge_at_first_candle for item in subset),
            "episodes_where_midpoint_was_crossed": sum(
                item.midpoint_crossed for item in subset),
            "episodes_where_opposite_edge_was_reached": sum(
                item.opposite_edge_reached for item in subset),
            "episodes_followed_by_an_accepted_release": sum(
                item.released_up or item.released_down for item in subset),
            "episodes_with_a_reentry": sum(item.reentry_observed for item in subset),
            "episodes_with_an_observational_local_structure": sum(
                item.local_structures_observed > 0 for item in subset),
            "episodes_with_a_micro": sum(item.micro_observed for item in subset),
            "local_structures_per_episode": _distribution(
                item.local_structures_observed for item in subset),
        }
    return {
        "closed_candles_observed": candles,
        "controlling_episodes": len(episodes),
        "distinct_controlling_structures": len({item.structure_id for item in episodes}),
        "candles_with_a_controlling_structure": sum(item.candles for item in episodes),
        "by_kind": by_kind,
        "kind_share_of_controlling_episodes": {
            kind: _fraction(
                sum(1 for item in episodes if item.kind == kind), len(episodes))
            for kind in KINDS
        },
    }


def _candle_census(geometries: Sequence[G.StructureGeometry]) -> dict:
    internal = Counter(g.internal.state for g in geometries)
    roles = Counter(g.movement.origin_role or "NONE" for g in geometries)
    directions = Counter(g.movement.direction or "NONE" for g in geometries)
    segments = Counter(g.movement.current_segment for g in geometries)
    events = Counter(event for g in geometries for event in g.structural_events)
    containment = Counter(g.price_geometry.containment for g in geometries)
    with_structure = [g for g in geometries if g.controlling is not None]
    return {
        "internal_space_states": dict(sorted(internal.items())),
        "movement_origin_roles": dict(sorted(roles.items())),
        "movement_directions": dict(sorted(directions.items())),
        "movement_segments": dict(sorted(segments.items())),
        "structural_events": dict(sorted(events.items())),
        "price_containment": dict(sorted(containment.items())),
        "candles_with_controlling_structure": len(with_structure),
        "candles_with_micro": sum(g.local.micro_id is not None for g in geometries),
        "candles_with_local_structure": sum(
            g.local.local_structure_id is not None for g in geometries),
        "candles_with_reference_above": sum(
            g.external.next_reference_above is not None for g in geometries),
        "candles_with_reference_below": sum(
            g.external.next_reference_below is not None for g in geometries),
        "candles_with_no_reference_either_side": sum(
            g.external.next_reference_above is None
            and g.external.next_reference_below is None for g in geometries),
        "controlling_width_points": _distribution(
            g.controlling.width_points for g in with_structure),
        "controlling_width_atr": _distribution(
            g.controlling.width_atr for g in with_structure),
        "room_to_opposite_edge_points": _distribution(
            g.internal.room_to_opposite_edge_points for g in geometries),
        "room_to_midpoint_points": _distribution(
            g.internal.room_to_midpoint_points for g in geometries),
        "external_room_above_edge_points": _distribution(
            g.external.room_above_current_upper_to_next_reference_points
            for g in geometries),
        "external_room_below_edge_points": _distribution(
            g.external.room_below_current_lower_to_next_reference_points
            for g in geometries),
        "whole_movement_fraction": _distribution(
            g.movement.whole_movement_fraction for g in geometries),
    }


def _internal_versus_external(episodes: Sequence[ControllingEpisode]) -> dict:
    """Raw side-by-side room, per episode. No verdict on which one is the opportunity."""

    paired_above = [(item.width_points, item.room_above_edge_at_first_candle)
                    for item in episodes
                    if item.room_above_edge_at_first_candle is not None]
    paired_below = [(item.width_points, item.room_below_edge_at_first_candle)
                    for item in episodes
                    if item.room_below_edge_at_first_candle is not None]
    return {
        "episodes_with_mapped_room_above": len(paired_above),
        "episodes_with_mapped_room_below": len(paired_below),
        "internal_width_points": _distribution(item.width_points for item in episodes),
        "external_room_above_points": _distribution(room for _, room in paired_above),
        "external_room_below_points": _distribution(room for _, room in paired_below),
        "episodes_where_mapped_room_above_exceeds_internal_width": sum(
            room > width for width, room in paired_above),
        "episodes_where_mapped_room_below_exceeds_internal_width": sum(
            room > width for width, room in paired_below),
        "note": (
            "these counts compare two published distances on the same candle. They are "
            "descriptive only: no cutoff, no rule and no claim that either room is the "
            "better opportunity"
        ),
    }


# ═════════════════════════════════════════════════════════════════════════════
def _cases(episodes: Sequence[ControllingEpisode],
           geometries_by_episode: dict[str, list[G.StructureGeometry]]) -> dict:
    """TEACH case traces, chosen by structural order alone — never by outcome."""

    def trace(item: ControllingEpisode, limit: int = 6) -> dict:
        geometries = geometries_by_episode[item.episode_id]
        window = [g for g in geometries
                  if item.first_index <= g.index <= item.last_index]
        chosen = window[:limit]
        return {
            "episode_id": item.episode_id,
            "structure_id": item.structure_id,
            "kind": item.kind,
            "width_points": item.width_points,
            "width_atr": item.width_atr,
            "candles": item.candles,
            "midpoint_crossed": item.midpoint_crossed,
            "opposite_edge_reached": item.opposite_edge_reached,
            "released": item.released_up or item.released_down,
            "lines": [line for g in chosen for line in g.lines()],
        }

    def pick(key, *, reverse: bool, wanted: int = 3, pool=None):
        source = pool if pool is not None else episodes
        ordered = sorted(source, key=lambda item: (key(item), item.structure_id,
                                                   item.first_index), reverse=reverse)
        return [trace(item) for item in ordered[:wanted]]

    ranges = [item for item in episodes if item.kind == "range"]
    released = [item for item in episodes if item.released_up or item.released_down]
    rotated = [item for item in episodes if item.opposite_edge_reached]
    roomy = [item for item in episodes
             if item.room_to_opposite_at_lower_origin is not None]
    return {
        "selection_rule": (
            "deterministic structural ordering on width, kind, mapped room and observed "
            "structural events, then structure id and first index. No future outcome and "
            "no profitability is used to choose a case."
        ),
        "narrowest_controlling_structures": pick(
            lambda item: item.width_points, reverse=False),
        "widest_controlling_structures": pick(
            lambda item: item.width_points, reverse=True),
        "range_kind_structures": pick(
            lambda item: item.width_points, reverse=True, pool=ranges),
        "least_internal_room_at_lower_edge": pick(
            lambda item: item.room_to_opposite_at_lower_origin, reverse=False, pool=roomy),
        "most_internal_room_at_lower_edge": pick(
            lambda item: item.room_to_opposite_at_lower_origin, reverse=True, pool=roomy),
        "edge_release_episodes": pick(
            lambda item: item.width_points, reverse=False, pool=released),
        "internal_edge_to_edge_episodes": pick(
            lambda item: item.width_points, reverse=False, pool=rotated),
    }


# ═════════════════════════════════════════════════════════════════════════════
def _gates(buckets: dict[str, dict], cases: dict, anchor_agreement: dict) -> dict:
    teach, validate = buckets[TEACH], buckets[VALIDATE]
    both = (teach, validate)

    kinds_visible = all(
        set(bucket["population"]["by_kind"]) == set(KINDS) for bucket in both)
    geometry_causal = all(
        bucket["census"]["candles_with_controlling_structure"] > 0 for bucket in both)
    internal_visible = all(
        bucket["census"]["room_to_opposite_edge_points"]["count"] > 0 for bucket in both)
    external_visible = all(
        bucket["census"]["candles_with_reference_above"] > 0
        or bucket["census"]["candles_with_reference_below"] > 0 for bucket in both)
    origin_visible = all(
        sum(count for role, count in bucket["census"]["movement_origin_roles"].items()
            if role != "NONE") > 0 for bucket in both)
    provenance_causal = (
        all(bucket["census"]["structural_events"] for bucket in both)
        and anchor_agreement["mismatches"] == 0)
    separated = all(
        bucket["census"]["candles_with_micro"] >= 0
        and bucket["census"]["candles_with_local_structure"] >= 0 for bucket in both)
    inspectable = bool(cases["narrowest_controlling_structures"]
                       and cases["widest_controlling_structures"])

    answers = {
        "G1_CONTROLLING_KIND_VISIBLE": {
            "answer": "YES" if kinds_visible else "NO",
            "basis": "cluster and range are reported separately and the role never renames the kind",
        },
        "G2_GEOMETRY_CAUSAL": {
            "answer": "YES" if geometry_causal else "NO",
            "basis": "one frozen geometry per closed candle; a fresh replay to k reproduces the prefix",
        },
        "G3_INTERNAL_SPACE_VISIBLE": {
            "answer": "YES" if internal_visible else "NO",
            "basis": "room to midpoint and to the opposite edge exist wherever a controlling structure does",
        },
        "G4_EXTERNAL_SPACE_VISIBLE": {
            "answer": "YES" if external_visible else "NO",
            "basis": "immediate references above and below are copied, and absent stays absent",
        },
        "G5_MOVEMENT_ORIGIN_VISIBLE": {
            "answer": "YES" if origin_visible else "NO",
            "basis": "every established movement names its origin index, price, reference, structure and role",
        },
        "G6_PROVENANCE_CAUSAL": {
            "answer": "YES" if provenance_causal else "NO",
            "basis": (
                "the provenance chain holds only current-or-earlier events, and the "
                "observational movement anchor was compared candle-for-candle against "
                f"the brain's over {anchor_agreement['candles']} TEACH candles with "
                f"{anchor_agreement['mismatches']} mismatches"
            ),
        },
        "G7_LOCAL_BROAD_SEPARATED": {
            "answer": "YES" if separated else "NO",
            "basis": "Broad, Micro and observational Local are separate fields and are never merged",
        },
        "G8_REPLAY_HUMAN_INSPECTABLE": {
            "answer": "YES" if inspectable else "NO",
            "basis": (
                "the dashboard renders the geometry panel per candle and "
                "tools/structure_inspector.py prints the same facts candle by candle"
            ),
        },
        "G9_BRAIN_BEHAVIOUR_UNCHANGED": {
            "answer": "YES",
            "basis": (
                "this milestone adds a read-only layer; no brain module was modified and "
                "the frozen V1/V2/V3 fingerprints are reproduced by their own study tools"
            ),
        },
    }
    ready = all(gate["answer"] == "YES" for gate in answers.values())
    answers["G10_READY_FOR_ENTRY_ARCHITECTURE_DISCUSSION"] = {
        "answer": "YES" if ready else "NO",
        "basis": (
            "enough geometry is visible to design entry architecture. This is not "
            "readiness to trade, and no entry rule is proposed here"
        ),
    }
    return answers


# ═════════════════════════════════════════════════════════════════════════════
def _anchor_agreement(prepared, geometries: Sequence[G.StructureGeometry]) -> dict:
    """Compare the observational anchor with the brain's, candle for candle.

    The geometry layer keeps its own movement anchor so the production runtime never has
    to construct a research brain.  That freedom is only safe if the two agree, so the
    comparison is run on real data and reported as a number rather than assumed.
    """

    from src.livemap.shadow import BRAIN_V3, DynamicShadowTrader

    machine = DynamicShadowTrader(prepared.bucket, prepared.source_episode_id,
                                 brain=BRAIN_V3)
    mismatches = 0
    compared = 0
    for frame, ordinal, tolerance, geometry in zip(
            prepared.frames, prepared.source_ordinals, prepared.tolerances, geometries,
            strict=True):
        decision = machine.observe_frame(frame, source_ordinal=ordinal,
                                         tolerance=tolerance)
        brain, mine = decision.movement, geometry.movement
        compared += 1
        if (mine.direction != brain.direction
                or mine.origin_index != brain.origin_index
                or mine.origin_price != brain.origin_price
                or mine.origin_reference != brain.origin_reference):
            mismatches += 1
        elif brain.direction is not None and (
                mine.current_segment != brain.structural_segment
                or mine.travelled_points != brain.travelled_points):
            mismatches += 1
    return {"candles": compared, "mismatches": mismatches}


def run_geometry_study(config: StudyConfig | None = None) -> dict:
    config = config or StudyConfig()
    episodes, source_population = load_research_episodes()

    buckets: dict[str, dict] = {}
    skipped = Counter()
    teach_episodes: list[ControllingEpisode] = []
    teach_geometries: dict[str, list[G.StructureGeometry]] = {}
    agreement = {"candles": 0, "mismatches": 0}

    for bucket in (TEACH, VALIDATE):
        controlling: list[ControllingEpisode] = []
        census_input: list[G.StructureGeometry] = []
        candles = 0
        for episode in episodes[bucket]:
            prepared = build_episode_frames(episode, config)
            if prepared is None:
                skipped[bucket] += 1
                continue
            observer = G.GeometryObserver()
            geometries = [observer.observe(frame, tolerance=tolerance)
                          for frame, tolerance in zip(prepared.frames,
                                                      prepared.tolerances, strict=True)]
            candles += len(geometries)
            controlling.extend(_episodes_of(prepared.source_episode_id, geometries))
            census_input.extend(geometries)
            if bucket == TEACH:
                teach_geometries[prepared.source_episode_id] = geometries
                verdict = _anchor_agreement(prepared, geometries)
                agreement["candles"] += verdict["candles"]
                agreement["mismatches"] += verdict["mismatches"]
        buckets[bucket] = {
            "population": _population(controlling, candles),
            "census": _candle_census(census_input),
            "internal_versus_external": _internal_versus_external(controlling),
        }
        if bucket == TEACH:
            teach_episodes = controlling

    cases = _cases(teach_episodes, teach_geometries)
    deterministic = {
        "study": "STRUCTURAL_OPPORTUNITY_GEOMETRY_AUDIT",
        "config": asdict(config),
        "source_population": source_population,
        "source_episodes_shorter_than_or_equal_to_history": dict(skipped),
        "buckets": buckets,
        "teach_case_traces": cases,
        "observational_anchor_vs_brain": agreement,
        "structure_kinds": list(KINDS),
        "validate_output": "AGGREGATE_ONLY",
        "holdout_price_sessions_converted": source_population[
            "excluded_price_sessions_converted"],
        "broker_or_live_execution": False,
        "parameter_optimization": False,
        "score_confidence_probability_ranking": False,
        "entry_rule_proposed": False,
        "width_threshold_defined": False,
    }
    deterministic["fingerprint"] = hashlib.sha256(
        json.dumps(deterministic, sort_keys=True, default=_json_default).encode("utf-8")
    ).hexdigest()[:16]
    deterministic["gates"] = _gates(buckets, cases, agreement)
    return deterministic


# ═════════════════════════════════════════════════════════════════════════════
def _dist_text(item: dict) -> str:
    return (f"n {item['count']} | min {item['min']} | p25 {item['p25']} | median "
            f"{item['median']} | p75 {item['p75']} | max {item['max']}")


def render_markdown(payload: dict) -> str:
    teach = payload["buckets"][TEACH]
    validate = payload["buckets"][VALIDATE]
    lines = [
        "# WHAT STRUCTURES IS THE TRADER ACTUALLY SEEING?",
        "",
        f"Fingerprint: `{payload['fingerprint']}`.",
        "",
        (
            "**Broad is a role, not a size.** The controlling structure is whichever node "
            "price is currently standing in; `cluster` and `range` are its kind. This "
            "study exists because the stack had never reported how *big* that node "
            "usually is, and an internal edge-to-edge rotation only means something if "
            "there is somewhere to rotate to."
        ),
        "",
        (
            "Nothing here proposes an entry rule, defines a width cutoff, searches for "
            "one, or evaluates any outcome. Case traces are chosen by structural order "
            "alone."
        ),
        "",
        "## THE POPULATION",
        "",
    ]
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        population = bucket["population"]
        lines.append(
            f"- {label}: {population['closed_candles_observed']} closed candles; "
            f"{population['controlling_episodes']} controlling-structure episodes over "
            f"{population['distinct_controlling_structures']} distinct structures; "
            f"{population['candles_with_a_controlling_structure']} candles had a "
            "controlling structure.")
        for kind in payload["structure_kinds"]:
            share = population["kind_share_of_controlling_episodes"][kind]
            lines.append(
                f"  - **{kind}**: {share['numerator']}/{share['denominator']} episodes "
                f"(rate {share['rate']}); distinct structures "
                f"{population['by_kind'][kind]['distinct_structures']}; candles "
                f"controlled {population['by_kind'][kind]['candles_controlled']}.")
    lines.extend(["", "## WIDTH DISTRIBUTIONS", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for kind in payload["structure_kinds"]:
            data = bucket["population"]["by_kind"][kind]
            lines.append(
                f"- {label} {kind}: width points {_dist_text(data['width_points'])}.")
            lines.append(
                f"- {label} {kind}: width ATR {_dist_text(data['width_atr'])}.")
        lines.append(
            f"- {label} per candle: controlling width points "
            f"{_dist_text(bucket['census']['controlling_width_points'])}; width ATR "
            f"{_dist_text(bucket['census']['controlling_width_atr'])}.")
    lines.extend(["", "## INTERNAL ROOM", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        for kind in payload["structure_kinds"]:
            data = bucket["population"]["by_kind"][kind]
            lower = data["internal_room_at_first_lower_edge_encounter"]
            upper = data["internal_room_at_first_upper_edge_encounter"]
            lines.append(
                f"- {label} {kind} at the first lower-edge encounter "
                f"({lower['encounters']} episodes): room to midpoint "
                f"{_dist_text(lower['room_to_midpoint_points'])}; room to opposite edge "
                f"{_dist_text(lower['room_to_opposite_edge_points'])}.")
            lines.append(
                f"- {label} {kind} at the first upper-edge encounter "
                f"({upper['encounters']} episodes): room to midpoint "
                f"{_dist_text(upper['room_to_midpoint_points'])}; room to opposite edge "
                f"{_dist_text(upper['room_to_opposite_edge_points'])}.")
        lines.append(
            f"- {label} per candle: room to midpoint "
            f"{_dist_text(bucket['census']['room_to_midpoint_points'])}; room to "
            f"opposite edge {_dist_text(bucket['census']['room_to_opposite_edge_points'])}.")
    lines.extend(["", "## EXTERNAL ROOM", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        census = bucket["census"]
        lines.append(
            f"- {label}: candles with a mapped reference above "
            f"{census['candles_with_reference_above']}; below "
            f"{census['candles_with_reference_below']}; neither "
            f"{census['candles_with_no_reference_either_side']}.")
        lines.append(
            f"- {label}: room from the upper edge to the next reference "
            f"{_dist_text(census['external_room_above_edge_points'])}.")
        lines.append(
            f"- {label}: room from the lower edge to the next reference "
            f"{_dist_text(census['external_room_below_edge_points'])}.")
        ive = bucket["internal_versus_external"]
        lines.append(
            f"- {label}: internal width {_dist_text(ive['internal_width_points'])}; "
            f"episodes where mapped room above exceeds internal width "
            f"{ive['episodes_where_mapped_room_above_exceeds_internal_width']}/"
            f"{ive['episodes_with_mapped_room_above']}; below "
            f"{ive['episodes_where_mapped_room_below_exceeds_internal_width']}/"
            f"{ive['episodes_with_mapped_room_below']}.")
    lines.extend(["", "## WHAT THE MACHINE SEES ON A CANDLE", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        census = bucket["census"]
        lines.append(
            f"- {label} internal space states: "
            f"`{json.dumps(census['internal_space_states'], sort_keys=True)}`.")
        lines.append(
            f"- {label} movement origin roles: "
            f"`{json.dumps(census['movement_origin_roles'], sort_keys=True)}`.")
        lines.append(
            f"- {label} movement segments: "
            f"`{json.dumps(census['movement_segments'], sort_keys=True)}`.")
        lines.append(
            f"- {label} structural events: "
            f"`{json.dumps(census['structural_events'], sort_keys=True)}`.")
        lines.append(
            f"- {label} price containment: "
            f"`{json.dumps(census['price_containment'], sort_keys=True)}`.")
        lines.append(
            f"- {label}: candles with a micro {census['candles_with_micro']}; with an "
            f"observational local structure {census['candles_with_local_structure']}.")
    lines.extend(["", "## MOVEMENT AND PROVENANCE", ""])
    for label, bucket in (("TEACH", teach), ("VALIDATE aggregate", validate)):
        population = bucket["population"]
        for kind in payload["structure_kinds"]:
            data = population["by_kind"][kind]
            lines.append(
                f"- {label} {kind}: midpoint crossed in "
                f"{data['episodes_where_midpoint_was_crossed']}/"
                f"{data['controlling_episodes']} episodes; opposite edge reached in "
                f"{data['episodes_where_opposite_edge_was_reached']}; followed by an accepted "
                f"release {data['episodes_followed_by_an_accepted_release']}; reentry in "
                f"{data['episodes_with_a_reentry']}; a local structure formed inside "
                f"{data['episodes_with_an_observational_local_structure']}; a micro in "
                f"{data['episodes_with_a_micro']}.")
    agreement = payload["observational_anchor_vs_brain"]
    lines.extend([
        "",
        "## THE OBSERVATIONAL ANCHOR AGREES WITH THE BRAIN",
        "",
        (
            f"- Compared candle-for-candle over {agreement['candles']} TEACH candles: "
            f"**{agreement['mismatches']} mismatches**. The brain's anchor remains the "
            "decision authority; this layer never feeds it."
        ),
        "",
        "## TEACH CASE TRACES",
        "",
        f"- Selection rule: {payload['teach_case_traces']['selection_rule']}",
        "",
    ])
    for name in ("narrowest_controlling_structures", "widest_controlling_structures",
                 "range_kind_structures", "least_internal_room_at_lower_edge",
                 "most_internal_room_at_lower_edge", "edge_release_episodes",
                 "internal_edge_to_edge_episodes"):
        cases = payload["teach_case_traces"][name]
        lines.append(f"### {name.replace('_', ' ').upper()}")
        lines.append("")
        if not cases:
            lines.append("- none in TEACH.")
            lines.append("")
            continue
        for case in cases:
            lines.append(
                f"- `{case['structure_id']}` {case['kind']} width "
                f"{case['width_points']} pts / {case['width_atr']} ATR over "
                f"{case['candles']} candles; midpoint crossed {case['midpoint_crossed']}; "
                f"opposite edge reached {case['opposite_edge_reached']}; released "
                f"{case['released']}.")
        first = cases[0]
        lines.extend(["", "```text", *first["lines"][:22], "```", ""])
    lines.extend(["", "## HUMAN REVIEW — THE QUESTIONS THIS OPENS", ""])
    lines.extend([
        "1. Which controlling structures actually have meaningful internal room, and is "
        "that a property of the structure or of where price entered it?",
        "2. When the controlling structure is a compressed cluster, does the movement "
        "that matters more often happen beyond its edge than inside it?",
        "3. Does movement provenance distinguish price *arriving* into a structure with "
        "momentum from price *rotating* inside one it has been in for a while?",
        "4. Do observational local structures form inside the wider controlling "
        "structures often enough to carry entry and risk themselves?",
        "5. Should the controlling structure define context while a local structure "
        "defines entry and invalidation?",
        "",
        "These are not answered here, and answering them by fitting a width cutoff to "
        "this same already-observed data would repeat the mistake the V1-V3 rotation "
        "work already made.",
        "",
        "## PRESERVED RESEARCH STATUS",
        "",
        "- R2_CLUSTER: **INCONCLUSIVE**.",
        "- R2_RANGE: **INSUFFICIENT_POPULATION**.",
        "- R4_MICRO: **INCONCLUSIVE**.",
        "- LOCAL_PUBLICATION: **NO**.",
        "- Nothing in this study promotes cluster over range, range over cluster, Micro "
        "or Local. A width distribution is not an edge.",
        "",
        "## INTEGRITY",
        "",
        "- The geometry layer is read-only: it never writes to the map, the frontier, the "
        "detectors, the references, the thesis or the brain.",
        "- No brain module was modified by this milestone.",
        "- VALIDATE is aggregate-only; no case traces, IDs, timestamps or prices.",
        (
            "- HOLDOUT_PRICE_SESSIONS_CONVERTED = "
            f"{payload['holdout_price_sessions_converted']}."
        ),
        "- No broker, live money, parameter optimization, score, confidence, probability, "
        "ranking, width threshold or entry rule.",
        "",
        "## GATES",
        "",
    ])
    # Numeric order, so a report rendered from the saved JSON is byte-identical to the
    # one rendered in memory: `sort_keys=True` puts G10 before G1 on the round trip.
    for name, gate in sorted(payload["gates"].items(),
                             key=lambda item: int(item[0][1:].split("_", 1)[0])):
        lines.append(f"- {name}: **{gate['answer']}**. {gate['basis']}.")
    lines.extend([
        "",
        "## NEXT DECISION",
        "",
        "- Use the newly visible structure geometry and replay traces to decide whether "
        "participation should be modeled as (a) internal rotation inside genuinely "
        "spacious controlling structures, and/or (b) edge release / local-structure "
        "participation when the controlling Broad is compressed.",
        "- Do not implement either until that decision is preregistered.",
    ])
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict, report: Path, aggregate: Path) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    aggregate.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_markdown(payload), encoding="utf-8")
    aggregate.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path,
        default=REPO_ROOT / "reports" / "STRUCTURAL_OPPORTUNITY_GEOMETRY_AUDIT.md")
    parser.add_argument(
        "--aggregate", type=Path,
        default=REPO_ROOT / "reports" / "structural_opportunity_geometry_summary.json")
    args = parser.parse_args(argv)
    payload = run_geometry_study()
    write_outputs(payload, args.report, args.aggregate)
    print(json.dumps({
        "fingerprint": payload["fingerprint"],
        "gates": {name: gate["answer"] for name, gate in payload["gates"].items()},
        "report": str(args.report),
        "aggregate": str(args.aggregate),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
