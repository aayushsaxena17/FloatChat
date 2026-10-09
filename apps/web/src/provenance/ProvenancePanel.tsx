import { useState } from "react";
import type { Provenance } from "../api/types";
import { formatUtc } from "../catalog/units";

function Facts({ entries }: { entries: Array<[string, React.ReactNode]> }) {
  return (
    <dl className="facts">
      {entries.map(([term, value]) => (
        <div key={term} style={{ display: "contents" }}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function geographyText(provenance: Provenance): string {
  const geography = provenance.geography;
  if (!geography) return "none (every float of the environment)";
  if (geography.kind === "named_region")
    return `${geography.name} (${geography.version}${geography.clipped ? ", clipped" : ""}; SHA-256 ${geography.sha256?.slice(0, 12)}…)`;
  if (geography.kind === "bbox")
    return (geography.boxes ?? [])
      .map((box) => `${box.west}–${box.east}°E, ${box.south}–${box.north}°N`)
      .join(" and ");
  return `${geography.longitude}°E, ${geography.latitude}°N, radius ${geography.radius_m} m`;
}

/** The PRD 17 provenance object of a result, on every result (ADR-0064). */
export function ProvenancePanel({
  provenance,
  open = false,
}: {
  provenance: Provenance;
  open?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const versions = provenance.versions as Record<string, unknown>;
  const region = versions.region as
    | { name?: string; version?: string }
    | undefined;
  const execution = provenance.execution;
  const environment = provenance.environment;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(provenance, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <details className="provenance" open={open} data-testid="provenance">
      <summary>Provenance (PRD §17)</summary>
      <Facts
        entries={[
          ["Source", `${provenance.source} (${versions.mapping as string})`],
          [
            "Environment",
            `${environment.name} (${environment.mode}); reference time ${formatUtc(environment.reference_time)}`,
          ],
          [
            "Ingested",
            `${formatUtc(environment.ingested_at)}; run ${environment.latest_run ?? "—"}`,
          ],
          [
            "Source retrieved",
            environment.source_retrieved
              ? `${formatUtc(environment.source_retrieved.start)} to ${formatUtc(environment.source_retrieved.end)}`
              : "—",
          ],
          ["Geography", geographyText(provenance)],
          [
            "Coverage",
            provenance.coverage
              ? `${provenance.coverage.slots_covered} of ${provenance.coverage.slots_total} slots covered, ${provenance.coverage.slots_missing} missing${provenance.coverage.partial ? " (partial)" : ""}; ${provenance.coverage.estimated_profiles.toLocaleString("en-GB")} profiles, ${provenance.coverage.estimated_levels.toLocaleString("en-GB")} levels in the manifests`
              : "not resolved for a read",
          ],
          [
            "QC policy",
            (versions.qc_policy as string | undefined) ?? "none (read)",
          ],
          [
            "Versions",
            `hash ${versions.hash as string}; qc ${versions.qc as string}; geometry ${versions.geometry as string}; schema ${versions.schema as string}; plan ${versions.plan_schema as string}${region ? `; region ${region.name} ${region.version}` : ""}`,
          ],
          ["Transformation", provenance.transformation],
          [
            "Execution",
            `${execution.source ?? "—"}${execution.elapsed_ms !== undefined && execution.elapsed_ms !== null ? `, ${execution.elapsed_ms} ms` : ""}${execution.rows !== undefined && execution.rows !== null ? `, ${execution.rows} rows` : ""}${execution.run_ids ? `; runs ${execution.run_ids.join(", ")}` : ""}${execution.partitions ? `; ${execution.partitions.length} partitions` : ""}`,
          ],
          ["Plan SHA-256", provenance.plan_sha256 ?? "none (read)"],
          ["Result SHA-256", provenance.result_sha256],
          ["Application commit", provenance.application_commit],
          [
            "Attribution",
            `${provenance.attribution.argo} · ${provenance.attribution.argovis}`,
          ],
        ]}
      />
      <p>
        <button type="button" onClick={copy}>
          {copied ? "Copied" : "Copy JSON"}
        </button>
      </p>
    </details>
  );
}
