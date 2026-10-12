# Stage 2 cross-route agreement check, 2026-10-11

- Commit: `ae527d8ca923`
- Container: `floatchat-stage0-wsl-dev-api-1`
- Tolerance: relative 1e-09, absolute 1e-09
- Dataset: session 302412131a7c99fb (stage2-dataset-302412131a7c99fb.json)

Each plan ran twice through `QueryService.query`: PostgreSQL route forced by an unbounded PostgreSQL level budget, DuckDB route forced by a budget of one level; the DuckDB plans are those of the latency matrix (`scripts/query_latency.py`).

| plan | est. levels | rows | PostgreSQL ms | DuckDB ms | max relative difference | status |
|---|---:|---:|---:|---:|---:|---|
| D01 Indian Ocean, Jan-Feb, by month, profile | 2715032 | 2 | 11216.9 | 3518.4 | 2.26e-15 | ok |
| D02 Indian Ocean, quarter, by month, profile | 4144346 | 3 | 19099.7 | 1983.6 | 1.85e-15 | ok |
| D03 Indian Ocean, quarter, by month, measurement | 4144346 | 3 | 32181.7 | 2526.4 | 5.92e-14 | ok |
| D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile | 4144346 | 63 | 59599.2 | 4380.5 | 3.02e-15 | ok |
| D05 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, measurement | 4144346 | 63 | 49909.2 | 4590.2 | 2.01e-14 | ok |
| D06 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, profile | 4144346 | 63 | 25960.9 | 3967.8 | 2.75e-15 | ok |
| D07 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, measurement | 4144346 | 63 | 30416.5 | 3461.0 | 1.48e-14 | ok |
| D08 Indian Ocean, quarter, month+float, profile | 4144346 | 1901 | 20226.3 | 2920.2 | 4.26e-16 | ok |
| D09 Indian Ocean, quarter, month+float, measurement | 4144346 | 1901 | 46235.0 | 1905.2 | 1.27e-14 | ok |
| D10 Indian Ocean, quarter, month+depth_bin 50, whole profile, temperature | 4144346 | 331 | 61984.8 | 3603.0 | 3.00e-15 | ok |

Result: **PASS** (10 of 10 plans agree).
