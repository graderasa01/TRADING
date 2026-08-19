# Structural Frame Traces

Reproduction:

```bash
python -c "from tests.test_participation import block; from src.livemap.frame import observe; s,f=block(0); frames=observe(s,f); [print('\n'.join(fr.lines())+'\n') for fr in frames[:6]]"
```

## Trace

```text
11:25
price 44,947.5
broad none
local none
micro none
approached_edge next_above
broken_edge none
release_held none
left none
next_above C08
next_below C09
local_invalidation none
broader_thesis_invalidation none

11:30
price 44,923.3
broad C05 44,761-44,966
local none
micro none
approached_edge next_above
broken_edge none
release_held none
left none
next_above C08
next_below C07
local_invalidation 44,760.5
broader_thesis_invalidation none

11:35
price 44,908.6
broad C05 44,761-44,966
local none
micro none
approached_edge next_above
broken_edge none
release_held none
left none
next_above C08
next_below C07
local_invalidation 44,760.5
broader_thesis_invalidation none

11:40
price 44,940.2
broad C05 44,761-44,966
local none
micro none
approached_edge next_above
broken_edge none
release_held none
left none
next_above C08
next_below C07
local_invalidation 44,760.5
broader_thesis_invalidation none

11:45
price 44,949.4
broad C05 44,761-44,966
local none
micro none
approached_edge next_above
broken_edge C09.high
release_held C09.high
left none
next_above C08
next_below C07
local_invalidation 44,760.5
broader_thesis_invalidation none

11:50
price 44,957.4
broad C05 44,761-44,966
local none
micro none
approached_edge upper
broken_edge none
release_held C09.high
left none
next_above C08
next_below C07
local_invalidation 44,760.5
broader_thesis_invalidation none
```
