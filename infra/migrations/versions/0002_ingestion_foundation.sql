-- stage1-v2 additive foundation. No deletes, extensions or cloud-specific objects.
CREATE SCHEMA IF NOT EXISTS app;

CREATE DOMAIN app.sha256 AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN app.finite_float8 AS double precision
  CHECK (VALUE > '-Infinity'::float8 AND VALUE < 'Infinity'::float8);
CREATE DOMAIN app.qc_code AS text CHECK (VALUE ~ '^[0-9]$');

CREATE TABLE app.ingestion_environment (
  id uuid PRIMARY KEY,
  name text NOT NULL UNIQUE CHECK (octet_length(name) BETWEEN 1 AND 128),
  mode text NOT NULL CHECK (mode IN ('normal','acceptance')),
  disposable boolean NOT NULL DEFAULT false,
  bucket text NOT NULL UNIQUE,
  queue_namespace text NOT NULL UNIQUE,
  compose_project text NOT NULL UNIQUE,
  CHECK (mode <> 'acceptance' OR disposable)
);
-- Scientific tables are database-local. Each physical database represents exactly
-- one environment; an acceptance marker can never be added alongside normal data.
CREATE UNIQUE INDEX one_environment_per_database ON app.ingestion_environment ((true));

CREATE TABLE app.ingestion_run (
  id uuid PRIMARY KEY,
  environment_id uuid NOT NULL REFERENCES app.ingestion_environment(id) ON DELETE RESTRICT,
  mode text NOT NULL CHECK (mode IN ('normal','acceptance')),
  run_reference_time_utc timestamptz NOT NULL,
  created_at_actual_utc timestamptz NOT NULL DEFAULT clock_timestamp(),
  requested_start timestamptz NOT NULL,
  requested_end timestamptz NOT NULL,
  geometry_version text NOT NULL CHECK (geometry_version = 'indian-ocean-v1'),
  geometry_sha256 app.sha256 NOT NULL,
  policy_versions jsonb NOT NULL,
  limits jsonb NOT NULL,
  state text NOT NULL DEFAULT 'planned' CHECK
    (state IN ('planned','fetching','landed','validating','publishing',
               'complete','partial','quarantined','failed')),
  control_epoch bigint NOT NULL DEFAULT 1 CHECK (control_epoch > 0),
  controller_claims integer NOT NULL DEFAULT 1 CHECK (controller_claims BETWEEN 1 AND 4),
  controller_lease_until timestamptz NOT NULL,
  work_deadline timestamptz NOT NULL,
  deadline timestamptz NOT NULL,
  cancellation_requested_at timestamptz,
  cancellation_affected boolean NOT NULL DEFAULT false,
  closed boolean NOT NULL DEFAULT false,
  termination_reason text,
  http_attempts integer NOT NULL DEFAULT 0 CHECK (http_attempts BETWEEN 0 AND 50000),
  raw_received_bytes bigint NOT NULL DEFAULT 0 CHECK (raw_received_bytes BETWEEN 0 AND 10737418240),
  canonical_bytes bigint NOT NULL DEFAULT 0 CHECK (canonical_bytes BETWEEN 0 AND 10737418240),
  accepted_profiles integer NOT NULL DEFAULT 0 CHECK (accepted_profiles BETWEEN 0 AND 100000),
  accepted_levels bigint NOT NULL DEFAULT 0 CHECK (accepted_levels BETWEEN 0 AND 100000000),
  scheduled boolean NOT NULL DEFAULT false,
  predecessor_id uuid REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  CHECK (requested_start < requested_end),
  CHECK (work_deadline = deadline - interval '60 seconds'),
  CHECK (deadline > created_at_actual_utc + interval '60 seconds'
         AND deadline <= created_at_actual_utc + interval '6 hours'),
  CHECK (mode <> 'acceptance' OR run_reference_time_utc = '2025-04-01T00:00:00Z')
);

CREATE FUNCTION app.check_run_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $body$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT EXISTS (SELECT 1 FROM app.ingestion_environment e
                   WHERE e.id = NEW.environment_id AND e.mode = NEW.mode
                   AND (NEW.mode <> 'acceptance' OR e.disposable)) THEN
      RAISE EXCEPTION 'unsafe_environment';
    END IF;
    IF NEW.requested_start < (((NEW.run_reference_time_utc AT TIME ZONE 'UTC')
                               - interval '12 months') AT TIME ZONE 'UTC')
       OR NEW.requested_end > NEW.run_reference_time_utc THEN
      RAISE EXCEPTION 'outside_rolling_window';
    END IF;
    RETURN NEW;
  END IF;
  IF ROW(NEW.id,NEW.environment_id,NEW.mode,NEW.run_reference_time_utc,
         NEW.created_at_actual_utc,NEW.requested_start,NEW.requested_end,
         NEW.geometry_version,NEW.geometry_sha256,NEW.policy_versions,NEW.limits,
         NEW.work_deadline,NEW.deadline,NEW.scheduled)
     IS DISTINCT FROM ROW(OLD.id,OLD.environment_id,OLD.mode,OLD.run_reference_time_utc,
         OLD.created_at_actual_utc,OLD.requested_start,OLD.requested_end,
         OLD.geometry_version,OLD.geometry_sha256,OLD.policy_versions,OLD.limits,
         OLD.work_deadline,OLD.deadline,OLD.scheduled) THEN
    RAISE EXCEPTION 'immutable_run_policy';
  END IF;
  IF OLD.state IN ('complete','partial','quarantined','failed') AND NEW.state <> OLD.state THEN
    RAISE EXCEPTION 'terminal_run';
  END IF;
  IF NEW.control_epoch < OLD.control_epoch OR NEW.controller_claims < OLD.controller_claims
     OR NEW.http_attempts < OLD.http_attempts OR NEW.raw_received_bytes < OLD.raw_received_bytes
     OR NEW.canonical_bytes < OLD.canonical_bytes OR NEW.accepted_profiles < OLD.accepted_profiles
     OR NEW.accepted_levels < OLD.accepted_levels OR (OLD.closed AND NOT NEW.closed) THEN
    RAISE EXCEPTION 'monotonic_run_control';
  END IF;
  RETURN NEW;
END $body$;
CREATE TRIGGER ingestion_run_immutable BEFORE INSERT OR UPDATE ON app.ingestion_run
FOR EACH ROW EXECUTE FUNCTION app.check_run_immutability();

CREATE TABLE app.ingestion_chunk (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  logical_chunk_key text NOT NULL,
  requested_start timestamptz NOT NULL,
  requested_end timestamptz NOT NULL,
  tile jsonb NOT NULL,
  plan_version text NOT NULL,
  parent_id uuid REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  leaf boolean NOT NULL DEFAULT true,
  state text NOT NULL DEFAULT 'planned' CHECK
    (state IN ('planned','fetching','landed','validating','publishing','complete','quarantined','failed')),
  fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
  control_epoch bigint NOT NULL DEFAULT 1 CHECK (control_epoch > 0),
  processing_claims integer NOT NULL DEFAULT 0 CHECK (processing_claims BETWEEN 0 AND 4),
  publication_attempts integer NOT NULL DEFAULT 0 CHECK (publication_attempts BETWEEN 0 AND 4),
  lease_until timestamptz,
  reason text,
  completed_at timestamptz,
  UNIQUE(run_id,logical_chunk_key), UNIQUE(id,run_id),
  CHECK (requested_start < requested_end),
  CHECK ((state = 'complete') = (completed_at IS NOT NULL))
);

CREATE TABLE app.ingestion_attempt (
  id uuid PRIMARY KEY,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  attempt_number integer NOT NULL CHECK (attempt_number > 0),
  logical_request_key text NOT NULL,
  request_attempt integer NOT NULL CHECK (request_attempt BETWEEN 1 AND 4),
  role text NOT NULL CHECK (role IN ('inventory_before','profile','inventory_after','metadata')),
  started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  finished_at timestamptz,
  disposition text CHECK (disposition IN ('verified_raw','transport_failure','size_limit','interrupted')),
  http_status integer,
  bytes_received bigint NOT NULL DEFAULT 0 CHECK (bytes_received >= 0),
  error_category text,
  request_parameters jsonb NOT NULL,
  UNIQUE(chunk_id,attempt_number), UNIQUE(chunk_id,logical_request_key,request_attempt),
  UNIQUE(id,chunk_id)
);
CREATE TABLE app.raw_manifest (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  chunk_id uuid NOT NULL,
  attempt_id uuid NOT NULL REFERENCES app.ingestion_attempt(id) ON DELETE RESTRICT,
  object_key text NOT NULL CHECK (object_key ~ '^raw/sha256/[0-9a-f]{64}\.json$'),
  sha256 app.sha256 NOT NULL,
  bytes bigint NOT NULL CHECK (bytes BETWEEN 0 AND 134217728),
  retrieved_at timestamptz NOT NULL,
  versions jsonb NOT NULL,
  sanitization jsonb NOT NULL,
  application_commit text NOT NULL,
  FOREIGN KEY(chunk_id,run_id) REFERENCES app.ingestion_chunk(id,run_id) ON DELETE RESTRICT,
  FOREIGN KEY(attempt_id,chunk_id) REFERENCES app.ingestion_attempt(id,chunk_id) ON DELETE RESTRICT,
  CHECK (object_key = 'raw/sha256/' || sha256 || '.json')
);

CREATE TABLE app.argo_float (
  id uuid PRIMARY KEY,
  source text NOT NULL CHECK (source = 'argovis'),
  platform_number text NOT NULL CHECK (octet_length(platform_number) BETWEEN 1 AND 32),
  UNIQUE(source,platform_number), UNIQUE(id,source)
);
CREATE TABLE app.argo_profile (
  id uuid PRIMARY KEY,
  source text NOT NULL CHECK (source = 'argovis'),
  source_profile_id text CHECK (octet_length(source_profile_id) BETWEEN 1 AND 512),
  float_id uuid NOT NULL,
  cycle_number bigint CHECK (cycle_number >= 0),
  direction text NOT NULL CHECK (direction IN ('A','D','U')),
  identity_observed_at timestamptz,
  observation_segment text CHECK (octet_length(observation_segment) BETWEEN 1 AND 128),
  fallback_complete boolean NOT NULL,
  observed_at timestamptz NOT NULL,
  observation_month date NOT NULL,
  position public.geometry(Point,4326) NOT NULL,
  content_hash app.sha256 NOT NULL,
  hash_version text NOT NULL CHECK (hash_version = 'scientific-json-v2'),
  mapping_version text NOT NULL CHECK (mapping_version = 'argovis-core-v1'),
  level_count integer NOT NULL CHECK (level_count BETWEEN 1 AND 10000),
  scientific_content jsonb NOT NULL,
  source_revision jsonb,
  created_run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  last_scientific_run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  last_chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  raw_manifest_id uuid NOT NULL REFERENCES app.raw_manifest(id) ON DELETE RESTRICT,
  FOREIGN KEY(float_id,source) REFERENCES app.argo_float(id,source) ON DELETE RESTRICT,
  UNIQUE(id,observation_month),
  CHECK (observation_month = date_trunc('month',observed_at AT TIME ZONE 'UTC')::date),
  CHECK (NOT public.ST_IsEmpty(position) AND public.ST_X(position) BETWEEN -180 AND 180
         AND public.ST_Y(position) BETWEEN -90 AND 90),
  CHECK (fallback_complete = (cycle_number IS NOT NULL AND direction IN ('A','D')
         AND identity_observed_at IS NOT NULL AND observation_segment IS NOT NULL)),
  CHECK (source_profile_id IS NOT NULL OR fallback_complete),
  CHECK (direction <> 'U' OR source_profile_id IS NOT NULL)
);
CREATE UNIQUE INDEX profile_source_id ON app.argo_profile(source,source_profile_id)
  WHERE source_profile_id IS NOT NULL;
CREATE UNIQUE INDEX profile_natural_key ON app.argo_profile
  (source,float_id,cycle_number,direction,identity_observed_at,observation_segment)
  WHERE fallback_complete;
CREATE INDEX profile_time ON app.argo_profile(observed_at);
CREATE INDEX profile_position ON app.argo_profile USING gist(position);

CREATE TABLE app.core_measurement (
  observation_month date NOT NULL,
  profile_id uuid NOT NULL,
  level_index integer NOT NULL CHECK (level_index >= 0 AND level_index < 10000),
  pressure app.finite_float8, pressure_adjusted app.finite_float8,
  temperature app.finite_float8, temperature_adjusted app.finite_float8,
  salinity app.finite_float8, salinity_adjusted app.finite_float8,
  pressure_error app.finite_float8 CHECK (pressure_error >= 0),
  pressure_original_error app.finite_float8 CHECK (pressure_original_error >= 0),
  temperature_error app.finite_float8 CHECK (temperature_error >= 0),
  temperature_original_error app.finite_float8 CHECK (temperature_original_error >= 0),
  salinity_error app.finite_float8 CHECK (salinity_error >= 0),
  salinity_original_error app.finite_float8 CHECK (salinity_original_error >= 0),
  pressure_qc app.qc_code, pressure_adjusted_qc app.qc_code,
  temperature_qc app.qc_code, temperature_adjusted_qc app.qc_code,
  salinity_qc app.qc_code, salinity_adjusted_qc app.qc_code,
  pressure_unit text CHECK (pressure_unit = 'dbar'),
  temperature_unit text CHECK (temperature_unit = 'degree_C'),
  salinity_unit text CHECK (salinity_unit = '1'),
  pressure_data_mode text CHECK (pressure_data_mode IN ('R','A','D')),
  temperature_data_mode text CHECK (temperature_data_mode IN ('R','A','D')),
  salinity_data_mode text CHECK (salinity_data_mode IN ('R','A','D')),
  pressure_unit_source text, temperature_unit_source text, salinity_unit_source text,
  pressure_qc_source text, pressure_adjusted_qc_source text,
  temperature_qc_source text, temperature_adjusted_qc_source text,
  salinity_qc_source text, salinity_adjusted_qc_source text,
  pressure_flags jsonb NOT NULL, temperature_flags jsonb NOT NULL, salinity_flags jsonb NOT NULL,
  canonical_level jsonb NOT NULL,
  PRIMARY KEY(observation_month,profile_id,level_index),
  FOREIGN KEY(profile_id,observation_month) REFERENCES app.argo_profile(id,observation_month)
    ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
  CHECK (observation_month = date_trunc('month',observation_month)::date),
  CHECK (jsonb_typeof(pressure_flags) = 'array' AND jsonb_typeof(temperature_flags) = 'array'
         AND jsonb_typeof(salinity_flags) = 'array'),
  CHECK ((pressure IS NULL AND pressure_adjusted IS NULL)
         OR (pressure_unit IS NOT NULL AND pressure_data_mode IS NOT NULL)),
  CHECK ((temperature IS NULL AND temperature_adjusted IS NULL)
         OR (temperature_unit IS NOT NULL AND temperature_data_mode IS NOT NULL)),
  CHECK ((salinity IS NULL AND salinity_adjusted IS NULL)
         OR (salinity_unit IS NOT NULL AND salinity_data_mode IS NOT NULL))
) PARTITION BY RANGE(observation_month);
-- Deliberately no default or auto-created partition. Administrator provisions
-- exact monthly children; an absent child is a pre-publication failure.

CREATE TABLE app.logical_partition_slot (
  environment_id uuid NOT NULL REFERENCES app.ingestion_environment(id) ON DELETE RESTRICT,
  logical_key text NOT NULL,
  observation_month date NOT NULL,
  tile_key text NOT NULL,
  slot_version bigint NOT NULL DEFAULT 0 CHECK (slot_version >= 0),
  membership_manifest jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY(environment_id,logical_key)
);
CREATE TABLE app.publication_intent (
  id uuid PRIMARY KEY,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  fence bigint NOT NULL CHECK (fence > 0),
  control_epoch bigint NOT NULL CHECK (control_epoch > 0),
  status text NOT NULL CHECK (status IN ('prepared','committed','abandoned')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  object_references jsonb NOT NULL,
  expected_bases jsonb NOT NULL,
  expected_revisions jsonb NOT NULL,
  disposition_reason text,
  UNIQUE(id,chunk_id)
);
CREATE FUNCTION app.check_intent_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $body$
BEGIN
  IF OLD.status IN ('committed','abandoned') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'terminal_publication_intent';
  END IF;
  IF ROW(NEW.id,NEW.chunk_id,NEW.created_at,NEW.object_references,
         NEW.expected_bases,NEW.expected_revisions)
     IS DISTINCT FROM ROW(OLD.id,OLD.chunk_id,OLD.created_at,OLD.object_references,
         OLD.expected_bases,OLD.expected_revisions)
     OR NEW.fence < OLD.fence OR NEW.control_epoch < OLD.control_epoch THEN
    RAISE EXCEPTION 'immutable_publication_intent';
  END IF;
  RETURN NEW;
END $body$;
CREATE TRIGGER publication_intent_transition BEFORE UPDATE ON app.publication_intent
FOR EACH ROW EXECUTE FUNCTION app.check_intent_transition();
CREATE TABLE app.dataset_partition (
  id uuid PRIMARY KEY,
  environment_id uuid NOT NULL,
  logical_key text NOT NULL,
  generation bigint NOT NULL CHECK (generation > 0),
  slot_version bigint NOT NULL CHECK (slot_version > 0),
  status text NOT NULL CHECK (status IN ('active','superseded','quarantined')),
  intent_id uuid NOT NULL REFERENCES app.publication_intent(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  object_key text NOT NULL,
  sha256 app.sha256 NOT NULL,
  bytes bigint NOT NULL CHECK (bytes > 0),
  row_count bigint NOT NULL CHECK (row_count > 0),
  profile_count integer NOT NULL CHECK (profile_count > 0),
  schema_sha256 app.sha256 NOT NULL,
  geometry_version text NOT NULL CHECK (geometry_version = 'indian-ocean-v1'),
  geometry_sha256 app.sha256 NOT NULL,
  versions jsonb NOT NULL,
  membership_manifest jsonb NOT NULL,
  verified_at timestamptz NOT NULL,
  verification_evidence jsonb NOT NULL,
  committed_at timestamptz NOT NULL,
  FOREIGN KEY(environment_id,logical_key) REFERENCES app.logical_partition_slot
    (environment_id,logical_key) ON DELETE RESTRICT,
  FOREIGN KEY(intent_id,chunk_id) REFERENCES app.publication_intent(id,chunk_id) ON DELETE RESTRICT,
  FOREIGN KEY(chunk_id,run_id) REFERENCES app.ingestion_chunk(id,run_id) ON DELETE RESTRICT,
  UNIQUE(environment_id,logical_key,generation),
  CHECK (object_key = 'normalised/sha256/' || sha256 || '.parquet')
);
CREATE UNIQUE INDEX one_active_generation ON app.dataset_partition(environment_id,logical_key)
  WHERE status = 'active';
CREATE TABLE app.coverage_receipt (
  id uuid PRIMARY KEY,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  intent_id uuid NOT NULL REFERENCES app.publication_intent(id) ON DELETE RESTRICT,
  environment_id uuid NOT NULL,
  logical_key text NOT NULL,
  requested_start timestamptz NOT NULL,
  requested_end timestamptz NOT NULL,
  slot_version bigint NOT NULL CHECK (slot_version >= 0),
  fetch_disposition text NOT NULL CHECK (fetch_disposition IN
    ('profiles_returned','verified_empty_fetch','source_absence_over_retained')),
  stored_disposition text NOT NULL CHECK (stored_disposition IN
    ('active_generation','empty_stored_selection','empty_stored_domain')),
  evidence jsonb NOT NULL,
  committed_at timestamptz NOT NULL,
  FOREIGN KEY(environment_id,logical_key) REFERENCES app.logical_partition_slot
    (environment_id,logical_key) ON DELETE RESTRICT,
  FOREIGN KEY(intent_id,chunk_id) REFERENCES app.publication_intent(id,chunk_id) ON DELETE RESTRICT,
  CHECK (requested_start < requested_end)
);
CREATE TABLE app.ingestion_event (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  chunk_id uuid REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  control_epoch bigint NOT NULL,
  fence bigint,
  old_state text,
  new_state text,
  reason text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE app.profile_outcome (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  occurrence_index integer NOT NULL CHECK (occurrence_index >= 0),
  identity_key text,
  outcome text NOT NULL CHECK (outcome IN ('outside_time','outside_region','outside_core',
    'overlap_duplicate','identical_duplicate','structurally_quarantined','insert','newer',
    'revision_only','noop','unordered_noop','stale_skip','revision_conflict',
    'blocked_by_chunk_quarantine','blocked_uncommitted')),
  source_levels integer CHECK (source_levels >= 0),
  unknown_levels_reason text,
  proposed_content_hash app.sha256,
  committed boolean NOT NULL DEFAULT false,
  evidence jsonb NOT NULL,
  UNIQUE(chunk_id,occurrence_index),
  CHECK (source_levels IS NOT NULL OR unknown_levels_reason IS NOT NULL)
);
CREATE TABLE app.ingestion_scope (
  environment_id uuid NOT NULL REFERENCES app.ingestion_environment(id) ON DELETE RESTRICT,
  source text NOT NULL CHECK (source = 'argovis'),
  region_version text NOT NULL,
  fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
  unfinished_run_id uuid REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  lease_until timestamptz,
  watermark timestamptz,
  backlog jsonb,
  PRIMARY KEY(environment_id,source,region_version)
);
CREATE TABLE app.scheduling_attempt (
  id uuid PRIMARY KEY,
  request_id uuid NOT NULL UNIQUE,
  environment_id uuid NOT NULL REFERENCES app.ingestion_environment(id) ON DELETE RESTRICT,
  mode text NOT NULL CHECK (mode IN ('normal','acceptance')),
  scope jsonb NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  status text NOT NULL CHECK (status = 'overlap_skip'),
  incumbent_run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  cause text NOT NULL
);
CREATE TABLE app.ingestion_staging (
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  chunk_id uuid NOT NULL,
  fence bigint NOT NULL,
  occurrence_index integer NOT NULL CHECK (occurrence_index >= 0),
  candidate jsonb NOT NULL,
  PRIMARY KEY(chunk_id,fence,occurrence_index),
  FOREIGN KEY(chunk_id,run_id) REFERENCES app.ingestion_chunk(id,run_id) ON DELETE RESTRICT
);

-- Read-only selection predicate. Byte/hash availability is checked by the bounded
-- Python selector, never inferred from the catalogue alone or a bucket listing.
CREATE VIEW app.committed_active_partitions AS
SELECT p.* FROM app.dataset_partition p
JOIN app.publication_intent i ON i.id = p.intent_id AND i.status = 'committed'
JOIN app.ingestion_chunk c ON c.id = p.chunk_id AND c.state = 'complete'
JOIN app.logical_partition_slot s ON s.environment_id = p.environment_id
  AND s.logical_key = p.logical_key AND s.slot_version = p.slot_version
WHERE p.status = 'active';

-- Stage 1 objects have explicit grants only. This also defeats the Stage 0
-- app-schema default DML grants when applying on an initialized database.
DO $body$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floatchat_app') THEN
    ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE SELECT,INSERT,UPDATE,DELETE
      ON TABLES FROM floatchat_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE USAGE ON SEQUENCES FROM floatchat_app;
    REVOKE ALL ON app.ingestion_environment, app.ingestion_run, app.ingestion_chunk,
      app.ingestion_attempt, app.raw_manifest, app.argo_float, app.argo_profile,
      app.core_measurement, app.logical_partition_slot, app.publication_intent,
      app.dataset_partition, app.coverage_receipt, app.ingestion_event,
      app.profile_outcome, app.ingestion_scope, app.scheduling_attempt,
      app.ingestion_staging FROM floatchat_app;
    REVOKE ALL ON app.ingestion_event_sequence_seq, app.profile_outcome_sequence_seq
      FROM floatchat_app;
    GRANT SELECT ON app.committed_active_partitions TO floatchat_app;
  END IF;
END $body$;
REVOKE ALL ON FUNCTION app.check_run_immutability() FROM PUBLIC;
REVOKE ALL ON FUNCTION app.check_intent_transition() FROM PUBLIC;
