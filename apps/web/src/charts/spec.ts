// Pure translation of the chart contract (PRD 11.3) into Plotly figures (ADR-0065): one
// figure per unit group, allow-listed trace keys only, units on every axis, fixed palette
// slots, a table view for every figure. Nothing from the server is executed.
import type { Data, Layout } from "plotly.js";
import type { ChartAxis, ChartSpec, ResultTable } from "../api/types";
import { axisTitle, columnLabel, unitLabel } from "../catalog/units";
import {
  CATEGORICAL,
  GRID,
  SURFACE,
  TEXT_PRIMARY,
  TEXT_SECONDARY,
  seriesColor,
} from "./palette";

export const TRACE_KEYS = new Set([
  "type",
  "mode",
  "name",
  "x",
  "y",
  "text",
  "nbinsx",
]);
export const TRACE_TYPES = new Set(["scatter", "scattergl", "histogram"]);

export interface Figure {
  key: string;
  title: string;
  data: Data[];
  layout: Partial<Layout>;
  table: { columns: string[]; rows: Array<Array<string | number | null>> };
  pointCount: number;
}

type ContractTrace = {
  type: string;
  mode?: string;
  name?: string;
  x?: Array<string | number | null>;
  y?: Array<string | number | null>;
  text?: string[];
  nbinsx?: number;
};

function contractTraces(chart: ChartSpec): ContractTrace[] {
  const plotly = chart.plotly as { traces?: unknown };
  if (!Array.isArray(plotly.traces)) return [];
  return plotly.traces.filter(
    (trace): trace is ContractTrace =>
      typeof trace === "object" &&
      trace !== null &&
      TRACE_TYPES.has((trace as { type?: unknown }).type as string) &&
      Object.keys(trace).every((key) => TRACE_KEYS.has(key)),
  );
}

export function baseLayout(
  xTitle: string,
  yTitle: string,
  reversedY: boolean,
): Partial<Layout> {
  return {
    autosize: true,
    margin: { l: 64, r: 16, t: 12, b: 52 },
    paper_bgcolor: SURFACE,
    plot_bgcolor: SURFACE,
    font: { family: "system-ui, sans-serif", size: 12, color: TEXT_PRIMARY },
    hovermode: "closest",
    xaxis: {
      title: { text: xTitle },
      gridcolor: GRID,
      zeroline: false,
      automargin: true,
    },
    yaxis: {
      title: { text: yTitle },
      gridcolor: GRID,
      zeroline: false,
      automargin: true,
      autorange: reversedY ? "reversed" : true,
    },
    legend: { orientation: "h", y: -0.25, font: { color: TEXT_SECONDARY } },
  };
}

function markerTrace(
  trace: ContractTrace,
  color: string,
  mode: string,
  hover: string,
): Data {
  return {
    type: "scatter",
    mode: mode as "lines+markers",
    name: trace.name ?? "",
    x: trace.x ?? [],
    y: trace.y ?? [],
    marker: { color, size: 8, line: { color: SURFACE, width: 1 } },
    line: { color, width: 2 },
    connectgaps: false,
    hovertemplate: hover,
  } as Data;
}

function hoverTemplate(
  xLabel: string,
  xUnit: string | null,
  yLabel: string,
  yUnit: string | null,
) {
  const x = `${xLabel}: %{x}${xUnit ? ` ${xUnit}` : ""}`;
  const y = `${yLabel}: %{y}${yUnit ? ` ${yUnit}` : ""}`;
  return `%{fullData.name}<br>${x}<br>${y}<extra></extra>`;
}

function unitGroups(
  traces: ContractTrace[],
  unitOf: (name: string) => string | null,
): Array<{ unit: string | null; traces: ContractTrace[] }> {
  const groups = new Map<
    string,
    { unit: string | null; traces: ContractTrace[] }
  >();
  for (const trace of traces) {
    const unit = unitOf(trace.name ?? "");
    const key = unit ?? (trace.name?.endsWith("_count") ? "count" : "");
    const group = groups.get(key) ?? { unit, traces: [] };
    group.traces.push(trace);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function tableOf(traces: ContractTrace[], xLabel: string): Figure["table"] {
  const xs = new Map<string | number, Array<string | number | null>>();
  for (const [index, trace] of traces.entries()) {
    (trace.x ?? []).forEach((x, position) => {
      const key = x ?? "";
      const row = xs.get(key) ?? traces.map(() => null);
      row[index] = trace.y?.[position] ?? null;
      xs.set(key, row);
    });
  }
  return {
    columns: [xLabel, ...traces.map((trace) => trace.name ?? "")],
    rows: [...xs.entries()].map(([x, values]) => [x, ...values]),
  };
}

function groupTitle(traces: ContractTrace[], unit: string | null): string {
  if (unit === null && traces.every((trace) => trace.name?.endsWith("_count")))
    return "Profiles with values (count)";
  const labels = traces.map((trace) => columnLabel(trace.name ?? ""));
  const shared = labels[0]?.split(" ")[0] ?? "";
  const suffixes = labels.map((label) => label.split(" ").slice(1).join(" "));
  const sameVariable = labels.every((label) => label.startsWith(shared));
  const title = sameVariable
    ? `${shared} ${suffixes.join(", ")}`.trim()
    : labels.join(", ");
  const rendered =
    unitLabel(unit) ?? (traces[0]?.name?.endsWith("_count") ? "count" : null);
  return rendered ? `${title} (${rendered})` : title;
}

/**
 * Figures for a chart contract. `result` supplies the unit of each series column, which the
 * contract's single y-axis cannot (the line_chart mixes temperature, salinity and counts).
 */
export function figuresFromChart(
  chart: ChartSpec,
  result: ResultTable,
): Figure[] {
  const traces = contractTraces(chart);
  if (traces.length === 0 || chart.type === "map") return [];
  const series = chart.series;
  const unitOf = (name: string) =>
    result.columns.find((column) => column.name === name)?.unit ?? null;
  const x: ChartAxis = chart.axis.x;
  const xLabel = x.label;
  const xUnit = unitLabel(x.unit);
  if (chart.type === "line_chart" || chart.type === "scatter") {
    return unitGroups(traces, unitOf).map(({ unit, traces: group }) => {
      const unitText =
        unitLabel(unit) ??
        (group[0]?.name?.endsWith("_count") ? "count" : null);
      const mode = chart.type === "line_chart" ? "lines+markers" : "markers";
      const data = group.map((trace) =>
        markerTrace(
          trace,
          seriesColor(trace.name ?? "", series),
          mode,
          hoverTemplate(xLabel, xUnit, columnLabel(trace.name ?? ""), unitText),
        ),
      );
      const yTitle = groupTitle(group, unit);
      const layout = baseLayout(axisTitle(xLabel, x.unit), yTitle, false);
      layout.showlegend = group.length > 1;
      // Month and day keys are calendar labels, not instants: categories keep the ticks on
      // the keys themselves instead of Plotly's weekly date ticks.
      if (x.field === "month" || x.field === "day")
        layout.xaxis = { ...layout.xaxis, type: "category" };
      return {
        key: `${chart.type}:${unit ?? group[0]?.name ?? ""}`,
        title: yTitle,
        data,
        layout,
        table: tableOf(group, axisTitle(xLabel, x.unit)),
        pointCount: group.reduce(
          (sum, trace) => sum + (trace.x?.length ?? 0),
          0,
        ),
      };
    });
  }
  if (chart.type === "histogram") {
    return traces.map((trace) => {
      const unit = unitOf(trace.name ?? "") ?? x.unit;
      const label = columnLabel(trace.name ?? x.field);
      const values = (trace.x ?? []).filter((value) => value !== null);
      const layout = baseLayout(
        axisTitle(label, unit),
        "Profiles (count)",
        false,
      );
      layout.showlegend = false;
      layout.bargap = 0.05;
      const data: Data[] = [
        {
          type: "histogram",
          name: label,
          x: values,
          nbinsx: trace.nbinsx,
          marker: {
            color: seriesColor(trace.name ?? "", series),
            line: { color: SURFACE, width: 1 },
          },
          hovertemplate: `${label}: %{x}<br>Profiles: %{y}<extra></extra>`,
        } as Data,
      ];
      return {
        key: `histogram:${trace.name ?? ""}`,
        title: `${label} distribution`,
        data,
        layout,
        table: {
          columns: [axisTitle(label, unit)],
          rows: values.map((value) => [value]),
        },
        pointCount: values.length,
      };
    });
  }
  // profile_plot and ts_diagram: one figure, one trace per profile, pressure downwards. Past
  // three profiles the colours fold to one slot (ADR-0065): identity stays on hover and in
  // the table, and no legend of opaque identifiers competes with the axes.
  const y = chart.axis.y;
  const reversed = Boolean(y?.reversed);
  const yLabel = y?.label ?? "";
  const folded = traces.length > 3;
  const data = traces.map((trace) =>
    markerTrace(
      trace,
      folded ? CATEGORICAL[2] : seriesColor(trace.name ?? "", series),
      trace.mode ?? "markers",
      hoverTemplate(xLabel, xUnit, yLabel, unitLabel(y?.unit)),
    ),
  );
  const layout = baseLayout(
    axisTitle(xLabel, x.unit),
    axisTitle(yLabel, y?.unit),
    reversed,
  );
  layout.showlegend = traces.length > 1 && !folded;
  return [
    {
      key: chart.type,
      title:
        chart.type === "ts_diagram"
          ? "Temperature-salinity diagram"
          : `${xLabel} profile`,
      data,
      layout,
      table: tableOf(traces, axisTitle(xLabel, x.unit)),
      pointCount: traces.reduce(
        (sum, trace) => sum + (trace.x?.length ?? 0),
        0,
      ),
    },
  ];
}
