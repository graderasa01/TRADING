"""
The authoritative break source — `src/livemap/breaks.py`.

One measurement is the whole reason this module exists. Over 29 replay blocks of real
Bank Nifty 5m:

```
distinct breaks                     578
  reported as ACCEPTED_*            783
  overwritten                       121  (21%)  — mostly REVISIT, some NEW_CLUSTER
```

`Frontier.on_candle` step 1 accepts the break and clears `self.current`; step 3 then runs
on the same candle, finds `current is None`, re-adopts or mints, and **unconditionally
reassigns** `interaction`. The break event is still in the log. The reading is not.

So the tests below are mostly one assertion said several ways: **every break in the log
comes back, whatever the reading ended up calling it.**

Nothing here changes break detection, acceptance, or the meaning of `ACCEPTED_*`, and
`test_accepted_still_means_exactly_what_it_meant` pins that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.boxes.structure import tol_at
from src.livemap import breaks as B
from src.livemap.breaks import ACCEPTED, FROZEN, LIVE, BreakRecord, from_logs, hidden
from src.livemap.retest import breaks_from
from tests.test_frontier_evidence import SHAPES, SPLIT, frontier_for, sit
from tests.test_micro import WIDE_BROKE, WIDE_ENDED, WIDE_HELD

#: `C01` in a plain `sit()` fixture is 22,460.7-22,475.1 and `tol` there is 3.0.
#:
#: The window in which a break **hides** is exactly `tol` wide and sits immediately above
#: the band: a close must be outside the band for acceptance to fire, and within
#: `high + tol` for step 3 to re-adopt the same structure on that same candle. Below the
#: window nothing breaks; above it, acceptance survives because there is nothing to adopt.
HI, TOL = 22475.1, 3.0
BASE = sit(22470, SPLIT + 30, 18)
ALL_HIDDEN = BASE + [HI + TOL * 0.5] * 6      # every break overwritten by REVISIT
MIXED = BASE + [HI + TOL * 0.8] * 6           # some overwritten, some not

ALL_SHAPES = dict(SHAPES, held=WIDE_HELD, broke=WIDE_BROKE, ended=WIDE_ENDED,
                  all_hidden=ALL_HIDDEN, mixed=MIXED)


def log_breaks(f):
    """The ground truth: every `break` event the frontier recorded, in either log."""
    return [e for e in list(f.log) + list(f.live_log) if e.kind == "break"]


# ─────────────────────────────────────────────────────────────────────────────
# the fixture is real
# ─────────────────────────────────────────────────────────────────────────────
def test_the_hiding_window_exists_and_is_tol_wide():
    """If this fails the fixture has drifted and every test below is testing nothing."""
    f = frontier_for(BASE)
    node = f.snapshot.structures()[0]
    assert (float(node.low), float(node.high)) == pytest.approx((22460.7, 22475.1))
    assert float(tol_at(f.candles, len(f.candles) - 1, Decimal("0.25"))) == TOL


def test_a_break_really_can_be_overwritten_on_its_own_candle():
    f = frontier_for(ALL_HIDDEN)
    records = from_logs(f)
    assert records, "the fixture produced no breaks at all"
    assert hidden(records) == records, (
        "every break in this fixture should have been overwritten; "
        f"got {[r.interaction for r in records]}")
    assert {r.interaction for r in records} == {"REVISIT"}


def test_the_mixed_fixture_exercises_both_paths():
    records = from_logs(frontier_for(MIXED))
    named = [r for r in records if r.named_by_interaction]
    assert named and hidden(records), (
        f"needed both kinds, got {[r.interaction for r in records]}")


# ─────────────────────────────────────────────────────────────────────────────
# the one thing this module is for
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_every_break_event_comes_back(name):
    """Every **break**, not every row. A revisited node writes twice — the owner's log
    keeps its plain record and `live_log` carries the evidence-bearing twin — so the row
    count is not the break count. Measured over the replay: 991 rows, 578 breaks."""
    f = frontier_for(ALL_SHAPES[name])
    distinct = sorted({(e.index, e.node_id, e.direction) for e in log_breaks(f)})
    records = from_logs(f)
    assert len(records) == len(distinct)
    assert [(r.index, r.structure_id, r.direction) for r in records] == distinct


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_one_break_is_one_record(name):
    f = frontier_for(ALL_SHAPES[name])
    records = from_logs(f)
    keys = [(r.index, r.structure_id, r.direction) for r in records]
    assert len(keys) == len(set(keys)), f"duplicate rows survived: {keys}"


def test_the_revisit_twins_evidence_survives_the_merge():
    """A2 put a revisited structure's accumulated evidence on the twin event, because a
    revisit is never finalised and it would otherwise die there. Collapsing the pair must
    not throw it away."""
    f = frontier_for(ALL_HIDDEN)
    twins = [e for e in log_breaks(f) if e.detail == B.REVISIT_ENDED]
    assert twins and all(e.evidence for e in twins)
    for r in from_logs(f):
        assert r.evidence, f"{r.structure_id} at c{r.index} lost the revisit evidence"


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_log_is_a_superset_of_what_the_interaction_names(name):
    """`retest.breaks_from()` reads `Reading.interaction` and therefore carries the same
    blind spot. It is left exactly as it is — this asserts the relationship rather than
    changing it."""
    f = frontier_for(ALL_SHAPES[name])
    records = from_logs(f)
    by_interaction = breaks_from(f.readings, f.candles)

    from_log = {(b.index, b.structure_id) for b in records}
    from_reading = {(b.index, b.structure_id) for b in by_interaction}
    assert from_reading <= from_log, (
        f"the interaction named a break the log does not have: "
        f"{from_reading - from_log}")


def test_reading_the_interaction_alone_loses_breaks():
    """The defect, as an assertion rather than a paragraph."""
    f = frontier_for(ALL_HIDDEN)
    assert len(from_logs(f)) == 3
    assert breaks_from(f.readings, f.candles) == []


def test_hidden_names_exactly_the_overwritten_ones():
    f = frontier_for(MIXED)
    records = from_logs(f)
    assert hidden(records) == [r for r in records if r.interaction not in ACCEPTED]
    for r in records:
        assert r.named_by_interaction == (r.interaction in ACCEPTED)


# ─────────────────────────────────────────────────────────────────────────────
# what each record carries
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_records_arrive_in_candle_order(name):
    records = from_logs(frontier_for(ALL_SHAPES[name]))
    assert [r.index for r in records] == sorted(r.index for r in records)


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_geometry_is_resolved_even_when_the_reading_lost_it(name):
    """Step 3 clears `self.left` too, so on an overwritten candle `Reading.left_low` is
    gone. The band is resolved from the node instead — the snapshot for a frozen one, the
    frontier's finalised history for a live one."""
    f = frontier_for(ALL_SHAPES[name])
    for r in from_logs(f):
        assert r.low is not None and r.high is not None, r
        assert r.low < r.high
        assert r.edge in (r.low, r.high)
        assert (r.edge == r.high) == (r.direction == "up")


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_source_says_which_map_owned_the_structure(name):
    f = frontier_for(ALL_SHAPES[name])
    for r in from_logs(f):
        in_snapshot = f.snapshot.by_id(r.structure_id) is not None
        assert r.source == (FROZEN if in_snapshot else LIVE)


def test_a_live_minted_structure_reaches_the_list():
    """Phase A2's finding was that live nodes carry about three quarters of all breaks.
    A source reading only `Frontier.log` would miss every one of them."""
    f = frontier_for(SHAPES["walkthrough"])
    assert any(r.source == LIVE for r in from_logs(f))


# ─────────────────────────────────────────────────────────────────────────────
# nothing about breaking changed
# ─────────────────────────────────────────────────────────────────────────────
def test_accepted_still_means_exactly_what_it_meant():
    assert ACCEPTED == {"ACCEPTED_ABOVE": "up", "ACCEPTED_BELOW": "down"}
    from src.livemap import retest
    assert retest.ACCEPTED == ACCEPTED


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_this_module_reads_and_changes_nothing(name):
    """Calling it twice, and calling it at all, must leave the frontier untouched."""
    f = frontier_for(ALL_SHAPES[name])
    before = (len(f.log), len(f.live_log), len(f.finalised), len(f.readings))
    first = from_logs(f)
    second = from_logs(f)
    assert first == second
    assert (len(f.log), len(f.live_log), len(f.finalised), len(f.readings)) == before


def test_the_vocabularies_are_closed():
    with pytest.raises(ValueError):
        BreakRecord(index=0, at=None, structure_id="C01", direction="sideways",
                    edge=Decimal(1))
    with pytest.raises(ValueError):
        BreakRecord(index=0, at=None, structure_id="C01", direction="up",
                    edge=Decimal(1), source="guessed")
    assert B.SOURCES == {FROZEN, LIVE}


def test_this_module_is_only_a_source():
    """The episode lives in `postbreak.py`. This module resolves the log into records and
    stops — it has no state machine and no lifecycle."""
    assert not hasattr(B, "BreakEpisode")
    assert not hasattr(B, "observe")
    assert set(B.__all__) == {"ACCEPTED", "BREAK_KIND", "REVISIT_ENDED", "FROZEN", "LIVE",
                              "SOURCES", "BreakRecord", "from_logs", "hidden"}


def test_only_one_event_kind_is_admitted():
    """L1, at the source. `EVENT_KINDS` permits nine; this admits one, by name."""
    from src.boxes.snapshot import EVENT_KINDS
    assert B.BREAK_KIND == "break"
    assert B.BREAK_KIND in EVENT_KINDS
    assert len(EVENT_KINDS) > 1
