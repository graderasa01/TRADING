#!/usr/bin/env python3
"""
boxfilm.py — the box stack as a filmstrip. No JavaScript, anywhere.

    python tools/boxfilm.py --day 2026-02-16
    python tools/boxfilm.py --day 2026-02-16 --frames 8

## Why this exists

`chart.py` is interactive — zoom, pan, a replay you can slow to 2 s per candle. All of
that is JavaScript, and a preview pane that renders a page as a **static snapshot** runs
none of it. The chart was fine; it was simply never executing.

So this renders the same information with the interaction removed rather than disabled:
several moments through one session, each drawn as plain SVG the moment the file is
written. There is no script tag in the output. It renders in a snapshot, an email, a
screenshot or a printout identically.

## What a frame shows

Each frame is the session **as the engine saw it at that candle** — candles up to that
point and nothing after, and the four boxes exactly as `compute_stack` derived them from
those candles. Reading down the page is watching the boxes form, hold and move, which is
what they will do live.

The price scale is shared by every frame on purpose. Per-frame autoscaling would make
each one look tidy and would hide the only thing worth seeing: how far a box moves
between frames.
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

from src.boxes.engine import DEFAULT_WINDOWS, SKIPS, compute_stack  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402

W, H = 1000, 380
PAD_L, PAD_R, PAD_T, PAD_B = 62, 120, 10, 22
# REST boxes are zones — drawn filled. SPAN boxes are boundaries — drawn as outlines.
# That is the semantic difference, so it is also the visual one.
RESTS = {"l3": (0.34, 1.7), "l2": (0.22, 1.4), "l1r": (0.14, 1.3), "l0r": (0.08, 1.2)}
SPANS = {"l1": 1.2, "l0": 1.0}


def load(symbol: str, day: date, lookback_days: int = 10):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-lookback_days:]
    stream, start = [], 0
    for session in feed.sessions(days=days):
        if session.day == day:
            start = len(stream)
        stream.extend(session.candles)
    return stream, start


def frame(stream, start, upto, lo: float, hi: float) -> str:
    """One moment. Reads `stream[:upto + 1]` and not one candle more."""
    today = stream[start:upto + 1]
    ranges = [c.h - c.l for c in stream]
    window = ranges[max(0, upto - 19):upto + 1]
    atr = sum(window) / len(window)
    stack = compute_stack(stream[:upto + 1], atr)

    n_total = 375
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    cw = iw / n_total

    def X(k: int) -> float:
        return PAD_L + (k + 0.5) * cw

    def Y(p: float) -> float:
        return PAD_T + (hi - p) / (hi - lo) * ih

    out = []
    step = 200 if (hi - lo) > 900 else 100 if (hi - lo) > 400 else 50
    for q in range(int(lo // step + 1) * step, int(hi), step):
        out.append(f'<line x1="{PAD_L}" y1="{Y(q):.1f}" x2="{W - PAD_R}" y2="{Y(q):.1f}" '
                   f'stroke="currentColor" stroke-opacity=".10"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{Y(q) + 3.5:.1f}" font-size="10" '
                   f'text-anchor="end" fill="currentColor" opacity=".5">{q:,}</text>')

    # SPAN boxes — how far it went. Just their two edges, labelled in the margin. Drawn
    # as filled boxes they swallow the panel and say nothing; their whole job is to say
    # how far the far target is.
    for name, sw in SPANS.items():
        box = getattr(stack, name)
        if box is None:
            continue
        for edge, side in ((float(box.outer_high), "high"), (float(box.outer_low), "low")):
            if not (lo <= edge <= hi):
                continue
            out.append(f'<line x1="{PAD_L}" y1="{Y(edge):.1f}" x2="{W - PAD_R}" '
                       f'y2="{Y(edge):.1f}" stroke="currentColor" stroke-width="{sw}" '
                       f'stroke-opacity=".42" stroke-dasharray="2 5"/>')
            out.append(f'<text x="{W - PAD_R + 5}" y="{Y(edge) + 3:.1f}" font-size="10" '
                       f'fill="currentColor" opacity=".62">'
                       f'{name.upper()} {side} {edge:,.0f}</text>')

    # REST boxes — where it paused. Widest first, so the small one lands on top.
    for name in ("l0r", "l1r", "l2", "l3"):
        box = getattr(stack, name)
        if box is None:
            continue
        op, sw = RESTS[name]
        back = DEFAULT_WINDOWS[name] + SKIPS[name]
        x0 = max(PAD_L, X(upto - start - back))
        x1 = min(W - PAD_R, X(upto - start - SKIPS[name]) + cw)
        ol, oh = float(box.outer_low), float(box.outer_high)
        out.append(f'<rect x="{x0:.1f}" y="{Y(oh):.1f}" width="{max(x1 - x0, 2):.1f}" '
                   f'height="{max(Y(ol) - Y(oh), 1):.1f}" fill="none" stroke="currentColor" '
                   f'stroke-width="{sw}" stroke-opacity="{op + .16:.2f}" '
                   f'stroke-dasharray="5 3"/>')
        if not box.degenerate:
            il, ih_ = float(box.inner_low), float(box.inner_high)
            out.append(f'<rect x="{x0:.1f}" y="{Y(ih_):.1f}" width="{max(x1 - x0, 2):.1f}" '
                       f'height="{max(Y(il) - Y(ih_), 1.5):.1f}" fill="currentColor" '
                       f'fill-opacity="{op * .40:.2f}" stroke="currentColor" '
                       f'stroke-width="{sw}" stroke-opacity="{op + .30:.2f}"/>')
        label = f'{name.upper()}{" · travelling" if box.degenerate else ""}'
        out.append(f'<text x="{x0 + 4:.1f}" y="{Y(oh) - 3:.1f}" font-size="10" '
                   f'fill="currentColor" opacity=".82">{label}</text>')

    for k, c in enumerate(today):
        o, h, l_, cl = float(c.o), float(c.h), float(c.l), float(c.c)
        x = X(k)
        out.append(f'<line x1="{x:.1f}" y1="{Y(h):.1f}" x2="{x:.1f}" y2="{Y(l_):.1f}" '
                   f'stroke="currentColor" stroke-width="1" stroke-opacity=".8"/>')
        yt, yb = Y(max(o, cl)), Y(min(o, cl))
        out.append(f'<rect x="{x - cw * .34:.1f}" y="{yt:.1f}" width="{max(cw * .68, 1):.1f}" '
                   f'height="{max(yb - yt, 1):.1f}" '
                   f'fill="{"var(--bg)" if cl >= o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width="1"/>')

    for k in range(0, len(today), 60):
        out.append(f'<text x="{X(k):.1f}" y="{H - 6}" font-size="10" text-anchor="middle" '
                   f'fill="currentColor" opacity=".5">'
                   f'{today[k].open_time.strftime("%H:%M")}</text>')

    close = today[-1].c
    pos = stack.positions(close)

    # "kya bana last days se, aur kya abhi" — in words, per box
    def built_from(name: str) -> str:
        back = DEFAULT_WINDOWS[name]
        skip = SKIPS[name]
        first = stream[max(0, upto - skip - back + 1)]
        last = stream[max(0, upto - skip)]
        same_day = first.open_time.date() == last.open_time.date()
        when = (f'{first.open_time:%H:%M}' if same_day
                else f'{first.open_time:%d %b %H:%M}')
        return (f'<b>{name.upper()}</b> {back} candles &rarr; {when}&ndash;'
                f'{last.open_time:%H:%M}'
                + ('' if same_day else ' <i>(reaches into earlier sessions)</i>'))

    sources = " &nbsp;&middot;&nbsp; ".join(
        built_from(k) for k in ("l3", "l2", "l1r", "l0r"))
    readout = "  ".join(
        f'{k.upper()} {"—" if v is None else f"{float(v) * 100:.0f}%"}'
        for k, v in pos.items())
    # When price has sat in one place, the densest band over 75 candles becomes the same
    # band as the rotation over 20 — L2 and L3 collapse into each other and the middle of
    # the hierarchy stops existing. Say so rather than drawing two boxes on top of one
    # another and letting the eye assume there is a target between them.
    if stack.l2 and stack.l3 and not stack.l3.degenerate:
        overlap = (min(stack.l2.inner_high, stack.l3.inner_high)
                   - max(stack.l2.inner_low, stack.l3.inner_low))
        thinner = min(stack.l2.inner_width, stack.l3.inner_width)
        if thinner > 0 and overlap / thinner > Decimal("0.8"):
            readout += "   &nbsp; L2 and L3 have collapsed into one band — no target between them"
    return (f'<h2>{today[-1].open_time.strftime("%H:%M")} &middot; candle '
            f'{upto - start} &middot; close {float(close):,.0f}</h2>'
            f'<p class="pos">built from &nbsp; {sources}</p>'
            f'<p class="pos">position &nbsp; {readout}</p>'
            f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def render(symbol: str, day: date, frames: int, out_dir: Path) -> Path:
    stream, start = load(symbol, day)
    today = stream[start:]
    lo = min(float(c.l) for c in today)
    hi = max(float(c.h) for c in today)
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad

    marks = [start + int(len(today) * (i + 1) / frames) - 1 for i in range(frames)]
    body = "\n".join(frame(stream, start, m, lo, hi) for m in marks)

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} {day} — box stack</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --ink:#e8e8ea; --bg:#16181d; }} }}
  body {{ font:13px/1.5 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1100px; }}
  h1 {{ font-size:17px; margin:0 0 3px; }}
  h2 {{ font-size:12px; margin:22px 0 0; font-weight:640;
       font-variant-numeric:tabular-nums; }}
  .pos {{ font-size:11.5px; opacity:.65; margin:1px 0 3px;
         font-variant-numeric:tabular-nums; }}
  .sub {{ opacity:.65; margin:0 0 4px; font-size:12.5px; }}
  .key {{ font-size:12px; opacity:.8; margin:10px 0 0; padding:9px 12px; border-radius:7px;
         border:1px solid color-mix(in srgb, currentColor 18%, transparent); }}
  svg {{ display:block; width:100%; height:auto; }}
</style>
<h1>{symbol} &middot; {day:%d %b %Y} ({day:%a}) &mdash; the box stack, moment by moment</h1>
<p class="sub">Each frame is the session <b>as the engine saw it at that candle</b> —
nothing after it exists yet. The four boxes are re-derived from scratch on every candle;
none of them is stored.</p>
<div class="key">
<b>Har box do sawaal ka jawab hai.</b> Bhari hui patti = <b>kahan aaram kiya</b>.
Dashed line = <b>kitni door gaya</b>.<br>
<b>L3</b> pichhli 20 candles &mdash; abhi kahan ghoom rahi hai &middot;
<b>L2</b> 75 &mdash; pichhle ghante ka aaram &middot;
<b>L1R</b> 375 &mdash; din ka aaram &middot;
<b>L0R</b> 1875 &mdash; hafte ka aaram &middot;
<b>L1 / L0</b> lines &mdash; din aur hafte ke sire.<br>
Har box apni <b>lookback jitna chauda</b> hai, to screen par uski chaudai batati hai wo
kitne peeche se bana. Har REST box apne se chhote box ki candles chhod deta hai, warna
dono ek hi patti ban jaate hain.<br>
<b>position</b> = close us box ke andar kahan hai. 100% se upar = price us box se upar
nikal chuki. 0% se neeche = neeche nikal chuki.<br>
<b>travelling</b> = us window me price kahin ruki hi nahi &mdash; koi patti hai hi nahi,
aur ye bhi ek jawab hai.
</div>
{body}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"boxfilm_{symbol.replace(' ', '_')}_{day}.html"
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
