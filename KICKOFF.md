# KICKOFF — Claude Code ke liye pehla kaam

> Ye file Claude Code ko ye batati hai ki **shuru kahan se karna hai aur kis order me.**
> Build ke rules `BUILD-BRIEF.md` me hain. Ye sirf pehle teen din ka plan hai.

---

## 0. Pehle ye padho, isi order me

1. `CLAUDE.md` — constitution
2. `BUILD-BRIEF.md` — working agreement, aur §4 jahan spec chup hai
3. `prototype/FINDINGS.md` — **6 bugs jo engine chalane se mile.** Char ne system ko
   trade karne hi nahi diya. Inme se koi bhi spec padh kar nahi milta
4. `REVIEW-v2.md` — v1 me kya toota tha aur kyun
5. `specs/10-SELF-DIAGNOSTICS.md` — engine ko apni kharabi khud pakadni hai
6. `specs/12-TEACHING-LOOP.md` aur `specs/13-CANDLE-DIALOGUE.md` — **ye P1.5 hai,
   aur ye poore project ki sabse zaroori calibration hai.** Inhe padh lo taaki P1
   banate waqt pata ho ki uska output kis shakl me chahiye
7. `specs/11-LEARNING-LOOP.md` — baad me chalega, par uski disciplines har jagah lagti hain

`prototype/` me ek chalta hua reference implementation hai. Wo production code nahi hai
— koi Decimal nahi, koi test nahi, exits nahi. Par wo **sabit karta hai ki har rule
asal me kya karta hai**, aur wahi char bugs dobara mat banana.

---

## 1. ⚠ SABSE PEHLE: DATA. Engine ka ek line bhi baad me.

Bina data ke kuch bhi validate nahi ho sakta, aur har phase ka gate data maangta hai.

### Kya chahiye (user ko dena hai, Claude Code ise bana nahi sakta)

```bash
export KITE_API_KEY=...
export KITE_API_SECRET=...
```

- **Kite Connect subscription** — ₹500/month per API key. **Historical data ab isi me
  free hai** (Feb 2025 se alag charge hata diya gaya). Pehle ₹2,000 alag lagte the —
  wo purani jaankari hai
- Access token roz naya banta hai. Login flow handle karna padega
- **Credentials sirf environment variables se. Repo me, config me, ya log me kabhi
  nahi.** P0 me ek pre-commit secret scan lagao

### Task 1 — `tools/fetch_kite.py`

```
Instruments (instrument master se token resolve karo, hardcode mat karo):
  NIFTY BANK      ← primary
  NIFTY 50        ← cross-instrument validation ke liye (spec 09)
  NIFTY FIN SERVICE
  SENSEX          (agar accessible ho)

Interval : "minute"
Range    : jitna mile — 3 saal target, kam se kam 12 mahine
Output   : data/{SYMBOL}/{YYYY-MM}.parquet   (CSV bhi chalega)
```

**Ye limits dhyaan me rakho:**

| Cheez | Value |
|---|---|
| Minute data, ek request me | **max 60 din** — loop lagana padega |
| Rate limit | official docs se confirm karo, saare REST calls ek throttled client ke peeche |
| Depth | 1m ke liye 3+ saal available hai; jitna mile utna lo |

Requirements:

- **Resume on failure.** 3 saal × 4 instruments = sau se zyada requests. Beech me toota
  to shuru se mat karo — ek manifest rakho jo bataye kaun se mahine ho gaye
- **Backoff** rate limit par, aur har request ko log karo
- **Manifest** — `data/manifest.json`: har file, uski date range, candle count, download
  timestamp, aur SHA

### Task 2 — `tools/verify_data.py` — download se zyada zaroori

Downloaded data par chalao aur report likho. **Ye kiye bina P0 shuru mat karna.**

```
har trading day ke liye:
  candle count           expect 375 (09:15–15:30). Kam hai to kitne missing?
  session boundaries     pehli candle 09:15, aakhri 15:29
  gaps                   lagataar missing minutes — kitne, kahan
  duplicates             ek hi timestamp do baar
  OHLC sanity            l <= o,c <= h ; koi zero/negative range?
  holidays               NSE holiday list se cross-check — missing din chhutti thi?
  price continuity       previous close se gap % — 2%+ wale din flag karo

poore dataset ke liye:
  trading days count, coverage %
  1m range distribution  → ATR ki asli range dekho
  ATR14 distribution     → params.yaml ke atr_min 12 / atr_max 60 sach me sahi hain?
```

**Wo aakhri line sabse important hai.** `params.yaml` ke saare vol thresholds *andaaze*
hain. Asli data mil gaya hai to unhe **naapo**, aur `atr_min_percentile` /
`atr_max_percentile` bharo. Ye pehla parameter hai jo hypothesis se measurement banega.

### Task 3 — user ko report karo, phir ruko

`data/DATA-REPORT.md` likho aur **P0 shuru karne se pehle ruko.** Batao:

- kitne mahine mile, har instrument ke
- coverage % aur gaps kahan hain
- asli ATR distribution vs `params.yaml` ke andaaze
- kya P9 (3 saal × 4 instruments) is data se possible hai

Agar 12 mahine se kam mila, ye **bata do** — P9 ka plan badalna padega.

---

## 2. Data ke baad: reachability, phir engine

### Task 4 — `python3 prototype/reachability.py` chalao

Ye pehle se likha hua hai aur abhi **12/12 pass** hai, plus teen config values jo user
ko bharni hain. Isko `src/health/reachability.py` me le jao aur startup se jodo.

**Kisi bhi assertion ke fail hone par engine start nahi karega.** Ye char me se teen
dry-run bugs ek bhi candle process kiye bina pakad leta.

### Task 5 — P0 shuru karo, `BUILD-BRIEF.md` §2 ke hisaab se

Aur ye niyam har phase par:

```
har phase ke ANT me:
  1. us phase ka gate chalao (BUILD-BRIEF §2)
  2. ek pura din replay karo aur DETECTION COUNTS chhapo (BUILD-BRIEF §4b)
  3. PROGRESS.md likho
  4. RUKO. user ko batao. agla phase apne aap shuru mat karo.
```

---

## 3. Teen niyam jo sab par lagte hain

### 3.1 Jahan spec chup hai, wahan DECISIONS.md

`BUILD-BRIEF.md` §4 me gyarah decisions pehle se likhi hain (D-001 se D-011d). Naya
silent guess mila to usse waise hi document karo, **code likhne se pehle.**

### 3.2 Trade nahi, DETECTION gino

P3 se aage har phase par ye block chhapo:

```
levels born ............ > 20
Grade A tak pahunche ... > 0     ← Bug 1 yahan tha
ALERT candles .......... > 0     ← Bug 3 yahan tha
setups DETECTED ........ > 0     ← ye number sabse zaroori hai
signals ................ 0 bhi chalega
```

**Signals zero ho sakte hain. Detections zero nahi ho sakte.** Zero detection ka matlab
market engine ke faisla-karne wale hisse tak pahunchi hi nahi — aur uske upar kuch
banane ka koi fayda nahi.

### 3.3 Kabhi nahi

`CLAUDE.md` §6 padho. Sabse zaroori: **`src/broker/live.py` nahi banega.** Ye stage paper
hai. Beech me kaha jaye to mana karo aur is line par ungli rakho.

---

## 4. Pehle teen din ka plan

| Din | Kaam | Kab poora |
|---|---|---|
| 1 | `fetch_kite.py`, ek mahina test karke, phir poora download chalu | manifest bana, download chal raha hai |
| 2 | `verify_data.py` + `DATA-REPORT.md` + ATR distribution | report ready, **user ko dikha kar ruko** |
| 3 | reachability wire karo, P0 shuru — config loader, models, ReplayFeed, Aggregator | `test_no_lookahead_by_truncation` green |
| 4-5 | P1 — level engine (1m/5m/15m), dormant pool, structure, journey, board | overlap test ≥60% |
| 6+ | **P1.5 — teaching loop.** Yahan user ka waqt lagega, tumhara nahi | 12 sessions annotated, holdout verified |

**Din 2 par rukna zaroori hai.** Data report decide karti hai ki P9 ka plan bachta hai
ya badalna padega, aur wo faisla P0 se pehle lena hai.

**Aur P1.5 par lamba rukna padega — wo normal hai.** Us phase ka kaam trader ka hai,
tumhara nahi. Tum tools banao (chart renderer, reasoning record, annotation pipeline,
regression harness) aur phir **ruk jao.** 12 sessions annotate hone me ek hafta lag
sakta hai. P2 tab tak shuru mat karna. Agar rukna asehaj lage, `prototype/FINDINGS.md`
dobara padh lo — wahan ek engine hai jo poori tarah bana hua tha aur kabhi trade nahi
karta tha.

---

## 5. User se kya maangna hai, aur kab

| Kab | Kya | Kyun |
|---|---|---|
| abhi | `KITE_API_KEY`, `KITE_API_SECRET` | data ke bina kuch nahi |
| abhi | `session.risk_per_trade_rupees` | jaan-boojh kar `null` hai — user ka conscious faisla |
| P5 se pehle | `config/costs.yaml` broker ki current charge list se, `last_verified` ke saath | engine bina iske start nahi hoga |
| P2 se pehle | `config/events.yaml` — RBI MPC + 5 heavyweight bank results + Budget | engine bina iske start nahi hoga |
| **P1 ke shuru me** | **user ke apne 10 charts, unke apne levels marked** | P1 ka gate. **User ko engine ka output dekhne se PEHLE mark karna hai** — ulta hua to test agreement nahi, agreeableness naapega |
| **P1.5** | **12 annotated sessions** (spec 12) — 8 teach + 4 holdout, randomly sampled aur regime ke hisaab se stratified | Level engine ki calibration. User ko teeno bucket bharne hain: `missed`, `false_positive`, `confirmed_good`. **Sirf `missed` bharna calibration nahi, inflation hai** |
| P8 se pehle | static IP wala host (cloud VM) | SEBI ke April 2026 rules ke tehat API access ke liye zaroori |

Ye maangte waqt saaf batao ki kyun chahiye aur kya ruka hua hai.

---

## 6. Sabse bada khatra — jaan-boojh kar aakhir me likha hai

Sabse zyada mumkin failure ye nahi hai ki Claude Code kharab code likhe. Ye hai ki wo
**P0 se P7 tak sab kuch achhe se bana de, tests green hon, report sundar ho — aur engine
kabhi trade hi na kare**, aur kisi ko char mahine tak pata na chale.

Dry run me theek yahi hua tha. Char alag bugs, sabhi ek dusre ke saath interaction me,
aur engine ne kabhi shikayat nahi ki — har candle par ek saaf, confident `NO_TRADE`.
Report me zero trades dikhte aur jawab lagta *"shaant market, system disciplined hai."*

Isliye:

- **P1 ka overlap gate skip mat karna** (spec 09 §3.2b)
- **P3 se aage har phase par detection counts chhapna**
- **Reachability assertions har startup par chalana**

Ye teen cheezein us failure mode ke against poora bachaav hain. Baaki sab uske baad
aata hai.

---

*Ye system paisa kho sakta hai. Dhyaan se banao, imaandaari se test karo, chhoti size
rakho. `prototype/FINDINGS.md` ka har number is repo par asli code chala kar nikla hai.*
