// The categorical palette for the light surfaces, validated with the data-viz palette
// checks (lightness band, chroma floor, adjacent-pair CVD separation, normal-vision floor),
// in its fixed slot order: blue, orange, aqua, yellow, magenta, green, violet, red. Slots are
// assigned by series identity and never cycled (ADR-0065); past three slots a scatter folds
// to "Other". Three slots sit below 3:1 on white, which the table view of every chart covers.
export const CATEGORICAL = [
  "#0077b6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#e34948",
] as const;

export const SURFACE = "#ffffff";
export const TEXT_PRIMARY = "#0a1d4f";
export const TEXT_SECONDARY = "#46577f";
export const GRID = "#e4eef3";

/** Map roles: profile points, the selected float's trajectory, the selected profile. */
export const MAP_COLORS = {
  profile: CATEGORICAL[0],
  trajectory: CATEGORICAL[1],
  selected: CATEGORICAL[6],
  cluster: CATEGORICAL[0],
  sea: "#dcf2f8",
  land: "#f3f5f7",
  coast: "#a9bcc8",
  graticule: "#bfe1ec",
  region: CATEGORICAL[7],
} as const;

/** Stable slot for a series: the index of its name in the chart's declared series list. */
export function seriesColor(name: string, series: readonly string[]): string {
  const index = series.indexOf(name);
  return CATEGORICAL[(index < 0 ? series.length : index) % CATEGORICAL.length];
}
