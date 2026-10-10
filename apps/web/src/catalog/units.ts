// Units and labels (PRD 14.5: units on every axis and table field; ADR-0065 for salinity).
// The API reports Stage 1 unit codes; the dashboard renders them with their scientific names.

export const UNIT_LABELS: Record<string, string> = {
  degree_C: "°C",
  "1": "PSS-78, dimensionless",
  dbar: "dbar",
  degrees_east: "°E",
  degrees_north: "°N",
  m: "m",
  count: "count",
};

export const VARIABLE_LABELS: Record<string, string> = {
  temperature: "Temperature",
  salinity: "Practical salinity",
  pressure: "Pressure",
};

export function unitLabel(unit: string | null | undefined): string | null {
  if (unit === null || unit === undefined || unit === "") return null;
  return UNIT_LABELS[unit] ?? unit;
}

/** "Temperature (°C)", "Practical salinity (PSS-78, dimensionless)", "Month". */
export function axisTitle(
  label: string,
  unit: string | null | undefined,
): string {
  const rendered = unitLabel(unit);
  return rendered ? `${label} (${rendered})` : label;
}

/** The variable behind a result column such as `temperature_mean`. */
export function variableOf(column: string): string | null {
  for (const variable of Object.keys(VARIABLE_LABELS)) {
    if (column === variable || column.startsWith(`${variable}_`))
      return variable;
  }
  return null;
}

/** Human label for a result column: `salinity_mean` -> "Practical salinity mean". */
export function columnLabel(column: string): string {
  const variable = variableOf(column);
  if (variable === null) return column.replace(/_/g, " ");
  const suffix = column.slice(variable.length + 1).replace(/_/g, " ");
  return suffix
    ? `${VARIABLE_LABELS[variable]} ${suffix}`
    : VARIABLE_LABELS[variable];
}

export function formatNumber(
  value: number | null | undefined,
  digits = 3,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number.isInteger(value)
    ? value.toLocaleString("en-GB")
    : value.toLocaleString("en-GB", { maximumFractionDigits: digits });
}

/** UTC timestamp rendered as `2025-01-31 23:23 UTC`; the convention is always stated. */
export function formatUtc(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]} ${match[2]} UTC` : value;
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  return value.slice(0, 10);
}
