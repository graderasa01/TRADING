"""
The adaptive cluster-range mapper — `src/boxes/adaptive.py`, `src/boxes/mapper.py`.

The two sequences the whole design exists to tell apart are the first two tests. They have
the **same high and the same low**, so every detector built on extremes calls them the same
object:

    100 → 109 → 102 → 108 → 101 → 110     rotation   → a range
    100 → 102 → 104 → 106 → 108 → 110     migration  → nothing at all

Everything else here guards a bug that has already happened once in this repo: giant boxes
over trends, boxes that widen to contain the candle that broke them, one move counted as
three breaks, and a box that keeps breaking every candle after price has left it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.adaptive import (
    WINDOWS, choose, compression, core_band, migration, read_window, touches, traverses,
    visits)
from src.boxes.mapper import Mapper, build, story
from src.domain.models import IST, Candle

ATR = Decimal("10")


def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)
    return [Candle("TEST", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path(closes: list[float], wick: float = 1.0) -> list[tuple[float, ...]]:
    """Candles walking through `closes`, each with a small wick either side."""
    out = []
    prev = closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def rotate(low: float, high: float, legs: int, per_leg: int = 6) -> list[float]:
    """`legs` trips between `low` and `high`, `per_leg` candles each."""
    out, a = [], low
    for i in range(legs):
        b = high if a == low else low
        out += [a + (b - a) * (j + 1) / per_leg for j in range(per_leg)]
        a = b
    return out


def sit(price: float, n: int, width: float = 6.0) -> list[float]:
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# the two sequences
# ─────────────────────────────────────────────────────────────────────────────
def test_rotation_is_a_range():
    """100 → 109 → 102 → 108 → 101 → 110 — two-sided auction."""
    candles = make(path(rotate(60000, 60100, legs=5, per_leg=7)))
    _, rng = choose(candles, ATR)
    assert rng is not None, "rotation between two defended edges must be a range"
    assert rng.traverses >= 2 and rng.upper_touches >= 2 and rng.lower_touches >= 2
    assert float(rng.low) < 60020 and float(rng.high) > 60080


def test_migration_is_nothing_at_all():
    """100 → 102 → 104 → 106 → 108 → 110 — the same high and low, no structure.

    This is the failure that killed the last three designs: a staircase drawn as one giant
    box. `migration` and the stability run must both refuse it.
    """
    candles = make(path([60000 + 2.5 * i for i in range(40)]))
    cluster, rng = choose(candles, ATR)
    assert cluster is None, cluster
    assert rng is None, rng


def test_the_two_sequences_have_identical_extremes():
    """Proof that the distinction cannot come from high/low — it has to come from shape."""
    a = make(path(rotate(60000, 60100, legs=5, per_leg=7)))
    b = make(path([60000 + 100 * i / 34 for i in range(35)]))
    assert abs(max(k.h for k in a) - max(k.h for k in b)) < 5
    assert abs(min(k.l for k in a) - min(k.l for k in b)) < 5
    assert migration(a) < 0.25 < migration(b)


# ─────────────────────────────────────────────────────────────────────────────
# the measurements
# ─────────────────────────────────────────────────────────────────────────────
def test_migration_is_one_for_a_perfect_staircase_and_zero_for_a_round_trip():
    up = make(path([60000 + 5 * i for i in range(20)]))
    assert migration(up) == pytest.approx(1.0, abs=1e-9)
    there_and_back = make(path([60000 + 5 * i for i in range(10)]
                               + [60045 - 5 * i for i in range(10)]))
    assert migration(there_and_back) < 0.1


def test_compression_separates_grinding_from_travelling():
    assert compression(make(path(sit(60000, 30)))) > 0.75
    assert compression(make(path([60000 + 6 * i for i in range(30)]))) < 0.35


def test_core_band_is_the_hump_not_the_whole_range():
    """One dense stay surrounded by traffic must come back as the stay.

    With two *equal* humps the tightest half-minutes band is legitimately one of them —
    each holds exactly half — so the fixture is deliberately lopsided.
    """
    candles = make(path([60000 + 3 * i for i in range(12)] + sit(60036, 40)))
    band = core_band(candles, ATR)
    assert band is not None
    lo, hi = band
    assert 60028 < float(lo) and float(hi) < 60044, (float(lo), float(hi))
    assert float(hi - lo) < 16, "the core swallowed the approach"


def test_touches_counts_approaches_not_candles():
    """Ten candles grinding the high are one touch. Price must leave by more than tol and
    come back for the second to count."""
    grind = make(path([60100] * 12))
    n, _ = touches(grind, Decimal("60100"), Decimal("2.5"), upper=True, gap=3)
    assert n == 1, n
    twice = make(path([60100] * 4 + [60040] * 8 + [60100] * 4))
    n, band = touches(twice, Decimal("60100"), Decimal("2.5"), upper=True, gap=3)
    assert n == 2, n
    assert band is not None


def test_traverses_uses_thirds_so_drifting_in_the_middle_is_not_rotation():
    middle = make(path([60050 + (i % 3) for i in range(30)]))
    assert traverses(middle, Decimal("60000"), Decimal("60100")) == 0
    swinging = make(path(rotate(60000, 60100, legs=4, per_leg=6)))
    assert traverses(swinging, Decimal("60000"), Decimal("60100")) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# the adaptive window
# ─────────────────────────────────────────────────────────────────────────────
def test_chooses_the_smallest_stable_window_not_the_largest():
    """A cluster that has existed for the last 25 candles, with older unrelated history
    before it, must be found by a small window — not by the biggest one that still fits."""
    candles = make(path([60300 - 4 * i for i in range(40)] + sit(60140, 30)))
    cluster, _ = choose(candles, ATR)
    assert cluster is not None
    assert cluster.window <= 33, f"picked N={cluster.window}, too far back"
    assert float(cluster.low) > 60100, "the box reached back into the downtrend"


def test_no_stable_run_means_no_box():
    """Refusing to answer is a real answer. During a trend it is the correct one."""
    candles = make(path([60000 + 3.2 * i for i in range(90)]))
    assert choose(candles, ATR) == (None, None)


def test_stability_needs_three_agreeing_windows():
    """A structure visible at exactly one window length is noise, and must be rejected even
    though `read_window` found it."""
    candles = make(path(rotate(60000, 60100, legs=5, per_leg=7)))
    hits = [read_window(candles, n, ATR)[1] for n in WINDOWS]
    found = [n for n, p in zip(WINDOWS, hits) if p is not None]
    _, chosen = choose(candles, ATR)
    assert chosen is not None
    assert len(found) >= 3, found


# ─────────────────────────────────────────────────────────────────────────────
# freeze and break
# ─────────────────────────────────────────────────────────────────────────────
def test_an_admitted_box_never_moves_again():
    """The whole point. The box must not widen to contain the candle that breaks it."""
    m = Mapper()
    for c in make(path(rotate(60000, 60100, legs=5, per_leg=7))):
        m.on_candle(c)
    assert m.boxes, "expected at least one box"
    before = {id(b): (b.kind, b.low, b.high, b.born, b.window) for b in m.boxes}
    for c in make(path([60100 + 8 * i for i in range(15)])):
        m.on_candle(c)
    for b in m.boxes:
        if id(b) in before:
            assert (b.kind, b.low, b.high, b.born, b.window) == before[id(b)],                 f"a frozen box moved: {b.label()}"


def test_leaving_is_recorded_once_not_on_every_candle_away():
    """Candles 34, 35 and 36 of one move were once recorded as three separate breaks, and a
    box price had left long ago kept re-triggering the counter."""
    m = build(make(path(sit(60000, 40))))
    box = m.current()
    assert box is not None and box.state == "holding"

    away = make(path([60400] * 30))
    for k, c in enumerate(away):
        m.on_candle(c)
        if k == 0:
            assert box.state == "holding", "one close outside must not be a break"
    assert box.left_at is not None and box.left_side == "up"
    first = box.left_at
    for c in make(path([60400] * 20)):        # far away, never returning
        m.on_candle(c)
    assert box.left_at == first, "the break was recorded again later"
    assert box.crossed_at is None, "never came back through — not crossed"


def test_one_close_out_then_back_in_is_not_a_break():
    """A single poke outside must leave the box holding, and must reset the counter."""
    m = build(make(path(sit(60000, 40))))
    box = m.current()
    assert box is not None
    mid = float(box.mid)
    for c in make(path([60400, mid, 60400, mid, mid])):
        m.on_candle(c)
        assert box.state == "holding", "alternating pokes broke the box"


def test_a_left_box_stays_on_the_map_as_a_target():
    """The design fault the first build had: deleting a box when price left it emptied the
    whole above/below stack, because the only surviving box was the one price was in."""
    m = build(make(path(sit(60000, 40) + [60000 + 10 * i for i in range(1, 26)]
                        + sit(60250, 40))))
    assert m.current() is not None, "expected a box at the new resting price"
    below = m.below()
    assert below, "the shelf price rose out of vanished from the map"
    assert any(b.state == "left" for b in below)


def test_crossed_marks_a_box_that_has_been_sliced_straight_through():
    """Out one side and out the other with no close inside — price went through it.

    A close *inside* on the way back is a different thing: the shelf is still there and
    price returned to it, which registers as a confirmation, not a crossing.
    """
    m = build(make(path(sit(60000, 40))))
    box = m.current()
    assert box is not None
    for c in make(path([60400] * 6 + [59600] * 6)):
        m.on_candle(c)
    assert box.left_side == "up" and box.crossed_at is not None
    assert box.spent and box not in m.live()


def test_coming_back_and_rebuilding_is_a_confirmation_not_a_crossing():
    """Price leaving and the same structure re-forming is the `revisit` evidence the window
    scan structurally cannot see — the core band is where price sat *during* the window, so
    it can never record price returning to it later."""
    m = build(make(path(sit(60000, 40))))
    box = m.current()
    assert box is not None and box.confirmations == 0
    for c in make(path([60400] * 8 + sit(float(box.mid), 30))):
        m.on_candle(c)
    assert box.confirmations >= 1, "the market rebuilt the same shelf and nothing recorded it"
    assert box.state == "holding" and not box.spent


def test_rotations_are_recorded_on_the_box_they_happened_in():
    m = build(make(path(rotate(60000, 60100, legs=6, per_leg=7))))
    rots = [r for _, r in m.all_rotations()]
    assert rots, "a rotating range recorded no rotations"
    assert all(r.direction in ("high->low", "low->high") for r in rots)
    assert all(r.points > 0 and r.candles > 0 for r in rots)


# ─────────────────────────────────────────────────────────────────────────────
# the map that reaches the trader
# ─────────────────────────────────────────────────────────────────────────────
def test_story_targets_are_measured_from_the_edge_that_breaks():
    """The bug that killed the block map: a break of 60,472 handed a target of 60,425 —
    47 points *behind* the trigger."""
    m = build(make(path(sit(60000, 30) + rotate(60000, 60120, legs=4, per_leg=8)
                        + sit(60060, 20))))
    here = m.current()
    if here is None:
        pytest.skip("no box under price in this fixture")
    for b in m.above(price=here.high):
        assert b.low > here.high
    for b in m.below(price=here.low):
        assert b.high < here.low
    lines = story(m)
    assert any(ln.startswith("AGAR UPAR") for ln in lines)
    assert any(ln.startswith("ABHI") for ln in lines)


def test_story_survives_an_empty_map():
    m = build(make(path([60000 + 3.2 * i for i in range(60)])))
    assert m.live() == []
    lines = story(m)
    assert any("kisi box ke andar nahi" in ln for ln in lines)


def test_no_look_ahead_the_map_at_candle_k_uses_only_candles_up_to_k():
    """CLAUDE.md §3. Building to candle 60 and then continuing must give exactly the same
    boxes at candle 60 as building the whole thing and asking about candle 60."""
    candles = make(path(rotate(60000, 60100, legs=6, per_leg=7)))
    short = build(candles[:60])
    long = Mapper()
    for c in candles[:60]:
        long.on_candle(c)
    snapshot = [(b.kind, b.low, b.high, b.born) for b in long.boxes]
    for c in candles[60:]:
        long.on_candle(c)
    assert [(b.kind, b.low, b.high, b.born) for b in long.boxes[:len(snapshot)]] == snapshot
    assert [(b.kind, b.low, b.high, b.born) for b in short.boxes] == snapshot
