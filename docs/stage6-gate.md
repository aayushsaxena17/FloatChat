# Stage 6 gate report - forecasting

- Stage 6 - **complete**: software, tests, the eight committed series snapshots and the
  evaluation report over them.
- Branch `codex/stage-6` from `codex/stage-5`; pull request against `codex/stage-5` (stacked,
  ADR-0082). Plan: [docs/stage6-plan.md](stage6-plan.md); decisions ADR-0082 to ADR-0085.

## What was built

- Migration `infra/migrations/versions/0020_forecasts.sql`: `forecast_definition`,
  `forecast_model`, `forecast_run` (PRD §6.9).
- `packages/core/src/floatchat_core/forecast/`: `model.py` (request `forecast-request-v1`,
  `ForecastLimits`, records, the §12.4 boundary text), `series.py` (the monthly
  profile-balanced series over the committed parts through the query engine's aggregate
  template in DuckDB, one calendar year per execution; `series-snapshot-v1`; the missing-data
  policy; eligibility checks), `models.py` (seasonal naive with empirical intervals; the
  bounded SARIMA grid of 144 orders with AICc ranking; rolling-origin, expanding-window
  backtests with refit per fold; MAE, RMSE, MASE, 80% and 95% coverage; Ljung-Box and
  residual-mean diagnostics; selection by the simplest candidate that beats the baseline by
  5%), `store.py` (PostgreSQL and memory stores), `runner.py` (the forecast job: series
  chunk, model chunk, run and model rows, JSON model artefacts under `forecasts/`).
- The jobs worker serves `forecast` jobs (`workers/src/floatchat_workers/jobs.py`); the
  ingestion adapter reconnects after a lost database session (found during the Stage 5 run).
- API `apps/api/src/floatchat_api/forecast_api.py`: `POST /v1/forecasts` (202, a job and the
  definition), `GET /v1/forecasts`, `GET /v1/forecasts/{run_id}`; code `forecast_not_found`;
  OpenAPI 0.5.0.
- Web `apps/web/src/forecasts/`: `/forecasts` (form and run list), `/forecasts/:forecastId`
  (history and forecast with 80% and 95% bands through a dedicated figure builder, the
  backtest table of every candidate with the baseline and the selected model marked, model
  and snapshot facts, warnings, the boundary text; refused runs show the reason and history).
- Evaluation `eval/forecast/harness.py` (`make eval-forecast`, `--rebuild` through a running
  stack, `--grid small` for quick checks), snapshots under `eval/forecast/series/`.

## How to run and see it

```bash
make dev                      # the stack (the jobs worker serves export and forecast)
make eval-forecast            # the report from the committed snapshots, no database needed
python -m eval.forecast.harness --rebuild --api-url http://127.0.0.1:8000   # fresh snapshots
```

Open http://127.0.0.1:5173/forecasts, choose a variable and region, "Run forecast"; the job
page follows it and the run page shows the result.

## Tests and CI

- `tests/stage6/test_models.py` (baseline, SARIMA beating the baseline on a seasonal series
  with trend, the experimental path when no candidate clears the margin, the run document
  with fill flags, the four refusal rules, the missing policy, the grids),
  `test_forecast_api.py` (creation as a job, attachment, validation, scoping, boundary),
  `test_harness.py` (report and sidecar from snapshots incl. a refusal).
- Web: `src/forecasts/ForecastsPage.test.tsx` (form to job, the detail never without its
  backtest table, refusal, the figure).
- CI integration: a forecast over the three seeded months is refused with
  `history_too_short` and the run, list and boundary text are served; Playwright
  `e2e/forecasts.spec.ts`.

## Measured results

[reports/eval_forecast_2026-10-16.md](../reports/eval_forecast_2026-10-16.md), from
`make eval-forecast` over the eight committed snapshots in `eval/forecast/series/` (data
snapshot ids, dataset version `8562e75d/27`, seed 20261016, library versions and the full
grid are in its header); the JSON sidecar holds every candidate's metrics. Nothing is repeated
here by hand. In words:

- Three series published a SARIMA that beats the seasonal-naive baseline by more than 5% on
  the mean MASE over the three horizons (the selection rule; per-horizon gains are in the
  table, and the Arabian Sea salinity gain at horizon 3 is under 5%) and passes the residual
  diagnostics (Arabian Sea temperature and salinity, Bay of Bengal salinity).
- Two series are `experimental`: Bay of Bengal temperature (no candidate beats the baseline
  by 5%) and Laccadive Sea temperature (the candidates that beat it fail the Ljung-Box
  test). The baseline wins are reported as such.
- Three series are refused: both Andaman Sea series (`history_too_short`, no month with five
  profiles) and Laccadive Sea salinity (`missingness_exceeds_policy`: 14 scattered months
  between 2020-01 and 2024-08 have fewer than five profiles with science-ready salinity,
  while the temperature series of the same region misses five; the longest gap, 2024-01 to
  2024-04, exceeds the two-month policy).
- A non-stationary candidate over the Arabian Sea temperature series diverged numerically in
  the backtest (mean MASE of order 10^14 in the first report); the backtest now reports such
  a candidate as diverged and never selects it (found through the report, fixed before the
  committed run).
- The report is reproducible: two consecutive `make eval-forecast` runs from the committed
  snapshots produced identical Markdown reports (checked by diff) and JSON sidecars that
  differ only in the wall-clock seconds per series; the date header is the only input that
  changes between days.
- `reports/stage6-smoke-forecast-2026-10-16.json` is the earlier live refusal during the Stage
  5 fetches, kept as evidence for the job, snapshot and refusal paths.

## Deviations from the PRD

- Regions only (no float-level series) in v1 (ADR-0083).
- Forecast artefacts are JSON parameter records, not pickled estimators (ADR-0084).
- The Diebold-Mariano test (optional in §30.4) is not implemented; recorded as future work.

## Known issues and risks

- The history behind the series comes from the Stage 5 historical fetches (ten years for the
  Arabian Sea, six for the Bay of Bengal, the Laccadive Sea through the overlapping Arabian
  Sea tiles); the committed snapshots state exactly which months each series has. A series
  shorter than 36 regular months is refused by design.
- `--grid small` is for checks only and says so in the report.
- The development stack's workers were rebuilt with the diverged-fit guard after the report
  run; forecast runs created before that keep the candidate row with the absurd MASE in
  their stored backtest table (the run page shows it as the report did).
- Interval coverage of the seasonal-naive baseline uses one empirical error distribution for
  every horizon (ADR-0084 point 1); the SARIMA intervals come from statsmodels.
- Interval coverage is reported but not part of the selection rule (PRD §9.5 selects on
  MASE and diagnostics): the published Arabian Sea salinity model covers 39% / 58% of the
  backtest actuals at nominal 80% / 95%, which the report and the run page show. A coverage
  floor in the selection rule is a candidate change for the owner's review.
- `make eval-forecast` over the full grid takes about 12 minutes on this host when the
  ingestion pool is idle (70 to 210 s per eligible series).

## Needs from Aayush

- Review the stacked pull requests (design, Stage 5, Stage 6) in order.
- Decide whether interval coverage should join the selection rule (see known issues).
- The Laccadive Sea salinity series is refused because 14 months have fewer than five
  profiles with science-ready salinity (a four-month gap in early 2024). Lowering
  `min_profiles` for salinity or widening the gap policy is a modelling decision for you; the
  refusal is the designed behaviour.

## Proposed plan for the next stage

Stage 7 (auth, quotas, security, observability): OIDC login and roles mapping the client
identifier of Stages 4-6 to users, quotas on jobs and exports, the security test suite,
OpenTelemetry traces through the API and the workers.
