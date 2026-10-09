// Pure helpers over profile headers: records, GeoJSON for the map, trajectories.
import type { CollectionResponse, FloatResponse } from "../api/types";
import { tableRecords, type Cell } from "../api/types";
import type { ProfilesPage } from "../api/hooks";

export interface ProfilePoint {
  id: string;
  platform: string;
  cycle: number;
  direction: string;
  observedAt: string;
  longitude: number;
  latitude: number;
  levelCount: number;
}

function toPoint(record: Record<string, Cell>): ProfilePoint | null {
  const longitude = record.longitude;
  const latitude = record.latitude;
  if (typeof longitude !== "number" || typeof latitude !== "number")
    return null;
  return {
    id: String(record.id),
    platform: String(record.platform_number),
    cycle: Number(record.cycle_number),
    direction: String(record.direction ?? ""),
    observedAt: String(record.observed_at),
    longitude,
    latitude,
    levelCount: Number(record.level_count ?? 0),
  };
}

export function pointsOf(
  pages: CollectionResponse[] | ProfilesPage | undefined,
): ProfilePoint[] {
  if (!pages) return [];
  const list = Array.isArray(pages) ? pages : pages.pages;
  return list.flatMap((page) =>
    tableRecords(page.result)
      .map(toPoint)
      .filter((point): point is ProfilePoint => point !== null),
  );
}

export function toFeatureCollection(
  points: ProfilePoint[],
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((point) => ({
      type: "Feature",
      id: point.id,
      properties: {
        id: point.id,
        platform: point.platform,
        cycle: point.cycle,
        observedAt: point.observedAt,
        month: point.observedAt.slice(0, 7),
      },
      geometry: {
        type: "Point",
        coordinates: [point.longitude, point.latitude],
      },
    })),
  };
}

export interface TrajectoryPoint {
  id: string;
  cycle: number;
  observedAt: string;
  longitude: number;
  latitude: number;
}

/** The trajectory in time order (the API returns newest first). */
export function trajectoryOf(
  float: FloatResponse | undefined,
): TrajectoryPoint[] {
  if (!float) return [];
  return tableRecords(float.trajectory)
    .map((record) => ({
      id: String(record.id),
      cycle: Number(record.cycle_number),
      observedAt: String(record.observed_at),
      longitude: Number(record.longitude),
      latitude: Number(record.latitude),
    }))
    .filter(
      (point) =>
        Number.isFinite(point.longitude) && Number.isFinite(point.latitude),
    )
    .sort((a, b) => a.observedAt.localeCompare(b.observedAt));
}

export function trajectoryFeatures(
  points: TrajectoryPoint[],
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = points.map((point) => ({
    type: "Feature",
    properties: {
      id: point.id,
      cycle: point.cycle,
      observedAt: point.observedAt,
    },
    geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
  }));
  if (points.length > 1) {
    features.push({
      type: "Feature",
      properties: { kind: "track" },
      geometry: {
        type: "LineString",
        coordinates: points.map((point) => [point.longitude, point.latitude]),
      },
    });
  }
  return { type: "FeatureCollection", features };
}

/** The bounding box of points, or null when there are none. */
export function boundsOf(
  points: Array<{ longitude: number; latitude: number }>,
): [[number, number], [number, number]] | null {
  if (points.length === 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const point of points) {
    west = Math.min(west, point.longitude);
    east = Math.max(east, point.longitude);
    south = Math.min(south, point.latitude);
    north = Math.max(north, point.latitude);
  }
  return [
    [west, south],
    [east, north],
  ];
}
