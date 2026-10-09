import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:5173" },
  // The Vite dev server in the integration stack pre-bundles MapLibre and Plotly on the first
  // request (docs/stage3-plan.md section 0).
  timeout: 120000,
  retries: 0,
});
