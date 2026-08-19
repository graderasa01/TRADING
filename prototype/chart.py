#!/usr/bin/env python3
"""ANNOTATION CHART — engine ki lines chart par, taaki trader ungli rakh sake.
Standalone HTML banata hai. Har candle par index likha hai, taaki annotation me
exact jagah bata sako."""
import json, os, sys
D=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,D)
from engine_fixed import Engine, T0

def tm(i): m=T0+i; return f"{m//60:02d}:{m%60:02d}"

def render(from_i=0, to_i=120, out="chart.html"):
    d=json.load(open(os.path.join(D,'session.json'))); C=d['candles']
    E=Engine(d['pdh'],d['pdl'],d['pdc']); snaps=[]
    for _,o,h,l,c in C:
        E.on_candle(o,h,l,c)
        snaps.append([(round(lv.body_edge,1),lv.grade,lv.kind) for lv in E.levels.values() if lv.state=="alive"])

    win=C[from_i:to_i]; snap=snaps[to_i-1]
    lo=min(x[3] for x in win)-15; hi=max(x[2] for x in win)+15
    W,H=1400,620; PAD=70
    def X(i): return PAD+(i-from_i)*((W-PAD-160)/len(win))+((W-PAD-160)/len(win))/2
    def Y(p): return 30+(hi-p)/(hi-lo)*(H-90)

    parts=[]
    # price grid
    step=50
    p=int(lo/step)*step
    while p<hi:
        if p>lo:
            major = p%500==0
            parts.append(f'<line x1="{PAD}" y1="{Y(p):.1f}" x2="{W-160}" y2="{Y(p):.1f}" stroke="#000" stroke-opacity="{0.18 if major else 0.07}" stroke-width="{1.2 if major else 1}"/>')
            parts.append(f'<text x="{PAD-6}" y="{Y(p)+3:.1f}" font-size="10" text-anchor="end" fill="#666">{p:,}</text>')
        p+=step
    # candles
    bw=max(2,(W-PAD-160)/len(win)*0.6)
    for k,(idx,o,h,l,c) in enumerate(win):
        cx=X(idx); up=c>=o
        parts.append(f'<line x1="{cx:.1f}" y1="{Y(h):.1f}" x2="{cx:.1f}" y2="{Y(l):.1f}" stroke="#444" stroke-width="1"/>')
        yt,yb=Y(max(o,c)),Y(min(o,c))
        parts.append(f'<rect x="{cx-bw/2:.1f}" y="{yt:.1f}" width="{bw:.1f}" height="{max(yb-yt,1):.1f}" fill="{"#fff" if up else "#222"}" stroke="#222" stroke-width="1"/>')
        if idx%10==0:
            parts.append(f'<text x="{cx:.1f}" y="{H-42}" font-size="9" text-anchor="middle" fill="#999">{idx}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{H-30}" font-size="9" text-anchor="middle" fill="#666">{tm(idx)}</text>')
    # engine levels
    for px,g,kind in sorted(snap,key=lambda z:-z[0]):
        if not (lo<px<hi): continue
        dash = "none" if g=="A" else ("5 3" if g=="B" else "2 4")
        wdt  = 2.0 if g=="A" else (1.3 if g=="B" else 1.0)
        parts.append(f'<line x1="{PAD}" y1="{Y(px):.1f}" x2="{W-160}" y2="{Y(px):.1f}" stroke="#000" stroke-width="{wdt}" stroke-dasharray="{dash}" stroke-opacity="0.85"/>')
        parts.append(f'<text x="{W-154}" y="{Y(px)+3:.1f}" font-size="10" fill="#111"><tspan font-weight="600">{px:,.0f}</tspan>  {kind} {g}</text>')

    svg=f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;font-family:ui-sans-serif,system-ui">{"".join(parts)}</svg>'
    html=f"""<!doctype html><meta charset=utf-8><title>Level annotation — candles {from_i}-{to_i}</title>
<style>body{{font:14px/1.5 ui-sans-serif,system-ui;max-width:1440px;margin:24px auto;padding:0 16px;color:#111}}
code{{background:#f2f2ef;padding:1px 5px;border-radius:3px}}h1{{font-size:17px}}
.k{{display:inline-block;margin-right:18px;font-size:12px;color:#555}}</style>
<h1>Level annotation — candles {from_i}–{to_i} ({tm(from_i)}–{tm(to_i-1)})</h1>
<p><span class=k>solid = Grade A</span><span class=k>dashed = Grade B</span><span class=k>dotted = Grade C</span>
<span class=k>x-axis = candle index</span></p>
{svg}
<p>Ab <code>annotations.yaml</code> me likho: kaunsi line <b>honi chahiye thi</b> (missed),
aur kaunsi line <b>nahi honi chahiye thi</b> (false_positive). Dono zaroori hain.
Candle index chart se lo.</p>"""
    open(os.path.join(D,out),"w").write(html)
    return out, len(snap)

if __name__=="__main__":
    a=int(sys.argv[1]) if len(sys.argv)>1 else 0
    b=int(sys.argv[2]) if len(sys.argv)>2 else 120
    f,n=render(a,b)
    print(f"{f} bana — candles {a}-{b}, {n} live levels chart par")
