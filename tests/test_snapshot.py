"""
The frozen map — `src/boxes/snapshot.py`.

The whole value of a snapshot is that it **cannot change**, so the tests are mostly
attempts to change it. `LIVE-FRONTIER.md` law 1: *"MAP M001 + [live events], never
MAP M001'."*
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.snapshot import (
    LiveEvent, LiveLog, build_snapshot, diff, from_json, next_version, to_json)
from src.domain.models import IST, Candle

TOL = Decimal("5")


def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=9, minute=15)
    return [Candle("TEST", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path(closes, wick: float = 1.0):
    out, prev = [], closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def sit(price: float, n: int, width: float = 18.0):
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


@pytest.fixture
def canvas():
    return make(path(sit(60000, 40) + ramp(60000, 60300, 25) + sit(60300, 45)))


@pytest.fixture
def snap(canvas):
    return build_snapshot(canvas, "TEST")


# ─────────────────────────────────────────────────────────────────────────────
# it cannot change
# ─────────────────────────────────────────────────────────────────────────────
def test_snapshot_is_frozen(snap):
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.version = "M999"
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.nodes[0].low = Decimal("1")


def test_nodes_and_relations_are_tuples(snap):
    """A list would let a consumer append to the map it was handed."""
    assert isinstance(snap.nodes, tuple)
    assert isinstance(snap.relations, tuple)
    for n in snap.nodes:
        assert isinstance(n.children, tuple)
        assert isinstance(n.rotations, tuple)


def test_live_events_do_not_touch_the_snapshot(snap):
    before = dataclasses.astuple(snap)
    log = LiveLog(snap)
    target = snap.structures()[0].id
    for i in range(5):
        log.append(LiveEvent("touch", target, snap.built_at_index + 1 + i,
                             snap.built_at))
    assert dataclasses.astuple(snap) == before, "the snapshot moved"
    assert len(log) == 5


def test_log_is_append_only():
    """No clear, no delete, no reassignment. The only thing it can do is grow."""
    assert not hasattr(LiveLog, "clear")
    assert not hasattr(LiveLog, "remove")
    assert not hasattr(LiveLog, "__setitem__")


def test_log_returns_a_copy(snap):
    log = LiveLog(snap)
    log.append(LiveEvent("touch", snap.structures()[0].id, 999, snap.built_at))
    grabbed = log.events
    assert isinstance(grabbed, tuple)
    assert len(log) == 1


# ─────────────────────────────────────────────────────────────────────────────
# the log refuses nonsense
# ─────────────────────────────────────────────────────────────────────────────
def test_unknown_event_kind_is_refused(snap):
    with pytest.raises(ValueError, match="unknown live event"):
        LiveEvent("teleported", snap.structures()[0].id, 1, snap.built_at)


def test_event_for_a_node_that_does_not_exist_is_refused(snap):
    log = LiveLog(snap)
    with pytest.raises(KeyError):
        log.append(LiveEvent("break", "C999", 1, snap.built_at))


def test_events_must_arrive_in_candle_order(snap):
    log = LiveLog(snap)
    nid = snap.structures()[0].id
    log.append(LiveEvent("touch", nid, 200, snap.built_at))
    with pytest.raises(ValueError, match="candle order"):
        log.append(LiveEvent("touch", nid, 199, snap.built_at))


# ─────────────────────────────────────────────────────────────────────────────
# identity
# ─────────────────────────────────────────────────────────────────────────────
def test_label_never_renders_a_bare_version(snap):
    """'M001 freeze' read as settled truth is the misreading that would make this lie."""
    label = snap.label()
    assert label != snap.version
    assert f"i={snap.built_at_index}" in label
    assert snap.version in label


def test_next_version():
    assert next_version(None) == "M001"
    assert next_version("M001") == "M002"
    assert next_version("M009") == "M010"


# ─────────────────────────────────────────────────────────────────────────────
# diff — the honest measure of repainting
# ─────────────────────────────────────────────────────────────────────────────
def test_a_snapshot_against_itself_has_nothing_moved(snap):
    d = diff(snap, snap, TOL)
    assert not d.of("moved"), d.summary()
    assert not d.of("vanished")
    assert not d.of("appeared")
    assert len(d.of("survived")) == len(snap.structures())


def test_diff_matches_structurally_not_by_id(canvas):
    """Ids are minted per build, so `C12` in M001 and `C12` in M002 are unrelated."""
    a = build_snapshot(canvas, "TEST", version="M001")
    b = build_snapshot(canvas[:-10], "TEST", version="M002")
    d = diff(a, b, TOL)
    assert d.before == "M001" and d.after == "M002"
    matched = d.of("survived") + d.of("moved")
    assert matched, "the shelves are the same shelves; ids differing must not hide that"
    for c in matched:
        assert c.before.kind == c.after.kind


def test_growing_the_canvas_appends_rather_than_rewrites(canvas):
    """The oldest structures must survive a rebuild that only added candles."""
    a = build_snapshot(canvas[:70], "TEST", version="M001")
    b = build_snapshot(canvas, "TEST", version="M002")
    d = diff(a, b, TOL)
    assert len(d.of("vanished")) <= 1, d.summary()


# ─────────────────────────────────────────────────────────────────────────────
# round trip
# ─────────────────────────────────────────────────────────────────────────────
def test_json_round_trip_preserves_the_map(snap):
    log = LiveLog(snap)
    log.append(LiveEvent("break", snap.structures()[0].id, 500, snap.built_at,
                         "up", Decimal("60300.5"), "two closes beyond"))

    back, back_log = from_json(to_json(snap, log))

    assert back.version == snap.version
    assert back.built_at == snap.built_at
    assert back.built_at_index == snap.built_at_index
    assert len(back.nodes) == len(snap.nodes)
    assert len(back.relations) == len(snap.relations)
    for old, new in zip(snap.nodes, back.nodes):
        assert (old.id, old.kind, old.start, old.end) == (new.id, new.kind,
                                                          new.start, new.end)
        assert old.low == new.low and old.high == new.high, "Decimal precision lost"
        assert old.children == new.children and old.parent == new.parent
    assert len(back_log) == 1
    assert back_log.events[0].level == Decimal("60300.5")


def test_round_trip_carries_an_events_evidence(snap):
    """`LiveEvent.evidence` is the only way a revisit's history survives at all.

    `Frontier` never finalises a revisited node — `if not node.revisited` — so the touches,
    rotations and dwell it accumulated have nowhere to live except on the break event
    itself. If that dictionary is dropped at the JSON boundary, a reloaded map is missing
    exactly the visits it could not reconstruct from the nodes.
    """
    log = LiveLog(snap)
    log.append(LiveEvent("break", snap.structures()[0].id, 500, snap.built_at,
                         "up", Decimal("60300.5"), "revisit ended",
                         {"upper_touches": 3.0, "lower_touches": 2.0, "rotations": 4.0,
                          "time_inside": 41.0, "interactions": 46.0}))

    _, back_log = from_json(to_json(snap, log))

    assert back_log.events[0].evidence == {
        "upper_touches": 3.0, "lower_touches": 2.0, "rotations": 4.0,
        "time_inside": 41.0, "interactions": 46.0}


def test_an_event_without_evidence_round_trips_as_empty(snap):
    """The field is additive and defaulted, so every event written before it existed —
    and every event that simply has nothing to carry — must reload as `{}`, not `None`."""
    log = LiveLog(snap)
    log.append(LiveEvent("touch", snap.structures()[0].id, 500, snap.built_at))
    _, back_log = from_json(to_json(snap, log))
    assert back_log.events[0].evidence == {}


def test_round_trip_keeps_decimals_exact(snap):
    """`Decimal(repr(x))` at the loader boundary, never `Decimal(float)` — D-014."""
    back, _ = from_json(to_json(snap))
    for old, new in zip(snap.nodes, back.nodes):
        assert str(old.low) == str(new.low)
        assert str(old.high) == str(new.high)
