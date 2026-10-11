import { Layers, ArrowDown, ArrowRight } from "lucide-react";
import type { ProfileResponse } from "../api/types";
import { formatNumber, formatUtc } from "../catalog/units";
import { levelsOf } from "../charts/profile";
import { Panel } from "../components/Panel";
import { Button } from "../components/ui/button";

function coordinate(value: number, positive: string, negative: string) {
  return `${Math.abs(value).toFixed(3)}°${value < 0 ? negative : positive}`;
}

export function ProfileSummary({
  profile,
  onSelectNewest,
}: {
  profile?: ProfileResponse;
  onSelectNewest?: () => void;
}) {
  if (!profile)
    return (
      <Panel title="Profile details" className="profile-summary">
        <div className="profile-summary-empty">
          <Layers size={28} aria-hidden="true" />
          <h3>Start with one observation</h3>
          <p>
            A float is the instrument. A profile is one set of readings through
            the water column, collected on a single cycle.
          </p>
          <p>
            Select a row to see its location, measurement range, and three
            detailed charts.
          </p>
          {onSelectNewest ? (
            <Button variant="outline" onClick={onSelectNewest}>
              Inspect newest profile <ArrowRight aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </Panel>
    );
  const header = profile.profile;
  const levels = levelsOf(profile);
  const temperatures = levels.flatMap((level) =>
    level.temperature === null ? [] : [level.temperature],
  );
  const salinities = levels.flatMap((level) =>
    level.salinity === null ? [] : [level.salinity],
  );
  const range = (values: number[], unit: string) =>
    values.length
      ? `${formatNumber(Math.min(...values))}–${formatNumber(Math.max(...values))} ${unit}`
      : "No retained values";
  return (
    <Panel title="Profile details" className="profile-summary">
      <div className="profile-identity">
        <Layers size={20} aria-hidden="true" />
        <div>
          <strong>Float {header.platform_number}</strong>
          <span>
            Cycle {header.cycle_number} ·{" "}
            {header.direction === "D" ? "Descending" : "Ascending"} observation
          </span>
        </div>
      </div>
      <dl className="profile-summary-facts">
        <dt>Observed</dt>
        <dd>{formatUtc(header.observed_at)}</dd>
        <dt>Location</dt>
        <dd>
          {coordinate(header.latitude, "N", "S")} ·{" "}
          {coordinate(header.longitude, "E", "W")}
        </dd>
        <dt>Retained levels</dt>
        <dd>
          {formatNumber(levels.length)} of {formatNumber(header.level_count)}
        </dd>
        <dt>Pressure range</dt>
        <dd>
          {range(
            levels.map((level) => level.pressure),
            "dbar",
          )}
        </dd>
        <dt>Temperature range</dt>
        <dd>{range(temperatures, "°C")}</dd>
        <dt>Salinity range</dt>
        <dd>{range(salinities, "PSS-78")}</dd>
      </dl>
      <p className="profile-summary-guide">
        <ArrowDown size={16} aria-hidden="true" /> Read the charts below:
        pressure increases downward, toward deeper water.
      </p>
    </Panel>
  );
}
