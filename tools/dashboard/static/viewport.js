/* viewport.js — pan, zoom and crosshair for an SVG price chart.
 *
 * Extracted from `tools/chart.py`'s inline panel code rather than rewritten: that
 * interaction model (drag to pan, wheel to zoom about the cursor, double-click to reset,
 * a click that is suppressed when the pointer moved) was already built and already
 * behaves the way the other chart tools in this repo behave. Two chart tools with
 * different mouse conventions is a small thing that makes a tool feel wrong.
 *
 * It owns the VIEW window and the pixel↔data mapping, and nothing else. It knows nothing
 * about candles, boxes, releases or theses — the caller redraws and the caller decides
 * what a click means.
 */
export function attach(svg, opts) {
  const o = Object.assign({
    padL: 8, padR: 78, padT: 12, padB: 24,
    count: 1,                    // how many data points exist
    onDraw: () => {},            // called whenever VIEW changes
    onHover: () => {},           // (dataIndex, price, x, y)
    onClick: () => {},           // (dataIndex, price)
    onLeave: () => {},
  }, opts || {});

  const V = { lo: 0, hi: Math.max(1, o.count - 1) };
  let W = 0, H = 0, LO = 0, HI = 1;

  const rect = () => svg.getBoundingClientRect();
  const at = ev => {
    const b = rect();
    return [(ev.clientX - b.left) / b.width * W, (ev.clientY - b.top) / b.height * H];
  };

  const api = {
    get view() { return V; },
    /* the caller tells us the pixel size and price band it just drew with */
    frame(w, h, lo, hi) { W = w; H = h; LO = lo; HI = hi; },
    /* data index ↔ pixel x */
    x(i) {
      const inner = W - o.padL - o.padR;
      return o.padL + (i - V.lo) / (V.hi - V.lo || 1) * inner;
    },
    index(x) {
      const inner = W - o.padL - o.padR;
      return V.lo + (x - o.padL) / inner * (V.hi - V.lo);
    },
    y(p) {
      const inner = H - o.padT - o.padB;
      return o.padT + (HI - p) / ((HI - LO) || 1) * inner;
    },
    price(y) {
      const inner = H - o.padT - o.padB;
      return HI - (y - o.padT) / inner * (HI - LO);
    },
    /* the width one data slot occupies, in pixels */
    slot() {
      const inner = W - o.padL - o.padR;
      return inner / ((V.hi - V.lo) || 1);
    },
    setCount(n) { o.count = n; },
    reset(lo, hi) { V.lo = lo; V.hi = hi; o.onDraw(); },
    zoom(factor, anchor) {
      const width = (V.hi - V.lo) * factor;
      const frac = (anchor - V.lo) / ((V.hi - V.lo) || 1);
      V.lo = anchor - width * frac;
      V.hi = anchor + width * (1 - frac);
      o.onDraw();
    },
  };

  let drag = null, moved = 0;
  svg.addEventListener('mousedown', ev => {
    drag = { x: ev.clientX, lo: V.lo, hi: V.hi }; moved = 0;
    svg.classList.add('panning');
  });
  window.addEventListener('mouseup', () => {
    drag = null; svg.classList.remove('panning');
  });
  svg.addEventListener('mousemove', ev => {
    const [x, y] = at(ev);
    if (drag) {
      moved += Math.abs(ev.clientX - drag.x);
      const shift = (drag.x - ev.clientX) / rect().width * (drag.hi - drag.lo);
      V.lo = drag.lo + shift; V.hi = drag.hi + shift;
      o.onDraw();
      return;
    }
    o.onHover(api.index(x), api.price(y), x, y);
  });
  svg.addEventListener('mouseleave', () => o.onLeave());
  svg.addEventListener('wheel', ev => {
    ev.preventDefault();
    api.zoom(ev.deltaY > 0 ? 1.22 : 1 / 1.22, api.index(at(ev)[0]));
  }, { passive: false });
  svg.addEventListener('click', ev => {
    if (moved > 4) return;                       /* a pan, not a click */
    const [x, y] = at(ev);
    o.onClick(api.index(x), api.price(y), x, y);
  });
  svg.addEventListener('dblclick', () => api.reset(0, Math.max(1, o.count - 1)));

  return api;
}
