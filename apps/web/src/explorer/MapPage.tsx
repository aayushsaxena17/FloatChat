import { Link } from "react-router";
import { StatusMessage } from "../components/StatusMessage";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import { FilterBar } from "./FilterBar";
import { LazyMapView as MapView } from "./LazyMapView";
import { ProfileList } from "./ProfileList";
import { useExplorerData } from "./useExplorerData";
import { toSearchParams } from "./filters";
import { MAP_COLORS } from "../charts/palette";

export function MapPage() {
  const data = useExplorerData();
  const { filters, update, profiles, points, trajectory, float } = data;
  const first = profiles.data?.pages[0];
  return (
    <>
      <div className="page-heading explorer-heading">
        <div>
          <p className="eyebrow">THE OBSERVATORY / SPATIAL EXPLORATION</p>
          <h1>Explore: map</h1>
          <p className="page-description">
            Follow an instrument. Trace its journey through the ocean.
          </p>
        </div>
        <span className="explorer-coordinate">20°E — 120°E / 60°S — 30°N</span>
      </div>
      <FilterBar
        filters={filters}
        update={update}
        parameters={data.parameters.data}
      />
      <StatusMessage
        loading={profiles.isPending && profiles.fetchStatus !== "idle"}
        error={profiles.error ?? float.error}
      >
        <div className="map-layout">
          <div>
            <MapView
              points={points}
              trajectory={trajectory}
              selectedProfile={filters.profile}
              regionBox={data.regionBox}
              truncated={profiles.data?.truncated}
              onSelect={data.select}
            />
            <div className="legend" aria-label="Map legend">
              <span>
                <span
                  className="swatch"
                  style={{ background: MAP_COLORS.profile }}
                />
                profile location (clusters show their count)
              </span>
              <span>
                <span
                  className="swatch"
                  style={{ background: MAP_COLORS.trajectory }}
                />
                trajectory of float {filters.platform ?? "(select a profile)"}
              </span>
              <span>
                <span
                  className="swatch"
                  style={{ background: MAP_COLORS.selected }}
                />
                selected profile
              </span>
              <span>
                <span
                  className="swatch"
                  style={{
                    background: "transparent",
                    border: `1px dashed ${MAP_COLORS.region}`,
                  }}
                />
                region bounding box
              </span>
            </div>
            {filters.profile ? (
              <p>
                <Link
                  to={`/explore/profiles?${toSearchParams(filters).toString()}`}
                >
                  Open the selected profile's charts
                </Link>
              </p>
            ) : null}
          </div>
          <div>
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
              />
            )}
            {first ? <ProvenancePanel provenance={first.provenance} /> : null}
          </div>
        </div>
      </StatusMessage>
    </>
  );
}
