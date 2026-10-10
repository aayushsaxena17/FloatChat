import { useCallback, useMemo, useRef } from "react";
import { useSearchParams } from "react-router";
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
  const latest = useRef(params);
  const pending = useRef<string[]>([]);
  const current = params.toString();
  const arrived = pending.current.indexOf(current);
  if (arrived >= 0) {
    // One of our writes reached the router; later writes are still on their way.
    pending.current = pending.current.slice(arrived + 1);
  } else if (pending.current.length === 0) {
    // A navigation this hook did not make (a link, back, a first render).
    latest.current = params;
  }
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
