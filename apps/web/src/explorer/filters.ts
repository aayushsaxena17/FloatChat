// The filter model behind the URL (PRD 14.3: search parameters own shareable filters).
// Pure functions: parsing, validation, serialisation and the API/plan documents they produce.
import type { QueryPlan } from "../api/client";
import type { Environment } from "../api/types";

export const QC_POLICIES = ["science_ready", "mode_selected", "raw"] as const;
export type QcPolicyName = (typeof QC_POLICIES)[number];
export const VARIABLES = ["temperature", "salinity"] as const;
export type Variable = (typeof VARIABLES)[number];
export const DEFAULT_REGION = "Indian Ocean";
export const MAX_DEPTH_DBAR = 12000;
/** Profile charts are bounded to chart_series (20) profiles per request. */
export const TS_PROFILE_LIMIT = 20;
export const HISTOGRAM_BINS = 40;

export interface Filters {
  region: string;
  /** UTC calendar day, inclusive. */
  start: string | null;
  /** UTC calendar day, exclusive. */
  end: string | null;
  depthMin: number | null;
  depthMax: number | null;
  qc: QcPolicyName;
  platform: string | null;
  profile: string | null;
  variable: Variable;
}

export type FilterErrors = Partial<Record<keyof Filters, string>>;

const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function isDay(value: string | null): value is string {
  if (value === null || !DAY.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(value)
  );
}

function numberOrNull(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

/** Defaults come from the environment's hot tier when the URL carries no dates. */
export function defaultRange(environment: Environment | undefined): {
  start: string | null;
  end: string | null;
} {
  const tier = environment?.hot_tier;
  if (!tier?.start || !tier?.end) return { start: null, end: null };
  return { start: tier.start.slice(0, 10), end: tier.end.slice(0, 10) };
}

export function parseFilters(
  params: URLSearchParams,
  environment?: Environment,
): Filters {
  const range = defaultRange(environment);
  const qc = params.get("qc");
  const variable = params.get("variable");
  return {
    region: params.get("region") ?? DEFAULT_REGION,
    start: params.get("start") ?? range.start,
    end: params.get("end") ?? range.end,
    depthMin: numberOrNull(params.get("depth_min")),
    depthMax: numberOrNull(params.get("depth_max")),
    qc: (QC_POLICIES as readonly string[]).includes(qc ?? "")
      ? (qc as QcPolicyName)
      : "science_ready",
    platform: params.get("platform"),
    profile: params.get("profile"),
    variable: (VARIABLES as readonly string[]).includes(variable ?? "")
      ? (variable as Variable)
      : "temperature",
  };
}

/** Every explicit value is written so a copied URL reproduces the view. */
export function toSearchParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams();
  params.set("region", filters.region);
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.depthMin !== null && !Number.isNaN(filters.depthMin))
    params.set("depth_min", String(filters.depthMin));
  if (filters.depthMax !== null && !Number.isNaN(filters.depthMax))
    params.set("depth_max", String(filters.depthMax));
  params.set("qc", filters.qc);
  if (filters.platform) params.set("platform", filters.platform);
  if (filters.profile) params.set("profile", filters.profile);
  if (filters.variable !== "temperature")
    params.set("variable", filters.variable);
  return params;
}

export function validateFilters(filters: Filters): FilterErrors {
  const errors: FilterErrors = {};
  if (!filters.region.trim()) errors.region = "Choose a region.";
  if (filters.start !== null && !isDay(filters.start))
    errors.start = "Use a UTC day as YYYY-MM-DD.";
  if (filters.end !== null && !isDay(filters.end))
    errors.end = "Use a UTC day as YYYY-MM-DD.";
  if (isDay(filters.start) && isDay(filters.end)) {
    if (filters.start >= filters.end)
      errors.end =
        "The end day must be after the start day (end is exclusive).";
    else if (daysBetween(filters.start, filters.end) > 366)
      errors.end = "The range is bounded to 366 days.";
  }
  const depth = (value: number | null) =>
    value === null ||
    (!Number.isNaN(value) && value >= 0 && value <= MAX_DEPTH_DBAR);
  if (!depth(filters.depthMin))
    errors.depthMin = `Pressure must be between 0 and ${MAX_DEPTH_DBAR} dbar.`;
  if (!depth(filters.depthMax) || filters.depthMax === 0)
    errors.depthMax = `Pressure must be between 0 and ${MAX_DEPTH_DBAR} dbar.`;
  if (
    filters.depthMin !== null &&
    filters.depthMax !== null &&
    !errors.depthMin &&
    !errors.depthMax &&
    filters.depthMin >= filters.depthMax
  )
    errors.depthMax = "The maximum pressure must exceed the minimum.";
  return errors;
}

export function daysBetween(start: string, end: string): number {
  return (
    (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
    86_400_000
  );
}

/** True when the filters can be sent (dates known and nothing invalid). */
export function isReady(filters: Filters): boolean {
  return (
    isDay(filters.start) &&
    isDay(filters.end) &&
    Object.keys(validateFilters(filters)).length === 0
  );
}

export type TimeRange = { start: string; end: string };

export function timeRange(filters: Filters): TimeRange | null {
  if (!isDay(filters.start) || !isDay(filters.end)) return null;
  return {
    start: `${filters.start}T00:00:00Z`,
    end: `${filters.end}T00:00:00Z`,
  };
}

function depthRange(filters: Filters): { min: number; max: number } | null {
  if (filters.depthMax === null && filters.depthMin === null) return null;
  return {
    min: filters.depthMin ?? 0,
    max: filters.depthMax ?? MAX_DEPTH_DBAR,
  };
}

export type ReadParams = {
  start?: string;
  end?: string;
  region: string;
  depth_min?: number;
  depth_max?: number;
  qc_policy: QcPolicyName;
};

/** Query parameters of the read endpoints for these filters. */
export function toReadParams(filters: Filters): ReadParams {
  const range = timeRange(filters);
  const depth = depthRange(filters);
  return {
    start: range?.start,
    end: range?.end,
    region: filters.region,
    depth_min: depth?.min,
    depth_max: depth?.max,
    qc_policy: filters.qc,
  };
}

const base = (
  filters: Filters,
): Pick<QueryPlan, "time_range" | "geography" | "depth_dbar"> => {
  const range = timeRange(filters);
  if (range === null) throw new Error("filters need a start and end day");
  const depth = depthRange(filters);
  return {
    time_range: range,
    geography: { kind: "named_region", value: filters.region },
    depth_dbar: depth ?? undefined,
  };
};

/** Monthly (or daily, for ranges within 31 days) mean and count of both variables. */
export function timeSeriesPlan(filters: Filters): QueryPlan {
  const daily =
    isDay(filters.start) &&
    isDay(filters.end) &&
    daysBetween(filters.start, filters.end) <= 31;
  return {
    ...base(filters),
    variables: ["temperature", "salinity"],
    qc_policy: filters.qc === "raw" ? "science_ready" : filters.qc,
    operation: {
      kind: "aggregate",
      group_by: [daily ? "day" : "month"],
      metrics: ["mean", "count"],
      unit: "profile",
    },
    presentation: { kind: "line_chart" },
  };
}

/** One value per profile in the depth band, binned. */
export function histogramPlan(filters: Filters): QueryPlan {
  return {
    ...base(filters),
    variables: [filters.variable],
    qc_policy: filters.qc === "raw" ? "science_ready" : filters.qc,
    operation: {
      kind: "aggregate",
      group_by: ["profile"],
      metrics: ["mean"],
      unit: "profile",
    },
    presentation: { kind: "histogram", bins: HISTOGRAM_BINS },
  };
}

/** The newest profiles' levels as a temperature-salinity diagram (bounded to 20 profiles). */
export function tsDiagramPlan(filters: Filters): QueryPlan {
  return {
    ...base(filters),
    variables: ["temperature", "salinity", "pressure"],
    qc_policy: filters.qc,
    operation: { kind: "profiles", limit: TS_PROFILE_LIMIT },
    presentation: { kind: "ts_diagram" },
  };
}
