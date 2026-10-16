# Historical jobs report (2026-10-16)

Commit `2e8956a97a28b41b579a3203619eb5d7e02b9dff`; API `http://127.0.0.1:8000`; client `stage5-report`. One export request run 3 times through `POST /v1/exports` (ADR-0079); every number below is read from the job rows and the ingestion runs they created.

## Request

- Region: Arabian Sea
- Period: 2015-04-01T00:00:00Z to 2025-04-01T00:00:00Z (exclusive)
- Depth: 0.0 to 2000.0 dbar; QC policy science_ready; format parquet

## Runs

| Run | Job | State | Months × tiles | Reused | Fetch chunks | Duration (job) | Chunk time | HTTP requests | Retries | Profiles accepted |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `9102c598` | failed | 1200 | 30 (2%) | 10 (9 complete, 1 failed) | 777.5 min | 350.8 min | 9455 | 1 | 24907 |
| 2 | `4c5e8664` | partial | 1200 | 1124 (94%) | 9 (9 complete, 0 failed) | 19.3 min | 19.2 min | 1229 | 0 | 3579 |
| 3 | `385a0867` | partial | 1200 | 1188 (99%) | 9 (9 complete, 0 failed) | 5.5 min | 5.4 min | 0 | 0 | 0 |

## Chunks of run 1

| Chunk | Months | State | Ingestion runs | Last run state | Termination | Leaf states | HTTP requests | Retries | Profiles | Levels | Received | Duration |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2015-04..2015-12 | failed | 1 | partial | deadline_expired | {"failed": 65, "complete": 25} | 494 | 0 | 1455 | 173486 | 10.8 MB | 426.6 min (spans the clock jump) |
| 2 | 2016-01..2016-12 | complete | 2 | complete | - | {"complete": 36} | 602 | 0 | 1517 | 781082 | 42.3 MB | 78.2 min |
| 3 | 2017-01..2017-12 | complete | 1 | quarantined | - | {"quarantined": 1} | 7 | 0 | 0 | 0 | 337.0 KB | 173.1 min |
| 4 | 2018-01..2018-12 | complete | 1 | complete | - | {"complete": 120} | 2016 | 0 | 6156 | 2347164 | 128.3 MB | 20.8 min |
| 5 | 2019-01..2019-12 | complete | 1 | complete | - | {"complete": 120} | 1828 | 0 | 3438 | 1704390 | 112.8 MB | 13.6 min |
| 6 | 2020-01..2020-12 | complete | 1 | complete | - | {"complete": 84} | 1100 | 1 | 2613 | 1442295 | 73.9 MB | 9.6 min |
| 7 | 2021-01..2021-12 | complete | 1 | partial | - | {"complete": 83, "quarantined": 1} | 896 | 0 | 2650 | 1722908 | 78.6 MB | 15.1 min |
| 8 | 2022-01..2022-12 | complete | 1 | partial | - | {"complete": 78, "quarantined": 6} | 763 | 0 | 2306 | 1533458 | 73.8 MB | 11.8 min |
| 9 | 2023-01..2023-12 | complete | 1 | partial | - | {"complete": 83, "quarantined": 1} | 820 | 0 | 2408 | 1659146 | 88.2 MB | 11.4 min |
| 10 | 2024-01..2024-12 | complete | 1 | complete | - | {"complete": 84} | 929 | 0 | 2364 | 1696345 | 90.2 MB | 11.0 min |
| 11 | export | failed | - | - | - | {} | - | - | - | - | - | 6.2 min |

## Chunks of run 2

| Chunk | Months | State | Ingestion runs | Last run state | Termination | Leaf states | HTTP requests | Retries | Profiles | Levels | Received | Duration |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2015-06..2015-12 | complete | 1 | partial | - | {"complete": 68, "quarantined": 2} | 1211 | 0 | 3501 | 504046 | 28.5 MB | 10.9 min |
| 2 | 2016-01 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 3 | 2016-03 | complete | 1 | complete | - | {"complete": 1} | 18 | 0 | 78 | 13215 | 586.5 KB | 3.8 min |
| 4 | 2017-02 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 5 | 2021-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 6 | 2022-06..2022-07 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 7 | 2022-10 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 8 | 2022-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 9 | 2023-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 10 | export | complete | - | - | - | {} | - | - | - | - | - | 4.5 min |

## Chunks of run 3

| Chunk | Months | State | Ingestion runs | Last run state | Termination | Leaf states | HTTP requests | Retries | Profiles | Levels | Received | Duration |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2015-09 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 2 | 2015-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 3 | 2016-01 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 4 | 2017-02 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 5 | 2021-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 6 | 2022-06..2022-07 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 7 | 2022-10 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 8 | 2022-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 9 | 2023-12 | complete | 0 | quarantined | - | {} | - | - | - | - | - | 0.0 min |
| 10 | export | complete | - | - | - | {} | - | - | - | - | - | 5.4 min |

## Artefacts

| Run | Role | File | Bytes | Rows | Profiles | SHA-256 |
|---|---|---|---|---|---|---|
| 2 | data | `floatchat-export-4c5e8664.parquet` | 212381074 | 13322687 | 31131 | `c5b70570a8630cfc…` |
| 2 | manifest | `floatchat-export-4c5e8664.manifest.json` | 165485 | 0 | 0 | `d1c05e7fde815dd5…` |
| 2 | provenance | `floatchat-export-4c5e8664.provenance.json` | 171585 | 0 | 0 | `13970cea1b8ac3a1…` |
| 3 | data | `floatchat-export-385a0867.parquet` | 212381074 | 13322687 | 31131 | `c5b70570a8630cfc…` |
| 3 | manifest | `floatchat-export-385a0867.manifest.json` | 165485 | 0 | 0 | `27f2df644ce317f6…` |
| 3 | provenance | `floatchat-export-385a0867.provenance.json` | 171584 | 0 | 0 | `485674b3f21396eb…` |

## What run 2 added to the stores

| Measure | Before | After | Added |
|---|---|---|---|
| Profiles in the registry | 55257 | 58836 | 3579 |
| Measurement levels in PostgreSQL | 25231834 | 25749095 | 517261 |
| Committed Parquet parts | 1418 | 1475 | 57 |
| PostgreSQL bytes of core_measurement | 0.0 KB | 0.0 KB | 0.0 KB |
| PostgreSQL bytes of argo_profile | 1.10 GB | 1.13 GB | 29.3 MB |
| PostgreSQL database bytes | 8.35 GB | 8.54 GB | 196.6 MB |
| Object-store bytes of committed parts | 1.73 GB | 1.77 GB | 38.4 MB |

## What run 3 added to the stores

| Measure | Before | After | Added |
|---|---|---|---|
| Profiles in the registry | 58836 | 58836 | 0 |
| Measurement levels in PostgreSQL | 25749095 | 25749095 | 0 |
| Committed Parquet parts | 1475 | 1475 | 0 |
| PostgreSQL bytes of core_measurement | 0.0 KB | 0.0 KB | 0.0 KB |
| PostgreSQL bytes of argo_profile | 1.13 GB | 1.13 GB | 0.0 KB |
| PostgreSQL database bytes | 8.54 GB | 8.54 GB | 176.0 KB |
| Object-store bytes of committed parts | 1.77 GB | 1.77 GB | 0.0 KB |

## Notes

- Cache reuse ratio of run 3: 0.99 (slots reused over slots required; slots not reused are fetched, or listed as quarantined without a run).
- Missing slots after run 3: 12 (months ['2015-09', '2015-12', '2016-01', '2017-02', '2021-12', '2022-06', '2022-07', '2022-10', '2022-12', '2023-12'])
- The data artefacts of the runs that exported are byte-identical (one SHA-256, `c5b70570a8630cfc…`): the export is deterministic over the same catalogue.
- Historical months are stored in PostgreSQL and as Parquet parts alike (ADR-0078 point 4); the table above records the cost of that decision for this region.
- Failed chunk: run 1 chunk 1 (2015-04..2015-12): fetch_partial - The ingestion run ended partial (deadline_expired). after 1 ingestion run(s); it failed before the runner retried fetch chunks (one run only).
- Failed chunk: run 1 chunk 11 (export): export_failed - DuckDB: IOException.
- Run 2: 12 month-tile slot(s) quarantined by the Stage 1 source policy (an upstream data warning quarantines the whole month-tile, ADR-0040/0046) and not fetched again: ['2015-09 50:20', '2015-12 50:20', '2016-01 50:20', '2017-02 50:20', '2021-12 50:20', '2022-06 50:10', '2022-06 50:20', '2022-07 50:10', '2022-10 50:20', '2022-12 50:20', '2022-12 60:20', '2023-12 50:10'].
- Run 3: 12 month-tile slot(s) quarantined by the Stage 1 source policy (an upstream data warning quarantines the whole month-tile, ADR-0040/0046) and not fetched again: ['2015-09 50:20', '2015-12 50:20', '2016-01 50:20', '2017-02 50:20', '2021-12 50:20', '2022-06 50:10', '2022-06 50:20', '2022-07 50:10', '2022-10 50:20', '2022-12 50:20', '2022-12 60:20', '2023-12 50:10'].
- Run 3 planned 9 fetch chunk(s) from the catalogue for the slots the previous run left missing (months ['2015-09', '2015-12', '2016-01', '2017-02', '2021-12', '2022-06', '2022-07', '2022-10', '2022-12', '2023-12']); everything else was reused.
- The host clock jumped about seven hours at 00:48 UTC on 2026-10-16; job durations that include it are not wall time. The 'Chunk time' column sums chunk durations and leaves out run 1 chunk 1 (2015-04..2015-12).
