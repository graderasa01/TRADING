# Structural Frame Traces

Reproduction:

```bash
python -c "from tests.test_participation import block; from src.livemap.frame import observe; s,f=block(0); frames=observe(s,f); [print('\n'.join(fr.lines())+'\n') for fr in frames if 404 <= fr.index <= 411]"
```

The frame contains geometry and upstream thesis facts only. It does not select a local
invalidation, choose one release, or rank one approached side over another.

```text
11:45
PRICE 44,949.4
BROAD C05 44,761-44,966 | low 44,760.5 | high 44,965.8
LOCAL none
MICRO none none | low none | high none
DELTA +9.2
CURRENT EDGE DISTANCES upper 16.4 | lower 188.9
WATCH ABOVE APPROACHING_NEXT_ZONE
WATCH BELOW FAR_FROM_NEXT_ZONE
APPROACHED EDGES watch.above
RELEASES ON THIS CANDLE RL01 INNER C09.high up
ACTIVE RELEASE RL01 INNER C09.high
LEFT STRUCTURE none
NEXT REFERENCES above C08 | below C07
BROADER THESIS none | NO_IDEA | generation 0 | NO_THESIS
BROADER THESIS INVALIDATION none

11:50
PRICE 44,957.4
BROAD C05 44,761-44,966 | low 44,760.5 | high 44,965.8
LOCAL none
MICRO none none | low none | high none
DELTA +8.0
CURRENT EDGE DISTANCES upper 8.4 | lower 196.9
WATCH ABOVE APPROACHING_NEXT_ZONE
WATCH BELOW FAR_FROM_NEXT_ZONE
APPROACHED EDGES current.upper, watch.above
RELEASES ON THIS CANDLE none
ACTIVE RELEASE RL01 INNER C09.high
LEFT STRUCTURE none
NEXT REFERENCES above C08 | below C07
BROADER THESIS none | NO_IDEA | generation 0 | NO_THESIS
BROADER THESIS INVALIDATION none

12:00
PRICE 44,920.2
BROAD C05 44,761-44,966 | low 44,760.5 | high 44,965.8
LOCAL none
MICRO none none | low none | high none
DELTA -63.6
CURRENT EDGE DISTANCES upper 45.6 | lower 159.7
WATCH ABOVE APPROACHING_NEXT_ZONE
WATCH BELOW FAR_FROM_NEXT_ZONE
APPROACHED EDGES watch.above
RELEASES ON THIS CANDLE none
ACTIVE RELEASE none
LEFT STRUCTURE none
NEXT REFERENCES above C08 | below C07
BROADER THESIS none | NO_IDEA | generation 0 | NO_THESIS
BROADER THESIS INVALIDATION none

12:15
PRICE 45,016.8
BROAD none
LOCAL none
MICRO none none | low none | high none
DELTA +29.0
CURRENT EDGE DISTANCES upper none | lower none
WATCH ABOVE APPROACHING_NEXT_ZONE
WATCH BELOW APPROACHING_NEXT_ZONE
APPROACHED EDGES watch.above, watch.below
RELEASES ON THIS CANDLE RL02 OUTER C05.high up | RL03 INNER C09.high up
ACTIVE RELEASE RL03 INNER C09.high
LEFT STRUCTURE C05
NEXT REFERENCES above C04 | below C05
BROADER THESIS C05/GEN1/UP | LONG_IDEA | generation 1 | ACTIVE
BROADER THESIS INVALIDATION 44,965.8

12:20
PRICE 45,016.0
BROAD none
LOCAL none
MICRO none
DELTA -0.8
CURRENT EDGE DISTANCES upper none | lower none
WATCH ABOVE APPROACHING_NEXT_ZONE
WATCH BELOW APPROACHING_NEXT_ZONE
APPROACHED EDGES watch.above, watch.below
RELEASES ON THIS CANDLE none
ACTIVE RELEASE RL03 INNER C09.high
LEFT STRUCTURE C05
NEXT REFERENCES above C04 | below C05
BROADER THESIS C05/GEN1/UP | LONG_IDEA | generation 1 | ACTIVE
BROADER THESIS INVALIDATION 44,965.8
```

The 12:15 frame preserves both relevant watch sides and both releases. The active release
is copied from upstream state and is not substituted for the complete release tuple.
