# Stage 3 plan - web dashboard (reviewed 2026-10-09)

Status: **authorized, implementation starting** (owner instruction 2026-10-09: Stage 2 and the
Stage 2 fixes are accepted; build Stage 3 on them; decide open questions without further
approval). Scope: build prompt "Stage 3", PRD §2.1, §5.1, §5.10, §11.3, §14, §17, §20. Branch
`codex/stage-3` from `codex/stage-2-fixes` at `5cf262e`; one pull request into `main`.
Decisions taken in this review are ADR-0061 to ADR-0065.

## 0. What this review changed in the gate's proposed plan

The Stage 2 gate proposed: map from `/v1/floats` and `/v1/profiles`, profile and T-S views from
`/v1/profiles/{id}`, time series and histograms from `POST /v1/query`, a provenance panel,
URL-bound filters, TanStack Query over the generated client, Playwright against the dev
dataset, and three decisions (library pins, the Vite proxy, the attribution footer). Reviewing
that against the merged code and the build prompt changed the following:

1. **Branch base.** The branch starts from `codex/stage-2-fixes` (PR #7, open), not `main`,
   because the dashboard runs against the warm-up and cold-fill retry that branch adds. The pull
   request targets `main`; after PR #7's squash merge the branch is rebased onto `main` so the
   Stage 2 fix commits drop out of the diff (same reasoning as ADR-0056). Branch name follows
   the `codex/stage-N` convention rather than the literal "Stage3".
2. **E2E data in CI.** The CI `integration` job already starts the full dev stack and runs the
   Playwright suite, but on an empty database; the Stage 3 scenario (Arabian Sea, January 2025,
   0-100 dbar, map points and a profile chart) needs science rows and a catalogue. The Stage 2
   seed (`tests/stage2/conftest.py`: environment, run, chunk, floats, profiles, levels, slots,
   parts, receipts) moves to a module the API image ships, and the integration script seeds the
   disposable project with it after the existing empty-database checks (ADR-0063). Acceptance
   against the imported Stage 1 dataset is a separate local Playwright run whose screenshots and
   report go under `reports/`.
3. **Generated types are mostly `unknown`.** Every nested object in the Stage 2 responses
   (`environment`, `profile`, `float`, `coverage`, `chart`, `provenance`) is declared
   `additionalProperties: true` without fields, so "use the generated client" would bind the
   dashboard to `{[k: string]: unknown}`. Stage 3 tightens the Pydantic response models for the
   stable shapes (the `describe()` outputs, the chart contract, the provenance top level; the
   Plotly traces and layout stay loose) and regenerates `openapi.json` and `schema.d.ts`
   (ADR-0064). This is what PRD §5.1 means by generated types keeping the contracts aligned.
4. **Provenance on every result.** Only `POST /v1/query` carries a provenance object; the four
   read endpoints carry none. The build prompt says "provenance panel (§17) on every result", so
   the reads gain a reduced provenance object built without a coverage resolution (ADR-0064).
5. **Source and ingestion timestamps.** The coverage panel must show them (build prompt scope
   4), but the API exposes only the reference time and run identifiers. Migration
   `0017_query_environment_timestamps` extends the `app.query_environment` view (additive
   `CREATE OR REPLACE VIEW`, new columns at the end) with the latest completed run's id, its
   actual creation time (ingestion timestamp) and the earliest and latest `raw_manifest.retrieved_at`
   of that run (source retrieval window); `EnvironmentInfo.describe()` reports them (ADR-0064).
6. **`application_commit` is "unknown"** on the dev stack. The provenance panel displays it, so
   Compose passes `APPLICATION_COMMIT` to the `api` service and `scripts/dev.py` and
   `scripts/integration.py` set it from `git rev-parse HEAD` when Git is available (ADR-0064).
7. **Library majors.** React Router 8 requires React 19.2.7 and the repository pins 19.2.0;
   Stage 3 pins `react-router` 7.18.4 (the declarative API the app needs is identical) and leaves
   React alone. MapLibre 6 is ESM-only and WebGL2-only; headless Chromium on this host and on
   GitHub runners provides WebGL2 through SwiftShader (probed 2026-10-09). Plotly 4 removed the
   Mapbox traces and changed colour parsing; the cartesian bundle covers every chart kind the
   contract emits except `scattergeo`, which the dashboard renders with MapLibre (ADR-0061).
8. **Basemap without network.** Tests never call external services, and the map must work
   offline in CI and in the demonstration, so the basemap is a Natural Earth land layer bundled
   with the app, not a tile server (ADR-0062).
9. **One unit per chart.** The contract's `line_chart` puts `temperature_mean`, `salinity_mean`
   and the counts in one spec. A dual-axis chart is not acceptable (§14.5 units on every axis;
   the data-visualisation rule of one axis), so the dashboard renders one panel per unit group
   from the same spec (ADR-0065).
10. **Map payload bound.** `/v1/profiles` pages at 1,000 and the envelope quarter holds 5,814
    profiles. The map follows at most five pages (5,000 points) and labels "showing N of more"
    when truncated (PRD §14.4; ADR-0062).
11. **Stage 0 browser check kept.** `e2e/scaffold.spec.ts` asserts the readiness status text and
    runs in the integration job; the app shell keeps a readiness indicator and the spec is
    adapted to the new routes (`/` redirects to `/dashboard`).
12. **Cold Vite in the integration stack.** The `web` service runs the Vite dev server; its first
    request pre-bundles MapLibre and Plotly. `optimizeDeps.include` lists them and the e2e
    budgets in `scripts/integration.py` and `playwright.config.ts` are raised.

## 1. Inputs Stage 2 provides (as built)

- Endpoints (`apps/api/openapi.json`, PR #6 and #7): `GET /v1/catalog/parameters` (variables with
  units and descriptions, QC policies, named regions with bbox and citation, limits),
  `GET /v1/catalog/coverage?start&end&region|bbox` (environment, geography, coverage summary,
  per-slot states `covered`, `empty_verified`, `missing` with gaps, profiles and levels from
  manifests), `GET /v1/floats` (identity and profile-derived statistics, keyset cursor),
  `GET /v1/floats/{platform_number}` (summary plus a bounded trajectory newest first),
  `GET /v1/profiles` (headers, filters `start`, `end`, `region|bbox`, `platform_number`,
  `depth_min`, `depth_max`, `qc_policy`, cursor, `limit` up to 1,000),
  `GET /v1/profiles/{id}?qc_policy&depth_min&depth_max` (header plus policy-selected levels with
  QC, data mode and unit per variable, at most 10,000 levels), `POST /v1/query` (the
  `stage2-plan-v1` plan; `result`, `chart`, `coverage`, `partial`, `missing`, `execution`,
  `interpretation`, `provenance`).
- Chart contract (`chart.py`): `type` in `line_chart`, `scatter`, `histogram`, `map`,
  `profile_plot`, `ts_diagram`; `encodings {x, y, series}` and `axis {x, y}` each
  `{field, label, unit, reversed}`; `series [names]`; `missing_value_policy "null"`;
  `aggregation` text; `data {inline, points, url}`; `provenance_ref`; `plotly {traces, layout}`
  with traces restricted to `scatter`, `scattergl`, `histogram`, `scattergeo` and the keys
  `type, mode, name, x, y, lon, lat, text, nbinsx`. Bounds: 5,000 points per series, 20 series,
  200 histogram bins; profile charts need the `profiles` operation with `limit` at most 20.
- Provenance (`provenance.py`): `source`, `environment`, `versions` (mapping, hash, qc,
  qc_policy, geometry, schema, plan_schema, region), `geography`, `coverage`, `execution`,
  `plan_sha256`, `result_sha256`, `application_commit`, `transformation`, `attribution`
  (Argo DOI 10.17882/42182; Argovis DOI 10.1175/JTECH-D-19-0041.1).
- Units: temperature `degree_C`, salinity `1` (practical salinity, dimensionless), pressure
  `dbar`; the parameter catalogue carries the human description of each.
- Dev dataset (ADR-0059, report `reports/stage2-dataset-302412131a7c99fb.json`): 5,814 profiles,
  4,144,346 levels, Jan-Mar 2025, reference time 2025-04-01T00:00:00Z; Arabian Sea holds 425
  profiles from 53 floats in the quarter, 132 of them in January 2025 with levels in 0-100 dbar.
- Web scaffold: Vite 7, React 19.2, TypeScript 5.9 strict, ESLint 9, Prettier, Vitest 4 with
  jsdom and Testing Library, Playwright 1.58 (Chromium installed), the generated
  `src/api/schema.d.ts` and the typed `client.ts` (`listFloats`, `getFloat`, `listProfiles`,
  `getProfile`, `getCoverage`, `getCatalogParameters`, `postQuery`, `ApiError`). Vite proxies
  `/v1` to the API (`API_PROXY_TARGET`, `http://api:8000` in Compose).
- CI (`.github/workflows/ci.yml`): `web` job regenerates and diffs the client, lints, type-checks,
  tests and builds; `integration` job runs `scripts/integration.py` (Docker acceptance ending in
  `pnpm test:e2e` against the `web` service); the `docker` job builds the web image target
  `build`. `tests/test_compose.py` pins the Compose service set.

## 2. Decisions (summary; full text in DECISIONS.md)

| ADR | Decision |
|---|---|
| 0061 | Stage 3 scope and branch; routes and stubs; pins: react-router 7.18.4, @tanstack/react-query 5.104.1, maplibre-gl 6.13.0, plotly.js-cartesian-dist-min 4.1.2 (+ @types/plotly.js); no new service, no new framework |
| 0062 | Offline basemap from Natural Earth (public domain) clipped to the Indian Ocean envelope; MapLibre built-in clustering; a bounded point cap of 5,000 with a truncation label; the `map` chart kind rendered by MapLibre; a list view beside the map as the non-canvas path |
| 0063 | Dashboard test data: the Stage 2 seed becomes `scripts/science_seed.py` shipped in the API image; the integration project is seeded (database rows through `db-init`, objects through `api`) before the e2e; Stage 3 adds January Arabian Sea rows to the seed used by the Docker project only; local acceptance on the imported dataset with screenshots under `reports/` |
| 0064 | API additions for the dashboard: typed response models (additive, `extra="allow"`), provenance on the read endpoints, migration 0017 (`query_environment` timestamps), `APPLICATION_COMMIT` wiring |
| 0065 | Chart rendering: one unit per panel, the validated reference palette in fixed slot order, units on every axis, a table view for every chart, no executable content from the server |

## 3. Work items

In dependency order. Web paths are under `apps/web/src/`. Every item has tests (section 6).

### W1. API additions (ADR-0064)

- `apps/api/src/floatchat_api/query_api.py`: Pydantic models `Environment` (id, name, mode,
  reference_time, completed_runs, hot_tier, postgresql_window, latest_run, ingested_at,
  source_retrieved), `Interval` (start, end), `GeographyInfo` (kind, name, version, sha256,
  clipped, boxes, longitude, latitude, radius_km; optional fields), `QcPolicy` (name, version,
  description), `SlotCoverage`, `CoverageSummary`, `Column`, `ChartAxis`, `ChartSpec`
  (type, encodings, axis, series, missing_value_policy, aggregation, data, provenance_ref,
  plotly as a loose object), `Provenance` (source, environment, versions, geography,
  coverage optional, execution, plan_sha256 optional, result_sha256, application_commit,
  transformation, attribution). Every model allows extra keys so later stages stay additive.
  `CollectionResponse`, `FloatResponse`, `ProfileResponse`, `CoverageResponse` and
  `QueryResponse` reference them; the reads gain `provenance: Provenance`.
- `packages/core/src/floatchat_core/query/provenance.py`: `build_read(...)` for the reads:
  environment, source, versions (no plan schema or QC policy where the read has none), geography
  (null for an unfiltered float listing), execution (`source: postgresql`, `run_ids`, `rows`),
  `result_sha256`, application commit, transformation text, attribution. `router.py` attaches it
  in `floats`, `float_detail`, `profiles` and `profile`.
- `infra/migrations/versions/0017_query_environment_timestamps.{py,sql}`: `CREATE OR REPLACE VIEW
  app.query_environment` adding `latest_run_id`, `ingested_at`
  (`created_at_actual_utc` of the latest completed run), `source_retrieved_from` and
  `source_retrieved_to` (min and max `raw_manifest.retrieved_at` of that run); grants unchanged
  (the view keeps its ACL). Downgrade refused, as for 0016. `catalogue.py` reads the new columns;
  `EnvironmentInfo.describe()` adds `latest_run`, `ingested_at` and `source_retrieved`.
- `floatchat_core.config.Settings.application_commit` already exists; Compose `api` gets
  `APPLICATION_COMMIT: ${APPLICATION_COMMIT:-unknown}`; `scripts/dev.py` and
  `scripts/integration.py` export it from `git rev-parse HEAD` when available.
- Regenerate `apps/api/openapi.json` and `apps/web/src/api/schema.d.ts`; update the contract-test
  doubles in `tests/stage2/test_api.py` to the typed shapes; `client.ts` exports the new named
  types.

### W2. Seed module and CI data (ADR-0063)

- `scripts/science_seed.py`: the Stage 2 constants and builders (`SEED`, `PROFILES`, `LEVELS`,
  `profile_rows`, `catalogue_rows`, `part_table`, `parquet_bytes`) moved from the conftest, plus
  `STAGE3_PROFILES` (two more January 2025 Arabian Sea profiles of float `5900001` so the
  scenario shows several map points and a trajectory, and one float `5900004` with a single
  January profile at a different position). `tests/stage2/conftest.py` imports the Stage 2 list
  unchanged. Entry points: `python scripts/science_seed.py database` (needs
  `DATABASE_ADMIN_URL`; refuses a database that already holds an environment row; creates the
  monthly partitions; inserts the rows) and `python scripts/science_seed.py objects` (needs the
  storage settings; uploads the parts under their catalogue keys and verifies length and SHA-256).
- `infra/docker/api.Dockerfile` copies `scripts/science_seed.py`.
- `scripts/integration.py`: after the Stage 2 empty-database checks and the first `db-init`,
  runs the database step through `db-init` and the objects step through `api`, asserts
  `/v1/profiles?region=Arabian Sea&start=2025-01-01&end=2025-02-01&depth_max=100` returns the
  seeded profiles, and later runs the Playwright suite with a raised budget (300 s).

### W3. Application shell, routing, state (ADR-0061)

- Dependencies: `react-router` 7.18.4, `@tanstack/react-query` 5.104.1, `maplibre-gl` 6.13.0,
  `plotly.js-cartesian-dist-min` 4.1.2, `@types/plotly.js` 3.0.15, `@types/geojson` 7946.0.16.
- `app/`: `App.tsx` (providers: `QueryClientProvider`, `BrowserRouter`; layout with header,
  navigation, readiness indicator, attribution footer; error boundary), `routes.tsx`
  (`/` -> `/dashboard`; `/dashboard`, `/explore/map`, `/explore/profiles`; stubs for `/login`,
  `/chat`, `/jobs`, `/forecasts`, `/settings`, `/admin/usage`, `/admin/ingestion` naming the
  stage that delivers them), `Stub.tsx`, `ErrorBoundary.tsx`.
- `explorer/filters.ts`: the filter model (`region`, `start`, `end`, `depthMin`, `depthMax`,
  `qc`, `platform`, `profile`) parsed from and written to URL search parameters with defaults
  from the environment (hot tier) and validation; `useFilters()` over `useSearchParams`.
  `explorer/FilterBar.tsx`: region select (from the parameter catalogue), month-aware date
  inputs, depth inputs, QC policy select, float input; every control labelled; changes write the
  URL.
- `api/hooks.ts`: TanStack Query hooks over `client.ts` (`useParameters`, `useCoverage`,
  `useFloats`, `useFloat`, `useProfiles` with bounded page following, `useProfile`, `useQuery`),
  stable keys from the filter model, `ApiError` surfaced with code and correlation id.
- `components/`: `Panel`, `DataTable` (bounded, with units in headers), `StatusMessage`
  (loading, empty, error with correlation id), `VisuallyHidden`, `SkipLink`.

### W4. Map (ADR-0062)

- `map/land.json`: Natural Earth 1:50m land polygons clipped to 10-130E, 65S-35N by
  `scripts/build_basemap.py` (run once from a downloaded copy; the script records the source URL,
  SHA-256 and the clip box in the JSON's `properties`; tests never fetch).
- `map/style.ts`: a MapLibre style with a sea-coloured background, the land fill and outline,
  a graticule every 10 degrees with labels, no glyphs or sprites from the network.
- `explorer/MapView.tsx`: MapLibre map over the style; a GeoJSON source of profile points with
  `cluster: true` (cluster circles with counts, unclustered circles coloured by month with a
  shape-free status: month is also in the hover and in the list); the selected float's
  trajectory as a line plus points ordered by time; the region polygon outline from the catalogue
  bbox; click on a point writes `profile=` (and `platform=`) to the URL; keyboard: the list
  beside the map (`ProfileList.tsx`, a table of the plotted profiles with buttons) selects the
  same way, so no interaction needs the canvas. The map reports "N profiles plotted" (and
  "showing N of more" when the page cap truncates) in a live region. On MapLibre `error` (no
  WebGL) the list stays and the canvas shows the reason.

### W5. Charts (ADR-0065)

- `charts/plotly.ts`: the Plotly loader (`plotly.js-cartesian-dist-min` through a module
  declaration typed by `@types/plotly.js`); `charts/Plot.tsx`: a `useEffect` wrapper around
  `Plotly.react` with resize handling and `purge` on unmount; `charts/spec.ts`: pure translation
  of the chart contract into Plotly figures: allow-listed trace keys only, one figure per unit
  group, axis titles with units, reversed pressure axis, fixed palette slots, marker size and
  line width per the mark rules, hover template with units; `charts/palette.ts` (reference
  categorical slots, validated); `charts/ChartPanel.tsx`: figure plus a table view toggle and
  the aggregation text.
- `explorer/ProfileCharts.tsx`: for the selected profile (`/v1/profiles/{id}`), temperature
  versus pressure and salinity versus pressure (pressure increasing downwards) and the T-S
  diagram, plus QC and data-mode counts; `explorer/ProfilesView.tsx` (`/explore/profiles`):
  the filter bar, the profile list for the filters, the selected profile's charts, the
  multi-profile T-S diagram through `POST /v1/query` (`profiles` operation, `ts_diagram`, at most
  20 profiles).
- `dashboard/Dashboard.tsx` (`/dashboard`): the filter bar, the coverage panel, a map summary,
  the monthly time series (`aggregate` by month, mean and count, `line_chart`; one panel per
  variable) and the distribution view (`aggregate` histogram of the selected variable, bins
  bounded), the provenance panel of each result.

### W6. Coverage and provenance panels

- `catalog/CoveragePanel.tsx`: from `/v1/catalog/coverage` for the filters: requested range,
  region (name, version, clipped flag), profile and level counts from manifests, slots covered,
  verified empty and missing with a list of missing months and tiles, hot tier and PostgreSQL
  window labels, reference time, ingestion timestamp and source retrieval window (W1), the
  completed run count; `partial` shown as a non-colour badge.
- `provenance/ProvenancePanel.tsx`: used on every result: source and attribution, environment,
  versions, geography, coverage summary (when present), execution (route, elapsed, rows, run
  ids or partitions), plan and result digests, application commit, transformation; a copy
  button for the JSON.

### W7. Accessibility and attribution (PRD §14.5, §3.2)

- Keyboard reachable controls and list rows; visible focus ring tokens; skip link; landmarks;
  live regions for loading and counts; units on every axis and table header; the palette slots
  validated with the data-visualisation validator in light mode; month and QC state never by
  colour alone; UTC stated beside every timestamp; longitude convention stated on the map.
- Footer: Argo citation and DOI, Argovis citation, Marine Regions (IHO Sea Areas v3, CC-BY 4.0),
  Natural Earth (public domain).

### W8. Tests and CI (section 6)

### W9. Local acceptance on the imported dataset

- `scripts/stage3_acceptance.py`: runs the Playwright suite against the dev stack (full
  dataset) with screenshots of the dashboard, the map and the profile view, and writes
  `reports/stage3-acceptance-<date>.json` (dataset identity from `/v1/catalog/coverage`, the
  counts shown, timings) and the PNGs under `reports/stage3-acceptance-<date>/`.

### W10. Documents and gate

- `README.md` (dashboard section, screenshots), `PROGRESS.md`, `DECISIONS.md`,
  `docs/stage3-gate.md` in the gate format.

## 4. URL state (PRD §14.3)

`/dashboard?region=Arabian%20Sea&start=2025-01-01&end=2025-02-01&depth_min=0&depth_max=100&qc=science_ready`
`/explore/map?...&platform=5900001&profile=<uuid>`
`/explore/profiles?...&profile=<uuid>`

- Dates are UTC calendar days (`YYYY-MM-DD`); `end` is exclusive and sent as `T00:00:00Z`.
- Defaults when absent: the environment's hot tier (from `/v1/catalog/coverage` without
  parameters), region `Indian Ocean`, depth unset, `qc=science_ready`.
- Invalid values are reported beside the control and the request is not sent.
- TanStack Query owns server state; component state owns hover and the table toggle; nothing
  server-side is duplicated into a global store.

## 5. Plans the dashboard sends (`stage2-plan-v1`)

| View | Plan |
|---|---|
| Time series | `aggregate`, `group_by: ["month"]` (or `["day"]` when the range is at most 31 days), `metrics: ["mean","count"]`, `unit: "profile"`, variables temperature and salinity, `line_chart` |
| Distribution | `aggregate`, `group_by: ["profile"]` (one value per profile in the depth band), `metrics: ["mean"]`, one variable, `histogram` with `bins` 40 |
| Multi-profile T-S | `profiles`, `limit: 20`, variables temperature, salinity, pressure, `ts_diagram` |
| Single profile | `GET /v1/profiles/{id}` (no plan) |

The `map` chart kind is never requested; the map reads `/v1/profiles` directly.

## 6. Tests

- Vitest and Testing Library (`src/**/*.test.tsx`), with MapLibre and Plotly mocked (jsdom has
  no WebGL and no layout): filter model round trips and validation; hooks' query keys and the
  page-following cap; `charts/spec.ts` (unit grouping, allow-listed keys, reversed axis, palette
  order stability when a series disappears, units in titles); coverage panel rendering from a
  recorded `/v1/catalog/coverage` response; provenance panel from a recorded `/v1/query`
  response; profile charts from a recorded `/v1/profiles/{id}` response; the dashboard and the
  profile view with a mocked client (loading, empty, error with correlation id); route stubs.
  Recorded responses live in `src/test/fixtures/` and are captured from the dev API by
  `scripts/capture_web_fixtures.py` (identifiers kept, nothing invented).
- Playwright (`e2e/dashboard.spec.ts`): open `/dashboard`, set region Arabian Sea, January
  2025, depth 0-100, assert the URL carries the parameters, see the live count of plotted
  profiles on `/explore/map` and at least one point feature in the source (through
  `page.evaluate` on the exposed map handle), open `/explore/profiles`, select the first listed
  profile, see the temperature-pressure chart container with its axis titles and the table view
  with at least one level row, and the provenance panel. `e2e/scaffold.spec.ts` adapted (the
  readiness status in the shell).
- Python: `tests/stage2/test_api.py` doubles updated for the typed models; new tests for
  `build_read`, the 0017 view (integration suite: `ingested_at` and the retrieval window on the
  seeded server), the seed module (deterministic part bytes, refusal on a populated database,
  the Stage 3 rows inside the Arabian Sea polygon), `scripts/build_basemap.py` clipping on a tiny
  input, and the acceptance script's report shape.
- CI: the `web` job as today (the lockfile is committed); `integration` seeds and runs the e2e;
  the `docker` job builds the web image.

## 7. Out of scope

Authentication (Stage 7), chat (Stage 4), jobs and exports including the "export the filtered
dataset" action of §2.1 (Stage 5; the dashboard shows the action disabled with the stage named),
forecasts (Stage 6), BGC parameters, correlation views beyond the T-S diagram and the histogram
(the Stage 2 contract has no correlation operation; recorded as a known gap), dark mode (the
tokens are in place; a validated dark palette is a follow-up), map tiles from a server.

## 8. Gate

`make lint`, `make typecheck`, `make test` green; `pytest tests/stage2 -m integration` green;
`scripts/integration.py` (seeded e2e) green locally and in CI; `scripts/stage3_acceptance.py`
run on the imported dataset with its report and screenshots committed; gate report
`docs/stage3-gate.md`; PROGRESS.md and DECISIONS.md updated; pull request into `main`.
