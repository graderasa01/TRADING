"""
The prohibitions from CLAUDE.md §6 and BUILD-BRIEF §3, as tests rather than as prose.

Every one of these is a rule someone will be tempted to bend at 3pm on a bad day, and
a rule that lives only in a document bends silently. Spec 09 §3.2 calls these the
"static / architectural" layer and lists most of them by name.

These run on every commit. `test_no_live_broker_module` is the one BUILD-BRIEF §3
explicitly requires to be added in P0.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


def src_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.name != "__init__.py")


def module_of(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT).with_suffix("")).replace("\\", "/")


# ─────────────────────────────────────────────────────────────────────────────
# the one that matters most at this stage
# ─────────────────────────────────────────────────────────────────────────────
def test_no_live_broker_module():
    """CLAUDE.md §6, BUILD-BRIEF §3. This stage is paper only."""
    assert not (SRC / "broker" / "live.py").exists(), (
        "src/broker/live.py exists. No live order path may be written at this stage.")


def test_no_live_order_placement_anywhere():
    """A live path can arrive without being called live.py."""
    forbidden = re.compile(r"\b(place_order|modify_order|cancel_order)\s*\(", re.I)
    for path in src_files():
        text = path.read_text(encoding="utf-8")
        # kiteconnect's own method names; a PaperBroker must not call them
        assert not forbidden.search(text), f"{module_of(path)} calls a live order method"


def test_no_stop_loss_widening_or_disable_flag():
    """CLAUDE.md §6: no SL widening, no 'temporarily disable SL' flag."""
    bad_key = re.compile(r"disable[_.]?\w*sl|sl\w*[_.]?disable|widen\w*_?(sl|stop)", re.I)
    for path in list(src_files()) + [REPO_ROOT / "config" / "params.yaml"]:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue                       # the prohibition may be *described*
            assert not bad_key.search(line), f"{module_of(path)}: {line.strip()[:70]}"


def test_no_martingale_or_size_up_after_loss():
    banned = re.compile(r"\b(martingale|average_down|averaging_down|size_up_after_loss)\b", re.I)
    for path in src_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert not banned.search(line), f"{module_of(path)}: {line.strip()[:70]}"


# ─────────────────────────────────────────────────────────────────────────────
# determinism and no-look-ahead, structurally
# ─────────────────────────────────────────────────────────────────────────────
def test_no_datetime_now_in_the_engine_path():
    """Spec 01 §3: 'The engine never calls datetime.now().' The engine's `now` comes
    from the Feed, or replay and live diverge in a way no test can see."""
    engine_dirs = ("domain", "levels", "structure", "state", "guards", "modes",
                   "setups", "risk", "exits")
    # Anchored so that `candle.open_time.time()` — a datetime accessor on data the Feed
    # supplied — is not mistaken for `time.time()`, a read of the wall clock.
    pattern = re.compile(r"(?<![\w.])(datetime\.now|time\.time|date\.today)\s*\(")
    for path in src_files():
        if path.parent.name not in engine_dirs:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not pattern.search(line), (
                f"{module_of(path)}:{i} reads the wall clock inside the engine path")


def test_no_float_in_money_paths():
    """CLAUDE.md §5. A float price is a rounding error waiting for a P&L report."""
    engine_dirs = ("domain", "levels", "structure", "state", "risk", "exits", "options")
    for path in src_files():
        if path.parent.name not in engine_dirs:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "float":
                pytest.fail(f"{module_of(path)}:{node.lineno} calls float() in a money path")


# ─────────────────────────────────────────────────────────────────────────────
# module boundaries — spec 01 §5
# ─────────────────────────────────────────────────────────────────────────────
def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


# Spec 01 §5. Packages that do not exist yet are simply not checked — the boundary
# activates by itself the moment the package appears, with no test to remember to
# enable. Deliberately not a skip: BUILD-BRIEF §8 forbids closing a phase with skipped
# tests, and a skip here would report as a hole in P0 rather than as P1 work not started.
BOUNDARIES = [
    ("structure", "levels",
     "spec 04: structure must not see levels, or a level justifies a structure that "
     "justifies the level"),
    ("setups", "options",
     "spec 08: no signal may be computed from option premium price action"),
    ("levels", "options", "spec 08"),
]


def test_module_boundaries():
    for package, forbidden, why in BOUNDARIES:
        folder = SRC / package
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            for name in imports_of(path):
                assert f"src.{forbidden}" not in name, (
                    f"{module_of(path)} imports {name} — {why}")


def test_journey_never_read_by_the_trading_path():
    """D-011b. The Journey is a logged prediction and nothing more until P9 measures
    it. An unmeasured intuition wired into a gate is the most likely way this system
    acquires a losing rule that nobody can argue with, because it will feel true."""
    for package in ("setups", "risk", "exits"):
        folder = SRC / package
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            for name in imports_of(path):
                assert "journey" not in name.lower(), (
                    f"{module_of(path)} imports {name}. journey_gates_trades is false "
                    f"and must be enforced structurally, not by convention.")


def test_partial_candles_never_reach_a_detector():
    """Spec 01 §4: *"Partials may be used for exactly ONE purpose: knowing how far into
    an HTF candle we are. They must never be used for pattern detection, level creation,
    or signals."*

    `structure/` is that one permitted purpose — spec 04 §4 Law B needs the partial for
    `htf_progress` and the journalled shape forecast, which is what feeds the
    `htf_close_proximity` guard. So it is deliberately absent from this list; the type
    distinction (a `PartialCandle` has no `body`, wicks or `close_third`) is what stops
    it being used for anything else there.

    Detection and signal generation may not touch a forming candle at all.
    """
    for package in ("levels", "setups"):
        folder = SRC / package
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "PartialCandle" not in text, (
                f"{module_of(path)} references PartialCandle — a forming candle must "
                f"never feed pattern detection")


# ─────────────────────────────────────────────────────────────────────────────
# reporting honesty
# ─────────────────────────────────────────────────────────────────────────────
def test_gross_is_never_formatted_for_output():
    """CLAUDE.md §8 and spec 08 §4.2: gross_pnl is never displayed on its own."""
    fmt = re.compile(r'(f".*\bgross\b|print\([^)]*gross|\.format\([^)]*gross)', re.I)
    for path in src_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not fmt.search(line), (
                f"{module_of(path)}:{i} formats a gross figure for output")


def test_no_print_in_src():
    """CLAUDE.md §5: structured logging only. tools/ are CLIs and are exempt."""
    for path in src_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "print":
                pytest.fail(f"{module_of(path)}:{node.lineno} calls print()")


def test_every_points_threshold_has_an_atr_sibling():
    """REVIEW-v2 §12. An absolute point threshold means a 3-year backtest silently
    tests a different system at each end of the sample — and DATA-REPORT.md §5 shows
    it also makes the four-instrument P9 impossible."""
    import yaml

    params = yaml.safe_load((REPO_ROOT / "config" / "params.yaml").read_text(encoding="utf-8"))

    # Four deliberate exceptions, each because ATR genuinely cannot normalise it.
    exempt_keys = {
        # ATR is the thing being measured; it cannot be expressed as a multiple of
        # itself. DATA-REPORT.md §5 shows the cost of that: as absolute points these
        # two block 84% of Nifty 50 candles, which is the open question in BUILD-PLAN §1.1.
        "atr_min_points", "atr_max_points",
        # A hard ceiling regardless of volatility is absolute by definition (spec 07 §1.2).
        "r_absolute_max_points",
    }
    # Premium points, not index points — a different unit entirely, calibrated from
    # observed quotes in P8.5 rather than normalised by an index ATR.
    exempt_sections = {"slippage"}

    missing: list[str] = []
    for section, body in params.items():
        if not isinstance(body, dict) or section in exempt_sections:
            continue
        for key in body:
            if not key.endswith("_points") or key in exempt_keys:
                continue
            stem = key[: -len("_points")]
            candidates = {f"{stem}_atr_mult"}
            for edge in ("_min", "_max"):        # sl_buffer_min_points -> sl_buffer_atr_mult
                if stem.endswith(edge):
                    candidates.add(f"{stem[: -len(edge)]}_atr_mult")
            if not (candidates & set(body)):
                missing.append(f"{section}.{key} (looked for {sorted(candidates)})")
    assert not missing, f"points thresholds with no ATR-relative sibling: {missing}"
