// Minimal typed client for the FloatChat query API (plan W5). No runtime dependency: it wraps
// `fetch`, builds URLs under /v1 and types every response from the generated `schema.d.ts`
// (regenerate with `pnpm --filter @floatchat/web generate:api`).
import type { components, paths } from "./schema";

export const API_PREFIX = "/v1";
export const CORRELATION_HEADER = "X-Correlation-ID";

export type ErrorEnvelope = components["schemas"]["ErrorResponse"];
// openapi-typescript marks properties that have a server-side default (`dataset`, `qc_policy`)
// as required; they are optional in a request, so the plan type relaxes them.
export type QueryPlan = Partial<components["schemas"]["QueryRequest"]>;

type Get<P extends keyof paths> = paths[P] extends { get: infer Operation }
  ? Operation
  : never;
type Query<P extends keyof paths> =
  Get<P> extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never;
type Ok<Operation> = Operation extends {
  responses: { 200: { content: { "application/json": infer Body } } };
}
  ? Body
  : never;

export type CoverageParams = Query<"/v1/catalog/coverage">;
export type FloatsParams = Query<"/v1/floats">;
export type FloatParams = Query<"/v1/floats/{platform_number}">;
export type ProfilesParams = Query<"/v1/profiles">;
export type ProfileParams = Query<"/v1/profiles/{profile_id}">;

export type ParametersResponse = Ok<Get<"/v1/catalog/parameters">>;
export type CoverageResponse = Ok<Get<"/v1/catalog/coverage">>;
export type FloatsResponse = Ok<Get<"/v1/floats">>;
export type FloatResponse = Ok<Get<"/v1/floats/{platform_number}">>;
export type ProfilesResponse = Ok<Get<"/v1/profiles">>;
export type ProfileResponse = Ok<Get<"/v1/profiles/{profile_id}">>;
export type QueryResponse =
  paths["/v1/query"]["post"]["responses"][200]["content"]["application/json"];

export interface RequestOptions {
  /** Sent as X-Correlation-ID; the server echoes it when it is an ASCII token of at most 64 characters. */
  correlationId?: string;
  signal?: AbortSignal;
}

function isEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

/** A non-2xx answer. `envelope` is the parsed error body, or null when the body was not one. */
export class ApiError extends Error {
  readonly status: number;
  readonly envelope: ErrorEnvelope | null;
  readonly correlationId: string | null;

  constructor(
    status: number,
    envelope: ErrorEnvelope | null,
    headerCorrelationId: string | null = null,
  ) {
    super(envelope?.error.message ?? `Request failed with HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.envelope = envelope;
    this.correlationId = envelope?.error.correlation_id ?? headerCorrelationId;
  }

  get code(): string {
    return this.envelope?.error.code ?? "unknown_error";
  }

  get details(): ErrorEnvelope["error"]["details"] {
    return this.envelope?.error.details ?? [];
  }
}

type QueryValue = string | number | boolean | null | undefined;

export function buildUrl(
  path: string,
  params: Readonly<Record<string, QueryValue>> = {},
): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== null && value !== undefined)
      search.append(name, String(value));
  }
  const text = search.toString();
  return `${API_PREFIX}${path}${text ? `?${text}` : ""}`;
}

async function request<T>(
  method: "GET" | "POST",
  url: string,
  options: RequestOptions,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.correlationId)
    headers[CORRELATION_HEADER] = options.correlationId;
  const init: RequestInit = { method, headers, signal: options.signal };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  if (!response.ok) {
    const parsed: unknown = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      isEnvelope(parsed) ? parsed : null,
      response.headers.get(CORRELATION_HEADER),
    );
  }
  return (await response.json()) as T;
}

const segment = encodeURIComponent;

export function getCatalogParameters(
  options: RequestOptions = {},
): Promise<ParametersResponse> {
  return request("GET", buildUrl("/catalog/parameters"), options);
}

export function getCoverage(
  params: CoverageParams = {},
  options: RequestOptions = {},
): Promise<CoverageResponse> {
  return request("GET", buildUrl("/catalog/coverage", params), options);
}

export function listFloats(
  params: FloatsParams = {},
  options: RequestOptions = {},
): Promise<FloatsResponse> {
  return request("GET", buildUrl("/floats", params), options);
}

export function getFloat(
  platformNumber: string,
  params: FloatParams = {},
  options: RequestOptions = {},
): Promise<FloatResponse> {
  return request(
    "GET",
    buildUrl(`/floats/${segment(platformNumber)}`, params),
    options,
  );
}

export function listProfiles(
  params: ProfilesParams = {},
  options: RequestOptions = {},
): Promise<ProfilesResponse> {
  return request("GET", buildUrl("/profiles", params), options);
}

export function getProfile(
  profileId: string,
  params: ProfileParams = {},
  options: RequestOptions = {},
): Promise<ProfileResponse> {
  return request(
    "GET",
    buildUrl(`/profiles/${segment(profileId)}`, params),
    options,
  );
}

export function postQuery(
  plan: QueryPlan,
  options: RequestOptions = {},
): Promise<QueryResponse> {
  return request("POST", buildUrl("/query"), options, plan);
}
