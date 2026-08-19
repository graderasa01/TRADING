"""The learning loop — spec 11. Split discipline and hypothesis testing.

Kept in its own package so nothing in the trading path can import it. A rule that has
survived this loop is written into `config/params.yaml`; the loop itself never runs
inside `on_candle`.
"""
