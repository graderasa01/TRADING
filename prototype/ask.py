#!/usr/bin/env python3
"""ASK — kisi bhi candle / group / swing par poocho: "tum yahan kya soch rahe the?"

Usage:
  python3 ask.py 77             ek candle
  python3 ask.py 75 82          ek group
  python3 ask.py swing 57720    swing ke aas-paas
"""
import json, os, sys
D=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,D)
from engine_fixed import Engine, P, T0

def tm(i): m=T0+i; return f"{m//60:02d}:{m%60:02d}"

d=json.load(open(os.path.join(D,'session.json'))); C=d['candles']
rng=[c[2]-c[3] for c in C]
def atr(i,n=20): return sum(rng[max(0,i-n+1):i+1])/min(n,i+1) if i>=0 else None

E=Engine(d['pdh'],d['pdl'],d['pdc']); TRACE=[]
for i,(_,o,h,l,c) in enumerate(C):
    E.on_candle(o,h,l,c)
    TRACE.append(dict(
        mode=E.log[-1]["mode"], gate=E.log[-1].get("gate"), setup=E.log[-1].get("setup"),
        levels=[(round(lv.body_edge,1),lv.grade,lv.kind,lv.touches,lv.state) for lv in E.levels.values() if lv.state=="alive"],
        dormant=len(E.dormant), day_hi=E.day_hi, day_lo=E.day_lo,
        axis=(round(E.axis.body_edge,1) if E.axis and E.axis.state=="alive" else None),
        swings5=list(E.swings5)))

def thought(i):
    idx,o,h,l,c = C[i]; t=TRACE[i]; a=atr(i)
    cd=E.c1[i]
    out=[]
    A=out.append
    A(f"╔{'═'*76}╗")
    A(f"║ CANDLE {i}  ·  {tm(i)}   O {o:,.1f}  H {h:,.1f}  L {l:,.1f}  C {c:,.1f}".ljust(77)+"║")
    A(f"╚{'═'*76}╝")

    A("\n  ── MAINE KYA DEKHA ──────────────────────────────────────────────")
    r=h-l; body=abs(c-o); uw=h-max(o,c); lw=min(o,c)-l
    cp = 0.5 if r==0 else (c-l)/r
    third = "top" if cp>=0.66 else ("bottom" if cp<=0.34 else "mid")
    last6=[round(rng[j],1) for j in range(max(0,i-5),i+1)]
    A(f"     range        {r:.1f} pts = {r/a:.2f}x ATR20 ({a:.1f})")
    A(f"     pichhli 6    {last6}")
    A(f"     body {body:.1f}  upper wick {uw:.1f} ({uw/r*100 if r else 0:.0f}%)  lower wick {lw:.1f} ({lw/r*100 if r else 0:.0f}%)")
    A(f"     close        {third} third  (position {cp:.2f})")
    # time at price
    tap=sum(1 for j in range(max(0,i-10),i+1) if C[j][3]<=c<=C[j][2])
    A(f"     time-at-price pichhli 11 candles me se {tap} ne is price ko touch kiya")
    # compression
    r3=sum(rng[max(0,i-2):i+1])/3; r10=sum(rng[max(0,i-12):i-2])/max(1,len(rng[max(0,i-12):i-2]))
    A(f"     compression  last3 avg {r3:.1f} ÷ prior10 avg {r10:.1f} = {r3/r10:.2f}")

    A("\n  ── BOARD ME KYA BADLA ──────────────────────────────────────────")
    prev = TRACE[i-1] if i>0 else None
    ch=[]
    if prev:
        if t["day_hi"]>prev["day_hi"]: ch.append(f"naya day high {t['day_hi']:,.0f}")
        if t["day_lo"]<prev["day_lo"]: ch.append(f"naya day low {t['day_lo']:,.0f}")
        if t["axis"]!=prev["axis"]: ch.append(f"axis ab {t['axis']}")
        n0=set(x[0] for x in prev["levels"]); n1=set(x[0] for x in t["levels"])
        for p in n1-n0: ch.append(f"naya level {p:,.1f}")
        for p in n0-n1: ch.append(f"level gaya {p:,.1f}")
        if len(t["swings5"])>len(prev["swings5"]): ch.append(f"naya 5m swing: {t['swings5'][-1]}")
    A("     " + ("; ".join(ch) if ch else "kuch nahi. Board waisa hi hai."))

    A("\n  ── MERA DHYAAN KAHAN THA ───────────────────────────────────────")
    ad=max(20,1.5*(atr(i,14) or 20))
    near=sorted(t["levels"], key=lambda L:abs(L[0]-c))[:3]
    for L in near:
        dist=abs(L[0]-c)
        flag = "  ← ALERT range me" if dist<=ad and L[1]=="A" else ("  (Grade A nahi, ignore)" if dist<=ad else "")
        A(f"     {L[0]:>9,.1f}  {L[2]:<7} grade {L[1]}  touches {L[3]}  — {dist:>5.1f} pts{flag}")
    A(f"     alert_distance {ad:.0f} pts    →    MODE: {t['mode']}" + (f"   gate: {t['gate']}" if t['gate'] else ""))
    if t.get("setup"): A(f"     setup evaluate hua: {t['setup']}")

    A("\n  ── AGLI CANDLE PAR MERI UMEED ──────────────────────────────────")
    if near:
        L=near[0]
        A(f"     AGAR body close {L[0]:,.0f} ke upar → {L[2]} flip, agla obstacle upar")
        A(f"     AGAR body close {L[0]:,.0f} ke neeche → wo resistance ban jaayega")
    else:
        A("     koi level paas nahi. Kuch conditional nahi keh sakta.")

    A("\n  ── MAIN YE DEKH HI NAHI SAKTA ──────────────────────────────────")
    gaps=[]
    if r3/r10 < 0.5: gaps.append(f"compression ban rahi hai (ratio {r3/r10:.2f}) — mera koi coil detector nahi hai")
    if tap>=4: gaps.append(f"{tap} candles ek hi price par ruki — main sirf swing aur wick cluster dhoondhta hu, 'time at price' nahi")
    if not near: gaps.append("khaali jagah — main sirf levels ke paas jaagta hu, momentum nahi dekhta")
    if abs(c-round(c/100)*100)<5: gaps.append("round number bilkul paas — par maine unhe weak kar diya hai (REVIEW-v2 §5)")
    A("     " + ("\n     ".join(gaps) if gaps else "is candle par koi obvious andha spot nahi."))
    return "\n".join(out)

if __name__=="__main__":
    if sys.argv[1]=="swing":
        px=float(sys.argv[2])
        cands=[i for i in range(len(C)) if C[i][3]<=px<=C[i][2]]
        print(f"{px:,.0f} ko touch karne wali candles: {cands}\n")
        for i in cands[:2]: print(thought(i)); print()
    else:
        a=int(sys.argv[1]); b=int(sys.argv[2]) if len(sys.argv)>2 else a
        for i in range(a,b+1): print(thought(i)); print()
