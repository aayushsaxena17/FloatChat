-- stage1-v3 runtime amendment (ADR-0043): run wall-time bound 6 h -> 12 h, from the
-- measured live throughput in reports/stage1-live-throughput-c9af101a.json. Additive;
-- the 60-second final evidence reserve and every other bound are unchanged.
DO $body$
DECLARE c text;
BEGIN
  SELECT conname INTO STRICT c FROM pg_constraint
    WHERE conrelid='app.ingestion_run'::regclass AND contype='c'
    AND pg_get_constraintdef(oid) LIKE '%deadline <= (created_at_actual_utc + ''06:00:00''::interval)%';
  EXECUTE format('ALTER TABLE app.ingestion_run DROP CONSTRAINT %I', c);
END $body$;
ALTER TABLE app.ingestion_run ADD CONSTRAINT ingestion_run_deadline_window
  CHECK (deadline > created_at_actual_utc + interval '60 seconds'
         AND deadline <= created_at_actual_utc + interval '12 hours');

CREATE OR REPLACE FUNCTION app.admit_run(p_environment uuid,p_request uuid,p_mode text,p_scheduled boolean,
  p_start timestamptz,p_end timestamptz,p_seconds integer,p_geometry_hash text,p_versions jsonb,p_limits jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE e app.ingestion_environment; s app.ingestion_scope; r app.ingestion_run;
        reference timestamptz; actual timestamptz; first timestamptz; last timestamptz;
        run_uuid uuid; admission_uuid uuid;
BEGIN
  SELECT * INTO STRICT e FROM app.ingestion_environment WHERE id=p_environment;
  IF e.mode<>p_mode OR (p_mode='acceptance' AND NOT e.disposable)
     OR (p_scheduled AND p_mode<>'normal') OR p_seconds NOT BETWEEN 61 AND 43200
     OR p_geometry_hash<>encode(sha256(convert_to('POLYGON((20 -60,120 -60,120 30,20 30,20 -60))','UTF8')),'hex')
     THEN RAISE EXCEPTION 'unsafe_run_configuration'; END IF;
  INSERT INTO app.ingestion_scope(environment_id,source,region_version)
    VALUES(p_environment,'argovis','indian-ocean-v1') ON CONFLICT DO NOTHING;
  SELECT * INTO STRICT s FROM app.ingestion_scope WHERE environment_id=p_environment
    AND source='argovis' AND region_version='indian-ocean-v1' FOR UPDATE;
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
      jsonb_build_object('source','argovis','region_version','indian-ocean-v1'),
      'overlap_skip',r.id,'unfinished_run');
    RETURN jsonb_build_object('kind','overlap_skip','event_id',admission_uuid);
  END IF;
  actual := clock_timestamp();
  reference := CASE WHEN p_mode='acceptance' THEN '2025-04-01T00:00:00Z'::timestamptz ELSE actual END;
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
    WHERE environment_id=p_environment AND source='argovis' AND region_version='indian-ocean-v1';
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason)
    VALUES(run_uuid,1,'run_admitted_reference_captured');
  RETURN jsonb_build_object('kind','created','run_id',run_uuid);
END $body$;
