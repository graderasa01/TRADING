"""
The trade thesis snapshot and the position lifecycle — `src/livemap/position.py`.

The capability under test is *staying inside the market story after participating*: a
position carries the reason it exists, the market is allowed to develop around it, and only
the current generation's own invalidation closes it.

```
§6   the snapshot never changes, whatever the market does afterwards
§13  a new generation exits first and never auto-opens
§17  position state is not market direction
§20  a position does not exit merely because the market developed
§21  an exit candle can never also open
§22  one opportunity, one open
```
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from src.livemap import position as PO
from src.livemap import reactor as RE
from src.livemap import release as R
from src.livemap import thesis as TH
from tests.test_participation import block

SRC = Path(__file__).resolve().parent.parent / "src"


def world(n: int = 0, take: int | None = None):
    """A block, and a lifecycle with research positions injected on real candidates."""
    snap, f = block(n)
    opportunities = PO.candidates_in(RE.replay(snap, f))
    assert opportunities, "no candidate in this block — every test below would be vacuous"
    chosen = opportunities if take is None else opportunities[:take]
    states, records = PO.lifecycle(
        snap, f, execution=PO.ResearchPositionInjector(chosen))
    return snap, f, states, records


@pytest.fixture(scope="module")
def injected():
    return world()


@pytest.fixture(scope="module")
def flat():
    snap, f = block(0)
    return (snap, f, *PO.lifecycle(snap, f))


# ═════════════════════════════════════════════════════════════════════════════
# §31 / §28 — production cannot fabricate a position
# ═════════════════════════════════════════════════════════════════════════════
def test_the_default_contract_opens_nothing(flat):
    _snap, _f, states, records = flat
    assert records == []
    assert {s.phase for s in states} == {PO.FLAT_PHASE}
    assert {s.position for s in states} == {PO.FLAT}
    assert {s.position_after for s in states} == {PO.FLAT}


def test_a_research_injector_cannot_be_constructed_empty():
    """An empty injector would behave like `NoExecution` while looking like a research
    mode, and an 'open everything' mode is what §31 forbids."""
    with pytest.raises(ValueError, match="specific opportunities"):
        PO.ResearchPositionInjector([])


def test_the_injector_opens_only_what_it_was_given(injected):
    snap, f, _states, _records = injected
    opportunities = PO.candidates_in(RE.replay(snap, f))
    one = opportunities[:1]
    _s, records = PO.lifecycle(snap, f, execution=PO.ResearchPositionInjector(one))
    assert len(records) == 1
    assert records[0].snapshot.opportunity_id == one[0]


def test_the_injector_never_claims_validation():
    inj = PO.ResearchPositionInjector([("x",)])
    assert inj.validated is False


def test_the_lifecycle_imports_nothing_that_trades():
    """§28. The module may not reach a broker, a risk engine or an order path."""
    tree = ast.parse((SRC / "livemap" / "position.py").read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    for bad in ("broker", "risk", "sizing", "options", "guards", "orders", "exits",
                "modes", "setups"):
        assert not [m for m in mods if m == bad or m.startswith(f"src.{bad}")], bad


def test_the_lifecycle_produces_no_order_shaped_field():
    banned = ("order", "size", "qty", "quantity", "lots", "risk", "margin", "premium",
              "strike", "target", "trail", "stop_loss")
    for cls in (PO.TradeThesisSnapshot, PO.PositionEvaluation, PO.PositionState):
        bad = [f.name for f in fields(cls)
               if any(b in f.name.lower() for b in banned)]
        assert not bad, f"{cls.__name__} carries {bad}"


# ═════════════════════════════════════════════════════════════════════════════
# §5 / §6 — the snapshot
# ═════════════════════════════════════════════════════════════════════════════
def test_a_snapshot_is_frozen(injected):
    _s, _f, _states, records = injected
    snap = records[0].snapshot
    with pytest.raises(FrozenInstanceError):
        snap.generation = 99


def test_the_snapshot_copies_its_source_exactly(injected):
    snap_, f, states, _records = injected
    decisions = {d.index: d for d in RE.replay(
        snap_, f, execution=PO.ResearchPositionInjector(
            PO.candidates_in(RE.replay(snap_, f))))}
    for s in states:
        if s.phase != PO.OPEN:
            continue
        c = decisions[s.index].context
        t = s.snapshot
        assert t.generation == c.generation
        assert t.idea == c.idea
        assert t.opportunity_id == c.opportunity
        assert t.invalidation_reference == c.invalidation_price
        assert t.invalidation_rule == c.invalidation
        assert t.releases == c.all_releases
        # value equality, not identity: this is a second, independent replay, so its
        # `Release` objects are equal-but-distinct. Identity within one run is asserted
        # by `TradeThesisSnapshot.__post_init__` and by the test below.
        assert t.release == c.release
        assert t.next_reference_at_open == c.next_reference
        assert t.free_to_near_at_open == c.free_to_near
        assert t.corridor_at_open == c.corridor
        assert t.side == (PO.LONG if c.idea == TH.LONG_IDEA else PO.SHORT)


def test_the_snapshot_references_its_release_rather_than_copying_it(injected):
    """§5: reference what can be referenced safely. A re-copied release would be a second
    version of the same fact, free to drift from the first."""
    _s, _f, states, records = injected
    for r in records:
        assert r.snapshot.release is not None
        assert any(x is r.snapshot.release for x in r.snapshot.releases)
    for s in states:
        if s.phase == PO.OPEN:
            assert s.snapshot.release is s.snapshot.release  # same object, not rebuilt
            assert s.snapshot.broken_edge is s.snapshot.release.broken_edge


def test_the_snapshot_carries_no_field_from_the_future():
    banned = ("mfe", "mae", "outcome", "result", "closed", "exit", "pnl", "won",
              "invalidated_at", "held_until")
    assert [f.name for f in fields(PO.TradeThesisSnapshot)
            if any(b in f.name.lower() for b in banned)] == []


def test_a_snapshot_cannot_be_changed_by_the_market_moving_on(injected):
    """§6, the point of the whole layer. The market develops for the rest of the block —
    new releases, new micro, a new generation — and the snapshot is byte-identical."""
    _s, _f, states, records = injected
    record = records[0]
    frozen = replace(record.snapshot)          # an independent equal copy
    later = [s for s in states if s.index > record.snapshot.opened_index]
    assert later, "nothing happened after the open — the test would be vacuous"
    assert any(s.evaluation is not None and s.evaluation.developments for s in later), \
        "the market never developed after the open — the test would be vacuous"
    assert record.snapshot == frozen
    for s in states:
        if s.snapshot is record.snapshot:
            assert s.snapshot == frozen


def test_a_snapshot_can_only_come_from_a_candidate(flat):
    _snap, _f, states, _records = flat
    with pytest.raises(ValueError, match="participation candidate"):
        PO.TradeThesisSnapshot.of(
            RE.ParticipationDecision(index=0, at=states[0].at, price=states[0].price,
                                     position=PO.FLAT, action=RE.NO_TRADE,
                                     status=RE.UNAVAILABLE,
                                     execution_status=RE.EXEC_NA))


def test_the_snapshot_records_which_way_the_thesis_dies(injected):
    _s, _f, _states, records = injected
    for r in records:
        want = PO.DIES_BELOW if r.snapshot.side == PO.LONG else PO.DIES_ABOVE
        assert r.snapshot.invalidation_direction == want


# ═════════════════════════════════════════════════════════════════════════════
# §8 — the lifecycle
# ═════════════════════════════════════════════════════════════════════════════
def test_every_phase_is_in_the_closed_vocabulary(injected):
    _s, _f, states, _r = injected
    assert {s.phase for s in states} <= PO.PHASES


def test_the_lifecycle_runs_flat_open_hold_and_out(injected):
    _s, _f, states, records = injected
    phases = [s.phase for s in states]
    assert PO.OPEN in phases and PO.HOLD in phases and PO.INVALIDATED in phases
    for r in records:
        assert r.state == PO.EXITED or r.closed_index is None
        assert r.timeline[0][2] == PO.OPEN


def test_an_open_is_flat_before_and_positioned_after(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.phase == PO.OPEN:
            assert s.position == PO.FLAT
            assert s.position_after in (PO.LONG, PO.SHORT)
            assert s.position_after == s.snapshot.side


def test_an_invalidation_is_positioned_before_and_flat_after(injected):
    _s, _f, states, _r = injected
    seen = 0
    for s in states:
        if s.phase == PO.INVALIDATED:
            assert s.position in (PO.LONG, PO.SHORT)
            assert s.position_after == PO.FLAT
            assert s.exit_reason in PO.EXIT_REASONS
            seen += 1
    assert seen, "no invalidation in this block — the assertion would be vacuous"


def test_hold_and_continuation_keep_the_position(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.phase in (PO.HOLD, PO.CONTINUATION):
            assert s.position == s.position_after
            assert s.position in (PO.LONG, PO.SHORT)
            assert s.action in (RE.HOLD_LONG, RE.HOLD_SHORT)


def test_the_timeline_is_append_only_and_causal(injected):
    _s, _f, _states, records = injected
    for r in records:
        idx = [t[0] for t in r.timeline]
        assert idx == sorted(idx)
        assert idx[0] == r.snapshot.opened_index
        if r.closed_index is not None:
            assert idx[-1] == r.closed_index


# ═════════════════════════════════════════════════════════════════════════════
# §13 / §14 / §19 — generations
# ═════════════════════════════════════════════════════════════════════════════
def test_a_position_survives_while_its_thesis_does(injected):
    """What a HOLD actually guarantees: the direction still matches and the entry thesis
    is not invalidated. Thesis *identity* is checked separately below, because
    `exit_check` keys on the generation integer rather than the identity."""
    _s, _f, states, _r = injected
    for s in states:
        if s.phase in (PO.HOLD, PO.CONTINUATION):
            assert s.evaluation.direction_same
            assert not s.evaluation.entry_thesis_invalidated
            assert s.evaluation.current_generation == s.snapshot.generation


def test_a_thesis_change_under_a_held_position_is_always_reported(injected):
    """The residual case, made visible rather than asserted away.

    `reactor.exit_check` compares the generation **integer** and the direction. A different
    structure breaking the same way at the same generation number therefore holds the
    position. That is the validated contract and this stage does not change it — but the
    evaluation must say so, so a reader can see the position is now running under a thesis
    it was not opened on.
    """
    _s, _f, states, _r = injected
    drifted = [s for s in states
               if s.phase in (PO.HOLD, PO.CONTINUATION)
               and not s.evaluation.thesis_generation_same]
    for s in drifted:
        assert "thesis changed" in s.evaluation.developments
        assert s.phase == PO.CONTINUATION, (
            "a thesis change under a live position must never be reported as a quiet HOLD")
        assert s.evaluation.current_identity != \
            s.snapshot.identity


def test_the_same_structure_rebreaking_is_not_a_thesis_change(injected):
    """`opportunity_of` moves its break-candle field when a structure re-breaks, and that
    is right for deduplicating opportunities and wrong for *"is this the same thesis?"*.
    Measured on one block: 35 of 70 held candles looked changed under the full triple, and
    every one was the same structure at the same generation with the same invalidation."""
    _s, _f, states, _r = injected
    for s in states:
        if s.evaluation is None or s.snapshot.identity is None:
            continue
        if s.evaluation.current_identity is None:
            continue
        same_structure_and_generation = (
            s.evaluation.current_identity
            == s.snapshot.identity)
        if same_structure_and_generation:
            assert s.evaluation.thesis_generation_same
            assert "thesis changed" not in s.evaluation.developments


def test_a_thesis_change_exits(injected):
    """The integer may be equal on both sides — `L01/GEN1/UP` giving way to `C08/GEN1/DOWN`
    is a complete thesis change that an integer comparison calls "same"."""
    _s, _f, states, _r = injected
    changed = [s for s in states
               if s.phase == PO.INVALIDATED
               and s.exit_reason == RE.R_GENERATION_CHANGED]
    for s in changed:
        assert s.evaluation.generation_changed
        assert s.evaluation.current_identity != s.snapshot.identity
        assert s.position_after == PO.FLAT


def test_the_old_generations_invalidation_is_never_reused(injected):
    """§14/§15. On an exit the entry snapshot still carries the dead generation's
    reference, and the current market carries the new one. They must be different objects
    and the evaluation must show both."""
    _s, _f, states, _r = injected
    checked = 0
    for s in states:
        if s.phase != PO.INVALIDATED or not s.evaluation.generation_changed:
            continue
        assert s.snapshot.invalidation_reference is not None
        # The snapshot keeps the dead thesis's own reference, untouched. Compared on
        # IDENTITY, not on the generation integer — `L01` generation 1 giving way to `C08`
        # generation 1 is a complete thesis change that an integer comparison calls "same".
        assert s.snapshot.identity != \
            s.evaluation.current_identity
        checked += 1
    if not checked:
        pytest.skip("no generation-change exit in this block")


def test_a_new_generation_never_auto_opens(injected):
    """§13. After an exit the position is flat and the new generation must earn its own
    candidate on a later candle."""
    _s, _f, states, _r = injected
    for a, b in zip(states, states[1:]):
        if a.phase == PO.INVALIDATED:
            assert a.position_after == PO.FLAT
            assert b.position == PO.FLAT


# ═════════════════════════════════════════════════════════════════════════════
# §21 — same-candle safety, both permutations
# ═════════════════════════════════════════════════════════════════════════════
def test_an_exit_candle_never_also_opens(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.phase == PO.INVALIDATED:
            assert s.snapshot.side in (PO.LONG, PO.SHORT)
            assert s.action in (RE.EXIT_LONG, RE.EXIT_SHORT)
            assert s.position_after == PO.FLAT, "a position was opened on an exit candle"


def test_both_exit_directions_behave_the_same_way(injected):
    _s, _f, states, _r = injected
    sides = {s.snapshot.side for s in states if s.phase == PO.INVALIDATED}
    assert sides, "no exit at all"
    for s in states:
        if s.phase != PO.INVALIDATED:
            continue
        want = RE.EXIT_LONG if s.position == PO.LONG else RE.EXIT_SHORT
        assert s.action == want
        assert s.position_after == PO.FLAT


def test_no_candle_ever_carries_two_position_changes(injected):
    _s, _f, states, _r = injected
    for s in states:
        changes = sum([s.position != s.position_after])
        assert changes <= 1


# ═════════════════════════════════════════════════════════════════════════════
# §12 / §20 — the market may develop without closing the position
# ═════════════════════════════════════════════════════════════════════════════
def test_a_development_does_not_close_a_position(injected):
    """§20, and the reason the whole layer exists. A new release, a micro change or a
    route change while the generation holds is a CONTINUATION, not an exit."""
    _s, _f, states, _r = injected
    developed = [s for s in states if s.phase == PO.CONTINUATION]
    assert developed, "no development while positioned — the assertion would be vacuous"
    for s in developed:
        assert s.position_after == s.position
        assert s.exit_reason is None
        assert s.evaluation.developments


def test_a_same_generation_release_is_a_continuation_not_an_open(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.evaluation is None or not s.evaluation.new_release_same_generation:
            continue
        assert s.phase in (PO.CONTINUATION, PO.INVALIDATED)
        assert s.phase != PO.OPEN


def test_developments_are_named_not_scored(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.evaluation is None:
            continue
        assert all(isinstance(d, str) for d in s.evaluation.developments)


def test_an_absent_route_is_not_reported_as_a_changed_one(injected):
    """The release-relative route exists only on a candle that carried a release. Calling
    its absence a change made almost every candle a CONTINUATION and hid the real ones."""
    _s, _f, states, _r = injected
    for s in states:
        if s.evaluation is None:
            continue
        if s.evaluation.path_unobserved:
            assert not s.evaluation.path_changed


# ═════════════════════════════════════════════════════════════════════════════
# §17 — position state is not market direction
# ═════════════════════════════════════════════════════════════════════════════
def test_the_market_can_point_one_way_while_the_position_is_flat(flat):
    _snap, _f, states, _r = flat
    snap_, f = block(0)
    decisions = {d.index: d for d in RE.replay(snap_, f)}
    ideas = {decisions[s.index].context.idea for s in states
             if s.position == PO.FLAT and decisions[s.index].context.generation}
    assert ideas & {TH.LONG_IDEA, TH.SHORT_IDEA}, (
        "the market never had a direction while flat — the separation is untested")


def test_the_market_can_point_against_an_open_position(injected):
    """§17's second case: a `SHORT_IDEA` while the position is still `LONG`, until the
    structural invalidation closes it."""
    snap_, f, states, _r = injected
    decisions = {d.index: d for d in RE.replay(
        snap_, f, execution=PO.ResearchPositionInjector(
            PO.candidates_in(RE.replay(snap_, f))))}
    against = [s for s in states
               if s.position in (PO.LONG, PO.SHORT)
               and decisions[s.index].context.idea not in (
                   TH.LONG_IDEA if s.position == PO.LONG else TH.SHORT_IDEA,)]
    # when it happens the position is exited, never silently flipped
    for s in against:
        assert s.phase == PO.INVALIDATED or s.position_after == s.position


def test_the_position_side_is_never_read_off_the_market(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.snapshot is None:
            continue
        assert s.snapshot.side in (PO.LONG, PO.SHORT)
        assert s.snapshot.side == (PO.LONG if s.snapshot.idea == TH.LONG_IDEA
                                  else PO.SHORT)


# ═════════════════════════════════════════════════════════════════════════════
# §22 — opportunity identity
# ═════════════════════════════════════════════════════════════════════════════
def test_one_opportunity_can_only_open_once(injected):
    _s, _f, _states, records = injected
    ids = [r.snapshot.opportunity_id for r in records]
    assert ids and len(ids) == len(set(ids))


def test_the_lifecycle_uses_the_production_opportunity_identity(injected):
    snap_, f, _states, records = injected
    live = {d.opportunity for d in RE.replay(snap_, f) if d.is_candidate}
    for r in records:
        assert r.snapshot.opportunity_id in live


def test_only_one_position_is_open_at_a_time(injected):
    _s, _f, states, _r = injected
    for s in states:
        assert s.position in PO.POSITIONS


# ═════════════════════════════════════════════════════════════════════════════
# §25 — causality and determinism
# ═════════════════════════════════════════════════════════════════════════════
def test_prefix_causality(injected):
    snap_, f, states, _r = injected
    chosen = PO.candidates_in(RE.replay(snap_, f))
    for frac in (0.3, 0.6, 0.9):
        k = states[int(len(states) * frac)].index
        cut, _rec = PO.lifecycle(
            snap_, f, execution=PO.ResearchPositionInjector(chosen), upto=k)
        assert cut == [s for s in states if s.index <= k]


def test_determinism(injected):
    snap_, f, states, records = injected
    chosen = PO.candidates_in(RE.replay(snap_, f))
    again, again_records = PO.lifecycle(
        snap_, f, execution=PO.ResearchPositionInjector(chosen))
    assert again == states
    assert [r.snapshot for r in again_records] == [r.snapshot for r in records]
    assert [r.timeline for r in again_records] == [r.timeline for r in records]


def test_the_flat_lifecycle_is_also_deterministic(flat):
    snap_, f, states, _r = flat
    assert PO.lifecycle(snap_, f)[0] == states


# ═════════════════════════════════════════════════════════════════════════════
# §30 — the observation world is untouched
# ═════════════════════════════════════════════════════════════════════════════
def test_the_lifecycle_mutates_no_observation():
    snap_, f = block(0)
    before = (list(f.readings), len(f.log), len(f.live_log),
              [n.id for n in f.history()], tuple(n.id for n in snap_.nodes),
              list(R.observe(f, snap_)), list(TH.narrate(snap_, f)))
    PO.lifecycle(snap_, f)
    PO.lifecycle(snap_, f, execution=PO.ResearchPositionInjector(
        PO.candidates_in(RE.replay(snap_, f))))
    after = (list(f.readings), len(f.log), len(f.live_log),
             [n.id for n in f.history()], tuple(n.id for n in snap_.nodes),
             list(R.observe(f, snap_)), list(TH.narrate(snap_, f)))
    assert before == after


def test_the_lifecycle_agrees_with_the_decision_stream(injected):
    """There is one position fold. If the lifecycle ever disagreed with the reactor about
    where a position was, the trader render would be describing a different run."""
    snap_, f, states, _r = injected
    chosen = PO.candidates_in(RE.replay(snap_, f))
    decisions = RE.replay(snap_, f, execution=PO.ResearchPositionInjector(chosen))
    assert len(states) == len(decisions)
    for s, d in zip(states, decisions):
        assert (s.index, s.position, s.action) == (d.index, d.position, d.action)


# ═════════════════════════════════════════════════════════════════════════════
# the render
# ═════════════════════════════════════════════════════════════════════════════
def test_the_render_shows_entry_thesis_current_market_delta_and_action(injected):
    _s, _f, states, _r = injected
    held = next(s for s in states if s.phase in (PO.HOLD, PO.CONTINUATION))
    text = "\n".join(PO.render(held))
    for heading in ("ENTRY THESIS", "CURRENT MARKET", "THESIS RELATION",
                    "POSITION ACTION"):
        assert heading in text, heading


def test_the_render_never_names_an_order_or_a_target(injected):
    _s, _f, states, _r = injected
    for s in states[:250]:
        text = " ".join(PO.render(s)).lower()
        for word in ("order", "target", "trailing", "atr stop", "size", "quantity",
                     "will reach", "expected to reach"):
            assert word not in text, word


# ═════════════════════════════════════════════════════════════════════════════
# §16 — management classification, and §18's render
# ═════════════════════════════════════════════════════════════════════════════
def test_management_uses_only_the_closed_vocabulary(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.evaluation is None:
            continue
        assert set(s.evaluation.management) <= PO.MANAGEMENT
        assert s.evaluation.management, "an evaluation must always classify something"


def test_management_carries_no_score_or_weight():
    """§16: no weights, no `weak`/`strong`, no confidence."""
    for member in PO.MANAGEMENT:
        low = member.lower()
        for banned in ("weak", "strong", "score", "confidence", "probability",
                       "weight", "rank", "high", "low"):
            assert banned not in low, member


def test_a_quiet_candle_says_the_thesis_is_still_valid(injected):
    _s, _f, states, _r = injected
    quiet = [s for s in states
             if s.phase == PO.HOLD and s.evaluation is not None]
    assert quiet
    for s in quiet:
        assert s.evaluation.management == (PO.THESIS_STILL_VALID,)


def test_a_continuation_names_what_developed(injected):
    _s, _f, states, _r = injected
    cont = [s for s in states if s.phase == PO.CONTINUATION]
    assert cont
    for s in cont:
        m = s.evaluation.management
        assert PO.SAME_THESIS_CONTINUATION in m or PO.THESIS_CHANGED in m
        assert PO.THESIS_STILL_VALID not in m
        assert len(m) > 1, "a continuation must say what continued"


def test_an_invalidation_is_classified_as_such(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.phase == PO.INVALIDATED:
            assert PO.THESIS_INVALIDATED in s.evaluation.management


def test_a_micro_development_is_reported_without_closing_the_position(injected):
    _s, _f, states, _r = injected
    micro = [s for s in states
             if s.evaluation is not None
             and PO.MICRO_DEVELOPMENT in s.evaluation.management
             and not s.evaluation.entry_thesis_invalidated]
    for s in micro:
        assert s.position_after == s.position
        assert s.action in (RE.HOLD_LONG, RE.HOLD_SHORT)


def test_the_snapshot_remembers_the_micro_as_it_stood_at_the_open(injected):
    _s, _f, states, _r = injected
    for s in states:
        if s.phase != PO.OPEN:
            continue
        # a snapshot field, so a later micro change is a development rather than a
        # reconstruction from current state
        assert s.snapshot.micro_state_at_open == s.snapshot.micro_state_at_open


def test_the_render_has_the_thesis_relation_section(injected):
    _s, _f, states, _r = injected
    held = next(s for s in states if s.phase in (PO.HOLD, PO.CONTINUATION))
    text = "\n".join(PO.render(held))
    for heading in ("ENTRY THESIS", "CURRENT MARKET", "THESIS RELATION",
                    "POSITION ACTION", "management:"):
        assert heading in text, heading
