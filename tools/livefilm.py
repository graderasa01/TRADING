#!/usr/bin/env python3
"""
livefilm.py — the live map, candle by candle. No JavaScript.

    python tools/livefilm.py --day 2026-02-16
    python tools/livefilm.py --day 2026-02-16 --from 780 --to 890

## Why a film and not a chart

A chart shows where the structures ended up. It cannot show the thing that matters here:
**what the map was saying at each candle, while it was happening.** A frame is cut every
time the state changes, so the sequence a trader would have watched is the sequence on
the page:

```
60,702  WAIT              inside C03
60,715  APPROACHING_UPPER edge 60,718 ahead
60,720  BREAK_ATTEMPT_UP  break level 60,718
60,702  BREAKOUT_FAILURE  closed back inside
60,730  BREAK_ATTEMPT_UP  same edge, unmoved
60,741  BREAKOUT          accepted
```

The edge never moves between frames. That is the whole point of freezing the map, and it
is visible here rather than argued about.

**Nothing on this page is a trade.** `STATUS` and `MARKET STATE` describe where price is
and what it just did. The decision layer is quarantined and does not exist.
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
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.livemap.interpreter import Interpreter, MapState  # noqa: E402

W, H = 1080, 330
PAD_L, PAD_R, PAD_T, PAD_B = 66, 16, 10, 24
TAIL = 150          # candles of context drawn behind the live edge


def load(symbol: str, day: date, n: int = 1000):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-5:]
    out = []
    for s in feed.sessions(days=days):
        out.extend(s.candles)
    return out[-n:]


def frame_svg(candles, snap, state: MapState, anchors) -> str:
    hi_i = state.index
    lo_i = max(0, hi_i - TAIL)
    shown = candles[lo_i:hi_i + 1]
    n = len(shown)

    lo_v = float(min(k.l for k in shown))
    hi_v = float(max(k.h for k in shown))
    for r in state.above.all() + state.below.all():
        lo_v, hi_v = min(lo_v, float(r.low)), max(hi_v, float(r.high))
    pad = (hi_v - lo_v) * 0.08 or 1.0
    lo_v, hi_v = lo_v - pad, hi_v + pad

    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    cw = iw / max(n, 1)
    X = lambda k: PAD_L + (k - lo_i + 0.5) * cw                     # noqa: E731
    Y = lambda v: PAD_T + (hi_v - float(v)) / (hi_v - lo_v) * ih    # noqa: E731
    right = PAD_L + iw
    out: list[str] = []

    # frozen structures, faint
    for node in snap.nodes:
        if node.kind not in STRUCTURE_KINDS or node.end < lo_i:
            continue
        x0 = X(max(node.start, lo_i))
        x1 = X(min(node.end, hi_i)) + cw
        out.append(f'<rect x="{x0:.1f}" y="{Y(node.high):.1f}" '
                   f'width="{max(x1 - x0, 1.5):.1f}" '
                   f'height="{max(Y(node.low) - Y(node.high), 1.5):.1f}" '
                   f'fill="var(--frozen)" fill-opacity=".10" stroke="var(--frozen)" '
                   f'stroke-width=".9" stroke-opacity=".45"/>')

    # references
    for r, side in [(x, "up") for x in state.above.all()] + \
                   [(x, "dn") for x in state.below.all()]:
        y = Y(r.high if side == "dn" else r.low)
        out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                   f'stroke="var(--ref)" stroke-width="1" stroke-opacity=".55" '
                   f'stroke-dasharray="4 5"/>')
        out.append(f'<text x="{PAD_L + 4}" y="{y - 3:.1f}" font-size="9" '
                   f'fill="var(--ref)" opacity=".9">{r.id} {r.band}</text>')

    # the current structure and its break levels — the only solid lines on the page
    if state.current is not None:
        c = state.current
        y0, y1 = Y(c.high), Y(c.low)
        out.append(f'<rect x="{PAD_L}" y="{y0:.1f}" width="{iw:.1f}" '
                   f'height="{max(y1 - y0, 2):.1f}" fill="var(--cur)" '
                   f'fill-opacity=".13"/>')
        for y, lab, price in ((y0, "BREAK UP", c.high), (y1, "BREAK DOWN", c.low)):
            out.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                       f'stroke="var(--cur)" stroke-width="2"/>')
            out.append(f'<text x="{right - 4}" y="{y - 4:.1f}" font-size="9.5" '
                       f'text-anchor="end" font-weight="700" fill="var(--cur)">'
                       f'{lab} {float(price):,.0f}</text>')

    for a in anchors:
        if a.index > hi_i or not a.uncovered:
            continue
        y = Y(a.price)
        out.append(f'<line x1="{max(X(a.index), PAD_L):.1f}" y1="{y:.1f}" '
                   f'x2="{right}" y2="{y:.1f}" stroke="var(--anchor)" '
                   f'stroke-width="1" stroke-opacity=".7"/>')

    body = max(cw * 0.62, 0.8)
    for k, cd in enumerate(shown, start=lo_i):
        x = X(k)
        out.append(f'<line x1="{x:.2f}" y1="{Y(cd.h):.1f}" x2="{x:.2f}" '
                   f'y2="{Y(cd.l):.1f}" stroke="currentColor" stroke-width=".85" '
                   f'stroke-opacity=".8"/>')
        yt, yb = Y(max(cd.o, cd.c)), Y(min(cd.o, cd.c))
        out.append(f'<rect x="{x - body / 2:.2f}" y="{yt:.1f}" width="{body:.2f}" '
                   f'height="{max(yb - yt, .8):.1f}" '
                   f'fill="{"var(--bg)" if cd.c >= cd.o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width=".85"/>')

    # the live edge
    out.append(f'<line x1="{X(hi_i):.1f}" y1="{PAD_T}" x2="{X(hi_i):.1f}" '
               f'y2="{PAD_T + ih}" stroke="var(--now)" stroke-width="1.4" '
               f'stroke-opacity=".8"/>')
    out.append(f'<circle cx="{X(hi_i):.1f}" cy="{Y(state.price):.1f}" r="3.2" '
               f'fill="var(--now)"/>')

    for k in range(lo_i, hi_i + 1, max(1, n // 6)):
        out.append(f'<text x="{X(k):.1f}" y="{H - 6}" font-size="9" '
                   f'text-anchor="middle" fill="currentColor" opacity=".45">'
                   f'{candles[k].open_time:%H:%M}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def frame_html(candles, snap, state: MapState, anchors) -> str:
    body = "\n".join(f"<div>{ln}</div>" for ln in state.lines())
    head = (f"c{state.index} &middot; {state.at:%d %b %H:%M} &middot; "
            f"<b>{state.status}</b> &middot; {state.market_state}")
    return (f'<section><h2>{head}</h2>'
            f'<div class="wrap"><div class="chart">'
            f'{frame_svg(candles, snap, state, anchors)}</div>'
            f'<div class="state">{body}</div></div></section>')


def render(symbol: str, day: date, first: int, last: int, out_dir: Path,
           max_frames: int) -> Path:
    candles = load(symbol, day)
    last = min(last, len(candles) - 1)
    snap = build_snapshot(candles[:first], symbol)
    chain, _ = build_chain(candles[:first])
    anchors = build_anchors(chain, candles[:first])
    f = run(snap, candles[:first], candles[first:last + 1])
    states = Interpreter(snap, f, anchors=anchors).states()

    # a frame per state change — the sequence a trader would have watched
    frames, prev = [], None
    for s in states:
        if s.status != prev:
            frames.append(s)
            prev = s.status
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        frames = [frames[int(i * step)] for i in range(max_frames)]

    blocks = "\n".join(frame_html(candles, snap, s, anchors) for s in frames)
    counts = {}
    for s in states:
        counts[s.status] = counts.get(s.status, 0) + 1
    tally = "  ".join(f"{k}&nbsp;{v}" for k, v in sorted(counts.items()))

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} {day} — live map film</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff; --frozen:#1d6fd0;
          --cur:#c2760a; --ref:#0f9d76; --anchor:#8b5cf6; --now:#c0392b; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e9e9ec; --bg:#14161a; --frozen:#6aa8f5; --cur:#f0b24a;
            --ref:#4fd1a5; --anchor:#b794f6; --now:#ff7b6b; }} }}
  body {{ font:13px/1.55 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1560px; }}
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
  .chart {{ flex:1 1 620px; min-width:320px; }}
  .state {{ flex:0 1 430px; font:11.5px/1.65 ui-monospace,monospace;
           white-space:pre-wrap; padding:9px 12px; border-radius:6px;
           border:1px solid color-mix(in srgb, currentColor 16%, transparent); }}
  svg {{ display:block; width:100%; height:auto; }}
  .f {{ color:var(--frozen); font-weight:650; }}
  .c {{ color:var(--cur); font-weight:650; }}
  .r {{ color:var(--ref); font-weight:650; }}
  .a {{ color:var(--anchor); font-weight:650; }}
</style>
<h1>{symbol} &middot; {day:%d %b %Y} &mdash; live map film</h1>
<div class="warn"><b>THIS IS NOT A TRADE SYSTEM.</b> Every line is a description of where
price is and what it just did. <code>STATUS</code> and <code>MARKET STATE</code> name
locations and events, never actions &mdash; <code>src/livemap/</code> is import-isolated
from <code>setups/</code>, <code>risk/</code> and <code>exits/</code>, and a test asserts
it. The decision layer does not exist.</div>
<div class="key">
<span class="c">Solid amber lines = BREAK LEVELS</span> &mdash; the current structure's
<b>own</b> edges. These are the breakout points, and they do not move between frames.<br>
<span class="r">Dashed green = next structural REFERENCE</span> &mdash; a place to look
at, never a boundary and never a promised target.
<span class="f">Faint blue = frozen historical structures</span> from <code>M001</code>.
<span class="a">Purple = structural anchor</span> with no box on it.<br>
<b>Red line</b> = the live candle. Everything to its right is unknown to the map.<br>
<b>SPACE</b> is first-class: a break with 5 points of room and one with 100 are different
events, and only the distance says which is which.
</div>
<p style="opacity:.7;font-size:12px">{len(states)} candles &middot; {len(frames)} frames
&middot; {tally}</p>
{blocks}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"livefilm_{symbol.replace(' ', '_')}_{day}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day", default="2026-02-16")
    ap.add_argument("--from", dest="first", type=int, default=780)
    ap.add_argument("--to", dest="last", type=int, default=890)
    ap.add_argument("--max-frames", type=int, default=22)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "structmap"))
    args = ap.parse_args(argv)
    path = render(args.symbol, date.fromisoformat(args.day), args.first, args.last,
                  Path(args.out), args.max_frames)
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
