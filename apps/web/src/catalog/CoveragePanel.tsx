import type { CoverageResponse } from "../api/types";
import { formatDay, formatNumber, formatUtc } from "../catalog/units";
import { Panel } from "../components/Panel";
import { Badge } from "../components/ui/badge";
import { DetailsDialog } from "../components/DetailsDialog";
import { CheckCircle2, AlertCircle, Database } from "lucide-react";

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
    <Badge
      variant="outline"
      className="badge"
      data-kind={summary.partial ? "partial" : "complete"}
    >
      {summary.partial ? "partial coverage" : "coverage complete"}
    </Badge>
  );
  return (
    <Panel title="Coverage" badge={badge} className="coverage">
      <div className="coverage-explanation">
        {summary.partial ? (
          <AlertCircle size={20} aria-hidden="true" />
        ) : (
          <CheckCircle2 size={20} aria-hidden="true" />
        )}
        <div>
          <h3>
            {summary.partial
              ? "Some source data is missing"
              : "All expected slots checked"}
          </h3>
          <p>
            Each slot is one month in a 10° geographic tile. Checked empty areas
            count as complete; this does not mean the whole ocean was sampled.
          </p>
        </div>
      </div>
      <div
        className="coverage-bar"
        role="img"
        aria-label={`${summary.slots_covered} slots with data, ${summary.slots_empty_verified} verified empty, ${summary.slots_missing} missing`}
      >
        <span
          className="slots-data"
          style={{
            width: `${summary.slots_total ? (summary.slots_covered / summary.slots_total) * 100 : 0}%`,
          }}
        />
        <span
          className="slots-empty"
          style={{
            width: `${summary.slots_total ? (summary.slots_empty_verified / summary.slots_total) * 100 : 0}%`,
          }}
        />
        <span
          className="slots-missing"
          style={{
            width: `${summary.slots_total ? (summary.slots_missing / summary.slots_total) * 100 : 0}%`,
          }}
        />
      </div>
      <div className="coverage-legend">
        <span>
          <i className="slots-data" />
          {summary.slots_covered} with data
        </span>
        <span>
          <i className="slots-empty" />
          {summary.slots_empty_verified} empty
        </span>
        <span>
          <i className="slots-missing" />
          {summary.slots_missing} missing
        </span>
      </div>
      <div className="coverage-scope">
        <span>Selected region</span>
        <strong>{geography.name ?? geography.kind}</strong>
        <span>Observation period · UTC</span>
        <strong>
          {formatDay(summary.requested.start)} to{" "}
          {formatDay(summary.requested.end)}
        </strong>
        <small>Start included · end excluded</small>
      </div>
      {summary.partial ? (
        <p className="coverage-warning" role="status">
          Results may be incomplete. Review missing slots before drawing
          conclusions. Open Coverage & ingestion details to see the missing
          areas.
        </p>
      ) : null}
      <div className="coverage-source">
        <Database size={16} aria-hidden="true" />
        <div>
          <strong>Argo GDAC via Argovis</strong>
          <span>Core Argo · temperature, salinity & pressure</span>
        </div>
      </div>
      <div className="coverage-details">
        <DetailsDialog
          title="Coverage & ingestion details"
          description="Source records, geographic coverage and ingestion history for this selection. Totals are measured before pressure and quality filtering."
        >
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
            <dd>
              argovis (Argo GDAC through Argovis); population argovis-core-v1
            </dd>
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
        </DetailsDialog>
      </div>
    </Panel>
  );
}
