# Stage 6 gate report - forecasting

- Stage 6 - **complete in software and tests; the evaluation report depends on the Stage 5
  historical fetches, whose status is recorded below**.
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

`reports/eval_forecast_<date>.md` from `make eval-forecast` over the committed snapshots
(data snapshot ids, dataset versions, seed, library versions and the grid are in its header).
Nothing is repeated here by hand. Per series it reports the baseline and selected MASE per
horizon, coverage, and whether the baseline was beaten, including the series where it was not
and the refused series.

## Deviations from the PRD

- Regions only (no float-level series) in v1 (ADR-0083).
- Forecast artefacts are JSON parameter records, not pickled estimators (ADR-0084).
- The Diebold-Mariano test (optional in §30.4) is not implemented; recorded as future work.

## Known issues and risks

- The ten-year history behind the six evaluation series comes from the Stage 5 historical
  fetches, which were still running on this host when the stage was written; the committed
  snapshots and the report state exactly which months each series has. A series shorter than
  36 regular months is refused by design.
- `make eval-forecast` over the full grid fits 144 orders per series; on this host under
  ingestion load that is minutes per series. `--grid small` is for checks only and says so in
  the report.
- Interval coverage of the seasonal-naive baseline uses one empirical error distribution for
  every horizon (ADR-0084 point 1); the SARIMA intervals come from statsmodels.

## Needs from Aayush

- Review the stacked pull requests (design, Stage 5, Stage 6) in order.
- Let the Stage 5 fetches finish (or run `scripts/stage5_report.py run` for the regions you
  want), then `python -m eval.forecast.harness --rebuild` and commit the refreshed snapshots
  and report.

## Proposed plan for the next stage

Stage 7 (auth, quotas, security, observability): OIDC login and roles mapping the client
identifier of Stages 4-6 to users, quotas on jobs and exports, the security test suite,
OpenTelemetry traces through the API and the workers.
