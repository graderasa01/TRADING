"""
The vocabulary — every question this engine can ask about a candle, a group, or a
relation between them, and which of those questions anything actually acts on.

## The question this module exists to answer

> *"Code me koi logic hai bhi ya nahi? Kis tarike se pata karta hai? Aisa koi algorithm
> hai, agar hai to kis type ka?"*

Answering that from memory is worthless — memory rots the moment a detector changes. So
every entry here carries the callable that computes it, the config keys a detector for it
**owns**, and the source it lives in. Status is then *derived*, never asserted:

| status | meaning | what to do about it |
|---|---|---|
| `ACTED_ON` | measured, and a live params key drives a detector | tune it, don't rebuild it |
| `BLIND_SPOT` | measured, nothing consumes it | a new detector is justified |
| `NOT_BUILT` | not measured, but this feed could support it | code exists to be written |
| `UNOBSERVABLE` | **this feed cannot express it, ever** | stop. Building is not an option. |

`record.py` already derives blind spots this way for its five probes (spec 13 §2.1:
*"naya detector banao, wo line list se apne aap hat jaayegi"*). This extends the same
mechanism to the whole vocabulary, and adds the fourth row — which did not exist and
which turned out to matter.

## The fourth row, and why it was added

`record.py` lists `volume_spike` as a blind spot with the admission *"mere paas koi
volume rule nahi hai"* — which reads as *"so go build one."* That is wrong, and it is
wrong in the direction that costs the most: it invites work that cannot succeed.

Measured across every downloaded file, all four instruments, 1,120,535 one-minute
candles:

```
non-zero volume rows: 0
```

Bank Nifty is an **index**, not a traded instrument. It has no volume, no bid, no ask,
no order flow, and it never will on this feed. Any intuition that rests on absorption,
on a volume climax, on who is lifting the offer, is not a missing detector — it is
outside what these candles can say. `test_unobservable_are_actually_unobservable` re-runs
that count against the real data so the claim cannot quietly become false.

Being told "this cannot be built" in an hour is worth more than discovering it in a
month.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Literal, Sequence

from src.config.loader import Config
from src.domain.models import ZERO, Candle

Status = Literal["ACTED_ON", "PLANNED", "BLIND_SPOT", "NOT_BUILT", "UNOBSERVABLE"]
Family = Literal["candle", "span", "relation", "context"]

_SRC = Path(__file__).resolve().parent.parent


def _keys_read_in_src() -> frozenset[str]:
    """Which config keys does `src/` actually read?

    Not as simple as grepping the dotted key. `levels/engine.py` reads its own section
    through a prefix helper — `self._p("round_number_grid")` — so the dotted form appears
    nowhere. Both spellings are therefore searched: the full key and its final segment.

    Heuristic, and stated as one. It can produce a false ACTED_ON if a suffix collides
    with an unrelated string literal; it cannot silently produce a false BLIND_SPOT,
    which is the direction that would invite building something that already exists.
    """
    found: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if path.name == "vocabulary.py":
            continue                    # this file names every key; it would match all
        text = path.read_text(encoding="utf-8", errors="replace")
        for capability in CAPABILITIES:
            for key in capability.params:
                last = key.rsplit(".", 1)[-1]
                parts = last.split("_")
                # the third form catches an f-string: `self._p(f"swing_lookback_bars_{tf}")`
                if (f'"{key}"' in text or f'"{last}"' in text
                        or any(f'"{"_".join(parts[:i])}_' in text
                               for i in range(1, len(parts)))):
                    found.add(key)
    return frozenset(found)


_KEYS_READ: frozenset[str] | None = None


def keys_read_in_src() -> frozenset[str]:
    global _KEYS_READ
    if _KEYS_READ is None:
        _KEYS_READ = _keys_read_in_src()
    return _KEYS_READ


@dataclass
class Span:
    """The candles a claim is about. One candle is a span of length 1 — the trader says
    *"is candle par"* and *"in candles me"* with the same breath, so the code should not
    make them different kinds of thing."""
    candles: Sequence[Candle]
    lo: int
    hi: int
    atr: Decimal | None = None

    def __post_init__(self) -> None:
        self.lo = max(0, min(self.lo, len(self.candles) - 1))
        self.hi = max(self.lo, min(self.hi, len(self.candles) - 1))

    @property
    def members(self) -> list[Candle]:
        return list(self.candles[self.lo:self.hi + 1])

    @property
    def first(self) -> Candle:
        return self.candles[self.lo]

    @property
    def last(self) -> Candle:
        return self.candles[self.hi]

    def before(self, n: int) -> list[Candle]:
        return list(self.candles[max(0, self.lo - n):self.lo])

    def after(self, n: int) -> list[Candle]:
        return list(self.candles[self.hi + 1:min(len(self.candles), self.hi + 1 + n)])

    @property
    def high(self) -> Decimal:
        return max(k.h for k in self.members)

    @property
    def low(self) -> Decimal:
        return min(k.l for k in self.members)


@dataclass(frozen=True)
class Capability:
    name: str
    question: str                       # in plain words, as a trader would ask it
    family: Family
    algorithm: str                      # what KIND of computation this is
    params: tuple[str, ...]             # config keys a detector for this owns
    source: str                         # where it is computed
    fn: Callable[[Span], Decimal | None] | None = None
    consumed_at: tuple[str, ...] = ()   # "path::token" — direct use with no config key

    def status(self, cfg: Config) -> Status:
        """Derived, never asserted — the same discipline spec 13 §2.1 applies to blind
        spots. Five answers, and the difference between the middle two is the one that
        saves time: `PLANNED` means the number is already written down and the detector
        is not built; `BLIND_SPOT` means nobody has even decided what to call it."""
        if self.fn is None:
            return "NOT_BUILT"
        if self.consumed_at:
            return "ACTED_ON"
        present = [k for k in self.params if cfg.get(k, None) is not None]
        if not present:
            return "BLIND_SPOT"
        read = keys_read_in_src()
        return "ACTED_ON" if any(k in read for k in present) else "PLANNED"


@dataclass(frozen=True)
class Unobservable:
    name: str
    question: str
    why: str
    evidence: str


# ─────────────────────────────────────────────────────────────────────────────
# what this feed physically cannot say. Not a backlog — a boundary.
# ─────────────────────────────────────────────────────────────────────────────
UNOBSERVABLE: tuple[Unobservable, ...] = (
    Unobservable(
        "volume", "kitna volume tha yahan?",
        "NIFTY BANK is an index. Kite reports volume 0 on every index candle.",
        "1,120,535 candles across 4 instruments: 0 with non-zero volume "
        "(tests/test_p15_hypothesis.py::test_unobservable_are_actually_unobservable)"),
    Unobservable(
        "absorption", "yahan bade orders absorb ho rahe the?",
        "Absorption is volume traded against price that did not move. With no volume, "
        "the two candles 'heavy absorption' and 'nobody traded' are byte-identical.",
        "follows from volume"),
    Unobservable(
        "order_flow", "buyers aggressive the ya sellers?",
        "Requires trade-side tagging or bid/ask. The 1m OHLC feed carries neither. A "
        "close in the top third is a WEAK proxy and is already available as "
        "`close_third` — do not confuse the two.",
        "spec 02: the historical feed is OHLC + volume only"),
    Unobservable(
        "spread", "spread kitna tha?",
        "Quotes exist only on the option leg, live, at order time — that is the cost "
        "gate's input (CLAUDE.md §11), not a price-action input.",
        "spec 08; historical index candles carry no quote"),
    Unobservable(
        "open_interest", "OI kya keh raha tha?",
        "Not in the index candle feed. Available per option strike from a different "
        "endpoint, and CLAUDE.md §2 forbids computing signals from option data.",
        "CLAUDE.md §2 — signal on the INDEX, execute on the option"),
)


# ─────────────────────────────────────────────────────────────────────────────
# measurements
# ─────────────────────────────────────────────────────────────────────────────
def _mean_range(candles: Sequence[Candle]) -> Decimal | None:
    real = [k for k in candles if not k.synthetic]
    return (sum(k.range for k in real) / len(real)) if real else None


def _range_x_atr(s: Span) -> Decimal | None:
    return (s.last.range / s.atr) if s.atr else None


def _body_pct(s: Span) -> Decimal | None:
    k = s.last
    return (k.body / k.range * 100) if k.range > ZERO else None


def _upper_wick_pct(s: Span) -> Decimal | None:
    k = s.last
    return (k.upper_wick / k.range * 100) if k.range > ZERO else None


def _lower_wick_pct(s: Span) -> Decimal | None:
    k = s.last
    return (k.lower_wick / k.range * 100) if k.range > ZERO else None


def _close_position(s: Span) -> Decimal | None:
    return s.last.close_position if s.last.range > ZERO else None


def _span_compression(s: Span) -> Decimal | None:
    """Span ka mean range vs usse pehle ke 10 — the coil measurement."""
    inside = _mean_range(s.members)
    base = _mean_range(s.before(10))
    if inside is None or base is None or base <= ZERO:
        return None
    return inside / base


def _span_overlap(s: Span) -> Decimal | None:
    """What fraction of the span's candles overlap the span's middle third — how much of
    a group is *the same price* rather than a trend through it."""
    members = s.members
    if len(members) < 2:
        return None
    height = s.high - s.low
    if height <= ZERO:
        return Decimal(1)
    third_lo = s.low + height / 3
    third_hi = s.high - height / 3
    inside = sum(1 for k in members if k.l <= third_hi and k.h >= third_lo)
    return Decimal(inside) / len(members)


def _span_directionality(s: Span) -> Decimal | None:
    """|net| / total travelled. 1.0 = a straight line, 0.1 = churn. Spec 09's regime
    measure, applied to any group the trader circles."""
    members = s.members
    if len(members) < 2:
        return None
    travelled = sum(k.range for k in members)
    if travelled <= ZERO:
        return None
    return abs(members[-1].c - members[0].o) / travelled


def _span_high_progress(s: Span) -> Decimal | None:
    """Are the highs stepping up through the span? +1 every higher high, -1 every lower,
    normalised. A sequence measure, not a shape measure."""
    members = s.members
    if len(members) < 2:
        return None
    steps = sum(1 if b.h > a.h else (-1 if b.h < a.h else 0)
                for a, b in zip(members, members[1:]))
    return Decimal(steps) / (len(members) - 1)


def _engulfs_prior_body(s: Span) -> Decimal | None:
    """Relation: does this candle's body cover the previous candle's body?"""
    if s.hi < 1:
        return None
    now, prev = s.last, s.candles[s.hi - 1]
    return Decimal(1) if (now.body_top >= prev.body_top
                          and now.body_bottom <= prev.body_bottom) else Decimal(0)


def _inside_prior_range(s: Span) -> Decimal | None:
    if s.hi < 1:
        return None
    now, prev = s.last, s.candles[s.hi - 1]
    return Decimal(1) if (now.h <= prev.h and now.l >= prev.l) else Decimal(0)


def _closed_back_inside(s: Span) -> Decimal | None:
    """Relation: the candle poked beyond the prior candle's extreme and closed back
    within it. The shape a sweep is made of — spec 06 setup B's raw material."""
    if s.hi < 1:
        return None
    now, prev = s.last, s.candles[s.hi - 1]
    poked_up = now.h > prev.h and now.c <= prev.h
    poked_down = now.l < prev.l and now.c >= prev.l
    return Decimal(1) if (poked_up or poked_down) else Decimal(0)


def _expansion_vs_prior(s: Span) -> Decimal | None:
    """BUILD-BRIEF §7 M-3's measurement: this candle against the prior 10."""
    base = _mean_range(s.before(10))
    if base is None or base <= ZERO:
        return None
    return s.last.range / base


def _time_at_price(s: Span) -> Decimal | None:
    price = s.last.c
    window = s.before(11)
    return Decimal(sum(1 for k in window if k.l <= price <= k.h)) if window else None


def _round_proximity(s: Span) -> Decimal | None:
    remainder = s.last.c % Decimal(100)
    return min(remainder, Decimal(100) - remainder)


def _minutes_from_open(s: Span) -> Decimal | None:
    t = s.last.open_time
    return Decimal((t.hour - 9) * 60 + t.minute - 15)


CAPABILITIES: tuple[Capability, ...] = (
    # ── one candle ───────────────────────────────────────────────────────────
    Capability("range_x_atr", "ye candle apne din ke hisaab se kitni badi hai?",
               "candle", "ratio against a rolling scale",
               ("levels.launch_impulse_atr_mult",),
               "src/domain/models.py:Candle.range", _range_x_atr),
    Capability("body_pct", "kitna hissa body hai, kitna wick?",
               "candle", "ratio of two candle geometries",
               ("setups.b_sweep_wick_ratio",),
               "src/domain/models.py:Candle.body", _body_pct),
    Capability("upper_wick_pct", "upar ka wick kitna lamba tha?",
               "candle", "ratio of two candle geometries",
               ("setups.b_sweep_wick_ratio",),
               "src/domain/models.py:Candle.upper_wick", _upper_wick_pct),
    Capability("lower_wick_pct", "neeche ka wick kitna lamba tha?",
               "candle", "ratio of two candle geometries",
               ("setups.b_sweep_wick_ratio",),
               "src/domain/models.py:Candle.lower_wick", _lower_wick_pct),
    Capability("close_position", "close kahan hua — upar, beech, ya neeche?",
               "candle", "normalised position within a range",
               (),                      # no threshold: 'top third' is a definition
               "src/domain/models.py:Candle.close_third", _close_position,
               ("src/levels/detectors.py::close_third",)),

    # ── a group ──────────────────────────────────────────────────────────────
    Capability("span_compression", "ye group pichhle group se kitna shaant tha?",
               "span", "windowed mean ratio",
               # setups.c_compression_ratio is the same MEASUREMENT used for a different
               # JOB — it grades a range before a C break. Nothing uses compression to
               # FIND anything, which is the blind spot spec 13 §2.1 is about.
               ("levels.compression_ratio_max", "levels.coil_min_candles"),
               "src/reasoning/vocabulary.py", _span_compression),
    Capability("span_overlap", "in candles ne ek hi jagah kitna time bitaya?",
               "span", "counting membership of a geometric band",
               ("levels.time_at_price_min_candles",),
               "src/reasoning/vocabulary.py", _span_overlap),
    Capability("span_directionality", "ye group ek line thi ya churn?",
               "span", "net displacement / total path length",
               ("structure.regime_lookback_5m",),
               "src/structure/engine.py", _span_directionality),
    Capability("span_high_progress", "highs step-by-step upar ja rahe the?",
               "span", "sign sequence over consecutive pairs",
               ("levels.swing_lookback_bars_1m",),
               "src/indicators/swings.py", _span_high_progress),

    # ── a relation between candles ───────────────────────────────────────────
    Capability("engulfs_prior_body", "isne pichhli candle ki body poori dhak li?",
               "relation", "interval containment between two candles",
               ("setups.engulf_min_body_mult",),
               "src/reasoning/vocabulary.py", _engulfs_prior_body),
    Capability("inside_prior_range", "ye candle pichhli ke andar hi rahi?",
               "relation", "interval containment between two candles",
               ("levels.inside_bar_min_count",),
               "src/reasoning/vocabulary.py", _inside_prior_range),
    Capability("closed_back_inside", "bahar nikal kar wapas andar band hui?",
               "relation", "extreme breach + close comparison",
               ("levels.sweep_reclaim_close_third",),
               "src/reasoning/vocabulary.py", _closed_back_inside),
    Capability("expansion_vs_prior", "ye candle pichhli 10 se kitni guna hai?",
               "relation", "ratio against a trailing mean",
               ("levels.regime_break_range_mult",),
               "src/reasoning/vocabulary.py", _expansion_vs_prior),

    # ── where price is ───────────────────────────────────────────────────────
    Capability("time_at_price", "is price par pehle kitni baar rukI thi?",
               "context", "counting touches of a horizontal band",
               ("levels.time_at_price_min_candles",),
               "src/reasoning/record.py", _time_at_price),
    Capability("round_proximity", "round number kitni door hai?",
               "context", "modular distance to a grid",
               ("levels.round_number_grid",),
               "src/levels/detectors.py:round_numbers", _round_proximity),
    Capability("minutes_from_open", "din ka kaunsa waqt tha?",
               "context", "clock arithmetic",
               ("time.opening_range_end",),
               "src/guards/engine.py", _minutes_from_open),

    # ── measurable from this feed, but nobody has written it ─────────────────
    Capability("failed_retest_depth", "retest pichhli baar se kitna kam gehra tha?",
               "relation", "comparative depth of two approaches to one level",
               ("levels.retest_shallower_ratio",),
               "NOT BUILT — no function computes this", None),
    Capability("velocity_change", "approach dheemi ho rahi thi ya tez?",
               "span", "first difference of per-candle displacement",
               ("levels.approach_deceleration_ratio",),
               "NOT BUILT — no function computes this", None),
)


BY_NAME = {c.name: c for c in CAPABILITIES}
UNOBSERVABLE_BY_NAME = {u.name: u for u in UNOBSERVABLE}


def describe(cfg: Config) -> list[tuple[str, Capability]]:
    return sorted(((c.status(cfg), c) for c in CAPABILITIES),
                  key=lambda pair: (pair[0], pair[1].name))
