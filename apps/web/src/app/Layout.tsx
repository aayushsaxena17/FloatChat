import { NavLink, Outlet, useLocation } from "react-router";
import {
  LayoutDashboard,
  Map,
  Layers,
  MessageSquare,
  ListChecks,
  TrendingUp,
  ArrowUpRight,
} from "lucide-react";
import { WaveMark } from "../components/WaveMark";
import { ReadinessStatus } from "./ReadinessStatus";

const LINKS = [
  ["/dashboard", "Dashboard", LayoutDashboard],
  ["/explore/map", "Map", Map],
  ["/explore/profiles", "Profiles", Layers],
  ["/chat", "Chat", MessageSquare],
  ["/jobs", "Jobs", ListChecks],
  ["/forecasts", "Forecasts", TrendingUp],
] as const;

/** Routes that fill the viewport like an app: their own scrolling, no page footer. */
const APP_ROUTES = ["/chat"];
/** Routes that lay out their own width, so the hero can run edge to edge. */
const WIDE_ROUTES = ["/dashboard"];

export function Layout() {
  const { pathname } = useLocation();
  const app = APP_ROUTES.some((route) => pathname.startsWith(route));
  const wide = WIDE_ROUTES.some((route) => pathname.startsWith(route));
  return (
    <div className={app ? "shell shell-app" : "shell"}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink to="/dashboard" className="brand" aria-label="FloatChat home">
          <span className="brand-symbol">
            <WaveMark size={20} />
          </span>
          FloatChat
        </NavLink>
        <nav aria-label="Primary">
          {LINKS.map(([path, label, Icon]) => (
            <NavLink key={path} to={path}>
              <Icon size={16} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
        <ReadinessStatus />
      </header>
      <main id="main" tabIndex={-1} className={wide ? "main-wide" : undefined}>
        <Outlet />
      </main>
      {app ? null : (
        <footer className="footer">
          <div className="footer-inner">
            <div className="footer-intro">
              <div className="footer-brand">
                <strong>FloatChat</strong>
                <p>
                  Argo float observations in the Indian Ocean, with coverage and
                  provenance for every number. Times are UTC; depths are
                  pressure in dbar.
                </p>
              </div>
              <ul className="footer-links">
                <li>
                  <a
                    href="https://argo.ucsd.edu/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Argo programme <ArrowUpRight size={13} aria-hidden="true" />
                  </a>
                </li>
                <li>
                  <a
                    href="https://argovis.colorado.edu/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Argovis <ArrowUpRight size={13} aria-hidden="true" />
                  </a>
                </li>
                <li>
                  <a
                    href="https://www.marineregions.org/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Marine Regions <ArrowUpRight size={13} aria-hidden="true" />
                  </a>
                </li>
              </ul>
            </div>
            <details>
              <summary>Data sources and acknowledgements</summary>
              <p>
                Data: Argo (2000). Argo float data and metadata from Global Data
                Assembly Centre (Argo GDAC). SEANOE.{" "}
                <a href="https://doi.org/10.17882/42182">doi:10.17882/42182</a>.
                Access service: Tucker, Giglio, Scanderbeg and Shen (2020),
                Argovis,{" "}
                <a href="https://doi.org/10.1175/JTECH-D-19-0041.1">
                  doi:10.1175/JTECH-D-19-0041.1
                </a>
                .
              </p>
              <p>
                Regions: Flanders Marine Institute (2018), IHO Sea Areas,
                version 3, Marine Regions,{" "}
                <a href="https://doi.org/10.14284/323">doi:10.14284/323</a>{" "}
                (CC-BY 4.0), simplified per ADR-0060. Basemap: Natural Earth
                (public domain). Longitudes are degrees east in −180…180.
              </p>
            </details>
          </div>
        </footer>
      )}
    </div>
  );
}
