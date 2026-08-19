# DATA REPORT

*Generated 2026-08-12 00:01 IST from `C:\Users\hp\Desktop\traderpar\banknifty-copilot\data` by `tools/verify_data.py`.*

This report exists to answer one question before any engine code is written: **are `volatility.atr_min_points 12` and `atr_max_points 60` in `config/params.yaml` right?** Everything else here is the integrity evidence that the measurement can be trusted.

## 1. Coverage

| instrument | files | first day | last day | trading days | candles | median close |
|---|---:|---|---|---:|---:|---:|
| NIFTY 50 | 37 | 2023-08-01 | 2026-08-11 | 751 | 280,133 | 24,034 |
| NIFTY BANK | 37 | 2023-08-01 | 2026-08-11 | 751 | 280,132 | 52,129 |
| NIFTY FIN SERVICE | 37 | 2023-08-01 | 2026-08-11 | 751 | 280,133 | 23,994 |
| SENSEX | 37 | 2023-08-01 | 2026-08-11 | 751 | 280,137 | 77,963 |

Range **2023-08-01 → 2026-08-11** — 791 weekdays, 745 with data (94.2% of weekdays; the remainder should be NSE holidays).

**Suspected holidays** (weekday, no data on any instrument): 46. 2023-08-15, 2023-09-19, 2023-10-02, 2023-10-24, 2023-11-14, 2023-11-27, 2023-12-25, 2024-01-22, 2024-01-26, 2024-03-08, 2024-03-25, 2024-03-29 …

**Real holes: none.** Every instrument has data on every day that any instrument has data.

## 2. Per-day integrity

| instrument | normal days | clean | wrong count | with gaps | duplicates | OHLC violations | special |
|---|---:|---:|---:|---:|---:|---:|---:|
| NIFTY 50 | 746 | 744 | 2 | 2 | 0 | 0 | 5 |
| NIFTY BANK | 746 | 743 | 3 | 3 | 0 | 0 | 5 |
| NIFTY FIN SERVICE | 746 | 744 | 2 | 2 | 0 | 0 | 5 |
| SENSEX | 746 | 744 | 2 | 2 | 0 | 0 | 5 |

**Abbreviated sessions — 5, excluded from every statistic below and from the overnight-continuity chain** (DECISIONS.md D-018). Not gaps, not defects — not a real market:

| day | weekday | window | what it is |
|---|---|---|---|
| 2023-11-12 | Sun | 18:15–19:14 | off-hours 18:15-19:14, 60 candles (Muhurat) |
| 2024-03-02 | Sat | 09:15–12:29 | half day, ends 12:29, 105 candles (NSE DR-site test) |
| 2024-05-18 | Sat | 09:15–12:29 | half day, ends 12:29, 105 candles (NSE DR-site test) |
| 2024-11-01 | Fri | 18:00–18:59 | off-hours 18:00-18:59, 60 candles (Muhurat) |
| 2025-10-21 | Tue | 13:45–14:44 | off-hours 13:45-14:44, 60 candles (Muhurat) |

**The engine must skip these too.** `2025-10-21`'s Muhurat window (13:45–14:44) sits **inside** `time.windows_normal` `[13:30, 14:45]`, so without an explicit exclusion the engine would treat a one-hour ceremonial session as an ordinary trading window and never mention it.

**Full sessions held on a weekend — 3, KEPT**: 2024-01-20 (Sat), 2025-02-01 (Sat), 2026-02-01 (Sun). A complete 09:15–15:29 session with real liquidity, held for the Union Budget or as an NSE special session. Dropping these would break the overnight chain and invent a gap on the following Monday. Whether the engine *trades* them is `config/events.yaml`'s business (Budget is a full-day blackout) — a calendar decision, not a data-integrity one.

**NIFTY 50 — worst gap days:**

| day | candles | missing | runs |
|---|---:|---:|---|
| 2024-04-23 | 369 | 6 | 10:52–10:57 (6) |
| 2023-08-07 | 374 | 1 | 15:23–15:23 (1) |

**NIFTY BANK — worst gap days:**

| day | candles | missing | runs |
|---|---:|---:|---|
| 2024-04-23 | 369 | 6 | 10:52–10:57 (6) |
| 2023-08-07 | 374 | 1 | 15:23–15:23 (1) |
| 2025-12-15 | 374 | 1 | 15:15–15:15 (1) |

**NIFTY FIN SERVICE — worst gap days:**

| day | candles | missing | runs |
|---|---:|---:|---|
| 2024-04-23 | 369 | 6 | 10:52–10:57 (6) |
| 2023-08-07 | 374 | 1 | 15:23–15:23 (1) |

**SENSEX — worst gap days:**

| day | candles | missing | runs |
|---|---:|---:|---|
| 2025-12-15 | 373 | 2 | 15:15–15:15 (1), 15:17–15:17 (1) |
| 2023-08-07 | 374 | 1 | 15:23–15:23 (1) |

**NIFTY 50 — overnight gaps ≥ 2.0%:** 9 — 2024-06-03 (+3.49%), 2025-04-07 (-5.04%), 2025-04-15 (+2.29%), 2026-02-03 (+4.90%), 2026-03-02 (-2.08%), 2026-03-09 (-2.46%), 2026-03-19 (-2.38%), 2026-04-01 (+2.32%) …

**NIFTY BANK — overnight gaps ≥ 2.0%:** 12 — 2024-01-17 (-3.20%), 2024-06-03 (+3.92%), 2025-04-07 (-4.23%), 2025-04-15 (+2.53%), 2026-02-03 (+4.79%), 2026-03-02 (-2.11%), 2026-03-04 (-2.35%), 2026-03-09 (-2.87%) …

**NIFTY FIN SERVICE — overnight gaps ≥ 2.0%:** 11 — 2024-01-17 (-3.29%), 2024-06-03 (+4.02%), 2025-04-07 (-4.04%), 2025-04-15 (+2.71%), 2026-02-03 (+4.90%), 2026-03-04 (-2.16%), 2026-03-09 (-2.93%), 2026-03-19 (-2.97%) …

**SENSEX — overnight gaps ≥ 2.0%:** 13 — 2024-06-03 (+3.47%), 2024-08-05 (-2.89%), 2025-04-07 (-5.25%), 2025-04-15 (+2.16%), 2026-02-03 (+4.52%), 2026-03-02 (-3.41%), 2026-03-04 (-2.08%), 2026-03-09 (-2.45%) …

## 3. ATR14(1m) — measured, against the guess

ATR convention: simple mean of `high - low` over 14 candles, within a session, no carry across days (DECISIONS.md D-012 — this is what `prototype/engine_fixed.py` does and what every threshold in `params.yaml` was reasoned against).

### NIFTY 50

| p1 | p5 | p10 | p25 | **p50** | p75 | p90 | p95 | p99 | mean | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3.6 | 4.5 | 5.0 | 6.1 | 7.8 | 10.3 | 13.7 | 16.2 | 23.4 | 8.8 | 107.4 |

- `atr_min_points 12` sits at the **84.3th percentile** → **84.3%** of candles are blocked by `volatility_floor`
- `atr_max_points 60` sits at the **100.0th percentile** → **0.0%** of candles are blocked by `volatility_ceiling`
- combined: the volatility gate rejects **84.4%** of all candles
- inside `time.windows_normal` only (the candles that can actually trade): floor blocks **79.8%**, ceiling blocks **0.0%**, median ATR **8.4**
- true-range variant median **7.8** vs plain-range median **7.8** (+0.6%) — the convention choice is worth this much

**By time of day** (median ATR14):

| bucket | 09:15-09:30 open | 09:30-11:15 window A | 11:15-13:30 lunch | 13:30-14:45 window B | 14:45-15:29 close |
|---|---:|---:|---:|---:|---:|
| median | 15.5 | 9.1 | 6.9 | 7.6 | 8.2 |

**By year** (median ATR14 — this is the number that decides whether one fixed point threshold can span the sample):

| year | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| median | 5.3 | 8.4 | 7.6 | 9.1 |
| p5 | 3.5 | 5.0 | 4.7 | 5.6 |
| p95 | 9.4 | 17.5 | 15.5 | 17.2 |

### NIFTY BANK

| p1 | p5 | p10 | p25 | **p50** | p75 | p90 | p95 | p99 | mean | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11.5 | 14.0 | 15.6 | 18.8 | 23.6 | 30.2 | 38.8 | 45.7 | 64.7 | 26.1 | 249.7 |

- `atr_min_points 12` sits at the **1.4th percentile** → **1.4%** of candles are blocked by `volatility_floor`
- `atr_max_points 60` sits at the **98.5th percentile** → **1.5%** of candles are blocked by `volatility_ceiling`
- combined: the volatility gate rejects **2.9%** of all candles
- inside `time.windows_normal` only (the candles that can actually trade): floor blocks **0.9%**, ceiling blocks **1.7%**, median ATR **25.2**
- true-range variant median **23.7** vs plain-range median **23.6** (+0.6%) — the convention choice is worth this much

**By time of day** (median ATR14):

| bucket | 09:15-09:30 open | 09:30-11:15 window A | 11:15-13:30 lunch | 13:30-14:45 window B | 14:45-15:29 close |
|---|---:|---:|---:|---:|---:|
| median | 47.1 | 27.5 | 21.1 | 22.6 | 24.8 |

**By year** (median ATR14 — this is the number that decides whether one fixed point threshold can span the sample):

| year | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| median | 17.8 | 25.4 | 22.3 | 27.3 |
| p5 | 11.4 | 15.1 | 14.4 | 17.6 |
| p95 | 31.3 | 51.1 | 40.4 | 49.3 |

### NIFTY FIN SERVICE

| p1 | p5 | p10 | p25 | **p50** | p75 | p90 | p95 | p99 | mean | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4.9 | 6.1 | 6.8 | 8.3 | 10.4 | 13.4 | 17.2 | 20.3 | 29.0 | 11.5 | 108.8 |

- `atr_min_points 12` sits at the **65.5th percentile** → **65.5%** of candles are blocked by `volatility_floor`
- `atr_max_points 60` sits at the **99.9th percentile** → **0.1%** of candles are blocked by `volatility_ceiling`
- combined: the volatility gate rejects **65.6%** of all candles
- inside `time.windows_normal` only (the candles that can actually trade): floor blocks **58.3%**, ceiling blocks **0.1%**, median ATR **11.1**
- true-range variant median **10.5** vs plain-range median **10.4** (+0.6%) — the convention choice is worth this much

**By time of day** (median ATR14):

| bucket | 09:15-09:30 open | 09:30-11:15 window A | 11:15-13:30 lunch | 13:30-14:45 window B | 14:45-15:29 close |
|---|---:|---:|---:|---:|---:|
| median | 21.3 | 12.1 | 9.3 | 10.0 | 11.0 |

**By year** (median ATR14 — this is the number that decides whether one fixed point threshold can span the sample):

| year | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| median | 7.5 | 10.7 | 10.3 | 12.1 |
| p5 | 4.8 | 6.4 | 6.7 | 7.9 |
| p95 | 12.7 | 22.1 | 19.0 | 22.1 |

### SENSEX

| p1 | p5 | p10 | p25 | **p50** | p75 | p90 | p95 | p99 | mean | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12.6 | 14.9 | 16.3 | 19.4 | 24.6 | 32.6 | 43.0 | 50.8 | 70.9 | 27.9 | 334.9 |

- `atr_min_points 12` sits at the **0.6th percentile** → **0.6%** of candles are blocked by `volatility_floor`
- `atr_max_points 60` sits at the **97.7th percentile** → **2.3%** of candles are blocked by `volatility_ceiling`
- combined: the volatility gate rejects **2.9%** of all candles
- inside `time.windows_normal` only (the candles that can actually trade): floor blocks **0.3%**, ceiling blocks **2.4%**, median ATR **26.4**
- true-range variant median **24.8** vs plain-range median **24.6** (+1.1%) — the convention choice is worth this much

**By time of day** (median ATR14):

| bucket | 09:15-09:30 open | 09:30-11:15 window A | 11:15-13:30 lunch | 13:30-14:45 window B | 14:45-15:29 close |
|---|---:|---:|---:|---:|---:|
| median | 51.0 | 29.0 | 21.4 | 22.7 | 28.5 |

**By year** (median ATR14 — this is the number that decides whether one fixed point threshold can span the sample):

| year | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|
| median | 18.5 | 26.0 | 23.7 | 29.4 |
| p5 | 12.4 | 16.1 | 15.1 | 17.4 |
| p95 | 33.5 | 54.1 | 46.6 | 56.5 |

## 4. Day-level volatility — how many whole days the gate removes

A candle-level percentage understates the effect: ATR is persistent, so blocked candles cluster into blocked days. This counts days by their median ATR14.

| instrument | days | median-ATR < min | median-ATR > max | tradeable days |
|---|---:|---:|---:|---:|
| NIFTY 50 | 746 | 686 (92.0%) | 0 (0.0%) | 60 |
| NIFTY BANK | 746 | 0 (0.0%) | 2 (0.3%) | 744 |
| NIFTY FIN SERVICE | 746 | 551 (73.9%) | 1 (0.1%) | 194 |
| SENSEX | 746 | 0 (0.0%) | 2 (0.3%) | 744 |

## 5. Cross-instrument — can one point threshold serve all four? (P9)

`CLAUDE.md` §8 requires the identical, unchanged ruleset to run on all four instruments. `atr_min_points` / `atr_max_points` are **absolute points**, so this table decides whether that is possible.

| instrument | median close | median ATR14 | ATR as bps of price | % candles below min | % above max |
|---|---:|---:|---:|---:|---:|
| NIFTY 50 | 24,034 | 7.8 | 3.24 | 84.3% | 0.0% |
| NIFTY BANK | 52,129 | 23.6 | 4.52 | 1.4% | 1.5% |
| NIFTY FIN SERVICE | 23,994 | 10.4 | 4.33 | 65.5% | 0.1% |
| SENSEX | 77,963 | 24.6 | 3.15 | 0.6% | 2.3% |

## 6. What this says to write into `params.yaml`

Measured on **NIFTY BANK**, 270,044 ATR observations over 751 sessions:

| candidate | percentile | points |
|---|---:|---:|
| floor | p1 | 11.5 |
| floor | p2 | 12.5 |
| floor | p5 | 14.0 |
| floor | p10 | 15.6 |
| ceiling | p90 | 38.8 |
| ceiling | p95 | 45.7 |
| ceiling | p98 | 56.0 |
| ceiling | p99 | 64.7 |

Current guesses: floor **12** (= p1.4), ceiling **60** (= p98.5).

`atr_min_percentile` / `atr_max_percentile` are still `null`. They should be set from the table above rather than left as points, because §3's by-year row shows whether a fixed point value means the same thing across the sample. Filling them is a decision for the user, not for this tool — the numbers are here, the choice is not made.

## 7. Is the P9 plan (3 years × 4 instruments) possible with this data?

- **NIFTY 50**: 3.0 years, 751 sessions → **yes**
- **NIFTY BANK**: 3.0 years, 751 sessions → **yes**
- **NIFTY FIN SERVICE**: 3.0 years, 751 sessions → **yes**
- **SENSEX**: 3.0 years, 751 sessions → **yes**

