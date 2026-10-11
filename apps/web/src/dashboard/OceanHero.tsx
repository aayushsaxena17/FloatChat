import { ArrowDown, ArrowUpRight, Compass, Waves } from "lucide-react";
import { Link } from "react-router";

// An abstract ocean-current study, deliberately separate from the observed data below.
// Static SVG keeps this illustration crisp, offline-capable and inexpensive to render.
function OceanContours() {
  return (
    <svg
      className="ocean-contours"
      viewBox="0 0 900 640"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id="contour-ink"
          x1="180"
          y1="580"
          x2="780"
          y2="60"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#4bd9b0" stopOpacity="0.04" />
          <stop offset="0.48" stopColor="#66dfc8" stopOpacity="0.65" />
          <stop offset="1" stopColor="#9edbdf" stopOpacity="0.1" />
        </linearGradient>
        <radialGradient id="ocean-glow">
          <stop stopColor="#176c66" stopOpacity="0.26" />
          <stop offset="1" stopColor="#176c66" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="520" cy="300" rx="380" ry="310" fill="url(#ocean-glow)" />
      <g stroke="url(#contour-ink)" strokeWidth="0.85">
        {Array.from({ length: 40 }, (_, index) => {
          const i = index;
          return (
            <path
              key={i}
              d={`M ${120 + i * 13} -40 C ${580 + i * 10} ${50 + i * 5}, ${-50 + i * 12} ${190 + i * 3}, ${220 + i * 11} ${315 + i * 3} S ${800 + i * 4} ${390 - i * 2}, ${520 + i * 14} 700`}
            />
          );
        })}
      </g>
      <g stroke="#84b3b4" strokeOpacity="0.16" strokeDasharray="2 7">
        <path d="M 190 0 V 640 M 430 0 V 640 M 670 0 V 640 M 0 140 H 900 M 0 380 H 900" />
        <circle cx="550" cy="290" r="164" />
        <circle cx="550" cy="290" r="245" />
      </g>
      <g stroke="#b3dfd7" strokeOpacity="0.6">
        <path d="M 423 140 H 437 M 430 133 V 147 M 663 380 H 677 M 670 373 V 387 M 183 380 H 197 M 190 373 V 387" />
      </g>
      <g fill="#8de6cf">
        <circle cx="475" cy="242" r="3" />
        <circle cx="636" cy="368" r="3" />
        <circle cx="566" cy="472" r="2.5" />
      </g>
      <circle
        className="ocean-pulse"
        cx="475"
        cy="242"
        r="12"
        stroke="#8de6cf"
        strokeOpacity="0.35"
      />
    </svg>
  );
}

export function OceanHero({ query }: { query: string }) {
  return (
    <section className="ocean-hero" aria-labelledby="hero-title">
      <OceanContours />
      <div className="hero-topline">
        <span>
          <span className="hero-marker" /> THE ARGO OBSERVATORY
        </span>
        <span className="hero-edition">INDIAN OCEAN / 01</span>
      </div>
      <div className="hero-copy">
        <p className="hero-kicker">A WINDOW BENEATH THE SURFACE</p>
        <h1 id="hero-title">
          An ocean of data.
          <br />
          <em>A deeper understanding.</em>
        </h1>
        <p className="hero-description">
          Follow the floats. Read the currents. Explore temperature, salinity,
          and the stories held beneath the Indian Ocean.
        </p>
        <div className="hero-actions">
          <Link className="hero-primary" to={`/explore/map?${query}`}>
            <Compass size={17} aria-hidden="true" /> Explore the ocean{" "}
            <ArrowUpRight size={17} aria-hidden="true" />
          </Link>
          <a className="hero-secondary" href="#observations">
            View observations <ArrowDown size={15} aria-hidden="true" />
          </a>
        </div>
      </div>
      <div className="hero-footnote">
        <span>
          <Waves size={16} aria-hidden="true" /> CORE ARGO{" "}
          <span className="hero-divider">/</span> TEMPERATURE · SALINITY ·
          PRESSURE
        </span>
        <span className="hero-art-caption">
          OCEAN CURRENT STUDY · ILLUSTRATION
        </span>
      </div>
    </section>
  );
}
