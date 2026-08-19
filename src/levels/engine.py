"""
LevelEngine — spec 03.

Maintains the level book: births, touches, grading, death, dormancy, the 8-cap and the
obstacle list. One call per closed 1m candle, in the order spec 03 §10 fixes:

    1  day high / low          7  wick clusters
    2  age out expired         8  re-grade
    3  touches                 9  death rules
    4  breaks -> axis         10  the 8-cap
    5  TURN births            11  obstacles
    6  LAUNCH births

*"Order matters: breaks before births, deaths before the cap."*

## The four fixes from prototype/FINDINGS.md are load-bearing here

**Bug 1 — `departure_speed` is computed for every kind, not only LAUNCH.** v1 defined it
inside the LAUNCH section, so TURN and ANCHOR defaulted to 0, could never score 3, and
could never reach Grade A. Since a setup may only trigger at Grade A, the engine could
trade at exactly one kind of level, and ALERT was 0% of the dry-run session.

**Bug 2 — a touch is an EVENT, not a minute.** Price must LEAVE the zone by
`touch_separation` before the next entry counts. Without it, PDL died at 09:57 from
three minutes of hovering — two minutes before its own sweep.

**Bug 5 — only a Grade A or B level may create an axis.** 28 breaks in one session filled
6 of the 8 slots with Grade C axes, crowding out the levels the engine exists to find.

**D-011c — one price is one level.** Detection runs 15m -> 5m -> 1m and merges by zone
proximity, keeping the highest `born_tf`. The 8-cap is meaningless if the same price
occupies three slots.

## What this module is NOT allowed to know

It never sees positions, structure, or setups (spec 01 §5). It reads candles and ATR and
writes a book. `structure/` is joined to it only in `state/board.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Literal

from src.config.loader import Config
from src.domain.models import (
    ZERO, Candle, Grade, Level, LevelKind, LevelSide, LevelState, ObstacleStrength,
)
from src.indicators.swings import SwingDetector
from src.levels.detectors import (
    Candidate, LaunchAttempt, detect_launch, find_wick_clusters, round_numbers,
    turn_from_pivot,
)

GRADE_ORDER = {Grade.A: 3, Grade.B: 2, Grade.C: 1}
TF_ORDER = {"1m": 0, "5m": 1, "15m": 2, "1d": 3}


@dataclass(frozen=True, slots=True)
class Obstacle:
    """A price in the way, with the strength that decides whether it may veto a trade.

    Spec 03 §6b splits one question into two, because v1 collapsed them and let the
    weaker one veto: the space GATE uses strength >= medium; T1 placement respects
    everything, including weak.
    """
    price: Decimal
    strength: ObstacleStrength
    source: str
    level: Level | None = None

    @property
    def gates_space(self) -> bool:
        return self.strength in (ObstacleStrength.STRONG, ObstacleStrength.MEDIUM)


@dataclass
class _Pending:
    """A candidate waiting for `departure_lookahead_candles` to pass.

    Not look-ahead — spec 03 §3: *"the level simply does not exist until candle
    born_i + n closes."* It is the same delay a swing pivot already has.
    """
    candidate: Candidate
    resolve_at: int


@dataclass
class LevelBook:
    """Four collections, and the distinction between the first two is load-bearing.

    `live` holds every level the engine is tracking. `active_ids` is the capped subset —
    spec 03 §8b's "keep 8, drop the rest to an inactive pool". The pool is inactive for
    ALERT and setup purposes only: a level in it is still touched, still breaks, still
    ages and still dies. Freezing it instead would let a level survive by being
    ignored, and then reappear stale when the cap widened.

    `rounds` is separate because a round number is not a level. Spec 03 §6 strips it of
    everything a level has — it can never be Grade A, never triggers ALERT, never counts
    against the cap — and leaves only its role as an obstacle for T1. Keeping ~30 of
    them in `live` made 89% of the book Grade B and reported a full book on a session
    whose real book held two levels.
    """
    live: dict[str, Level] = field(default_factory=dict)
    rounds: dict[str, Level] = field(default_factory=dict)
    dormant: dict[str, Level] = field(default_factory=dict)
    dead: dict[str, Level] = field(default_factory=dict)
    active_ids: tuple[str, ...] = ()

    def active(self) -> list[Level]:
        """The book the trader would draw — after the cap, highest price first."""
        return sorted((self.live[i] for i in self.active_ids if i in self.live),
                      key=lambda x: x.body_edge, reverse=True)

    def grade_a(self) -> list[Level]:
        """Only ACTIVE levels may trigger a setup — a level outside the cap is not in
        front of you, whatever its grade."""
        return [x for x in self.active() if x.grade is Grade.A]

    def inactive(self) -> list[Level]:
        return [lv for lid, lv in self.live.items() if lid not in self.active_ids]

    def all_known(self) -> Iterable[Level]:
        yield from self.live.values()
        yield from self.rounds.values()
        yield from self.dormant.values()


class LevelEngine:
    def __init__(self, config: Config, symbol: str,
                 pdh: Decimal | None = None, pdl: Decimal | None = None,
                 pdc: Decimal | None = None) -> None:
        self.cfg = config
        self.symbol = symbol
        self.book = LevelBook()

        self.candles: list[Candle] = []
        self.m5: list[Candle] = []
        self.m15: list[Candle] = []
        self._m5_index: dict[datetime, int] = {}
        self._m15_index: dict[datetime, int] = {}

        self._det = {tf: SwingDetector(tf, k=int(self._p(f"swing_lookback_bars_{tf}")))
                     for tf in ("1m", "5m", "15m")}
        self._pending: list[_Pending] = []
        self._seq = 0
        self._atr20_history: list[Decimal | None] = []

        self.day_high: Decimal | None = None
        self.day_low: Decimal | None = None
        self.day_high_at: datetime | None = None
        self.day_low_at: datetime | None = None
        self.axis_id: str | None = None
        self.pdh, self.pdl, self.pdc = pdh, pdl, pdc

        self._round_grid: set[Decimal] = set()
        self._round_recomputed_at = -1
        self._opening_range_done = False
        self.or_high: Decimal | None = None
        self.or_low: Decimal | None = None
        self.events: list[dict[str, object]] = []      # births, deaths, dormancy, revival

    # ── config shorthands ───────────────────────────────────────────────────
    def _p(self, key: str, default=None) -> object:
        return self.cfg.get(f"levels.{key}", default) if default is not None \
            else self.cfg.get(f"levels.{key}")

    def _d(self, key: str) -> Decimal:
        return self.cfg.dec(f"levels.{key}")

    # ── identity ────────────────────────────────────────────────────────────
    def _new_id(self, kind: LevelKind, tf: str, price: Decimal) -> str:
        self._seq += 1
        return f"L{self._seq:03d}_{tf}_{kind.value[:3].upper()}_{price:.0f}"

    # ─────────────────────────────────────────────────────────────────────────
    # the entry point
    # ─────────────────────────────────────────────────────────────────────────
    def on_candle(self, candle: Candle, atr20: Decimal | None,
                  m5: Candle | None = None, m15: Candle | None = None) -> None:
        i = len(self.candles)
        self.candles.append(candle)
        self._atr20_history.append(atr20)
        if m5 is not None:
            self._m5_index[m5.open_time] = len(self.m5)
            self.m5.append(m5)
        if m15 is not None:
            self._m15_index[m15.open_time] = len(self.m15)
            self.m15.append(m15)

        self._update_day_extremes(candle, i)          # 1
        self._seed_anchors(candle, i, atr20)
        self._expire(candle, i)                       # 2
        self._touches(candle, i, atr20)               # 3
        self._breaks(candle, i, atr20)                # 4
        self._resolve_pending(i, atr20)               # 5+6+7 land here after their delay
        self._detect_turns(candle, i, m5, m15)        # 5
        self._detect_launch(i, atr20)                 # 6
        self._detect_clusters(i, atr20)               # 7
        self._regrade(i)                              # 8
        self._deaths(candle, i, atr20)                # 9
        self._dormancy(candle, i, atr20)              # 9b
        self._apply_cap(candle)                       # 10

    # ── 1. day extremes ─────────────────────────────────────────────────────
    def _update_day_extremes(self, candle: Candle, i: int) -> None:
        if candle.synthetic:
            return
        if self.day_high is None or candle.h > self.day_high:
            self.day_high, self.day_high_at = candle.h, candle.open_time
        if self.day_low is None or candle.l < self.day_low:
            self.day_low, self.day_low_at = candle.l, candle.open_time

    # ── ANCHORs ─────────────────────────────────────────────────────────────
    def _seed_anchors(self, candle: Candle, i: int, atr20: Decimal | None) -> None:
        """PDH/PDL/PDC once at open; the opening range at 09:30 (spec 03 §6).

        Anchors have `pocket == 0` — `body_edge == wick_tip`. Everything downstream must
        survive that, which is why spec 03 §6 calls it out and `test_round_number_zero_
        pocket` exists.
        """
        if i == 0:
            for price, name in ((self.pdh, "PDH"), (self.pdl, "PDL"), (self.pdc, "PDC")):
                if price is None:
                    continue
                side = LevelSide.RESISTANCE if name == "PDH" else (
                    LevelSide.SUPPORT if name == "PDL" else LevelSide.AXIS)
                self._create(Candidate(LevelKind.ANCHOR, side, price, price, 0, "1d",
                                       {"anchor": name}), i, departure=ZERO)

        end = self.cfg.time_at("time.opening_range_end")
        if not self._opening_range_done and candle.open_time.time() >= end:
            window = [k for k in self.candles[:i] if k.open_time.time() < end and not k.synthetic]
            if window:
                hi = max(k.h for k in window)
                lo = min(k.l for k in window)
                self.or_high, self.or_low = hi, lo
                self._create(Candidate(LevelKind.ANCHOR, LevelSide.RESISTANCE, hi, hi, i, "1d",
                                       {"anchor": "OR_high"}), i, departure=ZERO)
                self._create(Candidate(LevelKind.ANCHOR, LevelSide.SUPPORT, lo, lo, i, "1d",
                                       {"anchor": "OR_low"}), i, departure=ZERO)
            self._opening_range_done = True

        self._refresh_round_numbers(candle, i)

    def _refresh_round_numbers(self, candle: Candle, i: int) -> None:
        """D-011: seed from the previous day's range until today's exceeds it, and
        recompute at most once per 5m candle so the book does not churn."""
        if i - self._round_recomputed_at < 5 and self._round_grid:
            return
        self._round_recomputed_at = i
        span = None
        if self.day_high is not None and self.day_low is not None:
            span = self.day_high - self.day_low
        prev_span = (self.pdh - self.pdl) if (self.pdh and self.pdl) else None
        if span is None or (prev_span is not None and span < prev_span):
            span = prev_span
        if span is None or span <= ZERO:
            return

        grid = int(self._p("round_number_grid"))
        reach = Decimal("1.5") * span
        wanted = set(round_numbers(candle.c - reach, candle.c + reach, grid))
        for price in wanted - self._round_grid:
            major = int(self._p("round_number_major_grid"))
            self._create(Candidate(LevelKind.ANCHOR, LevelSide.AXIS, price, price, i, "1d",
                                   {"anchor": "round", "major": price % major == 0}),
                         i, departure=ZERO, is_round=True)
        self._round_grid |= wanted

    # ── 2. expiry ───────────────────────────────────────────────────────────
    def _expire(self, candle: Candle, i: int) -> None:
        micro_ttl = timedelta(minutes=int(self._p("micro_level_ttl_minutes")))
        axis_ttl = timedelta(minutes=int(self._p("axis_ttl_minutes")))
        for lid, lv in list(self.book.live.items()):
            if lv.kind is LevelKind.ANCHOR:
                continue                                     # anchors never expire
            ttl = axis_ttl if lv.kind is LevelKind.BREAK else (
                micro_ttl if lv.born_tf == "1m" else None)
            if ttl is not None and candle.open_time - lv.born_at > ttl:
                self._kill(lid, "expired", i)

    # ── 3. touches ──────────────────────────────────────────────────────────
    def _touches(self, candle: Candle, i: int, atr20: Decimal | None) -> None:
        """Spec 03 §4 v2.2 — a touch requires separation.

            inside = candle.l <= zone_high and candle.h >= zone_low
            if inside and not in_zone:      touches += 1 ; in_zone = True
            elif not inside and price has LEFT by `separation`:   in_zone = False

        Hovering is one touch, however long it lasts.
        """
        if candle.synthetic:
            return                                            # D-009: only advances the clock
        sep = self.cfg.effective("levels.touch_separation_points",
                                 "levels.touch_separation_atr_mult", atr20)
        for store in (self.book.live, self.book.rounds):
          for lid, lv in list(store.items()):
            inside = candle.l <= lv.zone_high and candle.h >= lv.zone_low
            if inside and not lv.in_zone:
                store[lid] = replace(lv, touches=lv.touches + 1,
                                     last_touch_at=candle.open_time, in_zone=True)
            elif not inside and lv.in_zone:
                left = candle.l > lv.zone_high + sep or candle.h < lv.zone_low - sep
                if left:
                    store[lid] = replace(lv, in_zone=False)

    # ── 4. breaks ───────────────────────────────────────────────────────────
    def _breaks(self, candle: Candle, i: int, atr20: Decimal | None) -> None:
        """A body close beyond a live level kills it. Only a Grade A or B level then
        creates an axis (spec 03 §5 v2.2, Bug 5) — a Grade C level breaking is not news,
        it is context giving way."""
        if candle.synthetic:
            return
        min_grade = str(self._p("axis_min_broken_grade"))
        threshold = GRADE_ORDER[Grade(min_grade)]

        for lid, lv in list(self.book.live.items()):
            # A level breaks only in the direction that INVALIDATES it. Support breaks
            # downward; resistance breaks upward; an axis works both ways and so breaks
            # either way (spec 03 §5). Checking both directions on every level makes
            # each one break twice — once on the way past and once on the way back —
            # which manufactured 523 axes and 746 "broken" deaths in one session.
            above = candle.body_bottom > lv.zone_high
            below = candle.body_top < lv.zone_low

            # ARMING — a level can only be broken once price has been on the side it is
            # supposed to defend. On a gap-down open, PDL and PDC sit ABOVE price, and
            # without this the very first candle "breaks" both of them before the market
            # has done anything. Price did not trade through them; it gapped over them,
            # which is exactly the distinction spec 05 §1c draws: "a gap does not erase
            # yesterday's decision points — it just means we arrived at them from a
            # different direction." On 2026-03-04 this left the book holding one anchor
            # out of three, with the nearest live level 1,231 points away.
            defending = (not below) if lv.side is LevelSide.SUPPORT else (
                (not above) if lv.side is LevelSide.RESISTANCE else True)
            if not lv.armed:
                if defending:
                    self.book.live[lid] = replace(lv, armed=True)
                continue

            if lv.side is LevelSide.SUPPORT:
                broke_up, broke_down = False, below
            elif lv.side is LevelSide.RESISTANCE:
                broke_up, broke_down = above, False
            else:                                   # AXIS — post-break, works both ways
                broke_up, broke_down = above, below
            if not (broke_up or broke_down):
                continue
            if lv.is_round_number:
                continue                                     # a 100-mark is not a structure

            # A BREAK axis that is broken back through has FAILED — spec 03 §5 calls the
            # axis "the invalidation line (body close back through it = the move failed)",
            # and spec 06's Setup A rejects on exactly this with `setup_stale`. Minting a
            # fresh axis there would re-arm, on every oscillation, the one level that just
            # proved unreliable. Measured over 10 sessions before this fix: 1504 of 2417
            # breaks (62%) were axes breaking axes — a self-sustaining generator, and the
            # same shape as FINDINGS Bug 5.
            if lv.kind is LevelKind.BREAK:
                self._kill(lid, "flip_failed", i)
                continue

            self._kill(lid, "broken", i)
            if GRADE_ORDER[lv.grade] < threshold:
                continue
            axis = Candidate(LevelKind.BREAK, LevelSide.AXIS,
                             body_edge=lv.body_edge,
                             wick_tip=candle.l if broke_up else candle.h,
                             born_index=i, born_tf=lv.born_tf,
                             evidence={"source": "break", "broken_level": lid,
                                       "broken_grade": lv.grade.value,
                                       "direction": "up" if broke_up else "down"})
            new_id = self._create(axis, i, departure=None)
            if new_id:
                self.axis_id = new_id

    # ── 5/6/7. births ───────────────────────────────────────────────────────
    def _detect_turns(self, candle: Candle, i: int,
                      m5: Candle | None, m15: Candle | None) -> None:
        """D-011c: run 15m -> 5m -> 1m so a price found on several timeframes merges
        upward into one level carrying the highest `born_tf`."""
        if m15 is not None:
            for pivot in self._det["15m"].on_candle(m15):
                self._queue(turn_from_pivot(pivot, self._htf_born_index(self.m15[pivot.index])))
        if m5 is not None:
            for pivot in self._det["5m"].on_candle(m5):
                self._queue(turn_from_pivot(pivot, self._htf_born_index(self.m5[pivot.index])))
        for pivot in self._det["1m"].on_candle(candle):
            self._queue(turn_from_pivot(pivot, pivot.index))

    def _htf_born_index(self, htf: Candle) -> int:
        """The 1m index an HTF candle opened at. Aggregation is aligned (spec 01 §4),
        so this is exact rather than a search."""
        for k, one in enumerate(self.candles):
            if one.open_time == htf.open_time:
                return k
        return max(0, len(self.candles) - 1)

    def _detect_launch(self, i: int, atr20: Decimal | None) -> None:
        if atr20 is None:
            return
        attempt: LaunchAttempt = detect_launch(
            self.candles, i, atr20,
            impulse_atr_mult=self._d("launch_impulse_atr_mult"),
            base_atr_mult=self._d("launch_base_atr_mult"),
            base_min=int(self._p("launch_base_min_candles")),
            base_max=int(self._p("launch_base_max_candles")))
        if attempt.candidate is not None:
            self._queue(attempt.candidate)
        elif attempt.reason not in ("impulse_too_small", "no_atr", "synthetic_impulse"):
            # Near-misses are the raw material of P1.5 (spec 12 §5 step 2).
            self.events.append({"at": i, "event": "launch_near_miss",
                                "reason": attempt.reason, **attempt.measured})

    def _detect_clusters(self, i: int, atr20: Decimal | None) -> None:
        tol = self.cfg.effective("levels.wick_cluster_tolerance_points",
                                 "levels.wick_cluster_tolerance_atr_mult", atr20)
        for cand in find_wick_clusters(
                self.candles, i,
                min_touches=int(self._p("wick_cluster_min_touches")),
                tolerance=tol,
                window=int(self._p("wick_cluster_window_candles"))):
            self._queue(cand)

    def _queue(self, cand: Candidate) -> None:
        n = int(self._p("departure_lookahead_candles"))
        self._pending.append(_Pending(cand, cand.born_index + n))

    def _resolve_pending(self, i: int, atr20: Decimal | None) -> None:
        """Compute `departure_speed` for every kind (spec 03 §3 v2.2, Bug 1) and admit
        the level. A LAUNCH additionally REQUIRES the speed; others merely score for it."""
        still: list[_Pending] = []
        for pend in self._pending:
            if pend.resolve_at > i:
                still.append(pend)
                continue
            cand = pend.candidate
            atr_at_birth = self._atr20_history[cand.born_index] \
                if cand.born_index < len(self._atr20_history) else None
            if atr_at_birth is None or atr_at_birth <= ZERO:
                # D-023: no ATR20 at birth (the first 20 candles). The level is admitted
                # with departure 0 rather than discarded — discarding would delete every
                # level formed in the opening 20 minutes, including the opening range.
                departure = ZERO
            else:
                ref = cand.body_edge
                later = self.candles[min(pend.resolve_at, len(self.candles) - 1)]
                departure = abs(later.c - ref) / atr_at_birth

            if cand.kind is LevelKind.LAUNCH and departure < self._d("min_departure_speed"):
                self.events.append({"at": i, "event": "launch_rejected_slow_departure",
                                    "departure": departure,
                                    "required": self._d("min_departure_speed")})
                continue
            self._create(cand, i, departure=departure)
        self._pending = still

    # ── creation, with cross-timeframe merge (D-011c) ───────────────────────
    def _create(self, cand: Candidate, i: int, departure: Decimal | None,
                is_round: bool = False) -> str | None:
        atr20 = self._atr20_history[i] if i < len(self._atr20_history) else None
        tol = self.cfg.effective("levels.wick_cluster_tolerance_points",
                                 "levels.wick_cluster_tolerance_atr_mult", atr20)

        for lid, existing in list(self.book.live.items()) + list(self.book.dormant.items()):
            if abs(existing.body_edge - cand.body_edge) > tol:
                continue
            # Same price. Merge upward rather than duplicating (D-011c).
            better_tf = TF_ORDER[cand.born_tf] > TF_ORDER[existing.born_tf]
            merged = replace(
                existing,
                born_tf=cand.born_tf if better_tf else existing.born_tf,
                departure_speed=max(existing.departure_speed, departure or ZERO),
                evidence_tfs=existing.evidence_tfs | {cand.born_tf})
            (self.book.live if lid in self.book.live else self.book.dormant)[lid] = merged
            return None

        is_round_number = is_round or bool(cand.evidence.get("anchor") == "round")
        level = Level(
            id=self._new_id(cand.kind, cand.born_tf, cand.body_edge),
            kind=cand.kind, side=cand.side,
            born_at=self.candles[min(cand.born_index, i)].open_time,
            born_tf=cand.born_tf,
            body_edge=cand.body_edge, wick_tip=cand.wick_tip,
            departure_speed=departure or ZERO,
            grade=Grade(str(self._p("round_number_max_grade"))) if is_round_number else Grade.C,
            is_round_number=is_round_number,
            evidence_tfs=frozenset({cand.born_tf}))
        # Round numbers live apart from the book (spec 03 §6): obstacle only, never a
        # trigger, never counted against the cap, never in the grade distribution.
        (self.book.rounds if is_round_number else self.book.live)[level.id] = level
        self.events.append({"at": i, "event": "born", "id": level.id,
                            "kind": level.kind.value, "tf": level.born_tf,
                            "price": level.body_edge, "departure": level.departure_speed})
        return level.id

    # ── 8. grading ──────────────────────────────────────────────────────────
    def _regrade(self, i: int) -> None:
        min_dep = self._d("min_departure_speed")
        fast_mult = self._d("clean_formation_fast_mult")
        min_candles = int(self._p("clean_formation_min_candles"))
        a_min = int(self._p("grade_a_min_score"))
        b_min = int(self._p("grade_b_min_score"))
        round_cap = Grade(str(self._p("round_number_max_grade")))

        for lid, lv in list(self.book.live.items()):
            untested = lv.touches == 0
            fast = lv.departure_speed >= min_dep
            htf = lv.kind is LevelKind.ANCHOR or lv.born_tf in ("5m", "15m", "1d") \
                or bool(lv.evidence_tfs & {"5m", "15m"})
            # v2.2: an ANCHOR always earns clean formation — PDH/PDL/PDC are formed over
            # an entire session, the longest time-at-price available (spec 03 §7).
            if lv.kind is LevelKind.ANCHOR:
                clean = True
            else:
                clean = (self._time_at_price(lv, i) >= min_candles
                         or lv.departure_speed >= fast_mult * min_dep)

            score = sum((untested, fast, htf, clean))
            grade = Grade.A if score >= a_min else (Grade.B if score >= b_min else Grade.C)
            if lv.is_round_number and GRADE_ORDER[grade] > GRADE_ORDER[round_cap]:
                grade = round_cap
            if grade is not lv.grade:
                self.book.live[lid] = replace(lv, grade=grade)

    def _time_at_price(self, lv: Level, i: int) -> int:
        """D-023: how many candles in a window ending at birth intersected the zone.

        Spec 03 §7 asks for "long time-at-price (>= 10 candles)" without saying over what
        window or by what test. A window of 2x the threshold, ending at birth, keeps the
        measure local to the level's formation — a level is clean because price WORKED
        there, not because price happened to revisit an hour later.
        """
        window = int(self._p("clean_formation_min_candles")) * 2
        born = next((k for k, cd in enumerate(self.candles) if cd.open_time == lv.born_at), i)
        start = max(0, born - window)
        return sum(1 for cd in self.candles[start:born + 1]
                   if not cd.synthetic and cd.l <= lv.zone_high and cd.h >= lv.zone_low)

    # ── 9. deaths ───────────────────────────────────────────────────────────
    def _deaths(self, candle: Candle, i: int, atr20: Decimal | None) -> None:
        max_touches = int(self._p("max_touches"))
        accept = int(self._p("acceptance_candles"))
        for lid, lv in list(self.book.live.items()):
            if lv.touches >= max_touches:
                self._kill(lid, "exhausted", i)
                continue
            if lv.kind is LevelKind.ANCHOR and lv.is_round_number:
                continue
            if self._accepted_through(lv, i, accept):
                self._kill(lid, "accepted_through", i)

    def _accepted_through(self, lv: Level, i: int, need: int) -> bool:
        """D-024: `acceptance_candles` CONSECUTIVE body closes beyond the zone, in the
        direction that invalidates the level.

        Two readings had to be fixed here.

        **Consecutive.** Spec 03 §8 says "closed bodies beyond it for >=
        acceptance_candles" without saying whether they must be consecutive. Consecutive
        is the conservative reading: five scattered closes over an hour describe price
        passing by; five in a row describe price having moved on.

        **Directional.** Non-directional acceptance killed a support level because price
        spent five candles ABOVE it — which is a healthy untested support, not an
        invalidated one. That single error emptied the book to ~2 levels a session and,
        worse, made the dormant pool (spec 03 §8b, the whole v2.1 "level memory" idea)
        unreachable: every level died of acceptance long before it could travel 25 x ATR
        away and go dormant. Every run reported "0 sleeps / 0 revivals" and nothing
        looked wrong.
        """
        if i + 1 < need:
            return False
        recent = self.candles[i - need + 1:i + 1]
        if any(cd.synthetic for cd in recent):
            return False
        above = all(cd.body_bottom > lv.zone_high for cd in recent)
        below = all(cd.body_top < lv.zone_low for cd in recent)
        if lv.side is LevelSide.SUPPORT:
            return below
        if lv.side is LevelSide.RESISTANCE:
            return above
        return above or below                     # AXIS works both ways

    def _kill(self, lid: str, reason: str, i: int) -> None:
        lv = (self.book.live.pop(lid, None) or self.book.dormant.pop(lid, None)
              or self.book.rounds.pop(lid, None))
        if lv is None:
            return
        self.book.dead[lid] = replace(lv, state=LevelState.DEAD, death_reason=reason)
        if lid == self.axis_id:
            self.axis_id = None
        self.events.append({"at": i, "event": "died", "id": lid, "reason": reason,
                            "price": lv.body_edge, "grade": lv.grade.value})

    # ── 9b. dormancy — spec 03 §8b ──────────────────────────────────────────
    def _dormancy(self, candle: Candle, i: int, atr20: Decimal | None) -> None:
        """*"Distance is the reason to REMEMBER a level, not to forget it."*

        v1 killed anything beyond 25 x ATR, so the engine deleted a level precisely
        because price had travelled away from it — and had nothing left when price came
        back. Only distance causes dormancy; exhaustion, acceptance and expiry still kill
        outright, because those mean the level stopped being real.
        """
        if atr20 is None or not bool(self._p("dormant_pool_enabled")):
            return
        sleep_at = self._d("dormancy_distance_atr_mult") * atr20
        wake_at = self._d("revival_distance_atr_mult") * atr20
        min_grade = GRADE_ORDER[Grade(str(self._p("dormant_min_grade_at_sleep")))]
        pool_max = int(self._p("dormant_pool_max"))
        max_age = timedelta(minutes=int(self._p("dormant_max_age_minutes")))

        for lid, lv in list(self.book.live.items()):
            if lv.kind is LevelKind.ANCHOR:
                continue                                   # anchors are never far away
            if abs(candle.c - lv.body_edge) <= sleep_at:
                continue
            if GRADE_ORDER[lv.grade] < min_grade:
                self._kill(lid, "irrelevant", i)           # Grade C dies properly
                continue
            self.book.dormant[lid] = replace(self.book.live.pop(lid), state=LevelState.DORMANT)
            self.events.append({"at": i, "event": "dormant", "id": lid,
                                "price": lv.body_edge, "grade": lv.grade.value})

        for lid, lv in list(self.book.dormant.items()):
            if candle.open_time - lv.born_at > max_age:
                self._kill(lid, "expired_dormant", i)
                continue
            if abs(candle.c - lv.body_edge) <= wake_at:
                # D-011d: revived with touches and born_at INTACT. A level tested twice
                # before it slept is on its third touch when price returns, and the third
                # touch is where the system stops taking reversals.
                self.book.live[lid] = replace(self.book.dormant.pop(lid),
                                              state=LevelState.ALIVE)
                self.events.append({"at": i, "event": "revived", "id": lid,
                                    "price": lv.body_edge, "touches": lv.touches,
                                    "grade": lv.grade.value})

        if len(self.book.dormant) > pool_max:
            for lid, _ in sorted(self.book.dormant.items(),
                                 key=lambda kv: kv[1].born_at)[:len(self.book.dormant) - pool_max]:
                self._kill(lid, "dormant_pool_full", i)

    # ── 10. the cap ─────────────────────────────────────────────────────────
    def _apply_cap(self, candle: Candle) -> None:
        """Spec 03 §8b + D-006. Eight lines is a risk control, not a preference: a book
        that grows unbounded always has a level near price, so ALERT never switches off.

        Round numbers do not count against the cap (spec 03 §6) — they are the densest
        thing on the chart and would otherwise fill it.
        """
        cap = int(self._p("max_active_levels"))
        counted = dict(self.book.live)          # rounds are excluded by construction now
        if len(counted) <= cap:
            self.book.active_ids = tuple(counted)
            return

        keep: list[str] = []

        def add(lid: str | None) -> None:
            if lid and lid in counted and lid not in keep and len(keep) < cap:
                keep.append(lid)

        # 1. the 2 nearest above and 2 nearest below current price
        above = sorted((lv for lv in counted.values() if lv.body_edge > candle.c),
                       key=lambda x: x.body_edge - candle.c)
        below = sorted((lv for lv in counted.values() if lv.body_edge <= candle.c),
                       key=lambda x: candle.c - x.body_edge)
        for lv in above[:2]:
            add(lv.id)
        for lv in below[:2]:
            add(lv.id)
        # 2. the current BREAK axis
        add(self.axis_id)
        # 3. day high / day low
        for lv in counted.values():
            if self.day_high is not None and lv.wick_tip == self.day_high:
                add(lv.id)
            if self.day_low is not None and lv.wick_tip == self.day_low:
                add(lv.id)
        # 4. highest-grade remainder. D-006 tie-break: grade, then newer wins.
        for lv in sorted(counted.values(),
                         key=lambda x: (-GRADE_ORDER[x.grade], -x.born_at.timestamp())):
            add(lv.id)

        self.book.active_ids = tuple(keep)

    # ── 11. obstacles ───────────────────────────────────────────────────────
    def obstacles(self, price: Decimal, direction: Literal["up", "down"]) -> list[Obstacle]:
        """Everything in the way, sorted by distance, each tagged with its strength.

        Spec 03 §9. The space GATE takes the nearest with `gates_space`; T1 placement
        takes the nearest of any strength. Two questions, two answers — v1 collapsed them
        and let a 100-mark veto trades on the entry price's last two digits.
        """
        strengths = self.cfg.get("levels.obstacle_strength")
        out: list[Obstacle] = []

        def push(p: Decimal, key: str, source: str, level: Level | None = None) -> None:
            if (direction == "up" and p <= price) or (direction == "down" and p >= price):
                return
            out.append(Obstacle(p, ObstacleStrength(strengths[key]), source, level))

        for lv in list(self.book.live.values()) + list(self.book.rounds.values()):
            if lv.is_round_number:
                major = int(self._p("round_number_major_grid"))
                push(lv.body_edge, "round_500" if lv.body_edge % major == 0 else "round_100",
                     "round_number", lv)
                continue
            key = {Grade.A: "grade_a_level", Grade.B: "grade_b_level",
                   Grade.C: "grade_c_level"}[lv.grade]
            push(lv.body_edge, key, f"{lv.kind.value}_{lv.grade.value}", lv)

        if self.day_high is not None:
            push(self.day_high, "day_high_low", "day_high")
        if self.day_low is not None:
            push(self.day_low, "day_high_low", "day_low")
        if self.pdh is not None:
            push(self.pdh, "pdh_pdl", "PDH")
        if self.pdl is not None:
            push(self.pdl, "pdh_pdl", "PDL")

        out.sort(key=lambda o: abs(o.price - price))
        return out

    def space_obstacle(self, price: Decimal, direction: Literal["up", "down"]) -> Obstacle | None:
        return next((o for o in self.obstacles(price, direction) if o.gates_space), None)

    def t1_obstacle(self, price: Decimal, direction: Literal["up", "down"]) -> Obstacle | None:
        obstacles = self.obstacles(price, direction)
        return obstacles[0] if obstacles else None
