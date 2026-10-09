# Stage 2 query latency report, 2026-10-09

- Commit: `fc9051c83d03`
- Base URL: http://127.0.0.1:8000
- Runs per plan: 20 warm after 2 discarded; one cold call per plan after the restart command
- Host: Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39, 8 CPUs
- Dataset: source session `302412131a7c99fb`, digest (dump SHA-256) `objects 206|301781882`
- API limits (`/v1/catalog/parameters`): chart_points_per_series=5000, chart_series=20, default_page_size=100, duckdb_level_budget=5000000, histogram_bins=200, max_rows=50000, nearest_k=100, nearest_radius_km=2000.0, object_fetch_bytes=536870912, object_fetch_seconds=120.0, page_size=1000, postgres_level_budget=1000000, profile_levels=10000, query_timeout_seconds=10.0, request_bytes=65536, response_bytes=8388608, time_span_days=366, trajectory_points=1000

Method: One optional restart command, then a cold pass of one call per query plan in matrix order and one call per metadata route, then for each plan and route --warmup discarded calls followed by --runs recorded warm calls. Wall time is time.perf_counter around the HTTP request and body read (loopback, no proxy); server time is execution.elapsed_ms. p50 and p95 are nearest-rank over the sorted warm samples. A call that fails ends the warm loop of its plan and marks the row. Later cold calls may benefit from object-cache fills made by earlier plans of the same pass; the on-disk object cache is emptied only if the restart command does so.

## PostgreSQL route (profile listings, nearest, small aggregates)

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| postgresql | P01 profiles, Arabian Sea, Jan | 185,694 | 100 | 227.9 | 22.0 | 25.9 | 18.5 | 21.7 | ok |
| postgresql | P02 profiles, Bay of Bengal, Feb, 0-200 dbar | 47,334 | 83 | 227.4 | 27.8 | 37.9 | 23.2 | 30.8 | ok |
| postgresql | P03 profiles, bbox 50E-75E 10S-20N, quarter, temperature | 656,597 | 100 | 131.1 | 27.5 | 36.0 | 23.9 | 31.9 | ok |
| postgresql | P04 profiles, Southern Indian Ocean, Mar, 500-1000 dbar | 922,593 | 100 | 3870.3 | 115.6 | 142.9 | 112.0 | 136.7 | ok |
| postgresql | P05 nearest 10 within 500 km of 65E 15N, quarter | 81,561 | 10 | 139.5 | 15.9 | 25.4 | 12.9 | 19.2 | ok |
| postgresql | P06 nearest 50 within 1000 km of 88E 10N, quarter | 150,990 | 50 | 70.5 | 33.9 | 64.9 | 29.7 | 59.6 | ok |
| postgresql | P07 nearest 100 within 2000 km of 75E 40S, quarter | 1,967,594 | 100 | 202.3 | 97.4 | 149.1 | 92.9 | 139.9 | ok |
| postgresql | P08 aggregate, Laccadive Sea, Jan, by month | 72,848 | 1 | 73.8 | 21.4 | 29.4 | 18.7 | 22.6 | ok |
| postgresql | P09 aggregate, bbox 60E-75E 5N-20N, Feb, by month | 93,781 | 1 | 2680.4 | 456.7 | 609.2 | 453.2 | 603.4 | ok |
| postgresql | P10 aggregate, Andaman Sea, Mar, 0-500 dbar, by month | 2,247 | 0 | 61.6 | 23.0 | 28.1 | 19.1 | 23.9 | ok |

Objective (PRD section 3.1): warm p95 under 5000 ms. Worst warm p95: 609.2 ms. **PASS**

## DuckDB route (aggregates up to the whole-envelope quarter)

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| duckdb | D01 Indian Ocean, Jan-Feb, by month, profile | 2,715,032 | 2 | 3336.6 | 723.6 | 899.5 | 707.0 | 892.2 | ok |
| duckdb | D02 Indian Ocean, quarter, by month, profile | 4,144,346 | 3 | 11722.4 | 1077.4 | 1463.5 | 1059.6 | 1455.5 | ok |
| duckdb | D03 Indian Ocean, quarter, by month, measurement | 4,144,346 | 3 | 4439.4 | 1255.7 | 1512.6 | 1248.0 | 1495.2 | ok |
| **-** (expected duckdb) | D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile | - | - | - | - | - | - | - | **statement_timeout** HTTP 504 |
| duckdb | D05 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, measurement | 4,144,346 | 63 | 4163.3 | 1497.6 | 1678.1 | 1492.4 | 1670.7 | ok |
| duckdb | D06 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, profile | 4,144,346 | 63 | 1800.4 | 1199.8 | 1406.1 | 1190.6 | 1399.6 | ok |
| duckdb | D07 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, measurement | 4,144,346 | 63 | 1568.9 | 1386.1 | 1825.6 | 1380.3 | 1817.2 | ok |
| duckdb | D08 Indian Ocean, quarter, month+float, profile | 4,144,346 | 1,901 | 1128.1 | 1040.4 | 1245.0 | 1016.1 | 1227.6 | ok |
| duckdb | D09 Indian Ocean, quarter, month+float, measurement | 4,144,346 | 1,901 | 1524.3 | 1166.0 | 1394.9 | 1151.7 | 1377.7 | ok |
| duckdb | D10 Indian Ocean, quarter, month+depth_bin 50, whole profile, temperature | 4,144,346 | 331 | 976.9 | 1047.6 | 1230.8 | 1032.5 | 1223.6 | ok |

Objective (PRD section 3.1): warm p95 under 5000 ms. Worst warm p95: 1825.6 ms. **FAIL**
- D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile: failed with statement_timeout

## Metadata routes

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| metadata | GET /v1/catalog/parameters | - | - | 4.3 | 1.8 | 2.0 | - | - | ok |
| metadata | GET /v1/catalog/coverage?region=Arabian Sea | - | - | 32.7 | 25.8 | 29.1 | - | - | ok |
| metadata | GET /v1/floats?limit=100 | - | 100 | 33.5 | 9.0 | 9.8 | - | - | ok |
| metadata | GET /v1/profiles?region=Arabian Sea&limit=100 | - | 100 | 12.1 | 12.9 | 14.6 | - | - | ok |

Objective (PRD section 3.1): warm p95 under 2000 ms. Worst warm p95: 29.1 ms. **PASS**

## Comparison with PRD section 3.1

| table | objective | worst warm p95 ms | result |
|---|---|---:|---|
| PostgreSQL route (profile listings, nearest, small aggregates) | p95 under 5000 ms | 609.2 | PASS |
| DuckDB route (aggregates up to the whole-envelope quarter) | p95 under 5000 ms | 1825.6 | FAIL |
| Metadata routes | p95 under 2000 ms | 29.1 | PASS |

Metadata objective: Metadata/API p95 under 2 seconds. Aggregate objective: cached aggregate-query p95 under 5 seconds, applied to every row of both query tables.
