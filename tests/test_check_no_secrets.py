"""
A secret scanner is only worth having if it fails on a real leak and stays quiet on
ordinary code. Both directions are tested here, because a scanner with false positives
gets bypassed with --no-verify, which is worse than having none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_no_secrets as S

REAL_KEY = "z9x8c7v6b5n4m3q2"          # 16 lowercase alnum, like a Kite api_key
REAL_SECRET = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"   # 32, like a Kite api_secret


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(S, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(S, "live_credentials", lambda: {})
    return tmp_path


# ── it must catch a real leak ───────────────────────────────────────────────
def test_live_credential_value_in_any_file_is_caught(repo: Path, monkeypatch):
    monkeypatch.setattr(S, "live_credentials", lambda: {"KITE_API_SECRET": REAL_SECRET})
    (repo / "notes.md").write_text(f"remember: {REAL_SECRET}\n", encoding="utf-8")
    problems = S.scan(staged_only=False)
    assert len(problems) == 1
    assert "notes.md:1" in problems[0]
    assert "rotate" in problems[0], "a leaked secret is already compromised — say so"


def test_credential_shaped_assignment_is_caught(repo: Path):
    (repo / "config.py").write_text(f'api_key = "{REAL_KEY}"\n', encoding="utf-8")
    problems = S.scan(staged_only=False)
    assert len(problems) == 1 and "config.py:1" in problems[0]


def test_dotenv_inside_the_repo_is_caught_even_if_empty(repo: Path):
    (repo / ".env").write_text("", encoding="utf-8")
    problems = S.scan(staged_only=False)
    assert len(problems) == 1
    assert ".banknifty-copilot" in problems[0], "must say where it should go instead"


def test_scanner_returns_nonzero(repo: Path, monkeypatch):
    monkeypatch.setattr(S, "live_credentials", lambda: {"KITE_API_KEY": REAL_KEY})
    (repo / "leak.txt").write_text(REAL_KEY, encoding="utf-8")
    assert S.main([]) == 1


# ── and it must stay quiet on ordinary code ────────────────────────────────
def test_code_identifiers_are_not_flagged(repo: Path):
    (repo / "app.py").write_text(
        "access_token = load_access_token(api_key)\n"
        "api_key, source = read_credential('KITE_API_KEY')\n"
        'kite = KiteConnect(api_key=api_key)\n',
        encoding="utf-8",
    )
    assert S.scan(staged_only=False) == []


def test_test_fixtures_with_hyphenated_fake_values_are_not_flagged(repo: Path):
    (repo / "test_x.py").write_text(
        'F.save_access_token("tok-abc", api_key="super-secret-key")\n', encoding="utf-8"
    )
    assert S.scan(staged_only=False) == []


def test_env_example_with_placeholders_is_exempt(repo: Path):
    (repo / ".env.example").write_text(
        "KITE_API_KEY=your_api_key_here\nKITE_API_SECRET=your_api_secret_here\n", encoding="utf-8"
    )
    assert S.scan(staged_only=False) == []


def test_the_real_repo_is_clean():
    """The actual repository, scanned by the real rules. This is the regression."""
    assert S.scan(staged_only=False) == []
