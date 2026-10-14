import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  ArrowDown,
  ArrowUpRight,
  CalendarCheck,
  FileCheck,
  Thermometer,
} from "lucide-react";

/** Whether this browser can draw the scene at all; jsdom and text browsers cannot. */
function canRenderScene(): boolean {
  if (typeof window === "undefined") return false;
  if (!("WebGLRenderingContext" in window)) return false;
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
  } catch {
    return false;
  }
}

function prefersStill(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * The scene mounts after the first paint and only where WebGL exists; three.js arrives in
 * its own chunk (ADR-0076). Until then the hero shows its sky-to-water poster, which is also
 * the whole hero where the scene cannot run.
 */
function OceanScene() {
  const host = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const container = host.current;
    if (!container || !canRenderScene()) return;
    let dispose: (() => void) | undefined;
    let cancelled = false;
    void import("./oceanScene").then(({ mountOceanScene }) => {
      if (cancelled) return;
      try {
        dispose = mountOceanScene(container, {
          still: prefersStill(),
          onReady: () => setReady(true),
        });
      } catch {
        // A lost or refused context leaves the poster in place.
      }
    });
    return () => {
      cancelled = true;
      dispose?.();
    };
  }, []);
  return (
    <div
      className="ocean-hero-scene"
      ref={host}
      data-ready={ready}
      aria-hidden="true"
    />
  );
}

export function OceanHero({ query }: { query: string }) {
  return (
    <section className="ocean-hero" aria-labelledby="hero-title">
      <OceanScene />
      <div className="hero-copy">
        <h1 id="hero-title">The Indian Ocean, measured by drifting floats.</h1>
        <p className="hero-description">
          FloatChat brings together temperature, salinity and pressure profiles
          from Argo floats, shows how complete the coverage is, and keeps the
          source of every number.
        </p>
        <div className="hero-actions">
          <Link className="hero-primary" to={`/explore/map?${query}`}>
            Explore the map <ArrowUpRight size={17} aria-hidden="true" />
          </Link>
          <a className="hero-secondary" href="#observations">
            View observations <ArrowDown size={15} aria-hidden="true" />
          </a>
        </div>
        <ul className="hero-facts">
          <li>
            <Thermometer size={16} aria-hidden="true" />
            Core Argo: temperature, salinity, pressure
          </li>
          <li>
            <CalendarCheck size={16} aria-hidden="true" />
            Coverage checked month by month
          </li>
          <li>
            <FileCheck size={16} aria-hidden="true" />
            Every number traceable to its source
          </li>
        </ul>
      </div>
    </section>
  );
}
