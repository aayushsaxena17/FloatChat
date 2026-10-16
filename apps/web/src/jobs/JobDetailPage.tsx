import { Link, useParams } from "react-router";
import { AlertCircle, Download, FileText } from "lucide-react";
import { describeError } from "../api/hooks";
import { formatNumber, formatUtc } from "../catalog/units";
import { Panel } from "../components/Panel";
import { StatusMessage } from "../components/StatusMessage";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { DetailsDialog } from "../components/DetailsDialog";
import type { ArtefactRecord, JobChunkRecord } from "./client";
import {
  CHUNK_LABELS,
  chunkOutcome,
  depthOf,
  formatBytes,
  periodOf,
  regionOf,
  stateKind,
  stateLabel,
  titleOf,
  variablesOf,
} from "./format";
import { isActive, useCancelJob, useJob } from "./useJobs";

const CITATION =
  "Argo (2000). Argo float data and metadata from Global Data Assembly Centre (Argo GDAC). SEANOE. https://doi.org/10.17882/42182";

function ChunkTable({ chunks }: { chunks: JobChunkRecord[] }) {
  if (chunks.length === 0)
    return (
      <p className="status" role="status">
        The job has not been planned yet. Planning compares the request with the
        months already in the catalogue.
      </p>
    );
  return (
    <div className="table-wrap">
      <table className="data">
        <caption className="sr-only">Chunks of this job</caption>
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col">Months</th>
            <th scope="col">State</th>
            <th scope="col">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {chunks.map((chunk) => (
            <tr key={chunk.id} data-state={chunk.state}>
              <td>{chunk.kind === "fetch" ? "Fetch" : "Export"}</td>
              <td>
                {chunk.kind === "fetch" ? chunk.label : "requested period"}
              </td>
              <td>{CHUNK_LABELS[chunk.state] ?? chunk.state}</td>
              <td className="chunk-outcome">{chunkOutcome(chunk) || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArtefactCard({ artefact }: { artefact: ArtefactRecord }) {
  const label =
    artefact.role === "data"
      ? `${artefact.format.toUpperCase()} data`
      : artefact.role === "manifest"
        ? "Manifest"
        : "Provenance";
  return (
    <li className="artefact">
      <div className="artefact-head">
        <FileText size={18} aria-hidden="true" />
        <div>
          <h3>{label}</h3>
          <p className="chart-caption">{artefact.filename}</p>
        </div>
        {artefact.download_url ? (
          <Button asChild size="sm">
            <a href={artefact.download_url} download={artefact.filename}>
              <Download aria-hidden="true" />
              Download
            </a>
          </Button>
        ) : (
          <span className="chart-caption">
            {artefact.state === "available" ? "Link unavailable" : "Expired"}
          </span>
        )}
      </div>
      <dl className="facts">
        <dt>Size</dt>
        <dd>{formatBytes(artefact.bytes)}</dd>
        {artefact.role === "data" ? (
          <>
            <dt>Rows</dt>
            <dd>{formatNumber(artefact.row_count, 0)} measurement levels</dd>
            <dt>Profiles</dt>
            <dd>{formatNumber(artefact.profile_count, 0)}</dd>
          </>
        ) : null}
        <dt>SHA-256</dt>
        <dd>
          <code>{artefact.sha256}</code>
        </dd>
        <dt>Created</dt>
        <dd>{formatUtc(artefact.created_at)}</dd>
        <dt>Expires</dt>
        <dd>{formatUtc(artefact.expires_at)}</dd>
      </dl>
    </li>
  );
}

export function JobDetailPage() {
  const { jobId } = useParams();
  const detail = useJob(jobId);
  const cancel = useCancelJob(jobId ?? "");
  const job = detail.data?.job;
  const request = (job?.request ?? {}) as Record<string, unknown>;
  const missing = Array.isArray(
    (job?.result as Record<string, unknown> | undefined)?.missing_slots,
  )
    ? ((job?.result as Record<string, unknown>).missing_slots as Array<{
        month: string;
      }>)
    : [];
  const missingMonths = [...new Set(missing.map((slot) => slot.month))].sort();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="chart-caption">
            <Link to="/jobs">Jobs</Link>
          </p>
          <h1>{job ? titleOf(job) : "Job"}</h1>
          {job ? (
            <p className="page-description">
              {periodOf(request)} · {depthOf(request)} · {variablesOf(request)}
              {" · "}
              {String(request.qc_policy ?? "science_ready").replace("_", " ")}
            </p>
          ) : null}
        </div>
        {job ? (
          <div className="job-actions">
            <Badge
              variant="outline"
              className="badge"
              data-kind={stateKind(job.state)}
            >
              {stateLabel(job.state)}
            </Badge>
            {isActive(job) && !job.cancel_requested_at ? (
              <Button
                variant="outline"
                onClick={() => cancel.mutate(job.version)}
                disabled={cancel.isPending}
              >
                Cancel job
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
      <StatusMessage loading={detail.isPending} error={detail.error}>
        {job ? (
          <div className="job-detail">
            {cancel.error ? (
              <p className="status" data-kind="error" role="alert">
                {describeError(cancel.error).message}
              </p>
            ) : null}
            {job.cancel_requested_at && isActive(job) ? (
              <p className="status" role="status">
                Cancellation requested; the current step finishes first.
              </p>
            ) : null}
            {job.error ? (
              <p className="status" data-kind="error" role="alert">
                <AlertCircle size={18} aria-hidden="true" />
                {String(
                  job.error.message ?? job.error.code ?? "The job failed.",
                )}
              </p>
            ) : null}
            {job.state === "partial" ? (
              <p className="status" role="status">
                <AlertCircle size={18} aria-hidden="true" />
                Some months could not be fetched from the source
                {missingMonths.length
                  ? `: ${missingMonths.slice(0, 12).join(", ")}${missingMonths.length > 12 ? ` and ${missingMonths.length - 12} more` : ""}`
                  : ""}
                . The export covers what is available; the manifest lists the
                gaps. Re-run the request later to fill them.
              </p>
            ) : null}
            <Panel title="Progress">
              <dl className="facts">
                <dt>Region</dt>
                <dd>{regionOf(request)}</dd>
                <dt>Created</dt>
                <dd>{formatUtc(job.created_at)}</dd>
                {job.started_at ? (
                  <>
                    <dt>Started</dt>
                    <dd>{formatUtc(job.started_at)}</dd>
                  </>
                ) : null}
                {job.finished_at ? (
                  <>
                    <dt>Finished</dt>
                    <dd>{formatUtc(job.finished_at)}</dd>
                  </>
                ) : null}
                {typeof job.progress.slots_total === "number" ? (
                  <>
                    <dt>Months × tiles</dt>
                    <dd>
                      {formatNumber(Number(job.progress.slots_total), 0)}{" "}
                      required,{" "}
                      {formatNumber(Number(job.progress.slots_reused ?? 0), 0)}{" "}
                      already in the catalogue
                    </dd>
                  </>
                ) : null}
              </dl>
              <div style={{ marginTop: 14 }}>
                <ChunkTable chunks={detail.data?.chunks ?? []} />
              </div>
            </Panel>
            <Panel title="Downloads">
              {detail.data?.artefacts.length ? (
                <ul className="artefact-list">
                  {detail.data.artefacts.map((artefact) => (
                    <ArtefactCard key={artefact.id} artefact={artefact} />
                  ))}
                </ul>
              ) : (
                <p className="status" role="status">
                  {isActive(job)
                    ? "Files appear here when the export step finishes."
                    : "This job produced no files."}
                </p>
              )}
              <p className="chart-caption" style={{ marginTop: 12 }}>
                Cite the data as: {CITATION}. Download links are valid for
                fifteen minutes; reload the page for a fresh one.
              </p>
            </Panel>
            <DetailsDialog
              title="Request and plan"
              description="The export request as stored and the validated query plan behind it."
            >
              <pre className="json">
                {JSON.stringify(
                  { request: job.request, plan: job.plan },
                  null,
                  2,
                )}
              </pre>
            </DetailsDialog>
          </div>
        ) : null}
      </StatusMessage>
    </>
  );
}
