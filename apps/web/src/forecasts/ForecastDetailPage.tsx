import { Link, useParams } from "react-router";
import { AlertCircle } from "lucide-react";
import { formatUtc } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { Panel } from "../components/Panel";
import { StatusMessage } from "../components/StatusMessage";
import { Badge } from "../components/ui/badge";
import { DetailsDialog } from "../components/DetailsDialog";
import { forecastFigure } from "./figure";
import { formatMetric, statusKind, statusLabel } from "./format";
import { useForecast } from "./useForecasts";

type Metrics = Record<
  string,
  {
    mae?: number;
    rmse?: number;
    mase?: number;
    coverage80?: number;
    coverage95?: number;
  }
>;
type BacktestEntry = {
  candidate?: { label?: string; parameters?: number };
  horizons?: Metrics;
  mean_mase?: number | null;
};

function MetricsTable({
  results,
  baseline,
  selected,
  horizons,
}: {
  results: Record<string, BacktestEntry>;
  baseline: string;
  selected: string | null;
  horizons: number[];
}) {
  const names = Object.keys(results);
  if (names.length === 0)
    return (
      <p className="status" role="status">
        No backtest was run.
      </p>
    );
  return (
    <div className="table-wrap">
      <table className="data">
        <caption className="sr-only">
          Rolling-origin backtest metrics per candidate and horizon
        </caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col">Mean MASE</th>
            {horizons.map((h) => (
              <th
                key={h}
                scope="col"
              >{`h${h} MAE / RMSE / MASE / cov 80 / cov 95`}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const entry = results[name];
            const role =
              name === baseline
                ? " (baseline)"
                : name === selected
                  ? " (selected)"
                  : "";
            return (
              <tr
                key={name}
                data-selected={name === selected ? "true" : undefined}
              >
                <td>
                  {name}
                  {role}
                </td>
                <td>{formatMetric(entry.mean_mase)}</td>
                {horizons.map((h) => {
                  const m = entry.horizons?.[String(h)] ?? {};
                  return (
                    <td key={h}>
                      {formatMetric(m.mae)} / {formatMetric(m.rmse)} /{" "}
                      {formatMetric(m.mase)} / {formatMetric(m.coverage80, 2)} /{" "}
                      {formatMetric(m.coverage95, 2)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ForecastDetailPage() {
  const { forecastId } = useParams();
  const detail = useForecast(forecastId);
  const run = detail.data?.run;
  const definition = detail.data?.definition;
  const model = detail.data?.model;
  const backtest = (run?.backtest ?? {}) as {
    results?: Record<string, BacktestEntry>;
    baseline?: string;
    horizons?: number[];
    folds?: number;
    protocol?: string;
    selection?: {
      selected?: { label?: string } | null;
      reasons?: string[];
      diagnostics?: Record<string, unknown>;
    };
  };
  const selectedLabel = backtest.selection?.selected?.label ?? null;
  const policy = (
    run?.history as { policy?: Record<string, unknown> } | undefined
  )?.policy;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="chart-caption">
            <Link to="/forecasts">Forecasts</Link>
          </p>
          <h1>
            {definition
              ? `${definition.variable === "salinity" ? "Salinity" : "Temperature"}, ${definition.region}`
              : "Forecast"}
          </h1>
          {definition ? (
            <p className="page-description">
              Monthly profile-balanced mean, {String(definition.depth_dbar.min)}{" "}
              to {String(definition.depth_dbar.max)} dbar, science-ready QC, at
              least {definition.min_profiles} profiles per month
              {run ? `, horizon ${run.horizon} months` : ""}.
            </p>
          ) : null}
        </div>
        {run ? (
          <Badge
            variant="outline"
            className="badge"
            data-kind={statusKind(run.status)}
          >
            {statusLabel(run.status)}
          </Badge>
        ) : null}
      </div>
      <StatusMessage loading={detail.isPending} error={detail.error}>
        {run && definition ? (
          <div className="job-detail">
            {run.status === "pending" ? (
              <p className="status" role="status">
                The forecast job is running; this page refreshes until it
                finishes.
                {run.job_id ? (
                  <>
                    {" "}
                    <Link to={`/jobs/${run.job_id}`}>Follow the job.</Link>
                  </>
                ) : null}
              </p>
            ) : null}
            {run.status === "refused" ? (
              <p className="status" data-kind="error" role="alert">
                <AlertCircle size={18} aria-hidden="true" />
                No forecast was produced: {run.reason}
              </p>
            ) : null}
            {run.status === "experimental" ? (
              <p className="status" role="status">
                <AlertCircle size={18} aria-hidden="true" />
                No SARIMA candidate beat the seasonal-naive baseline by the
                required margin and passed diagnostics. The baseline forecast is
                shown for reference only; it is not an authoritative forecast.
              </p>
            ) : null}
            {run.status !== "pending" ? (
              <ChartPanel
                figure={forecastFigure(run, definition.variable)}
                caption={
                  run.status === "refused"
                    ? "History only; the run was refused."
                    : `Shaded bands are the 80% and 95% prediction intervals of ${selectedLabel ?? backtest.baseline ?? "the model"}.`
                }
                description="History, forecast and prediction intervals"
                explanation={
                  policy
                    ? `Missing policy: ${String(policy.rule)}; ${String(policy.months_missing)} of ${String(policy.months_total)} months interpolated.`
                    : undefined
                }
              />
            ) : null}
            {run.status === "published" || run.status === "experimental" ? (
              <Panel title="Backtest against the baseline">
                <p className="chart-caption">
                  {backtest.protocol ?? "Rolling-origin backtest"};{" "}
                  {backtest.folds ?? "—"} folds; horizons{" "}
                  {(backtest.horizons ?? []).join(", ")} months. MASE below 1
                  beats the seasonal naive on that fold's history; coverage is
                  the share of actuals inside the interval.
                </p>
                <MetricsTable
                  results={backtest.results ?? {}}
                  baseline={backtest.baseline ?? "seasonal naive (12)"}
                  selected={selectedLabel}
                  horizons={backtest.horizons ?? [1, 2, 3]}
                />
                {backtest.selection?.reasons?.length ? (
                  <ul className="forecast-reasons">
                    {backtest.selection.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                ) : null}
              </Panel>
            ) : null}
            <Panel title="Model and data">
              <dl className="facts">
                <dt>Status</dt>
                <dd>{statusLabel(run.status)}</dd>
                <dt>Selected model</dt>
                <dd>
                  {selectedLabel ??
                    (run.status === "refused"
                      ? "none"
                      : "seasonal naive (12), not authoritative")}
                </dd>
                {model ? (
                  <>
                    <dt>Model version</dt>
                    <dd>
                      v{model.version} ({model.family}, {model.status})
                    </dd>
                    <dt>Training snapshot</dt>
                    <dd>
                      <code>
                        {String(
                          (model.training_snapshot as { snapshot_id?: string })
                            .snapshot_id ?? "",
                        )}
                      </code>
                    </dd>
                  </>
                ) : null}
                <dt>Generated</dt>
                <dd>{formatUtc(run.generated_at ?? run.created_at)}</dd>
                <dt>Seed and versions</dt>
                <dd>
                  seed {run.seed}; statsmodels{" "}
                  {String(run.versions.statsmodels ?? "—")}, scipy{" "}
                  {String(run.versions.scipy ?? "—")}
                </dd>
                {backtest.selection?.diagnostics &&
                "ljung_box_p" in backtest.selection.diagnostics ? (
                  <>
                    <dt>Residual diagnostics</dt>
                    <dd>
                      Ljung-Box p{" "}
                      {formatMetric(backtest.selection.diagnostics.ljung_box_p)}
                      ; residual mean{" "}
                      {formatMetric(
                        backtest.selection.diagnostics.residual_mean,
                        4,
                      )}
                    </dd>
                  </>
                ) : null}
              </dl>
              {run.warnings.length ? (
                <ul className="forecast-reasons">
                  {run.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : null}
            </Panel>
            <p className="status" role="note" data-testid="boundary">
              {run.limitations || detail.data?.boundary}
            </p>
            <DetailsDialog
              title="Run record"
              description="The stored run, definition and model as the API returns them."
            >
              <pre className="json">{JSON.stringify(detail.data, null, 2)}</pre>
            </DetailsDialog>
          </div>
        ) : null}
      </StatusMessage>
    </>
  );
}
