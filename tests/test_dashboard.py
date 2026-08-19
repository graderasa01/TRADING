"""The observatory dashboard — `tools/dashboard/`.

A dashboard is a view. These are the assertions that it stayed one:

```
composition   every rendered value is a copy of a production field
no-lookahead  the payload for candle k contains nothing from candle k+1
one engine    the live route and the historical route produce identical frames
safety        no order/broker/sizing/risk vocabulary anywhere in the dashboard
              no route can execute; EXECUTION_STATUS is UNAVAILABLE
holdout       the picker offers teach only, and `split.holdout()` is never called
view-only     the browser code derives no parent, route, thesis or identity
```
"""
from __future__ import annotations

import ast
import json
import re
import threading
import urllib.request
from pathlib import Path

import pytest

from src.livemap import observatory as OB
from src.livemap import reactor as RE
from tools.dashboard import sessions as S
from tools.dashboard.feed import KiteSource, PacedSource, ReplaySource
from tools.dashboard.server import serve

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "tools" / "dashboard"
STATIC = DASH / "static"


@pytest.fixture(scope="module")
def session():
    return S.load("block0")


@pytest.fixture(scope="module")
def built():
    return S.build("block0", paper=True)


# ═════════════════════════════════════════════════════════════════════════════
# COMPOSITION — the payload copies, it does not compute
# ═════════════════════════════════════════════════════════════════════════════
def test_the_payload_matches_the_production_frames(session, built):
    snapshot = session.snapshot
    execution = S.contract_for(session, True)
    frames = OB.frames(snapshot, list(session.history), list(session.live),
                       execution=execution)
    assert len(built["frames"]) == len(frames)
    for row, frame in zip(built["frames"], frames):
        assert row["i"] == frame.index
        assert row["action"] == frame.action
        assert row["phase"] == frame.state.phase
        assert row["pos"] == frame.state.position_after
        assert row["exec"] == frame.execution_status
        assert row["thesis"]["identity"] == (str(frame.context.thesis_identity)
                                             if frame.context.thesis_identity else None)
        assert row["why"]["codes"] == list(frame.why.codes)
        assert row["eye"] == [[q, a] for q, a in OB.trader_eye(frame)]


def test_every_box_in_the_payload_is_a_box_the_frame_froze(session, built):
    snapshot = session.snapshot
    frames = OB.frames(snapshot, list(session.history), list(session.live),
                       execution=S.contract_for(session, True))
    for row, frame in zip(built["frames"], frames):
        assert [b["id"] for b in row["boxes"]] == [b.id for b in frame.geometry.boxes]
        assert [b["p"] for b in row["boxes"]] == [b.parent for b in frame.geometry.boxes]


def test_the_payload_never_carries_a_future_field(built):
    """The frame for candle k must mention no candle after k."""
    frames = built["frames"]
    for k, row in enumerate(frames):
        i = row["i"]
        for b in row["boxes"]:
            if b["st"] == "HISTORICAL":
                continue
            assert b["s"] <= i, f"c{i} carries a box starting at {b['s']}"
            assert b["e"] is None or b["e"] <= i, f"c{i} carries a box ending at {b['e']}"
        if row["entry"]:
            assert row["entry"]["index"] <= i


def test_the_payload_is_json_serialisable_and_holds_no_decimals(built):
    text = json.dumps(built)
    assert "Decimal" not in text
    assert len(text) > 1000


# ═════════════════════════════════════════════════════════════════════════════
# ONE ENGINE — the live route is the historical route
# ═════════════════════════════════════════════════════════════════════════════
def test_the_live_route_and_the_historical_route_agree(session):
    """The dashboard's live mode drives `LiveSession`; its historical mode calls
    `frames()`. If those ever differ, a replay and a broker feed are two systems."""
    snapshot = session.snapshot
    execution = S.contract_for(session, True)
    batch = OB.frames(snapshot, list(session.history), list(session.live),
                      execution=execution)
    engine = OB.LiveSession(snapshot, list(session.history), execution=execution)
    for candle in session.live:
        engine.on_candle(candle)
    assert [S.frame_json(f) for f in engine.frames] == [S.frame_json(f) for f in batch]


def test_a_paced_source_yields_exactly_the_replay_candles(session):
    paced = PacedSource(session.live[:3], seconds=0.0)
    assert list(paced.candles()) == list(ReplaySource(session.live[:3]).candles())
    assert paced.live is True and ReplaySource([]).live is False


def test_the_broker_source_refuses_rather_than_pretending(session):
    """A live mode that is secretly a replay is worse than no live mode."""
    with pytest.raises(NotImplementedError) as exc:
        list(KiteSource().candles())
    assert "not built" in str(exc.value).lower()
    assert "market data only" in str(exc.value).lower()


# ═════════════════════════════════════════════════════════════════════════════
# SAFETY
# ═════════════════════════════════════════════════════════════════════════════
def dash_files():
    return sorted(p for p in DASH.rglob("*.py")) + [ROOT / "tools" / "dash.py"]


def test_the_dashboard_imports_nothing_that_can_trade():
    forbidden = ("broker", "orders", "risk", "sizing", "options", "setups", "exits",
                 "modes", "guards", "journal")
    for path in dash_files():
        mods = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
        bad = [m for m in mods for f in forbidden
               if m == f or m.startswith(f"src.{f}") or m.startswith(f"{f}.")]
        assert not bad, f"{path.name} imports {bad}"


def test_no_dashboard_file_carries_order_vocabulary():
    words = ("ENTER_LONG", "ENTER_SHORT", "place_order", "modify_order", "cancel_order",
             "lot_size", "quantity", "position_size")
    for path in list(dash_files()) + list(STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                    doc = ast.get_docstring(node)
                    if doc:
                        text = text.replace(doc, "")
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"#.*", "", text)
        for w in words:
            assert w not in text, f"{path.name} contains {w!r} outside its prose"


def test_the_server_exposes_no_route_that_could_execute():
    src = (DASH / "server.py").read_text(encoding="utf-8")
    routes = set(re.findall(r'url\.path == "([^"]+)"', src))
    assert routes <= {"/api/catalog", "/api/session", "/api/live/poll",
                      "/api/live/open", "/api/live/stop"}, routes
    for bad in ("order", "trade", "execute", "buy", "sell", "size"):
        assert not [r for r in routes if bad in r], routes


def test_the_catalog_offers_teach_only():
    """No tool in this repo reads the holdout, and the picker cannot offer one."""
    from src.learning.split import load_split
    sp = load_split()
    cat = S.catalog()
    for d in cat["days"]:
        assert sp.bucket_of(d["label"]) == "teach", d


def test_loading_a_non_teach_day_is_refused():
    from src.feed.replay_feed import ReplayFeed
    from src.learning.split import load_split
    sp = load_split()
    other = next((d for d in ReplayFeed("NIFTY BANK", on_gap="skip").available_days()
                  if sp.bucket_of(d) != "teach"), None)
    if other is None:
        pytest.skip("every available day is teach")
    with pytest.raises(KeyError):
        S.load(f"day{other}")


def test_the_default_session_opens_no_position():
    payload = S.build("block0", paper=False)
    assert payload["contract"] == "NoExecution"
    assert payload["validated"] is False
    assert {f["phase"] for f in payload["frames"]} == {"FLAT"}
    assert {f["pos"] for f in payload["frames"]} == {"FLAT"}
    assert payload["execution_status"] == RE.EXEC_UNAVAILABLE


def test_a_paper_session_is_labelled_paper_everywhere(built):
    assert built["contract"] == "ResearchPositionInjector"
    assert built["validated"] is False
    assert built["execution_status"] == RE.EXEC_UNAVAILABLE
    positioned = [f for f in built["frames"] if f["phase"] != "FLAT"]
    assert positioned, "the research contract opened nothing — assertion vacuous"
    assert {f["exec"] for f in built["frames"] if f["disposition"]} <= {"RESOLVED"}


# ═════════════════════════════════════════════════════════════════════════════
# VIEW-ONLY — the browser derives nothing
# ═════════════════════════════════════════════════════════════════════════════
def test_the_browser_code_derives_no_production_fact():
    """The visual layer must not recompute nesting, route, thesis or identity. The first
    version of `scenarios()` compared two price bands to decide nesting and reported it on
    284 of 300 candles against the map's own 18 — a layer that re-derives another layer's
    fact gets it wrong."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    banned = [
        (r"\.lo\s*<\s*\w+\.lo", "comparing two box bands — nesting is `node.parent`"),
        (r"\bidentity\s*=\s*[^=]", "building a thesis identity"),
        (r"generation\s*\+\s*1", "advancing a generation"),
        (r"\bfree_to_near\b\s*[-+*/]", "recomputing the route"),
    ]
    for pattern, why in banned:
        assert not re.search(pattern, js), f"app.js derives a production fact: {why}"


def test_the_viewport_module_knows_nothing_about_the_domain():
    """It was extracted to be reusable; a chart interaction layer that knows what a
    thesis is has stopped being one."""
    js = (STATIC / "viewport.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    for word in ("thesis", "release", "identity", "participation", "position",
                 "candle", "box"):
        assert word not in js.lower(), f"viewport.js mentions {word!r}"


def test_the_page_loads_no_external_resource():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for url in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert url.startswith("/static/"), f"external resource {url}"


# ═════════════════════════════════════════════════════════════════════════════
# THE SERVER, end to end
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def live_server():
    httpd = serve("127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=120) as r:
        return json.loads(r.read())


def test_the_server_serves_the_page_and_its_assets(live_server):
    for path in ("/", "/static/app.css", "/static/app.js", "/static/viewport.js"):
        with urllib.request.urlopen(live_server + path, timeout=30) as r:
            assert r.status == 200
            assert r.read()


def test_the_catalog_route_lists_blocks_and_scenarios(live_server):
    cat = get(live_server, "/api/catalog")
    assert len(cat["blocks"]) == S.TEACH_BLOCKS
    assert set(cat["scenarios"]) == set(OB.SCENARIOS)


def test_the_session_route_returns_frames(live_server):
    payload = get(live_server, "/api/session?key=block0")
    assert len(payload["frames"]) == 300
    assert payload["execution_status"] == "UNAVAILABLE"
    assert payload["questions"] == list(OB.EYE_QUESTIONS)


def test_an_unknown_session_is_a_404_not_a_crash(live_server):
    try:
        get(live_server, "/api/session?key=block999")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        pytest.fail("a missing block should 404")


def test_the_trader_panel_answers_the_nine_questions(built):
    for row in built["frames"][:60]:
        assert [q for q, _ in row["eye"]] == list(OB.EYE_QUESTIONS)
        assert all(a for _, a in row["eye"])


def test_the_scenarios_are_the_production_ones(built):
    assert set(built["scenarios"]) == set(OB.SCENARIOS)
    assert set(built["scenario_names"]) == set(OB.SCENARIOS)
