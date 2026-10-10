import { vi } from "vitest";

/** jsdom has neither WebGL nor layout: the map and Plotly are replaced by inert elements. */
export function mockHeavyLibraries() {
  vi.mock("../charts/Plot", () => ({
    Plot: ({ label }: { label: string }) => (
      <div role="img" aria-label={label} data-testid="plot" />
    ),
  }));
  vi.mock("../explorer/MapView", () => ({
    MapView: ({
      points,
      truncated,
    }: {
      points: unknown[];
      truncated?: boolean;
    }) => (
      <p role="status" data-testid="map-status">
        {points.length} profiles plotted
        {truncated
          ? " (showing the first 5,000 of more; narrow the filters)"
          : ""}
      </p>
    ),
  }));
}
