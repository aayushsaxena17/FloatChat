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
    // Plotly mutates axis ranges during zoom. Keep React's figure unchanged so a
    // remount (Reset view or returning from Table) restores the original axes.
    void Plotly.react(node, structuredClone(data), structuredClone(layout), {
      displaylogo: false,
      responsive: true,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    });
    // Container widths change at responsive breakpoints, even without a window resize.
    let frame = 0;
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
              void Plotly.Plots.resize(node);
            });
          });
    observer?.observe(node);
    return () => {
      observer?.disconnect();
      cancelAnimationFrame(frame);
      Plotly.purge(node);
    };
  }, [data, layout]);
  return <div ref={element} className="chart" role="img" aria-label={label} />;
}
