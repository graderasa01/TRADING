"""Research-only live structure truth audit.

This module measures the live structural stack without changing production behavior.
It deliberately lives under ``tools/`` and only observes:

* production ``Frontier.on_candle`` and its real ``adaptive.choose`` calls;
* an observational local scan that reuses the existing detector/currency/containment
  rules but never admits a node;
* fresh historical-prefix rebuilds for a bounded set of simultaneous cluster/range
  cases.

No execution, broker, setup, stop, target, probability, rank, or score is produced here.
The detector's existing internal ``Proposal.score`` may be copied as source evidence, but
this tool never turns it into trader-facing importance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes import adaptive
from src.boxes import frontier as frontier_mod
from src.boxes.adaptive import Proposal, WINDOWS, overlap
from src.boxes.frontier import Frontier, Reading
from src.boxes.hierarchy import Node
from src.boxes.micro import CONFIRMED as MICRO_CONFIRMED
from src.boxes.snapshot import SAME_NODE_OVERLAP, MapSnapshot, build_snapshot
from src.boxes.structure import STRUCTURE_KINDS, atr_at, tol_at
from src.domain.models import Candle
from src.feed.aggregator import Aggregator
from src.feed.replay_feed import ReplayFeed
from src.learning.split import TEACH, VALIDATE, load_split
from src.livemap.interpreter import Interpreter
SYMBOL = "NIFTY BANK"


@dataclass(frozen=True, slots=True)
class AuditConfig:
    history: int = 400
    live: int = 300
    max_blocks: int | None = None
    prefix_examples: int = 12
    trace_examples: int = 8


@dataclass(frozen=True, slots=True)
class Block:
    bucket: str
    ordinal: int
    start_index: int
    history: tuple[Candle, ...]
    live: tuple[Candle, ...]


@dataclass(frozen=True, slots=True)
class Band:
    low: Decimal
    high: Decimal

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    def as_text(self) -> str:
        return f"{float(self.low):,.1f}-{float(self.high):,.1f}"


@dataclass(frozen=True, slots=True)
class ChooseObservation:
    bucket: str
    block: int
    index: int
    at: str
    price: Decimal
    cluster: Band | None
    range: Band | None
    cluster_window: int | None
    range_window: int | None
    cluster_current: bool
    range_current: bool
    selected_kind: str | None
    selected_band: Band | None
    known_match: str | None
    relation: str


@dataclass(frozen=True, slots=True)
class LocalObservation:
    bucket: str
    block: int
    index: int
    at: str
    price: Decimal
    parent_id: str
    parent_kind: str
    parent_band: Band
    candidate_kind: str
    candidate_band: Band
    candidate_window: int
    production_micro_id: str | None
    production_micro_state: str | None
    production_micro_band: Band | None
    micro_relation: str


@dataclass(frozen=True, slots=True)
class PrefixComparison:
    bucket: str
    block: int
    index: int
    at: str
    price: Decimal
    cluster_band: Band
    range_band: Band
    historical_tight_id: str | None
    historical_tight_kind: str | None
    historical_tight_band: Band | None
    historical_parent_id: str | None
    live_current_kind: str | None
    live_current_band: Band | None
    live_parent_id: str | None
    micro_id: str | None
    micro_band: Band | None
    classification: str


@dataclass(frozen=True, slots=True)
class HolderObservation:
    bucket: str
    block: int
    index: int
    at: str
    live_id: str
    live_kind: str
    live_band: Band
    holders: tuple[str, ...]
    tightest_holder: str | None
    deterministic: bool


@dataclass(frozen=True, slots=True)
class AuditResult:
    config: dict
    populations: dict
    counts: dict
    examples: dict
    timings: dict
    fingerprint: str


def _band(p: Proposal | Node | None) -> Band | None:
    if p is None:
        return None
    return Band(p.low, p.high)


def _band_from_pair(pair: tuple[Decimal, Decimal] | None) -> Band | None:
    if pair is None:
        return None
    return Band(pair[0], pair[1])


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


def _serialise(obj):
    return json.loads(json.dumps(obj, default=_decimal_default, sort_keys=True))


def _contains(outer: Band, inner: Band, tol: Decimal) -> bool:
    """Same containment shape as hierarchy/micro: inside edges and strictly narrower."""
    return outer.low - tol <= inner.low and inner.high <= outer.high + tol and inner.width < outer.width


def band_relation(cluster: Band | None, rng: Band | None, tol: Decimal = Decimal("0")) -> str:
    if cluster is None or rng is None:
        return "not_both"
    if _contains(rng, cluster, tol):
        return "cluster_inside_range"
    if _contains(cluster, rng, tol):
        return "range_inside_cluster"
    ov = overlap((cluster.low, cluster.high), (rng.low, rng.high))
    if ov > 0:
        return "partial_overlap"
    return "disjoint"


def proposal_relation(a: Band | None, b: Band | None, tol: Decimal) -> str:
    if a is None or b is None:
        return "absent"
    if abs(a.low - b.low) <= tol and abs(a.high - b.high) <= tol:
        return "same"
    ov = overlap((a.low, a.high), (b.low, b.high))
    if ov >= SAME_NODE_OVERLAP:
        return "overlapping"
    return "different"


def holder_candidates(band: Band, known: Sequence[Node], tol: Decimal) -> tuple[list[Node], Node | None, bool]:
    holders = [n for n in known if n.kind in STRUCTURE_KINDS and _contains(_band(n), band, tol)]  # type: ignore[arg-type]
    if not holders:
        return [], None, True
    ordered = sorted(holders, key=lambda n: (n.width, n.end, n.id))
    tightest_width = ordered[0].width
    tied = [n for n in ordered if n.width == tightest_width]
    return holders, ordered[0], len(tied) == 1


def aggregate_m5_by_bucket() -> tuple[dict[str, tuple[Candle, ...]], dict[str, int]]:
    split = load_split()
    by_bucket: dict[str, list[Candle]] = {TEACH: [], VALIDATE: []}
    sessions: Counter[str] = Counter()
    feed = ReplayFeed(SYMBOL, on_gap="skip")

    for session in feed.sessions():
        bucket = split.bucket_of(session.day)
        if bucket not in by_bucket:
            continue
        agg = Aggregator(htf=("5m",))
        m5: list[Candle] = []
        for candle in session.candles:
            update = agg.on_candle(candle)
            if update.m5 is not None:
                m5.append(update.m5)
        by_bucket[bucket].extend(m5)
        sessions[bucket] += 1

    return {k: tuple(v) for k, v in by_bucket.items()}, dict(sessions)


def make_blocks(candles: Sequence[Candle], bucket: str, config: AuditConfig) -> list[Block]:
    span = config.history + config.live
    blocks: list[Block] = []
    for ordinal, start in enumerate(range(0, len(candles) - span + 1, span), start=1):
        if config.max_blocks is not None and len(blocks) >= config.max_blocks:
            break
        blocks.append(Block(
            bucket=bucket,
            ordinal=ordinal,
            start_index=start,
            history=tuple(candles[start:start + config.history]),
            live=tuple(candles[start + config.history:start + span]),
        ))
    return blocks


def observational_local_candidates(frontier: Frontier, reading: Reading) -> list[Proposal]:
    """Look inside current with existing detector/currency/containment only.

    This is intentionally not MicroObserver. Micro bounds windows by the parent's own
    detector window. This research scan asks a different observational question: if the
    already-existing major detector is simply run over the current visit span, is there a
    stable narrower structure that the live one-current Frontier cannot publish?
    """
    parent = frontier.current
    if parent is None or reading.band is None:
        return []

    i = reading.index
    span = frontier.candles[parent.evidence_from:i + 1]
    windows = [n for n in WINDOWS if n <= len(span)]
    if not windows:
        return []
    atr = atr_at(frontier.candles, i)
    if atr <= 0:
        return []

    tol = tol_at(frontier.candles, i, frontier.tol_atr)
    cluster, rng = adaptive.choose(span, atr, windows=windows,
                                   tol_atr=frontier.tol_atr,
                                   min_score=frontier.min_score,
                                   session_aware=True)
    found = []
    for p in (cluster, rng):
        if p is None:
            continue
        if not _contains(Band(parent.low, parent.high), Band(p.low, p.high), tol):
            continue
        if not frontier._band_is_current(p.low, p.high, tol):
            continue
        found.append(p)
    return found


def classify_prefix(prefix_snapshot: MapSnapshot, reading: Reading,
                    cluster: Band, rng: Band, tol: Decimal) -> PrefixComparison:
    price = reading.measurements.get("_price_decimal")
    if not isinstance(price, Decimal):
        raise ValueError("reading must carry _price_decimal for prefix classification")

    hist_tight = prefix_snapshot.containing(price, tol)
    hist_parent = prefix_snapshot.by_id(hist_tight.parent) if hist_tight and hist_tight.parent else None
    live_band = _band_from_pair(reading.band)
    micro_band = (_band_from_pair((reading.micro.micro_low, reading.micro.micro_high))
                  if reading.micro and reading.micro.micro_low is not None
                  and reading.micro.micro_high is not None else None)
    live_parent = hist_parent if reading.node_id and prefix_snapshot.by_id(reading.node_id) else None

    if hist_tight is None and live_band is None:
        classification = "INSUFFICIENT_INFORMATION"
    elif hist_tight is not None and live_band is not None:
        hist_band = _band(hist_tight)
        if proposal_relation(hist_band, live_band, tol) == "same":
            classification = "SAME_SEMANTICS"
        elif hist_tight.kind == "cluster" and reading.node_kind == "range" and _contains(live_band, hist_band, tol):  # type: ignore[arg-type]
            classification = "LIVE_SCALE_COLLAPSE"
        elif hist_tight.end > reading.index:
            classification = "HISTORICAL_RETROSPECTION_ONLY"
        else:
            classification = "PRESENTATION_ONLY"
    elif hist_tight is not None:
        classification = "HISTORICAL_RETROSPECTION_ONLY"
    else:
        classification = "TRUE_CAUSAL_DIVERGENCE"

    return PrefixComparison(
        bucket="",
        block=0,
        index=reading.index,
        at="",
        price=price,
        cluster_band=cluster,
        range_band=rng,
        historical_tight_id=hist_tight.id if hist_tight else None,
        historical_tight_kind=hist_tight.kind if hist_tight else None,
        historical_tight_band=_band(hist_tight),
        historical_parent_id=hist_parent.id if hist_parent else None,
        live_current_kind=reading.node_kind,
        live_current_band=live_band,
        live_parent_id=live_parent.id if live_parent else None,
        micro_id=reading.micro.micro_id if reading.micro else None,
        micro_band=micro_band,
        classification=classification,
    )


def _with_price(reading: Reading, price: Decimal) -> Reading:
    measurements = dict(reading.measurements)
    measurements["_price_decimal"] = price
    return Reading(
        index=reading.index,
        state=reading.state,
        interaction=reading.interaction,
        node_id=reading.node_id,
        node_kind=reading.node_kind,
        node_status=reading.node_status,
        band=reading.band,
        break_level_up=reading.break_level_up,
        break_level_down=reading.break_level_down,
        left_id=reading.left_id,
        left_edge=reading.left_edge,
        left_low=reading.left_low,
        left_high=reading.left_high,
        left_kind=reading.left_kind,
        arrived_from=reading.arrived_from,
        arrived_direction=reading.arrived_direction,
        bars_in_transit=reading.bars_in_transit,
        measurements=measurements,
        candidate=reading.candidate,
        evidence=reading.evidence,
        micro=reading.micro,
    )


def run_block(block: Block, config: AuditConfig, counters: dict[str, Counter],
              examples: dict[str, list], timings: Counter[str]) -> None:
    snapshot = build_snapshot(block.history, SYMBOL)
    frontier = Frontier(snapshot, block.history)
    interpreter = Interpreter(snapshot, frontier)
    current_choose: list[ChooseObservation] = []
    original_choose = frontier_mod.choose

    def wrapped_choose(candles: Sequence[Candle], atr: Decimal, **kwargs):
        cluster, rng = adaptive.choose(candles, atr, **kwargs)
        i = frontier._i
        tol = frontier._tol()
        cluster_current = cluster is not None and frontier._is_current(cluster, tol)
        range_current = rng is not None and frontier._is_current(rng, tol)
        firm = next((p for p in (rng, cluster)
                     if p is not None and frontier._is_current(p, tol)), None)
        known = frontier._known_match(firm) if firm is not None else None
        obs = ChooseObservation(
            bucket=block.bucket,
            block=block.ordinal,
            index=i,
            at=frontier.candles[i].close_time.isoformat(),
            price=frontier.candles[i].c,
            cluster=_band(cluster),
            range=_band(rng),
            cluster_window=cluster.window if cluster else None,
            range_window=rng.window if rng else None,
            cluster_current=cluster_current,
            range_current=range_current,
            selected_kind=firm.kind if firm else None,
            selected_band=_band(firm),
            known_match=known.id if known else None,
            relation=band_relation(_band(cluster), _band(rng), tol),
        )
        current_choose.append(obs)
        return cluster, rng

    try:
        frontier_mod.choose = wrapped_choose
        for candle in block.live:
            before_ids = {n.id for n in frontier.finalised}
            t0 = perf_counter()
            reading = frontier.on_candle(candle)
            timings["frontier_seconds"] += perf_counter() - t0

            choose_obs = current_choose[-1] if current_choose and current_choose[-1].index == reading.index else None
            if choose_obs is not None:
                c = choose_obs.cluster is not None
                r = choose_obs.range is not None
                key = "BOTH" if c and r else "CLUSTER_ONLY" if c else "RANGE_ONLY" if r else "NEITHER"
                counters["choose"][key] += 1
                if c and r:
                    counters["simultaneous"]["BOTH_DETECTED"] += 1
                    counters["simultaneous"][choose_obs.relation] += 1
                    if choose_obs.cluster_current and choose_obs.range_current:
                        counters["simultaneous"]["BOTH_CURRENT"] += 1
                        if choose_obs.selected_kind == "range":
                            counters["simultaneous"]["LIVE_SELECTED_RANGE"] += 1
                        elif choose_obs.selected_kind == "cluster":
                            counters["simultaneous"]["LIVE_SELECTED_CLUSTER"] += 1
                    else:
                        counters["simultaneous"]["BOTH_NOT_BOTH_CURRENT"] += 1
                    if choose_obs.relation in {"cluster_inside_range", "range_inside_cluster"}:
                        counters["simultaneous"]["BOTH_WITH_CONTAINMENT"] += 1
                    else:
                        counters["simultaneous"]["BOTH_WITHOUT_CONTAINMENT"] += 1
                    if len(examples["simultaneous"]) < config.trace_examples:
                        examples["simultaneous"].append(asdict(choose_obs))

                if (c and r and choose_obs.cluster_current and choose_obs.range_current
                        and len(examples["prefix"]) < config.prefix_examples):
                    t1 = perf_counter()
                    prefix_snapshot = build_snapshot(frontier.candles[:reading.index + 1], SYMBOL)
                    timings["prefix_rebuild_seconds"] += perf_counter() - t1
                    tol = frontier._tol()
                    comparison = classify_prefix(
                        prefix_snapshot,
                        _with_price(reading, candle.c),
                        choose_obs.cluster,
                        choose_obs.range,
                        tol,
                    )
                    comparison = PrefixComparison(
                        bucket=block.bucket,
                        block=block.ordinal,
                        index=comparison.index,
                        at=candle.close_time.isoformat(),
                        price=comparison.price,
                        cluster_band=comparison.cluster_band,
                        range_band=comparison.range_band,
                        historical_tight_id=comparison.historical_tight_id,
                        historical_tight_kind=comparison.historical_tight_kind,
                        historical_tight_band=comparison.historical_tight_band,
                        historical_parent_id=comparison.historical_parent_id,
                        live_current_kind=comparison.live_current_kind,
                        live_current_band=comparison.live_current_band,
                        live_parent_id=comparison.live_parent_id,
                        micro_id=comparison.micro_id,
                        micro_band=comparison.micro_band,
                        classification=comparison.classification,
                    )
                    counters["prefix"][comparison.classification] += 1
                    examples["prefix"].append(asdict(comparison))

            t2 = perf_counter()
            local = observational_local_candidates(frontier, reading)
            timings["local_scan_seconds"] += perf_counter() - t2
            micro_present = bool(reading.micro and reading.micro.micro_id)
            micro_confirmed = bool(reading.micro and reading.micro.micro_state == MICRO_CONFIRMED)
            if local:
                counters["local"]["LOCAL_FOUND"] += 1
            else:
                counters["local"]["LOCAL_ABSENT"] += 1
            counters["micro_matrix"][
                ("LOCAL_FOUND" if local else "LOCAL_ABSENT")
                + " + "
                + ("MICRO_FOUND" if micro_present else "MICRO_ABSENT")
            ] += 1
            if micro_confirmed:
                counters["local"]["MICRO_CONFIRMED"] += 1

            if local:
                parent = frontier.current
                first = local[0]
                micro_band = (_band_from_pair((reading.micro.micro_low, reading.micro.micro_high))
                              if reading.micro and reading.micro.micro_low is not None
                              and reading.micro.micro_high is not None else None)
                tol = frontier._tol()
                obs = LocalObservation(
                    bucket=block.bucket,
                    block=block.ordinal,
                    index=reading.index,
                    at=candle.close_time.isoformat(),
                    price=candle.c,
                    parent_id=parent.id if parent else "",
                    parent_kind=parent.kind if parent else "",
                    parent_band=Band(parent.low, parent.high) if parent else Band(Decimal(0), Decimal(0)),
                    candidate_kind=first.kind,
                    candidate_band=Band(first.low, first.high),
                    candidate_window=first.window,
                    production_micro_id=reading.micro.micro_id if reading.micro else None,
                    production_micro_state=reading.micro.micro_state if reading.micro else None,
                    production_micro_band=micro_band,
                    micro_relation=proposal_relation(Band(first.low, first.high), micro_band, tol),
                )
                counters["local_relations"][obs.micro_relation] += 1
                if len(examples["local"]) < config.trace_examples:
                    examples["local"].append(asdict(obs))

            if reading.interaction in {"NEW_CLUSTER", "NEW_RANGE"} and frontier.current is not None:
                live = frontier.current
                live_band = Band(live.low, live.high)
                known = list(snapshot.structures()) + [n for n in frontier.history() if n.end <= reading.index]
                holders, tightest, deterministic = holder_candidates(live_band, known, frontier._tol())
                counters["holders"]["births"] += 1
                if holders:
                    counters["holders"]["inside_known_holder"] += 1
                    if deterministic:
                        counters["holders"]["deterministic"] += 1
                    else:
                        counters["holders"]["ambiguous"] += 1
                else:
                    counters["holders"]["no_holder"] += 1
                holder_obs = HolderObservation(
                    bucket=block.bucket,
                    block=block.ordinal,
                    index=reading.index,
                    at=candle.close_time.isoformat(),
                    live_id=live.id,
                    live_kind=live.kind,
                    live_band=live_band,
                    holders=tuple(n.id for n in sorted(holders, key=lambda n: (n.width, n.id))),
                    tightest_holder=tightest.id if tightest else None,
                    deterministic=deterministic,
                )
                if len(examples["holders"]) < config.trace_examples:
                    examples["holders"].append(asdict(holder_obs))

            if frontier.finalised and {n.id for n in frontier.finalised} != before_ids:
                counters["live"]["finalised"] += len({n.id for n in frontier.finalised} - before_ids)

            state = interpreter.read(reading)
            for role, ref in (
                ("ABOVE_NEXT", state.above.next),
                ("ABOVE_MAJOR", state.above.next_major),
                ("BELOW_NEXT", state.below.next),
                ("BELOW_MAJOR", state.below.next_major),
            ):
                if ref is None:
                    continue
                counters[f"reference_age_{role}"]["n"] += 1
                counters[f"reference_age_{role}"]["sum"] += ref.age
                counters[f"reference_age_{role}"]["max"] = max(counters[f"reference_age_{role}"]["max"], ref.age)

        # End-of-block structural depth facts are historical-only and do not read holdout.
        counters["depth"]["snapshot_nodes"] += len(snapshot.structures())
        counters["depth"]["snapshot_nested"] += sum(1 for n in snapshot.structures() if n.parent is not None)
        counters["depth"]["max_snapshot_depth"] = max(
            counters["depth"]["max_snapshot_depth"],
            max((n.depth for n in snapshot.structures()), default=0),
        )
        counters["live"]["micro_created"] += sum(
            1 for r in frontier.readings if r.micro and "MICRO_CREATED" in r.micro.events
        )
        counters["live"]["micro_confirmed"] += sum(
            1 for r in frontier.readings if r.micro and "MICRO_CONFIRMED" in r.micro.events
        )
        counters["live"]["micro_breaks"] += sum(
            1 for r in frontier.readings
            if r.micro and (("MICRO_BREAK_UP" in r.micro.events) or ("MICRO_BREAK_DOWN" in r.micro.events))
        )
    finally:
        frontier_mod.choose = original_choose


def _counter_dict(counter: Counter) -> dict:
    return {str(k): v for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def run_audit(config: AuditConfig) -> AuditResult:
    timings: Counter[str] = Counter()
    t0 = perf_counter()
    candles_by_bucket, sessions = aggregate_m5_by_bucket()
    timings["load_seconds"] = perf_counter() - t0

    counters: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list] = defaultdict(list)
    populations: dict[str, dict] = {}
    blocks_by_bucket = {
        bucket: make_blocks(candles, bucket, config)
        for bucket, candles in candles_by_bucket.items()
    }

    for bucket, candles in candles_by_bucket.items():
        populations[bucket] = {
            "sessions": sessions.get(bucket, 0),
            "m5_candles": len(candles),
            "blocks": len(blocks_by_bucket[bucket]),
        }

    t_run = perf_counter()
    for bucket in (TEACH, VALIDATE):
        for block in blocks_by_bucket[bucket]:
            run_block(block, config, counters, examples, timings)
    timings["audit_seconds"] = perf_counter() - t_run
    timings["total_seconds"] = perf_counter() - t0

    counts = {name: _counter_dict(counter) for name, counter in sorted(counters.items())}
    payload = {
        "config": asdict(config),
        "populations": populations,
        "counts": counts,
        "examples": _serialise(dict(examples)),
        "timings": {k: round(v, 6) for k, v in sorted(timings.items())},
    }
    deterministic_payload = {
        "config": payload["config"],
        "populations": payload["populations"],
        "counts": payload["counts"],
        "examples": payload["examples"],
    }
    fingerprint = json.dumps(deterministic_payload, sort_keys=True, default=_decimal_default)
    checksum = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return AuditResult(
        config=payload["config"],
        populations=populations,
        counts=counts,
        examples=payload["examples"],
        timings=payload["timings"],
        fingerprint=checksum,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=int, default=400)
    parser.add_argument("--live", type=int, default=300)
    parser.add_argument("--max-blocks", type=int, default=None)
    parser.add_argument("--prefix-examples", type=int, default=12)
    parser.add_argument("--trace-examples", type=int, default=8)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    result = run_audit(AuditConfig(
        history=args.history,
        live=args.live,
        max_blocks=args.max_blocks,
        prefix_examples=args.prefix_examples,
        trace_examples=args.trace_examples,
    ))
    payload = asdict(result)
    text = json.dumps(payload, indent=2, sort_keys=True, default=_decimal_default)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
