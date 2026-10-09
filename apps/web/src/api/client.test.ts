import { afterEach, expect, it, vi } from "vitest";
import {
  ApiError,
  getCatalogParameters,
  getCoverage,
  getFloat,
  getProfile,
  listFloats,
  listProfiles,
  postQuery,
  type QueryPlan,
} from "./client";

afterEach(() => vi.unstubAllGlobals());

function reply(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(headers),
    json: async () => body,
  };
}

function stubFetch(response: ReturnType<typeof reply>) {
  const fetch = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function lastCall(fetch: ReturnType<typeof stubFetch>) {
  const [url, init] = fetch.mock.calls.at(-1) as [string, RequestInit];
  return { url, init, headers: init.headers as Record<string, string> };
}

it("builds URLs under /v1 and returns the parsed body", async () => {
  const fetch = stubFetch(reply(200, { plan_schema: "stage2-plan-v1" }));
  expect(await getCatalogParameters()).toEqual({
    plan_schema: "stage2-plan-v1",
  });
  expect(lastCall(fetch).url).toBe("/v1/catalog/parameters");
  expect(lastCall(fetch).init.method).toBe("GET");
  expect(lastCall(fetch).init.body).toBeUndefined();

  await listFloats();
  expect(lastCall(fetch).url).toBe("/v1/floats");
});

it("encodes query parameters and skips unset ones", async () => {
  const fetch = stubFetch(reply(200, {}));
  await getCoverage({
    start: "2025-01-01T00:00:00Z",
    end: "2025-02-01T05:30:00+05:30",
    bbox: "50,-10,80.5,25",
    region: null,
  });
  const { url } = lastCall(fetch);
  expect(url).toBe(
    "/v1/catalog/coverage?start=2025-01-01T00%3A00%3A00Z" +
      "&end=2025-02-01T05%3A30%3A00%2B05%3A30&bbox=50%2C-10%2C80.5%2C25",
  );

  await listProfiles({
    limit: 25,
    platform_number: "5900001",
    depth_min: 0,
    qc_policy: undefined,
  });
  expect(lastCall(fetch).url).toBe(
    "/v1/profiles?limit=25&platform_number=5900001&depth_min=0",
  );
});

it("puts path identifiers in the path, escaped", async () => {
  const fetch = stubFetch(reply(200, {}));
  await getFloat("5900001", { limit: 10, cursor: "abc" });
  expect(lastCall(fetch).url).toBe("/v1/floats/5900001?limit=10&cursor=abc");

  await getFloat("a/b c");
  expect(lastCall(fetch).url).toBe("/v1/floats/a%2Fb%20c");

  await getProfile("00000000-0000-4000-8000-000000000101", {
    qc_policy: "raw",
    depth_max: 500,
  });
  expect(lastCall(fetch).url).toBe(
    "/v1/profiles/00000000-0000-4000-8000-000000000101?qc_policy=raw&depth_max=500",
  );
});

it("posts a plan as JSON", async () => {
  const response = { result: { rows: [] }, partial: false };
  const fetch = stubFetch(reply(200, response));
  const plan: QueryPlan = {
    dataset: "core",
    time_range: { start: "2025-01-01T00:00:00Z", end: "2025-02-01T00:00:00Z" },
    geography: { kind: "bbox", west: 50, south: -10, east: 80, north: 25 },
    variables: ["temperature"],
    operation: { kind: "profiles", limit: 10 },
  };
  expect(await postQuery(plan)).toEqual(response);
  const { url, init, headers } = lastCall(fetch);
  expect(url).toBe("/v1/query");
  expect(init.method).toBe("POST");
  expect(headers["Content-Type"]).toBe("application/json");
  expect(headers.Accept).toBe("application/json");
  expect(init.body).toBe(JSON.stringify(plan));
  expect(JSON.parse(init.body as string)).toEqual(plan);
});

it("sends the correlation ID only when given", async () => {
  const fetch = stubFetch(reply(200, {}));
  await getCatalogParameters({ correlationId: "trace-1" });
  expect(lastCall(fetch).headers["X-Correlation-ID"]).toBe("trace-1");
  await postQuery({ dataset: "core" }, { correlationId: "trace-2" });
  expect(lastCall(fetch).headers["X-Correlation-ID"]).toBe("trace-2");
  await getCatalogParameters();
  expect(lastCall(fetch).headers).not.toHaveProperty("X-Correlation-ID");
});

it("forwards the abort signal", async () => {
  const fetch = stubFetch(reply(200, {}));
  const controller = new AbortController();
  await listFloats({}, { signal: controller.signal });
  expect(lastCall(fetch).init.signal).toBe(controller.signal);
});

it("throws an ApiError carrying the 422 error envelope", async () => {
  const envelope = {
    error: {
      code: "coverage_missing",
      message: "No committed coverage exists for the requested scope.",
      details: [
        {
          field: "time_range",
          code: "invalid_time_range",
          message: "out of window",
        },
      ],
      correlation_id: "trace-3",
    },
  };
  stubFetch(reply(422, envelope, { "X-Correlation-ID": "trace-3" }));
  const failure = await postQuery({ dataset: "core" }).catch((error) => error);
  expect(failure).toBeInstanceOf(ApiError);
  expect(failure).toBeInstanceOf(Error);
  expect(failure.status).toBe(422);
  expect(failure.envelope).toEqual(envelope);
  expect(failure.code).toBe("coverage_missing");
  expect(failure.details).toEqual(envelope.error.details);
  expect(failure.correlationId).toBe("trace-3");
  expect(failure.message).toBe(envelope.error.message);
});

it("throws an ApiError without an envelope for a non-envelope error body", async () => {
  const fetch = vi.fn().mockResolvedValue({
    ok: false,
    status: 502,
    headers: new Headers({ "X-Correlation-ID": "trace-4" }),
    json: async () => {
      throw new SyntaxError("not json");
    },
  });
  vi.stubGlobal("fetch", fetch);
  const failure = await getCatalogParameters().catch((error) => error);
  expect(failure).toBeInstanceOf(ApiError);
  expect(failure.status).toBe(502);
  expect(failure.envelope).toBeNull();
  expect(failure.code).toBe("unknown_error");
  expect(failure.correlationId).toBe("trace-4");
  expect(failure.message).toBe("Request failed with HTTP 502");
});

it("lets network failures through unchanged", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await expect(listFloats()).rejects.toThrow("offline");
});
