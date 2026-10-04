import { useEffect, useState } from "react";

export function App() {
  const [status, setStatus] = useState("Checking local services…");
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    fetch("/v1/health/ready", { signal: controller.signal })
      .then((response) =>
        setStatus(
          response.ok ? "Local services ready" : "Local services unavailable",
        ),
      )
      .catch(() => setStatus("Local services unavailable"))
      .finally(() => clearTimeout(timer));
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  return (
    <main>
      <p className="eyebrow">FLOATCHAT</p>
      <h1>
        Explore the ocean.
        <br />
        One question at a time.
      </h1>
      <p>
        Argo ocean observations, with a conversational workspace for research.
      </p>
      <p className="construction">Status: under construction</p>
      <p role="status">{status}</p>
      <footer>
        Argo GDAC · DOI 10.17882/42182 · Prototype data access via Argovis
      </footer>
    </main>
  );
}
