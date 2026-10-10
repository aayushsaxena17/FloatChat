// TanStack Query owns server state (PRD 14.3). Keys derive from the filters so a URL change
// refetches exactly what changed; errors surface as ApiError with code and correlation id.
import { useQuery } from "@tanstack/react-query";
import {
  ApiError,
  getCatalogParameters,
  getCoverage,
  getFloat,
  getProfile,
  listProfiles,
  postQuery,
  type ParametersResponse,
  type QueryPlan,
} from "./client";
import type {
  CollectionResponse,
  CoverageResponse,
  FloatResponse,
  ProfileResponse,
  QueryResponse,
} from "./types";
import {
  isReady,
  timeRange,
  toReadParams,
  type Filters,
} from "../explorer/filters";

/** Pages followed for the map (PRD 14.4; ADR-0062): five pages of the 1,000 bound. */
export const PROFILE_PAGE_LIMIT = 1000;
export const PROFILE_PAGE_CAP = 5;

export function retryPolicy(count: number, error: unknown): boolean {
  if (error instanceof ApiError) return error.status >= 500 && count < 1;
  return count < 1;
}

export function useParameters() {
  return useQuery<ParametersResponse, Error>({
    queryKey: ["parameters"],
    queryFn: ({ signal }) => getCatalogParameters({ signal }),
    staleTime: Infinity,
  });
}

/** The environment (reference time, tiers, timestamps) comes with any coverage answer. */
export function useEnvironment() {
  return useQuery<CoverageResponse, Error>({
    queryKey: ["coverage", "environment"],
    queryFn: ({ signal }) => getCoverage({}, { signal }),
    staleTime: 5 * 60_000,
  });
}

export function useCoverage(filters: Filters) {
  const range = timeRange(filters);
  return useQuery<CoverageResponse, Error>({
    queryKey: ["coverage", filters.region, range?.start, range?.end],
    queryFn: ({ signal }) =>
      getCoverage(
        { region: filters.region, start: range?.start, end: range?.end },
        { signal },
      ),
    enabled: isReady(filters),
  });
}

export interface ProfilesPage {
  pages: CollectionResponse[];
  /** True when the page cap stopped before the last page. */
  truncated: boolean;
}

/** Every profile header for the filters, following cursors up to the cap. */
export function useProfilesAll(filters: Filters) {
  const params = toReadParams(filters);
  return useQuery<ProfilesPage, Error>({
    queryKey: ["profiles", params, PROFILE_PAGE_CAP],
    queryFn: async ({ signal }) => {
      const pages: CollectionResponse[] = [];
      let cursor: string | null | undefined;
      for (let page = 0; page < PROFILE_PAGE_CAP; page += 1) {
        const response = await listProfiles(
          { ...params, limit: PROFILE_PAGE_LIMIT, cursor: cursor ?? undefined },
          { signal },
        );
        pages.push(response);
        cursor = response.next_cursor;
        if (!cursor) return { pages, truncated: false };
      }
      return { pages, truncated: true };
    },
    enabled: isReady(filters),
  });
}

export function useProfile(filters: Filters) {
  const id = filters.profile;
  const depth = toReadParams(filters);
  return useQuery<ProfileResponse, Error>({
    queryKey: ["profile", id, filters.qc, depth.depth_min, depth.depth_max],
    queryFn: ({ signal }) =>
      getProfile(
        id as string,
        {
          qc_policy: filters.qc,
          depth_min: depth.depth_min,
          depth_max: depth.depth_max,
        },
        { signal },
      ),
    enabled: Boolean(id),
  });
}

export function useFloat(filters: Filters) {
  const platform = filters.platform;
  const range = timeRange(filters);
  return useQuery<FloatResponse, Error>({
    queryKey: ["float", platform, range?.start, range?.end],
    queryFn: ({ signal }) =>
      getFloat(
        platform as string,
        { start: range?.start, end: range?.end, limit: PROFILE_PAGE_LIMIT },
        { signal },
      ),
    enabled: Boolean(platform) && range !== null,
  });
}

/** One validated plan through POST /v1/query; the key is the plan document itself. */
export function usePlanQuery(plan: QueryPlan | null, enabled = true) {
  return useQuery<QueryResponse, Error>({
    queryKey: ["query", plan],
    queryFn: ({ signal }) => postQuery(plan as QueryPlan, { signal }),
    enabled: enabled && plan !== null,
  });
}

export function describeError(error: unknown): {
  message: string;
  code: string | null;
  correlationId: string | null;
} {
  if (error instanceof ApiError) {
    const detail = error.details
      .map((item) =>
        `${item.field ?? ""} ${item.message ?? item.code ?? ""}`.trim(),
      )
      .filter(Boolean)
      .join("; ");
    return {
      message: detail ? `${error.message} (${detail})` : error.message,
      code: error.code,
      correlationId: error.correlationId,
    };
  }
  if (error instanceof Error)
    return { message: error.message, code: null, correlationId: null };
  return { message: "Request failed", code: null, correlationId: null };
}
