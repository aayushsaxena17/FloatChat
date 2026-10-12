# Dashboard latency, 2026-10-11 (branch `perf/dashboard-latency`)

Host: WSL2 on Windows, 8 CPUs visible, 3.7 GB RAM; the dev Compose stack with the imported
Jan-Mar 2025 dataset (5,814 profiles, 4,144,346 levels, 206 parts in the part cache, nothing
fetched from object storage during any run). Raw outputs are in
`reports/dashboard-latency-2026-10-11/`; the probe is `scripts/dashboard_latency_probe.py`.

## Method

Each run starts from a freshly started API (empty memo) after the part-cache warm-up. Every
aggregate uses a different but equal-cost metric set, so the result memo never answers and every
number is a real execution. "Whole quarter" is the dashboard's default view (Indian Ocean,
Jan-Mar 2025, monthly mean and count of temperature and salinity, DuckDB route); "Arabian Sea" is
the same over 0-100 dbar (PostgreSQL route).

- **Before:** `main` at `7efeb2d` (`before-uncached.json`), one run.
- **After:** `ae527d8` (`after-uncached.json` with the backend changes, `after-uncached-2.json`
  on the final branch head after a restart).

## Results (milliseconds)

| Measure | Before | After, run 1 | After, run 2 |
|---|---:|---:|---:|
| Whole quarter, five calls | 2698, 2054, 1206, 3412, 2916 | 1092, 924, 986, 657, 567 | 1361, 790, 544, 595, 627 |
| Whole quarter, median | 2698 | 924 | 627 |
| Arabian Sea, five calls | 1273, 208, 219, 232, 277 | 521, 178, 177, 205, 189 | 1468, 201, 298, 234, 193 |
| `/v1/health/live` while aggregates run, max / median | 1372 / 1265 | 103 / 11 | 32 / 8 |
| Health samples taken during the aggregates | 3 | 28 | 34 |
| Whole quarter and Arabian Sea in parallel, wall time | 1348 | 565 | 681 |

Repeating an identical question is answered from the result memo (`baseline.json` is the old
code, `after-backend.json` the new; same plans asked three times):

| Same question again | Before | After |
|---|---:|---:|
| Whole quarter, second and third call | 1460, 1251 | 21, 17 |
| Arabian Sea, second and third call | 227, 404 | 9, 8 |

Before, only three health samples fit into three aggregates because each health call waited for
the running aggregate; the medians show the event loop was blocked. After, health answers in
about 10 ms throughout.

Web bundle (`pnpm build`): at the Stage 3 gate (`docs/stage3-gate.md`; not rebuilt on `7efeb2d`)
the first page load fetched the entry (159 kB gzipped), MapLibre (288 kB) and Plotly (504 kB) up
front; it now fetches the 139 kB entry, and the map chunk
(350 kB with MapLibre) and Plotly (504 kB) load on first use. Persisted answers (IndexedDB) make
a refresh reuse coverage and chart results without a request.

## Caveats

- A third run on the branch (between the two above) showed two whole-quarter calls near 3.1 s and
  a 3.8 s parallel pair; its output file was lost to a session restart, so it is not in the table.
  `main` showed spikes of the same size (3.4 s). The first call after a start and occasional
  spikes come from this 3.7 GB host (swap in use, page cache shared with Docker), not from the
  query path: five further uncached queries in-process took 0.5-1.75 s.
- One run per side; the numbers are indicative, not a benchmark.
- The route check (`reports/stage2-route-check_2026-10-11.md`) runs both routes in one process and
  its timings include contention; it proves agreement (10 of 10 plans, maximum relative
  difference 5.9e-14), not latency.
