#!/usr/bin/env python3
"""
REACHABILITY ASSERTIONS — spec 10 §3.3

Har gate ke liye sabse favourable admissible input banao aur check karo ki gate
pass ho SAKTA hai. Jo gate kisi bhi input par pass nahi ho sakta, wo ek strict
filter nahi hai — wo config me bug hai.

Ye char me se teen dry-run bugs pakad leta, ek bhi candle process kiye bina.
Aur likhne ke 20 minute baad isne ek naya bug pakda jo maine khud daala tha
(b_entry_max_extreme_atr_mult 1.2, jo kisi bhi ATR par pass nahi ho sakta tha).

Run:  python3 prototype/reachability.py
Engine ko ye P2 me startup par chalana hai aur FAIL par start hi nahi karna.
"""
import sys, os, yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = yaml.safe_load(open(os.path.join(ROOT, "config", "params.yaml")))
L, S, R, V, T, ST = P["levels"], P["setups"], P["risk"], P["volatility"], P["time"], P["structure"]

results = []
def assert_(name, ok, detail, catches=""):
    results.append((name, bool(ok), detail, catches))

def eff(pts, mult, atr):
    return max(pts, mult * atr)

ATRS = list(range(V["atr_min_points"], V["atr_max_points"] + 1))

# ─── 1. Kya koi level kind Grade A tak pahunch sakta hai? ────────────────────
# Criteria: untested(1) + fast_departure(1) + HTF_confirmed(1) + clean_formation(1)
kinds = {
    "TURN 1m":   dict(untested=1, departure=1, htf=0, clean=1),   # departure ab sab ke liye
    "TURN 5m":   dict(untested=1, departure=1, htf=1, clean=1),
    "TURN 15m":  dict(untested=1, departure=1, htf=1, clean=1),
    "ANCHOR":    dict(untested=1, departure=0, htf=1, clean=1),   # clean: poore session me bana
    "LAUNCH":    dict(untested=1, departure=1, htf=0, clean=1),
}
reach_a = {k: sum(v.values()) >= L["grade_a_min_score"] for k, v in kinds.items()}
assert_("koi level kind Grade A ban sakta hai", any(reach_a.values()),
        ", ".join(k for k, v in reach_a.items() if v) or "KOI NAHI",
        "Bug 1 — ALERT 0% poore din")
assert_("ANCHOR Grade A ban sakta hai", reach_a["ANCHOR"],
        f"score {sum(kinds['ANCHOR'].values())} vs need {L['grade_a_min_score']}",
        "Bug 1 + spec 06 contradiction: ANCHOR par Setup B mandatory hai")

# ─── 2. R bounds har allowed ATR par sane hain? ──────────────────────────────
bad = [a for a in ATRS
       if eff(R["r_min_points"], R["r_min_atr_mult"], a)
          >= min(R["r_absolute_max_points"], eff(R["r_max_points"], R["r_max_atr_mult"], a))]
assert_("r_min < r_max har allowed ATR par", not bad,
        f"ATR {V['atr_min_points']}–{V['atr_max_points']}" + (f", fails at {bad}" if bad else ""))

# ─── 3. Setup B ka R ceiling ke andar aa sakta hai? ──────────────────────────
cap, buf, rmax_m = S["b_entry_max_extreme_atr_mult"], R["sl_buffer_atr_mult"], R["r_max_atr_mult"]
assert_("Setup B pullback entry R ceiling me fits", cap + buf <= rmax_m,
        f"{cap} + {buf} = {cap+buf:.2f}  must be <= {rmax_m}",
        "Bug 4 — aur ye assertion ne mera apna 1.2 wala bug pakda")

TYPICAL = range(15, 41)      # Bank Nifty 1m ATR14 yahan rehta hai zyadatar waqt
bad_typ, bad_ext = [], []
for a in ATRS:
    Rv = cap * a + eff(R["sl_buffer_min_points"], buf, a)
    lo = eff(R["r_min_points"], R["r_min_atr_mult"], a)
    hi = min(R["r_absolute_max_points"], eff(R["r_max_points"], rmax_m, a))
    if not (lo <= Rv <= hi):
        (bad_typ if a in TYPICAL else bad_ext).append(a)
assert_("Setup B R typical ATR band (15-40) me fits", not bad_typ,
        f"fails at ATR {bad_typ}" if bad_typ else "ATR 15-40 sab ok")
if bad_ext:
    print_note = (f"ATR {min(bad_ext)}+ par Setup B ka R absolute cap "
                  f"({R['r_absolute_max_points']}) se bahar — us volatility par setup "
                  f"tradeable nahi. Ye design hai, bug nahi.")
else:
    print_note = None

# ─── 4. Har setup ke paas ek permitting window hai? ──────────────────────────
exempt = T.get("htf_close_exempt_setups", [])
tail_min = ST["htf_close_buffer_minutes"]
b_stale = S["b_reclaim_max_candles"]
assert_("Setup B HTF-tail ke andar reachable", "B_sweep_reclaim" in exempt,
        f"tail {tail_min} min blocked, B stale after {b_stale} candles",
        "Bug 3 — sweep tail me hi banti hai; block + stale = setup delete")

# ─── 5. Touch counting level ko turant nahi maar deti? ───────────────────────
assert_("touch separation > 0 with finite max_touches",
        L["touch_separation_atr_mult"] > 0 and L["max_touches"] > 0,
        f"sep {L['touch_separation_atr_mult']}×ATR, max_touches {L['max_touches']}",
        "Bug 2 — PDL apne sweep se 2 min pehle mar gaya tha")

# ─── 6. Dormancy hysteresis ─────────────────────────────────────────────────
assert_("revival dormancy se nazdeek hai",
        L["revival_distance_atr_mult"] < L["dormancy_distance_atr_mult"],
        f"{L['revival_distance_atr_mult']} < {L['dormancy_distance_atr_mult']}")

# ─── 7. Space gate obstacle density ke saath achievable? ────────────────────
# Weak (round-100) obstacles gate nahi karte; gating grid 500 hai.
worst_gap = L["round_number_major_grid"]
need = R["min_space_ratio"] * min(R["r_absolute_max_points"],
                                  eff(R["r_max_points"], rmax_m, 25))
assert_("space gate max-R trade ke liye achievable", need <= worst_gap,
        f"need {need:.0f} pts at ATR 25, round-500 grid {worst_gap}",
        "REVIEW-v2 §5 — round-100 gating hone par ye impossible tha")

# ─── 8. Discipline invariants ───────────────────────────────────────────────
assert_("journey trades ko gate nahi kar sakti", ST["journey_gates_trades"] is False,
        "must stay False until P9 measures D2 hit rate")
assert_("round numbers Grade A nahi ban sakte", L["round_number_max_grade"] != "A",
        f"capped at {L['round_number_max_grade']}")
assert_("15m swing rule maujood hai", "swing_lookback_bars_15m" in L,
        f"k={L.get('swing_lookback_bars_15m')}",
        "mythinking.md §1: levels 15m se aate hain")
# ─── CONFIG COMPLETENESS — alag category ────────────────────────────────────
# Ye reachability bugs nahi hain. Ye woh values hain jo jaan-boojh kar khaali
# chhodi gayi hain taaki user consciously bhare. Engine start nahi karega, par
# wajah alag hai — "tumne abhi bhari nahi" vs "ye kabhi kaam nahi kar sakta".
incomplete = []
def need(path, why):
    node = P
    for k in path.split("."):
        node = (node or {}).get(k) if isinstance(node, dict) else None
    if node is None: incomplete.append((path, why))

need("session.risk_per_trade_rupees", "tumhara faisla — koi default jaan-boojh kar nahi")
COSTS = yaml.safe_load(open(os.path.join(ROOT, "config", "costs.yaml")))
if COSTS["costs"]["last_verified"] is None:
    incomplete.append(("costs.last_verified", "broker ki current charge list se verify karo"))
EVENTS = yaml.safe_load(open(os.path.join(ROOT, "config", "events.yaml")))
if EVENTS.get("last_updated") is None:
    incomplete.append(("events.last_updated", "RBI MPC + 5 bank results ki dates daalo"))

# ─── report ─────────────────────────────────────────────────────────────────
print("=" * 78)
print("  REACHABILITY ASSERTIONS — spec 10 §3.3")
print("=" * 78)
print()
fails = 0
for name, ok, detail, catches in results:
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {detail}")
    if catches:
        print(f"        └─ catches: {catches}")
    if not ok: fails += 1
print()
print(f"  {len(results)-fails}/{len(results)} reachability assertions pass")
if print_note:
    print(f"\n  NOTE  {print_note}")

if incomplete:
    print()
    print("=" * 78)
    print("  CONFIG ADHOORA — ye bug nahi hai, ye tumhare bharne ka intezaar hai")
    print("=" * 78)
    print()
    for k, why in incomplete:
        print(f"  ...  {k:<38} {why}")

print()
if fails:
    print(f"  ⛔ {fails} REACHABILITY FAIL — engine start NAHI karega.")
    print("     Ye strict filters nahi hain. Ye aise gates hain jo kisi bhi")
    print("     admissible input par pass nahi ho sakte — config me bug hai.")
elif incomplete:
    print(f"  ⏸  Rules sahi hain ({len(results)}/{len(results)} reachable), par {len(incomplete)} config values baaki hain.")
    print("     Engine tab tak start nahi karega. Ye by design hai.")
else:
    print("  ✅ Sab clear — engine start kar sakta hai.")
sys.exit(1 if (fails or incomplete) else 0)
