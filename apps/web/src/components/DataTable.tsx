import { formatNumber } from "../catalog/units";

type Cell = string | number | boolean | null;

/** A bounded table with units in its headers; numbers are formatted, nulls shown as a dash. */
export function DataTable({
  columns,
  rows,
  caption,
  limit = 500,
}: {
  columns: string[];
  rows: Cell[][];
  caption?: string;
  limit?: number;
}) {
  const shown = rows.slice(0, limit);
  return (
    <div className="table-wrap">
      <table className="data">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, index) => (
            <tr key={index}>
              {row.map((cell, position) => (
                <td key={position}>
                  {typeof cell === "number"
                    ? formatNumber(cell)
                    : (cell ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > limit ? (
        <p className="chart-caption">
          Showing the first {limit} of {rows.length} rows.
        </p>
      ) : null}
    </div>
  );
}
