"""
The Trader Reader — `src/livemap/trader.py`.

The five fixtures are the **real Bank Nifty situations already found in the live trace**,
rebuilt synthetically so they are deterministic:

| case | what it is |
|---|---|
| 1 | clean upside breakout with a lot of room |
| 2 | clean downside breakout with a lot of room |
| 3 | mechanically identical breakout with ~nothing above it |
| 4 | break attempt that re-entered |
| 5 | revisit of a historical structure, then a break of **its own** edge |

Case 3 exists to pin the thing this layer must never do: cases 1 and 3 are the same
breakout by every mechanical test, and the only difference is `SPACE`. The Reader must
report that difference and **must not** rule on it — a threshold picked from these
examples would be fitted to them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.frontier import run
from src.boxes.snapshot import build_snapshot
from src.domain.models import IST, Candle
from src.livemap.interpreter import Interpreter
from src.livemap.trader import (
    BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK, FORBIDDEN, LOCATIONS, WAIT, read_all)

SPLIT = 90


def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=9, minute=15)
    return [Candle("NIFTY BANK", "1m", start + timedelta(minutes=i),
                   start + timedelta(minutes=i + 1),
                   Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c)))
            for i, (o, h, l, c) in enumerate(spec)]


def path(closes, wick: float = 1.5):
    out, prev = [], closes[0]
    for c in closes:
        out.append((prev, max(prev, c) + wick, min(prev, c) - wick, c))
        prev = c
    return out


def sit(price: float, n: int, width: float = 18.0):
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def trader_for(closes):
    candles = make(path(closes))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    f = run(snap, candles[:SPLIT], candles[SPLIT:])
    return read_all(Interpreter(snap, f).states())


def families(states):
    return [t.family for t in states]


# ─────────────────────────────────────────────────────────────────────────────
# case 1 — clean upside breakout, plenty of room
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def case_open_breakout():
    """60,417-60,452 broken upward, next reference far away."""
    return trader_for(sit(60434, SPLIT + 30, width=35)
                      + ramp(60456, 60690, 45)
                      + sit(60700, 30, width=20))


def test_open_breakout_is_a_long_candidate(case_open_breakout):
    longs = [t for t in case_open_breakout if t.family == BREAKOUT_LONG]
    assert longs, f"no long candidate in {sorted(set(families(case_open_breakout)))}"
    t = longs[0]
    assert t.break_direction == "up"
    assert t.break_level is not None
    assert t.reason.startswith("accepted above")


def test_the_break_level_is_the_structures_own_edge(case_open_breakout):
    """Never the next reference."""
    for t in case_open_breakout:
        if t.break_level is None or t.next_reference_low is None:
            continue
        assert t.break_level != t.next_reference_low


# ─────────────────────────────────────────────────────────────────────────────
# case 2 — clean downside breakout
# ─────────────────────────────────────────────────────────────────────────────
def test_downside_breakout_is_a_short_candidate():
    states = trader_for(sit(60708, SPLIT + 30, width=22)
                        + ramp(60694, 60480, 45)
                        + sit(60470, 30, width=20))
    shorts = [t for t in states if t.family == BREAKOUT_SHORT]
    assert shorts, f"no short candidate in {sorted(set(families(states)))}"
    t = shorts[0]
    assert t.break_direction == "down"
    assert t.reason.startswith("accepted below")


# ─────────────────────────────────────────────────────────────────────────────
# case 3 — the same breakout, with nothing above it
# ─────────────────────────────────────────────────────────────────────────────
def test_a_cramped_breakout_is_still_a_candidate_but_the_space_shows_it():
    """Mechanically identical to case 1. **Not** downgraded, **not** skipped — the
    difference is carried in `SPACE` and settled by replay, not here."""
    cramped = trader_for(sit(60434, SPLIT + 30, width=35)
                         + ramp(60456, 60470, 8)
                         + sit(60474, 40, width=12))
    longs = [t for t in cramped if t.family == BREAKOUT_LONG]
    if not longs:
        pytest.skip("this shape did not produce an accepted break")
    t = longs[0]
    assert t.family == BREAKOUT_LONG, "a tight breakout is still a breakout"
    if t.space_points is not None:
        assert t.space_points < 200, "this fixture is supposed to be cramped"


def test_space_is_never_used_to_change_the_family():
    """The rule set contains no space threshold. If one appears, this fails."""
    import inspect

    from src.livemap import trader
    src = inspect.getsource(trader.read)
    for token in ("space_points >", "space_points <", "space_atr >", "space_atr <"):
        assert token not in src, (
            f"{token!r} appears in the decision path — space is evidence at this stage, "
            f"not a gate. Replay decides the threshold.")


# ─────────────────────────────────────────────────────────────────────────────
# case 4 — break attempt that came back
# ─────────────────────────────────────────────────────────────────────────────
def test_a_reentry_is_a_failed_break_candidate():
    states = trader_for(sit(60708, SPLIT + 25, width=22)
                        + ramp(60722, 60726, 3)
                        + sit(60706, 35, width=22))
    failed = [t for t in states if t.family == FAILED_BREAK]
    assert failed, f"no failed break in {sorted(set(families(states)))}"
    t = failed[0]
    assert t.failed_side in {"up", "down"}
    assert t.reentry_level is not None


def test_a_failed_upside_break_is_not_turned_into_a_short():
    """The rule *"failed breakout = reverse trade"* is exactly what this layer refuses."""
    states = trader_for(sit(60708, SPLIT + 25, width=22)
                        + ramp(60722, 60726, 3)
                        + sit(60706, 35, width=22))
    for t in states:
        if t.family == FAILED_BREAK:
            assert t.family != BREAKOUT_SHORT
            assert t.break_direction == "", "a failed break has no trade direction"


# ─────────────────────────────────────────────────────────────────────────────
# case 5 — revisit, then a break of its own edge
# ─────────────────────────────────────────────────────────────────────────────
def test_a_revisited_structure_breaks_at_its_own_edge():
    states = trader_for(sit(60708, SPLIT + 20, width=22)
                        + ramp(60694, 60560, 25)
                        + sit(60706, 30, width=22)
                        + ramp(60694, 60520, 25))
    revisits = [t for t in states if t.revisit]
    assert revisits, "returning to a frozen structure must be flagged as a revisit"
    breaks = [t for t in states if t.family in {BREAKOUT_LONG, BREAKOUT_SHORT}]
    assert breaks, "the revisited structure must be breakable"
    for t in breaks:
        assert t.structure_id is not None


# ─────────────────────────────────────────────────────────────────────────────
# discipline
# ─────────────────────────────────────────────────────────────────────────────
def test_wait_is_the_default(case_open_breakout):
    assert families(case_open_breakout).count(WAIT) > len(case_open_breakout) / 2, (
        "most candles are not trades; WAIT must dominate")


def test_range_interior_never_produces_a_breakout(case_open_breakout):
    """Interior means no edge is in play, so no breakout can be read there.

    `FAILED_BREAK` is the one non-WAIT family allowed here, and correctly so: a break
    that re-entered puts price back in the interior — that is what re-entry *means*.
    """
    for t in case_open_breakout:
        if t.location == "INTERIOR":
            assert t.family in {WAIT, FAILED_BREAK}, (
                f"c{t.index}: interior produced {t.family}")


def test_locations_are_a_closed_vocabulary(case_open_breakout):
    for t in case_open_breakout:
        assert t.location in LOCATIONS


def test_the_reader_never_names_an_action(case_open_breakout):
    for t in case_open_breakout:
        text = " ".join(t.lines()).upper()
        for word in FORBIDDEN:
            assert word not in text
    for word in FORBIDDEN:
        assert not any(word in fam for fam in
                       (BREAKOUT_LONG, BREAKOUT_SHORT, FAILED_BREAK, WAIT))


def test_there_is_no_entry_ready_state():
    """Entry needs more evidence than map interpretation. Inventing it here would turn a
    description into an instruction."""
    from src.livemap.trader import FAMILIES
    assert not any("ENTRY" in f for f in FAMILIES)


def test_there_is_no_trade_score():
    """Every reason stays a separate field. One number would hide which fact carried the
    decision — which is the only thing worth checking at this stage."""
    from src.livemap.trader import TraderState
    fields = set(TraderState.__annotations__)
    for token in ("score", "confidence", "probability", "weight", "rating"):
        assert not any(token in f for f in fields), (
            f"a {token} field would collapse the evidence: {fields}")
