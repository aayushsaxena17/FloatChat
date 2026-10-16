import { useNavigate } from "react-router";
import { Download } from "lucide-react";
import { describeError } from "../api/hooks";
import type { ExportRequestBody } from "../jobs/client";
import { useCreateExport } from "../jobs/useJobs";

export type JobOfferPayload = Omit<ExportRequestBody, "format">;

/** The assistant offered to run a long request as an export job (ADR-0081). */
export function JobOffer({ offer }: { offer: JobOfferPayload }) {
  const create = useCreateExport();
  const navigate = useNavigate();
  const start = (format: "csv" | "parquet") =>
    create.mutate(
      { ...offer, format },
      { onSuccess: (created) => void navigate(`/jobs/${created.job.id}`) },
    );
  return (
    <div className="chat-offer" role="group" aria-label="Run as an export job">
      <Download size={16} aria-hidden="true" />
      <span>Run it as a background export</span>
      <button
        type="button"
        className="chat-chip"
        onClick={() => start("parquet")}
        disabled={create.isPending}
      >
        Parquet
      </button>
      <button
        type="button"
        className="chat-chip"
        onClick={() => start("csv")}
        disabled={create.isPending}
      >
        CSV
      </button>
      {create.error ? (
        <p className="chat-offer-error" role="alert">
          {describeError(create.error).message}
        </p>
      ) : null}
    </div>
  );
}
