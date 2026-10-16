import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router";
import { renderWithProviders, stubApi } from "../test/client";
import parameters from "../test/fixtures/parameters.json";

vi.mock("../charts/Plot", () => ({
  Plot: ({ label }: { label: string }) => (
    <div role="img" aria-label={label} data-testid="plot" />
  ),
}));

const { ForecastsPage } = await import("./ForecastsPage");
const { ForecastDetailPage } = await import("./ForecastDetailPage");
const { forecastFigure } = await import("./figure");

const RUN = {
  id: "44444444-4444-4444-8444-444444444444",
  definition_id: "55555555-5555-4555-8555-555555555555",
  model_id: "66666666-6666-4666-8666-666666666666",
  job_id: "77777777-7777-4777-8777-777777777777",
  horizon: 3,
  status: "published",
  reason: null,
  history: {
    months: ["2024-01", "2024-02", "2024-03"],
    values: [27.1, 27.4, 28.0],
    filled: [false, true, false],
    counts: [12, 3, 9],
    policy: { rule: "min_profiles", months_missing: 1, months_total: 3 },
  },
  forecast: {
    months: ["2024-04", "2024-05", "2024-06"],
    mean: [28.5, 29.0, 29.3],
    lower80: [28.2, 28.6, 28.8],
    upper80: [28.8, 29.4, 29.8],
    lower95: [28.0, 28.3, 28.4],
    upper95: [29.0, 29.7, 30.2],
    model: { label: "SARIMA(0,1,1)(0,1,1)[12]" },
  },
  backtest: {
    protocol: "rolling-origin, expanding window, refit per fold",
    folds: 12,
    horizons: [1, 2, 3],
    baseline: "seasonal naive (12)",
    results: {
      "seasonal naive (12)": {
        mean_mase: 1.0,
        horizons: {
          "1": {
            mae: 0.5,
            rmse: 0.6,
            mase: 1.0,
            coverage80: 0.75,
            coverage95: 0.92,
          },
          "2": {
            mae: 0.5,
            rmse: 0.6,
            mase: 1.0,
            coverage80: 0.75,
            coverage95: 0.92,
          },
          "3": {
            mae: 0.5,
            rmse: 0.6,
            mase: 1.0,
            coverage80: 0.75,
            coverage95: 0.92,
          },
        },
      },
      "SARIMA(0,1,1)(0,1,1)[12]": {
        mean_mase: 0.61,
        horizons: {
          "1": {
            mae: 0.3,
            rmse: 0.35,
            mase: 0.6,
            coverage80: 0.83,
            coverage95: 0.95,
          },
          "2": {
            mae: 0.31,
            rmse: 0.36,
            mase: 0.61,
            coverage80: 0.8,
            coverage95: 0.96,
          },
          "3": {
            mae: 0.32,
            rmse: 0.37,
            mase: 0.62,
            coverage80: 0.79,
            coverage95: 0.95,
          },
        },
      },
    },
    selection: {
      selected: { label: "SARIMA(0,1,1)(0,1,1)[12]" },
      reasons: [],
      diagnostics: { ljung_box_p: 0.41, residual_mean: 0.001 },
    },
  },
  warnings: ["1 months were interpolated: 2024-02"],
  limitations:
    "This is a statistical extrapolation of a derived observational series. It is not a physics-based ocean forecast and must not replace an operational ocean model.",
  seed: 20261016,
  versions: { statsmodels: "0.14.6", scipy: "1.18.1" },
  generated_at: "2026-10-16T09:00:00Z",
  created_at: "2026-10-16T08:50:00Z",
  updated_at: "2026-10-16T09:00:00Z",
};
const DEFINITION = {
  id: RUN.definition_id,
  definition_sha256: "a".repeat(64),
  variable: "temperature",
  region: "Arabian Sea",
  depth_dbar: { min: 0, max: 100 },
  frequency: "monthly",
  aggregation: "profile_balanced_mean",
  qc_policy: "science_ready",
  min_profiles: 5,
  series_start: "2015-04-01T00:00:00Z",
  series_end: "2025-04-01T00:00:00Z",
};
const MODEL = {
  id: RUN.model_id,
  version: 2,
  family: "sarima",
  order: {},
  training_snapshot: { snapshot_id: "snap-1" },
  metrics: {},
  diagnostics: {},
  status: "selected",
};

afterEach(() => vi.unstubAllGlobals());

describe("Forecasts", () => {
  it("creates a forecast job from the form and opens the job page", async () => {
    const api = stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/forecasts": {
        job: { id: RUN.job_id, state: "queued" },
        definition: DEFINITION,
        created: true,
        attached: false,
      },
    });
    renderWithProviders(
      <Routes>
        <Route path="/forecasts" element={<ForecastsPage />} />
        <Route path="/jobs/:jobId" element={<p>job page</p>} />
      </Routes>,
      "/forecasts",
    );
    await userEvent.selectOptions(
      await screen.findByLabelText("Variable"),
      "salinity",
    );
    await userEvent.clear(screen.getByLabelText("Horizon (months)"));
    await userEvent.type(screen.getByLabelText("Horizon (months)"), "6");
    await userEvent.click(screen.getByRole("button", { name: "Run forecast" }));
    expect(await screen.findByText("job page")).toBeInTheDocument();
    const call = api.fetch.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/v1/forecasts") && init?.method === "POST",
    );
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toEqual({
      variable: "salinity",
      geography: { kind: "named_region", value: "Arabian Sea" },
      depth_dbar: { min: 0, max: 100 },
      horizon: 6,
      min_profiles: 5,
    });
  });

  it("never shows a forecast chart without its backtest table, and prints the boundary", async () => {
    stubApi({
      [`/v1/forecasts/${RUN.id}`]: {
        run: RUN,
        definition: DEFINITION,
        model: MODEL,
        boundary: RUN.limitations,
      },
    });
    renderWithProviders(
      <Routes>
        <Route path="/forecasts/:forecastId" element={<ForecastDetailPage />} />
      </Routes>,
      `/forecasts/${RUN.id}`,
    );
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Temperature, Arabian Sea",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Published").length).toBeGreaterThan(0);
    expect(screen.getByTestId("plot")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(
      rows.some((row) =>
        row.textContent?.includes("seasonal naive (12) (baseline)"),
      ),
    ).toBe(true);
    expect(
      rows.some((row) =>
        row.textContent?.includes("SARIMA(0,1,1)(0,1,1)[12] (selected)"),
      ),
    ).toBe(true);
    expect(screen.getAllByText(/0\.610/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("boundary")).toHaveTextContent(
      /not a physics-based ocean forecast/,
    );
    expect(screen.getByText(/v2 \(sarima, selected\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 months were interpolated/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Ljung-Box p 0.410/)).toBeInTheDocument(),
    );
  });

  it("shows a refusal with its reason and the history only", async () => {
    stubApi({
      [`/v1/forecasts/${RUN.id}`]: {
        run: {
          ...RUN,
          status: "refused",
          reason: "history_too_short: Only 20 regular months",
          forecast: {},
          backtest: {},
          model_id: null,
        },
        definition: DEFINITION,
        model: null,
        boundary: RUN.limitations,
      },
    });
    renderWithProviders(
      <Routes>
        <Route path="/forecasts/:forecastId" element={<ForecastDetailPage />} />
      </Routes>,
      `/forecasts/${RUN.id}`,
    );
    expect((await screen.findAllByText("Refused")).length).toBeGreaterThan(0);
    expect(screen.getByRole("alert")).toHaveTextContent(/history_too_short/);
    expect(
      screen.queryByText(/Backtest against the baseline/),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("boundary")).toBeInTheDocument();
  });

  it("builds the figure with history, two bands and the forecast mean, plus a table", () => {
    const figure = forecastFigure(RUN as never, "temperature");
    expect(figure.data.map((trace) => trace.name)).toEqual([
      "history",
      "95% interval",
      "80% interval",
      "forecast (SARIMA(0,1,1)(0,1,1)[12])",
    ]);
    expect(figure.table.rows).toHaveLength(6);
    expect(figure.table.rows[1][2]).toBe("interpolated");
    expect(figure.table.rows[5]).toEqual([
      "2024-06",
      29.3,
      "forecast",
      28.4,
      30.2,
    ]);
    expect(figure.pointCount).toBe(6);
  });
});
