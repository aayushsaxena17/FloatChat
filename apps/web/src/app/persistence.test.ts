import "fake-indexeddb/auto";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import type { CoverageResponse } from "../api/types";
import {
  datasetVersion,
  guardDatasetVersion,
  indexedDbStorage,
  isPersistable,
} from "./persistence";

afterEach(() => window.localStorage.clear());

describe("what persists", () => {
  it("keeps catalogue, coverage and plan answers, never the environment or profile lists", () => {
    expect(isPersistable(["parameters"])).toBe(true);
    expect(isPersistable(["query", { dataset: "core" }])).toBe(true);
    expect(
      isPersistable([
        "coverage",
        "Arabian Sea",
        "2025-01-01T00:00:00Z",
        "2025-02-01T00:00:00Z",
      ]),
    ).toBe(true);
    expect(isPersistable(["coverage", "environment"])).toBe(false);
    expect(isPersistable(["profiles", {}, 5])).toBe(false);
    expect(isPersistable(["profile", "id"])).toBe(false);
    expect(isPersistable(["float", "5900001"])).toBe(false);
  });
});

describe("IndexedDB storage", () => {
  it("stores, reads and removes a value", async () => {
    expect(await indexedDbStorage.getItem("k")).toBeNull();
    await indexedDbStorage.setItem("k", "value");
    expect(await indexedDbStorage.getItem("k")).toBe("value");
    await indexedDbStorage.setItem("k", "newer");
    expect(await indexedDbStorage.getItem("k")).toBe("newer");
    await indexedDbStorage.removeItem("k");
    expect(await indexedDbStorage.getItem("k")).toBeNull();
  });
});

describe("dataset guard", () => {
  const coverage = (run: string, completed: number) =>
    ({
      environment: { id: "env", latest_run: run, completed_runs: completed },
    }) as unknown as CoverageResponse;

  it("derives the version from the environment", () => {
    expect(datasetVersion(coverage("r1", 2))).toBe("env:r1:2");
    expect(datasetVersion(undefined)).toBeNull();
  });

  it("drops persisted answers only when the dataset version changes", () => {
    const client = new QueryClient();
    const seed = () => {
      client.setQueryData(["query", { plan: 1 }], { ok: 1 });
      client.setQueryData(["coverage", "Arabian Sea", "a", "b"], { ok: 2 });
      client.setQueryData(["profiles", {}, 5], { ok: 3 });
    };
    seed();
    expect(guardDatasetVersion(client, "env:r1:2")).toBe(false); // first sight: nothing to compare
    expect(guardDatasetVersion(client, "env:r1:2")).toBe(false);
    expect(client.getQueryData(["query", { plan: 1 }])).toEqual({ ok: 1 });
    expect(guardDatasetVersion(client, "env:r2:3")).toBe(true);
    expect(client.getQueryData(["query", { plan: 1 }])).toBeUndefined();
    expect(
      client.getQueryData(["coverage", "Arabian Sea", "a", "b"]),
    ).toBeUndefined();
    expect(client.getQueryData(["profiles", {}, 5])).toEqual({ ok: 3 }); // not persisted, kept
    expect(guardDatasetVersion(client, null)).toBe(false);
  });
});
