#!/usr/bin/env python3
"""
dash.py — run the Reactive Trader Observatory dashboard.

    python tools/dash.py
    python tools/dash.py --port 9000 --open

One page. Pick a teach block or a session day, replay it candle by candle, or attach the
paced feed and watch the identical production pipeline answer one candle at a time.

**Market data only.** No broker, no order, no sizing, no risk, no target.
`EXECUTION_STATUS = UNAVAILABLE`. A position appears only when PAPER is switched on, which
attaches a named research contract and labels every position `PAPER`.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401
from tools.dashboard.server import serve  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)

    httpd = serve(a.host, a.port)
    url = f"http://{a.host}:{a.port}/"
    print(f"Reactive Trader Observatory  {url}")
    print("EXECUTION_STATUS = UNAVAILABLE   no broker, no order, no sizing, no risk")
    print("Ctrl-C to stop.")
    if a.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
