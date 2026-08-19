/* app.js — the Reactive Trader Observatory.
 *
 * A VIEW. It renders facts the production pipeline already produced and computes none of
 * its own: no parent/nesting, no route, no thesis, no identity, no participation outcome
 * is derived here. Every value drawn or printed comes straight off a frame.
 *
 * The no-lookahead rule is structural, not cosmetic: `cur` is the cursor and nothing past
 * `F[cur]` is drawn or read, except in AUDIT mode where the future panel is labelled as
 * future and is the only place it appears.
 */
import { attach } from '/static/viewport.js';

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d) => v == null ? '—'
  : v.toLocaleString('en-IN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });

/* ── state ───────────────────────────────────────────────────────────────── */
let DATA = null, F = [], cur = 0, mode = 'SYSTEM', timer = null, live = null;
let paper = false;
const LAYERS = {
  boxes: 1, history: 0, micro: 1, OUTER: 1, INNER: 1, MICRO: 1,
  invalidation: 1, position: 1, candidates: 1,
  /* §16 the reference layers. `primary` is on, `secondary` is not: the whole point of
   * this stage is that the chart opens showing the few references that matter now. */
  primary: 1, secondary: 0, areas: 1,
};
/* §27/§28 — two readabilities, not two truths. FOCUS dims everything that is not the
 * active path; MAP shows the structures as they are. Neither hides a fact. */
let view = 'FOCUS';
const TAIL = 110;

/* ── viewport (pan / zoom / crosshair), reused from tools/chart.py ───────── */
let VP = null, LOP = 0, HIP = 1;

function ensureViewport() {
  if (VP) return VP;
  VP = attach($('svg'), {
    count: 1,
    onDraw: () => draw(false),
    onHover: (i, p, x, y) => hover(i, p, x, y),
    onLeave: () => { $('tip').style.display = 'none'; },
    onClick: i => {
      const k = F.findIndex(f => f.i === Math.round(i));
      if (k >= 0 && k <= cur) goto(k);        /* never select a future candle */
    },
  });
  return VP;
}

/* ── loading ─────────────────────────────────────────────────────────────── */
async function catalog() {
  const c = await (await fetch('/api/catalog')).json();
  const sel = $('session');
  sel.innerHTML = '';
  for (const b of c.blocks) sel.add(new Option(b.label, b.key));
  for (const d of c.days) sel.add(new Option('session ' + d.label, d.key));
}

async function loadSession(key) {
  stopLive(); stopPlay();
  $('side').innerHTML = '<div class="muted">building ' + esc(key)
    + ' from the production pipeline…</div>';
  const r = await fetch(`/api/session?key=${encodeURIComponent(key)}&paper=${paper ? 1 : 0}`);
  const d = await r.json();
  if (d.error) { $('side').innerHTML = `<div class="stop">${esc(d.error)}</div>`; return; }
  DATA = d; F = d.frames; cur = 0;
  VP = null; $('svg').innerHTML = '';
  ensureViewport();
  buildLayers(); buildScenarios();
  $('title').textContent = `${d.symbol} · 5m · ${d.label}`;
  draw();
}

/* ── layer + scenario chrome ─────────────────────────────────────────────── */
function buildLayers() {
  const host = $('layers'); host.innerHTML = '';
  for (const k of Object.keys(LAYERS)) {
    const b = document.createElement('button');
    b.className = 'sm' + (LAYERS[k] ? ' on' : '');
    b.textContent = k;
    b.onclick = () => { LAYERS[k] = !LAYERS[k]; b.className = 'sm' + (LAYERS[k] ? ' on' : ''); draw(); };
    host.appendChild(b);
  }
}

function buildScenarios() {
  const sel = $('scen'); sel.innerHTML = '<option value="">jump to…</option>';
  for (const [k, name] of Object.entries(DATA.scenario_names)) {
    const hits = DATA.scenarios[k] || [];
    const o = new Option(`${k} — ${name}${hits.length ? ` (${hits.length})` : ' — none here'}`, k);
    o.disabled = !hits.length;
    sel.add(o);
  }
  sel.onchange = () => {
    const hits = DATA.scenarios[sel.value] || [];
    if (hits.length) goto(F.findIndex(f => f.i === hits[0]));
    sel.value = '';
  };
}

/* ── the chart ───────────────────────────────────────────────────────────── */
function draw(reframe = true) {
  if (!F.length) return;
  const f = F[cur];
  const vp = ensureViewport();
  const el = document.querySelector('.chart');
  const W = el.clientWidth, H = el.clientHeight;
  const showFuture = mode === 'AUDIT';
  const last = showFuture ? Math.min(F.length - 1, cur + 25) : cur;
  const from = Math.max(0, cur - TAIL);
  const vis = F.slice(from, last + 1);

  if (reframe) { vp.setCount(F.length); vp.reset(F[from].i, F[last].i + 1); }

  /* which map structures THIS candle refers to — read off the frame, not decided here */
  const referenced = new Set([f.cur, f.path.next].filter(Boolean));
  for (const r of f.releases) { referenced.add(r.id); if (r.parent) referenced.add(r.parent); }
  for (const b of f.boxes) if (b.p && referenced.has(b.p)) referenced.add(b.id);
  for (const b of f.boxes) if (b.p && referenced.has(b.id)) referenced.add(b.p);
  if (f.entry) { referenced.add(f.entry.parent); }

  const drawn = b => {
    const e = b.e === null ? f.i : b.e;
    return e >= vis[0].i || LAYERS.history || referenced.has(b.id);
  };

  /* price band.
   *
   * The candles are the anchor. A map structure may widen the band but not swallow it:
   * R01 in teach block 4 is several times the height of a 110-candle window, and letting
   * it set the scale squashed every candle into the bottom eighth of the chart — the
   * picture was technically complete and completely unreadable. A structure taller than
   * the clamp is drawn and simply runs off the top or bottom, which is what a price chart
   * has always done with a zone bigger than the screen. */
  let lo = Infinity, hi = -Infinity;
  for (const c of vis) { lo = Math.min(lo, c.l); hi = Math.max(hi, c.h); }
  const span = (hi - lo) || 10;
  const floor = lo - span * 1.1, ceil = hi + span * 1.1;
  if (LAYERS.boxes) for (const b of f.boxes) {
    if (!drawn(b)) continue;
    lo = Math.min(lo, Math.max(b.lo, floor));
    hi = Math.max(hi, Math.min(b.hi, ceil));
  }
  for (const r of f.releases) if (LAYERS[r.scale] && r.edge != null) {
    lo = Math.min(lo, r.edge); hi = Math.max(hi, r.edge);
  }
  if (LAYERS.invalidation && f.inval.price != null) {
    lo = Math.min(lo, Math.max(f.inval.price, floor));
    hi = Math.max(hi, Math.min(f.inval.price, ceil));
  }
  const pad = (hi - lo) * 0.07 || 10; lo -= pad; hi += pad;
  LOP = lo; HIP = hi;
  vp.frame(W, H, lo, hi);
  const X = i => vp.x(i), Y = p => vp.y(p), bw = Math.max(1.5, vp.slot() * 0.62);
  const P = [];

  /* grid */
  for (let g = 0; g <= 5; g++) {
    const p = lo + (hi - lo) * g / 5, y = Y(p);
    P.push(`<line x1="0" x2="${W - 78}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-dasharray="1 5"/>`);
    P.push(`<text x="${W - 72}" y="${y + 4}" fill="var(--dim)" font-size="10">${fmt(p)}</text>`);
  }

  /* boxes — exactly the set this frame froze.
   *
   * A structure whose forming window ended before the visible range is still a live
   * reference on the map: the thesis names C03, the release names its parent, the path
   * names C06. Skipping those because their candles scrolled off screen left the panel
   * talking about boxes the chart did not draw. So a past box is drawn as a standing
   * price band when this candle actually refers to it, and hidden otherwise so the chart
   * does not fill with thirty warm-up zones. `history` shows all of them.
   *
   * The reference set is read off the frame — current structure, each release and its
   * parent, the path's next reference, and either half of a nested pair. Nothing here
   * decides what is relevant; it lists what this candle already mentions. */
  if (LAYERS.boxes) {
    const sorted = [...f.boxes].sort((a, b) => (b.hi - b.lo) - (a.hi - a.lo));
    for (const b of sorted) {
      const e = b.e === null ? f.i : b.e;
      const past = e < vis[0].i;
      if (!drawn(b)) continue;
      const x0 = past ? 0 : X(Math.max(b.s, vis[0].i));
      const x1 = past ? W - 78 : X(Math.min(e, vis[vis.length - 1].i) + 1);
      const y0 = Y(b.hi), y1 = Y(b.lo);
      const nested = b.p != null;
      P.push(`<rect x="${x0}" y="${y0}" width="${Math.max(2, x1 - x0)}" height="${Math.max(1, y1 - y0)}"
        fill="${b.st === 'LIVE' ? 'var(--live)' : 'var(--hist)'}"
        fill-opacity="${b.st === 'LIVE' ? .55 : past ? .16 : .32}"
        stroke="${b.st === 'LIVE' ? 'var(--accent)' : nested ? 'var(--inner)' : 'var(--line)'}"
        stroke-width="${b.st === 'LIVE' ? 1.3 : nested ? 1.2 : .8}"
        ${nested ? 'stroke-dasharray="4 2"' : ''}/>`);
      if (x1 - x0 > 24) P.push(`<text x="${x0 + 3}" y="${y0 + 11}" font-size="9.5"
        fill="${nested ? 'var(--inner)' : past ? 'var(--dim)' : 'var(--ink)'}"
        >${esc(b.id)}${nested ? ' ⊂ ' + esc(b.p) : ''}${past ? ' (map)' : ''}</text>`);
      /* '⊂' is the MAP hierarchy (node.parent). A release's own containing
       * structure is a different fact (release.parent_id) and is labelled 'inside'
       * on the release line, so the two are never read as one claim. */
    }
  }

  /* micro */
  if (LAYERS.micro && f.micro && f.micro.lo != null) {
    const y0 = Y(f.micro.hi), y1 = Y(f.micro.lo);
    const x0 = X(Math.max(vis[0].i, f.i - 16)), x1 = X(f.i + 1);
    P.push(`<rect x="${x0}" y="${y0}" width="${Math.max(2, x1 - x0)}" height="${Math.max(1, y1 - y0)}"
      fill="none" stroke="var(--micro)" stroke-width="1" stroke-dasharray="3 2"/>`);
    P.push(`<text x="${x1 + 4}" y="${y0 - 3}" fill="var(--micro)" font-size="9.5"
      >micro ${esc(f.micro.id || '')} ${esc(f.micro.state || '')}</text>`);
  }

  /* candles */
  for (const c of vis) {
    const x = X(c.i), future = c.i > f.i, now = c.i === f.i;
    const col = now ? 'var(--hi)' : future ? 'var(--dim)' : (c.c >= c.o ? 'var(--long)' : 'var(--short)');
    const op = future ? .3 : 1;
    P.push(`<line x1="${x + bw / 2}" x2="${x + bw / 2}" y1="${Y(c.h)}" y2="${Y(c.l)}" stroke="${col}" opacity="${op}"/>`);
    P.push(`<rect x="${x}" y="${Y(Math.max(c.o, c.c))}" width="${bw}"
      height="${Math.max(1, Math.abs(Y(c.o) - Y(c.c)))}" fill="${col}" opacity="${op}"/>`);
  }

  /* releases — OUTER / INNER / MICRO toggled separately */
  let relRow = 0;                     /* two edges 20 points apart printed on one line */
  for (const r of f.releases) {
    if (!LAYERS[r.scale]) continue;
    const col = `var(--${r.scale.toLowerCase()})`, y = Y(r.edge);
    P.push(`<line x1="0" x2="${W - 78}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1.4"/>`);
    P.push(`<text x="4" y="${y - 4 - relRow++ * 11}" fill="${col}" font-size="10">${esc(r.scale)} ${esc(r.boundary)} ${esc(r.dir.toUpperCase())} ${fmt(r.edge)}${r.parent ? '  inside ' + esc(r.parent) : ''}</text>`);
    P.push(`<path d="M ${X(f.i) + bw / 2} ${y} l -4.5 ${r.dir === 'up' ? 10 : -10} l 9 0 z" fill="${col}"/>`);
  }
  if (f.simultaneous && f.releases.length > 1) {
    P.push(`<text x="4" y="14" fill="var(--accent)" font-size="10.5"
      >MULTI-SCALE · ${f.releases.length} releases this candle · ${esc(f.thesis.scale)}</text>`);
  }

  /* invalidation */
  if (LAYERS.invalidation && f.inval.price != null) {
    const y = Y(f.inval.price);
    P.push(`<line x1="0" x2="${W - 78}" y1="${y}" y2="${y}" stroke="var(--inval)" stroke-width="1" stroke-dasharray="7 3"/>`);
    P.push(`<text x="${W - 82}" y="${y - 4}" fill="var(--inval)" font-size="10" text-anchor="end">invalidation ${fmt(f.inval.price)}</text>`);
  }

  /* §25 the reference hierarchy. PRIMARY by default; FAR/COUNTER behind a toggle. */
  const R = f.ref;
  if (R) {
    const roleColour = {
      IMMEDIATE: 'var(--imm)', NEXT: 'var(--nxt)', MAJOR: 'var(--maj)',
      FAR: 'var(--dim)', COUNTER_THESIS: 'var(--inval)',
      CURRENT_BOUNDARY: 'var(--hi)', PARENT_BOUNDARY: 'var(--maj)',
      NESTED_BOUNDARY: 'var(--inner)',
    };
    const wanted = r => (R.primary_roles.includes(r.role) ? LAYERS.primary
                                                          : LAYERS.secondary);
    /* areas first, so a structure's own two edges read as one band not two lines */
    if (LAYERS.areas) for (const side of [R.up, R.down]) {
      for (const a of side.areas) {
        const first = side.refs.find(r => r.id === a.id);
        if (!first || !wanted(first)) continue;
        const y0 = Y(a.hi), y1 = Y(a.lo);
        const dim = view === 'FOCUS' && R.active && side.direction !== R.active;
        P.push(`<rect x="0" y="${y0}" width="${W - 78}" height="${Math.max(1, y1 - y0)}"
          fill="${roleColour[first.role] || 'var(--dim)'}" fill-opacity="${dim ? .04 : .10}"/>`);
      }
    }
    for (const side of [R.up, R.down]) {
      const dim = view === 'FOCUS' && R.active && side.direction !== R.active;
      for (const r of side.refs) {
        if (!wanted(r)) continue;
        const col = roleColour[r.role] || 'var(--dim)';
        const y = Y(r.price);
        const op = dim ? .3 : 1;
        P.push(`<line x1="0" x2="${W - 78}" y1="${y}" y2="${y}" stroke="${col}"
          stroke-width="${r.role === 'MAJOR' ? 1.8 : 1.1}" opacity="${op}"
          ${r.role === 'FAR' ? 'stroke-dasharray="2 6"' : ''}/>`);
        P.push(`<text x="4" y="${y - 3}" fill="${col}" font-size="10" opacity="${op}"
          >${esc(r.role)}  ${esc(r.label)}  ${fmt(r.price)}  ${fmt(r.distance)} pts${r.parent ? '  ⊂ ' + esc(r.parent) : ''}</text>`);
      }
    }
    if (R.counter && LAYERS.secondary) {
      const y = Y(R.counter.price);
      P.push(`<line x1="0" x2="${W - 78}" y1="${y}" y2="${y}" stroke="var(--inval)"
        stroke-width="1.1" stroke-dasharray="8 3"/>`);
    }
  }

  /* markers, only on candles at or before the cursor */
  for (const c of vis) {
    if (c.i > f.i) continue;
    const x = X(c.i) + bw / 2;
    if (LAYERS.candidates && c.action.startsWith('PARTICIPATION_CANDIDATE')) {
      const up = c.action.endsWith('LONG');
      P.push(`<circle cx="${x}" cy="${Y(up ? c.l : c.h) + (up ? 14 : -14)}" r="3.6" fill="none"
        stroke="${up ? 'var(--long)' : 'var(--short)'}" stroke-width="1.5"/>`);
    }
    if (!LAYERS.position) continue;
    if (c.phase === 'OPEN') {
      const up = c.pos === 'LONG';
      P.push(`<path d="M ${x} ${Y(up ? c.l : c.h) + (up ? 22 : -22)} l -5.5 ${up ? 8 : -8} l 11 0 z"
        fill="${up ? 'var(--long)' : 'var(--short)'}"/>`);
    }
    if (c.phase === 'INVALIDATED') {
      const y = Y(c.c);
      P.push(`<path d="M ${x - 4.5} ${y - 4.5} l 9 9 M ${x + 4.5} ${y - 4.5} l -9 9" stroke="var(--inval)" stroke-width="1.7"/>`);
    }
    if (c.phase === 'CONTINUATION') {
      P.push(`<circle cx="${x}" cy="${Y(c.c)}" r="1.8" fill="var(--paper)"/>`);
    }
  }

  /* the live paper position's entry level */
  if (LAYERS.position && f.entry && f.phase !== 'FLAT') {
    const y = Y(f.entry.price), col = f.entry.side === 'LONG' ? 'var(--long)' : 'var(--short)';
    P.push(`<line x1="${X(f.entry.index)}" x2="${W - 78}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1" stroke-dasharray="4 3"/>`);
    P.push(`<text x="${X(f.entry.index) + 3}" y="${y - 4}" fill="${col}" font-size="10">PAPER ${esc(f.entry.side)} ${fmt(f.entry.price, 1)}</text>`);
  }

  /* the cursor */
  P.push(`<line x1="${X(f.i) + bw / 2}" x2="${X(f.i) + bw / 2}" y1="0" y2="${H}" stroke="var(--hi)" stroke-opacity=".18"/>`);

  const svg = $('svg');
  svg.setAttribute('width', W); svg.setAttribute('height', H);
  svg.innerHTML = P.join('');
  panel(f); timeline();
  $('clock').textContent = `c${f.i}  ${f.t.slice(11)}  ${fmt(f.c, 1)}`;
  $('progress').textContent = `candle ${cur + 1} / ${F.length}`;
  pills();
}

function hover(i, p) {
  const k = Math.round(i);
  const f = F.find(x => x.i === k);
  const tip = $('tip');
  if (!f || k > F[cur].i) { tip.style.display = 'none'; return; }
  tip.style.display = 'block';
  tip.style.left = Math.min(window.innerWidth - 260, VP.x(k) + 14) + 'px';
  tip.style.top = Math.max(6, VP.y(p) - 46) + 'px';
  tip.textContent = `c${f.i} ${f.t.slice(11)}\nO ${fmt(f.o, 1)}  H ${fmt(f.h, 1)}\n`
    + `L ${fmt(f.l, 1)}  C ${fmt(f.c, 1)}\n${f.action}`;
}

function pills() {
  const bits = [`<span class="pill exec">EXECUTION ${esc(DATA.execution_status)}</span>`];
  if (DATA.contract !== 'NoExecution')
    bits.unshift(`<span class="pill paper">PAPER · ${esc(DATA.contract)}</span>`);
  if (live) bits.unshift('<span class="pill live">LIVE FEED</span>');
  $('pills').innerHTML = bits.join(' ');
}

/* ── the trader panel ────────────────────────────────────────────────────── */
function panel(f) {
  const kv = o => '<div class="kv">' + Object.entries(o)
    .map(([k, v]) => `<b>${esc(k)}</b><span>${v == null ? '—' : v}</span>`).join('') + '</div>';
  let h = '';

  if (DATA.contract !== 'NoExecution')
    h += `<div class="warn"><b>PAPER</b> — positions here were opened by
          <b>${esc(DATA.contract)}</b> (validated = ${DATA.validated}). No order exists,
          no size, no risk. <b>EXECUTION_STATUS = UNAVAILABLE</b>.</div>`;

  /* the nine questions come first: this is the trader's checklist */
  h += '<h4>Trader panel</h4><div class="eye">'
    + f.eye.map(([q, a]) => `<b>${esc(q)}</b><span>${esc(a)}</span>`).join('') + '</div>';

  if (mode === 'BLIND') {
    h += '<h4>Blind mode</h4><div class="muted">Thesis, participation and action are '
      + 'hidden. Read the chart yourself, then switch to <b>System</b>.</div>';
    $('side').innerHTML = h; return;
  }

  h += '<h4>Where am I</h4>' + kv({
    'Price': `<span class="big">${fmt(f.c, 1)}</span>`, 'Time': f.t,
    'Structure': esc(f.cur || '—'), 'Location': esc(f.thesis.location),
    'Position in': f.thesis.pos_in_current == null ? '—' : f.thesis.pos_in_current.toFixed(2),
    'State': esc(f.thesis.state || '—'), 'Scale': esc(f.thesis.scale),
  });

  h += '<h4>What broke</h4>';
  h += f.releases.length
    ? f.releases.map(r => kv({
      'Scale': `<span style="color:var(--${r.scale.toLowerCase()})">${esc(r.scale)}</span>`,
      'Boundary': esc(r.boundary), 'Direction': esc(r.dir.toUpperCase()),
      'Broken edge': fmt(r.edge), 'Parent': esc(r.parent || '—'),
      'Origin': esc(r.origin),
      'Where': esc(f.thesis.release_location || '—') + ' · ' + esc(f.thesis.parent_location || '—'),
    })).join('<div style="height:7px"></div>')
    : '<div class="muted">nothing broke on this candle</div>';
  if (f.simultaneous)
    h += `<div class="muted" style="margin-top:5px">simultaneous — ${f.releases.length}
          releases kept, controlling scale ${esc(f.thesis.scale)}</div>`;

  h += '<h4>Micro</h4>' + (f.micro_read.id
    ? kv({ 'Micro': esc(f.micro_read.id), 'State': esc(f.micro_read.state),
           'View': esc(f.micro_read.view), 'Rotations': f.micro_read.rotations,
           'Last': esc(f.micro_read.last || '—') })
    : '<div class="muted">absent</div>');

  h += '<h4>Thesis</h4>' + (f.thesis.gen ? kv({
    'Idea': `<span class="tag ${f.thesis.idea}">${esc(f.thesis.idea)}</span>`,
    'Generation': f.thesis.gen, 'Identity': esc(f.thesis.identity),
    'Status': esc(f.thesis.status), 'Contradicted': f.thesis.contradicted ? 'YES' : 'none',
    'Next expected': esc(f.thesis.next_expected),
    'Since break': f.thesis.bars_since_break == null ? '—' : f.thesis.bars_since_break + ' candles',
    'Travelled': fmt(f.thesis.travelled),
  }) : '<div class="muted">none — no structural event has set a direction</div>');

  h += '<h4>Participation</h4>' + kv({
    'Outcome': esc(f.part.outcome.replace('PARTICIPATION_', '')),
    'Opportunity': esc(f.part.kind), 'Entry-shaped': f.part.entry_shaped ? 'yes' : 'no',
    'Reasons': f.part.reasons.length ? f.part.reasons.map(esc).join('<br>') : '—',
    'Id': `<span style="font-size:11px">${esc(f.part.opportunity || '—')}</span>`,
  });

  /* §25 the reference paths, active one first */
  const R = f.ref;
  if (R) {
    const card = r => `<div class="ref ${esc(r.role)}">
      <div class="rh"><b>${esc(r.role)}</b><span>${esc(r.label)}</span></div>
      <div class="rb">${fmt(r.price)} &nbsp; ${fmt(r.distance)} pts &nbsp;
        ${esc(r.kind)}${r.parent ? ' &nbsp; ⊂ ' + esc(r.parent) : ''}</div>
      <div class="rw">${esc(r.why)}</div></div>`;
    const sideBlock = (s, title, isActive) => {
      const shown = s.refs.filter(r => R.primary_roles.includes(r.role));
      return `<h4>${esc(title)}${isActive ? ' — ACTIVE' : ''}</h4>`
        + (shown.length ? shown.map(card).join('')
                        : '<div class="muted">nothing mapped ahead</div>')
        + (s.far.length ? `<div class="muted" style="margin-top:4px">+ ${s.far.length}
            further reference${s.far.length > 1 ? 's' : ''} (secondary)</div>` : '');
    };
    const upFirst = R.active !== 'down';
    h += upFirst
      ? sideBlock(R.up, 'UP PATH', R.active === 'up') + sideBlock(R.down, 'DOWN PATH', R.active === 'down')
      : sideBlock(R.down, 'DOWN PATH', true) + sideBlock(R.up, 'UP PATH', false);
    if (R.counter) h += '<h4>Counter-thesis</h4>' + card(R.counter);
    if (R.current_boundaries.length)
      h += '<h4>Current structure</h4>' + R.current_boundaries.map(card).join('');
  }

  h += '<h4>Route (published)</h4>' + (f.path.next ? kv({
    'Next': esc(f.path.next), 'Free': fmt(f.path.near), 'Depth': fmt(f.path.depth),
    'Far free': fmt(f.path.far_free), 'Far ref': fmt(f.path.far),
  }) : '<div class="muted">nothing mapped ahead of the broken boundary</div>');

  h += '<h4>Invalidation</h4>' + kv({
    'Price': fmt(f.inval.price), 'Away': fmt(f.inval.distance),
    'Rule': `<span style="font-size:11px">${esc(f.inval.rule || '—')}</span>`,
  });

  h += '<h4>Position</h4>' + kv({
    'Now': `<span class="tag ${f.pos}">${esc(f.pos)}</span>`
      + (f.phase !== 'FLAT' ? ' <span class="pill paper">PAPER</span>' : ''),
    'Phase': esc(f.phase),
    'Exit reason': esc(f.exit_reason || '—'),
    'Execution': esc(f.exec) + (f.disposition ? `<br><span class="muted">${esc(f.disposition)}</span>` : ''),
  });

  if (f.entry) {
    h += '<h4>Entry thesis — frozen</h4>' + kv({
      'Side': `<span class="tag ${f.entry.side}">${esc(f.entry.side)}</span>`,
      'Identity': esc(f.entry.identity), 'Opened': `c${f.entry.index} ${esc(f.entry.at)}`,
      'Price': fmt(f.entry.price, 1), 'Scale': esc(f.entry.scale || '—'),
      'Broken edge': fmt(f.entry.edge), 'Parent': esc(f.entry.parent || '—'),
      'Invalidation': fmt(f.entry.inval) + ' ' + esc(f.entry.inval_dir),
      'State at open': esc(f.entry.state), 'Micro at open': esc(f.entry.micro || '—'),
      'Path at open': esc(f.entry.next || '—') + '  free ' + fmt(f.entry.near),
    });
    h += '<h4>Entry thesis vs current market</h4>' + kv({
      'Entry identity': esc(f.entry.identity),
      'Current identity': esc(f.cur_identity || '—'),
      'Thesis': f.same_identity ? '<span style="color:var(--long)">SAME</span>'
                                : '<span style="color:var(--inval)">CHANGED</span>',
      'Direction': f.same_direction ? 'unchanged' : '<span style="color:var(--inval)">CHANGED</span>',
      'Management': f.mgmt.map(esc).join('<br>') || '—',
    });
  }

  h += `<h4>Why — ${esc(f.action)}</h4><ul class="why">`
    + f.why.lines.map(l => `<li>${esc(l)}</li>`).join('') + '</ul>'
    + `<div class="code">${f.why.codes.map(esc).join(' · ')}</div>`
    + `<div class="narr">${esc(f.why.narrative)}</div>`;

  if (mode === 'AUDIT') {
    h += '<h4>Audit — what happened after</h4>'
      + '<div class="warn">Future information. Shown for debugging only; it never '
      + 'reaches the engine and no earlier panel above used it.</div><div class="ev">'
      + F.slice(cur + 1, cur + 10).map(x =>
        `<span class="muted">c${x.i}</span><span class="muted">${esc(x.t.slice(11))}</span>
         <span>${fmt(x.c, 1)} · ${esc(x.action)}${x.exit_reason ? ' · ' + esc(x.exit_reason) : ''}</span>`
      ).join('') + '</div>';
  }
  $('side').innerHTML = h;
}

/* ── timeline ────────────────────────────────────────────────────────────── */
function timeline() {
  const rows = [];
  for (let k = 0; k <= cur; k++)
    for (const e of F[k].events)
      rows.push(`<div class="row ${k === cur ? 'now' : ''}" data-k="${k}">
        <span class="muted">c${F[k].i}</span><span class="muted">${esc(F[k].t.slice(11))}</span>
        <span>${esc(e)}</span></div>`);
  const tl = $('tl');
  tl.innerHTML = rows.length ? rows.join('')
    : '<div class="muted" style="grid-column:1/4">nothing structural yet</div>';
  tl.querySelectorAll('.row').forEach(r => r.onclick = () => goto(+r.dataset.k));
  tl.parentElement.scrollTop = tl.parentElement.scrollHeight;
}

/* ── transport ───────────────────────────────────────────────────────────── */
function goto(k) {
  if (!F.length) return;
  cur = Math.max(0, Math.min(F.length - 1, k));
  draw();
}
function stopPlay() {
  if (timer) clearInterval(timer);
  timer = null; $('play').textContent = '▶ Play'; $('play').className = '';
}
$('play').onclick = () => {
  if (timer) return stopPlay();
  $('play').textContent = '❚❚ Pause'; $('play').className = 'on';
  timer = setInterval(() => {
    if (cur >= F.length - 1) return stopPlay();
    goto(cur + 1);
  }, +$('speed').value);
};
$('speed').onchange = () => { if (timer) { stopPlay(); $('play').onclick(); } };
$('step').onclick = () => goto(cur + 1);
$('back').onclick = () => goto(cur - 1);
$('load').onclick = () => loadSession($('session').value);
$('paper').onclick = () => {
  paper = !paper;
  $('paper').textContent = 'PAPER ' + (paper ? 'on' : 'off');
  $('paper').className = paper ? 'on' : '';
};
document.querySelectorAll('.view').forEach(b => b.onclick = () => {
  view = b.dataset.v;
  document.querySelectorAll('.view').forEach(x => x.className = 'view' + (x === b ? ' on' : ''));
  if (view === 'MAP') { LAYERS.secondary = 1; LAYERS.history = 1; }
  else { LAYERS.secondary = 0; LAYERS.history = 0; }
  buildLayers(); draw();
});
document.querySelectorAll('.mode').forEach(b => b.onclick = () => {
  mode = b.dataset.m;
  document.querySelectorAll('.mode').forEach(x => x.className = 'mode' + (x === b ? ' on' : ''));
  draw();
});
addEventListener('keydown', e => {
  if (e.target.tagName === 'SELECT') return;
  if (e.key === 'ArrowRight') goto(cur + 1);
  if (e.key === 'ArrowLeft') goto(cur - 1);
  if (e.key === ' ') { e.preventDefault(); $('play').onclick(); }
});
addEventListener('resize', () => draw(false));

/* ── live feed — the same pipeline, one candle at a time ─────────────────── */
async function stopLive() {
  if (!live) return;
  await fetch(`/api/live/stop?id=${encodeURIComponent(live.id)}`, { method: 'POST' });
  clearInterval(live.poll); live = null; $('golive').className = ''; pills();
}
$('golive').onclick = async () => {
  if (live) return stopLive();
  stopPlay();
  const key = $('session').value;
  const secs = Math.max(0.05, (+$('speed').value) / 1000);
  const r = await fetch(
    `/api/live/open?key=${encodeURIComponent(key)}&paper=${paper ? 1 : 0}&seconds=${secs}`,
    { method: 'POST' });
  const meta = await r.json();
  if (meta.error) { $('side').innerHTML = `<div class="stop">${esc(meta.error)}</div>`; return; }
  live = { id: meta.id };
  DATA = Object.assign({ frames: [], scenarios: {}, }, meta);
  F = []; cur = 0; VP = null; $('svg').innerHTML = '';
  ensureViewport(); buildLayers(); buildScenarios();
  $('title').textContent = `${meta.symbol} · 5m · ${meta.label} · ${meta.source}`;
  $('golive').className = 'on';
  live.poll = setInterval(async () => {
    const d = await (await fetch(`/api/live/poll?id=${encodeURIComponent(live.id)}`)).json();
    if (d.error) { $('side').innerHTML = `<div class="stop">${esc(d.error)}</div>`; return; }
    if (d.frames.length) {
      F = F.concat(d.frames);
      cur = F.length - 1;                    /* live always sits on the newest candle */
      draw();
    }
    if (d.done) { clearInterval(live.poll); $('golive').className = ''; }
  }, 400);
  pills();
};

/* ── go ──────────────────────────────────────────────────────────────────── */
await catalog();
await loadSession($('session').value);
