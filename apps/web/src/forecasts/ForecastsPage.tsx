import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { TrendingUp } from "lucide-react";
import { describeError, useParameters } from "../api/hooks";
import { formatUtc } from "../catalog/units";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import {
  NativeSelect,
  NativeSelectOption,
} from "../components/ui/native-select";
import { StatusMessage } from "../components/StatusMessage";
import type { ForecastRunRecord } from "./client";
import { statusKind, statusLabel } from "./format";
import { useCreateForecast, useForecasts } from "./useForecasts";

const FALLBACK_REGIONS = [
  "Arabian Sea",
  "Bay of Bengal",
  "Laccadive Sea",
  "Andaman Sea",
];

function regionNames(parameters: unknown): string[] {
  const regions =
    (
      parameters as
        | { geography?: { named_region?: Array<{ name: string }> } }
        | undefined
    )?.geography?.named_region ?? [];
  const names = regions.map((region) => region.name);
  return names.length ? names : FALLBACK_REGIONS;
}

export function runTitle(
  run: Pick<ForecastRunRecord, "history" | "horizon">,
): string {
  return `${run.horizon}-month forecast`;
}

/** PRD 2.4: the forecast workspace. A request is a job; the runs are listed here. */
export function ForecastsPage() {
  const parameters = useParameters();
  const runs = useForecasts();
  const create = useCreateForecast();
  const navigate = useNavigate();
  const [variable, setVariable] = useState<"temperature" | "salinity">(
    "temperature",
  );
  const [region, setRegion] = useState("Arabian Sea");
  const [depthMax, setDepthMax] = useState("100");
  const [horizon, setHorizon] = useState("3");
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    create.mutate(
      {
        variable,
        geography: { kind: "named_region", value: region },
        depth_dbar: { min: 0, max: Number(depthMax) || 100 },
        horizon: Math.min(12, Math.max(1, Number(horizon) || 3)),
        min_profiles: 5,
      },
      {
        onSuccess: (created) => {
          void navigate(`/jobs/${created.job.id}`);
        },
      },
    );
  };
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Forecasts</h1>
          <p className="page-description">
            Statistical forecasts of a monthly, profile-balanced regional mean,
            backtested against a seasonal-naive baseline before anything is
            shown. Not an ocean model.
          </p>
        </div>
      </div>
      <form
        className="forecast-form panel"
        onSubmit={submit}
        aria-label="New forecast"
      >
        <h2>
          <TrendingUp size={18} aria-hidden="true" />
          New forecast
        </h2>
        <div className="forecast-fields">
          <label>
            Variable
            <NativeSelect
              value={variable}
              onChange={(event) =>
                setVariable(
                  event.target.value === "salinity"
                    ? "salinity"
                    : "temperature",
                )
              }
            >
              <NativeSelectOption value="temperature">
                Temperature
              </NativeSelectOption>
              <NativeSelectOption value="salinity">Salinity</NativeSelectOption>
            </NativeSelect>
          </label>
          <label>
            Region
            <NativeSelect
              value={region}
              onChange={(event) => setRegion(event.target.value)}
            >
              {regionNames(parameters.data).map((name) => (
                <NativeSelectOption key={name} value={name}>
                  {name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </label>
          <label>
            Depth band, 0 to (dbar)
            <Input
              type="number"
              min={1}
              max={12000}
              value={depthMax}
              onChange={(event) => setDepthMax(event.target.value)}
            />
          </label>
          <label>
            Horizon (months)
            <Input
              type="number"
              min={1}
              max={12}
              value={horizon}
              onChange={(event) => setHorizon(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={create.isPending}>
            Run forecast
          </Button>
        </div>
        <p className="chart-caption">
          Monthly means over the last ten years of committed data, science-ready
          QC, at least five profiles per month. The run refuses when the history
          is too short, too sparse or constant, and labels the result
          experimental when no model beats the baseline.
        </p>
        {create.error ? (
          <p className="status" data-kind="error" role="alert">
            {describeError(create.error).message}
          </p>
        ) : null}
      </form>
      <StatusMessage
        loading={runs.isPending}
        error={runs.error}
        empty={
          runs.data && runs.data.length === 0 ? "No forecasts yet." : false
        }
      >
        <ul className="job-list" aria-label="Forecast runs">
          {(runs.data ?? []).map((run) => (
            <li key={run.id} className="job-row">
              <div className="job-row-main">
                <Link to={`/forecasts/${run.id}`} className="job-title">
                  {runTitle(run)}
                  {run.history && "months" in run.history
                    ? ` · ${(run.history as { months?: string[] }).months?.length ?? 0} months of history`
                    : ""}
                </Link>
                <p className="job-meta">
                  Created {formatUtc(run.created_at)}
                  {run.reason ? ` · ${run.reason}` : ""}
                </p>
              </div>
              <Badge
                variant="outline"
                className="badge"
                data-kind={statusKind(run.status)}
              >
                {statusLabel(run.status)}
              </Badge>
            </li>
          ))}
        </ul>
      </StatusMessage>
    </>
  );
}
