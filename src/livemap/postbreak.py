"""
The post-break eye — the story **after** a major structure breaks.

Today `ACCEPTED_ABOVE` is the end of the story: the node is finalised, `left` is set, and
the frontier moves on to hunting the next structure. The extension, the pause, the retest,
the re-entry, the new box built on top of the old edge — all of it is in the candle stream
and described by nothing.

```
STRUCTURE -> BREAK EVENT -> BREAK EPISODE
                 |
   EXTENDING / PAUSING / ROTATING / RETESTING / REENTERING / FORMING_NEW_STRUCTURE
                 |
           NEXT ACCEPTED BREAK
```

Measured over 29 replay blocks: **578 episodes covering 8,226 of 8,700 candles (95%)**,
median 9 candles, p90 30, max 99. It is an observation layer and reaches no conclusion.

## A pure consumer, and why that matters here

`Frontier` is not modified and knows nothing about this module. Everything below is read
off a finished `Frontier` — its readings, its two logs, its candles — the same shape
`eye.py` and `breaks.py` already take. Living in `src/livemap/` also puts it inside
`test_livemap_quarantine.py` in both directions, so *"post-break state does not reach the
Trader Reader"* is structural rather than a rule someone has to remember.

## Four locks, and where each one lives

```
L1  trigger        only an accepted major break starts an episode      BREAK_KIND
L2  new structure  a revisited historical structure is NOT a new one   _forming()
L3  live ends_at   the identity carries no future                      BreakEpisode
L4  causal         one candle at a time, no list of future breaks      PostBreakObserver
```

### L1 — the trigger

Episodes come from `breaks.from_logs()`, which admits one event kind and only one.
`Reading.interaction` is never read to find a break: it is presentation, it is overwritten
on its own candle in 21% of cases, and a source built on it loses one break in five.

`MICRO_BREAK` cannot start an episode either, and structurally: micro events never enter
`log` or `live_log` at all. Phase B kept them on `Reading.micro` and the observer's own
history, so there is no path from a micro to this module's break source.

### L2 — a revisit is not a new structure

The obvious rule — *"the frontier holds a node that is not the broken one"* — is wrong.
Price leaving `C21` and walking back into `C13`, a structure the map has had all along, is
a **revisit**. Measured, that rule called 1,837 candles `FORMING_NEW_STRUCTURE` where the
correct one calls 1,213: **a third of them were a revisited historical structure.**

A4's `Reading.node_status` already separates the two — `PROVISIONAL` when the frontier
minted the node, `HISTORICAL` when it adopted one the map already knew — so no new
detector is needed. See `_forming()`.

### L3 and L4 — nothing here may see the next candle

`BreakEpisode` has **no `ends_at`**. An episode's end is the next accepted break, which has
not happened while the episode is live; putting it on the identity would give every state
referencing that identity a fact from the future. The end lives on `EpisodeSpan`, built by
`spans()` after a full replay and never touched by the observer.

`PostBreakObserver` is fed one candle at a time and holds no list of future breaks, the
same shape `MicroObserver` has. `observe(..., upto=k)` is therefore prefix-equal to
`observe(...)[:k+1]`, which is the whole no-look-ahead guarantee in one assertion.

## Every rule reused, none introduced

```
beyond / contact / extension / failure   livemap/retest.py, verbatim
BREAK_CLOSES                             boxes/structure.py
tol_at                                   boxes/structure.py
traverses / MIN_TRAVERSES                boxes/adaptive.py
node_status PROVISIONAL | HISTORICAL     boxes/frontier.py  (A4)
break source                             livemap/breaks.py
```

**No new number is introduced anywhere in this module.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from src.boxes.adaptive import MIN_TRAVERSES, traverses
from src.boxes.frontier import (
    PROVISIONAL, STRUCTURE_CANDIDATE, Frontier, Reading)
from src.boxes.snapshot import MapSnapshot
from src.boxes.structure import BREAK_CLOSES, atr_at, tol_at
from src.domain.models import ZERO, Candle
from src.livemap.breaks import BreakRecord, from_logs

# ── the closed vocabulary ────────────────────────────────────────────────────
#
# Persistent situations, not one-shot events: each candle answers *"where is this story
# now"*, the way `LEAVING`, `MICRO_RANGE` and `RANGE_INTERIOR` already do. The transitions
# are recoverable for free — Phase C's `Transition` fires whenever a tracked field changes.
EXTENDING = "EXTENDING"
PAUSING = "PAUSING"
ROTATING = "ROTATING"
RETESTING = "RETESTING"
REENTERING = "REENTERING"
FORMING_NEW_STRUCTURE = "FORMING_NEW_STRUCTURE"

EPISODE_STATES = frozenset({EXTENDING, PAUSING, ROTATING, RETESTING, REENTERING,
                            FORMING_NEW_STRUCTURE})

#: Evaluated most specific first. The order is the design: a pause never becomes a new
#: structure, and contact with the episode's own edge outranks a box somewhere else.
PRECEDENCE = (REENTERING, RETESTING, FORMING_NEW_STRUCTURE, EXTENDING, ROTATING, PAUSING)


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class BreakEpisode:
    """The broken structure, frozen at the moment it broke.

    Immutable by type. **There is deliberately no `ends_at`** — see the module docstring.
    """

    id: str                         # "E17"
    broken_id: str
    broken_edge: Decimal
    broken_low: Decimal
    broken_high: Decimal
    direction: str                  # up | down
    break_index: int
    break_at: datetime
    source: str                     # frozen | live — which map owned the structure
    #: `cluster` | `range`, copied off the broken node. A copy, never a classification.
    kind: str = ""
    #: Whether `Reading.interaction` named this break. `False` for the 21% it did not;
    #: kept as evidence rather than as a thing anything branches on.
    named_by_interaction: bool = True
    #: What a revisited structure had accumulated when it broke. Empty otherwise.
    evidence: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise ValueError(f"direction must be up|down, got {self.direction!r}")

    @property
    def band(self) -> str:
        return f"{float(self.broken_low):,.0f}-{float(self.broken_high):,.0f}"

    def beyond(self, price: Decimal) -> Decimal:
        """How far `price` sits past the broken edge, in the break's direction.

        `retest.py`'s own helper, so *"outside"* means the same thing on 5m as on 1m.
        Negative means price is back inside the structure that broke.
        """
        return ((price - self.broken_edge) if self.direction == "up"
                else (self.broken_edge - price))


@dataclass(frozen=True, slots=True)
class EpisodeSpan:
    """An episode paired with the break that ended it.

    **Offline only.** `ends_at` is the next accepted break's index, which does not exist
    while the episode is live, so this is built by `spans()` after a full replay and is
    never referenced by the observer or by any `EpisodeState`.
    """

    episode: BreakEpisode
    ends_at: int | None = None

    @property
    def length(self) -> int | None:
        return None if self.ends_at is None else self.ends_at - self.episode.break_index


@dataclass(frozen=True, slots=True)
class EpisodeState:
    """One candle of a post-break story. Every field is a measurement."""

    index: int
    at: datetime
    price: Decimal
    episode: BreakEpisode
    state: str
    bars_since_break: int

    # ── where price is relative to the broken edge ───────────────────────────
    beyond: Decimal = ZERO          # signed; negative means back inside
    beyond_atr: float = 0.0
    new_extreme: bool = False       # a new post-break extreme THIS candle
    max_excursion: Decimal = ZERO   # running, in the break direction
    # ── the episode's own territory ──────────────────────────────────────────
    span_low: Decimal | None = None
    span_high: Decimal | None = None
    traverses: int = 0
    # ── the return leg ───────────────────────────────────────────────────────
    closes_back: int = 0            # consecutive closes back through the edge
    returned_inside: bool = False   # ever
    contacted: bool = False         # ever within tol of the edge
    retest_depth: Decimal = ZERO    # deepest penetration back through it
    # ── carried, never re-derived ────────────────────────────────────────────
    micro_id: str | None = None
    micro_low: Decimal | None = None
    micro_high: Decimal | None = None
    micro_state: str | None = None
    micro_view: str | None = None
    new_structure_id: str | None = None

    def __post_init__(self) -> None:
        if self.state not in EPISODE_STATES:
            raise ValueError(
                f"unknown episode state {self.state!r}. Add it to EPISODE_STATES first — "
                f"and if it names a trade rather than an observation, it does not belong "
                f"in this layer at all.")

    def lines(self) -> list[str]:
        e = self.episode
        out = [f"BROKEN        {e.broken_id}  {e.band}   "
               f"BREAK {e.direction.upper()} {float(e.broken_edge):,.0f}",
               f"EPISODE       {e.id}   state = {self.state}   "
               f"{self.bars_since_break} bars"]
        out.append(f"BEYOND        {float(self.beyond):+,.0f} pts "
                   f"({self.beyond_atr:+.1f} ATR)"
                   + ("   new extreme" if self.new_extreme else ""))
        if self.contacted:
            out.append(f"RETEST        depth {float(self.retest_depth):,.0f} pts"
                       + ("   returned inside" if self.returned_inside else ""))
        if self.micro_id:
            out.append(f"  └─ MICRO    {self.micro_id}  "
                       f"{float(self.micro_low):,.0f}-{float(self.micro_high):,.0f}  "
                       f"{self.micro_view}")
        if self.new_structure_id:
            out.append(f"NEW           {self.new_structure_id}")
        return out


# ─────────────────────────────────────────────────────────────────────────────
class PostBreakObserver:
    """Fed one candle at a time, exactly as `MicroObserver` is.

    It holds the current episode and its running evidence, and **no list of future
    breaks**. A new break arrives on the candle it happens; nothing consults what comes
    next. That is L4, and it is what makes `observe(upto=k)` prefix-equal to a full run.
    """

    __slots__ = ("tol_atr", "break_closes", "episode", "_n", "_span_low", "_span_high",
                 "_max_excursion", "_closes_back", "_returned", "_contacted", "_depth",
                 "_minted")

    def __init__(self, *, tol_atr: Decimal = Decimal("0.25"),
                 break_closes: int = BREAK_CLOSES) -> None:
        self.tol_atr = tol_atr
        self.break_closes = break_closes
        self.episode: BreakEpisode | None = None
        self._n = 0
        self._reset()

    def _reset(self) -> None:
        self._span_low: Decimal | None = None
        self._span_high: Decimal | None = None
        self._max_excursion = ZERO
        self._closes_back = 0
        self._returned = False
        self._contacted = False
        self._depth = ZERO
        #: Ids the frontier was seen to MINT inside this episode — the causal witness for
        #: `FORMING_NEW_STRUCTURE`. Forward-only: an id enters it on the candle its
        #: `NEW_*` interaction is observed, never before.
        self._minted: set[str] = set()

    # ── the one thing that starts a story ───────────────────────────────────
    def _open(self, brk: BreakRecord) -> BreakEpisode:
        self._n += 1
        self._reset()
        return BreakEpisode(
            id=f"E{self._n:02d}", broken_id=brk.structure_id, broken_edge=brk.edge,
            broken_low=brk.low, broken_high=brk.high, direction=brk.direction,
            break_index=brk.index, break_at=brk.at, source=brk.source, kind=brk.kind,
            named_by_interaction=brk.named_by_interaction,
            evidence=dict(brk.evidence))

    # ── L2 ──────────────────────────────────────────────────────────────────
    def _forming(self, reading: Reading, episode: BreakEpisode) -> str | None:
        """The id of a structure this break's aftermath built, or `None`.

        A revisited historical structure is **not** one. `Reading.node_status` is A4's own
        distinction — `PROVISIONAL` when the frontier minted the node, `HISTORICAL` when it
        adopted one the map already had — so this needs no detector of its own.

        The `_minted` check is the causal witness the lock asks for: the id must have been
        seen being born, inside this episode, on a candle already observed.
        """
        if reading.state == STRUCTURE_CANDIDATE:
            return reading.node_id or STRUCTURE_CANDIDATE
        if (reading.node_id is not None
                and reading.node_id != episode.broken_id
                and reading.node_status == PROVISIONAL
                and reading.node_id in self._minted):
            return reading.node_id
        return None

    # ── the loop ────────────────────────────────────────────────────────────
    def on_candle(self, reading: Reading, candle: Candle,
                  candles: Sequence[Candle],
                  brk: BreakRecord | None = None) -> EpisodeState | None:
        """One candle. `brk` is the break record **at this candle**, if any.

        Returns `None` before the first break of the run — there is no story to tell yet.
        """
        if brk is not None:
            self.episode = self._open(brk)
        episode = self.episode
        if episode is None:
            return None

        # the frontier minting is witnessed as it happens, never inferred afterwards
        if reading.interaction.startswith("NEW_") and reading.node_id:
            self._minted.add(reading.node_id)

        i, price = reading.index, candle.c
        beyond = episode.beyond(price)
        up = episode.direction == "up"

        # extension — retest.py's own "hold": a new extreme in the break's direction
        far = episode.beyond(candle.h if up else candle.l)
        new_extreme = far > self._max_excursion
        if new_extreme:
            self._max_excursion = far

        self._span_low = candle.l if self._span_low is None else min(self._span_low,
                                                                     candle.l)
        self._span_high = candle.h if self._span_high is None else max(self._span_high,
                                                                       candle.h)

        # contact — retest.py's own rule: price trades back into the edge's tol skirt
        tol = tol_at(candles, i, self.tol_atr)
        near = episode.beyond(candle.l if up else candle.h)
        contact = near <= tol
        if contact:
            self._contacted = True
            self._depth = max(self._depth, max(ZERO, -near))

        # failure — retest.py's own rule, which is the repo's acceptance rule reversed
        inside = (price < episode.broken_edge) if up else (price > episode.broken_edge)
        self._closes_back = self._closes_back + 1 if inside else 0
        reentered = self._closes_back >= self.break_closes
        if reentered:
            self._returned = True

        rot = 0
        if (self._span_low is not None and self._span_high is not None
                and self._span_high > self._span_low):
            rot = traverses(candles[episode.break_index:i + 1],
                            self._span_low, self._span_high)

        new_id = self._forming(reading, episode)

        state = (REENTERING if reentered else
                 RETESTING if contact else
                 FORMING_NEW_STRUCTURE if new_id else
                 EXTENDING if new_extreme else
                 ROTATING if rot >= MIN_TRAVERSES else
                 PAUSING)

        atr = atr_at(candles, i)
        m = reading.micro
        return EpisodeState(
            index=i, at=candle.close_time, price=price, episode=episode, state=state,
            bars_since_break=i - episode.break_index,
            beyond=beyond, beyond_atr=float(beyond / atr) if atr > ZERO else 0.0,
            new_extreme=new_extreme, max_excursion=self._max_excursion,
            span_low=self._span_low, span_high=self._span_high, traverses=rot,
            closes_back=self._closes_back, returned_inside=self._returned,
            contacted=self._contacted, retest_depth=self._depth,
            micro_id=m.micro_id if m else None,
            micro_low=m.micro_low if m else None,
            micro_high=m.micro_high if m else None,
            micro_state=m.micro_state if m else None,
            micro_view=m.view if m else None,
            new_structure_id=new_id)


# ─────────────────────────────────────────────────────────────────────────────
def observe(frontier: Frontier, snapshot: MapSnapshot | None = None, *,
            upto: int | None = None,
            tol_atr: Decimal | None = None) -> list[EpisodeState]:
    """Fold the observer over a frontier's readings. Causal: `upto=k` is prefix-equal to a
    full run truncated at `k`."""
    records = {r.index: r for r in from_logs(frontier, snapshot)}
    observer = PostBreakObserver(
        tol_atr=frontier.tol_atr if tol_atr is None else tol_atr,
        break_closes=frontier.break_closes)
    out: list[EpisodeState] = []
    for reading in frontier.readings:
        if upto is not None and reading.index > upto:
            break
        state = observer.on_candle(reading, frontier.candles[reading.index],
                                   frontier.candles, records.get(reading.index))
        if state is not None:
            out.append(state)
    return out


def episodes(frontier: Frontier,
             snapshot: MapSnapshot | None = None) -> list[BreakEpisode]:
    """One episode per accepted break, in candle order."""
    seen: dict[str, BreakEpisode] = {}
    for state in observe(frontier, snapshot):
        seen.setdefault(state.episode.id, state.episode)
    return list(seen.values())


def spans(frontier: Frontier, snapshot: MapSnapshot | None = None) -> list[EpisodeSpan]:
    """**Offline only.** Pairs each episode with the break that ended it.

    Uses the *next* episode's break index, which is exactly the future the live path may
    not see — which is why it lives here and not on `BreakEpisode`.
    """
    found = episodes(frontier, snapshot)
    return [EpisodeSpan(e, nxt.break_index if nxt else None)
            for e, nxt in zip(found, list(found[1:]) + [None])]


def compact(state: EpisodeState) -> str:
    """One line per candle, for a scrollable trace."""
    e = state.episode
    micro = (f"{state.micro_view or ''} {state.micro_id or ''}".strip() or "—")
    return (f"c{state.index:<4} {float(state.price):>9,.1f}  {e.id} {e.broken_id:<4} "
            f"{e.direction:<4} {state.state:<22} {state.bars_since_break:>3}b "
            f"{float(state.beyond):>+8,.0f}  {micro}")


__all__ = ["EXTENDING", "PAUSING", "ROTATING", "RETESTING", "REENTERING",
           "FORMING_NEW_STRUCTURE", "EPISODE_STATES", "PRECEDENCE", "BreakEpisode",
           "EpisodeSpan", "EpisodeState", "PostBreakObserver", "observe", "episodes",
           "spans", "compact"]
