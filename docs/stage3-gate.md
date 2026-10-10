# Stage 3 gate - web dashboard

**Stage 3 - complete.** CI green on `815751a` (run 38008497585, all seven jobs) and on `5b5bd54` (run 38007878218). Branch `codex/stage-3` from
`codex/stage-2-fixes` (`5cf262e`, PR #7); pull request
[#8](https://github.com/aayushsaxena17/FloatChat/pull/8) targets `main` and is rebased once PR #7
is squash-merged (ADR-0061). Scope: build prompt "Stage 3", PRD §2.1, §5.1, §5.10, §11.3, §14,
§17; reviewed plan [docs/stage3-plan.md](stage3-plan.md); decisions ADR-0061 to ADR-0065. Owner
instruction 2026-10-09: build on the accepted Stage 2 and decide open questions without approval;
the advisor reviewed the approach and the written plan (PROGRESS.md).

## What was built

- `apps/web/src/app/`: `App.tsx` (TanStack Query client, router, error boundary), `routes.tsx`
  (`/` -> `/dashboard`; `/dashboard`, `/explore/map`, `/explore/profiles`; stubs for `/login`,
  `/chat`, `/jobs`, `/forecasts`, `/settings`, `/admin/*` naming their stage), `Layout.tsx` (skip
  link, navigation, readiness status, attribution footer), `Stub.tsx`, `ErrorBoundary.tsx`.
- `apps/web/src/explorer/`: `filters.ts` (the URL filter model: region, start, end, depth, QC
  policy, float, profile, variable; validation; read parameters and the three plan documents),
  `useFilters.ts`, `FilterBar.tsx`, `MapView.tsx` (MapLibre 6 over the offline style; clustered
  profile points with DOM count markers; the selected float's trajectory; the region bounding box;
  hover popups; live count; WebGL failure fallback), `ProfileList.tsx` (the keyboard path),
  `ProfileCharts.tsx`, `ProfilesView.tsx`, `MapPage.tsx`, `profiles.ts`, `useExplorerData.ts`.
- `apps/web/src/dashboard/Dashboard.tsx`: coverage panel, compact map, monthly or daily time series
  (one panel per unit), distribution histogram of the chosen variable, provenance on each result,
  the export action disabled and named for Stage 5.
- `apps/web/src/charts/`: `spec.ts` (contract to Plotly figures: allow-listed keys, one unit per
  panel, units on axes, palette by series identity, folding past three profiles, table data),
  `profile.ts` (profile figures and QC summary), `Plot.tsx`, `ChartPanel.tsx`, `palette.ts`,
  `plotly.ts` (cartesian bundle).
- `apps/web/src/catalog/` (`units.ts`, `CoveragePanel.tsx`), `provenance/ProvenancePanel.tsx`,
  `components/` (`DataTable`, `Panel`, `StatusMessage`), `map/style.ts` and `map/land.json`
  (Natural Earth land clipped by `scripts/build_basemap.py`, source SHA-256 recorded),
  `api/hooks.ts`, `api/types.ts`, `style.css` (tokens).
- API (ADR-0064): typed response models in `apps/api/src/floatchat_api/query_api.py`,
  `provenance.build_read` on the four read endpoints, migration
  `infra/migrations/versions/0017_query_env_times.{py,sql}` (latest run, ingestion timestamp,
  source retrieval window on `app.query_environment`), `APPLICATION_COMMIT` through Compose from
  `scripts/dev.py` and `scripts/integration.py`; `apps/api/openapi.json` and
  `apps/web/src/api/schema.d.ts` regenerated.
- Test data (ADR-0063): `scripts/science_seed.py` (the Stage 2 seed plus four January 2025 Arabian
  Sea profiles; `database` and `objects` entry points; shipped in the API image),
  `scripts/integration.py` seeds the disposable project and asserts the scenario,
  `scripts/capture_web_fixtures.py` records the Vitest fixtures, `scripts/stage3_acceptance.py`
  runs the suite on the imported dataset with screenshots.
- Tests: `apps/web/src/**/*.test.{ts,tsx}` (47 cases), `apps/web/e2e/dashboard.spec.ts` and the
  adapted `scaffold.spec.ts`, `tests/stage3/` (17 cases: read provenance, seed, basemap), the Stage
  2 integration suite extended for 0017 and read provenance.

## How to run and see it

```bash
make dev
```

```bash
uv run --all-packages --frozen python scripts/stage2_dataset.py import --session 302412131a7c99fb
```

Then open http://127.0.0.1:5173/dashboard?region=Arabian%20Sea&start=2025-01-01&end=2025-02-01&depth_min=0&depth_max=100
(the `web` service runs the Vite dev server; the first request pre-bundles the map and chart
libraries). Checks:

```bash
make lint
```

```bash
make typecheck
```

```bash
make test
```

```bash
uv run --all-packages --frozen python -m pytest tests/stage2 -m integration -q
```

```bash
make integration
```

```bash
uv run --all-packages --frozen python scripts/stage3_acceptance.py --base-url http://127.0.0.1:5173 --api-url http://127.0.0.1:8000
```

## Tests and CI

Local (WSL2 Ubuntu 24.04, Docker Desktop); the Python and web suites re-run on the gate head `1f3ac89`, the Docker acceptance and the integration suite on `56900f4` (no Python source changed afterwards):

| Check | Result |
|---|---|
| `ruff check`, `ruff format --check`, `pnpm lint`, `pnpm format:check` | clean |
| `mypy` (strict, 53 source files), `tsc --noEmit` | clean |
| `pytest -m 'not integration'` (Stages 0-3) | 1,870 passed, 1 skipped, 122 integration deselected (97.2 s on `1f3ac89`) |
| `pnpm test` (Vitest, jsdom, MapLibre and Plotly mocked) | 50 passed in 12 files |
| `pytest tests/stage2/test_integration.py -m integration` (disposable PostGIS, migration 0017, read provenance) | 12 passed |
| `pnpm build` (Vite) | built; chunks `index` 503 kB, `maplibre` 1,058 kB, `plotly` 1,512 kB (gzip 159, 288, 504 kB), worker 508 kB |
| `make secrets-current` (gitleaks 8.30.1) | one finding, the owner's git-ignored `.env.txt` (ADR-0039); nothing tracked |
| `scripts/integration.py` (Docker acceptance: empty-database checks, seed of 9 profiles with catalogue and objects, API restart with warm-up, probes, outages, repeat start-up, Playwright e2e) | complete; [reports/stage0-integration.json](../reports/stage0-integration.json), project `floatchat-stage0-test-ac9dd329caa2`, empty-volume start-up 27.4 s, 5 profiles in the scenario, both e2e specs passed (7.9 s and 3.8 s) |
| Playwright against the imported dataset (the `web` container on 5173, dev API) | 2 passed ([report](../reports/stage3-acceptance-2026-10-10.json)) |

CI (GitHub Actions, workflow `CI`) on the pull-request heads: run
[38007878218](https://github.com/aayushsaxena17/FloatChat/actions/runs/38007878218) on `5b5bd54` and
run [38008497585](https://github.com/aayushsaxena17/FloatChat/actions/runs/38008497585) on the final
head `815751a`: `python`, `web`, `docker`, `integration` (the seeded Docker acceptance with both
Playwright specs), `secrets-current`, `secrets-history` and `stage1-offline-components` (with
`tests/stage3` and the Stage 2 integration step) all succeeded. The Docker Hub rate limit that hit
PR #7 did not recur.

## Measured results

All numbers come from files written by scripts; nothing is typed by hand.

Acceptance on the imported Jan-Mar 2025 dataset
([reports/stage3-acceptance-2026-10-10.json](../reports/stage3-acceptance-2026-10-10.json),
screenshots `01-dashboard.png`, `02-map.png`, `03-profiles.png` under
`reports/stage3-acceptance-2026-10-10/`): environment
`floatchat-s1-acceptance-302412131a7c99fb`, reference time 2025-04-01T00:00:00Z, latest run
`8562e75d`, ingested 2026-10-09T11:59:11Z, source retrieved 2026-10-09T11:35:41Z to 11:57:50Z.

| Scenario (Arabian Sea, 2025-01-01 to 2025-02-01, 0-100 dbar) | Value |
|---|---:|
| Profiles listed and plotted | 132 |
| Coverage slots (month x tile): covered / verified empty / missing | 9 / 1 / 0 of 10 |
| Profiles and levels in the manifests for the scenario's region and month | 291; 185,694 |
| Playwright: dashboard scenario; shell check | 13.0 s; 3.2 s (both passed, on the `web` container) |

Seeded Docker project ([reports/stage0-integration.json](../reports/stage0-integration.json)):
5 profiles in the scenario (the seed's January Arabian Sea rows), e2e passed in 7.9 s on the
containerised Vite dev server.

## Deviations from the PRD (with ADRs)

- React Router 7.18.4 rather than the current major (React Router 8 needs React 19.2.7; the
  repository pins 19.2.0); the declarative API is identical (ADR-0061).
- The `map` chart kind of the contract is never requested; the map reads `/v1/profiles` and
  bounds itself to 5,000 points with a truncation label (PRD §14.4; ADR-0062).
- The basemap is a bundled Natural Earth land layer rather than a tile service; text on the map is
  DOM overlays because MapLibre symbol layers need a glyph server (ADR-0062).
- CI's end-to-end run uses the synthetic seed (real-data acceptance is the local run above);
  the seed is labelled test data, not Stage 1 evidence (ADR-0063).
- The read endpoints gained a provenance object and the environment view gained timestamps; both
  additive (ADR-0064).
- A chart with mixed units renders as one panel per unit; no dual axis (ADR-0065).
- Correlation views (PRD §2.1) beyond the T-S diagram and the histogram are not built: the Stage 2
  contract has no correlation operation (plan section 7). Dark mode is deferred (tokens in place).

## Known issues and risks

- The `docker` and `integration` jobs pull base images and can hit Docker Hub's anonymous rate
  limit as PR #7 did; both runs of this stage passed without it.
- A re-run of the CI `integration` job on PR #8 failed: the end-to-end test filled the date and
  depth controls faster than React re-rendered, and each filter update rebuilt the URL from the
  last render's filters, so a later write dropped `end`. Fixed by building every update on the
  latest URL the hook wrote (`explorer/useFilters.ts`), with a regression test that fails on the
  old hook. Earlier green runs had simply not hit the race.
- The Vitest suite showed one timing-dependent failure in `Dashboard.test.tsx` during a run with
  Docker builds in parallel on this host; it did not reproduce in two further runs or in CI.
- Bundle size: Plotly's cartesian bundle and MapLibre total about 950 kB gzipped; they are split
  into their own cacheable chunks but not lazy-loaded per route (follow-up).
- The map eases to a selected profile at zoom 8.2 so it leaves its cluster; on a narrow viewport
  this hides the rest of the region until the user zooms out (the list beside the map stays).
- The multi-profile T-S diagram folds the 20 newest profiles to one colour; identity is on hover
  and in the table (ADR-0065). A per-float colouring would need a float column in the chart
  contract (follow-up).
- The Vite dev server inside the `web` container pre-bundles the map and chart libraries on the
  first request; the integration script's e2e budget is 300 s and the Playwright timeouts 120 s
  per test for that reason.
- `tests/test_refetch.py` HTTPS deadline tests remain load-sensitive (Stage 2 known issue); the
  full suite passed on an idle host.
- No authentication, quotas or rate limits (Stage 7); the API and web servers bind to loopback.

## Needs from Aayush

1. Merge PR #7 (Stage 2 fixes); then the Stage 3 branch is rebased onto `main` and its pull request
   re-checked.
2. Review and merge the Stage 3 pull request after CI.
3. Use the dashboard for ten minutes as a researcher and note anything confusing; the screenshots
   under `reports/stage3-acceptance-2026-10-10/` are the README material.
4. ADR-0057, ADR-0059 and ADR-0060 (Stage 2) still await confirmation.

## Proposed plan for Stage 4

Natural-language assistant (PRD §9.2, §10, §30.2-§30.3): a chat route over `POST /v1/chat/messages`
that turns a question into a validated `stage2-plan-v1` document (the only thing the LLM
produces), shows the interpretation panel (the plan, the coverage, the provenance) beside the
result rendered with the Stage 3 chart components, retrieval over the parameter catalogue and
region definitions (pgvector), prompt-injection controls, the golden benchmark under `eval/` with
plan accuracy and result accuracy measured separately, and the two-model ablation when a second
key exists. Decisions to record first: the LLM provider abstraction and key handling, the
conversation store (server-side, PRD §14.3), the benchmark's question set and scoring.
