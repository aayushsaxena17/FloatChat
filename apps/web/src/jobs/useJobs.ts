// TanStack Query owns the job list and detail; the detail additionally follows the job's
// event stream while it is active and refetches on every event (PRD 14.3: jobs live on the
// server, the browser only observes them).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { retryPolicy } from "../api/hooks";
import {
  cancelJob,
  createExport,
  getJob,
  listJobs,
  streamJobEvents,
  type ExportRequestBody,
  type JobDetail,
  type JobRecord,
} from "./client";

export const ACTIVE_STATES = new Set([
  "queued",
  "fetching",
  "exporting",
  "analysing",
]);

export function isActive(job: Pick<JobRecord, "state"> | undefined): boolean {
  return job !== undefined && ACTIVE_STATES.has(job.state);
}

export function useJobs() {
  return useQuery<JobRecord[], Error>({
    queryKey: ["jobs"],
    queryFn: ({ signal }) => listJobs(signal),
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.some(isActive) ? 15_000 : false,
    retry: retryPolicy,
  });
}

export function useJob(id: string | undefined) {
  const client = useQueryClient();
  const query = useQuery<JobDetail, Error>({
    queryKey: ["jobs", id],
    queryFn: ({ signal }) => getJob(id as string, signal),
    enabled: Boolean(id),
    staleTime: 5_000,
    // A safety net under the stream: an active job is re-read every half minute anyway.
    refetchInterval: (query) =>
      isActive(query.state.data?.job) ? 30_000 : false,
    retry: retryPolicy,
  });
  const active = isActive(query.data?.job);
  const lastSeq = useRef(0);
  useEffect(() => {
    if (!id || !active) return;
    const controller = new AbortController();
    let cancelled = false;
    const follow = async () => {
      try {
        await streamJobEvents(
          id,
          (event) => {
            lastSeq.current = Math.max(lastSeq.current, event.seq);
            void client.invalidateQueries({ queryKey: ["jobs", id] });
            void client.invalidateQueries({ queryKey: ["jobs"], exact: true });
          },
          controller.signal,
          lastSeq.current,
        );
      } catch {
        // The polling refetch covers a dropped stream; nothing to show the user here.
      } finally {
        if (!cancelled)
          void client.invalidateQueries({ queryKey: ["jobs", id] });
      }
    };
    void follow();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [id, active, client]);
  return query;
}

export function useCreateExport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ExportRequestBody) => createExport(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["jobs"], exact: true });
    },
  });
}

export function useCancelJob(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (version: number) => cancelJob(id, version),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["jobs", id] });
      void client.invalidateQueries({ queryKey: ["jobs"], exact: true });
    },
  });
}
