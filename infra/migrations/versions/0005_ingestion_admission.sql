ALTER TABLE app.ingestion_run ADD COLUMN request_id uuid UNIQUE;
ALTER TABLE app.ingestion_run ADD COLUMN controller_instance uuid;
CREATE TABLE app.ingestion_input (
  run_id uuid PRIMARY KEY REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK(kind IN ('live','captured','replay')),
  descriptor jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE app.canonical_work (
  id uuid PRIMARY KEY,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  fence bigint NOT NULL,
  status text NOT NULL CHECK(status IN ('reserved','complete','process_loss')),
  reserved_bytes bigint NOT NULL CHECK(reserved_bytes=16777216),
  actual_bytes bigint CHECK(actual_bytes BETWEEN 0 AND 16777216)
);

CREATE FUNCTION app.assert_run(p_run uuid,p_epoch bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run FOR UPDATE;
  IF r.closed OR r.control_epoch<>p_epoch OR r.cancellation_requested_at IS NOT NULL
     OR r.work_deadline<=clock_timestamp() OR r.controller_lease_until<=clock_timestamp()
     THEN RAISE EXCEPTION 'run_fenced'; END IF;
END $body$;

CREATE FUNCTION app.admit_run(p_environment uuid,p_request uuid,p_mode text,p_scheduled boolean,
  p_start timestamptz,p_end timestamptz,p_seconds integer,p_geometry_hash text,p_versions jsonb,p_limits jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE e app.ingestion_environment; s app.ingestion_scope; r app.ingestion_run;
        reference timestamptz; actual timestamptz; first timestamptz; last timestamptz;
        run_uuid uuid; admission_uuid uuid;
BEGIN
  SELECT * INTO STRICT e FROM app.ingestion_environment WHERE id=p_environment;
  IF e.mode<>p_mode OR (p_mode='acceptance' AND NOT e.disposable)
     OR (p_scheduled AND p_mode<>'normal') OR p_seconds NOT BETWEEN 61 AND 21600
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

CREATE FUNCTION app.persist_plan(p_run uuid,p_epoch bigint,p_plan jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; item jsonb; n integer;
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) THEN RETURN; END IF;
  n := jsonb_array_length(p_plan);
  IF n NOT BETWEEN 1 AND 16384 THEN RAISE EXCEPTION 'chunk_count_limit'; END IF;
  -- Compare the entire deterministic initial space/time population, not merely
  -- each row's bounds. Omitting or duplicating one tile must fail admission.
  IF EXISTS (
    WITH RECURSIVE slices(first,last) AS (
      SELECT r.requested_start,least(r.requested_end,r.requested_start+interval '7 days',
        ((date_trunc('month',r.requested_start AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      UNION ALL
      SELECT last,least(r.requested_end,last+interval '7 days',
        ((date_trunc('month',last AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
        FROM slices WHERE last<r.requested_end
    ), expected AS (
      SELECT first,last,west,south,10 AS width,10 AS height FROM slices
        CROSS JOIN generate_series(20,110,10) w(west)
        CROSS JOIN generate_series(-60,20,10) s(south)
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
       OR (item->>'end')::timestamptz-(item->>'start')::timestamptz>interval '7 days'
       THEN RAISE EXCEPTION 'invalid_plan_chunk'; END IF;
    INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,tile,plan_version)
      VALUES((item->>'id')::uuid,p_run,item->>'key',(item->>'start')::timestamptz,
        (item->>'end')::timestamptz,item->'tile','indian-ocean-plan-v1');
  END LOOP;
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason,evidence)
    VALUES(p_run,p_epoch,'complete_plan_persisted',jsonb_build_object('chunks',n));
END $body$;

CREATE FUNCTION app.controller_heartbeat(p_run uuid,p_epoch bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()+interval '10 minutes' WHERE id=p_run;
  UPDATE app.ingestion_scope SET lease_until=clock_timestamp()+interval '10 minutes'
    WHERE unfinished_run_id=p_run;
END $body$;

CREATE FUNCTION app.account_bytes(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                  p_attempt uuid,p_bytes integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_bytes NOT BETWEEN 1 AND 65536 OR NOT EXISTS(SELECT 1 FROM app.ingestion_attempt
       WHERE id=p_attempt AND chunk_id=p_chunk AND disposition IS NULL)
       THEN RAISE EXCEPTION 'invalid_byte_accounting'; END IF;
  UPDATE app.ingestion_run SET raw_received_bytes=raw_received_bytes+p_bytes WHERE id=p_run;
  UPDATE app.ingestion_attempt SET bytes_received=bytes_received+p_bytes WHERE id=p_attempt;
END $body$;

CREATE FUNCTION app.finish_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_attempt uuid,p_disposition text,p_status integer,p_error text,p_manifest jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF NOT EXISTS(SELECT 1 FROM app.ingestion_attempt WHERE id=p_attempt AND chunk_id=p_chunk
      AND disposition IS NULL) THEN RAISE EXCEPTION 'attempt_already_final'; END IF;
  IF p_disposition='verified_raw' THEN
    INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,retrieved_at,
      versions,sanitization,application_commit)
    VALUES((p_manifest->>'id')::uuid,p_run,p_chunk,p_attempt,p_manifest->>'key',p_manifest->>'sha256',
      (p_manifest->>'bytes')::bigint,(p_manifest->>'retrieved_at')::timestamptz,p_manifest->'versions',
      p_manifest->'sanitization',p_manifest->>'application_commit');
  ELSIF p_manifest IS NOT NULL THEN RAISE EXCEPTION 'unexpected_raw_manifest'; END IF;
  UPDATE app.ingestion_attempt SET disposition=p_disposition,finished_at=clock_timestamp(),
    http_status=p_status,error_category=p_error WHERE id=p_attempt;
END $body$;

CREATE FUNCTION app.account_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                      p_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_bytes NOT BETWEEN 1 AND 16777216 THEN RAISE EXCEPTION 'canonical_output_limit'; END IF;
  UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+p_bytes WHERE id=p_run;
END $body$;

CREATE FUNCTION app.prepare_intent(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_intent uuid,p_objects jsonb,p_bases jsonb,p_revisions jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF NOT EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE id=p_chunk AND state='publishing')
    THEN RAISE EXCEPTION 'invalid_publication_phase'; END IF;
  UPDATE app.publication_intent SET status='abandoned',disposition_reason='bounded_rebuild'
    WHERE chunk_id=p_chunk AND status='prepared';
  INSERT INTO app.publication_intent VALUES(p_intent,p_chunk,p_fence,p_epoch,'prepared',clock_timestamp(),
    p_objects,p_bases,p_revisions,NULL);
END $body$;

CREATE FUNCTION app.ensure_slot(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                               p_month date,p_west integer,p_south integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; slot text;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  IF p_month<>date_trunc('month',p_month)::date OR p_west NOT BETWEEN 20 AND 110
     OR (p_west-20)%10<>0 OR p_south NOT BETWEEN -60 AND 20 OR (p_south+60)%10<>0
     THEN RAISE EXCEPTION 'invalid_slot'; END IF;
  slot := app.owner_slot(p_month::timestamp AT TIME ZONE 'UTC',p_west,p_south);
  INSERT INTO app.logical_partition_slot(environment_id,logical_key,observation_month,tile_key)
    VALUES(r.environment_id,slot,p_month,p_west||':'||p_south) ON CONFLICT DO NOTHING;
  RETURN slot;
END $body$;

CREATE FUNCTION app.check_staging_authority() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE epoch bigint;
BEGIN
  SELECT control_epoch INTO STRICT epoch FROM app.ingestion_chunk WHERE id=NEW.chunk_id;
  PERFORM app.assert_authority(NEW.run_id,NEW.chunk_id,epoch,NEW.fence);
  IF NEW.occurrence_index NOT BETWEEN 0 AND 1999 OR octet_length(NEW.candidate::text)>67108864
    THEN RAISE EXCEPTION 'staging_resource_limit'; END IF;
  RETURN NEW;
END $body$;
CREATE TRIGGER staging_authority BEFORE INSERT ON app.ingestion_staging
FOR EACH ROW EXECUTE FUNCTION app.check_staging_authority();

DO $body$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='floatchat_ingestor') THEN
    CREATE ROLE floatchat_ingestor NOLOGIN;
  END IF;
END $body$;
GRANT USAGE ON SCHEMA app TO floatchat_ingestor;
GRANT SELECT ON app.ingestion_environment,app.ingestion_run,app.ingestion_chunk,
  app.ingestion_attempt,app.raw_manifest,app.argo_float,app.argo_profile,app.core_measurement,
  app.logical_partition_slot,app.publication_intent,app.dataset_partition,app.coverage_receipt,
  app.ingestion_event,app.profile_outcome,app.ingestion_scope,app.scheduling_attempt,
  app.ingestion_staging,app.committed_active_partitions TO floatchat_ingestor;
GRANT INSERT ON app.ingestion_staging TO floatchat_ingestor;
REVOKE ALL ON FUNCTION app.assert_run(uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.admit_run(uuid,uuid,text,boolean,timestamptz,timestamptz,integer,text,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.persist_plan(uuid,bigint,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.controller_heartbeat(uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.account_bytes(uuid,uuid,bigint,bigint,uuid,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.finish_attempt(uuid,uuid,bigint,bigint,uuid,text,integer,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.account_canonical(uuid,uuid,bigint,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.prepare_intent(uuid,uuid,bigint,bigint,uuid,jsonb,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.ensure_slot(uuid,uuid,bigint,bigint,date,integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.check_staging_authority() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.admit_run(uuid,uuid,text,boolean,timestamptz,timestamptz,integer,text,jsonb,jsonb),
  app.owner_slot(timestamptz,numeric,numeric),
  app.persist_plan(uuid,bigint,jsonb),app.controller_heartbeat(uuid,bigint),
  app.claim_chunk(uuid,uuid,bigint),app.adopt_controller(uuid),app.heartbeat(uuid,uuid,bigint,bigint),
  app.transition_chunk(uuid,uuid,bigint,bigint,text,text,jsonb),app.finalize_run(uuid,text),
  app.reserve_http_attempt(uuid,uuid,bigint,bigint,uuid,text,text,jsonb),
  app.account_bytes(uuid,uuid,bigint,bigint,uuid,integer),
  app.finish_attempt(uuid,uuid,bigint,bigint,uuid,text,integer,text,jsonb),
  app.account_canonical(uuid,uuid,bigint,bigint,bigint),
  app.prepare_intent(uuid,uuid,bigint,bigint,uuid,jsonb,jsonb,jsonb),
  app.ensure_slot(uuid,uuid,bigint,bigint,date,integer,integer),
  app.clear_staging(uuid,uuid,bigint,bigint),
  app.commit_publication(uuid,uuid,bigint,bigint,uuid,jsonb,jsonb)
TO floatchat_ingestor;

CREATE FUNCTION app.start_controller(p_run uuid,p_instance uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; epoch bigint;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run FOR UPDATE;
  IF r.closed THEN RETURN NULL; END IF;
  IF r.controller_instance=p_instance AND r.controller_lease_until>clock_timestamp() THEN
    PERFORM app.assert_run(p_run,r.control_epoch);
    RETURN r.control_epoch;
  END IF;
  IF r.controller_instance IS NULL AND r.controller_lease_until>clock_timestamp() THEN
    PERFORM app.assert_run(p_run,r.control_epoch);
    UPDATE app.ingestion_run SET controller_instance=p_instance WHERE id=p_run;
    RETURN r.control_epoch;
  END IF;
  IF r.controller_lease_until>clock_timestamp() THEN RETURN NULL; END IF;
  epoch := app.adopt_controller(p_run);
  UPDATE app.ingestion_run SET controller_instance=p_instance WHERE id=p_run;
  RETURN epoch;
END $body$;

CREATE FUNCTION app.persist_input(p_run uuid,p_epoch bigint,p_kind text,p_descriptor jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  IF EXISTS(SELECT 1 FROM app.ingestion_input WHERE run_id=p_run) THEN
    IF NOT EXISTS(SELECT 1 FROM app.ingestion_input WHERE run_id=p_run
       AND kind=p_kind AND descriptor=p_descriptor) THEN RAISE EXCEPTION 'immutable_input_descriptor'; END IF;
    RETURN;
  END IF;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) OR octet_length(p_descriptor::text)>65536
    THEN RAISE EXCEPTION 'input_must_precede_plan'; END IF;
  INSERT INTO app.ingestion_input(run_id,kind,descriptor) VALUES(p_run,p_kind,p_descriptor);
END $body$;

CREATE FUNCTION app.reserve_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,p_work uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE used bigint; reserved bigint;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT canonical_bytes INTO used FROM app.ingestion_run WHERE id=p_run;
  SELECT coalesce(sum(w.reserved_bytes),0) INTO reserved FROM app.canonical_work w
    JOIN app.ingestion_chunk c ON c.id=w.chunk_id WHERE c.run_id=p_run AND w.status='reserved';
  IF used+reserved+16777216>10737418240 THEN RAISE EXCEPTION 'canonical_output_limit'; END IF;
  INSERT INTO app.canonical_work VALUES(p_work,p_chunk,p_fence,'reserved',16777216,NULL);
END $body$;

CREATE FUNCTION app.finish_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                    p_work uuid,p_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_bytes NOT BETWEEN 0 AND 16777216 THEN RAISE EXCEPTION 'canonical_output_limit'; END IF;
  UPDATE app.canonical_work SET status='complete',actual_bytes=p_bytes WHERE id=p_work
    AND chunk_id=p_chunk AND fence=p_fence AND status='reserved';
  IF NOT FOUND THEN RAISE EXCEPTION 'canonical_reservation_final'; END IF;
  UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+p_bytes WHERE id=p_run;
END $body$;

CREATE FUNCTION app.record_profile_outcomes(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                           p_outcomes jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE item jsonb;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF jsonb_array_length(p_outcomes)>2000 THEN RAISE EXCEPTION 'profile_count_limit'; END IF;
  -- This is the current selected response's proposed ledger. A changing
  -- inventory/recovery cannot leave obsolete ordinals, hashes or level counts.
  -- Earlier raw payloads and retry events remain immutable attempt evidence.
  DELETE FROM app.profile_outcome WHERE chunk_id=p_chunk AND NOT committed;
  FOR item IN SELECT value FROM jsonb_array_elements(p_outcomes) LOOP
    INSERT INTO app.profile_outcome(chunk_id,occurrence_index,identity_key,outcome,source_levels,
      unknown_levels_reason,proposed_content_hash,committed,evidence)
    VALUES(p_chunk,(item->>'index')::integer,item->>'identity',item->>'outcome',
      (item->>'levels')::integer,item->>'unknown_levels_reason',item->>'hash',false,item->'evidence')
    ON CONFLICT(chunk_id,occurrence_index) DO UPDATE SET outcome=excluded.outcome,
      evidence=excluded.evidence WHERE NOT app.profile_outcome.committed;
  END LOOP;
END $body$;

CREATE FUNCTION app.split_chunk(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,p_children jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE c app.ingestion_chunk; a jsonb; b jsonb; item jsonb; valid boolean;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id=p_chunk;
  IF NOT c.leaf OR c.state NOT IN ('planned','fetching','landed','validating')
    OR jsonb_array_length(p_children)<>2
    OR (SELECT count(*)+2 FROM app.ingestion_chunk WHERE run_id=p_run)>16384
    THEN RAISE EXCEPTION 'chunk_split_denied'; END IF;
  a := p_children->0; b := p_children->1;
  -- Exact two-child union: either a temporal split or an integral spatial split.
  valid := a->'tile'=c.tile AND b->'tile'=c.tile
    AND (a->>'start')::timestamptz=c.requested_start
    AND (b->>'end')::timestamptz=c.requested_end
    AND (a->>'end')::timestamptz=(b->>'start')::timestamptz
    AND (a->>'end')::timestamptz-(a->>'start')::timestamptz>=interval '1 hour'
    AND (b->>'end')::timestamptz-(b->>'start')::timestamptz>=interval '1 hour';
  IF NOT valid THEN
    valid := (a->>'start')::timestamptz=c.requested_start AND (a->>'end')::timestamptz=c.requested_end
      AND (b->>'start')::timestamptz=c.requested_start AND (b->>'end')::timestamptz=c.requested_end
      AND ((a->'tile'->>'west')::integer=(c.tile->>'west')::integer
        AND (a->'tile'->>'south')::integer=(c.tile->>'south')::integer)
      AND ((
        a->'tile'->>'south'=b->'tile'->>'south'
        AND a->'tile'->>'height'=c.tile->>'height' AND b->'tile'->>'height'=c.tile->>'height'
        AND (b->'tile'->>'west')::integer=(a->'tile'->>'west')::integer+(a->'tile'->>'width')::integer
        AND (a->'tile'->>'width')::integer+(b->'tile'->>'width')::integer=(c.tile->>'width')::integer
      ) OR (
        a->'tile'->>'west'=b->'tile'->>'west'
        AND a->'tile'->>'width'=c.tile->>'width' AND b->'tile'->>'width'=c.tile->>'width'
        AND (b->'tile'->>'south')::integer=(a->'tile'->>'south')::integer+(a->'tile'->>'height')::integer
        AND (a->'tile'->>'height')::integer+(b->'tile'->>'height')::integer=(c.tile->>'height')::integer
      ));
  END IF;
  IF valid IS NOT TRUE THEN RAISE EXCEPTION 'invalid_split_coverage'; END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(p_children) LOOP
    IF (item->'tile'->>'width')::integer NOT BETWEEN 1 AND 10
      OR (item->'tile'->>'height')::integer NOT BETWEEN 1 AND 10 THEN RAISE EXCEPTION 'invalid_split_tile'; END IF;
    INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,tile,plan_version,parent_id)
      VALUES((item->>'id')::uuid,p_run,item->>'key',(item->>'start')::timestamptz,
        (item->>'end')::timestamptz,item->'tile',c.plan_version,p_chunk);
  END LOOP;
  UPDATE app.ingestion_chunk SET leaf=false,state='failed',reason='split_replaced',lease_until=NULL WHERE id=p_chunk;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,old_state,new_state,reason,evidence)
    VALUES(p_run,p_chunk,p_epoch,p_fence,c.state,'failed','split_replaced',p_children);
END $body$;

GRANT SELECT ON app.ingestion_input,app.canonical_work TO floatchat_ingestor;
REVOKE ALL ON FUNCTION app.start_controller(uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.persist_input(uuid,bigint,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.reserve_canonical(uuid,uuid,bigint,bigint,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.finish_canonical(uuid,uuid,bigint,bigint,uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.record_profile_outcomes(uuid,uuid,bigint,bigint,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.split_chunk(uuid,uuid,bigint,bigint,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.start_controller(uuid,uuid),app.persist_input(uuid,bigint,text,jsonb),
  app.reserve_canonical(uuid,uuid,bigint,bigint,uuid),app.finish_canonical(uuid,uuid,bigint,bigint,uuid,bigint),
  app.record_profile_outcomes(uuid,uuid,bigint,bigint,jsonb),app.split_chunk(uuid,uuid,bigint,bigint,jsonb)
TO floatchat_ingestor;
