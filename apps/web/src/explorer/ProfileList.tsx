import { formatUtc } from "../catalog/units";
import type { ProfilePoint } from "./profiles";

/** The plotted profiles as a table with buttons: the keyboard path to every result (PRD 14.5). */
export function ProfileList({
  points,
  selectedProfile,
  onSelect,
  limit = 200,
}: {
  points: ProfilePoint[];
  selectedProfile: string | null;
  onSelect: (point: { id: string; platform: string }) => void;
  limit?: number;
}) {
  const shown = points.slice(0, limit);
  return (
    <div className="table-wrap" data-testid="profile-list">
      <table className="data">
        <caption className="sr-only">
          Profiles for the filters, newest first
        </caption>
        <thead>
          <tr>
            <th scope="col">Float</th>
            <th scope="col">Cycle</th>
            <th scope="col">Observed (UTC)</th>
            <th scope="col">Longitude (°E)</th>
            <th scope="col">Latitude (°N)</th>
            <th scope="col">Levels</th>
            <th scope="col">
              <span className="sr-only">Select</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((point) => {
            const selected = point.id === selectedProfile;
            return (
              <tr key={point.id} aria-selected={selected}>
                <td>{point.platform}</td>
                <td>
                  {point.cycle}
                  {point.direction === "D" ? " (descending)" : ""}
                </td>
                <td>{formatUtc(point.observedAt)}</td>
                <td>{point.longitude.toFixed(3)}</td>
                <td>{point.latitude.toFixed(3)}</td>
                <td>{point.levelCount}</td>
                <td>
                  <button
                    type="button"
                    className="link"
                    aria-pressed={selected}
                    onClick={() =>
                      onSelect({ id: point.id, platform: point.platform })
                    }
                  >
                    {selected ? "Selected" : "Show profile"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {points.length > limit ? (
        <p className="chart-caption">
          Listing the first {limit} of {points.length.toLocaleString("en-GB")}{" "}
          profiles; the map shows all of them.
        </p>
      ) : null}
    </div>
  );
}
