import { useMemo } from "react";
import {
  useEnvironment,
  useFloat,
  useParameters,
  useProfile,
  useProfilesAll,
} from "../api/hooks";
import { useFilters } from "./useFilters";
import { pointsOf, trajectoryOf } from "./profiles";

/** The filters, the environment they default from, and the data the explorer views share. */
export function useExplorerData() {
  const environment = useEnvironment();
  const { filters, update } = useFilters(environment.data?.environment);
  const parameters = useParameters();
  const profiles = useProfilesAll(filters);
  const float = useFloat(filters);
  const profile = useProfile(filters);
  const points = useMemo(() => pointsOf(profiles.data), [profiles.data]);
  const trajectory = useMemo(() => trajectoryOf(float.data), [float.data]);
  const regionBox = useMemo(() => {
    const regions =
      (
        parameters.data as
          | {
              geography?: {
                named_region?: Array<{
                  name: string;
                  bbox?: {
                    west: number;
                    south: number;
                    east: number;
                    north: number;
                  };
                }>;
              };
            }
          | undefined
      )?.geography?.named_region ?? [];
    return (
      regions.find((region) => region.name === filters.region)?.bbox ?? null
    );
  }, [parameters.data, filters.region]);
  const select = (point: { id: string; platform: string }) =>
    update({ profile: point.id, platform: point.platform });
  return {
    environment,
    filters,
    update,
    parameters,
    profiles,
    float,
    profile,
    points,
    trajectory,
    regionBox,
    select,
  };
}
