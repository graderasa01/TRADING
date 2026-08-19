"""DETECTION SCORER — har labelled move par poochho: engine ne dekha ya nahi,
aur agar nahi, to funnel me KAHAN kho gaya."""
import json,os,sys
D=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,D)
from engine_fixed import Engine,P,T0
from label import label_moves

d=json.load(open(os.path.join(D,'session.json'))); C=d['candles']
rng=[c[2]-c[3] for c in C]
def atr_at(i,n=14):
    if i<n: return None
    return sum(rng[i-n+1:i+1])/n

moves=label_moves(C,atr_at)

# engine chalao, har candle par snapshot rakho
E=Engine(d['pdh'],d['pdl'],d['pdc']); snaps=[]
for i,(_,o,h,l,c) in enumerate(C):
    E.on_candle(o,h,l,c)
    snaps.append(dict(
        levels=[(lv.body_edge,lv.grade,lv.kind,lv.state) for lv in E.levels.values() if lv.state=="alive"],
        mode=E.log[-1]["mode"], gate=E.log[-1].get("gate"), setup=E.log[-1].get("setup")))

def tm(i): m=T0+i; return f"{m//60:02d}:{m%60:02d}"

print("="*80); print("  MOVE LABELLER — market kahan se kahan gayi (candles se, bina raay ke)"); print("="*80)
print(f"\n  {len(moves)} significant moves mile (>=4x ATR, <=30 candles)\n")
print(f"  {'from':<7}{'dir':<6}{'origin':>10}{'pts':>7}{'xATR':>6}{'cands':>7}")
for m in moves:
    print(f"  {tm(m['origin_i']):<7}{m['dir']:<6}{m['origin']:>10,.0f}{m['pts']:>7.0f}{m['size_atr']:>6.1f}{m['candles']:>7}")

print("\n"+"="*80); print("  DETECTION FUNNEL — har move par engine kahan tha"); print("="*80)
tol=lambda i: max(15,0.6*(atr_at(i) or 20))
F=dict(any_level=0,grade_a=0,alert=0,setup=0)
misses=[]
for m in moves:
    i=m['origin_i']; s=snaps[i]; t=tol(i)
    near=[L for L in s['levels'] if abs(L[0]-m['origin'])<=t]
    a_near=[L for L in near if L[1]=='A']
    # move ke shuru hone se 3 candle pehle tak koi ALERT/setup tha?
    win=range(max(0,i-3),min(len(snaps),i+2))
    alert=any(snaps[j]['mode']=='ALERT' for j in win)
    setup=any(snaps[j].get('setup') for j in win)
    if near: F['any_level']+=1
    if a_near: F['grade_a']+=1
    if alert: F['alert']+=1
    if setup: F['setup']+=1
    if not setup:
        nearest=min(s['levels'],key=lambda L:abs(L[0]-m['origin'])) if s['levels'] else None
        misses.append(dict(m=m,near=len(near),a=len(a_near),alert=alert,
            nearest=(round(nearest[0],1),nearest[1],nearest[2],round(abs(nearest[0]-m['origin']),1)) if nearest else None,
            gate=s['gate'],mode=s['mode']))
N=len(moves)
for k,lbl in [('any_level','koi level origin ke paas tha'),('grade_a','wo Grade A tha'),
              ('alert','mode ALERT tha'),('setup','setup DETECT hua')]:
    v=F[k]; bar='#'*int(v/max(N,1)*30)
    print(f"  {lbl:<32} {v:>3}/{N}  {v/max(N,1)*100:>5.0f}%  {bar}")

print("\n"+"="*80); print(f"  MISS REPORT — {len(misses)} moves jo engine ne miss kiye"); print("="*80)
for x in misses[:8]:
    m=x['m']
    print(f"\n  {tm(m['origin_i'])}  {m['dir']} {m['pts']:.0f} pts ({m['size_atr']:.1f}x ATR) from {m['origin']:,.0f}")
    print(f"      levels within {tol(m['origin_i']):.0f} pts : {x['near']}   (Grade A: {x['a']})")
    if x['nearest']: print(f"      nearest level          : {x['nearest'][0]:,.0f} {x['nearest'][2]} grade {x['nearest'][1]}, {x['nearest'][3]:.0f} pts door")
    print(f"      mode / gate            : {x['mode']} / {x['gate']}")
    o=m['origin_i']
    pre=[round(rng[j],1) for j in range(max(0,o-4),o+1)]
    print(f"      origin se pehle 5 candle ki range: {pre}   (ATR {m['atr']})")

# ---- MISS ko categorise karo — pattern dhoondhne ke liye ----
print("\n"+"="*80); print("  MISS BUCKETS — kis wajah se kho rahe hain"); print("="*80)
buckets={}
for x in misses:
    if x['gate']=='time_window':      k="time window ke bahar — sahi hai, bug nahi"
    elif x['near']==0:                k="ORIGIN PAR KOI LEVEL HI NAHI — detector missing"
    elif x['a']==0:                   k="level tha par Grade A nahi — grading ka sawaal"
    elif not x['alert']:              k="Grade A tha par ALERT nahi — alert_distance tight"
    else:                             k="ALERT tha par setup nahi bana — setup conditions"
    buckets.setdefault(k,[]).append(x)
for k,v in sorted(buckets.items(),key=lambda z:-len(z[1])):
    print(f"\n  [{len(v):>2}]  {k}")
    for x in v[:3]:
        m=x['m']; o=m['origin_i']
        pre=[round(rng[j],1) for j in range(max(0,o-4),o+1)]
        print(f"         {tm(o)} {m['dir']} {m['pts']:.0f}pts | pre-ranges {pre} | ATR {m['atr']}")
