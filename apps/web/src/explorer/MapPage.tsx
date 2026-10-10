import { Link } from "react-router";
import { StatusMessage } from "../components/StatusMessage";
import { ProvenancePanel } from "../provenance/ProvenancePanel";
import { FilterBar } from "./FilterBar";
import { MapView } from "./MapView";
import { ProfileList } from "./ProfileList";
import { useExplorerData } from "./useExplorerData";
import { toSearchParams } from "./filters";

export function MapPage() {
  const data = useExplorerData();
  const { filters, update, profiles, points, trajectory, float } = data;
  const first = profiles.data?.pages[0];
  return (
    <>
      <h1>Explore: map</h1>
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
                <span className="swatch" style={{ background: "#2a78d6" }} />
                profile location (clusters show their count)
              </span>
              <span>
                <span className="swatch" style={{ background: "#eb6834" }} />
                trajectory of float {filters.platform ?? "(select a profile)"}
              </span>
              <span>
                <span className="swatch" style={{ background: "#4a3aa7" }} />
                selected profile
              </span>
              <span>
                <span
                  className="swatch"
                  style={{
                    background: "transparent",
                    border: "1px dashed #e34948",
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
