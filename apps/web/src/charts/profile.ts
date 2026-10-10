// Figures for one profile's levels (GET /v1/profiles/{id}): temperature and salinity against
// pressure (downwards) and the temperature-salinity diagram. Pure; tested without Plotly.
import type { Data } from "plotly.js";
import type { ProfileResponse } from "../api/types";
import { tableRecords } from "../api/types";
import { axisTitle, unitLabel, VARIABLE_LABELS } from "../catalog/units";
import { CATEGORICAL, SURFACE } from "./palette";
import { baseLayout, type Figure } from "./spec";

type Level = {
  pressure: number;
  temperature: number | null;
  salinity: number | null;
};

export function levelsOf(profile: ProfileResponse): Level[] {
  return tableRecords(profile.levels)
    .map((record) => ({
      pressure: Number(record.pressure),
      temperature:
        typeof record.temperature === "number" ? record.temperature : null,
      salinity: typeof record.salinity === "number" ? record.salinity : null,
    }))
    .filter((level) => Number.isFinite(level.pressure))
    .sort((a, b) => a.pressure - b.pressure);
}

function unit(profile: ProfileResponse, column: string): string | null {
  return (
    profile.levels.columns.find((item) => item.name === column)?.unit ?? null
  );
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
      mode: "lines+markers",
      name: label,
      x: kept.map((level) => level[variable]),
      y: kept.map((level) => level.pressure),
      marker: { color, size: 6, line: { color: SURFACE, width: 1 } },
      line: { color, width: 2 },
      hovertemplate: `${label}: %{x} ${unitLabel(xUnit) ?? ""}<br>Pressure: %{y} ${unitLabel(pUnit) ?? ""}<extra></extra>`,
    } as Data,
  ];
  const layout = baseLayout(
    axisTitle(label, xUnit),
    axisTitle("Pressure", pUnit),
    true,
  );
  layout.showlegend = false;
  return {
    key: `profile:${variable}`,
    title: `${label} versus pressure`,
    data,
    layout,
    table: {
      columns: [axisTitle("Pressure", pUnit), axisTitle(label, xUnit)],
      rows: kept.map((level) => [level.pressure, level[variable]]),
    },
    pointCount: kept.length,
  };
}

export function profileFigures(profile: ProfileResponse): Figure[] {
  const levels = levelsOf(profile);
  const tUnit = unit(profile, "temperature");
  const sUnit = unit(profile, "salinity");
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
        text: both.map((level) => `${level.pressure} dbar`),
        marker: {
          color: CATEGORICAL[2],
          size: 7,
          line: { color: SURFACE, width: 1 },
        },
        hovertemplate: `Salinity: %{x}<br>Temperature: %{y} °C<br>%{text}<extra></extra>`,
      } as Data,
    ],
    layout: {
      ...baseLayout(
        axisTitle("Practical salinity", sUnit),
        axisTitle("Temperature", tUnit),
        false,
      ),
      showlegend: false,
    },
    table: {
      columns: [
        "Pressure (dbar)",
        axisTitle("Practical salinity", sUnit),
        axisTitle("Temperature", tUnit),
      ],
      rows: both.map((level) => [
        level.pressure,
        level.salinity,
        level.temperature,
      ]),
    },
    pointCount: both.length,
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
