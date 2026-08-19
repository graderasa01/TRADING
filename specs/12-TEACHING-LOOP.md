# 12 — THE TEACHING LOOP

> Trader chart dekhta hai, kehta hai *"yahan ek line honi chahiye thi, aur ye wajah
> hai"* — aur engine us wajah ko arithmetic me badal leta hai.
>
> **Ye P1 ke turant baad aata hai, poore build se pehle.** Ek uncalibrated level engine
> ke upar P2–P9 banana, reyt par ghar banana hai.

---

## 1. Ye kyun sabse pehle hona chahiye

Har detection threshold — swing lookback 3, wick cluster 5 points, launch impulse
2.0 × ATR, departure speed 1.0 — **kabhi kisi chart se nahi milaya gaya.** Sab reasoned
hain, measured nahi.

Aur agar level engine galat hai, to **neeche kuch bhi sahi nahi ho sakta.** Ek perfect
risk engine, jo ek perfect setup ko galat level par size kar raha hai, paisa khone ka
perfect tareeka hai.

Spec 09 §3.2b ka overlap test overlap ka **percentage** deta hai. Ye spec us percentage
ka **kaaran** pakadta hai — aur kaaran hi wo cheez hai jo code ban sakti hai. 62%
overlap ek number hai. *"Ye line isliye honi chahiye thi ki do chup candles ke baad ek
badi candle nikli"* — ye ek rule hai.

---

## 2. Loop

```
1  RENDER     engine ki lines chart par           → prototype/chart.py
2  ANNOTATE   trader batata hai kya galat tha     → annotations.yaml
3  MEASURE    engine us jagah ka arithmetic nikalta hai
4  DIAGNOSE   kaunsa maujooda detector kareeb tha, kitne se chooka
5  PROPOSE    threshold change (pehli pasand) ya naya detector (aakhri)
6  REGRESS    saari purani annotations par test — kuch toota to nahi
7  COMMIT     ya discard. Dono soorat me DECISIONS.md me likho
```

---

## 3. ⚠ Teen cheezein jo idea me nahi thi — aur inke bina ye ulta kaam karega

### 3.1 Galat lines bhi mark karni hongi. Ye sabse zaroori addition hai.

Sochne ka natural tareeka hai: *"ye line honi chahiye thi."* Agar sirf yahi mark hoga,
to **har session engine ko zyada lines banane ki taraf dhakelega.** Aur:

```
zyada levels → zyada ALERT → zyada setups → zyada trades
```

— theek wahi failure jise `CLAUDE.md` aur spec 05 rokne ke liye bane hain. Dry run me
ek din me 36 TURN levels bane the aur 8-cap unse bhar gaya tha. Us system ko **aur**
lines nahi chahiye; use **behtar** lines chahiye.

To annotation me teen buckets hain, aur teeno bharne hain:

| Bucket | Kya | Kya theek karta hai |
|---|---|---|
| `missed` | line honi chahiye thi, engine ne nahi khinchi | recall |
| `false_positive` | engine ne khinchi, honi nahi chahiye thi | **precision** |
| `confirmed_good` | engine ne sahi pakda | regression protection |

**Ek annotation jisme `false_positive` khaali hai, wo calibration nahi hai — wo
inflation hai.** Har session me kam se kam utni hi galat lines mark karo jitni missing.
Agar sach me koi galat nahi lagti, to likh do ki dekha aur koi nahi mili — par dekhna
zaroori hai.

`confirmed_good` regression test hai. Jab Claude Code koi rule badle, ye levels bache
rehne chahiye. Iske bina har fix chupchap kuch aur tod dega.

### 3.2 Engine ko tumse ASAHMAT hone ka haq hona chahiye

Ye doosri badi baat hai.

Tum likhoge *"price yahan 4 baar rejected hui."* Engine data se ginega — aur ho sakta
hai jawab **2** ho. Ya tum kahoge *"lambi wick thi"* aur wick candle ki range ka 38%
nikle, 55% nahi.

**Us soorat me engine ko tumhe wapas batana hai, chup nahi rehna.**

```
ANNOTATION #3 — 57,698, "price 4 baar ruki"
  measured : zone me 2 alag entries (separation rule ke hisaab se)
             candles 71, 78. Beech ke touches separated nahi the.
  ⚠ tumhari wajah ka number data se match nahi karta.
    Kya (a) tolerance zyada chaudi honi chahiye, (b) touch ki definition galat
    hai, ya (c) is level ki asli wajah kuch aur thi?
```

Iske bina tool sirf **tumhari galtiyon ko code me likh dega, extra steps ke saath.**
Har trader ke paas aise patterns hote hain jinpe wo yakeen karta hai aur jo data me
nahi hain — sabke paas hote hain. Ye loop unhe pakadne ka sabse sasta mauka hai, aur wo
mauka sirf tab milta hai jab engine "nahi" keh sakta ho.

**Ye ek feature hai, bug nahi.** Agar Claude Code har annotation ko maan leta hai, to wo
tumhari raay ko automate kar raha hai — market ko nahi.

### 3.3 Sessions blind chunni hongi

Agar tum khud din chunoge, to **yaad rehne wale** din chunoge — jinme kuch bada hua.
Wahi survivorship bias hai jo backtest ko sundar aur live ko kharab banata hai.

```
sessions ko RANDOMLY sample karo, regime ke hisaab se stratified:
  4 trending · 4 ranging · 2 gap · 1 expiry · 1 high-vol   = 12 sessions
annotate karne se PEHLE list fix karo aur commit karo
```

Aur wahi split-discipline jo spec 11 me hai:

```
teach     8 sessions   — annotate karo, rules banao
holdout   4 sessions   — kabhi annotate mat karo. Calibration ke baad
                         inpe overlap naapo. Agar teach par 80% aur holdout
                         par 50%, to tumne calibrate nahi, memorise kiya
```

---

## 4. Annotation format

`prototype/annotations.example.yaml` dekho. Sabse zaroori field:

```yaml
measurable: |
  Do lagataar candles jinki range < 0.3 x ATR thi, turant baad ek candle
  jiski range > 2.5 x ATR.
```

**Ye field hi tumhari aankh aur code ke beech ka pul hai.** `why` insaani hai —
"price ruki phir bhaagi." `measurable` wahi baat numbers me hai.

Aur ek baat: **agar `measurable` nahi bhar paate, to wo apne aap me jaankari hai.**
Do matlab ho sakte hain:

1. Rule asli hai par tumne kabhi shabdon me nahi rakha → Claude Code candles se nikalne
   ki koshish karega (§5)
2. Ye rule nahi, **yaad** hai — tumhe wo move yaad hai aur ab lagta hai ki level dikh
   raha tha

Dusra bahut aam hai aur sharm ki baat nahi. Isliye field optional hai, par khaali
chhodne par annotation `confidence: low` ho jaata hai aur jab tak do aur sessions me
wahi pattern na dikhe, uspe rule nahi banega.

---

## 5. Claude Code ek annotation ke saath kya kare — exact algorithm

```
INPUT: ek annotation (price, candle range, why, measurable)

1. MEASURE — us jagah ka poora arithmetic nikalo, chahe measurable bhara ho ya nahi.
   Har baar wahi ~30 measurements, taaki annotations ke beech tulna ho sake:

     candle ranges  : t-10 se t+5 tak, aur ATR20 se ratio
     wick ratios    : upper aur lower, har candle ki range ke share me
     close position : har candle ka close_third
     time at price  : kitni candles ne is price ko touch kiya, separation ke saath
     departure      : is price se 3/5/10 candle baad price kitni door thi ÷ ATR
     approach       : price yahan tak kaise aayi — tezi se ya reng kar
     HTF context    : ye price kisi 5m/15m swing ke kitne paas hai
     prior touches  : session me pehle kitni baar
     compression    : (last 3 candles ki range) ÷ (pichhli 10 ki range)

2. NEAR-MISS — poochho kaunsa maujooda detector KAREEB tha aur kitne se chooka:

     "LAUNCH detector 0.15 x ATR se chooka — base ki combined range
      0.95 x ATR thi, threshold 0.8 hai"

   **Ye sabse valuable output hai.** "0.15 se chooka" ka matlab hai threshold
   thoda galat hai. "Koi detector kareeb nahi tha" ka matlab hai sach me kuch
   naya chahiye — aur wo bahut kam hona chahiye.

3. CROSS-CHECK — trader ki `measurable` ko step 1 ke numbers se milao.
   Match nahi karta? **Bata do (§3.2). Aage mat badho.**

4. PROPOSE — is order me, hamesha:
     (a) maujooda threshold badlo          ← sabse pehli pasand
     (b) maujooda detector me clause jodo
     (c) naya detector                     ← sirf jab (a) aur (b) na chalein

   Har proposal ke saath:
     - exact arithmetic, jaise params.yaml me likha jayega
     - mechanism — market aisa KYUN karta hai (spec 11 §D2)
     - reachability check — spec 10 §3.3, kyunki do theek-lagne wale
       parameters milkar ek gate ko namumkin bana sakte hain

5. REGRESS — poore annotation set par chalao:
     missed          → kitne ab pakde gaye?
     false_positive  → kitne ab bhi ban rahe hain? Naye to nahi bane?
     confirmed_good  → sab abhi bhi zinda hain? Ek bhi toota to proposal REJECT
     poora session   → levels/day, ALERT %, detections/day — pehle vs baad

6. REPORT — fayda aur keemat saath me, hamesha:

     PROPOSAL: launch_base_atr_mult 0.8 → 1.0
       BENEFIT  missed pakde        +3 of 7
                overlap             62% → 79%
       COST     levels/day          41 → 46
                ALERT share         19% → 22%
                false_positives     2 naye
                confirmed_good      12/12 zinda
       MECHANISM  base ko utna chup hona zaroori nahi jitna hum maan rahe the;
                  maayne ye rakhta hai ki price WAHAN RUKI, na ki kitni shaant thi
       VERDICT   accept — recall bada, precision par asar mamooli
```

---

## 6. Kab rukna hai

Loop ka ant hona chahiye, warna ye ek shauk ban jaata hai jo dhire-dhire overfit karta
hai.

**Ruk jao jab:**

- **Do lagataar sessions me koi naya rule na nikle.** Level engine calibrate ho gaya
- Rules 4 se zyada badh gaye hon (spec 11 §7 ka wahi budget)
- Precision shuruaati value se neeche gir jaye
- Naye missed annotations pehle wale annotations ke `false_positive` se takrane lagein
  — matlab tum ab shor calibrate kar rahe ho

**Phir, sirf ek baar, holdout ke 4 sessions par overlap naapo.** Teach par 80% aur
holdout par 50% ka matlab hai memorisation. Sahi jawab hai shuruaati thresholds par
wapas jaana — holdout ko naya validate set banakar loop dobara chalana nahi.

---

## 7. Build order — ye P1.5 hai

```
P0    data + feed + aggregator
P1    level engine + structure + board
P1.5  ◀── TEACHING LOOP. Yahan ruko. Level engine calibrate karo.
P2    guards + modes + health monitor
...
```

**Ye order ka faisla jaan-boojh kar hai.** P1.5 ko baad me karna — maan lo P7 ke baad —
matlab paanch phases ek aise level engine ke upar bane hain jo shayad galat hai, aur
uske baad ki har calibration un paanch phases ke through regress karni padegi.

P1.5 ko **kam se kam 8 annotated sessions** chahiye, aur wo trader se aate hain. Ye ek
insaani bottleneck hai — shayad ek hafta. **Wo hafta lagao.** Uske bina P2–P9 ek aise
foundation par bane hain jise kabhi kisi ne chart se nahi milaya.

---

## 8. Tools

```bash
python3 prototype/chart.py 20 110      # candles 20-110 ka annotation chart
                                       # → chart.html, browser me kholo
cp prototype/annotations.example.yaml annotations/2026-08-11.yaml
                                       # bharo: missed, false_positive, confirmed_good
```

Chart me har candle ka index likha hai, taaki annotation me exact jagah batayi ja sake.
Grade A solid line hai, B dashed, C dotted — to ye bhi dikhta hai ki engine kisko
tradeable maan raha hai, sirf ye nahi ki usne kya dhoonda.

**Aur GUI ki koshish mat karna.** HTML chart + YAML file wala loop aaj kaam karta hai
aur seekhne ke liye poora kaafi hai. Ek click-to-mark interface achha lagega aur ek
bhi extra rule nahi dega.

---

## 9. Tests

| Test | Expectation |
|---|---|
| `test_annotation_schema_validates` | Missing `why` → reject; missing `measurable` → accept with `confidence: low` |
| `test_false_positive_bucket_required` | `false_positive` key hi nahi → warning, aur session incomplete mark |
| `test_confirmed_good_is_regression` | Koi bhi rule change jo `confirmed_good` level ko maar de → proposal reject |
| `test_measurement_battery_is_fixed` | Har annotation par wahi ~30 measurements, taaki tulna ho sake |
| `test_engine_can_disagree` | Annotation kahe "4 touches", data kahe 2 → conflict report bane |
| `test_holdout_never_annotated` | Holdout sessions ki koi annotation file nahi ho sakti |
| `test_proposal_includes_cost` | Bina precision impact ke koi proposal accept nahi |
| `test_threshold_change_preferred` | Naya detector tabhi jab koi threshold change kaam na kare |

---

*Is loop ka kaam engine ko har line khinchwana nahi hai. Wo engine jo har line khinchta
hai, wo har jagah trade karta hai. Iska kaam hai tumhari aankh ka jo hissa arithmetic
me badal sakta hai use nikal lena — aur imaandaari se batana ki kaunsa hissa nahi badal
sakta.*
