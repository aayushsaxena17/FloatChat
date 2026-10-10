import type { CoverageResponse } from "../api/types";
import { formatDay, formatNumber, formatUtc } from "../catalog/units";
import { Panel } from "../components/Panel";

/**
 * Coverage of the filters (build prompt scope 4): range, region, profile and level counts from
 * the manifests, missingness by slot, hot tier and window labels, source retrieval and
 * ingestion timestamps (ADR-0064). Partial coverage is a text badge, never colour alone.
 */
export function CoveragePanel({ coverage }: { coverage: CoverageResponse }) {
  const summary = coverage.coverage;
  const environment = coverage.environment;
  const geography = coverage.geography;
  const missingMonths = [
    ...new Set(summary.missing.map((slot) => slot.month)),
  ].sort();
  const badge = (
    <span
      className="badge"
      data-kind={summary.partial ? "partial" : "complete"}
    >
      {summary.partial ? "partial coverage" : "coverage complete"}
    </span>
  );
  return (
    <Panel title="Coverage" badge={badge} className="coverage">
      <dl className="facts">
        <dt>Requested range</dt>
        <dd>
          {formatDay(summary.requested.start)} to{" "}
          {formatDay(summary.requested.end)} (UTC, end exclusive); months{" "}
          {summary.months.join(", ") || "—"}
        </dd>
        <dt>Region</dt>
        <dd>
          {geography.name ?? geography.kind}
          {geography.version
            ? ` (${geography.version}${geography.clipped ? ", clipped to the envelope" : ""})`
            : ""}
        </dd>
        <dt>Profiles in manifests</dt>
        <dd>{formatNumber(summary.estimated_profiles)}</dd>
        <dt>Levels in manifests</dt>
        <dd>{formatNumber(summary.estimated_levels)}</dd>
        <dt>Slots (month × 10° tile)</dt>
        <dd>
          {summary.slots_covered} covered, {summary.slots_empty_verified}{" "}
          verified empty, {summary.slots_missing} missing of{" "}
          {summary.slots_total}
        </dd>
        <dt>Missing</dt>
        <dd>
          {missingMonths.length === 0
            ? "nothing missing in the requested scope"
            : `${missingMonths.join(", ")}: ${summary.missing
                .slice(0, 12)
                .map(
                  (slot) =>
                    `${slot.tile.west}°E/${slot.tile.south}°N (${slot.gaps.join(", ")})`,
                )
                .join(
                  "; ",
                )}${summary.missing.length > 12 ? `; and ${summary.missing.length - 12} more` : ""}`}
        </dd>
        <dt>Source</dt>
        <dd>argovis (Argo GDAC through Argovis); population argovis-core-v1</dd>
        <dt>Source retrieved</dt>
        <dd>
          {environment.source_retrieved
            ? `${formatUtc(environment.source_retrieved.start)} to ${formatUtc(environment.source_retrieved.end)}`
            : "unknown (no completed run)"}
        </dd>
        <dt>FloatChat ingestion</dt>
        <dd>
          {formatUtc(environment.ingested_at)} (run{" "}
          {environment.latest_run ?? "—"}; {environment.completed_runs}{" "}
          completed)
        </dd>
        <dt>Reference time</dt>
        <dd>
          {formatUtc(environment.reference_time)}; environment{" "}
          {environment.name} ({environment.mode})
        </dd>
        <dt>Hot tier (3 months)</dt>
        <dd>
          {environment.hot_tier
            ? `${formatDay(environment.hot_tier.start)} to ${formatDay(environment.hot_tier.end)}`
            : "—"}
        </dd>
        <dt>PostgreSQL window (12 months)</dt>
        <dd>
          {environment.postgresql_window
            ? `${formatDay(environment.postgresql_window.start)} to ${formatDay(environment.postgresql_window.end)}`
            : "—"}
        </dd>
        <dt>Core versus BGC</dt>
        <dd>
          Core Argo only (temperature, salinity, pressure); BGC parameters
          arrive after v1.
        </dd>
      </dl>
    </Panel>
  );
}
