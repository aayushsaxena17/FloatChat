import { useMemo } from "react";
import type { ProfileResponse } from "../api/types";
import { formatUtc } from "../catalog/units";
import { ChartPanel } from "../charts/ChartPanel";
import { levelSummary, profileFigures } from "../charts/profile";
import { ProvenancePanel } from "../provenance/ProvenancePanel";

/** Temperature and salinity versus pressure, the T-S diagram, QC summary, provenance. */
export function ProfileCharts({ profile }: { profile: ProfileResponse }) {
  const figures = useMemo(() => profileFigures(profile), [profile]);
  const summary = useMemo(() => levelSummary(profile), [profile]);
  const header = profile.profile;
  const caption = `Float ${header.platform_number}, cycle ${header.cycle_number}, ${formatUtc(header.observed_at)}, ${header.longitude.toFixed(3)}°E ${header.latitude.toFixed(3)}°N; ${profile.levels.row_count} of ${header.level_count} levels after ${profile.qc_policy.name}.`;
  return (
    <div className="grid" data-testid="profile-charts">
      {figures.map((figure) => (
        <ChartPanel key={figure.key} figure={figure} caption={caption} />
      ))}
      <section className="panel">
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
                  <td>{row.modes}</td>
                  <td>{row.qc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ProvenancePanel provenance={profile.provenance} />
      </section>
    </div>
  );
}
