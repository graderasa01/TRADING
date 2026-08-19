"""The OBSERVATORY — `src/livemap/observatory.py`.

A visual layer is the easiest place in the system to leak the future, and it leaks somewhere
no decision test looks: the *geometry*. A box finalised at candle 60, drawn on candle 40,
makes the picture better than the system is, and nothing in the decision suite would notice.

```
no-lookahead    frame k's geometry == a fresh frontier fed only k candles
one engine      LiveSession (candle at a time) == frames() (batch), frame for frame
causality       frames(upto k) is prefix-equal to a full run
determinism     two runs, identical
composition     the frame invents no fact and no reason
safety          no order, no broker, no size; paper positions are explicit
```
"""
from __future__ import annotations

import ast
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from src.boxes.frontier import Frontier, run
from src.livemap import boundary as BD
from src.livemap import observatory as OB
from src.livemap import participation as PE
from src.livemap import position as POS
from src.livemap import reactor as RE
from tests.test_participation import BARS, HIST, block, streams
from src.learning.split import load_split
from src.feed.replay_feed import ReplayFeed

SRC = Path(__file__).resolve().parent.parent / "src"
SYMBOL = "NIFTY BANK"


def deep(o):
    if is_dataclass(o) and not isinstance(o, type):
        return (type(o).__name__,) + tuple(deep(getattr(o, f.name)) for f in fields(o))
    if isinstance(o, (list, tuple)):
        return tuple(deep(x) for x in o)
    return o


@pytest.fixture(scope="module")
def candles():
    """The same teach block `block(0)` is built from, but as raw candles, because the
    observatory drives the frontier itself rather than receiving a finished one."""
    sp = load_split()
    days = ReplayFeed(SYMBOL, on_gap="skip").available_days()
    _m1, m5 = streams(sp.teach(days)[:40])
    blk = m5[:BARS]
    return blk[:HIST], blk[HIST:]


@pytest.fixture(scope="module")
def world():
    return block(0)


@pytest.fixture(scope="module")
def built(candles):
    hist, live = candles
    from src.boxes.snapshot import build_snapshot
    snap = build_snapshot(hist, SYMBOL)
    return snap, hist, live


@pytest.fixture(scope="module")
def fr(built):
    snap, hist, live = built
    return OB.frames(snap, hist, live)


@pytest.fixture(scope="module")
def research(built):
    """A named research contract, so the position lifecycle has something to render."""
    snap, hist, live = built
    f = run(snap, hist, live)
    ids = POS.candidates_in(RE.replay(snap, f, execution=RE.ImmediateExecution()))
    return POS.ResearchPositionInjector(ids)


# ═════════════════════════════════════════════════════════════════════════════
# THE ONE THAT MATTERS — no future geometry
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("k", [10, 40, 100, 200])
def test_the_geometry_of_frame_k_is_what_a_fresh_run_to_k_produces(built, fr, k):
    """A box drawn on candle k must be a box that existed at candle k.

    Rebuilt from scratch: a new `Frontier` fed only the first k live candles, and its node
    set compared with the frame's. If the observatory read `history()` back at the end of
    the run, this fails — which is the whole reason it does not.
    """
    snap, hist, live = built
    fresh = Frontier(snap, hist)
    for c in live[:k]:
        fresh.on_candle(c)
    reading = fresh.readings[-1]
    want = OB._geometry(fresh, snap, reading.index, reading)
    got = next(x.geometry for x in fr if x.index == reading.index)
    assert deep(got) == deep(want)


def test_no_frame_ever_shows_a_box_finalised_after_its_own_candle(fr):
    """The property the parametrised test proves at four points, asserted everywhere."""
    offenders = []
    for frame in fr:
        for box in frame.geometry.boxes:
            if box.status == "FINALISED" and box.end is not None \
                    and box.end > frame.index:
                offenders.append((frame.index, box.id, box.end))
    assert not offenders, f"future boxes drawn: {offenders[:5]}"


def test_no_frame_shows_a_box_that_starts_after_its_own_candle(fr):
    offenders = [(f.index, b.id, b.start) for f in fr for b in f.geometry.boxes
                 if b.status != "HISTORICAL" and b.start > f.index]
    assert not offenders, f"boxes from the future drawn: {offenders[:5]}"


def test_the_box_count_never_shrinks_as_the_replay_advances(fr):
    """Geometry accumulates. A box vanishing would mean the track was rebuilt from a
    later state rather than frozen at the candle."""
    counts = [len([b for b in f.geometry.boxes if b.status == "FINALISED"]) for f in fr]
    assert counts == sorted(counts)


# ═════════════════════════════════════════════════════════════════════════════
# ONE ENGINE — historical and live
# ═════════════════════════════════════════════════════════════════════════════
def test_the_live_session_and_the_batch_replay_agree_candle_for_candle(built, fr):
    """§11 of the brief: historical replay and the live feed must be the same engine.

    Fed one candle at a time, exactly as a broker feed would, the session must produce the
    identical frame sequence — geometry, context, decision, position, boundary and reason.
    """
    snap, hist, live = built
    session = OB.LiveSession(snap, hist)
    for c in live:
        session.on_candle(c)
    assert len(session.frames) == len(fr)
    for a, b in zip(session.frames, fr):
        assert deep(a) == deep(b), f"live and batch disagree at c{a.index}"


def test_the_live_session_frame_is_final_the_moment_it_is_produced(built):
    """A frame handed to the screen must never be rewritten by a later candle — that is
    what makes what a trader saw at 13:45 the truth about 13:45."""
    snap, hist, live = built
    session = OB.LiveSession(snap, hist)
    seen = {}
    for c in live[:120]:
        frame = session.on_candle(c)
        if frame is None:
            continue
        seen[frame.index] = deep(frame)
    for frame in session.frames:
        if frame.index in seen:
            assert deep(frame) == seen[frame.index], f"c{frame.index} was rewritten"


def test_the_live_session_keeps_no_position_fold_of_its_own():
    """The previous stage established there is exactly one fold. A private incremental
    copy inside the live path would be a second one."""
    src = (SRC / "livemap" / "observatory.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "LiveSession")
    body = ast.unparse(cls)
    for banned in ("book.position", "self.position =", "Book()"):
        assert banned not in body, f"LiveSession runs its own fold: {banned}"


# ═════════════════════════════════════════════════════════════════════════════
# CAUSALITY and DETERMINISM
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("k", [25, 50, 100, 200])
def test_frames_are_prefix_causal(built, fr, k):
    snap, hist, live = built
    cut = OB.frames(snap, hist, live[:k])
    assert len(cut) == k
    for a, b in zip(cut, fr[:k]):
        assert deep(a) == deep(b)


def test_frames_are_deterministic(built):
    snap, hist, live = built
    a = OB.frames(snap, hist, live[:150])
    b = OB.frames(snap, hist, live[:150])
    assert [deep(x) for x in a] == [deep(x) for x in b]


def test_the_geometry_track_produces_the_same_frontier_as_run(built):
    """`geometry_track` must not be a second observation path — it is `run()` with the
    per-candle state kept."""
    snap, hist, live = built
    mine, _track = OB.geometry_track(snap, hist, live)
    theirs = run(snap, hist, live)
    assert [deep(r) for r in mine.readings] == [deep(r) for r in theirs.readings]
    assert [deep(n) for n in mine.history()] == [deep(n) for n in theirs.history()]


# ═════════════════════════════════════════════════════════════════════════════
# COMPOSITION — the frame invents nothing
# ═════════════════════════════════════════════════════════════════════════════
def test_every_why_code_is_an_existing_vocabulary_member(fr, built, research):
    snap, hist, live = built
    known = (set(OB._REASON_ENGLISH) | set(OB._MANAGEMENT_ENGLISH) | POS.MANAGEMENT
             | POS.EXIT_REASONS | PE.OPPORTUNITIES)
    for frames_ in (fr, OB.frames(snap, hist, live, execution=research)):
        for frame in frames_:
            unknown = [c for c in frame.why.codes if c not in known]
            assert not unknown, f"c{frame.index} invented a reason: {unknown}"


def test_the_frame_never_disagrees_with_the_production_decision(built, world, research):
    """Every frame field that also exists upstream must be the upstream value."""
    snap, hist, live = built
    for ex in (RE.NoExecution(), research):
        frames_ = OB.frames(snap, hist, live, execution=ex)
        f = run(snap, hist, live)
        decisions = RE.replay(snap, f, execution=ex)
        states, _ = POS.lifecycle(snap, f, execution=ex)
        assert len(frames_) == len(decisions)
        for frame, d, st in zip(frames_, decisions, states):
            assert frame.index == d.index
            assert frame.action == d.action
            assert frame.phase == st.phase
            assert frame.position == st.position_after
            assert deep(frame.context) == deep(d.context)
            assert deep(frame.state) == deep(st)


def test_the_frame_candle_is_the_feeds_candle(built, fr):
    snap, hist, live = built
    by_time = {c.close_time: c for c in live}
    for frame in fr:
        candle = by_time.get(frame.at)
        if candle is None:
            continue
        assert (frame.o, frame.h, frame.l, frame.c) == (candle.o, candle.h,
                                                        candle.l, candle.c)


def test_the_trader_eye_answers_every_question_from_the_frame(fr):
    for frame in fr[:80]:
        answers = OB.trader_eye(frame)
        assert [q for q, _ in answers] == list(OB.EYE_QUESTIONS)
        assert all(a for _, a in answers), f"c{frame.index} left a question blank"


# ═════════════════════════════════════════════════════════════════════════════
# SAFETY — the observatory cannot execute
# ═════════════════════════════════════════════════════════════════════════════
def test_the_observatory_imports_nothing_that_can_trade():
    forbidden = ("broker", "orders", "risk", "sizing", "options", "setups", "exits",
                 "modes", "guards", "journal", "split", "learning")
    mods = set()
    for node in ast.walk(ast.parse((SRC / "livemap" / "observatory.py")
                                   .read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    offenders = [m for m in mods for f in forbidden
                 if m == f or m.startswith(f"src.{f}") or m.startswith(f"{f}.")]
    assert not offenders, offenders


def test_the_observatory_carries_no_order_vocabulary():
    text = (SRC / "livemap" / "observatory.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    code = text
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                code = code.replace(doc, "")
    code = re.sub(r"#.*", "", code)
    for word in ("ENTER_LONG", "ENTER_SHORT", "place_order", "quantity", "lot_size"):
        assert word not in code, f"observatory.py contains {word!r} outside its prose"


def test_under_the_default_contract_no_frame_shows_a_position(fr):
    assert {f.phase for f in fr} == {POS.FLAT_PHASE}
    assert {f.position for f in fr} == {PE.FLAT}
    assert not [f for f in fr if f.is_paper]
    assert {f.contract for f in fr} == {"NoExecution"}
    assert not any(f.contract_validated for f in fr)


def test_every_boundary_on_screen_is_unavailable_by_default(fr):
    reqs = [f.request for f in fr if f.request is not None]
    assert reqs, "no candidate in this block — the assertion would be vacuous"
    assert {r.execution_status for r in reqs} == {RE.EXEC_UNAVAILABLE}
    assert {r.disposition for r in reqs} == {BD.NO_CONTRACT}
    assert not any(r.creates_an_order for r in reqs)


def test_a_paper_position_is_always_labelled_as_research(built, research):
    snap, hist, live = built
    frames_ = OB.frames(snap, hist, live, execution=research)
    positioned = [f for f in frames_ if f.is_paper]
    assert positioned, "the research contract opened nothing — assertion vacuous"
    for frame in positioned:
        assert frame.contract == "ResearchPositionInjector"
        assert frame.contract_validated is False
        if frame.request is not None:
            assert frame.request.is_research is True
            assert frame.request.creates_an_order is False


# ═════════════════════════════════════════════════════════════════════════════
# §12 — the scenarios must be findable on real candles
# ═════════════════════════════════════════════════════════════════════════════
def test_the_scenario_index_is_built_from_real_candles(built, research):
    snap, hist, live = built
    hits = OB.scenarios(OB.frames(snap, hist, live, execution=research))
    assert set(hits) == set(OB.SCENARIOS)
    for key, idx in hits.items():
        assert all(isinstance(i, int) for i in idx), key


def test_the_events_timeline_never_reports_an_absent_fact(fr):
    for frame in fr:
        if not frame.context.all_releases:
            assert not [e for e in frame.events if "RELEASE" in e]
        if frame.phase != POS.INVALIDATED:
            assert not [e for e in frame.events if e.startswith("EXIT")]
