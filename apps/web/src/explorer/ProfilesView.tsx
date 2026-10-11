import { StatusMessage } from "../components/StatusMessage";
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
      <div className="page-heading explorer-heading">
        <div>
          <p className="eyebrow">THE OBSERVATORY / VERTICAL EXPLORATION</p>
          <h1>Explore: profiles</h1>
          <p className="page-description">
            Read the water column through temperature, salinity, and pressure.
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
            <h2>Profiles ({points.length.toLocaleString("en-GB")})</h2>
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
          <p className="eyebrow">ONE OBSERVATION / THE WATER COLUMN</p>
          <h2>Selected profile</h2>
          <p className="page-description">
            Temperature and salinity at each measured pressure. Hover for
            values; drag to zoom.
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
