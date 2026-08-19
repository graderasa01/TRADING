"""Realistic Bank Nifty 1m session generator.
Structure is DELIBERATE — we plant the situations a trader would recognise,
then let the engine find them on its own from numbers only."""
import random, json
random.seed(20260811)

PDC = 57612.0
PDH = 57840.0
PDL = 57455.0

C = []            # (minute_index, o,h,l,c)
def push(o,h,l,c):
    C.append((len(C), round(o,2), round(h,2), round(l,2), round(c,2)))

def drift(px, n, bias, vol, wick=0.70):
    """n candles drifting with `bias` pts/candle and `vol` noise."""
    for _ in range(n):
        o = px
        c = o + bias + random.gauss(0, vol)
        hi = max(o,c) + abs(random.gauss(0, vol*wick))
        lo = min(o,c) - abs(random.gauss(0, vol*wick))
        push(o,hi,lo,c); px = c
    return px

px = 57625.0                                   # flat-ish open vs PDC 57612

# 09:15-09:30  opening range: choppy, no direction  (15 candles)
px = drift(px, 15, 0.0, 16.0)

# 09:30-09:52  drift down toward PDL             (22)
px = drift(px, 22, -6.2, 13.0)

# 09:52-09:57  approach PDL 57455                 (5)
px = drift(px, 5, -4.0, 11.0)

# 09:57  THE SWEEP — wick through PDL, body back inside
o = px
lo = PDL - 21.0
hi = o + 4.0
c  = PDL + 9.0
push(o,hi,lo,c); px = c
# 09:58  reclaim candle: body closes well above PDL, close in top third
o = px; lo = o - 5.0; c = o + 26.0; hi = c + 3.0
push(o,hi,lo,c); px = c

# 09:59-10:25  the move up off the sweep          (27)
px = drift(px, 27, 5.4, 14.0)

# 10:26-10:31  a quiet base                       (6)
px = drift(px, 6, 0.2, 5.0)

# 10:32  IMPULSE candle (launch)                  (1)
o = px; c = o + 62.0; hi = c + 4.0; lo = o - 3.0
push(o,hi,lo,c); px = c

# 10:33-10:47  continue up, make the day high     (15)
px = drift(px, 15, 4.8, 15.0)
day_high_area = px

# 10:48-11:14  pull back into the launch zone     (27)
px = drift(px, 27, -3.6, 13.0)

# 11:15-13:29  LUNCH: tight chop, and we plant a TEXTBOOK setup at 12:10
px = drift(px, 40, 0.1, 7.5)
o = px; lo = px - 24.0; hi = px + 3.0; c = px + 11.0   # perfect sweep-reclaim at 12:10
push(o,hi,lo,c); px = c
o = px; lo = o-4; c = o + 19.0; hi = c+2
push(o,hi,lo,c); px = c
px = drift(px, 93, 0.0, 7.8)

# 13:30-14:20  afternoon push up, breaks the morning structure  (50)
px = drift(px, 50, 3.9, 15.0)

# 14:21-14:45  retest of the broken level                        (25)
px = drift(px, 25, -2.4, 13.0)

# 14:46-15:29  drift into the close
px = drift(px, 375-len(C), 1.0, 12.0)

C = C[:375]
json.dump({"pdh":PDH,"pdl":PDL,"pdc":PDC,"candles":C}, open('/tmp/demo/session.json','w'))

H=[x[2] for x in C]; L=[x[3] for x in C]
print(f"375 x 1m candles banaye")
print(f"  PDH {PDH:,.0f}   PDL {PDL:,.0f}   PDC {PDC:,.0f}")
print(f"  Open {C[0][1]:,.0f}  High {max(H):,.0f}  Low {min(L):,.0f}  Close {C[-1][4]:,.0f}")
print(f"  Day range {max(H)-min(L):,.0f} pts")
rng=[H[i]-L[i] for i in range(len(C))]
print(f"  1m candle range: avg {sum(rng)/len(rng):.1f}  max {max(rng):.0f}")
