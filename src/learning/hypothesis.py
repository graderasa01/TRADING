"""
Turning "yahan aisa hota hai" into a claim that is allowed to be wrong.

## What this is for

The trader can see things on a chart that do not survive being typed into a chat window.
The way to move that knowledge into the engine is **not** to describe it better. It is to
make it *falsifiable*: state it as a predicate over candles, say in advance what it
predicts, and then let three years of data answer.

Everything here exists to protect one number — the rate at which a claim is right — from
the four ways it gets inflated:

**1. Hindsight.** A threshold chosen after seeing the result is not a finding. So a
hypothesis is registered with a digest over its claim fields *before* `measure` will run,
and editing the threshold afterwards invalidates the digest. The tool refuses.

**2. The missing base rate.** *"Compression ke baad 61% baar continue hota hai"* is not a
finding if price continues 60% of the time anyway. Every measurement reports the
conditional rate **and** the base rate over all comparable spans, and the verdict is
driven by the difference, never by the conditional rate alone.

**3. Multiple comparisons.** Test twenty ideas against the same three years and one will
clear p<0.05 by luck. The ledger counts every hypothesis ever registered — *including the
dead ones*, which is the only reason the count means anything — and the significance
threshold is divided by it.

**4. Fitting to data you have already seen.** The predicate runs on `teach`. Certification
runs on `validate`, which the split fenced off before any of this was measured.
`tools/hypothesis.py` will not report a validate score until the teach result exists,
because a claim tested on both at once has no out-of-sample left.

## What it deliberately does not do

It does not decide whether the mechanism is real. Spec 11 §6: *"Use the model to generate
hypotheses. Use the held-out data to kill them. Never let the model do both jobs."* This
module is the killing half.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from src.domain.models import ZERO, Candle
from src.reasoning.vocabulary import BY_NAME, UNOBSERVABLE_BY_NAME, Span

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEDGER_DIR = REPO_ROOT / "learning"
HYPOTHESIS_DIR = LEDGER_DIR / "hypotheses"

OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
       ">": lambda a, b: a > b, "<": lambda a, b: a < b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


class HypothesisError(RuntimeError):
    """Refusing to produce a number that would be misread."""


# ─────────────────────────────────────────────────────────────────────────────
# the claim
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Clause:
    capability: str
    op: str
    value: str

    def holds(self, span: Span) -> bool | None:
        cap = BY_NAME.get(self.capability)
        if cap is None or cap.fn is None:
            return None
        measured = cap.fn(span)
        if measured is None:
            return None
        return OPS[self.op](measured, Decimal(self.value))

    def __str__(self) -> str:
        cap = BY_NAME.get(self.capability)
        question = cap.question if cap else "?"
        return f"{self.capability} {self.op} {self.value}    ({question})"


# Every one of these is measured in units of the ATR ending BEFORE the span — never the
# span's own range. See `_outcome_holds`: normalising by a quantity the predicate selects
# on manufactures an 8x edge out of a random walk.
OUTCOMES = {
    "continuation": "price travels +k x ATR in the span's own direction before -k x ATR "
                    "against it, within `horizon` candles",
    "reversal": "price travels k x ATR AGAINST the span's direction before k x ATR with "
                "it, within `horizon` candles",
    "expansion": "the next `horizon` candles' mean range >= k x the ATR BEFORE the span",
    "quiet": "the next `horizon` candles' mean range <= k x the ATR BEFORE the span",
}


@dataclass
class Hypothesis:
    id: str
    stated: str                       # the trader's own words, unedited
    mechanism: str                    # WHY the market does this — spec 11 §D2
    clauses: list[Clause]
    span_len: int
    outcome: str
    horizon: int
    k: str
    predicted_rate: str               # what the trader expects, BEFORE measuring
    author: str = ""
    registered_at: str = ""
    registered_digest: str = ""
    notes: str = ""
    status: str = "draft"             # draft | registered | measured | validated | dead
    # Results are written back by `measure`/`validate` and are NOT part of the digest —
    # recording an outcome must never look like tampering with the claim. They are stored
    # so that a hypothesis which failed cannot quietly leave the ledger; the
    # multiple-comparison budget is only honest if the dead ones stay in it.
    results: dict[str, Any] = field(default_factory=dict)

    # ── the digest is the whole preregistration mechanism ────────────────────
    def claim_digest(self) -> str:
        payload = json.dumps({
            "stated": self.stated.strip(),
            "mechanism": self.mechanism.strip(),
            "clauses": [asdict(c) for c in self.clauses],
            "span_len": self.span_len, "outcome": self.outcome,
            "horizon": self.horizon, "k": str(self.k),
            "predicted_rate": str(self.predicted_rate),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def check_registered(self) -> None:
        if not self.registered_digest:
            raise HypothesisError(
                f"{self.id} has not been registered.\n"
                f"    python tools/hypothesis.py register learning/hypotheses/{self.id}.yaml\n"
                f"Registration freezes the claim. Measuring first and writing the "
                f"threshold afterwards is not a finding, it is a description of the "
                f"sample.")
        current = self.claim_digest()
        if current != self.registered_digest:
            raise HypothesisError(
                f"{self.id} was edited after registration.\n"
                f"    registered as  {self.registered_digest}\n"
                f"    now hashes to  {current}\n"
                f"A threshold moved after seeing a result is fitted to that result. Either\n"
                f"revert the edit, or register the changed claim as a NEW hypothesis — it\n"
                f"then counts against the multiple-comparison budget, which is the point.")

    def unobservable_clause(self) -> str | None:
        for clause in self.clauses:
            if clause.capability in UNOBSERVABLE_BY_NAME:
                return clause.capability
        return None

    def unbuilt_clauses(self) -> list[str]:
        return [c.capability for c in self.clauses
                if c.capability in BY_NAME and BY_NAME[c.capability].fn is None]

    def unknown_clauses(self) -> list[str]:
        return [c.capability for c in self.clauses
                if c.capability not in BY_NAME and c.capability not in UNOBSERVABLE_BY_NAME]


# ─────────────────────────────────────────────────────────────────────────────
# measuring
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Result:
    """Both numbers, always. A conditional rate without its base rate is the single most
    common way a backtest tells a flattering lie."""
    events: int = 0                   # spans where the predicate held
    hits: int = 0                     # ... and the outcome followed
    base_spans: int = 0               # all comparable spans
    base_hits: int = 0
    sessions: int = 0
    undefined: int = 0                # spans a clause could not be computed on
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.events if self.events else 0.0

    @property
    def base_rate(self) -> float:
        return self.base_hits / self.base_spans if self.base_spans else 0.0

    @property
    def lift(self) -> float:
        return (self.rate / self.base_rate) if self.base_rate else 0.0

    @property
    def firing_rate(self) -> float:
        return self.events / self.base_spans if self.base_spans else 0.0

    def z_and_p(self) -> tuple[float, float]:
        """Two-proportion z-test, normal approximation.

        Approximation, not exactness — the spans overlap, so the samples are not
        independent and the true p is larger than this one. That direction matters: this
        number is *optimistic*, and it is reported as a floor on doubt rather than a
        certificate.
        """
        n1, n2 = self.events, self.base_spans - self.events
        if n1 < 2 or n2 < 2:
            return 0.0, 1.0
        x1, x2 = self.hits, self.base_hits - self.hits
        p1, p2 = x1 / n1, x2 / n2
        pooled = (x1 + x2) / (n1 + n2)
        denom = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        if denom == 0:
            return 0.0, 1.0
        z = (p1 - p2) / denom
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        return z, p

    def wilson_interval(self, confidence: float = 0.95) -> tuple[float, float]:
        """Wilson score interval — behaves at small n, where the normal interval runs off
        the end of [0, 1] and quietly implies certainty it does not have."""
        n = self.events
        if n == 0:
            return 0.0, 1.0
        z = 1.959963985 if confidence == 0.95 else 2.575829304
        p = self.rate
        denom = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denom
        margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return max(0.0, centre - margin), min(1.0, centre + margin)


def verdict_for(result: Result, alpha: float) -> tuple[str, str]:
    """(label, explanation). Extracted from the printing so it can be tested.

    The direction branch exists because the first real run got it wrong: `coil-expansion`
    scored 4.1% against a 16.5% base — a large, highly significant effect running the
    OPPOSITE way to the claim — and the verdict read "SURVIVES teach". Checking only
    significance and magnitude congratulates you for being precisely wrong.
    """
    _, p = result.z_and_p()
    lo, hi = result.wilson_interval()
    edge = result.rate - result.base_rate

    if result.events < 30:
        return "INSUFFICIENT", (
            f"{result.events} events. Below about 30 this is a story, not a rate.")
    if lo <= result.base_rate <= hi:
        return "NO EDGE", (
            "the base rate sits inside your own confidence interval. The predicate "
            "selects spans; it does not select outcomes.")
    if p >= alpha:
        return "NOT SIGNIFICANT", (
            f"p {p:.5f} against a corrected threshold of {alpha:.5f}.")
    if edge < 0:
        return "CONTRADICTED", (
            f"the effect is real and it runs BACKWARDS — matching spans see the outcome "
            f"{-edge * 100:.1f}pp LESS often than spans in general. The mechanism may "
            f"still be true with the prediction inverted, but that is a NEW hypothesis "
            f"and costs a new slot. It is not an edit to this one.")
    if edge < 0.03:
        return "REAL BUT SMALL", (
            f"a {edge * 100:+.1f}pp edge survives costs only if R is large. CLAUDE.md "
            f"§11: the round trip is 44-64% of a 25-point R.")
    return "SURVIVES teach", (
        "nothing is proven yet. It has earned a validate run.")


def _atr_series(candles: Sequence[Candle], period: int = 20) -> list[Decimal | None]:
    """The D-012 convention: simple mean of `high - low`, session-scoped, no carry."""
    out: list[Decimal | None] = []
    ranges: list[Decimal] = []
    for k in candles:
        ranges.append(k.range)
        window = ranges[-period:]
        out.append(sum(window) / len(window) if len(window) >= period else None)
    return out


def _outcome_holds(h: Hypothesis, span: Span, ref_atr: Decimal) -> bool | None:
    """`ref_atr` is the ATR **before** the span, and that is not a detail.

    The first version of `expansion` asked whether the next candles averaged more than
    `k x the span's own mean range`. On a random walk that predicate scored 12.0% against
    a 1.5% base — an 8x lift with no edge present, and `test_reports_no_edge_on_noise`
    caught it.

    The reason is that the outcome was normalised by the same quantity the predicate
    selected on. Choose quiet spans, and "the next candles are twice as loud as this
    span" becomes nearly free, because the denominator is what you selected for. That is
    regression to the mean wearing a discovery's clothes, and it is the single easiest
    way for this whole tool to produce confident nonsense.

    So every outcome is measured against the ATR *ending before the span starts*, which
    the predicate cannot select on. The question becomes "after a quiet stretch, does the
    market get louder **than it was before the stretch**" — which is the thing a trader
    actually means, and is answerable.
    """
    after = span.after(h.horizon)
    if len(after) < h.horizon:
        return None
    k = Decimal(str(h.k))
    atr = ref_atr

    if h.outcome in ("continuation", "reversal"):
        net = span.last.c - span.first.o
        if net == ZERO:
            return None
        direction = 1 if net > ZERO else -1
        if h.outcome == "reversal":
            direction = -direction
        start = span.last.c
        target, stop = start + direction * k * atr, start - direction * k * atr
        for candle in after:
            hit_target = candle.h >= target if direction > 0 else candle.l <= target
            hit_stop = candle.l <= stop if direction > 0 else candle.h >= stop
            if hit_target and hit_stop:
                return None            # both inside one candle — the 1m feed cannot order them
            if hit_target:
                return True
            if hit_stop:
                return False
        return False

    later = [c.range for c in after]
    if not later:
        return None
    ratio = (sum(later) / len(later)) / atr
    return ratio >= k if h.outcome == "expansion" else ratio <= k


def measure_session(h: Hypothesis, candles: Sequence[Candle], day: date,
                    result: Result, *, collect_examples: int = 0) -> None:
    """One session. Every span of `span_len` is a trial — both for the predicate and for
    the base rate, so the two rates are computed over exactly the same population."""
    atrs = _atr_series(candles)
    n = len(candles)
    for hi in range(h.span_len - 1, n):
        lo = hi - h.span_len + 1
        atr = atrs[hi]
        ref_atr = atrs[lo - 1] if lo > 0 else None
        if atr is None or atr <= ZERO or ref_atr is None or ref_atr <= ZERO:
            continue
        span = Span(candles, lo, hi, atr)
        outcome = _outcome_holds(h, span, ref_atr)
        if outcome is None:
            continue

        result.base_spans += 1
        result.base_hits += int(outcome)

        verdicts = [c.holds(span) for c in h.clauses]
        if any(v is None for v in verdicts):
            result.undefined += 1
            continue
        if not all(verdicts):
            continue

        result.events += 1
        result.hits += int(outcome)
        if len(result.examples) < collect_examples:
            result.examples.append({
                "day": str(day), "candles": [span.lo, span.hi],
                "time": span.last.open_time.strftime("%H:%M"),
                "outcome": outcome,
                "measured": {c.capability: _fmt(BY_NAME[c.capability].fn(span))
                             for c in h.clauses if BY_NAME.get(c.capability)
                             and BY_NAME[c.capability].fn},
            })


def _fmt(value: Decimal | None) -> str:
    return "—" if value is None else f"{float(value):.3f}"


# ─────────────────────────────────────────────────────────────────────────────
# the ledger — the multiple-comparison budget only works if failures are in it
# ─────────────────────────────────────────────────────────────────────────────
def ledger_entries() -> list[dict[str, Any]]:
    import yaml

    if not HYPOTHESIS_DIR.exists():
        return []
    out = []
    for path in sorted(HYPOTHESIS_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw["_path"] = str(path.relative_to(REPO_ROOT))
        out.append(raw)
    return out


def registered_count() -> int:
    """Every hypothesis that was ever frozen, dead ones included.

    Counting only the survivors is how a 1-in-20 fluke becomes 'the one that worked'.
    """
    return sum(1 for e in ledger_entries() if e.get("registered_digest"))


def alpha_for(n_registered: int, family_alpha: float = 0.05) -> float:
    return family_alpha / max(1, n_registered)


def family_error_probability(n: int, alpha: float = 0.05) -> float:
    """P(at least one false positive) across n independent tests at `alpha`."""
    return 1 - (1 - alpha) ** max(0, n)


# ─────────────────────────────────────────────────────────────────────────────
def load_hypothesis(path: Path) -> Hypothesis:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [f for f in ("id", "stated", "mechanism", "clauses", "outcome") if not raw.get(f)]
    if missing:
        raise HypothesisError(f"{path.name} is missing required field(s): {missing}")
    if raw["outcome"] not in OUTCOMES:
        raise HypothesisError(
            f"outcome '{raw['outcome']}' is not one of {sorted(OUTCOMES)}.\n"
            f"The menu is fixed on purpose — an outcome invented after the fact is the "
            f"easiest of all the ways to manufacture a result.")
    clauses = [Clause(**c) for c in raw["clauses"]]
    for clause in clauses:
        if clause.op not in OPS:
            raise HypothesisError(f"unknown operator '{clause.op}' — use one of {sorted(OPS)}")
    return Hypothesis(
        id=str(raw["id"]), stated=str(raw["stated"]), mechanism=str(raw["mechanism"]),
        clauses=clauses, span_len=int(raw.get("span_len", 1)),
        outcome=str(raw["outcome"]), horizon=int(raw.get("horizon", 10)),
        k=str(raw.get("k", "1.0")), predicted_rate=str(raw.get("predicted_rate", "")),
        author=str(raw.get("author", "")), registered_at=str(raw.get("registered_at", "")),
        registered_digest=str(raw.get("registered_digest", "")),
        notes=str(raw.get("notes", "")), status=str(raw.get("status", "draft")),
        results=dict(raw.get("results") or {}))


def record_result(h: Hypothesis, bucket: str, result: Result, verdict: str) -> Hypothesis:
    h.results[bucket] = {
        "sessions": result.sessions, "spans": result.base_spans,
        "events": result.events, "hits": result.hits,
        "rate_pct": round(result.rate * 100, 2),
        "base_rate_pct": round(result.base_rate * 100, 2),
        "edge_pp": round((result.rate - result.base_rate) * 100, 2),
        "p": round(result.z_and_p()[1], 8), "verdict": verdict,
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if verdict in ("CONTRADICTED", "NO EDGE", "NOT SIGNIFICANT", "INSUFFICIENT"):
        h.status = "dead" if bucket == "validate" else "measured"
    elif bucket == "validate":
        h.status = "validated"
    else:
        h.status = "measured"
    return h


def save_hypothesis(h: Hypothesis, path: Path) -> None:
    import yaml

    payload = asdict(h)
    payload["clauses"] = [asdict(c) for c in h.clauses]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def register(h: Hypothesis) -> Hypothesis:
    h.registered_at = datetime.now().astimezone().isoformat(timespec="seconds")
    h.registered_digest = h.claim_digest()
    h.status = "registered"
    return h
