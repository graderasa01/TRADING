"""
The four ways a level is born — spec 03 §1.

> A level is not a line. A level is a **record of where an order imbalance happened.**
> There are exactly four ways one comes into existence. If a line cannot be traced to
> one of them, it does not go on the chart.

Each detector is a pure function over candles. They return *candidates*; the engine
owns identity, merging, grading and death, because those are questions about the book
rather than about the shape.

## LAUNCH is the one that matters and the one that barely fires

Spec 03 §3 calls it "the highest-value 1m level" — the level invisible on 5m because it
lives inside a 5m candle's body. The dry run produced exactly **one** in a full session
(`prototype/FINDINGS.md`, Bug 5) while producing 36 TURNs. If that ratio survives on
real data it is worth knowing early, which is why `LaunchCandidate` carries the reason
it failed rather than returning `None`: a detector that says "no" without saying why
cannot be calibrated in P1.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from src.domain.models import ZERO, Candle, LevelKind, LevelSide
from src.indicators.swings import Pivot


@dataclass(frozen=True, slots=True)
class Candidate:
    """A level the engine may create. Not yet identity, not yet graded."""
    kind: LevelKind
    side: LevelSide
    body_edge: Decimal
    wick_tip: Decimal
    born_index: int                  # index into the 1m stream
    born_tf: str
    evidence: dict[str, object] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# TURN — 2a. swing pivot
# ─────────────────────────────────────────────────────────────────────────────
def turn_from_pivot(pivot: Pivot, index_1m: int) -> Candidate:
    """Spec 03 §2a geometry: `body_edge` is the body extreme of the pivot candle,
    `wick_tip` is its high (for a high) or low (for a low).

    The distinction is the whole of spec 03 §4: entry references `body_edge` because
    that is where the decision was made; the stop goes beyond `wick_tip` because that is
    where the stops already sit.
    """
    k = pivot.candle
    if pivot.is_high:
        return Candidate(LevelKind.TURN, LevelSide.RESISTANCE,
                         body_edge=k.body_top, wick_tip=k.h,
                         born_index=index_1m, born_tf=pivot.swing.tf,
                         evidence={"source": "swing_pivot", "pivot_index": pivot.index})
    return Candidate(LevelKind.TURN, LevelSide.SUPPORT,
                     body_edge=k.body_bottom, wick_tip=k.l,
                     born_index=index_1m, born_tf=pivot.swing.tf,
                     evidence={"source": "swing_pivot", "pivot_index": pivot.index})


# ─────────────────────────────────────────────────────────────────────────────
# TURN — 2b. wick cluster
# ─────────────────────────────────────────────────────────────────────────────
def find_wick_clusters(candles: list[Candle], end_index: int, *,
                       min_touches: int, tolerance: Decimal,
                       window: int) -> list[Candidate]:
    """>= `min_touches` wick tips within `tolerance` of each other, inside `window`
    candles (spec 03 §2b).

    Only clusters ENDING at `end_index` are returned — the cluster is news on the candle
    that completes it, and re-emitting every historical cluster on every candle would
    make the book churn. Spec 09 §3.2b warns that this rule alone "can produce 8
    candidate clusters where a human would draw 2", so the engine's dedup and the
    8-level cap are what make it usable, not the detector.
    """
    if end_index < min_touches - 1 or tolerance <= ZERO:
        return []
    start = max(0, end_index - window + 1)
    scope = [(i, candles[i]) for i in range(start, end_index + 1) if not candles[i].synthetic]
    if len(scope) < min_touches:
        return []

    last = candles[end_index]
    if last.synthetic:
        return []

    out: list[Candidate] = []
    for side in ("high", "low"):
        # Spec 03 §2b says "wicks whose TIPS fall within tolerance" — a wick, not an
        # extreme. A candle that closed at its high has no upper wick and therefore no
        # rejection at that price; counting it turns "price was refused here twice" into
        # "price reached here twice", which is a different and much weaker claim.
        # 9.6% of Bank Nifty 1m candles have no upper wick, 7.8% no lower.
        def tip(k: Candle) -> Decimal:
            return k.h if side == "high" else k.l

        def has_wick(k: Candle) -> bool:
            return (k.upper_wick if side == "high" else k.lower_wick) > ZERO

        if not has_wick(last):
            continue
        anchor = tip(last)
        members = [(i, k) for i, k in scope
                   if has_wick(k) and abs(tip(k) - anchor) <= tolerance]
        if len(members) < min_touches:
            continue
        tips = [tip(k) for _, k in members]
        bodies = [k.body_top if side == "high" else k.body_bottom for _, k in members]
        out.append(Candidate(
            LevelKind.TURN,
            LevelSide.RESISTANCE if side == "high" else LevelSide.SUPPORT,
            body_edge=sum(bodies) / len(bodies),           # mean of body extremes
            wick_tip=max(tips) if side == "high" else min(tips),
            born_index=end_index, born_tf="1m",
            evidence={"source": "wick_cluster", "touches": len(members),
                      "member_indices": [i for i, _ in members]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# LAUNCH — §3
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class LaunchAttempt:
    """Why a launch did or did not form. The rejection reasons feed P1.5's near-miss
    diagnosis (spec 12 §5 step 2), which is the most valuable output of that loop:
    'missed by 0.15 x ATR' is a threshold change, 'no detector was close' is not."""
    candidate: Candidate | None
    reason: str
    measured: dict[str, object] = field(default_factory=dict)


def detect_launch(candles: list[Candle], impulse_index: int, atr20: Decimal, *,
                  impulse_atr_mult: Decimal, base_atr_mult: Decimal,
                  base_min: int, base_max: int) -> LaunchAttempt:
    """Spec 03 §3. `impulse_index` is the candle being tested as the impulse.

    Departure speed is NOT checked here — it is only knowable
    `departure_lookahead_candles` later, and the engine resolves it then (spec 03 §3:
    "the level simply does not exist until candle born_i + n closes").
    """
    if atr20 is None or atr20 <= ZERO:
        return LaunchAttempt(None, "no_atr")
    impulse = candles[impulse_index]
    if impulse.synthetic:
        return LaunchAttempt(None, "synthetic_impulse")

    need = impulse_atr_mult * atr20
    if impulse.range < need:
        return LaunchAttempt(None, "impulse_too_small",
                             {"range": impulse.range, "required": need,
                              "shortfall_atr": (need - impulse.range) / atr20})

    third = impulse.close_third
    if third == "mid":
        return LaunchAttempt(None, "impulse_not_decisive", {"close_position": impulse.close_position})
    direction: Literal["up", "down"] = "up" if third == "top" else "down"

    # The base is the LARGEST n in [base_min, base_max] that stays quiet enough.
    best_n = None
    combined_at: dict[int, Decimal] = {}
    for n in range(base_min, base_max + 1):
        lo_i = impulse_index - n
        if lo_i < 0:
            break
        base = candles[lo_i:impulse_index]
        if any(k.synthetic for k in base):
            continue
        combined = max(k.h for k in base) - min(k.l for k in base)
        combined_at[n] = combined
        if combined <= base_atr_mult * atr20:
            best_n = n
    if best_n is None:
        tightest = min(combined_at.values()) if combined_at else None
        return LaunchAttempt(None, "no_quiet_base",
                             {"combined_by_n": combined_at,
                              "allowed": base_atr_mult * atr20,
                              "shortfall_atr": None if tightest is None
                              else (tightest - base_atr_mult * atr20) / atr20})

    base = candles[impulse_index - best_n:impulse_index]
    if direction == "up":
        cand = Candidate(LevelKind.LAUNCH, LevelSide.SUPPORT,
                         body_edge=max(k.body_bottom for k in base),   # top of accumulation
                         wick_tip=min(k.l for k in base),
                         born_index=impulse_index, born_tf="1m",
                         evidence={"source": "launch", "direction": "up",
                                   "base_candles": best_n,
                                   "impulse_range": impulse.range})
    else:
        cand = Candidate(LevelKind.LAUNCH, LevelSide.RESISTANCE,
                         body_edge=min(k.body_top for k in base),
                         wick_tip=max(k.h for k in base),
                         born_index=impulse_index, born_tf="1m",
                         evidence={"source": "launch", "direction": "down",
                                   "base_candles": best_n,
                                   "impulse_range": impulse.range})
    return LaunchAttempt(cand, "ok", {"base_candles": best_n,
                                      "combined_range": combined_at[best_n]})


# ─────────────────────────────────────────────────────────────────────────────
# ANCHOR — §6
# ─────────────────────────────────────────────────────────────────────────────
def round_numbers(low: Decimal, high: Decimal, grid: int) -> list[Decimal]:
    """Every multiple of `grid` inside [low, high]."""
    if grid <= 0 or high < low:
        return []
    g = Decimal(grid)
    first = (low / g).to_integral_value(rounding="ROUND_CEILING") * g
    out, p = [], first
    while p <= high:
        out.append(p)
        p += g
    return out
