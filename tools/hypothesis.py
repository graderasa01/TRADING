#!/usr/bin/env python3
"""
hypothesis.py — you say what you see; the data says whether it is there.

    python tools/hypothesis.py vocab                      # what can the engine see at all?
    python tools/hypothesis.py new coil-break             # a blank claim to fill in
    python tools/hypothesis.py translate learning/hypotheses/coil-break.yaml
    python tools/hypothesis.py register  learning/hypotheses/coil-break.yaml
    python tools/hypothesis.py measure   learning/hypotheses/coil-break.yaml
    python tools/hypothesis.py validate  learning/hypotheses/coil-break.yaml
    python tools/hypothesis.py ledger

## The order is the whole point

`translate` before `register`, `register` before `measure`, `measure` before `validate`.
Each step is refused until the one before it has happened, and the refusals are not
bureaucracy — each one blocks a specific way the final number gets inflated:

* **translate first**, because the commonest failure is not that the trader is wrong. It
  is that the predicate is a bad translation of what they meant, and a bad translation
  produces a confident "the data disagrees with you" that is really "the code disagrees
  with itself." `translate` prints real spans from `teach` that match, so a mistranslation
  is visible before anyone's intuition gets contradicted.

* **register before measure**, because a threshold picked after seeing the result
  describes the sample, not the market.

* **measure before validate**, because a claim scored on both splits at once has no
  out-of-sample left. Spec 11 §D1.

## ⚠ What this tool cannot protect you from

It counts hypotheses and divides the significance threshold by the count. That handles
*independent* tests. It does **not** handle the case where twenty variations of one idea
are registered until one clears — the arithmetic looks correct and the answer is still
wrong. Spec 11 §7's stopping rules are the defence there, and they are a decision, not a
computation. This tool will tell you the count. It cannot tell you that you have started
fishing.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.config.loader import load_config  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.learning.hypothesis import (  # noqa: E402
    HYPOTHESIS_DIR, OUTCOMES, Hypothesis, HypothesisError, Result, alpha_for,
    family_error_probability, ledger_entries, load_hypothesis, measure_session, register,
    record_result, registered_count, save_hypothesis, verdict_for)
from src.learning.split import load_split  # noqa: E402
from src.reasoning.vocabulary import (  # noqa: E402
    BY_NAME, UNOBSERVABLE, describe)

RULE = "─" * 74


TEMPLATE = """# HYPOTHESIS — one thing you see on the chart, written so it can be WRONG.
#
# Fill this in, then:
#   python tools/hypothesis.py translate learning/hypotheses/{id}.yaml
#
# `translate` shows you real candles that match. Read them BEFORE registering. If they
# are not the thing you meant, the predicate is a bad translation — fix it now, while
# fixing it is free.

id: "{id}"
author: ""

# In your own words. Do not clean it up for me — the raw sentence is the record.
stated: |


# WHY does the market do this? One sentence, about the market, not about the data.
# Spec 11 §D2:
#   "price compresses before expansion because participants stop disagreeing"  -> a mechanism
#   "levels born between 10:15 and 10:45 work better"                          -> a fit; delete it
# If you cannot answer this, the claim is probably a memory of one session.
mechanism: |


# The predicate. Run `python tools/hypothesis.py vocab` for everything available.
clauses:
  - capability: "span_compression"
    op: "<="
    value: "0.6"

span_len: 8          # how many candles the claim is about. 1 = a single candle.

# What you say happens next. Menu is fixed — see `vocab`.
outcome: "expansion"
horizon: 10          # candles to look ahead
k: "1.8"             # the size, in the outcome's own units

# ⚠ BEFORE any measurement: what rate do you EXPECT? A number, however rough.
# This is the field that makes the result mean something. If you write nothing, the
# measurement can only confirm you — it can never surprise you.
predicted_rate: ""

notes: |

"""


# ─────────────────────────────────────────────────────────────────────────────
def cmd_vocab(args) -> int:
    cfg = load_config(strict=False)
    print(f"\n{RULE}\nWHAT THE ENGINE CAN SEE — and what it does about it\n{RULE}")

    groups: dict[str, list] = {}
    for status, cap in describe(cfg):
        groups.setdefault(status, []).append(cap)

    headings = {
        "ACTED_ON": ("MEASURED, AND SOMETHING ACTS ON IT",
                     "a params key drives a detector — tune these, don't rebuild them"),
        "BLIND_SPOT": ("MEASURED, NOTHING ACTS ON IT",
                       "the engine can compute this and no detector consumes it. A new "
                       "detector here is justified — spec 13 §2.1"),
        "NOT_BUILT": ("NOT MEASURED, BUT THIS FEED SUPPORTS IT",
                      "nobody wrote the function. Code that does not exist yet"),
    }
    for status in ("ACTED_ON", "BLIND_SPOT", "NOT_BUILT"):
        caps = groups.get(status, [])
        if not caps:
            continue
        title, note = headings[status]
        print(f"\n{title}   [{len(caps)}]\n  {note}\n")
        for cap in caps:
            print(f"  {cap.name:<22} {cap.question}")
            print(f"  {'':<22} algorithm: {cap.algorithm}")
            print(f"  {'':<22} family: {cap.family}   keys: "
                  f"{', '.join(cap.params) or '—'}")
            print(f"  {'':<22} {cap.source}\n")

    print(f"\n{RULE}\nWHAT THIS FEED CANNOT SAY — EVER   [{len(UNOBSERVABLE)}]\n{RULE}")
    print("  Not a backlog. These are not missing detectors; they are outside what a\n"
          "  1-minute INDEX candle contains. No amount of building reaches them.\n")
    for u in UNOBSERVABLE:
        print(f"  {u.name:<18} {u.question}")
        print(f"  {'':<18} {u.why}")
        print(f"  {'':<18} evidence: {u.evidence}\n")

    print(f"{RULE}\nOUTCOMES you may predict\n{RULE}")
    for name, meaning in OUTCOMES.items():
        print(f"  {name:<14} {meaning}")
    print()
    return 0


def cmd_new(args) -> int:
    HYPOTHESIS_DIR.mkdir(parents=True, exist_ok=True)
    path = HYPOTHESIS_DIR / f"{args.id}.yaml"
    if path.exists():
        print(f"{path} already exists", file=sys.stderr)
        return 1
    path.write_text(TEMPLATE.format(id=args.id), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}\n")
    print("Next:  python tools/hypothesis.py vocab            # what you can say")
    print(f"then:  python tools/hypothesis.py translate {path.relative_to(REPO_ROOT)}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
def _sessions_for(bucket: str, symbol: str, limit: int | None,
                  *, reason: str = "", hypothesis_id: str = ""):
    split = load_split()
    feed = ReplayFeed(symbol, on_gap="skip")
    days = feed.available_days()
    if bucket == "teach":
        wanted = split.teach(days)
    elif bucket == "validate":
        wanted = split.validate(days)
    else:
        wanted = split.holdout(days, reason=reason, hypothesis_id=hypothesis_id)
    if limit:
        wanted = wanted[:limit]
    return split, feed, wanted


def cmd_translate(args) -> int:
    """Show the trader what their sentence became, on real candles, before it is frozen."""
    h = load_hypothesis(Path(args.file))
    print(f"\n{RULE}\nTRANSLATION CHECK — {h.id}\n{RULE}")
    print(f"\nYou said:\n  {h.stated.strip() or '(nothing written)'}\n")
    print(f"Mechanism:\n  {h.mechanism.strip() or '(nothing written)'}\n")

    unknown = h.unknown_clauses()
    unobservable = h.unobservable_clause()
    unbuilt = h.unbuilt_clauses()

    if unobservable:
        u = next(u for u in UNOBSERVABLE if u.name == unobservable)
        print(f"  STOP — this claim rests on `{u.name}`, which this feed cannot express.")
        print(f"         {u.why}")
        print(f"         evidence: {u.evidence}")
        print("\n  This is not a detector waiting to be written. Nothing built on these\n"
              "  candles can answer it. If the intuition is real it will need a different\n"
              "  instrument or a different feed — not more code.\n")
        return 1
    if unknown:
        print(f"  FAIL  unknown capability: {unknown}")
        print("        `python tools/hypothesis.py vocab` lists every name available.\n")
        return 1
    if unbuilt:
        print(f"  NOT BUILT — {unbuilt}")
        print("        The feed supports this; no function computes it yet. That is a\n"
              "        genuine gap and the honest answer is that it must be written before\n"
              "        the claim can be tested. Nothing here is blocked by physics.\n")
        return 1

    print("Which becomes, mechanically:\n")
    print(f"  FOR every group of {h.span_len} consecutive 1m candle(s):")
    for clause in h.clauses:
        print(f"    AND  {clause}")
    print(f"\n  THEN within the next {h.horizon} candles, expect: {h.outcome}")
    print(f"       ({OUTCOMES[h.outcome]}, k = {h.k})")
    print(f"\n  You predict this holds: {h.predicted_rate or '⚠ NOT STATED'}")
    if not h.predicted_rate.strip():
        print("       Write a number. Without it the measurement can only agree with you.")

    cfg = load_config(strict=False)
    for clause in h.clauses:
        cap = BY_NAME[clause.capability]
        if cap.status(cfg) == "BLIND_SPOT":
            print(f"\n  note  `{clause.capability}` is measured but no detector consumes it.")
            print("        If this claim survives, that is where it would be built in.")

    print(f"\n{RULE}\nREAL SPANS THAT MATCH — read these before registering\n{RULE}")
    _, feed, days = _sessions_for("teach", args.symbol, args.sessions)
    result = Result()
    for session in feed.sessions(days=days):
        result.sessions += 1
        measure_session(h, session.candles, session.day, result,
                        collect_examples=args.examples)
        if len(result.examples) >= args.examples:
            break

    if not result.examples:
        print(f"\n  none in {result.sessions} session(s). The predicate never fires — which\n"
              "  is itself an answer: either a threshold is far off, or the thing you see\n"
              "  is rarer than the clauses describe.\n")
        return 1
    for ex in result.examples:
        print(f"\n  {ex['day']}  candles {ex['candles'][0]}-{ex['candles'][1]}  "
              f"at {ex['time']}   outcome: "
              f"{'as predicted' if ex['outcome'] else 'NOT as predicted'}")
        for key, value in ex["measured"].items():
            print(f"      {key:<22} {value}")
    print(f"\n  Chart them:  python tools/chart.py --day {result.examples[0]['day']}")
    print("\n  Is this the thing you meant? If not, the predicate is wrong — fix it NOW,\n"
          "  before registering. After registration a change becomes a new hypothesis and\n"
          "  costs you a slot in the multiple-comparison budget.\n")
    print(f"  Ready:  python tools/hypothesis.py register {args.file}\n")
    return 0


def cmd_register(args) -> int:
    path = Path(args.file)
    h = load_hypothesis(path)
    if h.registered_digest:
        print(f"{h.id} is already registered as {h.registered_digest} "
              f"({h.registered_at}).", file=sys.stderr)
        return 1
    problems = []
    if not h.stated.strip():
        problems.append("`stated` is empty — the claim in your own words is the record")
    if not h.mechanism.strip():
        problems.append(
            "`mechanism` is empty. Spec 11 §D2: a rule without a market mechanism is a "
            "fit.\n        'Why does the market do this?' — one sentence.")
    if not h.predicted_rate.strip():
        problems.append(
            "`predicted_rate` is empty. Register a number BEFORE measuring or the result "
            "cannot\n        surprise you, and a result that cannot surprise you is not "
            "evidence.")
    if problems:
        for p in problems:
            print(f"  FAIL  {p}")
        return 1

    before = registered_count()
    h = register(h)
    save_hypothesis(h, path)
    print(f"\nregistered {h.id}   digest {h.registered_digest}")
    print("  The claim is now frozen. Editing any claim field invalidates the digest and\n"
          "  `measure` will refuse — deliberately.\n")
    print(f"  hypotheses registered so far: {before + 1}")
    print(f"  significance threshold now:   p < {alpha_for(before + 1):.4f}  "
          f"(0.05 / {before + 1}, Bonferroni)")
    print(f"\n  python tools/hypothesis.py measure {args.file}\n")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
def _run(h: Hypothesis, bucket: str, symbol: str, limit: int | None,
         reason: str = "") -> Result:
    _, feed, days = _sessions_for(bucket, symbol, limit, reason=reason, hypothesis_id=h.id)
    result = Result()
    for session in feed.sessions(days=days):
        result.sessions += 1
        measure_session(h, session.candles, session.day, result)
    return result


def _report(h: Hypothesis, result: Result, bucket: str) -> str:
    n = registered_count()
    alpha = alpha_for(n)
    z, p = result.z_and_p()
    lo, hi = result.wilson_interval()

    print(f"\n{RULE}\n{bucket.upper()} — {h.id}\n{RULE}")
    print(f"\n  sessions            {result.sessions}")
    print(f"  spans examined      {result.base_spans:,}")
    print(f"  predicate fired     {result.events:,}   "
          f"({result.firing_rate * 100:.2f}% of spans)")
    if result.undefined:
        print(f"  undefined           {result.undefined:,}  (a clause could not be "
              f"computed — too early in the session, or a flat candle)")

    if result.events < 30:
        print(f"\n  ⚠ {result.events} events is too few to conclude anything. Anything "
              f"below ~30\n    is a story, not a rate.")

    print(f"\n  YOUR RATE           {result.rate * 100:.1f}%   "
          f"({result.hits:,} of {result.events:,})")
    print(f"  95% interval        {lo * 100:.1f}% .. {hi * 100:.1f}%")
    print(f"  BASE RATE           {result.base_rate * 100:.1f}%   "
          f"(the same outcome over ALL {result.base_spans:,} spans)")
    print(f"  lift                {result.lift:.2f}x")
    print(f"  edge                {(result.rate - result.base_rate) * 100:+.1f} "
          f"percentage points")
    if h.predicted_rate.strip():
        print(f"  you predicted       {h.predicted_rate}")

    print(f"\n  z = {z:.2f}   p = {p:.5f}")
    print(f"  threshold           p < {alpha:.5f}   (0.05 / {n} registered, Bonferroni)")
    print(f"  at {n} hypotheses, P(at least one false positive at 0.05) = "
          f"{family_error_probability(n) * 100:.0f}%")

    label, why = verdict_for(result, alpha)
    print(f"\n  {'─' * 70}")
    print(f"  VERDICT     {label}")
    for line in textwrap.wrap(why, 62):
        print(f"              {line}")
    print(f"  {'─' * 70}")
    return label


def cmd_measure(args) -> int:
    path = Path(args.file)
    h = load_hypothesis(path)
    h.check_registered()
    result = _run(h, "teach", args.symbol, args.sessions)
    label = _report(h, result, "teach")
    save_hypothesis(record_result(h, "teach", result, label), path)
    print("\n  This is the split you are ALLOWED to look at in detail. Nothing measured\n"
          "  here certifies anything — it only decides whether validate is worth "
          "spending.\n")
    if result.events >= 30 and result.rate > result.base_rate:
        print(f"  python tools/hypothesis.py validate {args.file}\n")
    else:
        print("  Do not run validate. Spec 11 §D1 — each look costs the split some of its\n"
              "  value, and there is nothing here worth spending it on.\n")
    return 0


def cmd_validate(args) -> int:
    path = Path(args.file)
    h = load_hypothesis(path)
    h.check_registered()
    result = _run(h, "validate", args.symbol, args.sessions)
    label = _report(h, result, "validate")
    save_hypothesis(record_result(h, "validate", result, label), path)
    print("\n  Scores only — spec 11 §D1 forbids reading individual cases from validate,\n"
          "  and this command deliberately prints none.")
    print("\n  If teach was strong and this is not, the teach result was the sample "
          "talking.\n  That is the loop working, and the correct response is to mark this "
          "one dead\n  in the ledger — not to adjust it and re-run.\n")
    return 0


def cmd_ledger(args) -> int:
    entries = ledger_entries()
    n = registered_count()
    print(f"\n{RULE}\nHYPOTHESIS LEDGER\n{RULE}\n")
    if not entries:
        print("  empty.\n")
        return 0
    for e in entries:
        print(f"  {e.get('id', '?'):<24} {e.get('status', 'draft'):<12} "
              f"{e.get('registered_digest') or '—'}")
        stated = (e.get("stated") or "").strip().splitlines()
        if stated:
            print(f"  {'':<24} {stated[0][:60]}")
    print(f"\n  registered (incl. dead)   {n}")
    print(f"  corrected threshold       p < {alpha_for(n):.5f}")
    print(f"  P(>=1 false positive)     {family_error_probability(n) * 100:.0f}% at 0.05 "
          f"uncorrected")
    print("\n  Dead hypotheses stay in this count. Deleting the failures is exactly how a\n"
          "  1-in-20 fluke becomes 'the one that worked'.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="NIFTY BANK")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("vocab", help="what the engine can see, and what it cannot")
    p.set_defaults(func=cmd_vocab)

    p = sub.add_parser("new", help="a blank hypothesis")
    p.add_argument("id")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("translate", help="what your sentence became, on real candles")
    p.add_argument("file")
    p.add_argument("--examples", type=int, default=5)
    p.add_argument("--sessions", type=int, default=40)
    p.set_defaults(func=cmd_translate)

    p = sub.add_parser("register", help="freeze the claim")
    p.add_argument("file")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("measure", help="the teach split")
    p.add_argument("file")
    p.add_argument("--sessions", type=int, default=None)
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("validate", help="the validate split — scores only")
    p.add_argument("file")
    p.add_argument("--sessions", type=int, default=None)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("ledger", help="every hypothesis ever registered")
    p.set_defaults(func=cmd_ledger)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except HypothesisError as exc:
        print(f"\n  FAIL  {exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
