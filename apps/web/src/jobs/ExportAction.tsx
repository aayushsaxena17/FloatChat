import { useState } from "react";
import { useNavigate } from "react-router";
import { Download } from "lucide-react";
import { describeError } from "../api/hooks";
import { Button } from "../components/ui/button";
import {
  NativeSelect,
  NativeSelectOption,
} from "../components/ui/native-select";
import {
  daysBetween,
  isDay,
  timeRange,
  validateFilters,
  type Filters,
} from "../explorer/filters";
import type { ExportRequestBody } from "./client";
import { useCreateExport } from "./useJobs";

/** Exports take up to twenty years (JOBS_TIME_SPAN_DAYS), unlike the dashboard's 366 days. */
export const EXPORT_SPAN_DAYS = 7320;

/** Ready when the filters are valid apart from the dashboard's own span bound. */
export function exportReady(filters: Filters): boolean {
  if (!isDay(filters.start) || !isDay(filters.end)) return false;
  const errors = validateFilters(filters);
  const spanOnly = Object.entries(errors).every(
    ([key, message]) =>
      key === "end" && message?.startsWith("The range is bounded"),
  );
  return (
    spanOnly &&
    filters.start < filters.end &&
    daysBetween(filters.start, filters.end) <= EXPORT_SPAN_DAYS
  );
}

/** The export request for the current dashboard filters (export-request-v1, ADR-0081). */
export function exportRequest(
  filters: Filters,
  format: "csv" | "parquet",
): ExportRequestBody | null {
  const range = timeRange(filters);
  if (range === null) return null;
  const depth =
    filters.depthMin === null && filters.depthMax === null
      ? undefined
      : { min: filters.depthMin ?? 0, max: filters.depthMax ?? 12000 };
  return {
    time_range: range,
    geography: { kind: "named_region", value: filters.region },
    depth_dbar: depth,
    qc_policy: filters.qc,
    format,
  };
}

/** Creates an export job for the filters and opens it; identical requests attach (ADR-0079). */
export function ExportAction({ filters }: { filters: Filters }) {
  const [format, setFormat] = useState<"csv" | "parquet">("parquet");
  const create = useCreateExport();
  const navigate = useNavigate();
  const ready = exportReady(filters);
  const submit = () => {
    const body = exportRequest(filters, format);
    if (!body) return;
    create.mutate(body, {
      onSuccess: (created) => {
        void navigate(`/jobs/${created.job.id}`);
      },
    });
  };
  return (
    <div className="export-notice" data-kind="ready">
      <Download size={18} aria-hidden="true" />
      <div>
        <h2>Dataset export</h2>
        <p className="chart-caption">
          Every measurement level of the filtered profiles, with QC and
          data-mode columns, a manifest and provenance. Long periods fetch the
          missing months first and run in the background.
        </p>
        {create.error ? (
          <p className="status" data-kind="error" role="alert">
            {describeError(create.error).message}
          </p>
        ) : null}
      </div>
      <div className="export-actions">
        <NativeSelect
          aria-label="Export format"
          value={format}
          onChange={(event) =>
            setFormat(event.target.value === "csv" ? "csv" : "parquet")
          }
        >
          <NativeSelectOption value="parquet">Parquet</NativeSelectOption>
          <NativeSelectOption value="csv">CSV</NativeSelectOption>
        </NativeSelect>
        <Button
          type="button"
          variant="outline"
          onClick={submit}
          disabled={!ready || create.isPending}
        >
          Export filtered dataset
        </Button>
      </div>
    </div>
  );
}
