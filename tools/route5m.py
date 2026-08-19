#!/usr/bin/env python3
"""
route5m.py — the forward route, found in real Bank Nifty and drawn. No JavaScript.

    python tools/route5m.py
    python tools/route5m.py --budget 40

## What this page is for

`map5m.py` asked whether the 5m boxes are where a trader would draw them. This asks the
next question: **once you are standing in a box, is the road ahead described honestly?**

Four things have to be visible, and each gets its own real example rather than a
hand-built one:

```
CASE A   near edge almost touching, far edge a long way behind it
         -> FREE 5 is not "no room". It is "the first decision is 5 points away".
CASE B   next zone far away
         -> nothing to interact with yet. Watch, do not prepare.
CASE C   a PARENT boundary arrives before its own CHILD's boundary
         -> the price-ordered corridor. `NEXT` / `NEXT_MAJOR` are type labels and
            they get the order wrong here.
RETEST   a confirmed 5m break, watched on 1m: away, back, hold or fail.
```

## The selection rule is not a trading rule

To *find* an example of "near edge very close, far edge a long way behind" something has
to decide what "very close" means. The ratios below do exactly that and **they exist only
to pick a picture**. They are not in `src/`, nothing imports them, and no map, frontier or
route measurement consults them. `ZoneRoute` itself contains no ratio, no cut-off and no
score — it reports `FREE_TO_NEAR`, `ZONE_DEPTH` and `FREE_TO_FAR` and leaves the reading
to a human.

## Nothing was re-detected for this page

The 5m candles come from the repo's own `Aggregator`; the map from `build_snapshot` /
`Frontier` / `Interpreter`; the retests from `livemap/retest.py`, which reads 1m candles
and contains no detector. No threshold was changed for 5m.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.anchors import build_anchors  # noqa: E402
from src.boxes.frontier import run  # noqa: E402
from src.boxes.snapshot import build_snapshot  # noqa: E402
from src.boxes.structure import build_chain  # noqa: E402
from src.feed.aggregator import Aggregator  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.livemap.interpreter import Interpreter  # noqa: E402
from src.livemap.retest import compact as retest_line  # noqa: E402
from src.livemap.retest import observe_all, tally  # noqa: E402
from src.livemap.route import nested_stops  # noqa: E402
from tools.map5m import PAD_B, PAD_L, PAD_R, PAD_T, W, draw  # noqa: E402

DEFAULT_DAYS = ["2026-02-16", "2025-09-12", "2024-12-18", "2024-09-06", "2023-10-04"]
BARS, LIVE = 400, 60

#: PICTURE-SELECTION ONLY. See the module docstring. Nothing in `src/` reads these.
A_DEPTH_OVER_FREE = 4.0        # case A: the depth must dwarf the free space
A_FREE_ATR = 0.5               # ...and the free space must be small in ATR terms
B_FREE_OVER_DEPTH = 3.0        # case B: the free space must dwarf the depth
B_FREE_ATR = 2.0


# ─────────────────────────────────────────────────────────────────────────────
def streams(symbol: str, day: date, sessions: int = 8):
    """1m and 5m for the same sessions, so a 5m break can be watched on 1m."""
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-sessions:]
    m1, m5 = [], []
    for s in feed.sessions(days=days):
        agg = Aggregator(htf=("5m",))
        for c in s.candles:
            m1.append(c)
            u = agg.on_candle(c)
            if u.m5 is not None:
                m5.append(u.m5)
    return m1, m5


def build(symbol: str, m5, upto: int | None = None):
    """Snapshot + frontier + states, optionally stopped at a candle. Re-running rather
    than slicing keeps every drawn frame causal: nothing finalised later is on the page."""
    split = max(len(m5) - LIVE, len(m5) // 2)
    snap = build_snapshot(m5[:split], symbol)
    chain, _ = build_chain(m5[:split])
    anchors = build_anchors(chain, m5[:split])
    end = len(m5) if upto is None else upto + 1
    f = run(snap, m5[:split], m5[split:end])
    return snap, anchors, f, Interpreter(snap, f, anchors=anchors).states()


# ─────────────────────────────────────────────────────────────────────────────
def score(state) -> dict[str, float]:
    """How good an *illustration* each state is for each case. Zero means "not this case"."""
    out = {"A": 0.0, "B": 0.0, "C": 0.0}
    for side in (state.above, state.below):
        r = side.route
        if r is None:
            continue
        free, depth = float(r.free_to_near), float(r.zone_depth)
        if free > 0 and depth >= A_DEPTH_OVER_FREE * free \
                and r.free_to_near_atr <= A_FREE_ATR:
            out["A"] = max(out["A"], depth / free)
        if depth > 0 and free >= B_FREE_OVER_DEPTH * depth \
                and r.free_to_near_atr >= B_FREE_ATR:
            out["B"] = max(out["B"], r.free_to_near_atr)
        if nested_stops(side.corridor):
            out["C"] = max(out["C"], float(len(side.corridor)))
    return out


def hunt(symbol: str, days: list[date], budget: int):
    """One pass over the sessions, keeping the best example of each case."""
    best: dict[str, tuple] = {}
    scanned = []
    for day in days[:budget]:
        m1, m5 = streams(symbol, day)
        m5 = m5[-BARS:]
        if len(m5) < 200:
            continue
        _, _, f, states = build(symbol, m5)
        obs = observe_all(f.readings, m5, m1)
        scanned.append((day, len(m5), len(states), obs))
        for s in states:
            sc = score(s)
            for case, v in sc.items():
                if v > 0 and (case not in best or v > best[case][0]):
                    best[case] = (v, day, s.index)
    return best, scanned


# ─────────────────────────────────────────────────────────────────────────────
def draw_retest(m1, o) -> str:
    """The 1m aftermath of one 5m break. A candle chart and four prices, nothing else."""
    lo_i = max(0, o.start_index - 25)
    hi_i = min(len(m1), (o.resolved_index or o.start_index + o.bars_seen) + 25)
    window = m1[lo_i:hi_i]
    n = len(window)
    lo_v = float(min(min(k.l for k in window), o.brk.low))
    hi_v = float(max(max(k.h for k in window), o.brk.high))
    pad = (hi_v - lo_v) * 0.08 or 1.0
    lo_v, hi_v = lo_v - pad, hi_v + pad

    h = 320
    iw, ih = W - PAD_L - PAD_R, h - PAD_T - PAD_B
    cw = iw / max(n, 1)
    X = lambda k: PAD_L + (k + 0.5) * cw                            # noqa: E731
    Y = lambda v: PAD_T + (hi_v - float(v)) / (hi_v - lo_v) * ih    # noqa: E731
    right = PAD_L + iw
    out: list[str] = []

    # the broken 5m structure, and its own edge
    out.append(f'<rect x="{PAD_L}" y="{Y(o.brk.high):.1f}" width="{iw:.1f}" '
               f'height="{max(Y(o.brk.low) - Y(o.brk.high), 2):.1f}" '
               f'fill="var(--cluster)" fill-opacity=".10"/>')
    ye = Y(o.brk.edge)
    out.append(f'<line x1="{PAD_L}" y1="{ye:.1f}" x2="{right}" y2="{ye:.1f}" '
               f'stroke="var(--cur)" stroke-width="2.2"/>')
    out.append(f'<text x="{right - 4}" y="{ye - 5:.1f}" font-size="10" '
               f'text-anchor="end" font-weight="700" fill="var(--cur)">'
               f'5m {o.brk.structure_id} EDGE {float(o.brk.edge):,.0f}</text>')

    for k, cd in enumerate(window):
        x = X(k)
        out.append(f'<line x1="{x:.2f}" y1="{Y(cd.h):.1f}" x2="{x:.2f}" '
                   f'y2="{Y(cd.l):.1f}" stroke="currentColor" stroke-width=".9" '
                   f'stroke-opacity=".85"/>')
        yt, yb = Y(max(cd.o, cd.c)), Y(min(cd.o, cd.c))
        out.append(f'<rect x="{x - max(cw * .6, 1) / 2:.2f}" y="{yt:.1f}" '
                   f'width="{max(cw * .6, 1):.2f}" height="{max(yb - yt, .9):.1f}" '
                   f'fill="{"var(--bg)" if cd.c >= cd.o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width=".9"/>')

    marks = [(o.start_index, "var(--now)", "5m BREAK"),
             (o.extension_index, "var(--free)", "extension"),
             (o.retest_index, "var(--zone)", "retest"),
             (o.resolved_index, "var(--anchor)",
              o.rebreak_direction and f"re-break {o.rebreak_direction}")]
    for idx, colour, label in marks:
        if idx is None or not label or not (lo_i <= idx < hi_i):
            continue
        x = X(idx - lo_i)
        out.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{PAD_T + ih}" '
                   f'stroke="{colour}" stroke-width="1.3" stroke-opacity=".8"/>')
        out.append(f'<text x="{x + 3:.1f}" y="{PAD_T + 11}" font-size="9" '
                   f'fill="{colour}" font-weight="650">{label}</text>')

    for k in range(0, n, max(1, n // 8)):
        out.append(f'<text x="{X(k):.1f}" y="{h - 8}" font-size="9" '
                   f'text-anchor="middle" fill="currentColor" opacity=".45">'
                   f'{window[k].open_time:%H:%M}</text>')
    return (f'<svg viewBox="0 0 {W} {h}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


# ─────────────────────────────────────────────────────────────────────────────
CASE_TEXT = {
    "A": ("CASE A &mdash; near edge almost touching, real depth behind it",
          "<b>FREE TO FIRST is small and ZONE DEPTH is not.</b> The old single "
          "<code>SPACE</code> field reported only the first number, and read as "
          "<i>&ldquo;no room&rdquo;</i>. It means the opposite of that: the first "
          "structural contact is very close, and the route space behind it is "
          "conditional on price being accepted inside the zone."),
    "B": ("CASE B &mdash; the next zone is a long way off",
          "<b>Nothing to interact with yet.</b> The watch state says so in words rather "
          "than leaving a consumer to divide two numbers: far from the zone is "
          "<code>FAR_FROM_NEXT_ZONE</code>, and it becomes "
          "<code>APPROACHING_NEXT_ZONE</code> when price is within <b>one zone-width</b> "
          "of the near edge &mdash; the box as its own ruler, the same rule the frontier "
          "already uses for <code>LEAVING</code>. No points constant decides it."),
    "C": ("CASE C &mdash; a parent boundary arrives before its own child's",
          "<b>This is why the corridor is ordered by price, not by label.</b> "
          "<code>NEXT</code> is the nearest <i>cluster</i> and <code>NEXT_MAJOR</code> "
          "the nearest <i>range</i>: both are type labels and neither says which "
          "boundary price meets first. Read the corridor line."),
}


def case_block(symbol: str, case: str, pick, budget_note: str) -> str:
    title, prose = CASE_TEXT[case]
    if pick is None:
        return (f"<section><h2>{title}</h2><div class='miss'>No example found in the "
                f"{budget_note}. That is a finding, not a rendering failure &mdash; the "
                f"shape may be rare on 5m, and nothing was loosened to manufacture "
                f"one.</div></section>")
    _, day, index = pick
    m1, m5 = streams(symbol, day)
    m5 = m5[-BARS:]
    snap, anchors, f, states = build(symbol, m5, upto=index)
    state = states[-1]
    body = "\n".join(f"<div>{ln}</div>" for ln in state.lines())
    head = (f"{title} &middot; {day} &middot; candle {index} "
            f"({m5[index].open_time:%d %b %H:%M})")
    return (f"<section><h2>{head}</h2><div class='note'>{prose}</div>"
            f"<div class='wrap'><div class='chart'>"
            f"{draw(m5[:index + 1], snap, f, state, anchors)}</div>"
            f"<div class='state'>{body}</div></div></section>")


def retest_block(symbol: str, scanned) -> str:
    picks, counts = {}, {k: 0 for k in ("NO_RETEST", "RETEST_HELD", "RETEST_FAILED",
                                        "RETEST_UNRESOLVED")}
    rows = []
    for day, _, _, obs in scanned:
        for k, v in tally(obs).items():
            counts[k] += v
        for o in obs:
            rows.append((day, o))
            if o.outcome in ("RETEST_HELD", "RETEST_FAILED") and o.outcome not in picks:
                picks[o.outcome] = (day, o)

    tallies = " &middot; ".join(f"<b>{k}</b> {v}" for k, v in counts.items())
    out = [f"<section><h2>5m BREAK &rarr; 1m RETEST</h2>"
           f"<div class='note'><b>This is an observation, not an entry rule.</b> The 5m "
           f"break is a <code>Frontier</code> reading production code already emits; "
           f"everything after it is read off 1m candles by a module that contains no "
           f"detector. Acceptance, failure and tolerance all reuse the repo's existing "
           f"rules &mdash; two closes, <code>tol_at</code>. The only free number is the "
           f"observation horizon, and widening it changes what you see, never what the "
           f"map says.<br><br>Across the scanned sessions: {tallies}</div>"]

    for outcome in ("RETEST_HELD", "RETEST_FAILED"):
        if outcome not in picks:
            out.append(f"<div class='miss'>no {outcome} example in the scanned "
                       f"sessions</div>")
            continue
        day, o = picks[outcome]
        m1, _ = streams(symbol, day)
        body = "\n".join(f"<div>{ln}</div>" for ln in o.lines())
        out.append(f"<h3>{outcome} &middot; {day}</h3>"
                   f"<div class='wrap'><div class='chart'>{draw_retest(m1, o)}</div>"
                   f"<div class='state'>{body}</div></div>")

    if rows:
        out.append("<div class='state wide'>" + "\n".join(
            f"<div>{d} {retest_line(o)}</div>" for d, o in rows[:60]) + "</div>")
    out.append("</section>")
    return "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
def render(symbol: str, days: list[date], budget: int, out_dir: Path) -> Path:
    best, scanned = hunt(symbol, days, budget)
    note = f"{len(scanned)} scanned sessions"
    blocks = "".join(case_block(symbol, c, best.get(c), note) for c in ("A", "B", "C"))
    blocks += retest_block(symbol, scanned)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} — the forward route</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff; --cluster:#1d6fd0;
          --range:#c2760a; --cur:#c2760a; --ref:#0f9d76; --anchor:#8b5cf6;
          --now:#c0392b; --free:#0f9d76; --zone:#1d6fd0; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e9e9ec; --bg:#14161a; --cluster:#6aa8f5; --range:#f0b24a;
            --cur:#f0b24a; --ref:#4fd1a5; --anchor:#b794f6; --now:#ff7b6b;
            --free:#4fd1a5; --zone:#6aa8f5; }} }}
  body {{ font:13px/1.55 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1620px; }}
  h1 {{ font-size:17px; margin:0 0 4px; }}
  h2 {{ font-size:12.5px; margin:0 0 6px; font-weight:650;
       font-variant-numeric:tabular-nums; }}
  h3 {{ font-size:12px; margin:14px 0 6px; font-weight:650; }}
  .warn, .note, .miss {{ border-radius:7px; padding:10px 13px; margin:0 0 12px;
         font-size:12.5px; }}
  .warn {{ border:2px solid var(--cur); }}
  .note {{ border:1px solid color-mix(in srgb, currentColor 18%, transparent);
          opacity:.92; }}
  .miss {{ border:1px dashed color-mix(in srgb, currentColor 35%, transparent); }}
  section {{ border-top:1px solid color-mix(in srgb, currentColor 15%, transparent);
            padding:14px 0 4px; }}
  .wrap {{ display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap; }}
  .chart {{ flex:1 1 720px; min-width:340px; }}
  .state {{ flex:0 1 430px; font:11.5px/1.65 ui-monospace,monospace;
           white-space:pre-wrap; padding:9px 12px; border-radius:6px;
           border:1px solid color-mix(in srgb, currentColor 16%, transparent);
           overflow-x:auto; }}
  .state.wide {{ flex:1 1 100%; margin-top:12px; font-size:11px; }}
  svg {{ display:block; width:100%; height:auto; }}
  code {{ font:11.5px ui-monospace,monospace;
         background:color-mix(in srgb, currentColor 9%, transparent);
         padding:1px 4px; border-radius:3px; }}
  .g {{ color:var(--free); font-weight:650; }}
  .c {{ color:var(--zone); font-weight:650; }}
</style>
<h1>{symbol} &mdash; the forward route</h1>
<div class="warn"><b>THIS IS A MEASUREMENT PAGE, NOT A STRATEGY.</b> Every number here
describes geography. There is no entry, no stop and no target on this page, and the layer
that would produce one does not exist.<br><br>
<b>The boundary rule, restated:</b> a structure breaks at <b>its own</b> edge. The next
zone's <b>far edge is never the current breakout level</b> &mdash; it is a conditional
second boundary that matters only after price has been accepted inside that zone, and
breaking it is <i>that zone's</i> breakout, not this one's.</div>
{blocks}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"route5m_{symbol.replace(' ', '_')}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--days", nargs="+", default=DEFAULT_DAYS)
    ap.add_argument("--budget", type=int, default=25,
                    help="how many sessions to scan for examples")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "structmap"))
    args = ap.parse_args(argv)

    days = [date.fromisoformat(d) for d in args.days]
    if len(days) < args.budget:
        feed = ReplayFeed(args.symbol, on_gap="skip")
        pool = [d for d in feed.available_days() if d not in days]
        step = max(1, len(pool) // max(args.budget - len(days), 1))
        days += pool[::step][:args.budget - len(days)]

    path = render(args.symbol, days, args.budget, Path(args.out))
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
