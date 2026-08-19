"""
Reading the split — and making the holdout expensive to read. Spec 11 §D1 and §8.

`tests/data_split.yaml` is only a defence if the code that consumes it cannot quietly
reach past the fence. Three mechanisms, in increasing order of how much they matter:

* `teach()` and `validate()` are ordinary calls.
* `holdout()` **requires a written reason** and appends an entry to `HOLDOUT-ACCESS.md`
  before returning a single date. Spec 11 §8's `test_holdout_access_is_logged` asks for
  exactly this. The point is not that the log stops you — it is that after the second
  entry appears in a file you read every week, you cannot tell yourself the holdout is
  still clean.
* `validate()` returns dates, never per-case detail. Spec 11 §D1: *"you may only run
  scores here, never read individual misses."* That is a discipline this module cannot
  enforce mechanically, so it is stated at the call site instead of pretended.

The log lives in its own file rather than being appended to `DECISIONS.md`. `DECISIONS.md`
is hand-maintained prose and a program that edits it will eventually corrupt it; a
machine-appended log belongs somewhere a machine owns.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPLIT_PATH = REPO_ROOT / "tests" / "data_split.yaml"
ACCESS_LOG = REPO_ROOT / "HOLDOUT-ACCESS.md"

TEACH, VALIDATE, HOLDOUT = "teach", "validate", "holdout"


class SplitError(RuntimeError):
    """Refusing to measure rather than measuring against a fence that is not there."""


@dataclass(frozen=True)
class Split:
    digest: str
    months: dict[str, str]                  # "2025-03" -> "teach"
    contaminated: frozenset[str]
    seen_sessions: frozenset[str]

    # ── membership ───────────────────────────────────────────────────────────
    def bucket_of(self, day: date | str) -> str:
        month = str(day)[:7]
        try:
            return self.months[month]
        except KeyError:
            raise SplitError(
                f"{day} is in {month}, which is not in the split. The split was drawn "
                f"over the downloaded calendar; new data means a new split, and a new "
                f"split invalidates every measurement taken under the old one.") from None

    def is_seen(self, day: date | str) -> bool:
        """True for the specific sessions already rendered as charts."""
        return str(day) in self.seen_sessions

    def months_in(self, bucket: str) -> list[str]:
        return sorted(m for m, b in self.months.items() if b == bucket)

    # ── the three accessors ──────────────────────────────────────────────────
    def teach(self, days: list[date]) -> list[date]:
        return [d for d in days if self.bucket_of(d) == TEACH]

    def validate(self, days: list[date]) -> list[date]:
        """Scores only. Never render, print or read an individual case from these —
        spec 11 §D1. Nothing here can enforce that; it is on the caller."""
        return [d for d in days if self.bucket_of(d) == VALIDATE]

    def holdout(self, days: list[date], *, reason: str, hypothesis_id: str = "") -> list[date]:
        """*"Touched ONCE, at the very end, ever."*

        Every call appends to `HOLDOUT-ACCESS.md`. If that file has more than one entry
        for a given rule set, the holdout has stopped being a holdout — spec 11 §7 is
        explicit that the response to a bad holdout result is to revert, never to re-run
        the loop with the holdout as the new validate.
        """
        if not reason or len(reason.strip()) < 20:
            raise SplitError(
                "holdout access needs a written reason of at least 20 characters, and it "
                "goes into HOLDOUT-ACCESS.md permanently.\n"
                "If the reason is hard to write, that is the signal — spec 11 §7 says the "
                "holdout is read once, after the stopping rules have already fired.")
        selected = [d for d in days if self.bucket_of(d) == HOLDOUT]
        _log_access(reason=reason.strip(), hypothesis_id=hypothesis_id,
                    digest=self.digest, n_sessions=len(selected))
        return selected


def _log_access(*, reason: str, hypothesis_id: str, digest: str, n_sessions: int) -> None:
    if not ACCESS_LOG.exists():
        ACCESS_LOG.write_text(
            "# HOLDOUT ACCESS LOG\n\n"
            "Appended by `src/learning/split.py`. Spec 11 §8 "
            "`test_holdout_access_is_logged`.\n\n"
            "> The holdout is touched once, at the very end, ever. A second entry below "
            "means\n> the holdout is no longer a holdout, and spec 11 §7's answer is to "
            "revert the\n> rule set — not to re-run the loop with the holdout as a new "
            "validate set.\n\n"
            "| when | split digest | hypothesis | sessions | reason |\n"
            "|---|---|---|---|---|\n", encoding="utf-8")
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    row = (f"| {stamp} | `{digest}` | {hypothesis_id or '—'} | {n_sessions} | "
           f"{reason.replace('|', '/')} |\n")
    with ACCESS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(row)


def access_count() -> int:
    if not ACCESS_LOG.exists():
        return 0
    return sum(1 for line in ACCESS_LOG.read_text(encoding="utf-8").splitlines()
               if line.startswith("| 2") or line.startswith("| 1"))


# ─────────────────────────────────────────────────────────────────────────────
def load_split(path: Path | None = None) -> Split:
    import yaml

    path = path or SPLIT_PATH
    if not path.exists():
        raise SplitError(
            f"{path} does not exist. Spec 11 §D1 requires the split to be written and "
            f"committed BEFORE the first measurement.\n"
            f"    python tools/make_split.py\n"
            f"A split drawn after a result is a tuned parameter wearing a fence's "
            f"clothes.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    months: dict[str, str] = {}
    for bucket in (TEACH, VALIDATE, HOLDOUT):
        for month in raw.get(bucket) or []:
            if month in months:
                raise SplitError(f"{month} appears in two buckets — the split overlaps")
            months[month] = bucket
    if not months:
        raise SplitError(f"{path} contains no month assignments")

    payload = "\n".join(f"{m}={b}" for m, b in sorted(months.items()))
    computed = hashlib.sha256(payload.encode()).hexdigest()[:16]
    stated = str(raw.get("digest", ""))
    if stated and stated != computed:
        raise SplitError(
            f"split digest mismatch: file says {stated}, contents hash to {computed}.\n"
            f"The month lists were edited by hand after generation. Every measurement "
            f"citing {stated} refers to a split that no longer exists.")

    return Split(digest=computed, months=months,
                 contaminated=frozenset(raw.get("contaminated_months") or []),
                 seen_sessions=frozenset(str(d) for d in (raw.get("seen_sessions") or [])))
