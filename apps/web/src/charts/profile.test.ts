import { describe, expect, it } from "vitest";
import type { ProfileResponse } from "../api/types";
import { levelSummary, levelsOf, profileFigures } from "./profile";
import fixture from "../test/fixtures/profile.json";

const profile = fixture as unknown as ProfileResponse;

describe("profile figures", () => {
  it("sorts levels by pressure and keeps the recorded values", () => {
    const levels = levelsOf(profile);
    expect(levels.length).toBe(profile.levels.row_count);
    for (let index = 1; index < levels.length; index += 1)
      expect(levels[index].pressure).toBeGreaterThanOrEqual(
        levels[index - 1].pressure,
      );
  });

  it("builds temperature and salinity against pressure (downwards) and a T-S diagram", () => {
    const figures = profileFigures(profile);
    expect(figures.map((figure) => figure.title)).toEqual([
      "Temperature versus pressure",
      "Practical salinity versus pressure",
      "Temperature-salinity diagram",
    ]);
    expect(figures[0].layout.yaxis?.autorange).toBe("reversed");
    expect(figures[0].layout.yaxis?.title).toEqual({ text: "Pressure (dbar)" });
    expect(figures[0].layout.xaxis?.title).toEqual({
      text: "Temperature (°C)",
    });
    expect(figures[1].layout.xaxis?.title).toEqual({
      text: "Practical salinity (PSS-78, dimensionless)",
    });
    expect(figures[2].layout.xaxis?.title).toEqual({
      text: "Practical salinity (PSS-78, dimensionless)",
    });
    expect(figures[2].layout.yaxis?.title).toEqual({
      text: "Temperature (°C)",
    });
    expect(figures[0].table.columns).toEqual([
      "Pressure (dbar)",
      "Temperature (°C)",
    ]);
    expect(figures[0].pointCount).toBeGreaterThan(0);
    expect(figures[0].pointCount).toBe(figures[0].table.rows.length);
  });

  it("summarises data modes and QC flags per variable without colour", () => {
    const summary = levelSummary(profile);
    expect(summary.map((row) => row.variable)).toEqual([
      "Temperature",
      "Practical salinity",
      "Pressure",
    ]);
    for (const row of summary) {
      expect(row.kept).toBeGreaterThan(0);
      expect(row.modes).toMatch(/[RAD]: \d+/);
      expect(row.qc).toMatch(/\d: \d+/);
    }
  });
});
