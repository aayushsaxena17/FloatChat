import { useMemo } from "react";
import { Link } from "react-router";
import {
  ArrowUpRight,
  CalendarDays,
  Database,
  Layers,
  Radio,
  Info,
  Download,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { formatNumber } from "../catalog/units";
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
    <div className="dashboard">
      <div className="page-heading">
        <div>
          <p className="eyebrow">OCEAN DATA EXPLORER</p>
          <h1>Dashboard</h1>
          <p className="page-description">
            Explore Argo observations across the Indian Ocean.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to={`/explore/profiles?${exploreQuery}`}>
            <Layers aria-hidden="true" />
            Browse profiles
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
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
      <div
        className="summary-grid"
        aria-label="Selection summary"
        aria-busy={coverage.isFetching}
      >
        {[
          {
            label: "Profiles in coverage",
            value: formatNumber(coverage.data?.coverage.estimated_profiles),
            note: "Recorded in source manifests",
            icon: Database,
          },
          {
            label: "Measurement levels",
            value: formatNumber(coverage.data?.coverage.estimated_levels),
            note: "Across covered profiles",
            icon: Layers,
          },
          {
            label: "Floats on the map",
            value: profiles.data
              ? formatNumber(
                  new Set(points.map((point) => point.platform)).size,
                )
              : "—",
            note: profiles.data?.truncated
              ? "From the first 5,000 profiles"
              : "Distinct observing instruments",
            icon: Radio,
          },
          {
            label: "Months in selection",
            value: coverage.data
              ? formatNumber(coverage.data.coverage.months.length)
              : "—",
            note: "Coverage is checked month by month",
            icon: CalendarDays,
          },
        ].map(({ label, value, note, icon: Icon }) => (
          <Card key={label} className="summary-card">
            <div className="summary-label">
              {label}
              <Icon size={17} aria-hidden="true" />
            </div>
            <strong>{value}</strong>
            <p>{note}</p>
          </Card>
        ))}
      </div>
      <p className="summary-note">
        Coverage totals describe source records before pressure and quality
        filtering.
      </p>
      <div className="overview-grid">
        <div className="coverage-column">
          <StatusMessage
            loading={coverage.isPending && coverage.fetchStatus !== "idle"}
            error={coverage.error}
          >
            {coverage.data ? <CoveragePanel coverage={coverage.data} /> : null}
          </StatusMessage>
        </div>
        <Panel
          title="Profile locations"
          className="locations-panel"
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link to={`/explore/map?${exploreQuery}`}>
                Open the map
                <ArrowUpRight aria-hidden="true" />
              </Link>
            </Button>
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
      </div>
      <section className="analysis-section" aria-labelledby="trends-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">OBSERVATIONS OVER TIME</p>
            <h2 id="trends-title">Temperature & salinity</h2>
            <p className="page-description">
              Profile-balanced averages and the number of contributing profiles.
            </p>
          </div>
          <span className="section-note">
            UTC ·{" "}
            {filters.depthMin === null && filters.depthMax === null
              ? "All pressures"
              : `${filters.depthMin ?? 0}–${filters.depthMax ?? 12000} dbar`}
          </span>
        </div>
        <StatusMessage
          loading={series.isPending && series.fetchStatus !== "idle"}
          error={series.error}
        >
          <div className="trend-grid">
            {seriesFigures.map((figure) => (
              <ChartPanel
                key={figure.key}
                compact
                figure={figure}
                caption={series.data?.interpretation.transformation as string}
              />
            ))}
          </div>
          {series.data ? (
            <div className="query-details">
              <p className="chart-caption">
                Averages of{" "}
                {series.data.plan.variables
                  ? (series.data.plan.variables as string[]).join(" and ")
                  : ""}{" "}
                by{" "}
                {(
                  series.data.plan.operation as { group_by?: string[] }
                ).group_by?.join(", ")}
                · {series.data.execution.source} ·{" "}
                {series.data.execution.elapsed_ms == null
                  ? "timing unavailable"
                  : `${(series.data.execution.elapsed_ms / 1000).toFixed(2)} seconds`}
                {series.data.partial
                  ? "; coverage partial (see the coverage panel)"
                  : ""}
                .
              </p>
              <ProvenancePanel provenance={series.data.provenance} />
            </div>
          ) : null}
        </StatusMessage>
      </section>
      <section
        className="distribution-section"
        aria-labelledby="distribution-title"
      >
        <div className="section-heading">
          <div>
            <h2 id="distribution-title">Profile distribution</h2>
            <p className="page-description">
              How individual profile averages are spread across the selection.
            </p>
          </div>
        </div>
        {coverage.data && !histogramAllowed ? (
          <p className="status" role="status" data-testid="histogram-bound">
            <Info size={18} aria-hidden="true" />
            <span>
              The per-profile distribution is available for at most{" "}
              {bound?.toLocaleString("en-GB") ?? "?"} profiles; this selection
              holds {estimated?.toLocaleString("en-GB") ?? "?"} in its coverage
              manifests. Narrow the region or the dates to see it.
            </span>
          </p>
        ) : null}
        <StatusMessage
          loading={
            distribution.isPending && distribution.fetchStatus !== "idle"
          }
          error={distribution.error}
        >
          <div className="trend-grid">
            {histogramFigures.map((figure) => (
              <ChartPanel
                key={figure.key}
                compact
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
      </section>
      <div className="export-notice">
        <Download size={18} aria-hidden="true" />
        <div>
          <h2>Dataset export</h2>
          <p className="chart-caption">
            Exporting the filtered dataset (CSV and Parquet with a manifest)
            will be available in a later release.
          </p>
        </div>
        <Button type="button" variant="outline" disabled>
          Export filtered dataset
        </Button>
      </div>
    </div>
  );
}
