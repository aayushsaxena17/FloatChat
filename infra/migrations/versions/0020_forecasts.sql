-- Stage 6 (ADR-0082): the forecast definition, the trained model versions and the runs
-- (PRD section 6.9). Additive; the application login writes all three tables.

CREATE TABLE app.forecast_definition (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id text NOT NULL CHECK (client_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
  definition_sha256 text NOT NULL CHECK (definition_sha256 ~ '^[0-9a-f]{64}$'),
  request jsonb NOT NULL,
  variable text NOT NULL CHECK (variable IN ('temperature','salinity')),
  region text NOT NULL CHECK (length(region) BETWEEN 1 AND 128),
  depth_min double precision NOT NULL CHECK (depth_min >= 0),
  depth_max double precision NOT NULL CHECK (depth_max > depth_min),
  frequency text NOT NULL DEFAULT 'monthly' CHECK (frequency IN ('monthly')),
  aggregation text NOT NULL DEFAULT 'profile_balanced_mean'
    CHECK (aggregation IN ('profile_balanced_mean')),
  qc_policy text NOT NULL DEFAULT 'science_ready' CHECK (qc_policy IN ('science_ready')),
  min_profiles integer NOT NULL CHECK (min_profiles BETWEEN 1 AND 100),
  series_start timestamptz NOT NULL,
  series_end timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (series_start < series_end),
  UNIQUE (client_id, definition_sha256)
);

CREATE TABLE app.forecast_model (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  definition_id uuid NOT NULL REFERENCES app.forecast_definition(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version >= 1),
  family text NOT NULL CHECK (family IN ('seasonal_naive','sarima')),
  model_order jsonb NOT NULL DEFAULT '{}'::jsonb,
  training_snapshot jsonb NOT NULL,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL CHECK (status IN ('selected','baseline','rejected')),
  artefact_key text CHECK (artefact_key ~ '^forecasts/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,128}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (definition_id, version)
);

CREATE TABLE app.forecast_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  definition_id uuid NOT NULL REFERENCES app.forecast_definition(id) ON DELETE CASCADE,
  model_id uuid REFERENCES app.forecast_model(id) ON DELETE SET NULL,
  job_id uuid REFERENCES app.analysis_job(id) ON DELETE SET NULL,
  client_id text NOT NULL CHECK (client_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
  horizon integer NOT NULL CHECK (horizon BETWEEN 1 AND 12),
  status text NOT NULL CHECK (status IN ('pending','published','experimental','refused')),
  reason text,
  history jsonb NOT NULL DEFAULT '{}'::jsonb,
  forecast jsonb NOT NULL DEFAULT '{}'::jsonb,
  backtest jsonb NOT NULL DEFAULT '{}'::jsonb,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  limitations text NOT NULL DEFAULT '',
  seed integer NOT NULL DEFAULT 20261016,
  versions jsonb NOT NULL DEFAULT '{}'::jsonb,
  generated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX forecast_run_client ON app.forecast_run(client_id, created_at DESC);
CREATE INDEX forecast_run_definition ON app.forecast_run(definition_id, created_at DESC);

REVOKE ALL ON app.forecast_definition, app.forecast_model, app.forecast_run FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floatchat_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.forecast_definition, app.forecast_model,
      app.forecast_run TO floatchat_app;
  END IF;
END $$;
