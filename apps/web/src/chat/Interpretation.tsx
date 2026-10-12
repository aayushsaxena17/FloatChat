import { useId, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Interpretation as InterpretationData } from "./client";

const LABELS: Record<string, string> = {
  time_range: "Period",
  geography: "Area",
  depth_dbar: "Depth",
  variables: "Variables",
  qc_policy: "QC policy",
  operation: "Operation",
  presentation: "Presentation",
};

function describeGeography(value: unknown): string {
  if (!value || typeof value !== "object") return "—";
  const geography = value as Record<string, unknown>;
  if (geography.kind === "named_region") return String(geography.value);
  if (geography.kind === "bbox")
    return `box ${geography.west}–${geography.east}°E, ${geography.south}–${geography.north}°N`;
  if (geography.kind === "point_radius")
    return `${geography.latitude}°N, ${geography.longitude}°E within ${geography.radius_km} km`;
  return JSON.stringify(value);
}

function describeOperation(value: unknown): string {
  if (!value || typeof value !== "object") return "—";
  const operation = value as Record<string, unknown>;
  if (operation.kind === "aggregate") {
    const keys = (operation.group_by as string[] | undefined) ?? [];
    const metrics = (operation.metrics as string[] | undefined) ?? [];
    return `aggregate ${metrics.join(", ")}${keys.length ? ` by ${keys.join(", ")}` : ""} per ${operation.unit ?? "profile"}${operation.depth_bin_size ? ` (${operation.depth_bin_size} dbar bins)` : ""}`;
  }
  if (operation.kind === "profiles")
    return `profiles, limit ${operation.limit}`;
  if (operation.kind === "nearest")
    return `${operation.k} nearest within ${operation.radius_km} km of ${operation.latitude}°N, ${operation.longitude}°E`;
  return JSON.stringify(value);
}

export function planRows(plan: Record<string, unknown> | null | undefined) {
  if (!plan) return [] as Array<[string, string]>;
  const range = plan.time_range as { start?: string; end?: string } | undefined;
  const depth = plan.depth_dbar as
    | { min?: number; max?: number }
    | null
    | undefined;
  const presentation = plan.presentation as
    | { kind?: string; bins?: number | null }
    | undefined;
  const rows: Array<[string, string]> = [
    [
      LABELS.time_range,
      range ? `${range.start} to ${range.end} (end exclusive)` : "—",
    ],
    [LABELS.geography, describeGeography(plan.geography)],
    [
      LABELS.depth_dbar,
      depth ? `${depth.min} to ${depth.max} dbar` : "whole water column",
    ],
    [
      LABELS.variables,
      ((plan.variables as string[] | undefined) ?? []).join(", ") || "—",
    ],
    [LABELS.qc_policy, String(plan.qc_policy ?? "science_ready")],
    [LABELS.operation, describeOperation(plan.operation)],
    [
      LABELS.presentation,
      presentation
        ? `${presentation.kind}${presentation.bins ? ` (${presentation.bins} bins)` : ""}`
        : "table",
    ],
  ];
  return rows;
}

/** PRD 9.2: "How FloatChat interpreted your request", so a wrong region, variable, depth or
 * aggregation is visible before the numbers are trusted. */
export function Interpretation({
  data,
  open = false,
}: {
  data: InterpretationData;
  open?: boolean;
}) {
  const [expanded, setExpanded] = useState(open);
  const id = useId();
  const rows = planRows(data.plan);
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <section
      className="interpretation"
      aria-labelledby={id}
      data-testid="interpretation"
    >
      <button
        type="button"
        className="interpretation-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <Icon size={14} aria-hidden="true" />
        <span id={id}>How FloatChat interpreted your request</span>
        <span className="interpretation-model">
          {data.provider}/{data.model}
          {data.provider === "offline" ? " (rule-based, not an LLM)" : ""}
        </span>
      </button>
      {expanded ? (
        <div className="interpretation-body">
          {rows.length ? (
            <dl className="interpretation-grid">
              {rows.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
              {data.transformation ? (
                <div>
                  <dt>Transformation</dt>
                  <dd>{data.transformation}</dd>
                </div>
              ) : null}
            </dl>
          ) : null}
          {data.clarification ? (
            <p className="interpretation-note">
              Missing: {data.clarification.missing.join(", ")}
            </p>
          ) : null}
          {data.validation && data.validation.length ? (
            <ul className="interpretation-note">
              {data.validation.map((detail, index) => (
                <li key={index}>
                  {detail.field}: {detail.message} [{detail.code}]
                </li>
              ))}
            </ul>
          ) : null}
          <dl className="interpretation-grid interpretation-meta">
            <div>
              <dt>Prompt</dt>
              <dd>
                {data.prompt_version} · narrator {data.narrator_version} ·
                retrieval {data.retrieval_mode}
              </dd>
            </div>
            <div>
              <dt>Embedding</dt>
              <dd>{data.embedding_model}</dd>
            </div>
            <div>
              <dt>Narrative</dt>
              <dd>
                {data.narrative_source ?? "—"}
                {data.narrative_rejected
                  ? " (model text rejected: ungrounded numbers)"
                  : ""}
                {data.narration_error
                  ? ` (narration ${data.narration_error})`
                  : ""}
              </dd>
            </div>
            <div>
              <dt>Reference time</dt>
              <dd>{data.reference_time ?? "—"}</dd>
            </div>
            {data.timings ? (
              <div>
                <dt>Timings (ms)</dt>
                <dd>
                  {Object.entries(data.timings)
                    .map(([step, ms]) => `${step} ${ms}`)
                    .join(" · ")}
                </dd>
              </div>
            ) : null}
            {data.tokens ? (
              <div>
                <dt>Tokens</dt>
                <dd>
                  {Object.entries(data.tokens)
                    .map(([name, count]) => `${name} ${count}`)
                    .join(" · ")}
                </dd>
              </div>
            ) : null}
          </dl>
          {data.retrieved && data.retrieved.length ? (
            <details className="interpretation-docs">
              <summary>
                Retrieved documents ({data.retrieved.length}
                {data.examples?.length
                  ? ` + ${data.examples.length} examples`
                  : ""}
                )
              </summary>
              <ul>
                {[...data.retrieved, ...(data.examples ?? [])].map((hit) => (
                  <li key={hit.id}>
                    <code>{hit.id}</code> {hit.title}{" "}
                    <span>({hit.score.toFixed(3)})</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {data.plan ? (
            <details className="interpretation-docs">
              <summary>
                Validated plan (stage2-plan-v1
                {data.plan_sha256
                  ? `, sha256 ${String(data.plan_sha256).slice(0, 12)}…`
                  : ""}
                )
              </summary>
              <pre>{JSON.stringify(data.plan, null, 2)}</pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
