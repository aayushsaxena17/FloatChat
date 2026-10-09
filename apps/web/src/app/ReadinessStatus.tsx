import { useEffect, useState } from "react";

/** The Stage 0 readiness indicator, kept in the shell (e2e/scaffold.spec.ts asserts it). */
export function ReadinessStatus() {
  const [state, setState] = useState<"checking" | "ready" | "unavailable">(
    "checking",
  );
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    fetch("/v1/health/ready", { signal: controller.signal })
      .then((response) => setState(response.ok ? "ready" : "unavailable"))
      .catch(() => setState("unavailable"))
      .finally(() => clearTimeout(timer));
    return () => {
      controller.abort();
      clearTimeout(timer);
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
