#!/usr/bin/env python3
"""
chart.py — the annotation chart. BUILD-PLAN §3.1.

    python tools/chart.py --selection reports/charts/selection.json   # all 10, blank
    python tools/chart.py --day 2026-03-04                            # one session
    python tools/chart.py --day 2026-03-04 --tf 60m,15m,5m,1m         # any timeframes
    python tools/chart.py --day 2026-03-04 --levels                   # engine book overlaid

One standalone HTML file per session. No server, no CDN, no build step — double-click it.
Panels share **one price scale**, so a line at 57,698 sits at the same height in every
panel. That is how the levels are actually drawn: `mythinking.md` §1 — *"15-min: Levels +
bias. Map. 5-min: ye mera ghar hai."*

## Why this was rewritten

The first version drew all 375 one-minute candles into a fixed 1000-unit viewBox. That is
2.5 units per candle, so every body was a 1.5-unit hairline and the 1m panel read as a
squiggle. You cannot "point at candle 76 and ask what happened" on a chart where candle 76
is one pixel wide. Worse, the layout was a hard `1fr 260px` grid with `preserveAspect
Ratio="none"`, so any window under about 1000px collapsed the chart column to a sliver and
squashed the candles vertically — which is what a preview pane does.

Three fixes, and the first is the one that matters:

1. **Synced zoom and pan.** Wheel to zoom, drag to pan, double-click to reset. All panels
   follow one shared window expressed in 1m index space, so the 15m, 5m and 1m panels are
   always showing the same stretch of the day. The price scale rescales to what is
   visible — still shared across panels, so the "same height in every panel" property
   holds.
2. **Real geometry.** The SVG viewBox is measured from the container in actual pixels and
   redrawn on resize, so nothing is ever stretched or squashed.
3. **It reflows.** Under 1000px the sidebar moves below the chart instead of strangling it.

## Timeframes

`--tf` takes any minute multiples. These are **display-only** resamplings computed here,
deliberately not routed through `domain.TF_MINUTES` — adding `30m` there would change what
a `Candle` is allowed to be across the whole engine, and spec 04's cardinal rule
(15m WHERE / 5m WHAT / 1m WHEN) is a design commitment, not a chart setting. Looking at a
60m panel to check a level costs nothing; letting the engine trade one is a decision that
belongs in `DECISIONS.md`. `test_resample_matches_the_aggregator` pins the display path to
the real aggregator at 5m and 15m so the two can never drift.

## Pointing at a candle

Hover anywhere: the readout gives the candle index, its time, its full OHLC and the price
under the cursor. Click: a horizontal line is drawn across every panel and the level joins
the list, ready to copy as YAML. The candle index is what the annotation schema references,
which is why it is on screen at all times rather than every tenth candle.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401  (console encoding, see module)

from src.config.loader import load_config  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.p1_pipeline import P1Pipeline  # noqa: E402

SESSION_OPEN = timedelta(hours=9, minutes=15)


def resample(candles, minutes: int) -> list[list[Any]]:
    """1m candles -> [index, "HH:MM", o, h, l, c] at any minute multiple.

    Buckets by minutes elapsed since 09:15, which is what makes an Indian 15m bar run
    09:15-09:30 rather than 09:00-09:15. Display only — see the module docstring.
    """
    out: list[list[Any]] = []
    bucket: list = []
    current = None
    for candle in candles:
        t = candle.open_time
        elapsed = (timedelta(hours=t.hour, minutes=t.minute) - SESSION_OPEN)
        key = int(elapsed.total_seconds() // 60) // minutes
        if current is None or key != current:
            if bucket:
                out.append(_bar(bucket, len(out)))
            bucket, current = [candle], key
        else:
            bucket.append(candle)
    if bucket:
        out.append(_bar(bucket, len(out)))
    return out


def _bar(group: list, index: int) -> list[Any]:
    return [index, group[0].open_time.strftime("%H:%M"),
            float(group[0].o), float(max(c.h for c in group)),
            float(min(c.l for c in group)), float(group[-1].c)]


HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark; --ink: #16181d; --bg: #fff; }
  @media (prefers-color-scheme: dark) { :root { --ink: #e8e8ea; --bg: #16181d; } }
  * { box-sizing: border-box; }
  body { font: 13px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0; padding: 14px 16px;
         color: var(--ink); background: var(--bg); overflow-x: hidden; }
  h1 { font-size: 16px; margin: 0 0 2px; font-weight: 620; }
  .sub { opacity: .62; margin: 0 0 12px; font-size: 12px; }
  .wrap { display: grid; grid-template-columns: minmax(0, 1fr) 264px; gap: 16px;
          align-items: start; }
  @media (max-width: 1000px) { .wrap { grid-template-columns: minmax(0, 1fr); } }
  #panels { min-width: 0; }
  .panel { position: relative; margin-bottom: 8px; min-width: 0; }
  .panel h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .07em;
              opacity: .55; margin: 0 0 2px; font-weight: 600;
              display: flex; justify-content: space-between; }
  svg { display: block; width: 100%; touch-action: none; cursor: crosshair; }
  svg.panning { cursor: grabbing; }
  .side { position: sticky; top: 14px; }
  @media (max-width: 1000px) { .side { position: static; } }
  .card { border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
          border-radius: 7px; padding: 11px 13px; margin-bottom: 11px; }
  .read { font-variant-numeric: tabular-nums; font-size: 12px; }
  .read b { font-size: 15px; font-weight: 640; }
  .read div { display: flex; justify-content: space-between; gap: 12px; }
  .muted { opacity: .55; }
  ul { list-style: none; margin: 0; padding: 0; font-variant-numeric: tabular-nums; }
  li { display: flex; justify-content: space-between; align-items: center; padding: 3px 0;
       border-bottom: 1px solid color-mix(in srgb, currentColor 10%, transparent); }
  li button { border: 0; background: none; cursor: pointer; color: inherit; opacity: .45;
              font-size: 15px; line-height: 1; padding: 0 2px; }
  li button:hover { opacity: 1; }
  textarea { width: 100%; height: 170px; font: 11.5px/1.45 ui-monospace, monospace;
             border-radius: 6px; padding: 8px;
             border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
             background: transparent; color: inherit; }
  .btn { font: inherit; padding: 5px 11px; border-radius: 6px; cursor: pointer;
         border: 1px solid color-mix(in srgb, currentColor 28%, transparent);
         background: transparent; color: inherit; }
  .btn:hover { background: color-mix(in srgb, currentColor 8%, transparent); }
  .hint { font-size: 11.5px; opacity: .6; margin: 8px 0 0; }
  .bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px;
         font-size: 12px; flex-wrap: wrap; }
  .bar .muted { font-variant-numeric: tabular-nums; }
</style>

<h1>__HEADING__</h1>
<p class="sub">__SUBTITLE__</p>

<div class="bar">
  <button class="btn" id="zoomout">&minus;</button>
  <button class="btn" id="zoomin">+</button>
  <button class="btn" id="reset">Full day</button>
  <span class="muted" id="range"></span>
  <span class="muted">wheel = zoom &middot; drag = pan &middot; double-click = reset</span>
</div>
<p class="sub" id="didwhat" style="margin:-4px 0 10px;min-height:18px"></p>

<div class="bar" id="livebar">
  <button class="btn" id="stepb" title="one candle back">&#9664;|</button>
  <button class="btn" id="play">&#9654; Play</button>
  <button class="btn" id="stepf" title="one candle forward">|&#9654;</button>
  <select class="btn" id="speed" title="replay speed">
    <option value="2000">2.0 s / candle &mdash; slowest</option>
    <option value="1000">1.0 s / candle &mdash; very slow</option>
    <option value="500" selected>0.5 s / candle &mdash; slow</option>
    <option value="200">0.2 s / candle</option>
    <option value="80">0.08 s / candle</option>
    <option value="25">0.025 s / candle &mdash; fast</option>
  </select>
  <input type="range" id="scrub" min="0" value="0" style="flex:1;min-width:180px">
  <span class="muted" id="nowlabel"></span>
  <button class="btn" id="toend">End of day</button>
  <label class="muted" style="display:flex;gap:5px;align-items:center;cursor:pointer">
    <input type="checkbox" id="showall"> show every level the engine built
  </label>
</div>

<div class="wrap">
  <div id="panels"></div>
  <div class="side">
    <div class="card read" id="readout"><span class="muted">hover the chart</span></div>
    <div class="card" id="storycard" style="display:none">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
        <strong style="font-size:12px">THIS LEVEL</strong>
        <button class="btn" id="closestory" style="padding:1px 7px">&times;</button>
      </div>
      <div id="story" class="read"></div>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px">
        <strong style="font-size:12px">MARKED LEVELS</strong>
        <span class="muted" id="count">0</span>
      </div>
      <ul id="marks"></ul>
      <p class="hint">Click any panel to mark a level. Click a line again to remove it.</p>
    </div>
    <div class="card">
      <textarea id="yaml" readonly></textarea>
      <div style="margin-top:8px;display:flex;gap:7px">
        <button class="btn" id="copy">Copy YAML</button>
        <button class="btn" id="clear">Clear</button>
      </div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
const MARKS = [];
const PANELS = [];
const PAD_L = 62, PAD_R = 14, PAD_T = 8, PAD_B = 20;
const N1 = DATA.tf["1m"].length;
const MIN_SPAN = 15;
let VIEW = { lo: 0, hi: N1 - 1 };
let NOW = N1 - 1;                       // the last candle the engine has been shown
let TIMER = null;
let PICKED = null;
let SHOW_ALL = false;

/* Change-point series: [[candleIndex, value], ...]. What was it at candle i? */
function valueAt(series, i) {
  let v = null;
  for (const [k, value] of series) { if (k > i) break; v = value; }
  return v;
}

/* Only levels the engine had actually built by NOW. A level born at 11:40 must not be
   on screen at 10:00 — that is the whole point of the scrub. */
function visibleLevels() {
  return (DATA.engine || []).filter(lv => {
    if (lv.born > NOW) return false;
    if (SHOW_ALL || lv.id === PICKED) return true;
    /* A change-point series freezes at the level's last update, so a level that died at
       candle 7 keeps reporting the `shown` value it had then. Death has to be checked
       explicitly or the book fills with ghosts. */
    if (lv.died !== null && lv.died <= NOW) return false;
    /* By default only the book the trader would actually see: the 8 that survived the
       cap at this moment. On 2026-02-16 the engine BUILT 175 levels and showed 8 — a
       chart with all 175 on it is a true picture of nothing. */
    return valueAt(lv.shown, NOW) === true;
  });
}

const clampView = () => {
  if (VIEW.hi - VIEW.lo < MIN_SPAN) VIEW.hi = VIEW.lo + MIN_SPAN;
  if (VIEW.lo < 0) { VIEW.hi -= VIEW.lo; VIEW.lo = 0; }
  if (VIEW.hi > N1 - 1) { VIEW.lo -= (VIEW.hi - (N1 - 1)); VIEW.hi = N1 - 1; }
  if (VIEW.lo < 0) VIEW.lo = 0;
};

/* The price scale is taken from the 1m candles inside the visible window and shared by
   every panel — so zooming makes the candles readable without the panels drifting out of
   alignment with each other. */
function extent() {
  let lo = Infinity, hi = -Infinity;
  for (let i = Math.floor(VIEW.lo); i <= Math.ceil(VIEW.hi) && i < N1; i++) {
    const r = DATA.tf["1m"][i];
    if (r[4] < lo) lo = r[4];
    if (r[3] > hi) hi = r[3];
  }
  if (!isFinite(lo)) return [0, 1];
  const pad = Math.max((hi - lo) * 0.06, 1);
  return [lo - pad, hi + pad];
}

const slice = p => {                       // the shared 1m window in this panel's indices
  const lo = Math.max(0, Math.floor(VIEW.lo / p.min));
  const hi = Math.min(p.rows.length - 1, Math.ceil(VIEW.hi / p.min));
  return [lo, Math.max(lo, hi)];
};

function draw(p) {
  const [LO, HI] = extent();
  const [a, b] = slice(p);
  const n = b - a + 1;
  const W = p.el.clientWidth || 900, H = p.H;
  const iw = W - PAD_L - PAD_R, ih = H - PAD_T - PAD_B;
  const cw = iw / n;
  const X = k => PAD_L + (k - a + 0.5) * cw;
  const Y = q => PAD_T + (HI - q) / (HI - LO) * ih;
  const bw = Math.max(1, Math.min(cw * 0.68, 26));

  let s = '';
  const span = HI - LO;
  const step = span > 900 ? 200 : span > 400 ? 100 : span > 150 ? 50 : span > 60 ? 20 : 10;
  for (let q = Math.ceil(LO / step) * step; q < HI; q += step) {
    const y = Y(q).toFixed(1);
    s += `<line x1="${PAD_L}" y1="${y}" x2="${W - PAD_R}" y2="${y}" stroke="currentColor"
          stroke-opacity="${q % (step * 5) === 0 ? .17 : .07}"/>`;
    s += `<text x="${PAD_L - 7}" y="${(+y + 3.5).toFixed(1)}" font-size="10" text-anchor="end"
          fill="currentColor" opacity=".5">${q.toLocaleString('en-IN')}</text>`;
  }

  for (let k = a; k <= b; k++) {
    const r = p.rows[k];
    if (!r) continue;
    if (k * p.min > NOW) break;          /* nothing after the scrub position exists yet */
    const [, , o, h, l, c] = r, up = c >= o, x = X(k);
    s += `<line x1="${x.toFixed(1)}" y1="${Y(h).toFixed(1)}" x2="${x.toFixed(1)}"
          y2="${Y(l).toFixed(1)}" stroke="currentColor" stroke-width="1"
          stroke-opacity=".75"/>`;
    const yt = Y(Math.max(o, c)), yb = Y(Math.min(o, c));
    s += `<rect x="${(x - bw / 2).toFixed(1)}" y="${yt.toFixed(1)}" width="${bw.toFixed(1)}"
          height="${Math.max(yb - yt, 1).toFixed(1)}" fill="${up ? 'var(--bg)' : 'currentColor'}"
          stroke="currentColor" stroke-width="1"/>`;
  }

  const every = Math.max(1, Math.ceil(n / Math.max(4, Math.floor(W / 82))));
  for (let k = a; k <= b; k++) {
    if ((k - a) % every || !p.rows[k]) continue;
    s += `<text x="${X(k).toFixed(1)}" y="${H - 6}" font-size="10" text-anchor="middle"
          fill="currentColor" opacity=".5">${p.rows[k][1]}</text>`;
  }

  /* The stateless box stack — BOX-MODEL.md. Each box spans its OWN lookback in x, so
     you can see how far back it was derived from. All four are re-derived every candle;
     nothing here is stored. */
  if (DATA.boxes) {
    const row = DATA.boxes.rows[Math.min(NOW, DATA.boxes.rows.length - 1)];
    const style = { l3: [.30, 1.6], l2: [.16, 1.3], l1: [.09, 1.1], l0: [.05, 1.0] };
    ['l0', 'l1', 'l2', 'l3'].forEach(nm => {
      const idx = { l3: 0, l2: 1, l1: 2, l0: 3 }[nm];
      const bx = row && row[idx];
      if (!bx) return;
      const [il, ih, ol, oh, degen] = bx;
      const back = DATA.boxes.windows[nm];
      const x0 = Math.max(PAD_L, PAD_L + ((NOW - back) / p.min - a + 0.5) * cw);
      const x1 = Math.min(W - PAD_R, PAD_L + (NOW / p.min - a + 1.5) * cw);
      if (x1 <= x0) return;
      const [op, sw] = style[nm];
      /* outer band = where the excursions reached. This is the edge a stop sits beyond,
         and it is the stable one: measured at 0.235 xATR of movement per candle against
         0.430 for the inner band. */
      s += `<rect x="${x0.toFixed(1)}" y="${Y(oh).toFixed(1)}"
            width="${(x1 - x0).toFixed(1)}"
            height="${Math.max(Y(ol) - Y(oh), 1).toFixed(1)}"
            fill="none" stroke="currentColor" stroke-width="${sw}"
            stroke-opacity="${op + .12}" stroke-dasharray="4 3"/>`;
      if (!degen) s += `<rect x="${x0.toFixed(1)}" y="${Y(ih).toFixed(1)}"
            width="${(x1 - x0).toFixed(1)}"
            height="${Math.max(Y(il) - Y(ih), 1).toFixed(1)}"
            fill="currentColor" fill-opacity="${op * .35}"
            stroke="currentColor" stroke-width="${sw}" stroke-opacity="${op + .25}"/>`;
      if (p.last) s += `<text x="${(x0 + 4).toFixed(1)}" y="${(Y(oh) + 11).toFixed(1)}"
            font-size="10" fill="currentColor" opacity=".6"
            >${nm.toUpperCase()}${degen ? ' (travelling)' : ''}</text>`;
    });
  }

  /* Zones, not lines — spec 03 §4. Each box starts at the candle the level was BORN on
     and ends where it died, so nothing is drawn across time the engine did not know it
     in. `x1m` converts a 1m candle index into this panel's x, which is what lets a 1m
     birth be positioned correctly on the 15m and 60m panels. */
  const x1m = i => PAD_L + (i / p.min - a + 0.5) * cw;
  p.boxes = [];
  for (const lv of visibleLevels()) {
    if (lv.zhi < LO || lv.zlo > HI) continue;
    const g = valueAt(lv.grades, NOW), shown = valueAt(lv.shown, NOW),
          touch = valueAt(lv.touches, NOW);
    const x0 = Math.max(PAD_L, x1m(lv.born));
    const x1 = Math.min(W - PAD_R, x1m(lv.died === null ? NOW : lv.died));
    const yt = Y(lv.zhi), yb = Y(lv.zlo);
    const h = Math.max(yb - yt, 1.6);
    const op = g === 'A' ? .17 : g === 'B' ? .10 : .055;

    s += `<rect x="${x0.toFixed(1)}" y="${yt.toFixed(1)}"
          width="${Math.max(x1 - x0, 2).toFixed(1)}" height="${h.toFixed(1)}"
          fill="currentColor" fill-opacity="${op}"/>`;
    const dash = g === 'A' ? 'none' : (g === 'B' ? '6 4' : '2 4');
    s += `<line x1="${x0.toFixed(1)}" y1="${Y(lv.body).toFixed(1)}"
          x2="${(W - PAD_R).toFixed(1)}" y2="${Y(lv.body).toFixed(1)}" stroke="currentColor"
          stroke-width="${g === 'A' ? 1.8 : g === 'B' ? 1.2 : 1}" stroke-dasharray="${dash}"
          stroke-opacity="${shown ? .7 : .28}"/>`;
    /* the candles it was built from */
    for (const j of lv.source) {
      if (j / p.min < a || j / p.min > b) continue;
      s += `<circle cx="${x1m(j).toFixed(1)}" cy="${Y(lv.wick).toFixed(1)}" r="2.6"
            fill="none" stroke="currentColor" stroke-width="1.3" stroke-opacity=".85"/>`;
    }
    if (p.last) {
      s += `<text x="${(W - PAD_R - 3)}" y="${(Y(lv.body) - 3).toFixed(1)}" font-size="10"
            text-anchor="end" fill="currentColor" opacity="${shown ? .7 : .35}"
            >${lv.kind} ${g} t${touch}${lv.died !== null ? ' \\u2020' : ''}</text>`;
      p.boxes.push({ lv, x0, x1: W - PAD_R, yt, yb: yt + h });
    }
  }

  p.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  p.svg.setAttribute('height', H);
  p.W = W; p.X = X; p.Y = Y; p.a = a; p.cw = cw; p.iw = iw; p.ih = ih;
  p.LO = LO; p.HI = HI;
  p.static.innerHTML = s;
  p.head.textContent = `${p.tf} · ${n} of ${p.rows.length} bars`;
}

function drawAll() {
  clampView();
  PANELS.forEach(draw);
  renderMarks();
  const t0 = DATA.tf["1m"][Math.floor(VIEW.lo)], t1 = DATA.tf["1m"][Math.floor(VIEW.hi)];
  document.getElementById('range').textContent =
    `candles ${Math.floor(VIEW.lo)}–${Math.floor(VIEW.hi)}  ·  ${t0[1]}–${t1[1]}`;
}

function build(tf, minutes, height, last) {
  const wrap = document.createElement('div');
  wrap.className = 'panel';
  wrap.innerHTML = `<h2><span class="ttl"></span></h2>
    <svg preserveAspectRatio="none"><g class="static"></g><g class="mk"></g>
    <g class="cross" style="pointer-events:none"></g></svg>`;
  document.getElementById('panels').appendChild(wrap);

  const p = { tf, min: minutes, H: height, last, rows: DATA.tf[tf], el: wrap,
              svg: wrap.querySelector('svg'), static: wrap.querySelector('.static'),
              mk: wrap.querySelector('.mk'), cross: wrap.querySelector('.cross'),
              head: wrap.querySelector('.ttl') };
  PANELS.push(p);

  const at = ev => {
    const box = p.svg.getBoundingClientRect();
    return [(ev.clientX - box.left) / box.width * p.W,
            (ev.clientY - box.top) / box.height * p.H];
  };
  const idx1m = x => VIEW.lo + (x - PAD_L) / p.iw * (VIEW.hi - VIEW.lo);
  const price = y => p.HI - (y - PAD_T) / p.ih * (p.HI - p.LO);

  let drag = null, moved = 0;
  p.svg.addEventListener('mousedown', ev => {
    drag = { x: ev.clientX, lo: VIEW.lo, hi: VIEW.hi }; moved = 0;
    p.svg.classList.add('panning');
  });
  window.addEventListener('mouseup', () => { drag = null; p.svg.classList.remove('panning'); });
  p.svg.addEventListener('mousemove', ev => {
    const [x, y] = at(ev);
    if (drag) {
      moved += Math.abs(ev.clientX - drag.x);
      const box = p.svg.getBoundingClientRect();
      const shift = (drag.x - ev.clientX) / box.width * (drag.hi - drag.lo);
      VIEW = { lo: drag.lo + shift, hi: drag.hi + shift };
      drawAll();
      return;
    }
    hover(p, x, y, idx1m(x), price(y));
  });
  p.svg.addEventListener('mouseleave', () => {
    PANELS.forEach(q => q.cross.innerHTML = '');
    document.getElementById('readout').innerHTML =
      '<span class="muted">hover the chart</span>';
  });
  p.svg.addEventListener('wheel', ev => {
    ev.preventDefault();
    zoom(ev.deltaY > 0 ? 1.22 : 1 / 1.22, idx1m(at(ev)[0]));
  }, { passive: false });
  p.svg.addEventListener('click', ev => {
    if (moved > 4) return;                      // a pan, not a click
    const [x, y] = at(ev);
    const hit = (p.boxes || []).find(bx => y >= bx.yt - 3 && y <= bx.yb + 3
                                        && x >= bx.x0 - 2 && x <= bx.x1);
    if (hit) { PICKED = hit.lv.id; story(hit.lv); return; }
    addMark(+price(y).toFixed(1), Math.round(idx1m(x)));
  });
  p.svg.addEventListener('dblclick', () => { VIEW = { lo: 0, hi: N1 - 1 }; drawAll(); });
}

function zoom(factor, anchor) {
  const width = (VIEW.hi - VIEW.lo) * factor;
  const frac = (anchor - VIEW.lo) / (VIEW.hi - VIEW.lo);
  VIEW = { lo: anchor - width * frac, hi: anchor + width * (1 - frac) };
  drawAll();
}

function hover(src, x, y, i1m, price) {
  const k = Math.max(0, Math.min(src.rows.length - 1, Math.floor(i1m / src.min)));
  const r = src.rows[k];
  document.getElementById('readout').innerHTML =
    `<div><span class="muted">1m candle</span><b>${Math.round(i1m)}</b></div>
     <div><span class="muted">${src.tf} bar</span><b>${r[1]}</b></div>
     <div><span class="muted">O</span><span>${r[2].toFixed(2)}</span></div>
     <div><span class="muted">H</span><span>${r[3].toFixed(2)}</span></div>
     <div><span class="muted">L</span><span>${r[4].toFixed(2)}</span></div>
     <div><span class="muted">C</span><span>${r[5].toFixed(2)}</span></div>
     <div style="margin-top:6px"><span class="muted">cursor</span>
       <b>${price.toFixed(1)}</b></div>`;
  for (const p of PANELS) {
    const yy = p.Y(price);
    let s = `<line x1="${PAD_L}" y1="${yy.toFixed(1)}" x2="${p.W - PAD_R}"
             y2="${yy.toFixed(1)}" stroke="currentColor" stroke-width="1"
             stroke-dasharray="3 3" stroke-opacity=".6"/>`;
    if (p === src) s += `<line x1="${x.toFixed(1)}" y1="${PAD_T}" x2="${x.toFixed(1)}"
             y2="${p.H - PAD_B}" stroke="currentColor" stroke-width="1"
             stroke-dasharray="3 3" stroke-opacity=".45"/>`;
    p.cross.innerHTML = s;
  }
}

function addMark(price, candle) {
  const near = MARKS.findIndex(m => Math.abs(m.price - price) < (PANELS[0].HI - PANELS[0].LO) * 0.006);
  if (near >= 0) MARKS.splice(near, 1); else MARKS.push({ price, candle });
  MARKS.sort((a, b) => b.price - a.price);
  drawAll();
}

function renderMarks() {
  for (const p of PANELS) {
    p.mk.innerHTML = MARKS.map(m => {
      if (m.price < p.LO || m.price > p.HI) return '';
      const y = p.Y(m.price).toFixed(1);
      return `<line x1="${PAD_L}" y1="${y}" x2="${p.W - PAD_R}" y2="${y}"
              stroke="currentColor" stroke-width="1.7" stroke-opacity=".95"/>`;
    }).join('');
  }
  document.getElementById('count').textContent = MARKS.length;
  document.getElementById('marks').innerHTML = MARKS.map((m, i) =>
    `<li><span>${m.price.toLocaleString('en-IN')}
     <span class="muted" style="font-size:11px">&nbsp;c${m.candle}</span></span>
     <button data-i="${i}">&times;</button></li>`).join('');
  document.querySelectorAll('#marks button').forEach(b =>
    b.onclick = () => { MARKS.splice(+b.dataset.i, 1); drawAll(); });

  document.getElementById('yaml').value =
    `# P1 level-overlap gate (spec 09 3.2b)\\n` +
    `# Marked BEFORE seeing any engine output.\\n` +
    `session: "${DATA.day}"\\n` +
    `symbol: "${DATA.symbol}"\\n` +
    `annotator: ""\\n` +
    `marked_before_engine_output: ${DATA.engine.length ? 'false' : 'true'}\\n` +
    `levels:\\n` +
    (MARKS.length ? MARKS.map(m =>
      `  - price: ${m.price}\\n    candle: ${m.candle}\\n    kind: ""      ` +
      `# turn | launch | break | anchor\\n    note: ""\\n`).join('')
      : `  []   # nothing marked yet\\n`);
}

for (const [tf, minutes, height, last] of DATA.panels) build(tf, minutes, height, last);
drawAll();
new ResizeObserver(() => drawAll()).observe(document.getElementById('panels'));

document.getElementById('reset').onclick = () => { VIEW = { lo: 0, hi: N1 - 1 }; drawAll(); };
document.getElementById('zoomin').onclick = () => zoom(1 / 1.4, (VIEW.lo + VIEW.hi) / 2);
document.getElementById('zoomout').onclick = () => zoom(1.4, (VIEW.lo + VIEW.hi) / 2);
document.addEventListener('keydown', ev => {
  const w = VIEW.hi - VIEW.lo;
  if (ev.key === 'ArrowRight') { VIEW = { lo: VIEW.lo + w * .2, hi: VIEW.hi + w * .2 }; drawAll(); }
  if (ev.key === 'ArrowLeft')  { VIEW = { lo: VIEW.lo - w * .2, hi: VIEW.hi - w * .2 }; drawAll(); }
  if (ev.key === '+' || ev.key === '=') zoom(1 / 1.4, (VIEW.lo + VIEW.hi) / 2);
  if (ev.key === '-') zoom(1.4, (VIEW.lo + VIEW.hi) / 2);
  if (ev.key === '0') { VIEW = { lo: 0, hi: N1 - 1 }; drawAll(); }
  if (ev.key === '.') { stop(); setNow(NOW + 1); }
  if (ev.key === ',') { stop(); setNow(NOW - 1); }
  if (ev.key === ' ') { ev.preventDefault(); document.getElementById('play').click(); }
});
/* ── the level's own history ──────────────────────────────────────────────── */
function story(lv) {
  const t = i => (DATA.tf['1m'][Math.max(0, Math.min(N1 - 1, i))] || ['', '?'])[1];
  const g = valueAt(lv.grades, NOW), shown = valueAt(lv.shown, NOW);
  const rows = [
    ['kind', `${lv.kind} · ${lv.side}`],
    ['born', `candle ${lv.born} · ${t(lv.born)} · on the ${lv.tf}`],
    ['from candles', lv.source.length ? lv.source.join(', ') + `  (${t(lv.source[0])})`
                                      : 'not a single 1m bar — built on the ' + lv.tf],
    ['zone', `${lv.zlo.toLocaleString('en-IN')} – ${lv.zhi.toLocaleString('en-IN')}`],
    ['body edge', lv.body.toLocaleString('en-IN') + '   (entry reference)'],
    ['wick tip', lv.wick.toLocaleString('en-IN') + '   (stop reference)'],
    ['pocket', (lv.zhi - lv.zlo).toFixed(1) + ' pts'],
    ['departure', lv.departure.toFixed(2) + ' x ATR'],
    ['grade now', g + (shown ? '   (in the visible 8)' : '   (built, not shown)')],
    ['touches', String(valueAt(lv.touches, NOW))],
  ];
  if (lv.grades.length > 1)
    rows.push(['grade history', lv.grades.map(([i, v]) => `${v}@${i}`).join(' → ')]);
  rows.push(lv.died === null
    ? ['status', 'alive']
    : ['died', `candle ${lv.died} · ${t(lv.died)} · ${lv.why_died}`]);
  document.getElementById('story').innerHTML = rows.map(([k, v]) =>
    `<div><span class="muted">${k}</span><span style="text-align:right">${v}</span></div>`)
    .join('');
  document.getElementById('storycard').style.display = '';
}
document.getElementById('closestory').onclick = () => {
  PICKED = null; document.getElementById('storycard').style.display = 'none';
};

/* ── scrub: replay the session one candle at a time ──────────────────────── */
const scrub = document.getElementById('scrub');
if (!(DATA.engine || []).length && !DATA.boxes)
  document.getElementById('livebar').style.display = 'none';
scrub.max = N1 - 1;
scrub.value = N1 - 1;
/* The engine narrating itself. Watching a replay at 2 s/candle is only worth doing if
   the screen says WHY something appeared — otherwise it is a slower way to watch price. */
function didWhat(i) {
  const out = [];
  for (const lv of (DATA.engine || [])) {
    if (lv.born === i)
      out.push(`+ ${lv.kind.toUpperCase()} born on the ${lv.tf} at ` +
               `${lv.body.toLocaleString('en-IN')}` +
               (lv.source.length ? ` (from candle ${lv.source.join(', ')})` : ''));
    if (lv.died === i) out.push(`† ${lv.kind} at ` +
               `${lv.body.toLocaleString('en-IN')} died — ${lv.why_died}`);
    if (lv.born > i) continue;
    for (const [k, g] of lv.grades)
      if (k === i && k !== lv.born)
        out.push(`~ ${lv.body.toLocaleString('en-IN')} regraded ${g}`);
    for (const [k, n] of lv.touches)
      if (k === i && n > 0)
        out.push(`· ${lv.body.toLocaleString('en-IN')} touched (${n})`);
  }
  return out;
}

function setNow(i) {
  NOW = Math.max(0, Math.min(N1 - 1, Math.round(i)));
  scrub.value = NOW;
  const built = visibleLevels().length;
  document.getElementById('nowlabel').textContent =
    `candle ${NOW} · ${(DATA.tf['1m'][NOW] || ['', '?'])[1]} · ${built} levels built`;
  if (DATA.boxes) {
    const row = DATA.boxes.rows[Math.min(NOW, DATA.boxes.rows.length - 1)];
    const close = (DATA.tf['1m'][NOW] || [0, 0, 0, 0, 0, 0])[5];
    const names = ['l3', 'l2', 'l1', 'l0'];
    document.getElementById('story').innerHTML = names.map((nm, i) => {
      const bx = row && row[i];
      if (!bx) return '';
      const [il, ih, ol, oh, degen] = bx;
      const pos = ih > il ? ((close - il) / (ih - il) * 100).toFixed(0) + '%' : '—';
      return `<div><span class="muted">${nm.toUpperCase()}</span><span style="text-align:right">`
        + (degen ? 'travelling' : `${il.toLocaleString('en-IN')}–${ih.toLocaleString('en-IN')}`)
        + `<br><span class="muted" style="font-size:11px">outer ${ol.toLocaleString('en-IN')}`
        + `–${oh.toLocaleString('en-IN')} · pos ${pos}</span></span></div>`;
    }).join('');
    document.getElementById('storycard').style.display = '';
    document.querySelector('#storycard strong').textContent = 'THE BOX STACK';
  }
  const did = didWhat(NOW);
  document.getElementById('didwhat').innerHTML = did.length
    ? did.slice(0, 4).join(' &nbsp;&nbsp; ') + (did.length > 4 ? ` &nbsp;+${did.length - 4} more` : '')
    : '<span class="muted">nothing changed on this candle</span>';
  drawAll();
  if (PICKED) {
    const lv = (DATA.engine || []).find(l => l.id === PICKED);
    if (lv && lv.born <= NOW) story(lv);
  }
}
scrub.oninput = () => setNow(+scrub.value);
document.getElementById('showall').onchange = ev => { SHOW_ALL = ev.target.checked; drawAll(); };
document.getElementById('toend').onclick = () => { stop(); setNow(N1 - 1); };
function stop() {
  if (TIMER) { clearInterval(TIMER); TIMER = null; }
  document.getElementById('play').innerHTML = '▶ Play';
}
document.getElementById('play').onclick = () => {
  if (TIMER) return stop();
  if (NOW >= N1 - 1) setNow(0);
  document.getElementById('play').innerHTML = '■ Pause';
  TIMER = setInterval(() => {
    if (NOW >= N1 - 1) return stop();
    setNow(NOW + 1);
  }, +document.getElementById('speed').value);
};
document.getElementById('speed').onchange = () => {
  if (TIMER) { stop(); document.getElementById('play').click(); }
};
document.getElementById('stepf').onclick = () => { stop(); setNow(NOW + 1); };
document.getElementById('stepb').onclick = () => { stop(); setNow(NOW - 1); };
setNow(N1 - 1);

document.getElementById('copy').onclick = () => {
  const t = document.getElementById('yaml'); t.select();
  navigator.clipboard.writeText(t.value);
  document.getElementById('copy').textContent = 'Copied';
  setTimeout(() => document.getElementById('copy').textContent = 'Copy YAML', 1200);
};
document.getElementById('clear').onclick = () => { MARKS.length = 0; drawAll(); };
</script>
"""


def level_timeline(symbol: str, day: date, upto: int | None) -> list[dict[str, Any]]:
    """Every level's whole life, not the book's final photograph.

    ## Why this replaced a list of prices

    The old version returned `{price, grade, kind, touches}` for the book at close, and
    the chart drew a horizontal line across the whole session. Three things were wrong
    with that, and they are the three things you cannot answer while looking at it:

    * **A level is a ZONE, never a line.** Spec 03 §4 says so in those words, and `Level`
      has carried `zone_low`/`zone_high` since P1 — the chart was throwing them away and
      drawing `body_edge`. So the pocket where stops actually sit was invisible.
    * **A line drawn from 09:15 claims the engine knew it at 09:15.** It did not. A level
      born at 11:40 was being drawn across the morning it did not exist in.
    * **Nothing said which candles made it.** *"Ye kis candle se bani hai"* had no answer
      on screen.

    So this walks the session one candle at a time and records, per level: the candle it
    was born on, the candles that formed it, every grade change, every touch, when it
    entered and left the visible 8, and how it died. `--` nothing here changes the level
    engine; it only writes down what the engine was already doing.
    """
    session = ReplayFeed(symbol, on_gap="skip").session(day)
    candles = list(session.candles)
    pipeline = P1Pipeline(load_config(strict=False), session)
    limit = len(candles) - 1 if upto is None else min(upto, len(candles) - 1)

    tl: dict[str, dict[str, Any]] = {}
    for i, candle in enumerate(candles):
        if i > limit:
            break
        pipeline.on_candle(candle)
        book = pipeline.levels.book
        active = set(book.active_ids)
        present = {lid: (lv, lid in active) for lid, lv in book.live.items()}
        present |= {lid: (lv, False) for lid, lv in book.dormant.items()}

        for lid, (lv, is_active) in present.items():
            if lv.is_round_number:
                continue
            rec = tl.get(lid)
            if rec is None:
                rec = tl[lid] = {
                    "id": lid, "kind": lv.kind.value, "side": lv.side.value,
                    "tf": lv.born_tf, "born": i, "died": None, "why_died": None,
                    "body": float(lv.body_edge), "wick": float(lv.wick_tip),
                    "zlo": float(lv.zone_low), "zhi": float(lv.zone_high),
                    "source": _source_candles(candles, lv, i),
                    "grades": [], "touches": [], "shown": [],
                    "departure": float(lv.departure_speed),
                }
            _mark(rec["grades"], i, lv.grade.value)
            _mark(rec["touches"], i, lv.touches)
            _mark(rec["shown"], i, is_active)

        for lid, lv in book.dead.items():
            rec = tl.get(lid)
            if rec is not None and rec["died"] is None:
                rec["died"] = i
                rec["why_died"] = lv.death_reason

    return sorted(tl.values(), key=lambda r: r["born"])


def _mark(series: list, index: int, value: Any) -> None:
    """Change-points only. A per-candle series for every level would be most of the
    file, and the chart only ever needs 'what was it at candle N'."""
    if not series or series[-1][1] != value:
        series.append([index, value])


def _source_candles(candles: list, level, born: int) -> list[int]:
    """The candles the level was actually built from.

    Found by looking backwards from the birth candle for the bar whose extreme *is* the
    level's `wick_tip` — a reconstruction, not a claim from the engine, because the
    engine does not record it. Exact matches only: a level whose tip came from an HTF bar
    or from a cluster mid-point will return nothing rather than guess, and the chart then
    says so instead of pointing at the wrong candle.
    """
    tip = level.wick_tip
    hits = [j for j in range(max(0, born - 40), born + 1)
            if candles[j].h == tip or candles[j].l == tip]
    return hits[-3:]


def box_timeline(symbol: str, day: date, lookback_days: int = 6) -> dict[str, Any]:
    """The four boxes as they stood at every candle of the session.

    The stream deliberately reaches back `lookback_days` sessions, because L1 and L0 read
    windows longer than a day. That is what removes the warm-up special case: at 09:30
    the L1 window still contains yesterday, so there is nothing to load and nothing to
    inherit (`BOX-MODEL.md` §2).
    """
    from src.boxes.engine import DEFAULT_WINDOWS, compute_stack

    feed = ReplayFeed(symbol, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-lookback_days:]
    stream: list = []
    start = 0
    for session in feed.sessions(days=days):
        if session.day == day:
            start = len(stream)
        stream.extend(session.candles)

    ranges = [c.h - c.l for c in stream]
    rows: list[list] = []
    for i in range(start, len(stream)):
        window = ranges[max(0, i - 19):i + 1]
        atr = sum(window) / len(window)
        stack = compute_stack(stream[:i + 1], atr)
        row = []
        for name in ("l3", "l2", "l1", "l0"):
            box = getattr(stack, name)
            row.append(None if box is None else
                       [float(box.inner_low), float(box.inner_high),
                        float(box.outer_low), float(box.outer_high),
                        int(box.degenerate)])
        rows.append(row)
    return {"windows": DEFAULT_WINDOWS, "rows": rows}


def _is_p1_gate_selection(path: str) -> bool:
    """The P1 gate's own session list must never be rendered with engine lines.

    Detected from the file's `purpose`, not its filename — a copy under another name is
    the same contamination.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("purpose") == "p1_overlap"
    except (OSError, ValueError):
        return False


def parse_tfs(text: str) -> list[tuple[str, int]]:
    out = []
    for token in text.split(","):
        token = token.strip().lower()
        if not token.endswith("m") or not token[:-1].isdigit() or int(token[:-1]) < 1:
            raise ValueError(f"bad timeframe {token!r} — use minutes, e.g. 1m,5m,15m,60m")
        out.append((token, int(token[:-1])))
    if not any(minutes == 1 for _, minutes in out):
        out.append(("1m", 1))                 # the index space every mark is expressed in
    return sorted(out, key=lambda pair: -pair[1])


def render_session(symbol: str, day: date, out_dir: Path,
                   window: tuple[int, int] | None = None,
                   with_levels: bool = False,
                   tfs: list[tuple[str, int]] | None = None,
                   with_boxes: bool = False) -> Path:
    session = ReplayFeed(symbol).session(day)
    ones = list(session.candles)
    if window:
        ones = ones[window[0]:window[1]]
    tfs = tfs or parse_tfs("15m,5m,1m")

    heights = {1: 320, 5: 250}
    panels = [[tf, minutes, heights.get(minutes, 220), minutes == 1] for tf, minutes in tfs]

    hi = max(float(c.h) for c in ones)
    lo = min(float(c.l) for c in ones)
    gap = session.open_gap_pct
    data = {
        "symbol": symbol, "day": str(day),
        "panels": panels,
        "tf": {tf: resample(ones, minutes) for tf, minutes in tfs},
        "engine": level_timeline(symbol, day, window[1] if window else None)
        if with_levels else [],
        "boxes": box_timeline(symbol, day) if with_boxes else None,
    }
    subtitle = (f"O {float(ones[0].o):,.0f} &middot; H {hi:,.0f} &middot; L {lo:,.0f} "
                f"&middot; C {float(ones[-1].c):,.0f} &middot; range {hi - lo:,.0f} pts"
                + (f" &middot; overnight gap {float(gap):+.2f}%" if gap is not None else "")
                + f" &middot; {len(ones)} 1m candles"
                + ("<br>Engine book overlaid: <b>solid = Grade A</b>, dashed = B, "
                   "dotted = C. Round numbers omitted."
                   if with_levels else
                   "<br>Blank chart — no engine lines. Mark your levels, then save the YAML."))

    html = (HTML
            .replace("__TITLE__", f"{symbol} {day} — mark your levels")
            .replace("__HEADING__", f"{symbol} &middot; {day:%d %b %Y} ({day:%a})")
            .replace("__SUBTITLE__", subtitle)
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol.replace(' ', '_')}_{day}.html"
    path.write_text(html, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--day", help="YYYY-MM-DD")
    ap.add_argument("--selection", help="a selection.json from tools/select_sessions.py")
    ap.add_argument("--candles", nargs=2, type=int, metavar=("FROM", "TO"))
    ap.add_argument("--tf", default="15m,5m,1m",
                    help="display timeframes, e.g. 60m,15m,5m,1m (1m always included)")
    ap.add_argument("--boxes", action="store_true",
                    help="overlay the stateless box stack — BOX-MODEL.md")
    ap.add_argument("--levels", action="store_true",
                    help="overlay the engine book — NEVER for the P1 gate")
    ap.add_argument("--out", default=str(REPO_ROOT / "reports" / "charts"))
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    window = tuple(args.candles) if args.candles else None
    tfs = parse_tfs(args.tf)

    if args.selection:
        payload = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        days = [(date.fromisoformat(s["day"]), s["bucket"]) for s in payload["sessions"]]
        symbol = payload.get("symbol", args.symbol)
    elif args.day:
        days = [(date.fromisoformat(args.day), "")]
        symbol = args.symbol
    else:
        ap.error("give --day or --selection")

    if args.levels and args.selection and _is_p1_gate_selection(args.selection):
        print("REFUSED: --levels on the P1 overlap selection.\n"
              "  Spec 09 sec 3.2b: the trader marks levels BEFORE seeing engine output.\n"
              "  Reverse that ordering and the test measures agreeableness, not agreement,\n"
              "  and it will pass while telling you nothing.\n"
              "  Use --levels on any OTHER session to check the engine's lines.",
              file=sys.stderr)
        return 2

    for day, bucket in days:
        path = render_session(symbol, day, out_dir, window, args.levels, tfs, args.boxes)
        print(f"  {day}  {bucket:<9} {path.stat().st_size // 1024:>4} KB  {path}")

    index = out_dir / "INDEX.html"
    kind = "engine book overlaid" if args.levels else "blank — mark your own levels"
    links = "\n".join(
        f'<li><a href="{symbol.replace(" ", "_")}_{d}.html">{d} &middot; {d:%a}</a>'
        f' <span style="opacity:.5">{b}</span></li>' for d, b in days)
    index.write_text(
        f'<!doctype html><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>charts</title>'
        f'<style>body{{font:14px/1.7 ui-sans-serif,system-ui;max-width:620px;margin:40px auto;'
        f'padding:0 16px;color-scheme:light dark}}li{{margin:2px 0}}</style>'
        f'<h1 style="font-size:17px">{len(days)} sessions — {kind}</h1>'
        f'<p style="opacity:.65;font-size:13px">Wheel to zoom, drag to pan, double-click to '
        f'reset. Click a panel to mark a level, then copy the YAML.</p>'
        f'<ul>{links}</ul>', encoding="utf-8")
    print(f"\n{len(days)} charts -> {out_dir}\nopen: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
