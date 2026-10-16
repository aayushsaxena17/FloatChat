import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
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
function OceanScene({
  copy,
  hero,
}: {
  copy: RefObject<HTMLDivElement | null>;
  hero: RefObject<HTMLElement | null>;
}) {
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
          copy: copy.current,
          // Written straight to the element: it changes every frame while the sea moves.
          onWaterline: (fraction) =>
            hero.current?.style.setProperty(
              "--waterline",
              `${(fraction * 100).toFixed(2)}%`,
            ),
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
  }, [copy, hero]);
  return (
    <div
      className="ocean-hero-scene"
      ref={host}
      data-ready={ready}
      aria-hidden="true"
    />
  );
}

/** The headline rises word by word out of the water; real spaces keep the accessible name. */
const TITLE = "The Indian Ocean, measured by drifting floats.";

function HeroCopy({
  query,
  decorative = false,
}: {
  query: string;
  decorative?: boolean;
}) {
  return (
    <>
      <h1 id={decorative ? undefined : "hero-title"}>
        {TITLE.split(" ").map((word, index) => (
          <Fragment key={index}>
            {index > 0 ? " " : null}
            <span
              className="hero-word"
              style={{ "--word": index } as CSSProperties}
            >
              <span>{word}</span>
            </span>
          </Fragment>
        ))}
      </h1>
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
    </>
  );
}

/**
 * The copy is drawn twice, clipped at the waterline the scene reports: navy ink where it
 * sits over the sky and the surface, white where it sits in the water. The upper layer is
 * decorative and inert; the lower one is the real, focusable copy.
 */
export function OceanHero({ query }: { query: string }) {
  const copy = useRef<HTMLDivElement>(null);
  const hero = useRef<HTMLElement>(null);
  return (
    <section className="ocean-hero" aria-labelledby="hero-title" ref={hero}>
      <OceanScene copy={copy} hero={hero} />
      <div className="hero-copy hero-copy-above" aria-hidden="true" inert>
        <div className="hero-block">
          <HeroCopy query={query} decorative />
        </div>
      </div>
      <div className="hero-copy hero-copy-below">
        <div className="hero-block" ref={copy}>
          <HeroCopy query={query} />
        </div>
      </div>
    </section>
  );
}
