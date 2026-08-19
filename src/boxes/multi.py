"""
Three maps, one story — 15m says WHERE, 5m says WHAT, 1m says WHEN.

## Four decisions taken here, and why

**1. Each timeframe gets its own block size, not the same twenty.**

A block is one chunk of a trader's attention. Twenty 1m candles is twenty minutes;
twenty 15m candles would be five hours, which is not the same kind of object at all. So
blocks are sized to give roughly geometric coverage:

```
1m   block 20  ->   20 minutes
5m   block 15  ->   75 minutes
15m  block 10  ->  150 minutes
```

**2. Each map keeps the same NUMBER of blocks, so its reach scales with its timeframe.**

Resolution stays constant — about 60–95 blocks — and the calendar depth falls out of the
arithmetic. A 15m map that only reaches back five days is not a 15m map; it is a 1m map
drawn badly.

**3. The three maps do not vote on direction. They answer different questions.**

`CLAUDE.md` §2 is explicit: *"15m says WHERE. 5m says WHAT. 1m says WHEN and WHERE THE
STOP GOES. 1m is never allowed to set direction."* So the 15m map contributes context and
far targets, 5m the range being worked, and **only the 1m live block is a trigger.**

**4. But their SHELVES do combine, and that is the strongest thing on the chart.**

A price where all three timeframes put a shelf is not three levels, it is one level three
scales agree on. Confluence counts timeframes, not blocks — a 15m shelf built from 4
blocks and a 1m shelf built from 40 count once each, because they are one vote from one
scale, and the 1m one is not ten times more informative for being made of smaller pieces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from src.boxes.map import Map, Zone, build_map, story
from src.domain.models import ZERO, Candle

# (block size, how many blocks the map should hold)
PLAN: dict[str, tuple[int, int]] = {"1m": (20, 95), "5m": (15, 75), "15m": (10, 60)}
ORDER = ("15m", "5m", "1m")


@dataclass
class Confluence:
    """One price several timeframes agree on."""
    low: Decimal
    high: Decimal
    tfs: set[str] = field(default_factory=set)
    blocks: int = 0

    @property
    def strength(self) -> int:
        return len(self.tfs)

    @property
    def mid(self) -> Decimal:
        return (self.low + self.high) / 2


def bars_needed(tf: str) -> int:
    size, count = PLAN[tf]
    return size * count


def build_multi(one_minute: Sequence[Candle], atr: Decimal) -> dict[str, Map]:
    """One map per timeframe. 5m and 15m come from the engine's own aggregator, so the
    bars here are the same objects the level engine would have seen — not a second
    resampling that could quietly disagree with it."""
    from src.feed.aggregator import aggregate_all

    ups = aggregate_all(one_minute, htf=("5m", "15m"))
    series = {"1m": list(one_minute),
              "5m": [u.m5 for u in ups if u.m5],
              "15m": [u.m15 for u in ups if u.m15]}

    maps: dict[str, Map] = {}
    for tf in ORDER:
        bars = series[tf]
        if not bars:
            continue
        size, count = PLAN[tf]
        # ATR is measured on the same timeframe, or a 15m block would be cut with a 1m
        # sense of scale and every shelf tolerance would be ten times too tight.
        recent = bars[-20:]
        tf_atr = sum(k.h - k.l for k in recent) / len(recent) if recent else atr
        maps[tf] = build_map(bars[-(size * count):], tf_atr, size)
    return maps


def confluence(maps: dict[str, Map], atr: Decimal,
               tolerance_atr: Decimal = Decimal("0.4"),
               min_blocks: int = 2) -> list[Confluence]:
    """Shelves from every timeframe, merged. Strength counts TIMEFRAMES, not blocks."""
    tol = max(atr * tolerance_atr, Decimal("0.05"))

    # Cluster shelf MIDPOINTS, not shelf bands.
    #
    # The first version merged bands whose edges came within tolerance, and chained them
    # exactly the way `map.merge_zones` once chained blocks: a 15m shelf is wide, it
    # touches the next one, and the result was a single "confluence" 365 points across
    # made of 172 blocks — which is not a level, it is the whole chart.
    #
    # A point cannot chain. Two shelves agree when their centres land together.
    raw: list[tuple[Decimal, Decimal, Decimal, str, int]] = []
    for tf, m in maps.items():
        for z in m.zones:
            n = len(set(z.blocks))
            if n >= min_blocks:
                raw.append(((z.low + z.high) / 2, z.low, z.high, tf, n))
    raw.sort()

    out: list[Confluence] = []
    anchor: Decimal | None = None
    for mid, lo, hi, tf, n in raw:
        if out and anchor is not None and mid - anchor <= tol:
            c = out[-1]
            c.low = min(c.low, lo)
            c.high = max(c.high, hi)
            c.tfs.add(tf)
            c.blocks += n
        else:
            out.append(Confluence(low=lo, high=hi, tfs={tf}, blocks=n))
            anchor = mid
    return out


def multi_story(maps: dict[str, Map], atr: Decimal) -> list[str]:
    """The three-timeframe read, in the order the cardinal rule sets."""
    out: list[str] = []
    price = maps["1m"].close if "1m" in maps else ZERO
    labels = {"15m": "WHERE ", "5m": "WHAT  ", "1m": "WHEN  "}

    for tf in ORDER:
        m = maps.get(tf)
        if m is None:
            continue
        live = m.live
        up = next(iter(m.above(price)), None)
        dn = next(iter(m.below(price)), None)
        out.append(
            f"{tf:>4} {labels[tf]} {len(m.blocks)} blocks, chaal {m.drift()}"
            + (f"   live {float(live.low):,.0f}-{float(live.high):,.0f}" if live else "")
            + f"   |  upar "
            + (f"{float(up.low):,.0f} (+{float(up.low - price):,.0f})" if up else "khaali")
            + "   neeche "
            + (f"{float(dn.high):,.0f} (-{float(price - dn.high):,.0f})" if dn else "khaali"))

    merged = confluence(maps, atr)
    strong = [c for c in merged if c.strength >= 2]
    out.append("")
    if strong:
        out.append("CONFLUENCE — jahan 2+ timeframe sehmat hain")
        for c in sorted(strong, key=lambda z: -z.mid)[:8]:
            gap = c.mid - price
            side = "upar" if gap > ZERO else "neeche"
            out.append(f"           {float(c.low):,.0f}-{float(c.high):,.0f}  "
                       f"{'+' if gap > ZERO else '-'}{abs(float(gap)):,.0f} pts {side}  "
                       f"[{' '.join(sorted(c.tfs, key=lambda t: ORDER.index(t)))}]  "
                       f"{c.blocks} blocks")
    else:
        out.append("CONFLUENCE — koi price nahi jispar do timeframe sehmat hon")

    # The trigger is the 1m live block, and only that. The target is allowed to come from
    # any timeframe — that is the whole point of having three maps.
    one = maps.get("1m")
    if one and one.live:
        live = one.live
        # `merged` is sorted low to high, so the NEAREST shelf below is the LAST one in
        # the list, not the first. The first version took dns[0] and reported a target
        # 2,355 points away — the lowest shelf in a month of history.
        ups = [c for c in merged if c.low > live.high]
        dns = [c for c in merged if c.high < live.low]
        dns = dns[::-1]
        out.append("")
        out.append(f"AGAR UPAR   {float(live.high):,.0f} ke upar 1m band -> "
                   + (f"target {float(ups[0].low):,.0f} "
                      f"(+{float(ups[0].low - live.high):,.0f} pts) "
                      f"[{' '.join(sorted(ups[0].tfs, key=lambda t: ORDER.index(t)))}]"
                      if ups else "khuli jagah"))
        out.append(f"AGAR NEECHE {float(live.low):,.0f} ke neeche 1m band -> "
                   + (f"target {float(dns[0].high):,.0f} "
                      f"(-{float(live.low - dns[0].high):,.0f} pts) "
                      f"[{' '.join(sorted(dns[0].tfs, key=lambda t: ORDER.index(t)))}]"
                      if dns else "khuli jagah"))
    return out


__all__ = ["PLAN", "ORDER", "Confluence", "bars_needed", "build_multi", "confluence",
           "multi_story", "Map", "Zone", "build_map", "story"]
