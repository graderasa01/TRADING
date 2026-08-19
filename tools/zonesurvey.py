#!/usr/bin/env python3
"""
zonesurvey.py — candidate parent ranges, drawn but **not admitted**. No JavaScript.

    python tools/zonesurvey.py
    python tools/zonesurvey.py --days 2026-02-16 2024-12-18 --alternations 3

## What this is, and what it deliberately is not

It is a measuring instrument. Every parent box it draws is a **candidate**, drawn dashed
and labelled PROVISIONAL, and none of them exist in `build_map()`. The question it exists
to answer is not *"where are the ranges"* but:

> do the spans this rule proposes look, on a real chart, like the two-sided auctions a
> trader would draw — or like arbitrary historical envelopes?

That question cannot be settled by a number, which is why this renders rather than
prints. Applying the raw range gates to long spans admitted 3 of ~1,400 spans across five
sessions; the child-zone reading admits ~80 before overlap selection. Whether those 80
are *right* is a matter for eyes.

## The reason column is the deliverable

Every candidate is listed with what happened to it — `accepted`, `rejected-separation`,
`rejected-no-alternation`, `rejected-overlap` and so on — so that a rule which is
throwing away good structures is visible rather than silent.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.anchors import build_anchors  # noqa: E402
from src.boxes.hierarchy import (  # noqa: E402
    MIN_ALTERNATIONS, select_non_overlapping, survey_parent_candidates,
    zone_transitions)
from src.boxes.structure import build_chain  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402

W, H = 1360, 520
PAD_L, PAD_R, PAD_T, PAD_B = 70, 20, 12, 28
DEFAULT_DAYS = ["2026-02-16", "2025-09-12", "2024-12-18", "2024-09-06", "2023-10-04"]


def load(symbol: str, day: date, n: int = 1000):
    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-5:]
    out = []
    for s in feed.sessions(days=days):
        out.extend(s.candles)
    return out[-n:]


def draw(candles, chain, accepted, anchors) -> str:
    n = len(candles)
    lo_v = float(min(k.l for k in candles))
    hi_v = float(max(k.h for k in candles))
    pad = (hi_v - lo_v) * 0.06 or 1.0
    lo_v, hi_v = lo_v - pad, hi_v + pad

    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    cw = iw / max(n, 1)
    X = lambda k: PAD_L + (k + 0.5) * cw                            # noqa: E731
    Y = lambda v: PAD_T + (hi_v - float(v)) / (hi_v - lo_v) * ih    # noqa: E731
    out: list[str] = []

    span = hi_v - lo_v
    tick = 500 if span > 2400 else 200 if span > 900 else 100 if span > 450 else 50
    q = int(lo_v // tick + 1) * tick
    while q < hi_v:
        out.append(f'<line x1="{PAD_L}" y1="{Y(q):.1f}" x2="{PAD_L + iw}" '
                   f'y2="{Y(q):.1f}" stroke="currentColor" stroke-opacity=".09"/>')
        out.append(f'<text x="{PAD_L - 7}" y="{Y(q) + 3.5:.1f}" font-size="10" '
                   f'text-anchor="end" fill="currentColor" opacity=".5">{q:,}</text>')
        q += tick

    # session boundaries
    for i in range(1, n):
        if candles[i].session_date != candles[i - 1].session_date:
            out.append(f'<line x1="{X(i):.1f}" y1="{PAD_T}" x2="{X(i):.1f}" '
                       f'y2="{PAD_T + ih}" stroke="currentColor" stroke-opacity=".25" '
                       f'stroke-dasharray="2 4"/>')

    # candidate parents first, so everything else sits on top
    for sel in accepted:
        r = sel.reading
        x0, x1 = X(r.start), X(r.end) + cw
        for zone, tag in ((r.low_zone, "LOW"), (r.high_zone, "HIGH")):
            out.append(f'<rect x="{x0:.1f}" y="{Y(zone[1]):.1f}" '
                       f'width="{x1 - x0:.1f}" '
                       f'height="{max(Y(zone[0]) - Y(zone[1]), 2):.1f}" '
                       f'fill="var(--zone)" fill-opacity=".16"/>')
            out.append(f'<text x="{x0 + 5:.1f}" y="{Y(zone[1]) - 3:.1f}" '
                       f'font-size="9" font-weight="700" fill="var(--zone)" '
                       f'opacity=".9">{tag}</text>')
        out.append(f'<rect x="{x0:.1f}" y="{Y(r.envelope[1]):.1f}" '
                   f'width="{x1 - x0:.1f}" '
                   f'height="{max(Y(r.envelope[0]) - Y(r.envelope[1]), 2):.1f}" '
                   f'fill="none" stroke="var(--cand)" stroke-width="2" '
                   f'stroke-dasharray="9 5"/>')
        out.append(f'<text x="{x0 + 5:.1f}" y="{Y(r.envelope[1]) + 13:.1f}" '
                   f'font-size="10.5" font-weight="700" fill="var(--cand)">'
                   f'PROVISIONAL {r.sequence}</text>')

        for t in zone_transitions(r, chain):
            up = t.direction == "LOW->HIGH"
            out.append(f'<line x1="{X(t.from_i):.1f}" y1="{Y(t.from_price):.1f}" '
                       f'x2="{X(t.to_i):.1f}" y2="{Y(t.to_price):.1f}" '
                       f'stroke="var(--cand)" stroke-width="1.6" stroke-opacity=".75"/>')
            out.append(f'<circle cx="{X(t.to_i):.1f}" cy="{Y(t.to_price):.1f}" r="3" '
                       f'fill="var(--cand)" opacity=".9"/>')
            out.append(f'<text x="{(X(t.from_i) + X(t.to_i)) / 2:.1f}" '
                       f'y="{(Y(t.from_price) + Y(t.to_price)) / 2 + (-4 if up else 11):.1f}" '
                       f'font-size="9" text-anchor="middle" fill="var(--cand)" '
                       f'opacity=".95">{float(t.points):,.0f}pts/{t.bars}c</text>')

    for ln in chain:
        if ln.is_structure:
            x0, x1 = X(ln.start), X(ln.end) + cw
            out.append(f'<rect x="{x0:.1f}" y="{Y(ln.high):.1f}" '
                       f'width="{max(x1 - x0, 1.5):.1f}" '
                       f'height="{max(Y(ln.low) - Y(ln.high), 1.5):.1f}" '
                       f'fill="var(--cluster)" fill-opacity=".18" '
                       f'stroke="var(--cluster)" stroke-width="1.2"/>')
        elif ln.is_impulse:
            out.append(f'<line x1="{X(ln.start):.1f}" y1="{Y(ln.low):.1f}" '
                       f'x2="{X(ln.end):.1f}" y2="{Y(ln.high):.1f}" '
                       f'stroke="var(--imp)" stroke-width="2.4" stroke-opacity=".85"/>')

    body = max(cw * 0.6, 0.7)
    for k, c in enumerate(candles):
        x = X(k)
        out.append(f'<line x1="{x:.2f}" y1="{Y(c.h):.1f}" x2="{x:.2f}" '
                   f'y2="{Y(c.l):.1f}" stroke="currentColor" stroke-width=".8" '
                   f'stroke-opacity=".72"/>')
        yt, yb = Y(max(c.o, c.c)), Y(min(c.o, c.c))
        out.append(f'<rect x="{x - body / 2:.2f}" y="{yt:.1f}" width="{body:.2f}" '
                   f'height="{max(yb - yt, .8):.1f}" '
                   f'fill="{"var(--bg)" if c.c >= c.o else "currentColor"}" '
                   f'stroke="currentColor" stroke-width=".8"/>')

    # anchors last: they are references, so they must be readable over everything
    for a in anchors:
        y = Y(a.price)
        low = a.kind == "swing_low"
        solid = a.uncovered
        out.append(f'<line x1="{X(a.index):.1f}" y1="{y:.1f}" x2="{PAD_L + iw}" '
                   f'y2="{y:.1f}" stroke="var(--anchor)" '
                   f'stroke-width="{1.5 if solid else 0.9}" '
                   f'stroke-opacity="{0.9 if solid else 0.4}" '
                   f'stroke-dasharray="{"" if solid else "2 5"}"/>')
        out.append(f'<path d="M {X(a.index):.1f} {y + (7 if low else -7):.1f} '
                   f'l -5 {6 if low else -6} l 10 0 z" fill="var(--anchor)" '
                   f'opacity="{0.95 if solid else 0.45}"/>')
        if solid:
            out.append(f'<text x="{X(a.index) + 7:.1f}" '
                       f'y="{y + (16 if low else -8):.1f}" font-size="9.5" '
                       f'font-weight="700" fill="var(--anchor)">'
                       f'{a.id} {float(a.price):,.0f}</text>')

    for k in range(0, n, max(1, n // 8)):
        out.append(f'<text x="{X(k):.1f}" y="{H - 8}" font-size="10" '
                   f'text-anchor="middle" fill="currentColor" opacity=".45">'
                   f'{candles[k].open_time:%d %b %H:%M}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">'
            + "".join(out) + "</svg>")


def day_block(symbol: str, iso: str, alternations: int) -> tuple[str, Counter, int]:
    candles = load(symbol, date.fromisoformat(iso))
    chain, _ = build_chain(candles)
    readings = survey_parent_candidates(chain, candles)
    sels = select_non_overlapping(readings, chain, min_alternations=alternations)
    accepted = [s for s in sels if s.reason.startswith("accepted")]
    tally = Counter(s.reason for s in sels)
    anchors = build_anchors(chain, candles)
    bare = [a for a in anchors if a.uncovered]

    alt3 = select_non_overlapping(readings, chain, min_alternations=3)
    n_alt3 = sum(1 for s in alt3 if s.reason.startswith("accepted"))

    rows = []
    for s in sorted(accepted, key=lambda s: s.reading.start):
        r = s.reading
        trans = zone_transitions(r, chain)
        story = " ".join(f"{t.from_id}&rarr;{t.to_id} ({float(t.points):,.0f}pts/"
                         f"{t.bars}c)" for t in trans)
        rows.append(
            f"<tr><td>c{r.start}-{r.end}</td><td>{r.bars}</td>"
            f"<td>{len(r.children)}</td>"
            f"<td>{float(r.envelope[0]):,.0f}&ndash;{float(r.envelope[1]):,.0f}</td>"
            f"<td>{float(r.low_zone[0]):,.0f}&ndash;{float(r.low_zone[1]):,.0f}</td>"
            f"<td>{float(r.high_zone[0]):,.0f}&ndash;{float(r.high_zone[1]):,.0f}</td>"
            f"<td>{r.sequence}</td><td>{r.alternations}</td>"
            f"<td>{r.shelf_ratio:.2f}</td><td>{r.migration:.2f}</td>"
            f"<td class='story'>{story or '&mdash;'}</td></tr>")

    reasons = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                      for k, v in tally.most_common())

    head = (f"{iso} &middot; {len(candles)} candles &middot; "
            f"{sum(1 for ln in chain if ln.is_structure)} clusters &middot; "
            f"<b>{len(accepted)} candidate parent"
            f"{'' if len(accepted) == 1 else 's'}</b> at alternations&ge;{alternations}"
            f" &middot; {n_alt3} at &ge;3 &middot; "
            f"<b>{len(anchors)} anchors</b> ({len(bare)} with no box on them)")

    arows = "".join(
        f"<tr><td>{a.id}</td><td>{a.kind.replace('swing_', '')}</td>"
        f"<td>{a.role.replace('impulse_', '')}</td>"
        f"<td>{float(a.price):,.0f}</td><td>c{a.index}</td>"
        f"<td>{float(a.displacement):,.0f}</td><td>{a.er:.2f}</td>"
        f"<td>{', '.join(a.moves)}</td>"
        f"<td>{'&mdash;' if a.uncovered else a.covered_by}</td>"
        f"<td>{'' if a.from_pivot else 'extreme candle'}</td></tr>"
        for a in sorted(anchors, key=lambda a: -a.displacement)[:12])

    table = (
        "<table><thead><tr><th>span</th><th>bars</th><th>kids</th><th>envelope</th>"
        "<th>LOW zone</th><th>HIGH zone</th><th>seq</th><th>alt</th>"
        "<th>sep/shelf</th><th>mig</th><th>rotation story</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=11>no candidate</td></tr>'}"
        "</tbody></table>")

    atable = (
        "<details open><summary><b>structural anchors</b> &mdash; biggest 12 by "
        "displacement. Solid line + label = <b>no box on it</b>, the case this layer "
        "exists for.</summary>"
        "<table><thead><tr><th>id</th><th>kind</th><th>role</th><th>price</th>"
        "<th>at</th><th>displacement</th><th>er</th><th>move</th><th>inside</th>"
        "<th>note</th></tr></thead>"
        f"<tbody>{arows or '<tr><td colspan=10>none</td></tr>'}</tbody></table></details>")

    block = (f"<h2>{head}</h2>{draw(candles, chain, accepted, anchors)}{table}{atable}"
             f"<details><summary>{sum(tally.values())} candidates, "
             f"what happened to each</summary>"
             f"<table class='small'><tbody>{reasons}</tbody></table></details>")
    return block, tally, len(accepted)


def render(symbol: str, days: list[str], alternations: int, out_dir: Path) -> Path:
    blocks, grand, per_day = [], Counter(), []
    for iso in days:
        b, t, n = day_block(symbol, iso, alternations)
        blocks.append(b)
        grand.update(t)
        per_day.append((iso, n))

    summary = "".join(f"<tr><td>{iso}</td><td>{n}</td></tr>" for iso, n in per_day)
    reasons = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>"
                      for k, v in grand.most_common())

    html = f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} — candidate parent ranges (measurement only)</title>
<style>
  :root {{ color-scheme: light dark; --ink:#16181d; --bg:#fff;
          --cluster:#1d6fd0; --cand:#c2760a; --zone:#0f9d76; --imp:#c0392b;
          --anchor:#8b5cf6; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e9e9ec; --bg:#14161a; --cluster:#6aa8f5; --cand:#f0b24a;
            --zone:#4fd1a5; --imp:#ff7b6b; --anchor:#b794f6; }} }}
  body {{ font:13px/1.55 ui-sans-serif,system-ui,sans-serif; margin:0; padding:16px;
         color:var(--ink); background:var(--bg); max-width:1420px; }}
  h1 {{ font-size:17px; margin:0 0 4px; }}
  h2 {{ font-size:12.5px; margin:26px 0 6px; font-weight:650;
       font-variant-numeric:tabular-nums; }}
  .warn {{ border:2px solid var(--cand); border-radius:7px; padding:10px 13px;
          margin:0 0 12px; font-size:12.5px; }}
  .key {{ font-size:12px; opacity:.88; padding:10px 13px; border-radius:7px;
         border:1px solid color-mix(in srgb, currentColor 18%, transparent);
         margin:0 0 8px; }}
  svg {{ display:block; width:100%; height:auto; }}
  table {{ border-collapse:collapse; font-size:11.5px; margin:8px 0 4px;
          font-variant-numeric:tabular-nums; width:100%; }}
  th,td {{ text-align:left; padding:3px 8px;
          border-bottom:1px solid color-mix(in srgb, currentColor 14%, transparent); }}
  th {{ opacity:.62; font-weight:600; }}
  .story {{ opacity:.85; }}
  .small {{ max-width:420px; }}
  details {{ margin:4px 0 0; font-size:12px; opacity:.85; }}
  .c {{ color:var(--cluster); font-weight:650; }}
  .o {{ color:var(--cand); font-weight:650; }}
  .z {{ color:var(--zone); font-weight:650; }}
  .i {{ color:var(--imp); font-weight:650; }}
  .a {{ color:var(--anchor); font-weight:650; }}
</style>
<h1>{symbol} &mdash; candidate parent ranges</h1>
<div class="warn"><b>MEASUREMENT ONLY.</b> Nothing on this page is admitted to the map.
<code>build_map()</code> does not know these boxes exist. The dashed outlines are
<b>candidates</b> produced by a hypothesis — child zones separated by more than a shelf is
thick, with price alternating between them &mdash; and the question this page exists to
answer is whether they look like auctions a trader would draw, or arbitrary envelopes.
<code>MIN_ALTERNATIONS</code> and the shelf-width separation are <b>unvalidated</b>.</div>
<div class="key">
<span class="o">Dashed amber box</span> = candidate parent envelope, with its LOW/HIGH
child zones shaded <span class="z">green</span> and the rotation between them drawn as
lines with points/candles.<br>
<span class="c">Blue box = CLUSTER</span> from the chain &mdash; these are real, they are
in the map. <span class="i">Red line = IMPULSE</span>.<br>
Vertical dotted lines are session boundaries. A structure may span them; the overnight
jump itself is a <code>gap</code> event and never an impulse.<br>
<span class="a">Purple triangle + ray = STRUCTURAL ANCHOR</span> &mdash; a swing low/high a move
launched from or terminated at. <b>Solid line with a label</b> means <b>no box sits on
it</b>: price came once, never stayed, so it is correctly not a cluster &mdash; but it is
where the move began, and it must not vanish from the map. Faint dashed = the anchor is
already inside a cluster, which speaks for it.<br>
<b>seq</b> = each child as L or H in time order. <b>alt</b> = how many times it flipped.
<b>sep/shelf</b> = gap between zones &divide; a typical shelf's own width.<br>
Anchors use the repo's existing <code>swings.py</code> pivot detector &mdash; no second
swing engine. They are selected on <b>displacement only</b>, never on efficiency: the
+326pt / <code>er 0.28</code> run on 16 Feb is correctly not an impulse, and the low it
launched from still matters.
</div>
<table class="small"><thead><tr><th>day</th><th>candidate parents</th></tr></thead>
<tbody>{summary}</tbody></table>
<details open><summary>all candidates across all days, by outcome</summary>
<table class="small"><tbody>{reasons}</tbody></table></details>
{''.join(blocks)}
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"zonesurvey_{symbol.replace(' ', '_')}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--days", nargs="+", default=DEFAULT_DAYS)
    ap.add_argument("--alternations", type=int, default=MIN_ALTERNATIONS)
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "structmap"))
    args = ap.parse_args(argv)
    path = render(args.symbol, args.days, args.alternations, Path(args.out))
    print(f"wrote {path}   ({path.stat().st_size // 1024} KB, no JavaScript)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
