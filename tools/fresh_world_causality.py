"""Independent prefix-world certification for the structural perception stack.

World A rebuilds from the fixed historical window and stops exactly at a cut. World B
starts from another fresh snapshot/frontier, captures a primitive canonical value at the
same cut, and only then continues. The two worlds never share domain objects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes import frontier as frontier_mod
from src.boxes.frontier import Frontier
from src.boxes.snapshot import MapSnapshot, build_snapshot
from src.domain.models import Candle
from src.learning.split import TEACH, VALIDATE
from src.livemap import frame as structural_frame
from src.livemap import thesis as thesis_mod
from tools.live_structure_truth import (
    AuditConfig,
    Block,
    EventObservation,
    assert_research_blocks,
    discover_event_catalog,
    load_research_episodes,
    make_blocks,
    observational_local_candidates,
    sample_event_observations,
)

SYMBOL = "NIFTY BANK"

CLASSIFICATIONS = (
    "FUTURE_LEAK",
    "MUTABLE_REFERENCE_LEAK",
    "IDENTITY_DRIFT",
    "PRESENTATION_ONLY",
    "EXPECTED_LIFECYCLE_DIFFERENCE",
    "BUG",
)
BLOCKING = frozenset({
    "FUTURE_LEAK",
    "MUTABLE_REFERENCE_LEAK",
    "IDENTITY_DRIFT",
    "BUG",
})
REQUIRED_EVENTS = (
    "major_birth",
    "forming_to_confirmed",
    "edge_approach",
    "break_attempt",
    "accepted_major_break",
    "re_entry",
    "revisit",
    "leaving",
    "new_major_structure",
    "micro_created",
    "micro_confirmed",
    "micro_break",
    "micro_collapse",
    "local_research_appearance",
    "local_research_disappearance",
    "simultaneous_cluster_range",
    "simultaneous_releases",
    "release_created",
    "release_still_held",
    "release_given_back",
    "reference_identity_change",
    "route_watch_change",
    "thesis_birth",
    "generation_change",
    "thesis_invalidation_or_reversal",
    "session_start",
)


@dataclass(frozen=True, slots=True)
class Cut:
    bucket: str
    block: int
    index: int
    at: str
    events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Mismatch:
    bucket: str
    block: int
    index: int
    at: str
    layer: str
    classification: str
    events: tuple[str, ...]
    prefix_fingerprint: str
    streaming_fingerprint: str


@dataclass(frozen=True, slots=True)
class CapturedTruth:
    value: dict
    retained: dict[str, Any]


RETAINED_LAYERS = (
    "frontier_reading",
    "map_state",
    "eye_state",
    "release_state",
    "reference_path",
    "live_thesis",
    "structural_frame",
)


def canonical(value: Any) -> Any:
    """Convert the full value into a deterministic tree of JSON primitives."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, float):
        return {"__float__": format(value, ".17g")}
    if is_dataclass(value) and not isinstance(value, type):
        out = {"__type__": type(value).__name__}
        for item in fields(value):
            out[item.name] = canonical(getattr(value, item.name))
        return out
    if isinstance(value, Mapping):
        return {
            str(key): canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [canonical(item) for item in value]
        return sorted(items, key=canonical_json)
    raise TypeError(f"unsupported canonical value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:16]


def primitive_only(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(primitive_only(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and primitive_only(item)
                   for key, item in value.items())
    return False


@contextmanager
def capture_choose(frontier: Frontier) -> Iterator[dict[int, tuple[Any, Any]]]:
    """Capture the cluster/range pair emitted by the frontier's existing call."""
    original = frontier_mod.choose
    emitted: dict[int, tuple[Any, Any]] = {}

    def wrapped(candles: Sequence[Candle], atr: Decimal, **kwargs):
        cluster, rng = original(candles, atr, **kwargs)
        emitted[frontier._i] = (cluster, rng)
        return cluster, rng

    frontier_mod.choose = wrapped
    try:
        yield emitted
    finally:
        frontier_mod.choose = original


def capture_truth(snapshot: MapSnapshot, frontier: Frontier,
                  chosen: tuple[Any, Any] | None) -> CapturedTruth:
    """Capture canonical truth plus the actual immutable trader-facing objects."""
    reading = frontier.readings[-1]
    frame = structural_frame.observe(snapshot, frontier)[-1]
    local = observational_local_candidates(frontier, reading)
    cluster, rng = chosen if chosen is not None else (None, None)
    identity = thesis_mod.identity_of(frame.thesis)
    raw = {
        "frozen_snapshot_structures": snapshot.structures(),
        "causally_available_structures": (
            tuple(snapshot.structures())
            + tuple(node for node in frontier.history() if node.end <= reading.index)
        ),
        "cluster_proposal": cluster,
        "range_proposal": rng,
        "frontier_reading": reading,
        "frontier_state": frontier.state,
        "frontier_current": frontier.current,
        "frontier_left": frontier.left,
        "frontier_candidate": frontier.candidate,
        "frontier_finalised": tuple(
            node for node in frontier.history() if node.end <= reading.index),
        "local_research": tuple(local),
        "micro_view": reading.micro,
        "map_state": frame.map,
        "eye_state": frame.eye,
        "release_state": frame.release,
        "simultaneous_releases": (
            frame.release.releases if frame.release.simultaneous else ()),
        "reference_path": frame.references,
        "live_thesis": frame.thesis,
        "thesis_identity": identity,
        "thesis_invalidation": {
            "rule": frame.thesis.invalidation,
            "price": frame.thesis.invalidation_price,
        },
        "structural_frame": frame,
    }
    captured = canonical(raw)
    if not primitive_only(captured):
        raise AssertionError("canonical capture retained a domain object")
    retained = {name: raw[name] for name in RETAINED_LAYERS}
    return CapturedTruth(value=captured, retained=retained)


def run_prefix_world(block: Block, cut_index: int) -> dict:
    """World A: fresh objects, feed only through the requested cut, then capture."""
    snapshot = build_snapshot(block.history, SYMBOL)
    frontier = Frontier(snapshot, block.history)
    live_count = cut_index - len(block.history) + 1
    if live_count <= 0 or live_count > len(block.live):
        raise ValueError(f"cut {cut_index} is outside block {block.ordinal}")
    with capture_choose(frontier) as choices:
        for candle in block.live[:live_count]:
            frontier.on_candle(candle)
        return capture_truth(snapshot, frontier, choices.get(cut_index)).value


def changed_paths(before: Any, after: Any, path: str = "") -> list[str]:
    """Locate nested mutations instead of reporting only a whole-object mismatch."""
    if type(before) is not type(after):
        return [path or "$"]
    if isinstance(before, dict):
        changed: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else str(key)
            if key not in before or key not in after:
                changed.append(child)
            else:
                changed.extend(changed_paths(before[key], after[key], child))
        return changed
    if isinstance(before, list):
        changed = []
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            if index >= len(before) or index >= len(after):
                changed.append(child)
            else:
                changed.extend(changed_paths(before[index], after[index], child))
        return changed
    return [] if before == after else [path or "$"]


def run_streaming_world(block: Block, cuts: Sequence[int]
                        ) -> tuple[dict[int, dict], list[dict]]:
    """World B: retain objects at cuts, feed the future, then serialize them again."""
    wanted = set(cuts)
    snapshot = build_snapshot(block.history, SYMBOL)
    frontier = Frontier(snapshot, block.history)
    captured: dict[int, dict] = {}
    retained_objects: dict[int, dict[str, Any]] = {}
    retained_before: dict[int, dict[str, Any]] = {}
    with capture_choose(frontier) as choices:
        for candle in block.live:
            reading = frontier.on_candle(candle)
            if reading.index in wanted:
                truth = capture_truth(snapshot, frontier, choices.get(reading.index))
                captured[reading.index] = truth.value
                retained_objects[reading.index] = truth.retained
                retained_before[reading.index] = {
                    layer: canonical(value) for layer, value in truth.retained.items()
                }

    changed: list[dict] = []
    for index, objects in retained_objects.items():
        for layer, retained in objects.items():
            before = retained_before[index][layer]
            after = canonical(retained)
            if before == after:
                continue
            changed.append({
                "index": index,
                "layer": layer,
                "paths": changed_paths(before, after),
                "before_fingerprint": fingerprint(before),
                "after_fingerprint": fingerprint(after),
            })
    missing = wanted - set(captured)
    if missing:
        raise ValueError(f"streaming world missed cuts {sorted(missing)}")
    return captured, changed


def _add_cut(target: dict[tuple[str, int, int], dict], block: Block,
             index: int, event: str) -> None:
    if index < len(block.history) or index >= len(block.history) + len(block.live):
        return
    candle = block.live[index - len(block.history)]
    key = (block.bucket, block.ordinal, index)
    item = target.setdefault(key, {
        "bucket": block.bucket,
        "block": block.ordinal,
        "index": index,
        "at": candle.close_time.isoformat(),
        "events": set(),
    })
    item["events"].add(event)


def select_cuts(blocks_by_bucket: dict[str, list[Block]], event_catalog: dict,
                *, ordinary_per_bucket: int = 8) -> list[Cut]:
    """Expand first/middle/last event occurrences to k-1/k/k+1."""
    selected: dict[tuple[str, int, int], dict] = {}
    for bucket in (TEACH, VALIDATE):
        by_ordinal = {block.ordinal: block for block in blocks_by_bucket[bucket]}
        catalog = event_catalog.get(bucket, {})
        for event in REQUIRED_EVENTS:
            observations = catalog.get(event, [])
            if not observations:
                continue
            for observation in sample_event_observations(observations):
                block = by_ordinal.get(observation.block)
                if block is None:
                    continue
                for offset in (-1, 0, 1):
                    _add_cut(selected, block, observation.index + offset, event)

        blocks = blocks_by_bucket[bucket]
        total = sum(len(block.live) for block in blocks)
        if not blocks or total == 0:
            continue
        for ordinal in range(1, ordinary_per_bucket + 1):
            position = (ordinal * (total - 1)) // (ordinary_per_bucket + 1)
            for block in blocks:
                if position < len(block.live):
                    _add_cut(selected, block, len(block.history) + position, "ordinary")
                    break
                position -= len(block.live)

    return [
        Cut(
            bucket=item["bucket"], block=item["block"], index=item["index"],
            at=item["at"], events=tuple(sorted(item["events"])),
        )
        for item in sorted(selected.values(), key=lambda value: (
            value["bucket"], value["block"], value["index"]))
    ]


def event_sampling_facts(event_catalog: dict) -> tuple[dict, dict]:
    covered: dict[str, list[str]] = {}
    sampled: dict[str, dict[str, int]] = {}
    for bucket in (TEACH, VALIDATE):
        catalog = event_catalog.get(bucket, {})
        covered[bucket] = [event for event in REQUIRED_EVENTS if catalog.get(event)]
        sampled[bucket] = {
            event: len(sample_event_observations(catalog[event]))
            for event in covered[bucket]
        }
    return covered, sampled


_INDEX_FIELDS = frozenset({
    "index", "start", "end", "built_at_index", "confirmed_at", "broken_at",
    "break_index", "evidence_from",
})


def contains_future_index(value: Any, cut_index: int, key: str = "") -> bool:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if (child_key in _INDEX_FIELDS and isinstance(child, int)
                    and child > cut_index):
                return True
            if contains_future_index(child, cut_index, child_key):
                return True
    elif isinstance(value, list):
        return any(contains_future_index(item, cut_index, key) for item in value)
    return False


def _without_identity(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_identity(item)
            for key, item in value.items()
            if not (key == "id" or key.endswith("_id") or key == "thesis_identity")
        }
    if isinstance(value, list):
        return [_without_identity(item) for item in value]
    return value


def classify_mismatch(prefix: Any, streaming: Any, cut_index: int) -> str:
    if contains_future_index(prefix, cut_index) or contains_future_index(streaming, cut_index):
        return "FUTURE_LEAK"
    if _without_identity(prefix) == _without_identity(streaming):
        return "IDENTITY_DRIFT"
    return "BUG"


def compare_cut(cut: Cut, prefix: dict, streaming: dict) -> list[Mismatch]:
    out: list[Mismatch] = []
    for layer in sorted(set(prefix) | set(streaming)):
        before = prefix.get(layer)
        normal = streaming.get(layer)
        if before == normal:
            continue
        out.append(Mismatch(
            bucket=cut.bucket,
            block=cut.block,
            index=cut.index,
            at=cut.at,
            layer=layer,
            classification=classify_mismatch(before, normal, cut.index),
            events=cut.events,
            prefix_fingerprint=fingerprint(before),
            streaming_fingerprint=fingerprint(normal),
        ))
    return out


def assert_validate_aggregate_only(result: dict) -> None:
    """Case-level public sections must contain TEACH records only."""
    for section in ("cuts", "mismatches", "mutable_reference_details"):
        if any(item.get("bucket") == VALIDATE for item in result.get(section, [])):
            raise AssertionError(f"{section} exposed a case-level validate record")
    if result.get("validate_exposure") != "aggregate_only":
        raise AssertionError("validate exposure policy is missing")


def run_certification(audit_payload: dict, *, ordinary_per_bucket: int = 8) -> dict:
    config_data = audit_payload["config"]
    config = AuditConfig(
        history=int(config_data["history"]),
        live=int(config_data["live"]),
        max_blocks=config_data.get("max_blocks"),
        prefix_examples=int(config_data.get("prefix_examples", 12)),
        trace_examples=int(config_data.get("trace_examples", 8)),
    )
    episodes_by_bucket, _source_population = load_research_episodes()
    blocks_by_bucket = {
        bucket: make_blocks(episodes, bucket, config)
        for bucket, episodes in episodes_by_bucket.items()
    }
    assert_research_blocks(blocks_by_bucket)
    event_catalog = discover_event_catalog(blocks_by_bucket, config)
    cuts = select_cuts(
        blocks_by_bucket,
        event_catalog,
        ordinary_per_bucket=ordinary_per_bucket,
    )
    event_types_covered, event_occurrences_sampled = event_sampling_facts(event_catalog)
    cuts_by_block: dict[tuple[str, int], list[Cut]] = defaultdict(list)
    for cut in cuts:
        cuts_by_block[(cut.bucket, cut.block)].append(cut)

    streaming: dict[tuple[str, int, int], dict] = {}
    mutable_reference_leaks: list[dict] = []
    by_bucket_ordinal = {
        bucket: {block.ordinal: block for block in blocks}
        for bucket, blocks in blocks_by_bucket.items()
    }
    for (bucket, ordinal), block_cuts in cuts_by_block.items():
        block = by_bucket_ordinal[bucket][ordinal]
        values, changed = run_streaming_world(block, [cut.index for cut in block_cuts])
        for cut in block_cuts:
            streaming[(bucket, ordinal, cut.index)] = values[cut.index]
        for leak in changed:
            mutable_reference_leaks.append({
                "bucket": bucket, "block": ordinal,
                "classification": "MUTABLE_REFERENCE_LEAK",
                **leak,
            })

    mismatches: list[Mismatch] = []
    for cut in cuts:
        block = by_bucket_ordinal[cut.bucket][cut.block]
        prefix = run_prefix_world(block, cut.index)
        normal = streaming[(cut.bucket, cut.block, cut.index)]
        mismatches.extend(compare_cut(cut, prefix, normal))

    classifications = Counter(item.classification for item in mismatches)
    classifications["MUTABLE_REFERENCE_LEAK"] += len(mutable_reference_leaks)
    for name in CLASSIFICATIONS:
        classifications.setdefault(name, 0)

    cuts_by_event: dict[str, Counter[str]] = {
        TEACH: Counter(), VALIDATE: Counter(),
    }
    for cut in cuts:
        for event in cut.events:
            cuts_by_event[cut.bucket][event] += 1
    cuts_by_bucket = Counter(cut.bucket for cut in cuts)
    mismatch_fields_by_bucket = Counter(item.bucket for item in mismatches)
    mismatch_fields_by_bucket.update(
        leak["bucket"] for leak in mutable_reference_leaks)
    mismatch_cuts_by_bucket = {
        bucket: len(
            {(item.block, item.index) for item in mismatches if item.bucket == bucket}
            | {(item["block"], item["index"]) for item in mutable_reference_leaks
               if item["bucket"] == bucket}
        )
        for bucket in (TEACH, VALIDATE)
    }
    classification_by_bucket = {
        bucket: Counter(item.classification for item in mismatches
                        if item.bucket == bucket)
        for bucket in (TEACH, VALIDATE)
    }
    layer_by_bucket = {
        bucket: Counter(item.layer for item in mismatches if item.bucket == bucket)
        for bucket in (TEACH, VALIDATE)
    }
    for leak in mutable_reference_leaks:
        classification_by_bucket[leak["bucket"]]["MUTABLE_REFERENCE_LEAK"] += 1
        layer_by_bucket[leak["bucket"]][leak["layer"]] += 1
    blocking_count = sum(classifications[name] for name in BLOCKING)
    result = {
        "config": {
            "history": config.history,
            "live": config.live,
            "ordinary_per_bucket": ordinary_per_bucket,
        },
        "source_audit_fingerprint": audit_payload.get("fingerprint"),
        "available_population": audit_payload.get("available_population", {}),
        "audited_population": audit_payload.get("audited_population", {}),
        "holdout_access_semantics": audit_payload.get("holdout_access_semantics", {}),
        "replay_integrity": {
            bucket: {
                "eligible_episodes": len(episodes_by_bucket[bucket]),
                "blocks": len(blocks_by_bucket[bucket]),
                "source_contiguous": True,
            }
            for bucket in (TEACH, VALIDATE)
        },
        "total_cuts": len(cuts),
        "cuts_by_bucket": dict(sorted(cuts_by_bucket.items())),
        "cuts_by_event": {
            bucket: dict(sorted(cuts_by_event[bucket].items()))
            for bucket in (TEACH, VALIDATE)
        },
        "event_types_covered": event_types_covered,
        "event_occurrences_sampled": event_occurrences_sampled,
        "unobserved_event_types": {
            bucket: [event for event in REQUIRED_EVENTS
                     if not event_catalog.get(bucket, {}).get(event)]
            for bucket in (TEACH, VALIDATE)
        },
        "mismatch_cuts": mismatch_cuts_by_bucket,
        "mismatch_fields": {
            bucket: mismatch_fields_by_bucket[bucket]
            for bucket in (TEACH, VALIDATE)
        },
        "mismatch_classification": {
            name: classifications[name] for name in CLASSIFICATIONS
        },
        "mismatch_classification_by_bucket": {
            bucket: {name: classification_by_bucket[bucket][name]
                     for name in CLASSIFICATIONS}
            for bucket in (TEACH, VALIDATE)
        },
        "validate_mismatch_aggregate": {
            "layers": dict(sorted(layer_by_bucket[VALIDATE].items())),
            "classifications": {
                name: classification_by_bucket[VALIDATE][name]
                for name in CLASSIFICATIONS
            },
        },
        "future_leaks": classifications["FUTURE_LEAK"],
        "mutable_reference_leaks": classifications["MUTABLE_REFERENCE_LEAK"],
        "identity_drift": classifications["IDENTITY_DRIFT"],
        "bugs": classifications["BUG"],
        "determinism_result": "PASS" if blocking_count == 0 else "FAIL",
        "retained_object_layers": list(RETAINED_LAYERS),
        "cuts": [asdict(cut) for cut in cuts if cut.bucket == TEACH],
        "mismatches": [asdict(item) for item in mismatches if item.bucket == TEACH],
        "mutable_reference_details": [item for item in mutable_reference_leaks
                                      if item["bucket"] == TEACH],
        "validate_exposure": "aggregate_only",
    }
    assert_validate_aggregate_only(result)
    stable = dict(result)
    stable.pop("fingerprint", None)
    result["fingerprint"] = fingerprint(canonical(stable))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--ordinary-per-bucket", type=int, default=8)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)

    audit_payload = json.loads(args.audit_json.read_text(encoding="utf-8"))
    result = run_certification(
        audit_payload,
        ordinary_per_bucket=args.ordinary_per_bucket,
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["determinism_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
