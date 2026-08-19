"""
The three setups' shared floor — spec 06.

> Three setups. Not four. *"Every additional setup increases trade frequency, and trade
> frequency is the dominant cost and error multiplier in this system."*

`REGISTRY` is asserted to hold exactly three entries by `test_registry_length_is_three`.
That assertion is the enforcement; a comment saying "do not add a fourth" is not.

## Why the preconditions live here and not in each detector

Seven checks run before any detector sees a candle. If each detector carried its own copy
they would drift, and the one that drifted would be the one that let a duplicate attempt
through at 14:30 on a day already down 2R. They are computed once, in one order, and the
gate name that comes back is the one the journal records.

## The rule that had to be code

> *"At `kind == ANCHOR`, Setup B is the only permitted setup. Enforce in `setups/base.py`,
> not by convention."*

Spec 06 says it in those words, and the reasoning is worth keeping in front of you: the
most-watched levels hold the most stops, so they are swept most often. Taking a plain
rejection at PDH/PDL without a sweep is standing exactly where the stop hunt is aimed.

## What this deliberately does NOT check

`mode == ALERT` is listed in spec 06's precondition block, and it is checked here, but the
pipeline (spec 01 §3 step 7) already refuses to call the setup layer outside ALERT. Both
exist on purpose: the pipeline decides *when to ask*, and this decides *what a valid
answer looks like*. `prototype/FINDINGS.md` Bug 3 was a detector that never ran because
the mode was wrong while every one of its own conditions passed — the two layers failing
independently is what made that invisible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

from src.config.loader import Config
from src.domain.models import ZERO, Candle, Grade, Level, LevelKind, Mode
from src.guards.engine import GuardOutcome
from src.state.board import StateBoard
from src.state.session_store import SessionState

SETUP_A = "A_flip_retest"
SETUP_B = "B_sweep_reclaim"
SETUP_C = "C_range_break_retest"


@dataclass(frozen=True)
class SetupContext:
    """Everything a detector may look at, and nothing else.

    Deliberately does not carry the pipeline, the journey ladder or the feed — a detector
    that can reach the ladder will eventually read it, and D-011b exists because
    `journey/` must never gate a trade.
    """
    candles: Sequence[Candle]          # 1m, closed only, ending at `index`
    index: int
    board: StateBoard
    level: Level
    cfg: Config
    guard: GuardOutcome
    state: SessionState
    mode: Mode
    trend_5m: str = "none"

    @property
    def candle(self) -> Candle:
        return self.candles[self.index]

    @property
    def atr14(self) -> Decimal:
        return self.board.atr_1m or ZERO

    @property
    def atr20(self) -> Decimal:
        return self.board.atr20_1m or ZERO

    def eff(self, points_key: str, mult_key: str, atr: Decimal | None = None) -> Decimal:
        return self.cfg.effective(points_key, mult_key,
                                  self.atr14 if atr is None else atr)

    def candles_since(self, born) -> int:
        """How many 1m candles have closed since a level was born. Counted from
        timestamps rather than stored indices so it is right after a restart, when the
        board is rebuilt from candles and no index survives."""
        for offset in range(self.index, -1, -1):
            if self.candles[offset].open_time <= born:
                return self.index - offset
        return self.index + 1

    def window(self, n: int) -> list[Candle]:
        return list(self.candles[max(0, self.index - n + 1):self.index + 1])


@dataclass(frozen=True)
class Detection:
    """A setup that fired. Not yet a signal — risk, space, cost and sizing all still get
    a vote (spec 01 §3, steps 8 to 12)."""
    setup: str
    side: str                          # "long" | "short"
    level_id: str
    entry_ref: Decimal
    extreme: Decimal                   # the price the stop must sit beyond
    trigger_index: int
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SetupResult:
    """Either a detection or the gate that stopped it. Never neither, never both — spec
    01 §1: a rejection carrying its exact gate is a successful output."""
    setup: str
    detection: Detection | None = None
    gate: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if (self.detection is None) == (self.gate is None):
            raise ValueError(f"{self.setup}: exactly one of detection/gate is required")


Detector = Callable[[SetupContext], SetupResult]


# ─────────────────────────────────────────────────────────────────────────────
def preconditions(ctx: SetupContext, setup: str) -> SetupResult | None:
    """`None` means proceed. Otherwise the rejection, with its gate already chosen.

    Order matters: the cheapest and most-common failures first, so the histogram spec 09
    asks for is dominated by the reason that actually stopped things rather than by
    whichever check happened to run first.
    """
    level = ctx.level

    if ctx.mode is not Mode.ALERT:
        return SetupResult(setup, gate="no_live_level",
                           detail=f"mode is {ctx.mode.value}, not ALERT")

    if setup in ctx.guard.blocked_setups:
        return SetupResult(setup, gate="no_setup",
                           detail=f"{setup} blocked by {ctx.guard.failed_gate or 'a guard'}")

    if level.grade is not Grade.A:
        return SetupResult(setup, gate="no_live_level",
                           detail=f"level {level.id} is grade {level.grade.value}")

    if not level.alive:
        return SetupResult(setup, gate="no_live_level",
                           detail=f"level {level.id} is {level.state.value}")

    max_touches = int(ctx.cfg.get("levels.max_touches"))
    if level.touches >= max_touches:
        return SetupResult(setup, gate="no_live_level",
                           detail=f"level {level.id} has {level.touches} touches "
                                  f"(max {max_touches})")

    # Spec 06: at an ANCHOR, Setup B is the ONLY permitted setup.
    if level.kind is LevelKind.ANCHOR and setup != SETUP_B:
        return SetupResult(setup, gate="no_setup",
                           detail=f"{level.id} is an ANCHOR — only {SETUP_B} may trade it "
                                  f"(spec 06). The most-watched levels are swept, not "
                                  f"cleanly rejected.")

    if ctx.state.has_attempted(level.id, setup):
        return SetupResult(setup, gate="duplicate_setup",
                           detail=f"{setup} already attempted at {level.id} this session")

    if ctx.state.in_cooldown(ctx.index):
        return SetupResult(setup, gate="no_setup",
                           detail=f"cooldown until candle {ctx.state.cooldown_until_candle}")

    return None


def no_synthetic(ctx: SetupContext, candles: Sequence[Candle], setup: str) -> SetupResult | None:
    """A forward-filled candle has no shape, so any rule reading its body or wicks is
    reading an invention. Checked against the specific candles a detector used rather
    than the whole window — a synthetic bar an hour earlier is irrelevant."""
    if any(k.synthetic for k in candles):
        return SetupResult(setup, gate="no_setup",
                           detail="a candle in this setup is synthetic (filled gap)")
    return None


# ─────────────────────────────────────────────────────────────────────────────
def build_registry() -> dict[str, Detector]:
    from src.setups.flip_retest import detect_a
    from src.setups.range_break import detect_c
    from src.setups.sweep_reclaim import detect_b

    return {SETUP_A: detect_a, SETUP_B: detect_b, SETUP_C: detect_c}


def evaluate(ctx: SetupContext) -> list[SetupResult]:
    """Every setup gets asked, and every answer is kept.

    Returning only the first hit would make the rejection histogram meaningless — spec
    01 §10: *"The most valuable dataset this system produces is why it did not trade."*
    """
    out = []
    for setup, detector in build_registry().items():
        stopped = preconditions(ctx, setup)
        out.append(stopped if stopped is not None else detector(ctx))
    return out
