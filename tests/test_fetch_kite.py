"""
The downloader cannot be tested against the API without credentials, but the parts
that can silently corrupt a three-year download are pure functions: the chunker
(which must never exceed Kite's 60-day limit), the resume predicate (which must
never treat today's half-written month as finished), and the token staleness rule.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

import pytest

import fetch_kite as F

IST = F.IST


# ── chunking ────────────────────────────────────────────────────────────────
def test_chunks_are_calendar_months_and_cover_the_range_exactly():
    chunks = list(F.month_chunks(date(2024, 11, 20), date(2025, 2, 3)))
    assert [k for k, _, _ in chunks] == ["2024-11", "2024-12", "2025-01", "2025-02"]
    assert chunks[0][1] == date(2024, 11, 20)      # clipped to --from
    assert chunks[0][2] == date(2024, 11, 30)
    assert chunks[-1][2] == date(2025, 2, 3)       # clipped to --to
    # no gaps, no overlaps
    for (_, _, end), (_, nxt, _) in zip(chunks, chunks[1:]):
        assert nxt == end + timedelta(days=1)


def test_no_chunk_can_exceed_the_60_day_api_limit():
    chunks = list(F.month_chunks(date(2023, 1, 1), date(2026, 8, 11)))
    assert len(chunks) == 44
    assert max((e - s).days + 1 for _, s, e in chunks) == 31 <= F.MAX_DAYS_PER_REQUEST


def test_single_day_range():
    assert list(F.month_chunks(date(2026, 3, 5), date(2026, 3, 5))) == \
        [("2026-03", date(2026, 3, 5), date(2026, 3, 5))]


# ── resume ──────────────────────────────────────────────────────────────────
def test_current_month_is_never_complete():
    today = date(2026, 8, 11)
    assert F.month_is_complete("2026-07", today) is True
    assert F.month_is_complete("2026-08", today) is False, "a partial month must be refetched"
    assert F.month_is_complete("2026-09", today) is False


def test_month_completeness_at_a_year_boundary():
    assert F.month_is_complete("2025-12", date(2026, 1, 1)) is True
    assert F.month_is_complete("2025-12", date(2025, 12, 31)) is False


# ── throttle ────────────────────────────────────────────────────────────────
def test_throttle_refuses_to_exceed_the_documented_rate():
    with pytest.raises(ValueError):
        F.Throttle(F.HISTORICAL_RPS + 0.5)
    assert F.Throttle(F.DEFAULT_RPS).min_interval == pytest.approx(1 / F.DEFAULT_RPS)


def test_throttle_actually_waits():
    import time

    t = F.Throttle(3.0)
    t.wait()
    start = time.monotonic()
    t.wait()
    assert time.monotonic() - start >= 1 / 3.0 - 0.02


# ── token lifetime ──────────────────────────────────────────────────────────
def test_token_dies_at_0600_ist_the_next_morning():
    issued = datetime(2026, 8, 11, 9, 0, tzinfo=IST)
    assert not F.token_is_stale(issued, datetime(2026, 8, 11, 23, 59, tzinfo=IST))
    assert not F.token_is_stale(issued, datetime(2026, 8, 12, 5, 59, tzinfo=IST))
    assert F.token_is_stale(issued, datetime(2026, 8, 12, 6, 0, tzinfo=IST))


# ── credentials never leak ──────────────────────────────────────────────────
def test_missing_credentials_raise_rather_than_default(monkeypatch):
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    with pytest.raises(F.MissingCredential):
        F.require_env("KITE_API_KEY", "test")


def test_process_environment_wins_over_the_registry(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "from-process")
    monkeypatch.setattr(F, "_read_user_scope_env", lambda name: "from-registry")
    assert F.read_credential("KITE_API_KEY") == ("from-process", "process environment")


def test_registry_is_the_fallback_when_the_process_env_is_stale(monkeypatch):
    """The whole point: a credential set after this process started is still found."""
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.setattr(F, "_read_user_scope_env", lambda name: "from-registry")
    value, source = F.read_credential("KITE_API_KEY")
    assert value == "from-registry" and "registry" in source


def test_blank_credential_is_treated_as_absent(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "   ")
    monkeypatch.setattr(F, "_read_user_scope_env", lambda name: None)
    assert F.read_credential("KITE_API_KEY") == (None, None)
    with pytest.raises(F.MissingCredential):
        F.require_env("KITE_API_KEY", "test")


def test_check_never_prints_the_credential(monkeypatch, capsys, tmp_path):
    secret = "supersecretvalue123"
    monkeypatch.setenv("KITE_API_KEY", secret)
    # the credentials dir must sit OUTSIDE the repo, or the guard fires — which is
    # itself the behaviour asserted by test_credentials_file_inside_the_repo_is_refused
    monkeypatch.setenv("BNC_TOKEN_DIR", str(tmp_path / "home"))
    monkeypatch.setattr(F, "REPO_ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    F.cmd_check(argparse.Namespace())
    out = capsys.readouterr().out
    assert secret not in out
    assert "sha256:" in out and str(len(secret)) in out


def test_check_fails_when_a_credential_leaked_into_the_repo(monkeypatch, capsys, tmp_path):
    secret = "supersecretvalue123"
    monkeypatch.setenv("KITE_API_KEY", secret)
    monkeypatch.setenv("BNC_TOKEN_DIR", str(tmp_path / "tok"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "notes.md").write_text(f"key = {secret}\n", encoding="utf-8")
    monkeypatch.setattr(F, "REPO_ROOT", repo)
    assert F.cmd_check(argparse.Namespace()) == 1
    assert "notes.md" in capsys.readouterr().out


# ── the credentials file (.env.example -> ~/.banknifty-copilot/.env) ────────
@pytest.fixture
def envfile(tmp_path, monkeypatch):
    """A credentials file at a path outside the repo, as .env.example instructs."""
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_API_SECRET", raising=False)
    monkeypatch.setattr(F, "_read_user_scope_env", lambda name: None)
    path = tmp_path / "home" / ".env"
    path.parent.mkdir()
    monkeypatch.setenv("BNC_ENV_FILE", str(path))
    return path


def test_env_file_is_read(envfile, monkeypatch):
    envfile.write_text(
        "# a comment\n"
        "\n"
        "KITE_API_KEY=abc123\n"
        'KITE_API_SECRET="def456"\n'
        "KITE_ACCESS_TOKEN=\n",
        encoding="utf-8",
    )
    assert F.read_credential("KITE_API_KEY")[0] == "abc123"
    assert F.read_credential("KITE_API_SECRET")[0] == "def456", "quotes must be stripped"
    assert F.read_credential("KITE_ACCESS_TOKEN")[0] is None, "an empty value is not a value"


def test_env_file_is_the_last_resort_not_the_first(envfile, monkeypatch):
    envfile.write_text("KITE_API_KEY=from-file\n", encoding="utf-8")
    assert F.read_credential("KITE_API_KEY")[0] == "from-file"
    monkeypatch.setattr(F, "_read_user_scope_env", lambda name: "from-registry")
    assert F.read_credential("KITE_API_KEY")[0] == "from-registry"
    monkeypatch.setenv("KITE_API_KEY", "from-process")
    assert F.read_credential("KITE_API_KEY")[0] == "from-process"


def test_missing_env_file_is_not_an_error(envfile):
    assert not envfile.exists()
    assert F.read_credential("KITE_API_KEY") == (None, None)


def test_credentials_file_inside_the_repo_is_refused(monkeypatch, tmp_path):
    """CLAUDE.md §4 / spec 08 §3.1 — no secret in the repo, gitignored or not."""
    monkeypatch.setattr(F, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("BNC_ENV_FILE", str(tmp_path / ".env"))
    with pytest.raises(F.CredentialInRepo):
        F.assert_env_file_outside_repo()
    with pytest.raises(F.CredentialInRepo):
        F.read_credential("KITE_API_KEY")


def test_default_credentials_file_is_outside_the_repo(monkeypatch):
    monkeypatch.delenv("BNC_ENV_FILE", raising=False)
    monkeypatch.delenv("BNC_TOKEN_DIR", raising=False)
    F.assert_env_file_outside_repo()          # must not raise
    assert F.REPO_ROOT not in F.env_file_path().parents


def test_cached_token_is_rejected_when_the_api_key_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("BNC_TOKEN_DIR", str(tmp_path))
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)
    F.save_access_token("tok-abc", api_key="key-one")
    assert F.load_access_token("key-one") == "tok-abc"
    assert F.load_access_token("key-two") is None, "a token from another key must not be reused"


def test_token_file_never_contains_the_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("BNC_TOKEN_DIR", str(tmp_path))
    F.save_access_token("tok-abc", api_key="super-secret-key")
    body = (tmp_path / "kite_token.json").read_text(encoding="utf-8")
    assert "super-secret-key" not in body
    assert "tok-abc" in body


def test_token_cache_path_is_outside_the_repo(monkeypatch):
    monkeypatch.delenv("BNC_TOKEN_DIR", raising=False)
    assert F.REPO_ROOT not in F.token_cache_path().parents


# ── layout ──────────────────────────────────────────────────────────────────
def test_symbol_dir_is_filesystem_safe():
    assert F.symbol_dir("NIFTY FIN SERVICE") == "NIFTY_FIN_SERVICE"
    assert F.symbol_dir("SENSEX") == "SENSEX"


def test_api_rows_are_sorted_and_tz_aware():
    raw = [
        {"date": datetime(2026, 3, 2, 9, 16, tzinfo=IST), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 0},
        {"date": datetime(2026, 3, 2, 9, 15, tzinfo=IST), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 0},
    ]
    rows = F.rows_from_api(raw)
    assert [r["ts"].minute for r in rows] == [15, 16]
    assert all(r["ts"].tzinfo is not None for r in rows)
