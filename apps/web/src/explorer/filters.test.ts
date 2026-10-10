import { describe, expect, it } from "vitest";
import {
  daysBetween,
  histogramPlan,
  isReady,
  parseFilters,
  timeSeriesPlan,
  toReadParams,
  toSearchParams,
  tsDiagramPlan,
  validateFilters,
} from "./filters";
import type { Environment } from "../api/types";

const ENVIRONMENT: Environment = {
  id: "e",
  name: "dev",
  mode: "acceptance",
  reference_time: "2025-04-01T00:00:00Z",
  completed_runs: 2,
  hot_tier: { start: "2025-01-01T00:00:00Z", end: "2025-04-01T00:00:00Z" },
};

const SCENARIO = new URLSearchParams(
  "region=Arabian%20Sea&start=2025-01-01&end=2025-02-01&depth_min=0&depth_max=100&qc=science_ready",
);

describe("parseFilters", () => {
  it("reads the scenario from the URL", () => {
    const filters = parseFilters(SCENARIO);
    expect(filters).toMatchObject({
      region: "Arabian Sea",
      start: "2025-01-01",
      end: "2025-02-01",
      depthMin: 0,
      depthMax: 100,
      qc: "science_ready",
      platform: null,
      profile: null,
      variable: "temperature",
    });
    expect(isReady(filters)).toBe(true);
  });

  it("defaults dates to the environment's hot tier and the region to the envelope", () => {
    expect(parseFilters(new URLSearchParams(), ENVIRONMENT)).toMatchObject({
      region: "Indian Ocean",
      start: "2025-01-01",
      end: "2025-04-01",
      depthMin: null,
      depthMax: null,
    });
    expect(isReady(parseFilters(new URLSearchParams()))).toBe(false);
  });

  it("ignores unknown QC policies and variables", () => {
    const filters = parseFilters(
      new URLSearchParams("qc=everything&variable=oxygen"),
    );
    expect(filters.qc).toBe("science_ready");
    expect(filters.variable).toBe("temperature");
  });
});

describe("toSearchParams", () => {
  it("round-trips every explicit value", () => {
    const filters = parseFilters(SCENARIO);
    const again = parseFilters(
      toSearchParams({ ...filters, profile: "p1", platform: "5900001" }),
    );
    expect(again).toEqual({ ...filters, profile: "p1", platform: "5900001" });
    expect(toSearchParams(filters).toString()).toContain("region=Arabian+Sea");
  });
});

describe("validateFilters", () => {
  it("rejects reversed and oversized ranges and bad depths", () => {
    const base = parseFilters(SCENARIO);
    expect(validateFilters(base)).toEqual({});
    expect(validateFilters({ ...base, end: "2025-01-01" }).end).toMatch(
      /after the start/,
    );
    expect(validateFilters({ ...base, end: "2026-02-01" }).end).toMatch(
      /366 days/,
    );
    expect(validateFilters({ ...base, start: "2025-13-01" }).start).toMatch(
      /YYYY-MM-DD/,
    );
    expect(validateFilters({ ...base, depthMin: 200 }).depthMax).toMatch(
      /exceed the minimum/,
    );
    expect(validateFilters({ ...base, depthMax: 20000 }).depthMax).toMatch(
      /12000/,
    );
    expect(
      validateFilters({ ...base, depthMin: Number.NaN }).depthMin,
    ).toBeTruthy();
    expect(daysBetween("2025-01-01", "2025-02-01")).toBe(31);
  });
});

describe("plans", () => {
  const filters = parseFilters(SCENARIO);

  it("sends the read parameters with UTC instants and an exclusive end", () => {
    expect(toReadParams(filters)).toEqual({
      start: "2025-01-01T00:00:00Z",
      end: "2025-02-01T00:00:00Z",
      region: "Arabian Sea",
      depth_min: 0,
      depth_max: 100,
      qc_policy: "science_ready",
    });
  });

  it("builds a daily line chart for a month and a monthly one for a quarter", () => {
    const daily = timeSeriesPlan(filters);
    expect(daily.operation).toEqual({
      kind: "aggregate",
      group_by: ["day"],
      metrics: ["mean", "count"],
      unit: "profile",
    });
    expect(daily.presentation).toEqual({ kind: "line_chart" });
    expect(daily.depth_dbar).toEqual({ min: 0, max: 100 });
    const quarter = timeSeriesPlan({ ...filters, end: "2025-04-01" });
    expect((quarter.operation as { group_by: string[] }).group_by).toEqual([
      "month",
    ]);
  });

  it("never sends raw to an aggregate but keeps it for profile reads", () => {
    const raw = { ...filters, qc: "raw" as const };
    expect(timeSeriesPlan(raw).qc_policy).toBe("science_ready");
    expect(histogramPlan(raw).qc_policy).toBe("science_ready");
    expect(tsDiagramPlan(raw).qc_policy).toBe("raw");
  });

  it("bounds the histogram and the T-S diagram", () => {
    const histogram = histogramPlan({ ...filters, variable: "salinity" });
    expect(histogram.variables).toEqual(["salinity"]);
    expect(histogram.presentation).toEqual({ kind: "histogram", bins: 40 });
    expect((histogram.operation as { group_by: string[] }).group_by).toEqual([
      "profile",
    ]);
    const ts = tsDiagramPlan(filters);
    expect(ts.operation).toEqual({ kind: "profiles", limit: 20 });
    expect(ts.variables).toEqual(["temperature", "salinity", "pressure"]);
  });

  it("omits the depth band when unset", () => {
    expect(
      timeSeriesPlan({ ...filters, depthMin: null, depthMax: null }).depth_dbar,
    ).toBeUndefined();
  });
});
