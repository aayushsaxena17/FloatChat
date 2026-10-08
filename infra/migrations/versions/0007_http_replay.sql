ALTER TABLE app.ingestion_attempt DROP CONSTRAINT ingestion_attempt_disposition_check;
ALTER TABLE app.ingestion_attempt ADD CONSTRAINT ingestion_attempt_disposition_check
  CHECK(disposition IN ('verified_raw','http_failure','transport_failure','size_limit','interrupted'));

CREATE TABLE app.replay_chunk_source (
  chunk_id uuid PRIMARY KEY REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  predecessor_chunk_id uuid NOT NULL REFERENCES app.ingestion_chunk(id) ON DELETE RESTRICT,
  UNIQUE(run_id,predecessor_chunk_id)
);
REVOKE ALL ON app.replay_chunk_source FROM PUBLIC,floatchat_app;
GRANT SELECT ON app.replay_chunk_source TO floatchat_ingestor;

CREATE FUNCTION app.persist_replay_plan(p_run uuid,p_epoch bigint) RETURNS void
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
      (c.plan_version<>'indian-ocean-plan-v1' OR
       (c.leaf AND (c.state<>'complete' OR EXISTS(SELECT 1 FROM app.ingestion_chunk k WHERE k.parent_id=c.id))) OR
       (NOT c.leaf AND (c.state<>'failed' OR c.reason<>'split_replaced' OR
         (SELECT count(*) FROM app.ingestion_chunk k WHERE k.parent_id=c.id)<>2)) OR
       (c.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.ingestion_chunk p
         WHERE p.id=c.parent_id AND p.run_id=predecessor)))
  ) THEN RAISE EXCEPTION 'invalid_replay_plan'; END IF;
  -- The roots were validated by persist_plan and every split by split_chunk.
  -- Recheck full root coverage here; component-only seeded plans are ineligible.
  IF EXISTS(
    WITH RECURSIVE slices(first,last) AS (
      SELECT r.requested_start,least(r.requested_end,r.requested_start+interval '7 days',
        ((date_trunc('month',r.requested_start AT TIME ZONE 'UTC')+interval '1 month') AT TIME ZONE 'UTC'))
      UNION ALL
      SELECT last,least(r.requested_end,last+interval '7 days',
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
REVOKE ALL ON FUNCTION app.persist_replay_plan(uuid,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.persist_replay_plan(uuid,bigint) TO floatchat_ingestor;
