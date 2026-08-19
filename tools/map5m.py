#!/usr/bin/env python3
"""
map5m.py — the 5-minute structural map, drawn. No JavaScript.

    python tools/map5m.py
    python tools/map5m.py --days 2026-02-16 --bars 400

## Why this page exists

Every claim made about 5m so far has been statistical: 2.0 structures per session
against 9.8 on 1m, the same width in ATR, five times the clock duration. Those are
numbers about a map nobody has looked at.

This is the audit. **Before any 5m → 1m execution layer is worth building, the 5m map
has to survive the same question the 1m map already passed:** can a trader read the
market's story off it, and are the boxes where a trader would draw them?

If the 5m boxes are ugly, an execution layer built on them is wasted work.

## What is drawn

Nothing is re-detected for this page. The 5m candles come from the repo's own
`Aggregator` on the 09:15 grid; the map comes from the same `build_snapshot` /
`Frontier` / `Interpreter` the 1m film uses, with **no threshold changed for 5m**.

* blue boxes — clusters, drawn across the candles they actually describe
* amber outline — ranges (there are very few; that is a finding, not a bug)
* purple rays — anchors with no box on them
* solid amber lines — the current structure's OWN edges: the break levels
* dashed green — the next structural reference above and below
* red line — the live candle
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
from src.boxes.structure import STRUCTURE_KINDS, build_chain  # noqa: E402
from src.feed.aggregator import Aggregator  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.livemap.interpreter import Interpreter  # noqa: E402

W, H = 1400, 560
PAD_L, PAD_R, PAD_T, PAD_B = 74, 20, 14, 30
DEFAULT_DAYS = ["2026-02-16", "2025-09-12", "2024-12-18", "2024-09-06", "2023-10-04"]


def five_minute(symbol: str, day: date, sessions: int = 8):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-sessions:]
    out = []
    for s in feed.sessions(days=days):
        agg = Aggregator(htf=("5m",))
        for c in s.candles:
            u = agg.on_candle(c)
            if u.m5 is not None:
                out.append(u.m5)
    return out


#: The route column lives inside the plot, hard against the right edge, so the corridor
#: reads top-to-bottom next to the live candle without covering the price action.
COL_W = 150


def route_layer(state, Y, right) -> list[str]:
    """The forward route, drawn as a column: free space, then the zone, then its far side.

    ```
    CURRENT
        |     free space          pale, and it is genuinely free
    NEAR EDGE                     solid — the first structural decision
        |     zone depth          filled — conditional route space
    FAR EDGE                      dashed — only after acceptance inside
    ```

    Nothing here is a target and nothing here is a break level. The current structure's
    own edges are still the only solid amber lines on the page.
    """
    out: list[str] = []
    x0 = right - COL_W
    for side in (state.above, state.below):
        r = side.route
        if r is None:
            continue
        y_edge, y_near, y_far = Y(r.origin_edge), Y(r.near_edge), Y(r.far_edge)

        a, b = sorted((y_edge, y_near))
        out.append(f'<rect x="{x0:.1f}" y="{a:.1f}" width="{COL_W - 8}" '
                   f'height="{max(b - a, 1):.1f}" fill="var(--free)" '
                   f'fill-opacity=".20"/>')
        out.append(f'<text x="{x0 + 5:.1f}" y="{(a + b) / 2 + 3.5:.1f}" font-size="9" '
                   f'fill="var(--free)" font-weight="650">FREE '
                   f'{float(r.free_to_near):,.0f}</text>')

        a, b = sorted((y_near, y_far))
        out.append(f'<rect x="{x0:.1f}" y="{a:.1f}" width="{COL_W - 8}" '
                   f'height="{max(b - a, 1):.1f}" fill="var(--zone)" '
                   f'fill-opacity=".22" stroke="var(--zone)" stroke-width="1"/>')
        out.append(f'<text x="{x0 + 5:.1f}" y="{(a + b) / 2 + 3.5:.1f}" font-size="9" '
                   f'fill="var(--zone)" font-weight="650">{r.id} DEPTH '
                   f'{float(r.zone_depth):,.0f}</text>')

        out.append(f'<line x1="{PAD_L}" y1="{y_near:.1f}" x2="{right}" '
                   f'y2="{y_near:.1f}" stroke="var(--zone)" stroke-width="1.6"/>')
        out.append(f'<text x="{x0 - 6:.1f}" y="{y_near - 3:.1f}" font-size="9.5" '
                   f'text-anchor="end" font-weight="700" fill="var(--zone)">'
                   f'NEAR {float(r.near_edge):,.0f} · {r.watch}</text>')
        out.append(f'<line x1="{PAD_L}" y1="{y_far:.1f}" x2="{right}" y2="{y_far:.1f}" '
                   f'stroke="var(--zone)" stroke-width="1.1" stroke-opacity=".55" '
                   f'stroke-dasharray="3 4"/>')
        out.append(f'<text x="{x0 - 6:.1f}" y="{y_far - 3:.1f}" font-size="9" '
                   f'text-anchor="end" fill="var(--zone)" opacity=".8">'
                   f'FAR {float(r.far_edge):,.0f} (conditional)</text>')

    # the corridor: every boundary ahead, in price order, labelled with whose it is
    for stop in tuple(state.above.corridor) + tuple(state.below.corridor):
        y = Y(stop.price)
        out.append(f'<line x1="{right - 14:.1f}" y1="{y:.1f}" x2="{right}" '
                   f'y2="{y:.1f}" stroke="var(--zone)" stroke-width="1.4"/>')
    return out


def draw(candles, snap, frontier, state, anchors) -> str:
    n = len(candles)
    lo_v = float(min(k.l for k in candles))
    hi_v = float(max(k.h for k in candles))
    pad = (hi_v - lo_v) * 0.05 or 1.0
    lo_v, hi_v = lo_v - pad, hi_v + pad

    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    cw = iw / max(n, 1)
    X = lambda k: PAD_L + (k + 0.5) * cw                            # noqa: E731
    Y = lambda v: PAD_T + (hi_v - float(v)) / (hi_v - lo_v) * ih    # noqa: E731
    right = PAD_L + iw
    out: list[str] = []

    span = hi_v - lo_v
    tick = 500 if span > 2400 else 200 if span > 900 else 100 if span > 450 else 50
    q = int(lo_v // tick + 1) * tick
    while q < hi_v:
        out.append(f'<line x1="{PAD_L}" y1="{Y(q):.1f}" x2="{right}" y2="{Y(q):.1f}" '
                   f'stroke="currentColor" stroke-opacity=".09"/>')
        out.append(f'<text x="{PAD_L - 7}" y="{Y(q) + 3.5:.1f}" font-size="10" '
                   f'text-anchor="end" fill="currentColor" opacity=".5">{q:,}</text>')
        q += tick

    for i in range(1, n):
        if candles[i].session_date != candles[i - 1].session_date:
            out.append(f'<line x1="{X(i):.1f}" y1="{PAD_T}" x2="{X(i):.1f}" '
                       f'y2="{PAD_T + ih}" stroke="currentColor" stroke-opacity=".22" '
                       f'stroke-dasharray="2 5"/>')
            out.append(f'<text x="{X(i) + 3:.1f}" y="{PAD_T + 10}" font-size="9" '
                       f'fill="currentColor" opacity=".45">'
                       f'{candles[i].open_time:%d %b}</text>')

    # every structure the map holds, drawn across the candles it describes
    nodes = [x for x in snap.nodes if x.kind in STRUCTURE_KINDS] + \
        list(frontier.history())
    for node in nodes:
        colour = "var(--range)" if node.kind == "range" else "var(--cluster)"
        x0, x1 = X(node.start), X(node.end) + cw
        out.append(f'<rect x="{x0:.1f}" y="{Y(node.high):.1f}" '
                   f'width="{max(x1 - x0, 2):.1f}" '
                   f'height="{max(Y(node.low) - Y(node.high), 2):.1f}" '
                   f'fill="{colour}" fill-opacity=".14" stroke="{colour}" '
                   f'stroke-width="{2.2 if node.kind == "range" else 1.2}"/>')
        out.append(f'<text x="{x0 + 3:.1f}" y="{Y(node.high) - 3:.1f}" font-size="9" '
                   f'fill="{colour}" opacity=".85">{node.id}</text>')

    for a in anchors:
        if not a.uncovered:
            continue
        y = Y(a.price)
        out.append(f'<line x1="{max(X(a.index), PAD_L):.1f}" y1="{y:.1f}" '
                   f'x2="{right}" y2="{y:.1f}" stroke="var(--anchor)" '
                   f'stroke-width="1.1" stroke-opacity=".75"/>')
        out.append(f'<text x="{right - 3:.1f}" y="{y - 3:.1f}" font-size="9" '
                   f'text-anchor="end" fill="var(--anchor)" opacity=".9">'
                   f'{a.id} {float(a.price):,.0f}</text>')

    # references
    for r, up in [(x, True) for x in state.above.all()] + \
                 [(x, False) for x in state.below.all()]:
        y = Y(r.low if up else r.high)
        out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                   f'stroke="var(--ref)" stroke-width="1.2" stroke-opacity=".6" '
                   f'stroke-dasharray="6 5"/>')
        out.append(f'<text x="{PAD_L + 4}" y="{y - 3:.1f}" font-size="9.5" '
                   f'font-weight="650" fill="var(--ref)">{r.id} {r.band}</text>')

    out.extend(route_layer(state, Y, right))

    # the current structure: the only solid lines
    if state.current is not None:
        c = state.current
        y0, y1 = Y(c.high), Y(c.low)
        out.append(f'<rect x="{PAD_L}" y="{y0:.1f}" width="{iw:.1f}" '
                   f'height="{max(y1 - y0, 2):.1f}" fill="var(--cur)" '
                   f'fill-opacity=".12"/>')
        for y, lab, price in ((y0, "BREAK UP", c.high), (y1, "BREAK DOWN", c.low)):
            out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                       f'stroke="var(--cur)" stroke-width="2.2"/>')
            out.append(f'<text x="{right - 4}" y="{y - 5:.1f}" font-size="10" '
                       f'text-anchor="end" font-weight="700" fill="var(--cur)">'
                       f'{lab} {float(price):,.0f}</text>')

    body = max(cw * 0.62, 1.0)
    for k, cd in enumerate(candles):
        x = X(k)
        out.append(f'<line x1="{x:.2f}" y1="{Y(cd.h):.1f}" x2="{x:.2f}" '
                   f'y2="{Y(cd.l):.1f}" stroke="currentColor" stroke-width=".9" '
                   f'stroke-opacity=".85"/>')
        yt, yb = Y(max(cd.o, cd.c)), Y(min(cd.o, cd.c))
        out.append(f'<rect x="{x - body / 2:.2f}" y="{yt:.1f}" width="{body:.2f}" '
                   f'height="{max(yb - yt, .9):.1f}" '
                   f'fill="{"var(--bg)" if cd.c >= cd.o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width=".9"/>')

    out.append(f'<line x1="{X(n - 1):.1f}" y1="{PAD_T}" x2="{X(n - 1):.1f}" '
               f'y2="{PAD_T + ih}" stroke="var(--now)" stroke-width="1.5"/>')

    for k in range(0, n, max(1, n // 9)):
        out.append(f'<text x="{X(k):.1f}" y="{H - 8}" font-size="9.5" '
                   f'text-anchor="middle" fill="currentColor" opacity=".45">'
                   f'{candles[k].open_time:%d %b %H:%M}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def block(symbol: str, iso: str, bars: int) -> str:
    candles = five_minute(symbol, date.fromisoformat(iso))[-bars:]
    split = max(len(candles) - 60, len(candles) // 2)
    snap = build_snapshot(candles[:split], symbol)
    chain, _ = build_chain(candles[:split])
    anchors = build_anchors(chain, candles[:split])
    f = run(snap, candles[:split], candles[split:])
    state = Interpreter(snap, f, anchors=anchors).states()[-1]

    clusters = [x for x in snap.nodes if x.kind == "cluster"]
    ranges = [x for x in snap.nodes if x.kind == "range"]
    sessions = len({c.session_date for c in candles})
    head = (f"{iso} &middot; {len(candles)} x 5m ({sessions} sessions) &middot; "
            f"{len(clusters)} clusters, {len(ranges)} ranges, {len(anchors)} anchors "
            f"&middot; {len(f.history())} finalised live")
    body = "\n".join(f"<div>{ln}</div>" for ln in state.lines())
    return (f"<section><h2>{head}</h2>"
            f"<div class='wrap'><div class='chart'>"
            f"{draw(candles, snap, f, state, anchors)}</div>"
            f"<div class='state'>{body}</div></div></section>")


def render(symbol: str, days: list[str], bars: int, out_dir: Path) -> Path:
    blocks = "\n".join(block(symbol, d, bars) for d in days)
    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} — 5-minute structural map</title>
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
  .warn {{ border:2px solid var(--cur); border-radius:7px; padding:10px 13px;
          margin:0 0 12px; font-size:12.5px; }}
  .key {{ font-size:12px; opacity:.88; padding:10px 13px; border-radius:7px;
         border:1px solid color-mix(in srgb, currentColor 18%, transparent);
         margin:0 0 14px; }}
  section {{ border-top:1px solid color-mix(in srgb, currentColor 15%, transparent);
            padding:14px 0 4px; }}
  .wrap {{ display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap; }}
  .chart {{ flex:1 1 720px; min-width:340px; }}
  .state {{ flex:0 1 430px; font:11.5px/1.65 ui-monospace,monospace;
           white-space:pre-wrap; padding:9px 12px; border-radius:6px;
           border:1px solid color-mix(in srgb, currentColor 16%, transparent); }}
  svg {{ display:block; width:100%; height:auto; }}
  .c {{ color:var(--cluster); font-weight:650; }}
  .r {{ color:var(--range); font-weight:650; }}
  .g {{ color:var(--ref); font-weight:650; }}
  .a {{ color:var(--anchor); font-weight:650; }}
</style>
<h1>{symbol} &mdash; 5-minute structural map</h1>
<div class="warn"><b>THIS IS AN AUDIT, NOT A STRATEGY.</b> Every claim about 5m so far
has been statistical &mdash; 2.0 structures per session against 9.8 on 1m, same width in
ATR, five times the clock duration. Those are numbers about a map nobody had looked at.
The question here is the one the 1m map already passed: <b>can a trader read the market's
story off this, and are the boxes where a trader would draw them?</b></div>
<div class="key">
<span class="c">Blue box = CLUSTER</span> drawn across the candles it describes.
<span class="r">Amber outline = RANGE</span> &mdash; there are very few, and that is a
finding rather than a bug.<br>
<span class="a">Purple ray = ANCHOR</span> with no box on it &mdash; a swing a move
launched from. <span class="g">Dashed green = next structural REFERENCE</span>.<br>
<b>Solid amber lines = BREAK LEVELS</b>: the current structure's <b>own</b> edges. Never
the next reference.<br>
<b>Right-hand column = the ROUTE.</b> <span class="g">Pale green = FREE space</span> from
the break level to the next zone's near edge; <span class="c">filled block = ZONE
DEPTH</span> between that zone's near and far edges. The <b>near edge is the first
structural decision</b>; the <b>far edge is conditional</b> &mdash; it matters only after
price is accepted inside the zone, and it is <b>never</b> the current breakout level.<br>
Vertical dotted lines are session boundaries; a 5m structure may span them.
No threshold was changed for 5m &mdash; the detectors are byte-identical to the 1m run.
</div>
{blocks}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"map5m_{symbol.replace(' ', '_')}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--days", nargs="+", default=DEFAULT_DAYS)
    ap.add_argument("--bars", type=int, default=400)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "structmap"))
    args = ap.parse_args(argv)
    path = render(args.symbol, args.days, args.bars, Path(args.out))
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
