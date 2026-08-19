"""
The per-candle reasoning record — spec 13.

> Kisi bhi candle par ungli rakho aur poocho: **"tum yahan kya soch rahe the?"**

Five parts per closed candle. All of them are already computed by the P1 pipeline; they
were simply never written down. The fifth is the one that does not exist anywhere else:

## "Main ye dekh hi nahi sakta" — the blind spots

> *Ek trading system ke liye jiska sahi jawab zyadatar "kuch nahi" hota hai, "maine kuch
> nahi dekha" aur "main dekh nahi sakta" — ye do bilkul alag baatein hain. Aaj tak dono
> ek jaisi dikhti thi.*

Spec 13 §2.1 requires this list to be **derived from `params.yaml`, not hardcoded**: a
thing the engine measures but no detector consumes is a blind spot, and *"naya detector
banao, wo line list se apne aap hat jaayegi."*

So each probe below names the config keys a detector for it **would** own. The probe is
a blind spot exactly while none of those keys exists in `params.yaml`. Adding a real
compression detector means adding `levels.compression_*`, and the line disappears by
itself — nobody has to remember to delete it.

Note what that implies and what it does not: a measurement used only for *grading* is
still a detection blind spot. Spec 13's own example is time-at-price, which
`clean_formation_min_candles` reads when scoring a level but which no detector will ever
use to *find* one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Sequence

from src.config.loader import Config
from src.domain.models import ZERO, Candle
from src.p1_pipeline import CandleRecord


@dataclass(frozen=True, slots=True)
class Probe:
    """A thing the engine can measure. Whether it can ACT on it is the question."""
    name: str
    admission: str                      # what the engine says when it cannot act
    detector_keys: tuple[str, ...]      # the params keys a detector for this would own
    measure: Callable[["Window"], Decimal | None]
    triggers_at: Callable[[Decimal], bool]

    def is_blind_spot(self, cfg: Config) -> bool:
        return not any(cfg.get(key, None) is not None for key in self.detector_keys)


@dataclass
class Window:
    """The candles around the one being asked about, plus the ATR they are measured in."""
    candles: Sequence[Candle]
    index: int
    atr20: Decimal | None

    @property
    def candle(self) -> Candle:
        return self.candles[self.index]

    def prior(self, n: int) -> list[Candle]:
        return list(self.candles[max(0, self.index - n):self.index])

    def mean_range(self, n: int) -> Decimal | None:
        window = self.prior(n)
        real = [k for k in window if not k.synthetic]
        return (sum(k.range for k in real) / len(real)) if real else None


# ─────────────────────────────────────────────────────────────────────────────
# the probes
# ─────────────────────────────────────────────────────────────────────────────
def _compression(w: Window) -> Decimal | None:
    """(last 3 candle ranges) / (prior 10) — spec 12 §5's measurement battery."""
    last3 = w.mean_range(3)
    prior10 = w.candles[max(0, w.index - 13):max(0, w.index - 3)]
    real = [k for k in prior10 if not k.synthetic]
    if last3 is None or not real:
        return None
    base = sum(k.range for k in real) / len(real)
    return (last3 / base) if base > ZERO else None


def _time_at_price(w: Window) -> Decimal | None:
    """How many of the prior 11 candles touched this candle's close."""
    price = w.candle.c
    window = w.prior(11)
    if not window:
        return None
    return Decimal(sum(1 for k in window if k.l <= price <= k.h))


def _round_proximity(w: Window) -> Decimal | None:
    remainder = w.candle.c % Decimal(100)
    return min(remainder, Decimal(100) - remainder)


def _regime_break(w: Window) -> Decimal | None:
    """BUILD-BRIEF §7 M-3 — *"Pehli candle jo pichli 10 se DOUBLE ho → kuch badal gaya."*
    Listed here because M-3 says to build it as a grade demotion and it is not built."""
    base = w.mean_range(10)
    if base is None or base <= ZERO:
        return None
    return w.candle.range / base


PROBES: tuple[Probe, ...] = (
    Probe("compression",
          "coil ban rahi hai — mera koi coil detector nahi hai",
          ("levels.compression_ratio_max", "levels.coil_min_candles"),
          _compression, lambda v: v < Decimal("0.5")),
    Probe("time_at_price",
          "main swing aur wick cluster dhoondhta hu, 'time at price' nahi",
          ("levels.time_at_price_min_candles",),
          _time_at_price, lambda v: v >= 4),
    Probe("round_number_near",
          "maine round numbers ko weak kar diya hai — REVIEW-v2 §5",
          ("levels.round_numbers_can_trigger_alert_when_untested",),
          _round_proximity, lambda v: v <= Decimal(5)),
    # `volume_spike` used to sit here, admitting *"mere paas koi volume rule nahi hai"* —
    # which reads as an invitation to go and write one. It is not. NIFTY BANK is an index
    # and Kite reports volume 0 on every candle of it: 1,120,535 candles downloaded, none
    # with a non-zero volume. So it was never a missing detector, it was a missing
    # instrument, and the admission pointed at a month of work that could not have
    # succeeded. It now lives in `vocabulary.UNOBSERVABLE`, where the answer is "stop"
    # rather than "build", and `test_unobservable_are_actually_unobservable` re-counts it
    # against the real files so the claim cannot quietly go stale.
    Probe("regime_break_candle",
          "ye candle pichhli 10 se dugni hai — BUILD-BRIEF §7 M-3 kehta hai board reset "
          "karo, par wo rule bana nahi hai",
          ("levels.regime_break_range_mult",),
          _regime_break, lambda v: v >= Decimal("2.0")),
)


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Reasoning:
    """Spec 13 §2's five parts."""
    saw: dict[str, object] = field(default_factory=dict)
    board_changed: list[str] = field(default_factory=list)
    attention: list[str] = field(default_factory=list)
    expectation: str = ""
    blind_spots: list[str] = field(default_factory=list)


def measure(cfg: Config, records: list[CandleRecord], index: int) -> Reasoning:
    """Everything the engine knew at candle `index`, and nothing it did not.

    Reads only `records[:index + 1]` — `test_thought_record_no_lookahead` (spec 13 §7)
    exists because a reasoning record built from the future is a record of hindsight.
    """
    record = records[index]
    candles = [r.candle for r in records[:index + 1]]
    w = Window(candles, index, record.board.atr20_1m)
    candle = record.candle
    atr = record.board.atr20_1m

    reasoning = Reasoning()
    reasoning.saw = {
        "range": candle.range,
        "range_x_atr": (candle.range / atr) if atr else None,
        "prior_6_ranges": [k.range for k in w.prior(6)],
        "body": candle.body,
        "upper_wick_pct": (candle.upper_wick / candle.range * 100) if candle.range else None,
        "lower_wick_pct": (candle.lower_wick / candle.range * 100) if candle.range else None,
        "close_third": candle.close_third,
        "close_position": candle.close_position,
        "time_at_price": _time_at_price(w),
        "compression": _compression(w),
    }

    if record.new_levels:
        reasoning.board_changed += [f"naya level {lid}" for lid in record.new_levels]
    if record.dead_levels:
        reasoning.board_changed += [f"level gaya {lid}" for lid in record.dead_levels]
    if index > 0:
        prev = records[index - 1].board
        if prev.control != record.board.control:
            reasoning.board_changed.append(
                f"control {prev.control} -> {record.board.control}")
        if prev.regime != record.board.regime:
            reasoning.board_changed.append(f"regime {prev.regime} -> {record.board.regime}")

    alert_distance = cfg.effective("modes.alert_distance_points",
                                   "modes.alert_distance_atr_mult", record.board.atr_1m)
    for level in sorted(record.board.levels_above + record.board.levels_below,
                        key=lambda lv: abs(lv.body_edge - candle.c))[:3]:
        distance = abs(level.body_edge - candle.c)
        if distance <= alert_distance and level.grade.value == "A":
            flag = "  <- ALERT range me"
        elif distance <= alert_distance:
            flag = "  (Grade A nahi, ignore)"
        else:
            flag = ""
        reasoning.attention.append(
            f"{level.body_edge:>10,.1f}  {level.kind.value:<7} grade {level.grade.value}  "
            f"touches {level.touches}  — {distance:>6.1f} pts{flag}")
    reasoning.attention.append(f"alert_distance {alert_distance:.0f} pts")
    reasoning.expectation = record.anticipation

    for probe in PROBES:
        value = probe.measure(w)
        if value is None or not probe.triggers_at(value):
            continue
        if probe.is_blind_spot(cfg):
            reasoning.blind_spots.append(f"{probe.name} = {value:.2f} — {probe.admission}")
    return reasoning
