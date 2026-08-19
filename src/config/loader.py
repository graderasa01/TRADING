"""
Config loader — CLAUDE.md §9 and spec 05 §1 guard 0.

Two jobs, and the second is the important one.

  1. Load `params.yaml`, `costs.yaml` and `events.yaml`, and give typed access.
  2. **Refuse to start** when a value the engine cannot honestly run without is
     missing or stale.

The refusals are not defensive programming, they are the guard-0 behaviour spec 05
specifies, and each has a reason written next to it. A trading system that starts with
an unverified cost model produces a profitable-looking backtest and an unprofitable
account, and the two are indistinguishable from inside.

`effective()` implements the one arithmetic pattern that appears everywhere in v2:

    effective = max(floor_points, atr_mult × ATR)

The floor is a dead-market guard, **not** the operating value (params.yaml header).
`REVIEW-v2.md` §7 documents what happens when that is got wrong: v1's
`max(10, 0.25 × ATR)` only exceeded 10 above ATR 40, so a claim that the buffer
"scales with volatility" was false about 95% of the time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from src.domain.models import IST, to_decimal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"


class ConfigError(RuntimeError):
    """Configuration is missing, malformed, or stale. The engine must not start."""


# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Config:
    params: dict[str, Any]
    costs: dict[str, Any]
    events: dict[str, Any]
    digest: str
    source_dir: Path

    # ── access ──
    def get(self, dotted: str, default: Any = "__raise__") -> Any:
        """`cfg.get("levels.max_touches")`. Raises on a missing key unless a default
        is given — a silently-defaulted threshold is a magic number with extra steps."""
        node: Any = self.params
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default == "__raise__":
                    raise ConfigError(f"missing config key: {dotted}")
                return default
            node = node[part]
        return node

    def dec(self, dotted: str, default: Any = "__raise__") -> Decimal:
        return to_decimal(self.get(dotted, default))

    def effective(self, points_key: str, atr_mult_key: str, atr: Decimal | None) -> Decimal:
        """max(floor_points, atr_mult × ATR) — the v2 threshold form.

        With ATR unavailable (warmup), the floor is returned. That is the only moment
        the floor is meant to be the operating value.
        """
        floor = self.dec(points_key)
        if atr is None:
            return floor
        return max(floor, self.dec(atr_mult_key) * atr)

    def windows(self, expiry: bool = False) -> list[tuple[dtime, dtime]]:
        key = "time.windows_expiry" if expiry else "time.windows_normal"
        return [(dtime.fromisoformat(a), dtime.fromisoformat(b)) for a, b in self.get(key)]

    def time_at(self, dotted: str) -> dtime:
        return dtime.fromisoformat(self.get(dotted))


# ─────────────────────────────────────────────────────────────────────────────
# startup refusals
# ─────────────────────────────────────────────────────────────────────────────
def _age_days(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        stamp = value
    elif isinstance(value, datetime):
        stamp = value.date()
    else:
        try:
            stamp = date.fromisoformat(str(value))
        except ValueError as exc:
            raise ConfigError(f"{label} is not a YYYY-MM-DD date: {value!r}") from exc
    return (datetime.now(IST).date() - stamp).days


def check_startup(cfg: Config, *, today: date | None = None) -> list[str]:
    """Every reason the engine must not start. Empty list means it may.

    Returned rather than raised so the startup banner can print all of them at once —
    finding three blockers one run at a time is how a morning gets lost.
    """
    problems: list[str] = []
    today = today or datetime.now(IST).date()

    # 1. risk per trade — deliberately null, spec 05 §4
    risk = cfg.get("session.risk_per_trade_rupees", None)
    if risk is None:
        problems.append(
            "session.risk_per_trade_rupees is null. It has no default ON PURPOSE — "
            "this is the number that decides how much a bad day costs, and choosing it "
            "must be a conscious act. Set it in config/params.yaml.")
    elif to_decimal(risk) <= 0:
        problems.append(f"session.risk_per_trade_rupees must be positive, got {risk}")

    # 2. cost model — spec 05 guard 0, params.yaml risk.max_cost_as_fraction_of_r
    costs = cfg.costs.get("costs", {})
    max_age = int(cfg.get("events.max_calendar_age_days", 30))
    cost_age = _age_days(costs.get("last_verified"), "costs.last_verified")
    if cost_age is None:
        problems.append(
            "costs.yaml last_verified is null. On this instrument the cost model decides "
            "whether any trade can be positive-expectancy at all (spec 07 §1.6) — a "
            "round trip is 44-64% of a 25-point R. Verify the rates against the broker's "
            "published charges and set the date.")
    elif cost_age > 90:
        problems.append(
            f"costs.yaml was last verified {cost_age} days ago (limit 90). Brokerage, STT "
            f"and exchange charges have all been revised in the last two years.")
    else:
        missing = [k for k, v in costs.items()
                   if v is None and k.endswith(("_pct", "_order", "_premium", "_buy"))]
        if missing:
            problems.append(f"costs.yaml has unfilled rates: {', '.join(sorted(missing))}")

    # 3. event calendar — fail closed, spec 05 §1b
    cal_age = _age_days(cfg.events.get("last_updated"), "events.last_updated")
    if cal_age is None:
        problems.append(
            "events.yaml last_updated is null. A stale calendar is worse than none — it "
            "produces confidence that the check is running when it is not. Fill the RBI "
            "MPC dates, the five heavyweight bank results days and the Budget, then set "
            "the date.")
    elif cal_age > max_age:
        problems.append(f"events.yaml is {cal_age} days old (limit {max_age})")

    # 4. reachability of the one constraint params.yaml documents inline
    #    (spec 10 §3.3 owns the full battery in P2; this one is cheap and it already
    #     bit once — b_entry_max_extreme_atr_mult 1.2 could never pass at any ATR)
    cap = cfg.dec("setups.b_entry_max_extreme_atr_mult")
    buf = cfg.dec("risk.sl_buffer_atr_mult")
    r_max = cfg.dec("risk.r_max_atr_mult")
    if cap + buf > r_max:
        problems.append(
            f"UNREACHABLE: setups.b_entry_max_extreme_atr_mult ({cap}) + "
            f"risk.sl_buffer_atr_mult ({buf}) = {cap + buf} > risk.r_max_atr_mult "
            f"({r_max}). A Setup B entry could never pass the R ceiling at any "
            f"volatility. See params.yaml's note and prototype/FINDINGS.md part 2.")

    # 5. the prohibition that must hold structurally
    if cfg.get("structure.journey_gates_trades", False):
        problems.append(
            "structure.journey_gates_trades is true. D-011b requires it to stay false "
            "until P9 measures the D2 hit rate — an unmeasured intuition wired into a "
            "gate is the most likely way this system acquires a losing rule.")

    if (REPO_ROOT / "src" / "broker" / "live.py").exists():
        problems.append("src/broker/live.py exists. This stage is paper only (CLAUDE.md §6).")

    if (REPO_ROOT / "HALT").exists():
        problems.append("./HALT is present — refusing to start (spec 08 part 5).")

    return problems


# ─────────────────────────────────────────────────────────────────────────────
def _digest(params: dict[str, Any], costs: dict[str, Any]) -> str:
    """Stable hash of everything that changes behaviour, for the startup banner and
    the journal header. Sorted keys, D-004's scheme."""
    blob = json.dumps({"params": params, "costs": costs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:8]


def load_config(config_dir: Path | None = None, *, strict: bool = True) -> Config:
    """Load and validate. `strict=False` skips the startup refusals — used only by
    tools that read thresholds without running the engine (the chart renderer, the
    data verifier). It must never be used by anything that can produce a Signal."""
    import yaml

    config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    if not config_dir.is_dir():
        raise ConfigError(f"config directory not found: {config_dir}")

    def read(name: str, required: bool) -> dict[str, Any]:
        path = config_dir / name
        if not path.exists():
            if required:
                raise ConfigError(f"{path} is missing. The engine fails closed on this.")
            return {}
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path} did not parse to a mapping")
        return loaded

    params = read("params.yaml", required=True)
    costs = read("costs.yaml", required=True)
    events = read("events.yaml", required=True)

    for section in ("meta", "levels", "structure", "time", "volatility",
                    "session", "modes", "setups", "risk", "exits", "options",
                    "slippage", "events", "gap_regime", "feed"):
        if section not in params:
            raise ConfigError(f"params.yaml is missing the '{section}' section")

    cfg = Config(params=params, costs=costs, events=events,
                 digest=_digest(params, costs), source_dir=config_dir)

    if strict:
        problems = check_startup(cfg)
        if problems:
            raise ConfigError(
                "ENGINE WILL NOT START — "
                f"{len(problems)} blocking problem(s):\n\n"
                + "\n\n".join(f"  {i}. {p}" for i, p in enumerate(problems, 1))
                + "\n")
    return cfg


def startup_banner(cfg: Config, problems: Sequence[str] = ()) -> str:
    """Spec 10 §4. Printed before the first candle, every session."""
    costs = cfg.costs.get("costs", {})
    risk = cfg.get("session.risk_per_trade_rupees", None)
    lines = [
        "BANK NIFTY CO-PILOT          MODE: PAPER",
        f"config digest    {cfg.digest}        "
        f"risk/trade  {'NOT SET' if risk is None else f'Rs {risk:,}'}",
        f"costs verified   {costs.get('last_verified') or 'NEVER'}      "
        f"events      {cfg.events.get('last_updated') or 'NEVER'}",
    ]
    if problems:
        lines.append("")
        lines.append(f"REFUSING TO START — {len(problems)} problem(s):")
        lines += [f"  - {p.splitlines()[0]}" for p in problems]
    return "\n".join(lines)
