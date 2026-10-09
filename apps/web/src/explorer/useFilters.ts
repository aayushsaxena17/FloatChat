import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";
import type { Environment } from "../api/types";
import { parseFilters, toSearchParams, type Filters } from "./filters";

/** The URL is the source of truth for filters; `update` writes it (replace, no history spam). */
export function useFilters(environment?: Environment): {
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
} {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => parseFilters(params, environment),
    [params, environment],
  );
  const update = useCallback(
    (patch: Partial<Filters>) => {
      setParams(toSearchParams({ ...filters, ...patch }), { replace: true });
    },
    [filters, setParams],
  );
  return { filters, update };
}
