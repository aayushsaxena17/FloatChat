import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, MapGeoJSONFeature } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import "maplibre-gl/dist/maplibre-gl.css";
import { MAP_COLORS } from "../charts/palette";
import { ATTRIBUTION, offlineStyle } from "../map/style";
import { formatUtc } from "../catalog/units";
import {
  boundsOf,
  toFeatureCollection,
  trajectoryFeatures,
  type ProfilePoint,
  type TrajectoryPoint,
} from "./profiles";

export interface MapViewProps {
  points: ProfilePoint[];
  trajectory: TrajectoryPoint[];
  selectedProfile: string | null;
  regionBox?: {
    west: number;
    south: number;
    east: number;
    north: number;
  } | null;
  truncated?: boolean;
  compact?: boolean;
  onSelect: (point: { id: string; platform: string }) => void;
}

// MapLibre 6 resolves its worker relative to its own module URL, which Vite's dependency
// pre-bundle breaks; the worker is addressed explicitly through Vite in dev and in the build.
maplibregl.setWorkerUrl(workerUrl);

const SOURCES = {
  profiles: "profiles",
  trajectory: "trajectory",
  region: "region",
} as const;

function regionFeature(
  box: NonNullable<MapViewProps["regionBox"]>,
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: [
            [box.west, box.south],
            [box.east, box.south],
            [box.east, box.north],
            [box.west, box.north],
            [box.west, box.south],
          ],
        },
      },
    ],
  };
}

/**
 * Profile locations (clustered), the selected float's trajectory and the region bounding box
 * (ADR-0062). Cluster counts are DOM markers (no glyph server); the hover popup carries the
 * profile identity; clicking a point selects it. The list beside the map is the keyboard path.
 */
export function MapView({
  points,
  trajectory,
  selectedProfile,
  regionBox,
  truncated,
  compact,
  onSelect,
}: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const popup = useRef<maplibregl.Popup | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const [ready, setReady] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string>("");

  useEffect(() => {
    if (!container.current) return;
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: container.current,
        style: offlineStyle(),
        center: [70, 5],
        zoom: 2.6,
        minZoom: 1.5,
        maxZoom: 10,
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
        maxBounds: [
          [-30, -80],
          [170, 60],
        ],
      });
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "The map could not start (WebGL2 is required).",
      );
      return;
    }
    mapRef.current = map;
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    map.addControl(
      new maplibregl.ScaleControl({ unit: "metric" }),
      "bottom-right",
    );
    map.on("error", (event) => {
      setFailure(event.error?.message ?? "The map reported an error.");
    });
    map.on("load", () => {
      map.addSource(SOURCES.region, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "region-line",
        type: "line",
        source: SOURCES.region,
        paint: {
          "line-color": MAP_COLORS.region,
          "line-width": 1.2,
          "line-dasharray": [2, 2],
        },
      });
      map.addSource(SOURCES.trajectory, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "trajectory-line",
        type: "line",
        source: SOURCES.trajectory,
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": MAP_COLORS.trajectory, "line-width": 2 },
      });
      map.addLayer({
        id: "trajectory-points",
        type: "circle",
        source: SOURCES.trajectory,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": MAP_COLORS.trajectory,
          "circle-radius": 5,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1,
        },
      });
      map.addSource(SOURCES.profiles, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        cluster: true,
        clusterRadius: 36,
        clusterMaxZoom: 7,
        promoteId: "id",
      });
      map.addLayer({
        id: "clusters",
        type: "circle",
        source: SOURCES.profiles,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": MAP_COLORS.cluster,
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
          "circle-radius": [
            "step",
            ["get", "point_count"],
            14,
            10,
            18,
            50,
            22,
            200,
            27,
            1000,
            32,
          ],
        },
      });
      map.addLayer({
        id: "profile-points",
        type: "circle",
        source: SOURCES.profiles,
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            MAP_COLORS.selected,
            MAP_COLORS.profile,
          ],
          "circle-radius": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            9,
            6,
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            3,
            1.5,
          ],
        },
      });
      map.on("click", "clusters", (event) => {
        const feature = event.features?.[0];
        const clusterId = feature?.properties?.cluster_id as number | undefined;
        if (clusterId === undefined || feature?.geometry.type !== "Point")
          return;
        const source = map.getSource(SOURCES.profiles) as GeoJSONSource;
        void source.getClusterExpansionZoom(clusterId).then((zoom) => {
          map.easeTo({
            center: (feature.geometry as GeoJSON.Point).coordinates as [
              number,
              number,
            ],
            zoom,
          });
        });
      });
      map.on("click", "profile-points", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        selectRef.current({
          id: String(feature.properties.id),
          platform: String(feature.properties.platform),
        });
      });
      map.on("mouseenter", "profile-points", (event) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = event.features?.[0];
        if (!feature || feature.geometry.type !== "Point") return;
        popup.current?.remove();
        popup.current = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 10,
        })
          .setLngLat(
            (feature.geometry as GeoJSON.Point).coordinates as [number, number],
          )
          .setText(
            `Float ${feature.properties.platform}, cycle ${feature.properties.cycle}, ${formatUtc(String(feature.properties.observedAt))}`,
          )
          .addTo(map);
      });
      map.on("mouseleave", "profile-points", () => {
        map.getCanvas().style.cursor = "";
        popup.current?.remove();
      });
      map.on("mouseenter", "clusters", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "clusters", () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("mousemove", (event) => {
        setCursor(
          `${event.lngLat.lng.toFixed(2)}°E, ${event.lngLat.lat.toFixed(2)}°N`,
        );
      });
      const syncClusterLabels = () => {
        const seen = new Set<string>();
        const features = map.queryRenderedFeatures({
          layers: ["clusters"],
        }) as MapGeoJSONFeature[];
        for (const feature of features) {
          if (feature.geometry.type !== "Point") continue;
          const key = String(feature.properties.cluster_id);
          seen.add(key);
          const count = Number(feature.properties.point_count);
          const coordinates = (feature.geometry as GeoJSON.Point)
            .coordinates as [number, number];
          const existing = markers.current.get(key);
          if (existing) {
            existing.setLngLat(coordinates);
            existing.getElement().textContent = count.toLocaleString("en-GB");
          } else {
            const element = document.createElement("div");
            element.className = "cluster-label";
            element.setAttribute("aria-hidden", "true");
            element.textContent = count.toLocaleString("en-GB");
            markers.current.set(
              key,
              new maplibregl.Marker({ element })
                .setLngLat(coordinates)
                .addTo(map),
            );
          }
        }
        for (const [key, marker] of markers.current) {
          if (!seen.has(key)) {
            marker.remove();
            markers.current.delete(key);
          }
        }
      };
      map.on("idle", syncClusterLabels);
      map.on("move", syncClusterLabels);
      setReady(true);
    });
    return () => {
      for (const marker of markers.current.values()) marker.remove();
      markers.current.clear();
      popup.current?.remove();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource(SOURCES.profiles) as GeoJSONSource | undefined)?.setData(
      toFeatureCollection(points),
    );
    const bounds = boundsOf(points);
    if (bounds && points.length > 1)
      map.fitBounds(bounds, { padding: 48, maxZoom: 6, duration: 0 });
    else if (bounds) map.easeTo({ center: bounds[0], zoom: 5, duration: 0 });
  }, [points, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource(SOURCES.trajectory) as GeoJSONSource | undefined)?.setData(
      trajectoryFeatures(trajectory),
    );
  }, [trajectory, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource(SOURCES.region) as GeoJSONSource | undefined)?.setData(
      regionBox
        ? regionFeature(regionBox)
        : { type: "FeatureCollection", features: [] },
    );
  }, [regionBox, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const point of points) {
      map.setFeatureState(
        { source: SOURCES.profiles, id: point.id },
        { selected: point.id === selectedProfile },
      );
    }
  }, [points, selectedProfile, ready]);

  const count = points.length.toLocaleString("en-GB");
  return (
    <div className={`map-frame${compact ? " compact" : ""}`}>
      <div
        ref={container}
        className="map-canvas"
        aria-label="Map of profile locations"
      />
      {failure ? (
        <div className="map-fallback" role="status">
          <p>
            The map could not render ({failure}). The profile list beside it
            carries the same data.
          </p>
        </div>
      ) : null}
      <p className="map-overlay" role="status" data-testid="map-status">
        {count} profiles plotted
        {truncated
          ? " (showing the first 5,000 of more; narrow the filters)"
          : ""}
        {trajectory.length > 0
          ? `; trajectory of ${trajectory.length} positions`
          : ""}
        {cursor ? ` · cursor ${cursor}` : ""}
      </p>
    </div>
  );
}
