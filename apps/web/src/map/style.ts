// The offline MapLibre style (ADR-0062): sea background, Natural Earth land, a 10-degree
// graticule as line layers. No glyphs, sprites or tiles: nothing is fetched from a server.
import type { StyleSpecification } from "maplibre-gl";
import { MAP_COLORS } from "../charts/palette";
import land from "./land.json";

export const ENVELOPE = { west: 20, south: -60, east: 120, north: 30 } as const;
const CLIP = (
  land as {
    properties: {
      clip_box: { west: number; south: number; east: number; north: number };
    };
  }
).properties.clip_box;

export function graticule(step = 10): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (
    let lon = Math.ceil(CLIP.west / step) * step;
    lon <= CLIP.east;
    lon += step
  ) {
    features.push({
      type: "Feature",
      properties: { kind: "meridian", value: lon },
      geometry: {
        type: "LineString",
        coordinates: [
          [lon, CLIP.south],
          [lon, CLIP.north],
        ],
      },
    });
  }
  for (
    let lat = Math.ceil(CLIP.south / step) * step;
    lat <= CLIP.north;
    lat += step
  ) {
    features.push({
      type: "Feature",
      properties: { kind: "parallel", value: lat },
      geometry: {
        type: "LineString",
        coordinates: [
          [CLIP.west, lat],
          [CLIP.east, lat],
        ],
      },
    });
  }
  return { type: "FeatureCollection", features };
}

export function offlineStyle(): StyleSpecification {
  return {
    version: 8,
    name: "FloatChat offline",
    sources: {
      land: {
        type: "geojson",
        data: land as unknown as GeoJSON.FeatureCollection,
      },
      graticule: { type: "geojson", data: graticule() },
    },
    layers: [
      {
        id: "sea",
        type: "background",
        paint: { "background-color": MAP_COLORS.sea },
      },
      {
        id: "land-fill",
        type: "fill",
        source: "land",
        paint: { "fill-color": MAP_COLORS.land },
      },
      {
        id: "land-line",
        type: "line",
        source: "land",
        paint: { "line-color": MAP_COLORS.coast, "line-width": 0.8 },
      },
      {
        id: "graticule",
        type: "line",
        source: "graticule",
        paint: {
          "line-color": MAP_COLORS.graticule,
          "line-width": 0.6,
          "line-dasharray": [4, 4],
        },
      },
    ],
  };
}

export const ATTRIBUTION =
  "Basemap: Natural Earth (public domain). Regions: Marine Regions IHO Sea Areas v3 (CC-BY 4.0).";
