import { useLocation } from "react-router";

export const STUBS: Record<string, { title: string; stage: string }> = {
  "/login": {
    title: "Sign in",
    stage: "Stage 7 (authentication, roles and quotas)",
  },
  "/chat": {
    title: "Chat",
    stage: "Stage 4 (natural-language assistant and benchmark)",
  },
  "/jobs": { title: "Jobs", stage: "Stage 5 (historical jobs and exports)" },
  "/forecasts": { title: "Forecasts", stage: "Stage 6 (forecasting)" },
  "/settings": { title: "Settings", stage: "Stage 7" },
  "/admin/usage": { title: "Usage", stage: "Stage 7" },
  "/admin/ingestion": { title: "Ingestion runs", stage: "Stage 7" },
};

/** PRD 14.1 routes that later stages deliver; each names its stage instead of pretending. */
export function Stub() {
  const location = useLocation();
  const key = Object.keys(STUBS).find((path) =>
    location.pathname.startsWith(path),
  );
  const stub = key
    ? STUBS[key]
    : { title: "Not yet available", stage: "a later stage" };
  return (
    <div className="stub">
      <h1>{stub.title}</h1>
      <p className="status" role="status">
        This area arrives with {stub.stage}. The dashboard, map and profile
        views are available now.
      </p>
    </div>
  );
}
