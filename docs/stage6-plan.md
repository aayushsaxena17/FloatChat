# Stage 6 plan - forecasting (reviewed 2026-10-16)

Status: **in progress on `codex/stage-6`** (owner instruction 2026-10-15: complete Stages 5 and
6 on separate branches, decide every open question). Scope: build prompt "Stage 6", PRD §2.4,
§5.12, §6.9, §9.5, §12, §13, §14, §18.3, §22, §30.4, §30.5. Branch `codex/stage-6` from
`codex/stage-5` (the jobs worker, the `forecast` queue name and the historical runs are its
inputs); one pull request, opened against `codex/stage-5`. Decisions taken in this review are
ADR-0082 to ADR-0085.

## 0. What this review decided

1. **A forecast is a job.** `POST /v1/forecasts` creates a job of kind `forecast` on the
   `forecast` queue (ADR-0077); the same worker process serves it. The job's chunks are
   `series` (build and snapshot the regular series) and `model` (backtest, select, forecast).
   Progress, cancellation, events and client scoping are the Stage 5 ones (ADR-0082).
2. **The forecastable unit is a monthly, profile-balanced mean** of one variable (temperature
   or salinity) over one named region and one depth band, under qc-policy-v1 `science_ready`,
   with a configured minimum of profiles per month (PRD §12.1). The series comes from the
   committed Parquet parts through DuckDB in the worker, with members from PostgreSQL, using
   the query engine's own aggregate template (`group_by month`, `unit profile`), so the number a
   forecast is trained on is the number the dashboard shows for that month (ADR-0083).
3. **The data snapshot is explicit and immutable**: dataset version (environment, latest run,
   completed runs), the partition ids and SHA-256 of every part read, the month values and
   counts, and the missing-data treatment. It is stored as an object and quoted by the model
   and the run (PRD §6.9, §17). The six evaluation series are committed under `eval/forecast/`
   so `make eval-forecast` reproduces the report from a clean checkout without a database
   (ADR-0085).
4. **Models and selection** (PRD §12.2, §30.4): seasonal-naive baseline (period 12); SARIMA
   candidates on a bounded grid (`p,q ∈ {0,1,2}`, `d ∈ {0,1}`, `P,Q ∈ {0,1}`, `D ∈ {0,1}`,
   `s = 12`), ranked by AICc on the first training window and the best three carried into a
   rolling-origin backtest with at least 12 folds and horizons 1 to 3 months, expanding
   window, refit per fold. Metrics per horizon: MAE, RMSE, MASE (scaled by the in-sample MAE of
   the seasonal-naive on the training window) and empirical 80% and 95% interval coverage.
   The selected model is the simplest candidate whose mean MASE over the horizons improves on
   the baseline by at least 5% and whose residuals pass the Ljung-Box test at lag 12
   (p > 0.05); otherwise the run is `experimental` and shows the baseline (ADR-0084).
5. **Refusals** (PRD §12.3): fewer than 36 regular months, missingness above 20% or a gap
   longer than two months after the minimum-profiles rule, a near-constant series, or a
   horizon above a quarter of the history refuse with the reason recorded; a candidate that
   does not beat the baseline or fails diagnostics does not refuse but labels the run
   `experimental` with no authoritative forecast (PRD §22 "Forecast fails validation").
6. **Honesty in the UI** (acceptance criterion): the workspace never shows a forecast without
   its backtest table; the §12.4 boundary text is on every run; refused runs show the reason and
   the history only.
7. **Data for the evaluation**: the Stage 5 historical runs provide ten years for the Arabian
   Sea, the Bay of Bengal and the Laccadive Sea (through the job system, so the catalogue
   carries their provenance); temperature and salinity at 0-100 dbar give the six series of
   §30.4, plus the Andaman Sea as a refusal case if its history is too sparse. The committed
   report names the data snapshot of every series.

## 1. Inputs

Stage 5: `JobRunner` and its store, `ExportWriter`'s DuckDB connection and part cache, the
`forecast` queue, the historical runs and their coverage. Stage 2: `compile_duckdb.aggregate_statement`,
`compile_sql.profile_slot_statement`, `QueryCatalogue`, named regions, provenance attribution.
Stage 3: `ChartPanel`/`figuresFromChart` (line charts; interval bands are new), `DataTable`.

## 2. Decisions (full text in DECISIONS.md)

- ADR-0082: scope, branch, forecast jobs and tables.
- ADR-0083: the forecastable unit, series builder, snapshot and missing-data policy.
- ADR-0084: models, backtest protocol, metrics, selection and refusal rules, artefacts, seeds.
- ADR-0085: API, workspace UI, the evaluation harness and report integrity.

## 3. Work items

- **W1 Migration `0020_forecasts`**: `app.forecast_definition` (id, client_id, request,
  definition_sha256, variable, region, depth, frequency, aggregation, qc_policy,
  min_profiles, created_at; unique on client and sha), `app.forecast_model` (id,
  definition_id, version, family, order, seasonal_order, training_snapshot, metrics,
  diagnostics, status `selected|baseline|rejected`, artefact_key, created_at),
  `app.forecast_run` (id, definition_id, model_id, job_id, horizon, status
  `published|experimental|refused`, history, forecast, backtest, warnings, limitations,
  reason, seed, generated_at). Grants to `floatchat_app`; `STAGE6_APPLICATION_TABLES`.
- **W2 `floatchat_core/forecast/`**: `model.py` (request `forecast-request-v1`, limits
  `FORECAST_*`), `series.py` (monthly profile-balanced series over DuckDB; snapshot document
  `series-snapshot-v1`; missing policy), `models.py` (seasonal naive, SARIMA grid, rolling
  backtest, metrics, diagnostics, selection), `store.py` (definitions, models, runs),
  `runner.py` (the `forecast` job: series chunk, model chunk, publication), `artefacts.py`
  (object keys under `forecasts/`).
- **W3 Worker**: the jobs worker dispatches `forecast` jobs to the forecast runner.
- **W4 API**: `POST /v1/forecasts` (202, job + definition), `GET /v1/forecasts` (client's runs),
  `GET /v1/forecasts/{run_id}` (history, forecast, intervals, backtest metrics, model, snapshot,
  limitations); codes `forecast_not_found` (404).
- **W5 Web**: `/forecasts` (form: variable, region, depth band, horizon; list of runs),
  `/forecasts/:forecastId` (history and forecast with 80%/95% bands, metrics against the
  baseline per horizon, model and snapshot facts, warnings, the boundary text; refused runs
  show the reason).
- **W6 Evaluation**: `eval/forecast/series/*.json` (six or more committed snapshots),
  `eval/forecast/harness.py` (`make eval-forecast`), `reports/eval_forecast_<date>.md` with
  commit, snapshot ids, seeds, per-series metrics, baseline wins and refusals.
- **W7 Tests**: series builder over synthetic parts; models on synthetic seasonal series
  (SARIMA beats the baseline on a seasonal series with trend; the baseline wins on white
  noise; refusals); store over the disposable database (integration); API over a memory store;
  web Vitest for the workspace; a harness smoke test.
- **W8 Documents**: `docs/stage6-gate.md`, PROGRESS.md, README (results table row), the report.

## 4. Out of scope

Float-level series (PRD §12.1 mentions a float; regions only in v1), BGC variables, Diebold-
Mariano (optional in §30.4; recorded as future work), production error tracking (§18.3),
model serving beyond the stored run, MLflow.

## 5. Gate

`make eval-forecast` regenerates the report from the committed snapshots; the UI shows no
forecast without its backtest metrics; lint, types and tests pass; the report includes a
series where SARIMA does not beat the baseline and a refused series.
