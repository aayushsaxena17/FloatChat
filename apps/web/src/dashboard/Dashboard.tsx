import { useMemo } from "react";
import { Link } from "react-router";
import { useCoverage, usePlanQuery } from "../api/hooks";
import { CoveragePanel } from "../catalog/CoveragePanel";
import { ChartPanel } from "../charts/ChartPanel";
import { figuresFromChart } from "../charts/spec";
import { Panel } from "../components/Panel";
import { StatusMessage } from "../components/StatusMessage";
import { FilterBar } from "../explorer/FilterBar";
import {
  histogramPlan,
  isReady,
  timeSeriesPlan,
  toSearchParams,
} from "../explorer/filters";
import { MapView } from "../explorer/MapView";
import { useExplorerData } from "../explorer/useExplorerData";
import { ProvenancePanel } from "../provenance/ProvenancePanel";

/** The contract's chart_points_per_series limit as the parameter catalogue publishes it. */
export function chartPointBound(parameters: unknown): number | null {
  const limits = (
    parameters as { limits?: Record<string, unknown> } | undefined
  )?.limits;
  const value = limits?.chart_points_per_series;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** PRD 2.1: the most recent data with explicit coverage, time series and distributions. */
export function Dashboard() {
  const data = useExplorerData();
  const { filters, update, profiles, points, trajectory } = data;
  const ready = isReady(filters);
  const coverage = useCoverage(filters);
  const seriesPlan = useMemo(
    () => (ready ? timeSeriesPlan(filters) : null),
    [filters, ready],
  );
  const histogram = useMemo(
    () => (ready ? histogramPlan(filters) : null),
    [filters, ready],
  );
  const series = usePlanQuery(seriesPlan);
  // The per-profile distribution is bounded by the contract's points-per-series limit
  // (chart.py); the request is only sent when the coverage estimate fits, and the panel says
  // how to narrow the filters otherwise.
  const bound = chartPointBound(data.parameters.data);
  const estimated = coverage.data?.coverage.estimated_profiles;
  const histogramAllowed =
    estimated !== undefined && bound !== null && estimated <= bound;
  const distribution = usePlanQuery(histogram, histogramAllowed);
  const seriesFigures = useMemo(
    () =>
      series.data?.chart
        ? figuresFromChart(series.data.chart, series.data.result)
        : [],
    [series.data],
  );
  const histogramFigures = useMemo(
    () =>
      distribution.data?.chart
        ? figuresFromChart(distribution.data.chart, distribution.data.result)
        : [],
    [distribution.data],
  );
  const exploreQuery = toSearchParams(filters).toString();
  return (
    <>
      <h1>Dashboard</h1>
      <FilterBar
        filters={filters}
        update={update}
        parameters={data.parameters.data}
        showVariable
      />
      {!ready ? (
        <p className="status" role="status">
          {filters.start && filters.end
            ? "Fix the filters to load data."
            : "Loading the environment's reference window…"}
        </p>
      ) : null}
      <div className="grid">
        <StatusMessage
          loading={coverage.isPending && coverage.fetchStatus !== "idle"}
          error={coverage.error}
        >
          {coverage.data ? <CoveragePanel coverage={coverage.data} /> : null}
        </StatusMessage>
        <Panel
          title="Profile locations"
          actions={
            <Link to={`/explore/map?${exploreQuery}`}>Open the map</Link>
          }
        >
          <StatusMessage
            loading={profiles.isPending && profiles.fetchStatus !== "idle"}
            error={profiles.error}
          >
            <MapView
              points={points}
              trajectory={trajectory}
              selectedProfile={filters.profile}
              regionBox={data.regionBox}
              truncated={profiles.data?.truncated}
              compact
              onSelect={data.select}
            />
            <p className="chart-caption">
              {points.length.toLocaleString("en-GB")} profiles from{" "}
              {new Set(points.map((point) => point.platform)).size} floats;
              click a point or use{" "}
              <Link to={`/explore/profiles?${exploreQuery}`}>
                the profile list
              </Link>
              .
            </p>
            {profiles.data?.pages[0] ? (
              <ProvenancePanel provenance={profiles.data.pages[0].provenance} />
            ) : null}
          </StatusMessage>
        </Panel>
        <div className="wide">
          <StatusMessage
            loading={series.isPending && series.fetchStatus !== "idle"}
            error={series.error}
          >
            <div className="grid">
              {seriesFigures.map((figure) => (
                <ChartPanel
                  key={figure.key}
                  figure={figure}
                  caption={series.data?.interpretation.transformation as string}
                />
              ))}
            </div>
            {series.data ? (
              <div className="panel" style={{ marginTop: 14 }}>
                <p className="chart-caption">
                  Time series of{" "}
                  {series.data.plan.variables
                    ? (series.data.plan.variables as string[]).join(" and ")
                    : ""}{" "}
                  by{" "}
                  {(
                    series.data.plan.operation as { group_by?: string[] }
                  ).group_by?.join(", ")}
                  ; route {series.data.execution.source},{" "}
                  {series.data.execution.elapsed_ms} ms
                  {series.data.partial
                    ? "; coverage partial (see the coverage panel)"
                    : ""}
                  .
                </p>
                <ProvenancePanel provenance={series.data.provenance} />
              </div>
            ) : null}
          </StatusMessage>
        </div>
        <div className="wide">
          {coverage.data && !histogramAllowed ? (
            <p className="status" role="status" data-testid="histogram-bound">
              The per-profile distribution is available for at most{" "}
              {bound?.toLocaleString("en-GB") ?? "?"} profiles; this selection
              holds {estimated?.toLocaleString("en-GB") ?? "?"} in its coverage
              manifests. Narrow the region or the dates to see it.
            </p>
          ) : null}
          <StatusMessage
            loading={
              distribution.isPending && distribution.fetchStatus !== "idle"
            }
            error={distribution.error}
          >
            <div className="grid">
              {histogramFigures.map((figure) => (
                <ChartPanel
                  key={figure.key}
                  figure={figure}
                  caption={
                    distribution.data?.interpretation.transformation as string
                  }
                />
              ))}
            </div>
            {distribution.data ? (
              <div className="panel" style={{ marginTop: 14 }}>
                <ProvenancePanel provenance={distribution.data.provenance} />
              </div>
            ) : null}
          </StatusMessage>
        </div>
        <Panel title="Export">
          <p className="chart-caption">
            Exporting the filtered dataset (CSV and Parquet with a manifest)
            arrives with Stage 5.
          </p>
          <button type="button" disabled>
            Export filtered dataset (Stage 5)
          </button>
        </Panel>
      </div>
    </>
  );
}
