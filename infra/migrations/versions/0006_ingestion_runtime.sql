CREATE TABLE app.run_baseline (
  run_id uuid PRIMARY KEY REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  evidence jsonb NOT NULL
);
CREATE TABLE app.chunk_accounting (
  chunk_id uuid PRIMARY KEY REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  fence bigint NOT NULL,
  evidence jsonb NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE app.run_final_evidence (
  run_id uuid PRIMARY KEY REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  evidence jsonb NOT NULL
);
REVOKE ALL ON app.run_final_evidence FROM PUBLIC,floatchat_app;
GRANT SELECT ON app.run_final_evidence TO floatchat_ingestor;
REVOKE ALL ON app.run_baseline,app.chunk_accounting FROM PUBLIC,floatchat_app;
GRANT SELECT ON app.run_baseline,app.chunk_accounting TO floatchat_ingestor;
ALTER TABLE app.ingestion_attempt ADD COLUMN origin text NOT NULL DEFAULT 'http'
  CHECK(origin IN ('http','captured','replay'));
CREATE TABLE app.processing_ticket (
  id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  control_epoch bigint NOT NULL,fence bigint NOT NULL,started boolean NOT NULL DEFAULT false,
  UNIQUE(chunk_id,fence)
);
GRANT SELECT ON app.processing_ticket TO floatchat_ingestor;
REVOKE ALL ON app.processing_ticket FROM PUBLIC,floatchat_app;

CREATE FUNCTION app.processing_ticket(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE ticket uuid;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  INSERT INTO app.processing_ticket(id,run_id,chunk_id,control_epoch,fence)
    VALUES(gen_random_uuid(),p_run,p_chunk,p_epoch,p_fence) ON CONFLICT DO NOTHING;
  SELECT id INTO STRICT ticket FROM app.processing_ticket WHERE chunk_id=p_chunk AND fence=p_fence;
  RETURN ticket;
END $body$;

CREATE FUNCTION app.start_worker(p_ticket uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE t app.processing_ticket;
BEGIN
  -- Consistent lock order: run/chunk authority precedes the ticket row.
  SELECT * INTO STRICT t FROM app.processing_ticket WHERE id=p_ticket;
  PERFORM app.assert_authority(t.run_id,t.chunk_id,t.control_epoch,t.fence);
  UPDATE app.processing_ticket SET started=true WHERE id=p_ticket AND NOT started;
  RETURN FOUND;
END $body$;

CREATE FUNCTION app.reserve_recorded_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_attempt uuid,p_key text,p_role text,p_parameters jsonb,p_origin text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE ordinal integer; attempts integer;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_origin NOT IN ('captured','replay') THEN RAISE EXCEPTION 'invalid_recorded_origin'; END IF;
  SELECT coalesce(max(attempt_number),0)+1 INTO ordinal FROM app.ingestion_attempt WHERE chunk_id=p_chunk;
  SELECT count(*)+1 INTO attempts FROM app.ingestion_attempt WHERE chunk_id=p_chunk AND logical_request_key=p_key;
  IF attempts>4 THEN RAISE EXCEPTION 'landing_retry_exhausted'; END IF;
  INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
    role,request_parameters,origin) VALUES(p_attempt,p_chunk,ordinal,p_key,attempts,p_role,p_parameters,p_origin);
END $body$;
REVOKE ALL ON FUNCTION app.processing_ticket(uuid,uuid,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.start_worker(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.reserve_recorded_attempt(uuid,uuid,bigint,bigint,uuid,text,text,jsonb,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.processing_ticket(uuid,uuid,bigint,bigint),app.start_worker(uuid),
  app.reserve_recorded_attempt(uuid,uuid,bigint,bigint,uuid,text,text,jsonb,text) TO floatchat_ingestor;

CREATE FUNCTION app.scientific_snapshot() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
SELECT jsonb_build_object(
  'floats',(SELECT count(*) FROM app.argo_float),
  'profiles',(SELECT count(*) FROM app.argo_profile),
  'measurement_levels',(SELECT count(*) FROM app.core_measurement),
  'profile_manifest_sha256',(SELECT encode(sha256(convert_to(coalesce(
    jsonb_agg(jsonb_build_array(id,content_hash,level_count) ORDER BY id),'[]'::jsonb)::text,'UTF8')),'hex')
    FROM app.argo_profile),
  'active_partitions',(SELECT count(*) FROM app.committed_active_partitions),
  'active_generation_sha256',(SELECT encode(sha256(convert_to(coalesce(
    jsonb_agg(jsonb_build_array(id,logical_key,generation,sha256) ORDER BY logical_key),'[]'::jsonb)::text,'UTF8')),'hex')
    FROM app.committed_active_partitions),
  'runs',(SELECT count(*) FROM app.ingestion_run),
  'attempts',(SELECT count(*) FROM app.ingestion_attempt),
  'audit_rows',(SELECT count(*) FROM app.ingestion_event)
);
$body$;

CREATE FUNCTION app.persist_baseline(p_run uuid,p_epoch bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  IF EXISTS(SELECT 1 FROM app.run_baseline WHERE run_id=p_run) THEN RETURN; END IF;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) THEN
    RAISE EXCEPTION 'baseline_must_precede_plan'; END IF;
  INSERT INTO app.run_baseline(run_id,evidence) VALUES(p_run,app.scientific_snapshot() ||
    jsonb_build_object('reconciliation',app.reconciliation_snapshot(p_run)));
END $body$;

CREATE FUNCTION app.record_accounting(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,p_evidence jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF octet_length(p_evidence::text)>65536 THEN RAISE EXCEPTION 'accounting_evidence_limit'; END IF;
  INSERT INTO app.chunk_accounting(chunk_id,fence,evidence) VALUES(p_chunk,p_fence,p_evidence)
    ON CONFLICT(chunk_id) DO UPDATE SET fence=excluded.fence,evidence=excluded.evidence,
      recorded_at=clock_timestamp();
END $body$;

CREATE FUNCTION app.ensure_measurement_month(p_run uuid,p_month date) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE r app.ingestion_run; name text; last date; expected text; relation regclass;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run FOR UPDATE;
  IF r.closed OR r.cancellation_requested_at IS NOT NULL OR r.work_deadline<=clock_timestamp()
    OR p_month<>date_trunc('month',p_month)::date
    OR p_month<date_trunc('month',(r.run_reference_time_utc AT TIME ZONE 'UTC')-interval '12 months')::date
    OR p_month>date_trunc('month',r.run_reference_time_utc AT TIME ZONE 'UTC')::date
    THEN RAISE EXCEPTION 'unsafe_measurement_month'; END IF;
  name := 'core_measurement_'||to_char(p_month,'YYYYMM');
  last := (p_month+interval '1 month')::date;
  PERFORM pg_advisory_xact_lock(hashtextextended('app/'||name,0));
  relation := to_regclass('app.'||name);
  expected := format('FOR VALUES FROM (%L) TO (%L)',p_month,last);
  IF relation IS NULL THEN
    EXECUTE format('CREATE TABLE app.%I PARTITION OF app.core_measurement %s',name,expected);
    EXECUTE format('REVOKE ALL ON app.%I FROM PUBLIC,floatchat_app,floatchat_ingestor',name);
    EXECUTE format('GRANT SELECT ON app.%I TO floatchat_ingestor',name);
  ELSIF NOT EXISTS(SELECT 1 FROM pg_inherits WHERE inhrelid=relation AND inhparent='app.core_measurement'::regclass)
    OR (SELECT pg_get_expr(relpartbound,oid) FROM pg_class WHERE oid=relation) IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'measurement_partition_mismatch';
  END IF;
END $body$;

REVOKE ALL ON FUNCTION app.scientific_snapshot() FROM PUBLIC;
REVOKE ALL ON FUNCTION app.persist_baseline(uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.record_accounting(uuid,uuid,bigint,bigint,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.ensure_measurement_month(uuid,date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.scientific_snapshot(),app.persist_baseline(uuid,bigint),
  app.record_accounting(uuid,uuid,bigint,bigint,jsonb) TO floatchat_ingestor;

CREATE FUNCTION app.reconciliation_snapshot(p_run uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
WITH r AS (SELECT requested_start AS first,requested_end AS last FROM app.ingestion_run WHERE id=p_run),
stored AS (SELECT id,content_hash,level_count,observed_at FROM app.argo_profile),
members AS (SELECT (m->>'profile_id')::uuid AS id,m->>'hash' AS hash,(m->>'levels')::integer AS levels
  FROM app.committed_active_partitions d,LATERAL jsonb_array_elements(d.membership_manifest) m),
populations AS (
  SELECT 'full_stored'::text AS scope,s.id,s.content_hash AS hash,s.level_count AS levels FROM stored s
  UNION ALL SELECT 'full_snapshot',m.id,m.hash,m.levels FROM members m
  UNION ALL SELECT 'run_eligible_stored',s.id,s.content_hash,s.level_count FROM stored s,r
    WHERE s.observed_at>=r.first AND s.observed_at<r.last
  UNION ALL SELECT 'run_eligible_snapshot',m.id,m.hash,m.levels FROM members m JOIN stored s ON s.id=m.id,r
    WHERE s.observed_at>=r.first AND s.observed_at<r.last),
summaries AS (SELECT scope,jsonb_build_object('profiles',count(*),'measurement_levels',sum(levels),
  'manifest_sha256',encode(sha256(convert_to(jsonb_agg(jsonb_build_array(id,hash,levels)
    ORDER BY id)::text,'UTF8')),'hex')) AS evidence FROM populations GROUP BY scope)
SELECT coalesce(jsonb_object_agg(scope,evidence),'{}'::jsonb) FROM summaries;
$body$;
CREATE FUNCTION app.capture_final_evidence(p_run uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM app.ingestion_run WHERE id=p_run AND closed)
    THEN RAISE EXCEPTION 'unfinished_run'; END IF;
  INSERT INTO app.run_final_evidence(run_id,evidence) VALUES(p_run,jsonb_build_object(
    'science',app.scientific_snapshot(),'reconciliation',app.reconciliation_snapshot(p_run),
    'report_metrics',app.report_metrics_snapshot(p_run),
    'active_generation_ids',(SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb)
      FROM app.committed_active_partitions))) ON CONFLICT DO NOTHING;
END $body$;
REVOKE ALL ON FUNCTION app.reconciliation_snapshot(uuid),app.capture_final_evidence(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.reconciliation_snapshot(uuid) TO floatchat_ingestor;

CREATE TABLE app.landing_reset (
  chunk_id uuid PRIMARY KEY REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  through_attempt integer NOT NULL,
  refresh_count integer NOT NULL CHECK(refresh_count BETWEEN 1 AND 3)
);
REVOKE ALL ON app.landing_reset FROM PUBLIC,floatchat_app;
GRANT SELECT ON app.landing_reset TO floatchat_ingestor;
CREATE FUNCTION app.restart_selection(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE cutoff integer;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF (SELECT state FROM app.ingestion_chunk WHERE id=p_chunk)<>'fetching'
    THEN RAISE EXCEPTION 'invalid_state_transition'; END IF;
  IF EXISTS(SELECT 1 FROM app.landing_reset WHERE chunk_id=p_chunk AND refresh_count>=3)
    THEN RAISE EXCEPTION 'http_retry_exhausted'; END IF;
  SELECT coalesce(max(attempt_number),0) INTO cutoff FROM app.ingestion_attempt WHERE chunk_id=p_chunk;
  INSERT INTO app.landing_reset VALUES(p_chunk,cutoff,1) ON CONFLICT(chunk_id) DO UPDATE
    SET through_attempt=excluded.through_attempt,refresh_count=app.landing_reset.refresh_count+1;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,reason,evidence)
    VALUES(p_run,p_chunk,p_epoch,p_fence,'inventory_changed_retry',jsonb_build_object('through_attempt',cutoff));
END $body$;
REVOKE ALL ON FUNCTION app.restart_selection(uuid,uuid,bigint,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.restart_selection(uuid,uuid,bigint,bigint) TO floatchat_ingestor;
-- Frozen reporting is captured in the same finalization transaction as the
-- terminal event. Later catalogue supersession or science cannot rewrite it.
CREATE FUNCTION app.report_metrics_snapshot(p_run uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE r app.ingestion_run; finish timestamptz; availability jsonb; result jsonb;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  SELECT coalesce(max(occurred_at),r.created_at_actual_utc) INTO finish
    FROM app.ingestion_event WHERE run_id=p_run;
  SELECT jsonb_build_object('full_retained',jsonb_build_object('pressure',jsonb_build_object('original',count(m.pressure) FILTER(WHERE true),'_adjusted',count(m.pressure_adjusted) FILTER(WHERE true),'_qc',count(m.pressure_qc) FILTER(WHERE true),'_adjusted_qc',count(m.pressure_adjusted_qc) FILTER(WHERE true),'_error',count(m.pressure_error) FILTER(WHERE true),'_original_error',count(m.pressure_original_error) FILTER(WHERE true)),'temperature',jsonb_build_object('original',count(m.temperature) FILTER(WHERE true),'_adjusted',count(m.temperature_adjusted) FILTER(WHERE true),'_qc',count(m.temperature_qc) FILTER(WHERE true),'_adjusted_qc',count(m.temperature_adjusted_qc) FILTER(WHERE true),'_error',count(m.temperature_error) FILTER(WHERE true),'_original_error',count(m.temperature_original_error) FILTER(WHERE true)),'salinity',jsonb_build_object('original',count(m.salinity) FILTER(WHERE true),'_adjusted',count(m.salinity_adjusted) FILTER(WHERE true),'_qc',count(m.salinity_qc) FILTER(WHERE true),'_adjusted_qc',count(m.salinity_adjusted_qc) FILTER(WHERE true),'_error',count(m.salinity_error) FILTER(WHERE true),'_original_error',count(m.salinity_original_error) FILTER(WHERE true))),'run_eligible',jsonb_build_object('pressure',jsonb_build_object('original',count(m.pressure) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted',count(m.pressure_adjusted) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_qc',count(m.pressure_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted_qc',count(m.pressure_adjusted_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_error',count(m.pressure_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_original_error',count(m.pressure_original_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end)),'temperature',jsonb_build_object('original',count(m.temperature) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted',count(m.temperature_adjusted) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_qc',count(m.temperature_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted_qc',count(m.temperature_adjusted_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_error',count(m.temperature_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_original_error',count(m.temperature_original_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end)),'salinity',jsonb_build_object('original',count(m.salinity) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted',count(m.salinity_adjusted) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_qc',count(m.salinity_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_adjusted_qc',count(m.salinity_adjusted_qc) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_error',count(m.salinity_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end),'_original_error',count(m.salinity_original_error) FILTER(WHERE p.observed_at>=r.requested_start AND p.observed_at<r.requested_end))))
    INTO availability FROM app.core_measurement m JOIN app.argo_profile p
      ON p.id=m.profile_id AND p.observation_month=m.observation_month;
  result:=jsonb_build_object(
    'availability',availability,
    'requested',jsonb_build_object('start',r.requested_start,'end',r.requested_end,
      'geometry_version',r.geometry_version,'geometry_sha256',r.geometry_sha256),
    'limits',r.limits,'policy_versions',r.policy_versions,
    'source_attribution',jsonb_build_object(
      'provider','International Argo Program and national contributors, via Argovis',
      'argo_doi','https://doi.org/10.17882/42182',
      'terms_and_acknowledgement','https://argo.ucsd.edu/data/acknowledging-argo/',
      'argovis_contract_citation','https://zenodo.org/records/15708506',
      'input_kind',(SELECT kind FROM app.ingestion_input WHERE run_id=p_run),
      'scope','Attribution is not proof of live capture; raw provenance distinguishes synthetic inputs'),
    'run_timing',jsonb_build_object('created_actual_utc',r.created_at_actual_utc,
      'terminal_event_actual_utc',finish,'elapsed_seconds',extract(epoch FROM finish-r.created_at_actual_utc)),
    'resource_counters',jsonb_build_object('http_attempts',r.http_attempts,
      'received_bytes',r.raw_received_bytes,'canonical_bytes',r.canonical_bytes,
      'accepted_new_profiles',r.accepted_profiles,'accepted_insert_replacement_levels',r.accepted_levels,
      'controller_claims',r.controller_claims),
    'active_generations',(SELECT coalesce(jsonb_agg(jsonb_build_object(
      'id',d.id,'logical_key',d.logical_key,'generation',d.generation,'sha256',d.sha256,
      'object_key',d.object_key,'bytes',d.bytes,'profiles',d.profile_count,'levels',d.row_count,
      'verified_at',d.verified_at,'committed_at',d.committed_at,'versions',d.versions,
      'verification_evidence',d.verification_evidence) ORDER BY d.logical_key),'[]'::jsonb)
      FROM app.committed_active_partitions d),
    'attempt_timing',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.origin,t.disposition),'[]'::jsonb)
      FROM (SELECT a.origin,a.disposition,count(*) AS attempts,
        count(*) FILTER(WHERE a.finished_at IS NULL) AS unfinished_attempts,
        sum(extract(epoch FROM a.finished_at-a.started_at)) AS elapsed_seconds_sum,
        min(a.started_at) AS first_started_at,max(a.finished_at) AS last_finished_at,
        max(extract(epoch FROM a.finished_at-a.started_at)) AS elapsed_seconds_max
        FROM app.ingestion_attempt a JOIN app.ingestion_chunk c ON c.id=a.chunk_id
        WHERE c.run_id=p_run GROUP BY a.origin,a.disposition) t),
    'attempt_reasons',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.origin,t.error_category,t.http_status),'[]'::jsonb)
      FROM (SELECT a.origin,a.disposition,a.error_category,a.http_status,count(*) AS attempts
        FROM app.ingestion_attempt a JOIN app.ingestion_chunk c ON c.id=a.chunk_id
        WHERE c.run_id=p_run GROUP BY a.origin,a.disposition,a.error_category,a.http_status) t),
    'http_retries',(SELECT coalesce(sum(greatest(n-1,0)),0) FROM
      (SELECT count(*) AS n FROM app.ingestion_attempt a JOIN app.ingestion_chunk c ON c.id=a.chunk_id
       WHERE c.run_id=p_run AND a.origin='http' GROUP BY a.chunk_id,a.logical_request_key) t),
    'processing_recoveries',(SELECT coalesce(sum(greatest(processing_claims-1,0)),0)
      FROM app.ingestion_chunk WHERE run_id=p_run),
    'phase_timings',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.phase),'[]'::jsonb)
      FROM (SELECT new_state AS phase,count(*) AS episodes,
        sum(extract(epoch FROM next_time-occurred_at)) AS wall_seconds_sum
        FROM (SELECT new_state,occurred_at,lead(occurred_at,1,finish)
          OVER(PARTITION BY chunk_id ORDER BY sequence) AS next_time
          FROM app.ingestion_event WHERE run_id=p_run AND chunk_id IS NOT NULL AND new_state IS NOT NULL) e
        GROUP BY new_state) t),
    'state_reasons',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.new_state,t.reason),'[]'::jsonb)
      FROM (SELECT new_state,reason,count(*) AS events FROM app.ingestion_event
        WHERE run_id=p_run GROUP BY new_state,reason) t),
    'unknown_level_reasons',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.reason),'[]'::jsonb)
      FROM (SELECT o.unknown_levels_reason AS reason,count(*) AS profile_occurrences
        FROM app.profile_outcome o JOIN app.ingestion_chunk c ON c.id=o.chunk_id
        WHERE c.run_id=p_run AND c.leaf AND o.source_levels IS NULL GROUP BY o.unknown_levels_reason) t),
    'replacement_levels',(SELECT jsonb_build_object(
      'old_levels_removed',coalesce(sum((o.evidence->>'old_levels')::bigint)
        FILTER(WHERE o.outcome='newer' AND o.committed),0),
      'inserted_replacement_levels',coalesce(sum(o.source_levels)
        FILTER(WHERE o.outcome IN ('insert','newer') AND o.committed),0),
      'no_op_levels',coalesce(sum(o.source_levels)
        FILTER(WHERE o.outcome IN ('noop','unordered_noop','revision_only') AND o.committed),0),
      'stale_skipped_levels',coalesce(sum(o.source_levels)
        FILTER(WHERE o.outcome='stale_skip' AND o.committed),0))
      FROM app.profile_outcome o JOIN app.ingestion_chunk c ON c.id=o.chunk_id WHERE c.run_id=p_run AND c.leaf),
    'verified_raw_provenance',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id),'[]'::jsonb)
      FROM (SELECT m.id,m.object_key,m.sha256,m.bytes,m.retrieved_at,m.application_commit,m.versions,
        m.sanitization,a.role,a.request_parameters,a.logical_request_key AS logical_request_sha256,a.origin,
        CASE WHEN a.role='metadata' THEN '/argo/meta' ELSE '/argo' END AS endpoint_path
        FROM app.raw_manifest m JOIN app.ingestion_attempt a ON a.id=m.attempt_id WHERE m.run_id=p_run) t),
    'catalogue_slot_versions',(SELECT coalesce(jsonb_object_agg(logical_key,slot_version),'{}'::jsonb)
      FROM app.logical_partition_slot),
    'selected_profiles_by_slot',(SELECT coalesce(jsonb_object_agg(slot,n),'{}'::jsonb) FROM
      (SELECT app.owner_slot(observed_at,(scientific_content->'longitude'->>'exact')::numeric,
        (scientific_content->'latitude'->>'exact')::numeric) AS slot,count(*) AS n FROM app.argo_profile
        WHERE observed_at>=r.requested_start AND observed_at<r.requested_end
        AND scientific_content->'longitude'->>'exact' IS NOT NULL
        AND scientific_content->'latitude'->>'exact' IS NOT NULL GROUP BY slot) t),
    'invalid_scientific_header_profiles',(SELECT count(*) FROM app.argo_profile
      WHERE scientific_content->'longitude'->>'exact' IS NULL OR scientific_content->'latitude'->>'exact' IS NULL),
    'coverage_receipt_count',(SELECT count(*) FROM app.coverage_receipt cr JOIN app.ingestion_chunk c
      ON c.id=cr.chunk_id AND c.state='complete' JOIN app.publication_intent i ON i.id=cr.intent_id AND i.status='committed'
      WHERE cr.requested_start<r.requested_end AND cr.requested_end>r.requested_start),
    'coverage_receipts',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.id),'[]'::jsonb) FROM
      (SELECT cr.id,cr.logical_key,cr.requested_start,cr.requested_end,cr.slot_version,
        cr.fetch_disposition,cr.stored_disposition,cr.committed_at,c.tile
        FROM app.coverage_receipt cr JOIN app.ingestion_chunk c ON c.id=cr.chunk_id AND c.state='complete'
        JOIN app.publication_intent i ON i.id=cr.intent_id AND i.status='committed'
        WHERE cr.requested_start<r.requested_end AND cr.requested_end>r.requested_start ORDER BY cr.id LIMIT 16385) t)
  );
  RETURN result;
END $body$;
REVOKE ALL ON FUNCTION app.report_metrics_snapshot(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.report_metrics_snapshot(uuid) TO floatchat_ingestor;

