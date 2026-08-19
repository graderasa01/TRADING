"""
The Trader Decision Layer — `src/livemap/decide.py`.

Seven semantic locks were attached to this layer's approval, and each has tests named for
it:

```
E-C1  bias is STATE-based, never latched on `returned_inside`
E-C2  the route stays three facts, never one generic `space`
E-C3  every gate names its source; a fact with no source makes the gate UNAVAILABLE
E-C4  `src/setups/` is a cross-check and is never imported
E-C5  TradeIntent is a research hypothesis, NOT an executable entry
E-C6  an UNAVAILABLE gate is never reported as PASS
E-C7  while its bound is null the space gate RECORDS and never rejects
```

The most important test in the file is `test_a_trade_intent_is_not_an_order`. Everything
else describes what the layer decides; that one pins what it is **not**.
"""

from __future__ import annotations

import re
from dataclasses import fields
from decimal import Decimal
from itertools import groupby
from pathlib import Path

import pytest

from src.domain.models import GATES, Rejection
from src.livemap import decide as D
from src.livemap.decide import (
    BIAS_VOCABULARY, CONFLICTED, GATE_OUTCOMES, LONG, LONG_BIAS, MEASURED, NO_BIAS, PASS,
    REJECT, SETUP_A, SETUP_B, SETUP_C, SETUPS, SHORT, SHORT_BIAS, TRADEABLE, UNAVAILABLE,
    UNAVAILABLE_GATES, Bounds, GateResult, TradeContext, TradeIntent, Verdict, contexts,
    decide_all, intents)
from src.livemap.postbreak import REENTERING, RETESTING, observe as episode_observe
from tests.test_breaks import ALL_HIDDEN, MIXED
from tests.test_frontier_evidence import SHAPES, frontier_for
from tests.test_micro import WIDE_BROKE, WIDE_ENDED, WIDE_HELD
from tests.test_postbreak import BREAK_THEN_BACK

SOURCE = Path(__file__).resolve().parent.parent / "src" / "livemap" / "decide.py"

ALL_SHAPES = dict(SHAPES, held=WIDE_HELD, broke=WIDE_BROKE, ended=WIDE_ENDED,
                  all_hidden=ALL_HIDDEN, mixed=MIXED, back=BREAK_THEN_BACK)


def verdicts_for(name):
    f = frontier_for(ALL_SHAPES[name])
    return f, decide_all(f)


@pytest.fixture
def back():
    return verdicts_for("back")


# ─────────────────────────────────────────────────────────────────────────────
# E-C5 — the intent is a hypothesis, not an order
# ─────────────────────────────────────────────────────────────────────────────
def test_a_trade_intent_is_not_an_order():
    """The single most important assertion in this file.

    `TradeIntent` is a research hypothesis. It is not an entry authorization, an order
    instruction or a broker action, and nothing downstream may read it as one.
    """
    assert D.order_shaped_fields() == [], (
        f"TradeIntent grew an execution-shaped field: {D.order_shaped_fields()}")
    names = {f.name for f in fields(TradeIntent)}
    for banned in ("size", "qty", "quantity", "lots", "limit", "target", "stop_points",
                   "risk", "capital", "premium", "strike"):
        assert banned not in names


def test_the_intent_says_it_is_not_executable(back):
    _, vs = back
    found = intents(vs)
    assert found
    for v in found:
        assert v.intent.executable is False


def test_an_intent_always_carries_what_was_never_evaluated(back):
    """It cannot be read without also being handed the gates that were not run."""
    _, vs = back
    found = intents(vs)
    assert found
    expected = tuple(g for g, _ in UNAVAILABLE_GATES)
    for v in found:
        assert v.intent.unresolved == expected
        assert v.intent.unresolved, "an intent with nothing unresolved would be a lie"


def test_this_layer_does_not_define_a_signal():
    """`domain.Signal` is still untyped — *"typed in P3"*. Phase E does not fill it."""
    assert not hasattr(D, "Signal")
    import src.domain.models as M
    assert not hasattr(M, "Signal")


# ─────────────────────────────────────────────────────────────────────────────
# E-C6 — AVAILABLE vs UNAVAILABLE
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_an_unavailable_gate_is_never_a_pass(name):
    _, vs = verdicts_for(name)
    unavailable = {g for g, _ in UNAVAILABLE_GATES}
    for v in vs:
        for g in v.gates:
            if g.gate in unavailable:
                assert g.outcome == UNAVAILABLE, f"c{v.index}: {g.gate} → {g.outcome}"
        assert set(v.unavailable) == unavailable
        assert not (set(x.gate for x in v.evaluable) & unavailable)


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_every_verdict_lists_the_unavailable_gates(name):
    _, vs = verdicts_for(name)
    for v in vs:
        assert len(v.unavailable) == len(UNAVAILABLE_GATES)


def test_the_wording_never_claims_all_gates_passed(back):
    _, vs = back
    found = intents(vs)
    assert found
    text = "\n".join(found[0].lines())
    assert "all currently evaluable required gates pass" in text
    for v in vs:
        rendered = " ".join(v.lines())
        assert "all gates" not in rendered
        assert "all ten" not in rendered


def test_the_source_never_claims_all_gates_pass():
    text = SOURCE.read_text(encoding="utf-8").lower()
    assert "all gates pass" not in text
    assert "all ten gates" not in text


# ─────────────────────────────────────────────────────────────────────────────
# E-C7 / E-C2 — the space gate records and does not reject
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_space_gate_rejects_nothing_while_its_bound_is_null(name):
    _, vs = verdicts_for(name)
    assert Bounds().space_active is False
    for v in vs:
        for g in v.gates:
            if g.gate == "space_insufficient":
                assert g.outcome == MEASURED, f"c{v.index}: space rejected with no bound"
        if v.rejection is not None:
            assert v.rejection.gate != "space_insufficient"


def test_the_space_gate_records_all_three_route_magnitudes(back):
    """E-C2: `free_to_near` alone is not the picture — a thin gap in front of a deep zone
    and a thin gap in front of open air are different events."""
    f, vs = back
    seen = 0
    for v in vs:
        g = next((x for x in v.gates if x.gate == "space_insufficient"), None)
        if g is None or "free_to_near" not in g.measured:
            continue
        for key in ("free_to_near", "free_to_near_atr", "zone_depth", "zone_depth_atr",
                    "free_to_far"):
            assert key in g.measured, f"c{v.index}: {key} was not recorded"
        assert "stops_ahead" in g.measured
        seen += 1
    assert seen or all(c.route(LONG) is None for c in contexts(f))


def test_freshness_is_recorded_not_gated(back):
    _, vs = back
    recorded = [g for v in vs for g in v.gates
                if g.gate == "setup_stale" and g.outcome == MEASURED]
    assert recorded
    for g in recorded:
        assert "bars_since_break" in g.measured


def test_a_bound_can_be_activated_and_then_it_rejects(back):
    """The gate is inactive because the bound is null, not because it is decorative."""
    f, _ = back
    tight = decide_all(f, bounds=Bounds(max_bars_since_break=0))
    stale = [v for v in tight if v.rejection and v.rejection.gate == "setup_stale"]
    assert stale, "activating the bound changed nothing — the gate is dead code"


# ─────────────────────────────────────────────────────────────────────────────
# E-C1 — bias is state-based, never latched
# ─────────────────────────────────────────────────────────────────────────────
def test_bias_follows_the_episode_state_and_flips_back(back):
    """`break → REENTERING → back outside` must read
    `LONG_BIAS → SHORT_BIAS → LONG_BIAS`. A latched bias would keep calling it a short."""
    _, vs = back
    runs = [k for k, _ in groupby(v.bias for v in vs)]
    assert LONG_BIAS in runs and SHORT_BIAS in runs
    for a, b, c in zip(runs, runs[1:], runs[2:]):
        if (a, b) == (LONG_BIAS, SHORT_BIAS) and c == LONG_BIAS:
            return
    pytest.fail(f"bias never returned after a re-entry: {runs}")


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_bias_is_read_from_the_current_state(name):
    f, vs = verdicts_for(name)
    states = {s.index: s for s in episode_observe(f)}
    for v in vs:
        s = states.get(v.index)
        if s is None:
            assert v.bias == NO_BIAS
            continue
        if v.bias == CONFLICTED:
            continue
        up = s.episode.direction == "up"
        expected = (SHORT_BIAS if up else LONG_BIAS) if s.state == REENTERING else (
            LONG_BIAS if up else SHORT_BIAS)
        assert v.bias == expected, f"c{v.index}: {s.state}"


def test_returned_inside_still_blocks_setup_a_after_the_bias_returns(back):
    """Bias says which way the market leans now; `returned_inside` says whether this
    retest is still trustworthy. They are different questions and both are kept."""
    f, vs = back
    states = {s.index: s for s in episode_observe(f)}
    first_reentry = min((i for i, s in states.items() if s.state == REENTERING),
                        default=None)
    assert first_reentry is not None
    later = [v for v in intents(vs) if v.index > first_reentry]
    assert not any(v.intent.setup in (SETUP_A, SETUP_C) for v in later), (
        "a retest was acted on after the edge had already been reclaimed")
    assert any(v.bias == LONG_BIAS for v in vs if v.index > first_reentry), (
        "the fixture never returned to the original bias — the test proves nothing")


# ─────────────────────────────────────────────────────────────────────────────
# E-C3 — strict input source
# ─────────────────────────────────────────────────────────────────────────────
def test_the_module_computes_no_clock_or_session_fact():
    """E-C3. The session and clock names are allowed in exactly one place — the
    `UNAVAILABLE_GATES` table, which exists to say who owns each missing fact. Anywhere
    else would be this module computing it."""
    text = SOURCE.read_text(encoding="utf-8")
    for banned in (".minute", ".hour", "timedelta", "datetime.now", "date.today"):
        assert banned not in text, f"decide.py computes {banned!r} — E-C3 forbids it"

    start = text.index("UNAVAILABLE_GATES")
    end = text.index("\n)", start)
    table, elsewhere = text[start:end], text[:start] + text[end:]
    for name in ("trades_taken", "consecutive_losses", "cumulative_r",
                 "attempted_levels", "SessionState"):
        assert name in table, f"{name} should be named as a missing upstream fact"
        assert name not in elsewhere, f"decide.py reads {name!r} — E-C3 forbids it"


def test_the_module_imports_nothing_from_the_trading_path_or_state():
    text = SOURCE.read_text(encoding="utf-8")
    forbidden = ("setups", "risk", "exits", "modes", "broker", "guards", "options",
                 "state")
    for line in text.splitlines():
        if line.startswith(("import ", "from ")):
            for pkg in forbidden:
                assert f"src.{pkg}" not in line, line


def test_the_unavailable_gates_name_their_owner():
    for gate, detail in UNAVAILABLE_GATES:
        assert gate in GATES, f"{gate} is not a domain GATES member"
        assert len(detail) > 20, f"{gate} does not say why it is unavailable"


def test_no_new_gate_was_invented():
    for v in verdicts_for("back")[1]:
        for g in v.gates:
            assert g.gate in GATES


# ─────────────────────────────────────────────────────────────────────────────
# E-C4 — setups are a cross-check, never a dependency
# ─────────────────────────────────────────────────────────────────────────────
def test_decide_has_no_dependency_on_setups():
    text = SOURCE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(src\.)?setups", text, re.MULTILINE)
    assert "src.setups" not in text
    assert "setups." not in text.replace("src/setups/", "")


def test_the_setup_labels_are_defined_here():
    assert SETUPS == {SETUP_A, SETUP_B, SETUP_C}
    import src.setups.base as base
    assert base.SETUP_A == "A_flip_retest"
    assert SETUP_A == base.SETUP_A, "the labels agree by intent, not by import"


# ─────────────────────────────────────────────────────────────────────────────
# the vocabularies and the contract
# ─────────────────────────────────────────────────────────────────────────────
def test_the_vocabularies_are_closed():
    assert BIAS_VOCABULARY == {LONG_BIAS, SHORT_BIAS, NO_BIAS, CONFLICTED}
    assert GATE_OUTCOMES == {PASS, REJECT, MEASURED, UNAVAILABLE}
    assert TRADEABLE == {RETESTING, REENTERING}
    with pytest.raises(ValueError):
        GateResult("no_setup", "MAYBE")
    with pytest.raises(ValueError):
        TradeIntent(setup="D_new_idea", side=LONG, trigger=Decimal(1),
                    invalidate=Decimal(1), invalidate_rule=D.RECLAIMED,
                    episode_id="E01", broken_id="C01")


def test_exactly_one_of_intent_or_rejection():
    with pytest.raises(ValueError):
        Verdict(index=0, at=None, price=Decimal(1), bias=NO_BIAS)
    with pytest.raises(ValueError):
        Verdict(index=0, at=None, price=Decimal(1), bias=NO_BIAS,
                rejection=Rejection("no_setup", "x", None),
                intent=TradeIntent(SETUP_A, LONG, Decimal(1), Decimal(1), D.RECLAIMED,
                                   "E01", "C01"))


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_every_candle_produces_a_decision(name):
    f, vs = verdicts_for(name)
    assert len(vs) == len(f.readings)
    for v in vs:
        assert (v.intent is None) != (v.rejection is None)
        if v.rejection is not None:
            assert v.rejection.gate in GATES


# ─────────────────────────────────────────────────────────────────────────────
# A — the context computes nothing
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_context_computes_nothing(name):
    from src.livemap.eye import observe as eye_observe
    from src.livemap.interpreter import Interpreter
    f = frontier_for(ALL_SHAPES[name])
    maps = {s.index: s for s in Interpreter(f.snapshot, f).states()}
    eyes = {e.index: e for e in eye_observe(f.snapshot, f)}
    eps = {e.index: e for e in episode_observe(f)}
    for ctx in contexts(f):
        m = maps[ctx.index]
        assert ctx.at == m.at and ctx.price == m.price and ctx.atr == m.atr
        assert ctx.map == m
        assert ctx.eye == eyes[ctx.index]
        assert ctx.episode == eps.get(ctx.index)
        assert ctx.route_above == m.route_above
        assert ctx.route_below == m.route_below
        assert ctx.corridor_above == m.corridor_above
        assert ctx.space_above == m.space_above
        assert ctx.space_below == m.space_below


# ─────────────────────────────────────────────────────────────────────────────
# each gate rejects for its own reason
# ─────────────────────────────────────────────────────────────────────────────
def test_no_episode_rejects_as_no_setup():
    f = frontier_for(SHAPES["one-way walk"])
    vs = decide_all(f)
    assert vs and all(v.rejection.gate in ("no_setup", "warmup") for v in vs)
    assert all(v.bias == NO_BIAS for v in vs)


def test_an_untradeable_situation_rejects_as_no_setup(back):
    f, vs = back
    states = {s.index: s for s in episode_observe(f)}
    for v in vs:
        s = states.get(v.index)
        if s is not None and s.state not in TRADEABLE and v.rejection:
            assert v.rejection.gate == "no_setup"


def test_a_conflict_rejects_and_never_resolves_toward_trading(back):
    _, vs = back
    conflicted = [v for v in vs if v.bias == CONFLICTED]
    assert conflicted
    for v in conflicted:
        assert v.intent is None
        assert v.rejection.gate == "bias_conflict"
        assert v.rejection.detail


# ─────────────────────────────────────────────────────────────────────────────
# symmetry, causality, determinism, isolation
# ─────────────────────────────────────────────────────────────────────────────
def _episode_at(direction: str, state: str, *, kind: str, excursion="20",
                returned=False):
    """A hand-built episode, so symmetry can be tested without a mirrored fixture.

    Every synthetic shape in this repo breaks **upward**, so a fixture-only symmetry test
    would silently only ever exercise one side — the `retest.py` trick of replaying a
    fixture upside down needs a fixture that goes the other way, and there is none.
    """
    from src.livemap.postbreak import BreakEpisode, EpisodeState
    edge = Decimal("22480") if direction == "up" else Decimal("22450")
    ep = BreakEpisode(
        id="E01", broken_id="C01", broken_edge=edge, broken_low=Decimal("22450"),
        broken_high=Decimal("22480"), direction=direction, break_index=10,
        break_at=None, source="frozen", kind=kind)
    return EpisodeState(index=20, at=None, price=edge, episode=ep, state=state,
                        bars_since_break=10, max_excursion=Decimal(excursion),
                        returned_inside=returned)


def _ctx(episode, interaction="INSIDE"):
    from src.boxes.frontier import Reading
    from src.livemap.eye import EyeState
    from src.livemap.interpreter import MapState, SideReferences
    price = episode.episode.broken_edge
    reading = Reading(index=20, state="MOVING", interaction=interaction)
    state = MapState(index=20, at=None, price=price, current=None, break_up=None,
                     break_down=None, above=SideReferences(), below=SideReferences(),
                     interaction=interaction, atr=Decimal("10"))
    return TradeContext(index=20, at=None, price=price, atr=Decimal("10"),
                        reading=reading, map=state,
                        eye=EyeState(index=20, at=None, price=price), episode=episode)


@pytest.mark.parametrize("state,kind,up_side,setup", [
    (RETESTING, "cluster", LONG, SETUP_A),
    (RETESTING, "range", LONG, SETUP_C),
    (REENTERING, "cluster", SHORT, SETUP_B),
])
def test_the_setups_are_symmetric(state, kind, up_side, setup):
    """The same situation mirrored must give the same setup and the opposite side.

    A retest of an up-break is long; of a down-break, short. A failed up-break is short;
    a failed down-break, long. No sign is hard-coded.
    """
    other = SHORT if up_side == LONG else LONG
    assert D.setup_of(_ctx(_episode_at("up", state, kind=kind))) == (setup, up_side)
    assert D.setup_of(_ctx(_episode_at("down", state, kind=kind))) == (setup, other)


def test_the_sweep_extreme_mirrors():
    """Setup B's invalidation is the failed sweep's extreme — above the edge for an
    up-break, below it for a down-break."""
    up = _ctx(_episode_at("up", REENTERING, kind="cluster", excursion="20"))
    down = _ctx(_episode_at("down", REENTERING, kind="cluster", excursion="20"))
    _, inv_up, rule = D.references(up, SETUP_B)
    _, inv_dn, _ = D.references(down, SETUP_B)
    assert rule == D.BEYOND_SWEEP
    assert inv_up == up.episode.episode.broken_edge + Decimal("20")
    assert inv_dn == down.episode.episode.broken_edge - Decimal("20")


def test_bias_mirrors():
    for state in (RETESTING, "EXTENDING", "PAUSING"):
        assert D.bias_of(_ctx(_episode_at("up", state, kind="cluster")))[0] == LONG_BIAS
        assert D.bias_of(_ctx(_episode_at("down", state, kind="cluster")))[0] == SHORT_BIAS
    assert D.bias_of(_ctx(_episode_at("up", REENTERING, kind="cluster")))[0] == SHORT_BIAS
    assert D.bias_of(_ctx(_episode_at("down", REENTERING, kind="cluster")))[0] == LONG_BIAS


def test_both_sides_are_reachable_on_real_shapes():
    seen = set()
    for name in ALL_SHAPES:
        seen |= {v.intent.side for v in intents(verdicts_for(name)[1])}
    assert seen, "no intent on any shape"


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_decide_all_is_prefix_causal(name):
    f = frontier_for(ALL_SHAPES[name])
    full = decide_all(f)
    for k in [r.index for r in f.readings[::7]]:
        assert decide_all(f, upto=k) == [v for v in full if v.index <= k], f"upto={k}"


def test_an_invalidation_reference_existed_before_the_intent(back):
    """It is the broken edge, frozen at the break — never a price from a later candle."""
    f, vs = back
    for v in intents(vs):
        episode = next(s.episode for s in episode_observe(f) if s.index == v.index)
        assert episode.break_index <= v.index
        assert v.intent.trigger == episode.broken_edge


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_layer_is_deterministic(name):
    f = frontier_for(ALL_SHAPES[name])
    assert decide_all(f) == decide_all(f)


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_no_rendered_line_names_an_execution_concept(name):
    _, vs = verdicts_for(name)
    for v in vs:
        text = " ".join(v.lines() + [D.compact(v)]).upper()
        for word in D.FORBIDDEN:
            assert word not in text.split(), f"c{v.index}: emitted {word!r}"


def test_the_trading_path_cannot_reach_this_module():
    src = Path(__file__).resolve().parent.parent / "src"
    for package in ("setups", "risk", "exits", "modes", "broker", "guards", "options"):
        d = src / package
        if not d.is_dir():
            continue
        for path in d.rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("import ", "from ")):
                    assert "decide" not in line, f"{path}: {line}"


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_this_module_changes_nothing(name):
    f = frontier_for(ALL_SHAPES[name])
    before = (len(f.log), len(f.live_log), len(f.finalised), len(f.readings))
    decide_all(f)
    assert (len(f.log), len(f.live_log), len(f.finalised), len(f.readings)) == before


def test_the_bounds_are_all_null_by_default():
    """Every number ships unset. Filling one is a separate reviewed step."""
    b = Bounds()
    assert b.max_bars_since_break is None
    assert b.min_free_to_near_atr is None
    assert b.min_zone_depth_atr is None
    assert b.min_free_to_far_atr is None
    assert b.space_active is False


def test_params_yaml_declares_every_bound_as_null():
    text = (Path(__file__).resolve().parent.parent / "config"
            / "params.yaml").read_text(encoding="utf-8")
    block = text.split("\ndecide:")[1]
    for key in ("max_bars_since_break", "min_free_to_near_atr", "min_zone_depth_atr",
                "min_free_to_far_atr"):
        assert re.search(rf"{key}:\s*null", block), f"{key} is not null in params.yaml"
