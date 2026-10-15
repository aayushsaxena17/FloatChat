-- Stage 5 (ADR-0078, ADR-0079): the historical ingestion run mode and the job, chunk, event
-- and artefact tables. Additive for every existing object except the run mode constraints,
-- the run trigger, admit_run, persist_plan and the query_environment view, which learn the
-- new mode. A historical run's reference time is its requested end and its span is at most
-- twelve months, so every Stage 1 eligibility rule holds for it unchanged.

-- 1. Run mode constraints.
ALTER TABLE app.ingestion_run DROP CONSTRAINT ingestion_run_mode_check;
ALTER TABLE app.ingestion_run ADD CONSTRAINT ingestion_run_mode_check
  CHECK (mode IN ('normal','acceptance','historical'));
ALTER TABLE app.ingestion_run ADD CONSTRAINT ingestion_run_historical_check
  CHECK (mode <> 'historical' OR (run_reference_time_utc = requested_end AND NOT scheduled));
ALTER TABLE app.scheduling_attempt DROP CONSTRAINT scheduling_attempt_mode_check;
ALTER TABLE app.scheduling_attempt ADD CONSTRAINT scheduling_attempt_mode_check
  CHECK (mode IN ('normal','acceptance','historical'));

-- 2. The run trigger: a historical run is admitted in a normal environment or a disposable
-- acceptance environment; its end is never in the future. The rolling-window check keeps
-- its text: with T = requested_end it is exactly the twelve-month span bound.
CREATE OR REPLACE FUNCTION app.check_run_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, app AS $body$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT EXISTS (SELECT 1 FROM app.ingestion_environment e
                   WHERE e.id = NEW.environment_id
                   AND (e.mode = NEW.mode OR NEW.mode = 'historical')
                   AND (NEW.mode <> 'acceptance' OR e.disposable)
                   AND (NEW.mode <> 'historical' OR e.mode = 'normal' OR e.disposable)) THEN
      RAISE EXCEPTION 'unsafe_environment';
    END IF;
    IF NEW.requested_start < (((NEW.run_reference_time_utc AT TIME ZONE 'UTC')
                               - interval '12 months') AT TIME ZONE 'UTC')
       OR NEW.requested_end > NEW.run_reference_time_utc THEN
      RAISE EXCEPTION 'outside_rolling_window';
    END IF;
    IF NEW.mode = 'historical' AND NEW.requested_end > NEW.created_at_actual_utc THEN
      RAISE EXCEPTION 'historical_end_in_future';
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

-- 3. Admission (body of migration 0015 plus the historical mode).
CREATE OR REPLACE FUNCTION app.admit_run(p_environment uuid,p_request uuid,p_mode text,p_scheduled boolean,
  p_start timestamptz,p_end timestamptz,p_seconds integer,p_geometry_hash text,p_versions jsonb,p_limits jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE e app.ingestion_environment; s app.ingestion_scope; r app.ingestion_run;
        reference timestamptz; actual timestamptz; first timestamptz; last timestamptz;
        run_uuid uuid; admission_uuid uuid; src text;
BEGIN
  src := app.run_source(p_versions);
  SELECT * INTO STRICT e FROM app.ingestion_environment WHERE id=p_environment;
  IF (e.mode<>p_mode AND NOT (p_mode='historical' AND (e.mode='normal' OR e.disposable)))
     OR (p_mode='acceptance' AND NOT e.disposable)
     OR (p_scheduled AND p_mode<>'normal') OR p_seconds NOT BETWEEN 61 AND 43200
     OR p_geometry_hash<>encode(sha256(convert_to('POLYGON((20 -60,120 -60,120 30,20 30,20 -60))','UTF8')),'hex')
     THEN RAISE EXCEPTION 'unsafe_run_configuration'; END IF;
  actual := clock_timestamp();
  IF p_mode='historical' AND (p_start IS NULL OR p_end IS NULL OR p_end>actual
     OR p_start < (((p_end AT TIME ZONE 'UTC')-interval '12 months') AT TIME ZONE 'UTC'))
     THEN RAISE EXCEPTION 'invalid_historical_interval'; END IF;
  INSERT INTO app.ingestion_scope(environment_id,source,region_version)
    VALUES(p_environment,src,'indian-ocean-v1') ON CONFLICT DO NOTHING;
  SELECT * INTO STRICT s FROM app.ingestion_scope WHERE environment_id=p_environment
    AND source=src AND region_version='indian-ocean-v1' FOR UPDATE;
  SELECT * INTO r FROM app.ingestion_run WHERE request_id=p_request;
  IF r.id IS NOT NULL THEN RETURN jsonb_build_object('kind','existing','run_id',r.id); END IF;
  SELECT id INTO admission_uuid FROM app.scheduling_attempt WHERE request_id=p_request;
  IF admission_uuid IS NOT NULL THEN
    RETURN jsonb_build_object('kind','overlap_skip','event_id',admission_uuid);
  END IF;
  IF s.unfinished_run_id IS NOT NULL THEN
    SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=s.unfinished_run_id;
    IF NOT r.closed AND r.controller_lease_until<=clock_timestamp() THEN
      INSERT INTO app.ingestion_event(run_id,control_epoch,reason,evidence)
        VALUES(r.id,r.control_epoch,'recovery_admission',jsonb_build_object('request_id',p_request));
      RETURN jsonb_build_object('kind','recover','run_id',r.id);
    END IF;
    admission_uuid := gen_random_uuid();
    INSERT INTO app.scheduling_attempt(id,request_id,environment_id,mode,scope,status,
      incumbent_run_id,cause) VALUES(admission_uuid,p_request,p_environment,p_mode,
      jsonb_build_object('source',src,'region_version','indian-ocean-v1'),
      'overlap_skip',r.id,'unfinished_run');
    RETURN jsonb_build_object('kind','overlap_skip','event_id',admission_uuid);
  END IF;
  actual := clock_timestamp();
  reference := CASE WHEN p_mode='acceptance' THEN '2025-04-01T00:00:00Z'::timestamptz
                    WHEN p_mode='historical' THEN p_end ELSE actual END;
  IF p_scheduled THEN
    first := greatest(((reference AT TIME ZONE 'UTC')-interval '12 months') AT TIME ZONE 'UTC',
                      coalesce(s.watermark,reference)-interval '14 days');
    last := least(reference,first+interval '31 days');
  ELSE first := p_start; last := p_end; END IF;
  IF first IS NULL OR last IS NULL OR first>=last THEN RAISE EXCEPTION 'invalid_run_interval'; END IF;
  run_uuid := gen_random_uuid();
  INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,created_at_actual_utc,
    requested_start,requested_end,geometry_version,geometry_sha256,policy_versions,limits,
    controller_lease_until,work_deadline,deadline,scheduled,request_id)
  VALUES(run_uuid,p_environment,p_mode,reference,actual,first,last,'indian-ocean-v1',p_geometry_hash,
    p_versions,p_limits,actual+interval '10 minutes',
    actual+(p_seconds-60)*interval '1 second',actual+p_seconds*interval '1 second',p_scheduled,p_request);
  UPDATE app.ingestion_scope SET fence=fence+1,unfinished_run_id=run_uuid,
    lease_until=actual+interval '10 minutes',
    backlog=CASE WHEN p_scheduled AND last<reference THEN jsonb_build_object('start',last,'end',reference)
                 ELSE NULL END
    WHERE environment_id=p_environment AND source=src AND region_version='indian-ocean-v1';
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason)
    VALUES(run_uuid,1,'run_admitted_reference_captured');
  RETURN jsonb_build_object('kind','created','run_id',run_uuid);
END $body$;

-- 4. The plan of a historical run covers only the tiles its input descriptor names
-- (body of migration 0009 with the expected tile set made mode-dependent).
CREATE OR REPLACE FUNCTION app.persist_plan(p_run uuid,p_epoch bigint,p_plan jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; item jsonb; n integer; named jsonb;
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) THEN RETURN; END IF;
  n := jsonb_array_length(p_plan);
  IF n NOT BETWEEN 1 AND 16384 THEN RAISE EXCEPTION 'chunk_count_limit'; END IF;
  IF r.mode='historical' THEN
    SELECT descriptor->'tiles' INTO named FROM app.ingestion_input WHERE run_id=p_run;
    IF named IS NULL OR jsonb_typeof(named)<>'array' OR jsonb_array_length(named)=0
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(named) t
                  WHERE jsonb_typeof(t)<>'array' OR jsonb_array_length(t)<>2
                     OR (t->>0)::integer NOT BETWEEN 20 AND 110 OR (t->>0)::integer % 10 <> 0
                     OR (t->>1)::integer NOT BETWEEN -60 AND 20 OR (t->>1)::integer % 10 <> 0)
       THEN RAISE EXCEPTION 'invalid_historical_tiles'; END IF;
  END IF;
  IF EXISTS (
    WITH RECURSIVE slices(first,last) AS (
      SELECT r.requested_start,least(r.requested_end,
        ((date_trunc('month',r.requested_start AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      UNION ALL
      SELECT last,least(r.requested_end,
        ((date_trunc('month',last AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
        FROM slices WHERE last<r.requested_end
    ), tiles(west,south) AS (
      SELECT DISTINCT (t->>0)::integer,(t->>1)::integer FROM jsonb_array_elements(named) t
        WHERE r.mode='historical'
      UNION ALL
      SELECT w.west,s.south FROM generate_series(20,110,10) w(west)
        CROSS JOIN generate_series(-60,20,10) s(south) WHERE r.mode<>'historical'
    ), expected AS (
      SELECT first,last,west,south,10 AS width,10 AS height FROM slices CROSS JOIN tiles
    ), supplied AS (
      SELECT (value->>'start')::timestamptz AS first,(value->>'end')::timestamptz AS last,
        (value->'tile'->>'west')::integer AS west,(value->'tile'->>'south')::integer AS south,
        (value->'tile'->>'width')::integer AS width,(value->'tile'->>'height')::integer AS height
      FROM jsonb_array_elements(p_plan)
    )
    SELECT 1 FROM (
      (SELECT * FROM expected EXCEPT ALL SELECT * FROM supplied)
      UNION ALL (SELECT * FROM supplied EXCEPT ALL SELECT * FROM expected)
    ) differences
  ) THEN RAISE EXCEPTION 'incomplete_initial_plan'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(p_plan) LOOP
    IF (item->>'start')::timestamptz<r.requested_start
       OR (item->>'end')::timestamptz>r.requested_end
       OR date_trunc('month',(item->>'start')::timestamptz AT TIME ZONE 'UTC')
          <> date_trunc('month',((item->>'end')::timestamptz-interval '1 microsecond') AT TIME ZONE 'UTC')
       THEN RAISE EXCEPTION 'invalid_plan_chunk'; END IF;
    INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,tile,plan_version)
      VALUES((item->>'id')::uuid,p_run,item->>'key',(item->>'start')::timestamptz,
        (item->>'end')::timestamptz,item->'tile','indian-ocean-plan-v2');
  END LOOP;
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason,evidence)
    VALUES(p_run,p_epoch,'complete_plan_persisted',
      jsonb_build_object('chunks',n,'plan_version','indian-ocean-plan-v2'));
END $body$;

-- 5. The dashboard's reference time comes from normal and acceptance runs only; historical
-- runs still count as completed runs (the dataset version, ADR-0067).
CREATE OR REPLACE VIEW app.query_environment AS
SELECT e.id, e.name, e.mode, e.disposable,
  latest.run_reference_time_utc AS reference_time,
  (SELECT count(*) FROM app.ingestion_run r
    WHERE r.environment_id = e.id AND r.closed AND r.state IN ('complete','partial')) AS completed_runs,
  latest.id AS latest_run_id,
  latest.created_at_actual_utc AS ingested_at,
  (SELECT min(m.retrieved_at) FROM app.raw_manifest m WHERE m.run_id = latest.id) AS source_retrieved_from,
  (SELECT max(m.retrieved_at) FROM app.raw_manifest m WHERE m.run_id = latest.id) AS source_retrieved_to
FROM app.ingestion_environment e
LEFT JOIN LATERAL (
  SELECT r.id, r.run_reference_time_utc, r.created_at_actual_utc FROM app.ingestion_run r
  WHERE r.environment_id = e.id AND r.closed AND r.state IN ('complete','partial')
    AND r.mode <> 'historical'
  ORDER BY r.run_reference_time_utc DESC, r.created_at_actual_utc DESC LIMIT 1
) latest ON true;

-- 6. Jobs (ADR-0079): the application login owns the rows; the worker and the API share it.
CREATE TABLE app.analysis_job (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL CHECK (kind IN ('export','forecast')),
  queue text NOT NULL CHECK (queue IN ('interactive-analysis','bulk-analysis','export','forecast')),
  client_id text NOT NULL CHECK (client_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
  idempotency_key text CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
  request jsonb NOT NULL,
  request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  plan jsonb NOT NULL,
  state text NOT NULL DEFAULT 'queued' CHECK (state IN (
    'queued','fetching','exporting','analysing','completed','partial','cancelled','failed')),
  progress jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  error jsonb,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  claimed_by text CHECK (length(claimed_by) <= 128),
  lease_until timestamptz,
  cancel_requested_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  started_at timestamptz,
  finished_at timestamptz,
  UNIQUE (client_id, idempotency_key)
);
CREATE INDEX analysis_job_client ON app.analysis_job(client_id, created_at DESC);
CREATE INDEX analysis_job_queue ON app.analysis_job(queue, created_at)
  WHERE state IN ('queued','fetching','exporting','analysing');
CREATE INDEX analysis_job_attach ON app.analysis_job(client_id, request_sha256)
  WHERE state IN ('queued','fetching','exporting','analysing');

CREATE TABLE app.analysis_job_chunk (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES app.analysis_job(id) ON DELETE CASCADE,
  seq integer NOT NULL CHECK (seq >= 1),
  kind text NOT NULL CHECK (kind IN ('fetch','export','series','model')),
  label text NOT NULL CHECK (length(label) BETWEEN 1 AND 128),
  interval_start timestamptz,
  interval_end timestamptz,
  tiles jsonb NOT NULL DEFAULT '[]'::jsonb,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN (
    'pending','running','complete','reused','failed','cancelled')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  ingestion_run_id uuid,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  error jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  CHECK (interval_start IS NULL OR interval_end IS NULL OR interval_start < interval_end),
  UNIQUE (job_id, seq)
);

CREATE TABLE app.analysis_job_event (
  job_id uuid NOT NULL REFERENCES app.analysis_job(id) ON DELETE CASCADE,
  seq integer NOT NULL CHECK (seq >= 1),
  kind text NOT NULL CHECK (length(kind) BETWEEN 1 AND 64),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (job_id, seq)
);

CREATE TABLE app.analysis_artefact (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES app.analysis_job(id) ON DELETE CASCADE,
  format text NOT NULL CHECK (format IN ('csv','parquet','json')),
  role text NOT NULL DEFAULT 'data' CHECK (role IN ('data','manifest','provenance','model')),
  object_key text NOT NULL UNIQUE CHECK (object_key ~ '^exports/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,128}$'),
  bytes bigint NOT NULL CHECK (bytes >= 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  row_count bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
  profile_count bigint NOT NULL DEFAULT 0 CHECK (profile_count >= 0),
  manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
  state text NOT NULL DEFAULT 'available' CHECK (state IN ('available','expired','deleted')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  expires_at timestamptz NOT NULL,
  deleted_at timestamptz,
  CHECK (expires_at > created_at)
);
CREATE INDEX analysis_artefact_job ON app.analysis_artefact(job_id, created_at);
CREATE INDEX analysis_artefact_expiry ON app.analysis_artefact(expires_at) WHERE state = 'available';

REVOKE ALL ON app.analysis_job, app.analysis_job_chunk, app.analysis_job_event,
  app.analysis_artefact FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floatchat_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON app.analysis_job, app.analysis_job_chunk,
      app.analysis_job_event, app.analysis_artefact TO floatchat_app;
  END IF;
END $$;
