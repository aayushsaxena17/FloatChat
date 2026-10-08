# Stage 2 plan - query engine and API (draft, not started)

Status: **planning only**. Stage 2 starts after the Stage 1 gate closes with the
advisor's recorded agreement (ADR-0039). Scope: build prompt "Stage 2", PRD §8, §11.3,
§13. Work happens on branch `codex/stage-2` from the Stage 1 head.

## Inputs Stage 1 provides

- Committed science in PostgreSQL (`app.argo_profile`, month-partitioned
  `app.core_measurement`) and verified Parquet generations selected through
  `select_active_partitions` / `app.committed_active_partitions`.
- Catalogue slots `argovis/core/YYYY-MM/<west>:<south>/indian-ocean-v1/...` with
  coverage receipts; S1-SOURCE-2 receipts and exclusions in persisted reports.

## Work items

1. `packages/core/src/floatchat_core/query/plan.py`: Pydantic `QueryPlan` per §8.1
   (dataset, time_range, geography: named_region | bbox | point+radius, depth_dbar,
   variables, qc_policy, operation: profiles | aggregate | nearest, presentation).
   Rejections: unknown fields/columns/functions, invalid ranges, unbounded raw requests,
   disallowed formats, cost estimate over budget, variable/operation mismatch.
2. Named regions: Indian Ocean, Arabian Sea, Bay of Bengal, Andaman Sea, Laccadive Sea,
   Southern Indian Ocean, as versioned WKT with source citation (IHO "Limits of Oceans
   and Seas" via Marine Regions gazetteer IDs) and SHA-256; migration 0010 adds a
   read-only `app.named_region` table. Southern Indian Ocean uses the PRD envelope
   clipped at 60S where the IHO polygon is not suitable; recorded in an ADR.
3. Compilers (`query/compile_sql.py`, `query/compile_duckdb.py`, `query/chart.py`):
   parameterised SQLAlchemy Core over a read-only role with `statement_timeout`;
   DuckDB over an explicit allow-list of catalogue-selected object keys (no globbing,
   no external access); Plotly spec from bounded result schemas (§11.3).
4. Coverage router (§8.3) over the 12-month PostgreSQL window and Parquet generations,
   with partial-coverage labelling and the result sanitiser (§8.5).
5. API (`apps/api`): `GET /v1/catalog/parameters`, `/v1/catalog/coverage`, `/v1/floats`,
   `/v1/floats/{platform_number}`, `/v1/profiles`, `/v1/profiles/{profile_id}`,
   `POST /v1/query`; §13.2 conventions (versioned prefix, stable error codes,
   correlation-ID header, cursor pagination, no raw SQL anywhere).
6. Migration 0010: read-only `floatchat_query` role (SELECT on science/catalogue views
   only, statement timeout), `app.named_region`; additive only.
7. OpenAPI published as a tested artefact; TypeScript client generated into
   `apps/web/src/api/` (openapi-typescript, pinned).
8. Tests: compiler allow-lists, SQL-injection attempts through every plan field,
   interval arithmetic, longitude/dateline cases, nearest-profile via `ST_DWithin` with
   geodesic ordering, router partial labelling, sanitiser, API contract tests.
9. `scripts/query_latency.py` -> `reports/query_latency_<date>.md`: p50/p95 over 10
   representative queries per route (PostGIS, DuckDB hot tier) against the accepted
   Jan-Mar 2025 data.

## New dependencies (PRD-named tools)

`duckdb` (Python, pinned in `packages/core`), `geoalchemy2` only if SQLAlchemy Core
with explicit PostGIS functions proves insufficient, and `openapi-typescript` (web dev).
Each pinned in the lockfiles; ADR only if a tool outside the PRD is needed.

## Gate

Lint, types, unit and integration tests green locally and on the actual PR head; the
latency report produced by the script; gate report and advisor agreement before Stage 3.
