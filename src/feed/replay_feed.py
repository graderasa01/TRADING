"""
ReplayFeed — historical 1m candles, one session at a time. Spec 01 §2 and §3.

The engine must not be able to tell replay from live, so this feed's only job is to
hand over closed `Candle` objects in order and to be honest about the gaps.

## Three behaviours that decide whether a backtest tells the truth

**Session isolation.** Sessions are yielded one at a time and the engine is reset
between them. A replay that streams December into January builds levels across an
overnight gap the market never traded through.

**Gap policy (spec 01 §3).** One missing minute is forward-filled as a zero-range
`synthetic` candle, which every detector then ignores (D-009). Two or more consecutive
missing minutes raise `FeedGapError` — never guess through a gap. The real data has
three such days in three years, so this path is rare and therefore untested unless it
is tested deliberately.

**Abbreviated sessions are skipped (D-018).** Muhurat and NSE disaster-recovery
half-days are not a market. The 2025-10-21 Muhurat session runs 13:45–14:44, entirely
inside `time.windows_normal` `[13:30, 14:45]` — without this the engine would trade a
one-hour ceremonial session as an ordinary afternoon and never mention it. Full
sessions that happen to fall on a weekend (Union Budget) are kept: they are a real
market, and dropping them invents an overnight gap on the following Monday.

Prices are converted with `Decimal(repr(x))` per D-014 — never `Decimal(float)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from src.domain.models import IST, Candle, to_decimal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SESSION_OPEN = dtime(9, 15)
SESSION_LAST_CANDLE = dtime(15, 29)
FULL_SESSION_CANDLES = 375
MAX_SYNTHETIC_RUN = 1          # params.yaml feed.synthetic_candle_max_consecutive


class FeedGapError(RuntimeError):
    """Two or more consecutive missing minutes. Never guess through a gap."""


@dataclass(frozen=True, slots=True)
class Session:
    """One trading day, ready to replay.

    `pdh`/`pdl`/`pdc` come from the **previous session that actually happened**, not
    from yesterday's calendar date. On 2026-03-04 the prior session is 2026-02-27, and
    an engine that looked up "yesterday" would find nothing and start with no anchors —
    silently, on every day after a holiday. Spec 03 §6 makes PDH/PDL/PDC Grade A while
    untested, so losing them costs the day's three most-watched levels.
    """
    symbol: str
    day: date
    candles: tuple[Candle, ...]
    prev_close: Decimal | None
    synthetic_count: int
    pdh: Decimal | None = None
    pdl: Decimal | None = None
    prev_day: date | None = None

    @property
    def pdc(self) -> Decimal | None:
        return self.prev_close

    @property
    def is_full(self) -> bool:
        return len(self.candles) == FULL_SESSION_CANDLES

    @property
    def open_gap_pct(self) -> Decimal | None:
        if self.prev_close is None or self.prev_close == 0:
            return None
        return (self.candles[0].o - self.prev_close) / self.prev_close * 100

    def __len__(self) -> int:
        return len(self.candles)


@dataclass(frozen=True, slots=True)
class SourceDay:
    """One chronological day present in the source, before replay exclusions."""

    day: date
    first: dtime
    last: dtime
    kind: str


# ─────────────────────────────────────────────────────────────────────────────
# session classification — D-018. Shared with tools/verify_data.py by rule, and
# pinned by a test so the two cannot drift apart.
# ─────────────────────────────────────────────────────────────────────────────
def classify_session(day: date, first: dtime, last: dtime) -> tuple[str, str]:
    """Returns (kind, reason). kind is 'normal' | 'abbreviated' | 'weekend_full'."""
    if first > SESSION_OPEN:
        return "abbreviated", f"off-hours session {first:%H:%M}-{last:%H:%M} (Muhurat)"
    if last < dtime(15, 0):
        return "abbreviated", f"half day, ends {last:%H:%M} (NSE DR-site test)"
    if day.weekday() >= 5:
        return "weekend_full", "full session on a weekend (Union Budget / NSE special)"
    return "normal", ""


# ─────────────────────────────────────────────────────────────────────────────
def _normalise_ts(value) -> datetime:
    ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return ts if ts.tzinfo else ts.replace(tzinfo=IST)


def _read_timestamps(path: Path) -> Iterable[datetime]:
    """Read only source timestamps; OHLC values never enter the research index."""
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        values = pq.read_table(path, columns=["ts"]).column("ts").to_pylist()
        return tuple(_normalise_ts(value).astimezone(IST) for value in values)

    import csv

    with path.open(newline="", encoding="utf-8") as fh:
        return tuple(
            _normalise_ts(row["ts"]).astimezone(IST)
            for row in csv.DictReader(fh)
        )


def _read_file(path: Path, symbol: str, *,
               wanted_days: frozenset[date] | None = None
               ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        cols = pq.read_table(path).to_pydict()
        rows = zip(cols["ts"], cols["open"], cols["high"], cols["low"],
                   cols["close"], cols["volume"])
    else:
        import csv

        with path.open(newline="", encoding="utf-8") as fh:
            rows = [(_normalise_ts(r["ts"]), r["open"], r["high"],
                     r["low"], r["close"], r["volume"]) for r in csv.DictReader(fh)]
    out = []
    for ts, o, h, l, c, v in rows:
        ts = _normalise_ts(ts).astimezone(IST)
        if wanted_days is not None and ts.date() not in wanted_days:
            continue
        out.append((ts, to_decimal(o), to_decimal(h),
                    to_decimal(l), to_decimal(c), int(v or 0)))
    return out


class ReplayFeed:
    """
        feed = ReplayFeed("NIFTY BANK")
        for session in feed.sessions(start=date(2026, 3, 1)):
            engine = Engine(...)
            for candle in session.candles:
                engine.on_candle(candle)
    """

    def __init__(self, symbol: str, data_root: Path | None = None,
                 *, skip_abbreviated: bool = True, fill_gaps: bool = True,
                 on_gap: str = "raise") -> None:
        """
        on_gap — what a multi-minute hole does to an iteration over many sessions.

          "raise" (default)  the faithful behaviour, spec 01 §3. Use it whenever a
                             specific day was asked for: if you named the day, you need
                             to know it is unusable rather than receive silence.
          "skip"             record the day in `self.skipped` and continue. Needed by
                             anything that sweeps the whole dataset — the P9 replay and
                             the session profiler — because one 6-minute hole in 2024
                             must not abort three years of validation (D-022).

        There are three such days in three years, so this path is rare, which is exactly
        why it is a named option rather than a bare try/except at each call site.
        """
        if on_gap not in ("raise", "skip"):
            raise ValueError(f"on_gap must be 'raise' or 'skip', got {on_gap!r}")
        self.symbol = symbol
        self.data_root = Path(data_root) if data_root else REPO_ROOT / "data"
        self.skip_abbreviated = skip_abbreviated
        self.fill_gaps = fill_gaps
        self.on_gap = on_gap
        self.skipped: list[tuple[date, str]] = []

    # ── loading ──
    def _data_files(self) -> list[Path]:
        folder = self.data_root / self.symbol.replace(" ", "_")
        if not folder.is_dir():
            raise FileNotFoundError(
                f"no data for {self.symbol} at {folder}. "
                f"Run: python tools/fetch_kite.py fetch --years 3")
        return [path for path in sorted(folder.iterdir())
                if path.suffix in (".parquet", ".csv")]

    def _raw_by_day(self, start: date | None, end: date | None,
                    days: Sequence[date] | None = None) -> dict[date, list]:
        by_day: dict[date, list] = {}
        wanted_days = frozenset(days) if days is not None else None
        for path in self._data_files():
            for row in _read_file(path, self.symbol, wanted_days=wanted_days):
                day = row[0].date()
                if start and day < start:
                    continue
                if end and day > end:
                    continue
                by_day.setdefault(day, []).append(row)
        return by_day

    # ── gaps ──
    def _to_candles(self, day: date, rows: list) -> tuple[list[Candle], int]:
        rows = sorted({r[0]: r for r in rows}.values(), key=lambda r: r[0])
        candles: list[Candle] = []
        synthetic = 0

        for i, (ts, o, h, l, c, v) in enumerate(rows):
            if i > 0 and self.fill_gaps:
                prev_ts = rows[i - 1][0]
                missing = int((ts - prev_ts).total_seconds() // 60) - 1
                if missing > MAX_SYNTHETIC_RUN:
                    raise FeedGapError(
                        f"{self.symbol} {day}: {missing} consecutive minutes missing after "
                        f"{prev_ts:%H:%M}. Spec 01 §3 — never guess through a gap.")
                for k in range(missing):
                    fill_ts = prev_ts + timedelta(minutes=k + 1)
                    prev_close = candles[-1].c
                    candles.append(Candle(
                        self.symbol, "1m", fill_ts, fill_ts + timedelta(minutes=1),
                        prev_close, prev_close, prev_close, prev_close,
                        volume=None, synthetic=True))
                    synthetic += 1
            candles.append(Candle(self.symbol, "1m", ts, ts + timedelta(minutes=1),
                                  o, h, l, c, v or None))
        return candles, synthetic

    # ── the public iterator ──
    def sessions(self, start: date | None = None, end: date | None = None,
                 days: Sequence[date] | None = None) -> Iterator[Session]:
        by_day = self._raw_by_day(start, end, days)
        wanted = sorted(set(days) & set(by_day)) if days is not None else sorted(by_day)
        prev_close: Decimal | None = None
        pdh: Decimal | None = None
        pdl: Decimal | None = None
        prev_day: date | None = None

        for day in wanted:
            rows = sorted(by_day[day], key=lambda r: r[0])
            kind, reason = classify_session(day, rows[0][0].time(), rows[-1][0].time())

            if kind == "abbreviated" and self.skip_abbreviated:
                self.skipped.append((day, reason))
                # prev_close is deliberately NOT advanced: an abbreviated session is not
                # the reference the next real session gaps from (D-018).
                continue

            try:
                candles, synthetic = self._to_candles(day, rows)
            except FeedGapError as exc:
                if self.on_gap == "raise":
                    raise
                self.skipped.append((day, str(exc)))
                # prev_close IS advanced here, unlike an abbreviated session: the market
                # traded that day, we simply cannot replay it honestly. The next day's
                # overnight gap is still measured against a real close.
                prev_close = rows[-1][4]
                continue

            yield Session(symbol=self.symbol, day=day, candles=tuple(candles),
                          prev_close=prev_close, synthetic_count=synthetic,
                          pdh=pdh, pdl=pdl, prev_day=prev_day)
            real = [k for k in candles if not k.synthetic]
            prev_close = candles[-1].c
            pdh = max(k.h for k in real)
            pdl = min(k.l for k in real)
            prev_day = day

    def session(self, day: date) -> Session:
        """One session, with `prev_close` resolved from the previous usable day.

        Without the look-back a single-session load reports `prev_close = None`, and the
        gap_regime guard (spec 05 §1c) silently sees no gap on every day it is handed.
        A guard that cannot fire is worse than no guard.
        """
        prior = [d for d in self.available_days(end=day) if d < day]
        wanted = ([prior[-1]] if prior else []) + [day]
        result: Session | None = None
        for s in self.sessions(days=wanted):
            if s.day == day:
                result = s
        if result is None:
            raise KeyError(f"{self.symbol} has no usable session on {day}: "
                           f"{dict(self.skipped).get(day, 'no data')}")
        return result

    def available_days(self, start: date | None = None, end: date | None = None) -> list[date]:
        """Normal + full-weekend sessions only. Cheap — reads timestamps, not candles."""
        return [source.day for source in self.source_days(start, end)
                if source.kind != "abbreviated" or not self.skip_abbreviated]

    def source_days(self, start: date | None = None,
                    end: date | None = None) -> list[SourceDay]:
        """Every chronological source day, including abbreviated session barriers."""
        spans: dict[date, tuple[dtime, dtime]] = {}
        for path in self._data_files():
            for ts in _read_timestamps(path):
                day = ts.date()
                if start and day < start:
                    continue
                if end and day > end:
                    continue
                at = ts.time()
                first, last = spans.get(day, (at, at))
                spans[day] = (min(first, at), max(last, at))
        return [
            SourceDay(day=day, first=first, last=last,
                      kind=classify_session(day, first, last)[0])
            for day, (first, last) in sorted(spans.items())
        ]
