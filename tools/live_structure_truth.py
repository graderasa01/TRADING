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
from typing import Callable, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boxes import adaptive
from src.boxes import frontier as frontier_mod
from src.boxes.adaptive import Proposal, WINDOWS, overlap
from src.boxes.frontier import Frontier, Reading
from src.boxes.hierarchy import Node
from src.boxes.micro import (
    CONFIRMED as MICRO_CONFIRMED,
    MICRO_BREAK_DOWN,
    MICRO_BREAK_UP,
    MICRO_COLLAPSED,
    MICRO_CONFIRMED as MICRO_CONFIRMED_EVENT,
    MICRO_CREATED,
)
from src.boxes.snapshot import SAME_NODE_OVERLAP, MapSnapshot, build_snapshot
from src.boxes.structure import STRUCTURE_KINDS, atr_at, tol_at
from src.domain.models import Candle
from src.feed.aggregator import Aggregator
from src.feed.replay_feed import ReplayFeed, Session
from src.learning.split import TEACH, VALIDATE, load_split
from src.livemap import frame as structural_frame
from src.livemap import thesis as thesis_mod
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
    episode: int = 1
    source_start_ordinal: int = 0
    source_end_ordinal: int = 0
    source_session_ordinals: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceSessionRecord:
    source_ordinal: int
    day: date
    bucket: str
    m5: tuple[Candle, ...] | None


@dataclass(frozen=True, slots=True)
class ResearchEpisode:
    bucket: str
    ordinal: int
    sessions: tuple[SourceSessionRecord, ...]

    @property
    def candles(self) -> tuple[Candle, ...]:
        return tuple(candle for session in self.sessions for candle in session.m5 or ())

    @property
    def source_start_ordinal(self) -> int:
        return self.sessions[0].source_ordinal

    @property
    def source_end_ordinal(self) -> int:
        return self.sessions[-1].source_ordinal


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
class EventObservation:
    event: str
    bucket: str
    block: int
    index: int
    at: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    config: dict
    holdout_access_semantics: dict
    available_population: dict
    audited_population: dict
    counts: dict
    events: dict
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


def partition_source_sessions(
        records: Sequence[SourceSessionRecord]) -> dict[str, tuple[ResearchEpisode, ...]]:
    """Create maximal replayable runs without deleting intervening source sessions."""
    episodes: dict[str, list[ResearchEpisode]] = {TEACH: [], VALIDATE: []}
    current: list[SourceSessionRecord] = []

    def flush() -> None:
        if not current:
            return
        bucket = current[0].bucket
        episodes[bucket].append(ResearchEpisode(
            bucket=bucket,
            ordinal=len(episodes[bucket]) + 1,
            sessions=tuple(current),
        ))
        current.clear()

    for record in sorted(records, key=lambda item: item.source_ordinal):
        replayable = record.bucket in episodes and record.m5 is not None
        adjacent = bool(
            current
            and record.bucket == current[-1].bucket
            and record.source_ordinal == current[-1].source_ordinal + 1
        )
        if not replayable:
            flush()
            continue
        if current and not adjacent:
            flush()
        current.append(record)
    flush()

    for bucket, bucket_episodes in episodes.items():
        for episode in bucket_episodes:
            ordinals = tuple(item.source_ordinal for item in episode.sessions)
            if episode.bucket != bucket or ordinals != tuple(range(
                    ordinals[0], ordinals[-1] + 1)):
                raise AssertionError("research episode is not source-session contiguous")
            if any(item.bucket != bucket or item.m5 is None
                   for item in episode.sessions):
                raise AssertionError("research episode crossed a bucket or replay barrier")
    return {bucket: tuple(items) for bucket, items in episodes.items()}


def _aggregate_session(session: Session, aggregator_factory: Callable[..., Aggregator]
                       ) -> tuple[Candle, ...]:
    aggregator = aggregator_factory(htf=("5m",))
    m5: list[Candle] = []
    for candle in session.candles:
        update = aggregator.on_candle(candle)
        if update.m5 is not None:
            m5.append(update.m5)
    return tuple(m5)


def load_research_episodes(
        *, feed: ReplayFeed | None = None, split=None,
        aggregator_factory: Callable[..., Aggregator] = Aggregator,
        ) -> tuple[dict[str, tuple[ResearchEpisode, ...]], dict]:
    """Load only TEACH/VALIDATE prices while retaining every source-day barrier."""
    split = split or load_split()
    feed = feed or ReplayFeed(SYMBOL, on_gap="skip")
    source_days = feed.source_days()
    usable_kinds = {"normal", "weekend_full"}
    bucket_by_day = {source.day: split.bucket_of(source.day) for source in source_days}
    requested_days = [
        source.day for source in source_days
        if source.kind in usable_kinds and bucket_by_day[source.day] in (TEACH, VALIDATE)
    ]

    m5_by_day: dict[date, tuple[Candle, ...]] = {}
    for session in feed.sessions(days=requested_days):
        bucket = bucket_by_day[session.day]
        if bucket not in (TEACH, VALIDATE):
            raise AssertionError("non-research session reached the M5 aggregator")
        m5_by_day[session.day] = _aggregate_session(session, aggregator_factory)

    records = tuple(
        SourceSessionRecord(
            source_ordinal=ordinal,
            day=source.day,
            bucket=bucket_by_day[source.day],
            m5=m5_by_day.get(source.day),
        )
        for ordinal, source in enumerate(source_days)
    )
    episodes = partition_source_sessions(records)
    source_population = {
        "source_sessions_indexed": len(source_days),
        "price_sessions_requested": len(requested_days),
        "price_sessions_replayed": len(m5_by_day),
        "excluded_price_sessions_converted": 0,
        "buckets": {
            bucket: {
                "source_sessions_assigned": sum(
                    item.bucket == bucket for item in records),
                "replayable_sessions": sum(
                    item.bucket == bucket and item.m5 is not None for item in records),
                "m5_candles": sum(
                    len(item.m5 or ()) for item in records if item.bucket == bucket),
                "eligible_episodes": len(episodes[bucket]),
            }
            for bucket in (TEACH, VALIDATE)
        },
    }
    return episodes, source_population


def make_blocks(episodes: Sequence[ResearchEpisode], bucket: str,
                config: AuditConfig) -> list[Block]:
    span = config.history + config.live
    blocks: list[Block] = []
    for episode in episodes:
        if episode.bucket != bucket:
            raise AssertionError("block builder received an episode from another bucket")
        candles = episode.candles
        ordinal_by_day = {
            item.day: item.source_ordinal for item in episode.sessions
        }
        for start in range(0, len(candles) - span + 1, span):
            if config.max_blocks is not None and len(blocks) >= config.max_blocks:
                return blocks
            consumed = tuple(candles[start:start + span])
            touched = tuple(sorted({ordinal_by_day[candle.session_date]
                                    for candle in consumed}))
            expected = tuple(range(touched[0], touched[-1] + 1))
            if touched != expected:
                raise AssertionError("block omitted a source session inside its span")
            blocks.append(Block(
                bucket=bucket,
                ordinal=len(blocks) + 1,
                start_index=start,
                history=consumed[:config.history],
                live=consumed[config.history:],
                episode=episode.ordinal,
                source_start_ordinal=touched[0],
                source_end_ordinal=touched[-1],
                source_session_ordinals=touched,
            ))
    return blocks


def population_facts(
        episodes_by_bucket: dict[str, tuple[ResearchEpisode, ...]],
        source_population: dict,
        config: AuditConfig,
        blocks_by_bucket: dict[str, list[Block]]) -> tuple[dict, dict]:
    """Keep availability and actual consumption in mechanically separate records."""
    available: dict[str, dict] = {}
    audited: dict[str, dict] = {}
    span = config.history + config.live
    for bucket in (TEACH, VALIDATE):
        episodes = episodes_by_bucket.get(bucket, ())
        blocks = blocks_by_bucket.get(bucket, [])
        bucket_source = source_population["buckets"][bucket]
        available[bucket] = dict(bucket_source)
        available[bucket].update({
            "episodes_long_enough": sum(len(episode.candles) >= span
                                         for episode in episodes),
            "possible_blocks": sum(len(episode.candles) // span
                                   for episode in episodes),
            "unused_warmup_tail_candles": sum(len(episode.candles) % span
                                               for episode in episodes),
        })
        audited[bucket] = {
            "blocks_processed": len(blocks),
            "history_candles_consumed": sum(len(block.history) for block in blocks),
            "live_candles_observed": sum(len(block.live) for block in blocks),
            "episodes_touched": len({block.episode for block in blocks}),
            "unique_sessions_touched": len({ordinal for block in blocks
                                             for ordinal in block.source_session_ordinals}),
        }
    return available, audited


def assert_research_blocks(blocks_by_bucket: dict[str, list[Block]], split=None) -> None:
    """Fail before any observer if a block crosses a source or split boundary."""
    split = split or load_split()
    for bucket in (TEACH, VALIDATE):
        for block in blocks_by_bucket.get(bucket, []):
            if block.bucket != bucket:
                raise AssertionError("block is assigned to the wrong research bucket")
            ordinals = block.source_session_ordinals
            if ordinals and ordinals != tuple(range(ordinals[0], ordinals[-1] + 1)):
                raise AssertionError("block source ordinals are not contiguous")
            if any(split.bucket_of(candle.session_date) != bucket
                   for candle in block.history + block.live):
                raise AssertionError("block crossed a split boundary")


def _record_event(catalog: dict[str, list[EventObservation]], event: str,
                  block: Block, index: int, at: str) -> None:
    bucket = catalog.setdefault(event, [])
    bucket.append(EventObservation(
        event=event,
        bucket=block.bucket,
        block=block.ordinal,
        index=index,
        at=at,
    ))


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
        classification = "NO_STRUCTURE_EITHER"
    elif hist_tight is not None and live_band is not None:
        hist_band = _band(hist_tight)
        if proposal_relation(hist_band, live_band, tol) == "same":
            classification = "SAME_SEMANTICS"
        elif hist_tight.kind == "cluster" and reading.node_kind == "range" and _contains(live_band, hist_band, tol):  # type: ignore[arg-type]
            classification = "LIVE_SCALE_COLLAPSE"
        elif hist_tight.end > reading.index:
            classification = "HISTORICAL_SCAN_ONLY"
        else:
            classification = "PRESENTATION_ONLY"
    elif hist_tight is not None:
        classification = "HISTORICAL_SCAN_ONLY"
    else:
        classification = "LIVE_FRONTIER_ONLY"

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
              examples: dict[str, list], events: dict[str, list[EventObservation]],
              timings: Counter[str]) -> None:
    snapshot = build_snapshot(block.history, SYMBOL)
    frontier = Frontier(snapshot, block.history)
    interpreter = Interpreter(snapshot, frontier)
    current_choose: list[ChooseObservation] = []
    original_choose = frontier_mod.choose
    previous_reading: Reading | None = None
    previous_local = False
    previous_session = block.history[-1].session_date if block.history else None
    expose_cases = block.bucket == TEACH

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
        if cluster is not None and rng is not None:
            _record_event(events, "simultaneous_cluster_range", block, i, obs.at)
        return cluster, rng

    try:
        frontier_mod.choose = wrapped_choose
        for candle in block.live:
            before_ids = {n.id for n in frontier.finalised}
            t0 = perf_counter()
            reading = frontier.on_candle(candle)
            timings["frontier_seconds"] += perf_counter() - t0
            state = interpreter.read(reading)

            if candle.session_date != previous_session:
                _record_event(events, "session_start", block, reading.index,
                              candle.close_time.isoformat())
            if reading.interaction in {"NEW_CLUSTER", "NEW_RANGE"}:
                counters["lifecycle"]["major_births"] += 1
                _record_event(events, "major_birth", block, reading.index,
                              candle.close_time.isoformat())
                _record_event(events, "new_major_structure", block, reading.index,
                              candle.close_time.isoformat())
            if (previous_reading is not None
                    and previous_reading.state == "STRUCTURE_CANDIDATE"
                    and reading.state == "CONFIRMED"):
                _record_event(events, "forming_to_confirmed", block, reading.index,
                              candle.close_time.isoformat())
            if state.status in {"APPROACHING_UPPER", "APPROACHING_LOWER"}:
                _record_event(events, "edge_approach", block, reading.index,
                              candle.close_time.isoformat())
            if reading.interaction.startswith("BREAK_ATTEMPT_"):
                _record_event(events, "break_attempt", block, reading.index,
                              candle.close_time.isoformat())
            if reading.interaction in {"ACCEPTED_ABOVE", "ACCEPTED_BELOW"}:
                counters["lifecycle"]["accepted_breaks"] += 1
                _record_event(events, "accepted_major_break", block, reading.index,
                              candle.close_time.isoformat())
            if reading.interaction == "RE_ENTRY":
                _record_event(events, "re_entry", block, reading.index,
                              candle.close_time.isoformat())
            if reading.interaction == "REVISIT":
                counters["lifecycle"]["revisits"] += 1
                _record_event(events, "revisit", block, reading.index,
                              candle.close_time.isoformat())
            if reading.state == "LEAVING" or reading.interaction == "LEAVING":
                _record_event(events, "leaving", block, reading.index,
                              candle.close_time.isoformat())

            micro_events = tuple(reading.micro.events) if reading.micro else ()
            for emitted, counter_name, event_name in (
                (MICRO_CREATED, "micro_created", "micro_created"),
                (MICRO_CONFIRMED_EVENT, "micro_confirmed", "micro_confirmed"),
                (MICRO_BREAK_UP, "micro_breaks", "micro_break"),
                (MICRO_BREAK_DOWN, "micro_breaks", "micro_break"),
                (MICRO_COLLAPSED, "micro_collapses", "micro_collapse"),
            ):
                if emitted in micro_events:
                    counters["lifecycle"][counter_name] += 1
                    _record_event(events, event_name, block, reading.index,
                                  candle.close_time.isoformat())

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
                    if (expose_cases
                            and len(examples["simultaneous"]) < config.trace_examples):
                        examples["simultaneous"].append(asdict(choose_obs))

                if (c and r and choose_obs.cluster_current and choose_obs.range_current
                        and counters["prefix_sampling"]["sampled"]
                        < config.prefix_examples):
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
                    counters["prefix_sampling"]["sampled"] += 1
                    if expose_cases:
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
            if bool(local) != previous_local:
                event_name = "local_research_appearance" if local else "local_research_disappearance"
                _record_event(events, event_name, block, reading.index,
                              candle.close_time.isoformat())
            previous_local = bool(local)

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
                if expose_cases and len(examples["local"]) < config.trace_examples:
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
                if expose_cases and len(examples["holders"]) < config.trace_examples:
                    examples["holders"].append(asdict(holder_obs))

            if frontier.finalised and {n.id for n in frontier.finalised} != before_ids:
                counters["lifecycle"]["major_finalised"] += len(
                    {n.id for n in frontier.finalised} - before_ids)

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

            previous_reading = reading
            previous_session = candle.session_date

        # End-of-block structural depth facts are historical-only and do not read holdout.
        counters["depth"]["snapshot_nodes"] += len(snapshot.structures())
        counters["depth"]["snapshot_nested"] += sum(1 for n in snapshot.structures() if n.parent is not None)
        counters["depth"]["max_snapshot_depth"] = max(
            counters["depth"]["max_snapshot_depth"],
            max((n.depth for n in snapshot.structures()), default=0),
        )
        frames = structural_frame.observe(snapshot, frontier)
        previous_active = None
        previous_references = None
        previous_watches = None
        previous_identity = None
        previous_generation = 0
        for frame in frames:
            at = frame.at.isoformat()
            if frame.release.releases:
                counters["lifecycle"]["release_created"] += len(frame.release.releases)
                _record_event(events, "release_created", block, frame.index, at)
            if frame.release.simultaneous:
                counters["lifecycle"]["simultaneous_releases"] += 1
                _record_event(events, "simultaneous_releases", block, frame.index, at)
            active = frame.release.active
            if (previous_active is not None and active is not None
                    and previous_active.id == active.id):
                _record_event(events, "release_still_held", block, frame.index, at)
            if previous_active is not None and active is None:
                _record_event(events, "release_given_back", block, frame.index, at)

            reference_identity = tuple(
                (ref.direction, ref.role, ref.structure_id, ref.edge)
                for path in (frame.references.up, frame.references.down)
                for ref in path.references
            )
            if previous_references is not None and reference_identity != previous_references:
                _record_event(events, "reference_identity_change", block, frame.index, at)

            watches = (frame.eye.watch_above, frame.eye.watch_below)
            if previous_watches is not None and watches != previous_watches:
                _record_event(events, "route_watch_change", block, frame.index, at)

            identity = thesis_mod.identity_of(frame.thesis)
            if previous_identity is None and identity is not None:
                _record_event(events, "thesis_birth", block, frame.index, at)
            if frame.thesis.generation != previous_generation and previous_generation:
                _record_event(events, "generation_change", block, frame.index, at)
                _record_event(events, "thesis_invalidation_or_reversal", block,
                              frame.index, at)
            elif frame.thesis.thesis_status == "INVALIDATED":
                _record_event(events, "thesis_invalidation_or_reversal", block,
                              frame.index, at)

            previous_active = active
            previous_references = reference_identity
            previous_watches = watches
            previous_identity = identity
            previous_generation = frame.thesis.generation
    finally:
        frontier_mod.choose = original_choose


def _counter_dict(counter: Counter) -> dict:
    return {str(k): v for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def _complete_counter_vocabulary(counters: dict[str, Counter]) -> None:
    expected = {
        "choose": ("CLUSTER_ONLY", "RANGE_ONLY", "BOTH", "NEITHER"),
        "simultaneous": (
            "BOTH_DETECTED", "BOTH_CURRENT", "BOTH_NOT_BOTH_CURRENT",
            "cluster_inside_range", "range_inside_cluster", "partial_overlap", "disjoint",
            "LIVE_SELECTED_CLUSTER", "LIVE_SELECTED_RANGE",
            "BOTH_WITH_CONTAINMENT", "BOTH_WITHOUT_CONTAINMENT",
        ),
        "lifecycle": (
            "major_births", "major_finalised", "revisits", "accepted_breaks",
            "micro_created", "micro_confirmed", "micro_breaks", "micro_collapses",
            "release_created", "simultaneous_releases",
        ),
        "micro_matrix": (
            "LOCAL_ABSENT + MICRO_ABSENT", "LOCAL_ABSENT + MICRO_FOUND",
            "LOCAL_FOUND + MICRO_ABSENT", "LOCAL_FOUND + MICRO_FOUND",
        ),
    }
    for group, names in expected.items():
        for name in names:
            counters[group][name] += 0


def sample_event_observations(
        observations: Sequence[EventObservation]) -> tuple[EventObservation, ...]:
    """Return all rare cases, otherwise the exact first, middle, and last cases."""
    ordered = sorted(observations, key=lambda item: (item.block, item.index, item.at))
    if len(ordered) <= 3:
        return tuple(ordered)
    return ordered[0], ordered[len(ordered) // 2], ordered[-1]


def public_event_catalog(bucket: str,
                         catalog: dict[str, list[EventObservation]]) -> dict:
    out = {}
    for name, observations in sorted(catalog.items()):
        item = {"occurrences": len(observations)}
        if bucket == TEACH:
            item["sampled"] = _serialise([
                asdict(observation)
                for observation in sample_event_observations(observations)
            ])
        out[name] = item
    return out


def discover_event_catalog(blocks_by_bucket: dict[str, list[Block]],
                           config: AuditConfig
                           ) -> dict[str, dict[str, list[EventObservation]]]:
    """Re-observe events in memory; no case-level VALIDATE data is returned by CLIs."""
    events_by_bucket: dict[str, dict[str, list[EventObservation]]] = {
        TEACH: defaultdict(list),
        VALIDATE: defaultdict(list),
    }
    discovery_config = AuditConfig(
        history=config.history,
        live=config.live,
        max_blocks=config.max_blocks,
        prefix_examples=0,
        trace_examples=0,
    )
    for bucket in (TEACH, VALIDATE):
        for block in blocks_by_bucket[bucket]:
            run_block(
                block,
                discovery_config,
                defaultdict(Counter),
                defaultdict(list),
                events_by_bucket[bucket],
                Counter(),
            )
    return events_by_bucket


def run_audit(config: AuditConfig) -> AuditResult:
    timings: Counter[str] = Counter()
    t0 = perf_counter()
    episodes_by_bucket, source_population = load_research_episodes()
    timings["load_seconds"] = perf_counter() - t0

    counters_by_bucket: dict[str, dict[str, Counter]] = {
        TEACH: defaultdict(Counter),
        VALIDATE: defaultdict(Counter),
    }
    examples_by_bucket: dict[str, dict[str, list]] = {
        TEACH: defaultdict(list),
        VALIDATE: defaultdict(list),
    }
    events_by_bucket: dict[str, dict[str, list[EventObservation]]] = {
        TEACH: defaultdict(list),
        VALIDATE: defaultdict(list),
    }
    blocks_by_bucket = {
        bucket: make_blocks(episodes, bucket, config)
        for bucket, episodes in episodes_by_bucket.items()
    }
    assert_research_blocks(blocks_by_bucket)
    available_population, audited_population = population_facts(
        episodes_by_bucket, source_population, config, blocks_by_bucket)

    t_run = perf_counter()
    for bucket in (TEACH, VALIDATE):
        for block in blocks_by_bucket[bucket]:
            run_block(
                block,
                config,
                counters_by_bucket[bucket],
                examples_by_bucket[bucket],
                events_by_bucket[bucket],
                timings,
            )
    timings["audit_seconds"] = perf_counter() - t_run
    timings["total_seconds"] = perf_counter() - t0

    for bucket in (TEACH, VALIDATE):
        _complete_counter_vocabulary(counters_by_bucket[bucket])

    counts = {
        bucket: {
            name: _counter_dict(counter)
            for name, counter in sorted(counters_by_bucket[bucket].items())
        }
        for bucket in (TEACH, VALIDATE)
    }
    examples = {
        TEACH: _serialise(dict(examples_by_bucket[TEACH])),
        VALIDATE: {},
    }
    events = {
        bucket: public_event_catalog(bucket, events_by_bucket[bucket])
        for bucket in (TEACH, VALIDATE)
    }
    payload = {
        "config": asdict(config),
        "available_population": available_population,
        "audited_population": audited_population,
        "counts": counts,
        "events": events,
        "examples": examples,
        "holdout_access_semantics": {
            "accessor_called": False,
            "source_index": "timestamps_only",
            "price_conversion": "teach_validate_whitelist_only",
            "excluded_price_sessions_converted": source_population[
                "excluded_price_sessions_converted"],
        },
        "timings": {k: round(v, 6) for k, v in sorted(timings.items())},
    }
    deterministic_payload = {
        "config": payload["config"],
        "holdout_access_semantics": payload["holdout_access_semantics"],
        "available_population": payload["available_population"],
        "audited_population": payload["audited_population"],
        "counts": payload["counts"],
        "events": payload["events"],
        "examples": payload["examples"],
    }
    fingerprint = json.dumps(deterministic_payload, sort_keys=True, default=_decimal_default)
    checksum = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return AuditResult(
        config=payload["config"],
        holdout_access_semantics=payload["holdout_access_semantics"],
        available_population=available_population,
        audited_population=_serialise(audited_population),
        counts=counts,
        events=events,
        examples=examples,
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
