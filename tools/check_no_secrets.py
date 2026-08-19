#!/usr/bin/env python3
"""
check_no_secrets.py — refuse to let a credential into the repo.

    python tools/check_no_secrets.py              # scan tracked + untracked files
    python tools/check_no_secrets.py --staged     # scan only what is staged (pre-commit)
    python tools/check_no_secrets.py --install    # install as a git pre-commit hook

Required by spec 08 §3.1 ("add a pre-commit check for this") and by CLAUDE.md §4,
KICKOFF §1 and BUILD-BRIEF §6, which all say the same thing: no API key or secret in
the repo, in config files, or in logs.

Two independent checks, because either alone misses cases:

  1. EXACT — if a credential is currently readable from the environment or the
     credentials file, look for that literal string in the repo. Catches the real leak,
     with zero false positives.
  2. SHAPE — look for assignments that appear to carry a live secret
     (`KITE_API_SECRET=abc123`, `api_key = "..."`). Catches a leak of a credential this
     machine does not happen to hold, at the cost of occasional false positives, which
     are silenced by using an obvious placeholder.

A file is only interesting if it is in the repo. `.env.example` is exempt from the shape
check by name — it exists to show the format and holds nothing.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import _console  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parent.parent
CREDENTIAL_NAMES = ("KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN")

# `NAME = value`, where the value has the shape of a real Kite credential rather than
# of a variable name. Kite api_key / api_secret / access_token are unbroken runs of
# lowercase alphanumerics (16 and 32 chars respectively).
#
# The value pattern deliberately allows NO underscore, hyphen, dot or uppercase, and
# requires at least one digit. That is what separates a credential from an identifier:
# `access_token = load_access_token(...)` and `api_key="super-secret-key"` both break on
# their separators, while `z9x8c7v6b5n4m3q2` does not. Without this the check fires on
# ordinary code, and a scanner that cries wolf is one people learn to bypass with
# --no-verify — which is worse than no scanner.
SHAPE = re.compile(
    r"""(?ix)
    \b (kite[_-]?)? (api[_-]?key | api[_-]?secret | access[_-]?token) \b
    \s* [:=] \s*
    ["'] (?P<value> (?=[a-z0-9]*\d) [a-z0-9]{16,64}) ["']
    """
)
PLACEHOLDER = re.compile(
    r"(?i)(your|placeholder|example|dummy|xxx+|\.\.\.|<.*>|here|changeme|redacted|test|fake|sample)"
)

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", "data"}
SKIP_SUFFIXES = {".parquet", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".pyc", ".ico"}
SHAPE_EXEMPT = {".env.example"}


def live_credentials() -> dict[str, str]:
    """Whatever this machine can actually read, so we can look for it verbatim."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    try:
        import fetch_kite
    except ImportError:
        return {n: v for n in CREDENTIAL_NAMES if (v := os.environ.get(n, "").strip())}
    found = {}
    for name in CREDENTIAL_NAMES:
        try:
            value, _ = fetch_kite.read_credential(name)
        except Exception:
            value = os.environ.get(name, "").strip() or None
        if value and len(value) >= 8:
            found[name] = value
    return found


def files_to_scan(staged_only: bool) -> list[Path]:
    if staged_only:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        return [REPO_ROOT / line for line in out.stdout.splitlines() if line.strip()]
    result = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix in SKIP_SUFFIXES:
            continue
        if SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts):
            continue
        result.append(path)
    return result


def scan(staged_only: bool) -> list[str]:
    problems: list[str] = []
    live = live_credentials()

    for path in files_to_scan(staged_only):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            for name, value in live.items():
                if value in line:
                    problems.append(
                        f"{rel}:{line_no}  contains the live value of {name}. "
                        f"Remove it AND rotate the credential — it is already on disk here."
                    )
            if rel.name in SHAPE_EXEMPT:
                continue
            match = SHAPE.search(line)
            if match and not PLACEHOLDER.search(match.group("value")):
                problems.append(
                    f"{rel}:{line_no}  looks like a credential assignment: "
                    f"{match.group(0)[:48]}..."
                )

    # a secrets file must never exist inside the repo at all, gitignored or not.
    # `.env` matches both globs, so deduplicate — one file, one complaint.
    candidates = set(REPO_ROOT.glob(".env*")) | set(REPO_ROOT.glob("*.env"))
    for candidate in sorted(candidates):
        if candidate.name in SHAPE_EXEMPT:
            continue
        problems.append(
            f"{candidate.name}  is a credentials file inside the repo. "
            f"Move it to ~/.banknifty-copilot/.env — see .env.example."
        )
    return problems


def install_hook() -> int:
    hooks = REPO_ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print(f"no .git/hooks at {hooks} — is this a git repo?", file=sys.stderr)
        return 2
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# installed by tools/check_no_secrets.py --install\n"
        'exec python "$(git rev-parse --show-toplevel)/tools/check_no_secrets.py" --staged\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    print(f"installed {hook}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true", help="scan only staged files (pre-commit mode)")
    ap.add_argument("--install", action="store_true", help="install as a git pre-commit hook")
    args = ap.parse_args(argv)

    if args.install:
        return install_hook()

    problems = scan(args.staged)
    if problems:
        print("SECRET SCAN FAILED\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\nNo API key or secret may live in this repo (CLAUDE.md sec 4, spec 08 sec 3.1).",
              file=sys.stderr)
        return 1
    print(f"secret scan clean ({'staged files' if args.staged else 'whole repo'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
