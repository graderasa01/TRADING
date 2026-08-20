"""Building a dashboard session, and turning frames into the JSON the page renders.

**A copy, field for field.** Nothing in this file computes, derives or decides anything:
every value is read off a production object that already owns it. The one transformation is
`Decimal → float`, for JSON, after every decision has already been taken in `Decimal`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from src.boxes.frontier import run
from src.boxes.snapshot import build_snapshot
from src.learning.split import load_split
from src.livemap import observatory as OB
from src.livemap import position as POS
from src.livemap import reactor as RE
from src.livemap import reference as REF

from tools.dashboard.feed import SYMBOL, ReplaySource, m5_of

BARS, HIST = 700, 400
TEACH_BLOCKS = 24


def n(v):
    return None if v is None else float(v)


@dataclass(frozen=True)
class Session:
    """One loadable thing: a teach block or a session day, plus its warm-up."""

    key: str
    label: str
    history: tuple
    live: tuple

    @property
    def snapshot(self):
        return build_snapshot(list(self.history), SYMBOL)


# ─────────────────────────────────────────────────────────────────────────────
def catalog(blocks: int = TEACH_BLOCKS) -> dict:
    """What the picker offers. Teach only — no test or tool in this repo reads the
    holdout, and `split.holdout()` is never called."""
    sp = load_split()
    days = [d for d in _days() if sp.bucket_of(d) == "teach"]
    return {
        "blocks": [{"key": f"block{i}", "label": f"teach block {i}"}
                   for i in range(blocks)],
        "days": [{"key": f"day{d}", "label": str(d)} for d in days[-120:]],
        "scenarios": OB.SCENARIOS,
    }


def _days():
    from src.feed.replay_feed import ReplayFeed
    return ReplayFeed(SYMBOL, on_gap="skip").available_days()


def load(key: str) -> Session:
    """`block<N>` or `day<YYYY-MM-DD>` → the candles it is built from."""
    sp = load_split()
    if key.startswith("block"):
        i = int(key[5:])
        teach = [d for d in _days() if sp.bucket_of(d) == "teach"]
        m5 = m5_of(teach[:((i + 1) * BARS) // 75 + 12])
        blk = m5[i * BARS:(i + 1) * BARS]
        if len(blk) < BARS:
            raise KeyError(f"block {i} is short ({len(blk)}/{BARS})")
        return Session(key, f"teach block {i}", tuple(blk[:HIST]), tuple(blk[HIST:]))

    if key.startswith("day"):
        d = date.fromisoformat(key[3:])
        if sp.bucket_of(d) != "teach":
            raise KeyError(f"{d} is not a teach session — this tool reads teach only")
        window = [x for x in _days() if x <= d][-6:]
        m5 = m5_of(window)
        cut = next((i for i, c in enumerate(m5) if c.close_time.date() == d), None)
        if cut is None or cut < 120:
            raise KeyError(f"not enough history before {d}")
        return Session(key, str(d), tuple(m5[:cut]), tuple(m5[cut:]))

    raise KeyError(f"unknown session {key!r}")


def contract_for(session: Session, paper: bool) -> RE.ExecutionContract:
    """`NoExecution` unless PAPER was explicitly asked for, in which case a named
    research injector. There is no third option and no live one."""
    if not paper:
        return RE.NoExecution()
    snapshot = session.snapshot
    f = run(snapshot, list(session.history), list(session.live))
    ids = POS.candidates_in(RE.replay(snapshot, f, execution=RE.ImmediateExecution()))
    return POS.ResearchPositionInjector(ids) if ids else RE.NoExecution()


def build(key: str, *, paper: bool = False) -> dict:
    """A whole session, ready to render. Historical path."""
    session = load(key)
    snapshot = session.snapshot
    execution = contract_for(session, paper)
    frames = OB.frames(snapshot, list(session.history), list(session.live),
                       execution=execution)
    return payload(frames, session.key, session.label, execution,
                   source=ReplaySource(session.live).name)


# ─────────────────────────────────────────────────────────────────────────────
def frame_json(f) -> dict:
    """One frame → one JSON object. Every key is a copy of a production field."""
    c, st, g = f.context, f.state, f.geometry
    snap, ev = st.snapshot, st.evaluation
    return {
        "i": f.index, "t": f.at.strftime("%Y-%m-%d %H:%M"),
        "o": n(f.o), "h": n(f.h), "l": n(f.l), "c": n(f.c),
        "boxes": [{"id": b.id, "kind": b.kind, "s": b.start, "e": b.end,
                   "lo": n(b.low), "hi": n(b.high), "p": b.parent, "d": b.depth,
                   "st": b.status} for b in g.boxes],
        "micro": (None if g.micro_low is None else
                  {"id": g.micro_id, "lo": n(g.micro_low), "hi": n(g.micro_high),
                   "state": g.micro_state, "parent": g.micro_parent}),
        "cur": g.current_id,
        "band": [n(g.band[0]), n(g.band[1])] if g.band else None,
        "releases": [{"scale": r.scale, "boundary": r.boundary, "id": r.broken_id,
                      "dir": r.direction, "edge": n(r.broken_edge),
                      "parent": r.parent_id, "origin": r.origin,
                      "plo": n(r.parent_low), "phi": n(r.parent_high)}
                     for r in c.all_releases],
        "simultaneous": c.simultaneous,
        "thesis": {"idea": c.idea.replace("_IDEA", ""), "gen": c.generation,
                   "status": c.thesis_status, "state": c.current_state,
                   "next_expected": c.next_expected,
                   "identity": str(c.thesis_identity) if c.thesis_identity else None,
                   "contradicted": c.contradicted, "location": c.current_location,
                   "pos_in_current": n(c.position_in_current),
                   "scale": c.controlling_scale,
                   "release_location": c.release_location,
                   "parent_location": c.parent_location,
                   "bars_since_break": c.bars_since_break,
                   "travelled": n(c.excursion_travelled)},
        "micro_read": {"id": c.micro_id, "state": c.micro_state, "view": c.micro_view,
                       "rotations": c.micro_rotations, "last": c.micro_last_direction},
        "path": {"next": c.next_reference, "far": n(c.far_reference),
                 "near": n(c.free_to_near), "depth": n(c.zone_depth),
                 "far_free": n(c.free_to_far), "corridor": list(c.corridor[:4]),
                 "watch": c.watch},
        "inval": {"rule": c.invalidation, "price": n(c.invalidation_price),
                  "distance": n(c.invalidation_distance)},
        "part": {"outcome": c.participation, "reasons": list(c.reasons),
                 "kind": c.opportunity_kind, "entry_shaped": c.entry_shaped,
                 "opportunity": str(c.opportunity) if c.opportunity else None},
        "action": f.action, "status": f.decision.status, "exec": f.execution_status,
        "disposition": f.request.disposition if f.request else None,
        "phase": st.phase, "pos_before": st.position, "pos": st.position_after,
        "exit_reason": st.exit_reason,
        "entry": (None if snap is None else {
            "side": snap.side, "identity": str(snap.identity), "gen": snap.generation,
            "at": snap.opened_at.strftime("%H:%M"), "index": snap.opened_index,
            "price": n(snap.opened_price), "scale": snap.release_scale,
            "edge": n(snap.broken_edge), "parent": snap.parent_structure_id,
            "inval": n(snap.invalidation_reference), "inval_dir": snap.invalidation_direction,
            "rule": snap.invalidation_rule, "state": snap.current_state_at_open,
            "micro": snap.micro_state_at_open, "next": snap.next_reference_at_open,
            "near": n(snap.free_to_near_at_open)}),
        "mgmt": list(ev.management) if ev else [],
        "developments": list(ev.developments) if ev else [],
        "same_identity": (ev.thesis_generation_same if ev else None),
        "same_direction": (ev.direction_same if ev else None),
        "cur_identity": (str(ev.current_identity) if ev and ev.current_identity else None),
        "why": {"codes": list(f.why.codes), "lines": list(f.why.lines),
                "narrative": f.why.narrative},
        "eye": [[q, a] for q, a in OB.trader_eye(f)],
        "events": list(f.events),
        "ref": reference_json(f.reference),
        "geo": geometry_json(f.structure_geometry),
    }


def geometry_json(g) -> dict | None:
    """The structural opportunity geometry. A copy — no field here is computed."""
    if g is None:
        return None
    c, pg, i, e, m, lo = (g.controlling, g.price_geometry, g.internal, g.external,
                          g.movement, g.local)

    def ref(r):
        return None if r is None else {
            "id": r.structure_id, "kind": r.kind, "label": r.label,
            "price": n(r.price), "dir": r.direction,
            "edge_distance": n(r.edge_distance_points),
            "edge_distance_atr": _round(r.edge_distance_atr),
            "price_distance": n(r.price_distance_points),
            "price_distance_atr": _round(r.price_distance_atr)}

    return {
        "controlling": None if c is None else {
            "id": c.structure_id, "kind": c.kind, "lo": n(c.low), "hi": n(c.high),
            "mid": n(c.midpoint), "width": n(c.width_points),
            "width_atr": _round(c.width_atr), "parent": c.parent_id,
            "status": c.status},
        "price": {"price": n(pg.price), "location": pg.price_location,
                  "containment": pg.containment,
                  "to_lower": n(pg.distance_to_lower_points),
                  "to_lower_atr": _round(pg.distance_to_lower_atr),
                  "to_mid": n(pg.distance_to_midpoint_points),
                  "to_mid_atr": _round(pg.distance_to_midpoint_atr),
                  "to_upper": n(pg.distance_to_upper_points),
                  "to_upper_atr": _round(pg.distance_to_upper_atr)},
        "internal": {"state": i.state,
                     "room_lower": n(i.room_to_lower_edge_points),
                     "room_mid": n(i.room_to_midpoint_points),
                     "room_mid_atr": _round(i.room_to_midpoint_atr),
                     "room_upper": n(i.room_to_upper_edge_points),
                     "landmark": i.next_internal_landmark,
                     "room_landmark": n(i.room_to_next_internal_landmark_points),
                     "room_landmark_atr": _round(i.room_to_next_internal_landmark_atr),
                     "room_opposite": n(i.room_to_opposite_edge_points),
                     "room_opposite_atr": _round(i.room_to_opposite_edge_atr)},
        "external": {"above": ref(e.next_reference_above),
                     "below": ref(e.next_reference_below),
                     "room_above_edge": n(e.room_above_current_upper_to_next_reference_points),
                     "room_above_edge_atr": _round(
                         e.room_above_current_upper_to_next_reference_atr),
                     "room_below_edge": n(e.room_below_current_lower_to_next_reference_points),
                     "room_below_edge_atr": _round(
                         e.room_below_current_lower_to_next_reference_atr),
                     "released": e.outside_released_structure_id,
                     "released_edge": n(e.released_edge)},
        "movement": {"direction": m.direction, "origin_index": m.origin_index,
                     "origin_price": n(m.origin_price),
                     "origin_reference": m.origin_reference,
                     "origin_structure": m.origin_structure_id,
                     "origin_kind": m.origin_structure_kind,
                     "origin_role": m.origin_role, "outside": m.outside,
                     "destination": n(m.destination_price),
                     "destination_reference": m.destination_reference,
                     "path_midpoint": n(m.path_midpoint),
                     "travelled": n(m.travelled_points),
                     "travelled_atr": _round(m.travelled_atr),
                     "remaining": n(m.remaining_points),
                     "whole_fraction": _round(m.whole_movement_fraction),
                     "segment": m.current_segment,
                     "segment_fraction": _round(m.current_segment_fraction),
                     "midpoint_crossed": m.midpoint_crossed,
                     "opposite_reached": m.opposite_edge_reached,
                     "events": [{"i": ev.index, "event": ev.event, "id": ev.structure_id,
                                 "kind": ev.structure_kind, "price": n(ev.price)}
                                for ev in m.events]},
        "local": {"micro_id": lo.micro_id, "micro_state": lo.micro_state,
                  "micro_lo": n(lo.micro_low), "micro_hi": n(lo.micro_high),
                  "micro_width": n(lo.micro_width_points),
                  "micro_where": lo.price_location_vs_micro,
                  "local_id": lo.local_structure_id, "local_kind": lo.local_structure_kind,
                  "local_lo": n(lo.local_low), "local_hi": n(lo.local_high),
                  "local_width": n(lo.local_width_points),
                  "local_holder": lo.local_holder_id,
                  "local_where": lo.price_location_vs_local},
        "events": list(g.structural_events),
    }


def _round(v):
    return None if v is None else round(v, 3)


def _ref(r) -> dict:
    """One reference. Copied — no field here ranks it against another."""
    return {"role": r.role, "id": r.structure_id, "edge": r.edge, "label": r.label,
            "price": n(r.price), "kind": r.kind, "parent": r.parent_id,
            "distance": n(r.distance), "distance_atr": round(r.distance_atr, 2),
            "pos": r.route_position, "dir": r.direction, "why": r.reason,
            "area": r.area_id}


def _side_json(s) -> dict:
    return {
        "direction": s.direction,
        "refs": [_ref(r) for r in s.references],
        "areas": [{"id": a.id, "lo": n(a.low), "hi": n(a.high), "why": a.reason,
                   "members": [r.label for r in a.members]} for a in s.areas],
        "enclosures": [list(e) for e in s.enclosures],
        "immediate": _ref(s.immediate) if s.immediate else None,
        "next": _ref(s.next) if s.next else None,
        "major": _ref(s.major) if s.major else None,
        "far": [_ref(r) for r in s.far],
    }


def reference_json(rp) -> dict | None:
    if rp is None:
        return None
    return {
        "active": rp.active, "current": rp.current_id,
        "up": _side_json(rp.up), "down": _side_json(rp.down),
        "counter": _ref(rp.counter) if rp.counter else None,
        "current_boundaries": [_ref(r) for r in rp.current_boundaries],
        "invalidation": n(rp.invalidation_price),
        "invalidation_rule": rp.invalidation_rule,
        "primary_roles": sorted(REF.PRIMARY_ROLES),
        "secondary_roles": sorted(REF.SECONDARY_ROLES),
    }


def payload(frames: Sequence, key: str, label: str,
            execution: RE.ExecutionContract, *, source: str) -> dict:
    return {
        "key": key, "label": label, "symbol": SYMBOL,
        "contract": execution.name, "validated": bool(execution.validated),
        "source": source,
        "execution_status": RE.EXEC_UNAVAILABLE,
        "frames": [frame_json(f) for f in frames],
        "scenarios": OB.scenarios(frames),
        "scenario_names": OB.SCENARIOS,
        "questions": list(OB.EYE_QUESTIONS),
        "roles": sorted(REF.ROLES),
        "role_reasons": dict(REF.REASON),
    }


__all__ = ["BARS", "HIST", "TEACH_BLOCKS", "Session", "catalog", "load", "build",
           "contract_for", "frame_json", "geometry_json", "payload"]
