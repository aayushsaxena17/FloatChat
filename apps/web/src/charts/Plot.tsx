import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";
import Plotly from "./plotly";

/** A Plotly figure in a div: `Plotly.react` on every change, purged on unmount. */
export function Plot({
  data,
  layout,
  label,
}: {
  data: Data[];
  layout: Partial<Layout>;
  label: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    void Plotly.react(node, data, layout, {
      displaylogo: false,
      responsive: true,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    });
    return () => {
      Plotly.purge(node);
    };
  }, [data, layout]);
  return <div ref={element} className="chart" role="img" aria-label={label} />;
}
