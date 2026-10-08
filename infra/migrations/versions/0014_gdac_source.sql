-- GDAC NetCDF source population and relaxed source checks (stage1-v4, package G)
-- Additive: every Argovis rule is kept; gdac rows carry source 'gdac', mapping
-- 'gdac-core-v1', input kind/attempt origin 'gdac' and optional raw .nc objects.
-- Inline checks have generated names, so they are found by definition and counted.
DO $migration$
DECLARE
  r_table record;
  r_check record;
  dropped integer;
BEGIN
  FOR r_table IN SELECT * FROM (VALUES
    ('app.argo_float'::regclass,'%argovis%',1),
    ('app.argo_profile'::regclass,'%argovis%',2),
    ('app.ingestion_scope'::regclass,'%argovis%',1),
    ('app.raw_manifest'::regclass,'%raw/sha256/%',2),
    ('app.ingestion_attempt'::regclass,'%captured%',1),
    ('app.ingestion_input'::regclass,'%captured%',1)
  ) AS t(tbl,pattern,expected) LOOP
    dropped := 0;
    FOR r_check IN SELECT c.conname FROM pg_constraint c
      WHERE c.conrelid=r_table.tbl AND c.contype='c' AND pg_get_constraintdef(c.oid) LIKE r_table.pattern
    LOOP
      EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',r_table.tbl,r_check.conname);
      dropped := dropped+1;
    END LOOP;
    IF dropped<>r_table.expected THEN
      RAISE EXCEPTION 'unexpected_check_constraints % %',r_table.tbl,dropped;
    END IF;
  END LOOP;
END $migration$;

ALTER TABLE app.argo_float
  ADD CONSTRAINT argo_float_source_check CHECK (source IN ('argovis','gdac'));
ALTER TABLE app.argo_profile
  ADD CONSTRAINT argo_profile_source_check CHECK (source IN ('argovis','gdac')),
  ADD CONSTRAINT argo_profile_mapping_version_check CHECK (
    (source = 'argovis' AND mapping_version = 'argovis-core-v1')
    OR (source = 'gdac' AND mapping_version = 'gdac-core-v1'));
ALTER TABLE app.ingestion_scope
  ADD CONSTRAINT ingestion_scope_source_check CHECK (source IN ('argovis','gdac'));
ALTER TABLE app.raw_manifest
  ADD CONSTRAINT raw_manifest_object_key_check
    CHECK (object_key ~ '^raw/sha256/[0-9a-f]{64}\.(json|nc)$'),
  ADD CONSTRAINT raw_manifest_object_key_digest_check CHECK (
    object_key = 'raw/sha256/' || sha256 || '.json'
    OR object_key = 'raw/sha256/' || sha256 || '.nc');
ALTER TABLE app.ingestion_attempt
  ADD CONSTRAINT ingestion_attempt_origin_check
    CHECK (origin IN ('http','captured','replay','cache','gdac'));
ALTER TABLE app.ingestion_input
  ADD CONSTRAINT ingestion_input_kind_check CHECK (kind IN ('live','captured','replay','gdac'));

-- Same body as 0012 (origin 'cache' kept) plus the recorded origin 'gdac' (derived NetCDF landings).
CREATE OR REPLACE FUNCTION app.reserve_recorded_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_attempt uuid,p_key text,p_role text,p_parameters jsonb,p_origin text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE ordinal integer; attempts integer;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_origin NOT IN ('captured','replay','cache','gdac') THEN RAISE EXCEPTION 'invalid_recorded_origin'; END IF;
  SELECT coalesce(max(attempt_number),0)+1 INTO ordinal FROM app.ingestion_attempt WHERE chunk_id=p_chunk;
  SELECT count(*)+1 INTO attempts FROM app.ingestion_attempt WHERE chunk_id=p_chunk AND logical_request_key=p_key;
  IF attempts>4 THEN RAISE EXCEPTION 'landing_retry_exhausted'; END IF;
  INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
    role,request_parameters,origin) VALUES(p_attempt,p_chunk,ordinal,p_key,attempts,p_role,p_parameters,p_origin);
END $body$;

-- Logical partition key of the separate GDAC population (mirror of app.owner_slot, 0004).
CREATE FUNCTION app.gdac_owner_slot(p_time timestamptz,p_longitude numeric,p_latitude numeric)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, app AS $body$
SELECT 'gdac/core/' || to_char(p_time AT TIME ZONE 'UTC','YYYY-MM') || '/' ||
  (CASE WHEN p_longitude = 120 THEN 110 ELSE floor((p_longitude-20)/10)*10+20 END)::integer || ':' ||
  (CASE WHEN p_latitude = 30 THEN 20 ELSE floor((p_latitude+60)/10)*10-60 END)::integer ||
  '/indian-ocean-v1/gdac-core-v1/scientific-json-v2';
$body$;
REVOKE ALL ON FUNCTION app.gdac_owner_slot(timestamptz,numeric,numeric) FROM PUBLIC;
