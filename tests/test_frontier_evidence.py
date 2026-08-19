"""
Phase A — the live frontier stops throwing information away.

The audit found nine places where `frontier.py` discarded facts it already had. Four are
fixed here, and every one of these tests exists because the information was measurably
gone before:

```
A1  the FORMING candidate      a whole Proposal reduced to one word
A2  live-minted node events    ~75% of breaks left no trace anywhere
A3  rotations and touches      frozen at mint; `finalise()` had no `rotations` argument
A4  status                     one field answering two different questions
```

**The governing invariant, and the test that enforces it.** Phase A captures evidence and
never interprets it. Nothing in `frontier.py` may branch on a touch count, a rotation
count or a dwell length. `test_the_map_story_did_not_move` is the mechanical guard: the
same candles must produce the same structures, the same geometry and the same interaction
sequence as before Phase A existed. If an evidence counter ever leaks into an admission
decision, that test is what catches it.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.boxes.frontier import (
    CLOSED, LIVE_STATES, MAP_STATUSES, STATUS_CONFIRMED, STRUCTURE_CANDIDATE, Frontier,
    run)
from src.boxes.snapshot import LiveEvent, LiveEventLog, build_snapshot
from src.domain.models import IST, Candle

SPLIT = 90
GOLDEN = Path(__file__).parent / "fixtures" / "frontier_map_story.json"


def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=9, minute=15)
    return [Candle("TEST", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path_of(closes, wick: float = 1.5):
    out, prev = [], closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def sit(price: float, n: int, width: float = 18.0):
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def swing(lo: float, hi: float, n: int, period: int):
    """A shelf that crosses slowly, so successive edge approaches are separated by more
    than `touches()`'s `gap` and therefore count separately."""
    return [lo + (hi - lo) * (0.5 - 0.5 * math.cos(2 * math.pi * i / period))
            for i in range(n)]


def frontier_for(closes) -> Frontier:
    candles = make(path_of(closes))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    return run(snap, candles[:SPLIT], candles[SPLIT:])


#: The four shapes `test_frontier.py` uses for its integrity invariants, plus the
#: walkthrough. The walkthrough is here because **none of the other four finalises a
#: single node** — measured, not assumed — so without it the `finalised` half of the
#: golden story would be pinned against four empty lists and would catch nothing.
SHAPES = {
    "rest-break-rest": sit(22470, SPLIT + 20, 20) + ramp(22482, 22560, 20)
                       + sit(22570, 40, 10),
    "there and back": sit(22470, SPLIT + 20, 20) + ramp(22482, 22560, 20)
                      + sit(22470, 40, 20),
    "double return": sit(22470, SPLIT, 20) + ramp(22482, 22540, 12)
                     + sit(22470, 25, 20) + ramp(22482, 22540, 12)
                     + sit(22470, 25, 20),
    "one-way walk": sit(22470, SPLIT, 20) + ramp(22482, 22900, 60),
    "walkthrough": sit(22470, SPLIT + 30, 20) + ramp(22482, 22550, 25)
                   + sit(22560, 45, 8) + ramp(22572, 22650, 22),
}


@pytest.fixture
def banknifty() -> Frontier:
    """`test_frontier.py`'s walkthrough: the frozen 22460-22480 cluster is adopted and
    broken, and a genuinely new shelf at 22560 is minted and broken in turn."""
    return frontier_for(sit(22470, SPLIT + 30, width=20)
                        + ramp(22482, 22550, 25)
                        + sit(22560, 45, width=8)
                        + ramp(22572, 22650, 22))


# ─────────────────────────────────────────────────────────────────────────────
# the invariant that makes Phase A "Phase A"
# ─────────────────────────────────────────────────────────────────────────────
def story(closes) -> dict:
    """Everything Phase A promised NOT to change."""
    f = frontier_for(closes)
    return {
        "finalised": [
            {"kind": n.kind, "start": n.start, "end": n.end,
             "low": str(n.low), "high": str(n.high), "window": n.window}
            for n in f.history()],
        "readings": [
            {"i": r.index, "state": r.state, "interaction": r.interaction,
             "node_id": r.node_id,
             "band": [str(r.band[0]), str(r.band[1])] if r.band else None,
             "up": None if r.break_level_up is None else str(r.break_level_up),
             "dn": None if r.break_level_down is None else str(r.break_level_down)}
            for r in f.readings],
    }


def test_the_map_story_did_not_move():
    """Phase A adds fields; it must not move a single boundary or reorder one state.

    The fixture was generated only after a 29-block real Bank Nifty replay — 8,700
    readings, 165 finalised nodes, 499 frozen events — was confirmed byte-identical
    before and after the change. This pins the same guarantee in CI without needing the
    CSV archive.
    """
    got = {name: story(closes) for name, closes in SHAPES.items()}
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name in SHAPES:
        assert got[name] == want[name], (
            f"{name}: the major-map story moved. Phase A is supposed to be purely "
            f"additive — an evidence counter has leaked into a decision.")


# ─────────────────────────────────────────────────────────────────────────────
# A1 — the candidate is no longer reduced to one word
# ─────────────────────────────────────────────────────────────────────────────
def test_forming_now_says_what_is_forming(banknifty):
    """`_loose_candidate()` always computed a full Proposal; the old code kept only the
    string `STRUCTURE_CANDIDATE` and dropped the band, the score and the window."""
    forming = [r for r in banknifty.readings if r.state == STRUCTURE_CANDIDATE]
    assert forming, "the fixture never reached STRUCTURE_CANDIDATE"
    for r in forming:
        assert r.candidate is not None, f"c{r.index}: FORMING with nothing to show"
        assert r.candidate.low < r.candidate.high
        assert r.candidate.window > 0
        assert r.candidate.kind in {"cluster", "range"}


def test_a_candidate_exists_exactly_when_the_state_says_so(banknifty):
    for r in banknifty.readings:
        assert (r.candidate is not None) == (r.state == STRUCTURE_CANDIDATE), (
            f"c{r.index}: state {r.state} but candidate="
            f"{'set' if r.candidate else 'None'}")


def test_the_candidate_is_cleared_once_a_structure_confirms(banknifty):
    confirmed = [r for r in banknifty.readings if r.node_id is not None]
    assert confirmed
    assert all(r.candidate is None for r in confirmed), (
        "a confirmed structure still carries a candidate — the two would be read as "
        "two different bands in play at once")


# ─────────────────────────────────────────────────────────────────────────────
# A2 — live-minted nodes finally have a history
# ─────────────────────────────────────────────────────────────────────────────
def test_frozen_events_still_go_to_the_frozen_log(banknifty):
    """`test_the_broken_structure_survives_as_history` must keep passing unchanged."""
    breaks = banknifty.log.of_kind("break")
    assert breaks, "the break of the frozen cluster must still reach M001's log"
    for e in breaks:
        assert banknifty.snapshot.by_id(e.node_id) is not None


def test_live_minted_events_reach_the_live_log(banknifty):
    """Before this, `_record` had no `else` — every event whose node the frontier had
    minted was silently discarded."""
    assert len(banknifty.live_log) > 0, "the frontier kept no record of its own work"
    frozen_ids = {n.id for n in banknifty.snapshot.structures()}
    minted = [e for e in banknifty.live_log if e.node_id not in frozen_ids]
    assert minted, f"no live-minted node reached the live log: {banknifty.live_log.events}"


def test_the_two_logs_are_split_by_ownership(banknifty):
    """Not by importance — `log` is what price did to the frozen map, `live_log` is what
    it did to what the frontier built."""
    for e in banknifty.log:
        assert banknifty.snapshot.by_id(e.node_id) is not None


def test_the_live_log_is_append_only():
    log = LiveEventLog()
    at = datetime(2025, 3, 4, 9, 20, tzinfo=IST)
    log.append(LiveEvent("break", "L01", 5, at))
    assert len(log) == 1
    for forbidden in ("clear", "remove", "pop", "__setitem__", "__delitem__"):
        assert not hasattr(log, forbidden), f"LiveEventLog exposes {forbidden}"


def test_the_live_log_enforces_candle_order():
    log = LiveEventLog()
    at = datetime(2025, 3, 4, 9, 20, tzinfo=IST)
    log.append(LiveEvent("break", "L01", 10, at))
    with pytest.raises(ValueError):
        log.append(LiveEvent("touch", "L01", 9, at))


def test_a_revisits_evidence_survives_its_break():
    """A revisited node is never finalised — `if not node.revisited` — so everything the
    visit accumulated used to die at the break. It rides on an event instead, because the
    snapshot must never be edited."""
    f = frontier_for(sit(22470, SPLIT + 20, width=20)
                     + ramp(22482, 22560, 20)
                     + sit(22470, 45, width=20)
                     + ramp(22482, 22600, 20))
    carried = [e for e in f.live_log if e.evidence]
    assert carried, "a revisit ended and took its whole history with it"
    ev = carried[-1].evidence
    for key in ("upper_touches", "lower_touches", "rotations", "time_inside",
                "interactions"):
        assert key in ev, f"{key} missing from the carried evidence"


# ─────────────────────────────────────────────────────────────────────────────
# A3 — evidence moves, geometry does not
# ─────────────────────────────────────────────────────────────────────────────
def test_a_finalised_node_remembers_its_rotations(banknifty):
    """`finalise()` had no `rotations` argument at all, so every frontier-built node
    reached history with `rotations = ()` while batch nodes carried the full list."""
    assert banknifty.finalised
    assert any(n.rotations for n in banknifty.finalised), (
        "no finalised node carried a single rotation — the batch map would have")


def test_finalised_measurements_carry_the_dwell(banknifty):
    n = banknifty.finalised[-1]
    for key in ("time_inside", "interactions", "rotations_count"):
        assert key in n.measurements, f"{key} missing from {n.id}'s measurements"


def test_touches_are_re_read_rather_than_frozen_at_mint():
    """`_mint` copied the Proposal's counts once and no later candle touched them.

    The shelf here swings slowly on purpose. `adaptive.touches()` merges approaches that
    are closer together than `gap`, because *"ten consecutive candles grinding the high
    are **one** touch — price has to leave by more than `tol` and come back for the second
    one to count."* On the fast `sit()` shelf every approach merges into one and the count
    correctly never moves; that is the touch rule working, not a frozen counter. A slow
    swing separates them, which is what makes the re-read observable at all.
    """
    f = frontier_for(sit(22470, SPLIT, width=20) + ramp(22482, 22600, 20)
                     + swing(22600, 22640, 70, period=18))
    seen = [r.evidence.get("upper_touches", 0) for r in f.readings
            if r.node_id and r.evidence]
    assert seen, "no evidence was recorded on any reading"
    assert max(seen) > min(seen), (
        f"upper_touches never changed across the shelf's life: {sorted(set(seen))}")


def test_rotations_are_re_read_on_a_shelf_that_keeps_crossing():
    """The counter that moves on any oscillation, fast or slow."""
    f = frontier_for(sit(22470, SPLIT, width=20) + ramp(22482, 22600, 20)
                     + sit(22610, 60, width=14))
    seen = [r.evidence.get("rotations", 0) for r in f.readings
            if r.node_id and r.evidence]
    assert seen and max(seen) > min(seen), (
        f"rotations never grew while price kept crossing the band: {sorted(set(seen))}")


def test_the_band_is_never_repainted(banknifty):
    """The one thing Phase A must not do. `events.py` exists because a breakout candle
    widening the box it is breaking makes the break hide itself."""
    first: dict[str, tuple] = {}
    for r in banknifty.readings:
        if r.node_id is None or r.band is None:
            continue
        if r.node_id not in first:
            first[r.node_id] = r.band
        assert r.band == first[r.node_id], (
            f"c{r.index}: {r.node_id} was repainted from "
            f"{first[r.node_id]} to {r.band}")


@pytest.mark.parametrize("name", list(SHAPES))
def test_the_band_is_never_repainted_on_any_shape(name):
    f = frontier_for(SHAPES[name])
    first: dict[str, tuple] = {}
    for r in f.readings:
        if r.node_id is None or r.band is None:
            continue
        first.setdefault(r.node_id, r.band)
        assert r.band == first[r.node_id], f"{name}: {r.node_id} was repainted"


def test_an_adopted_node_measures_the_visit_not_the_absence():
    """`_adopt` keeps the original `start` so the shelf keeps its identity. Measuring
    evidence from there would count every excursion and return during the absence as
    rotation inside a band price was nowhere near, so `evidence_from` is the revisit."""
    f = frontier_for(sit(22470, SPLIT + 20, width=20)
                     + ramp(22482, 22560, 20)
                     + sit(22470, 45, width=20))
    revisits = [r for r in f.readings if r.interaction == "REVISIT"]
    assert revisits, "the fixture never revisited anything"
    node = f.current
    assert node is not None and node.revisited
    assert node.evidence_from > node.start, (
        "an adopted node is measuring evidence from its original birth, which spans "
        "the whole period price was somewhere else entirely")


# ─────────────────────────────────────────────────────────────────────────────
# A4 — two vocabularies, two questions
# ─────────────────────────────────────────────────────────────────────────────
def test_the_two_status_vocabularies_are_closed_and_disjoint():
    assert LIVE_STATES == {STATUS_CONFIRMED, CLOSED}
    assert MAP_STATUSES == {"PROVISIONAL", "HISTORICAL"}
    assert not (LIVE_STATES & MAP_STATUSES) - {STATUS_CONFIRMED}, (
        "the two vocabularies overlap again — that is the confusion A4 removed")


def test_every_reading_uses_a_known_map_status(banknifty):
    for r in banknifty.readings:
        assert r.node_status is None or r.node_status in MAP_STATUSES


def test_a_reading_refuses_an_unknown_map_status():
    from src.boxes.frontier import Reading
    with pytest.raises(ValueError):
        Reading(index=0, state="MOVING", interaction="MOVING", node_status="CONFIRMED")


def test_a_live_node_reports_its_own_lifecycle(banknifty):
    assert banknifty.left is None or banknifty.left.live_status == CLOSED
    for node in (banknifty.current, banknifty.left):
        if node is not None:
            assert node.live_status in LIVE_STATES
