# REVIEW v2 — kya toota, kyun toota, kya badla

**Date:** 11 Aug 2026
**Scope:** poore repo ka review — CLAUDE.md, 9 specs, params.yaml
**Method:** design ke apne numbers pe arithmetic chalayi, aur India-specific
market facts verify kiye (expiry, lot size, SEBI algo framework)

> Original v1 `git` me safe hai — commit `v1 specs as written, before live-reality
> review`. Kuch bhi kho nahi gaya, `git diff` se sab dikh jayega.

---

## Pehle, imaandaari se: ye design achha hai

Ye sab likhne se pehle ek baat saaf karni hai. Jitne trading systems log likhte hain,
unme se **95% me ye teen cheezein nahi hoti** jo tumhare v1 me pehle din se hain:

- **Default output = NO_TRADE**, aur har rejection ka gate naam se log hota hai
- **Look-ahead ki truncation test** — backtest jhooth bolne ka #1 tarika, aur tumne
  usko CI me daal diya
- **Rejection log ko primary dataset maanna** — most people log only trades

Aur `mythinking.md` ka §14 — jahan tumne likha ki entry timing aur level
identification sabse **kam** matter karte hain, jabki log wahin 90% mehnat karte hain
— wo lines is poore repo se zyada valuable hain.

Isliye neeche jo bhi likha hai wo "ye galat hai" nahi hai. Wo hai: **ye teen jagah
arithmetic tumhare khilaf ja rahi thi, aur v1 ko pata nahi tha.**

---

# PART 1 — JO CHEEZEIN LIVE ME TOOT JAATI

## 🔴 1. Bank Nifty ke weekly options exist hi nahi karte

`params.yaml` me tha: `expiry_preference: "nearest_weekly"`.

**NSE ne 20 November 2024 ko Bank Nifty weekly derivatives band kar diye.** SEBI ke
framework ke baad har exchange sirf ek index pe weekly de sakta hai — NSE ne Nifty 50
rakha. Bank Nifty ab **sirf monthly** hai, **last Tuesday** ko expire hota hai.

Iska matlab v1 ka pura expiry regime — spec 05 ka narrow window, spec 07 ka
`expiry_size_multiplier`, "weekly expiry day: no trades before 10:00" — **mahine me 4
din ke liye nahi, 1 din ke liye** hai.

Ye zyadatar **achhi khabar** hai: sabse mushkil regime ab saal me 50 baar nahi, 12 baar
aata hai. Par uss ek din ye zyada matter karta hai, kyunki poore mahine ka open
interest ek hi din me unwind hota hai.

**Aur ek chhoti si cheez jo bada farak karti hai:** lot size ab **30** hai (Jan 2026
series se, pehle 35 tha, Nov 2024 se pehle 15). Spec 07 ke worked example me 15 likha
tha. Do saal me teen baar badla hai — **instrument master se padho, config se kabhi
mat maano.**

---

## 🔴 2. Cost — yahi decide karta hai system chalega ya nahi

Ye sabse bada finding hai. Baaki sab iske aage chhota hai.

Weekly gaye, to ab monthly ATM option hi vehicle hai. Uska premium 3–4x hai, aur spread
bhi usi hisaab se. Tumhare **apne** design ke numbers se — R = 25 index points, ATM
delta 0.5:

```
R premium points me ............................ 12.5

round-trip slippage, spec ka apna assumption ....  5.5 prem pts  =  44% of R
round-trip slippage, realistic monthly ATM ......  8.0 prem pts  =  64% of R
round-trip slippage, tez/wide market ............ 13.0 prem pts  = 104% of R
```

Ab isko T1-at-1.5R-plus-runner scheme me daalo:

| cost | avg win | avg loss | break-even win rate |
|---|---|---|---|
| 0.10R | +1.90R | −1.10R | **36.7%** |
| 0.30R | +1.70R | −1.30R | **43.3%** |
| 0.50R | +1.50R | −1.50R | **50.0%** |

Is tarah ke setup ka realistic win rate **35–45%** hota hai.

**Matlab 0.50R cost pe system break-even se neeche hai — ek bhi galat read se pehle.**

Aur sabse bura: spec 07 ka **jo worked example v1 me "textbook trade" tha, wo v2 ke
cost gate se reject ho jaata hai.** Saare structural gates pass — level Grade A, sweep
valid, space 4.9x, R in bounds. Fail sirf execution economics pe: 53% of R spread
crossing me chala gaya.

### Isliye cost ab ek PRE-TRADE GATE hai, report line nahi

```python
reject "cost_excessive" if
    modelled_round_trip_cost > 0.25 × R_premium
 OR R_premium < 8 × observed_spread      # live quote se, model se nahi
```

Ye gate **bahut baar firegi. Wahi iska kaam hai.** Isko neeche mat karna trades badhane
ke liye — R badhao.

Dhyaan do: ye exactly wahi baat hai jo tumne khud `mythinking.md` §9 me likhi thi —
*"kam aur badi trade, zyada aur chhoti se behtar hai... cost per trade fixed hai."*
v2 ne bas usko code me daal diya. Tumhari soch sahi thi, v1 ke numbers usse match
nahi kar rahe the.

### Escape hatch — jaan lo, abhi decide mat karo

Agar P8.5 me measured cost 0.35R se upar nikle, to problem strategy nahi, **vehicle**
hai. Bank Nifty **futures** pe wahi trade ~3 index points round trip me hoti hai —
**~12% of R** — kyunki delta ka divisor nahi hai aur spread 1–2 point hai. Aur index
stop broker pe **asli SL-M** ban jaata hai, jo neeche wali problem #3 poori khatam kar
deta hai.

Keemat: margin (~₹2 lakh/lot vs ~₹60k–1.5L premium) aur gap loss uncapped.

Tumne options chuna hai — theek hai, wahi build kar raha hu. Bas ye number yaad rakho
comparison ke liye jab P8.5 me asli spread measure ho jaye. **Data pe decide karna, abhi
nahi.**

---

## 🔴 3. "Hard SL always resting" — ye build ho hi nahi sakta tha

CLAUDE.md v1 §6: *"Hard SL — always resting in the system. Never mental."*

Ye **likha nahi jaana chahiye tha**, kyunki banaya nahi ja sakta. Stop ek **index**
level hai. Position ek **option** hai. Koi broker option leg pe index-triggered stop
accept nahi karta.

To v1 ka "hard SL" asal me ek **software stop** tha jo process ke saath mar jaata hai —
mental stop, bas extra steps ke saath. Aur documentation me likha tha ki wo resting hai.
**Ye sabse khatarnaak type ki documentation error hai**, kyunki isse tum wo cheez banate
hi nahi jo missing thi.

### v2 — teen layer, aur teeno alag hain

| Layer | Kya | Kahan | Kab firegi |
|---|---|---|---|
| **L1** | Thesis invalidation | software, 1m close | aksar — yahi paisa bachati hai |
| **L2** | Index stop `sl_index` pe | software, **tick pe** | kabhi-kabhi |
| **L3** | Premium backstop SL-M | **broker pe asli order** | lagbhag kabhi nahi |

**L2 tick pe chalna zaroori hai.** v1 poora exit engine 1m close pe chalata tha — 25
point ke R pe wo market ko **59 second** muft de deta hai, aur exactly tab sabse zyada
jab price tez tumhare khilaaf ja rahi hai.

Ye no-look-ahead rule nahi todta. Wo rule **entry** ke liye hai. Exit karte waqt koi
future information nahi hai — sirf latency hai. Entry path aur exit path physically
alag rakho.

**L3** entry fill ke turant baad broker pe rakhi jaati hai, `2.0 × R_premium` door. Ye
trading stop nahi hai — ye **disaster stop** hai. Process mar jaye, bijli chali jaye,
websocket wapas na aaye — L3 hi ek cheez hai tumhare aur unmanaged position ke beech.
Agar ye kabhi fill ho, wo ek **incident** hai, normal loss nahi.

Plus ek **alag process ka heartbeat watchdog**: 90 second heartbeat na aaye → position
flat karo aur alert.

Ek trading process jo position ke saath mar sakta hai, broker pe kuch resting nahi, aur
koi dekh nahi raha — **ye poore design ka sabse bada uncontrolled risk hai.** Specs
03–06 ke kisi bhi entry rule se bada.

---

## 🔴 4. Session limits ek restart se khatam ho jaati thi

`trades_taken`, `consecutive_losses`, cooldown, duplicate registry — sab v1 me **sirf
memory me** the.

```
09:47  trade 1 fill, loss           → consecutive_losses = 1
10:31  trade 2 fill, loss           → consecutive_losses = 2 → BLOCKED
10:58  unhandled exception, process mar gaya
11:02  supervisor ne restart kiya
       → trades_taken = 0, consecutive_losses = 0, BLOCKED gayab
11:20  trade 3 fill, loss
12:05  trade 4 fill, loss
```

**2 trade ke cap wale din pe 4 loss.** Kill switch ek restart se haar gaya — aur wahi
waqt hai jab wo sabse zyada chahiye.

Aur ye koi imaginary scenario nahi hai: spec 01 §9 khud **mandate** karta hai ki
"unhandled exception → snapshot state, set BLOCKED". Yaani restart-adjacent path design
me hai hi.

**v2:** har change pe disk pe likho, startup pe load karo, `--force-fresh-session` ke
bina reset **forbidden**. Aur resume ke baad broker se reconcile — agar engine kehta hai
flat aur broker ke paas position hai, alert karo aur trade mat karo.

Board candles se rebuild hota hai. **Session state nahi hota.** Do alag mechanism hain,
alag rakho.

---

# PART 2 — JO CHUPKE SE NUMBERS KHARAB KAR RAHA THA

Ye wo bugs hain jo system ko crash nahi karte. Wo system ko chalne dete hain aur
**galat numbers dete hain** — jo zyada khatarnaak hai.

## 🟡 5. Round numbers — space gate ek sikka uchhalna ban gaya tha

v1 me har 100-mark ek pura level tha: Grade A tak ja sakta tha, cap me count hota tha,
ALERT trigger karta tha, aur space gate ko block karta tha.

100-point grid pe iske teen alag nuksaan hain:

**(a) ALERT kabhi band hi nahi hoti.** `alert_distance = 20` pe, price kisi na kisi
100-mark ke 20 point andar **session ka 40%** rehti hai — har 100 me se 40 ka band. Asli
levels usse upar. Spec 05 khud kehta hai 70% WATCH / 25% ALERT expect karo, aur warn
karta hai ki ALERT 40% se upar gaya to "system over-trade karne wala hai". **v1 ka apna
round-number rule wo guarantee kar raha tha.**

**(b) Level cap noise se bhar jaata tha.** Cap "2 nearest above, 2 nearest below" rakhta
hai. Round numbers sabse dense cheez hain, to wo chaar slot lagbhag hamesha 100-marks
ban jaate — TURN aur LAUNCH levels bahar, jinke liye poora engine bana tha.

**(c) Space gate entry price ke aakhri do digit pe chalne laga.** Agle 100-mark ki doori
lagbhag uniform hai [0,100] pe:

| R | space chahiye | P(pass) sirf round numbers se |
|---|---|---|
| 12 | 30 | 70% |
| 20 | 50 | 50% |
| 25 | 62.5 | **37.5%** |
| 35 | 87.5 | **12.5%** |
| 40+ | 100+ | **0% — mathematically impossible** |

25-point R wali trade **62% baar reject** ho jaati thi, kisi asli level ko dekhe bina —
sirf isliye ki entry price agle sau se kitni door thi.

Aur ye **R ke saath correlated** hai — yaani ye system ko chhote stops ki taraf dhakel
raha tha, jahan cost drag sabse bura hai. **v1 ke do gates ulti disha me khinch rahe
the:** `r_too_wide` R ko chhota karta tha, cost chhote R ko maarti thi.

**v2 — obstacle strength:**

```
strong  (Grade A, PDH/PDL, day H/L, OR)  → space gate + T1
medium  (Grade B, round 500/1000, range) → space gate + T1
weak    (Grade C, round 100)             → sirf T1. Kabhi reject nahi kar sakta.
```

Round 100 ab Grade A ban hi nahi sakta, cap me count nahi hota, ALERT trigger nahi
karta. Par **T1 ko अब bhi cap karta hai** — wo hissa v1 ka sahi tha.

Dono values (`space_v2` aur `space_v1_all_obstacles`) har decision pe log hoti hain,
taaki spec 09 ki counterfactual study **maap** sake ki ye change sahi tha ya nahi —
maanna nahi pade.

---

## 🟡 6. R ka flat ceiling Setup B ko delete kar raha tha

Setup B ki apni conditions **majboor** karti hain ki stop chaura ho. B3 kehta hai wick
candle ki range ka ≥55% ho, B6 kehta hai close top third me ho. To:

```
R  =  (≈0.70 × candle_range)  +  sl_buffer
```

v1 ke saath (buffer flat 10, r_max flat 35):

| sweep candle range | v1 R | v1 verdict |
|---|---|---|
| 25 | 27.5 | OK |
| 30 | 31.0 | OK |
| 40 | 38.0 | **rejected** |
| 50 | 45.0 | **rejected** |

Bank Nifty pe active window me 40–50 point ki 1m candle koi anokhi baat nahi hai — wo
**wahi hai jo ek asli liquidity sweep dikhti hai** kisi defended level pe.

To v1 kharab Setup B trades filter nahi kar raha tha. Wo **sabse strong wali** filter
kar raha tha aur sirf darpok chhoti sweeps rakh raha tha. Aur ceiling flat hone ki wajah
se ye **high-volatility din pe zyada** hota tha — jab sweeps sabse meaningful hoti hain.

Spec 06 khud Setup B ko "best risk-reward, lowest frequency" kehta hai. v1 ke risk
engine ne usko lowest-frequency bana diya, market se koi lena-dena nahi.

**v2:** `r_max = min(60, max(35, 1.40 × ATR14_1m))` — quiet 20-ATR din pe 35, tez
40-ATR din pe 56, absolute cap 60. Space gate ratio-based hai, to bada R apne aap
proportionally bada space maangta hai.

---

## 🟡 7. ATR buffer kabhi fire hi nahi hota tha

Spec 07 v1 ne likha: *"Buffer scales with volatility."* Formula: `max(10, 0.25 × ATR)`.

| ATR14_1m | v1 buffer | kaunsa term jeeta |
|---|---|---|
| 15 | 10.0 | flat 10 |
| 25 | 10.0 | flat 10 |
| 35 | 10.0 | flat 10 |
| 40 | 10.0 | flat 10 (tie) |
| 50 | 12.5 | ATR |

ATR term tabhi jeetta hai jab ATR > 40, jo rare hai. **Yaani wo claim lagbhag 95% waqt
jhooth tha** — v1 ne flat 10-point buffer ship kiya jispe ek ATR expression sajaya hua
tha.

**v2:** `max(6, 0.45 × ATR)` → 6.8 / 11.3 / 15.8 / 22.5 unhi rows pe. Ab sach me adapt
karta hai.

---

## 🟡 8. Reconciliation check har din fail hota

v1: *"Any OHLC mismatch > 0.05 → mark the day SUSPECT."*

Live 1m candles **websocket snapshots** se banti hain — Kite index quotes lagbhag ek
per second bhejta hai, har trade nahi. Minute ka asli high/low aksar do snapshots ke
beech hota hai. Jo index ek minute me 40 point chal sakta hai, uspe 0.05 point se zyada
miss hona **normal behaviour hai**, anomaly nahi.

To v1 **har ek din SUSPECT** mark karta. Aur jo alarm hamesha bajta hai, use aadmi
ignore karna seekh jaata hai — aur yahi wo ek check hai jo baaki sabko validate karta
hai.

**v2:** threshold ATR-relative, aur judgement **mismatch rate** pe (>2% candles), kisi
ek candle pe nahi. Aur pehle **5 din sirf measure karo** — apne feed ka actual deviation
distribution nikaalo, phir uske 99th percentile se threshold set karo. Data se nikla
threshold asli check hai; round number se chuna hua theatre hai.

### Aur ek gehri problem jo v2 ne solve nahi ki, sirf expose ki

```
replay_source: "kite_historical"    ← P9 iss pe validate hoga
live_source:   "tick_built"         ← asli trading iss pe hogi
```

Ye **ek hi minute ke do alag data sources** hain. Spec 01 §1 ka design goal #1 hai
"paper result live me achievable hona chahiye". Wo goal utna hi sach hai jitna in dono
ke beech ka gap chhota hai — aur v1 ne wo gap kabhi maapa nahi.

P8 me isko explicitly maapna hai: **ek hi session pe dono se engine chalao aur decision
streams diff karo.** P&L nahi — decisions. Agar alag signals aate hain, to P9 ka number
live system describe nahi karta, aur report ke header me wo likha hona chahiye.

Ye zero nahi nikalega. Imaandaar goal hai isko **maapna, bound karna, aur likhna** —
claim karke gayab kar dena nahi.

---

# PART 3 — JO MISSING THA

## 🟢 9. Event blackout calendar

News input ka prohibition rehta hai — engine kabhi news nahi padhega. Ye **file me pehle
se likhi hui date ka lookup** hai. Koi forecast nahi, koi interpretation nahi, **koi
curve-fitting risk nahi** (RBI MPC dates poore financial year ke liye publish hoti hain).

**Kyun zaroori hai:** Bank Nifty index ka lagbhag **75% paanch stocks** me hai — HDFC
Bank, ICICI, SBI, Axis, Kotak. Unke results wale din index tumhare levels ko respect
nahi karta; wo information pe reprice hota hai, kisi level pe order flow se nahi.
Volatility ceiling isko **baad me** pakadta hai. Calendar **pehle** pakadta hai.

```
poora din band  : RBI MPC, Union Budget, off-cycle RBI action
11:15 tak band  : heavyweight bank results
10:00 tak band  : US FOMC ke agle Indian session
sirf tag        : monthly expiry, US CPI, index rebalance
```

`tagged_only` list utni hi important hai. Wo din normally trade hote hain par journal me
tag ho jaate hain, taaki weekly review unke hisaab se cut kar sake. **Kisi bhi cheez ko
bura din dekhne ke baad blackout list me mat daalna** — wo curve-fitting hai.

**Fail closed:** file missing ya 30 din purani → engine start nahi hoga.

## 🟢 10. Gap-day regime

Har carried 1m/5m level ka matlab hai "price yahan trade hui, aur kisi ne defend kiya".
Bade gap ke baad price beech ki range me trade hui hi nahi — wo levels ek aisa market
describe karte hain jo ab exist nahi karta. v1 khushi-khushi us level ka "flip retest"
detect kar leta jise price gap kar ke cross kar gayi thi.

Gap > 0.40% → saare TURN/LAUNCH/BREAK levels maaro, sirf PDH/PDL/PDC aur opening range
bachao, 10:00 tak koi entry nahi.

## 🟢 11. `r_model_broken` — ye batata hai ki galti kahan hai

`risk_rupees = r_points × ref_delta × lot_size` ek **model** hai. Asli loss me IV
movement, gamma, aur exit spread bhi hai — aur stop-out pe teeno ek saath tumhare
khilaaf jaate hain.

Agar asli loss systematically 1.3R hai jab model 1.0R kehta hai, to:
- `−2R` daily cap asal me `−2.6R` cap hai
- journal ka har `r_realised` galat hai
- P9 report kahegi "strategy fail hui" jabki **uske neeche ka arithmetic** fail hua

```python
if len(losses) >= 10 and median(abs(r) for r in recent_losses) > 1.2:
    block("r_model_broken")
```

Iske bina "strategy haari" aur "arithmetic galat tha" P&L me **bilkul ek jaise dikhte
hain.** Sahi response delta measurement theek karna hai — risk budget badha kar numbers
match karana nahi.

---

# PART 4 — SMART AUR DYNAMIC: tumne yahi poocha tha

Tumne poocha "kuch smart aur dynamic add karna ho to". Pehle ek baat — **tumhare apne
document ne warn kiya tha** ki har extra filter backtest ko sundar aur live system ko
kharab karta hai. Wo warning bilkul sahi hai, aur maine usko follow kiya hai.

Isliye maine **sirf do naye gates** add kiye — cost gate aur event blackout — aur dono
first principles se justify hote hain, kisi result ko dekh kar nahi bane. Baaki sab
**corrections aur normalisations** hain, naye filters nahi.

Asli "dynamic" upgrade ye hai:

## ⚡ 12. Har threshold ab ATR-normalised hai

**Ye sabse important structural change hai.**

Bank Nifty 2022 me ~35,000 tha, aaj Aug 2026 me ~57,700. v1 ke saare thresholds absolute
points me the — 8-pt pierce, 10-pt buffer, 12–35 R bounds, 25–120 range width, 20-pt
alert distance.

Matlab **ek 3-saal ka backtest chupke se sample ke dono siron pe alag system test kar
raha hai.** 8 point ka pierce 35,000 pe kuch aur hai, 57,700 pe kuch aur.

v2 me har threshold ka form hai:

```
effective = max(floor_points, atr_mult × ATR14_1m)
```

Floor ek **dead-market guard** hai, operating value nahi.

Aur iske liye ek test hai jo poore bug-class ko pakadta hai:

```python
def test_thresholds_are_index_level_invariant():
    """
    full_session.csv lo. Ek copy banao jisme har price +20,000 shift ho
    aur har range proportionally scale ho.
    Decision STREAM identical hona chahiye — sirf absolute prices alag.
    Agar nahi, to koi absolute threshold abhi bhi logic me chhupa hai.
    """
```

## ⚡ 13. Cross-instrument validation — sabse strong test, aur muft

Ye sabse bada leverage hai jo tumhe abhi mil sakta hai.

6 mahine × ~3 trade/week = **~70 trades.** 40% win rate pe uska 95% confidence interval
lagbhag **±12 percentage points** hai. Wo test nahi hai — wo ek number hai jise tum
kisi bhi disha me over-interpret kar loge.

**Wahi ruleset, bilkul unchanged, Nifty 50 + FinNifty + Sensex pe, 3 saal.**

- 4 instruments × 3 saal ≈ **800–1000 trades**
- Koi parameter per-instrument re-tune nahi hoga. Agar Nifty pe alag numbers chahiye,
  to wo Bank Nifty pe fitted the.
- **Ye tabhi possible hai kyunki v2 me thresholds ATR-normalised hain** — v1 ke absolute
  points doosre index level pe meaningless hain.

| Result | Matlab |
|---|---|
| Chaaron pe chala | Rules kuch asli describe kar rahe hain |
| Sirf Bank Nifty pe | Ek instrument, ek window pe fitted. Imaandaar conclusion: no edge |
| Kisi pe nahi | Saaf, sasta, jaldi jawab. **Ye achha outcome hai** — muft me pata chal gaya |

Ye **sirf validation** hai. Trading me multi-instrument scanning ka prohibition
(spec 01 §10) waisa hi rehta hai.

## ⚡ 14. Pre-registered sensitivity grid

Ek P9 run ek parameter combination pe ek number deta hai. Wo nahi batata ki result ek
**plateau** hai ya ek **spike**.

**P9 chalane se PEHLE** grid likh do, repo me commit kar do, date ke saath. Phir har
combination chalao aur **surface** dekho, peak nahi:

| Surface | Matlab |
|---|---|
| Chaudi plateau, aas-paas sab positive | Shayad asli hai. **Centre lo, peak kabhi nahi** |
| Ek spike, chaaron taraf loss | Noise. Edge nahi hai, ek lucky cell hai |
| Grid ke kinare ki taraf badhta hua | Grid galat hai, ya wo parameter hona hi nahi chahiye |

**Pre-registration hi isko curve-fitting se alag karti hai.** Results dekh kar grid
chunna, ya grid ko achhe dikhne wali disha me extend karna — wahi fitting hai, bas naye
kapde pehen kar.

## ⚡ 15. Har gate ko score do — aur zero wale delete karo

```
gate_value(g) = mean_R(taken trades) − mean_R(g ne jo reject kiye, forward replay)
```

| Reading | Action |
|---|---|
| strongly positive | rakho |
| ≈ zero | **delete karo** — sample size khaata hai, deta kuch nahi |
| negative | delete karo, aur pata karo reasoning ulti kyun thi |

≈ 0 wala gate harmless nahi hai. Wo pehle se chhote sample ko aur chhota karta hai, aur
har deleted gate ek kam parameter hai overfit karne ko. **Bias deletion ki taraf hona
chahiye.**

---

# PART 5 — REGULATORY (SEBI algo framework, April 2026 se mandatory)

Ye ek bhi trading rule nahi badalta. Ye badalta hai **code kahan chalega** aur **kya
paperwork pehle karna hoga** — aur yahi wo cheez hai jo project ko aakhri step pe atka
deti hai agar aakhri step tak chhod do.

**Zerodha se likhit me confirm karna, ye area baar-baar badla hai:**

| Requirement | Yahan kya matlab |
|---|---|
| **10 orders/second threshold** | Iske neeche registration nahi chahiye. Ye system din me kuch orders deta hai, bahut neeche hai. Design aisa karo ki burst ho hi na sake — **retry loop hi realistic tarika hai galti se ise cross karne ka** |
| **Algo ID har order pe** | API orders pe exchange-assigned tag ab optional nahi. Abhi `OptionOrder` me daal do, paper me bhi |
| **Static IP whitelisting** | Home broadband, mobile hotspot, cafe wifi — kuch kaam nahi karega. **Ek chhota cloud VM (Indian region) chahiye.** Budget me rakho |
| **OAuth only, 2FA, daily session expiry** | Token roz naya. Runner ko daily login handle karna hai aur stale token pe **loudly fail** karna hai |
| **Broker-registered strategies** | Tumhare use case ke liye compliance desk me plain-English strategy description file karni padegi ya nahi — **ye broker se seedha poochho** |

Do practical baatein:

1. **Static IP paper phase ko bhi affect karta hai**, kyunki P8 live Kite data pe
   chalta hai. Hosting P8 se pehle sort karo, live se pehle nahi.
2. **Compliance ka sawaal jaldi poochho.** Uska jawab decide karta hai ki live phase ek
   config change hai ya mahinon ka approval process. P9 ke baad ye pata chalna mehnga
   tarika hoga seekhne ka.

---

# PART 6 — AB KYA KARNA HAI, IS ORDER ME

Build order ab bhi P0 → P9 hai, par do jagah badla hai:

| Phase | v2 me kya add hua |
|---|---|
| **P2** | event guard, gap guard, **session persistence** (kill karke restart karo, limits bachni chahiye) |
| **P5** | **cost gate**, wide-spread fixture pe reject hona chahiye |
| **P6** | **backstop + watchdog** — process maaro position ke saath, broker pe SL-M resting milni chahiye |
| **P8** | **2 hafte ka bid/ask log**, aur tick-built vs historical decision-stream divergence measure |
| **P8.5** | 🆕 **cost verification.** `costs.yaml` bharo, measured spread se guesses replace karo, cost gate saare P8 signals pe dobara chalao |
| **P9** | **3 saal, 4 instruments**, same params, plus pre-registered grid |

**P8.5 sabse important naya gate hai.** Agar wahan measured cost ke saath zyadatar
signals reject ho jaayein, to **P9 pe waqt lagane se pehle ruk jaana** aur vehicle pe
sochna. P9 ek mahine ka kaam hai; P8.5 do din ka. Sasta wala pehle karo.

---

## Aur aakhri baat, imaandaari se

Ye review ne teen jagah dikhaya ki **arithmetic tumhare khilaaf ja rahi thi aur v1 ko
pata nahi tha** — round numbers ne space gate ko sikka bana diya, R ceiling ne Setup B
ko delete kar diya, aur cost ne pura expectancy equation apne haath me le liya.

Teeno tumhare *reasoning* ki galti nahi thi. Teeno **un numbers ki galti thi jo kabhi
maape nahi gaye.** Aur wo exactly wahi cheez hai jo tumne khud CLAUDE.md §8 me likhi
thi: *"Every number in params.yaml is a starting hypothesis, not a discovered truth."*

v2 ne bas kuch hypotheses ko test kar liya — kaagaz pe, arithmetic se, market data se
pehle. Baaki sab abhi bhi untested hai.

**Aur ek cheez v2 bhi nahi keh sakta: ki ye system paisa banayega.** Cost gate ne jo
dikhaya wo ye hai ki monthly ATM options pe 25-point stop ke saath margin bahut patli
hai. Ho sakta hai P8.5 ke baad jawab ho "R bada karo", ho sakta hai "vehicle badlo", ho
sakta hai "ye kaam nahi karega". Teeno jawab valid hain, aur teesra bhi ek **achha**
outcome hai agar wo sasta mila.

Chhoti size. Measure pehle, believe baad me.

---

*Ye ek rules framework ka review hai, financial advice nahi. Main financial advisor
nahi hu. Automated trading manual se tez paisa kha sakti hai. Sirf utna risk lena jitna
kho sakte ho.*

---

## Sources

- [NSE to discontinue weekly index derivatives for Bank Nifty](https://newsonair.gov.in/nse-to-discontinue-weekly-index-derivatives-for-bank-nifty-nifty-midcap-select-nifty-financial-services)
- [NSE to discontinue Nifty Bank weekly index derivatives, keeps Nifty 50](https://www.benzinga.com/markets/equities/24/10/41285131/nse-to-discontinue-nifty-bank-weekly-index-derivatives-keeps-nifty-50)
- [Bank Nifty Expiry 2026: Monthly & Quarterly Expiry on Tuesday](https://hdfcsky.com/blogs/share-market/bank-nifty-expiry)
- [NSE Revises Lot Sizes for Nifty, Bank Nifty from Jan 2026](https://hdfcsky.com/news/nse-revises-market-lot-sizes-for-major-index-derivatives-effective-january-2026)
- [NSE circular — index derivatives lot size revision](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf)
- [SEBI Extends Retail Algo Trading Deadline to April 2026](https://www.outlookbusiness.com/markets/sebi-extends-deadline-to-implement-retail-algo-trading-by-april-2026)
- [SEBI Algo Trading Rules 2026: What Retail Traders Must Know](https://www.sahi.com/blogs/sebi-algo-trading-rules-2026-what-every-retail-trader-must-know-before-april)
- [Process for registration of algos — Kite Connect forum](https://kite.trade/forum/discussion/15194/process-for-registration-of-algos)
