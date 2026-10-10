import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, stubApi } from "../test/client";
import parameters from "../test/fixtures/parameters.json";
import coverage from "../test/fixtures/coverage.json";
import profiles from "../test/fixtures/profiles.json";
import line from "../test/fixtures/query-line.json";

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

const { Dashboard } = await import("./Dashboard");
const SCENARIO =
  "/dashboard?region=Arabian%20Sea&start=2025-01-01&end=2025-02-01&depth_min=0&depth_max=100&qc=science_ready";

afterEach(() => vi.unstubAllGlobals());

describe("Dashboard", () => {
  it("loads coverage, the map points and the charts for the URL's filters", async () => {
    const api = stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/catalog/coverage": coverage,
      "/v1/profiles": profiles,
      "/v1/query": line,
    });
    renderWithProviders(<Dashboard />, SCENARIO);
    expect(
      await screen.findByRole("heading", { name: /Coverage/ }),
    ).toBeInTheDocument();
    expect(await screen.findByTestId("map-status")).toHaveTextContent(
      /\d+ profiles plotted/,
    );
    // The stub answers both plan queries with the line fixture, so each heading appears twice.
    expect(
      (await screen.findAllByRole("heading", { name: "Temperature mean (°C)" }))
        .length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByRole("heading", {
        name: "Practical salinity mean (PSS-78, dimensionless)",
      }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("provenance").length).toBeGreaterThanOrEqual(
      2,
    );
    expect(
      screen.getByRole("button", { name: /Export filtered dataset/ }),
    ).toBeDisabled();
    const profilesCall = api.calls.find((call) =>
      call.includes("/v1/profiles"),
    );
    expect(profilesCall).toContain("region=Arabian+Sea");
    expect(profilesCall).toContain("start=2025-01-01T00%3A00%3A00Z");
    expect(profilesCall).toContain("depth_max=100");
    const queryCall = api.fetch.mock.calls.find(([url]) =>
      String(url).endsWith("/v1/query"),
    );
    const body = JSON.parse(String(queryCall?.[1]?.body));
    expect(body.geography).toEqual({
      kind: "named_region",
      value: "Arabian Sea",
    });
    expect(body.depth_dbar).toEqual({ min: 0, max: 100 });
  });

  it("withholds the per-profile distribution above the published chart bound", async () => {
    const wide = {
      ...coverage,
      coverage: { ...coverage.coverage, estimated_profiles: 5814 },
    };
    const api = stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/catalog/coverage": wide,
      "/v1/profiles": profiles,
      "/v1/query": line,
    });
    renderWithProviders(<Dashboard />, SCENARIO);
    const notice = await screen.findByTestId("histogram-bound");
    expect(notice).toHaveTextContent("at most 5,000 profiles");
    expect(notice).toHaveTextContent("holds 5,814");
    // The time series still runs; only the histogram request is withheld.
    await screen.findAllByRole("heading", { name: "Temperature mean (°C)" });
    const queries = api.calls.filter(
      (call) => call.startsWith("POST") && call.endsWith("/v1/query"),
    );
    expect(queries).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an API error with its code and correlation id", async () => {
    stubApi(
      {
        "/v1/catalog/parameters": parameters,
        "/v1/profiles": profiles,
        "/v1/query": line,
      },
      { "/v1/catalog/coverage?region": 422 },
    );
    renderWithProviders(<Dashboard />, SCENARIO);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("[coverage_missing]");
    expect(alert).toHaveTextContent("Correlation ID trace-x");
  });

  it("writes filter changes to the URL and validates them beside the control", async () => {
    stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/catalog/coverage": coverage,
      "/v1/profiles": profiles,
      "/v1/query": line,
    });
    renderWithProviders(<Dashboard />, SCENARIO);
    const form = await screen.findByRole("form", { name: "Filters" });
    const depthMin = within(form).getByLabelText("Pressure from (dbar)");
    await userEvent.clear(depthMin);
    await userEvent.type(depthMin, "200");
    await waitFor(() =>
      expect(within(form).getByText(/exceed the minimum/)).toBeInTheDocument(),
    );
    expect(within(form).getByLabelText(/Pressure to/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("asks for the environment's window when the URL carries no dates", async () => {
    stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/catalog/coverage": coverage,
    });
    renderWithProviders(<Dashboard />, "/dashboard");
    // The coverage fixture's environment defaults the dates; the filters then become ready.
    expect(
      await screen.findByRole("heading", { name: /Coverage/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Start (UTC day, inclusive)")).toHaveValue(
      "2025-01-01",
    );
  });
});
