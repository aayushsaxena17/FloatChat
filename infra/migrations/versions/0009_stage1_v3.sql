-- stage1-v3 (ADR-0040..ADR-0042). Additive and versioned; earlier rows keep
-- their recorded plan versions, manifests, outcomes and frozen evidence.

-- ADR-0041 S1-RESOURCE-3: run canonical-work cap 10 GiB -> 40 GiB, sized from the
-- measured Jan-Mar 2025 census. Profile/chunk caps and the 16 MiB reservation stay.
ALTER TABLE app.ingestion_run DROP CONSTRAINT ingestion_run_canonical_bytes_check;
ALTER TABLE app.ingestion_run ADD CONSTRAINT ingestion_run_canonical_bytes_check
  CHECK (canonical_bytes BETWEEN 0 AND 42949672960);

CREATE OR REPLACE FUNCTION app.reserve_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,
  p_fence bigint,p_work uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE used bigint; reserved bigint;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT canonical_bytes INTO used FROM app.ingestion_run WHERE id=p_run;
  SELECT coalesce(sum(w.reserved_bytes),0) INTO reserved FROM app.canonical_work w
    JOIN app.ingestion_chunk c ON c.id=w.chunk_id WHERE c.run_id=p_run AND w.status='reserved';
  IF used+reserved+16777216>42949672960 THEN
    RAISE EXCEPTION 'canonical_output_limit' USING DETAIL = jsonb_build_object(
      'scope','run','operation','reservation','limit_bytes',42949672960,
      'used_bytes',used+reserved,'requested_bytes',16777216)::text;
  END IF;
  INSERT INTO app.canonical_work VALUES(p_work,p_chunk,p_fence,'reserved',16777216,NULL);
END $body$;

-- ADR-0041 plan v2: initial slices are whole UTC calendar months (clipped to the
-- request), so each month/tile slot is published once per run unless split.
CREATE OR REPLACE FUNCTION app.persist_plan(p_run uuid,p_epoch bigint,p_plan jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; item jsonb; n integer;
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) THEN RETURN; END IF;
  n := jsonb_array_length(p_plan);
  IF n NOT BETWEEN 1 AND 16384 THEN RAISE EXCEPTION 'chunk_count_limit'; END IF;
  IF EXISTS (
    WITH RECURSIVE slices(first,last) AS (
      SELECT r.requested_start,least(r.requested_end,
        ((date_trunc('month',r.requested_start AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      UNION ALL
      SELECT last,least(r.requested_end,
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

CREATE OR REPLACE FUNCTION app.persist_replay_plan(p_run uuid,p_epoch bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE r app.ingestion_run; previous app.ingestion_run; predecessor uuid; n integer;
BEGIN
  PERFORM app.assert_run(p_run,p_epoch);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  SELECT (descriptor->>'predecessor_run')::uuid INTO predecessor FROM app.ingestion_input
    WHERE run_id=p_run AND kind='replay';
  SELECT * INTO previous FROM app.ingestion_run WHERE id=predecessor FOR SHARE;
  IF previous.id IS NULL OR previous.id=r.id OR NOT previous.closed OR previous.state<>'complete'
    OR previous.environment_id<>r.environment_id OR previous.mode<>r.mode
    OR previous.requested_start<>r.requested_start OR previous.requested_end<>r.requested_end
    OR previous.geometry_sha256<>r.geometry_sha256 OR previous.policy_versions<>r.policy_versions
    THEN RAISE EXCEPTION 'invalid_replay_predecessor'; END IF;
  IF EXISTS(SELECT 1 FROM app.ingestion_chunk WHERE run_id=p_run) THEN
    IF EXISTS(SELECT 1 FROM app.ingestion_chunk c WHERE c.run_id=p_run AND NOT EXISTS(
      SELECT 1 FROM app.replay_chunk_source b WHERE b.chunk_id=c.id AND b.run_id=p_run))
      THEN RAISE EXCEPTION 'invalid_replay_plan'; END IF;
    RETURN;
  END IF;
  SELECT count(*) INTO n FROM app.ingestion_chunk WHERE run_id=predecessor;
  IF n NOT BETWEEN 1 AND 16384 OR EXISTS(
    SELECT 1 FROM app.ingestion_chunk c WHERE c.run_id=predecessor AND
      (c.plan_version<>'indian-ocean-plan-v2' OR
       (c.leaf AND (c.state<>'complete' OR EXISTS(SELECT 1 FROM app.ingestion_chunk k WHERE k.parent_id=c.id))) OR
       (NOT c.leaf AND (c.state<>'failed' OR c.reason<>'split_replaced' OR
         (SELECT count(*) FROM app.ingestion_chunk k WHERE k.parent_id=c.id)<>2)) OR
       (c.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.ingestion_chunk p
         WHERE p.id=c.parent_id AND p.run_id=predecessor)))
  ) THEN RAISE EXCEPTION 'invalid_replay_plan'; END IF;
  IF EXISTS(
    WITH RECURSIVE slices(first,last) AS (
      SELECT r.requested_start,least(r.requested_end,
        ((date_trunc('month',r.requested_start AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      UNION ALL
      SELECT last,least(r.requested_end,
        ((date_trunc('month',last AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      FROM slices WHERE last<r.requested_end
    ), expected AS (
      SELECT first,last,west,south,10 AS width,10 AS height FROM slices
      CROSS JOIN generate_series(20,110,10) w(west) CROSS JOIN generate_series(-60,20,10) s(south)
    ), supplied AS (
      SELECT requested_start AS first,requested_end AS last,(tile->>'west')::integer AS west,
        (tile->>'south')::integer AS south,(tile->>'width')::integer AS width,
        (tile->>'height')::integer AS height FROM app.ingestion_chunk
        WHERE run_id=predecessor AND parent_id IS NULL
    ) SELECT 1 FROM ((SELECT * FROM expected EXCEPT ALL SELECT * FROM supplied)
      UNION ALL (SELECT * FROM supplied EXCEPT ALL SELECT * FROM expected)) differences
  ) THEN RAISE EXCEPTION 'invalid_replay_plan'; END IF;
  IF (WITH RECURSIVE tree(id) AS (
    SELECT id FROM app.ingestion_chunk WHERE run_id=predecessor AND parent_id IS NULL
    UNION SELECT c.id FROM app.ingestion_chunk c JOIN tree t ON c.parent_id=t.id
      WHERE c.run_id=predecessor
  ) SELECT count(*) FROM tree)<>n THEN RAISE EXCEPTION 'invalid_replay_plan'; END IF;
  INSERT INTO app.replay_chunk_source(chunk_id,run_id,predecessor_chunk_id)
    SELECT gen_random_uuid(),p_run,id FROM app.ingestion_chunk WHERE run_id=predecessor;
  INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,
    tile,plan_version,parent_id,leaf,state,reason)
    SELECT b.chunk_id,p_run,c.logical_chunk_key,c.requested_start,c.requested_end,c.tile,
      c.plan_version,parent.chunk_id,c.leaf,CASE WHEN c.leaf THEN 'planned' ELSE 'failed' END,
      CASE WHEN c.leaf THEN NULL ELSE 'split_replaced' END
    FROM app.replay_chunk_source b JOIN app.ingestion_chunk c ON c.id=b.predecessor_chunk_id
    LEFT JOIN app.replay_chunk_source parent ON parent.run_id=p_run AND parent.predecessor_chunk_id=c.parent_id
    WHERE b.run_id=p_run;
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason,evidence)
    VALUES(p_run,p_epoch,'captured_replay_plan_persisted',
      jsonb_build_object('predecessor_run',predecessor,'chunks',n,'plan_version','captured-replay-v1'));
END $body$;

-- ADR-0040 S1-SOURCE-2: a verified raw landing records its HTTP status. Only 200
-- or the validated empty-delivery 404 receipt can be verified raw evidence.
ALTER TABLE app.raw_manifest ADD COLUMN http_status integer NOT NULL DEFAULT 200
  CHECK (http_status IN (200,404));

CREATE OR REPLACE FUNCTION app.finish_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_attempt uuid,p_disposition text,p_status integer,p_error text,p_manifest jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF NOT EXISTS(SELECT 1 FROM app.ingestion_attempt WHERE id=p_attempt AND chunk_id=p_chunk
      AND disposition IS NULL) THEN RAISE EXCEPTION 'attempt_already_final'; END IF;
  IF p_disposition='verified_raw' THEN
    IF p_status IS NULL OR p_status NOT IN (200,404) THEN
      RAISE EXCEPTION 'invalid_verified_status'; END IF;
    INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,retrieved_at,
      versions,sanitization,application_commit,http_status)
    VALUES((p_manifest->>'id')::uuid,p_run,p_chunk,p_attempt,p_manifest->>'key',p_manifest->>'sha256',
      (p_manifest->>'bytes')::bigint,(p_manifest->>'retrieved_at')::timestamptz,p_manifest->'versions',
      p_manifest->'sanitization',p_manifest->>'application_commit',p_status);
  ELSIF p_manifest IS NOT NULL THEN RAISE EXCEPTION 'unexpected_raw_manifest'; END IF;
  UPDATE app.ingestion_attempt SET disposition=p_disposition,finished_at=clock_timestamp(),
    http_status=p_status,error_category=p_error WHERE id=p_attempt;
END $body$;

-- ADR-0040 S1-SOURCE-2: whole-profile source-loss exclusion ledger outcome.
ALTER TABLE app.profile_outcome DROP CONSTRAINT profile_outcome_outcome_check;
ALTER TABLE app.profile_outcome ADD CONSTRAINT profile_outcome_outcome_check
  CHECK (outcome IN ('outside_time','outside_region','outside_core',
    'overlap_duplicate','identical_duplicate','structurally_quarantined','insert','newer',
    'revision_only','noop','unordered_noop','stale_skip','revision_conflict',
    'blocked_by_chunk_quarantine','blocked_uncommitted','excluded_source_loss'));
