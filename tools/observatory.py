#!/usr/bin/env python3
"""
observatory.py — the reactive trader, candle by candle, on a chart.

    python tools/observatory.py --day 2026-02-16
    python tools/observatory.py --block 0 --paper
    python tools/observatory.py --day 2026-02-16 --open

## What this is for

Every previous stage proved the system is *internally* correct. This one asks the only
question those stages could not: **does the picture match what a trader would see?** A
release the code calls `INNER C04.low` has to look like an inner cluster giving way inside
an intact parent, or the vocabulary is describing something other than the market.

## The rule that makes it worth trusting

**No future candle, and no future box, is ever drawn.** The engine sees candles up to the
cursor and nothing else, and the geometry is frozen per candle by
`livemap/observatory.geometry_track` rather than read back at the end of the run — which
would have leaked five structures onto candle 440 of the first teach block, one of them the
structure a later position opens on. `Reveal Next Candle` moves the cursor; it does not
un-hide something the system already knew.

`AUDIT` mode is the single exception and it is labelled: it shows what happened *after* a
chosen candle, side by side with what the system saw at it. That is a debugging view, and
nothing in it reaches the engine.

## Nothing here trades

No broker, no order, no size, no risk. A position on this screen exists only because a
research contract was named on the command line with `--paper`, and it is labelled `PAPER`
everywhere it appears. The execution boundary reads `UNAVAILABLE` by default.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.boxes.frontier import run  # noqa: E402
from src.boxes.snapshot import build_snapshot  # noqa: E402
from src.feed.aggregator import Aggregator  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.learning.split import load_split  # noqa: E402
from src.livemap import observatory as OB  # noqa: E402
from src.livemap import position as POS  # noqa: E402
from src.livemap import reactor as RE  # noqa: E402

SYMBOL = "NIFTY BANK"
BARS, HIST = 700, 400


# ─────────────────────────────────────────────────────────────────────────────
def n(v):
    """Decimal → float for JSON, `None` preserved. Presentation only — every decision
    was already taken in `Decimal`."""
    return None if v is None else float(v)


def m5_of(days) -> list:
    out = []
    for session in ReplayFeed(SYMBOL, on_gap="skip").sessions(days=days):
        agg = Aggregator(htf=("5m",))
        for candle in session.candles:
            u = agg.on_candle(candle)
            if u.m5 is not None:
                out.append(u.m5)
    return out


def load_block(index: int):
    sp = load_split()
    days = ReplayFeed(SYMBOL, on_gap="skip").available_days()
    need = ((index + 1) * BARS) // 75 + 12
    m5 = m5_of(sp.teach(days)[:need])
    blk = m5[index * BARS:(index + 1) * BARS]
    if len(blk) < BARS:
        raise SystemExit(f"block {index} is short ({len(blk)}/{BARS} candles)")
    return blk[:HIST], blk[HIST:], f"teach block {index}"


def load_day(day: date, lookback: int = 6):
    feed = ReplayFeed(SYMBOL, on_gap="skip")
    days = [d for d in feed.available_days(end=day) if d <= day][-lookback:]
    if day not in days:
        raise SystemExit(f"{day} is not in the available sessions")
    m5 = m5_of(days)
    live_from = next(i for i, c in enumerate(m5) if c.close_time.date() == day)
    if live_from < 120:
        raise SystemExit("not enough history before this day to build a snapshot")
    return m5[:live_from], m5[live_from:], str(day)


# ─────────────────────────────────────────────────────────────────────────────
def serialise(frames: list, contract: str, validated: bool, label: str) -> dict:
    """Frames → the JSON the page renders. A copy, field for field. Nothing is computed."""
    out = []
    for f in frames:
        c, st, g = f.context, f.state, f.geometry
        rels = [{"scale": r.scale, "boundary": r.boundary, "id": r.broken_id,
                 "dir": r.direction, "edge": n(r.broken_edge), "parent": r.parent_id,
                 "origin": r.origin,
                 "parent_low": n(r.parent_low), "parent_high": n(r.parent_high)}
                for r in c.all_releases]
        snap = st.snapshot
        ev = st.evaluation
        out.append({
            "i": f.index, "t": f.at.strftime("%Y-%m-%d %H:%M"),
            "o": n(f.o), "h": n(f.h), "l": n(f.l), "c": n(f.c),
            "boxes": [{"id": b.id, "kind": b.kind, "s": b.start, "e": b.end,
                       "lo": n(b.low), "hi": n(b.high), "p": b.parent,
                       "d": b.depth, "st": b.status} for b in g.boxes],
            "micro": (None if g.micro_id is None and g.micro_low is None else
                      {"id": g.micro_id, "lo": n(g.micro_low), "hi": n(g.micro_high),
                       "state": g.micro_state, "parent": g.micro_parent}),
            "cur": g.current_id,
            "band": [n(g.band[0]), n(g.band[1])] if g.band else None,
            "bl_up": n(g.break_level_up), "bl_dn": n(g.break_level_down),
            "releases": rels,
            "thesis": {"idea": c.idea.replace("_IDEA", ""), "gen": c.generation,
                       "status": c.thesis_status, "state": c.current_state,
                       "identity": str(c.thesis_identity) if c.thesis_identity else None,
                       "contradicted": c.contradicted,
                       "location": c.current_location,
                       "pos_in_current": n(c.position_in_current),
                       "scale": c.controlling_scale,
                       "release_location": c.release_location,
                       "parent_location": c.parent_location,
                       "bars_since_break": c.bars_since_break,
                       "travelled": n(c.excursion_travelled)},
            "micro_read": {"id": c.micro_id, "state": c.micro_state,
                           "view": c.micro_view, "rotations": c.micro_rotations,
                           "last": c.micro_last_direction},
            "path": {"next": c.next_reference, "far": n(c.far_reference),
                     "near": n(c.free_to_near), "depth": n(c.zone_depth),
                     "far_free": n(c.free_to_far),
                     "corridor": list(c.corridor[:4]), "watch": c.watch},
            "inval": {"rule": c.invalidation, "price": n(c.invalidation_price),
                      "distance": n(c.invalidation_distance)},
            "part": {"outcome": c.participation, "reasons": list(c.reasons),
                     "kind": c.opportunity_kind, "entry_shaped": c.entry_shaped,
                     "opportunity": str(c.opportunity) if c.opportunity else None},
            "action": f.action, "status": f.decision.status,
            "exec": f.execution_status,
            "disposition": f.request.disposition if f.request else None,
            "phase": st.phase, "pos_before": st.position, "pos": st.position_after,
            "exit_reason": st.exit_reason,
            "entry": (None if snap is None else {
                "side": snap.side, "identity": str(snap.identity),
                "gen": snap.generation, "at": snap.opened_at.strftime("%H:%M"),
                "index": snap.opened_index, "price": n(snap.opened_price),
                "scale": snap.release_scale, "edge": n(snap.broken_edge),
                "parent": snap.parent_structure_id,
                "inval": n(snap.invalidation_reference),
                "inval_dir": snap.invalidation_direction,
                "rule": snap.invalidation_rule,
                "state": snap.current_state_at_open,
                "micro": snap.micro_state_at_open,
                "next": snap.next_reference_at_open,
                "near": n(snap.free_to_near_at_open)}),
            "mgmt": list(ev.management) if ev else [],
            "developments": list(ev.developments) if ev else [],
            "same_identity": (ev.thesis_generation_same if ev else None),
            "same_direction": (ev.direction_same if ev else None),
            "why": {"codes": list(f.why.codes), "lines": list(f.why.lines),
                    "narrative": f.why.narrative},
            "eye": [[q, a] for q, a in OB.trader_eye(f)],
            "events": list(f.events),
        })
    return {"label": label, "symbol": SYMBOL, "contract": contract,
            "validated": validated, "frames": out,
            "scenarios": {k: v for k, v in OB.scenarios(frames).items()},
            "scenario_names": OB.SCENARIOS}


# ─────────────────────────────────────────────────────────────────────────────
PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>Reactive Trader Observatory</title>
<style>
:root{
  --bg:#0e1117; --panel:#161b22; --line:#242c38; --ink:#c9d4e3; --dim:#7d8899;
  --hi:#e6edf7; --accent:#4c8dff; --long:#2ea043; --short:#e5534b;
  --outer:#4c8dff; --inner:#b07cf0; --micro:#d29922; --inval:#e5534b;
  --hist:#2b3440; --live:#3d4a5c; --paper:#d29922;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.5 var(--mono)}
.wrap{display:grid;grid-template-columns:1fr 380px;grid-template-rows:auto 1fr auto;
      height:100vh;gap:1px;background:var(--line)}
.bar{grid-column:1/3;background:var(--panel);padding:8px 12px;display:flex;
     gap:14px;align-items:center;flex-wrap:wrap}
.chart{background:var(--bg);position:relative;overflow:hidden}
.side{background:var(--panel);overflow-y:auto;padding:12px 14px}
.tl{grid-column:1/3;background:var(--panel);height:132px;overflow-y:auto;padding:6px 12px}
button,select{background:#20272f;color:var(--ink);border:1px solid var(--line);
       border-radius:5px;padding:4px 10px;font:12px var(--mono);cursor:pointer}
button:hover{background:#2b3440;color:var(--hi)}
button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
button:disabled{opacity:.35;cursor:default}
.sep{width:1px;height:20px;background:var(--line)}
.lay{display:flex;gap:4px;flex-wrap:wrap}
.lay button{padding:3px 8px;font-size:11px}
h4{margin:14px 0 5px;font-size:10px;letter-spacing:.14em;color:var(--dim);
   text-transform:uppercase;border-bottom:1px solid var(--line);padding-bottom:4px}
h4:first-child{margin-top:0}
.kv{display:grid;grid-template-columns:106px 1fr;gap:1px 8px;font-size:12px}
.kv b{color:var(--dim);font-weight:400}
.kv span{color:var(--hi);word-break:break-word}
.big{font-size:19px;color:var(--hi)}
.tag{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px;
     border:1px solid var(--line)}
.LONG{color:var(--long);border-color:var(--long)} .SHORT{color:var(--short);border-color:var(--short)}
.FLAT{color:var(--dim)}
.why{margin:0;padding-left:16px} .why li{margin:2px 0;color:var(--hi)}
.code{color:var(--dim);font-size:11px;margin-top:5px;word-break:break-all}
.narr{color:var(--dim);font-size:11.5px;font-style:italic;margin-top:8px;line-height:1.55}
.ev{display:grid;grid-template-columns:52px 60px 1fr;gap:2px 10px;font-size:11.5px}
.ev div{padding:1px 0}
.ev .row{display:contents;cursor:pointer}
.ev .row:hover span{background:#20272f;color:var(--hi)}
.ev .row.now span{background:#233047;color:var(--hi)}
.muted{color:var(--dim)}
.eye b{color:var(--dim);font-weight:400;display:block;margin-top:6px;font-size:10.5px;
       letter-spacing:.08em}
.eye span{color:var(--hi);font-size:12px}
.paper{background:var(--paper);color:#000;padding:1px 7px;border-radius:3px;
       font-size:10px;letter-spacing:.1em;font-weight:700}
.warn{background:#3a2d12;border:1px solid var(--paper);color:var(--paper);
      padding:6px 9px;border-radius:5px;font-size:11px;margin-bottom:10px}
svg{display:block}
.hint{color:var(--dim);font-size:11px}
#audit{display:none;background:#1a1f27;border:1px solid var(--line);border-radius:5px;
       padding:8px 10px;margin-top:10px}
</style>
<div class="wrap">
  <div class="bar">
    <b style="color:var(--hi)" id="ttl"></b>
    <span class="sep"></span>
    <button id="play">▶ Play</button>
    <button id="step">Reveal Next Candle ▸</button>
    <button id="back">◂</button>
    <select id="speed">
      <option value="1000">1×</option><option value="500">2×</option>
      <option value="200" selected>5×</option><option value="50">20×</option>
    </select>
    <span class="sep"></span>
    <span class="hint">Mode</span>
    <button class="mode" data-m="BLIND">Blind</button>
    <button class="mode on" data-m="SYSTEM">System</button>
    <button class="mode" data-m="AUDIT">Audit</button>
    <span class="sep"></span>
    <span class="lay" id="layers"></span>
    <span class="sep"></span>
    <select id="scen"></select>
    <span style="flex:1"></span>
    <span id="clock" class="big"></span>
  </div>
  <div class="chart"><svg id="svg"></svg></div>
  <div class="side" id="side"></div>
  <div class="tl"><div class="ev" id="tl"></div></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const F = D.frames, N = F.length;
let cur = 0, mode = 'SYSTEM', timer = null;
const LAYERS = {boxes:1, micro:1, releases:1, invalidation:1, path:1, position:1,
                candidates:1, future:0};
const TAIL = 90;                       // candles of context behind the cursor

document.getElementById('ttl').textContent =
  `${D.symbol} · 5m · ${D.label}` + (D.contract !== 'NoExecution' ? '  ' : '');

/* ── layer toggles ───────────────────────────────────────────────────────── */
const lay = document.getElementById('layers');
for (const k of Object.keys(LAYERS)) {
  if (k === 'future') continue;
  const b = document.createElement('button');
  b.textContent = k; b.className = LAYERS[k] ? 'on' : '';
  b.onclick = () => { LAYERS[k] = !LAYERS[k]; b.className = LAYERS[k] ? 'on' : ''; draw(); };
  lay.appendChild(b);
}

/* ── scenario jump list ──────────────────────────────────────────────────── */
const sc = document.getElementById('scen');
sc.innerHTML = '<option value="">jump to scenario…</option>';
for (const [k, name] of Object.entries(D.scenario_names)) {
  const hits = D.scenarios[k] || [];
  const o = document.createElement('option');
  o.value = k; o.disabled = !hits.length;
  o.textContent = `${k} — ${name}` + (hits.length ? ` (${hits.length})` : ' — none');
  sc.appendChild(o);
}
sc.onchange = () => {
  const hits = D.scenarios[sc.value] || [];
  if (hits.length) { goto(F.findIndex(f => f.i === hits[0])); }
  sc.value = '';
};

/* ── geometry ────────────────────────────────────────────────────────────── */
function scales(vis, f) {
  const W = document.querySelector('.chart').clientWidth;
  const H = document.querySelector('.chart').clientHeight;
  const L = 8, R = 74, T = 10, B = 22;
  let lo = Infinity, hi = -Infinity;
  for (const c of vis) { lo = Math.min(lo, c.l); hi = Math.max(hi, c.h); }
  if (LAYERS.boxes) for (const b of f.boxes) {
    if (b.e !== null && b.e < vis[0].i) continue;
    lo = Math.min(lo, b.lo); hi = Math.max(hi, b.hi);
  }
  if (LAYERS.invalidation && f.inval.price) { lo = Math.min(lo, f.inval.price); hi = Math.max(hi, f.inval.price); }
  const pad = (hi - lo) * 0.08 || 10; lo -= pad; hi += pad;
  const n = Math.max(vis.length, 12);
  return {
    W, H, L, R, T, B, lo, hi,
    x: i => L + (i + 0.5) * ((W - L - R) / n),
    bw: Math.max(2, ((W - L - R) / n) * 0.66),
    y: p => T + (hi - p) * ((H - T - B) / (hi - lo)),
    first: vis[0].i,
  };
}
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt = (v, d) => v == null ? '—' : v.toLocaleString('en-IN', {minimumFractionDigits: d||0, maximumFractionDigits: d||0});

function draw() {
  const f = F[cur];
  const lo0 = Math.max(0, cur - TAIL);
  const vis = F.slice(lo0, mode === 'AUDIT' && LAYERS.future ? Math.min(N, cur + 20) : cur + 1);
  const s = scales(vis, f);
  const P = [];
  const px = i => s.x(i - s.first);

  /* price grid */
  for (let g = 0; g <= 4; g++) {
    const p = s.lo + (s.hi - s.lo) * g / 4, y = s.y(p);
    P.push(`<line x1="${s.L}" x2="${s.W - s.R}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-dasharray="1 4"/>`);
    P.push(`<text x="${s.W - s.R + 6}" y="${y + 4}" fill="var(--dim)" font-size="10">${fmt(p, 0)}</text>`);
  }

  /* boxes — only those the frame froze at this candle */
  if (LAYERS.boxes) for (const b of f.boxes) {
    const e = b.e === null ? f.i : b.e;
    if (e < s.first) continue;
    const x0 = px(Math.max(b.s, s.first)), x1 = px(Math.min(e, vis[vis.length-1].i));
    const y0 = s.y(b.hi), y1 = s.y(b.lo);
    const col = b.st === 'LIVE' ? 'var(--live)' : 'var(--hist)';
    P.push(`<rect x="${x0}" y="${y0}" width="${Math.max(2, x1-x0)}" height="${Math.max(1, y1-y0)}"
      fill="${col}" fill-opacity="${b.st==='LIVE'?.5:.3}" stroke="${b.st==='LIVE'?'var(--accent)':'var(--line)'}"
      stroke-width="${b.st==='LIVE'?1.2:.8}"/>`);
    if (x1 - x0 > 26) P.push(`<text x="${x0+3}" y="${y0+11}" fill="var(--dim)" font-size="9.5">${esc(b.id)}</text>`);
  }

  /* micro */
  if (LAYERS.micro && f.micro && f.micro.lo != null) {
    const y0 = s.y(f.micro.hi), y1 = s.y(f.micro.lo);
    P.push(`<rect x="${px(Math.max(s.first, f.i-14))}" y="${y0}" width="${px(f.i)-px(Math.max(s.first,f.i-14))+s.bw}"
      height="${Math.max(1,y1-y0)}" fill="none" stroke="var(--micro)" stroke-width="1" stroke-dasharray="3 2"/>`);
    P.push(`<text x="${px(f.i)+s.bw+4}" y="${y0-2}" fill="var(--micro)" font-size="9.5">micro ${esc(f.micro.id||'')} ${esc(f.micro.state||'')}</text>`);
  }

  /* candles */
  vis.forEach((c, k) => {
    const x = s.x(k), up = c.c >= c.o;
    const col = k === vis.length - 1 && !(mode==='AUDIT'&&LAYERS.future&&c.i>f.i) ? 'var(--hi)'
              : (c.i > f.i ? 'var(--dim)' : (up ? 'var(--long)' : 'var(--short)'));
    const op = c.i > f.i ? .35 : 1;
    P.push(`<line x1="${x+s.bw/2}" x2="${x+s.bw/2}" y1="${s.y(c.h)}" y2="${s.y(c.l)}" stroke="${col}" opacity="${op}"/>`);
    P.push(`<rect x="${x}" y="${s.y(Math.max(c.o,c.c))}" width="${s.bw}"
      height="${Math.max(1, Math.abs(s.y(c.o)-s.y(c.c)))}" fill="${col}" opacity="${op}"/>`);
  });

  /* releases */
  if (LAYERS.releases) for (const r of f.releases) {
    const col = r.scale === 'OUTER' ? 'var(--outer)' : r.scale === 'INNER' ? 'var(--inner)' : 'var(--micro)';
    const y = s.y(r.edge);
    P.push(`<line x1="${s.L}" x2="${s.W-s.R}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1.4"/>`);
    P.push(`<text x="${s.L+4}" y="${y-4}" fill="${col}" font-size="10">${esc(r.scale)} ${esc(r.boundary)} ${r.dir.toUpperCase()} ${fmt(r.edge)}</text>`);
    P.push(`<path d="M ${px(f.i)+s.bw/2} ${y} l -4 ${r.dir==='up'?9:-9} l 8 0 z" fill="${col}"/>`);
  }

  /* invalidation */
  if (LAYERS.invalidation && f.inval.price != null) {
    const y = s.y(f.inval.price);
    P.push(`<line x1="${s.L}" x2="${s.W-s.R}" y1="${y}" y2="${y}" stroke="var(--inval)" stroke-width="1" stroke-dasharray="6 3"/>`);
    P.push(`<text x="${s.W-s.R-4}" y="${y-4}" fill="var(--inval)" font-size="10" text-anchor="end">invalidation ${fmt(f.inval.price)}</text>`);
  }

  /* path */
  if (LAYERS.path && f.path.far != null) {
    const y = s.y(f.path.far);
    P.push(`<line x1="${px(f.i)}" x2="${s.W-s.R}" y1="${y}" y2="${y}" stroke="var(--dim)" stroke-width="1" stroke-dasharray="2 5"/>`);
    P.push(`<text x="${s.W-s.R-4}" y="${y+12}" fill="var(--dim)" font-size="10" text-anchor="end">far ${esc(f.path.next||'')} ${fmt(f.path.far)}</text>`);
  }

  /* candidate + position markers, back along the visible window */
  for (const c of vis) {
    if (c.i > f.i) continue;
    const x = px(c.i) + s.bw / 2;
    if (LAYERS.candidates && c.action.startsWith('PARTICIPATION_CANDIDATE')) {
      const up = c.action.endsWith('LONG');
      P.push(`<circle cx="${x}" cy="${s.y(up ? c.l : c.h) + (up ? 13 : -13)}" r="3.4"
        fill="none" stroke="${up?'var(--long)':'var(--short)'}" stroke-width="1.4"/>`);
    }
    if (LAYERS.position && c.phase === 'OPEN') {
      const up = c.pos === 'LONG';
      P.push(`<path d="M ${x} ${s.y(up?c.l:c.h)+(up?20:-20)} l -5 ${up?7:-7} l 10 0 z"
        fill="${up?'var(--long)':'var(--short)'}"/>`);
    }
    if (LAYERS.position && c.phase === 'INVALIDATED') {
      const y = s.y(c.c);
      P.push(`<path d="M ${x-4} ${y-4} l 8 8 M ${x+4} ${y-4} l -8 8" stroke="var(--inval)" stroke-width="1.6"/>`);
    }
  }

  /* the open position's entry level */
  if (LAYERS.position && f.entry && f.phase !== 'FLAT') {
    const y = s.y(f.entry.price);
    P.push(`<line x1="${px(f.entry.index)}" x2="${s.W-s.R}" y1="${y}" y2="${y}"
      stroke="${f.entry.side==='LONG'?'var(--long)':'var(--short)'}" stroke-width="1" stroke-dasharray="4 3"/>`);
    P.push(`<text x="${px(f.entry.index)+3}" y="${y-4}" fill="${f.entry.side==='LONG'?'var(--long)':'var(--short)'}"
      font-size="10">PAPER ${esc(f.entry.side)} ${fmt(f.entry.price,1)}</text>`);
  }

  const svg = document.getElementById('svg');
  svg.setAttribute('width', s.W); svg.setAttribute('height', s.H);
  svg.innerHTML = P.join('');
  side(f); timeline();
  document.getElementById('clock').textContent = `c${f.i}  ${f.t.slice(11)}  ${fmt(f.c,1)}`;
}

/* ── the trader panel ────────────────────────────────────────────────────── */
function side(f) {
  const blind = mode === 'BLIND';
  const kv = o => '<div class="kv">' + Object.entries(o)
    .map(([k, v]) => `<b>${esc(k)}</b><span>${v == null ? '—' : v}</span>`).join('') + '</div>';
  let h = '';
  if (D.contract !== 'NoExecution')
    h += `<div class="warn"><b>PAPER</b> — positions on this screen were opened by
          <b>${esc(D.contract)}</b>, validated = ${D.validated}. No order exists.</div>`;

  h += '<h4>Current market</h4>' + kv({
    'Price': `<span class="big">${fmt(f.c, 1)}</span>`,
    'Time': f.t, 'Structure': esc(f.cur || '—'),
    'Location': esc(f.thesis.location),
    'Position in': f.thesis.pos_in_current == null ? '—' : f.thesis.pos_in_current.toFixed(2),
    'State': esc(f.thesis.state || '—'), 'Scale': esc(f.thesis.scale),
  });

  h += '<h4>Release</h4>';
  h += f.releases.length ? f.releases.map(r => kv({
    'Scale': esc(r.scale), 'Structure': esc(r.id), 'Boundary': esc(r.boundary),
    'Direction': esc(r.dir.toUpperCase()), 'Broken edge': fmt(r.edge),
    'Parent': esc(r.parent || '—'), 'Where': esc(f.thesis.release_location || '—'),
    'Parent loc': esc(f.thesis.parent_location || '—'),
  })).join('<div style="height:6px"></div>') : '<div class="muted">nothing broke on this candle</div>';

  h += '<h4>Micro</h4>' + (f.micro_read.id
    ? kv({'Micro': esc(f.micro_read.id), 'State': esc(f.micro_read.state),
          'View': esc(f.micro_read.view), 'Rotations': f.micro_read.rotations,
          'Last': esc(f.micro_read.last || '—')})
    : '<div class="muted">absent</div>');

  if (blind) {
    h += '<h4>Blind mode</h4><div class="muted">The system\'s thesis, participation and '
       + 'action are hidden. Read the chart, then switch to <b>System</b>.</div>';
    document.getElementById('side').innerHTML = h;
    return;
  }

  h += '<h4>Thesis</h4>' + (f.thesis.gen ? kv({
    'Idea': `<span class="tag ${f.thesis.idea === 'LONG' ? 'LONG' : 'SHORT'}">${esc(f.thesis.idea)}</span>`,
    'Generation': f.thesis.gen, 'Identity': esc(f.thesis.identity),
    'Status': esc(f.thesis.status), 'Contradicted': f.thesis.contradicted ? 'YES' : 'none',
    'Since break': f.thesis.bars_since_break == null ? '—' : f.thesis.bars_since_break + ' candles',
    'Travelled': fmt(f.thesis.travelled),
  }) : '<div class="muted">none — no structural event has set a direction</div>');

  h += '<h4>Participation</h4>' + kv({
    'Outcome': esc(f.part.outcome.replace('PARTICIPATION_', '')),
    'Opportunity': esc(f.part.kind), 'Entry-shaped': f.part.entry_shaped ? 'yes' : 'no',
    'Reasons': f.part.reasons.length ? f.part.reasons.map(esc).join('<br>') : '—',
    'Id': `<span style="font-size:11px">${esc(f.part.opportunity || '—')}</span>`,
  });

  h += '<h4>Path</h4>' + (f.path.next ? kv({
    'Next': esc(f.path.next), 'Free': fmt(f.path.near), 'Depth': fmt(f.path.depth),
    'Far free': fmt(f.path.far_free), 'Far ref': fmt(f.path.far),
    'Corridor': f.path.corridor.length ? f.path.corridor.map(esc).join('<br>') : '—',
  }) : '<div class="muted">nothing mapped ahead of the broken boundary</div>');

  h += '<h4>Invalidation</h4>' + kv({
    'Price': fmt(f.inval.price), 'Away': fmt(f.inval.distance),
    'Rule': `<span style="font-size:11px">${esc(f.inval.rule || '—')}</span>`,
  });

  h += '<h4>Position</h4>' + kv({
    'Current': `<span class="tag ${f.pos}">${esc(f.pos)}</span>`
             + (f.phase !== 'FLAT' ? ' <span class="paper">PAPER</span>' : ''),
    'Phase': esc(f.phase),
    'Execution': esc(f.exec) + (f.disposition ? `<br><span class="muted">${esc(f.disposition)}</span>` : ''),
  });

  if (f.entry) {
    h += '<h4>Entry thesis <span class="paper">PAPER</span></h4>' + kv({
      'Side': `<span class="tag ${f.entry.side}">${esc(f.entry.side)}</span>`,
      'Identity': esc(f.entry.identity), 'Opened': `c${f.entry.index} ${esc(f.entry.at)}`,
      'Price': fmt(f.entry.price, 1), 'Scale': esc(f.entry.scale || '—'),
      'Broken edge': fmt(f.entry.edge), 'Parent': esc(f.entry.parent || '—'),
      'Invalidation': fmt(f.entry.inval) + ' ' + esc(f.entry.inval_dir),
      'State at open': esc(f.entry.state), 'Micro at open': esc(f.entry.micro || '—'),
    });
    h += '<h4>Current vs entry</h4>' + kv({
      'Thesis': f.same_identity ? 'SAME identity' : 'identity CHANGED',
      'Direction': f.same_direction ? 'unchanged' : 'CHANGED',
      'Management': f.mgmt.map(esc).join('<br>') || '—',
    });
  }

  h += `<h4>Why — ${esc(f.action)}</h4>`;
  h += '<ul class="why">' + f.why.lines.map(l => `<li>${esc(l)}</li>`).join('') + '</ul>';
  h += `<div class="code">${f.why.codes.map(esc).join(' · ')}</div>`;
  h += `<div class="narr">${esc(f.why.narrative)}</div>`;

  h += '<h4>Trader eye</h4><div class="eye">'
     + f.eye.map(([q, a]) => `<b>${esc(q)}</b><span>${esc(a)}</span>`).join('') + '</div>';

  if (mode === 'AUDIT') {
    const later = F.slice(cur + 1, cur + 9);
    h += '<h4>Audit — what happened after</h4>';
    h += '<div class="warn">This is future information. It is shown for debugging and '
       + 'never reaches the engine.</div>';
    h += '<div class="ev">' + later.map(x =>
      `<div class="muted">c${x.i}</div><div class="muted">${esc(x.t.slice(11))}</div>
       <div>${fmt(x.c,1)} · ${esc(x.action)}${x.exit_reason ? ' · ' + esc(x.exit_reason) : ''}</div>`
    ).join('') + '</div>';
  }
  document.getElementById('side').innerHTML = h;
}

/* ── the event timeline ──────────────────────────────────────────────────── */
function timeline() {
  const rows = [];
  for (let k = 0; k <= cur; k++) {
    const f = F[k];
    for (const e of f.events)
      rows.push(`<div class="row ${k===cur?'now':''}" data-k="${k}"><span class="muted">c${f.i}</span>
        <span class="muted">${esc(f.t.slice(11))}</span><span>${esc(e)}</span></div>`);
  }
  const tl = document.getElementById('tl');
  tl.innerHTML = rows.length ? rows.join('')
    : '<div class="muted" style="grid-column:1/4">nothing structural yet</div>';
  tl.querySelectorAll('.row').forEach(r => r.onclick = () => goto(+r.dataset.k));
  tl.parentElement.scrollTop = tl.parentElement.scrollHeight;
}

/* ── controls ────────────────────────────────────────────────────────────── */
function goto(k) { cur = Math.max(0, Math.min(N - 1, k)); draw(); }
document.getElementById('step').onclick = () => goto(cur + 1);
document.getElementById('back').onclick = () => goto(cur - 1);
document.querySelectorAll('.mode').forEach(b => b.onclick = () => {
  mode = b.dataset.m;
  document.querySelectorAll('.mode').forEach(x => x.className = 'mode' + (x === b ? ' on' : ''));
  LAYERS.future = (mode === 'AUDIT') ? 1 : 0;
  draw();
});
const play = document.getElementById('play');
play.onclick = () => {
  if (timer) { clearInterval(timer); timer = null; play.textContent = '▶ Play'; play.className = ''; return; }
  play.textContent = '❚❚ Pause'; play.className = 'on';
  const tick = () => { if (cur >= N - 1) { play.onclick(); return; } goto(cur + 1); };
  timer = setInterval(tick, +document.getElementById('speed').value);
};
document.getElementById('speed').onchange = () => { if (timer) { play.onclick(); play.onclick(); } };
addEventListener('keydown', e => {
  if (e.key === 'ArrowRight') goto(cur + 1);
  if (e.key === 'ArrowLeft') goto(cur - 1);
  if (e.key === ' ') { e.preventDefault(); play.onclick(); }
});
addEventListener('resize', draw);
draw();
</script>
"""


def render(frames: list, contract: str, validated: bool, label: str,
           out: Path) -> Path:
    data = serialise(frames, contract, validated, label)
    page = PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


# ─────────────────────────────────────────────────────────────────────────────
def find_scenarios(blocks: int = 24) -> int:
    """Which teach block shows each scenario. Without this the fifteen visual checks
    cannot be done: block 0 alone carries only nine of them."""
    sp = load_split()
    days = ReplayFeed(SYMBOL, on_gap="skip").available_days()
    m5 = m5_of(sp.teach(days)[:(blocks * BARS) // 75 + 12])
    seen: dict[str, list[tuple[int, int, int]]] = {k: [] for k in OB.SCENARIOS}

    for b in range(blocks):
        blk = m5[b * BARS:(b + 1) * BARS]
        if len(blk) < BARS:
            break
        hist, live = blk[:HIST], blk[HIST:]
        snapshot = build_snapshot(hist, SYMBOL)
        f = run(snapshot, hist, live)
        ids = POS.candidates_in(RE.replay(snapshot, f, execution=RE.ImmediateExecution()))
        ex = POS.ResearchPositionInjector(ids) if ids else RE.NoExecution()
        for k, idx in OB.scenarios(OB.frames(snapshot, hist, live, execution=ex)).items():
            if idx:
                seen[k].append((b, len(idx), idx[0]))

    print(f"{'':3}{'scenario':<52}{'blocks':>7}{'candles':>9}   open with")
    for k, name in OB.SCENARIOS.items():
        hits = seen[k]
        total = sum(h[1] for h in hits)
        cmd = (f"--block {hits[0][0]} --paper   (c{hits[0][2]})" if hits
               else "NOT PRESENT ANYWHERE IN TEACH")
        print(f"{k:<3}{name:<52}{len(hits):>7}{total:>9}   {cmd}")
    missing = [k for k, v in seen.items() if not v]
    if missing:
        print()
        print(f"scenarios with no real instance in teach: {', '.join(missing)}")
        print("These are reported, never simulated — a fixture built to make a scenario")
        print("appear would be validating the fixture, not the system.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--day", help="a session date, YYYY-MM-DD")
    src.add_argument("--block", type=int, help="a teach block index")
    src.add_argument("--find", action="store_true",
                     help="scan every teach block and report which block each of the "
                          "fifteen scenarios can be seen in. Prints a jump list.")
    ap.add_argument("--paper", action="store_true",
                    help="open PAPER positions on every candidate this run offers, so the "
                         "position lifecycle is visible. Research only — no order exists.")
    ap.add_argument("--out", default="reports/observatory")
    ap.add_argument("--open", action="store_true", help="open in a browser when written")
    a = ap.parse_args(argv)

    if a.find:
        return find_scenarios()

    if a.block is not None:
        hist, live, label = load_block(a.block)
        name = f"block{a.block}"
    else:
        d = date.fromisoformat(a.day)
        hist, live, label = load_day(d)
        name = str(d)

    snapshot = build_snapshot(hist, SYMBOL)
    execution = RE.NoExecution()
    if a.paper:
        f = run(snapshot, hist, live)
        ids = POS.candidates_in(RE.replay(snapshot, f, execution=RE.ImmediateExecution()))
        if not ids:
            raise SystemExit("no candidate in this sample — nothing to open on")
        execution = POS.ResearchPositionInjector(ids)

    frames = OB.frames(snapshot, hist, live, execution=execution)
    out = render(frames, execution.name, bool(execution.validated), label,
                 REPO_ROOT / a.out / f"observatory_{name}{'_paper' if a.paper else ''}.html")

    hits = OB.scenarios(frames)
    opened = sum(1 for x in frames if x.phase == POS.OPEN)
    print(f"candles     {len(frames)}")
    print(f"contract    {execution.name}   validated={execution.validated}")
    print(f"positions   {opened}" + ("   PAPER - no order exists" if opened else ""))
    print(f"candidates  {sum(1 for x in frames if x.decision.is_candidate)}")
    print(f"execution   {sorted({x.execution_status for x in frames if x.request})}")
    print("scenarios")
    for k, name_ in OB.SCENARIOS.items():
        n_ = len(hits[k])
        print(f"  {k}  {name_:<48} {n_ if n_ else '-'}")
    print(f"\nwrote {out}  ({out.stat().st_size // 1024} KB)")
    if a.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
