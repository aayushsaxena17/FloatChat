// Plain-language descriptions of job records for the list and the detail page.
import { formatDay, formatNumber } from "../catalog/units";
import type { JobChunkRecord, JobRecord } from "./client";

export const STATE_LABELS: Record<string, string> = {
  queued: "Queued",
  fetching: "Fetching source data",
  exporting: "Writing the export",
  analysing: "Analysing",
  completed: "Completed",
  partial: "Completed with gaps",
  cancelled: "Cancelled",
  failed: "Failed",
};

export const CHUNK_LABELS: Record<string, string> = {
  pending: "waiting",
  running: "running",
  complete: "complete",
  reused: "already available",
  failed: "failed",
  cancelled: "cancelled",
};

/** The badge kind drives colour; the label always carries the meaning (ADR-0076). */
export function stateKind(state: string): "complete" | "partial" | "neutral" {
  if (state === "completed") return "complete";
  if (state === "partial" || state === "failed" || state === "cancelled")
    return "partial";
  return "neutral";
}

export function stateLabel(state: string): string {
  return STATE_LABELS[state] ?? state;
}

type Request = Record<string, unknown>;

function asRecord(value: unknown): Request {
  return typeof value === "object" && value !== null ? (value as Request) : {};
}

export function regionOf(request: Request): string {
  const geography = asRecord(request.geography);
  if (geography.kind === "named_region") return String(geography.value);
  if (geography.kind === "bbox")
    return `${geography.west}° to ${geography.east}° E, ${geography.south}° to ${geography.north}° N`;
  if (geography.kind === "point_radius")
    return `${geography.radius_km} km around ${geography.latitude}° N, ${geography.longitude}° E`;
  return "selected area";
}

export function periodOf(request: Request): string {
  const range = asRecord(request.time_range);
  const start = typeof range.start === "string" ? range.start : null;
  const end = typeof range.end === "string" ? range.end : null;
  if (!start || !end) return "selected period";
  return `${formatDay(start.slice(0, 10))} to ${formatDay(end.slice(0, 10))}`;
}

export function depthOf(request: Request): string {
  const depth = asRecord(request.depth_dbar);
  if (depth.max === undefined) return "all depths";
  return `${formatNumber(Number(depth.min ?? 0), 0)} to ${formatNumber(Number(depth.max), 0)} dbar`;
}

export function variablesOf(request: Request): string {
  const variables = Array.isArray(request.variables)
    ? (request.variables as string[])
    : [];
  return variables.length
    ? variables.join(", ")
    : "temperature, salinity, pressure";
}

export function titleOf(job: Pick<JobRecord, "request" | "kind">): string {
  const request = asRecord(job.request);
  const format = String(request.format ?? "").toUpperCase();
  return `${format} export, ${regionOf(request)}`;
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

/** One line of progress for the list: chunk counts and the reuse ratio when known. */
export function progressLine(job: JobRecord): string {
  const progress = asRecord(job.progress);
  const total = Number(progress.fetch_total ?? 0);
  const complete = Number(progress.fetch_complete ?? 0);
  const failed = Number(progress.fetch_failed ?? 0);
  const reuse = progress.reuse_ratio;
  const parts: string[] = [];
  if (total > 0)
    parts.push(
      `${complete} of ${total} source ${total === 1 ? "chunk" : "chunks"} fetched` +
        (failed ? `, ${failed} failed` : ""),
    );
  if (typeof reuse === "number")
    parts.push(
      `${Math.round(reuse * 100)}% of the months were already available`,
    );
  return parts.join(" · ");
}

export function chunkOutcome(chunk: JobChunkRecord): string {
  const evidence = asRecord(chunk.evidence);
  const bits: string[] = [];
  if (chunk.kind === "fetch") {
    if (typeof evidence.accepted_profiles === "number")
      bits.push(`${formatNumber(evidence.accepted_profiles, 0)} profiles`);
    if (typeof evidence.http_attempts === "number")
      bits.push(`${formatNumber(evidence.http_attempts, 0)} requests`);
    if (typeof evidence.http_retries === "number" && evidence.http_retries > 0)
      bits.push(`${evidence.http_retries} retried`);
    const missing = Array.isArray(evidence.missing_chunks)
      ? evidence.missing_chunks.length
      : 0;
    if (missing) bits.push(`${missing} source chunks missing`);
  } else if (typeof evidence.rows === "number") {
    bits.push(`${formatNumber(evidence.rows, 0)} rows`);
    if (typeof evidence.profiles === "number")
      bits.push(`${formatNumber(evidence.profiles, 0)} profiles`);
  }
  if (chunk.error && typeof chunk.error.message === "string")
    bits.push(chunk.error.message);
  return bits.join(" · ");
}
