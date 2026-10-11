// Figures for one profile's levels (GET /v1/profiles/{id}): temperature and salinity against
// pressure (downwards) and the temperature-salinity diagram. Pure; tested without Plotly.
import type { Data, Layout } from "plotly.js";
import type { ProfileResponse } from "../api/types";
import { tableRecords } from "../api/types";
import { axisTitle, unitLabel, VARIABLE_LABELS } from "../catalog/units";
import { CATEGORICAL, GRID, TEXT_PRIMARY, TEXT_SECONDARY } from "./palette";
import { baseLayout, type Figure } from "./spec";

type Level = {
  pressure: number;
  temperature: number | null;
  salinity: number | null;
};

export function levelsOf(profile: ProfileResponse): Level[] {
  return tableRecords(profile.levels)
    .map((record) => ({
      pressure:
        typeof record.pressure === "number" ? record.pressure : Number.NaN,
      temperature:
        typeof record.temperature === "number" ? record.temperature : null,
      salinity: typeof record.salinity === "number" ? record.salinity : null,
    }))
    .filter((level) => Number.isFinite(level.pressure))
    .sort((a, b) => a.pressure - b.pressure);
}

/** Spacious axes for dense scientific profiles; no smoothing or value reduction. */
function profileLayout(
  xTitle: string,
  yTitle: string,
  pressureAxis: boolean,
): Partial<Layout> {
  const layout = baseLayout(xTitle, yTitle, pressureAxis);
  return {
    ...layout,
    height: 430,
    margin: { l: 70, r: 20, t: 22, b: 64 },
    font: {
      family: "Segoe UI, system-ui, sans-serif",
      size: 12,
      color: TEXT_PRIMARY,
    },
    showlegend: false,
    hoverlabel: {
      bgcolor: "#173743",
      bordercolor: GRID,
      font: { color: TEXT_PRIMARY, size: 12 },
    },
    xaxis: {
      ...layout.xaxis,
      nticks: 5,
      ticks: "outside",
      ticklen: 4,
      tickcolor: GRID,
      title: { text: xTitle, standoff: 18 },
    },
    yaxis: {
      ...layout.yaxis,
      nticks: 6,
      ticks: "outside",
      ticklen: 4,
      tickcolor: GRID,
      title: { text: yTitle, standoff: 14 },
    },
  };
}

function unit(profile: ProfileResponse, column: string): string | null {
  return (
    profile.levels.columns.find((item) => item.name === column)?.unit ?? null
  );
}

/** Explain missing values using the returned data and flags, without guessing sensor faults. */
function emptyProfileReason(
  profile: ProfileResponse,
  levels: Level[],
  variable: "temperature" | "salinity",
): string {
  const records = tableRecords(profile.levels);
  if (records.length === 0)
    return "No readings match the selected pressure range.";
  if (levels.length === 0) return "No usable pressure readings are available.";
  const label = variable === "salinity" ? "Salinity" : "Temperature";
  if (records.some((record) => typeof record[variable] === "number"))
    return `${label} readings have no usable pressure values.`;
  if (records.every((record) => record[`${variable}_qc`] === "4"))
    return `${label} readings are marked as bad quality.`;
  if (
    profile.qc_policy.name === "science_ready" &&
    records.every((record) => {
      const flag = record[`${variable}_qc`];
      return typeof flag === "string" && flag !== "1" && flag !== "2";
    })
  )
    return `No ${variable} readings pass the quality check.`;
  return `No ${variable} values are available for this selection.`;
}

function variableFigure(
  profile: ProfileResponse,
  levels: Level[],
  variable: "temperature" | "salinity",
  color: string,
): Figure {
  const label = VARIABLE_LABELS[variable];
  const xUnit = unit(profile, variable);
  const pUnit = unit(profile, "pressure");
  const kept = levels.filter((level) => level[variable] !== null);
  const data: Data[] = [
    {
      type: "scatter",
      mode: "lines",
      name: label,
      // Keep excluded levels as nulls, so the line does not bridge missing data.
      x: levels.map((level) => level[variable]),
      y: levels.map((level) => level.pressure),
      line: { color, width: 2.3, shape: "linear", simplify: false },
      connectgaps: false,
      hovertemplate: `${label}: %{x:.3f} ${variable === "salinity" ? "PSS-78" : (unitLabel(xUnit) ?? "")}<br>Pressure: %{y:.1f} ${unitLabel(pUnit) ?? ""}<extra></extra>`,
    } as Data,
  ];
  const layout = profileLayout(
    variable === "salinity" ? "Salinity (PSS-78)" : axisTitle(label, xUnit),
    axisTitle("Pressure", pUnit),
    true,
  );
  layout.xaxis = {
    ...layout.xaxis,
    tickformat: variable === "temperature" ? ".0f" : ".2f",
  };
  return {
    key: `profile:${variable}`,
    title: `${label} versus pressure`,
    data,
    layout,
    table: {
      columns: [
        axisTitle("Pressure", pUnit),
        variable === "salinity" ? "Salinity (PSS-78)" : axisTitle(label, xUnit),
      ],
      rows: kept.map((level) => [level.pressure, level[variable]]),
    },
    pointCount: kept.length,
    emptyReason:
      kept.length === 0
        ? emptyProfileReason(profile, levels, variable)
        : undefined,
  };
}

export function profileFigures(profile: ProfileResponse): Figure[] {
  const levels = levelsOf(profile);
  const tUnit = unit(profile, "temperature");
  const both = levels.filter(
    (level) => level.temperature !== null && level.salinity !== null,
  );
  const ts: Figure = {
    key: "profile:ts",
    title: "Temperature-salinity diagram",
    data: [
      {
        type: "scatter",
        mode: "markers",
        name: profile.profile.source_profile_id,
        x: both.map((level) => level.salinity),
        y: both.map((level) => level.temperature),
        customdata: both.map((level) => level.pressure),
        marker: {
          color: both.map((level) => level.pressure),
          colorscale: [
            [0, "#f5d692"],
            [0.35, "#80d9cb"],
            [0.7, "#6aafe0"],
            [1, "#a39cf4"],
          ],
          size: 3.5,
          opacity: 0.9,
          line: { width: 0 },
          showscale: both.length > 0,
          colorbar: {
            title: {
              text: "Pressure<br>(dbar)",
              font: { size: 11, color: TEXT_SECONDARY },
            },
            thickness: 9,
            len: 0.78,
            outlinewidth: 0,
            tickfont: { size: 10, color: TEXT_SECONDARY },
            nticks: 5,
            xpad: 8,
          },
        },
        hovertemplate: `Salinity: %{x:.3f} PSS-78<br>Temperature: %{y:.2f} °C<br>Pressure: %{customdata:.1f} dbar<extra></extra>`,
      } as Data,
    ],
    layout: {
      ...profileLayout(
        "Salinity (PSS-78)",
        axisTitle("Temperature", tUnit),
        false,
      ),
      margin: { l: 62, r: 80, t: 22, b: 64 },
      xaxis: {
        ...profileLayout(
          "Salinity (PSS-78)",
          axisTitle("Temperature", tUnit),
          false,
        ).xaxis,
        tickformat: ".2f",
      },
    },
    table: {
      columns: [
        "Pressure (dbar)",
        "Salinity (PSS-78)",
        axisTitle("Temperature", tUnit),
      ],
      rows: both.map((level) => [
        level.pressure,
        level.salinity,
        level.temperature,
      ]),
    },
    pointCount: both.length,
    emptyReason:
      both.length > 0
        ? undefined
        : levels.length === 0
          ? emptyProfileReason(profile, levels, "salinity")
          : !levels.some((level) => level.salinity !== null)
            ? "No usable salinity readings to pair with temperature."
            : !levels.some((level) => level.temperature !== null)
              ? "No usable temperature readings to pair with salinity."
              : "Temperature and salinity are missing at matching levels.",
  };
  return [
    variableFigure(profile, levels, "temperature", CATEGORICAL[0]),
    variableFigure(profile, levels, "salinity", CATEGORICAL[1]),
    ts,
  ];
}

/** Counts of QC flags and data modes per variable, for the non-colour status summary. */
export function levelSummary(
  profile: ProfileResponse,
): Array<{ variable: string; kept: number; modes: string; qc: string }> {
  const records = tableRecords(profile.levels);
  return (["temperature", "salinity", "pressure"] as const).map((variable) => {
    const kept = records.filter(
      (record) => typeof record[variable] === "number",
    ).length;
    const count = (column: string) => {
      const tally = new Map<string, number>();
      for (const record of records) {
        const value = record[column];
        if (typeof value === "string")
          tally.set(value, (tally.get(value) ?? 0) + 1);
      }
      return [...tally.entries()]
        .sort()
        .map(([key, n]) => `${key}: ${n}`)
        .join(", ");
    };
    return {
      variable: VARIABLE_LABELS[variable],
      kept,
      modes: count(`${variable}_data_mode`) || "—",
      qc: count(`${variable}_qc`) || "—",
    };
  });
}
