#!/usr/bin/env python3
"""
make_split.py — write `tests/data_split.yaml`. Run ONCE, commit, never re-run casually.

    python tools/make_split.py                 # writes the file if absent
    python tools/make_split.py --force         # overwrite. Loud, and logged.

## Why this file has to exist before the teaching loop, not after

Spec 11 §D1: *"Write the split to `tests/data_split.yaml` and commit it **before the
first run.**"*

The teaching loop's whole danger is that it feels like progress. You look at a move the
engine missed, add a rule that catches it, repeat — and end up with a system that
explains the past perfectly and has learned nothing. The only defence that actually
works is data the rule was never allowed to see. That defence is worth exactly nothing
if the split is drawn *after* the first measurement, because by then the choice of split
is itself a tuned parameter.

So this runs first, on nothing but the calendar and a rule stated in advance.

## The rule, stated before the assignment was computed

1. **Split by month, never by day.** Spec 11 §D1: random day-splitting scatters a single
   trending week across all three sets, so a rule fitted to that regime scores well
   everywhere. Months keep regimes intact.

2. **Every month containing a chart the trader has already marked goes to `teach`.**
   `reports/charts/selection.json` names 10 sessions rendered for the P1 overlap gate.
   Its own note only asked for those *days* to be excluded from holdout. That is too
   weak. Having seen 2026-07-21 tells you what July 2026 felt like, and regime is a
   month-scale property — the same property §D1 blocks by month to protect. Day-level
   exclusion would leave the leak it was written to stop. So contamination is inherited
   by the whole month.

3. **The remaining months are dealt by chronological index mod 5**: `{0,1,2} -> teach`,
   `{3} -> validate`, `{4} -> holdout`. No seed, no shuffle, nothing to tune. Dealing by
   position rather than by block spreads all three sets across the full three years, so
   validate and holdout each see 2023, 2024, 2025 and 2026 rather than one era.

That yields more than the nominal 60/20/20 in `teach`, because rule 2 forces ten months
there. The cost is real and it is the right way round: a smaller validate set makes it
*harder* to certify a rule, and the alternative — putting months the trader has seen
into holdout — makes it easier while looking identical in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

SPLIT_PATH = REPO_ROOT / "tests" / "data_split.yaml"
SELECTION_PATH = REPO_ROOT / "reports" / "charts" / "selection.json"
DATA_DIR = REPO_ROOT / "data" / "NIFTY_BANK"

TEACH, VALIDATE, HOLDOUT = "teach", "validate", "holdout"


def months_available() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.parquet"))


def contaminated_months() -> tuple[list[str], list[str]]:
    """Months containing a session the trader has already looked at."""
    if not SELECTION_PATH.exists():
        return [], []
    data = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    days = [s["day"] for s in data.get("sessions", [])]
    return sorted({d[:7] for d in days}), sorted(days)


def assign(months: list[str], contaminated: set[str]) -> dict[str, str]:
    """Rule 2 then rule 3. Deterministic: same calendar in, same split out."""
    out: dict[str, str] = {}
    clean_index = 0
    for month in months:
        if month in contaminated:
            out[month] = TEACH
            continue
        slot = clean_index % 5
        out[month] = TEACH if slot < 3 else (VALIDATE if slot == 3 else HOLDOUT)
        clean_index += 1
    return out


def digest(assignment: dict[str, str]) -> str:
    payload = "\n".join(f"{m}={s}" for m, s in sorted(assignment.items()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def render(assignment: dict[str, str], contaminated: list[str], days: list[str]) -> str:
    counts = Counter(assignment.values())
    total = len(assignment)
    lines = [
        "# DATA SPLIT — spec 11 §D1. Written before the first teaching-loop measurement.",
        "#",
        "# DO NOT EDIT BY HAND, and do not regenerate to 'improve' a result. The whole",
        "# value of this file is that it was fixed before anyone knew what it would cost.",
        "#",
        "# teach     you may examine every individual miss in detail",
        "# validate  scores only. Never read an individual case here.",
        "# holdout   touched ONCE, at the very end, ever — and every read is logged to",
        "#           HOLDOUT-ACCESS.md by src/learning/split.py. There is no quiet read.",
        "#",
        "# Assignment rule, fixed in advance (tools/make_split.py):",
        "#   1. split by month, never by day",
        "#   2. any month containing an already-marked chart -> teach",
        "#   3. remaining months, chronological index mod 5: {0,1,2}->teach 3->validate"
        " 4->holdout",
        "",
        f"generated: \"{datetime.now().astimezone().isoformat(timespec='seconds')}\"",
        "generator: \"tools/make_split.py\"",
        f"digest: \"{digest(assignment)}\"",
        "",
        "counts:",
        f"  months_total: {total}",
        f"  teach: {counts[TEACH]}",
        f"  validate: {counts[VALIDATE]}",
        f"  holdout: {counts[HOLDOUT]}",
        "",
        "# Months quarantined into `teach` by rule 2 — the trader has seen a chart from",
        "# each of these. They may be taught on; they may never certify anything.",
        "contaminated_months:",
    ]
    lines += [f"  - \"{m}\"" for m in contaminated] or ["  []"]
    lines += ["", "# The specific sessions rendered for the P1 overlap gate.",
              "seen_sessions:"]
    lines += [f"  - \"{d}\"" for d in days] or ["  []"]

    for name in (TEACH, VALIDATE, HOLDOUT):
        lines += ["", f"{name}:"]
        lines += [f"  - \"{m}\"" for m, s in sorted(assignment.items()) if s == name]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing split. Every measurement taken under the "
                         "old split becomes uncitable.")
    args = ap.parse_args(argv)

    if SPLIT_PATH.exists() and not args.force:
        print(f"{SPLIT_PATH.relative_to(REPO_ROOT)} already exists — refusing to redraw "
              f"it.\nA split redrawn after a measurement is not a split, it is a "
              f"parameter.\nUse --force only if nothing has been measured yet.",
              file=sys.stderr)
        return 1

    months = months_available()
    if not months:
        print(f"no data in {DATA_DIR}", file=sys.stderr)
        return 2
    contaminated, days = contaminated_months()
    assignment = assign(months, set(contaminated))

    SPLIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_PATH.write_text(render(assignment, contaminated, days), encoding="utf-8")

    counts = Counter(assignment.values())
    print(f"wrote {SPLIT_PATH.relative_to(REPO_ROOT)}   digest {digest(assignment)}")
    print(f"  months            {len(months)}  ({months[0]} .. {months[-1]})")
    print(f"  contaminated      {len(contaminated)} -> forced into teach")
    print(f"  teach             {counts[TEACH]}")
    print(f"  validate          {counts[VALIDATE]}")
    print(f"  holdout           {counts[HOLDOUT]}")
    print("\nCommit this before measuring anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
