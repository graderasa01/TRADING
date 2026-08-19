# DRY RUN — 6 bugs jo sirf ENGINE CHALANE se mile

**Date:** 11 Aug 2026
**Kya kiya:** specs 01–09 ka ek working prototype likha (levels, structure, guards,
mode machine, setups A/B, risk, cost gate, journey ladder) aur ek realistic
375-candle Bank Nifty session par chalaya.

```
Session : Open 57,625  High 57,968  Low 57,434  Close 57,831  (range 534 pts)
Anchors : PDH 57,840   PDL 57,455   PDC 57,612
1m ATR14: 17–33 (vol gate 12–60 ke andar — sahi range)
Planted : PDL par ek textbook sweep-reclaim 09:57–09:58
```

Ye chhe bugs **koi bhi spec padh kar nahi pakad sakta.** Sab arithmetic ke andar
chhupe the aur sirf chalane par bahar aaye.

---

## 🔴 BUG 1 — Sirf LAUNCH levels hi kabhi Grade A ban sakte hain

**Pehla run: ALERT mode = 0%. Poore din me ek bhi setup evaluate nahi hua.**

Spec 03 §7 me grading ke 4 criteria hain, Grade A ke liye 3 chahiye:

| level type | untested | fast departure | HTF confirmed | clean formation | score | grade |
|---|---|---|---|---|---|---|
| TURN (1m swing) | 1 | 0 | 0 | 0 | 1 | C |
| TURN (5m swing) | 1 | 0 | 1 | 0 | 2 | B |
| TURN (15m swing) | 1 | 0 | 1 | 0 | 2 | B |
| ANCHOR PDH/PDL | 1 | 0 | 1 | 0 | 2 | B |
| ANCHOR opening range | 1 | 0 | 1 | 0 | 2 | B |
| **LAUNCH (fast)** | 1 | 1 | 0 | 1 | **3** | **A** |

**Wajah:** `departure_speed` spec me sirf LAUNCH levels ke liye define hai (spec 03 §3).
TURN aur ANCHOR ke liye kabhi define hi nahi kiya → default 0 → wo 2 se upar score
nahi kar sakte → **kabhi Grade A nahi** → aur setup sirf Grade A par trigger hota hai.

**Aur ek seedha contradiction:**

- spec 06: *"At `kind == ANCHOR`, Setup B is the **only permitted** setup"*
- spec 03: *"a setup may only trigger at a **Grade A** level"*
- par ANCHOR kabhi Grade A ho hi nahi sakta

→ **PDH/PDL par Setup B kabhi fire nahi karega.** Do rules jo alag-alag sahi hain,
saath me ek dusre ko kaat dete hain.

**Fix jo lagaya:** `departure_speed` har level type ke liye compute karo —
`|price 3 candles baad − level| ÷ ATR`. Ye TURN ke liye utna hi meaningful hai jitna
LAUNCH ke liye. Plus ANCHOR ko clean-formation ka point (wo poore session me bante hain).

**Natija:** ALERT 0% → **11.5%**

---

## 🔴 BUG 2 — Level 3 minute me mar jaata hai, bina ek bhi asli test ke

Fix 1 ke baad bhi 0 signals. Maine PDL ka trace nikala:

```
time     low       touches   state    event
09:15    57,620    0         alive
09:55    57,447    1         alive    pehla touch
09:56    57,446    2         alive
09:57    57,434    3         DEAD     <-- exhausted
```

**PDL 09:57 par mar gaya — apne hi sweep se 2 minute pehle.**

spec 03 §4: *"a touch means price entered `[zone_low, zone_high]`"*. PDH/PDL/round
numbers ka `pocket = 0`, yaani zone ek hi price hai. Engine har 1m candle par touch
count karta hai.

To price PDL ke aas-paas 3 minute mandrayi → 3 "touches" → `max_touches` → exhausted.

**Ek TEST aur ek MINUTE alag cheezein hain. Spec ne dono ko ek maan liya.** Insaan
kahega "abhi to ek hi test hua hai" — engine kehta hai "teen ho gaye, level khatam."

**Fix jo lagaya:** touch tabhi ginega jab price zone se **baahar** ja kar (0.6 × ATR
door) **wapas** aaye. Mandrana ek touch hai, teen nahi.

**Natija:** ALERT 11.5% → **16.3%**, PDL sweep ke waqt zinda

---

## 🔴 BUG 3 — Sabse bada. Do rules milkar Setup B ko delete kar dete hain.

Fix 2 ke baad bhi 0 signals. Maine 09:58 par Setup B ki **har** condition check ki:

```
B1 level Grade A?          A          PASS
B1 level alive?            alive      PASS
B2 pierce 21 >= 12?                   PASS
B3 lower wick 83% >= 55%?             PASS
B5 reclaim 35 >= 7?                   PASS
B6 close in top third? (top)          PASS
Mode: PDL 35 pts door, alert distance 44   PASS
```

**Chhe me se chhe pass. Phir bhi kuch nahi hua.**

Wajah — 09:58 session ka minute 43 hai. 15m candle 09:45–10:00 chal rahi hai,
uske andar position = **13 / 15**.

```
spec 05 guard #6 — htf_close_proximity:
   "no new entries in the final 3 minutes of a 15m candle"
   13 >= 12  →  BLOCKED
```

Mode `BLOCKED` ho gaya, `ALERT` nahi. **Setup detector chala hi nahi. Engine ne wo
perfect sweep DEKHA tak nahi.**

### Aur yahan asli baat

`mythinking.md` §6 me tumne khud likha hai:

> *"15m candle band hone se 3-4 min pehle | **Wick yahin banti hai.** Naya trade nahi
> kholta, **2 min rukta hu.**"*

Tum kehte ho: wick yahin banti hai, isliye main 2 minute **rukta hu** — phir lunga.
Spec ne isko *"3 minute entry BAND"* bana diya.

Ab Setup B ka B7 dekho: *"Candles between sweep and reclaim ≤ 2. Candle 3+ → stale."*

```
sweep 15m close ke aakhri 3 minute me banti hai   (tumhare hi observation se)
un 3 minute me entry blocked hai
blackout khatam hone tak reclaim 2 candle purani → setup_stale
```

**Jis waqt Setup B sabse zyada banti hai, theek us waqt system usse structurally trade
nahi kar sakta.** Dono rules alag-alag bilkul sahi hain. Saath me wo setup ko mita dete
hain.

**Fix jo lagaya:** `htf_close_proximity` sirf **continuation** setups (A aur C) par
lagega. Setup B exempt hai — kyunki guard ki wajah hi ye hai ki *"HTF candle apni shakal
aakhri minute me palatti hai"*, aur Setup B **wahi trade hai jo us palat se paisa banati
hai.** Guard ka apna reason Setup B par lagta hi nahi.

**Natija:** ALERT 16.3% → **19.5%**, aur pehli baar setup evaluate hua

---

## 🔴 BUG 4 — v2 ka ATR-relative R ceiling bhi kaafi nahi tha

Fix 3 ke baad, aakhirkar:

```
09:58  [REJECT] B_sweep_reclaim mila 57,455 pe — par r_too_wide.
                R = 69.1  (allowed 16.0 – 40.7)
```

`REVIEW-v2.md` §6 me maine analytically kaha tha ki v1 ka flat 35-point ceiling Setup B
ko maar deta hai, aur usko `max(35, 1.40 × ATR)` bana diya tha. **Yahan ATR 29 tha, to
ceiling 40.7 — aur asli trade ka R 69 nikla. v2 ka fix bhi kam pad gaya.**

Kyun:
```
sweep low     57,434
reclaim close 57,490   ← entry
                  56 pts ka fasla
+ sl_buffer   13
= R           69
```

Sweep candle ka wick 30 point neeche gaya, phir reclaim candle ne 26 point ka body
banaya. Dono achhe signs hain — aur dono milkar entry ko stop se 56 point door kar dete
hain.

**Ye ek asli design tension hai, bug nahi.** Reclaim ke close par ghusna aur stop sweep
wick ke paar rakhna — achhi sweep par hamesha bada R dega. Teen imaandaar raste hain:

1. **Reclaim ke baad pullback par ghuso**, close par nahi — setup badal jaayega, par R
   aadha ho jaayega
2. **Bada R accept karo aur size ghatao** — par phir cost gate kaatega (R bada hai to
   cost fraction theek hai, ye actually chalega)
3. **Aise trades chhod do** — par phir Setup B lagbhag bacha hi nahi

**Ye faisla tumhara hai. Main ise fix nahi kar sakta — ye strategy ka sawaal hai,
arithmetic ka nahi.**

---

## 🟡 BUG 5 — BREAK axes ne poora level book kha liya

```
Ek din me: TURN 36 · BREAK 27 · ANCHOR 5 · LAUNCH 1
28 breaks
Din ke ant me level book: 8 me se 6 slots BREAK axes (sab grade C)
```

Har body-close kisi bhi level ke paar ek naya AXIS banata hai. 36 TURN levels hain, to
28 breaks ho jaate hain, aur 8-level cap axes se bhar jaata hai — wahi TURN aur LAUNCH
levels bahar jo system dhoondhne ke liye bana tha.

Aur dhyaan do: **sirf 1 LAUNCH level bana poore din me** — jabki spec use "the
highest-value 1m level" kehta hai. Sabse kimti detector sabse kam fire karta hai.

**Suggested fix (lagaya nahi — tumhara faisla):** AXIS sirf tab bane jab tootne wala
level Grade A ya B ho. Grade C level ka tootna koi khabar nahi hai.

---

## 🟡 BUG 6 — Spec ka apna mode-split target uske apne time windows se possible nahi

```
spec 05 kehta hai : ~70% WATCH / 25% ALERT / 5% IN
asli natija       : 52% BLOCKED / 28% WATCH / 19% ALERT / 0% IN
```

Time windows hi 182 candles block kar dete hain (375 me se 49%), plus
htf_close_proximity aur warmup. **BLOCKED hamesha sabse bada bucket rahega** — par
spec ki expected distribution me BLOCKED hai hi nahi.

Ye khatarnaak isliye hai ki spec kehta hai *"agar ALERT 40% se upar jaye to system
over-trade karne wala hai"* — ek warning jo galat baseline par set hai.

**Fix:** expected split ko **eligible minutes** par batao, poore session par nahi:
`WATCH ~60% / ALERT ~35% / IN ~5% of non-BLOCKED candles`.

---

# PART 2 — SAB FIX KARNE KE BAAD

Chheo fixes lagaye (`engine_fixed.py`) aur wahi session dobara chalaya.

## Pehle vs baad

| | v1 jaisa likha tha | 6 fixes ke baad |
|---|---|---|
| ALERT mode | **0.0%** | **19.5%** |
| Setups detected | **0** | **1** |
| Grade A levels | sirf LAUNCH | TURN, ANCHOR, LAUNCH sab |
| PDL sweep ke waqt | **dead** (09:57 par exhausted) | **alive, Grade A** |
| Level book me BREAK axes | 6 / 8 | 1 / 8 |
| Dead levels | 45 | 30 |
| Signals | 0 | 0 — **par ab asli wajah se** |

## Wo planted sweep, ab poore pipeline se

```
09:58  [REJECT] B_sweep_reclaim mila 57,455 pe
                space_insufficient — space 41.3 ÷ R 37.8 = 1.09x, chahiye 2.5x
```

Poora rasta ab kaam karta hai:

```
PDL Grade A, alive, touches 0          ✓   (Bug 1 + 2 fix)
mode ALERT (35 pts door, alert 44)     ✓   (Bug 3 fix — detector chala)
pierce 21 ≥ 12                          ✓
lower wick 83% ≥ 55%                    ✓
reclaim 35 ≥ 7, close top third         ✓
entry 57,458.7 (pullback mode)          ✓   (Bug 4 fix — reclaim close 57,490 nahi)
R = 37.8, bounds 16.0–40.7              ✓   (v1 me R 69 tha → r_too_wide)
space 41.3 to round-500 @ 57,500        ✗   REJECT
```

**Aur ye rejection bilkul sahi hai.** 57,500 ek asli magnet hai, entry se sirf 41 point
upar. 38-point stop ke saath 41 point ki chhat me ghusna kharab trade hai — engine ne
theek pakda. **v1 me ye trade reject nahi hoti thi; v1 me ye trade DEKHI hi nahi jaati
thi.** Farak yahi hai.

## Aur ek bug — mere apne fix me

FIX 6 likhte waqt maine `b_entry_max_extreme_atr_mult: 1.2` rakha. Chala to R phir bhi
ceiling ke bahar. Algebra:

```
R      = (entry_cap + sl_buffer) × ATR = (1.20 + 0.45) × ATR = 1.65 × ATR
r_max  = 1.40 × ATR
chalega tabhi jab  cap + 0.45 ≤ 1.40   →   cap ≤ 0.95
```

**1.65 kabhi 1.40 se chhota nahi hoga. Wo cap kisi bhi ATR par pass nahi kar sakta tha.**

Ye theek wahi bug-class hai jo `specs/10-SELF-DIAGNOSTICS.md` §3.3 ki reachability
assertions pakadti hain — do parameters jo alag-alag theek lagte hain par saath me ek
gate ko namumkin bana dete hain. **Aur maine ye galti khud kar di, us spec ko likhne ke
20 minute baad.** Isse behtar sabooti nahi ho sakti ki wo assertions zaroori hain.

`0.85` par set kiya, ab har ATR par pass hota hai.

---

# Din bhar ka final natija (fixes se PEHLE)

```
375 candles
BLOCKED  195  52.0%
WATCH    107  28.5%
ALERT     73  19.5%
IN         0   0.0%

Rejections:  time_window 182 · no_setup 72 · warmup 13 · r_too_wide 1
SIGNALS:     0
Journeys logged: 28
```

**Ek bhi trade nahi — ek aise din par jisme maine jaan-boojh kar ek textbook setup
plant kiya tha.**

Char bug fix karne ke baad engine ne usse **dekha**, sahi pehchana, aur phir R = 69 par
imaandaari se reject kar diya.

---

# To ye kya sabit karta hai

**Achhi khabar:** engine sach me "dekhta" hai. Bina chart ke usne opening range banaya,
swing pivots nikale, PDL par 21-point pierce aur 83% wick pehchana, sweep ko breakout se
alag kiya, 28 journeys map kiye, aur har candle par imaandaari se bataya ki usne trade
kyun nahi liya. **Wo hissa kaam karta hai.**

**Buri khabar:** likhi hui spec, jaisi hai, **kabhi trade nahi karti.** Char alag-alag
bugs — aur unme se koi bhi spec padh kar nahi milta. Sabhi ek dusre ke saath interaction
me the.

**Aur asli seekh:** ye char bugs 20 minute me mile kyunki maine engine chalaya. Agar
Claude Code poora P0–P7 bina is test ke banata, to ye bugs P9 tak zinda rehte — aur
tab report kehti *"no edge found"*, jabki asli baat hoti *"the engine never traded."*

**Isliye BUILD-BRIEF ka P1 gate (level-overlap test) skip mat karna. Aur usme ye
bhi jodo: P3 ke baad ek pura din chalao aur ginno ki kitne setups DETECT hue —
sirf kitne trade hue, wo nahi.** Agar detection zero hai, kuch aur banane ka koi
matlab nahi.

---

## Files

| File | Kya hai |
|---|---|
| `gen.py` | 375-candle realistic session generator, structure planted |
| `engine.py` | spec 01–09 ka faithful implementation — **bugs ke saath, jaisa likha hai** |
| `engine_fixed.py` | wahi + 4 fixes (grading, touch, htf-exempt, diagnostics) |
| `run.py` | session chalao aur report chhapo |
| `session.json` | wahi data, taaki natija dobara mile |

```bash
cd prototype && python3 run.py
```

Ye production code nahi hai — koi Decimal nahi, koi test nahi, exits nahi, options
layer nahi. Ye ek **reference implementation** hai jo sabit karta hai ki rules kya
karte hain. Claude Code isse padh kar samajh sakta hai ki har rule ka asli behaviour
kya hai, aur ye char bugs dobara na banaye.

---

*Sab numbers is prototype ko is session par chala kar nikle hain. Data synthetic hai,
par structure realistic hai aur bugs asli hain — wo rules ke logic me hain, data me
nahi.*
