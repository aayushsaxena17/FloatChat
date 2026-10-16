// Jobs API client (Stage 5, ADR-0079, ADR-0081): export creation, job reads, cancellation and
// the progress stream. Jobs are scoped to the browser's client identifier, the same one the
// chat uses, so the stream is read over fetch (EventSource cannot send the header).
import { ApiError, buildUrl, CORRELATION_HEADER } from "../api/client";
import type { components } from "../api/schema";
import { CLIENT_HEADER, clientId } from "../chat/client";

export type JobRecord = components["schemas"]["JobRecord"];
export type JobChunkRecord = components["schemas"]["JobChunkRecord"];
export type ArtefactRecord = components["schemas"]["ArtefactRecord"];
export type JobDetail = components["schemas"]["JobDetail"];
export type JobCreated = components["schemas"]["JobCreated"];
export type ExportRequestBody = components["schemas"]["ExportRequestBody"];

export interface JobEvent {
  seq: number;
  kind: string;
  data: Record<string, unknown> & { job_state?: string | null };
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { Accept: "application/json", [CLIENT_HEADER]: clientId(), ...extra };
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const parsed: unknown = await response.json().catch(() => null);
    const envelope =
      parsed && typeof parsed === "object" && "error" in parsed
        ? (parsed as ApiError["envelope"])
        : null;
    throw new ApiError(
      response.status,
      envelope,
      response.headers.get(CORRELATION_HEADER),
    );
  }
  return (await response.json()) as T;
}

export async function createExport(
  body: ExportRequestBody,
  signal?: AbortSignal,
): Promise<JobCreated> {
  const response = await fetch(buildUrl("/exports"), {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal,
  });
  return readJson<JobCreated>(response);
}

export async function listJobs(signal?: AbortSignal): Promise<JobRecord[]> {
  const response = await fetch(buildUrl("/jobs", { limit: 100 }), {
    headers: headers(),
    signal,
  });
  const body = await readJson<{ jobs: JobRecord[] }>(response);
  return body.jobs;
}

export async function getJob(
  id: string,
  signal?: AbortSignal,
): Promise<JobDetail> {
  const response = await fetch(buildUrl(`/jobs/${encodeURIComponent(id)}`), {
    headers: headers(),
    signal,
  });
  return readJson<JobDetail>(response);
}

export async function cancelJob(
  id: string,
  version: number,
): Promise<JobRecord> {
  const response = await fetch(
    buildUrl(`/jobs/${encodeURIComponent(id)}/cancel`),
    {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ version }),
    },
  );
  const body = await readJson<{ job: JobRecord }>(response);
  return body.job;
}

/** Parses complete SSE blocks with their `id:` lines; comments (keep-alives) are skipped. */
export function parseJobSse(buffer: string): {
  events: JobEvent[];
  rest: string;
} {
  const events: JobEvent[] = [];
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let kind = "";
    let seq = 0;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) kind = line.slice(6).trim();
      else if (line.startsWith("id:")) seq = Number(line.slice(3).trim()) || 0;
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (!kind || data.length === 0) continue;
    try {
      events.push({
        seq,
        kind,
        data: JSON.parse(data.join("\n")) as JobEvent["data"],
      });
    } catch {
      // A malformed block is dropped; the job detail is re-read on every event anyway.
    }
  }
  return { events, rest };
}

/**
 * Follow a job's progress events until the stream ends (a terminal event) or `signal` aborts.
 * `after` resumes from the last sequence number seen, as `Last-Event-ID` would.
 */
export async function streamJobEvents(
  id: string,
  onEvent: (event: JobEvent) => void,
  signal: AbortSignal,
  after = 0,
): Promise<void> {
  const response = await fetch(
    buildUrl(`/jobs/${encodeURIComponent(id)}/events`, { after }),
    { headers: headers({ Accept: "text/event-stream" }), signal },
  );
  if (!response.ok || !response.body) {
    const parsed: unknown = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      parsed && typeof parsed === "object" && "error" in parsed
        ? (parsed as ApiError["envelope"])
        : null,
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseJobSse(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
}
