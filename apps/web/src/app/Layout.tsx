import { NavLink, Outlet } from "react-router";
import { ReadinessStatus } from "./ReadinessStatus";

const LINKS = [
  ["/dashboard", "Dashboard"],
  ["/explore/map", "Map"],
  ["/explore/profiles", "Profiles"],
  ["/chat", "Chat"],
  ["/jobs", "Jobs"],
  ["/forecasts", "Forecasts"],
] as const;

export function Layout() {
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <NavLink to="/dashboard" className="brand">
          FLOATCHAT
        </NavLink>
        <nav aria-label="Primary">
          {LINKS.map(([path, label]) => (
            <NavLink key={path} to={path}>
              {label}
            </NavLink>
          ))}
        </nav>
        <ReadinessStatus />
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
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
          4.0), simplified per ADR-0060. Basemap: Natural Earth (public domain).
          Times are UTC; longitudes are degrees east in −180…180.
        </p>
      </footer>
    </div>
  );
}
