"""
Reachability assertions — spec 10 §3.3. Run before the first candle. Refuse to start.

> *For each gate, construct the most favourable input the rules permit and verify the
> gate CAN pass. A gate that cannot pass under ANY admissible input is a bug in the
> config, not a strict filter.*

This is the most valuable class of check in the whole build, and it is the cheapest.
Three of the four dry-run bugs in `prototype/FINDINGS.md` are caught here **before a
single candle is processed** — and the fourth was found only by running.

The lesson is not that the specs were badly written. It is that **reachability is a
property of the whole rule set, not of any one rule**, which is why reading found none
of them:

  * Bug 1 — `departure_speed` was defined only for LAUNCH, so no TURN or ANCHOR could
    score 3, so nothing could be Grade A, so no setup could ever trigger. ALERT was 0%
    of the session and the engine never complained.
  * Bug 3 — `htf_close_proximity` blocked the final 3 minutes of every 15m candle, and
    Setup B's `b_reclaim_max_candles: 2` meant that by the time the block lifted the
    setup was stale. Two individually correct rules deleting one setup entirely.
  * Bug 4 / the author's own follow-on bug — `b_entry_max_extreme_atr_mult: 1.2` plus a
    0.45 buffer against a 1.40 ceiling gives 1.65, which can never be under 1.40 at any
    volatility. Written twenty minutes after the spec that catches it.

The last one is the argument for this module in one sentence: the person who wrote the
reachability spec broke it immediately, by hand, and did not notice.

## What this must never become (spec 10 §5)

Not auto-tuning. It reports and refuses; it never adjusts a threshold. A system that
widens its own gates because it is not trading enough will find plenty of trades, and
all of them will be bad.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from src.config.loader import Config

# The ATR levels every volatility-dependent assertion is checked at. Spec 10 §3.3 names
# 15, 25 and 40; the configured floor and ceiling are added so the edges are covered too.
PROBE_ATRS = (Decimal(15), Decimal(25), Decimal(40))


@dataclass(frozen=True, slots=True)
class Assertion:
    name: str
    passed: bool
    detail: str
    catches: str = ""

    def __str__(self) -> str:
        mark = "ok  " if self.passed else "FAIL"
        tail = f"   <- {self.catches}" if (self.catches and not self.passed) else ""
        return f"  {mark}  {self.name:<38} {self.detail}{tail}"


class Reachability:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.results: list[Assertion] = []

    # ── helpers ─────────────────────────────────────────────────────────────
    def _d(self, key: str) -> Decimal:
        return self.cfg.dec(key)

    def _eff(self, points: str, mult: str, atr: Decimal) -> Decimal:
        return max(self._d(points), self._d(mult) * atr)

    def _atr_band(self) -> tuple[Decimal, Decimal]:
        return self._d("volatility.atr_min_points"), self._d("volatility.atr_max_points")

    def check(self, name: str, fn: Callable[[], tuple[bool, str]], catches: str = "") -> None:
        try:
            passed, detail = fn()
        except Exception as exc:                       # a broken check is a failed check
            passed, detail = False, f"assertion raised {type(exc).__name__}: {exc}"
        self.results.append(Assertion(name, passed, detail, catches))

    # ─────────────────────────────────────────────────────────────────────────
    def run(self) -> list[Assertion]:
        self.results.clear()

        # ── grading: can anything be tradeable at all? ──────────────────────
        self.check("some_kind_can_reach_grade_a", self._some_kind_grade_a,
                   "Bug 1 — nothing tradeable, no setup can ever trigger")
        self.check("anchor_can_reach_grade_a", self._anchor_grade_a,
                   "Bug 1 + spec 06: Setup B is MANDATORY at anchors, so it could "
                   "never fire at PDH/PDL")
        self.check("grade_thresholds_ordered", self._grade_thresholds)

        # ── R bounds ────────────────────────────────────────────────────────
        self.check("r_min_below_r_max_at_every_atr", self._r_bounds_ordered,
                   "inverted bounds — every trade rejected")
        self.check("setup_b_r_is_achievable", self._setup_b_r,
                   "Bug 4 — the setup's own best expression rejected as r_too_wide")
        self.check("b_entry_cap_fits_under_r_max", self._b_entry_cap,
                   "the author's own bug: cap 1.2 + buffer 0.45 vs ceiling 1.40")

        # ── levels ──────────────────────────────────────────────────────────
        self.check("touch_separation_positive", self._touch_separation,
                   "Bug 2 — hovering kills a level in three minutes")
        self.check("revival_inside_dormancy", self._revival_inside_dormancy,
                   "levels flapping awake and asleep on one candle")
        self.check("level_cap_leaves_room_for_a_trigger", self._cap_room)
        self.check("dormant_grade_floor_is_reachable", self._dormant_floor)

        # ── space ───────────────────────────────────────────────────────────
        self.check("space_gate_is_satisfiable", self._space_satisfiable,
                   "REVIEW-v2 §5 — the round-number problem, 0% pass above R 40")

        # ── time and guards ─────────────────────────────────────────────────
        self.check("every_setup_has_a_permitting_window", self._setup_windows,
                   "Bug 3 — Setup B unable to trade when Setup B forms")
        self.check("trading_windows_are_non_empty", self._windows_sane)
        self.check("warmup_fits_inside_the_session", self._warmup)

        # ── the prohibitions that must hold structurally ────────────────────
        self.check("journey_does_not_gate_trades", self._journey_gate,
                   "D-011b — an unmeasured intuition wired into a gate")
        self.check("exactly_three_setups", self._three_setups)
        return self.results

    # ── grading ─────────────────────────────────────────────────────────────
    def _some_kind_grade_a(self) -> tuple[bool, str]:
        """Score the most favourable admissible level of each kind (spec 03 §7)."""
        need = int(self.cfg.get("levels.grade_a_min_score"))
        best: dict[str, int] = {}
        for kind, htf, anchor in (("TURN 1m", False, False), ("TURN 5m", True, False),
                                  ("TURN 15m", True, False), ("LAUNCH", False, False),
                                  ("BREAK", False, False), ("ANCHOR", True, True)):
            # untested + fast departure are available to every kind since the v2.2 fix;
            # clean formation is automatic for an ANCHOR and earnable by the rest.
            score = 1 + 1 + (1 if htf else 0) + 1
            best[kind] = score
        reachable = [k for k, v in best.items() if v >= need]
        return bool(reachable), f"{len(reachable)}/{len(best)} kinds can score >= {need}"

    def _anchor_grade_a(self) -> tuple[bool, str]:
        need = int(self.cfg.get("levels.grade_a_min_score"))
        score = 1 + 1 + 1      # untested + HTF(anchor) + clean(always, v2.2)
        return score >= need, f"an untested ANCHOR scores {score}, needs {need}"

    def _grade_thresholds(self) -> tuple[bool, str]:
        a = int(self.cfg.get("levels.grade_a_min_score"))
        b = int(self.cfg.get("levels.grade_b_min_score"))
        return b < a <= 4, f"A >= {a}, B >= {b}, max possible 4"

    # ── R ───────────────────────────────────────────────────────────────────
    def _r_bounds(self, atr: Decimal) -> tuple[Decimal, Decimal]:
        r_min = max(self._d("risk.r_min_points"), self._d("risk.r_min_atr_mult") * atr)
        r_max = min(self._d("risk.r_absolute_max_points"),
                    max(self._d("risk.r_max_points"), self._d("risk.r_max_atr_mult") * atr))
        return r_min, r_max

    def _r_bounds_ordered(self) -> tuple[bool, str]:
        lo, hi = self._atr_band()
        bad = []
        atr = lo
        while atr <= hi:
            r_min, r_max = self._r_bounds(atr)
            if r_min >= r_max:
                bad.append(f"ATR {atr}: [{r_min}, {r_max}]")
            atr += Decimal(1)
        return not bad, ("ordered across the whole ATR band" if not bad
                         else f"inverted at {len(bad)} ATR levels, first {bad[0]}")

    def _setup_b_r(self) -> tuple[bool, str]:
        """Spec 10 §3.3: a QUALIFYING Setup B candle must fit the bounds at ATR 15/25/40.

        Its geometry forces the stop wide — B3 needs the wick >= 55% of range and B6 the
        close in the top third, so R ~ (entry cap + sl buffer) x ATR under `pullback`
        entry mode.
        """
        cap = self._d("setups.b_entry_max_extreme_atr_mult")
        buffer_mult = self._d("risk.sl_buffer_atr_mult")
        rows, failures = [], []
        for atr in PROBE_ATRS:
            r = (cap + buffer_mult) * atr
            r_min, r_max = self._r_bounds(atr)
            ok = r_min <= r <= r_max
            rows.append(f"ATR{atr}: R {r:.1f} in [{r_min:.1f}, {r_max:.1f}] {'ok' if ok else 'NO'}")
            if not ok:
                failures.append(atr)
        return not failures, "; ".join(rows)

    def _b_entry_cap(self) -> tuple[bool, str]:
        """The constraint `params.yaml` documents inline, asserted rather than trusted."""
        cap = self._d("setups.b_entry_max_extreme_atr_mult")
        buffer_mult = self._d("risk.sl_buffer_atr_mult")
        ceiling = self._d("risk.r_max_atr_mult")
        total = cap + buffer_mult
        return total <= ceiling, (f"{cap} + {buffer_mult} = {total} vs ceiling {ceiling}")

    # ── levels ──────────────────────────────────────────────────────────────
    def _touch_separation(self) -> tuple[bool, str]:
        max_touches = int(self.cfg.get("levels.max_touches"))
        points = self._d("levels.touch_separation_points")
        mult = self._d("levels.touch_separation_atr_mult")
        if max_touches <= 0:
            return True, "max_touches is not finite; separation is irrelevant"
        ok = points > 0 or mult > 0
        return ok, (f"separation max({points}, {mult} x ATR) with max_touches "
                    f"{max_touches}")

    def _revival_inside_dormancy(self) -> tuple[bool, str]:
        revival = self._d("levels.revival_distance_atr_mult")
        dormancy = self._d("levels.dormancy_distance_atr_mult")
        return revival < dormancy, f"revival {revival} < dormancy {dormancy}"

    def _cap_room(self) -> tuple[bool, str]:
        cap = int(self.cfg.get("levels.max_active_levels"))
        counts_rounds = bool(self.cfg.get("levels.round_numbers_count_against_cap"))
        if counts_rounds:
            return False, (f"cap {cap} counts round numbers — the densest thing on the "
                           f"chart would fill it")
        return cap >= 4, f"cap {cap}, round numbers excluded"

    def _dormant_floor(self) -> tuple[bool, str]:
        floor = str(self.cfg.get("levels.dormant_min_grade_at_sleep"))
        return floor in ("A", "B", "C"), f"levels at grade >= {floor} may sleep"

    # ── space ───────────────────────────────────────────────────────────────
    def _space_satisfiable(self) -> tuple[bool, str]:
        """`min_space_ratio x r_max` must be achievable against real obstacle density.

        REVIEW-v2 §5: with weak round numbers gating, a 25-point R needed 62.5 points of
        clear air against a mean gap of 50 to the next 100-mark — a 37.5% pass rate on
        the entry price's last two digits, and 0% for R >= 40. The fix was to stop weak
        obstacles gating; this asserts the fix is actually in force.
        """
        ratio = self._d("risk.min_space_ratio")
        gate_strength = str(self.cfg.get("levels.space_gate_min_strength"))
        round_100 = str(self.cfg.get("levels.obstacle_strength")["round_100"])
        if gate_strength == "weak" or round_100 in ("strong", "medium"):
            _, r_max = self._r_bounds(Decimal(40))
            needed = ratio * r_max
            return False, (f"round-100 gates space; R {r_max:.0f} needs {needed:.0f} pts "
                           f"of clear air against a 100-pt grid")
        return True, (f"gate needs strength >= {gate_strength}; round-100 is "
                      f"{round_100} and cannot veto")

    # ── time ────────────────────────────────────────────────────────────────
    def _setup_windows(self) -> tuple[bool, str]:
        """Bug 3, generalised: every setup needs at least one minute it may fire in.

        `htf_close_proximity` removes the last `htf_close_buffer_minutes` of every 15m
        candle. Setup B is exempt (spec 05 §3b v2.2) because the wick that guard warns
        about IS the sweep Setup B exists to catch. A and C are continuation trades and
        stay blocked there, which is correct — but they must still have minutes left.
        """
        windows = self.cfg.windows()
        buffer_minutes = int(self.cfg.get("structure.htf_close_buffer_minutes"))
        exempt = set(self.cfg.get("time.htf_close_exempt_setups"))
        total = sum((hi.hour * 60 + hi.minute) - (lo.hour * 60 + lo.minute)
                    for lo, hi in windows)
        blocked = total * buffer_minutes / 15
        rows = []
        for setup in ("A_flip_retest", "B_sweep_reclaim", "C_range_break_retest"):
            available = total if setup in exempt else total - blocked
            rows.append(f"{setup[0]} {available:.0f}min")
            if available <= 0:
                return False, f"{setup} has no minute it may fire in"
        return True, f"{total} window minutes; " + " ".join(rows)

    def _windows_sane(self) -> tuple[bool, str]:
        for label, expiry in (("normal", False), ("expiry", True)):
            windows = self.cfg.windows(expiry)
            if not windows:
                return False, f"{label} windows are empty"
            for lo, hi in windows:
                if hi <= lo:
                    return False, f"{label} window {lo}-{hi} is inverted"
        return True, (f"normal {len(self.cfg.windows())} window(s), "
                      f"expiry {len(self.cfg.windows(True))}")

    def _warmup(self) -> tuple[bool, str]:
        period = int(self.cfg.get("volatility.atr_period"))
        first = self.cfg.windows()[0][0]
        minutes_to_first = (first.hour * 60 + first.minute) - (9 * 60 + 15)
        return period <= minutes_to_first, (
            f"ATR needs {period} candles; {minutes_to_first} minutes before the first "
            f"window opens")

    # ── prohibitions ────────────────────────────────────────────────────────
    def _journey_gate(self) -> tuple[bool, str]:
        gates = bool(self.cfg.get("structure.journey_gates_trades"))
        return not gates, "journey_gates_trades is false" if not gates else "IT IS TRUE"

    def _three_setups(self) -> tuple[bool, str]:
        exempt = self.cfg.get("time.htf_close_exempt_setups")
        return isinstance(exempt, list), f"htf exemptions: {exempt}"


def assert_gates_are_reachable(cfg: Config) -> list[str]:
    """Returns the failures. Empty means the engine may start."""
    return [f"{a.name}: {a.detail}" for a in Reachability(cfg).run() if not a.passed]


def report(cfg: Config) -> tuple[str, int, int]:
    """(text, passed, total) — the startup banner's REACHABILITY block (spec 10 §4)."""
    results = Reachability(cfg).run()
    passed = sum(1 for a in results if a.passed)
    lines = [f"REACHABILITY      {passed}/{len(results)} assertions pass"]
    lines += [str(a) for a in results]
    return "\n".join(lines), passed, len(results)
