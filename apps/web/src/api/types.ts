// Named aliases over the generated OpenAPI types (ADR-0064). Nothing here is hand-typed: every
// shape comes from `schema.d.ts`, regenerated with `pnpm --filter @floatchat/web generate:api`.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Environment = Schemas["Environment"];
export type TimeInterval = Schemas["TimeInterval"];
export type GeographyInfo = Schemas["GeographyInfo"];
export type QcPolicy = Schemas["QcPolicy"];
export type SlotCoverage = Schemas["SlotCoverage"];
export type CoverageSummary = Schemas["CoverageSummary"];
export type Column = Schemas["Column"];
export type ResultTable = Schemas["ResultTable"];
export type ChartAxis = Schemas["ChartAxis"];
export type ChartSpec = Schemas["ChartSpec"];
export type Execution = Schemas["Execution"];
export type Provenance = Schemas["Provenance"];
export type FloatSummary = Schemas["FloatSummary"];
export type ProfileHeader = Schemas["ProfileHeader"];
export type CollectionResponse = Schemas["CollectionResponse"];
export type FloatResponse = Schemas["FloatResponse"];
export type ProfileResponse = Schemas["ProfileResponse"];
export type CoverageResponse = Schemas["CoverageResponse"];
export type QueryResponse = Schemas["QueryResponse"];

/** A result-table cell as the sanitiser emits it (numbers, strings or null). */
export type Cell = string | number | boolean | null;

/** Rows of a result table keyed by column name. */
export function tableRecords(table: ResultTable): Array<Record<string, Cell>> {
  const names = table.columns.map((column) => column.name);
  return table.rows.map((row) => {
    const record: Record<string, Cell> = {};
    names.forEach((name, index) => {
      record[name] = (row[index] ?? null) as Cell;
    });
    return record;
  });
}

export function columnUnit(table: ResultTable, name: string): string | null {
  return table.columns.find((column) => column.name === name)?.unit ?? null;
}
