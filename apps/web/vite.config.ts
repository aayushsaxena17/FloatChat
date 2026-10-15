import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    proxy: { "/v1": process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000" },
  },
  // The heavy libraries are pre-bundled at start so the first request in the integration
  // stack does not pay for them inside the e2e budget (docs/stage3-plan.md section 0).
  build: {
    // MapLibre and Plotly are imported dynamically (ADR-0068), so each becomes its own
    // cacheable chunk loaded on first use; manual chunks would pull shared helpers into them
    // and force the entry to preload them.
    chunkSizeWarningLimit: 1600,
  },
  optimizeDeps: {
    include: [
      "maplibre-gl",
      "plotly.js-cartesian-dist-min",
      "react-router",
      "@tanstack/react-query",
      // The loader and three itself go through the same pre-bundle, or dev serves two copies.
      "three",
      "three/examples/jsm/loaders/GLTFLoader.js",
    ],
  },
  test: {
    // Full dashboard interaction tests share the WSL host with the local Docker stack.
    maxWorkers: 2,
    testTimeout: 10000,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
