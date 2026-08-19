"""
The hard safety guarantees for the promoted participation engine.

Promotion moved a validated research contract into `src/`, where the trading path could in
principle reach it. These are the assertions that say it cannot, stated statically where
possible and dynamically where not:

```
candidate cannot reach a broker          static import audit
candidate cannot become an order         source audit for the order vocabulary
candidate cannot create size or risk     field audit + import audit
candidate cannot touch the holdout       the engine never imports the split at all
candidate cannot mutate the observation  before/after deep comparison of every layer
candidate cannot auto-reverse            tests/test_reactor.py
candidate cannot duplicate               tests/test_reactor.py
candidate cannot use future data         tests/test_reactor.py, prefix causality
candidate cannot use an old generation   tests/test_reactor.py
```

`tests/test_livemap_quarantine.py` already asserts that `setups/ risk/ exits/ modes/
broker/ guards/ options/` do not import `livemap`, and it globs the package, so the three
promoted modules are covered by it the moment they exist. These tests assert the other
direction and the things a glob cannot see.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.boxes.frontier import Frontier
from src.livemap import participation as PE
from src.livemap import reactor as RE
from src.livemap import release as R
from src.livemap import thesis as TH
from src.livemap.interpreter import Interpreter
from tests.test_participation import block

SRC = Path(__file__).resolve().parent.parent / "src"
ENGINE = ("livemap/thesis.py", "livemap/participation.py", "livemap/reactor.py")


def engine_files() -> list[Path]:
    return [SRC / name for name in ENGINE]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# the engine cannot reach anything that trades
# ═════════════════════════════════════════════════════════════════════════════
def test_the_engine_files_all_exist():
    """A safety suite that silently checks nothing is worse than no safety suite."""
    missing = [str(p) for p in engine_files() if not p.exists()]
    assert not missing, missing


@pytest.mark.parametrize("name", ENGINE)
def test_the_engine_imports_no_trading_path_module(name):
    forbidden = ("broker", "risk", "sizing", "options", "setups", "exits", "modes",
                 "guards", "journal")
    mods = imported_modules(SRC / name)
    offenders = [m for m in mods
                 for f in forbidden
                 if m == f or m.startswith(f"src.{f}") or m.startswith(f"{f}.")]
    assert not offenders, f"{name} imports {offenders}"


@pytest.mark.parametrize("name", ENGINE)
def test_the_engine_never_reads_the_split(name):
    """No holdout dependency, of any kind. The engine does not know a split exists, so it
    cannot spend one — and `HOLDOUT-EXPOSURE.md` explains why that matters."""
    mods = imported_modules(SRC / name)
    assert not [m for m in mods if "split" in m or "learning" in m], name


@pytest.mark.parametrize("name", ENGINE)
def test_the_engine_carries_no_order_vocabulary(name):
    """`ENTER_*`, `BUY`, `SELL`, an order call or a size. The contract's own `FORBIDDEN`
    tuples say the same thing about rendered output; this says it about the source."""
    text = (SRC / name).read_text(encoding="utf-8")
    # strip the prose: a docstring is allowed to explain what is forbidden
    tree = ast.parse(text)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                docstrings.add(doc)
    code = text
    for doc in docstrings:
        code = code.replace(doc, "")
    code = re.sub(r"#.*", "", code)

    for word in ("ENTER_LONG", "ENTER_SHORT", "place_order", "modify_order",
                 "cancel_order", "lot_size", "quantity"):
        assert word not in code, f"{name} contains {word!r} outside its prose"


def test_no_decision_field_can_carry_a_position_size():
    from dataclasses import fields
    banned = ("size", "qty", "quantity", "lots", "capital", "risk", "reward",
              "margin", "premium", "strike", "limit", "stop", "target")
    for cls in (RE.ParticipationDecision, PE.ParticipationContext):
        bad = [f.name for f in fields(cls)
               if any(b in f.name.lower() for b in banned)]
        assert not bad, f"{cls.__name__} carries {bad}"


def test_the_action_vocabulary_can_never_authorise_an_order():
    assert not any(a.startswith("ENTER") or a in ("BUY", "SELL", "ORDER")
                   for a in RE.ACTIONS)
    assert not any("REVERS" in a for a in RE.ACTIONS)


def test_the_default_contract_can_never_resolve_execution():
    ctr = RE.NoExecution()
    assert ctr.status(None) == RE.EXEC_UNAVAILABLE
    assert ctr.resolves(None) is False
    assert ctr.validated is False


# ═════════════════════════════════════════════════════════════════════════════
# the engine cannot mutate what it reads
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def world():
    return block(0)


def observation_fingerprint(snap, f: Frontier):
    """Everything the engine reads, captured deeply enough that a mutation would show."""
    interp = Interpreter(snap, f)
    return {
        "readings": list(f.readings),
        "log": [(e.kind, e.index, e.node_id, e.direction, e.level) for e in f.log],
        "live_log": [(e.kind, e.index, e.node_id, e.direction, e.level)
                     for e in f.live_log],
        "history": [(n.id, n.kind, n.start, n.end, n.low, n.high) for n in f.history()],
        "snapshot": [(n.id, n.kind, n.low, n.high, n.parent) for n in snap.nodes],
        "candles": list(f.candles),
        "releases": list(R.observe(f, snap)),
        "thesis": list(TH.narrate(snap, f)),
        "route": [(s.index, s.route_above, s.route_below, s.above.corridor,
                   s.below.corridor) for s in interp.states()],
    }


def test_the_engine_mutates_no_observation(world):
    """§14. Every layer the engine consumes must be byte-identical afterwards — the
    observation, the releases, the thesis and the route."""
    snap, f = world
    before = observation_fingerprint(snap, f)
    RE.replay(snap, f)
    RE.replay(snap, f, execution=RE.ImmediateExecution())
    PE.eye(snap, f)
    after = observation_fingerprint(snap, f)
    for key in before:
        assert before[key] == after[key], f"the engine mutated {key}"


def test_the_engine_adds_nothing_to_the_map(world):
    snap, f = world
    ids_before = {n.id for n in f.history()} | {n.id for n in snap.nodes}
    decisions = RE.replay(snap, f)
    ids_after = {n.id for n in f.history()} | {n.id for n in snap.nodes}
    assert ids_before == ids_after
    release_ids = {r.id for d in decisions for r in d.context.all_releases}
    assert not (release_ids & ids_after), "a release id reached the map"


# ═════════════════════════════════════════════════════════════════════════════
# the capability the whole build exists for
# ═════════════════════════════════════════════════════════════════════════════
def test_inner_participation_is_possible_while_the_parent_is_intact(world):
    """§10 of the brief, asserted on real candles rather than described.

    An inner cluster releases, the parent has not broken, price is beyond the inner edge
    and still inside the parent — and the engine is able to produce a candidate without
    waiting for the outer box.
    """
    snap, f = world
    inner = [d for d in RE.replay(snap, f)
             if d.context.release is not None
             and d.context.release_scale == R.INNER]
    assert inner, "no inner release in this block — the assertion would be vacuous"
    intact = [d for d in inner if d.context.parent_location in
              (R.INSIDE_PARENT, R.AT_PARENT_EDGE)]
    assert intact, "no inner release happened while the parent was intact"
    for d in intact:
        assert d.context.release.parent_id is not None
        assert d.context.release.route is None or \
            d.context.release.route.origin_edge == d.context.release.broken_edge


def test_multi_scale_releases_are_preserved_through_the_decision(world):
    snap, f = world
    for d in RE.replay(snap, f):
        rel = d.context.all_releases
        if len(rel) > 1:
            assert len({r.id for r in rel}) == len(rel)
            assert d.context.release in rel
            scales = {r.scale for r in rel}
            if len(scales) > 1:
                assert d.context.controlling_scale == R.MULTI_SCALE
