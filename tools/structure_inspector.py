"""Candle-by-candle structural inspector — what did the machine believe on THIS candle?

The dashboard (`python tools/dash.py`) renders the same facts graphically.  This is the
terminal view of the identical `StructureGeometry` objects, for the cases where a
deterministic, diffable, copy-pasteable block is what you want.

```
python tools/structure_inspector.py --episode 0                 # first 40 candles
python tools/structure_inspector.py --episode 0 --from 120 --to 140
python tools/structure_inspector.py --episode 0 --index 133     # one candle
python tools/structure_inspector.py --episode 0 --step          # press Enter to advance
python tools/structure_inspector.py --episode 0 --narrowest 3   # the tightest Broads
```

**TEACH only.**  `--bucket validate` is refused: VALIDATE is aggregate-only and a
candle-level trace of it would be a case-level disclosure.  HOLDOUT is never loaded.

It decides nothing.  Every line is a copy of a fact `src/livemap/geometry.py` read off a
`StructuralFrame`, and that layer in turn copies from the map, the references, the micro
and the observational local structures.  There is no action, no signal and no position.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.learning.split import TEACH
from src.livemap.geometry import GeometryObserver, StructureGeometry
from tools.dynamic_reactive_trader_study import StudyConfig, build_episode_frames
from tools.live_structure_truth import load_research_episodes

RULE = "-" * 78


def episode_geometry(ordinal: int, config: StudyConfig | None = None
                     ) -> tuple[str, list[StructureGeometry]]:
    """Replay one TEACH source episode and return its geometry, candle by candle."""

    config = config or StudyConfig()
    episodes, _ = load_research_episodes()
    teach = episodes[TEACH]
    if not 0 <= ordinal < len(teach):
        raise SystemExit(f"episode {ordinal} out of range (0..{len(teach) - 1})")
    prepared = build_episode_frames(teach[ordinal], config)
    if prepared is None:
        raise SystemExit(f"episode {ordinal} is shorter than the history window")
    observer = GeometryObserver()
    geometries = [observer.observe(frame, tolerance=tolerance)
                  for frame, tolerance in zip(prepared.frames, prepared.tolerances,
                                              strict=True)]
    return prepared.source_episode_id, geometries


def render(geometry: StructureGeometry) -> str:
    return "\n".join(geometry.lines())


def _selected(geometries: Sequence[StructureGeometry], args) -> list[StructureGeometry]:
    if args.index is not None:
        return [g for g in geometries if g.index == args.index]
    if args.narrowest or args.widest:
        with_structure = [g for g in geometries if g.controlling is not None]
        # deterministic: width, then structure id, then candle index. Never an outcome.
        ordered = sorted(
            with_structure,
            key=lambda g: (g.controlling.width_points, g.controlling.structure_id, g.index),
            reverse=bool(args.widest))
        wanted = args.narrowest or args.widest
        seen: dict[str, StructureGeometry] = {}
        for item in ordered:
            seen.setdefault(item.controlling.structure_id, item)
            if len(seen) >= wanted:
                break
        return list(seen.values())
    start = args.start if args.start is not None else 0
    end = args.end if args.end is not None else start + args.count - 1
    return [g for g in geometries if start <= g.index <= end]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=TEACH,
                        help="teach only; validate and holdout are refused")
    parser.add_argument("--episode", type=int, default=0, help="TEACH source episode")
    parser.add_argument("--index", type=int, default=None, help="one candle index")
    parser.add_argument("--from", dest="start", type=int, default=None)
    parser.add_argument("--to", dest="end", type=int, default=None)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--narrowest", type=int, default=0,
                        help="show the N narrowest controlling structures")
    parser.add_argument("--widest", type=int, default=0,
                        help="show the N widest controlling structures")
    parser.add_argument("--step", action="store_true",
                        help="advance one candle per Enter press")
    args = parser.parse_args(argv)

    if args.bucket != TEACH:
        raise SystemExit(
            "this inspector is TEACH-only: VALIDATE stays aggregate-only and HOLDOUT is "
            "never loaded")

    episode_id, geometries = episode_geometry(args.episode)
    chosen = _selected(geometries, args)
    header = (f"{episode_id}  candles {geometries[0].index}..{geometries[-1].index}  "
              f"showing {len(chosen)}")
    print(header)
    print(RULE)
    for geometry in chosen:
        print(render(geometry))
        print(RULE)
        if args.step:
            try:
                input("[Enter] next candle, Ctrl-C to stop  ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
