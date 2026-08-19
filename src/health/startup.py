"""
The startup sequence — spec 10 §4 and spec 05 §1 guard 0.

> Print before the first candle, every session. If any reachability assertion fails,
> **refuse to start.**

Three families of refusal, and the difference between them matters:

  * **Config incomplete** — `risk_per_trade_rupees` is null, `costs.yaml` unverified,
    `events.yaml` stale. These are things a human must supply, and the engine refusing
    is the design working (spec 05 §4: *"Forcing that decision to be conscious is the
    point."*).
  * **Config unreachable** — a gate that cannot pass under any admissible input. This is
    a bug in the numbers, and it is the class that made the dry-run engine unable to
    trade while reporting nothing wrong.
  * **Session ambiguity** — a state file exists for today and no `--force-fresh-session`
    was given. Silently resetting a kill switch is forbidden (CLAUDE.md §12).

Every one of them prints all its problems at once. Discovering three blockers one run at
a time is how a morning gets lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from src.config.loader import Config, check_startup
from src.health.reachability import report as reachability_report
from src.state.session_store import SessionStore

BANNER_WIDTH = 66


@dataclass
class StartupResult:
    may_start: bool
    banner: str
    blockers: list[str] = field(default_factory=list)


def startup(cfg: Config, today: date, store: SessionStore | None = None,
            *, mode: str = "PAPER") -> StartupResult:
    lines: list[str] = []
    blockers: list[str] = []

    costs = cfg.costs.get("costs", {})
    risk = cfg.get("session.risk_per_trade_rupees", None)
    lines.append(f"BANK NIFTY CO-PILOT          MODE: {mode}")
    lines.append(f"config digest    {cfg.digest}        "
                 f"risk/trade  {'NOT SET' if risk is None else f'Rs {risk:,}'}")
    lines.append(f"costs verified   {costs.get('last_verified') or 'NEVER':<12}   "
                 f"events      {cfg.events.get('last_updated') or 'NEVER'}")
    lines.append("")

    text, passed, total = reachability_report(cfg)
    lines.append(text)
    if passed != total:
        blockers += [f"reachability: {total - passed} assertion(s) failed"]

    config_problems = check_startup(cfg, today=today)
    if config_problems:
        lines.append("")
        lines.append(f"CONFIG            {len(config_problems)} blocker(s)")
        for problem in config_problems:
            lines.append(f"  FAIL  {problem.splitlines()[0]}")
        blockers += config_problems

    if store is not None:
        if store.requires_explicit_fresh(today):
            message = (f"a session state file already exists for {today}. Resuming is "
                       f"the default; starting fresh requires --force-fresh-session. "
                       f"Silent reset is forbidden (CLAUDE.md §12).")
            lines.append("")
            lines.append(f"  FAIL  {message}")
            blockers.append(message)
        else:
            resumed = store.resume_banner()
            if resumed:
                lines.append("")
                lines.append(resumed)

    lines.append("")
    if blockers:
        lines.append(f"REFUSING TO START — {len(blockers)} blocker(s). "
                     f"Nothing below this line runs.")
    else:
        lines.append("READY — no blockers. The engine may process candles.")

    return StartupResult(may_start=not blockers, banner="\n".join(lines), blockers=blockers)
