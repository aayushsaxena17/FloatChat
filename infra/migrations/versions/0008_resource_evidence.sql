-- Diagnostic-only replacement. Same authority, locks, counters, limits and
-- canonical_output_limit category; no ingestion/scientific rows are changed.
CREATE OR REPLACE FUNCTION app.reserve_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,
  p_fence bigint,p_work uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE used bigint; reserved bigint;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT canonical_bytes INTO used FROM app.ingestion_run WHERE id=p_run;
  SELECT coalesce(sum(w.reserved_bytes),0) INTO reserved FROM app.canonical_work w
    JOIN app.ingestion_chunk c ON c.id=w.chunk_id WHERE c.run_id=p_run AND w.status='reserved';
  IF used+reserved+16777216>10737418240 THEN
    RAISE EXCEPTION 'canonical_output_limit' USING DETAIL = jsonb_build_object(
      'scope','run','operation','reservation','limit_bytes',10737418240,
      'used_bytes',used+reserved,'requested_bytes',16777216)::text;
  END IF;
  INSERT INTO app.canonical_work VALUES(p_work,p_chunk,p_fence,'reserved',16777216,NULL);
END $body$;

CREATE FUNCTION app.safe_resource_limit(p_value jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,app AS $body$
DECLARE key text; amount text;
BEGIN
  IF jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN RETURN NULL; END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(p_value))<>5 OR
     NOT (p_value ?& ARRAY['scope','operation','limit_bytes','used_bytes','requested_bytes']) OR
     p_value->>'scope' NOT IN ('number','profile','chunk','run') OR
     p_value->>'operation' NOT IN ('normalization','encoding','reservation','accounting','readback')
    THEN RETURN NULL; END IF;
  IF jsonb_typeof(p_value->'scope') IS DISTINCT FROM 'string' OR
     jsonb_typeof(p_value->'operation') IS DISTINCT FROM 'string' THEN RETURN NULL; END IF;
  FOREACH key IN ARRAY ARRAY['limit_bytes','used_bytes','requested_bytes'] LOOP
    amount := p_value->>key;
    IF jsonb_typeof(p_value->key) IS DISTINCT FROM 'number' OR
       amount !~ '^[0-9]{1,19}$' THEN RETURN NULL; END IF;
    IF amount::numeric>9223372036854775807 THEN RETURN NULL; END IF;
  END LOOP;
  RETURN p_value;
END $body$;

CREATE FUNCTION app.resource_limit_snapshot(p_run uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
  SELECT coalesce(jsonb_agg(jsonb_build_object('chunk_id',t.chunk_id,
    'occurred_at',t.occurred_at,'resource_limit',app.safe_resource_limit(t.resource))
    ORDER BY t.sequence),'[]'::jsonb)
  FROM (SELECT sequence,chunk_id,occurred_at,evidence->'resource_limit' AS resource
    FROM app.ingestion_event WHERE run_id=p_run AND reason='canonical_output_limit'
    ORDER BY sequence LIMIT 16384) t;
$body$;

CREATE OR REPLACE FUNCTION app.capture_final_evidence(p_run uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM app.ingestion_run WHERE id=p_run AND closed)
    THEN RAISE EXCEPTION 'unfinished_run'; END IF;
  INSERT INTO app.run_final_evidence(run_id,evidence) VALUES(p_run,jsonb_build_object(
    'science',app.scientific_snapshot(),'reconciliation',app.reconciliation_snapshot(p_run),
    'report_metrics',app.report_metrics_snapshot(p_run)||jsonb_build_object(
      'resource_limits',app.resource_limit_snapshot(p_run)),
    'active_generation_ids',(SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb)
      FROM app.committed_active_partitions))) ON CONFLICT DO NOTHING;
END $body$;

REVOKE ALL ON FUNCTION app.safe_resource_limit(jsonb),app.resource_limit_snapshot(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.resource_limit_snapshot(uuid) TO floatchat_ingestor;

CREATE OR REPLACE FUNCTION app.finish_canonical(p_run uuid,p_chunk uuid,p_epoch bigint,
  p_fence bigint,p_work uuid,p_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_bytes NOT BETWEEN 0 AND 16777216 THEN
    RAISE EXCEPTION 'canonical_output_limit' USING DETAIL = jsonb_build_object(
      'scope','profile','operation','accounting','limit_bytes',16777216,
      'used_bytes',0,'requested_bytes',greatest(p_bytes,0))::text;
  END IF;
  UPDATE app.canonical_work SET status='complete',actual_bytes=p_bytes WHERE id=p_work
    AND chunk_id=p_chunk AND fence=p_fence AND status='reserved';
  IF NOT FOUND THEN RAISE EXCEPTION 'canonical_reservation_final'; END IF;
  UPDATE app.ingestion_run SET canonical_bytes=canonical_bytes+p_bytes WHERE id=p_run;
END $body$;
