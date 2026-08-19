#!/usr/bin/env python3
"""
ask.py — "tum yahan kya soch rahe the?"  Spec 13.

    python tools/ask.py 2026-03-04 77           # one candle
    python tools/ask.py 2026-03-04 75 82        # a group
    python tools/ask.py 2026-03-04 --blind      # every candle with a blind spot
    python tools/ask.py 2026-03-04 --swings     # every confirmed swing

Spec 12 takes an opinion on a whole session. This has a conversation about one candle.

## The rule this tool exists under — spec 13 §5

> **Baat-cheet rules DHOONDHTI hai. Accept nahi karti.**
> Baat-cheet me kabhi `params.yaml` mat badalna. Kabhi bhi. Ek session me chaahe wo
> kitna hi obvious lage.

Agreeing is very cheap in conversation — cheaper than in an annotation, which is why
spec 13 calls this a *faster* overfitting risk than spec 12. Whatever comes out of a
session here is a **candidate**, written to `annotations/candidates/`, and it goes
through the spec 12 pipeline before it touches anything.

Maximum three candidates a session. Past that *"tum rules nahi dhoondh rahe — tum ek din
ko dobara jee rahe ho."*

And the answer this tool is explicitly allowed to give, which it will not give unless
the permission is written down: **"is candle par kuch nahi tha. Tumhe wo move yaad hai,
isliye ab yahan structure dikh raha hai. Numbers me kuch khaas nahi."**
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import _console  # noqa: E402,F401  (console encoding, see module)

from src.config.loader import load_config  # noqa: E402
from src.feed.replay_feed import ReplayFeed  # noqa: E402
from src.p1_pipeline import P1Pipeline  # noqa: E402
from src.reasoning.record import PROBES, measure  # noqa: E402

W = 74


def rule(title: str = "") -> str:
    return f"  -- {title} " + "-" * max(0, W - len(title) - 6) if title else "  " + "-" * W


def show(cfg, records, index: int) -> None:
    record = records[index]
    candle = record.candle
    r = measure(cfg, records, index)

    print(f"\n{'=' * W}")
    print(f" CANDLE {index}  ·  {candle.open_time:%H:%M}   "
          f"O {candle.o:,.2f}  H {candle.h:,.2f}  L {candle.l:,.2f}  C {candle.c:,.2f}")
    print("=" * W)

    print(rule("MAINE KYA DEKHA"))
    saw = r.saw
    atr_note = f" = {saw['range_x_atr']:.2f}x ATR20 ({record.board.atr20_1m:,.1f})" \
        if saw["range_x_atr"] is not None else ""
    print(f"     range        {saw['range']:.1f} pts{atr_note}")
    print(f"     pichhli 6    {[float(round(x, 1)) for x in saw['prior_6_ranges']]}")
    if saw["upper_wick_pct"] is not None:
        print(f"     body {saw['body']:.1f}  upper wick {candle.upper_wick:.1f} "
              f"({saw['upper_wick_pct']:.0f}%)  lower wick {candle.lower_wick:.1f} "
              f"({saw['lower_wick_pct']:.0f}%)")
    print(f"     close        {saw['close_third']} third (position {saw['close_position']:.2f})")
    if saw["time_at_price"] is not None:
        print(f"     time-at-price  pichhli 11 me se {saw['time_at_price']:.0f} candles "
              f"ne is price ko touch kiya")
    if saw["compression"] is not None:
        print(f"     compression  last3 / prior10 = {saw['compression']:.2f}")

    print(rule("BOARD ME KYA BADLA"))
    print("     " + ("; ".join(r.board_changed) if r.board_changed
                     else "kuch nahi. Board waisa hi hai."))

    print(rule("MERA DHYAAN KAHAN THA"))
    for line in r.attention:
        print(f"     {line}")

    print(rule("AGLI CANDLE PAR MERI UMEED"))
    for chunk in r.expectation.split(". "):
        if chunk.strip():
            print(f"     {chunk.strip().rstrip('.')}.")

    print(rule("MAIN YE DEKH HI NAHI SAKTA"))
    if r.blind_spots:
        for line in r.blind_spots:
            print(f"     {line}")
    else:
        print("     is candle par kuch aisa nahi jo main naap raha hoon par use nahi kar sakta.")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("day", help="YYYY-MM-DD")
    ap.add_argument("candles", nargs="*", type=int, help="index, or two for a range")
    ap.add_argument("--symbol", default="NIFTY BANK")
    ap.add_argument("--blind", action="store_true", help="only candles with a blind spot")
    ap.add_argument("--swings", action="store_true", help="only confirmed 5m swings")
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args(argv)

    cfg = load_config(strict=False)
    session = ReplayFeed(args.symbol).session(date.fromisoformat(args.day))
    pipeline = P1Pipeline(cfg, session)
    records = pipeline.run()

    if args.blind:
        hits = [i for i in range(len(records)) if measure(cfg, records, i).blind_spots]
        print(f"\n{len(hits)} of {len(records)} candles have something the engine measures "
              f"but cannot act on.")
        print(f"blind-spot probes active: {', '.join(p.name for p in PROBES if p.is_blind_spot(cfg))}")
        chosen = hits[:: max(1, len(hits) // args.limit)][:args.limit] if hits else []
    elif args.swings:
        times = {s.time for s in pipeline.structure.swings["5m"]["high"]} | \
                {s.time for s in pipeline.structure.swings["5m"]["low"]}
        chosen = [i for i, r in enumerate(records) if r.candle.open_time in times][:args.limit]
        print(f"\n{len(chosen)} confirmed 5m swings shown.")
    elif len(args.candles) == 2:
        chosen = list(range(args.candles[0], min(args.candles[1] + 1, len(records))))
    elif len(args.candles) == 1:
        chosen = [args.candles[0]]
    else:
        ap.error("give a candle index, two for a range, or --blind / --swings")

    for index in chosen:
        if 0 <= index < len(records):
            show(cfg, records, index)

    print(rule())
    print("  Spec 13 §5: this conversation FINDS candidates. It does not accept them.")
    print("  Nothing here changes params.yaml. Write candidates to annotations/candidates/")
    print("  and run them through the spec 12 pipeline — measured, cost-checked, regressed.")
    print("  Max 3 a session. And \"there was nothing here, you just remember the move\"")
    print("  is a valid answer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
