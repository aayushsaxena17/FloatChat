import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";

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
    // Plotly (about 500 kB gzipped) loads with the first chart, not with the page (ADR-0068).
    let cancelled = false;
    let frame = 0;
    let observer: ResizeObserver | null = null;
    let plotly: typeof import("./plotly").default | null = null;
    void import("./plotly").then(({ default: loaded }) => {
      if (cancelled) return;
      plotly = loaded;
      // Plotly mutates axis ranges during zoom. Keep React's figure unchanged so a
      // remount (Reset view or returning from Table) restores the original axes.
      void loaded.react(node, structuredClone(data), structuredClone(layout), {
        displaylogo: false,
        responsive: true,
        modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
      });
      // Container widths change at responsive breakpoints, even without a window resize.
      observer =
        typeof ResizeObserver === "undefined"
          ? null
          : new ResizeObserver(() => {
              cancelAnimationFrame(frame);
              frame = requestAnimationFrame(() => {
                void loaded.Plots.resize(node);
              });
            });
      observer?.observe(node);
    });
    return () => {
      cancelled = true;
      observer?.disconnect();
      cancelAnimationFrame(frame);
      plotly?.purge(node);
    };
  }, [data, layout]);
  return <div ref={element} className="chart" role="img" aria-label={label} />;
}
