import { useMemo } from "react";
import { usePlanQuery } from "../api/hooks";
import { ChartPanel } from "../charts/ChartPanel";
import { figuresFromChart } from "../charts/spec";
import { StatusMessage } from "../components/StatusMessage";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import { FilterBar } from "./FilterBar";
import { isReady, tsDiagramPlan, TS_PROFILE_LIMIT } from "./filters";
import { ProfileCharts } from "./ProfileCharts";
import { ProfileList } from "./ProfileList";
import { useExplorerData } from "./useExplorerData";

export function ProfilesView() {
  const data = useExplorerData();
  const { filters, update, profiles, points, profile } = data;
  const ready = isReady(filters);
  const plan = useMemo(
    () => (ready ? tsDiagramPlan(filters) : null),
    [filters, ready],
  );
  const ts = usePlanQuery(plan);
  const tsFigures = useMemo(
    () =>
      ts.data?.chart ? figuresFromChart(ts.data.chart, ts.data.result) : [],
    [ts.data],
  );
  return (
    <>
      <h1>Explore: profiles</h1>
      <FilterBar
        filters={filters}
        update={update}
        parameters={data.parameters.data}
      />
      <div className="map-layout">
        <div>
          <StatusMessage
            loading={profiles.isPending && profiles.fetchStatus !== "idle"}
            error={profiles.error}
          >
            <h2>Profiles ({points.length.toLocaleString("en-GB")})</h2>
            {points.length === 0 && profiles.data ? (
              <p className="status" role="status">
                No profiles match these filters.
              </p>
            ) : (
              <ProfileList
                points={points}
                selectedProfile={filters.profile}
                onSelect={data.select}
                limit={100}
              />
            )}
          </StatusMessage>
        </div>
        <div>
          <StatusMessage
            loading={ts.isPending && ts.fetchStatus !== "idle"}
            error={ts.error}
          >
            {tsFigures.map((figure) => (
              <ChartPanel
                key={figure.key}
                figure={figure}
                caption={`Newest ${Math.min(TS_PROFILE_LIMIT, ts.data?.chart?.series.length ?? 0)} profiles; ${ts.data?.interpretation.transformation as string}`}
              />
            ))}
            {ts.data ? (
              <ProvenancePanel provenance={ts.data.provenance} />
            ) : null}
          </StatusMessage>
        </div>
      </div>
      <h2 style={{ marginTop: 16 }}>Selected profile</h2>
      {!filters.profile ? (
        <p className="status" role="status">
          Select a profile from the list (or on the map) to see its temperature,
          salinity and T-S charts.
        </p>
      ) : (
        <StatusMessage loading={profile.isPending} error={profile.error}>
          {profile.data ? <ProfileCharts profile={profile.data} /> : null}
        </StatusMessage>
      )}
    </>
  );
}
