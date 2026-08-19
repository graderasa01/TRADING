"""
The quarantine — `LIVE-FRONTIER.md` §8.

`src/journey/ladder.py` established this pattern and its docstring gives the reason:
*"a strong intuition that has never been measured is exactly the kind of thing that
quietly becomes a rule and then quietly loses money."*

`src/livemap/` is in exactly that position. It reads well, it has no outcome validation
whatsoever, and the fastest way for it to start losing money is for something on the
trading path to quietly start importing it. So that is asserted statically rather than
trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

#: Anything that can contribute to a Signal. Directories that do not exist yet are
#: skipped, so this keeps working as the build order fills them in.
TRADING_PATH = ("setups", "risk", "exits", "modes", "broker", "guards", "options")

IMPORT = re.compile(r"^\s*(?:from|import)\s+(?:src\.)?(livemap|boxes\.frontier)",
                    re.MULTILINE)


def _python_files(package: str) -> list[Path]:
    d = SRC / package
    return sorted(d.rglob("*.py")) if d.is_dir() else []


def test_livemap_never_read_by_the_trading_path():
    offenders = []
    for package in TRADING_PATH:
        for f in _python_files(package):
            if IMPORT.search(f.read_text(encoding="utf-8")):
                offenders.append(str(f.relative_to(SRC)))
    assert not offenders, (
        f"the trading path imports the live map: {offenders}. This layer has zero "
        f"outcome validation; it must not be able to influence a Signal.")


def test_the_quarantine_covers_the_directories_that_exist():
    """A guard that silently checks nothing is worse than no guard."""
    present = [p for p in TRADING_PATH if (SRC / p).is_dir()]
    assert present, "no trading-path package found — the assertion above is vacuous"
    assert any(_python_files(p) for p in present)


def test_livemap_does_not_import_the_trading_path():
    """The isolation runs both ways: the map must not learn about setups or risk."""
    pattern = re.compile(
        r"^\s*(?:from|import)\s+(?:src\.)?(" + "|".join(TRADING_PATH) + r")\b",
        re.MULTILINE)
    offenders = [str(f.relative_to(SRC)) for f in _python_files("livemap")
                 if pattern.search(f.read_text(encoding="utf-8"))]
    assert not offenders, f"the live map reaches into the trading path: {offenders}"
