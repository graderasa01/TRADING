"""
The live frontier — `src/boxes/frontier.py`.

The Bank Nifty walkthrough is the first test and it exists to pin one thing above all
others: **a `22460-22480` cluster breaks above `22480`.** An earlier draft of the plan
said `22500` — the next structural reference — and that confusion is the reason this
fixture is written in real Bank Nifty numbers rather than in `100 → 110`.

```
BREAK_LEVEL_UP    = the current structure's OWN high
NEXT reference    = somewhere else entirely, and never a breakout point
```
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.boxes.frontier import (
    CLOSED, CONFIRMED, LEAVING, MOVING, STRUCTURE_CANDIDATE, Frontier, run)
from src.boxes.adaptive import overlap
from src.boxes.snapshot import SAME_NODE_OVERLAP, build_snapshot
from src.domain.models import IST, Candle

SPLIT = 90          # candles handed to the snapshot before the frontier starts


def make(spec, day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(
        hour=9, minute=15)
    return [Candle("TEST", "1m", start + timedelta(minutes=i),
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


def frontier_for(closes) -> Frontier:
    candles = make(path(closes))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    return run(snap, candles[:SPLIT], candles[SPLIT:])


def interactions(f: Frontier) -> list[str]:
    return [r.interaction for r in f.readings]


def states(f: Frontier) -> list[str]:
    return [r.state for r in f.readings]


# ─────────────────────────────────────────────────────────────────────────────
# the Bank Nifty walkthrough
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def banknifty() -> Frontier:
    """22460-22480 cluster, break above its OWN edge, travel, new shelf at 22560, and
    that shelf broken through its own edge in turn.

    The opening cluster is already inside the snapshot, so the frontier **adopts** it
    rather than minting a duplicate — that is the point of the RC2/RC3 fix. The 22560
    shelf is genuinely new, so it is the one that gets minted and finalised.
    """
    return frontier_for(
        sit(22470, SPLIT + 30, width=20)          # the 22460-22480 cluster, in M001
        + ramp(22482, 22550, 25)                  # leaving, travelling
        + sit(22560, 45, width=8)                 # a NEW shelf at the next reference
        + ramp(22572, 22650, 22))                 # and out through ITS own edge


def test_break_level_is_the_structures_own_edge(banknifty):
    """The whole point. 22480 is the break level; 22560 is a reference, not a boundary."""
    confirmed = [r for r in banknifty.readings if r.break_level_up is not None]
    assert confirmed, "the cluster must be confirmed at some point"
    first = confirmed[0]
    assert 22470 <= float(first.break_level_up) <= 22495, (
        f"break level up is {float(first.break_level_up):,.0f}; it must be the "
        f"cluster's own high near 22480, never the next reference at 22560")
    assert 22450 <= float(first.break_level_down) <= 22475


def test_the_sequence_is_visible_candle_by_candle(banknifty):
    """Not just a final CONFIRMED — the lifecycle has to be readable as it happens.

    The assertion is on the *departure* ordering, not on a total order of first
    appearances. `BREAK_ATTEMPT_UP` legitimately precedes the first `INSIDE`: a cluster's
    band is `core_band`, a 70% value area, so the ordinary oscillation that defines the
    shelf pokes past its own edge from the start. Demanding otherwise would be asserting
    that a value area is an envelope, which is the mistake `extend_back` already had to
    unlearn.
    """
    seen = interactions(banknifty)
    for want in ("INSIDE", "BREAK_ATTEMPT_UP", "ACCEPTED_ABOVE", "LEAVING"):
        assert want in seen, f"{want} never appeared in {sorted(set(seen))}"

    accepted = seen.index("ACCEPTED_ABOVE")
    assert seen.index("INSIDE") < accepted, "stood in the shelf only after leaving it"
    assert seen.index("BREAK_ATTEMPT_UP") < accepted, "accepted before attempting"
    assert seen.index("LEAVING") > accepted, "left before the break was accepted"
    assert "NEW_CLUSTER" in seen, (
        f"the 22560 shelf is genuinely new and must be minted: {sorted(set(seen))}")


def test_a_close_past_the_edge_is_an_attempt_not_an_approach():
    """`break_closes` may delay ACCEPTANCE. It must never delay the ATTEMPT.

    The first version tested containment with the tolerance skirt, so a close inside the
    skirt still read as sitting at the edge. On 2026-02-16:

        c807   price 60,511.8   C08 = 60,462-60,507   ->  AT_UPPER_EDGE

    Price was four points **above** the boundary and the map said it was approaching it.
    """
    f = frontier_for(sit(22470, SPLIT + 30, width=20) + ramp(22484, 22530, 14))
    for r in f.readings:
        if r.band is None:
            continue
        low, high = r.band
        close = f.candles[r.index].c
        if close > high:
            assert r.interaction in {"BREAK_ATTEMPT_UP", "ACCEPTED_ABOVE"}, (
                f"c{r.index}: close {float(close):,.1f} is above the edge "
                f"{float(high):,.1f} but the map says {r.interaction}")
        elif close < low:
            assert r.interaction in {"BREAK_ATTEMPT_DOWN", "ACCEPTED_BELOW"}, (
                f"c{r.index}: close {float(close):,.1f} is below the edge "
                f"{float(low):,.1f} but the map says {r.interaction}")


def test_acceptance_needs_two_closes_not_one(banknifty):
    """`break_closes = 2` — the repo's existing structural constant. One wick is not a
    break, and no new threshold is invented for acceptance."""
    seen = interactions(banknifty)
    first_attempt = seen.index("BREAK_ATTEMPT_UP")
    first_accept = seen.index("ACCEPTED_ABOVE")
    assert first_accept > first_attempt, "accepted before it even attempted"


def test_the_broken_structure_survives_as_history(banknifty):
    """The opening cluster is `M001`'s, so its break is recorded against `M001`'s node
    rather than minting a copy. The 22560 shelf is new, so that one is finalised."""
    breaks = banknifty.log.of_kind("break")
    assert breaks, "the break of the frozen cluster must reach the live log"
    assert breaks[0].direction == "up"

    assert banknifty.finalised, "the NEW shelf at 22560 must survive as history"
    fresh = banknifty.finalised[-1]
    assert 22530 <= float(fresh.low) and float(fresh.high) <= 22600
    assert fresh.provisional is False


def test_a_new_shelf_forms_at_the_next_reference(banknifty):
    """22560 is where a NEW structure may form, with its OWN edges."""
    later = [r for r in banknifty.readings[-30:] if r.band is not None]
    assert later, "nothing formed at 22560"
    low, high = later[-1].band
    assert 22530 <= float(low) and float(high) <= 22600, (
        f"new shelf came back as {float(low):,.0f}-{float(high):,.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# refusal 1 — a walk is not twenty boxes
# ─────────────────────────────────────────────────────────────────────────────
def test_leaving_is_a_state_not_a_box_per_candle():
    f = frontier_for(sit(22470, SPLIT + 20, width=20) + ramp(22482, 22620, 60))
    assert LEAVING in states(f) or MOVING in states(f)
    born = {r.node_id for r in f.readings[-55:] if r.node_id}
    assert len(born) <= 1, f"a one-way walk minted {len(born)} structures: {born}"


def test_a_staircase_confirms_nothing():
    f = frontier_for(sit(22470, SPLIT, width=20) + ramp(22480, 22900, 70))
    tail = states(f)[-60:]
    assert CONFIRMED not in tail, "a one-way walk must not confirm a structure"


# ─────────────────────────────────────────────────────────────────────────────
# refusal 2 — the shelf just left cannot be reborn
# ─────────────────────────────────────────────────────────────────────────────
def test_the_shelf_just_left_is_not_reborn_as_a_new_one():
    """Price leaves 22470, pokes out, comes back. That is a revisit, not a birth."""
    f = frontier_for(sit(22470, SPLIT + 20, width=20)
                     + ramp(22482, 22496, 6)
                     + sit(22472, 40, width=20))
    ids = [r.node_id for r in f.readings if r.node_id]
    assert len(set(ids)) <= 2, f"the same shelf was minted repeatedly: {set(ids)}"


def test_a_return_is_a_revisit_not_a_new_structure():
    """The RC2 fix. Measured against the batch over five sessions, 11 of 37 finalised
    live nodes were a shelf the frontier had already finalised, re-minted under a new
    id — one shelf reported as four."""
    f = frontier_for(sit(22470, SPLIT + 20, width=20)
                     + ramp(22482, 22560, 20)
                     + sit(22470, 45, width=20))
    seen = interactions(f)
    assert "REVISIT" in seen, (
        f"coming back to a known shelf must be a revisit: {sorted(set(seen))}")

    minted = [r.node_id for r in f.readings if r.node_id and r.node_id.startswith("L")]
    zones = {(round(float(n.low) / 50), round(float(n.high) / 50))
             for n in f.history()}
    assert len(zones) == len(f.history()), (
        f"two finalised nodes describe the same shelf: {[n.id for n in f.history()]}")
    assert len(set(minted)) <= 2, f"minted too many structures: {set(minted)}"


def test_the_two_integrity_invariants_hold_on_every_shape():
    """Level 1, locked. Measured against the batch over five real sessions these were
    **11 of 37** and **3 of 37** before the fix; they are now zero and must stay zero.

        duplicate re-mint       a shelf finalised twice under two ids
        frozen-overlap reclaim  a live node claiming territory `M001` already describes

    Both are wrong on the live map's own terms, whatever the batch says.
    """
    shapes = {
        "rest-break-rest": sit(22470, SPLIT + 20, 20) + ramp(22482, 22560, 20)
                           + sit(22570, 40, 10),
        "there and back": sit(22470, SPLIT + 20, 20) + ramp(22482, 22560, 20)
                          + sit(22470, 40, 20),
        "double return": sit(22470, SPLIT, 20) + ramp(22482, 22540, 12)
                         + sit(22470, 25, 20) + ramp(22482, 22540, 12)
                         + sit(22470, 25, 20),
        "one-way walk": sit(22470, SPLIT, 20) + ramp(22482, 22900, 60),
        # ── the four above finalise NOTHING. Measured, not assumed: every one of them
        # ends with its structures either adopted from `M001` or still standing, so
        # `f.history()` is empty and both loops below used to iterate zero times. The
        # invariants were asserted against nothing at all. These three exist so the
        # assertions actually run.
        "two new shelves": sit(22470, SPLIT + 20, 20) + ramp(22482, 22550, 18)
                           + sit(22560, 40, 10) + ramp(22572, 22650, 18)
                           + sit(22660, 40, 10) + ramp(22672, 22740, 18),
        "three new shelves": sit(22470, SPLIT + 15, 20) + ramp(22482, 22550, 14)
                             + sit(22560, 32, 10) + ramp(22572, 22640, 14)
                             + sit(22650, 32, 10) + ramp(22662, 22730, 14)
                             + sit(22740, 32, 10) + ramp(22752, 22820, 14),
        # A live node whose SPAN reaches back into the frozen map's territory — the only
        # way the reclaim loop's `if node.end < fz.start ...: continue` guard is passed.
        # `extend_back` walks L01 to c1 while `M001`'s cluster owns c0-89. The bands
        # share 0.48 of the narrower one: a genuine near-miss against the 0.5 line, which
        # is exactly the RC3 shape and makes this a tripwire rather than a formality.
        "adjacent to frozen": sit(22470, SPLIT, 44) + sit(22492, 40, 8)
                              + ramp(22500, 22580, 18),
        "clear of frozen": sit(22470, SPLIT, 44) + sit(22500, 40, 8)
                           + ramp(22508, 22580, 18),
    }
    dup_pairs = reclaim_pairs = finalised = 0
    for name, closes in shapes.items():
        candles = make(path(closes))
        snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
        f = run(snap, candles[:SPLIT], candles[SPLIT:])
        hist = list(f.history())
        finalised += len(hist)

        for i, node in enumerate(hist):
            for earlier in hist[:i]:
                dup_pairs += 1
                share = overlap((node.low, node.high), (earlier.low, earlier.high))
                assert share < SAME_NODE_OVERLAP, (
                    f"{name}: {node.id} re-mints {earlier.id} (overlap {share:.2f})")

        for node in hist:
            for fz in snap.structures():
                if node.end < fz.start or node.start > fz.end:
                    continue
                reclaim_pairs += 1
                share = overlap((node.low, node.high), (fz.low, fz.high))
                assert share < SAME_NODE_OVERLAP, (
                    f"{name}: {node.id} reclaims frozen {fz.id} "
                    f"(overlap {share:.2f})")

    # ── the assertions above are worthless if they never execute ─────────────
    assert finalised >= 5, (
        f"only {finalised} nodes were ever finalised across every shape; the invariants "
        f"below are being asserted against almost nothing")
    assert dup_pairs > 0, (
        "no two finalised nodes were ever compared — the duplicate-re-mint invariant "
        "did not run")
    assert reclaim_pairs > 0, (
        "no finalised node's span ever overlapped a frozen node's — the frozen-reclaim "
        "invariant did not run")


def test_frozen_territory_is_not_reclaimed():
    """RC3. `extend_back` walks backward from where a structure was detected and has no
    idea where `M001` ends, so a live node's span could land inside a shelf the frozen map
    already describes — measured at 3 of 37 before the fix.

    A proposal landing on frozen territory is `M001`'s node seen again, so there is
    nothing to clamp and nothing to reclaim.
    """
    candles = make(path(sit(22470, SPLIT + 40, width=20) + ramp(22482, 22600, 30)))
    snap = build_snapshot(candles[:SPLIT], "NIFTY BANK")
    f = run(snap, candles[:SPLIT], candles[SPLIT:])

    frozen_ids = {n.id for n in snap.structures()}
    for node in f.history():
        assert node.id not in frozen_ids, f"{node.id} duplicates a frozen node"
        for fz in snap.structures():
            if node.end < fz.start or node.start > fz.end:
                continue
            share = overlap((node.low, node.high), (fz.low, fz.high))
            assert share < SAME_NODE_OVERLAP, (
                f"{node.id} c{node.start}-{node.end} reclaims frozen {fz.id} "
                f"c{fz.start}-{fz.end} (overlap {share:.2f})")


def test_a_distant_new_structure_is_allowed_immediately():
    """The guard is band overlap, NOT a banned transition. A genuinely different shelf
    must be free to form as soon as it exists."""
    f = frontier_for(sit(22470, SPLIT + 20, width=20)
                     + ramp(22482, 22700, 30)
                     + sit(22710, 45, width=10))
    bands = [r.band for r in f.readings[-25:] if r.band]
    assert bands, "a distant new shelf was blocked from forming"
    assert float(bands[-1][0]) > 22600, (
        f"the new shelf came back at {float(bands[-1][0]):,.0f}, not near 22710")


def test_overlap_guard_uses_the_shared_threshold():
    """Same constant `mapper.py` uses to decide a proposal is a box it has seen."""
    assert SAME_NODE_OVERLAP == 0.5


# ─────────────────────────────────────────────────────────────────────────────
# refusal 3 — a band is not a location
# ─────────────────────────────────────────────────────────────────────────────
def test_a_band_price_has_left_is_not_current():
    """The real bug: at candle 443 price traded at 60,380-60,409 while the detector
    correctly returned a shelf at 60,271-60,309 that price had left eight candles back."""
    f = frontier_for(sit(22470, SPLIT + 40, width=20) + ramp(22485, 22900, 40))
    tail = f.readings[-25:]
    for r in tail:
        if r.band is not None:
            low, high = r.band
            close = f.candles[len(f.candles) - len(f.readings) + f.readings.index(r)].c
            assert low - 200 <= close <= high + 200, (
                f"c{r.index}: reported band {float(low):,.0f}-{float(high):,.0f} "
                f"while price was at {float(close):,.0f}")


def test_currency_slack_is_one_candle():
    from src.boxes.frontier import CURRENCY_SLACK
    assert CURRENCY_SLACK == 1


# ─────────────────────────────────────────────────────────────────────────────
# live and frozen objects are never the same instance
# ─────────────────────────────────────────────────────────────────────────────
def test_finalise_constructs_a_new_object(banknifty):
    """Law 3. Sharing one instance would make the immutable snapshot mutable through a
    back door."""
    frozen = banknifty.finalised[-1]
    live_ids = {id(n) for n in [banknifty.current] if n is not None}
    assert id(frozen) not in live_ids
    assert type(frozen).__name__ == "Node"


def test_the_snapshot_never_moves(banknifty):
    import dataclasses
    before = dataclasses.astuple(banknifty.snapshot)
    assert dataclasses.astuple(banknifty.snapshot) == before


def test_provisional_stage_actually_happens():
    """`choose()` needs three successive windows to concur, so a shelf is visible as a
    candidate before it is confirmed. If PROVISIONAL never appears it is a formality."""
    f = frontier_for(sit(22470, SPLIT, width=20)
                     + ramp(22482, 22600, 20)
                     + sit(22610, 50, width=10))
    assert STRUCTURE_CANDIDATE in states(f), (
        f"never provisional, went straight to confirmed: {sorted(set(states(f)))}")


def test_status_of_a_broken_node_is_closed(banknifty):
    """`LiveNode.live_status` is the node's OWN lifecycle — `CONFIRMED` while it is being
    stood in, `CLOSED` once price has left through an edge.

    This used to read `left.status == HISTORICAL`, sharing its words with
    `Reading.node_status`, which answers an entirely different question: *should the map
    present this as something history already knew, or as something the frontier just
    built?* One field, two meanings, and the interpreter was told `PROVISIONAL` about
    nodes the frontier considered confirmed.
    """
    assert banknifty.left is None or banknifty.left.live_status == CLOSED
