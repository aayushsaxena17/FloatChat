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
    expect(figures[0].layout.yaxis?.title).toMatchObject({
      text: "Pressure (dbar)",
    });
    expect(figures[0].layout.xaxis?.title).toMatchObject({
      text: "Temperature (°C)",
    });
    expect(figures[1].layout.xaxis?.title).toMatchObject({
      text: "Salinity (PSS-78)",
    });
    expect(figures[2].layout.xaxis?.title).toMatchObject({
      text: "Salinity (PSS-78)",
    });
    expect(figures[2].layout.yaxis?.title).toMatchObject({
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

  it("preserves gaps and excludes missing pressure rather than fabricating a surface reading", () => {
    const modified = structuredClone(profile);
    const names = modified.levels.columns.map((column) => column.name);
    modified.levels.rows[1][names.indexOf("temperature")] = null;
    modified.levels.rows[2][names.indexOf("pressure")] = null;
    const levels = levelsOf(modified);
    expect(levels).toHaveLength(profile.levels.row_count - 1);
    const figures = profileFigures(modified);
    const trace = figures[0].data[0] as {
      x: Array<number | null>;
      mode: string;
      connectgaps: boolean;
    };
    expect(trace.x).toEqual(levels.map((level) => level.temperature));
    expect(trace.x).toContain(null);
    expect(trace.connectgaps).toBe(false);
    expect(trace.mode).toBe("lines");
    expect(figures[0].table.rows).toHaveLength(
      levels.filter((level) => level.temperature !== null).length,
    );
  });

  it("colours each T-S pair by its actual pressure and keeps every valid pair in the table", () => {
    const figure = profileFigures(profile)[2];
    const paired = levelsOf(profile).filter(
      (level) => level.temperature !== null && level.salinity !== null,
    );
    const trace = figure.data[0] as {
      x: number[];
      y: number[];
      customdata: number[];
      marker: { color: number[] };
    };
    expect(trace.customdata).toEqual(paired.map((level) => level.pressure));
    expect(trace.marker.color).toEqual(trace.customdata);
    expect(figure.table.rows).toEqual(
      paired.map((level) => [
        level.pressure,
        level.salinity,
        level.temperature,
      ]),
    );
    expect(trace.x).toEqual(paired.map((level) => level.salinity));
    expect(trace.y).toEqual(paired.map((level) => level.temperature));
  });

  it("explains bad salinity and the resulting missing T-S pairs", () => {
    const modified = structuredClone(profile);
    const names = modified.levels.columns.map((column) => column.name);
    for (const row of modified.levels.rows) {
      row[names.indexOf("salinity")] = null;
      row[names.indexOf("salinity_qc")] = "4";
    }
    const figures = profileFigures(modified);
    expect(figures[0].pointCount).toBeGreaterThan(0);
    expect(figures[1].pointCount).toBe(0);
    expect(figures[1].emptyReason).toBe(
      "Salinity readings are marked as bad quality.",
    );
    expect(figures[2].pointCount).toBe(0);
    expect(figures[2].emptyReason).toBe(
      "No usable salinity readings to pair with temperature.",
    );
  });

  it("does not blame quality control when salinity is simply missing", () => {
    const modified = structuredClone(profile);
    const names = modified.levels.columns.map((column) => column.name);
    for (const row of modified.levels.rows) {
      row[names.indexOf("salinity")] = null;
      row[names.indexOf("salinity_qc")] = null;
    }
    expect(profileFigures(modified)[1].emptyReason).toBe(
      "No salinity values are available for this selection.",
    );
  });

  it("explains an empty pressure selection without claiming bad data", () => {
    const modified = structuredClone(profile);
    modified.levels.rows = [];
    modified.levels.row_count = 0;
    for (const figure of profileFigures(modified)) {
      expect(figure.pointCount).toBe(0);
      expect(figure.emptyReason).toBe(
        "No readings match the selected pressure range.",
      );
    }
  });

  it("explains why readings at different levels cannot form T-S pairs", () => {
    const modified = structuredClone(profile);
    const names = modified.levels.columns.map((column) => column.name);
    modified.levels.rows = modified.levels.rows.slice(0, 2);
    modified.levels.rows[0][names.indexOf("salinity")] = null;
    modified.levels.rows[1][names.indexOf("temperature")] = null;
    const figures = profileFigures(modified);
    expect(figures[0].pointCount).toBe(1);
    expect(figures[1].pointCount).toBe(1);
    expect(figures[2].pointCount).toBe(0);
    expect(figures[2].emptyReason).toBe(
      "Temperature and salinity are missing at matching levels.",
    );
  });
});
