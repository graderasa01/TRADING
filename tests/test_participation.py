"""
The participation context and the market eye — `src/livemap/participation.py`.

Ported from the research scratchpad at promotion, apart from the imports and the
position-carrying cases, which moved to `test_reactor.py` with the fold that owns them.
`block()` lives here and `test_reactor.py` imports it, so one 5m block is built per module
rather than per test.

What is pinned:

```
§26  causality      eye(upto=k) is prefix-equal to a full run truncated at k
§27  determinism    the same stream twice gives the same contexts
§13  the outcome    AVAILABLE / CONSTRAINED / UNAVAILABLE is presence-of-facts only
§30  no score       no threshold anywhere; a tiny free_to_near is never a constraint
§12  opportunity    new vs continuation vs repeat
§17  position       no automatic reversal, no second entry in one generation
§18  invalidation   always the CURRENT generation's structural reference
§31  execution      AVAILABLE never becomes an order
```
"""
from __future__ import annotations

from functools import lru_cache

import pytest

from src.boxes.frontier import run
from src.boxes.snapshot import build_snapshot
from src.feed.aggregator import Aggregator
from src.feed.replay_feed import ReplayFeed
from src.learning.split import load_split
from src.livemap import participation as PE
from src.livemap import release as R
from src.livemap import thesis as TH

SYMBOL = "NIFTY BANK"
BARS, HIST = 700, 400


def streams(days):
    """1m and 5m candles for `days`. The aggregator's own output, never re-derived."""
    m1, m5 = [], []
    for session in ReplayFeed(SYMBOL, on_gap="skip").sessions(days=days):
        agg = Aggregator(htf=("5m",))
        for candle in session.candles:
            m1.append(candle)
            update = agg.on_candle(candle)
            if update.m5 is not None:
                m5.append(update.m5)
    return m1, m5


@lru_cache(maxsize=4)
def block(n: int = 0):
    """One real teach block. Real data, because the whole point is that these layers
    compose over the market the stack actually produces.

    **Teach only.** No test in this repo may read the holdout, and this is the helper all
    three participation suites build from, so the restriction lives in one place.

    Cached: four module fixtures across three files want the same block, and rebuilding it
    each time cost about 18 seconds apiece. Sharing is safe because nothing mutates it —
    `test_the_engine_mutates_no_observation` is the assertion that keeps it safe.
    """
    sp = load_split()
    days = ReplayFeed(SYMBOL, on_gap="skip").available_days()
    _m1, m5 = streams(sp.teach(days)[:40])
    blk = m5[n * BARS:(n + 1) * BARS]
    snap = build_snapshot(blk[:HIST], SYMBOL)
    return snap, run(snap, blk[:HIST], blk[HIST:])


@pytest.fixture(scope="module")
def world():
    snap, f = block(0)
    return snap, f, PE.eye(snap, f)


@pytest.fixture(scope="module")
def with_release(world):
    _snap, _f, ctx = world
    return [c for c in ctx if c.release is not None]


# ═════════════════════════════════════════════════════════════════════════════
# §26 / §27
# ═════════════════════════════════════════════════════════════════════════════
def test_prefix_causality(world):
    snap, f, full = world
    for k in (full[5].index, full[len(full) // 2].index, full[-2].index):
        assert PE.eye(snap, f, upto=k) == [c for c in full if c.index <= k]


def test_determinism(world):
    snap, f, full = world
    assert PE.eye(snap, f) == full


def test_no_later_candle_rewrites_an_earlier_release(world):
    snap, f, full = world
    born = {r.id: r for c in full for r in c.all_releases}
    for k in (full[len(full) // 3].index, full[-3].index):
        for c in PE.eye(snap, f, upto=k):
            for r in c.all_releases:
                assert r == born[r.id]


# ═════════════════════════════════════════════════════════════════════════════
# §13 — the outcome is presence-of-facts
# ═════════════════════════════════════════════════════════════════════════════
def test_every_outcome_is_in_the_closed_vocabulary(world):
    _snap, _f, full = world
    assert {c.participation for c in full} <= PE.OUTCOMES
    assert {c.opportunity_kind for c in full} <= PE.OPPORTUNITIES


def test_unavailable_always_names_a_missing_fact(with_release):
    bad = [c for c in with_release
           if c.participation == PE.UNAVAILABLE and not c.reasons]
    assert not bad, "UNAVAILABLE without a named missing fact is a silent refusal"


def test_constrained_always_names_a_constraint(with_release):
    bad = [c for c in with_release
           if c.participation == PE.CONSTRAINED and not c.reasons]
    assert not bad


def test_available_carries_no_reasons(with_release):
    assert all(not c.reasons for c in with_release
               if c.participation == PE.AVAILABLE)


def test_available_always_has_the_four_required_facts(with_release):
    """A thesis with a direction, a current-generation invalidation, a release, and a
    mapped path beyond the boundary that broke."""
    for c in with_release:
        if c.participation != PE.AVAILABLE:
            continue
        assert c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA)
        assert c.invalidation_price is not None
        assert c.release is not None
        assert c.next_reference is not None and c.free_to_near is not None


def test_a_release_with_no_mapped_path_is_unavailable_not_constrained(with_release):
    """The difference matters: `CONSTRAINED` says *"I can see it and something blocks
    it"*; `UNAVAILABLE` says *"I cannot see it at all"*."""
    for c in with_release:
        if c.release is not None and c.next_reference is None and c.generation:
            assert c.participation == PE.UNAVAILABLE
            assert PE.NO_PATH in c.reasons


# ═════════════════════════════════════════════════════════════════════════════
# §30 — no score, no threshold
# ═════════════════════════════════════════════════════════════════════════════
def test_no_field_is_a_score():
    banned = ("score", "confidence", "probability", "strength", "weight", "rank",
              "rating", "quality")
    from dataclasses import fields
    offenders = [f.name for f in fields(PE.ParticipationContext)
                 if any(b in f.name.lower() for b in banned)]
    assert offenders == []


def test_a_tiny_path_is_reported_and_never_gated(with_release):
    """§21's second scenario — *"the next opposing structure is immediately ahead"* — is a
    fact on the context, not a refusal. Turning it into one needs a threshold, and no
    threshold has been earned."""
    have = sorted((c for c in with_release if c.free_to_near is not None),
                  key=lambda c: c.free_to_near)
    assert have, "no release carried a path at all — the test would assert nothing"
    thinnest = have[:max(1, len(have) // 4)]
    assert any(c.participation == PE.AVAILABLE for c in thinnest), (
        f"none of the {len(thinnest)} thinnest paths "
        f"(min {float(thinnest[0].free_to_near):.1f} pts) reached AVAILABLE — a thin "
        f"path has silently become a rejection, which is a hidden threshold")


def test_the_render_never_shows_a_number_as_a_verdict(world):
    _snap, _f, full = world
    for c in full[:200]:
        text = " ".join(c.render()).upper()
        for word in ("CONFIDENCE", "PROBABILITY", "SCORE", "GUARANTEED", "WILL REACH",
                     "EXPECTED TO REACH", "BUY", "SELL"):
            assert word not in text, f"{word!r} leaked into the trader view"


# ═════════════════════════════════════════════════════════════════════════════
# §12 — opportunity identity
# ═════════════════════════════════════════════════════════════════════════════
def test_a_repeat_of_the_same_boundary_in_one_generation_is_named(world):
    _snap, _f, full = world
    kinds = {c.opportunity_kind for c in full if c.release is not None}
    assert kinds <= PE.OPPORTUNITIES
    for c in full:
        if c.opportunity_kind == PE.SAME_GENERATION_REPEAT:
            assert PE.DUPLICATE in c.reasons
            assert c.participation == PE.CONSTRAINED


def test_a_continuation_release_is_never_entry_shaped(world):
    _snap, _f, full = world
    for c in full:
        if c.opportunity_kind in (PE.SAME_GENERATION_CONTINUATION,
                                  PE.SAME_GENERATION_REPEAT):
            assert not c.entry_shaped
            assert c.participation == PE.CONSTRAINED


def test_a_new_thesis_release_is_the_thesis_own_break(world):
    _snap, _f, full = world
    for c in full:
        if c.opportunity_kind == PE.NEW_THESIS:
            assert c.generation == 1
            assert c.release.broken_id is not None


# ═════════════════════════════════════════════════════════════════════════════
# §5 — simultaneous releases survive
# ═════════════════════════════════════════════════════════════════════════════
def test_simultaneous_releases_are_all_kept(world):
    _snap, _f, full = world
    multi = [c for c in full if c.simultaneous]
    if not multi:
        pytest.skip("no simultaneous release in this block")
    for c in multi:
        assert len(c.all_releases) > 1
        assert c.controlling_scale == R.MULTI_SCALE
        assert PE.MULTI_SCALE_UNRESOLVED in c.reasons or \
            c.participation == PE.UNAVAILABLE


def test_the_release_location_is_available_whenever_a_release_exists(with_release):
    """The hole the study measured: `PRICE_LOCATION` was `NO_STRUCTURE` on 82% of
    releases. The release-relative location is defined on 100% of them."""
    assert all(c.release_location is not None for c in with_release)
    assert all(c.release_location in R.RELEASE_LOCATIONS for c in with_release)


# ═════════════════════════════════════════════════════════════════════════════
# §18 — the invalidation is always the CURRENT generation's
# ═════════════════════════════════════════════════════════════════════════════
def test_invalidation_is_present_whenever_a_thesis_has_a_direction(world):
    _snap, _f, full = world
    for c in full:
        if c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA):
            assert c.invalidation_price is not None
            assert c.invalidation, "an invalidation price with no rule is half a fact"


def test_invalidation_wording_follows_the_generation(world):
    _snap, _f, full = world
    for c in full:
        if c.generation >= 2 and c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA):
            assert "generation" in c.invalidation, (
                "a reversal generation must not be worded like the original break")


def test_no_atr_or_percentage_stop_anywhere(world):
    """§18 forbids an invented stop. The invalidation must be a structural reference."""
    _snap, _f, full = world
    for c in full[:200]:
        text = " ".join(c.render()).lower()
        for word in ("atr stop", "trailing", "stop-loss", "stop loss", "% stop"):
            assert word not in text


# ═════════════════════════════════════════════════════════════════════════════
# §17 / §31 — position, reversal, execution
# ═════════════════════════════════════════════════════════════════════════════
def test_execution_status_is_always_unavailable(world):
    _snap, _f, full = world
    assert {c.execution_status for c in full} == {PE.EXEC_UNAVAILABLE}


def test_the_observer_view_carries_no_position(world):
    """`eye()` is the observation. The position-aware fold is `reactor.replay`, and there
    is deliberately only one of it — two folds applying the transition in different orders
    is how a research path and a live path start disagreeing about the same day."""
    _snap, _f, full = world
    assert {c.position for c in full} == {PE.FLAT}


# ═════════════════════════════════════════════════════════════════════════════
# composition — nothing is re-derived
# ═════════════════════════════════════════════════════════════════════════════
def test_the_context_copies_the_release_verbatim(world):
    """If the participation layer ever recomputed a release the two would drift, and the
    trace would stop describing the observation layer."""
    snap, f, full = world
    truth = {r.id: r for s in R.observe(f, snap) for r in s.releases}
    for c in full:
        for r in c.all_releases:
            assert r == truth[r.id]


def test_the_context_copies_the_thesis_verbatim(world):
    snap, f, full = world
    truth = {t.index: t for t in TH.narrate(snap, f)}
    for c in full:
        t = truth[c.index]
        assert (c.idea, c.generation, c.thesis_status, c.current_state) == (
            t.idea, t.generation, t.thesis_status, t.current_state)
        assert c.invalidation_price == t.invalidation_price
        assert c.current_location == t.price_location


def test_the_path_comes_from_the_release_not_from_the_current_structure(world):
    """The defect the whole build exists to fix, asserted on real candles."""
    _snap, _f, full = world
    for c in full:
        if c.release is None or c.release.route is None:
            continue
        assert c.free_to_near == c.release.route.free_to_near
        assert c.release.route.origin_edge == c.release.broken_edge
