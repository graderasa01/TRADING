"""
The live map interpreter — geography, never a decision.

This package is **import-isolated on purpose**, the same way `src/journey/` is, and for the
same reason its docstring gives: *"a strong intuition that has never been measured is
exactly the kind of thing that quietly becomes a rule and then quietly loses money."*

`test_livemap_never_read_by_the_trading_path` asserts statically that `setups/`, `risk/`,
`exits/`, `modes/`, `broker/` and `guards/` do not import anything from here.

What this package produces:

```
CURRENT · BREAK_LEVELS · ABOVE · BELOW · INTERACTION · REFERENCES · STATUS
```

What it must never produce: `LONG`, `SHORT`, `ENTRY`, a size, a stop, or a target.
The map is geography. The decision layer does not exist yet.
"""
