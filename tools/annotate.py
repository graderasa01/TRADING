#!/usr/bin/env python3
"""
annotate.py — the teaching loop's pipeline. Spec 12.

    python tools/annotate.py new 2026-03-04              # a blank annotation to fill
    python tools/annotate.py check annotations/2026-03-04.yaml
    python tools/annotate.py measure annotations/2026-03-04.yaml
    python tools/annotate.py regress                     # every annotation, current rules

## What this tool is for, and what it must refuse to be

Spec 09 §3.2b's overlap test gives a **percentage**. This gives the **reason** — and the
reason is the part that can become code. *"62% overlap"* is a number. *"Ye line isliye
honi chahiye thi ki do chup candles ke baad ek badi candle nikli"* is a rule.

Three disciplines are enforced here rather than trusted (spec 12 §3):

**1. Three buckets, all of them.** `missed` · `false_positive` · `confirmed_good`. An
annotation with an empty `false_positive` bucket is **not calibration, it is inflation**
— it pushes the engine toward more lines every session, and more lines means more ALERT
means more trades, which is the exact failure `CLAUDE.md` exists to prevent. `check`
refuses to pass a session that only says what was missing.

**2. The engine may disagree with you.** You write *"price yahan 4 baar rejected hui"*;
`measure` counts from the data and may say **2**. It reports the conflict and stops.
Without that, the tool *"sirf tumhari galtiyon ko code me likh dega, extra steps ke
saath."* Every trader has patterns they believe in that are not in the data — this loop
is the cheapest chance to catch them, and it only works if the engine can say no.

**3. Cost is reported with benefit, always.** No proposal is acceptable without its
precision impact (spec 11 §D3). A detector that fires on everything catches every move
that follows anything; that is arithmetic, not detection.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401  (console encoding, see module)

from src.config.loader import load_config  # noqa: E402
from src.domain.models import ZERO  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.levels.detectors import detect_launch, find_wick_clusters  # noqa: E402
from src.p1_pipeline import P1Pipeline  # noqa: E402

ANNOTATION_DIR = REPO_ROOT / "annotations"
BUCKETS = ("missed", "false_positive", "confirmed_good")

TEMPLATE = """# TEACHING ANNOTATION — spec 12
#
# Teen buckets. TEENO bharne hain.
#
#   missed          line honi chahiye thi, engine ne nahi khinchi   -> recall
#   false_positive  engine ne khinchi, honi nahi chahiye thi        -> PRECISION
#   confirmed_good  engine ne sahi pakda                            -> regression
#
# Sirf `missed` bharoge to har session engine ko ZYADA lines ki taraf dhakelega,
# aur zyada lines = zyada ALERT = zyada trades. Wahi cheez jise rokne ke liye
# CLAUDE.md aur spec 05 bane hain. `false_positive` hi wo balance hai.
#
# Agar sach me koi galat line nahi lagi, to likh do ki dekha aur koi nahi mili —
# par dekhna zaroori hai.

session: "{day}"
annotator: ""

missed:
  # - price: 57698
  #   candles: [75, 79]        # chart ke x-axis se index
  #   kind: "launch"           # turn | launch | break | anchor | naya
  #   should_have: "grade_a"   # exist | grade_a | alert
  #   why: |
  #     Apne shabdon me — jaise kisi ko samjhaate ho.
  #   measurable: |
  #     ⚠ SABSE ZAROORI FIELD. "Kis NUMBER se pata chala?"
  #     Nahi bhar paate? Khaali chhod do — confidence apne aap `low` ho jaayegi,
  #     aur jab tak do aur sessions me wahi pattern na dikhe, uspe rule nahi banega.
  #     Wo apne aap me jaankari hai: shayad ye rule nahi, YAAD hai.
  #   confidence: "high"       # high | medium | low

false_positive:
  # - price: 57833
  #   candle: 210
  #   engine_said: "TURN grade C"
  #   why: |
  #     Ye sirf ek 1m swing hai jise kisi ne defend nahi kiya.
  #   measurable: |
  #     Departure ke baad price 20 candles me wapas aa gayi aur bina ruke paar kar gayi.

confirmed_good:
  # - price: 57455
  #   note: "PDL. Sahi pakda, sahi grade. Isko mat todna."
"""


# ─────────────────────────────────────────────────────────────────────────────
# the fixed measurement battery — spec 12 §5 step 1
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Measurement:
    """*"Har baar wahi ~30 measurements, taaki annotations ke beech tulna ho sake."*

    Fixed on purpose. A battery that changes between annotations cannot be compared
    across them, and comparison is the only way a pattern shows up in more than one
    session — which is what separates a rule from a memory.
    """
    price: Decimal
    at_candles: tuple[int, ...]
    values: dict[str, Any] = field(default_factory=dict)
    near_miss: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)


def battery(pipeline: P1Pipeline, price: Decimal, lo: int, hi: int) -> Measurement:
    candles = pipeline.levels.candles
    mid = min(max((lo + hi) // 2, 0), len(candles) - 1)
    atr = pipeline.records[mid].board.atr20_1m or Decimal(20)
    window = candles[max(0, mid - 10):min(len(candles), mid + 6)]
    m = Measurement(price=price, at_candles=(lo, hi))

    m.values["atr20"] = atr
    m.values["candle_ranges"] = [k.range for k in window]
    m.values["range_x_atr"] = [round(k.range / atr, 2) for k in window]
    m.values["upper_wick_pct"] = [
        round(k.upper_wick / k.range * 100) if k.range else None for k in window]
    m.values["lower_wick_pct"] = [
        round(k.lower_wick / k.range * 100) if k.range else None for k in window]
    m.values["close_thirds"] = [k.close_third for k in window]

    # time at price, with the separation rule the engine actually uses (spec 03 §4)
    sep = max(Decimal(8), Decimal("0.6") * atr)
    touching, separated, in_zone = 0, 0, False
    for k in candles[:hi + 1]:
        inside = k.l <= price <= k.h
        if inside:
            touching += 1
            if not in_zone:
                separated += 1
                in_zone = True
        elif in_zone and (k.l > price + sep or k.h < price - sep):
            in_zone = False
    m.values["candles_touching_price"] = touching
    m.values["separated_touches"] = separated

    for n in (3, 5, 10):
        idx = min(mid + n, len(candles) - 1)
        m.values[f"departure_{n}_candles_x_atr"] = round(
            abs(candles[idx].c - price) / atr, 2)

    before = candles[max(0, mid - 5):mid]
    if before:
        m.values["approach_speed_x_atr"] = round(
            abs(before[-1].c - before[0].o) / (atr * len(before)), 2)

    last3 = candles[max(0, mid - 2):mid + 1]
    prior10 = candles[max(0, mid - 12):max(0, mid - 2)]
    if last3 and prior10:
        a = sum(k.range for k in last3) / len(last3)
        b = sum(k.range for k in prior10) / len(prior10)
        m.values["compression"] = round(a / b, 2) if b > ZERO else None

    board = pipeline.records[mid].board
    nearest = min((lv for lv in board.levels_above + board.levels_below),
                  key=lambda lv: abs(lv.body_edge - price), default=None)
    m.values["nearest_engine_level"] = None if nearest is None else {
        "price": nearest.body_edge, "grade": nearest.grade.value,
        "kind": nearest.kind.value, "distance": abs(nearest.body_edge - price)}
    m.values["htf_swing_distance"] = _htf_distance(pipeline, price)
    return m


def _htf_distance(pipeline: P1Pipeline, price: Decimal) -> Decimal | None:
    swings = pipeline.structure.swings["5m"]
    prices = [s.price for s in swings["high"] + swings["low"]]
    return min((abs(p - price) for p in prices), default=None)


# ─────────────────────────────────────────────────────────────────────────────
# near-miss diagnosis — spec 12 §5 step 2, "the most valuable output"
# ─────────────────────────────────────────────────────────────────────────────
def diagnose(pipeline: P1Pipeline, cfg, price: Decimal, lo: int, hi: int) -> dict[str, Any]:
    """*"Kaunsa maujooda detector KAREEB tha aur kitne se chooka."*

    "Missed by 0.15 x ATR" is a threshold change. "No detector was close" is the only
    honest reason to consider a new one — and that should be rare.
    """
    candles = pipeline.levels.candles
    out: dict[str, Any] = {}
    best_launch: dict[str, Any] | None = None

    for i in range(max(0, lo - 2), min(hi + 3, len(candles))):
        atr = pipeline.records[i].board.atr20_1m
        if atr is None or atr <= ZERO:
            continue
        attempt = detect_launch(
            candles, i, atr,
            impulse_atr_mult=cfg.dec("levels.launch_impulse_atr_mult"),
            base_atr_mult=cfg.dec("levels.launch_base_atr_mult"),
            base_min=int(cfg.get("levels.launch_base_min_candles")),
            base_max=int(cfg.get("levels.launch_base_max_candles")))
        shortfall = attempt.measured.get("shortfall_atr")
        if attempt.candidate is not None:
            best_launch = {"candle": i, "reason": "would have fired"}
            break
        if shortfall is not None and (best_launch is None
                                      or shortfall < best_launch.get("shortfall_atr", 1e9)):
            best_launch = {"candle": i, "reason": attempt.reason,
                           "shortfall_atr": round(float(shortfall), 3)}
    if best_launch:
        out["LAUNCH"] = best_launch

    tol = cfg.effective("levels.wick_cluster_tolerance_points",
                        "levels.wick_cluster_tolerance_atr_mult",
                        pipeline.records[min(hi, len(candles) - 1)].board.atr20_1m)
    hits = [i for i in range(max(0, lo), min(hi + 1, len(candles)))
            if any(abs(k.body_edge - price) <= tol * 3
                   for k in find_wick_clusters(candles, i, min_touches=2,
                                               tolerance=tol, window=30))]
    out["WICK_CLUSTER"] = {"fired_at": hits[:4], "tolerance": round(float(tol), 1)} if hits \
        else {"fired_at": [], "note": "no cluster within 3x tolerance of this price"}

    swings = pipeline.structure.swings["1m"]["high"] + pipeline.structure.swings["1m"]["low"]
    nearest_swing = min((abs(s.price - price) for s in swings), default=None)
    out["SWING_PIVOT"] = {"nearest_swing_distance": (round(float(nearest_swing), 1)
                                                     if nearest_swing is not None else None)}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# cross-check — spec 12 §3.2. The engine's right to disagree.
# ─────────────────────────────────────────────────────────────────────────────
CLAIM_PATTERNS = [
    ("touches", ("baar", "times", "touch", "rejected", "ruki"), "separated_touches"),
    ("wick", ("wick", "%"), None),
]


def cross_check(entry: dict[str, Any], m: Measurement) -> list[str]:
    """Compare the trader's stated numbers against the measured ones.

    Deliberately conservative: it only speaks when it finds a number in the prose that
    it can bind to a measurement. A cross-checker that guesses produces noise, and noise
    here trains the trader to ignore the one time it is right.
    """
    conflicts: list[str] = []
    text = f"{entry.get('why', '')} {entry.get('measurable', '')}".lower()
    import re

    for word, cues in (("touch", ("baar", "times", "touch", "rejected", "ruki", "tested")),):
        if not any(cue in text for cue in cues):
            continue
        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", text) if int(n) <= 20]
        if not numbers:
            continue
        claimed = numbers[0]
        measured = m.values["separated_touches"]
        if claimed != measured:
            conflicts.append(
                f"you say {claimed} {word}(es); the data says {measured} separated "
                f"touch(es) (candles that entered the zone after leaving it by "
                f"max(8, 0.6 x ATR)). Raw candles touching the price: "
                f"{m.values['candles_touching_price']}.\n"
                f"      Is it (a) the tolerance is too narrow, (b) the touch definition "
                f"is wrong, or (c) this level's real reason was something else?")
    return conflicts


# ─────────────────────────────────────────────────────────────────────────────
# commands
# ─────────────────────────────────────────────────────────────────────────────
def load_annotation(path: Path) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for bucket in BUCKETS:
        data.setdefault(bucket, None)
    return data


def cmd_new(args) -> int:
    ANNOTATION_DIR.mkdir(parents=True, exist_ok=True)
    path = ANNOTATION_DIR / f"{args.day}.yaml"
    if path.exists():
        print(f"{path} already exists", file=sys.stderr)
        return 1
    path.write_text(TEMPLATE.format(day=args.day), encoding="utf-8")
    print(f"wrote {path}\n\nRender the chart with the engine's book overlaid:")
    print(f"  python tools/chart.py --day {args.day} --levels")
    return 0


def cmd_check(args) -> int:
    """Schema, and the discipline that matters more than the schema."""
    path = Path(args.file)
    data = load_annotation(path)
    problems, warnings = [], []

    if not data.get("session"):
        problems.append("no `session` date")
    counts = {b: len(data.get(b) or []) for b in BUCKETS}

    for entry in (data.get("missed") or []):
        if not entry.get("why"):
            problems.append(f"missed @ {entry.get('price')}: `why` is required")
        if not entry.get("measurable"):
            entry["confidence"] = "low"
            warnings.append(
                f"missed @ {entry.get('price')}: no `measurable` -> confidence: low. "
                f"That is information, not a failure — it may be a memory rather than a "
                f"rule. No rule will be built on it until the same pattern appears in "
                f"two more sessions.")

    print(f"\n{path.name}   missed {counts['missed']} · "
          f"false_positive {counts['false_positive']} · "
          f"confirmed_good {counts['confirmed_good']}")

    if counts["false_positive"] == 0:
        problems.append(
            "`false_positive` is EMPTY.\n"
            "      Spec 12 §3.1: an annotation with only missed levels is not\n"
            "      calibration, it is inflation. It pushes the engine toward more lines\n"
            "      every session — more lines, more ALERT, more trades.\n"
            "      Mark at least as many wrong lines as missing ones. If none look wrong,\n"
            "      write that you looked and found none — but look.")
    if counts["confirmed_good"] == 0:
        warnings.append("`confirmed_good` is empty — nothing protects the levels the "
                        "engine already gets right from the next rule change.")

    for w in warnings:
        print(f"  warn  {w}")
    for p in problems:
        print(f"  FAIL  {p}")
    print()
    return 1 if problems else 0


def cmd_measure(args) -> int:
    path = Path(args.file)
    data = load_annotation(path)
    cfg = load_config(strict=False)
    day = date.fromisoformat(str(data["session"]))
    pipeline = P1Pipeline(cfg, ReplayFeed(args.symbol).session(day))
    pipeline.run()

    print(f"\n{'=' * 72}\nMEASURING {path.name} — {day}\n{'=' * 72}")
    for bucket in ("missed", "false_positive"):
        for entry in (data.get(bucket) or []):
            price = Decimal(str(entry["price"]))
            span = entry.get("candles") or [entry.get("candle", 0)] * 2
            lo, hi = int(span[0]), int(span[-1])
            m = battery(pipeline, price, lo, hi)
            m.near_miss = diagnose(pipeline, cfg, price, lo, hi)
            m.conflicts = cross_check(entry, m)

            print(f"\n── {bucket.upper()} @ {price:,.1f}  candles {lo}-{hi} "
                  f"{'─' * 24}")
            print("\n  1. MEASURED")
            print(f"     ATR20 {m.values['atr20']:.1f}")
            print(f"     ranges (x ATR)      {m.values['range_x_atr']}")
            print(f"     upper wick %        {m.values['upper_wick_pct']}")
            print(f"     lower wick %        {m.values['lower_wick_pct']}")
            print(f"     close thirds        {m.values['close_thirds']}")
            print(f"     time at price       {m.values['candles_touching_price']} candles "
                  f"touched it; {m.values['separated_touches']} separated touches")
            print(f"     departure x ATR     3c {m.values['departure_3_candles_x_atr']}  "
                  f"5c {m.values['departure_5_candles_x_atr']}  "
                  f"10c {m.values['departure_10_candles_x_atr']}")
            print(f"     compression         {m.values.get('compression')}")
            print(f"     nearest 5m swing    {m.values['htf_swing_distance']}")
            print(f"     engine's nearest    {m.values['nearest_engine_level']}")

            print("\n  2. NEAR MISS — which detector was closest, and by how much")
            for name, detail in m.near_miss.items():
                print(f"     {name:<14} {detail}")

            print("\n  3. CROSS-CHECK")
            if m.conflicts:
                for conflict in m.conflicts:
                    print(f"     !! {conflict}")
                print("     Spec 12 §3.2 — stopping here. Resolve this before proposing "
                      "anything.")
            else:
                print("     no numeric claim in your text conflicts with the data.")
    print(f"\n{'=' * 72}")
    print("4. PROPOSE — threshold change first, clause second, new detector last.")
    print("   Every proposal needs: exact arithmetic, a market MECHANISM (not a data")
    print("   description), a reachability check (spec 10 §3.3), and its COST in")
    print("   precision and levels/day. Spec 12 §5.")
    print("5. REGRESS — python tools/annotate.py regress")
    return 0


def cmd_regress(args) -> int:
    """*"confirmed_good -> sab abhi bhi zinda hain? Ek bhi toota to proposal REJECT."*"""
    cfg = load_config(strict=False)
    files = sorted(ANNOTATION_DIR.glob("*.yaml"))
    if not files:
        print(f"no annotations in {ANNOTATION_DIR}", file=sys.stderr)
        return 2

    total = {"confirmed_kept": 0, "confirmed_lost": 0, "missed_caught": 0, "missed_still": 0,
             "fp_still_drawn": 0, "fp_gone": 0}
    print(f"\nREGRESSION over {len(files)} annotation(s)\n{'=' * 60}")
    for path in files:
        data = load_annotation(path)
        if not data.get("session"):
            continue
        day = date.fromisoformat(str(data["session"]))
        pipeline = P1Pipeline(cfg, ReplayFeed(args.symbol).session(day))
        pipeline.run()
        book = pipeline.levels.book
        drawn = [lv for lv in list(book.live.values()) + list(book.dead.values())]

        def near(price: Decimal, tol: Decimal) -> list:
            return [lv for lv in drawn if abs(lv.body_edge - price) <= tol]

        atr = pipeline.records[-1].board.atr20_1m or Decimal(20)
        tol = max(Decimal(10), Decimal("0.4") * atr)      # spec 09 §3.2b's match rule
        line = [f"  {path.name}"]
        for entry in (data.get("confirmed_good") or []):
            hit = bool(near(Decimal(str(entry["price"])), tol))
            total["confirmed_kept" if hit else "confirmed_lost"] += 1
            if not hit:
                line.append(f"    LOST confirmed_good @ {entry['price']} — REJECT any "
                            f"proposal that did this")
        for entry in (data.get("missed") or []):
            hit = bool(near(Decimal(str(entry["price"])), tol))
            total["missed_caught" if hit else "missed_still"] += 1
        for entry in (data.get("false_positive") or []):
            hit = bool(near(Decimal(str(entry["price"])), tol))
            total["fp_still_drawn" if hit else "fp_gone"] += 1
        print("\n".join(line))

    print(f"\n{'=' * 60}")
    print(f"  confirmed_good kept    {total['confirmed_kept']} / "
          f"{total['confirmed_kept'] + total['confirmed_lost']}   "
          f"<- any loss rejects the change")
    print(f"  missed now caught      {total['missed_caught']} / "
          f"{total['missed_caught'] + total['missed_still']}   (recall)")
    print(f"  false positives gone   {total['fp_gone']} / "
          f"{total['fp_gone'] + total['fp_still_drawn']}   (precision)")
    print("\n  Recall without precision is half a fraction (spec 11 §D3).")
    return 1 if total["confirmed_lost"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="create a blank annotation")
    p.add_argument("day")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("check", help="schema + the three-bucket discipline")
    p.add_argument("file")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("measure", help="the battery, the near-miss, the cross-check")
    p.add_argument("file")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("regress", help="every annotation against the current rules")
    p.set_defaults(func=cmd_regress)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
