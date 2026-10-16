// The forecast figure: history, the forecast mean and its 80% and 95% bands (ADR-0085). A
// dedicated builder because interval bands need `fill` traces the contract charts do not allow.
import type { Data } from "plotly.js";
import { baseLayout, type Figure } from "../charts/spec";
import { CATEGORICAL } from "../charts/palette";
import type { ForecastRunRecord } from "./client";

const UNITS: Record<string, string> = {
  temperature: "Temperature (°C)",
  salinity: "Practical salinity (PSS-78, dimensionless)",
};

function rgba(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function numbers(value: unknown): number[] {
  return Array.isArray(value)
    ? value.map((item) => (typeof item === "number" ? item : Number.NaN))
    : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

/** History plus forecast when the run has one; the table lists every month shown. */
export function forecastFigure(
  run: ForecastRunRecord,
  variable: string,
): Figure {
  const history = run.history as Record<string, unknown>;
  const forecast = run.forecast as Record<string, unknown>;
  const months = strings(history.months);
  const values = numbers(history.values);
  const filled = Array.isArray(history.filled)
    ? (history.filled as boolean[])
    : [];
  const futureMonths = strings(forecast.months);
  const mean = numbers(forecast.mean);
  const data: Data[] = [
    {
      type: "scatter",
      mode: "lines+markers",
      name: "history",
      x: months,
      y: values,
      line: { color: CATEGORICAL[0], width: 1.5 },
      marker: {
        size: 4,
        color: months.map((_, index) =>
          filled[index] ? "#ffffff" : CATEGORICAL[0],
        ),
        line: { color: CATEGORICAL[0], width: 1 },
      },
      hovertemplate: "%{x}: %{y:.3f}<extra>history</extra>",
    },
  ];
  if (futureMonths.length && mean.length) {
    const bands: Array<[string, number[], number[], number]> = [
      [
        "95% interval",
        numbers(forecast.lower95),
        numbers(forecast.upper95),
        0.12,
      ],
      [
        "80% interval",
        numbers(forecast.lower80),
        numbers(forecast.upper80),
        0.22,
      ],
    ];
    for (const [name, lower, upper, alpha] of bands) {
      data.push({
        type: "scatter",
        mode: "lines",
        name,
        x: [...futureMonths, ...[...futureMonths].reverse()],
        y: [...upper, ...[...lower].reverse()],
        fill: "toself",
        fillcolor: rgba(CATEGORICAL[1], alpha),
        line: { color: "rgba(0,0,0,0)" },
        hoverinfo: "skip",
      });
    }
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: `forecast (${String((forecast.model as Record<string, unknown> | undefined)?.label ?? "model")})`,
      x: futureMonths,
      y: mean,
      line: { color: CATEGORICAL[1], width: 2, dash: "dot" },
      marker: { size: 5, color: CATEGORICAL[1] },
      hovertemplate: "%{x}: %{y:.3f}<extra>forecast</extra>",
    });
  }
  const rows: Array<Array<string | number | null>> = months.map(
    (month, index) => [
      month,
      values[index] ?? null,
      filled[index] ? "interpolated" : "observed",
      null,
      null,
    ],
  );
  futureMonths.forEach((month, index) => {
    rows.push([
      month,
      mean[index] ?? null,
      "forecast",
      numbers(forecast.lower95)[index] ?? null,
      numbers(forecast.upper95)[index] ?? null,
    ]);
  });
  return {
    key: `forecast-${run.id}`,
    title: UNITS[variable] ?? variable,
    data,
    layout: {
      ...baseLayout("Month", UNITS[variable] ?? variable, false),
      showlegend: true,
      legend: { orientation: "h", y: -0.25 },
    },
    table: {
      columns: ["month", "value", "kind", "lower 95%", "upper 95%"],
      rows,
    },
    pointCount: months.length + futureMonths.length,
    emptyReason: months.length
      ? undefined
      : "No history was built for this series.",
  };
}
