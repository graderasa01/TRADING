from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, fields
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.domain.models import IST
from src.learning.split import TEACH, VALIDATE
from tools.structural_response_study import (
    CausalSample,
    LocalContext,
    MicroContext,
    ReleaseFact,
    ResponseObserver,
    StructureFact,
    aggregate,
)

BASE = datetime(2025, 1, 2, 9, 20, tzinfo=IST)
STRUCTURE = StructureFact(
    "C01", "cluster", Decimal(100), Decimal(110), "R01", "INSIDE_STRUCTURE")


def sample(index: int, close: str, *, high: str | None = None,
           low: str | None = None, interaction: str = "INSIDE",
           current: StructureFact | None = STRUCTURE, left_id: str | None = None,
           bucket: str = TEACH, episode: str | None = None,
           source_ordinal: int = 4, micro: MicroContext | None = None,
           local: LocalContext | None = None,
           releases: tuple[ReleaseFact, ...] = ()) -> CausalSample:
    c = Decimal(close)
    h = Decimal(high) if high is not None else c + Decimal("0.5")
    l = Decimal(low) if low is not None else c - Decimal("0.5")
    return CausalSample(
        bucket=bucket,
        source_episode_id=episode or f"{bucket}-EP001",
        source_ordinal=source_ordinal,
        index=index,
        at=BASE + timedelta(minutes=5 * index),
        o=c,
        h=h,
        l=l,
        c=c,
        atr=Decimal(2),
        tolerance=Decimal(1),
        frontier_state="LEAVING" if interaction.startswith("ACCEPTED_") else "CONFIRMED",
        interaction=interaction,
        current=current,
        left_id=left_id,
        micro=micro or MicroContext("ABSENT"),
        local=local or LocalContext(False),
        releases=releases,
    )


def observe(*samples: CausalSample) -> ResponseObserver:
    first = samples[0]
    observer = ResponseObserver(first.bucket, first.source_episode_id)
    for item in samples:
        observer.observe(item)
    observer.finish()
    return observer


def test_structure_and_upper_lower_encounter_identities_are_deterministic():
    observer = observe(
        sample(0, "105"),
        sample(1, "109.5", high="110", low="108", interaction="AT_UPPER_EDGE"),
        sample(2, "106", high="107", low="105.5"),
        sample(3, "100.5", high="101", low="100", interaction="AT_LOWER_EDGE"),
    )

    assert observer.structures[0].origin.structure_episode_id == "teach-EP001:C01:V001"
    assert observer.structures[0].origin.birth_index is None
    assert [item.origin.encounter_id for item in observer.encounters] == [
        "teach-EP001:C01:V001:upper:E001",
        "teach-EP001:C01:V001:lower:E001",
    ]
    assert [item.origin.edge_id for item in observer.encounters] == [
        "C01.upper", "C01.lower"]


def test_repeated_edge_encounters_are_distinct_and_ordered():
    observer = observe(
        sample(0, "105"),
        sample(1, "109.5", high="110", low="108", interaction="AT_UPPER_EDGE"),
        sample(2, "106", high="107", low="105.5"),
        sample(3, "109.5", high="110.5", low="109", interaction="AT_UPPER_EDGE"),
    )

    uppers = [item for item in observer.encounters if item.origin.side == "upper"]
    assert [item.origin.ordinal_for_edge for item in uppers] == [1, 2]
    assert uppers[0].end_reason == "MOVED_INSIDE"
    assert uppers[1].end_reason == "SOURCE_EPISODE_BOUNDARY"


def test_touch_without_break_records_inside_response_only():
    observer = observe(
        sample(0, "105"),
        sample(1, "108.9", high="110.2", low="108.5", interaction="AT_UPPER_EDGE"),
        sample(2, "107", high="108", low="106"),
    )
    encounter = observer.encounters[0]
    events = {event for item in encounter.observations for event in item.events}

    assert encounter.first_touch_index == 1
    assert "CLOSE_INSIDE_AFTER_UPPER_TEST" in events
    assert encounter.first_accepted_break_index is None
    assert encounter.max_outside_excursion == Decimal("0.2")


def test_penetration_then_reclaim_and_retest_remain_append_only():
    observer = observe(
        sample(0, "105"),
        sample(1, "111", high="112", low="109", interaction="BREAK_ATTEMPT_UP"),
        sample(2, "109.5", high="111", low="109", interaction="RE_ENTRY"),
        sample(3, "108", high="110", low="107"),
    )
    encounter = observer.encounters[0]
    events = [event for item in encounter.observations for event in item.events]

    assert encounter.first_reclaim_index == 2
    assert encounter.first_return_retest_index == 3
    assert encounter.end_reason == "RECLAIM_HELD_INSIDE"
    assert "RECLAIM_UPPER" in events
    assert "HOLD_INSIDE_AFTER_RECLAIM" in events


def test_accepted_break_finalises_structure_and_encounter_on_terminal_candle():
    observer = observe(
        sample(0, "105"),
        sample(1, "111", high="112", low="109", interaction="BREAK_ATTEMPT_UP"),
        sample(2, "112", high="113", low="111", interaction="ACCEPTED_ABOVE",
               current=None, left_id="C01"),
    )
    structure = observer.structures[0]
    encounter = observer.encounters[0]

    assert structure.accepted_break == "ACCEPTED_ABOVE"
    assert structure.finalised is True
    assert structure.end_reason == "ACCEPTED_BREAK"
    assert encounter.first_accepted_break_index == 2
    assert encounter.end_reason == "ACCEPTED_BREAK"


def test_reentry_and_opposite_edge_traversal_are_raw_lifecycle_facts():
    reentry = observe(
        sample(0, "105"),
        sample(1, "111", high="112", low="109", interaction="BREAK_ATTEMPT_UP"),
        sample(2, "109", high="111", low="108", interaction="RE_ENTRY"),
        sample(3, "108", high="109", low="107"),
    )
    traversal = observe(
        sample(0, "105"),
        sample(1, "109", high="110", low="108", interaction="AT_UPPER_EDGE"),
        sample(2, "101", high="109", low="100", interaction="AT_LOWER_EDGE"),
    )

    assert reentry.structures[0].reentries == 1
    assert reentry.encounters[0].first_reclaim_index == 2
    assert traversal.encounters[0].midpoint_reached_index == 2
    assert traversal.encounters[0].opposite_edge_reached_index == 2
    assert traversal.encounters[0].end_reason == "OPPOSITE_EDGE_REACHED"


def test_origin_candle_range_cannot_claim_later_response_order():
    observer = observe(
        sample(0, "105"),
        sample(1, "109", high="111", low="99", interaction="AT_UPPER_EDGE"),
    )
    encounter = observer.encounters[0]

    assert encounter.first_touch_index == 1
    assert encounter.midpoint_reached_index is None
    assert encounter.opposite_edge_reached_index is None


def _release(release_id: str, scale: str = "OUTER") -> ReleaseFact:
    return ReleaseFact(
        release_id, scale, "LOG" if scale == "OUTER" else "MICRO_EVENT",
        "C01", Decimal(110), Decimal(100), Decimal(110), "cluster", "up",
        "R01", Decimal(112), Decimal(2), 1.0, "BEYOND_BROKEN_EDGE", ("C02.low",))


def test_simultaneous_releases_are_all_preserved_as_linked_children():
    observer = ResponseObserver(TEACH, "teach-EP001")
    observer.observe(sample(0, "105"))
    observer.observe(sample(
        1, "112", high="113", low="111", interaction="ACCEPTED_ABOVE",
        current=None, left_id="C01",
        releases=(_release("RL01"), _release("RL02", "MICRO"))))
    release_origin = asdict(observer.releases[0].origin)
    observer.observe(sample(2, "109", current=None))
    observer.finish()

    assert len(observer.releases) == 2
    assert len({item.origin.release_episode_id for item in observer.releases}) == 2
    assert all(item.origin.structure_episode_id
               == observer.structures[0].origin.structure_episode_id
               for item in observer.releases)
    assert all(item.giveback_index == 2 for item in observer.releases)
    assert asdict(observer.releases[0].origin) == release_origin
    with pytest.raises(FrozenInstanceError):
        observer.releases[0].origin.price = Decimal(999)  # type: ignore[misc]


def test_micro_and_local_are_frozen_subordinate_origin_context_only():
    micro = MicroContext("CONFIRMED", "M01", Decimal(104), Decimal(106),
                         ("MICRO_CONFIRMED",))
    local = LocalContext(True, "range", Decimal(103), Decimal(107), "C01",
                         "CONTAINS_MICRO")
    observer = observe(
        sample(0, "105", micro=micro, local=local),
        sample(1, "109.5", high="110", low="109", interaction="AT_UPPER_EDGE",
               micro=micro, local=local),
    )
    origin = observer.encounters[0].origin

    assert origin.micro == micro
    assert origin.local == local
    names = {item.name.lower() for item in fields(type(origin.micro))}
    assert not names.intersection({"micro_bullish", "micro_bearish", "micro_entry"})


def test_origins_are_immutable_when_future_candles_append():
    observer = ResponseObserver(TEACH, "teach-EP001")
    observer.observe(sample(0, "105"))
    observer.observe(sample(1, "109.5", high="110", low="109",
                            interaction="AT_UPPER_EDGE"))
    structure_before = asdict(observer.structures[0].origin)
    encounter_before = asdict(observer.encounters[0].origin)
    observer.observe(sample(2, "111", high="112", low="109",
                            interaction="BREAK_ATTEMPT_UP"))

    assert asdict(observer.structures[0].origin) == structure_before
    assert asdict(observer.encounters[0].origin) == encounter_before
    with pytest.raises(FrozenInstanceError):
        observer.encounters[0].origin.edge_price = Decimal(999)  # type: ignore[misc]
    assert all(item.index >= observer.encounters[0].origin.start_index
               for item in observer.encounters[0].observations)


def test_source_episode_barrier_and_monotonic_replay_are_hard_failures():
    observer = ResponseObserver(TEACH, "teach-EP001")
    observer.observe(sample(0, "105"))

    with pytest.raises(AssertionError, match="barrier"):
        observer.observe(sample(1, "105", episode="teach-EP002"))
    with pytest.raises(AssertionError, match="increasing"):
        observer.observe(sample(0, "105"))
    with pytest.raises(AssertionError, match="research buckets"):
        ResponseObserver("holdout", "holdout-EP001")


def test_validate_public_result_is_aggregate_only():
    observer = observe(
        sample(0, "105", bucket=VALIDATE),
        sample(1, "109.5", high="110", low="109", bucket=VALIDATE,
               interaction="AT_UPPER_EDGE"),
    )
    public = aggregate([observer])
    encoded = json.dumps(public, sort_keys=True)

    assert public["structure_population"]["episodes"] == 1
    assert "validate-EP001" not in encoded
    assert "C01" not in encoded
    assert BASE.isoformat() not in encoded
    assert "start_index" not in encoded


def test_same_causal_stream_has_deterministic_aggregate():
    stream = (
        sample(0, "105"),
        sample(1, "109.5", high="110", low="109", interaction="AT_UPPER_EDGE"),
        sample(2, "111", high="112", low="109", interaction="BREAK_ATTEMPT_UP"),
        sample(3, "109", high="111", low="108", interaction="RE_ENTRY"),
        sample(4, "107", high="108", low="106"),
    )

    assert aggregate([observe(*stream)]) == aggregate([observe(*stream)])
