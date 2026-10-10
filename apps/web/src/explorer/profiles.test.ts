import { describe, expect, it } from "vitest";
import type { CollectionResponse, FloatResponse } from "../api/types";
import {
  boundsOf,
  pointsOf,
  toFeatureCollection,
  trajectoryFeatures,
  trajectoryOf,
} from "./profiles";
import profiles from "../test/fixtures/profiles.json";
import float from "../test/fixtures/float.json";

const page = profiles as unknown as CollectionResponse;
const detail = float as unknown as FloatResponse;

describe("profile points", () => {
  it("turns profile headers into points and GeoJSON features", () => {
    const points = pointsOf([page]);
    expect(points.length).toBe(page.result.row_count);
    const collection = toFeatureCollection(points);
    expect(collection.features[0].id).toBe(points[0].id);
    expect(collection.features[0].properties).toMatchObject({
      platform: points[0].platform,
      month: points[0].observedAt.slice(0, 7),
    });
    expect(pointsOf({ pages: [page, page], truncated: true }).length).toBe(
      2 * page.result.row_count,
    );
    expect(pointsOf(undefined)).toEqual([]);
  });

  it("orders a trajectory in time and draws a track when it has more than one position", () => {
    const track = trajectoryOf(detail);
    expect(track.length).toBe(detail.trajectory.row_count);
    for (let index = 1; index < track.length; index += 1)
      expect(track[index].observedAt >= track[index - 1].observedAt).toBe(true);
    const features = trajectoryFeatures(track);
    expect(
      features.features.filter(
        (feature) => feature.geometry.type === "LineString",
      ).length,
    ).toBe(track.length > 1 ? 1 : 0);
    expect(trajectoryOf(undefined)).toEqual([]);
  });

  it("computes bounds", () => {
    expect(boundsOf([])).toBeNull();
    expect(
      boundsOf([
        { longitude: 60, latitude: 10 },
        { longitude: 70, latitude: 5 },
      ]),
    ).toEqual([
      [60, 5],
      [70, 10],
    ]);
  });
});
