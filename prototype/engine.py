"""BANK NIFTY CO-PILOT — reference implementation of specs 01-09 (v2.1).
Closed candles only. No look-ahead: at step t the engine sees candles[0..t] only."""
import json, math
from dataclasses import dataclass, field
from typing import Optional, List, Dict

P = dict(  # config/params.yaml
  swing_k_1m=3, swing_k_5m=2, swing_k_15m=2,
  cluster_min_touches=2, cluster_tol_pts=5, cluster_tol_atr=0.20, cluster_window=30,
  launch_impulse_atr=2.0, launch_base_atr=0.8, launch_base_min=2, launch_base_max=4, min_departure=1.0,
  max_touches=3, acceptance_candles=5, micro_ttl_min=90, axis_ttl_min=120,
  dormancy_atr=25, revival_atr=15, max_active_levels=8,
  grade_a_min=3, grade_b_min=2, clean_formation_candles=10,
  atr_period=14, atr_min=12, atr_max=60,
  alert_pts=20, alert_atr=1.5,
  max_trades=3, max_consec_loss=2, max_loss_r=2.0, risk_rupees=5000,
  htf_close_buffer_min=3,
  b_pierce_pts=8, b_pierce_atr=0.4, b_wick_ratio=0.55, b_reclaim_pts=5, b_reclaim_atr=0.25, b_reclaim_max=2,
  a_retest_pts=8, a_retest_atr=0.5, a_hold_pts=5, a_hold_atr=0.3, a_retest_max=20,
  sl_buf_pts=6, sl_buf_atr=0.45,
  r_min_pts=12, r_min_atr=0.55, r_max_pts=35, r_max_atr=1.40, r_abs_max=60,
  min_space_ratio=2.5, t1_r=1.5,
  max_cost_frac_r=0.25, min_r_prem_spread=8.0, lot_size=30, delta=0.5,
  slip_entry=2.0, slip_exit=2.0, slip_stopgap=1.5,
  windows=[("09:30","11:15"),("13:30","14:45")],
)
def mins(hhmm): h,m = hhmm.split(":"); return int(h)*60+int(m)
WIN = [(mins(a),mins(b)) for a,b in P["windows"]]
T0  = mins("09:15")

@dataclass
class Candle:
    i:int; o:float; h:float; l:float; c:float; tf:str="1m"
    @property
    def rng(self): return self.h-self.l
    @property
    def body_top(self): return max(self.o,self.c)
    @property
    def body_bot(self): return min(self.o,self.c)
    @property
    def lower_wick(self): return self.body_bot-self.l
    @property
    def upper_wick(self): return self.h-self.body_top
    @property
    def cpos(self): return 0.5 if self.rng==0 else (self.c-self.l)/self.rng
    @property
    def third(self): return "top" if self.cpos>=0.66 else ("bottom" if self.cpos<=0.34 else "mid")
    def t(self):
        m=T0+self.i; return f"{m//60:02d}:{m%60:02d}"

@dataclass
class Level:
    id:str; kind:str; side:str; born_i:int; born_tf:str
    body_edge:float; wick_tip:float
    departure:float=0.0; touches:int=0; grade:str="C"
    state:str="alive"; death:Optional[str]=None; grade_at_sleep:str="C"
    @property
    def zlo(self): return min(self.body_edge,self.wick_tip)
    @property
    def zhi(self): return max(self.body_edge,self.wick_tip)

STRENGTH = {"anchor_pdh":"strong","anchor_pdl":"strong","anchor_or":"strong",
            "day_extreme":"strong","round_500":"medium","round_100":"weak"}

class Engine:
    def __init__(s, pdh,pdl,pdc):
        s.pdh,s.pdl,s.pdc = pdh,pdl,pdc
        s.c1:List[Candle]=[]; s.c5:List[Candle]=[]; s.c15:List[Candle]=[]
        s.levels:Dict[str,Level]={}; s.dormant:Dict[str,Level]={}
        s.orh=s.orl=None; s.day_hi=-1e9; s.day_lo=1e9
        s.axis=None; s.axis_at=None; s.swings5=[]; s.bos=None
        s.trades=0; s.consec_loss=0; s.cum_r=0.0; s.blocked=None
        s.attempted=set(); s.log=[]; s.journeys=[]; s.narrate=[]
        s.mode_count={"BLOCKED":0,"WATCH":0,"ALERT":0,"IN":0}
        s.rejects={}; s.signals=[]; s._n=0

    # ---------- helpers ----------
    def atr(s,n=14,tf="1m"):
        arr = {"1m":s.c1,"5m":s.c5}[tf]
        if len(arr)<n: return None
        return sum(x.rng for x in arr[-n:])/n
    def eff(s,pts,mult,atr): return max(pts, mult*atr) if atr else pts

    def agg(s):
        n=len(s.c1)
        if n%5==0:
            w=s.c1[-5:]; s.c5.append(Candle(n-1,w[0].o,max(x.h for x in w),min(x.l for x in w),w[-1].c,"5m"))
        if n%15==0:
            w=s.c1[-15:]; s.c15.append(Candle(n-1,w[0].o,max(x.h for x in w),min(x.l for x in w),w[-1].c,"15m"))

    # ---------- LEVELS ----------
    def add(s,lv):
        for e in list(s.levels.values())+list(s.dormant.values()):
            if abs(e.body_edge-lv.body_edge) <= P["cluster_tol_pts"]:
                order={"1m":0,"5m":1,"15m":2,"1d":3}
                if order[lv.born_tf]>order[e.born_tf]: e.born_tf=lv.born_tf
                return False
        s.levels[lv.id]=lv; return True

    def swings(s,arr,k,tf):
        i=len(arr)-1-k
        if i<k: return
        H=[x.h for x in arr]; L=[x.l for x in arr]
        if all(H[i]>H[i-j] for j in range(1,k+1)) and all(H[i]>H[i+j] for j in range(1,k+1)):
            s.add(Level(f"T{tf}H{arr[i].i}","TURN","resistance",arr[i].i,tf,arr[i].body_top,arr[i].h))
            if tf=="5m": s.swings5.append(("high",arr[i].h,arr[i].i))
        if all(L[i]<L[i-j] for j in range(1,k+1)) and all(L[i]<L[i+j] for j in range(1,k+1)):
            s.add(Level(f"T{tf}L{arr[i].i}","TURN","support",arr[i].i,tf,arr[i].body_bot,arr[i].l))
            if tf=="5m": s.swings5.append(("low",arr[i].l,arr[i].i))

    def launch(s):
        a=s.atr(20)
        if not a or len(s.c1)<9: return
        i=len(s.c1)-4                      # need 3 candles after, so confirm at t-3
        if i<5: return
        imp=s.c1[i]
        if imp.rng < P["launch_impulse_atr"]*a: return
        if imp.third not in ("top","bottom"): return
        for n in range(P["launch_base_max"],P["launch_base_min"]-1,-1):
            base=s.c1[i-n:i]
            if not base: continue
            w=max(x.h for x in base)-min(x.l for x in base)
            if w <= P["launch_base_atr"]*a*n:
                dep = abs(s.c1[i+3].c - imp.c)/a
                if dep < P["min_departure"]: return
                if imp.third=="top":
                    s.add(Level(f"LA{i}","LAUNCH","support",i,"1m",
                        max(x.body_bot for x in base), min(x.l for x in base), dep))
                else:
                    s.add(Level(f"LA{i}","LAUNCH","resistance",i,"1m",
                        min(x.body_top for x in base), max(x.h for x in base), dep))
                return

    def anchors(s):
        if not s.levels.get("PDH"):
            s.levels["PDH"]=Level("PDH","ANCHOR","resistance",0,"1d",s.pdh,s.pdh)
            s.levels["PDL"]=Level("PDL","ANCHOR","support",0,"1d",s.pdl,s.pdl)
            s.levels["PDC"]=Level("PDC","ANCHOR","axis",0,"1d",s.pdc,s.pdc)
        if len(s.c1)==15 and s.orh is None:
            s.orh=max(x.h for x in s.c1); s.orl=min(x.l for x in s.c1)
            s.levels["ORH"]=Level("ORH","ANCHOR","resistance",14,"15m",s.orh,s.orh)
            s.levels["ORL"]=Level("ORL","ANCHOR","support",14,"15m",s.orl,s.orl)
            s.narrate.append((s.c1[-1].t(),"OR",f"Opening range set: {s.orl:,.0f} – {s.orh:,.0f} (width {s.orh-s.orl:.0f} pts). Ab ye din ka pehla asli level hai."))

    def breaks(s):
        c=s.c1[-1]
        for lv in list(s.levels.values()):
            if lv.state!="alive" or lv.kind=="BREAK": continue
            broke = (lv.side=="resistance" and c.body_bot>lv.body_edge) or \
                    (lv.side=="support"    and c.body_top<lv.body_edge)
            if broke and lv.kind!="ANCHOR":
                lv.state="dead"; lv.death="broken"
                ax=Level(f"BR{c.i}","BREAK","axis",c.i,"1m",lv.body_edge,
                         c.h if lv.side=="resistance" else c.l)
                ax.grade="A"; s.levels[ax.id]=ax; s.axis=ax; s.axis_at=c.i
                s.journey(lv,c,"up" if lv.side=="resistance" else "down")
                s.narrate.append((c.t(),"BREAK",
                    f"{lv.kind} {lv.body_edge:,.0f} toota (body close). AXIS bana — ab wo support/resistance flip hai."))

    def journey(s,broken,c,direction):
        rungs=[]
        cands=[lv for lv in s.levels.values() if lv.state=="alive" and lv.id!=broken.id]
        ahead=[lv for lv in cands if (lv.body_edge>c.c if direction=="up" else lv.body_edge<c.c)]
        ahead.sort(key=lambda x:abs(x.body_edge-c.c))
        if ahead: rungs.append(("D1",ahead[0].body_edge,f"nearest {ahead[0].kind} {ahead[0].grade}"))
        origins=[lv for lv in cands if lv.kind=="LAUNCH" and (lv.body_edge>c.c if direction=="up" else lv.body_edge<c.c)]
        if origins:
            o=max(origins,key=lambda x:abs(x.body_edge-c.c))
            rungs.append(("D2",o.body_edge,"origin of prior move — 'jahan se aaya'"))
        anchor = s.pdh if direction=="up" else s.pdl
        rungs.append(("D4",anchor,"PDH" if direction=="up" else "PDL"))
        s.journeys.append(dict(at=c.t(),origin=round(broken.body_edge,1),dir=direction,
                               rungs=[(a,round(b,1),d) for a,b,d in rungs],outcome="open"))

    def touches_and_death(s):
        c=s.c1[-1]; a=s.atr(20) or 20
        for lv in s.levels.values():
            if lv.state!="alive": continue
            if c.l<=lv.zhi and c.h>=lv.zlo: lv.touches+=1
            if lv.touches>=P["max_touches"]: lv.state="dead"; lv.death="exhausted"
        # dormancy (v2.1) — distance puts a level to SLEEP, not to death
        for lv in list(s.levels.values()):
            if lv.state!="alive" or lv.kind=="ANCHOR": continue
            if abs(c.c-lv.body_edge) > P["dormancy_atr"]*a and lv.grade in ("A","B"):
                lv.state="dormant"; lv.grade_at_sleep=lv.grade
                s.dormant[lv.id]=s.levels.pop(lv.id)
        for lv in list(s.dormant.values()):
            if abs(c.c-lv.body_edge) <= P["revival_atr"]*a:
                lv.state="alive"; s.levels[lv.id]=s.dormant.pop(lv.id)   # touches PRESERVED

    def grade(s):
        a=s.atr(20) or 20
        for lv in s.levels.values():
            if lv.state!="alive": continue
            sc=0
            if lv.touches==0: sc+=1
            if lv.departure>=P["min_departure"]: sc+=1
            if lv.born_tf in ("5m","15m","1d") or lv.kind=="ANCHOR": sc+=1
            if lv.departure>=P["min_departure"]*1.5: sc+=1
            lv.grade = "A" if sc>=P["grade_a_min"] else ("B" if sc>=P["grade_b_min"] else "C")
        # round numbers can never be Grade A (v2)
        for lv in s.levels.values():
            if lv.kind=="ROUND" and lv.grade=="A": lv.grade="B"

    def cap(s):
        c=s.c1[-1]
        alive=[l for l in s.levels.values() if l.state=="alive" and l.kind!="ROUND"]
        if len(alive)<=P["max_active_levels"]: return
        alive.sort(key=lambda x:abs(x.body_edge-c.c))
        for lv in alive[P["max_active_levels"]:]:
            lv.state="dormant"; lv.grade_at_sleep=lv.grade; s.dormant[lv.id]=s.levels.pop(lv.id)

    def obstacles(s,price,direction):
        out=[]
        for lv in s.levels.values():
            if lv.state!="alive": continue
            if (direction=="up" and lv.body_edge>price) or (direction=="down" and lv.body_edge<price):
                st = "strong" if (lv.kind=="ANCHOR" or lv.grade=="A") else ("medium" if lv.grade=="B" else "weak")
                out.append((abs(lv.body_edge-price),lv.body_edge,st,lv.id))
        r = 500*(math.ceil(price/500) if direction=="up" else math.floor(price/500))
        if abs(r-price)>1: out.append((abs(r-price),r,"medium",f"round{int(r)}"))
        r100 = 100*(math.ceil(price/100) if direction=="up" else math.floor(price/100))
        if abs(r100-price)>1: out.append((abs(r100-price),r100,"weak",f"r{int(r100)}"))
        for d in (s.day_hi,s.day_lo):
            if (direction=="up" and d>price) or (direction=="down" and d<price):
                out.append((abs(d-price),d,"strong","day_extreme"))
        out.sort(); return out

    # ---------- GUARDS ----------
    def guards(s):
        c=s.c1[-1]; m=T0+c.i
        if len(s.c1)<P["atr_period"]: return "warmup"
        if s.blocked: return s.blocked
        if not any(a<=m<b for a,b in WIN): return "time_window"
        pos_in_15 = (m-T0)%15
        if pos_in_15 >= 15-P["htf_close_buffer_min"]: return "htf_close_proximity"
        a=s.atr()
        if a<P["atr_min"]: return "volatility_floor"
        if a>P["atr_max"]: return "volatility_ceiling"
        if s.trades>=P["max_trades"]: s.blocked="session_max_trades"; return s.blocked
        if s.consec_loss>=P["max_consec_loss"]: s.blocked="session_consec_loss"; return s.blocked
        if s.cum_r<=-P["max_loss_r"]: s.blocked="session_max_loss"; return s.blocked
        return None

    def mode(s,gate):
        if gate: return "BLOCKED"
        c=s.c1[-1]; a=s.atr() or 20
        d=s.eff(P["alert_pts"],P["alert_atr"],a)
        for lv in s.levels.values():
            if lv.state=="alive" and lv.grade=="A" and lv.kind!="ROUND" and abs(c.c-lv.body_edge)<=d:
                return "ALERT"
        return "WATCH"

    # ---------- SETUPS ----------
    def setup_B(s):
        """Sweep-reclaim. Sweep candle = t-1 or t; reclaim = current."""
        a=s.atr() or 20
        pierce_min=s.eff(P["b_pierce_pts"],P["b_pierce_atr"],a)
        reclaim_min=s.eff(P["b_reclaim_pts"],P["b_reclaim_atr"],a)
        cur=s.c1[-1]
        for back in (0,1,2):
            if len(s.c1)<back+2: continue
            sw=s.c1[-1-back]
            for lv in s.levels.values():
                if lv.state!="alive" or lv.grade!="A" or lv.kind=="ROUND": continue
                if (lv.id,"B") in s.attempted: continue
                # long at support
                if lv.side in ("support","axis"):
                    pierce = lv.wick_tip - sw.l
                    if pierce < pierce_min: continue
                    if sw.rng==0 or sw.lower_wick/sw.rng < P["b_wick_ratio"]: continue
                    if cur.c - lv.body_edge < reclaim_min: continue
                    if cur.third!="top": continue
                    return dict(setup="B_sweep_reclaim",dir="long",level=lv,extreme=sw.l,
                        entry=cur.c, ev=dict(pierce=round(pierce,1),
                        wick_ratio=round(sw.lower_wick/sw.rng,2),
                        reclaim=round(cur.c-lv.body_edge,1),candles_since_sweep=back))
        return None

    def setup_A(s):
        """Flip retest at the BREAK axis."""
        if not s.axis or s.axis.state!="alive": return None
        a=s.atr() or 20; c=s.c1[-1]
        if c.i - s.axis_at > P["a_retest_max"]: return None
        if (s.axis.id,"A") in s.attempted: return None
        tol=s.eff(P["a_retest_pts"],P["a_retest_atr"],a)
        hold=s.eff(P["a_hold_pts"],P["a_hold_atr"],a)
        recent=s.c1[s.axis_at+1:]
        if len(recent)<3: return None
        up = s.axis.wick_tip > s.axis.body_edge
        if up:
            if abs(c.c-s.axis.body_edge)>tol*3: return None
            if any(x.body_bot < s.axis.body_edge-hold for x in recent): return None
            lows=[x.l for x in recent]; hl=min(lows)
            if c.c <= s.c1[-2].h: return None
            if c.third!="top": return None
            return dict(setup="A_flip_retest",dir="long",level=s.axis,extreme=hl,entry=c.c,
                        ev=dict(axis=round(s.axis.body_edge,1),higher_low=round(hl,1),
                                candles_since_break=c.i-s.axis_at))
        return None

    # ---------- RISK + COST ----------
    def evaluate(s,cand):
        a=s.atr() or 20; ev=dict(cand["ev"])
        buf=s.eff(P["sl_buf_pts"],P["sl_buf_atr"],a)
        sl = cand["extreme"]-buf if cand["dir"]=="long" else cand["extreme"]+buf
        R  = abs(cand["entry"]-sl)
        rmin=s.eff(P["r_min_pts"],P["r_min_atr"],a)
        rmax=min(P["r_abs_max"],s.eff(P["r_max_pts"],P["r_max_atr"],a))
        ev.update(atr=round(a,1),sl=round(sl,1),R=round(R,1),r_min=round(rmin,1),r_max=round(rmax,1))
        if R<rmin: return None,"r_too_tight",ev
        if R>rmax: return None,"r_too_wide",ev
        obs=s.obstacles(cand["entry"],"up" if cand["dir"]=="long" else "down")
        gate_obs=[o for o in obs if o[2] in ("strong","medium")]
        if not gate_obs: return None,"space_insufficient",ev
        space=gate_obs[0][0]; ratio=space/R
        ev.update(space=round(space,1),space_obstacle=gate_obs[0][3],space_ratio=round(ratio,2),
                  nearest_any=round(obs[0][0],1) if obs else None)
        if ratio<P["min_space_ratio"]: return None,"space_insufficient",ev
        # cost gate (v2)
        r_prem=R*P["delta"]; spread=1.6
        cost=spread+P["slip_entry"]+P["slip_exit"]+P["slip_stopgap"]
        ev.update(r_premium=round(r_prem,1),spread=spread,cost_prem=round(cost,1),
                  cost_frac=round(cost/r_prem,3))
        if cost/r_prem > P["max_cost_frac_r"]: return None,"cost_excessive",ev
        if r_prem < P["min_r_prem_spread"]*spread: return None,"cost_excessive",ev
        lots=int(P["risk_rupees"]//(R*P["delta"]*P["lot_size"]))
        if lots<1: return None,"size_zero",ev
        ev.update(lots=lots,t1=round(cand["entry"]+P["t1_r"]*R,1))
        return True,None,ev

    # ---------- MAIN ----------
    def on_candle(s,o,h,l,c):
        cd=Candle(len(s.c1),o,h,l,c); s.c1.append(cd); s.agg()
        s.day_hi=max(s.day_hi,h); s.day_lo=min(s.day_lo,l)
        s.anchors(); s.touches_and_death(); s.breaks()
        s.swings(s.c1,P["swing_k_1m"],"1m")
        if len(s.c1)%5==0:  s.swings(s.c5,P["swing_k_5m"],"5m")
        if len(s.c1)%15==0: s.swings(s.c15,P["swing_k_15m"],"15m")
        s.launch(); s.grade(); s.cap()

        gate=s.guards(); md=s.mode(gate); s.mode_count[md]+=1
        rec=dict(t=cd.t(),mode=md,px=round(c,1))
        if md=="BLOCKED":
            rec["gate"]=gate; s.rejects[gate]=s.rejects.get(gate,0)+1
        elif md=="ALERT":
            cand = s.setup_B() or s.setup_A()
            if not cand:
                rec["gate"]="no_setup"; s.rejects["no_setup"]=s.rejects.get("no_setup",0)+1
            else:
                ok,gt,ev = s.evaluate(cand)
                rec.update(setup=cand["setup"],level=round(cand["level"].body_edge,1),ev=ev)
                if ok:
                    rec["outcome"]="SIGNAL"; s.signals.append((cd.t(),cand,ev))
                    s.attempted.add((cand["level"].id,cand["setup"][0])); s.trades+=1
                    s.narrate.append((cd.t(),"SIGNAL",
                      f"{cand['setup']} {cand['dir'].upper()} @ {cand['entry']:,.0f} | SL {ev['sl']:,.0f} "
                      f"(R={ev['R']}) | space {ev['space']} = {ev['space_ratio']}x | {ev['lots']} lots"))
                else:
                    rec["gate"]=gt; s.rejects[gt]=s.rejects.get(gt,0)+1
                    s.narrate.append((cd.t(),"REJECT",
                      f"{cand['setup']} mila {cand['level'].body_edge:,.0f} pe — par {gt}. " +
                      (f"R={ev.get('R')} (allowed {ev.get('r_min')}-{ev.get('r_max')})" if "r_too" in gt else
                       f"space {ev.get('space')} ÷ R {ev.get('R')} = {ev.get('space_ratio')}x, chahiye 2.5x" if gt=="space_insufficient" else
                       f"cost {ev.get('cost_prem')} prem pts = {ev.get('cost_frac',0)*100:.0f}% of R" if gt=="cost_excessive" else "")))
        s.log.append(rec)
