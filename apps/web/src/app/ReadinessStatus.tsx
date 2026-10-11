import { useEffect, useState } from "react";

/** A bounded health check that recovers after startup and tracks dependency outages. */
export function ReadinessStatus() {
  const [state, setState] = useState<"checking" | "ready" | "unavailable">(
    "checking",
  );
  useEffect(() => {
    let disposed = false;
    let controller: AbortController | undefined;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let nextCheck: ReturnType<typeof setTimeout> | undefined;
    const check = async () => {
      const attempt = new AbortController();
      controller = attempt;
      deadline = setTimeout(() => attempt.abort(), 5000);
      try {
        const response = await fetch("/v1/health/ready", {
          signal: attempt.signal,
        });
        if (!disposed) setState(response.ok ? "ready" : "unavailable");
      } catch {
        if (!disposed) setState("unavailable");
      } finally {
        clearTimeout(deadline);
        if (!disposed)
          nextCheck = setTimeout(() => {
            void check();
          }, 15000);
      }
    };
    void check();
    return () => {
      disposed = true;
      controller?.abort();
      clearTimeout(deadline);
      clearTimeout(nextCheck);
    };
  }, []);
  const text =
    state === "checking"
      ? "Checking local services…"
      : state === "ready"
        ? "Local services ready"
        : "Local services unavailable";
  return (
    <span className="readiness" role="status" data-state={state}>
      {text}
    </span>
  );
}
