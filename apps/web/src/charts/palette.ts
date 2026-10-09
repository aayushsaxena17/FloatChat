// The validated reference categorical palette (data-visualisation method, light mode), in its
// fixed slot order: blue, orange, aqua, yellow, magenta, green, violet, red. Slots are assigned
// by series identity and never cycled (ADR-0065); past three slots a scatter folds to "Other".
export const CATEGORICAL = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#e34948",
] as const;

export const SURFACE = "#fcfcfb";
export const TEXT_PRIMARY = "#0b0b0b";
export const TEXT_SECONDARY = "#52514e";
export const GRID = "#e6e5e1";

/** Map roles: profile points, the selected float's trajectory, the selected profile. */
export const MAP_COLORS = {
  profile: CATEGORICAL[0],
  trajectory: CATEGORICAL[1],
  selected: CATEGORICAL[6],
  cluster: CATEGORICAL[0],
  sea: "#eaf2f7",
  land: "#e9e6dd",
  coast: "#b9b3a3",
  graticule: "#cfd8df",
  region: CATEGORICAL[7],
} as const;

/** Stable slot for a series: the index of its name in the chart's declared series list. */
export function seriesColor(name: string, series: readonly string[]): string {
  const index = series.indexOf(name);
  return CATEGORICAL[(index < 0 ? series.length : index) % CATEGORICAL.length];
}
