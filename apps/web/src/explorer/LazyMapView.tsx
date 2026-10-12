import { lazy, Suspense } from "react";
import type { MapViewProps } from "./MapView";

// MapLibre (about 290 kB gzipped plus its worker) loads when a map is first shown (ADR-0068).
const MapView = lazy(() =>
  import("./MapView").then((module) => ({ default: module.MapView })),
);

export function LazyMapView(props: MapViewProps) {
  return (
    <Suspense
      fallback={
        <div className={`map-frame${props.compact ? " compact" : ""}`}>
          <p className="map-overlay" role="status">
            Loading the map…
          </p>
        </div>
      }
    >
      <MapView {...props} />
    </Suspense>
  );
}
