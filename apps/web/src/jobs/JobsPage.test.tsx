import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router";
import { renderWithProviders, stubApi } from "../test/client";
import { parseJobSse } from "./client";

const { JobsPage } = await import("./JobsPage");
const { JobDetailPage } = await import("./JobDetailPage");
const { ExportAction } = await import("./ExportAction");

const JOB = {
  id: "11111111-1111-4111-8111-111111111111",
  kind: "export",
  queue: "export",
  idempotency_key: null,
  request: {
    schema: "export-request-v1",
    format: "parquet",
    time_range: { start: "2015-04-01T00:00:00Z", end: "2025-04-01T00:00:00Z" },
    geography: { kind: "named_region", value: "Arabian Sea" },
    depth_dbar: { min: 0, max: 2000 },
    qc_policy: "science_ready",
    variables: ["temperature", "salinity", "pressure"],
  },
  request_sha256: "a".repeat(64),
  plan: { plan_schema: "stage2-plan-v1" },
  state: "fetching",
  progress: {
    fetch_total: 10,
    fetch_complete: 3,
    fetch_failed: 0,
    slots_total: 1200,
    slots_reused: 30,
    reuse_ratio: 0.025,
  },
  result: {},
  error: null,
  version: 4,
  attempts: 1,
  cancel_requested_at: null,
  created_at: "2026-10-16T01:00:00Z",
  updated_at: "2026-10-16T01:05:00Z",
  started_at: "2026-10-16T01:00:05Z",
  finished_at: null,
};
const CHUNKS = [
  {
    id: "c1",
    seq: 1,
    kind: "fetch",
    label: "2015-04..2015-12",
    state: "complete",
    attempts: 1,
    evidence: { accepted_profiles: 1500, http_attempts: 270, http_retries: 2 },
    error: null,
  },
  {
    id: "c2",
    seq: 2,
    kind: "fetch",
    label: "2016-01..2016-12",
    state: "running",
    attempts: 1,
    evidence: {},
    error: null,
  },
  {
    id: "c3",
    seq: 3,
    kind: "export",
    label: "export",
    state: "pending",
    attempts: 0,
    evidence: {},
    error: null,
  },
];
const ARTEFACT = {
  id: "22222222-2222-4222-8222-222222222222",
  format: "parquet",
  role: "data",
  filename: "floatchat-export-11111111.parquet",
  bytes: 123456789,
  sha256: "b".repeat(64),
  row_count: 2500000,
  profile_count: 17000,
  state: "available",
  created_at: "2026-10-16T03:00:00Z",
  expires_at: "2026-10-23T03:00:00Z",
  download_url:
    "/v1/artefacts/22222222-2222-4222-8222-222222222222/download?token=1.ab",
};

afterEach(() => vi.unstubAllGlobals());

describe("Jobs", () => {
  it("lists the browser's jobs with their state and progress", async () => {
    stubApi({ "/v1/jobs": { jobs: [JOB] } });
    renderWithProviders(<JobsPage />, "/jobs");
    expect(
      await screen.findByRole("link", { name: "PARQUET export, Arabian Sea" }),
    ).toHaveAttribute("href", `/jobs/${JOB.id}`);
    expect(screen.getByText("Fetching source data")).toBeInTheDocument();
    expect(
      screen.getByText(/3 of 10 source chunks fetched/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/3% of the months were already/),
    ).toBeInTheDocument();
  });

  it("says when there are no jobs", async () => {
    stubApi({ "/v1/jobs": { jobs: [] } });
    renderWithProviders(<JobsPage />, "/jobs");
    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument();
  });

  it("shows chunks, downloads and the cancel action on the detail page", async () => {
    const api = stubApi({
      [`/v1/jobs/${JOB.id}/events`]: {},
      [`/v1/jobs/${JOB.id}/cancel`]: {
        job: { ...JOB, cancel_requested_at: "2026-10-16T01:10:00Z" },
      },
      [`/v1/jobs/${JOB.id}`]: {
        job: JOB,
        chunks: CHUNKS,
        artefacts: [ARTEFACT],
      },
    });
    renderWithProviders(
      <Routes>
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
      </Routes>,
      `/jobs/${JOB.id}`,
    );
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "PARQUET export, Arabian Sea",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 Apr 2015 to 1 Apr 2025/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent("2015-04..2015-12");
    expect(rows[1]).toHaveTextContent(
      "1,500 profiles · 270 requests · 2 retried",
    );
    expect(rows[2]).toHaveTextContent("running");
    expect(screen.getByText(/1,200 required/)).toBeInTheDocument();
    const download = screen.getByRole("link", { name: /Download/ });
    expect(download).toHaveAttribute("href", ARTEFACT.download_url);
    expect(screen.getByText("117.7 MB")).toBeInTheDocument();
    expect(
      screen.getByText(/2,500,000 measurement levels/),
    ).toBeInTheDocument();
    expect(screen.getByText(/doi.org\/10.17882\/42182/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    await waitFor(() =>
      expect(
        api.calls.some(
          (call) => call.startsWith("POST") && call.includes("/cancel"),
        ),
      ).toBe(true),
    );
    const cancelCall = api.fetch.mock.calls.find(([url]) =>
      String(url).includes("/cancel"),
    );
    expect(JSON.parse(String(cancelCall?.[1]?.body))).toEqual({ version: 4 });
  });

  it("explains a partial job and never shows a forecast-like claim", async () => {
    stubApi({
      [`/v1/jobs/${JOB.id}/events`]: {},
      [`/v1/jobs/${JOB.id}`]: {
        job: {
          ...JOB,
          state: "partial",
          finished_at: "2026-10-16T04:00:00Z",
          result: {
            missing_slots: [{ month: "2018-03" }, { month: "2018-04" }],
            failed_chunks: ["2018-01..2018-12"],
          },
        },
        chunks: CHUNKS,
        artefacts: [],
      },
    });
    renderWithProviders(
      <Routes>
        <Route path="/jobs/:jobId" element={<JobDetailPage />} />
      </Routes>,
      `/jobs/${JOB.id}`,
    );
    expect(await screen.findByText("Completed with gaps")).toBeInTheDocument();
    expect(screen.getByText(/2018-03, 2018-04/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel job" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("This job produced no files.")).toBeInTheDocument();
  });

  it("creates an export for the filters and opens the job", async () => {
    const api = stubApi({
      "/v1/exports": { job: JOB, created: true, attached: false },
      "/v1/jobs": { jobs: [JOB] },
    });
    renderWithProviders(
      <Routes>
        <Route
          path="/dashboard"
          element={
            <ExportAction
              filters={{
                region: "Arabian Sea",
                start: "2015-04-01",
                end: "2025-04-01",
                depthMin: 0,
                depthMax: 2000,
                qc: "science_ready",
                platform: null,
                profile: null,
                variable: "temperature",
              }}
            />
          }
        />
        <Route path="/jobs/:jobId" element={<p>job page</p>} />
      </Routes>,
      "/dashboard",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Export format"),
      "csv",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Export filtered dataset" }),
    );
    expect(await screen.findByText("job page")).toBeInTheDocument();
    const call = api.fetch.mock.calls.find(([url]) =>
      String(url).endsWith("/v1/exports"),
    );
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toEqual({
      time_range: {
        start: "2015-04-01T00:00:00Z",
        end: "2025-04-01T00:00:00Z",
      },
      geography: { kind: "named_region", value: "Arabian Sea" },
      depth_dbar: { min: 0, max: 2000 },
      qc_policy: "science_ready",
      format: "csv",
    });
    const headers = (call?.[1]?.headers ?? {}) as Record<string, string>;
    expect(headers["X-FloatChat-Client"]).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
  });

  it("parses event blocks with their ids and skips keep-alive comments", () => {
    const { events, rest } = parseJobSse(
      'id: 3\nevent: chunk\ndata: {"seq": 1}\n\n: keep-alive\n\nid: 4\nevent: finished\ndata: {"state": "completed"}\n\nid: 5\nevent: part',
    );
    expect(events).toEqual([
      { seq: 3, kind: "chunk", data: { seq: 1 } },
      { seq: 4, kind: "finished", data: { state: "completed" } },
    ]);
    expect(rest).toBe("id: 5\nevent: part");
  });
});
