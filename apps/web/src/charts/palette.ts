// The validated reference categorical palette (ocean observatory theme), in its
// fixed slot order: blue, orange, aqua, yellow, magenta, green, violet, red. Slots are assigned
// by series identity and never cycled (ADR-0065); past three slots a scatter folds to "Other".
export const CATEGORICAL = [
  "#74c7eb",
  "#f3b27f",
  "#7cdec0",
  "#ead28c",
  "#efa9c9",
  "#97cd9c",
  "#b5adf4",
  "#f19696",
] as const;

export const SURFACE = "#0b202a";
export const TEXT_PRIMARY = "#e1edea";
export const TEXT_SECONDARY = "#a0b6bd";
export const GRID = "#24404a";

/** Map roles: profile points, the selected float's trajectory, the selected profile. */
export const MAP_COLORS = {
  profile: CATEGORICAL[0],
  trajectory: CATEGORICAL[1],
  selected: CATEGORICAL[6],
  cluster: CATEGORICAL[0],
  sea: "#081b27",
  land: "#24404a",
  coast: "#52727c",
  graticule: "#1e3946",
  region: CATEGORICAL[7],
} as const;

/** Stable slot for a series: the index of its name in the chart's declared series list. */
export function seriesColor(name: string, series: readonly string[]): string {
  const index = series.indexOf(name);
  return CATEGORICAL[(index < 0 ? series.length : index) % CATEGORICAL.length];
}
