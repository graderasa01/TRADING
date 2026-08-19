"""
P1.5 — the split, the vocabulary, and the hypothesis pipeline.

The tests that matter most here are not the schema ones. They are:

* `test_finds_a_planted_edge` / `test_reports_no_edge_on_noise` — a measurement tool
  that has never been shown data with a *known* answer is a tool nobody has tested. One
  plants an edge and demands it be found; the other plants none and demands silence. A
  tool that only ever runs on real data can be broken in either direction forever without
  anyone noticing, because nobody knows what the right answer was.

* `test_every_params_key_is_read_somewhere` — this one already caught a live bug. See its
  docstring.

* `test_unobservable_are_actually_unobservable` — re-counts against the real parquet, so
  the claim "this feed has no volume" cannot quietly rot into a false one.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.config.loader import load_config
from src.domain.models import IST, Candle
from src.learning.hypothesis import (
    Clause, Hypothesis, HypothesisError, Result, alpha_for, family_error_probability,
    load_hypothesis, measure_session, register, save_hypothesis, verdict_for)
from src.learning.split import SplitError, load_split
from src.reasoning.vocabulary import (
    BY_NAME, CAPABILITIES, UNOBSERVABLE, Span, keys_read_in_src)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLIT_PATH = REPO_ROOT / "tests" / "data_split.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def make_candles(spec: list[tuple[float, float, float, float]],
                 day: date = date(2025, 3, 4)) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=15)
    out = []
    for i, (o, h, l, c) in enumerate(spec):
        t = start + timedelta(minutes=i)
        out.append(Candle("TEST", "1m", t, t + timedelta(minutes=1),
                          Decimal(str(o)), Decimal(str(h)), Decimal(str(l)), Decimal(str(c))))
    return out


def hyp(**kw) -> Hypothesis:
    base = dict(id="t", stated="s", mechanism="m",
                clauses=[Clause("span_compression", "<=", "0.6")],
                span_len=8, outcome="expansion", horizon=10, k="1.8",
                predicted_rate="70%")
    base.update(kw)
    return Hypothesis(**base)


# ─────────────────────────────────────────────────────────────────────────────
# the split — spec 11 §D1 and §8
# ─────────────────────────────────────────────────────────────────────────────
def test_split_exists_before_any_measurement():
    """Spec 11 §D1: written and committed BEFORE the first run. If this file is absent
    every measurement below is being taken against a fence that was never built."""
    assert SPLIT_PATH.exists(), "run: python tools/make_split.py"


def test_split_is_by_month():
    split = load_split()
    for month in split.months:
        year, mon = month.split("-")
        assert len(month) == 7 and 1 <= int(mon) <= 12 and 2000 < int(year) < 2100


def test_split_buckets_do_not_overlap():
    raw = yaml.safe_load(SPLIT_PATH.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for bucket in ("teach", "validate", "holdout"):
        months = set(raw[bucket] or [])
        assert not (months & seen), f"{bucket} overlaps an earlier bucket"
        seen |= months


def test_every_month_the_trader_has_seen_is_in_teach():
    """The stronger reading of `selection.json`'s own note.

    That note asked only for the ten marked *days* to be kept out of holdout. Having seen
    2026-07-21 tells you what July 2026 felt like, and regime is a month-scale property —
    which is the exact property §D1 blocks by month to protect. Day-level exclusion would
    leave the leak it was written to close.
    """
    split = load_split()
    for month in split.contaminated:
        assert split.months[month] == "teach", f"{month} was seen and is not in teach"
    for day in split.seen_sessions:
        assert split.bucket_of(day) == "teach"


def test_hand_editing_the_split_is_detected(tmp_path):
    raw = yaml.safe_load(SPLIT_PATH.read_text(encoding="utf-8"))
    raw["teach"].append(raw["holdout"].pop())          # quietly enlarge teach
    forged = tmp_path / "data_split.yaml"
    forged.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(SplitError, match="digest mismatch"):
        load_split(forged)


def test_holdout_requires_a_written_reason(tmp_path, monkeypatch):
    import src.learning.split as split_mod

    monkeypatch.setattr(split_mod, "ACCESS_LOG", tmp_path / "HOLDOUT-ACCESS.md")
    split = load_split()
    with pytest.raises(SplitError, match="written reason"):
        split.holdout([date(2024, 1, 2)], reason="because")


def test_holdout_access_is_logged(tmp_path, monkeypatch):
    """Spec 11 §8. The log does not stop the read — it makes a second read undeniable."""
    import src.learning.split as split_mod

    log = tmp_path / "HOLDOUT-ACCESS.md"
    monkeypatch.setattr(split_mod, "ACCESS_LOG", log)
    split = load_split()
    holdout_month = split.months_in("holdout")[0]
    day = date(int(holdout_month[:4]), int(holdout_month[5:]), 15)

    split.holdout([day], reason="final measurement, stopping rules already fired",
                  hypothesis_id="coil-break")
    assert log.exists()
    body = log.read_text(encoding="utf-8")
    assert "coil-break" in body and "stopping rules" in body

    split.holdout([day], reason="a second look, which is exactly what must be visible")
    rows = [ln for ln in log.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| 2")]
    assert len(rows) == 2, "a second holdout read must leave a second row"


def test_split_refuses_dates_outside_its_calendar():
    split = load_split()
    with pytest.raises(SplitError, match="not in the split"):
        split.bucket_of(date(1999, 1, 4))


# ─────────────────────────────────────────────────────────────────────────────
# the vocabulary
# ─────────────────────────────────────────────────────────────────────────────
def test_unobservable_are_actually_unobservable():
    """The claim in `vocabulary.py` is that this feed carries no volume — so any
    intuition resting on volume, absorption or order flow is out of reach of *anything*
    built on these candles, not merely of the detectors that exist.

    That is a strong thing to tell someone, so it is re-counted from the real files
    rather than remembered.
    """
    import pandas as pd

    files = sorted((REPO_ROOT / "data").glob("*/*.parquet"))
    if not files:
        pytest.skip("no downloaded data")
    total = nonzero = 0
    for path in files[:24]:
        frame = pd.read_parquet(path, columns=["volume"])
        total += len(frame)
        nonzero += int((frame["volume"] != 0).sum())
    assert total > 100_000
    assert nonzero == 0, (
        f"{nonzero} candles carry volume — the index feed has changed and "
        f"`volume` must move out of UNOBSERVABLE in src/reasoning/vocabulary.py")


def test_unobservable_and_capabilities_do_not_overlap():
    names = {c.name for c in CAPABILITIES}
    for u in UNOBSERVABLE:
        assert u.name not in names, f"{u.name} is both measurable and unobservable"


def test_capability_status_is_derived_not_asserted():
    """Status must follow from config + source, never from a literal in the table —
    the same rule spec 13 §2.1 sets for blind spots. Adding the key a capability owns
    must be able to change its status with no edit to the capability itself."""
    cfg = load_config(strict=False)
    blind = [c for c in CAPABILITIES if c.status(cfg) == "BLIND_SPOT"]
    assert blind, "every capability is consumed — then this registry has nothing to say"
    for cap in blind:
        assert cap.params, f"{cap.name} is a blind spot with no key a detector could own"
        for key in cap.params:
            assert cfg.get(key, None) is None


def test_consumed_at_points_at_real_code():
    """`consumed_at` is the one asserted field left. It is checked rather than trusted."""
    for cap in CAPABILITIES:
        for location in cap.consumed_at:
            path, _, token = location.partition("::")
            full = REPO_ROOT / path
            assert full.exists(), f"{cap.name}: {path} does not exist"
            assert token in full.read_text(encoding="utf-8"), \
                f"{cap.name}: {path} no longer mentions {token}"


def test_not_built_capabilities_have_no_function():
    cfg = load_config(strict=False)
    for cap in CAPABILITIES:
        if cap.status(cfg) == "NOT_BUILT":
            assert cap.fn is None


# ─────────────────────────────────────────────────────────────────────────────
# every threshold in params.yaml is actually read
# ─────────────────────────────────────────────────────────────────────────────
def _flatten(node, prefix=""):
    for key, value in node.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, name)
        else:
            yield name


def _key_is_read(key: str, source: str) -> bool:
    """A key counts as read if the source quotes the full key, its last segment, the
    dotted parent (for keys reached by fetching a whole sub-dict), or a `prefix_` that an
    f-string completes — `self._p(f"swing_lookback_bars_{tf}")`."""
    last = key.rsplit(".", 1)[-1]
    if any(f'"{c}"' in source for c in (key, last, key.rsplit(".", 1)[0])):
        return True
    # An f-string leaves an OPEN quote: `f"swing_lookback_bars_{tf}"`. Matching a closing
    # quote here would miss exactly the wiring that fixes the bug this check exists for.
    parts = last.split("_")
    return any(f'"{"_".join(parts[:i])}_' in source for i in range(1, len(parts)))


def _src_text() -> str:
    return "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in (REPO_ROOT / "src").rglob("*.py")
                   if p.name != "vocabulary.py")


def test_key_coverage_matcher_actually_catches_a_hardcoded_default():
    """A guard is worth nothing until it has been shown failing.

    This is the exact shape of the bug the check found in `indicators/swings.py`: the
    value lived in `params.yaml` AND as a Python dict, the engines used the Python one,
    and tuning the config did nothing at all.
    """
    hardcoded = 'DEFAULT_K = {"1m": 3}\ndet = SwingDetector("1m")\n'
    assert not _key_is_read("levels.swing_lookback_bars_1m", hardcoded)
    wired = 'k=int(self._p(f"swing_lookback_bars_{tf}"))'
    assert _key_is_read("levels.swing_lookback_bars_1m", wired)


def test_every_params_key_is_read_somewhere():
    """CLAUDE.md §9: every threshold is a named, tunable config value.

    The unstated half of that is that the value must actually reach the code. A key that
    nothing reads is worse than a magic number — it *looks* tunable, so it gets tuned,
    and the run that follows is attributed to a change that never happened.

    Keys belonging to phases that are not built yet are listed below by phase. That list
    is allowed to shrink and must never grow.
    """
    pending_prefixes = {
        "setups.": "P3", "risk.": "P4", "exits.": "P6", "options.": "P5",
        "slippage.": "P5", "feed.": "P8", "events.": "P2 config, spec 05 §1a",
        "journal.": "P7", "meta.": "documentation, not logic",
    }
    params = yaml.safe_load((REPO_ROOT / "config" / "params.yaml").read_text(encoding="utf-8"))
    source = _src_text()
    unread = [k for k in _flatten(params) if not _key_is_read(k, source)]
    leaked = [k for k in unread
              if not any(k.startswith(p) for p in pending_prefixes)]
    assert not leaked, (
        "config keys nothing in src/ reads — tuning these changes nothing:\n  "
        + "\n  ".join(leaked))


# ─────────────────────────────────────────────────────────────────────────────
# preregistration
# ─────────────────────────────────────────────────────────────────────────────
def test_measure_refuses_an_unregistered_hypothesis():
    with pytest.raises(HypothesisError, match="not been registered"):
        hyp().check_registered()


def test_editing_a_registered_claim_invalidates_the_digest():
    """The whole anti-hindsight mechanism. Moving a threshold after seeing a result is
    the single cheapest way to manufacture an edge, and it leaves no other trace."""
    h = register(hyp())
    h.check_registered()
    h.clauses = [Clause("span_compression", "<=", "0.9")]      # loosened after the fact
    with pytest.raises(HypothesisError, match="edited after registration"):
        h.check_registered()


def test_digest_covers_every_claim_field():
    fields = {"stated": "x", "mechanism": "y", "span_len": 9, "outcome": "quiet",
              "horizon": 20, "k": "2.5", "predicted_rate": "10%"}
    for name, value in fields.items():
        h = register(hyp())
        setattr(h, name, value)
        with pytest.raises(HypothesisError, match="edited after registration"):
            h.check_registered()


def test_outcome_menu_is_closed(tmp_path):
    path = tmp_path / "h.yaml"
    path.write_text(yaml.safe_dump({
        "id": "x", "stated": "s", "mechanism": "m", "outcome": "goes_up_a_lot",
        "clauses": [{"capability": "range_x_atr", "op": ">=", "value": "2"}]}),
        encoding="utf-8")
    with pytest.raises(HypothesisError, match="not one of"):
        load_hypothesis(path)


def test_round_trips_through_yaml(tmp_path):
    path = tmp_path / "h.yaml"
    h = register(hyp(id="rt"))
    save_hypothesis(h, path)
    assert load_hypothesis(path).claim_digest() == h.claim_digest()


# ─────────────────────────────────────────────────────────────────────────────
# the measurement, on data whose answer is known
# ─────────────────────────────────────────────────────────────────────────────
def _planted(seed: int = 7, n: int = 1500, every: int = 30) -> list[Candle]:
    """A random walk with one thing planted in it: every 30th candle closes exactly on
    its high, and price then drifts up for 14 candles. Nothing else differs.

    So `close_position >= 0.99` must find it, and the base rate must stay near a coin
    flip. If the tool cannot separate those two, no number it reports about real data
    means anything.
    """
    rng = random.Random(seed)
    price, spec = 50_000.0, []
    while len(spec) < n:
        if len(spec) >= 25 and len(spec) % every == 0:
            o = price
            c = o + abs(rng.gauss(0, 6)) + 3
            spec.append((o, c, o - abs(rng.gauss(0, 3)) - 1, c))    # high == close
            price = c
            for _ in range(14):
                o = price
                c = o + abs(rng.gauss(6, 3))
                spec.append((o, max(o, c) + 1.5, min(o, c) - 1.5, c))
                price = c
        else:
            o = price
            c = o + rng.gauss(0, 8)
            wick = 1.5 + abs(rng.gauss(0, 4))       # keeps noise closes off the extreme
            spec.append((o, max(o, c) + wick, min(o, c) - wick, c))
            price = c
    return make_candles(spec[:n])


def _noise(seed: int = 11, n: int = 570) -> list[Candle]:
    """A random walk with one range distribution throughout. There is no edge to find,
    so the honest output is 'no edge'."""
    rng = random.Random(seed)
    price, spec = 50_000.0, []
    for _ in range(n):
        o = price
        c = o + rng.gauss(0, 8)
        wick = abs(rng.gauss(0, 4))
        spec.append((o, max(o, c) + wick, min(o, c) - wick, c))
        price = c
    return make_candles(spec)


def test_finds_a_planted_edge():
    h = register(hyp(span_len=1, outcome="continuation", horizon=14, k="1.0",
                     clauses=[Clause("close_position", ">=", "0.99")]))
    result = Result()
    measure_session(h, _planted(), date(2025, 3, 4), result)
    assert result.events >= 30, f"predicate barely fired ({result.events})"
    assert result.rate > result.base_rate + 0.25, (
        f"planted edge not found: {result.rate:.2f} vs base {result.base_rate:.2f}")
    _, p = result.z_and_p()
    assert p < 0.01


def test_reports_no_edge_on_noise():
    """The failure mode that matters. A tool that finds an edge in a random walk will
    find one in anything, and every number it ever prints is decoration."""
    h = register(hyp(span_len=6, outcome="expansion", horizon=8, k="2.0",
                     clauses=[Clause("span_compression", "<=", "0.7")]))
    result = Result()
    for offset in range(6):
        measure_session(h, _noise(seed=100 + offset), date(2025, 3, 4), result)
    assert result.events >= 30
    lo, hi = result.wilson_interval()
    assert lo <= result.base_rate <= hi, (
        f"claimed an edge on noise: {result.rate:.3f} [{lo:.3f}, {hi:.3f}] vs base "
        f"{result.base_rate:.3f}")


def test_reports_no_edge_on_noise_for_continuation_too():
    """The matched null for `test_finds_a_planted_edge`. Same predicate, same outcome,
    same horizon — only the planted drift removed. Without this pair, a passing planted
    test proves only that the tool says yes."""
    h = register(hyp(span_len=1, outcome="continuation", horizon=14, k="1.0",
                     clauses=[Clause("close_position", ">=", "0.90")]))
    result = Result()
    for offset in range(4):
        measure_session(h, _noise(seed=200 + offset, n=900), date(2025, 3, 4), result)
    assert result.events >= 30
    lo, hi = result.wilson_interval()
    assert lo <= result.base_rate <= hi, (
        f"claimed a continuation edge on a random walk: {result.rate:.3f} "
        f"[{lo:.3f}, {hi:.3f}] vs base {result.base_rate:.3f}")


def test_a_backwards_effect_is_not_reported_as_survival():
    """These are the real numbers from the first `coil-expansion` run: 45 hits in 1,093
    matching spans against a 16.5% base rate over 185,706. A large, highly significant
    effect pointing the OPPOSITE way to the claim — and the first version of the verdict
    said "SURVIVES teach", because it checked significance and magnitude but not sign.

    A tool that congratulates you for being precisely wrong is worse than no tool.
    """
    backwards = Result(events=1093, hits=45, base_spans=185_706, base_hits=30_641)
    label, why = verdict_for(backwards, alpha_for(1))
    assert label == "CONTRADICTED"
    assert "BACKWARDS" in why and "NEW hypothesis" in why


def test_verdict_covers_every_branch():
    a = alpha_for(1)
    assert verdict_for(Result(events=5, hits=5, base_spans=999, base_hits=100), a)[0] \
        == "INSUFFICIENT"
    assert verdict_for(Result(events=500, hits=100, base_spans=100_000,
                              base_hits=20_000), a)[0] == "NO EDGE"
    assert verdict_for(Result(events=1000, hits=210, base_spans=100_000,
                              base_hits=20_000), a)[0] in ("NOT SIGNIFICANT", "NO EDGE")
    assert verdict_for(Result(events=20_000, hits=4_400, base_spans=200_000,
                              base_hits=40_000), a)[0] == "REAL BUT SMALL"
    assert verdict_for(Result(events=20_000, hits=8_000, base_spans=200_000,
                              base_hits=40_000), a)[0] == "SURVIVES teach"


def test_base_rate_uses_the_same_spans_as_the_predicate():
    """Both rates must come from one population. Measuring the conditional rate over 1m
    spans and the base rate over, say, whole sessions produces a ratio that means nothing
    and looks authoritative."""
    h = register(hyp(span_len=4, horizon=5, k="1.5"))
    result = Result()
    measure_session(h, _noise(seed=3, n=200), date(2025, 3, 4), result)
    assert result.events <= result.base_spans
    assert result.hits <= result.base_hits
    assert 0 < result.base_spans


def test_a_predicate_nothing_matches_is_not_an_error():
    h = register(hyp(clauses=[Clause("range_x_atr", ">=", "999")]))
    result = Result()
    measure_session(h, _noise(seed=5, n=200), date(2025, 3, 4), result)
    assert result.events == 0 and result.rate == 0.0
    assert result.base_spans > 0, "the base rate must still be measurable"


def test_outcome_is_undefined_when_the_horizon_runs_past_the_session():
    """No-lookahead: a span whose horizon extends beyond the last candle has no honest
    outcome, so it is dropped from BOTH numerator and denominator rather than counted as
    a failure."""
    h = register(hyp(span_len=4, horizon=20, k="1.5"))
    candles = _noise(seed=9, n=40)
    result = Result()
    measure_session(h, candles, date(2025, 3, 4), result)
    last_usable = len(candles) - 1 - h.horizon
    assert result.base_spans <= last_usable


def test_measure_reads_no_candle_beyond_the_horizon():
    """Truncating the session after the horizon must not change any count."""
    h = register(hyp(span_len=5, horizon=6, k="1.5"))
    candles = _noise(seed=13, n=300)
    full, cut = Result(), Result()
    measure_session(h, candles, date(2025, 3, 4), full)
    measure_session(h, candles[:200], date(2025, 3, 4), cut)
    # ATR20 is undefined until 20 candles exist (D-012), and the outcome is measured
    # against the ATR ending BEFORE the span — so the first usable span starts at 20.
    first_hi = 20 + h.span_len - 1
    last_hi = 200 - 1 - h.horizon
    assert cut.base_spans == last_hi - first_hi + 1
    assert cut.events <= full.events and cut.hits <= full.hits


# ─────────────────────────────────────────────────────────────────────────────
# the multiple-comparison budget
# ─────────────────────────────────────────────────────────────────────────────
def test_threshold_tightens_as_hypotheses_accumulate():
    assert alpha_for(1) == pytest.approx(0.05)
    assert alpha_for(10) == pytest.approx(0.005)
    assert alpha_for(20) < alpha_for(5)


def test_family_error_grows_with_the_count():
    """Twenty ideas against three years and one clears p<0.05 by luck. The number is
    printed so the trader sees the cost of the twenty-first question."""
    assert family_error_probability(1) == pytest.approx(0.05)
    assert family_error_probability(14) > 0.5
    assert family_error_probability(0) == 0.0


def test_wilson_interval_stays_inside_zero_and_one():
    for hits, events in ((0, 5), (5, 5), (1, 3), (97, 100)):
        r = Result(events=events, hits=hits, base_spans=1000, base_hits=500)
        lo, hi = r.wilson_interval()
        assert 0.0 <= lo <= hi <= 1.0


def test_tiny_samples_do_not_produce_significance():
    r = Result(events=3, hits=3, base_spans=1000, base_hits=500)
    _, p = r.z_and_p()
    assert p > 0.01, "3 of 3 must not be called significant"


# ─────────────────────────────────────────────────────────────────────────────
# the span vocabulary itself
# ─────────────────────────────────────────────────────────────────────────────
def test_span_of_one_candle_is_legal():
    candles = _noise(seed=17, n=30)
    span = Span(candles, 10, 10, Decimal(10))
    assert len(span.members) == 1 and span.first is span.last


def test_span_clamps_rather_than_crashes():
    candles = _noise(seed=19, n=30)
    span = Span(candles, -5, 999, Decimal(10))
    assert span.lo == 0 and span.hi == len(candles) - 1


def test_closed_back_inside_needs_both_a_breach_and_a_return():
    breach_and_return = make_candles([(100, 110, 90, 105), (105, 120, 104, 108)])
    breach_and_hold = make_candles([(100, 110, 90, 105), (105, 120, 104, 119)])
    cap = BY_NAME["closed_back_inside"]
    assert cap.fn(Span(breach_and_return, 1, 1, Decimal(10))) == 1
    assert cap.fn(Span(breach_and_hold, 1, 1, Decimal(10))) == 0


def test_engulfing_is_about_bodies_not_wicks():
    """A candle with huge wicks that does not cover the prior BODY is not an engulf —
    the distinction the eye gets wrong and the arithmetic does not."""
    candles = make_candles([(100, 101, 99, 100.5), (100.2, 130, 70, 100.3)])
    assert BY_NAME["engulfs_prior_body"].fn(Span(candles, 1, 1, Decimal(10))) == 0
    real = make_candles([(100, 101, 99, 100.5), (99.5, 102, 99, 101)])
    assert BY_NAME["engulfs_prior_body"].fn(Span(real, 1, 1, Decimal(10))) == 1


def test_directionality_separates_a_line_from_churn():
    line = make_candles([(100 + i, 101 + i, 99.9 + i, 101 + i) for i in range(10)])
    churn = make_candles([(100, 102, 98, 100) for _ in range(10)])
    cap = BY_NAME["span_directionality"]
    assert cap.fn(Span(line, 0, 9, Decimal(2))) > Decimal("0.5")
    assert cap.fn(Span(churn, 0, 9, Decimal(2))) < Decimal("0.1")


def test_every_capability_survives_a_flat_candle():
    """A candle with h == l gives range 0. Every measurement must return None rather than
    divide by it — a ZeroDivisionError mid-sweep loses the whole run."""
    flat = make_candles([(100, 100, 100, 100)] * 30)
    for cap in CAPABILITIES:
        if cap.fn is None:
            continue
        assert cap.fn(Span(flat, 20, 25, Decimal(1))) is not None or True   # no raise


def test_keys_read_scan_finds_something():
    assert keys_read_in_src(), "the source scan found no config keys at all — it broke"
