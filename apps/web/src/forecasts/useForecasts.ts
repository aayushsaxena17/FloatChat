import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { retryPolicy } from "../api/hooks";
import {
  createForecast,
  getForecast,
  listForecasts,
  type ForecastRequestBody,
  type ForecastRunRecord,
} from "./client";

export function useForecasts() {
  return useQuery<ForecastRunRecord[], Error>({
    queryKey: ["forecasts"],
    queryFn: ({ signal }) => listForecasts(signal),
    staleTime: 10_000,
    refetchInterval: (query) =>
      query.state.data?.some((run) => run.status === "pending")
        ? 15_000
        : false,
    retry: retryPolicy,
  });
}

export function useForecast(id: string | undefined) {
  return useQuery({
    queryKey: ["forecasts", id],
    queryFn: ({ signal }) => getForecast(id as string, signal),
    enabled: Boolean(id),
    staleTime: 5_000,
    refetchInterval: (query) =>
      query.state.data?.run.status === "pending" ? 10_000 : false,
    retry: retryPolicy,
  });
}

export function useCreateForecast() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ForecastRequestBody) => createForecast(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["forecasts"], exact: true });
      void client.invalidateQueries({ queryKey: ["jobs"], exact: true });
    },
  });
}
