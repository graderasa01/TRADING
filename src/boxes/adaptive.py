"""
The adaptive scan — `CLUSTER-RANGE-MAP.md` §3-§6.

Stateless. Given the candles up to now, it answers one question at many window lengths:

    "Is there, in the last N candles, a cluster or a range that is already established?"

and then hands back the answer from the **smallest N that was already stable** — stable
meaning the next two larger windows found the same thing in the same place.

Nothing here remembers anything between calls. Freezing happens in `mapper.py`; this
module only ever proposes.

## The two things this module exists to keep apart

```
100 → 109 → 102 → 108 → 101 → 110      rotation   → a range
100 → 102 → 104 → 106 → 108 → 110      migration  → nothing at all
```

Both have the same high and the same low, so any detector built on extremes calls them the
same object. `traverses` and `migration` are the two measurements that separate them, and
they are the reason this design is not the previous three.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import accumulate
from typing import Sequence

from src.domain.models import ZERO, Candle

MIN_STEP = Decimal("0.05")

# Roughly geometric: each step is about 1.22x the last. Twelve lengths cover eight minutes
# to seventy-five with no gap wide enough for a structure to hide in.
WINDOWS: tuple[int, ...] = (8, 10, 12, 15, 18, 22, 27, 33, 40, 50, 60, 75)

STABILITY_RUN = 3          # the trader's "2-3 successive expansions"
MIN_TOUCHES = 2            # a boundary defended once is not a boundary
MIN_TRAVERSES = 2


@dataclass(frozen=True, slots=True)
class Proposal:
    """One window's answer. Not a box until `mapper.py` admits and freezes it."""

    kind: str                          # "cluster" | "range"
    low: Decimal
    high: Decimal
    window: int                        # candles it was found in
    score: float                       # mean(parts) - migration, in [-1, +1]
    migration: float
    parts: dict[str, float] = field(default_factory=dict)
    visits: int = 0
    upper_touches: int = 0
    lower_touches: int = 0
    traverses: int = 0
    upper_band: tuple[Decimal, Decimal] | None = None
    lower_band: tuple[Decimal, Decimal] | None = None

    @property
    def width(self) -> Decimal:
        return self.high - self.low

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2

    def agrees_with(self, other: "Proposal", tol: Decimal) -> bool:
        """Same kind, both edges within `tol`. This is the whole stability test."""
        return (self.kind == other.kind
                and abs(self.low - other.low) <= tol
                and abs(self.high - other.high) <= tol)


# ─────────────────────────────────────────────────────────────────────────────
# measurements — each one lands in 0..1 against a stated null
# ─────────────────────────────────────────────────────────────────────────────
def minutes_at_price(window: Sequence[Candle], lo: Decimal, step: Decimal,
                     buckets: int) -> list[float]:
    """Time-at-price. **Every candle contributes exactly 1.0**, spread over the buckets it
    covered.

    This is the one piece kept from the deleted heat map, and it was kept because it was
    measured rather than liked. Plain coverage — *how many candles span this price* — hands
    a 120-point candle twenty-four times the vote of a 5-point candle, so the "busiest"
    band comes back as the one where price was moving **fastest**. Exactly backwards, and
    it is the bug that sat under `map.py` and `engine.py` the whole time.
    """
    delta = [0.0] * (buckets + 1)
    top = buckets - 1
    for k in window:
        if k.synthetic:
            continue
        a = max(0, min(top, int((k.l - lo) / step)))
        b = max(0, min(top, int((k.h - lo) / step)))
        w = 1.0 / (b - a + 1)
        delta[a] += w
        delta[b + 1] -= w
    return [v if v > 0.0 else 0.0 for v in accumulate(delta[:-1])]


CORE_SHARE = 0.7


def core_band(window: Sequence[Candle], atr: Decimal,
              share: float = CORE_SHARE) -> tuple[Decimal, Decimal] | None:
    """The **tightest** contiguous band holding `share` of the window's minutes.

    Tightest, not densest-around-the-peak: the sliding window finds the narrowest band
    that reaches the quota, which is valid because minutes are never negative.

    ## Why 0.7 and not 0.5

    Half was the first choice and it drew boxes narrower than the consolidations they
    described. Price then closed outside its own cluster on the ordinary swing of the
    range it was resting in, and every box registered a break within a few candles of
    being born. The trader's own worked example makes the intended width plain:

        100  102  104  103  104  102  103  104  103  105   ->  "CLUSTER 102-105"

    That is nearly the whole stay, not its dense half. At 0.7 this window returns
    102-104, which is the same band to within tolerance; at 0.5 it returns 103-104, a
    two-point sliver inside a five-point rest.

    0.7 is also the market-profile value-area convention, so it is a stated convention
    rather than a number fitted to this repo's data.
    """
    real = [k for k in window if not k.synthetic]
    if not real:
        return None
    lo = min(k.l for k in real)
    hi = max(k.h for k in real)
    if hi <= lo:
        return None
    step = max(atr / 10, MIN_STEP) if atr > ZERO else MIN_STEP
    buckets = int((hi - lo) / step) + 1
    if buckets < 2:
        return None

    heat = minutes_at_price(real, lo, step, buckets)
    need = sum(heat) * share
    if need <= 0:
        return None

    # Among the narrowest bands that reach the quota, take the one holding the MOST
    # minutes. Keeping the first one found instead put the box off-centre: a symmetric
    # rest at 60,000 came back as 59,996-60,001 because that band tied on width and was
    # seen first. Price then closed above its own cluster on every ordinary upswing, and
    # the box registered a break within a few candles of being born.
    best: tuple[int, int, float] | None = None
    total = 0.0
    left = 0
    for right in range(buckets):
        total += heat[right]
        while total - heat[left] >= need and left < right:
            total -= heat[left]
            left += 1
        if total < need:
            continue
        width = right - left
        if best is None or (width, -total) < (best[1] - best[0], -best[2]):
            best = (left, right, total)
    if best is None:
        return None
    return lo + step * best[0], lo + step * (best[1] + 1)


def visits(window: Sequence[Candle], low: Decimal, high: Decimal, gap: int) -> int:
    """Separate stays inside a band. Sixty consecutive candles is one visit, not sixty."""
    hits = [i for i, k in enumerate(window)
            if not k.synthetic and k.l <= high and k.h >= low]
    if not hits:
        return 0
    return 1 + sum(1 for a, b in zip(hits, hits[1:]) if b - a > gap)


def touches(window: Sequence[Candle], price: Decimal, tol: Decimal, upper: bool,
            gap: int) -> tuple[int, tuple[Decimal, Decimal] | None]:
    """Distinct approaches to a boundary, plus the band the touch prices actually landed in.

    > *"agar repeated highs 109.8 / 110.1 / 110.0 / 109.7 hain to 109.7-110.1 ko merge
    > karke high zone banao"*

    So a boundary is a band, not a line, and its width is measured rather than assumed.
    Ten consecutive candles grinding the high are **one** touch — price has to leave by
    more than `tol` and come back for the second one to count.
    """
    at = [(i, k.h if upper else k.l) for i, k in enumerate(window)
          if not k.synthetic and ((k.h >= price - tol) if upper else (k.l <= price + tol))]
    if not at:
        return 0, None
    n = 1 + sum(1 for (a, _), (b, _) in zip(at, at[1:]) if b - a > gap)
    prices = [p for _, p in at]
    return n, (min(prices), max(prices))


def traverses(window: Sequence[Candle], low: Decimal, high: Decimal) -> int:
    """Full trips between the bottom third and the top third.

    The measurement that separates a range from a slow trend. Thirds rather than halves so
    that drifting around the middle never registers as rotation, and closes rather than
    wicks so that one spike cannot manufacture a traverse.
    """
    rng = high - low
    if rng <= ZERO:
        return 0
    lo_line = low + rng / 3
    hi_line = high - rng / 3
    state: str | None = None
    count = 0
    for k in window:
        if k.synthetic:
            continue
        if k.c <= lo_line:
            if state == "high":
                count += 1
            state = "low"
        elif k.c >= hi_line:
            if state == "low":
                count += 1
            state = "high"
    return count


def migration(window: Sequence[Candle], *, session_aware: bool = False) -> float:
    """Kaufman's efficiency ratio: `|net| / total walk`. 1.0 is a perfect staircase.

    No parameters, no units. This is the whole of the continuation penalty — the rule that
    stops a 100→110 walk from being drawn as a ten-point box.

    ## `session_aware` — the overnight jump is not movement

    `structure.split_moves_at_sessions()` already says it, for the batch chain:

    > *"The overnight jump itself is not market movement, so it must never be measured as
    > one: left inside a move, a 300-point gap reads as a perfect efficiency-ratio
    > impulse."*

    The batch scan acts on that by cutting **moves** at the boundary. Nothing was doing it
    for a **measurement window**, and on 5m that is nearly every window there is: a
    session is exactly 75 candles and `WINDOW_MAX` is 75, so **98.7% of live windows span
    a boundary.** Measured over 120 teach sessions, the gap inflates this ratio by a
    median of `+0.03`, `+0.13` at p90, and up to `+0.52`. Since `read_window` scores
    structures as `mean(parts) - migration`, that is a direct, silent penalty — one 1 Mar
    window whose real efficiency was `0.007`, pure rotation, was read as `0.526` and could
    not have produced a structure at any score.

    With `session_aware`, a step that crosses a session boundary is dropped from **both**
    the walk and the net: price is credited with neither the distance nor the direction of
    a move it never made. Within a single session the two forms are the same function —
    the per-step sum telescopes to `last - first` — so the default keeps every existing
    caller byte-identical, and `test_session_aware_is_identical_within_one_session` pins
    that rather than trusting it.
    """
    real = [k for k in window if not k.synthetic]
    if len(real) < 2:
        return 0.0
    steps = [b.c - a.c for a, b in zip(real, real[1:])
             if not (session_aware and a.session_date != b.session_date)]
    walk = sum(abs(s) for s in steps)
    if walk <= ZERO:
        return 0.0
    return float(abs(sum(steps)) / walk)


def compression(window: Sequence[Candle]) -> float:
    """`1 - range / Σ(candle ranges)`. How much ground price re-covered."""
    real = [k for k in window if not k.synthetic]
    if not real:
        return 0.0
    path = sum(k.h - k.l for k in real)
    if path <= ZERO:
        return 0.0
    rng = max(k.h for k in real) - min(k.l for k in real)
    return max(0.0, min(1.0, float(1 - rng / path)))


def rejection_rate(window: Sequence[Candle], price: Decimal, tol: Decimal,
                   upper: bool) -> tuple[int, int]:
    """`(rejected, reached)` at a boundary — wicks that got there, and how many of those
    closed back inside by more than `tol`.

    A **rate**, not a count. The count version — `min(1, rejections / 4)` — read exactly
    1.00 on every box of every session measured, because four rejections is nothing over a
    forty-candle window. A component that is constant is not a measurement, it is a
    constant being added to the score, and it was quietly inflating every box by 0.25.
    """
    reached = rejected = 0
    for k in window:
        if k.synthetic:
            continue
        if (k.h >= price - tol) if upper else (k.l <= price + tol):
            reached += 1
            if (k.c <= price - tol) if upper else (k.c >= price + tol):
                rejected += 1
    return rejected, reached


def overlap(a: tuple[Decimal, Decimal], b: tuple[Decimal, Decimal]) -> float:
    """Shared height as a fraction of the **narrower** band. 1.0 means one contains the
    other; 0.0 means they are disjoint."""
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    if hi <= lo:
        return 0.0
    thin = min(a[1] - a[0], b[1] - b[0])
    return 1.0 if thin <= ZERO else float((hi - lo) / thin)


# ─────────────────────────────────────────────────────────────────────────────
# the two detectors
# ─────────────────────────────────────────────────────────────────────────────
def read_window(candles: Sequence[Candle], n: int, atr: Decimal, *,
                tol_atr: Decimal = Decimal("0.25"),
                min_score: float = 0.35,
                session_aware: bool = False) -> tuple[Proposal | None, Proposal | None]:
    """`(cluster, range)` from the last `n` candles. Either may be `None`.

    `session_aware` is passed straight through to `migration` and changes nothing else.
    `compression` is deliberately left alone: it measures the window's **extent**, and a
    band that spans a session boundary really does cover that range — the prices on both
    sides are real. Only the *path* reading is corrupted by a gap, and that is `migration`.
    """
    window = [k for k in candles[-n:] if not k.synthetic]
    if len(window) < 5:
        return None, None

    tol = max(atr * tol_atr, MIN_STEP)
    gap = max(3, n // 6)
    lo = min(k.l for k in window)
    hi = max(k.h for k in window)
    mig = migration(window, session_aware=session_aware)
    comp = compression(window)

    # ── cluster ─────────────────────────────────────────────────────────────
    cluster: Proposal | None = None
    band = core_band(window, atr)
    if band is not None:
        c_low, c_high = band
        rng = hi - lo
        v = visits(window, c_low, c_high, gap)
        # Null-calibrated: a uniform window's `share`-of-minutes band is `share x range`
        # wide, so this is 0 for a window with no structure and approaches 1 as the rest
        # tightens — independent of what `share` was set to.
        occupancy = (max(0.0, float(1 - (c_high - c_low) / (Decimal(str(CORE_SHARE)) * rng)))
                     if rng > ZERO else 0.0)
        rej_u, reach_u = rejection_rate(window, c_high, tol, True)
        rej_d, reach_d = rejection_rate(window, c_low, tol, False)
        reach = reach_u + reach_d
        reaction = (rej_u + rej_d) / reach if reach else 0.0

        # Three components, not four.
        #
        # `revisit` was the fourth, and measured on real sessions it read **0.00 on every
        # box of every day** — necessarily so, because the core band is by construction
        # *where price sat during this window*, so price does not leave it and return
        # inside the window that defined it. Revisit is a fact about a box's later life,
        # not about the window that found it; it now lives on `Box.confirmations`.
        #
        # There is no hard gate on visits either. `visits >= 2` was here first and it
        # rejected the trader's own worked example —
        #
        #     100 102 104 103 104 102 103 104 103 105
        #
        # — where price never leaves the band, so that is one visit by the gap rule and the
        # clearest cluster in the whole specification scored zero. Continuous occupancy is
        # acceptance too.
        parts = {"occupancy": occupancy, "compression": comp, "reaction": reaction}
        score = sum(parts.values()) / len(parts) - mig
        if score >= min_score:
            cluster = Proposal("cluster", c_low, c_high, n, score, mig, parts, visits=v)

    # ── range ───────────────────────────────────────────────────────────────
    rng_prop: Proposal | None = None
    up_n, up_band = touches(window, hi, tol, True, gap)
    dn_n, dn_band = touches(window, lo, tol, False, gap)
    tr = traverses(window, lo, hi)
    if up_n >= MIN_TOUCHES and dn_n >= MIN_TOUCHES and tr >= MIN_TRAVERSES:
        parts = {"upper": min(1.0, (up_n - 1) / 2), "lower": min(1.0, (dn_n - 1) / 2),
                 "rotation": min(1.0, tr / 3), "compression": comp}
        score = sum(parts.values()) / len(parts) - mig
        if score >= min_score:
            rng_prop = Proposal("range", lo, hi, n, score, mig, parts,
                                upper_touches=up_n, lower_touches=dn_n, traverses=tr,
                                upper_band=up_band, lower_band=dn_band)

    return cluster, rng_prop


def choose(candles: Sequence[Candle], atr: Decimal, *,
           windows: Sequence[int] = WINDOWS,
           tol_atr: Decimal = Decimal("0.25"),
           min_score: float = 0.35,
           run: int = STABILITY_RUN,
           session_aware: bool = False) -> tuple[Proposal | None, Proposal | None]:
    """The smallest window whose answer the next `run - 1` windows also agree with.

    > *"window ko sirf 'cluster mila / nahi mila' se choose mat karna. jis smallest window
    > mein same cluster/range boundary 2-3 successive expansions tak stable rahe, wahi
    > active window choose karo."*

    This is what removes the window-length parameter. There is no correct `N` to guess: a
    walk never reproduces the same boundaries at three successive lengths, because each
    expansion adds more walk and moves the edges, so **a trend simply returns nothing**.
    """
    tol = max(atr * tol_atr, MIN_STEP)
    reads = [read_window(candles, n, atr, tol_atr=tol_atr, min_score=min_score,
                         session_aware=session_aware)
             for n in windows]

    out: list[Proposal | None] = []
    for slot in (0, 1):
        found: Proposal | None = None
        for i in range(len(reads) - run + 1):
            seq = [reads[i + j][slot] for j in range(run)]
            if all(p is not None for p in seq) and all(
                    p.agrees_with(seq[0], tol) for p in seq[1:]):    # type: ignore[union-attr]
                found = seq[0]
                break
        out.append(found)
    return out[0], out[1]


__all__ = ["WINDOWS", "STABILITY_RUN", "MIN_TOUCHES", "MIN_TRAVERSES", "Proposal",
           "minutes_at_price", "core_band", "visits", "touches", "traverses",
           "migration", "compression", "rejections", "read_window", "choose"]
