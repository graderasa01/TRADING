from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.learning.split import TEACH, VALIDATE
from src.boxes.frontier import Frontier
from src.boxes.hierarchy import Node
from src.boxes.snapshot import build_snapshot
from tests.test_frontier import SPLIT, make, path, sit
from tools.live_structure_truth import (
    AuditConfig,
    Band,
    band_relation,
    holder_candidates,
    observational_local_candidates,
    run_audit,
)
from tools import live_structure_truth as audit_mod
from tests import test_release as release_fixture


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


def test_available_population_cannot_be_reported_as_audited_population(monkeypatch):
    candles = tuple(release_fixture.candles(range(1400)))
    monkeypatch.setattr(
        audit_mod,
        "aggregate_m5_by_bucket",
        lambda: (
            {TEACH: candles, VALIDATE: candles},
            {TEACH: 99, VALIDATE: 44},
        ),
    )
    monkeypatch.setattr(audit_mod, "run_block", lambda *args, **kwargs: None)

    result = run_audit(AuditConfig(max_blocks=1))

    assert result.available_population[TEACH] == {
        "sessions": 99,
        "candles": 1400,
    }
    assert result.audited_population[TEACH]["blocks_processed"] == 1
    assert result.audited_population[TEACH]["history_candles_consumed"] == 400
    assert result.audited_population[TEACH]["live_candles_observed"] == 300
    assert result.available_population[TEACH]["candles"] != (
        result.audited_population[TEACH]["live_candles_observed"])
    assert set(result.available_population[TEACH]) == {"sessions", "candles"}
    assert "sessions" not in result.audited_population[TEACH]


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
