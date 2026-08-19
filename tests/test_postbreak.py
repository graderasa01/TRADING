"""
The post-break eye — `src/livemap/postbreak.py`.

`ACCEPTED_ABOVE` used to be the end of the story. This layer keeps watching, as a chain of
episodes running from one accepted break to the next.

Four locks were attached to this layer's approval and each has tests named for it:

```
L1  trigger        only an accepted major break starts an episode
L2  new structure  a revisited historical structure is NOT a newly formed one
L3  live ends_at   the identity carries no fact from the future
L4  causal         observe(upto=k) is prefix-equal to a full run truncated at k
```

The fixtures are chosen so that between them every state fires: `walkthrough` builds a new
structure after its break, and `BREAK_THEN_BACK` extends, pauses, rotates, retests and
re-enters inside one episode.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.boxes.adaptive import MIN_TRAVERSES
from src.boxes.frontier import PROVISIONAL, HISTORICAL
from src.boxes.snapshot import EVENT_KINDS, LiveEvent
from src.boxes.structure import BREAK_CLOSES
from src.livemap import postbreak as P
from src.livemap.breaks import BREAK_KIND, from_logs, hidden
from src.livemap.interpreter import FORBIDDEN
from src.livemap.postbreak import (
    EPISODE_STATES, EXTENDING, FORMING_NEW_STRUCTURE, PAUSING, PRECEDENCE, REENTERING,
    RETESTING, ROTATING, BreakEpisode, EpisodeState, episodes, observe, spans)
from tests.test_breaks import ALL_HIDDEN, MIXED
from tests.test_frontier_evidence import SHAPES, SPLIT, frontier_for, ramp, sit
from tests.test_micro import WIDE_BROKE, WIDE_ENDED, WIDE_HELD

#: Extends, pauses, rotates, retests and re-enters inside a single episode — the shape the
#: `walkthrough` fixtures never produce because they only ever leave.
BREAK_THEN_BACK = (sit(22470, SPLIT + 30, 18) + ramp(22478, 22510, 6)
                   + ramp(22508, 22462, 10) + sit(22468, 25, 16))

ALL_SHAPES = dict(SHAPES, held=WIDE_HELD, broke=WIDE_BROKE, ended=WIDE_ENDED,
                  all_hidden=ALL_HIDDEN, mixed=MIXED, back=BREAK_THEN_BACK)

#: Shapes that actually break something. `one-way walk`, `held` and `broke` never do, and
#: a test that quietly iterates zero episodes is a test asserting nothing.
WITH_BREAKS = [n for n in ALL_SHAPES if n not in ("one-way walk", "held", "broke")]


def states_for(name):
    f = frontier_for(ALL_SHAPES[name])
    return f, observe(f)


@pytest.fixture
def back():
    return states_for("back")


@pytest.fixture
def walk():
    return states_for("walkthrough")


# ─────────────────────────────────────────────────────────────────────────────
# the vocabulary
# ─────────────────────────────────────────────────────────────────────────────
def test_the_vocabulary_is_closed():
    assert EPISODE_STATES == {EXTENDING, PAUSING, ROTATING, RETESTING, REENTERING,
                              FORMING_NEW_STRUCTURE}
    assert set(PRECEDENCE) == EPISODE_STATES
    assert PRECEDENCE == (REENTERING, RETESTING, FORMING_NEW_STRUCTURE, EXTENDING,
                          ROTATING, PAUSING)


def test_an_unknown_state_is_refused():
    with pytest.raises(ValueError):
        EpisodeState(index=0, at=None, price=Decimal(1), episode=None, state="BREAKOUT",
                     bars_since_break=0)


def test_nothing_in_this_layer_names_a_trade():
    for word in FORBIDDEN:
        assert not any(word in s for s in EPISODE_STATES)


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_no_rendered_line_names_a_trade(name):
    _, sts = states_for(name)
    for s in sts:
        text = " ".join(s.lines() + [P.compact(s)]).upper()
        for word in FORBIDDEN:
            assert word not in text.split(), f"c{s.index}: emitted {word!r}"


# ─────────────────────────────────────────────────────────────────────────────
# L1 — only an accepted major break starts an episode
# ─────────────────────────────────────────────────────────────────────────────
def test_l1_the_source_admits_one_event_kind_by_name():
    assert BREAK_KIND == "break"
    assert len(EVENT_KINDS) == 9, "the vocabulary grew — re-check the allow-list"


def test_l1_no_other_event_kind_produces_an_episode():
    """Eight of the nine permitted kinds, none of which is a break."""
    f = frontier_for(SHAPES["walkthrough"])
    at = f.candles[SPLIT].close_time
    others = [k for k in sorted(EVENT_KINDS) if k != BREAK_KIND]
    assert len(others) == 8
    fake = SimpleNamespace(
        log=[], live_log=[LiveEvent(k, "C01", SPLIT + i, at, "up", Decimal("22480"))
                          for i, k in enumerate(others)],
        readings=f.readings, snapshot=f.snapshot, candles=f.candles,
        history=lambda: ())
    assert from_logs(fake) == []


def test_l1_a_break_attempt_alone_starts_nothing():
    """`BREAK_ATTEMPT_*` is an interaction, never an event. Only the branch where
    `closes_beyond >= break_closes` writes a break."""
    f = frontier_for(ALL_SHAPES["back"])
    attempts = {r.index for r in f.readings
                if r.interaction.startswith("BREAK_ATTEMPT")}
    assert attempts, "the fixture never attempted a break"
    starts = {e.break_index for e in episodes(f)}
    assert not (attempts & starts)


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l1_a_micro_break_never_starts_an_episode(name):
    """Structural, not a rule: micro events never enter either log."""
    f = frontier_for(ALL_SHAPES[name])
    for e in list(f.log) + list(f.live_log):
        assert ".m" not in e.node_id
    for ep in episodes(f):
        assert ".m" not in ep.broken_id


def test_l1_a_fixture_whose_micro_breaks_gains_no_episode():
    f = frontier_for(WIDE_BROKE)
    broke = [r for r in f.readings if r.micro
             and {"MICRO_BREAK_UP", "MICRO_BREAK_DOWN"} & set(r.micro.events)]
    assert broke, "the fixture's micro never broke"
    assert episodes(f) == []


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l1_one_episode_per_accepted_break(name):
    f = frontier_for(ALL_SHAPES[name])
    records = from_logs(f)
    found = episodes(f)
    assert len(found) == len(records)
    assert [e.break_index for e in found] == [r.index for r in records]
    assert [e.broken_id for e in found] == [r.structure_id for r in records]


def test_the_interaction_is_never_the_source():
    """`all_hidden` is three breaks, not one of which the reading names."""
    f = frontier_for(ALL_HIDDEN)
    assert not any(r.interaction.startswith("ACCEPTED") for r in f.readings)
    found = episodes(f)
    assert len(found) == 3
    assert all(not e.named_by_interaction for e in found)


def test_every_hidden_break_reaches_an_episode():
    for name in ("all_hidden", "mixed"):
        f = frontier_for(ALL_SHAPES[name])
        records = from_logs(f)
        found = episodes(f)
        assert len(found) == len(records)
        assert (sum(1 for e in found if not e.named_by_interaction)
                == len(hidden(records)))


# ─────────────────────────────────────────────────────────────────────────────
# L2 — a revisited structure is not a new one
# ─────────────────────────────────────────────────────────────────────────────
def test_l2_a_revisited_historical_structure_is_not_a_new_structure():
    """`all_hidden` re-adopts `C01` — a snapshot structure — on the very candle it breaks.
    The loose rule (`node_id != broken_id`) would not fire here because it is the same id,
    so the sharper case is the status itself: every reading in this fixture is
    `HISTORICAL`, and no candle may read FORMING_NEW_STRUCTURE."""
    f = frontier_for(ALL_HIDDEN)
    inside = [r for r in f.readings if r.node_id]
    assert inside and all(r.node_status == HISTORICAL for r in inside)
    for s in observe(f):
        assert s.state != FORMING_NEW_STRUCTURE
        assert s.new_structure_id is None


def test_l2_a_minted_structure_is_a_new_structure(walk):
    f, sts = walk
    formed = [s for s in sts if s.state == FORMING_NEW_STRUCTURE]
    assert formed, "the fixture never built anything after its break"
    at = {r.index: r for r in f.readings}
    for s in formed:
        r = at[s.index]
        assert (r.state == "STRUCTURE_CANDIDATE"
                or (r.node_status == PROVISIONAL and r.node_id != s.episode.broken_id))


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l2_the_broken_structure_is_never_its_own_new_structure(name):
    _, sts = states_for(name)
    for s in sts:
        assert s.new_structure_id != s.episode.broken_id


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l2_a_historical_node_never_counts_as_newly_formed(name):
    f, sts = states_for(name)
    at = {r.index: r for r in f.readings}
    for s in sts:
        r = at[s.index]
        if r.node_status == HISTORICAL and r.state != "STRUCTURE_CANDIDATE":
            assert s.new_structure_id != r.node_id, f"c{s.index}: revisit read as new"


def test_l2_the_mint_is_witnessed_before_it_counts(walk):
    """The causal witness: an id counts only after its `NEW_*` interaction has been seen,
    inside this episode, on a candle already observed."""
    f, sts = walk
    at = {r.index: r for r in f.readings}
    born: dict[str, int] = {}
    for r in f.readings:
        if r.interaction.startswith("NEW_") and r.node_id:
            born.setdefault(r.node_id, r.index)
    for s in sts:
        nid = s.new_structure_id
        if nid and at[s.index].state != "STRUCTURE_CANDIDATE":
            assert nid in born and born[nid] <= s.index
            assert born[nid] >= s.episode.break_index


# ─────────────────────────────────────────────────────────────────────────────
# L3 — the identity carries no future
# ─────────────────────────────────────────────────────────────────────────────
def test_l3_the_episode_has_no_ends_at():
    names = {f.name for f in fields(BreakEpisode)}
    assert "ends_at" not in names
    assert not any("end" in n for n in names), sorted(names)


def test_l3_ends_at_lives_only_on_the_offline_span():
    assert "ends_at" in {f.name for f in fields(P.EpisodeSpan)}
    assert "ends_at" not in {f.name for f in fields(EpisodeState)}


def test_l3_the_episode_is_frozen(back):
    _, sts = back
    e = sts[0].episode
    with pytest.raises(FrozenInstanceError):
        e.broken_high = Decimal("1")


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l3_the_broken_geometry_never_changes(name):
    _, sts = states_for(name)
    first: dict[str, tuple] = {}
    for s in sts:
        e = s.episode
        band = (e.broken_id, e.broken_low, e.broken_high, e.broken_edge, e.direction,
                e.break_index)
        first.setdefault(e.id, band)
        assert band == first[e.id], f"c{s.index}: {e.id} moved"


# ─────────────────────────────────────────────────────────────────────────────
# L4 — causal
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", WITH_BREAKS)
def test_l4_observe_is_prefix_equal(name):
    f = frontier_for(ALL_SHAPES[name])
    full = observe(f)
    marks = sorted({e.break_index for e in episodes(f)}
                   | {r.index for r in f.readings[::5]})
    for k in marks:
        assert observe(f, upto=k) == [s for s in full if s.index <= k], f"upto={k}"


def test_l4_a_truncated_replay_sees_the_same_states(back):
    """The same frontier replayed to candle k, with the later breaks still in its logs,
    must produce exactly what a live run would have produced at k."""
    f, full = back
    for k in (s.index for s in full[::3]):
        assert observe(f, upto=k)[-1] == next(s for s in full if s.index == k)


def test_l4_the_observer_holds_no_future(back):
    """It is fed one candle at a time and keeps no record list."""
    obs = P.PostBreakObserver()
    assert not any("record" in s or "brk" in s or "next" in s
                   for s in P.PostBreakObserver.__slots__)
    f, full = back
    records = {r.index: r for r in from_logs(f)}
    out = []
    for r in f.readings:
        s = obs.on_candle(r, f.candles[r.index], f.candles, records.get(r.index))
        if s is not None:
            out.append(s)
    assert out == full


# ─────────────────────────────────────────────────────────────────────────────
# the states
# ─────────────────────────────────────────────────────────────────────────────
def test_every_state_fires_somewhere():
    seen = set()
    for name in WITH_BREAKS:
        seen |= {s.state for s in states_for(name)[1]}
    assert seen == EPISODE_STATES, f"never observed: {sorted(EPISODE_STATES - seen)}"


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_the_precedence_holds(name):
    """Each state implies the higher-precedence ones did not apply."""
    _, sts = states_for(name)
    for s in sts:
        reentered = s.closes_back >= BREAK_CLOSES
        assert (s.state == REENTERING) == reentered, f"c{s.index}"
        if s.state == FORMING_NEW_STRUCTURE:
            assert s.new_structure_id is not None
        if s.state == EXTENDING:
            assert s.new_extreme and s.new_structure_id is None
        if s.state == ROTATING:
            assert s.traverses >= MIN_TRAVERSES and not s.new_extreme
            assert s.new_structure_id is None
        if s.state == PAUSING:
            assert not s.new_extreme
            assert s.traverses < MIN_TRAVERSES
            assert s.new_structure_id is None


def test_a_pause_never_becomes_a_new_structure(back):
    _, sts = back
    assert any(s.state == PAUSING for s in sts)
    for s in sts:
        if s.state == PAUSING:
            assert s.new_structure_id is None


def test_extending_means_a_new_post_break_extreme(back):
    _, sts = back
    ext = [s for s in sts if s.state == EXTENDING]
    assert ext
    for s in ext:
        assert s.new_extreme
        assert s.max_excursion >= s.beyond


def test_retesting_is_contact_with_the_broken_edge(back):
    _, sts = back
    ret = [s for s in sts if s.state == RETESTING]
    assert ret
    for s in ret:
        assert s.contacted


def test_rotating_uses_the_episodes_own_territory(back):
    _, sts = back
    rot = [s for s in sts if s.state == ROTATING]
    assert rot
    for s in rot:
        assert s.span_low is not None and s.span_high > s.span_low
        assert s.traverses >= MIN_TRAVERSES


# ─────────────────────────────────────────────────────────────────────────────
# re-entry does not end the episode
# ─────────────────────────────────────────────────────────────────────────────
def test_reentry_does_not_end_the_episode(back):
    _, sts = back
    ids = [s.episode.id for s in sts]
    assert len(set(ids)) == 1, "the fixture broke twice; pick a single-episode one"
    assert REENTERING in {s.state for s in sts}


def test_break_extend_reenter_stays_one_episode():
    """`BREAK → EXTENDING → REENTERING` inside one id, which is what makes
    're-entered, then broke out again' representable at all."""
    f = frontier_for(ALL_SHAPES["back"])
    sts = observe(f)
    seq = [s.state for s in sts]
    assert EXTENDING in seq and REENTERING in seq
    assert seq.index(EXTENDING) < seq.index(REENTERING)
    assert len({s.episode.id for s in sts}) == 1


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_an_episode_runs_to_the_next_accepted_break(name):
    f = frontier_for(ALL_SHAPES[name])
    sp = spans(f)
    assert sp
    for a, b in zip(sp, sp[1:]):
        assert a.ends_at == b.episode.break_index
        assert a.ends_at > a.episode.break_index or a.length == 0
    assert sp[-1].ends_at is None, "exactly one episode is still open"
    assert sum(1 for s in sp if s.ends_at is None) == 1


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_episodes_do_not_overlap(name):
    f = frontier_for(ALL_SHAPES[name])
    sts = observe(f)
    order = []
    for s in sts:
        if not order or order[-1] != s.episode.id:
            order.append(s.episode.id)
    assert len(order) == len(set(order)), f"an episode resumed after another: {order}"


# ─────────────────────────────────────────────────────────────────────────────
# the micro stays subordinate
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", WITH_BREAKS)
def test_the_micro_is_carried_never_re_derived(name):
    f, sts = states_for(name)
    at = {r.index: r for r in f.readings}
    for s in sts:
        m = at[s.index].micro
        assert s.micro_id == (m.micro_id if m else None)
        assert s.micro_low == (m.micro_low if m else None)
        assert s.micro_high == (m.micro_high if m else None)
        assert s.micro_view == (m.view if m else None)
        assert s.micro_state == (m.micro_state if m else None)


def test_a_micro_inside_an_episode_is_rendered_under_it():
    f = frontier_for(WIDE_ENDED)
    sts = [s for s in observe(f) if s.micro_id]
    if not sts:
        pytest.skip("no micro survived into this fixture's episode")
    text = "\n".join(sts[0].lines())
    assert "MICRO" in text and sts[0].episode.id in text


# ─────────────────────────────────────────────────────────────────────────────
# isolation, and the failure cases
# ─────────────────────────────────────────────────────────────────────────────
def test_the_trading_path_cannot_see_an_episode():
    from pathlib import Path
    from src.livemap.interpreter import MapState
    from src.livemap.trader import TraderState
    for cls in (MapState, TraderState):
        assert not any("episode" in f.name for f in fields(cls))
    src = Path(__file__).resolve().parent.parent / "src" / "livemap"
    for name in ("trader.py", "interpreter.py", "route.py", "retest.py"):
        assert "postbreak" not in (src / name).read_text(encoding="utf-8")


def test_a_shape_that_never_breaks_has_no_episode():
    for name in ("one-way walk", "held", "broke"):
        f = frontier_for(ALL_SHAPES[name])
        assert episodes(f) == []
        assert observe(f) == []


def test_an_instant_acceptance_is_still_a_real_episode():
    """Two breaks a candle apart give a one-candle episode — a fact about the market, not
    something to merge away."""
    f = frontier_for(ALL_HIDDEN)
    sp = spans(f)
    short = [s for s in sp if s.length is not None and s.length <= 2]
    assert short
    for s in short:
        assert s.episode.broken_edge is not None
        assert s.episode.broken_low < s.episode.broken_high


def test_the_open_episode_has_no_end(back):
    f, _ = back
    sp = spans(f)
    assert sp[-1].ends_at is None and sp[-1].length is None


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_the_layer_is_deterministic(name):
    f = frontier_for(ALL_SHAPES[name])
    assert observe(f) == observe(f)
    assert episodes(f) == episodes(f)


@pytest.mark.parametrize("name", WITH_BREAKS)
def test_this_module_changes_nothing(name):
    f = frontier_for(ALL_SHAPES[name])
    before = (len(f.log), len(f.live_log), len(f.finalised), len(f.readings))
    observe(f)
    spans(f)
    assert (len(f.log), len(f.live_log), len(f.finalised), len(f.readings)) == before
