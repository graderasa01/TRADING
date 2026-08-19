"""The EXECUTION BOUNDARY — `src/livemap/boundary.py`.

The reactive trader is now responsible for observation, thesis, participation and
position management. These are the assertions that it **stops** before execution, stated
structurally where possible and on real candles where not:

```
§24 purity        no broker / order / risk / sizing / options import, anywhere upstream
§24 isolation     a candidate cannot create a position, an order, a size or a risk
§24 NoExecution   every candidate resolves to UNAVAILABLE; none becomes RESOLVED
§24 lifecycle     HOLD and EXIT stay inside the lifecycle; injection is explicit
§24 causality     boundary output is prefix-causal
§24 determinism   boundary output is deterministic
§17 shape         no order-shaped field can exist on the boundary object
§23 separation    a research resolution is visible as research in the object itself
```
"""
from __future__ import annotations

import ast
import re
from dataclasses import fields
from pathlib import Path

import pytest

from src.livemap import boundary as B
from src.livemap import participation as PE
from src.livemap import position as POS
from src.livemap import reactor as RE
from tests.test_participation import block

SRC = Path(__file__).resolve().parent.parent / "src"
#: The whole reactive side. The boundary is only a boundary if nothing upstream of it
#: can reach a broker either.
REACTIVE = ("livemap/thesis.py", "livemap/release.py", "livemap/participation.py",
            "livemap/reactor.py", "livemap/position.py", "livemap/boundary.py")


def imported_modules(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def code_without_prose(path: Path) -> str:
    """The source with docstrings and comments removed — a module is allowed to
    *explain* what it refuses to do."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                text = text.replace(doc, "")
    return re.sub(r"#.*", "", text)


@pytest.fixture(scope="module")
def world():
    return block(0)


@pytest.fixture(scope="module")
def candidates(world):
    snap, f = world
    return [d for d in RE.replay(snap, f) if d.is_candidate]


# ═════════════════════════════════════════════════════════════════════════════
# §24 — BOUNDARY PURITY
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", REACTIVE)
def test_the_reactive_side_imports_nothing_that_can_trade(name):
    """§19. `broker`, `orders`, `risk`, `sizing`, `options` must remain absent from the
    whole reactive path, not only from the boundary file."""
    forbidden = ("broker", "orders", "order", "risk", "sizing", "size", "options",
                 "setups", "exits", "modes", "guards", "journal")
    mods = imported_modules(SRC / name)
    offenders = [m for m in mods for f in forbidden
                 if m == f or m.startswith(f"src.{f}") or m.startswith(f"{f}.")]
    assert not offenders, f"{name} imports {offenders}"


@pytest.mark.parametrize("name", REACTIVE)
def test_the_reactive_side_never_reads_the_split(name):
    """No holdout dependency of any kind — it cannot spend what it cannot see."""
    mods = imported_modules(SRC / name)
    assert not [m for m in mods if "split" in m or "learning" in m], name


def test_the_boundary_carries_no_order_vocabulary():
    code = code_without_prose(SRC / "livemap" / "boundary.py")
    for word in ("ENTER_LONG", "ENTER_SHORT", "place_order", "modify_order",
                 "cancel_order", "submit", "BUY", "SELL"):
        assert word not in code, f"boundary.py contains {word!r} outside its prose"


def test_no_boundary_field_can_be_order_shaped():
    """§17. The object may not carry quantity, lots, size, margin, premium, strike, a
    limit or stop price, a target or a broker order id."""
    bad = [f.name for f in fields(B.ExecutionRequest)
           if any(w in f.name.lower() for w in B.FORBIDDEN)]
    assert not bad, f"ExecutionRequest carries {bad}"


def test_the_boundary_object_is_immutable(candidates):
    req = B.boundary_of(candidates[0])
    with pytest.raises(Exception):
        req.execution_status = RE.EXEC_RESOLVED


def test_the_boundary_reuses_the_reactors_execution_vocabulary():
    """§2. One status vocabulary, not two. The boundary adds a *disposition* and
    reuses `reactor.EXEC_*` verbatim for the status axis."""
    assert set(B.DISPOSITION_OF) == set(RE.EXEC_STATES)
    code = code_without_prose(SRC / "livemap" / "boundary.py")
    for literal in ('"UNAVAILABLE"', '"PENDING"', '"RESOLVED"', '"NOT_APPLICABLE"'):
        assert literal not in code, (
            f"boundary.py restates {literal} instead of reusing reactor's constant")


# ═════════════════════════════════════════════════════════════════════════════
# §24 — CANDIDATE ISOLATION
# ═════════════════════════════════════════════════════════════════════════════
def test_a_candidate_cannot_create_a_position_by_itself(world):
    """§20 / §31. Under the production default nothing opens, on every candle."""
    snap, f = world
    states, records = POS.lifecycle(snap, f)
    assert records == []
    assert {s.phase for s in states} == {POS.FLAT_PHASE}
    assert {s.position_after for s in states} == {PE.FLAT}


def test_a_candidate_cannot_create_an_order_or_a_size(candidates):
    req = B.boundary_of(candidates[0])
    assert req.creates_an_order is False
    for word in B.FORBIDDEN:
        assert not hasattr(req, word), f"the boundary exposed {word}"


def test_only_a_candidate_reaches_the_boundary(world):
    """§20. `HOLD` and `EXIT` are position management and never cross the seam."""
    snap, f = world
    ids = POS.candidates_in(RE.replay(snap, f, execution=RE.ImmediateExecution()))
    inj = POS.ResearchPositionInjector(ids)
    for d in RE.replay(snap, f, execution=inj):
        req = B.boundary_of(d, execution=inj)
        if d.action in (RE.HOLD_LONG, RE.HOLD_SHORT, RE.EXIT_LONG, RE.EXIT_SHORT,
                        RE.WATCH, RE.NO_TRADE):
            assert req is None, f"{d.action} reached the execution boundary"
        else:
            assert req is not None and req.decision_action in RE.CANDIDATES


def test_a_non_candidate_cannot_be_forced_through_the_boundary_object():
    with pytest.raises(ValueError):
        B.ExecutionRequest(
            opportunity_id=("X", 1, 1), thesis_identity=None,
            position_side=PE.LONG, decision_action=RE.HOLD_LONG, decision_index=1,
            decision_timestamp=__import__("datetime").datetime(2026, 1, 1),
            execution_status=RE.EXEC_UNAVAILABLE,
            execution_reason="", disposition=B.NO_CONTRACT)


# ═════════════════════════════════════════════════════════════════════════════
# §24 — NoExecution
# ═════════════════════════════════════════════════════════════════════════════
def test_every_candidate_resolves_to_unavailable(candidates):
    """§18. With `NoExecution`, always. No candidate becomes `RESOLVED`."""
    assert candidates, "no candidate in this block — the assertion would be vacuous"
    reqs = [B.boundary_of(d) for d in candidates]
    assert {r.execution_status for r in reqs} == {RE.EXEC_UNAVAILABLE}
    assert {r.disposition for r in reqs} == {B.NO_CONTRACT}
    assert not [r for r in reqs if r.execution_status == RE.EXEC_RESOLVED]
    assert {r.execution_reason for r in reqs} == {B.NO_EXECUTION_CONTRACT_EXISTS}
    assert not any(r.contract_validated for r in reqs)


def test_no_order_shaped_payload_exists_anywhere_in_the_boundary_output(candidates):
    reqs = B.requests(candidates)
    for r in reqs:
        for f in fields(r):
            assert not any(w in f.name.lower() for w in B.FORBIDDEN)
    c = B.census(reqs)
    assert c["orders created"] == 0
    assert c["research resolutions"] == 0
    assert c["by disposition"] == {B.NO_CONTRACT: len(reqs)}


def test_the_boundary_never_invents_a_resolved_state(world):
    """§18 / §21. `PENDING` and `RESOLVED` are vocabulary a future contract may use;
    nothing in production produces them."""
    snap, f = world
    reqs = B.requests(RE.replay(snap, f))
    assert not [r for r in reqs
                if r.execution_status in (RE.EXEC_PENDING, RE.EXEC_RESOLVED)]


# ═════════════════════════════════════════════════════════════════════════════
# §23 — RESEARCH AND LIVE CAN NEVER BE CONFUSED
# ═════════════════════════════════════════════════════════════════════════════
def test_a_research_resolution_is_visible_as_research(world):
    snap, f = world
    ids = POS.candidates_in(RE.replay(snap, f, execution=RE.ImmediateExecution()))
    inj = POS.ResearchPositionInjector(ids)
    reqs = B.requests(RE.replay(snap, f, execution=inj), execution=inj)
    resolved = [r for r in reqs if r.execution_status == RE.EXEC_RESOLVED]
    assert resolved, "the research contract resolved nothing — assertion vacuous"
    for r in resolved:
        assert r.is_research is True
        assert r.contract_validated is False
        assert r.contract == "ResearchPositionInjector"
        assert r.creates_an_order is False


def test_no_contract_in_the_repository_is_validated():
    for cls in (RE.NoExecution, RE.ImmediateExecution, POS.ResearchPositionInjector):
        assert cls.validated is False, f"{cls.__name__} claims to be validated"


def test_the_research_injector_cannot_be_constructed_empty():
    """§31. There is no 'open everything' mode, and research is never a default."""
    with pytest.raises(ValueError):
        POS.ResearchPositionInjector([])


def test_a_production_call_defaults_to_no_execution(world):
    snap, f = world
    reqs = B.requests(RE.replay(snap, f))
    assert {r.contract for r in reqs} == {"NoExecution"}


# ═════════════════════════════════════════════════════════════════════════════
# §24 — CAUSALITY and DETERMINISM
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("k", [25, 50, 100, 200])
def test_boundary_output_is_prefix_causal(world, k):
    snap, f = world
    full = RE.replay(snap, f)
    cut_index = full[k].index
    a = B.requests(RE.replay(snap, f, upto=cut_index))
    b = [r for r in B.requests(full) if r.decision_index <= cut_index]
    assert [r.line() for r in a] == [r.line() for r in b]


def test_boundary_output_is_deterministic(world):
    snap, f = world
    a = B.requests(RE.replay(snap, f))
    b = B.requests(RE.replay(snap, f))
    assert [r.lines() for r in a] == [r.lines() for r in b]


def test_the_boundary_mutates_nothing(world, candidates):
    """It copies from the decision; the decision must be untouched afterwards."""
    before = [d.line() for d in candidates]
    B.requests(candidates)
    assert [d.line() for d in candidates] == before


# ═════════════════════════════════════════════════════════════════════════════
# §22 — THE BOUNDARY TRACE
# ═════════════════════════════════════════════════════════════════════════════
def test_the_boundary_trace_ends_at_unavailable(candidates):
    req = B.boundary_of(candidates[0])
    text = "\n".join(req.lines())
    assert RE.EXEC_UNAVAILABLE in text
    assert B.NO_CONTRACT in text
    assert "NO ORDER" in text
    assert "NO POSITION" in text
