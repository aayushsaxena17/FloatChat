import { useId } from "react";
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
      <label>
        Region
        <select
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
        </select>
      </label>
      <label>
        Start (UTC day, inclusive)
        <input
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
        End (UTC day, exclusive)
        <input
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
      <label>
        Pressure from (dbar)
        <input
          type="number"
          min={0}
          max={12000}
          step="any"
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
        <input
          type="number"
          min={0}
          max={12000}
          step="any"
          value={filters.depthMax ?? ""}
          aria-invalid={Boolean(errors.depthMax)}
          onChange={(event) => numberPatch("depthMax", event.target.value)}
        />
        {errors.depthMax ? (
          <span className="field-error">{errors.depthMax}</span>
        ) : null}
      </label>
      <label>
        QC policy (qc-policy-v1)
        <select
          value={filters.qc}
          onChange={(event) =>
            update({ qc: event.target.value as QcPolicyName })
          }
        >
          {QC_POLICIES.map((policy) => (
            <option key={policy} value={policy}>
              {policy}
            </option>
          ))}
        </select>
      </label>
      <label>
        Float (platform number)
        <input
          type="text"
          inputMode="numeric"
          value={filters.platform ?? ""}
          placeholder="any"
          onChange={(event) =>
            update({ platform: event.target.value.trim() || null })
          }
        />
      </label>
      {showVariable ? (
        <label>
          Variable (distribution)
          <select
            value={filters.variable}
            onChange={(event) =>
              update({ variable: event.target.value as Variable })
            }
          >
            {VARIABLES.map((variable) => (
              <option key={variable} value={variable}>
                {variable}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <p className="note">
        Times are UTC; longitudes are degrees east in −180…180; the depth filter
        is sea pressure in dbar. QC policy raw applies to profile reads only;
        aggregates use science_ready in its place.
      </p>
    </form>
  );
}
