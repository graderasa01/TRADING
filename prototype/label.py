"""MOVE LABELLER — candles se hi, bina kisi judgement ke.
Har significant move nikalta hai: kahan se shuru hui, kab, kitni badi."""
import json, os, sys
D=os.path.dirname(os.path.abspath(__file__))

def label_moves(C, atr_fn, min_atr_mult=2.5, max_candles=30, max_retrace=0.35):
    """Ek MOVE = price >= min_atr_mult x ATR chali, <= max_candles me,
    beech me <= max_retrace pullback ke saath. Pure arithmetic. No opinion."""
    moves=[]; n=len(C)
    for i in range(20, n-3):
        a=atr_fn(i)
        if not a: continue
        need=min_atr_mult*a
        for direction,sign in (("up",1),("down",-1)):
            origin = C[i][3] if sign>0 else C[i][2]     # low for up-move, high for down
            best=0; best_j=None; peak=origin
            for j in range(i+1, min(i+max_candles, n)):
                ext = C[j][2] if sign>0 else C[j][3]
                move = sign*(ext-origin)
                if move>best: best, best_j, peak = move, j, ext
                # retrace check
                back = C[j][3] if sign>0 else C[j][2]
                if best>0 and sign*(peak-back)/best > max_retrace: break
            if best>=need and best_j:
                moves.append(dict(dir=direction, origin_i=i, origin=round(origin,1),
                    end_i=best_j, pts=round(best,1), candles=best_j-i,
                    atr=round(a,1), size_atr=round(best/a,1)))
    # overlapping moves ko merge karo — sabse bada rakho
    moves.sort(key=lambda m:-m["pts"]); keep=[]
    for m in moves:
        if not any(x["dir"]==m["dir"] and abs(x["origin_i"]-m["origin_i"])<8 for x in keep):
            keep.append(m)
    return sorted(keep, key=lambda m:m["origin_i"])
