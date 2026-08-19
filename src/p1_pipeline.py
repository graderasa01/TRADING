"""
The P1 pipeline — steps 1 to 4 of CLAUDE.md §3, wired together.

    1m candle closes
      1  Aggregator      -> 5m / 15m closed candles and partials
      2  LevelEngine     -> birth / test / grade / kill levels
      3  StructureEngine -> swings, BOS, trend, regime
      4  StateBoard      -> the 8 variables

Steps 5 onward — guards, modes, setups, risk, options, exits — are P2 and later. This
class exists so P1 can be run end to end and measured, and so the P1.5 tooling has one
thing to call.

**It cannot produce a Signal and it must not learn to.** The engine orchestrator in
`src/engine.py` is where the full pipeline lands; keeping this separate means the
P1.5 teaching loop can replay a session without any of the trading machinery existing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.config.loader import Config
from src.domain.models import Candle, LevelKind
from src.feed.aggregator import Aggregator, BarUpdate
from src.feed.replay_feed import Session
from src.indicators.atr import AtrBook
from src.journey.ladder import Journey, JourneyTracker, anchor_walls
from src.levels.engine import LevelEngine
from src.state.board import BoardBuilder, StateBoard
from src.structure.engine import StructureEngine


@dataclass
class CandleRecord:
    """Everything the engine knew at one candle. Spec 13 §2's reasoning record is
    rendered from this — every field is already computed, it was just never written."""
    index: int
    candle: Candle
    board: StateBoard
    anticipation: str
    bar: BarUpdate
    new_levels: list[str] = field(default_factory=list)
    dead_levels: list[str] = field(default_factory=list)
    new_journeys: list[Journey] = field(default_factory=list)


class P1Pipeline:
    def __init__(self, config: Config, session: Session) -> None:
        self.cfg = config
        self.session = session
        self.agg = Aggregator()
        self.atr = AtrBook()
        self.levels = LevelEngine(config, session.symbol,
                                  session.pdh, session.pdl, session.pdc)
        self.structure = StructureEngine(config)
        self.journeys = JourneyTracker(config)
        self.board_builder = BoardBuilder(config, self.levels, self.structure, self.journeys)
        self.records: list[CandleRecord] = []

    def on_candle(self, candle: Candle) -> CandleRecord:
        bar = self.agg.on_candle(candle)
        self.atr.on_1m(candle)
        if bar.m5:
            self.atr.on_5m(bar.m5)

        before_live = set(self.levels.book.live)
        events_before = len(self.levels.events)

        self.levels.on_candle(candle, self.atr.atr20_1m, bar.m5, bar.m15)
        self.structure.on_candle(candle, bar.m5, bar.m15_partial, self.atr.atr20_1m)
        self._spawn_journeys(candle, events_before)
        if bar.m5:
            self.journeys.on_5m_close(bar.m5, self.atr.atr20_1m)

        board = self.board_builder.build(candle, self.atr.atr_1m,
                                         self.atr.atr20_1m, self.atr.atr_5m)
        record = CandleRecord(
            index=len(self.records), candle=candle, board=board,
            anticipation=self.board_builder.anticipation(board), bar=bar,
            new_levels=sorted(set(self.levels.book.live) - before_live),
            dead_levels=[str(e["id"]) for e in self.levels.events[events_before:]
                         if e["event"] == "died"])
        self.records.append(record)
        return record

    def _spawn_journeys(self, candle: Candle, events_before: int) -> None:
        """A Journey on every break of a real level — spec 04 §6b.

        D-011b: this is written to the journal and read by nothing that can trade.
        `test_journey_never_read_by_the_trading_path` enforces that statically.
        """
        for event in self.levels.events[events_before:]:
            if event["event"] != "born" or event["kind"] != "break":
                continue
            axis = self.levels.book.live.get(str(event["id"]))
            if axis is None:
                continue
            direction = "up" if candle.c > axis.body_edge else "down"
            ahead = [lv for lv in self.levels.book.live.values()
                     if lv.id != axis.id and lv.kind is not LevelKind.BREAK]
            ahead += list(self.levels.book.dormant.values())
            origin = self._move_origin(direction)
            self.journeys.on_break(
                broken=axis, axis=axis, candle=candle, direction=direction,
                levels_ahead=ahead,
                anchors=anchor_walls(self.levels.pdh, self.levels.pdl,
                                     self.levels.day_high, self.levels.day_low,
                                     list(self.levels.book.rounds.values())),
                move_origin=origin,
                broken_range_width=self._range_width())

    def _move_origin(self, direction: str) -> tuple[Decimal, str] | None:
        """D2 — *"jahan se aaya"*. The swing the previous move came from.

        This is the rung spec 09 §3.2c scores, and the one that encodes the trader's core
        belief about this market. It has never been measured.
        """
        swings = self.structure.swings["5m"]
        source = swings["high"] if direction == "up" else swings["low"]
        if not source:
            return None
        swing = source[-1]
        return swing.price, f"origin of the {swing.time:%H:%M} 5m move"

    def _range_width(self) -> Decimal | None:
        highs = self.structure.swings["5m"]["high"]
        lows = self.structure.swings["5m"]["low"]
        if not highs or not lows:
            return None
        return abs(highs[-1].price - lows[-1].price)

    def run(self) -> list[CandleRecord]:
        for candle in self.session.candles:
            self.on_candle(candle)
        self.journeys.close_all(self.session.candles[-1].open_time)
        return self.records
