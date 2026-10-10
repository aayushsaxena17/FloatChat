import { useId, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Plot } from "./Plot";
import type { Figure } from "./spec";

/** One figure with its table view (PRD 14.5) and caption; the chart is never the only form. */
export function ChartPanel({
  figure,
  caption,
}: {
  figure: Figure;
  caption?: string;
}) {
  const [table, setTable] = useState(false);
  const id = useId();
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-header">
        <h2 id={id}>{figure.title}</h2>
        <div className="panel-actions">
          <button
            type="button"
            aria-pressed={!table}
            onClick={() => setTable(false)}
          >
            Chart
          </button>
          <button
            type="button"
            aria-pressed={table}
            onClick={() => setTable(true)}
          >
            Table
          </button>
        </div>
      </div>
      {table ? (
        <DataTable columns={figure.table.columns} rows={figure.table.rows} />
      ) : (
        <Plot
          data={figure.data}
          layout={figure.layout}
          label={`${figure.title}; use the table view for the values`}
        />
      )}
      <p className="chart-caption">
        {figure.pointCount.toLocaleString("en-GB")} points.
        {caption ? ` ${caption}` : ""}
      </p>
    </section>
  );
}
