#!/usr/bin/env python3
"""
mapfilm.py — the three-timeframe map, drawn. No JavaScript.

    python tools/mapfilm.py --day 2026-02-16
    python tools/mapfilm.py --day 2026-02-16 --frames 8

Each frame is one moment: the candles the engine had, the frozen blocks it cut them into,
the shelves those blocks agree on, and the story read off them. Nothing after that candle
exists in the frame.

## What is drawn, and why it is drawn that way

**Shelves are horizontal bands across the whole panel**, because that is what they are —
a price, not a place in time. A shelf found on 15m and a shelf found on 1m are the same
kind of object at different scales, so they differ only in weight.

**Confluence is filled; a single timeframe's shelf is a dashed line.** Two scales agreeing
is the strongest statement the map makes, and it should be the strongest mark on the page.

**The live 1m block is boxed at the right edge.** It is the only thing on the chart that
is still moving, and the only thing a trigger may come from — everything else was frozen
when its block closed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.multi import ORDER, build_multi, confluence, multi_story  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402

W, H = 1020, 420
PAD_L, PAD_R, PAD_T, PAD_B = 66, 150, 10, 22
TF_WEIGHT = {"15m": 2.1, "5m": 1.5, "1m": 1.0}


def load(symbol: str, day: date, sessions: int = 26):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-sessions:]
    stream, start = [], 0
    for s in feed.sessions(days=days):
        if s.day == day:
            start = len(stream)
        stream.extend(s.candles)
    return stream, start


def frame(stream, start, upto, lo: float, hi: float) -> str:
    today = stream[start:upto + 1]
    ranges = [c.h - c.l for c in stream]
    window = ranges[max(0, upto - 19):upto + 1]
    atr = sum(window) / len(window)
    maps = build_multi(stream[:upto + 1], atr)
    merged = confluence(maps, atr)

    n_total = 375
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    cw = iw / n_total
    X = lambda k: PAD_L + (k + 0.5) * cw                       # noqa: E731
    Y = lambda p: PAD_T + (hi - p) / (hi - lo) * ih             # noqa: E731

    out = []
    step = 200 if (hi - lo) > 900 else 100 if (hi - lo) > 400 else 50
    for q in range(int(lo // step + 1) * step, int(hi), step):
        out.append(f'<line x1="{PAD_L}" y1="{Y(q):.1f}" x2="{W - PAD_R}" y2="{Y(q):.1f}" '
                   f'stroke="currentColor" stroke-opacity=".09"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{Y(q) + 3.5:.1f}" font-size="10" '
                   f'text-anchor="end" fill="currentColor" opacity=".5">{q:,}</text>')

    # Only confluence, and only the nearest few.
    #
    # The first version drew every shelf from every timeframe — fifteen bands and a stack
    # of overlapping labels down the right margin, which is a picture of the data rather
    # than a picture of the decision. A trader reads the four or five prices around
    # them, not thirty.
    price = float(today[-1].c)
    strong = [c for c in merged if c.strength >= 2 and lo <= float(c.mid) <= hi]
    near = (sorted([c for c in strong if float(c.mid) > price],
                   key=lambda z: float(z.mid))[:3]
            + sorted([c for c in strong if float(c.mid) <= price],
                     key=lambda z: -float(z.mid))[:3])
    for c in sorted(near, key=lambda z: z.strength):
        top, bot = Y(float(c.high)), Y(float(c.low))
        tfs = sorted(c.tfs, key=lambda t: ORDER.index(t))
        weight = max(TF_WEIGHT[t] for t in tfs)
        if True:
            out.append(f'<rect x="{PAD_L}" y="{top:.1f}" width="{iw:.1f}" '
                       f'height="{max(bot - top, 2):.1f}" fill="currentColor" '
                       f'fill-opacity="{0.05 + 0.05 * c.strength:.2f}" '
                       f'stroke="currentColor" stroke-width="{weight}" '
                       f'stroke-opacity="{0.25 + 0.14 * c.strength:.2f}"/>')
        else:
            out.append(f'<line x1="{PAD_L}" y1="{(top + bot) / 2:.1f}" x2="{W - PAD_R}" '
                       f'y2="{(top + bot) / 2:.1f}" stroke="currentColor" '
                       f'stroke-width="{weight}" stroke-opacity=".22" '
                       f'stroke-dasharray="3 5"/>')
        out.append(f'<text x="{W - PAD_R + 5}" y="{(top + bot) / 2 + 3:.1f}" font-size="10" '
                   f'fill="currentColor" opacity="{0.45 + 0.16 * c.strength:.2f}">'
                   f'{" ".join(tfs)} &middot; {float(c.mid):,.0f}</text>')

    for k, cd in enumerate(today):
        o, h, l_, cl = float(cd.o), float(cd.h), float(cd.l), float(cd.c)
        x = X(k)
        out.append(f'<line x1="{x:.1f}" y1="{Y(h):.1f}" x2="{x:.1f}" y2="{Y(l_):.1f}" '
                   f'stroke="currentColor" stroke-width="1" stroke-opacity=".85"/>')
        yt, yb = Y(max(o, cl)), Y(min(o, cl))
        out.append(f'<rect x="{x - cw * .34:.1f}" y="{yt:.1f}" width="{max(cw * .68, 1):.1f}" '
                   f'height="{max(yb - yt, 1):.1f}" '
                   f'fill="{"var(--bg)" if cl >= o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width="1"/>')

    # the live 1m block — the only moving thing, and the only trigger
    one = maps.get("1m")
    if one is not None and one.live is not None:
        b = one.live
        span = b.last - b.first + 1
        x0, x1 = X(max(0, len(today) - span)), X(len(today) - 1) + cw
        out.append(f'<rect x="{x0:.1f}" y="{Y(float(b.high)):.1f}" '
                   f'width="{max(x1 - x0, 3):.1f}" '
                   f'height="{max(Y(float(b.low)) - Y(float(b.high)), 2):.1f}" '
                   f'fill="currentColor" fill-opacity=".10" stroke="currentColor" '
                   f'stroke-width="1.8" stroke-opacity=".75"/>')
        out.append(f'<text x="{x0 - 3:.1f}" y="{Y(float(b.high)) - 4:.1f}" font-size="10" '
                   f'text-anchor="end" fill="currentColor" opacity=".8">live 1m</text>')

    for k in range(0, len(today), 60):
        out.append(f'<text x="{X(k):.1f}" y="{H - 6}" font-size="10" text-anchor="middle" '
                   f'fill="currentColor" opacity=".5">'
                   f'{today[k].open_time.strftime("%H:%M")}</text>')

    lines = "".join(f'<div>{ln}</div>' for ln in multi_story(maps, atr) if ln.strip())
    return (f'<h2>{today[-1].open_time.strftime("%H:%M")} &middot; candle '
            f'{upto - start} &middot; close {float(today[-1].c):,.0f} &middot; '
            f'ATR {float(atr):.1f}</h2>'
            f'<div class="story">{lines}</div>'
            f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def render(symbol: str, day: date, frames: int, out_dir: Path) -> Path:
    stream, start = load(symbol, day)
    today = stream[start:]
    lo = min(float(c.l) for c in today)
    hi = max(float(c.h) for c in today)
    pad = (hi - lo) * 0.10
    lo, hi = lo - pad, hi + pad
    marks = [start + int(len(today) * (i + 1) / frames) - 1 for i in range(frames)]
    body = "\n".join(frame(stream, start, m, lo, hi) for m in marks)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} {day} — 3 timeframe map</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --ink:#e8e8ea; --bg:#16181d; }} }}
  body {{ font:13px/1.55 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1120px; }}
  h1 {{ font-size:17px; margin:0 0 3px; }}
  h2 {{ font-size:12.5px; margin:26px 0 4px; font-weight:640;
       font-variant-numeric:tabular-nums; }}
  .sub {{ opacity:.65; margin:0 0 6px; font-size:12.5px; }}
  .story {{ font:11.5px/1.6 ui-monospace,monospace; white-space:pre-wrap;
           opacity:.85; margin:0 0 6px; padding:8px 11px; border-radius:6px;
           border:1px solid color-mix(in srgb, currentColor 15%, transparent); }}
  .key {{ font-size:12px; opacity:.82; margin:10px 0 0; padding:9px 12px; border-radius:7px;
         border:1px solid color-mix(in srgb, currentColor 18%, transparent); }}
  svg {{ display:block; width:100%; height:auto; }}
</style>
<h1>{symbol} &middot; {day:%d %b %Y} ({day:%a}) &mdash; 15m / 5m / 1m ka ek map</h1>
<p class="sub">Har frame wahi session hai jaisa engine ne us candle par dekha. Peeche ki
market 20/15/10 candles ke blocks me kat kar <b>jam chuki hai</b> &mdash; wo blocks hilte
nahi. Sirf <b>live 1m block</b> zinda hai, aur trigger sirf wahi de sakta hai.</p>
<div class="key">
<b>Bhari patti</b> = do ya teen timeframe ek price par sehmat (confluence). Jitni gehri,
utne zyada timeframe.<br>
<b>Dashed line</b> = sirf ek timeframe ka shelf. Moti line = 15m, patli = 1m.<br>
<b>Boxed at right</b> = live 1m block &mdash; ekmatra cheez jo abhi bhi ban rahi hai.<br>
<b>shelf</b> = jahan bahut blocks ke kinare ek price par mile. <b>chaal</b> = pichhle 5
block ke centre kis taraf ja rahe hain.
</div>
{body}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mapfilm_{symbol.replace(' ', '_')}_{day}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day", required=True)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "boxes"))
    args = ap.parse_args(argv)
    path = render(args.symbol, date.fromisoformat(args.day), args.frames, Path(args.out))
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
