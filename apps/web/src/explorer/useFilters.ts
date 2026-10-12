import { useCallback, useLayoutEffect, useMemo, useRef } from "react";
import { useLocation, useSearchParams } from "react-router";
import type { Environment } from "../api/types";
import { parseFilters, toSearchParams, type Filters } from "./filters";

/**
 * The URL is the source of truth for filters; `update` writes it (replace, no history spam).
 *
 * Updates build on the latest URL this hook wrote, not on the last render: two controls changed
 * before React re-renders (a fast user or Playwright) would otherwise each rebuild the URL from
 * the same stale filters and the later write would drop the earlier change. React Router's
 * functional `setSearchParams` form reads render-time params too, so it does not avoid this.
 */
export function useFilters(environment?: Environment): {
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
} {
  const [params, setParams] = useSearchParams();
  const { key } = useLocation();
  const latest = useRef(params);
  const pending = useRef<string[]>([]);
  useLayoutEffect(() => {
    // A render can be interrupted and replayed with the old URL. Only a committed
    // navigation may acknowledge writes, otherwise that replay loses pending edits.
    const arrived = pending.current.lastIndexOf(params.toString());
    if (arrived >= 0) {
      pending.current = pending.current.slice(arrived + 1);
    } else {
      // A link or history navigation supersedes any unfinished filter navigation.
      pending.current = [];
    }
    if (pending.current.length === 0) latest.current = params;
    // The location key also distinguishes navigations to the same query string.
  }, [key, params]);
  const filters = useMemo(
    () => parseFilters(params, environment),
    [params, environment],
  );
  const update = useCallback(
    (patch: Partial<Filters>) => {
      const next = toSearchParams({
        ...parseFilters(latest.current, environment),
        ...patch,
      });
      latest.current = next;
      pending.current.push(next.toString());
      setParams(next, { replace: true });
    },
    [environment, setParams],
  );
  return { filters, update };
}
