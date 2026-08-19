#!/usr/bin/env python3
"""
boxmap.py — the adaptive cluster-range map, drawn. No JavaScript.

    python tools/boxmap.py --day 2026-02-16
    python tools/boxmap.py --day 2026-02-16 --frames 6

## Boxes are rectangles in time, not bands across the page

Every previous map in this repo drew levels as full-width horizontal bands, which throws
away the one thing the trader kept asking for: **kab draw hui.** A box here starts at the
candle it was admitted on and ends where price left it, so its rectangle is exactly the
stretch of session it describes — the shape drawn by hand on a chart.

After price leaves, the two edges continue to the right as dashed lines. The structure is
over; the level is not.

## One frame is already honest

The heat map needed a "hindsight" label because its profile was computed from the whole
session at once. Nothing here is. Every box was admitted by `Mapper.on_candle` using only
candles up to its birth, and frozen from that moment, so the end-of-day picture contains
no information the engine did not have when it drew each box. `--frames` exists to watch
the map build, not to make it truthful.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.mapper import Box, Mapper, story  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402

W, H = 1360, 560
PAD_L, PAD_R, PAD_T, PAD_B = 68, 214, 10, 26
STYLE = {"cluster": ("var(--cluster)", 1.6), "range": ("var(--range)", 2.4)}


def load(symbol: str, day: date, days: int):
    feed = ReplayFeed(symbol, on_gap="skip")
    wanted = [d for d in feed.available_days(end=day) if d <= day][-days:]
    out = []
    for s in feed.sessions(days=wanted):
        out.extend(s.candles)
    return out


def draw(m: Mapper, upto: int) -> str:
    """One picture of the map as it stood at candle `upto`."""
    shown = m.candles[:upto + 1]
    n = len(shown)
    lo_v = float(min(k.l for k in shown))
    hi_v = float(max(k.h for k in shown))
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
                   f'stroke="currentColor" stroke-opacity=".10"/>')
        out.append(f'<text x="{PAD_L - 7}" y="{Y(q) + 3.5:.1f}" font-size="10.5" '
                   f'text-anchor="end" fill="currentColor" opacity=".55">{q:,}</text>')
        q += tick

    lo_p = min(k.l for k in shown)
    hi_p = max(k.h for k in shown)
    for v, tag in ((hi_p, "HIGH"), (lo_p, "LOW")):
        out.append(f'<line x1="{PAD_L}" y1="{Y(v):.1f}" x2="{right}" y2="{Y(v):.1f}" '
                   f'stroke="currentColor" stroke-width="1.3" stroke-opacity=".5" '
                   f'stroke-dasharray="11 6"/>')
        out.append(f'<text x="{PAD_L + 5}" y="{Y(v) + (-5 if tag == "HIGH" else 12):.1f}" '
                   f'font-size="10" font-weight="700" fill="currentColor" opacity=".65">'
                   f'{tag} {float(v):,.0f}</text>')

    visible = [b for b in m.boxes if b.born <= upto]
    for b in visible:
        colour, weight = STYLE[b.kind]
        end = min(b.left_at if b.left_at is not None else upto, upto)
        x0, x1 = X(b.born), X(max(end, b.born)) + cw
        y0, y1 = Y(b.high), Y(b.low)
        faded = ".35" if b.spent else "1"
        out.append(f'<g opacity="{faded}">')
        out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{max(x1 - x0, 2):.1f}" '
                   f'height="{max(y1 - y0, 2):.1f}" fill="{colour}" fill-opacity=".13" '
                   f'stroke="{colour}" stroke-width="{weight}" stroke-opacity=".95"/>')
        # the level outlives the structure
        if b.left_at is not None and b.left_at < upto:
            for y in (y0, y1):
                out.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" '
                           f'stroke="{colour}" stroke-width="1" stroke-opacity=".5" '
                           f'stroke-dasharray="3 4"/>')
            arrow = "▲" if b.left_side == "up" else "▼"
            out.append(f'<text x="{x1 + 2:.1f}" '
                       f'y="{(y0 - 3) if b.left_side == "up" else (y1 + 10):.1f}" '
                       f'font-size="9" fill="{colour}" opacity=".8">{arrow}</text>')
        # rotations: a tick at each completed traverse
        for r in b.rotations:
            if r.to_i <= upto:
                out.append(f'<circle cx="{X(r.to_i):.1f}" cy="{Y(r.to_price):.1f}" r="1.7" '
                           f'fill="{colour}" opacity=".85"/>')
        out.append('</g>')

    body = max(cw * 0.62, 0.9)
    for k, c in enumerate(shown):
        x = X(k)
        out.append(f'<line x1="{x:.2f}" y1="{Y(c.h):.1f}" x2="{x:.2f}" y2="{Y(c.l):.1f}" '
                   f'stroke="currentColor" stroke-width=".9" stroke-opacity=".88"/>')
        yt, yb = Y(max(c.o, c.c)), Y(min(c.o, c.c))
        out.append(f'<rect x="{x - body / 2:.2f}" y="{yt:.1f}" width="{body:.2f}" '
                   f'height="{max(yb - yt, .9):.1f}" '
                   f'fill="{"var(--bg)" if c.c >= c.o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width=".9"/>')

    used: list[float] = []
    for b in sorted(visible, key=lambda z: -z.mid):
        colour, _ = STYLE[b.kind]
        y = max(Y(b.mid), PAD_T + 10)
        while any(abs(y - u) < 23 for u in used):
            y += 23
        used.append(y)
        extra = (f"{b.upper_touches}+{b.lower_touches} touch"
                 if b.kind == "range" else f"{b.confirmations + 1}x bani")
        out.append(f'<text x="{right + 10}" y="{y:.1f}" font-size="10.5" '
                   f'font-weight="650" fill="{colour}">'
                   f'{float(b.low):,.0f}&ndash;{float(b.high):,.0f}</text>')
        out.append(f'<text x="{right + 10}" y="{y + 11:.1f}" font-size="9.5" '
                   f'fill="currentColor" opacity=".6">N={b.window} &middot; '
                   f'{b.score:.2f} &middot; {extra} &middot; {len(b.rotations)} rot '
                   f'&middot; {b.state}</text>')

    for k in range(0, n, max(1, n // 7)):
        out.append(f'<text x="{X(k):.1f}" y="{H - 7}" font-size="10" text-anchor="middle" '
                   f'fill="currentColor" opacity=".5">'
                   f'{shown[k].open_time.strftime("%d %b %H:%M" if n > 400 else "%H:%M")}'
                   f'</text>')

    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def frame(candles, upto: int) -> str:
    m = Mapper()
    for c in candles[:upto + 1]:
        m.on_candle(c)
    lines = "".join(f"<div>{ln}</div>" for ln in story(m) if ln.strip())
    head = (f'{candles[upto].open_time:%d %b %H:%M} &middot; candle {upto} &middot; '
            f'close {float(m.close):,.0f} &middot; {len(m.boxes)} box '
            f'({len(m.holding())} andar, {len(m.broken())} toote)')
    return f'<h2>{head}</h2><div class="story">{lines}</div>{draw(m, upto)}'


def render(symbol: str, day: date, days: int, frames: int, out_dir: Path) -> Path:
    candles = load(symbol, day, days)
    n = len(candles)
    marks = ([n - 1] if frames <= 1
             else [int(n * (i + 1) / frames) - 1 for i in range(frames)])
    body = "\n".join(frame(candles, k) for k in marks)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} {day} — cluster / range map</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff;
          --cluster:#1d6fd0; --range:#c2760a; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e9e9ec; --bg:#14161a; --cluster:#6aa8f5; --range:#f0b24a; }} }}
  body {{ font:13px/1.55 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1420px; }}
  h1 {{ font-size:17px; margin:0 0 3px; }}
  h2 {{ font-size:12.5px; margin:26px 0 5px; font-weight:650;
       font-variant-numeric:tabular-nums; }}
  .sub {{ opacity:.66; margin:0 0 10px; font-size:12.5px; }}
  .story {{ font:11.5px/1.62 ui-monospace,monospace; white-space:pre-wrap; opacity:.9;
           margin:0 0 6px; padding:9px 12px; border-radius:6px;
           border:1px solid color-mix(in srgb, currentColor 16%, transparent); }}
  .key {{ font-size:12px; opacity:.86; padding:10px 13px; border-radius:7px;
         border:1px solid color-mix(in srgb, currentColor 18%, transparent); }}
  .c {{ color:var(--cluster); font-weight:650; }}
  .r {{ color:var(--range); font-weight:650; }}
  svg {{ display:block; width:100%; height:auto; }}
</style>
<h1>{symbol} &middot; {day:%d %b %Y} ({day:%a}) &mdash; cluster / range map</h1>
<p class="sub">Har candle par system 8 se 75 tak ki rolling windows scan karta hai, aur
<b>sabse chhoti window</b> leta hai jisme structure pehle se hi jam chuka ho (agli do badi
windows bhi wahi jagah bata rahi hon). Jo mila, wo <b>freeze</b> ho jaata hai &mdash; uske
kinare phir kabhi nahi hilte.</p>
<div class="key">
<span class="c">Neela box = CLUSTER</span> &mdash; price ek jagah baith gayi (occupancy +
compression + reaction).<br>
<span class="r">Peela box = RANGE</span> &mdash; dono taraf 2+ touch aur andar rotation.
Sirf high-low chaudi hone se range nahi banti.<br>
<b>Box ki chaudai = waqt</b>: jahan bana wahan se shuru, jahan price nikli wahan khatam.
Uske baad dashed line &mdash; structure khatam, level zinda. <b>▲▼</b> = kis taraf toota.<br>
<b>Chhote dots</b> = rotation, box ke andar ek poora chakkar. <b>N</b> = kitni candles me
mila. <b>score</b> = &minus;1 se +1, migration ghata kar.<br>
<b>Staircase par kuchh nahi banta</b> &mdash; 100&rarr;102&rarr;104&rarr;106 me high-low
to hai par structure nahi, aur migration penalty use kaat deti hai.
</div>
{body}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"boxmap_{symbol.replace(' ', '_')}_{day}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day", required=True)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "boxes"))
    args = ap.parse_args(argv)
    path = render(args.symbol, date.fromisoformat(args.day), args.days, args.frames,
                  Path(args.out))
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
