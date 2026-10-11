import { useMemo } from "react";
import type { ProfileResponse } from "../api/types";
import { formatUtc } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { levelSummary, profileFigures } from "../charts/profile";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import { ShieldCheck } from "lucide-react";

/** Temperature and salinity versus pressure, the T-S diagram, QC summary, provenance. */
export function ProfileCharts({ profile }: { profile: ProfileResponse }) {
  const figures = useMemo(() => profileFigures(profile), [profile]);
  const summary = useMemo(() => levelSummary(profile), [profile]);
  const header = profile.profile;
  const caption = `Float ${header.platform_number}, cycle ${header.cycle_number}, ${formatUtc(header.observed_at)}, ${header.longitude.toFixed(3)}°E ${header.latitude.toFixed(3)}°N; ${profile.levels.row_count} of ${header.level_count} levels after ${profile.qc_policy.name}.`;
  return (
    <div className="profile-analysis" data-testid="profile-charts">
      <div className="profile-charts-grid">
        {figures.map((figure, index) => (
          <ChartPanel
            key={figure.key}
            figure={figure}
            caption={caption}
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
