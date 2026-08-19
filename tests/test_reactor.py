"""
The reactive participation engine — `src/livemap/reactor.py`.

Organised around §25 and §32, because the hard-stop conditions are what these tests exist
to catch:

```
§32.1  a decision requires a fact unavailable at that candle
§32.2  a future candle changes an earlier decision
§32.3  a repeated release creates duplicate participation
§32.4  same-generation continuation causes automatic re-entry
§32.5  opposite generation causes automatic reversal
§32.6  old-generation invalidation is applied to a new generation
§32.8  an arbitrary threshold is introduced
```

Every one of these ran green in the research scratchpad before promotion and is ported
unchanged apart from its imports, so a promotion that altered behaviour would show up here
rather than in a replay months later.
"""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

import pytest

from src.livemap import participation as PE
from src.livemap import reactor as RE
from src.livemap import release as R
from src.livemap import thesis as TH
from tests.test_participation import block


@pytest.fixture(scope="module")
def world():
    snap, f = block(0)
    return snap, f, RE.replay(snap, f)


@pytest.fixture(scope="module")
def research():
    snap, f = block(0)
    return snap, f, RE.replay(snap, f, execution=RE.ImmediateExecution())


# ═════════════════════════════════════════════════════════════════════════════
# The contract itself
# ═════════════════════════════════════════════════════════════════════════════
def test_every_vocabulary_is_closed(world):
    _s, _f, ds = world
    assert {d.action for d in ds} <= RE.ACTIONS
    assert {d.status for d in ds} <= RE.STATUSES
    assert {d.execution_status for d in ds} <= RE.EXEC_STATES
    assert {d.position for d in ds} <= RE.POSITIONS


def test_there_is_no_enter_action():
    assert not any(a.startswith("ENTER") for a in RE.ACTIONS)


def test_there_is_no_reverse_action():
    """§15 and §30: a reversal is two decisions on two candles, never one."""
    assert not any("REVERS" in a for a in RE.ACTIONS)


def test_no_field_is_a_score():
    banned = ("score", "confidence", "probability", "strength", "weight", "rank")
    assert [f.name for f in fields(RE.ParticipationDecision)
            if any(b in f.name.lower() for b in banned)] == []


def test_the_decision_does_not_duplicate_the_context(world):
    """§4: consume the existing objects, do not copy their fields."""
    names = {f.name for f in fields(RE.ParticipationDecision)}
    ctx_only = {"free_to_near", "zone_depth", "free_to_far", "next_reference",
                "invalidation_price", "micro_state", "release_scale", "generation",
                "idea", "current_state", "contradicted", "opportunity_kind"}
    assert not (names & ctx_only), f"duplicated context fields: {names & ctx_only}"


def test_every_decision_carries_a_reason(world):
    _s, _f, ds = world
    assert all(d.reasons for d in ds), "a silent decision is not inspectable"


def test_a_candidate_requires_a_flat_position():
    with pytest.raises(ValueError, match="entry is never considered while in"):
        RE.ParticipationDecision(index=0, at=None, price=Decimal(1), position=RE.LONG,
                                 action=RE.CANDIDATE_LONG, status=RE.ACTIVE,
                                 execution_status=RE.EXEC_UNAVAILABLE)


def test_hold_and_exit_require_the_matching_position():
    for action, pos in ((RE.HOLD_LONG, RE.SHORT), (RE.EXIT_SHORT, RE.LONG)):
        with pytest.raises(ValueError, match="while"):
            RE.ParticipationDecision(index=0, at=None, price=Decimal(1), position=pos,
                                     action=action, status=RE.ACTIVE,
                                     execution_status=RE.EXEC_NA)


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError, match="unknown action"):
        RE.ParticipationDecision(index=0, at=None, price=Decimal(1), position=RE.FLAT,
                                 action="ENTER_LONG", status=RE.ACTIVE,
                                 execution_status=RE.EXEC_NA)


# ═════════════════════════════════════════════════════════════════════════════
# §6 / §27 — participation is not execution
# ═════════════════════════════════════════════════════════════════════════════
def test_the_default_execution_contract_is_the_honest_one(world):
    _s, _f, ds = world
    for d in ds:
        if d.is_candidate:
            assert d.execution_status == RE.EXEC_UNAVAILABLE
            assert RE.R_NO_EXECUTION in d.reasons
        assert not d.would_execute


def test_no_position_is_ever_opened_under_the_default_contract(world):
    _s, _f, ds = world
    assert {d.position for d in ds} == {RE.FLAT}
    assert not any(d.action in (RE.HOLD_LONG, RE.HOLD_SHORT, RE.EXIT_LONG,
                                RE.EXIT_SHORT) for d in ds)


def test_a_candidate_exists_even_though_execution_does_not(world):
    """The whole point of §6: the structural answer and the timing answer are separate,
    and the first may be yes while the second is no."""
    _s, _f, ds = world
    cands = [d for d in ds if d.is_candidate]
    assert cands, "no candidate at all — the separation would be untested"
    assert all(d.status == RE.ACTIVE for d in cands)
    assert all(d.execution_status == RE.EXEC_UNAVAILABLE for d in cands)


def test_neither_execution_contract_claims_validation():
    assert RE.NoExecution().validated is False
    assert RE.ImmediateExecution().validated is False


def test_execution_status_is_not_applicable_when_there_is_nothing_to_time(world):
    _s, _f, ds = world
    for d in ds:
        if not d.is_candidate:
            assert d.execution_status == RE.EXEC_NA


# ═════════════════════════════════════════════════════════════════════════════
# §8 — the decision order
# ═════════════════════════════════════════════════════════════════════════════
def test_no_thesis_gives_no_trade(world):
    _s, _f, ds = world
    for d in ds:
        c = d.context
        if d.position == RE.FLAT and (c.generation == 0
                                      or c.idea not in (TH.LONG_IDEA, TH.SHORT_IDEA)):
            assert d.action == RE.NO_TRADE and d.status == RE.UNAVAILABLE


def test_a_live_thesis_with_no_new_development_gives_watch(world):
    _s, _f, ds = world
    seen = 0
    for d in ds:
        c = d.context
        if (d.position == RE.FLAT and c.generation
                and c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA) and c.release is None):
            assert d.action == RE.WATCH and d.status == RE.ACTIVE
            assert d.reasons == (RE.R_WATCHING,)
            seen += 1
    assert seen, "no watching candle — the assertion would be vacuous"


def test_a_missing_fact_gives_no_trade_and_names_it(world):
    _s, _f, ds = world
    for d in ds:
        c = d.context
        if (d.position == RE.FLAT and c.release is not None
                and c.participation == PE.UNAVAILABLE and c.generation
                and c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA)):
            assert d.action == RE.NO_TRADE and d.status == RE.UNAVAILABLE
            assert len(d.reasons) > 1, "the missing fact was not named"


def test_a_constraint_gives_no_trade_and_names_it(world):
    _s, _f, ds = world
    for d in ds:
        if d.context.participation == PE.CONSTRAINED and d.position == RE.FLAT:
            assert d.action == RE.NO_TRADE and d.status == RE.BLOCKED
            assert RE.R_CONSTRAINED in d.reasons and len(d.reasons) > 1


def test_a_candidate_has_the_five_facts(world):
    """A thesis with a direction, a release, a current-generation invalidation, a mapped
    path from the broken boundary, and a new opportunity identity."""
    _s, _f, ds = world
    for d in ds:
        if not d.is_candidate:
            continue
        c = d.context
        assert c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA)
        assert c.release is not None
        assert c.invalidation_price is not None
        assert c.next_reference is not None
        assert c.entry_shaped


def test_the_candidate_direction_follows_the_thesis_not_the_release(world):
    """Direction comes from the causal thesis. The release supplies the moment."""
    _s, _f, ds = world
    for d in ds:
        if d.action == RE.CANDIDATE_LONG:
            assert d.context.idea == TH.LONG_IDEA
        if d.action == RE.CANDIDATE_SHORT:
            assert d.context.idea == TH.SHORT_IDEA


# ═════════════════════════════════════════════════════════════════════════════
# §15 / §16 / §32.4 / §32.5 — position handling
# ═════════════════════════════════════════════════════════════════════════════
def test_a_position_is_held_while_the_generation_supports_it(research):
    _s, _f, ds = research
    holds = [d for d in ds if d.action in (RE.HOLD_LONG, RE.HOLD_SHORT)]
    assert holds, "no hold at all — the position machine was never exercised"
    for d in holds:
        assert d.status == RE.ACTIVE
        assert d.reasons == (RE.R_THESIS_HOLDS,)
        assert d.open_identity == d.context.thesis_identity


def test_an_exit_is_always_a_generation_or_idea_change(research):
    _s, _f, ds = research
    exits = [d for d in ds if d.action in (RE.EXIT_LONG, RE.EXIT_SHORT)]
    assert exits
    for d in exits:
        assert d.status == RE.INVALIDATED
        assert d.reasons[0] in (RE.R_GENERATION_CHANGED, RE.R_IDEA_REVERSED,
                                RE.R_THESIS_UNRESOLVED)


def test_no_automatic_reversal(research):
    """§32.5. LONG -> SHORT in one step would let a dead idea authorise a new position."""
    _s, _f, ds = research
    seq = [d.position for d in ds]
    for a, b in zip(seq, seq[1:]):
        assert not (a == RE.LONG and b == RE.SHORT)
        assert not (a == RE.SHORT and b == RE.LONG)


def test_an_exit_candle_never_also_opens(research):
    _s, _f, ds = research
    for d in ds:
        if d.action in (RE.EXIT_LONG, RE.EXIT_SHORT):
            assert not d.is_candidate


def test_a_same_generation_continuation_never_re_enters(research):
    """§32.4. A further release inside a live generation is management information."""
    _s, _f, ds = research
    for d in ds:
        c = d.context
        if c.opportunity_kind in (PE.SAME_GENERATION_CONTINUATION,
                                  PE.SAME_GENERATION_REPEAT):
            assert not d.is_candidate
            assert d.action in (RE.NO_TRADE, RE.HOLD_LONG, RE.HOLD_SHORT,
                                RE.EXIT_LONG, RE.EXIT_SHORT, RE.WATCH)


def test_no_entry_is_considered_while_in_a_position(research):
    _s, _f, ds = research
    for d in ds:
        if d.position != RE.FLAT:
            assert not d.is_candidate


def test_one_opportunity_authorises_at_most_one_entry(research):
    """§32.3 and §18."""
    _s, _f, ds = research
    opened = [d.opportunity[0] for d in ds if d.would_execute and d.opportunity]
    assert opened, "nothing was opened — the assertion would be vacuous"
    assert len(opened) == len(set(opened))


def test_a_repeated_release_does_not_create_a_second_candidate(world):
    _s, _f, ds = world
    keys: set = set()
    for d in ds:
        if not d.is_candidate or d.opportunity is None:
            continue
        assert d.opportunity not in keys, f"duplicate participation on {d.opportunity}"
        keys.add(d.opportunity)


# ═════════════════════════════════════════════════════════════════════════════
# §17 / §32.6 — invalidation belongs to the current generation
# ═════════════════════════════════════════════════════════════════════════════
def test_a_held_position_always_matches_the_current_thesis(research):
    """Identity, not the integer. Audited over teach and validate, 14% of thesis
    transitions carry an equal generation integer, so an integer comparison here would
    pass while a position ran under a thesis that did not open it."""
    _s, _f, ds = research
    for d in ds:
        if d.action in (RE.HOLD_LONG, RE.HOLD_SHORT):
            assert d.open_identity == d.context.thesis_identity, (
                "a position survived into a thesis that did not open it")


def test_the_invalidation_wording_follows_the_generation(world):
    _s, _f, ds = world
    for d in ds:
        c = d.context
        if c.generation >= 2 and c.idea in (TH.LONG_IDEA, TH.SHORT_IDEA):
            assert "generation" in c.invalidation


def test_no_invented_stop_appears_anywhere(world):
    """§16 and §30: no trailing stop, no percentage stop, no ATR stop, no target."""
    _s, _f, ds = world
    for d in ds[:250]:
        text = " ".join(RE.render(d)).lower()
        for word in ("trailing", "atr stop", "stop loss", "stop-loss", "% stop",
                     "target", "will reach", "expected to reach", "guaranteed"):
            assert word not in text, f"{word!r} leaked into the trader render"


# ═════════════════════════════════════════════════════════════════════════════
# §25 — causality and determinism
# ═════════════════════════════════════════════════════════════════════════════
def test_prefix_causality(world):
    """§32.2. Actions, positions, statuses and contexts must all be prefix-equal."""
    snap, f, full = world
    for k in (full[5].index, full[len(full) // 2].index, full[-2].index):
        cut = RE.replay(snap, f, upto=k)
        assert cut == [d for d in full if d.index <= k]


def test_prefix_causality_in_research_mode(research):
    snap, f, full = research
    k = full[len(full) // 2].index
    cut = RE.replay(snap, f, execution=RE.ImmediateExecution(), upto=k)
    assert cut == [d for d in full if d.index <= k]


def test_determinism(world):
    snap, f, full = world
    assert RE.replay(snap, f) == full
    assert RE.replay(snap, f) == RE.replay(snap, f)


def test_no_future_candle_changes_an_earlier_decision(world):
    snap, f, full = world
    born = {d.index: d for d in full}
    for k in (full[len(full) // 3].index, full[-3].index):
        for d in RE.replay(snap, f, upto=k):
            assert d == born[d.index]


# ═════════════════════════════════════════════════════════════════════════════
# §32.1 — a decision never needs a fact it does not have
# ═════════════════════════════════════════════════════════════════════════════
def test_a_candidate_never_rests_on_a_missing_fact(world):
    _s, _f, ds = world
    for d in ds:
        if not d.is_candidate:
            continue
        c = d.context
        for name in ("release", "invalidation_price", "next_reference", "free_to_near",
                     "opportunity"):
            assert getattr(c, name) is not None, f"candidate with no {name}"


def test_an_unavailable_fact_is_always_named_never_substituted(world):
    _s, _f, ds = world
    for d in ds:
        if d.status == RE.UNAVAILABLE:
            assert len(d.reasons) >= 1
            assert all(isinstance(r, str) for r in d.reasons)


# ═════════════════════════════════════════════════════════════════════════════
# §11 — multi-scale
# ═════════════════════════════════════════════════════════════════════════════
def test_a_multi_scale_candle_keeps_every_release(world):
    _s, _f, ds = world
    multi = [d for d in ds if d.context.simultaneous]
    if not multi:
        pytest.skip("no simultaneous release in this block")
    for d in multi:
        assert len(d.context.all_releases) > 1
        assert d.context.controlling_scale == R.MULTI_SCALE
        text = " ".join(RE.render(d))
        for rec in d.context.all_releases:
            assert rec.broken_id in text, "a release vanished from the render"


def test_multi_scale_is_never_silently_resolved(world):
    _s, _f, ds = world
    for d in ds:
        if d.context.simultaneous:
            assert d.context.controlling_scale == R.MULTI_SCALE


# ═════════════════════════════════════════════════════════════════════════════
# §23 — the narrative is a restatement, never an extra claim
# ═════════════════════════════════════════════════════════════════════════════
def test_the_narrative_never_predicts(world):
    _s, _f, ds = world
    for d in ds[:250]:
        text = RE.narrative(d).lower()
        for word in ("will ", "expect", "should reach", "target", "likely",
                     "probably", "confidence"):
            assert word not in text, f"{word!r} turned the narrative into a forecast"


def test_the_narrative_mentions_the_release_when_there_is_one(world):
    _s, _f, ds = world
    for d in ds:
        if d.context.release is not None:
            assert d.context.release.broken_id in RE.narrative(d)


def test_the_render_order_is_the_one_the_brief_fixes(world):
    """WHAT HAPPENED -> WHERE -> THESIS -> PATH -> INVALIDATION -> PARTICIPATION ->
    EXECUTION. A reader relies on that order; a reshuffle would be a silent change."""
    _s, _f, ds = world
    d = next(d for d in ds if d.is_candidate)
    lines = RE.render(d)
    heads = [ln.split()[0] for ln in lines]
    for a, b in (("NEW", "LOCATION"), ("LOCATION", "PATH"), ("PATH", "INVALIDATION"),
                 ("INVALIDATION", "ACTION"), ("ACTION", "EXECUTION")):
        assert heads.index(a) < heads.index(b), f"{a} must come before {b}"


# ═════════════════════════════════════════════════════════════════════════════
# integration — the engine agrees with the layers it consumes
# ═════════════════════════════════════════════════════════════════════════════
def test_the_engine_and_the_observer_see_the_same_contexts(world):
    snap, f, ds = world
    obs = PE.eye(snap, f)
    assert [d.context for d in ds] == obs, (
        "the decision fold and the observer fold have drifted apart")


def test_the_context_still_copies_its_sources(world):
    snap, f, ds = world
    truth = {t.index: t for t in TH.narrate(snap, f)}
    rel = {r.id: r for s in R.observe(f, snap) for r in s.releases}
    for d in ds:
        c = d.context
        t = truth[c.index]
        assert (c.idea, c.generation, c.thesis_status) == (t.idea, t.generation,
                                                           t.thesis_status)
        assert c.invalidation_price == t.invalidation_price
        for x in c.all_releases:
            assert x == rel[x.id]


def test_decide_is_a_pure_function(world):
    """Same `(context, thesis, contract)`, same decision — re-run out of the fold, so a
    hidden dependence on the loop's state would show up here."""
    snap, f, ds = world
    theses = {t.index: t for t in TH.narrate(snap, f)}
    for d in ds[:150]:
        assert RE.decide(d.context, theses[d.index],
                         execution=RE.NoExecution()) == d
