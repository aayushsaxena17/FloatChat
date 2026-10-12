import { NavLink, Outlet } from "react-router";
import {
  LayoutDashboard,
  Map,
  Layers,
  MessageSquare,
  ListTodo,
  ChartNoAxesCombined,
  Waves,
  ArrowUpRight,
} from "lucide-react";
import { ReadinessStatus } from "./ReadinessStatus";

const LINKS = [
  ["/dashboard", "Dashboard", LayoutDashboard, false],
  ["/explore/map", "Map", Map, false],
  ["/explore/profiles", "Profiles", Layers, false],
  ["/chat", "Chat", MessageSquare, false],
  ["/jobs", "Jobs", ListTodo, true],
  ["/forecasts", "Forecasts", ChartNoAxesCombined, true],
] as const;

export function Layout() {
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink to="/dashboard" className="brand" aria-label="FloatChat home">
          <span className="brand-symbol">
            <Waves size={22} aria-hidden="true" />
          </span>
          <span>
            FloatChat<span className="brand-subtitle">ARGO OBSERVATORY</span>
          </span>
        </NavLink>
        <nav aria-label="Primary">
          {LINKS.map(([path, label, Icon, upcoming]) => (
            <NavLink
              key={path}
              to={path}
              className={upcoming ? "upcoming" : undefined}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
              {upcoming ? <span className="nav-soon">Soon</span> : null}
            </NavLink>
          ))}
        </nav>
        <ReadinessStatus />
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <div className="footer-intro">
          <Waves size={17} aria-hidden="true" />
          <span>Ocean observations, with a traceable source.</span>
          <a href="https://argo.ucsd.edu/" target="_blank" rel="noreferrer">
            About Argo <ArrowUpRight size={13} aria-hidden="true" />
          </a>
        </div>
        <details>
          <summary>Data sources & acknowledgements</summary>
          <p>
            Data: Argo (2000). Argo float data and metadata from Global Data
            Assembly Centre (Argo GDAC). SEANOE.{" "}
            <a href="https://doi.org/10.17882/42182">doi:10.17882/42182</a>.
            Access service: Tucker, Giglio, Scanderbeg and Shen (2020), Argovis,{" "}
            <a href="https://doi.org/10.1175/JTECH-D-19-0041.1">
              doi:10.1175/JTECH-D-19-0041.1
            </a>
            .
          </p>
          <p>
            Regions: Flanders Marine Institute (2018), IHO Sea Areas, version 3,
            Marine Regions,{" "}
            <a href="https://doi.org/10.14284/323">doi:10.14284/323</a> (CC-BY
            4.0), simplified per ADR-0060. Basemap: Natural Earth (public
            domain). Times are UTC; longitudes are degrees east in −180…180.
          </p>
        </details>
      </footer>
    </div>
  );
}
