# Stage 2 cross-route agreement check, 2026-10-09

- Commit: `142549f240ed`
- Container: `floatchat-stage0-wsl-dev-api-1`
- Tolerance: relative 1e-09, absolute 1e-09
- Dataset: session 302412131a7c99fb (stage2-dataset-302412131a7c99fb.json)

Each plan ran twice through `QueryService.query`: PostgreSQL route forced by an unbounded PostgreSQL level budget, DuckDB route forced by a budget of one level; the DuckDB plans are those of the latency matrix (`scripts/query_latency.py`).

| plan | est. levels | rows | PostgreSQL ms | DuckDB ms | max relative difference | status |
|---|---:|---:|---:|---:|---:|---|
| D01 Indian Ocean, Jan-Feb, by month, profile | 2715032 | 2 | 14295.2 | 2117.7 | 2.26e-15 | ok |
| D02 Indian Ocean, quarter, by month, profile | 4144346 | 3 | 15670.1 | 1842.6 | 2.47e-15 | ok |
| D03 Indian Ocean, quarter, by month, measurement | 4144346 | 3 | 24266.8 | 2774.4 | 5.84e-14 | ok |
| D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile | 4144346 | 63 | 27359.5 | 3670.6 | 3.85e-15 | ok |
| D05 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, measurement | 4144346 | 63 | 30003.5 | 7604.2 | 2.23e-14 | ok |
| D06 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, profile | 4144346 | 63 | 21156.1 | 2439.9 | 2.55e-15 | ok |
| D07 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, measurement | 4144346 | 63 | 13643.5 | 2973.1 | 1.72e-14 | ok |
| D08 Indian Ocean, quarter, month+float, profile | 4144346 | 1901 | 9630.0 | 2141.1 | 4.29e-16 | ok |
| D09 Indian Ocean, quarter, month+float, measurement | 4144346 | 1901 | 24296.8 | 3183.0 | 1.27e-14 | ok |
| D10 Indian Ocean, quarter, month+depth_bin 50, whole profile, temperature | 4144346 | 331 | 14540.4 | 1733.0 | 3.15e-15 | ok |

Result: **PASS** (10 of 10 plans agree).
