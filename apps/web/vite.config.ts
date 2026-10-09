import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/v1": process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000" },
  },
  // The heavy libraries are pre-bundled at start so the first request in the integration
  // stack does not pay for them inside the e2e budget (docs/stage3-plan.md section 0).
  optimizeDeps: {
    include: [
      "maplibre-gl",
      "plotly.js-cartesian-dist-min",
      "react-router",
      "@tanstack/react-query",
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
