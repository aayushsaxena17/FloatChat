import { StatusMessage } from "../components/StatusMessage";
import { Panel } from "../components/Panel";
import { FilterBar } from "./FilterBar";
import { ProfileCharts } from "./ProfileCharts";
import { ProfileList } from "./ProfileList";
import { ProfileSummary } from "./ProfileSummary";
import { useExplorerData } from "./useExplorerData";

export function ProfilesView() {
  const data = useExplorerData();
  const { filters, update, profiles, points, profile } = data;
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Profiles</h1>
          <p className="page-description">
            Temperature and salinity through the water column, one profile at a
            time.
          </p>
        </div>
      </div>
      <FilterBar
        filters={filters}
        update={update}
        parameters={data.parameters.data}
      />
      <div className="profiles-layout">
        <div>
          <StatusMessage
            loading={profiles.isPending && profiles.fetchStatus !== "idle"}
            error={profiles.error}
          >
            <Panel
              title={`Profiles (${points.length.toLocaleString("en-GB")})`}
              className="profiles-list-panel"
            >
              <p className="profiles-list-note">
                Newest observations first. Choose a row to inspect its water
                column.
              </p>
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
            </Panel>
          </StatusMessage>
        </div>
        <div>
          <StatusMessage
            loading={Boolean(filters.profile) && profile.isPending}
            error={profile.error}
          >
            <ProfileSummary
              profile={profile.data}
              onSelectNewest={
                points[0] ? () => data.select(points[0]) : undefined
              }
            />
          </StatusMessage>
        </div>
      </div>
      <div className="section-heading profile-analysis-heading">
        <div>
          <h2>Selected profile</h2>
          <p className="page-description">
            Temperature and salinity at each measured pressure.
          </p>
        </div>
      </div>
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
