import { useId } from "react";
import { SlidersHorizontal, RotateCcw } from "lucide-react";
import { Input } from "../components/ui/input";
import { NativeSelect } from "../components/ui/native-select";
import { Button } from "../components/ui/button";
import type { ParametersResponse } from "../api/client";
import {
  QC_POLICIES,
  VARIABLES,
  validateFilters,
  type Filters,
  type QcPolicyName,
  type Variable,
} from "./filters";

type Region = { name: string; kind: string };

function regionsOf(parameters: ParametersResponse | undefined): Region[] {
  const geography = (
    parameters as { geography?: { named_region?: Region[] } } | undefined
  )?.geography;
  return geography?.named_region ?? [];
}

/** Every filter lives in the URL (PRD 14.3); every control is labelled; errors sit beside it. */
export function FilterBar({
  filters,
  update,
  parameters,
  showVariable = false,
}: {
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
  parameters?: ParametersResponse;
  showVariable?: boolean;
}) {
  const errors = validateFilters(filters);
  const id = useId();
  const regions = regionsOf(parameters);
  const names = regions.map((region) => region.name);
  if (!names.includes(filters.region)) names.unshift(filters.region);
  const numberPatch = (key: "depthMin" | "depthMax", value: string) =>
    update({ [key]: value.trim() === "" ? null : Number(value) });
  return (
    <form
      className="filters"
      aria-label="Filters"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="filter-heading">
        <span>
          <SlidersHorizontal size={15} aria-hidden="true" />
          Your selection
        </span>
        <span className="filter-live">
          Filters update the results automatically
        </span>
      </div>
      <div className="primary-filters">
        <label>
          Region
          <NativeSelect
            value={filters.region}
            onChange={(event) =>
              update({
                region: event.target.value,
                profile: null,
                platform: null,
              })
            }
          >
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label>
          Start date <span className="label-hint">UTC · included</span>
          <Input
            aria-label="Start (UTC day, inclusive)"
            type="date"
            value={filters.start ?? ""}
            aria-invalid={Boolean(errors.start)}
            aria-describedby={errors.start ? `${id}-start` : undefined}
            onChange={(event) =>
              update({ start: event.target.value || null, profile: null })
            }
          />
          {errors.start ? (
            <span className="field-error" id={`${id}-start`}>
              {errors.start}
            </span>
          ) : null}
        </label>
        <label>
          End date <span className="label-hint">UTC · excluded</span>
          <Input
            aria-label="End (UTC day, exclusive)"
            type="date"
            value={filters.end ?? ""}
            aria-invalid={Boolean(errors.end)}
            aria-describedby={errors.end ? `${id}-end` : undefined}
            onChange={(event) =>
              update({ end: event.target.value || null, profile: null })
            }
          />
          {errors.end ? (
            <span className="field-error" id={`${id}-end`}>
              {errors.end}
            </span>
          ) : null}
        </label>
        {showVariable ? (
          <label>
            Distribution variable
            <NativeSelect
              aria-label="Variable (distribution)"
              value={filters.variable}
              onChange={(event) =>
                update({ variable: event.target.value as Variable })
              }
            >
              {VARIABLES.map((variable) => (
                <option key={variable} value={variable}>
                  {variable === "temperature"
                    ? "Temperature"
                    : "Practical salinity"}
                </option>
              ))}
            </NativeSelect>
          </label>
        ) : null}
      </div>
      <details
        className="advanced-filters"
        open={
          filters.depthMin !== null ||
          filters.depthMax !== null ||
          filters.qc !== "science_ready" ||
          filters.platform !== null ||
          Boolean(errors.depthMin || errors.depthMax)
        }
      >
        <summary>
          <SlidersHorizontal size={14} aria-hidden="true" />
          Advanced filters<span>Pressure, quality & float</span>
        </summary>
        <div className="advanced-grid">
          <label>
            Pressure from (dbar)
            <Input
              type="number"
              min={0}
              max={12000}
              step="any"
              placeholder="No minimum"
              value={filters.depthMin ?? ""}
              aria-invalid={Boolean(errors.depthMin)}
              onChange={(event) => numberPatch("depthMin", event.target.value)}
            />
            {errors.depthMin ? (
              <span className="field-error">{errors.depthMin}</span>
            ) : null}
          </label>
          <label>
            Pressure to (dbar)
            <Input
              type="number"
              min={0}
              max={12000}
              step="any"
              placeholder="No maximum"
              value={filters.depthMax ?? ""}
              aria-invalid={Boolean(errors.depthMax)}
              onChange={(event) => numberPatch("depthMax", event.target.value)}
            />
            {errors.depthMax ? (
              <span className="field-error">{errors.depthMax}</span>
            ) : null}
          </label>
          <label>
            Quality control
            <NativeSelect
              aria-label="QC policy (qc-policy-v1)"
              value={filters.qc}
              onChange={(event) =>
                update({ qc: event.target.value as QcPolicyName })
              }
            >
              {QC_POLICIES.map((policy) => (
                <option key={policy} value={policy}>
                  {policy === "science_ready"
                    ? "Science ready"
                    : policy === "mode_selected"
                      ? "Mode selected"
                      : "Raw measurements"}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label>
            Float trajectory
            <Input
              aria-label="Float (platform number)"
              type="text"
              inputMode="numeric"
              value={filters.platform ?? ""}
              placeholder="Enter platform number"
              onChange={(event) =>
                update({ platform: event.target.value.trim() || null })
              }
            />
          </label>
        </div>
        <p className="note">
          Pressure is measured in decibars (dbar), approximately one metre of
          depth per dbar. Raw quality applies to individual profile reads;
          aggregates use science ready instead. A float ID adds its trajectory
          to the map; regional charts still include all floats.
        </p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() =>
            update({
              depthMin: null,
              depthMax: null,
              qc: "science_ready",
              platform: null,
              profile: null,
            })
          }
        >
          <RotateCcw aria-hidden="true" />
          Clear advanced filters
        </Button>
      </details>
    </form>
  );
}
