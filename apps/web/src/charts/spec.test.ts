import { describe, expect, it } from "vitest";
import type { ChartSpec, QueryResponse } from "../api/types";
import { CATEGORICAL } from "./palette";
import { figuresFromChart } from "./spec";
import line from "../test/fixtures/query-line.json";
import histogram from "../test/fixtures/query-histogram.json";
import ts from "../test/fixtures/query-ts.json";

const lineResponse = line as unknown as QueryResponse;
const histogramResponse = histogram as unknown as QueryResponse;
const tsResponse = ts as unknown as QueryResponse;

describe("figuresFromChart", () => {
  it("splits a line chart into one figure per unit, never a dual axis", () => {
    const figures = figuresFromChart(
      lineResponse.chart as ChartSpec,
      lineResponse.result,
    );
    expect(figures.map((figure) => figure.title)).toEqual([
      "Temperature mean (°C)",
      "Profiles with values (count)",
      "Practical salinity mean (PSS-78, dimensionless)",
    ]);
    for (const figure of figures) {
      expect(figure.layout.yaxis?.title).toEqual({ text: figure.title });
      expect(figure.layout.xaxis?.title).toEqual({ text: "Day" });
      expect(figure.layout.yaxis?.autorange).toBe(true);
    }
    const counts = figures[1];
    expect(
      counts.data.map((trace) => (trace as { name: string }).name),
    ).toEqual(["temperature_count", "salinity_count"]);
    expect(counts.layout.showlegend).toBe(true);
    expect(figures[0].layout.showlegend).toBe(false);
    expect(counts.table.columns).toEqual([
      "Day",
      "temperature_count",
      "salinity_count",
    ]);
    expect(counts.table.rows.length).toBe(counts.pointCount / 2);
  });

  it("assigns palette slots by series identity", () => {
    const chart = lineResponse.chart as ChartSpec;
    const figures = figuresFromChart(chart, lineResponse.result);
    const colorOf = (name: string) => {
      for (const figure of figures) {
        const trace = figure.data.find(
          (item) => (item as { name: string }).name === name,
        ) as { marker: { color: string } } | undefined;
        if (trace) return trace.marker.color;
      }
      return null;
    };
    expect(colorOf("temperature_mean")).toBe(CATEGORICAL[0]);
    expect(colorOf("salinity_mean")).toBe(
      CATEGORICAL[chart.series.indexOf("salinity_mean")],
    );
    // Dropping a series keeps the survivors' colours (colour follows the entity, not the rank).
    const fewer: ChartSpec = {
      ...chart,
      plotly: {
        traces: (
          chart.plotly as { traces: Array<{ name: string }> }
        ).traces.filter((trace) => trace.name !== "temperature_mean"),
      },
    };
    const survivors = figuresFromChart(fewer, lineResponse.result);
    const salinity = survivors
      .flatMap((figure) => figure.data)
      .find(
        (trace) => (trace as { name: string }).name === "salinity_mean",
      ) as { marker: { color: string } };
    expect(salinity.marker.color).toBe(colorOf("salinity_mean"));
  });

  it("drops traces outside the allow-list and the map kind", () => {
    const chart = lineResponse.chart as ChartSpec;
    const poisoned: ChartSpec = {
      ...chart,
      plotly: {
        traces: [
          { type: "scatter", name: "ok", x: [1], y: [2], mode: "markers" },
          { type: "scatter", name: "bad", x: [1], y: [2], onclick: "alert(1)" },
          { type: "scattergeo", name: "geo", lon: [1], lat: [2] },
        ],
      },
    };
    const figures = figuresFromChart(poisoned, lineResponse.result);
    expect(
      figures
        .flatMap((figure) => figure.data)
        .map((trace) => (trace as { name: string }).name),
    ).toEqual(["ok"]);
    expect(
      figuresFromChart({ ...chart, type: "map" }, lineResponse.result),
    ).toEqual([]);
  });

  it("renders a histogram with the variable's unit and a profile count axis", () => {
    const [figure] = figuresFromChart(
      histogramResponse.chart as ChartSpec,
      histogramResponse.result,
    );
    expect(figure.title).toBe("Temperature mean distribution");
    expect(figure.layout.xaxis?.title).toEqual({
      text: "Temperature mean (°C)",
    });
    expect(figure.layout.yaxis?.title).toEqual({ text: "Profiles (count)" });
    expect((figure.data[0] as { nbinsx: number }).nbinsx).toBe(40);
    expect(figure.pointCount).toBe(figure.table.rows.length);
  });

  it("renders the T-S diagram with one trace per profile and units on both axes", () => {
    const [figure] = figuresFromChart(
      tsResponse.chart as ChartSpec,
      tsResponse.result,
    );
    expect(figure.title).toBe("Temperature-salinity diagram");
    expect(figure.data.length).toBe(
      (tsResponse.chart as ChartSpec).series.length,
    );
    expect(figure.layout.xaxis?.title).toEqual({
      text: "Practical salinity (PSS-78, dimensionless)",
    });
    expect(figure.layout.yaxis?.title).toEqual({ text: "Temperature (°C)" });
    expect(figure.layout.yaxis?.autorange).toBe(true);
  });

  it("points the pressure axis downwards for a profile plot", () => {
    const chart = tsResponse.chart as ChartSpec;
    const profilePlot: ChartSpec = {
      ...chart,
      type: "profile_plot",
      axis: {
        x: {
          field: "temperature",
          label: "Temperature",
          unit: "degree_C",
          reversed: false,
        },
        y: {
          field: "pressure",
          label: "Pressure",
          unit: "dbar",
          reversed: true,
        },
      },
    };
    const [figure] = figuresFromChart(profilePlot, tsResponse.result);
    expect(figure.layout.yaxis?.autorange).toBe("reversed");
    expect(figure.layout.yaxis?.title).toEqual({ text: "Pressure (dbar)" });
  });
});
