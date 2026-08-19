"""The Reactive Trader Observatory dashboard.

A visualisation layer over `src/livemap/observatory.py`, and nothing more. It takes no
decision, derives no fact and cannot execute: there is no order route, no sizing, no risk
and no broker. `EXECUTION_STATUS` is `UNAVAILABLE`.

    python tools/dash.py                 # http://127.0.0.1:8765
"""
