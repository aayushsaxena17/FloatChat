# Stage 2 query latency report, 2026-10-09

- Commit: `fc9051c83d03` (uncommitted changes)
- Base URL: http://127.0.0.1:8000
- Runs per plan: 20 warm after 2 discarded; one cold call per plan after the restart command
- Host: Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39, 8 CPUs
- Dataset: source session `302412131a7c99fb`, digest (dump SHA-256) `objects 206|301781882`
- API limits (`/v1/catalog/parameters`): chart_points_per_series=5000, chart_series=20, default_page_size=100, duckdb_level_budget=5000000, histogram_bins=200, max_rows=50000, nearest_k=100, nearest_radius_km=2000.0, object_fetch_bytes=536870912, object_fetch_seconds=120.0, page_size=1000, postgres_level_budget=1000000, profile_levels=10000, query_timeout_seconds=10.0, request_bytes=65536, response_bytes=8388608, time_span_days=366, trajectory_points=1000

Method: One optional restart command, then a cold pass of one call per query plan in matrix order and one call per metadata route, then for each plan and route --warmup discarded calls followed by --runs recorded warm calls. Wall time is time.perf_counter around the HTTP request and body read (loopback, no proxy); server time is execution.elapsed_ms. p50 and p95 are nearest-rank over the sorted warm samples. A call that fails ends the warm loop of its plan and marks the row. Later cold calls may benefit from object-cache fills made by earlier plans of the same pass; the on-disk object cache is emptied only if the restart command does so.

## PostgreSQL route (profile listings, nearest, small aggregates)

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| postgresql | P01 profiles, Arabian Sea, Jan | 185,694 | 100 | 396.6 | 21.4 | 25.2 | 18.2 | 21.5 | ok |
| postgresql | P02 profiles, Bay of Bengal, Feb, 0-200 dbar | 47,334 | 83 | 250.2 | 22.9 | 35.1 | 19.3 | 30.6 | ok |
| postgresql | P03 profiles, bbox 50E-75E 10S-20N, quarter, temperature | 656,597 | 100 | 63.9 | 41.5 | 57.3 | 37.1 | 50.8 | ok |
| postgresql | P04 profiles, Southern Indian Ocean, Mar, 500-1000 dbar | 922,593 | 100 | 1235.5 | 109.8 | 138.9 | 105.7 | 135.0 | ok |
| postgresql | P05 nearest 10 within 500 km of 65E 15N, quarter | 81,561 | 10 | 80.6 | 17.6 | 25.3 | 14.7 | 17.2 | ok |
| postgresql | P06 nearest 50 within 1000 km of 88E 10N, quarter | 150,990 | 50 | 36.6 | 29.6 | 32.1 | 26.6 | 29.1 | ok |
| postgresql | P07 nearest 100 within 2000 km of 75E 40S, quarter | 1,967,594 | 100 | 151.5 | 81.5 | 120.0 | 77.7 | 115.2 | ok |
| postgresql | P08 aggregate, Laccadive Sea, Jan, by month | 72,848 | 1 | 46.8 | 19.6 | 24.0 | 16.9 | 19.3 | ok |
| postgresql | P09 aggregate, bbox 60E-75E 5N-20N, Feb, by month | 93,781 | 1 | 2812.6 | 427.9 | 528.6 | 424.8 | 524.8 | ok |
| postgresql | P10 aggregate, Andaman Sea, Mar, 0-500 dbar, by month | 2,247 | 0 | 132.6 | 17.8 | 20.7 | 14.8 | 17.3 | ok |

Objective (PRD section 3.1): warm p95 under 5000 ms. Worst warm p95: 528.6 ms. **PASS**

## DuckDB route (aggregates up to the whole-envelope quarter)

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| duckdb | D01 Indian Ocean, Jan-Feb, by month, profile | 2,715,032 | 2 | 4163.2 | 677.1 | 942.1 | 671.0 | 930.6 | ok |
| duckdb | D02 Indian Ocean, quarter, by month, profile | 4,144,346 | 3 | 2695.5 | 960.0 | 1190.8 | 944.5 | 1182.0 | ok |
| duckdb | D03 Indian Ocean, quarter, by month, measurement | 4,144,346 | 3 | 2568.5 | 1208.0 | 1360.9 | 1199.2 | 1352.9 | ok |
| duckdb | D04 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, profile | 4,144,346 | 63 | 2378.3 | 1365.3 | 1544.2 | 1358.8 | 1533.8 | ok |
| duckdb | D05 Indian Ocean, quarter, month+depth_bin 100, 0-2000 dbar, measurement | 4,144,346 | 63 | 1728.7 | 1477.9 | 1859.7 | 1462.5 | 1852.5 | ok |
| duckdb | D06 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, profile | 4,144,346 | 63 | 1134.7 | 1148.4 | 1312.9 | 1138.5 | 1303.6 | ok |
| duckdb | D07 Indian Ocean, quarter, month+depth_bin 50, 0-1000 dbar, measurement | 4,144,346 | 63 | 1251.1 | 1314.7 | 1399.7 | 1309.9 | 1394.9 | ok |
| duckdb | D08 Indian Ocean, quarter, month+float, profile | 4,144,346 | 1,901 | 1586.0 | 1211.6 | 1377.8 | 1190.9 | 1350.8 | ok |
| duckdb | D09 Indian Ocean, quarter, month+float, measurement | 4,144,346 | 1,901 | 1309.1 | 1345.1 | 1525.9 | 1329.7 | 1510.1 | ok |
| duckdb | D10 Indian Ocean, quarter, month+depth_bin 50, whole profile, temperature | 4,144,346 | 331 | 1225.4 | 1178.0 | 1327.5 | 1167.6 | 1318.5 | ok |

Objective (PRD section 3.1): warm p95 under 5000 ms. Worst warm p95: 1859.7 ms. **PASS**

## Metadata routes

| route | plan | est. levels | rows | cold ms | warm p50 ms | warm p95 ms | server p50 ms | server p95 ms | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| metadata | GET /v1/catalog/parameters | - | - | 17.1 | 1.9 | 2.7 | - | - | ok |
| metadata | GET /v1/catalog/coverage?region=Arabian Sea | - | - | 42.8 | 27.6 | 32.0 | - | - | ok |
| metadata | GET /v1/floats?limit=100 | - | 100 | 21.8 | 9.4 | 12.5 | - | - | ok |
| metadata | GET /v1/profiles?region=Arabian Sea&limit=100 | - | 100 | 18.3 | 11.5 | 13.4 | - | - | ok |

Objective (PRD section 3.1): warm p95 under 2000 ms. Worst warm p95: 32.0 ms. **PASS**

## Comparison with PRD section 3.1

| table | objective | worst warm p95 ms | result |
|---|---|---:|---|
| PostgreSQL route (profile listings, nearest, small aggregates) | p95 under 5000 ms | 528.6 | PASS |
| DuckDB route (aggregates up to the whole-envelope quarter) | p95 under 5000 ms | 1859.7 | PASS |
| Metadata routes | p95 under 2000 ms | 32.0 | PASS |

Metadata objective: Metadata/API p95 under 2 seconds. Aggregate objective: cached aggregate-query p95 under 5 seconds, applied to every row of both query tables.
