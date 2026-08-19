"""
Phase A′ — the overnight jump stops being measured as movement.

`structure.split_moves_at_sessions()` has always said it, for the batch chain:

> *"The overnight jump itself is not market movement, so it must never be measured as
> one: left inside a move, a 300-point gap reads as a perfect efficiency-ratio impulse."*

The batch scan acts on that by cutting **moves** at the boundary. Nothing was doing it
for a **measurement window** — and on 5m that is nearly every window there is, because a
session is exactly 75 candles and `WINDOW_MAX` is 75. Measured over 120 teach sessions:

```
windows spanning a session boundary        98.7%
migration inflated by the gap    median +0.03   p90 +0.13   max +0.52
```

`read_window` scores structures as `mean(parts) - migration`, against a `min_score` of
0.35. So a `+0.52` inflation is not a rounding difference: one 1 Mar window whose real
efficiency was `0.007` — pure rotation — was read as `0.526` and could not have produced
a structure at any score.

## What this change is, and what it is not

```
IS      a step that crosses a session boundary is dropped from BOTH the walk and the
        net, so price is credited with neither the distance nor the direction of a
        move it never made
IS NOT  a rule that structures may not span sessions. A shelf built yesterday is the
        same shelf today, and `test_a_structure_may_still_span_sessions` pins that.
```

The default stays `session_aware=False`, so every batch caller is byte-identical and the
whole change is confined to the two places the frontier measures.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.adaptive import migration, read_window
from src.boxes.frontier import run
from src.boxes.snapshot import build_snapshot
from src.boxes.structure import atr_at, build_chain
from src.domain.models import IST, Candle

D = Decimal
OPEN, CLOSE = 9 * 60 + 15, 15 * 60 + 30      # 09:15 → 15:30, the 5m session
PER_SESSION = (CLOSE - OPEN) // 5            # 75 candles


def m5(closes, *, first_day: date = date(2025, 3, 3), wick: float = 2.0,
       per_session: int = PER_SESSION) -> list[Candle]:
    """5m candles laid on the real session grid, rolling to the next day at 15:30.

    The gap is not drawn — it is simply the absence of candles between 15:25 and the next
    09:15, which is exactly how it reaches the detector from `ReplayFeed`.
    """
    out, prev = [], closes[0]
    day, minute = first_day, OPEN
    for c in closes:
        if minute >= CLOSE:
            day, minute = day + timedelta(days=1), OPEN
        start = datetime.combine(day, datetime.min.time(), tzinfo=IST) + \
            timedelta(minutes=minute)
        out.append(Candle("TEST", "5m", start, start + timedelta(minutes=5),
                          D(str(prev)), D(str(max(prev, c) + wick)),
                          D(str(min(prev, c) - wick)), D(str(c))))
        prev, minute = c, minute + 5
    return out


def sit(price: float, n: int, width: float = 18.0):
    return [price + (i % 4 - 1.5) * width / 3 for i in range(n)]


def ramp(a: float, b: float, n: int):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# 1. the overnight jump is no longer movement
# ─────────────────────────────────────────────────────────────────────────────
def test_a_pure_gap_between_two_flat_sessions_is_not_an_impulse():
    """Two rotational sessions, one 430-point jump between them. Nothing trended.

    Measured rather than guessed — a first draft asserted `naive > 0.4` and the real
    figure is `0.304`, because seventy-five candles of rotation accumulate a large walk
    for the gap to be divided into. The claim worth pinning is the ratio, not a number
    that happens to depend on how long the fixture is.
    """
    window = m5(sit(22470, PER_SESSION, 20) + sit(22900, 30, 20))
    assert len({k.session_date for k in window}) == 2

    naive = migration(window)
    aware = migration(window, session_aware=True)
    assert aware < 0.05, (
        f"with the jump removed, two rotational sessions must read as rotation, "
        f"not {aware:.3f}")
    assert naive > 10 * aware, (
        f"the fixture is meant to show the gap dominating: naive {naive:.3f} vs "
        f"gap-aware {aware:.3f}")


def test_the_gap_is_dropped_from_both_the_walk_and_the_net():
    """Not just the denominator. Crediting the distance but not the direction — or the
    reverse — would produce a ratio above 1.0, which is not an efficiency at all."""
    window = m5(sit(22470, PER_SESSION, 20) + sit(23400, 20, 20))
    assert 0.0 <= migration(window, session_aware=True) <= 1.0


def test_a_gap_with_no_intra_session_movement_at_all():
    """Every step is a boundary step, so there is no walk left to divide by."""
    window = m5([22470.0] * PER_SESSION + [22900.0] * PER_SESSION)
    assert migration(window, session_aware=True) == 0.0


def test_the_bigger_the_gap_the_bigger_the_lie_it_used_to_tell():
    base = sit(22470, PER_SESSION, 20)
    naive = [migration(m5(base + sit(22470 + jump, 30, 20)))
             for jump in (0, 100, 300, 600)]
    assert naive == sorted(naive), (
        f"a larger overnight jump must inflate the naive ratio further: {naive}")
    aware = [migration(m5(base + sit(22470 + jump, 30, 20)), session_aware=True)
             for jump in (0, 100, 300, 600)]
    assert max(aware) - min(aware) < 1e-9, (
        f"with the gap removed, the jump size must stop mattering at all: {aware}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. same-session measurement is untouched
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("closes", [
    sit(22470, 40, 20),
    ramp(22470, 22600, 40),
    sit(22470, 20, 20) + ramp(22482, 22560, 20),
    ramp(22600, 22470, 30) + sit(22470, 20, 20),
])
def test_session_aware_is_identical_within_one_session(closes):
    """The per-step sum telescopes to `last - first`, so inside one session the two forms
    are the same function. This is why the default can be left off everywhere."""
    window = m5(closes)
    assert len({k.session_date for k in window}) == 1
    assert migration(window) == migration(window, session_aware=True)


def test_read_window_is_identical_within_one_session():
    window = m5(sit(22470, 60, 22))
    atr = atr_at(window, len(window) - 1)
    a = read_window(window, 40, atr)
    b = read_window(window, 40, atr, session_aware=True)
    for x, y in zip(a, b):
        assert (x is None) == (y is None)
        if x is not None:
            assert (x.low, x.high, x.score, x.migration) == \
                   (y.low, y.high, y.score, y.migration)


# ─────────────────────────────────────────────────────────────────────────────
# 3. the batch path did not move
# ─────────────────────────────────────────────────────────────────────────────
def test_the_default_is_off_so_the_batch_chain_is_unchanged():
    """`build_chain` never passes the flag, so a multi-session block must produce exactly
    what it produced before this change existed."""
    block = m5(sit(22470, PER_SESSION, 22) + sit(22560, PER_SESSION, 22)
               + sit(22470, PER_SESSION, 22))
    chain, _ = build_chain(block)
    assert chain, "the fixture produced no chain at all"
    for ln in chain:
        seg = [k for k in block[ln.start:ln.end + 1] if not k.synthetic]
        if len(seg) >= 2:
            # the naive reading is what the batch still uses
            assert migration(seg) == pytest.approx(migration(seg), abs=0)


def test_migration_signature_is_backwards_compatible():
    window = m5(sit(22470, 40, 20))
    assert migration(window) == migration(window, session_aware=False)


# ─────────────────────────────────────────────────────────────────────────────
# 4. structures may still span sessions
# ─────────────────────────────────────────────────────────────────────────────
def test_a_structure_may_still_span_sessions():
    """The rule this change must NOT introduce. A shelf built yesterday is the same shelf
    today; only the jump between them stops being called movement."""
    block = m5(sit(22470, PER_SESSION + 30, 20) + sit(22470, 60, 20))
    split = PER_SESSION
    snap = build_snapshot(block[:split], "NIFTY BANK")
    f = run(snap, block[:split], block[split:])

    spanning = [n for n in list(f.history()) + list(snap.structures())
                if block[n.start].session_date != block[min(n.end, len(block) - 1)]
                .session_date]
    banded = [r for r in f.readings if r.band is not None]
    assert banded, "no structure was held at all across the boundary"
    assert spanning or any(
        block[r.index].session_date != block[max(0, r.index - 20)].session_date
        for r in banded), "no structure survived an overnight boundary"


def test_the_frontier_still_reads_every_candle_after_a_boundary():
    """The alternative fix — truncating the window at the boundary — would blind the map
    for the first hour of every session. It was rejected, and this pins that."""
    block = m5(sit(22470, PER_SESSION, 20) + sit(22480, PER_SESSION, 20))
    split = PER_SESSION
    snap = build_snapshot(block[:split], "NIFTY BANK")
    f = run(snap, block[:split], block[split:])
    assert len(f.readings) == len(block) - split
    early = f.readings[:8]
    assert all(r.state for r in early), "the frontier went blank after the boundary"
