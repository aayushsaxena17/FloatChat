// Forecast API client (Stage 6, ADR-0085): creation as a job, the run list and the run detail.
import { ApiError, buildUrl, CORRELATION_HEADER } from "../api/client";
import type { components } from "../api/schema";
import { CLIENT_HEADER, clientId } from "../chat/client";

export type ForecastRunRecord = components["schemas"]["ForecastRunRecord"];
export type ForecastDetail = components["schemas"]["ForecastDetail"];
export type ForecastCreated = components["schemas"]["ForecastCreated"];
export type ForecastRequestBody = components["schemas"]["ForecastRequestBody"];
export type ForecastDefinitionRecord =
  components["schemas"]["ForecastDefinitionRecord"];

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

export async function createForecast(
  body: ForecastRequestBody,
): Promise<ForecastCreated> {
  const response = await fetch(buildUrl("/forecasts"), {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  return readJson<ForecastCreated>(response);
}

export async function listForecasts(
  signal?: AbortSignal,
): Promise<ForecastRunRecord[]> {
  const response = await fetch(buildUrl("/forecasts", { limit: 100 }), {
    headers: headers(),
    signal,
  });
  const body = await readJson<{ forecasts: ForecastRunRecord[] }>(response);
  return body.forecasts;
}

export async function getForecast(
  id: string,
  signal?: AbortSignal,
): Promise<ForecastDetail> {
  const response = await fetch(
    buildUrl(`/forecasts/${encodeURIComponent(id)}`),
    { headers: headers(), signal },
  );
  return readJson<ForecastDetail>(response);
}
