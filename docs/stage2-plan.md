# Stage 2 plan - query engine and API (reviewed 2026-10-09)

Status: **authorized, implementation starting**. The Stage 1 gate passed on session
`302412131a7c99fb` (docs/stage1-gate.md, ADR-0055) and `codex/stage-1` was squash-merged into
`main` as `91f7dd5` (PR #5; its tree equals the Stage 1 head `a4d6a01`). Stage 2 proceeds under
ADR-0039 and the owner's instruction of 2026-10-09. Scope: build prompt "Stage 2", PRD §8, §11.3,
§13.1-13.2, §17, §20. Branch `codex/stage-2` from `main` at `91f7dd5`; one pull request into
`main`. Decisions taken in this review are ADR-0056 to ADR-0060; the two marked "owner to confirm"
proceed under the stated assumption until the owner says otherwise.

## 0. What this review changed in the draft

The draft of 2026-10-08 predated stage1-v4 and the live acceptance. Corrections:

1. Migration number: the head is `0015_gdac_wiring`; Stage 2 adds `0016_query_access`, not 0010.
   The next ADR is 0056.
2. Catalogue model: a slot holds several active *parts* and at most one snapshot (ADR-0051); the
   acceptance catalogue has 206 parts and 0 snapshots. A reader keeps a part row only if its
   `(profile_id, profile_hash)` is in the slot's membership manifest (contract §7.2). The DuckDB
   compiler must apply that filter; an allow-list of object keys alone is wrong.
3. Two source populations exist (`argovis`, `gdac`, ADR-0052; GDAC uncertified). Stage 2 serves
   the `argovis` population only (ADR-0056).
4. The QC policy was a name without semantics. ADR-0057 defines `qc-policy-v1` on top of the
   contract's `core-good-v1` and the Argovis mode-to-variant rule.
5. Reference time: the acceptance environment is frozen at 2025-04-01T00:00:00Z. A router on the
   wall clock would put Jan-Mar 2025 outside every tier. The router reads the environment's
   reference time (ADR-0056).
6. Data for development and for the latency report: the dev stack holds no science. The only copy
   of the accepted Jan-Mar 2025 data is the preserved session's `db-1` and `minio-1` containers.
   ADR-0059 copies it into the dev project through a script; nothing attaches to the preserved
   containers and nothing is migrated on them.
7. Read-only access: `scripts/bootstrap_db.py` grants DML on every `app` table it does not know, so
   a bare `app.named_region` would become writable by `floatchat_app`. Stage 2 reads through views
   with explicit grants to a new `floatchat_query` login (ADR-0058).
8. Nearest-profile queries: `position` is `geometry(Point,4326)` with a GiST index; `ST_DWithin` on
   geography would not use it. Migration 0016 adds a geography index.
9. `/v1/floats`: `app.argo_float` has only `id`, `source`, `platform_number`. The endpoint returns
   identity plus statistics derived from profiles; PRD §6.1 metadata fields do not exist yet.
10. Partial coverage: Stage 2 labels missing slots and never creates chunks or jobs (§8.3 step 6
    and §8.4 are Stage 5).
11. DuckDB placement and bytes: in-process in the API, bounded, over a verified local cache of
    parts; no `httpfs`, no extension download, `enable_external_access=false` (ADR-0058).
12. Named regions: IHO Sea Areas v3 through the Marine Regions gazetteer, with recorded
    simplification and clipping to the Stage 1 envelope; "Indian Ocean" is the operational
    envelope, "Southern Indian Ocean" is a FloatChat definition (ADR-0060).
13. The dev Compose service set is asserted by `tests/test_compose.py`; Stage 2 adds environment
    variables and a cache volume to `api`, no service.

## 1. Inputs Stage 1 provides (as built)

- One `app.ingestion_environment` row per database (`one_environment_per_database`); runs carry
  `run_reference_time_utc`. The imported acceptance environment is mode `acceptance` with reference
  2025-04-01T00:00:00Z; a normal environment uses the latest completed run's reference.
- Science in PostgreSQL: `app.argo_float(id, source, platform_number)`, `app.argo_profile`
  (identity, `observed_at`, `observation_month`, `position` geometry 4326, `level_count`,
  `content_hash`, `scientific_content` jsonb, provenance FKs), `app.core_measurement` month-partitioned
  with per-variable original/adjusted values, QC, errors, units and data modes (contract §4, §6).
  Indexes: `profile_time(observed_at)`, `profile_position` GiST, owner-slot functional indexes.
  Acceptance population: 5,814 profiles, 4,144,346 levels, Jan-Mar 2025, all `source='argovis'`.
- Catalogue: `app.logical_partition_slot(environment_id, logical_key, observation_month, tile_key,
  slot_version, membership_manifest)`; `app.dataset_partition` parts and snapshots with
  `object_key = normalised/sha256/<sha256>.parquet`, `bytes`, `row_count`, `profile_count`, `kind`,
  `part_ordinal`, `versions`; view `app.committed_active_partitions` (committed intent, complete
  chunk, current slot version, status active). Manifest entries are
  `{"profile_id","hash","levels"}`. Acceptance: 206 parts, 301,781,882 bytes, 1-87 profiles per slot.
- Coverage receipts `app.coverage_receipt` (fetch and stored dispositions per slot and interval;
  64 verified-empty receipts per role in the acceptance run) and the pure resolver
  `floatchat_core.ingestion.coverage.resolve` (slot keys
  `argovis/core/YYYY-MM/<west>:<south>/indian-ocean-v1/argovis-core-v1/scientific-json-v2`).
- Parquet schema `core-parquet-v1`: `profile_id`, `source_profile_id`, `profile_hash`,
  `profile_content`, `canonical_level`, `level_index`, and per variable value, `_adjusted`, `_error`,
  `_original_error`, `_qc`, `_adjusted_qc`, `_qc_source`, `_adjusted_qc_source`, `_unit`,
  `_unit_source`, `_data_mode`, `_flags`. Never project `profile_content` or `canonical_level` in a
  query (they repeat the whole profile per level).
- Geometry `indian-ocean-v1`: `POLYGON((20 -60,120 -60,120 30,20 30,20 -60))`, planar `ST_Covers`
  membership, 10-degree tiles from (20,-60), no antimeridian crossing (contract §3.1).
- Roles: `floatchat_admin` (migrations), `floatchat_app` (API, Stage 0), `floatchat_ingestor`
  (workers). Byte identity of the two live runs is proven (ADR-0053, gate report), so the
  PostgreSQL rows and the Parquet parts hold the same values; Stage 2 tests use that.

## 2. Decisions (summary; full text in DECISIONS.md)

| ADR | Decision | Owner to confirm |
|---|---|---|
| 0056 | Branch from `main`; one environment, `argovis` population only; router reference time from the environment; partial labelling without jobs | no |
| 0057 | `qc-policy-v1`: `science_ready`, `mode_selected`, `raw`; aggregation unit `profile` or `measurement` | yes |
| 0058 | `floatchat_query` login over `app.query_*` views; SQLAlchemy Core compiler; DuckDB in-process over a verified local part cache with the manifest semi-join | no |
| 0059 | Stage 2 development dataset copied from session `302412131a7c99fb` by `scripts/stage2_dataset.py` | yes |
| 0060 | Named regions from IHO Sea Areas v3 (Marine Regions, CC-BY 4.0) with recorded simplification; operational Indian Ocean and Southern Indian Ocean | definitions |

## 3. Work items

In dependency order. Paths without a directory are under
`packages/core/src/floatchat_core/query/` (new package). Every item has tests (section 8).

### W1. Dataset and local environment (ADR-0059)

- `scripts/stage2_dataset.py import --session <id>`: starts only the session's `db-1` and `minio-1`
  containers, copies with `docker exec` `pg_dump --data-only` the tables `ingestion_environment`,
  `ingestion_run`, `ingestion_chunk`, `ingestion_attempt`, `raw_manifest`, `argo_float`,
  `argo_profile`, `core_measurement` (after creating the monthly partitions in the target with the
  same DDL `ensure_measurement_month` uses), `logical_partition_slot`, `publication_intent`,
  `dataset_partition`, `coverage_receipt`, extended by one `pg_constraint` query on the session
  database to the foreign-key closure of that list (a data-only restore fails on the first missing
  target); restores into the dev project's database as
  `floatchat_admin`; mirrors every object of `app.committed_active_partitions` into the dev bucket
  under the same key through a one-off container on the session network, verifying length and
  SHA-256 against the catalogue before and after the copy; stops the session containers; writes
  `reports/stage2-dataset-<session>.json` (source session and run ids, counts, dump SHA-256, object
  count and bytes, wall time). Refuses a target database that already holds an environment row.
  Never starts `acquire`, `process` or `supervisor`; never modifies the session.
- `scripts/dev.py`: generates `DB_QUERY_PASSWORD` for new configurations and appends missing new
  keys with generated values to an existing `.env` without rewriting existing keys (additive only).
- `infra/docker-compose.dev.yml`: `api` gains `QUERY_DATABASE_URL`, `QUERY_OBJECT_CACHE_DIR` and
  the named volume `query_cache`; `db-init` gains `DB_QUERY_PASSWORD`. Service set unchanged.
- `scripts/bootstrap_db.py`: creates `floatchat_query` when absent and unconditionally sets
  `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE` and the password (a migration run before the
  bootstrap leaves a `NOLOGIN` placeholder, see W2); adds `named_region` to the withheld set, which
  revokes everything from `floatchat_app` (it has no Stage 2 role). The bootstrap grant loop only
  handles relkinds `r`, `p` and `S`, so the `SELECT` grants on the `app.query_*` views made by the
  migration survive it. `tests/test_bootstrap.py` extended.

### W2. Migration `0016_query_access` (additive; ADR-0058, ADR-0060)

- Role settings: `ALTER ROLE floatchat_query SET default_transaction_read_only = on,
  statement_timeout = '15s', idle_in_transaction_session_timeout = '15s', lock_timeout = '2s',
  search_path = app, public`. Grants: `CONNECT`, `USAGE` on `app` and `public`, `SELECT` on the
  views below and on `app.named_region`; `REVOKE ALL ... FROM PUBLIC` on each new object. The
  migration creates the role `NOLOGIN` if absent so it applies on a bare database (same pattern as
  `floatchat_ingestor`); the bootstrap and the Stage 2 test fixture then set `LOGIN` and the
  password unconditionally, never only on creation.
- Views (owner `floatchat_admin`, invoker privileges not enabled, so the role needs nothing on the
  base tables): `app.query_float` (id, source, platform_number); `app.query_profile` (id, source,
  source_profile_id, float_id, platform_number, cycle_number, direction, observed_at,
  observation_month, position, level_count, content_hash, last_scientific_run_id);
  `app.query_measurement` (observation_month, profile_id, level_index, the 6 values, 6 QC codes,
  6 errors, 3 units, 3 data modes; no `*_flags`, no `*_source`); `app.query_environment`
  (environment id, name, mode, `reference_time` = `run_reference_time_utc` of the latest completed
  run); `app.query_slot`, `app.query_partition` (committed active parts/snapshots with object
  evidence), `app.query_coverage_receipt` (receipt joined to complete chunk, committed intent and
  slot, with the chunk tile) so `coverage.resolve` can run on the query role.
- `app.named_region(name, version, kind, source, source_id, citation, simplify_tolerance_deg,
  clipped, wkt, sha256, geometry geometry(MultiPolygon,4326), is_current)`, PK `(name, version)`.
  The Python migration wrapper verifies the SHA-256 of each WKT against the committed fixture
  before inserting (no pgcrypto dependency) and an integration test re-verifies the digests and
  `ST_IsValid` in the database. Rows come from
  `packages/core/src/floatchat_core/query/regions/named_regions.json`.
- Indexes: `profile_float_time ON app.argo_profile(float_id, observed_at)` and
  `profile_position_geog ON app.argo_profile USING gist((position::geography))`.
- Downgrade refused, like every Stage 1 migration.

### W3. `floatchat_core.query` package

- `plan.py`: `QueryPlan` (Pydantic v2, `extra="forbid"`, `plan_schema = "stage2-plan-v1"`) per
  section 4; `normalize()` returns the canonical plan and `plan_sha256`.
- `regions.py`: loads the committed fixture; `named_regions.json` carries name, version, kind,
  MRGID, citation, tolerance (0.05 degree) and minimum part area (50 km²), clipped flag, bbox,
  vertex counts, WKT, SHA-256; `scripts/build_named_regions.py` rebuilds it and the row block of
  migration 0016 from the gazetteer geometry endpoint through a disposable PostGIS container
  (network, owner-run, never in tests).
- `policy.py`: `qc-policy-v1` expressions per variable for SQL and DuckDB (ADR-0057), the depth
  predicate under the same policy, and the aggregation unit.
- `compile_sql.py`: SQLAlchemy Core over `Table` objects bound to the `app.query_*` views; column
  and function allow-lists; every value a bound parameter; geography resolved to
  `ST_Covers(ST_GeomFromText(:wkt, 4326), position)` for named regions and bboxes (two envelopes
  when a bbox crosses the antimeridian), `ST_DWithin(position::geography, ST_MakePoint(:lon,:lat)::geography, :radius_m)`
  with `ST_Distance` ordering for `nearest`; `source = 'argovis'` always bound; keyset pagination on
  `(observed_at, id)`; `LIMIT` from the plan bound by `QUERY_MAX_PAGE`.
- `catalogue.py`: `QueryCatalogue` on the query role: environment and reference time, tiles
  intersecting a geography (one PostGIS query over the 90 envelope tiles, cached per region version
  or bbox), `coverage.resolve` over the query views for (months x tiles), estimated levels and
  profiles from manifests, active parts per slot with object evidence.
- `cache.py`: content-addressed part cache `<dir>/<sha256>.parquet`; fill through boto3 from the
  configured bucket; verify length and SHA-256 before an atomic rename; LRU eviction at
  `QUERY_OBJECT_CACHE_BYTES`; never serves a file whose digest was not verified.
- `compile_duckdb.py`: per query a fresh connection configured
  `enable_external_access=false`, `autoinstall_known_extensions=false`,
  `autoload_known_extensions=false`, `memory_limit`, `threads`, then `lock_configuration=true`;
  registers `pyarrow.dataset.dataset([cached paths])` as `parts` (projection and filter pushdown by
  pyarrow, DuckDB never opens a path) and the slot manifests as an Arrow table `members`; the
  generated SQL is a fixed template with bound parameters and a semi-join on
  `(profile_id, profile_hash)`; per-query deadline through `interrupt()`.
- `router.py`: section 6. `sanitize.py`: section 7. `chart.py`: section 5.3. `provenance.py`:
  section 5.4. `errors.py`: the error-code registry (section 5.5). `limits.py`: `QueryLimits`
  settings with the defaults in section 4.4.

### W4. API (`apps/api`)

- Settings: `QUERY_DATABASE_URL` (secret), `QUERY_OBJECT_CACHE_DIR`, `QUERY_OBJECT_CACHE_BYTES`,
  `QUERY_*` limits; the existing `DATABASE_URL`, `REDIS_URL` and storage settings stay for
  readiness. Readiness adds a `query` probe (`SELECT 1` as `floatchat_query`).
- Routes (section 5): `GET /v1/catalog/parameters`, `GET /v1/catalog/coverage`, `GET /v1/floats`,
  `GET /v1/floats/{platform_number}`, `GET /v1/profiles`, `GET /v1/profiles/{profile_id}`,
  `POST /v1/query`. Correlation-ID middleware, error envelope, request-body limit (64 KiB JSON),
  response-size cap, no authentication (Stage 7), loopback binding unchanged.
- `apps/api/openapi.json` committed and tested against `app.openapi()`; FastAPI `/docs` stays on.
- Execution log line per query (correlation id, plan hash, route, timings, row counts, result
  hash) to stdout; no database write (the query role cannot write; audit tables are Stage 4/7).

### W5. TypeScript client (`apps/web`)

- `openapi-typescript` pinned as a dev dependency; `pnpm --filter @floatchat/web generate:api`
  writes `src/api/schema.d.ts` from `apps/api/openapi.json`; a hand-written `src/api/client.ts`
  typed `fetch` wrapper (no runtime dependency) with a Vitest test; ESLint ignores the generated
  file. CI regenerates and fails on a diff.

### W6. Tests and CI (section 8)

- `tests/stage2/` with its own `conftest.py` copying `deny_upstream` from `tests/stage1/conftest.py`
  and a `postgres` fixture following `tests/stage1/test_database.py` (pinned image, no host ports,
  migrations applied, seeded rows, `floatchat_query` connection).
- `.github/workflows`: the offline components job runs `tests/stage1 tests/stage2`; the `web` job
  runs the client generation and `git diff --exit-code apps/web/src/api`; `scripts/integration.py`
  adds a `GET /v1/catalog/parameters` check on the empty integration project.

### W7. Latency report (section 9)

`scripts/query_latency.py` writes `reports/query_latency_<date>.md` and `.json`.

### W8. Documents and gate

`docs/stage2-query-engine.md` (one compiled PostgreSQL statement and one DuckDB statement with
their plans explained, for the owner's gate checklist), `docs/stage2-gate.md` in the master-prompt
format, PROGRESS.md and DECISIONS.md updates, README quick start for the query API, `.env.example`.

## 4. Query plan `stage2-plan-v1`

### 4.1 Fields

```json
{
  "dataset": "core",
  "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-03-31T23:59:59Z"},
  "geography": {"kind": "named_region", "value": "Arabian Sea"},
  "depth_dbar": {"min": 0, "max": 100},
  "variables": ["temperature", "salinity"],
  "qc_policy": "science_ready",
  "operation": {"kind": "aggregate", "group_by": ["month"], "metrics": ["mean", "count"],
                "unit": "profile"},
  "presentation": {"kind": "line_chart"}
}
```

- `dataset`: `core` only (maps to `source='argovis'`, mapping `argovis-core-v1`).
- `time_range`: UTC ISO-8601 with offset; `start < end`; span at most 366 days; both inside the
  environment's committed months or the request is `partial`/`coverage_missing`.
- `geography`: `named_region {value}` (name of a current `app.named_region` row), `bbox
  {west, south, east, north}` in [-180,180] x [-90,90], `west > east` means an antimeridian crossing
  and compiles to two envelopes; 0-360 longitudes are rejected (`invalid_geography`), never wrapped;
  `point_radius {longitude, latitude, radius_km <= 2000}`.
- `depth_dbar`: `0 <= min < max <= 12000`, optional (default whole profile).
- `variables`: non-empty subset of `temperature`, `salinity`, `pressure`; `pressure` is implicit
  as the depth axis.
- `qc_policy`: `science_ready` (default), `mode_selected`, `raw` (ADR-0057; `raw` only with
  `operation.kind = profiles`).
- `operation`: `profiles {limit <= 1000, cursor}` (profile headers, optionally `levels: true` for a
  single profile elsewhere), `aggregate {group_by subset of month, day, profile, float, depth_bin
  {size in 10, 25, 50, 100}, region; metrics subset of mean, count, min, max, stddev, median;
  unit profile | measurement}`, `nearest {longitude, latitude, radius_km, k <= 100}`.
- `presentation`: `table` (default), `line_chart`, `scatter`, `profile_plot`, `ts_diagram`,
  `histogram {bins <= 200}`, `map`.

### 4.2 Rejections (HTTP 422, code `plan_invalid`, one `details[]` entry per violation)

Unknown field anywhere; unknown variable, region, metric, group key or presentation
(`unknown_variable`, `unknown_region`, `unknown_function`); `invalid_time_range`,
`invalid_depth_range`, `invalid_geography`; `unbounded_request` (profiles without limit or a
time range over the span limit, aggregate without `group_by` over more than one month);
`disallowed_format`; `cost_over_budget` (section 6 estimate above the route budgets);
`operation_variable_mismatch` (`ts_diagram` without both temperature and salinity, `profile_plot`
with `aggregate`, `median` with `unit = measurement` over DuckDB when unsupported, `nearest` with
`presentation` other than `table` or `map`).

### 4.3 Semantics

- Membership of a profile in a region or bbox: planar `ST_Covers` on geometry, the Stage 1 rule.
- Distance: geography (spheroid), metres in the response with `unit: "m"`.
- Depth filter and value selection follow the chosen policy (ADR-0057); a level whose
  policy-selected pressure is null is excluded from depth-filtered operations.
- `unit = profile`: metrics are computed per profile within the depth band first, then across
  profiles in the group; `count` is the number of profiles. `unit = measurement`: metrics over
  levels; `count` is the number of levels.
- Month keys are UTC calendar months; `day` likewise; `depth_bin` is `floor(pressure/size)*size`.

### 4.4 Limits (`QueryLimits`, environment-overridable, reported by `/v1/catalog/parameters`)

| Limit | Default |
|---|---|
| Request body | 64 KiB |
| Time span | 366 days |
| Page size | 1,000 (default 100) |
| Synchronous rows | 50,000 (PRD §3.1) |
| Response JSON | 8 MiB |
| PostgreSQL aggregate budget | 1,000,000 estimated levels |
| DuckDB aggregate budget | 5,000,000 estimated levels |
| Object bytes fetched per query | 512 MiB |
| Object fetch time per query | 120 s, 4 parallel downloads (separate from the query timeout) |
| Cache warm-up at start-up | on by default, 600 s, newest months first, never beyond the cache size |
| Nearest | radius 2,000 km, k 100 |
| Chart | 5,000 points per series, 20 series |
| Statement timeout | 15 s (role) and 10 s per query (API) |
| DuckDB | 512 MiB memory, 2 threads, 10 s |

## 5. API

### 5.1 Conventions (PRD §13.2)

Prefix `/v1`; JSON; UTC ISO-8601 with `Z`; `X-Correlation-ID` echoed when the client sends an ASCII
token of at most 64 characters, else generated (UUID4) and returned; stable error envelope
`{"error": {"code", "message", "details": [], "correlation_id"}}` with codes from `errors.py`
(section 5.5); keyset cursors (`cursor` opaque base64url of the last `(observed_at, id)`,
`next_cursor` null at the end, `invalid_cursor` on tampering); no raw SQL in any request or
response; no object keys, URIs, stack traces or SQL in errors. `Idempotency-Key`, `202`, `429` and
version fields are not needed by Stage 2's read-only endpoints and arrive with Stages 5 and 7.

### 5.2 Endpoints

- `GET /v1/catalog/parameters`: variables (name, unit, description, which columns Stage 1 stores),
  QC policies (name, version, description), named regions (name, version, kind, source, MRGID,
  citation, bbox, SHA-256, clipped), operations, presentations, limits, `plan_schema`.
- `GET /v1/catalog/coverage?start&end&region|bbox`: environment (name, mode, `reference_time`),
  hot and window intervals (labels), months, per month and tile: `covered`, `empty_verified`,
  `missing`; profiles and levels from manifests; active part counts. The same block is embedded in
  every `/v1/query` response.
- `GET /v1/floats?region|bbox&start&end&cursor&limit`: `platform_number`, `source`,
  `profile_count`, `first_observed_at`, `last_observed_at`, `last_position`, cycle range.
- `GET /v1/floats/{platform_number}`: the same plus a bounded trajectory (newest first, cursor,
  at most 1,000 points of `observed_at`, longitude, latitude, cycle, `profile_id`).
- `GET /v1/profiles?region|bbox|point_radius&start&end&platform_number&direction&cursor&limit`:
  headers (`id`, `source_profile_id`, `platform_number`, `cycle_number`, `direction`,
  `observed_at`, longitude, latitude, `level_count`, per-variable data mode).
- `GET /v1/profiles/{profile_id}?qc_policy&raw`: header plus levels (policy-selected `pressure`,
  `temperature`, `salinity` with QC and mode; `raw=true` adds original, adjusted and error
  columns), at most 10,000 levels (the schema bound).
- `POST /v1/query`: `{plan, result {columns [name, type, unit], rows}, chart?, coverage, partial,
  missing [slots], execution {source: postgresql|duckdb, elapsed_ms, rows}, provenance,
  interpretation}`.

### 5.3 Chart contract (PRD §11.3)

`{type, encodings {x, y, series, color?} each {field, label, unit}, axis {x, y {reversed}},
series [names], missing_value_policy: "null", aggregation: text, data {points | null},
provenance_ref}` plus `plotly {traces, layout}` restricted to an allow-list of trace types
(`scatter`, `scattergl`, `histogram`, `scattergeo`) and keys. `profile_plot` reverses the pressure
axis; `ts_diagram` plots salinity against temperature per profile; `map` emits bounded points.
The browser never receives executable content.

### 5.4 Provenance (PRD §17)

`environment {id, name, mode, reference_time}`, `source: argovis`, versions (`mapping
argovis-core-v1`, `hash scientific-json-v2`, `qc core-good-v1`, `qc_policy qc-policy-v1/<name>`,
`geometry indian-ocean-v1`, `schema core-parquet-v1`, `plan_schema stage2-plan-v1`, region name,
version and SHA-256), requested and actual coverage (months, slots covered and missing, profiles,
levels), execution (route, partition ids and SHA-256s for DuckDB, latest `last_scientific_run_id`
for PostgreSQL, elapsed), application commit, `result_sha256`, transformation description.

### 5.5 Error codes

`plan_invalid`, `unknown_variable`, `unknown_region`, `unknown_function`, `invalid_time_range`,
`invalid_depth_range`, `invalid_geography`, `unbounded_request`, `disallowed_format`,
`cost_over_budget`, `operation_variable_mismatch`, `coverage_missing` (404-like, HTTP 422),
`not_found` (404), `invalid_cursor` (400), `payload_too_large` (413), `result_too_large` (422),
`statement_timeout` (504), `execution_failed` (502 for object-store or DuckDB failures), and
`internal_error` (500). A test asserts the registry is closed and every raised code is in it.

## 6. Execution routes and the coverage router (PRD §8.3)

1. Validate and normalize the plan; hash it.
2. Resolve geography to a geometry (region WKT by name and current version; bbox envelopes;
   point-radius bbox prefilter) and to the envelope tiles it intersects.
3. Months intersecting `time_range`; months outside the environment's committed months are missing.
4. `coverage.resolve` over the query views for (months x tiles): per slot `covered` (fetch coverage
   proven and active parts or a verified-empty receipt), else `missing`.
5. Estimate: levels and profiles from the manifests of covered slots.
6. Route: `profiles`, `nearest` and single-profile reads use PostgreSQL. `aggregate` uses
   PostgreSQL when the estimate is within the PostgreSQL budget, else DuckDB when within the
   DuckDB budget and every covered slot's parts are cached or fetchable within the byte budget,
   else `cost_over_budget`. The tier labels (hot: `[reference - 3 months, reference)`, window:
   `[reference - 12 months, reference)`) are reported, not used for routing: Stage 1 keeps all
   accepted science in both stores (no destructive retention), so both routes see the same rows.
7. Execute under the deadline; sanitise; `partial = true` when any requested slot is missing, with
   the missing slots listed; `coverage_missing` when nothing is covered. No chunk or job is created.
8. Combine DuckDB part rows through the manifest semi-join (a replaced or moved profile is excluded
   by the manifest, duplicates of an unchanged `(profile_id, profile_hash)` pair are identical and
   collapsed by `DISTINCT` on the key before aggregation).
9. Log the execution record (section W4).

## 7. Security bounds (PRD §8.5, §16.3, §16.4)

Parameterised SQL only; identifiers from allow-lists; `text()` and f-string SQL forbidden in the
query package by a test; read-only role with statement timeout and no file, extension or
administrative privilege; DuckDB with external access disabled, no extensions, memory and thread
limits, configuration locked; object keys only from the catalogue and matched against
`^normalised/sha256/[0-9a-f]{64}\.parquet$`; object bytes verified against the catalogue before use;
request-body, page, row, byte and chart-cardinality limits; result sanitiser checks expected
columns and types, finite values (non-finite become null and are counted), no internal URI,
object key, credential, SQL or stack trace, units and provenance present.

## 8. Tests

Unit (`tests/stage2`, offline, upstream denied):
- Plan validation: every rejection in 4.2, unknown fields at every level, boundary values,
  antimeridian split, 0-360 rejection, normalization idempotence and hash stability.
- Compiler allow-lists: every plan field fuzzed with SQL fragments and identifiers (`'; DROP`,
  `--`, `$$`, unicode homoglyphs) compiles to the fixed templates with values only in parameters;
  the compiled statement text never contains a request string.
- QC policy expressions on fixture rows (R, A, D modes; QC 1/2/3/4/9; nulls); depth predicate.
- Coverage interval arithmetic (reuses `coverage.resolve` with synthetic receipts and parts).
- Router decisions and budgets; partial labelling; reference-time tiers.
- Sanitiser: NaN/Inf, oversized results, forbidden strings, missing provenance, chart cardinality.
- Chart compiler for every presentation and mismatch.
- Named regions: fixture SHA-256s, WKT validity, deterministic point membership (one inside and one
  outside point per region), bbox agreement with the gazetteer record.
- Error registry closed; correlation-ID echo and generation; cursor round trip and tampering.
- OpenAPI equals the committed file; the TypeScript client is regenerated without a diff.
- DuckDB: a part file outside the allow-list is never opened (the dataset gets only cached paths);
  external access and extension loading are disabled; manifest filtering excludes a replaced
  profile present in an older part; interrupt on deadline.

Integration (`-m integration`, pinned PostGIS image, no host ports):
- Migration 0016 applies on a fresh database and twice (idempotent); `floatchat_query` cannot
  `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `COPY TO PROGRAM` or read `app.ingestion_run`; statement
  timeout fires; region rows verify.
- Seeded profiles (reusing the Stage 1 seed pattern): `ST_Covers` membership at region edges,
  `nearest` ordering by geodesic distance with the geography index used (EXPLAIN contains the
  index), keyset pagination stability under insertion, `/v1/floats` statistics, a seeded `gdac`
  profile never appears, PostgreSQL and DuckDB aggregates agree on the same seeded data within
  1e-9 relative.
- API contract tests through `TestClient` for every endpoint, error envelope and headers.

## 9. Latency report

`scripts/query_latency.py --base-url http://127.0.0.1:8000 --runs 20` against the dev project
loaded by W1: ten queries per route chosen by estimated cost so the router selects the route
(PostgreSQL: four profile listings, three nearest, three small aggregates; DuckDB: ten aggregates
up to the whole-envelope quarter), each measured cold (empty object cache, API restarted) and warm,
p50 and p95 over the runs, the route asserted from `execution.source`. The report records commit,
dataset manifest digest and source session, host and container limits, and compares to PRD §3.1
(metadata p95 under 2 s, aggregate p95 under 5 s). Numbers in PROGRESS.md and the gate report are
copied from this file only.

## 10. Dependencies

`duckdb` 1.5.x pinned in `packages/core` (1.5.6 current on 2026-10-09); `sqlalchemy==2.0.48`
added to `packages/core` (already pinned in `apps/api`); `pyarrow` already present;
`openapi-typescript` 7.13.0 pinned in `apps/web` dev dependencies. No `geoalchemy2`, `shapely`,
`psycopg_pool` or Plotly Python package. Lockfiles updated with `uv lock` and
`pnpm install --lockfile-only`; no other new dependency without an ADR.

## 11. Execution order and delegation

W1 (dataset copy, owner to confirm ADR-0059) can start immediately and runs in the main session
because it touches preserved evidence. W2 and W3 `plan.py`, `policy.py`, `router.py`,
`catalogue.py`, `compile_duckdb.py` and the migration stay in the main session (contract and
scientific decisions). Delegable with full specifications: `regions.py` and the fixture builder,
`compile_sql.py` templates once the view contract is fixed, `errors.py`, `sanitize.py`, `chart.py`,
the API route handlers, the TypeScript client wiring, the unit-test files from section 8 and the
latency script (`sonnet-worker`); mechanical fixture and documentation updates (`haiku-worker`).
Commits are small and conventional, without Claude attribution (memory rule).

## 12. Gate

Lint, strict mypy, unit and integration tests green locally and on the pull-request head; the
latency report produced by the script from the W1 dataset; `apps/api/openapi.json` and the
generated client in sync; `docs/stage2-gate.md` in the master-prompt format with measured numbers
from `reports/`; advisor agreement recorded in PROGRESS.md before Stage 3.

## 13. Needs from Aayush

1. Confirm `qc-policy-v1` (ADR-0057) or state the preferred variant and QC selection.
2. Confirm the copy of session `302412131a7c99fb` into the dev project (ADR-0059); the alternative
   is a fresh live acceptance run on the Argovis key (about 23 minutes).
3. Confirm the Indian Ocean and Southern Indian Ocean definitions (ADR-0060).

## 14. Out of scope

Authentication, roles and quotas (Stage 7); jobs, exports and missing-data fetches (Stage 5);
chat and RAG (Stage 4); dashboard rendering (Stage 3); BGC; the GDAC population; cross-source
identity; destructive retention; any change to Stage 1 science, hashes or the ingestion path.
