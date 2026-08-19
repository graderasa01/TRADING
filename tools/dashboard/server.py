"""The dashboard server. Stdlib only — no new dependency for a viewing tool.

```
GET /                        the single page
GET /static/<name>           app.css · viewport.js · app.js
GET /api/catalog             what can be loaded
GET /api/session?key=&paper= a whole historical session, frames included
POST /api/live/open          start a LiveSession over a paced feed
GET  /api/live/poll?id=      the frames produced since the last poll
POST /api/live/stop
```

## What this server is not

It takes no decision. Every route returns facts that
`src/livemap/observatory.py` already produced from the production pipeline. There is no
order route, no position route and no execution route, because there is nothing to put in
them: `EXECUTION_STATUS` is `UNAVAILABLE` and the only way a position exists at all is an
explicitly-named research contract requested with `paper=1`.

## Live mode is the same engine

`/api/live/*` drives `observatory.LiveSession` one candle at a time from a `FeedSource`.
Attaching a broker websocket instead of `PacedSource` changes this file not at all — which
is the property `test_the_live_session_and_the_batch_replay_agree_candle_for_candle`
pins. It binds to localhost.
"""
from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.livemap import observatory as OB

from tools.dashboard import sessions as S
from tools.dashboard.feed import PacedSource

STATIC = Path(__file__).resolve().parent / "static"
#: Built sessions are cached: rebuilding a 700-candle block costs ~20 seconds and the
#: picker is meant to feel like a dashboard, not a batch job.
_CACHE: dict[tuple[str, bool], dict] = {}
_CACHE_LOCK = threading.Lock()
_LIVE: dict[str, "LiveRun"] = {}


class LiveRun:
    """One live session, fed on a background thread. Market data only."""

    def __init__(self, key: str, paper: bool, seconds: float) -> None:
        self.key = key
        self.session = S.load(key)
        self.execution = S.contract_for(self.session, paper)
        self.snapshot = self.session.snapshot
        self.engine = OB.LiveSession(self.snapshot, list(self.session.history),
                                     execution=self.execution)
        self.source = PacedSource(self.session.live, seconds=seconds)
        self.sent = 0
        self.done = False
        self.error: str | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for candle in self.source.candles():
                with self._lock:
                    self.engine.on_candle(candle)
        except Exception:                                   # noqa: BLE001
            self.error = traceback.format_exc(limit=4)
        finally:
            self.done = True

    def drain(self) -> dict:
        """Frames produced since the last poll. The engine is never asked to redo one."""
        with self._lock:
            frames = self.engine.frames[self.sent:]
            self.sent = len(self.engine.frames)
        return {"frames": [S.frame_json(f) for f in frames],
                "done": self.done, "error": self.error,
                "source": self.source.name, "live": self.source.live}


def _session(key: str, paper: bool) -> dict:
    with _CACHE_LOCK:
        hit = _CACHE.get((key, paper))
    if hit is not None:
        return hit
    built = S.build(key, paper=paper)
    with _CACHE_LOCK:
        _CACHE[(key, paper)] = built
    return built


class Handler(BaseHTTPRequestHandler):
    server_version = "observatory"

    def log_message(self, fmt, *args):       # noqa: A003 - quiet by default
        pass

    # ── plumbing ────────────────────────────────────────────────────────────
    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(json.dumps(obj, separators=(",", ":")).encode(),
                   "application/json; charset=utf-8", code)

    def _static(self, name: str) -> None:
        path = (STATIC / name).resolve()
        if not path.is_file() or STATIC not in path.parents:
            self._json({"error": "not found"}, 404)
            return
        kind = {".css": "text/css", ".js": "text/javascript",
                ".html": "text/html"}.get(path.suffix, "text/plain")
        self._send(path.read_bytes(), f"{kind}; charset=utf-8")

    # ── routes ──────────────────────────────────────────────────────────────
    def do_GET(self) -> None:                # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path in ("/", "/index.html"):
                self._static("index.html")
            elif url.path.startswith("/static/"):
                self._static(url.path[len("/static/"):])
            elif url.path == "/api/catalog":
                self._json(S.catalog())
            elif url.path == "/api/session":
                key = q.get("key", ["block0"])[0]
                paper = q.get("paper", ["0"])[0] == "1"
                self._json(_session(key, paper))
            elif url.path == "/api/live/poll":
                run = _LIVE.get(q.get("id", [""])[0])
                self._json(run.drain() if run else {"error": "no such live session"},
                           200 if run else 404)
            else:
                self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception:                                   # noqa: BLE001
            self._json({"error": traceback.format_exc(limit=4)}, 500)

    def do_POST(self) -> None:               # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == "/api/live/open":
                key = q.get("key", ["block0"])[0]
                paper = q.get("paper", ["0"])[0] == "1"
                seconds = float(q.get("seconds", ["1.0"])[0])
                run = LiveRun(key, paper, seconds)
                ident = f"{key}:{len(_LIVE)}"
                _LIVE[ident] = run
                self._json({"id": ident, "label": run.session.label,
                            "symbol": S.SYMBOL, "contract": run.execution.name,
                            "validated": bool(run.execution.validated),
                            "source": run.source.name,
                            "scenario_names": OB.SCENARIOS,
                            "questions": list(OB.EYE_QUESTIONS),
                            "execution_status": "UNAVAILABLE"})
            elif url.path == "/api/live/stop":
                _LIVE.pop(q.get("id", [""])[0], None)
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except KeyError as exc:
            self._json({"error": str(exc)}, 404)
        except Exception:                                   # noqa: BLE001
            self._json({"error": traceback.format_exc(limit=4)}, 500)


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


__all__ = ["Handler", "LiveRun", "serve", "STATIC"]
