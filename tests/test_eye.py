"""
The per-candle live eye — `src/livemap/eye.py`.

Phase C's whole claim is that it **reads**: every value is copied from a `Reading` or a
`MapState`, or is the difference between two such copies. So the first and most important
test here is not about deltas at all — it is `test_the_eye_computes_nothing`, which walks
every carried field and asserts it is identical to its source. That is what makes *"Phase
C does not compute"* mechanical rather than aspirational.

The rest are the three ways a delta lies:

```
None is not zero     246 -> None is not -246; it is not a number at all
first is not flat    the first candle has no previous
the subject moved    position in C21 minus position in R01 is not a movement
```
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.models import ZERO
from src.livemap import eye as E
from src.livemap.eye import (
    DELTA_FIELDS, DIRECTIONS, TRACKED, Delta, EdgePressure, EyeState, Transition,
    compact, observe, read_all)
from src.livemap.interpreter import FORBIDDEN, Interpreter
from tests.test_frontier_evidence import SHAPES, frontier_for
from tests.test_micro import WIDE_BROKE, WIDE_ENDED, WIDE_HELD

ALL_SHAPES = dict(SHAPES, held=WIDE_HELD, broke=WIDE_BROKE, ended=WIDE_ENDED)


def eyes_for(closes):
    f = frontier_for(closes)
    return f, observe(f.snapshot, f)


@pytest.fixture
def wide():
    return eyes_for(WIDE_BROKE)


@pytest.fixture
def ended():
    return eyes_for(WIDE_ENDED)


# ─────────────────────────────────────────────────────────────────────────────
# the vocabularies
# ─────────────────────────────────────────────────────────────────────────────
def test_the_vocabularies_are_closed():
    with pytest.raises(ValueError):
        Delta("momentum")
    with pytest.raises(ValueError):
        Transition("mood", "a", "b")
    with pytest.raises(ValueError):
        EdgePressure(side="sideways", edge=Decimal(1), distance=ZERO, distance_atr=0.0)
    assert DIRECTIONS == {"up", "down", "flat", ""}


def test_every_delta_field_names_its_subject():
    """The comparability table is what makes the subject rule mechanical. A field missing
    from it would silently compare across a change of structure."""
    assert set(E._SUBJECT) == set(DELTA_FIELDS)
    assert set(E._SUBJECT.values()) == {None, "node", "micro"}


def test_the_locked_delta_shape_kept_its_order():
    """`price, micro_high, micro_low, position, above_space, micro_state` was fixed before
    Phase B was built, so Phase B's fields could be chosen to feed it. The two one-sided
    names were completed; the locked six keep their relative order."""
    locked = ("price", "micro_high", "micro_low", "position_in_current",
              "space_above", "micro_state")
    assert [f for f in DELTA_FIELDS if f in locked] == list(locked)
    assert set(DELTA_FIELDS) - set(locked) == {"space_below", "position_in_micro"}


def test_nothing_in_this_layer_names_a_trade():
    for word in FORBIDDEN:
        assert not any(word in f.upper() for f in DELTA_FIELDS + TRACKED)


def test_a_measured_change_must_say_which_way_it_went():
    with pytest.raises(ValueError):
        Delta("price", Decimal(1), Decimal(2), Decimal(1), "")


# ─────────────────────────────────────────────────────────────────────────────
# the governing invariant — Phase C reads
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_eye_computes_nothing(name):
    """Every carried field, against its source, on every candle of every shape.

    `position_in_micro` is the single exception and is checked separately: it is the same
    arithmetic `Interpreter` uses for `Current.position`, pointed at the micro's band.
    """
    f = frontier_for(ALL_SHAPES[name])
    states = Interpreter(f.snapshot, f).states()
    eyes = read_all(f.readings, states, f.candles)
    assert len(eyes) == len(f.readings)

    for eye, reading, state in zip(eyes, f.readings, states):
        m = reading.micro
        assert eye.index == reading.index
        assert eye.at == state.at
        assert eye.price == state.price
        assert eye.node_id == reading.node_id
        assert eye.interaction == reading.interaction
        assert eye.state == reading.state
        assert eye.market_state == state.market_state
        assert eye.status == state.status
        assert eye.space_above == state.space_above
        assert eye.space_below == state.space_below
        assert eye.space_above_atr == state.space_above_atr
        assert eye.space_below_atr == state.space_below_atr
        assert eye.watch_above == (state.route_above.watch if state.route_above else None)
        assert eye.watch_below == (state.route_below.watch if state.route_below else None)
        assert eye.micro_id == (m.micro_id if m else None)
        assert eye.micro_view == (m.view if m else None)
        assert eye.micro_state == (m.micro_state if m else None)
        assert eye.micro_low == (m.micro_low if m else None)
        assert eye.micro_high == (m.micro_high if m else None)
        assert eye.position_in_current == (m.position_in_current if m else None)
        if eye.upper is not None:
            assert eye.upper.edge == state.break_up
            assert eye.upper.touches == int(reading.evidence.get("upper_touches", 0))
        if eye.lower is not None:
            assert eye.lower.edge == state.break_down
            assert eye.lower.touches == int(reading.evidence.get("lower_touches", 0))


def test_the_eye_never_reaches_back_into_the_frontier(wide):
    """A state that can reach back describes every candle using the last candle's world —
    the bug every layer here snapshots its fields to avoid.

    Checked by type rather than by name: `EyeState.state` is a legitimate field holding
    the frontier's state **word**, and a name-based check would flag it.
    """
    from src.boxes.frontier import Frontier, Reading
    from src.livemap.interpreter import Interpreter as I, MapState
    _, eyes = wide
    for eye in eyes:
        for name in EyeState.__slots__:
            assert not isinstance(getattr(eye, name),
                                  (Reading, MapState, Frontier, I)), name


# ─────────────────────────────────────────────────────────────────────────────
# the three refusals
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_first_candle_is_not_flat(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    first = eyes[0]
    assert first.first is True
    assert not first.subject_changed
    assert first.transitions == ()
    assert all(d.change is None and d.direction == "" for d in first.deltas)
    assert all(not d.moved for d in first.deltas)
    assert all(not e.first for e in eyes[1:])


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_none_is_never_treated_as_zero(name):
    """`space_above` is `None` when there is nothing above — *khuli jagah*. A micro's band
    is `None` before one exists. Neither may become a signed number."""
    _, eyes = eyes_for(ALL_SHAPES[name])
    checked = 0
    for eye in eyes:
        for d in eye.deltas:
            if d.before is None or d.after is None:
                assert d.change is None, f"c{eye.index}: {d.name} {d.before}->{d.after}"
                assert d.direction == ""
                checked += 1
    assert checked > 0, "no missing value was ever crossed — the assertion did not run"


def test_a_value_appearing_and_disappearing_is_not_a_movement(wide):
    """Specifically the micro band, which arrives and leaves repeatedly."""
    _, eyes = wide
    appeared = [e for e in eyes
                if (d := e.delta("micro_high")) and d.before is None
                and d.after is not None]
    vanished = [e for e in eyes
                if (d := e.delta("micro_high")) and d.before is not None
                and d.after is None]
    assert appeared and vanished
    for e in appeared + vanished:
        assert e.delta("micro_high").change is None
        assert e.delta("micro_low").change is None


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_a_delta_across_a_change_of_subject_is_refused(name):
    """Position in `C21` minus position in `R01` is not a movement. The values are still
    reported; only the subtraction is refused."""
    _, eyes = eyes_for(ALL_SHAPES[name])
    previous = None
    changes = 0
    for eye in eyes:
        if previous is None:
            previous = eye
            continue
        node_moved = eye.node_id != previous.node_id
        micro_moved = eye.micro_id != previous.micro_id
        assert eye.subject_changed == (node_moved or micro_moved), f"c{eye.index}"
        for d in eye.deltas:
            subject = E._SUBJECT[d.name]
            expect = not (subject == "node" and node_moved
                          or subject == "micro" and micro_moved)
            assert d.comparable is expect, f"c{eye.index}: {d.name}"
            if not expect:
                assert d.change is None
        changes += eye.subject_changed
        previous = eye


def test_price_is_comparable_across_a_change_of_subject(wide):
    """Price belongs to no structure. It keeps its delta when everything else loses one."""
    _, eyes = wide
    moved = [e for e in eyes if e.subject_changed and not e.first]
    assert moved
    for e in moved:
        assert e.delta("price").comparable is True
        assert e.delta("price").change is not None


# ─────────────────────────────────────────────────────────────────────────────
# the delta set
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_full_delta_set_is_always_present_and_in_order(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    for eye in eyes:
        assert tuple(d.name for d in eye.deltas) == DELTA_FIELDS
        assert eye.delta("price") is not None
        assert eye.delta("nothing") is None


def test_a_partial_delta_set_is_refused():
    """A consumer reading `deltas[4]` must always get the same field."""
    with pytest.raises(ValueError):
        EyeState(index=0, at=None, price=ZERO, deltas=(Delta("price"),))
    with pytest.raises(ValueError):
        EyeState(index=0, at=None, price=ZERO,
                 deltas=tuple(Delta(n) for n in reversed(DELTA_FIELDS)))


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_a_measured_delta_is_the_arithmetic_difference(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    previous = None
    for eye in eyes:
        for d in eye.deltas:
            if d.change is None:
                continue
            assert d.change == d.after - d.before
            assert d.direction == ("flat" if d.change == 0
                                   else "up" if d.change > 0 else "down")
        if previous is not None and eye.delta("price").change is not None:
            assert eye.delta("price").change == eye.price - previous.price
        previous = eye


# ─────────────────────────────────────────────────────────────────────────────
# transitions
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_transitions_name_exactly_what_changed(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    previous = None
    seen = 0
    for eye in eyes:
        if previous is None:
            previous = eye
            continue
        expected = {f: (getattr(previous, f), getattr(eye, f)) for f in TRACKED
                    if getattr(previous, f) != getattr(eye, f)}
        got = {t.field: (t.before, t.after) for t in eye.transitions}
        assert got == expected, f"c{eye.index}"
        assert tuple(t.field for t in eye.transitions) == tuple(
            f for f in TRACKED if f in expected), "transitions must follow TRACKED order"
        seen += len(eye.transitions)
        previous = eye


def test_an_unchanged_candle_reports_an_empty_tuple_not_a_gap(wide):
    _, eyes = wide
    quiet = [e for e in eyes if not e.first and not e.transitions]
    assert quiet, "every candle changed something — the empty case never ran"
    for e in quiet:
        assert e.transitions == ()


# ─────────────────────────────────────────────────────────────────────────────
# edge pressure — the parent's own edge, and nothing else
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_edge_pressure_is_measured_from_the_structures_own_edge(name):
    f = frontier_for(ALL_SHAPES[name])
    states = Interpreter(f.snapshot, f).states()
    eyes = read_all(f.readings, states, f.candles)
    checked = 0
    for eye, state in zip(eyes, states):
        if state.break_up is None:
            assert eye.upper is None and eye.lower is None
            continue
        assert eye.upper.distance == state.break_up - eye.price
        assert eye.lower.distance == eye.price - state.break_down
        # the next reference is somewhere else entirely and is never an edge
        if state.above.next is not None:
            assert eye.upper.edge != state.above.next.low or state.break_up == \
                state.above.next.low
        checked += 1


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_closing_counts_a_run_and_resets(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    previous = None
    runs = 0
    for eye in eyes:
        for side in ("upper", "lower"):
            now = getattr(eye, side)
            was = getattr(previous, side) if previous else None
            if now is None:
                continue
            same_node = previous is not None and previous.node_id == eye.node_id
            if not same_node or was is None or now.distance >= was.distance:
                assert now.closing == 0, f"c{eye.index} {side}"
            else:
                assert now.closing == was.closing + 1, f"c{eye.index} {side}"
                runs += 1
        previous = eye


def test_a_closing_run_of_more_than_one_actually_occurs(wide):
    """The whole point of the counter: *third candle running*, not just *closer today*."""
    _, eyes = wide
    assert max((e.upper.closing for e in eyes if e.upper), default=0) >= 2


def test_closing_resets_when_the_structure_changes(ended):
    _, eyes = ended
    previous = None
    for eye in eyes:
        if previous is not None and eye.node_id != previous.node_id:
            for side in ("upper", "lower"):
                ep = getattr(eye, side)
                if ep is not None:
                    assert ep.closing == 0, f"c{eye.index}: {side} counted across a change"
        previous = eye


# ─────────────────────────────────────────────────────────────────────────────
# micro position
# ─────────────────────────────────────────────────────────────────────────────
def test_position_in_micro_is_zero_at_the_low_and_one_at_the_high():
    lo, hi = Decimal("22490"), Decimal("22510")
    assert E._position(lo, lo, hi) == 0
    assert E._position(hi, lo, hi) == 1
    assert E._position(Decimal("22500"), lo, hi) == Decimal("0.5")


def test_position_in_micro_is_not_clamped():
    """`_third()` learned this the hard way: clamping to 1.0 reads as though price were
    still inside a band it has already closed above."""
    lo, hi = Decimal("22490"), Decimal("22510")
    assert E._position(Decimal("22530"), lo, hi) == 2
    assert E._position(Decimal("22470"), lo, hi) == -1


def test_position_in_micro_has_no_answer_without_a_band():
    assert E._position(Decimal("22500"), None, None) is None
    assert E._position(Decimal("22500"), Decimal("22500"), Decimal("22500")) is None


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_position_in_micro_matches_the_band_it_reports(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    checked = 0
    for eye in eyes:
        if eye.micro_low is None or eye.micro_high == eye.micro_low:
            assert eye.position_in_micro is None or eye.micro_low is not None
            continue
        assert eye.position_in_micro == (
            (eye.price - eye.micro_low) / (eye.micro_high - eye.micro_low))
        checked += 1
    if any(e.micro_id for e in eyes):
        assert checked > 0


# ─────────────────────────────────────────────────────────────────────────────
# isolation and determinism
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_eye_never_names_a_trade(name):
    _, eyes = eyes_for(ALL_SHAPES[name])
    for eye in eyes:
        text = " ".join(eye.lines() + [compact(eye)]).upper()
        for word in FORBIDDEN:
            assert word not in text.split(), (
                f"c{eye.index}: the eye emitted {word!r} — this layer describes change, "
                f"it does not trade")


def test_the_trader_reader_does_not_read_the_eye():
    """Phase B's isolation, restated for Phase C: the eye is a **sibling** of the Trader
    Reader, never a layer above it."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src" / "livemap"
    trader = (src / "trader.py").read_text(encoding="utf-8")
    assert "eye" not in trader.lower()
    # and the eye reads only the two layers below it — checked on import lines, since
    # the prose legitimately names the layer it is a sibling of
    imports = [ln for ln in (src / "eye.py").read_text(encoding="utf-8").splitlines()
               if ln.startswith(("import ", "from "))]
    assert imports
    assert not [ln for ln in imports if "trader" in ln or "retest" in ln]


@pytest.mark.parametrize("name", list(ALL_SHAPES))
def test_the_eye_is_deterministic(name):
    closes = ALL_SHAPES[name]
    assert eyes_for(closes)[1] == eyes_for(closes)[1]


def test_read_all_refuses_misaligned_input(wide):
    f, _ = wide
    states = Interpreter(f.snapshot, f).states()
    with pytest.raises(ValueError):
        read_all(f.readings, states[:-1], f.candles)


# ─────────────────────────────────────────────────────────────────────────────
# the assertions above are worthless if they never execute
# ─────────────────────────────────────────────────────────────────────────────
def test_every_path_is_actually_exercised_somewhere():
    """The per-shape tests above assert correctness and stay silent when a shape has no
    structures at all — `one-way walk` is a pure trend and never forms one, so demanding
    every path from every shape would only force a fixture to be bent into shape.

    This one asserts the paths run **somewhere** across the eight, which is the property
    that actually matters: a suite where the interesting branch never executes is a suite
    asserting nothing.
    """
    subject_changes = transitions = quiet = runs = long_runs = pressure = 0
    refused = appeared = 0
    for closes in ALL_SHAPES.values():
        _, eyes = eyes_for(closes)
        previous = None
        for eye in eyes:
            subject_changes += eye.subject_changed
            transitions += len(eye.transitions)
            quiet += not eye.first and not eye.transitions
            refused += sum(1 for d in eye.deltas if not d.comparable)
            appeared += sum(1 for d in eye.deltas
                            if d.before is None and d.after is not None and not eye.first)
            for side in ("upper", "lower"):
                ep = getattr(eye, side)
                if ep is None:
                    continue
                pressure += 1
                runs += ep.closing > 0
                long_runs += ep.closing > 1
            previous = eye
        assert previous is not None

    assert subject_changes > 0, "no parent or micro identity ever changed"
    assert transitions > 0, "no tracked state ever changed"
    assert quiet > 0, "every candle changed something — the empty-tuple case never ran"
    assert refused > 0, "no delta was ever refused for a change of subject"
    assert appeared > 0, "no value ever appeared from None"
    assert pressure > 0, "edge pressure was never measured"
    assert runs > 0, "the closing counter never counted"
    assert long_runs > 0, "no run of more than one candle — `closing` is not a run"


# ─────────────────────────────────────────────────────────────────────────────
# C′ — the overnight gap is not a candle's worth of movement
#
# A′ neutralised it for `migration()`; this layer did not exist then, so it inherited
# nothing. Measured before the guard: the delta across a boundary ran to a median of
# 153.4 points against 17.9 intraday, and 41 `closing` runs spanned a night.
# ─────────────────────────────────────────────────────────────────────────────
from datetime import date, datetime, timedelta  # noqa: E402

from src.boxes.frontier import Reading  # noqa: E402
from src.domain.models import IST, Candle  # noqa: E402
from src.livemap.eye import (  # noqa: E402
    COMPARABLE, INCOMPARABLE, MISSING_VALUE, NO_PREVIOUS, REASONS, SESSION_BOUNDARY,
    SUBJECT_CHANGED, read)
from src.livemap.interpreter import MapState, SideReferences  # noqa: E402

BAND = (Decimal("22450"), Decimal("22480"))


def two_sessions(day_one, day_two):
    """Closes over two calendar days — the only way to reach a session boundary, since
    every synthetic fixture in this repo lives inside one."""
    out = []
    for offset, closes in ((0, day_one), (1, day_two)):
        start = datetime.combine(date(2025, 3, 4) + timedelta(days=offset),
                                 datetime.min.time(), tzinfo=IST).replace(hour=9,
                                                                          minute=15)
        for k, c in enumerate(closes):
            p = Decimal(str(c))
            out.append(Candle("TEST", "5m", start + timedelta(minutes=5 * k),
                              start + timedelta(minutes=5 * (k + 1)),
                              p, p + 2, p - 2, p))
    return out


def stream(candles, node="C01", *, space=Decimal("100")):
    """Drive `read()` directly. The frontier cannot produce a two-day fixture without a
    real feed, and this layer's session rule is testable without one."""
    out, previous = [], None
    for i, k in enumerate(candles):
        reading = Reading(index=i, state="CONFIRMED", interaction="INSIDE",
                          node_id=node, node_kind="cluster", node_status="PROVISIONAL",
                          band=BAND, break_level_up=BAND[1], break_level_down=BAND[0])
        state = MapState(index=i, at=k.close_time, price=k.c, current=None,
                         break_up=BAND[1], break_down=BAND[0],
                         above=SideReferences(), below=SideReferences(),
                         interaction="INSIDE", space_above=space,
                         atr=Decimal("10"))
        previous = read(previous, reading, state, k)
        out.append(previous)
    return out


def test_the_reason_vocabulary_is_closed():
    assert REASONS == {COMPARABLE, NO_PREVIOUS, SESSION_BOUNDARY, SUBJECT_CHANGED,
                       MISSING_VALUE}
    assert INCOMPARABLE == {SESSION_BOUNDARY, SUBJECT_CHANGED}
    with pytest.raises(ValueError):
        Delta("price", reason="market_closed")


def test_a_delta_must_agree_with_its_own_reason():
    """A measured change with a reason, or a refusal without one, is a lie either way."""
    with pytest.raises(ValueError):
        Delta("price", Decimal(1), Decimal(2), Decimal(1), "up", True, SESSION_BOUNDARY)
    with pytest.raises(ValueError):
        Delta("price", Decimal(1), Decimal(2), None, "", True, COMPARABLE)
    with pytest.raises(ValueError):
        Delta("price", Decimal(1), Decimal(2), None, "", True, SESSION_BOUNDARY)


def test_within_one_session_nothing_changed():
    """Rule 1: same-session consecutive candles produce the exact existing delta."""
    eyes = stream(two_sessions([22460, 22465, 22472], [])[:3])
    assert [e.session_start for e in eyes] == [False, False, False]
    assert eyes[1].delta("price").change == Decimal("5")
    assert eyes[1].delta("price").reason == COMPARABLE
    assert eyes[2].delta("price").change == Decimal("7")
    assert all(d.comparable for e in eyes for d in e.deltas)


def test_the_overnight_gap_is_not_a_price_move():
    """Rule 2. 15:25 -> 09:15 is a gap; measuring it as one candle's movement is what
    made the median boundary delta 8.6x a normal candle."""
    eyes = stream(two_sessions([22460, 22465], [22800, 22805]))
    boundary = eyes[2]
    assert boundary.session_start is True
    for d in boundary.deltas:
        assert d.reason == SESSION_BOUNDARY
        assert d.comparable is False
        assert d.change is None
        assert d.direction == ""


def test_the_boundary_is_not_silently_a_zero():
    """Rule 3. A flat delta would claim price did not move — a different lie from the one
    being fixed. The values stay; only the subtraction is refused."""
    eyes = stream(two_sessions([22460, 22465], [22800]))
    d = eyes[2].delta("price")
    assert d.before == Decimal("22465")
    assert d.after == Decimal("22800")
    assert d.change is None and not d.moved
    assert d.direction != "flat"


def test_the_closing_run_does_not_survive_the_night():
    """Rule 4. Price closing on the upper edge for three candles, then a new session:
    the run must restart, or an overnight jump manufactures sustained pressure."""
    eyes = stream(two_sessions([22455, 22460, 22466, 22472], [22476, 22478]))
    runs = [e.upper.closing for e in eyes]
    assert runs[:4] == [0, 1, 2, 3], runs
    assert runs[4] == 0, f"the run survived the boundary: {runs}"
    assert runs[5] == 1, f"the new session did not start counting: {runs}"


def test_the_first_candle_after_the_boundary_compares_normally():
    """Rule 5."""
    eyes = stream(two_sessions([22460, 22465], [22800, 22810]))
    after = eyes[3]
    assert after.session_start is False
    assert after.delta("price").change == Decimal("10")
    assert after.delta("price").reason == COMPARABLE
    assert all(d.comparable for d in after.deltas)


def test_the_session_is_carried_on_the_state():
    eyes = stream(two_sessions([22460, 22465], [22800, 22810]))
    assert [e.session_date for e in eyes] == [date(2025, 3, 4)] * 2 + \
                                             [date(2025, 3, 5)] * 2
    assert [e.session_start for e in eyes] == [False, False, True, False]


def test_the_boundary_outranks_a_subject_change():
    """Precedence: a candle that is both a new day and a new box reports the new day.
    Both refuse the subtraction, and naming the outer fact is the honest one."""
    candles = two_sessions([22460, 22465], [22800])
    out, previous = [], None
    for i, k in enumerate(candles):
        node = "C01" if i < 2 else "C02"
        reading = Reading(index=i, state="CONFIRMED", interaction="INSIDE",
                          node_id=node, band=BAND,
                          break_level_up=BAND[1], break_level_down=BAND[0])
        state = MapState(index=i, at=k.close_time, price=k.c, current=None,
                         break_up=BAND[1], break_down=BAND[0],
                         above=SideReferences(), below=SideReferences(),
                         interaction="INSIDE", atr=Decimal("10"))
        previous = read(previous, reading, state, k)
        out.append(previous)
    assert out[2].delta("position_in_current").reason == SESSION_BOUNDARY


def test_the_first_candle_still_says_no_previous():
    eyes = stream(two_sessions([22460], []))
    assert eyes[0].first is True
    assert eyes[0].session_start is False
    assert all(d.reason == NO_PREVIOUS for d in eyes[0].deltas)


def test_the_session_rule_is_deterministic():
    candles = two_sessions([22460, 22465], [22800, 22810])
    assert stream(candles) == stream(candles)
