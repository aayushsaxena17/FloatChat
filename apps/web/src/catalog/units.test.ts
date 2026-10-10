import { describe, expect, it } from "vitest";
import {
  axisTitle,
  columnLabel,
  formatNumber,
  formatUtc,
  unitLabel,
  variableOf,
} from "./units";

describe("units", () => {
  it("renders the Stage 1 unit codes with their scientific names", () => {
    expect(unitLabel("degree_C")).toBe("°C");
    expect(unitLabel("1")).toBe("PSS-78, dimensionless");
    expect(unitLabel("dbar")).toBe("dbar");
    expect(unitLabel(null)).toBeNull();
    expect(axisTitle("Practical salinity", "1")).toBe(
      "Practical salinity (PSS-78, dimensionless)",
    );
    expect(axisTitle("Month", null)).toBe("Month");
  });

  it("labels result columns by variable", () => {
    expect(variableOf("salinity_mean")).toBe("salinity");
    expect(variableOf("month")).toBeNull();
    expect(columnLabel("temperature_count")).toBe("Temperature count");
    expect(columnLabel("depth_bin")).toBe("depth bin");
  });

  it("formats numbers and UTC timestamps with the convention stated", () => {
    expect(formatNumber(4144346)).toBe("4,144,346");
    expect(formatNumber(25.82271601)).toBe("25.823");
    expect(formatNumber(null)).toBe("—");
    expect(formatUtc("2025-01-31T23:23:01.002000Z")).toBe(
      "2025-01-31 23:23 UTC",
    );
    expect(formatUtc(null)).toBe("—");
  });
});
