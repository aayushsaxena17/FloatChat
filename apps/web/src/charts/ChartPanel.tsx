import { useId, useMemo, useState } from "react";
import { axisTitle, columnLabel } from "../catalog/units";
import { ChartNoAxesCombined, Table2, RotateCcw } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardHeader, CardContent } from "../components/ui/card";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "../components/ui/tabs";
import { DataTable } from "../components/DataTable";
import { DetailsDialog } from "../components/DetailsDialog";
import { Plot } from "./Plot";
import type { Figure } from "./spec";

/** One figure with its table view (PRD 14.5) and caption; the chart is never the only form. */
export function ChartPanel({
  figure,
  caption,
  compact = false,
  description,
  explanation,
  interactive = false,
}: {
  figure: Figure;
  caption?: string;
  compact?: boolean;
  description?: string;
  explanation?: string;
  interactive?: boolean;
}) {
  const id = useId();
  const [reset, setReset] = useState(0);
  const displayData = useMemo(
    () =>
      figure.data.map((trace) => ({
        ...trace,
        name: columnLabel(trace.name ?? ""),
      })),
    [figure.data],
  );
  const layout = useMemo(
    () => ({
      ...figure.layout,
      height: compact ? 280 : (figure.layout.height ?? 360),
    }),
    [figure.layout, compact],
  );
  const columns = figure.table.columns.map((column) => {
    if (column.endsWith("_count"))
      return axisTitle(columnLabel(column), "count");
    if (column.startsWith("temperature_"))
      return axisTitle(columnLabel(column), "degree_C");
    if (column.startsWith("salinity_"))
      return axisTitle(columnLabel(column), "1");
    return columnLabel(column);
  });
  return (
    <section className="chart-section" aria-labelledby={id}>
      <Card
        className={`panel chart-panel${interactive ? " profile-chart-panel" : ""}`}
      >
        <Tabs defaultValue="chart">
          <CardHeader className="panel-header">
            <h2 id={id}>{figure.title}</h2>
            <TabsList aria-label={`${figure.title} view`}>
              <TabsTrigger value="chart">
                <ChartNoAxesCombined aria-hidden="true" />
                Chart
              </TabsTrigger>
              <TabsTrigger value="table">
                <Table2 aria-hidden="true" />
                Table
              </TabsTrigger>
            </TabsList>
            {description ? (
              <p className="chart-description">{description}</p>
            ) : null}
          </CardHeader>
          <CardContent className="panel-content">
            <TabsContent value="table">
              <DataTable columns={columns} rows={figure.table.rows} />
            </TabsContent>
            <TabsContent value="chart">
              <Plot
                key={reset}
                data={displayData}
                layout={layout}
                label={`${figure.title}; use the table view for the values`}
              />
            </TabsContent>
            {explanation ? (
              <p className="chart-explanation">{explanation}</p>
            ) : null}
            {interactive ? (
              <div className="chart-tools">
                <span>Hover for readings · Drag to zoom</span>
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setReset((value) => value + 1)}
                >
                  <RotateCcw aria-hidden="true" />
                  Reset view
                </Button>
              </div>
            ) : null}
            <p className="chart-caption">
              {figure.pointCount.toLocaleString("en-GB")} plotted values ·
              Switch to Table for numerical values.
            </p>
            {caption ? (
              <div className="calculation-details">
                <DetailsDialog
                  title={`${figure.title}: calculation details`}
                  trigger="Calculation details"
                  description="How the displayed values were calculated for this selection."
                >
                  <p>{caption}</p>
                </DetailsDialog>
              </div>
            ) : null}
          </CardContent>
        </Tabs>
      </Card>
    </section>
  );
}
