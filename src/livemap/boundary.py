"""The EXECUTION BOUNDARY — where the reactive trader stops, and why it stops there.

```
Reactive Decision  →  Execution Boundary  →  Execution Contract  →  Broker / Order Engine
      reactor.py          this module          UNAVAILABLE              does not exist
```

The reactive core now owns observation, release, thesis, thesis identity, participation,
the trade thesis snapshot and the position lifecycle. It owns `HOLD` and it owns `EXIT`.
**It does not own execution, and this module is the seam that says so out loud** rather
than leaving the absence to be inferred from the fact that nobody wrote a broker yet.

## An `ExecutionRequest` is not an order

It is the statement *"the reactive trader has reached the point where an external
execution contract may decide whether and how to execute."* It carries the minimum a
future execution layer would need to identify **which** opportunity and **which** thesis
is being handed over, and deliberately nothing about how much:

```
carried    opportunity_id · thesis_identity · position_side · decision_action
           decision_timestamp · execution_status · execution_reason
           trade_thesis_snapshot (reference) · contract · contract_validated

NEVER      quantity · lots · size · margin · premium · strike · limit price
           stop price · target · broker order id
```

`__post_init__` refuses any of the forbidden vocabulary as an attribute, and
`tests/test_boundary.py` asserts the same thing about the class and about this file's
imports. The absence is structural, not a convention someone has to remember.

## Two axes, and they are not the same axis

`reactor.EXEC_*` already answers *"is execution timing solved?"* — it is reused verbatim
here rather than restated, because a second copy of a status vocabulary is how two layers
start disagreeing. What this module adds is the **disposition**: what the boundary itself
did with the candidate.

```
EXECUTION_STATUS   UNAVAILABLE | PENDING | RESOLVED | NOT_APPLICABLE   (reactor's)
DISPOSITION        NO_EXECUTION_CONTRACT | AWAITING_EXECUTION_CONTRACT
                   | EXECUTION_CONTRACT_RESOLVED                        (this module's)
```

Under production's default `NoExecution`, every candidate resolves to
`EXECUTION_STATUS = UNAVAILABLE` and `NO_EXECUTION_CONTRACT`, always. There is no
resolver here and none is being written: six execution studies produced no rule that
survived teach → validate, so `PENDING` and `RESOLVED` exist as vocabulary a future
contract may use and are **never produced by anything in this repository** except an
explicitly-named, `validated = False` research contract.

## Research and live can never be confused

A research contract can report `RESOLVED` — `ResearchPositionInjector` does, because the
lifecycle has to be exercised on something. So every request carries the contract's own
name and its `validated` flag, and `is_research` is true whenever a resolution came from
an unvalidated contract. A `RESOLVED` that nobody validated is visible as research in the
object itself, not only in the call site that produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime

from src.livemap import reactor as RE
from src.livemap import thesis as TH
from src.livemap.participation import FLAT, LONG, POSITIONS, SHORT

# ── §18 the boundary's own vocabulary. Closed, and it is a DISPOSITION, not a
#    second execution status: `reactor.EXEC_*` already owns that question. ────
NO_CONTRACT = "NO_EXECUTION_CONTRACT"
AWAITING_CONTRACT = "AWAITING_EXECUTION_CONTRACT"
CONTRACT_RESOLVED = "EXECUTION_CONTRACT_RESOLVED"
#: Deliberately NOT named `RESOLVED`: `reactor.EXEC_RESOLVED` already carries that word
#: on the other axis, and two neighbouring modules exporting one name for two different
#: facts is the ambiguity this whole stage exists to remove.
DISPOSITIONS = frozenset({NO_CONTRACT, AWAITING_CONTRACT, CONTRACT_RESOLVED})

#: The disposition each of `reactor`'s execution statuses maps to. One mapping, so the
#: two axes cannot drift apart in a caller's head.
DISPOSITION_OF = {
    RE.EXEC_UNAVAILABLE: NO_CONTRACT,
    RE.EXEC_PENDING: AWAITING_CONTRACT,
    RE.EXEC_RESOLVED: CONTRACT_RESOLVED,
    RE.EXEC_NA: NO_CONTRACT,
}

#: §17. Anything shaped like an order. Checked against the class's own fields and
#: against every attribute at construction — a boundary object that could carry a size
#: is a boundary that has already been crossed.
FORBIDDEN = ("quantity", "qty", "lots", "lot_size", "size", "margin", "premium",
             "strike", "limit", "stop", "target", "order_id", "broker", "price_limit",
             "risk", "capital", "reward", "trail")

#: §16. What the boundary says when there is nothing on the other side of it.
NO_EXECUTION_CONTRACT_EXISTS = RE.R_NO_EXECUTION


# ═════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """**The reactive trader has reached the boundary.** It is not an instruction.

    Read it as: *"this opportunity, on this thesis, on this side, reached the point where
    an execution contract would decide."* Whether one exists is
    `execution_status`; today it does not, and the answer is `UNAVAILABLE`.
    """

    opportunity_id: tuple
    thesis_identity: TH.ThesisIdentity | None
    position_side: str                      # LONG | SHORT — which side WOULD be taken
    decision_action: str                    # the reactor's own action, copied
    decision_index: int
    decision_timestamp: datetime
    execution_status: str                   # reactor.EXEC_* — reused, never restated
    execution_reason: str
    disposition: str
    #: The contract that answered, by name, and whether anything validated it. A
    #: `RESOLVED` from an unvalidated contract is research and says so here.
    contract: str = RE.NoExecution.name
    contract_validated: bool = False
    #: A REFERENCE to the frozen snapshot, when a position exists on this opportunity.
    #: `None` at the boundary in production, because nothing has opened.
    trade_thesis_snapshot: object | None = None

    def __post_init__(self) -> None:
        if self.position_side not in (LONG, SHORT):
            raise ValueError(f"a boundary side must be {LONG}|{SHORT}, "
                             f"got {self.position_side!r}")
        if self.execution_status not in RE.EXEC_STATES:
            raise ValueError(f"unknown execution status {self.execution_status!r}")
        if self.disposition not in DISPOSITIONS:
            raise ValueError(f"unknown boundary disposition {self.disposition!r}")
        if self.decision_action not in RE.CANDIDATES:
            raise ValueError("only a participation candidate reaches the execution "
                             f"boundary, got {self.decision_action!r}")
        bad = [f.name for f in fields(self)
               if any(w in f.name.lower() for w in FORBIDDEN)]
        if bad:
            raise ValueError(f"order-shaped fields on the execution boundary: {bad}")

    @property
    def is_research(self) -> bool:
        """A resolution nobody validated. True for `ResearchPositionInjector`."""
        return (self.execution_status == RE.EXEC_RESOLVED
                and not self.contract_validated)

    @property
    def creates_an_order(self) -> bool:
        """Always `False`, and it is a property rather than a comment so that a caller
        asking the question gets an answer from the object."""
        return False

    def lines(self) -> list[str]:
        out = [f"EXECUTION BOUNDARY c{self.decision_index}  "
               f"{self.decision_timestamp:%Y-%m-%d %H:%M}",
               f"                  {self.decision_action}   side would be "
               f"{self.position_side}",
               f"                  thesis {self.thesis_identity or '—'}",
               f"                  opportunity {self.opportunity_id}",
               f"                  contract {self.contract}   "
               f"validated {self.contract_validated}",
               f"EXECUTION_STATUS  {self.execution_status}",
               f"DISPOSITION       {self.disposition}",
               f"                  {self.execution_reason}"]
        if self.execution_status == RE.EXEC_UNAVAILABLE:
            out.append("                  NO ORDER · NO POSITION · NO SIZE · NO RISK")
        elif self.is_research:
            out.append("                  RESEARCH resolution — an unvalidated contract "
                       "answered. This is not evidence that live entry should happen.")
        return out

    def line(self) -> str:
        return (f"c{self.decision_index:<4} {self.decision_timestamp:%H:%M}  "
                f"{self.position_side:<6}{str(self.thesis_identity or '—'):<22}"
                f"{self.execution_status:<14}{self.disposition:<30}{self.contract}")


HEAD = (f"{'cand':<5}{'time':<7}{'SIDE':<6}{'THESIS':<22}{'EXECUTION':<14}"
        f"{'DISPOSITION':<30}CONTRACT")


# ═════════════════════════════════════════════════════════════════════════════
def boundary_of(decision: RE.ParticipationDecision, *,
                execution: RE.ExecutionContract | None = None,
                snapshot: object | None = None) -> ExecutionRequest | None:
    """The boundary a candle reached, or `None` if it never reached one.

    Only a `PARTICIPATION_CANDIDATE_*` arrives here. `HOLD` and `EXIT` are position
    management and are answered entirely inside the lifecycle — §20: the lifecycle may
    hold and may exit, and neither is an order, so neither crosses this seam.

    Nothing is measured, re-derived or decided. Every field is copied from the decision
    the reactor already took.
    """
    if not decision.is_candidate:
        return None
    execution = execution if execution is not None else RE.NoExecution()
    status = decision.execution_status
    c = decision.context
    return ExecutionRequest(
        opportunity_id=decision.opportunity,
        thesis_identity=c.thesis_identity if c is not None else None,
        position_side=LONG if decision.action == RE.CANDIDATE_LONG else SHORT,
        decision_action=decision.action,
        decision_index=decision.index,
        decision_timestamp=decision.at,
        execution_status=status,
        execution_reason=(NO_EXECUTION_CONTRACT_EXISTS
                          if status == RE.EXEC_UNAVAILABLE
                          else f"{execution.name} answered {status}"),
        disposition=DISPOSITION_OF[status],
        contract=execution.name,
        contract_validated=bool(execution.validated),
        trade_thesis_snapshot=snapshot)


def requests(decisions, *, execution: RE.ExecutionContract | None = None
             ) -> list[ExecutionRequest]:
    """Every boundary a run reached, in candle order."""
    out = []
    for d in decisions:
        req = boundary_of(d, execution=execution)
        if req is not None:
            out.append(req)
    return out


def census(reqs) -> dict:
    """§9-style named counts for the boundary. Nothing averaged, nothing hidden."""
    from collections import Counter
    return {
        "requests": len(reqs),
        "by execution status": dict(Counter(r.execution_status for r in reqs)),
        "by disposition": dict(Counter(r.disposition for r in reqs)),
        "by side": dict(Counter(r.position_side for r in reqs)),
        "by contract": dict(Counter(r.contract for r in reqs)),
        "research resolutions": sum(1 for r in reqs if r.is_research),
        "orders created": sum(1 for r in reqs if r.creates_an_order),
    }


__all__ = ["NO_CONTRACT", "AWAITING_CONTRACT", "CONTRACT_RESOLVED", "DISPOSITIONS", "DISPOSITION_OF",
           "FORBIDDEN", "NO_EXECUTION_CONTRACT_EXISTS", "ExecutionRequest",
           "boundary_of", "requests", "census", "HEAD",
           "FLAT", "LONG", "SHORT", "POSITIONS"]
