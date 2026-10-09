CREATE FUNCTION app.assert_authority(p_run uuid, p_chunk uuid, p_epoch bigint, p_fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; c app.ingestion_chunk;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id = p_run FOR UPDATE;
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id = p_chunk AND run_id = p_run FOR UPDATE;
  IF r.closed OR r.cancellation_requested_at IS NOT NULL
     OR r.state IN ('complete','partial','quarantined','failed')
     OR c.state IN ('complete','quarantined','failed')
     OR r.control_epoch <> p_epoch OR c.control_epoch <> p_epoch OR c.fence <> p_fence
     OR r.controller_lease_until <= clock_timestamp() OR c.lease_until IS NULL
     OR c.lease_until <= clock_timestamp()
     OR r.work_deadline <= clock_timestamp() THEN
    RAISE EXCEPTION 'publication_fenced';
  END IF;
END $body$;

CREATE FUNCTION app.claim_chunk(p_run uuid, p_chunk uuid, p_epoch bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; c app.ingestion_chunk; next_fence bigint;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id = p_run FOR UPDATE;
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id = p_chunk AND run_id = p_run FOR UPDATE;
  IF c.state IN ('complete','quarantined','failed') THEN RETURN NULL; END IF;
  IF r.closed OR r.control_epoch <> p_epoch OR r.cancellation_requested_at IS NOT NULL
     OR r.controller_lease_until <= clock_timestamp() OR r.work_deadline <= clock_timestamp()
     OR (c.lease_until > clock_timestamp() AND c.control_epoch = p_epoch)
     OR c.processing_claims >= 4 THEN RAISE EXCEPTION 'claim_denied'; END IF;
  IF (SELECT count(*) FROM app.ingestion_chunk active WHERE active.run_id=p_run
      AND active.control_epoch=p_epoch AND active.lease_until>clock_timestamp()
      AND active.state NOT IN ('complete','quarantined','failed'))>=2
      THEN RAISE EXCEPTION 'environment_concurrency_limit'; END IF;
  next_fence := c.fence + 1;
  -- Unknown canonical work is charged at its reserved upper bound on takeover.
  -- The reservation survives process death, so redelivery cannot reset budget.
  WITH spent AS (UPDATE app.canonical_work SET status='process_loss',actual_bytes=reserved_bytes
    WHERE chunk_id=p_chunk AND status='reserved' RETURNING reserved_bytes)
  UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+
    coalesce((SELECT sum(reserved_bytes) FROM spent),0) WHERE id=p_run;
  UPDATE app.ingestion_chunk SET fence = next_fence, control_epoch = p_epoch,
    processing_claims = processing_claims + 1, lease_until = clock_timestamp() + interval '10 minutes'
    WHERE id = p_chunk;
  UPDATE app.ingestion_attempt SET finished_at = clock_timestamp(), disposition = 'interrupted',
    error_category = 'process_loss_unknown_outcome'
    WHERE chunk_id = p_chunk AND disposition IS NULL;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,old_state,new_state,reason)
    VALUES(p_run,p_chunk,p_epoch,next_fence,c.state,c.state,'processing_claim');
  RETURN next_fence;
END $body$;

CREATE FUNCTION app.adopt_controller(p_run uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id = p_run FOR UPDATE;
  IF r.closed OR r.state IN ('complete','partial','quarantined','failed')
     OR r.cancellation_requested_at IS NOT NULL OR r.work_deadline <= clock_timestamp()
     OR r.controller_lease_until > clock_timestamp() OR r.controller_claims >= 4
     THEN RAISE EXCEPTION 'controller_claim_denied'; END IF;
  UPDATE app.ingestion_run SET control_epoch = control_epoch + 1,
    controller_claims = controller_claims + 1,
    controller_lease_until = clock_timestamp() + interval '10 minutes' WHERE id = p_run;
  UPDATE app.ingestion_scope SET fence = fence + 1,
    lease_until = clock_timestamp() + interval '10 minutes' WHERE unfinished_run_id = p_run;
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason)
    VALUES(p_run,r.control_epoch + 1,'controller_adoption');
  RETURN r.control_epoch + 1;
END $body$;

CREATE FUNCTION app.heartbeat(p_run uuid, p_chunk uuid, p_epoch bigint, p_fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  UPDATE app.ingestion_chunk SET lease_until = clock_timestamp() + interval '10 minutes'
    WHERE id = p_chunk;
END $body$;

CREATE FUNCTION app.transition_chunk(p_run uuid, p_chunk uuid, p_epoch bigint, p_fence bigint,
                                    p_state text, p_reason text, p_evidence jsonb DEFAULT '{}')
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE c app.ingestion_chunk;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id = p_chunk;
  -- Complete is exclusively a scientific publication-transaction operation.
  IF p_state = 'complete' OR NOT (CASE c.state
    WHEN 'planned' THEN p_state IN ('fetching','failed')
    WHEN 'fetching' THEN p_state IN ('fetching','landed','quarantined','failed')
    WHEN 'landed' THEN p_state IN ('landed','validating','quarantined','failed')
    WHEN 'validating' THEN p_state IN ('validating','publishing','quarantined','failed')
    WHEN 'publishing' THEN p_state IN ('publishing','quarantined','failed')
    ELSE false END) THEN RAISE EXCEPTION 'invalid_state_transition'; END IF;
  IF p_state = 'publishing' AND c.publication_attempts >= 4
    THEN RAISE EXCEPTION 'publication_budget_exhausted'; END IF;
  UPDATE app.ingestion_chunk SET state = p_state, reason = p_reason,
    publication_attempts = publication_attempts + CASE WHEN p_state = 'publishing' THEN 1 ELSE 0 END
    WHERE id = p_chunk;
  IF p_state IN ('quarantined','failed') THEN
    UPDATE app.ingestion_attempt SET finished_at=clock_timestamp(),disposition='interrupted',
      error_category=p_reason WHERE chunk_id=p_chunk AND disposition IS NULL;
    WITH spent AS (UPDATE app.canonical_work SET status='process_loss',actual_bytes=reserved_bytes
      WHERE chunk_id=p_chunk AND status='reserved' RETURNING reserved_bytes)
    UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+
      coalesce((SELECT sum(reserved_bytes) FROM spent),0) WHERE id=p_run;
    UPDATE app.publication_intent SET status = 'abandoned', disposition_reason = p_reason
      WHERE chunk_id = p_chunk AND status = 'prepared';
    UPDATE app.profile_outcome SET committed = false,
      outcome = CASE WHEN p_state = 'quarantined' THEN 'blocked_by_chunk_quarantine'
                     ELSE 'blocked_uncommitted' END,
      evidence = evidence || jsonb_build_object('blocking_reason',p_reason)
      WHERE chunk_id = p_chunk AND NOT committed
      AND outcome IN ('insert','newer','revision_only','noop','unordered_noop','stale_skip','blocked_uncommitted');
    IF p_state='quarantined' AND p_reason='revision_conflict' THEN
      -- Publication has rolled back. Capture current committed opponent state
      -- under the closing fence; keep immutable intent/object references intact.
      SELECT p_evidence || jsonb_build_object('publication_conflicts',coalesce(
        jsonb_agg(jsonb_build_object('stored_profile_id',p.id,'stored_hash',p.content_hash,
          'stored_revision',p.source_revision,'incoming_hash',s.candidate->>'content_hash',
          'incoming_revision',s.candidate->'revision','active_generation_ids',(
            SELECT coalesce(jsonb_agg(d.id),'[]'::jsonb) FROM app.dataset_partition d
            WHERE d.status='active' AND d.logical_key=app.owner_slot(p.observed_at,
              (p.scientific_content->'longitude'->>'exact')::numeric,
              (p.scientific_content->'latitude'->>'exact')::numeric)))),'[]'::jsonb))
      INTO p_evidence FROM app.ingestion_staging s JOIN app.argo_profile p
        ON p.source_profile_id=s.candidate->>'source_profile_id'
        OR p.id=(s.candidate->>'proposed_profile_id')::uuid
      WHERE s.chunk_id=p_chunk AND s.fence=p_fence
        AND app.revision_outcome(s.candidate->>'content_hash',s.candidate->'revision',
          p.content_hash,p.source_revision)='revision_conflict';
    END IF;
  END IF;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,
                                  old_state,new_state,reason,evidence)
    VALUES(p_run,p_chunk,p_epoch,p_fence,c.state,p_state,p_reason,p_evidence);
  -- For interleaved chunks the run phase describes current work, never coverage.
  IF p_state IN ('fetching','landed','validating','publishing') THEN
    INSERT INTO app.ingestion_event(run_id,control_epoch,old_state,new_state,reason)
      SELECT id,control_epoch,state,p_state,'child_phase' FROM app.ingestion_run
      WHERE id=p_run AND state<>p_state;
    UPDATE app.ingestion_run SET state=p_state WHERE id=p_run AND state<>p_state;
  END IF;
END $body$;

CREATE FUNCTION app.finalize_run(p_run uuid, p_reason text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; total integer; good integer; bad integer; quarantine integer;
        result text; affected integer := 0;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id = p_run FOR UPDATE;
  IF r.state IN ('complete','partial','quarantined','failed') THEN RETURN r.state; END IF;
  IF p_reason IS NOT NULL AND p_reason NOT IN ('operator_cancelled','deadline_expired',
        'recovery_budget_exhausted','execution_failed') THEN RAISE EXCEPTION 'invalid_termination'; END IF;
  IF p_reason = 'deadline_expired' AND r.work_deadline > clock_timestamp()
    THEN RAISE EXCEPTION 'deadline_not_expired'; END IF;
  IF p_reason IS NOT NULL THEN
    UPDATE app.ingestion_run SET closed = true, control_epoch = control_epoch + 1,
      termination_reason = p_reason,
      cancellation_requested_at = CASE WHEN p_reason = 'operator_cancelled'
        THEN clock_timestamp() ELSE cancellation_requested_at END WHERE id = p_run;
    INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,old_state,new_state,reason)
      SELECT p_run,id,r.control_epoch + 1,fence + 1,state,'failed',p_reason
      FROM app.ingestion_chunk WHERE run_id = p_run AND state NOT IN ('complete','quarantined','failed');
    UPDATE app.ingestion_chunk SET state = 'failed', reason = p_reason, fence = fence + 1,
      lease_until = NULL WHERE run_id = p_run AND state NOT IN ('complete','quarantined','failed');
    GET DIAGNOSTICS affected = ROW_COUNT;
    WITH spent AS (UPDATE app.canonical_work w SET status='process_loss',actual_bytes=w.reserved_bytes
      FROM app.ingestion_chunk c WHERE c.id=w.chunk_id AND c.run_id=p_run
      AND w.status='reserved' RETURNING w.reserved_bytes)
    UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+
      coalesce((SELECT sum(reserved_bytes) FROM spent),0) WHERE id=p_run;
    UPDATE app.ingestion_attempt a SET disposition='interrupted',finished_at=clock_timestamp(),
      error_category=p_reason FROM app.ingestion_chunk c
      WHERE c.id=a.chunk_id AND c.run_id=p_run AND a.disposition IS NULL;
    UPDATE app.publication_intent i SET status = 'abandoned', disposition_reason = p_reason
      FROM app.ingestion_chunk c WHERE c.id = i.chunk_id AND c.run_id = p_run AND i.status = 'prepared';
    UPDATE app.profile_outcome o SET outcome = 'blocked_uncommitted',
      evidence = evidence || jsonb_build_object('blocking_reason',p_reason)
      FROM app.ingestion_chunk c WHERE c.id = o.chunk_id AND c.run_id = p_run
      AND c.state = 'failed' AND NOT o.committed
      AND o.outcome IN ('insert','newer','revision_only','noop','unordered_noop','stale_skip');
  END IF;
  SELECT count(*),count(*) FILTER(WHERE state = 'complete'),
    count(*) FILTER(WHERE state = 'failed'),count(*) FILTER(WHERE state = 'quarantined')
    INTO total,good,bad,quarantine FROM app.ingestion_chunk WHERE run_id = p_run AND leaf;
  IF (total = 0 AND p_reason IS NULL) OR total <> good + bad + quarantine
    THEN RAISE EXCEPTION 'unfinished_run'; END IF;
  -- Admission can lose its controller before a plan has been committed. Closing
  -- that run is a recorded failure, never successful empty coverage.
  result := CASE WHEN total = 0 THEN 'failed' WHEN good = total THEN 'complete'
                 WHEN good > 0 THEN 'partial'
                 WHEN quarantine > 0 AND bad = 0 THEN 'quarantined' ELSE 'failed' END;
  UPDATE app.ingestion_run SET state = result, closed = true,
    cancellation_affected = (p_reason = 'operator_cancelled' AND affected > 0) IS TRUE,
    termination_reason = CASE WHEN result = 'complete' AND p_reason = 'operator_cancelled'
      THEN 'no_effect_already_complete' ELSE p_reason END WHERE id = p_run;
  UPDATE app.ingestion_scope SET unfinished_run_id = NULL, lease_until = NULL,
    watermark = CASE WHEN r.scheduled AND result = 'complete' THEN r.requested_end ELSE watermark END
    WHERE unfinished_run_id = p_run;
  INSERT INTO app.ingestion_event(run_id,control_epoch,old_state,new_state,reason)
    VALUES(p_run,r.control_epoch,r.state,result,coalesce(p_reason,'run_reduction'));
  PERFORM app.capture_final_evidence(p_run);
  RETURN result;
END $body$;

CREATE FUNCTION app.reserve_http_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_attempt uuid,p_key text,p_role text,p_parameters jsonb) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE attempts integer; ordinal integer;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT count(*) + 1 INTO attempts FROM app.ingestion_attempt
    WHERE chunk_id = p_chunk AND logical_request_key = p_key;
  SELECT coalesce(max(attempt_number),0) + 1 INTO ordinal FROM app.ingestion_attempt
    WHERE chunk_id = p_chunk;
  IF attempts > 4 THEN RAISE EXCEPTION 'http_retry_exhausted'; END IF;
  UPDATE app.ingestion_run SET http_attempts = http_attempts + 1 WHERE id = p_run;
  INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
                                    role,request_parameters)
    VALUES(p_attempt,p_chunk,ordinal,p_key,attempts,p_role,p_parameters);
  RETURN attempts;
END $body$;

-- Restricted staging cleanup is allowed, never unrestricted target deletes.
CREATE FUNCTION app.clear_staging(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  DELETE FROM app.ingestion_staging WHERE run_id = p_run AND chunk_id = p_chunk AND fence = p_fence;
END $body$;

REVOKE ALL ON FUNCTION app.assert_authority(uuid,uuid,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.claim_chunk(uuid,uuid,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.adopt_controller(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.heartbeat(uuid,uuid,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.transition_chunk(uuid,uuid,bigint,bigint,text,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.finalize_run(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.reserve_http_attempt(uuid,uuid,bigint,bigint,uuid,text,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.clear_staging(uuid,uuid,bigint,bigint) FROM PUBLIC;
