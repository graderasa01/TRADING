from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.boxes.frontier import Frontier
from src.boxes.hierarchy import Node
from src.boxes.snapshot import build_snapshot
from src.domain.models import IST, Candle
from src.feed.replay_feed import Session, SourceDay
from src.learning.split import TEACH, VALIDATE
from tests.test_frontier import SPLIT, make, path, sit
from tools.live_structure_truth import (
    AuditConfig,
    Band,
    Block,
    EventObservation,
    ResearchEpisode,
    SourceSessionRecord,
    assert_research_blocks,
    band_relation,
    holder_candidates,
    load_research_episodes,
    make_blocks,
    observational_local_candidates,
    partition_source_sessions,
    population_facts,
    public_event_catalog,
)


def test_audit_tool_imports_no_execution_surface():
    source = Path("tools/live_structure_truth.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    forbidden_prefixes = (
        "src.livemap.trader",
        "src.livemap.participation",
        "src.livemap.position",
        "src.setups",
        "src.risk",
        "src.broker",
        "src.exits",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imports)
    assert "HOLDOUT" not in source


def test_available_population_cannot_be_reported_as_audited_population():
    records = tuple(
        SourceSessionRecord(
            index,
            date(2025, 3, 3) + timedelta(days=index),
            TEACH,
            _day_candles(date(2025, 3, 3) + timedelta(days=index), 70),
        )
        for index in range(20)
    )
    episodes = {
        bucket: (ResearchEpisode(bucket, 1, tuple(
            SourceSessionRecord(item.source_ordinal, item.day, bucket, item.m5)
            for item in records
        )),)
        for bucket in (TEACH, VALIDATE)
    }
    source_population = {
        "buckets": {
            bucket: {
                "source_sessions_assigned": 99,
                "replayable_sessions": 20,
                "m5_candles": 1400,
                "eligible_episodes": 1,
            }
            for bucket in (TEACH, VALIDATE)
        }
    }
    config = AuditConfig(max_blocks=1)
    blocks = {bucket: make_blocks(episodes[bucket], bucket, config)
              for bucket in (TEACH, VALIDATE)}

    available, audited = population_facts(
        episodes, source_population, config, blocks)

    assert available[TEACH]["m5_candles"] == 1400
    assert available[TEACH]["possible_blocks"] == 2
    assert available[TEACH]["unused_warmup_tail_candles"] == 0
    assert audited[TEACH]["blocks_processed"] == 1
    assert audited[TEACH]["history_candles_consumed"] == 400
    assert audited[TEACH]["live_candles_observed"] == 300
    assert available[TEACH]["m5_candles"] != audited[TEACH]["live_candles_observed"]
    assert "source_sessions_assigned" not in audited[TEACH]


def test_interleaved_split_months_form_distinct_source_episodes():
    records = (
        SourceSessionRecord(0, date(2024, 12, 2), TEACH, ()),
        SourceSessionRecord(1, date(2025, 1, 2), VALIDATE, ()),
        SourceSessionRecord(2, date(2025, 2, 3), "holdout", None),
        SourceSessionRecord(3, date(2025, 3, 3), TEACH, ()),
        SourceSessionRecord(4, date(2025, 4, 1), VALIDATE, ()),
        SourceSessionRecord(5, date(2025, 5, 1), TEACH, ()),
        SourceSessionRecord(6, date(2025, 6, 2), "holdout", None),
        SourceSessionRecord(7, date(2025, 7, 1), VALIDATE, ()),
    )

    episodes = partition_source_sessions(records)

    assert [[item.source_ordinal for item in episode.sessions]
            for episode in episodes[TEACH]] == [[0], [3], [5]]
    assert [[item.source_ordinal for item in episode.sessions]
            for episode in episodes[VALIDATE]] == [[1], [4], [7]]


def _day_candles(day: date, count: int = 75) -> tuple[Candle, ...]:
    start = datetime.combine(day, time(9, 15), tzinfo=IST)
    return tuple(
        Candle("TEST", "5m", start + timedelta(minutes=5 * index),
               start + timedelta(minutes=5 * (index + 1)),
               Decimal(100), Decimal(101), Decimal(99), Decimal(100))
        for index in range(count)
    )


def test_blocks_stay_inside_one_episode_and_keep_consecutive_source_ordinals():
    first_sessions = tuple(
        SourceSessionRecord(index, date(2025, 3, 3) + timedelta(days=index),
                            TEACH, _day_candles(date(2025, 3, 3) + timedelta(days=index)))
        for index in range(10)
    )
    second_sessions = tuple(
        SourceSessionRecord(index + 20, date(2025, 4, 1) + timedelta(days=index),
                            TEACH, _day_candles(date(2025, 4, 1) + timedelta(days=index)))
        for index in range(10)
    )
    episodes = (
        ResearchEpisode(TEACH, 1, first_sessions),
        ResearchEpisode(TEACH, 2, second_sessions),
    )

    blocks = make_blocks(episodes, TEACH, AuditConfig())

    assert [block.episode for block in blocks] == [1, 2]
    assert all(block.source_session_ordinals == tuple(range(
        block.source_start_ordinal, block.source_end_ordinal + 1)) for block in blocks)
    assert all(len(block.history) == 400 and len(block.live) == 300
               for block in blocks)


def test_price_loading_and_aggregation_are_whitelisted_before_observers():
    days = (
        SourceDay(date(2024, 12, 2), time(9, 15), time(15, 29), "normal"),
        SourceDay(date(2025, 1, 2), time(9, 15), time(15, 29), "normal"),
        SourceDay(date(2025, 2, 3), time(9, 15), time(15, 29), "normal"),
        SourceDay(date(2025, 3, 3), time(9, 15), time(15, 29), "normal"),
    )
    buckets = {
        days[0].day: TEACH,
        days[1].day: VALIDATE,
        days[2].day: "holdout",
        days[3].day: TEACH,
    }
    requested: list[date] = []
    aggregated: list[date] = []

    class FakeSplit:
        def bucket_of(self, day):
            return buckets[day]

    class FakeFeed:
        def source_days(self):
            return list(days)

        def sessions(self, *, days):
            requested.extend(days)
            for day in days:
                candle = _day_candles(day, 1)[0]
                yield Session("TEST", day, (candle,), None, 0)

    class SpyAggregator:
        def __init__(self, **_kwargs):
            pass

        def on_candle(self, candle):
            aggregated.append(candle.session_date)
            return SimpleNamespace(m5=candle)

    episodes, facts = load_research_episodes(
        feed=FakeFeed(), split=FakeSplit(), aggregator_factory=SpyAggregator)

    assert days[2].day not in requested
    assert days[2].day not in aggregated
    assert facts["excluded_price_sessions_converted"] == 0
    assert [[session.source_ordinal for session in episode.sessions]
            for episode in episodes[TEACH]] == [[0], [3]]


def test_excluded_session_is_rejected_before_any_research_observer():
    excluded_day = date(2025, 2, 3)
    candles = _day_candles(excluded_day)
    repeated = tuple(candles[index % len(candles)] for index in range(700))
    block = Block(
        bucket=TEACH,
        ordinal=1,
        start_index=0,
        history=repeated[:400],
        live=repeated[400:],
        episode=1,
        source_start_ordinal=2,
        source_end_ordinal=2,
        source_session_ordinals=(2,),
    )

    class ExcludedSplit:
        def bucket_of(self, _day):
            return "holdout"

    with pytest.raises(AssertionError, match="split boundary"):
        assert_research_blocks({TEACH: [block], VALIDATE: []}, split=ExcludedSplit())


def test_validate_event_output_contains_aggregates_only():
    observations = [
        EventObservation("release_created", VALIDATE, 1, index, f"at-{index}")
        for index in range(5)
    ]

    public = public_event_catalog(VALIDATE, {"release_created": observations})

    assert public == {"release_created": {"occurrences": 5}}
    assert "at-" not in repr(public)


def test_band_relation_uses_existing_containment_shape():
    cluster = Band(Decimal("102"), Decimal("105"))
    rng = Band(Decimal("100"), Decimal("110"))
    assert band_relation(cluster, rng) == "cluster_inside_range"
    assert band_relation(rng, cluster) == "range_inside_cluster"
    assert (
        band_relation(Band(Decimal("100"), Decimal("105")),
                      Band(Decimal("104"), Decimal("110")))
        == "partial_overlap"
    )
    assert (
        band_relation(Band(Decimal("100"), Decimal("105")),
                      Band(Decimal("106"), Decimal("110")))
        == "disjoint"
    )


@dataclass(frozen=True)
class StubNode:
    id: str
    kind: str
    low: Decimal
    high: Decimal
    end: int = 0

    @property
    def width(self) -> Decimal:
        return self.high - self.low


def node(nid: str, low: str, high: str) -> Node:
    return Node(id=nid, kind="range", start=0, end=10,
                low=Decimal(low), high=Decimal(high))


def test_live_holder_is_tightest_existing_container_without_mutation():
    known = (node("R1", "100", "120"), node("R2", "104", "112"))
    holders, tightest, deterministic = holder_candidates(
        Band(Decimal("105"), Decimal("110")), known, Decimal("0"))
    assert [n.id for n in holders] == ["R1", "R2"]
    assert tightest and tightest.id == "R2"
    assert deterministic
    assert known[0].low == Decimal("100")


def test_observational_scan_is_research_only_and_deterministic():
    candles = make(path(sit(22470, SPLIT + 55, width=20)),
                   day=date(2025, 3, 4))
    snapshot = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    frontier = Frontier(snapshot, candles[:SPLIT])

    reading = None
    for candle in candles[SPLIT:]:
        reading = frontier.on_candle(candle)
        if frontier.current is not None:
            break

    assert reading is not None
    assert frontier.current is not None

    snapshot_nodes = snapshot.nodes
    history_before = frontier.history()
    log_before = tuple(frontier.log.events)
    live_log_before = tuple(frontier.live_log.events)
    current_before = (
        frontier.current.id,
        frontier.current.low,
        frontier.current.high,
        frontier.current.end,
        frontier.current.interactions,
    )

    first = observational_local_candidates(frontier, reading)
    second = observational_local_candidates(frontier, reading)

    assert [(p.kind, p.low, p.high, p.window) for p in first] == [
        (p.kind, p.low, p.high, p.window) for p in second
    ]
    assert snapshot.nodes is snapshot_nodes
    assert frontier.history() == history_before
    assert tuple(frontier.log.events) == log_before
    assert tuple(frontier.live_log.events) == live_log_before
    assert frontier.current is not None
    assert (
        frontier.current.id,
        frontier.current.low,
        frontier.current.high,
        frontier.current.end,
        frontier.current.interactions,
    ) == current_before
