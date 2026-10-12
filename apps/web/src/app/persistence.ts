// Browser persistence of finished answers (ADR-0068). TanStack Query's memory cache is written
// to IndexedDB so a refresh or a new tab reuses answers instead of recomputing them. Only small,
// version-guarded keys are kept: the parameter catalogue, coverage summaries and plan results.
// The 1.3 MB profile lists and the environment itself are always fetched fresh.
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import type { Query, QueryClient } from "@tanstack/react-query";
import type { CoverageResponse } from "../api/types";

export const PERSIST_MAX_AGE_MS = 24 * 60 * 60 * 1000;
/** Bump when the shape of a persisted answer changes, so old stores are discarded. */
export const PERSIST_BUSTER = "floatchat-web-1";
const DATABASE = "floatchat";
const STORE = "query-cache";
const DATASET_KEY = "floatchat.dataset-version";

/** True for the keys whose answers may outlive the page (never the environment). */
export function isPersistable(queryKey: readonly unknown[]): boolean {
  const [head, second] = queryKey;
  if (head === "parameters" || head === "query") return true;
  return head === "coverage" && second !== "environment";
}

export function shouldPersistQuery(query: Query): boolean {
  return query.state.status === "success" && isPersistable(query.queryKey);
}

function request<T>(
  build: (store: IDBObjectStore) => IDBRequest<T>,
  mode: IDBTransactionMode,
) {
  return new Promise<T>((resolve, reject) => {
    const opening = indexedDB.open(DATABASE, 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore(STORE);
    opening.onerror = () => reject(opening.error);
    opening.onsuccess = () => {
      const database = opening.result;
      const transaction = database.transaction(STORE, mode);
      const pending = build(transaction.objectStore(STORE));
      pending.onsuccess = () => resolve(pending.result);
      pending.onerror = () => reject(pending.error);
      transaction.oncomplete = () => database.close();
      transaction.onabort = () => database.close();
    };
  });
}

/** A minimal async key-value store over IndexedDB (no extra library). */
export const indexedDbStorage = {
  getItem: async (key: string): Promise<string | null> =>
    ((await request((store) => store.get(key), "readonly")) as
      | string
      | undefined) ?? null,
  setItem: async (key: string, value: string): Promise<void> => {
    await request((store) => store.put(value, key), "readwrite");
  },
  removeItem: async (key: string): Promise<void> => {
    await request((store) => store.delete(key), "readwrite");
  },
};

export function persistenceAvailable(): boolean {
  try {
    return typeof indexedDB !== "undefined" && indexedDB !== null;
  } catch {
    return false;
  }
}

export function createPersister() {
  return createAsyncStoragePersister({
    storage: indexedDbStorage,
    key: "floatchat-query-cache",
    throttleTime: 1000,
  });
}

/** The dataset an answer was computed from; a new ingestion run changes it. */
export function datasetVersion(
  coverage: CoverageResponse | undefined,
): string | null {
  const environment = coverage?.environment;
  if (!environment) return null;
  return [
    environment.id,
    environment.latest_run ?? "none",
    environment.completed_runs,
  ].join(":");
}

/**
 * Drop persisted answers that belong to another dataset version. Returns true when it did.
 * The marker sits in localStorage (tiny, synchronous); a blocked store only disables the guard's
 * memory, never the page.
 */
export function guardDatasetVersion(
  client: QueryClient,
  version: string | null,
): boolean {
  if (version === null) return false;
  let previous: string | null = null;
  try {
    previous = window.localStorage.getItem(DATASET_KEY);
    window.localStorage.setItem(DATASET_KEY, version);
  } catch {
    return false;
  }
  if (previous === null || previous === version) return false;
  client.removeQueries({ predicate: (query) => isPersistable(query.queryKey) });
  return true;
}
