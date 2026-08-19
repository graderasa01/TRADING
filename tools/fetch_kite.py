#!/usr/bin/env python3
"""
fetch_kite.py — resumable 1-minute historical downloader for the level engine.

    python tools/fetch_kite.py login                     # daily access token
    python tools/fetch_kite.py instruments               # resolve + print tokens
    python tools/fetch_kite.py fetch --years 3           # the actual download
    python tools/fetch_kite.py fetch --plan              # what it WOULD request

Credentials come from the environment and nowhere else:

    KITE_API_KEY        required for every subcommand
    KITE_API_SECRET     required only for `login`
    KITE_ACCESS_TOKEN   optional; otherwise the cached token from `login` is used

Nothing secret is ever written to the repo, to the manifest, or to a log line.
The cached access token lives OUTSIDE the repo (~/.banknifty-copilot/) — see
DECISIONS.md D-015.

Facts this tool is built around (kite.trade docs, verified 2026-08-11):
  * historical candle endpoint is rate limited to 3 req/second
  * `minute` interval allows a maximum of 60 days per request
  * 1-minute history goes back roughly 3 years

Output layout (KICKOFF.md §1 Task 1):
    data/{SYMBOL}/{YYYY-MM}.parquet     (or .csv with --format csv)
    data/manifest.json                  resume state + SHA per file
    data/fetch_log.jsonl                one JSON line per request
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import _console  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── the four instruments (KICKOFF §1). Tokens are RESOLVED, never hardcoded. ──
# name          → (exchange, tradingsymbol as it appears in the instrument master)
INSTRUMENTS: dict[str, tuple[str, str]] = {
    "NIFTY BANK":        ("NSE", "NIFTY BANK"),          # primary
    "NIFTY 50":          ("NSE", "NIFTY 50"),            # cross-validation (spec 09)
    "NIFTY FIN SERVICE": ("NSE", "NIFTY FIN SERVICE"),
    "SENSEX":            ("BSE", "SENSEX"),              # may not be accessible
}
OPTIONAL_INSTRUMENTS = {"SENSEX"}   # absence is reported, not fatal

INTERVAL = "minute"
MAX_DAYS_PER_REQUEST = 60           # Kite limit for `minute`
HISTORICAL_RPS = 3.0                # Kite limit for the historical endpoint
DEFAULT_RPS = 2.5                   # we stay under it
MANIFEST_SCHEMA = 1

log = logging.getLogger("fetch_kite")


# ─────────────────────────────────────────────────────────────────────────────
# logging — human on stderr, JSON lines on disk, secrets in neither
# ─────────────────────────────────────────────────────────────────────────────
class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(IST).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


def setup_logging(log_path: Path, verbose: bool) -> None:
    # The logger itself is always DEBUG so that EVERY request reaches the JSONL file
    # (KICKOFF §1 Task 1). Only the console is quietened.
    log.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.addHandler(console)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl = logging.FileHandler(log_path, encoding="utf-8")
    jsonl.setFormatter(JsonLineFormatter())
    jsonl.setLevel(logging.DEBUG)
    log.addHandler(jsonl)


def logx(level: int, msg: str, **fields: Any) -> None:
    log.log(level, msg, extra={"extra_fields": fields})


# ─────────────────────────────────────────────────────────────────────────────
# credentials
# ─────────────────────────────────────────────────────────────────────────────
class MissingCredential(RuntimeError):
    pass


class CredentialInRepo(RuntimeError):
    """A secret was found, or was configured to live, inside the repository."""


def env_file_path() -> Path:
    """The one credentials file, deliberately OUTSIDE the repo (see .env.example)."""
    override = os.environ.get("BNC_ENV_FILE")
    if override:
        return Path(override)
    base = os.environ.get("BNC_TOKEN_DIR")
    return (Path(base) if base else Path.home() / ".banknifty-copilot") / ".env"


def assert_env_file_outside_repo() -> None:
    """CLAUDE.md §4, KICKOFF §1, BUILD-BRIEF §6 and spec 08 §3.1 all forbid a secret
    inside the repo. A .gitignore is one edit away from failing; a path outside the
    repo cannot fail that way. Enforced rather than documented."""
    path = env_file_path().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise CredentialInRepo(
            f"the credentials file is configured inside the repo:\n"
            f"    {path}\n"
            f"  Move it outside — the intended location is:\n"
            f"    {Path.home() / '.banknifty-copilot' / '.env'}\n"
            f"  See .env.example. No secret may live in the repo, gitignored or not.\n"
        )


def _read_env_file(name: str) -> str | None:
    assert_env_file_outside_repo()
    path = env_file_path()
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip("'\"") or None
    return None


def _read_user_scope_env(name: str) -> str | None:
    """Windows only: read the User-scope variable straight out of HKCU\\Environment.

    `[Environment]::SetEnvironmentVariable(name, value, 'User')` and `setx` write to the
    registry, but a process that was already running when the variable was set keeps its
    own inherited copy of the old environment — and hands that stale copy to every child
    it spawns. So a credential set five minutes ago is invisible to an agent started ten
    minutes ago, and the usual fix is "restart everything".

    Reading the registry makes a freshly-set credential work immediately. It is still an
    environment variable; we are just reading the durable store instead of the inherited
    snapshot. Nothing is read from the repo and nothing is written anywhere.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip() or None
    except (OSError, ImportError, ValueError):
        return None


def read_credential(name: str) -> tuple[str | None, str | None]:
    """Three sources, first hit wins. Returns (value, where_it_came_from).

    The value is returned to the caller and nowhere else — never logged, never written
    to the manifest, never printed by `check`.
    """
    value = os.environ.get(name, "").strip()
    if value:
        return value, "process environment"
    value = _read_user_scope_env(name)
    if value:
        return value, "Windows user environment (registry)"
    value = _read_env_file(name)
    if value:
        return value, f"{env_file_path()}"
    return None, None


def require_env(name: str, why: str) -> str:
    value, _ = read_credential(name)
    if not value:
        raise MissingCredential(
            f"{name} is not set.\n"
            f"  Needed for: {why}\n"
            f"  Set it in the environment only — never in the repo, never in config, never in a log.\n"
            f"    PowerShell, persistent (survives a reboot, and this tool reads it immediately):\n"
            f"      [Environment]::SetEnvironmentVariable('{name}','<value>','User')\n"
            f"    PowerShell, this shell only:\n"
            f"      $env:{name} = '<value>'\n"
            f"    Or put it in the credentials file (see .env.example):\n"
            f"      {env_file_path()}\n"
        )
    return value


def token_cache_path() -> Path:
    base = os.environ.get("BNC_TOKEN_DIR")
    return (Path(base) if base else Path.home() / ".banknifty-copilot") / "kite_token.json"


def save_access_token(token: str, api_key: str) -> Path:
    """Cache outside the repo. Keyed by a hash of the api_key so two keys don't collide,
    and so the key itself is not recoverable from the file."""
    path = token_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": token,
        "api_key_sha256_8": hashlib.sha256(api_key.encode()).hexdigest()[:8],
        "issued_at": datetime.now(IST).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best effort on Windows
    return path


def token_is_stale(issued_at: datetime, now: datetime) -> bool:
    """Kite sessions die at 06:00 IST the morning after they were issued."""
    expiry = datetime.combine(issued_at.date() + timedelta(days=1), datetime.min.time(), tzinfo=IST)
    expiry = expiry.replace(hour=6)
    return now >= expiry


def load_access_token(api_key: str) -> str | None:
    env, source = read_credential("KITE_ACCESS_TOKEN")
    if env:
        logx(logging.INFO, "access token from KITE_ACCESS_TOKEN", source=source)
        return env
    path = token_cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        issued = datetime.fromisoformat(payload["issued_at"])
    except (OSError, ValueError, KeyError) as exc:
        logx(logging.WARNING, "token cache unreadable, ignoring", error=str(exc))
        return None
    if payload.get("api_key_sha256_8") != hashlib.sha256(api_key.encode()).hexdigest()[:8]:
        logx(logging.WARNING, "cached token belongs to a different API key, ignoring")
        return None
    if token_is_stale(issued, datetime.now(IST)):
        logx(logging.WARNING, "cached token expired (Kite sessions die 06:00 IST next day)",
             issued_at=payload["issued_at"])
        return None
    logx(logging.INFO, "access token from cache", issued_at=payload["issued_at"])
    return payload["access_token"]


# ─────────────────────────────────────────────────────────────────────────────
# throttling and retries
# ─────────────────────────────────────────────────────────────────────────────
class Throttle:
    """Every REST call goes through one of these. Kite allows 3/s on historical."""

    def __init__(self, rps: float) -> None:
        if rps > HISTORICAL_RPS:
            raise ValueError(f"--rps {rps} exceeds the documented limit of {HISTORICAL_RPS}/s")
        self.min_interval = 1.0 / rps
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


class FatalApiError(RuntimeError):
    """Retrying will not help — bad token, no subscription, bad input."""


def call_with_backoff(fn, *args, attempts: int = 5, base_delay: float = 2.0, **kwargs):
    from kiteconnect import exceptions as kexc

    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except (kexc.TokenException, kexc.PermissionException, kexc.InputException) as exc:
            raise FatalApiError(f"{type(exc).__name__}: {exc}") from exc
        except Exception as exc:  # network, throttle, 5xx, unparseable body
            if attempt == attempts:
                raise
            delay = base_delay ** attempt
            logx(logging.WARNING, "request failed, backing off",
                 attempt=attempt, of=attempts, sleep_s=delay, error=f"{type(exc).__name__}: {exc}")
            time.sleep(delay)
    raise AssertionError("unreachable")


# ─────────────────────────────────────────────────────────────────────────────
# instrument resolution
# ─────────────────────────────────────────────────────────────────────────────
def resolve_instruments(kite, throttle: Throttle, wanted: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Look every token up in the instrument master. Hardcoded tokens rot silently."""
    resolved: dict[str, dict[str, Any]] = {}
    by_exchange: dict[str, list[str]] = {}
    for name in wanted:
        exchange, _ = INSTRUMENTS[name]
        by_exchange.setdefault(exchange, []).append(name)

    for exchange, names in by_exchange.items():
        throttle.wait()
        try:
            dump = call_with_backoff(kite.instruments, exchange)
        except FatalApiError as exc:
            logx(logging.ERROR, "instrument master unavailable", exchange=exchange, error=str(exc))
            continue
        logx(logging.INFO, "instrument master loaded", exchange=exchange, rows=len(dump))
        index = {(row.get("tradingsymbol") or "").upper(): row for row in dump
                 if (row.get("segment") or "").upper() == "INDICES"}
        for name in names:
            _, tradingsymbol = INSTRUMENTS[name]
            row = index.get(tradingsymbol.upper())
            if row is None:
                level = logging.WARNING if name in OPTIONAL_INSTRUMENTS else logging.ERROR
                logx(level, "instrument not found in master", instrument=name,
                     exchange=exchange, tradingsymbol=tradingsymbol)
                continue
            resolved[name] = {
                "instrument_token": int(row["instrument_token"]),
                "exchange": exchange,
                "tradingsymbol": row["tradingsymbol"],
                "segment": row.get("segment"),
                "resolved_at": datetime.now(IST).isoformat(),
            }
            logx(logging.INFO, "resolved", instrument=name,
                 instrument_token=resolved[name]["instrument_token"], exchange=exchange)
    return resolved


# ─────────────────────────────────────────────────────────────────────────────
# storage
# ─────────────────────────────────────────────────────────────────────────────
COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def symbol_dir(name: str) -> str:
    return name.replace(" ", "_")


def rows_from_api(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in candles:
        ts = c["date"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        out.append({
            "ts": ts.astimezone(IST),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": int(c.get("volume") or 0),
        })
    out.sort(key=lambda r: r["ts"])
    return out


def write_candles(rows: list[dict[str, Any]], path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({
            "ts": pa.array([r["ts"] for r in rows], type=pa.timestamp("s", tz="Asia/Kolkata")),
            "open": pa.array([r["open"] for r in rows], type=pa.float64()),
            "high": pa.array([r["high"] for r in rows], type=pa.float64()),
            "low": pa.array([r["low"] for r in rows], type=pa.float64()),
            "close": pa.array([r["close"] for r in rows], type=pa.float64()),
            "volume": pa.array([r["volume"] for r in rows], type=pa.int64()),
        })
        pq.write_table(table, path, compression="zstd")
    else:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for r in rows:
                writer.writerow({**r, "ts": r["ts"].isoformat()})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# manifest
# ─────────────────────────────────────────────────────────────────────────────
def load_manifest(path: Path) -> dict[str, Any]:
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_SCHEMA:
            raise RuntimeError(f"manifest schema {manifest.get('schema_version')} != {MANIFEST_SCHEMA}")
        return manifest
    return {
        "schema_version": MANIFEST_SCHEMA,
        "interval": INTERVAL,
        "created_at": datetime.now(IST).isoformat(),
        "updated_at": None,
        "instruments": {},
        "files": {},
    }


def save_manifest(manifest: dict[str, Any], path: Path) -> None:
    manifest["updated_at"] = datetime.now(IST).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ─────────────────────────────────────────────────────────────────────────────
# date chunking
# ─────────────────────────────────────────────────────────────────────────────
def month_chunks(start: date, end: date) -> Iterator[tuple[str, date, date]]:
    """One chunk per calendar month. A month is <= 31 days, well inside the 60-day limit,
    and it makes the output layout data/{SYMBOL}/{YYYY-MM} fall out for free."""
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        nxt = date(cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1)
        chunk_start = max(cursor, start)
        chunk_end = min(nxt - timedelta(days=1), end)
        yield f"{cursor.year:04d}-{cursor.month:02d}", chunk_start, chunk_end
        cursor = nxt


def month_is_complete(month_key: str, today: date) -> bool:
    year, month = (int(x) for x in month_key.split("-"))
    last = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return last < today


# ─────────────────────────────────────────────────────────────────────────────
# fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_month(kite, throttle: Throttle, token: int, start: date, end: date) -> list[dict[str, Any]]:
    span_days = (end - start).days + 1
    if span_days > MAX_DAYS_PER_REQUEST:
        raise AssertionError(f"chunk of {span_days} days exceeds the {MAX_DAYS_PER_REQUEST}-day limit")
    throttle.wait()
    t0 = time.monotonic()
    candles = call_with_backoff(
        kite.historical_data,
        instrument_token=token,
        from_date=datetime.combine(start, datetime.min.time()),
        to_date=datetime.combine(end, datetime.max.time().replace(microsecond=0)),
        interval=INTERVAL,
    )
    logx(logging.DEBUG, "historical_data ok", instrument_token=token,
         start=str(start), end=str(end), rows=len(candles), elapsed_s=round(time.monotonic() - t0, 2))
    return rows_from_api(candles)


def cmd_fetch(args: argparse.Namespace) -> int:
    out_root = Path(args.out)
    manifest_path = out_root / "manifest.json"
    setup_logging(out_root / "fetch_log.jsonl", args.verbose)

    today = datetime.now(IST).date()
    end = date.fromisoformat(args.to) if args.to else today
    start = date.fromisoformat(getattr(args, "from")) if getattr(args, "from") else \
        date(end.year - args.years, end.month, 1)
    if start > end:
        log.error("--from is after --to")
        return 2

    wanted = args.symbols or list(INSTRUMENTS)
    unknown = [s for s in wanted if s not in INSTRUMENTS]
    if unknown:
        log.error("unknown symbol(s): %s — known: %s", unknown, list(INSTRUMENTS))
        return 2

    chunks = list(month_chunks(start, end))
    logx(logging.INFO, "plan", start=str(start), end=str(end), months=len(chunks),
         symbols=wanted, requests_max=len(chunks) * len(wanted), format=args.format)

    if args.plan:
        for name in wanted:
            print(f"{name}: {len(chunks)} months  {chunks[0][0]} .. {chunks[-1][0]}")
        print(f"\ntotal requests (worst case): {len(chunks) * len(wanted)}")
        print(f"at {args.rps} req/s that is ~{len(chunks) * len(wanted) / args.rps / 60:.1f} minutes of wall clock")
        return 0

    api_key = require_env("KITE_API_KEY", "every Kite REST call")
    access_token = load_access_token(api_key)
    if not access_token:
        log.error("no usable access token. Run:  python tools/fetch_kite.py login")
        return 3

    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    throttle = Throttle(args.rps)

    manifest = load_manifest(manifest_path)
    resolved = resolve_instruments(kite, throttle, wanted)
    if not resolved:
        log.error("no instruments resolved — cannot continue")
        return 4
    manifest["instruments"].update(resolved)
    save_manifest(manifest, manifest_path)

    missing_required = [n for n in wanted if n not in resolved and n not in OPTIONAL_INSTRUMENTS]
    if missing_required:
        log.error("required instruments unresolved: %s", missing_required)
        return 4

    suffix = "parquet" if args.format == "parquet" else "csv"
    downloaded = skipped = empty = failed = 0

    for name in wanted:
        if name not in resolved:
            continue
        token = resolved[name]["instrument_token"]
        for month_key, chunk_start, chunk_end in chunks:
            file_key = f"{name}/{month_key}"
            rel_path = f"{symbol_dir(name)}/{month_key}.{suffix}"
            abs_path = out_root / rel_path
            record = manifest["files"].get(file_key)
            complete = month_is_complete(month_key, today)

            if record and not args.refetch:
                fresh_enough = record["status"] == "ok" and record.get("month_complete") is True
                on_disk = (out_root / record["path"]).exists()
                if fresh_enough and on_disk:
                    skipped += 1
                    continue
                if record["status"] == "empty" and complete and not args.refetch_empty:
                    skipped += 1
                    continue

            try:
                rows = fetch_month(kite, throttle, token, chunk_start, chunk_end)
            except FatalApiError as exc:
                logx(logging.ERROR, "fatal API error — stopping this instrument",
                     instrument=name, month=month_key, error=str(exc))
                failed += 1
                manifest["files"][file_key] = {
                    "path": rel_path, "status": "error", "error": str(exc),
                    "attempted_at": datetime.now(IST).isoformat(),
                }
                save_manifest(manifest, manifest_path)
                break
            except Exception as exc:
                logx(logging.ERROR, "month failed after retries", instrument=name,
                     month=month_key, error=f"{type(exc).__name__}: {exc}")
                failed += 1
                manifest["files"][file_key] = {
                    "path": rel_path, "status": "error", "error": f"{type(exc).__name__}: {exc}",
                    "attempted_at": datetime.now(IST).isoformat(),
                }
                save_manifest(manifest, manifest_path)
                continue

            if not rows:
                empty += 1
                manifest["files"][file_key] = {
                    "path": rel_path, "status": "empty", "rows": 0,
                    "month_complete": complete,
                    "downloaded_at": datetime.now(IST).isoformat(),
                }
                logx(logging.INFO, "no candles returned", instrument=name, month=month_key)
                save_manifest(manifest, manifest_path)
                continue

            write_candles(rows, abs_path, args.format)
            manifest["files"][file_key] = {
                "path": rel_path,
                "status": "ok",
                "rows": len(rows),
                "first_ts": rows[0]["ts"].isoformat(),
                "last_ts": rows[-1]["ts"].isoformat(),
                "trading_days": len({r["ts"].date() for r in rows}),
                "sha256": sha256_file(abs_path),
                "instrument_token": token,
                "interval": INTERVAL,
                "month_complete": complete,
                "downloaded_at": datetime.now(IST).isoformat(),
            }
            save_manifest(manifest, manifest_path)
            downloaded += 1
            logx(logging.INFO, "saved", instrument=name, month=month_key,
                 rows=len(rows), days=manifest["files"][file_key]["trading_days"],
                 partial=not complete)

    logx(logging.INFO, "done", downloaded=downloaded, skipped=skipped, empty=empty, failed=failed)
    print(f"\ndownloaded {downloaded} · skipped {skipped} · empty {empty} · failed {failed}")
    print(f"manifest: {manifest_path}")
    print("\nnext:  python tools/verify_data.py")
    return 1 if failed else 0


# ─────────────────────────────────────────────────────────────────────────────
# login / instruments
# ─────────────────────────────────────────────────────────────────────────────
def cmd_login(args: argparse.Namespace) -> int:
    setup_logging(Path(args.out) / "fetch_log.jsonl", args.verbose)
    api_key = require_env("KITE_API_KEY", "the login URL")
    api_secret = require_env("KITE_API_SECRET", "exchanging the request token for an access token")

    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=api_key)
    request_token = args.request_token
    if not request_token:
        print("\n1. open this URL and log in:\n")
        print("   " + kite.login_url())
        print("\n2. you will be redirected to your registered redirect URL with")
        print("   ?request_token=XXXX in the address bar. Copy that value.\n")
        try:
            request_token = input("request_token: ").strip()
        except EOFError:
            log.error("no stdin — rerun with --request-token <value>")
            return 2
    if not request_token:
        log.error("empty request token")
        return 2

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
    except Exception as exc:
        log.error("generate_session failed: %s: %s", type(exc).__name__, exc)
        return 3

    path = save_access_token(session["access_token"], api_key)
    logx(logging.INFO, "session established", user_id=session.get("user_id"), cache=str(path))
    print(f"\naccess token cached at {path}")
    print("valid until 06:00 IST tomorrow. It is outside the repo and gitignored by location.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Prove the credentials are visible to this tool without revealing them.

    Prints length and an 8-char SHA-256 prefix only. The SHA is enough to confirm the
    value is the one you intended (compare it once) and useless to anyone reading a log.
    """
    print("credential visibility\n")
    ok = True
    for name, needed_for in (
        ("KITE_API_KEY", "every Kite call - REQUIRED"),
        ("KITE_API_SECRET", "the `login` step only"),
        ("KITE_ACCESS_TOKEN", "optional; the cache is used when this is unset"),
    ):
        value, source = read_credential(name)
        if value:
            digest = hashlib.sha256(value.encode()).hexdigest()[:8]
            print(f"  {name:<18} set    {len(value):>3} chars  sha256:{digest}  <- {source}")
        else:
            print(f"  {name:<18} NOT SET" + ("  <- blocks the download" if name == "KITE_API_KEY" else ""))
            if name == "KITE_API_KEY":
                ok = False

    env_path = env_file_path()
    print(f"\n  credentials file   {env_path}")
    print("                     " + ("present" if env_path.is_file() else "absent (fine if you used the environment)"))

    # `.env` matches both globs — deduplicate so one stray file is reported once
    strays = sorted({p.name for p in (set(REPO_ROOT.glob(".env*")) | set(REPO_ROOT.glob("*.env")))
                     if p.name != ".env.example"})
    if strays:
        print(f"\n  !! secret-shaped file(s) INSIDE the repo: {', '.join(strays)}")
        print("     Move them to the path above. .env.example is the only one that belongs here.")
        ok = False

    path = token_cache_path()
    print(f"\n  token cache        {path}")
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            issued = datetime.fromisoformat(payload["issued_at"])
            stale = token_is_stale(issued, datetime.now(IST))
            print(f"                     issued {issued:%Y-%m-%d %H:%M} IST - "
                  + ("EXPIRED, run `login` again" if stale else "valid"))
        except (OSError, ValueError, KeyError):
            print("                     unreadable - run `login` again")
    else:
        print("                     absent - run `login`")

    print(f"\n  repo scanned for leaked secrets: {REPO_ROOT}")
    leaked = []
    for name in ("KITE_API_KEY", "KITE_API_SECRET"):
        value, _ = read_credential(name)
        if not value:
            continue
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                if value in path.read_text(encoding="utf-8", errors="ignore"):
                    leaked.append((name, path.relative_to(REPO_ROOT)))
            except OSError:
                continue
    if leaked:
        for name, path in leaked:
            print(f"  !! {name} FOUND IN {path} - remove it, then rotate the credential")
        return 1
    print("                     clean\n")
    return 0 if ok else 3


def cmd_instruments(args: argparse.Namespace) -> int:
    setup_logging(Path(args.out) / "fetch_log.jsonl", args.verbose)
    api_key = require_env("KITE_API_KEY", "the instrument master")
    access_token = load_access_token(api_key)
    if not access_token:
        log.error("no usable access token. Run:  python tools/fetch_kite.py login")
        return 3

    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    resolved = resolve_instruments(kite, Throttle(args.rps), args.symbols or list(INSTRUMENTS))
    for name, meta in resolved.items():
        print(f"{name:20s} {meta['instrument_token']:>12}  {meta['exchange']}  {meta['segment']}")
    for name in (args.symbols or list(INSTRUMENTS)):
        if name not in resolved:
            print(f"{name:20s} {'NOT FOUND':>12}"
                  f"{'  (optional)' if name in OPTIONAL_INSTRUMENTS else '  ← REQUIRED'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO_ROOT / "data"), help="output root (default: data/)")
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS,
                        help=f"requests/second, hard ceiling {HISTORICAL_RPS} (default: {DEFAULT_RPS})")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="are the credentials visible? (never prints them)")
    p_check.set_defaults(func=cmd_check)

    p_login = sub.add_parser("login", help="daily access token")
    p_login.add_argument("--request-token", help="skip the interactive prompt")
    p_login.set_defaults(func=cmd_login)

    p_inst = sub.add_parser("instruments", help="resolve instrument tokens and exit")
    p_inst.add_argument("--symbols", nargs="*")
    p_inst.set_defaults(func=cmd_instruments)

    p_fetch = sub.add_parser("fetch", help="download 1m history")
    p_fetch.add_argument("--symbols", nargs="*")
    p_fetch.add_argument("--years", type=int, default=3, help="lookback in years (default: 3)")
    p_fetch.add_argument("--from", dest="from", help="YYYY-MM-DD, overrides --years")
    p_fetch.add_argument("--to", help="YYYY-MM-DD (default: today)")
    p_fetch.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    p_fetch.add_argument("--plan", action="store_true", help="print the request plan and exit")
    p_fetch.add_argument("--refetch", action="store_true", help="ignore the manifest, download everything")
    p_fetch.add_argument("--refetch-empty", action="store_true", help="retry months previously empty")
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MissingCredential as exc:
        print(f"\nBLOCKED — {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\ninterrupted — the manifest is current, rerun to resume", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
