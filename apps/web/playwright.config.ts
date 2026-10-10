import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:5173" },
  // The Vite dev server in the integration stack pre-bundles MapLibre and Plotly on the first
  // request (docs/stage3-plan.md section 0).
  timeout: 120000,
  // Data-dependent assertions wait for the API; the dev stack answers in under a second
  // when idle but shares the host with Docker builds during the integration run.
  expect: { timeout: 30000 },
  retries: 0,
});
