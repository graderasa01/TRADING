import json,sys
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine_fixed import Engine, P, T0
d=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'session.json'))); C=d['candles']
E=Engine(d['pdh'],d['pdl'],d['pdc'])
for _,o,h,l,c in C: E.on_candle(o,h,l,c)

print("="*78)
print("  BANK NIFTY CO-PILOT — 1 SESSION, 375 CANDLES")
print(f"  PDH {d['pdh']:,.0f}  PDL {d['pdl']:,.0f}  PDC {d['pdc']:,.0f}")
print("="*78)
print("\n### ENGINE NE DIN BHAR KYA SOCHA — key moments\n")
for t,kind,msg in E.narrate:
    print(f"  {t}  [{kind:<6}] {msg}")

print("\n### MODE SPLIT  (spec: ~70% WATCH / 25% ALERT / 5% IN)\n")
tot=sum(E.mode_count.values())
for k,v in E.mode_count.items():
    bar="#"*int(v/tot*46)
    print(f"  {k:<8} {v:>4}  {v/tot*100:>5.1f}%  {bar}")

print("\n### REJECTIONS — engine ne trade kyun NAHI liya\n")
for g,n in sorted(E.rejects.items(),key=lambda x:-x[1]):
    print(f"  {g:<24} {n:>4}")

print(f"\n### SIGNALS: {len(E.signals)}\n")
for t,cand,ev in E.signals:
    print(f"  {t}  {cand['setup']} {cand['dir']}  entry {cand['entry']:,.1f}")
    for k in ("R","sl","t1","space","space_ratio","lots","cost_frac","atr"):
        if k in ev: print(f"        {k:<14} {ev[k]}")

print("\n### LEVEL BOOK — din ke ant me\n")
alive=[l for l in E.levels.values() if l.state=="alive"]
alive.sort(key=lambda x:-x.body_edge)
for l in alive:
    print(f"  {l.body_edge:>9,.1f}  {l.kind:<7} {l.side:<11} grade {l.grade}  touches {l.touches}  born {l.born_tf}")
print(f"\n  alive {len(alive)} | dormant {len(E.dormant)} | dead {sum(1 for l in E.levels.values() if l.state=='dead')}")

print("\n### JOURNEYS — 'jahan se aaya wahan tak jayega' (logged, NOT traded)\n")
for j in E.journeys[:6]:
    print(f"  {j['at']}  break {j['origin']:,.0f} {j['dir']}")
    for lbl,px,why in j['rungs']: print(f"        {lbl}  {px:>9,.0f}   {why}")
