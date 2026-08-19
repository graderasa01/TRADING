"""
The historical structure map — `src/boxes/structure.py`.

Every test here locks a bug that **actually happened** while building this layer against
real Bank Nifty data on 2026-02-16, plus the two sequences the whole design exists to tell
apart. None of them are hypothetical:

| # | the bug | what it looked like |
|---|---|---|
| 1 | `extend_back` under-extension | a 40-candle shelf came back as 20 one-candle clusters |
| 2 | anchor assumed to be the structure's end | eight clusters reported at eight consecutive anchors, all describing one shelf price had already left |
| 3 | giant merged box | the failure the whole repo exists to prevent, one layer down |
| 4 | gap double-counting | `coverage 1004/1000` on a 1000-candle canvas |
| 5 | stale pullback | a +344 point run labelled a pullback of an impulse 600 candles earlier |

The partition assertion (§`assert_partition`) is run by most tests rather than one, because
"the segments tile the timeline exactly" is the property everything downstream — nesting,
the event graph, the spatial projection — silently assumes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from src.boxes.structure import (
    MIN_MOVE_BARS, STRUCTURE_KINDS, Link, build_chain, extend_back, last_touch)
from src.domain.models import IST, Candle

ATR = Decimal("10")


# ─────────────────────────────────────────────────────────────────────────────
# fixtures — the same helpers `test_adaptive_map.py` uses, kept local so this file
# stands alone and a change to one suite cannot silently retune the other
# ─────────────────────────────────────────────────────────────────────────────
def make(spec, day: date = date(2025, 3, 4), start_hour: int = 9,
         start_minute: int = 15) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=start_hour, minute=start_minute)
    return [Candle("TEST", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path(closes, wick: float = 1.0):
    out, prev = [], closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def sit(price: float, n: int, width: float = 18.0):
    """Price resting: a small four-beat oscillation, no net travel."""
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    """A one-way walk — an impulse leg."""
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def structures(chain) -> list[Link]:
    return [ln for ln in chain if ln.kind in STRUCTURE_KINDS]


def moves(chain) -> list[Link]:
    return [ln for ln in chain if ln.kind not in STRUCTURE_KINDS]


def assert_partition(chain: list[Link], candles: list[Candle]) -> None:
    """The links tile `candles` exactly: no hole, no overlap, nothing off the end.

    This is the invariant that caught the gap bug — the two candles either side of an
    overnight boundary were owned by the gap *and* by both neighbouring moves, so a
    1000-candle canvas reported 1004 candles of segments.
    """
    assert chain, "empty chain"
    assert chain[0].start == 0, f"chain starts at {chain[0].start}, not 0"
    assert chain[-1].end == len(candles) - 1, f"chain ends at {chain[-1].end}"
    for a, b in zip(chain, chain[1:]):
        assert b.start == a.end + 1, (
            f"{a.id} ends {a.end}, {b.id} starts {b.start} — "
            f"{'overlap' if b.start <= a.end else 'hole'}")
    assert sum(ln.bars for ln in chain) == len(candles)


# ─────────────────────────────────────────────────────────────────────────────
# 1. impulse -> cluster: two objects, and the boundary is recovered
# ─────────────────────────────────────────────────────────────────────────────
def test_impulse_then_cluster_are_two_objects():
    """The regression test for the entire design.

        100 -> 123   then   123 121 122 123 124 122 123

    must never come back as one 100-124 box. The impulse and the stabilisation after it
    are different things that happened at different times.
    """
    candles = make(path(ramp(60000, 60300, 30) + sit(60300, 45)))
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)

    st = structures(chain)
    assert st, "the 45-candle rest must be found"
    biggest = max(st, key=lambda ln: ln.bars)

    # It sits in the rest, not across the ramp.
    assert biggest.start >= 28, (
        f"structure starts at {biggest.start}; the rest begins at 30 — "
        f"extend_back walked back into the impulse")
    assert float(biggest.low) > 60250, f"band {biggest.label if False else biggest.low}"
    assert float(biggest.high) - float(biggest.low) < 150, "band swallowed the ramp"


def test_extend_back_stops_at_the_impulse():
    """`extend_back` in isolation: the ramp does not overlap the rest's band, so the walk
    must stop within a candle or two of where the rest actually began."""
    candles = make(path(ramp(60000, 60300, 30) + sit(60300, 45)))
    start = extend_back(candles, Decimal("60290"), Decimal("60310"), len(candles) - 1,
                        tol=Decimal("3"))
    assert 28 <= start <= 32, f"true start is 30, extend_back said {start}"


def test_last_touch_finds_the_real_end():
    """A window can still be dominated by a shelf price has already left.

    On 2026-02-16 at candle 443 price was trading at 60,380-60,409 and the detector
    correctly reported a cluster at 60,271-60,309 — a real structure that ended at 434.
    Taking the anchor as the end turned one shelf into eight one-candle clusters.
    """
    candles = make(path(sit(60000, 40) + ramp(60000, 60300, 20)))
    end = last_touch(candles, Decimal("59990"), Decimal("60010"), len(candles) - 1,
                     tol=Decimal("3"))
    assert end is not None and end <= 42, (
        f"the shelf ended around candle 39; last_touch said {end}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. cluster -> impulse -> cluster: three objects, no merged box
# ─────────────────────────────────────────────────────────────────────────────
def test_cluster_impulse_cluster_stays_three_objects():
    candles = make(path(sit(60000, 40) + ramp(60000, 60300, 25) + sit(60300, 40)))
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)

    st = structures(chain)
    assert len(st) >= 2, f"both shelves must survive, got {[ln.id for ln in st]}"

    lows = [ln for ln in st if float(ln.high) < 60150]
    highs = [ln for ln in st if float(ln.low) > 60150]
    assert lows and highs, "one shelf at each price is the whole point"

    between = [ln for ln in moves(chain)
               if lows[-1].end < ln.start and ln.end < highs[0].start]
    assert between, "the leg between the shelves must be its own object"


def test_no_giant_merged_box():
    """No structure may span both shelves. This is the bug the repo has already had
    three times, and it is the one that is easiest to reintroduce."""
    candles = make(path(sit(60000, 40) + ramp(60000, 60300, 25) + sit(60300, 40)))
    chain, _ = build_chain(candles)
    for ln in structures(chain):
        assert float(ln.width) < 200, (
            f"{ln.id} is {float(ln.width):.0f} points wide — it merged the two shelves "
            f"and the impulse between them")


def test_a_staircase_produces_no_structure_at_all():
    """100 -> 102 -> 104 -> 106 -> 108 -> 110. Same high and low as a range, no rotation.
    The correct answer is *no box*, and it stays the correct answer here."""
    candles = make(path(ramp(60000, 60600, 60)))
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)
    assert not structures(chain), (
        f"a one-way walk is not a structure: {[(ln.id, ln.kind) for ln in chain]}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. no one-candle false clusters
# ─────────────────────────────────────────────────────────────────────────────
def test_one_shelf_is_one_structure_not_twenty_slivers():
    """The `extend_back` under-extension bug, locked.

    A 60-candle rest must come back as roughly one object. Before the fix it came back as
    twenty one-candle clusters, because a cluster's band is `core_band` — the tightest
    band holding 70% of the window's minutes — so a third of its own candles fall outside
    it and "two consecutive closes outside" fired constantly while price sat still.
    """
    candles = make(path(sit(60000, 60)))
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)

    st = structures(chain)
    assert st, "a 60-candle rest must be found"
    assert len(st) <= 3, f"one shelf came back as {len(st)} objects: {[s.id for s in st]}"
    assert max(ln.bars for ln in st) >= 25, (
        f"longest structure is only {max(ln.bars for ln in st)} candles of 60")


def test_sub_resolution_moves_are_seams_not_events():
    """A move shorter than the smallest microscope window that also went nowhere is the
    joint between two detections, not a behaviour. Eleven such one-candle slivers were
    being reported as `transition` — a claim the data does not support."""
    candles = make(path(sit(60000, 40) + ramp(60000, 60300, 25) + sit(60300, 40)))
    chain, _ = build_chain(candles)
    for ln in moves(chain):
        if ln.bars < MIN_MOVE_BARS and ln.measurements.get("net_atr", 0.0) < 1.0:
            assert ln.kind in {"seam", "gap"}, (
                f"{ln.id} is {ln.bars} candles and went nowhere but is labelled "
                f"{ln.kind}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. pullback is context, and the context goes stale
# ─────────────────────────────────────────────────────────────────────────────
def test_pullback_needs_a_recent_impulse():
    """impulse -> base -> base -> base -> counter-move is NOT a pullback.

    A +344 point run was once labelled a pullback against an impulse six hundred candles
    earlier. By the third shelf the leg is over.
    """
    candles = make(path(
        ramp(60000, 60300, 25)          # impulse up
        + sit(60300, 30)                # base 1
        + sit(60280, 30)                # base 2
        + sit(60260, 30)                # base 3
        + ramp(60260, 60150, 20)))      # counter-move, long after the leg
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)

    tail = [ln for ln in moves(chain) if ln.start >= 110]
    assert tail, "the closing counter-move must exist as an object"
    assert all(ln.kind != "pullback" for ln in tail), (
        f"stale pullback: {[(ln.id, ln.kind, ln.start) for ln in tail]}")


def test_a_seam_does_not_end_a_leg():
    """Sub-resolution joints must not clear the impulse memory — otherwise every pullback
    is disqualified by the one-candle seam that precedes it."""
    candles = make(path(sit(60000, 30) + ramp(60000, 60300, 25) + sit(60300, 30)))
    chain, _ = build_chain(candles)
    seams = [ln for ln in chain if ln.kind == "seam"]
    for s in seams:
        assert s.bars < MIN_MOVE_BARS, f"{s.id} is {s.bars} candles — not a seam"


# ─────────────────────────────────────────────────────────────────────────────
# 5. sessions: a gap is an event, never an impulse, and never double-counted
# ─────────────────────────────────────────────────────────────────────────────
def two_sessions() -> list[Candle]:
    """Two days with a 200-point overnight jump, and a move running into the boundary on
    both sides so the gap lands inside a move rather than inside a structure."""
    day_one = make(path(sit(60000, 40) + ramp(60000, 60120, 25)),
                   day=date(2025, 3, 4))
    day_two = make(path(ramp(60320, 60420, 25) + sit(60420, 40)),
                   day=date(2025, 3, 5))
    return day_one + day_two


def test_gap_is_its_own_event_and_never_an_impulse():
    candles = two_sessions()
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)

    gaps = [ln for ln in chain if ln.kind == "gap"]
    assert len(gaps) == 1, f"one overnight boundary, {len(gaps)} gap events"
    assert gaps[0].bars == 2, "a gap owns exactly the two candles either side"
    assert candles[gaps[0].start].session_date != candles[gaps[0].end].session_date

    assert not any(ln.kind.startswith("impulse") and ln.start <= gaps[0].start
                   <= ln.end for ln in chain), "the overnight jump was read as an impulse"


def test_gap_does_not_break_the_partition():
    """`coverage 1004/1000` — the gap and both neighbouring moves each claimed the
    boundary candles."""
    candles = two_sessions()
    chain, _ = build_chain(candles)
    assert_partition(chain, candles)
    assert sum(ln.bars for ln in chain) == len(candles)


# ─────────────────────────────────────────────────────────────────────────────
# 6. the partition holds on shapes that are not textbook
# ─────────────────────────────────────────────────────────────────────────────
def test_partition_holds_on_mixed_shapes():
    for name, closes in (
            ("rest only", sit(60000, 90)),
            ("trend only", ramp(60000, 60900, 90)),
            ("rest-trend-rest", sit(60000, 30) + ramp(60000, 60300, 30) + sit(60300, 30)),
            ("v-shape", ramp(60000, 60300, 45) + ramp(60300, 60000, 45)),
            ("noise", sit(60000, 20) + ramp(60000, 60080, 10) + sit(60080, 20)
             + ramp(60080, 60010, 15) + sit(60010, 25)),
    ):
        candles = make(path(closes))
        chain, _ = build_chain(candles)
        assert_partition(chain, candles)
        assert all(ln.kind in STRUCTURE_KINDS or ln.kind in {
            "impulse_up", "impulse_down", "pullback", "transition", "seam", "gap"
        } for ln in chain), f"{name}: unknown kind"
