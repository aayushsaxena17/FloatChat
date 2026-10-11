import { useMemo } from "react";
import type { ProfileResponse } from "../api/types";
import { formatCoordinate, formatNumber, formatUtc } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { levelSummary, profileFigures } from "../charts/profile";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import { ShieldCheck } from "lucide-react";

/** Temperature and salinity versus pressure, the T-S diagram, QC summary, provenance. */
export function ProfileCharts({ profile }: { profile: ProfileResponse }) {
  const figures = useMemo(() => profileFigures(profile), [profile]);
  const summary = useMemo(() => levelSummary(profile), [profile]);
  const header = profile.profile;
  const qualityName =
    {
      science_ready: "Science ready",
      raw: "Raw measurements",
      mode_selected: "Mode selected",
    }[profile.qc_policy.name] ?? profile.qc_policy.name;
  return (
    <div className="profile-analysis" data-testid="profile-charts">
      <div className="profile-charts-grid">
        {figures.map((figure, index) => (
          <ChartPanel
            key={figure.key}
            figure={figure}
            interactive
            description={
              [
                "How water temperature changes with pressure.",
                "How saltiness changes with pressure.",
                "Temperature and salinity paired at each level.",
              ][index]
            }
            explanation={
              index === 2
                ? "Point colour shows pressure: warm colours are shallower, cool colours deeper. Salinity uses the dimensionless PSS-78 scale."
                : "Pressure increases downward. The line follows measured values; excluded readings leave gaps."
            }
          />
        ))}
      </div>
      <section className="panel profile-method">
        <details>
          <summary>How these charts are built</summary>
          <div className="profile-method-content">
            <dl className="profile-method-facts">
              <div>
                <dt>Observation</dt>
                <dd>
                  Float {header.platform_number} · Cycle {header.cycle_number}
                </dd>
              </div>
              <div>
                <dt>Recorded at</dt>
                <dd>{formatUtc(header.observed_at)}</dd>
              </div>
              <div>
                <dt>Location</dt>
                <dd>
                  {formatCoordinate(header.latitude, "N", "S")} ·{" "}
                  {formatCoordinate(header.longitude, "E", "W")}
                </dd>
              </div>
              <div>
                <dt>Quality policy</dt>
                <dd>{qualityName}</dd>
              </div>
            </dl>
            <div className="profile-method-grid">
              {figures.map((figure, index) => (
                <div key={figure.key}>
                  <h3>
                    {
                      [
                        "Temperature and pressure",
                        "Salinity and pressure",
                        "Temperature and salinity",
                      ][index]
                    }
                  </h3>
                  <p>
                    {
                      [
                        "Each valid temperature reading is placed at its measured pressure. Read from top to bottom to move deeper.",
                        "Each valid salinity reading is placed at its measured pressure. Bends in the line reflect changes in the recorded water column.",
                        "Each point pairs temperature and salinity from the same level. Point colour shows that level’s pressure.",
                      ][index]
                    }
                  </p>
                  <strong>
                    {formatNumber(figure.pointCount)}{" "}
                    {index === 2 ? "paired readings" : "readings"} shown
                  </strong>
                </div>
              ))}
            </div>
            <p className="profile-method-note">
              The pressure charts follow measurements without smoothing. Missing
              or excluded readings leave gaps; the temperature–salinity chart
              includes only levels where both values are available.
            </p>
          </div>
        </details>
      </section>
      <section className="panel profile-quality">
        <details>
          <summary>
            <ShieldCheck size={18} aria-hidden="true" />
            Quality & processing details
          </summary>
          <div className="profile-quality-content">
            <h2>Levels and quality control</h2>
            <p className="chart-caption">
              QC policy {profile.qc_policy.name} ({profile.qc_policy.version}):{" "}
              {profile.qc_policy.description}.
            </p>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Variable</th>
                    <th scope="col">Levels kept</th>
                    <th scope="col">Data modes</th>
                    <th scope="col">QC flags</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map((row) => (
                    <tr key={row.variable}>
                      <td>{row.variable}</td>
                      <td>{row.kept}</td>
                      <td>
                        {row.modes
                          .replace(/\bR:/g, "Original (R):")
                          .replace(/\bA:/g, "Adjusted (A):")
                          .replace(/\bD:/g, "Delayed mode (D):")}
                      </td>
                      <td>
                        {row.qc
                          .replace(/\b1:/g, "Good (1):")
                          .replace(/\b2:/g, "Probably good (2):")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ProvenancePanel provenance={profile.provenance} />
          </div>
        </details>
      </section>
    </div>
  );
}
