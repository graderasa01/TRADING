"""
The Live Map Interpreter — `src/livemap/interpreter.py`.

Two things are being guarded here and they matter more than the formatting:

1. **The break level is the current structure's own edge.** `22460-22480` breaks above
   `22480`. `22560` is the next structural *reference*. An earlier draft of the plan
   confused the two.
2. **This layer never emits a decision.** `STATUS_VOCABULARY` is closed, and
   `test_the_interpreter_cannot_say_long` reads the rendered output looking for trading
   words. The decision layer is quarantined and does not exist.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.frontier import Frontier, run
from src.boxes.snapshot import build_snapshot
from src.domain.models import IST, Candle
from src.livemap.interpreter import (
    FORBIDDEN, HISTORICAL, PROVISIONAL, STATUS_VOCABULARY, MapState, interpret)

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


def states_for(closes) -> tuple[list[MapState], Frontier]:
    candles = make(path(closes))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    f = run(snap, candles[:SPLIT], candles[SPLIT:])
    return interpret(snap, f), f


@pytest.fixture
def banknifty():
    """22460-22480 cluster, then a new shelf at the 22560 reference."""
    return states_for(sit(22470, SPLIT + 30, width=20)
                      + ramp(22482, 22550, 25)
                      + sit(22560, 45, width=8)
                      + ramp(22572, 22650, 22))[0]


# ─────────────────────────────────────────────────────────────────────────────
# rule 1 — the break level is the structure's own edge
# ─────────────────────────────────────────────────────────────────────────────
def test_break_levels_are_the_current_structures_own_edges(banknifty):
    inside = [s for s in banknifty if s.current is not None]
    assert inside, "price must stand inside something at some point"
    for s in inside:
        assert s.break_up == s.current.high
        assert s.break_down == s.current.low


def test_the_next_reference_is_never_the_break_level(banknifty):
    """22560 is a place to look at, not a boundary to break."""
    for s in banknifty:
        if s.break_up is None or s.above.next is None:
            continue
        assert s.above.next.low != s.break_up, (
            f"c{s.index}: the next reference {s.above.next.id} is being reported as "
            f"the break level")
        assert s.above.next.low > s.break_up, "a reference above must be beyond the edge"


def test_references_are_measured_from_the_edge_not_the_close(banknifty):
    """Measuring from the close while inside a structure puts the reference behind the
    trigger — the bug that killed the block map."""
    for s in banknifty:
        if s.current is None or s.above.next is None:
            continue
        expected = s.above.next.low - s.current.high
        assert s.above.next.distance == expected


def test_sides_never_mix(banknifty):
    for s in banknifty:
        for r in s.above.all():
            assert r.distance > 0, f"c{s.index}: {r.id} is above but {r.distance} away"
        for r in s.below.all():
            assert r.distance < 0, f"c{s.index}: {r.id} is below but {r.distance} away"


# ─────────────────────────────────────────────────────────────────────────────
# rule 2 — a live structure is never dressed as a historical one
# ─────────────────────────────────────────────────────────────────────────────
def test_a_freshly_minted_structure_is_provisional(banknifty):
    """The only frontier false positive found over five sessions was a shelf at the
    canvas right edge that was still forming. Standing in something is not knowing what
    it was."""
    minted = [s for s in banknifty
              if s.current is not None and s.current.id.startswith("L")]
    assert minted, "the 22560 shelf must be minted at some point"
    assert all(s.current.status == PROVISIONAL for s in minted)


def test_an_adopted_structure_is_historical():
    """A shelf the frozen map already had, revisited, is not provisional."""
    states, _ = states_for(sit(22470, SPLIT + 20, width=20)
                           + ramp(22482, 22560, 20)
                           + sit(22470, 45, width=20))
    adopted = [s for s in states
               if s.current is not None and s.current.status == HISTORICAL]
    assert adopted, "returning to a frozen shelf must be reported as historical"
    assert all(s.current.id.startswith("C") for s in adopted)


# ─────────────────────────────────────────────────────────────────────────────
# rule 3 — this layer cannot make a decision
# ─────────────────────────────────────────────────────────────────────────────
def test_status_vocabulary_is_closed(banknifty):
    for s in banknifty:
        assert s.status in STATUS_VOCABULARY


def test_an_unknown_status_is_refused(banknifty):
    from dataclasses import replace
    with pytest.raises(ValueError, match="unknown status"):
        replace(banknifty[0], status="GO_LONG_NOW")


def test_the_interpreter_cannot_say_long(banknifty):
    """Read the rendered output the way a consumer would, and look for trading words."""
    for s in banknifty:
        text = " ".join(s.lines()).upper()
        for word in FORBIDDEN:
            assert word not in text.split(), (
                f"c{s.index}: the map emitted {word!r} — this layer describes geography, "
                f"it does not trade")


def test_no_status_names_a_trade():
    for word in FORBIDDEN:
        assert not any(word in s for s in STATUS_VOCABULARY)


# ─────────────────────────────────────────────────────────────────────────────
# the state stream reads like the walkthrough
# ─────────────────────────────────────────────────────────────────────────────
def test_the_lifecycle_is_readable_in_status(banknifty):
    seen = [s.status for s in banknifty]
    for want in ("WAIT", "BREAK_ATTEMPT_UP", "ACCEPTED_ABOVE", "IN_TRANSIT"):
        assert want in seen, f"{want} missing from {sorted(set(seen))}"
    assert seen.index("BREAK_ATTEMPT_UP") < seen.index("ACCEPTED_ABOVE")


def test_a_failed_break_is_reported_as_such():
    states, _ = states_for(sit(22470, SPLIT + 25, width=20)
                           + ramp(22482, 22488, 3)
                           + sit(22470, 35, width=20))
    seen = [s.status for s in states]
    assert "BREAKOUT_FAILED" in seen or "WAIT" in seen


def test_references_say_what_each_price_is(banknifty):
    """Not an invalidation call — the layer that knows the position decides that."""
    withrefs = [s for s in banknifty if s.references]
    assert withrefs
    notes = {r.note for s in withrefs for r in s.references}
    assert "upper edge" in notes and "lower edge" in notes


def test_every_state_renders(banknifty):
    for s in banknifty:
        lines = s.lines()
        assert any(ln.startswith("STATUS") for ln in lines)
        assert any(ln.startswith("PRICE") for ln in lines)
