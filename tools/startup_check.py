#!/usr/bin/env python3
"""
startup_check.py — what the engine does before its first candle. Spec 10 §4.

    python tools/startup_check.py
    python tools/startup_check.py --date 2026-03-04 --force-fresh-session

Exit code 0 means the engine would start. Anything else means it would refuse, and the
banner says exactly why.

Run this after any change to `config/`. The whole argument for the reachability battery
is that it costs an hour and catches, before a single candle, the class of bug that
otherwise hides for four months behind a clean and confident `NO_TRADE`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401

from src.config.loader import load_config  # noqa: E402
from src.domain.models import IST  # noqa: E402
from src.health.startup import startup  # noqa: E402
from src.state.session_store import SessionStore, default_path  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, IST)")
    ap.add_argument("--force-fresh-session", action="store_true",
                    help="discard today's saved session state. Loud on purpose.")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    from datetime import datetime

    today = date.fromisoformat(args.date) if args.date else datetime.now(IST).date()
    cfg = load_config(args.config, strict=False)
    store = SessionStore(default_path(cfg), force_fresh=args.force_fresh_session)

    if args.force_fresh_session:
        print("!! --force-fresh-session: today's saved counters will be discarded.\n"
              "   trades_taken, consecutive_losses, cumulative_r and the duplicate\n"
              "   registry all reset. This is the only path that may do that.\n")

    result = startup(cfg, today, store)
    print(result.banner)
    return 0 if result.may_start else 1


if __name__ == "__main__":
    raise SystemExit(main())
