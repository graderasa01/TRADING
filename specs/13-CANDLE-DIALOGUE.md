# 13 — CANDLE DIALOGUE

> Kisi bhi candle, group ya swing par ungli rakho aur poocho: **"tum yahan kya soch
> rahe the?"** — aur engine poora jawab de, apne andhe spots samet.
>
> Spec 12 poore session par raay leta hai. Ye ek candle par baat-cheet karta hai.

---

## 1. Ye kyun chahiye

Spec 12 me trader chart dekh kar batata hai ki kaunsi line honi chahiye thi. Par uske
liye trader ko **pehle se pata hona chahiye** ki kya missing tha.

Aksar baat ulti hoti hai: *"is candle par main kuch note karta. Tumne kiya?"*

Us sawaal ka jawab dene ke liye engine ko har candle par apni soch **likhni** padegi —
sirf natija nahi (`mode=WATCH`), balki **observations** jinse wo natija nikla. Wo sab
waise bhi compute ho raha hai. Bas kabhi likha nahi gaya.

Aur ek hissa aisa hai jo aaj kahin nahi likha jaata, aur wahi sabse kimti hai:
**"main ye dekh hi nahi sakta."**

---

## 2. Har candle ka reasoning record

Har closed candle par paanch hisse. Sab pehle se compute ho rahe hain.

```
CANDLE 76 · 10:31   O 57,650.4  H 57,653.8  L 57,648.4  C 57,648.8

── MAINE KYA DEKHA ────────────────────────────────────────────
   range        5.4 pts = 0.21x ATR20 (26.0)
   pichhli 6    [22.4, 6.4, 18.4, 5.2, 5.3, 7.0]
   body 2.0  upper wick 3.4 (49%)  lower wick 1.6 (22%)
   close        bottom third (position 0.22)
   time-at-price  pichhli 11 me se 5 candles ne is price ko touch kiya
   compression  last3 avg 5.9 ÷ prior10 avg 27.8 = 0.21

── BOARD ME KYA BADLA ─────────────────────────────────────────
   kuch nahi. Board waisa hi hai.

── MERA DHYAAN KAHAN THA ──────────────────────────────────────
    57,646.7  BREAK   grade C  touches 1  —   1.7 pts  (Grade A nahi, ignore)
    57,658.2  TURN    grade A  touches 1  —   9.8 pts  ← ALERT range me
    57,676.3  ANCHOR  grade A  touches 0  —  27.9 pts  ← ALERT range me
   alert_distance 35 pts   →   MODE: ALERT   gate: no_setup

── AGLI CANDLE PAR MERI UMEED ─────────────────────────────────
   AGAR body close 57,647 ke upar  → BREAK flip, agla obstacle upar
   AGAR body close 57,647 ke neeche → wo resistance ban jaayega

── MAIN YE DEKH HI NAHI SAKTA ─────────────────────────────────
   compression ban rahi hai (ratio 0.21) — mera koi coil detector nahi hai
   5 candles ek hi price par ruki — main sirf swing aur wick cluster
   dhoondhta hu, 'time at price' nahi
```

**Agli candle 69 points ki nikli.** Engine ne ek candle pehle likh diya tha ki wahan
kuch ho raha hai aur uske paas uska rule nahi hai.

### 2.1 "Main ye dekh hi nahi sakta" — is spec ka dil

Baaki char hisse batate hain ki engine ne kya socha. Ye batata hai ki **wo kya soch hi
nahi sakta.**

Har candle par, engine kuch aise sawaal poochta hai jinke jawab wo compute kar sakta
hai par **jinpe uska koi rule nahi hai**:

| Observation | Honest admission |
|---|---|
| compression ratio < 0.5 | "coil ban rahi hai — mera koi coil detector nahi" |
| 4+ candles ek price par | "main swing aur wick cluster dhoondhta hu, time-at-price nahi" |
| koi level paas nahi | "main sirf levels ke paas jaagta hu, momentum nahi dekhta" |
| round number bilkul paas | "maine unhe weak kar diya hai — REVIEW-v2 §5" |
| volume spike (agar data ho) | "mere paas koi volume rule nahi hai" |

Ye list `params.yaml` se banti hai, hard-code nahi hoti: **jo cheez measure ho rahi hai
par kisi detector me use nahi hoti, wo apne aap yahan aa jaati hai.** Naya detector
banao, wo line list se apne aap hat jaayegi.

Ek trading system ke liye jiska sahi jawab zyadatar "kuch nahi" hota hai, *"maine kuch
nahi dekha"* aur *"main dekh nahi sakta"* — ye do bilkul alag baatein hain. Aaj tak
dono ek jaisi dikhti thi.

---

## 3. Swings — inpe alag se soch chahiye

Trader alag se swings ke baare me poochta hai, aur theek poochta hai. Aaj jab swing
confirm hota hai to engine ek TURN level bana deta hai aur aage badh jaata hai. Wo
swing ke baare me **koi umeed nahi banata.**

Har confirmed swing par ye likho:

```
SWING HIGH confirmed · candle 82 · 57,714.4   (3 bars right, confirmed at 85)

   sequence     pichhle 3 swing highs: 57,676 · 57,658 · 57,714  → HH
                pichhle 3 swing lows : 57,591 · 57,624 · 57,646  → HL
                → 5m trend: UP
   is swing ka  departure_speed 1.8x ATR  → grade A ban sakta hai
   ye kya hai   ek TURN resistance. Untested.
   agar price wapas aayi
                Setup B (sweep) yahan permitted hai — Grade A hai
                Setup A permitted nahi — ye axis nahi hai
   agar toota   BREAK axis banega, Journey shuru hogi:
                D1 57,840 (PDH)  D2 — koi launch origin upar nahi
   MAIN YE NAHI DEKH RAHA
                is swing tak price kaise pahunchi (approach speed)
                iske aur pichhle swing ke beech kitna waqt laga
```

Aakhri hissa phir wahi kaam kar raha hai: swing ke baare me jo cheezein *measurable*
hain par kisi rule me nahi hain, unhe saaf batana.

---

## 4. Dialogue protocol

```bash
python3 prototype/ask.py 77            # ek candle
python3 prototype/ask.py 75 82         # ek group
python3 prototype/ask.py swing 57720   # swing ke aas-paas
```

Trader apni baat isi shakl me likhta hai:

```yaml
- ref: "candle 74-76"
  i_would_have: |
    Yahan main note kar leta ki teen candle se ranges gir rahi hain aur price
    57,648 ke aas-paas atki hai. Coil ban rahi hai. Main 1m chart khol leta aur
    dono taraf ka plan bana leta — kyunki nikalegi to tez nikalegi.
  question: |
    Tumne is compression ko notice kiya? Aur agar kiya, to kuch kiya kyun nahi?
```

Engine ka jawab **teen hisson me hona chahiye, isi order me**:

1. **Numbers** — jo maine measure kiya (§2 ka record)
2. **Sahmati ya asahmati** — trader ki baat data se milti hai ya nahi
3. **Kya kiya ja sakta hai** — aur uski keemat

```
1. MEASURED
   candles 74-76 ranges: 5.2, 5.3, 7.0  (ATR20 = 26.0)
   compression ratio 0.21 — poore session ka sabse kam
   price 57,648 ke 6 pts ke andar 5 candles se

2. AGREEMENT
   ✓ Tumhari baat data se puri tarah milti hai. Ye session ki sabse tight
     compression thi, aur agli candle 2.65x ATR ki nikli.

3. WHAT COULD CHANGE
   Sabse kareeb maujooda detector: LAUNCH.
   Wo isko candle 77 ke BAAD pakadta — impulse dekh kar, base peeche
   dhoondh kar. Yaani level banta hai, par 4 candle DER se (3 confirmation
   bars + 1). Tum usse PEHLE tayyar ho jaate.

   Option A (threshold): kuch nahi. LAUNCH ko impulse chahiye hi chahiye —
            wo uski definition hai.
   Option B (naya):      compression detector — 3+ candles with range
            < 0.35x ATR aur combined < 1.0x ATR → ek WATCH zone, level nahi.
            Sirf ALERT trigger kare, setup nahi.
   COST     poore session par: aisi 11 compressions hain. 3 ke baad move aayi.
            ALERT share 19% → 28%. Precision 31% → 19%.
   MECHANISM  compression = participants disagree karna band kar dete hain;
            pehla disagreement price ko hilata hai. Ye asli hai.
   VERDICT  mechanism theek hai, par 3/11 hit rate par ye ALERT ko 9pp badha
            dega. Main isko LEVEL banane ke bajay sirf 'watch flag' banane ka
            suggestion dunga — jo journal me jaaye aur kuch gate na kare.
            Do mahine baad naapo ki 11 me se kitni chali.
```

Dhyaan do jawab ne **poori tarah maan nahi liya.** Usne mechanism accept kiya, keemat
naapi, aur ek chhota version suggest kiya. Wahi sahi behaviour hai.

---

## 5. ⚠ Dialogue ka apna khatra — conversational drift

Spec 11 aur 12 me overfitting ka khatra hai. Yahan ek naya, tez khatra hai.

**Baat-cheet me sehmat hona bahut aasan hai.** Trader kehta hai *"yahan ye bhi dekhna
tha"* — aur assistant ka default behaviour hai helpful banna, matlab kuch produce
karna. Bees candles ki baat-cheet = bees naye rules, har ek us waqt bilkul sahi lagta
hua.

Ye spec 12 ke annotation se **zyada** khatarnak hai, kyunki annotation likhne me mehnat
lagti hai aur baat-cheet me nahi. Ghisaav kam, isliye bahaav zyada.

**Do niyam, dono zaroori:**

### 5.1 Baat-cheet rules DHOONDHTI hai. Accept nahi karti.

```
DIALOGUE ka output = candidates ki list
                     → annotations/candidates/ me jaati hai
                     → spec 12 ke pipeline se guzarti hai
                     → measure, cost, regression, tabhi accept
```

**Baat-cheet me kabhi `params.yaml` mat badalna.** Kabhi bhi. Ek session me chaahe wo
kitna hi obvious lage. Candidate likho, session khatam karo, phir thande dimaag se
poori annotation pipeline chalao.

### 5.2 Ek session me 3 candidate, bas

Teen se zyada nikal rahe hain to tum rules nahi dhoondh rahe — tum ek din ko dobara
jee rahe ho. Session band karo.

**Aur engine ko ye kehne ka haq hai:** *"is candle par kuch nahi tha. Tumhe wo move
yaad hai, isliye ab yahan structure dikh raha hai. Numbers me kuch khaas nahi."*

Ye jawab dene ki ijazat **saaf likhi honi chahiye**, warna kabhi nahi aayega.

---

## 6. Engine kya nahi kar sakta — imaandaari se

**Kar sakta hai:** har candle ka poora arithmetic likhna, apne andhe spots batana, ye
batana ki kaunsa detector kitne se chooka, aur ek badlav ki keemat naapna.

**Nahi kar sakta:** ye jaanna ki jo pattern tumne dikhaya wo market ka mechanism hai ya
tumhare sample ka ittefaq. Wo sirf held-out data bata sakta hai (spec 11 §D1, spec 12
§3.3).

To baat-cheet ka kaam hai **tumhari soch ko measurable shakl dena.** Ye faisla ki wo
soch sach hai ya nahi — wo baat-cheet ka kaam nahi hai, aur kabhi nahi hoga.

---

## 7. Tests

| Test | Expectation |
|---|---|
| `test_thought_record_every_candle` | Har candle ka record, `NoOp` candles ka bhi |
| `test_blind_spots_derived_not_hardcoded` | Naya detector add karne par uski line list se hat jaaye |
| `test_swing_expectation_on_confirm` | Har confirmed swing par expectation record bane |
| `test_dialogue_never_writes_config` | Static: dialogue path se `params.yaml` write nahi ho sakta |
| `test_candidate_cap_enforced` | Ek session me 4th candidate → warning aur session close |
| `test_engine_can_say_nothing_here` | Aisa fixture jahan sahi jawab "kuch nahi tha" ho, aur wo jawab aaye |
| `test_thought_record_no_lookahead` | Candle i ka record sirf candles 0..i se bane |

---

## 8. Build order

**P1.5 ke andar, spec 12 ke saath.** Reasoning record har candle par likhna P1 ka hi
kaam hai — sab kuch pehle se compute ho raha hai, bas structured shakl me nikalna hai.

Aur ek fayda: ye record spec 12 ke annotations ko bahut behtar bana deta hai. Ungli
rakh kar poochne se pehle hi trader dekh sakta hai ki engine kya soch raha tha — to
uski annotations *"ye line honi chahiye thi"* se badal kar *"tumne compression dekhi
par uspe rule nahi hai, wo rule ye hona chahiye"* ban jaati hain.

Wo doosri wali kaafi zyada kaam ki hai.

---

*Ye baat-cheet engine ko har cheez dekhna sikhane ke liye nahi hai. Wo engine jo sab
kuch dekhta hai, har jagah trade karta hai. Ye is liye hai ki tum dono ek hi cheez dekh
rahe ho ya nahi — aur jab nahi, to farak kis number me hai.*
