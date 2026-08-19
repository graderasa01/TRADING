import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for extra in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


@pytest.fixture(autouse=True)
def isolate_credentials(tmp_path_factory, monkeypatch):
    """No test may ever see a real credential.

    Without this, `read_credential` falls through to the developer's own
    ~/.banknifty-copilot/.env — and a failing assertion then prints the live API key
    into the pytest diff, the terminal scrollback and CI logs. That happened once
    while writing these tests, which is exactly why this is autouse and not opt-in:
    the leak comes from the failure path, so it only appears on the days nobody is
    looking for it.

    A test that needs a credential sets its own; monkeypatch here runs first, so the
    test's setup wins.
    """
    empty = tmp_path_factory.mktemp("no-credentials")
    for name in ("KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BNC_ENV_FILE", str(empty / "absent.env"))
    monkeypatch.setenv("BNC_TOKEN_DIR", str(empty))

    import fetch_kite

    monkeypatch.setattr(fetch_kite, "_read_user_scope_env", lambda name: None)
    yield
