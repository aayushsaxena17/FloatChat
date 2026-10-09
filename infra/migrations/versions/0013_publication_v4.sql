-- stage1-v4 publication (package F): per-chunk parts, slim level staging, jsonb-free commit.
-- Contract section 7 clauses touched: "a generation contains the full accepted profile/level
-- set" becomes "the catalogue state of a slot is its membership manifest plus the active parts
-- and at most one snapshot that hold those rows"; steps 3-5 (candidate objects) publish only
-- the own profiles of the chunk; step 7 keeps one fenced transaction. compact_slot merges later.
-- Science rules, hashes, canonical bytes, error categories and fencing are unchanged.

-- Level rows travel by binary COPY into this table; commit_publication inserts them
-- set-based. UNLOGGED: purely transient, rebuilt by every staging call, never evidence.
CREATE UNLOGGED TABLE app.measurement_staging (
  run_id uuid NOT NULL,
  chunk_id uuid NOT NULL,
  fence bigint NOT NULL,
  occurrence_index integer NOT NULL CHECK (occurrence_index >= 0 AND occurrence_index < 2000),
  level_index integer NOT NULL CHECK (level_index >= 0 AND level_index < 10000),
  pressure app.finite_float8,
  pressure_adjusted app.finite_float8,
  temperature app.finite_float8,
  temperature_adjusted app.finite_float8,
  salinity app.finite_float8,
  salinity_adjusted app.finite_float8,
  pressure_error app.finite_float8,
  pressure_original_error app.finite_float8,
  temperature_error app.finite_float8,
  temperature_original_error app.finite_float8,
  salinity_error app.finite_float8,
  salinity_original_error app.finite_float8,
  pressure_qc app.qc_code,
  pressure_adjusted_qc app.qc_code,
  temperature_qc app.qc_code,
  temperature_adjusted_qc app.qc_code,
  salinity_qc app.qc_code,
  salinity_adjusted_qc app.qc_code,
  pressure_unit text,
  temperature_unit text,
  salinity_unit text,
  pressure_data_mode text,
  temperature_data_mode text,
  salinity_data_mode text,
  pressure_unit_source text,
  temperature_unit_source text,
  salinity_unit_source text,
  pressure_qc_source text,
  pressure_adjusted_qc_source text,
  temperature_qc_source text,
  temperature_adjusted_qc_source text,
  salinity_qc_source text,
  salinity_adjusted_qc_source text,
  pressure_flags jsonb NOT NULL,
  temperature_flags jsonb NOT NULL,
  salinity_flags jsonb NOT NULL,
  PRIMARY KEY(run_id,chunk_id,fence,occurrence_index,level_index)
);

-- One authority check per COPY statement, not per level row (60,000 rows per chunk).
CREATE FUNCTION app.check_measurement_staging_authority() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE staged record; epoch bigint;
BEGIN
  FOR staged IN SELECT DISTINCT n.run_id,n.chunk_id,n.fence FROM new_rows n LOOP
    SELECT k.control_epoch INTO STRICT epoch FROM app.ingestion_chunk k
      WHERE k.id=staged.chunk_id AND k.run_id=staged.run_id;
    PERFORM app.assert_authority(staged.run_id,staged.chunk_id,epoch,staged.fence);
  END LOOP;
  RETURN NULL;
END $body$;
CREATE TRIGGER measurement_staging_authority AFTER INSERT ON app.measurement_staging
REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT
EXECUTE FUNCTION app.check_measurement_staging_authority();

-- Restricted staging cleanup now covers the level rows too, including dead fences.
CREATE OR REPLACE FUNCTION app.clear_staging(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  DELETE FROM app.ingestion_staging WHERE run_id = p_run AND chunk_id = p_chunk AND fence = p_fence;
  DELETE FROM app.measurement_staging
    WHERE run_id = p_run AND chunk_id = p_chunk AND fence <= p_fence;
END $body$;

DO $body$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'floatchat_app') THEN
    REVOKE ALL ON app.measurement_staging FROM floatchat_app;
  END IF;
END $body$;
REVOKE ALL ON FUNCTION app.check_measurement_staging_authority() FROM PUBLIC;
GRANT SELECT,INSERT ON app.measurement_staging TO floatchat_ingestor;

-- The canonical level JSON lives only in scientific_content of the profile and in
-- Parquet; core_measurement stores typed values. The per-level check against the
-- canonical becomes app.audit_levels (sampled, callable separately).
ALTER TABLE app.core_measurement DROP COLUMN canonical_level;
DROP FUNCTION app.canonical_level_values(jsonb,jsonb);

-- Catalogue objects: a slot has several active parts (one per accepted commit) and at
-- most one snapshot (written by compact_slot). generation stays unique per slot but is
-- allocated as max+1, because a snapshot adds a generation without a membership change.
ALTER TABLE app.dataset_partition
  ADD COLUMN kind text NOT NULL DEFAULT 'snapshot' CHECK (kind IN ('part','snapshot')),
  ADD COLUMN part_ordinal integer;
DROP INDEX app.one_active_generation;
CREATE INDEX dataset_partition_active ON app.dataset_partition(environment_id,logical_key)
  WHERE status = 'active';
CREATE UNIQUE INDEX one_active_snapshot ON app.dataset_partition(environment_id,logical_key)
  WHERE status = 'active' AND kind = 'snapshot';

-- Same selection predicate; every active object of a slot carries the current slot
-- version (commit and compact_slot re-stamp them), so a stale object still never selects.
CREATE OR REPLACE VIEW app.committed_active_partitions AS
SELECT p.* FROM app.dataset_partition p
JOIN app.publication_intent i ON i.id = p.intent_id AND i.status = 'committed'
JOIN app.ingestion_chunk c ON c.id = p.chunk_id AND c.state = 'complete'
JOIN app.logical_partition_slot s ON s.environment_id = p.environment_id
  AND s.logical_key = p.logical_key AND s.slot_version = p.slot_version
WHERE p.status = 'active';

-- True when the incrementally maintained manifest equals the stored population of the slot.
CREATE FUNCTION app.audit_slot_manifest(p_environment uuid,p_logical_key text) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
  SELECT coalesce(s.membership_manifest IS NOT DISTINCT FROM (
    SELECT coalesce(jsonb_agg(jsonb_build_object('profile_id',p.id,'hash',p.content_hash,
      'levels',p.level_count) ORDER BY p.id),'[]'::jsonb) FROM app.argo_profile p
    WHERE app.owner_slot(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,
      (p.scientific_content->'latitude'->>'exact')::numeric)=p_logical_key),false)
  FROM app.logical_partition_slot s
  WHERE s.environment_id=p_environment AND s.logical_key=p_logical_key;
$body$;

-- Sampled replacement for the per-level content check: compares the stored typed rows of
-- up to p_sample profiles committed by p_chunk with their canonical levels, using the
-- same field comparison as before (app.level_mismatch). Raises the old category.
CREATE FUNCTION app.audit_levels(p_chunk uuid,p_sample integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE profiles_checked integer; levels_checked bigint; levels_expected bigint; mismatches bigint;
BEGIN
  IF p_sample IS NULL OR p_sample NOT BETWEEN 1 AND 2000 THEN
    RAISE EXCEPTION 'invalid_audit_sample'; END IF;
  WITH chosen AS (
    SELECT p.id,p.observation_month,p.level_count,p.scientific_content FROM app.argo_profile p
    WHERE p.last_chunk_id=p_chunk ORDER BY md5(p.id::text) LIMIT p_sample),
  checked AS (
    SELECT sp.id,app.level_mismatch(to_jsonb(m)-'profile_id'-'observation_month',
        k.canonical,m.level_index) AS bad
    FROM chosen sp
    JOIN app.core_measurement m ON m.profile_id=sp.id AND m.observation_month=sp.observation_month
    JOIN LATERAL jsonb_array_elements(sp.scientific_content->'levels')
      WITH ORDINALITY AS k(canonical,ord) ON k.ord-1=m.level_index)
  SELECT count(DISTINCT checked.id),count(*),count(*) FILTER (WHERE checked.bad),
         (SELECT coalesce(sum(chosen.level_count),0) FROM chosen)
    INTO profiles_checked,levels_checked,mismatches,levels_expected FROM checked;
  IF mismatches>0 OR levels_checked<>levels_expected THEN
    RAISE EXCEPTION 'measurement_content_mismatch'; END IF;
  RETURN jsonb_build_object('profiles',profiles_checked,'levels',levels_checked);
END $body$;

-- commit_publication v4: identical identity, revision, eligibility, raw-provenance, outcome,
-- receipt, fence and deadline checks and categories. Changes: levels come set-based from
-- app.measurement_staging (no per-level jsonb); the slot manifest is edited incrementally and
-- verified against the stored population; every accepted generation is a part and nothing is
-- superseded except a slot whose manifest becomes empty.
CREATE OR REPLACE FUNCTION app.commit_publication(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                       p_intent uuid,p_generations jsonb,p_receipts jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app, public AS $body$
DECLARE r app.ingestion_run; c app.ingestion_chunk; i app.publication_intent;
        candidate jsonb; science jsonb; generation jsonb; receipt jsonb;
        stored app.argo_profile; matched app.argo_profile;
        float_uuid uuid; profile_uuid uuid; stable_id text; platform text;
        obs timestamptz; identity_obs timestamptz; incoming_month date; old_month date;
        longitude numeric; latitude numeric; slot text; old_slot text; result text;
        actual_hash text; n integer; ordinal integer; changed text[] := ARRAY[]::text[];
        next_version bigint; base_version bigint; count_staged integer;
        staged_levels bigint; accepted_new integer := 0; accepted_level_total bigint := 0;
        member_profiles integer; member_levels bigint;
        selection_profiles integer;
        bases_changed boolean := false;
        inserted_levels bigint; accepted_ids uuid[] := ARRAY[]::uuid[];
        accepted_slots text[] := ARRAY[]::text[]; accepted_old text[] := ARRAY[]::text[];
        new_entries jsonb; removed_ids uuid[]; manifest jsonb; manifest_size integer;
        next_generation bigint; need_selection boolean;
BEGIN
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id=p_chunk AND run_id=p_run;
  IF c.state='complete' THEN RETURN; END IF; -- Lost acknowledgement is already complete.
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id=p_chunk AND run_id=p_run;
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  SELECT * INTO STRICT i FROM app.publication_intent WHERE id=p_intent AND chunk_id=p_chunk FOR UPDATE;
  IF c.state<>'publishing' OR i.status<>'prepared' OR i.fence<>p_fence OR i.control_epoch<>p_epoch
    THEN RAISE EXCEPTION 'publication_fenced'; END IF;
  IF jsonb_typeof(p_generations)<>'array' OR jsonb_typeof(p_receipts)<>'array'
    THEN RAISE EXCEPTION 'invalid_publication_evidence'; END IF;
  SELECT count(*) INTO count_staged FROM app.ingestion_staging
    WHERE run_id=p_run AND chunk_id=p_chunk AND fence=p_fence;
  IF count_staged > 2000 THEN RAISE EXCEPTION 'profile_count_limit'; END IF;
  SELECT coalesce(sum((s.candidate->>'level_count')::bigint),0) INTO staged_levels
    FROM app.ingestion_staging s WHERE s.run_id=p_run AND s.chunk_id=p_chunk AND s.fence=p_fence;
  IF staged_levels>2000000 THEN RAISE EXCEPTION 'measurement_count_limit'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_generations) g
      GROUP BY g->>'logical_key' HAVING count(*)>1)
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_receipts) g
      GROUP BY g->>'logical_key' HAVING count(*)>1)
    THEN RAISE EXCEPTION 'duplicate_publication_slot'; END IF;
  -- Every slot this transaction writes or receipts is locked in one deterministic order, so
  -- concurrent chunk commits cannot deadlock on slots reached through different loops.
  PERFORM sl.slot_version FROM app.logical_partition_slot sl
    WHERE sl.environment_id=r.environment_id AND sl.logical_key IN (
      SELECT g->>'logical_key' FROM jsonb_array_elements(p_generations) g
      UNION SELECT g->>'logical_key' FROM jsonb_array_elements(p_receipts) g)
    ORDER BY sl.logical_key FOR UPDATE;
  -- All proposed slots, including empty ownership-correction sources, are locked
  -- in deterministic order before any scientific write.
  FOR generation IN SELECT value FROM jsonb_array_elements(p_generations)
                    ORDER BY value->>'logical_key' LOOP
    SELECT slot_version INTO STRICT base_version FROM app.logical_partition_slot
      WHERE environment_id=r.environment_id AND logical_key=generation->>'logical_key' FOR UPDATE;
    IF base_version<>(generation->>'base_version')::bigint
      OR i.expected_bases->>(generation->>'logical_key') IS NULL
      OR (i.expected_bases->>(generation->>'logical_key'))::bigint<>base_version
      THEN bases_changed := true; END IF;
  END LOOP;
  FOR candidate,ordinal IN SELECT s.candidate,s.occurrence_index FROM app.ingestion_staging s
    WHERE s.run_id=p_run AND s.chunk_id=p_chunk AND s.fence=p_fence
    ORDER BY s.candidate->>'platform',s.candidate->>'source_profile_id',s.occurrence_index LOOP
    science := (candidate->>'canonical')::jsonb;
    actual_hash := encode(sha256(convert_to(candidate->>'canonical','UTF8')),'hex');
    IF actual_hash IS DISTINCT FROM candidate->>'content_hash'
      OR science->>'hash_version' IS DISTINCT FROM 'scientific-json-v2'
      OR science->>'mapping_version' IS DISTINCT FROM 'argovis-core-v1'
      THEN RAISE EXCEPTION 'scientific_hash_mismatch'; END IF;
    platform := candidate->>'platform'; stable_id := candidate->>'source_profile_id';
    obs := (candidate->>'observed_at')::timestamptz;
    identity_obs := (candidate->>'identity_observed_at')::timestamptz;
    incoming_month := date_trunc('month',obs AT TIME ZONE 'UTC')::date;
    longitude := (science->'longitude'->>'exact')::numeric;
    latitude := (science->'latitude'->>'exact')::numeric;
    slot := app.owner_slot(obs,longitude,latitude);
    IF obs < (((r.run_reference_time_utc AT TIME ZONE 'UTC') - interval '12 months') AT TIME ZONE 'UTC')
       OR obs>=r.run_reference_time_utc OR obs<c.requested_start OR obs>=c.requested_end
       OR longitude IS NULL OR latitude IS NULL OR longitude NOT BETWEEN 20 AND 120
       OR latitude NOT BETWEEN -60 AND 30 THEN RAISE EXCEPTION 'candidate_outside_eligibility'; END IF;
    IF science->>'platform' IS DISTINCT FROM platform
       OR (science->>'observed_at')::timestamptz IS DISTINCT FROM obs
       OR science->>'direction' IS DISTINCT FROM candidate->>'direction'
       OR science->'cycle' IS DISTINCT FROM candidate->'cycle' THEN RAISE EXCEPTION 'candidate_content_mismatch'; END IF;
    n := (candidate->>'level_count')::integer;
    IF n IS NULL OR n NOT BETWEEN 1 AND 10000 OR jsonb_array_length(science->'levels')<>n
      THEN RAISE EXCEPTION 'invalid_level_count'; END IF;
    -- Context locks cover ID-less possible timestamp corrections as well as exact keys.
    PERFORM pg_advisory_xact_lock(hashtextextended('argovis/'||platform||'/'||
      coalesce(candidate->>'cycle','')||'/'||coalesce(candidate->>'direction','')||'/single',0));
    SELECT id INTO float_uuid FROM app.argo_float WHERE source='argovis' AND platform_number=platform;
    stored := NULL; matched := NULL; old_slot := NULL;
    IF stable_id IS NOT NULL THEN
      SELECT * INTO stored FROM app.argo_profile WHERE source='argovis' AND source_profile_id=stable_id FOR UPDATE;
    END IF;
    IF float_uuid IS NOT NULL AND candidate->>'cycle' IS NOT NULL AND candidate->>'direction' IN ('A','D') THEN
      SELECT * INTO matched FROM app.argo_profile WHERE source='argovis' AND float_id=float_uuid
        AND cycle_number=(candidate->>'cycle')::bigint AND direction=candidate->>'direction'
        AND identity_observed_at=identity_obs AND observation_segment='single' FOR UPDATE;
    END IF;
    IF stored.id IS NOT NULL AND matched.id IS NOT NULL AND stored.id<>matched.id
      THEN RAISE EXCEPTION 'identity_conflict'; END IF;
    IF stored.id IS NULL AND matched.id IS NOT NULL THEN stored := matched; END IF;
    IF stored.id IS NOT NULL THEN
      IF stored.float_id IS DISTINCT FROM float_uuid OR (stored.source_profile_id IS NOT NULL AND stable_id IS NOT NULL
         AND stored.source_profile_id<>stable_id)
         OR (stored.direction IN ('A','D') AND candidate->>'direction' IN ('A','D')
             AND stored.direction<>candidate->>'direction') THEN RAISE EXCEPTION 'identity_conflict'; END IF;
      profile_uuid := stored.id; old_month := stored.observation_month;
      old_slot := app.owner_slot(stored.observed_at,
        (stored.scientific_content->'longitude'->>'exact')::numeric,
        (stored.scientific_content->'latitude'->>'exact')::numeric);
    ELSE
      IF stable_id IS NULL AND EXISTS(SELECT 1 FROM app.argo_profile WHERE float_id=float_uuid
         AND cycle_number=(candidate->>'cycle')::bigint AND direction=candidate->>'direction'
         AND observation_segment='single' AND source_profile_id IS NULL)
         THEN RAISE EXCEPTION 'fallback_observation_time_correction'; END IF;
      profile_uuid := (candidate->>'proposed_profile_id')::uuid;
    END IF;
    result := app.revision_outcome(actual_hash,candidate->'revision',stored.content_hash,stored.source_revision);
    IF result='revision_conflict' THEN RAISE EXCEPTION 'revision_conflict'; END IF;
    IF result IN ('insert','newer') THEN
      PERFORM app.ensure_measurement_month(p_run,incoming_month);
      accepted_new := accepted_new + CASE WHEN result='insert' THEN 1 ELSE 0 END;
      accepted_level_total := accepted_level_total+n;
      IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_generations) g
                    WHERE g->>'logical_key'=slot)
         OR (stored.id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_generations) g
                    WHERE g->>'logical_key'=old_slot)) THEN RAISE EXCEPTION 'missing_affected_slot'; END IF;
      IF NOT EXISTS(SELECT 1 FROM app.raw_manifest m WHERE m.id=(candidate->>'raw_manifest_id')::uuid
         AND m.run_id=p_run AND m.chunk_id=p_chunk) THEN RAISE EXCEPTION 'raw_provenance_mismatch'; END IF;
      IF float_uuid IS NULL THEN
        INSERT INTO app.argo_float(id,source,platform_number) VALUES(gen_random_uuid(),'argovis',platform)
          ON CONFLICT(source,platform_number) DO NOTHING;
        SELECT id INTO STRICT float_uuid FROM app.argo_float WHERE source='argovis' AND platform_number=platform;
      END IF;
      IF stored.id IS NOT NULL THEN
        DELETE FROM app.core_measurement WHERE profile_id=stored.id AND observation_month=old_month;
        UPDATE app.argo_profile SET observed_at=obs,observation_month=incoming_month,
          position=ST_SetSRID(ST_MakePoint(longitude::float8,latitude::float8),4326),
          content_hash=actual_hash,scientific_content=science,source_revision=candidate->'revision',
          level_count=n,last_scientific_run_id=p_run,last_chunk_id=p_chunk,
          raw_manifest_id=(candidate->>'raw_manifest_id')::uuid,
          source_profile_id=coalesce(source_profile_id,stable_id) WHERE id=stored.id;
      ELSE
        INSERT INTO app.argo_profile(id,source,source_profile_id,float_id,cycle_number,direction,
          identity_observed_at,observation_segment,fallback_complete,observed_at,observation_month,
          position,content_hash,hash_version,mapping_version,level_count,scientific_content,source_revision,
          created_run_id,last_scientific_run_id,last_chunk_id,raw_manifest_id)
        VALUES(profile_uuid,'argovis',stable_id,float_uuid,(candidate->>'cycle')::bigint,candidate->>'direction',
          identity_obs,'single',candidate->>'cycle' IS NOT NULL AND candidate->>'direction' IN ('A','D'),
          obs,incoming_month,ST_SetSRID(ST_MakePoint(longitude::float8,latitude::float8),4326),
          actual_hash,'scientific-json-v2','argovis-core-v1',n,science,candidate->'revision',
          p_run,p_run,p_chunk,(candidate->>'raw_manifest_id')::uuid);
      END IF;
      -- Levels: staged by binary COPY, inserted set-based. The values are the typed
      -- fields of the same Profile whose canonical bytes were hashed above; app.audit_levels
      -- re-derives them from the canonical content on a sample.
      IF EXISTS(SELECT 1 FROM app.measurement_staging m WHERE m.run_id=p_run AND m.chunk_id=p_chunk
          AND m.fence=p_fence AND m.occurrence_index=ordinal
          AND (m.level_index<0 OR m.level_index>n-1))
        THEN RAISE EXCEPTION 'invalid_level_index'; END IF;
      INSERT INTO app.core_measurement(observation_month,profile_id,level_index,
        pressure,pressure_adjusted,temperature,temperature_adjusted,salinity,salinity_adjusted,
        pressure_error,pressure_original_error,temperature_error,temperature_original_error,salinity_error,salinity_original_error,
        pressure_qc,pressure_adjusted_qc,temperature_qc,temperature_adjusted_qc,salinity_qc,salinity_adjusted_qc,
        pressure_unit,temperature_unit,salinity_unit,pressure_data_mode,temperature_data_mode,salinity_data_mode,
        pressure_unit_source,temperature_unit_source,salinity_unit_source,pressure_qc_source,pressure_adjusted_qc_source,temperature_qc_source,
        temperature_adjusted_qc_source,salinity_qc_source,salinity_adjusted_qc_source,pressure_flags,temperature_flags,salinity_flags)
        SELECT incoming_month,profile_uuid,m.level_index,
          m.pressure,m.pressure_adjusted,m.temperature,m.temperature_adjusted,m.salinity,m.salinity_adjusted,
          m.pressure_error,m.pressure_original_error,m.temperature_error,m.temperature_original_error,m.salinity_error,m.salinity_original_error,
          m.pressure_qc,m.pressure_adjusted_qc,m.temperature_qc,m.temperature_adjusted_qc,m.salinity_qc,m.salinity_adjusted_qc,
          m.pressure_unit,m.temperature_unit,m.salinity_unit,m.pressure_data_mode,m.temperature_data_mode,m.salinity_data_mode,
          m.pressure_unit_source,m.temperature_unit_source,m.salinity_unit_source,m.pressure_qc_source,m.pressure_adjusted_qc_source,m.temperature_qc_source,
          m.temperature_adjusted_qc_source,m.salinity_qc_source,m.salinity_adjusted_qc_source,m.pressure_flags,m.temperature_flags,m.salinity_flags
        FROM app.measurement_staging m
        WHERE m.run_id=p_run AND m.chunk_id=p_chunk AND m.fence=p_fence AND m.occurrence_index=ordinal;
      GET DIAGNOSTICS inserted_levels = ROW_COUNT;
      IF inserted_levels<>n THEN RAISE EXCEPTION 'level_set_mismatch'; END IF;
      changed := array_append(changed,slot);
      IF old_slot IS NOT NULL THEN changed := array_append(changed,old_slot); END IF;
      accepted_ids := array_append(accepted_ids,profile_uuid);
      accepted_slots := array_append(accepted_slots,slot);
      accepted_old := array_append(accepted_old,old_slot);
    ELSIF result='revision_only' THEN
      UPDATE app.argo_profile SET source_revision=candidate->'revision',
        source_profile_id=coalesce(source_profile_id,stable_id) WHERE id=profile_uuid;
    ELSIF stable_id IS NOT NULL AND stored.source_profile_id IS NULL THEN
      UPDATE app.argo_profile SET source_profile_id=stable_id WHERE id=profile_uuid;
    END IF;
    INSERT INTO app.profile_outcome(chunk_id,occurrence_index,identity_key,outcome,source_levels,
      proposed_content_hash,committed,evidence) VALUES(p_chunk,ordinal,profile_uuid::text,result,n,
      actual_hash,true,jsonb_build_object('old_levels',coalesce(stored.level_count,0),'new_levels',n))
      ON CONFLICT(chunk_id,occurrence_index) DO UPDATE SET outcome=excluded.outcome,committed=true,evidence=excluded.evidence;
  END LOOP;
  -- Scientific conflicts take precedence over a rebuildable base drift. Any
  -- provisional scientific writes above roll back with this exception.
  IF bases_changed THEN RAISE EXCEPTION 'publication_base_changed'; END IF;
  FOR generation IN SELECT value FROM jsonb_array_elements(p_generations) ORDER BY value->>'logical_key' LOOP
    slot := generation->>'logical_key';
    IF NOT slot=ANY(changed) THEN CONTINUE; END IF;
    IF coalesce(generation->>'kind','part')<>'part' THEN RAISE EXCEPTION 'invalid_publication_evidence'; END IF;
    -- Own accepted profiles of this chunk in the slot (final state, ordered by profile_id):
    -- exactly what the part holds. The generation must declare the same population.
    SELECT coalesce(jsonb_agg(jsonb_build_object('profile_id',x.pid,'hash',p.content_hash,
      'levels',p.level_count) ORDER BY x.pid),'[]'::jsonb) INTO new_entries
      FROM (SELECT DISTINCT ON (a.pid) a.pid,a.pslot
              FROM unnest(accepted_ids,accepted_slots) WITH ORDINALITY AS a(pid,pslot,ord)
              ORDER BY a.pid,a.ord DESC) x
      JOIN app.argo_profile p ON p.id=x.pid WHERE x.pslot=slot;
    IF generation->'membership_manifest' IS DISTINCT FROM new_entries
      THEN RAISE EXCEPTION 'stored_snapshot_membership_mismatch'; END IF;
    SELECT count(*),coalesce(sum((m->>'levels')::bigint),0) INTO member_profiles,member_levels
      FROM jsonb_array_elements(generation->'membership_manifest') m;
    IF member_profiles>0 AND (
       member_profiles IS DISTINCT FROM (generation->>'profile_count')::integer
       OR member_levels IS DISTINCT FROM (generation->>'row_count')::bigint
       OR generation->>'schema_sha256' IS NULL
       OR (generation->>'verified_at')::timestamptz>clock_timestamp()
       OR generation->'verification_evidence'->>'schema_sha256' IS DISTINCT FROM generation->>'schema_sha256'
       OR (generation->'verification_evidence'->>'rows')::bigint IS DISTINCT FROM member_levels
       OR (generation->'verification_evidence'->>'profiles')::integer IS DISTINCT FROM member_profiles)
       THEN RAISE EXCEPTION 'snapshot_count_or_schema_mismatch'; END IF;
    -- Incremental manifest: drop entries of profiles this chunk replaced here or moved out
    -- of here, add the own entries of the chunk, keep profile_id order.
    SELECT coalesce(array_agg(a.pid),ARRAY[]::uuid[]) INTO removed_ids
      FROM unnest(accepted_ids,accepted_slots,accepted_old) AS a(pid,pslot,pold)
      WHERE a.pslot=slot OR a.pold=slot;
    UPDATE app.logical_partition_slot AS sl SET slot_version=sl.slot_version+1,
      membership_manifest=(SELECT coalesce(jsonb_agg(merged.entry ORDER BY (merged.entry->>'profile_id')::uuid),
          '[]'::jsonb)
        FROM (SELECT kept.value AS entry FROM jsonb_array_elements(sl.membership_manifest) AS kept(value)
                WHERE NOT ((kept.value->>'profile_id')::uuid = ANY(removed_ids))
              UNION ALL
              SELECT added.value FROM jsonb_array_elements(new_entries) AS added(value)) merged)
      WHERE sl.environment_id=r.environment_id AND sl.logical_key=slot
      RETURNING sl.slot_version,jsonb_array_length(sl.membership_manifest)
      INTO next_version,manifest_size;
    -- The edited manifest must be the stored population of the slot (index-backed recompute).
    IF NOT app.audit_slot_manifest(r.environment_id,slot)
      THEN RAISE EXCEPTION 'stored_snapshot_membership_mismatch'; END IF;
    IF manifest_size=0 THEN
      -- Ownership correction removed the last profile: the slot has no active object.
      UPDATE app.dataset_partition AS d SET status='superseded'
        WHERE d.environment_id=r.environment_id AND d.logical_key=slot AND d.status='active';
    ELSE
      -- Active objects stay selectable at the new version; readers apply the manifest.
      UPDATE app.dataset_partition AS d SET slot_version=next_version
        WHERE d.environment_id=r.environment_id AND d.logical_key=slot AND d.status='active';
    END IF;
    IF jsonb_array_length(generation->'membership_manifest')>0 THEN
      IF NOT i.object_references @> jsonb_build_array(generation->>'object_key')
        OR generation->'verification_evidence' IS NULL THEN RAISE EXCEPTION 'unverified_final_object'; END IF;
      SELECT coalesce(max(d.generation),0)+1 INTO next_generation FROM app.dataset_partition d
        WHERE d.environment_id=r.environment_id AND d.logical_key=slot;
      INSERT INTO app.dataset_partition(id,environment_id,logical_key,generation,slot_version,status,
        intent_id,run_id,chunk_id,object_key,sha256,bytes,row_count,profile_count,schema_sha256,
        geometry_version,geometry_sha256,versions,membership_manifest,verified_at,
        verification_evidence,committed_at,kind,part_ordinal)
      VALUES((generation->>'id')::uuid,r.environment_id,slot,next_generation,next_version,'active',
        p_intent,p_run,p_chunk,generation->>'object_key',generation->>'sha256',
        (generation->>'bytes')::bigint,(generation->>'row_count')::bigint,
        (generation->>'profile_count')::integer,generation->>'schema_sha256',
        r.geometry_version,r.geometry_sha256,r.policy_versions,generation->'membership_manifest',
        (generation->>'verified_at')::timestamptz,generation->'verification_evidence',clock_timestamp(),
        'part',next_generation::integer);
    END IF;
  END LOOP;
  FOR receipt IN SELECT value FROM jsonb_array_elements(p_receipts) LOOP
    slot := receipt->>'logical_key';
    SELECT sl.slot_version,sl.membership_manifest INTO STRICT next_version,manifest
      FROM app.logical_partition_slot sl
      WHERE sl.environment_id=r.environment_id AND sl.logical_key=slot FOR UPDATE;
    -- A receipt-only slot is not covered by the generation base check above: the read of
    -- its counts by the caller is valid only if the slot has not moved since.
    IF NOT slot=ANY(changed) AND receipt->>'base_version' IS NOT NULL
       AND (receipt->>'base_version')::bigint<>next_version
       THEN RAISE EXCEPTION 'publication_base_changed'; END IF;
    SELECT count(*) INTO member_profiles FROM app.argo_profile p
      WHERE app.owner_slot(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,
        (p.scientific_content->'latitude'->>'exact')::numeric)=slot;
    -- Subdivided requests prove only their exact owned rectangle, not every
    -- profile in the parent ten-degree catalogue slot. Counted only when a disposition
    -- depends on it: the selection filter reads scientific_content of each profile.
    need_selection := receipt->>'stored_disposition'='empty_stored_selection'
      OR receipt->>'fetch_disposition' IN ('verified_empty_fetch','source_absence_over_retained');
    selection_profiles := NULL;
    IF need_selection THEN
      SELECT count(*) INTO selection_profiles FROM app.argo_profile p
        WHERE app.owner_slot(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,
          (p.scientific_content->'latitude'->>'exact')::numeric)=slot
        AND p.observed_at>=c.requested_start AND p.observed_at<c.requested_end
        AND (p.scientific_content->'longitude'->>'exact')::numeric>=(c.tile->>'west')::numeric
        AND ((p.scientific_content->'longitude'->>'exact')::numeric<
          (c.tile->>'west')::numeric+(c.tile->>'width')::numeric OR
          ((c.tile->>'west')::numeric+(c.tile->>'width')::numeric=120 AND
            (p.scientific_content->'longitude'->>'exact')::numeric=120))
        AND (p.scientific_content->'latitude'->>'exact')::numeric>=(c.tile->>'south')::numeric
        AND ((p.scientific_content->'latitude'->>'exact')::numeric<
          (c.tile->>'south')::numeric+(c.tile->>'height')::numeric OR
          ((c.tile->>'south')::numeric+(c.tile->>'height')::numeric=30 AND
            (p.scientific_content->'latitude'->>'exact')::numeric=30));
    END IF;
    IF (receipt->>'stored_disposition'='active_generation' AND member_profiles=0)
       OR (receipt->>'stored_disposition'='empty_stored_selection' AND selection_profiles<>0)
       OR (receipt->>'stored_disposition'='empty_stored_domain'
           AND (member_profiles<>0 OR NOT slot=ANY(changed)))
       OR (receipt->>'fetch_disposition'='verified_empty_fetch' AND selection_profiles<>0)
       OR (receipt->>'fetch_disposition'='source_absence_over_retained' AND selection_profiles=0)
       OR (receipt->>'fetch_disposition' IN ('verified_empty_fetch','source_absence_over_retained')
           AND count_staged<>0)
       THEN RAISE EXCEPTION 'coverage_disposition_mismatch'; END IF;
    INSERT INTO app.coverage_receipt(id,chunk_id,intent_id,environment_id,logical_key,
      requested_start,requested_end,slot_version,fetch_disposition,stored_disposition,evidence,committed_at)
    VALUES((receipt->>'id')::uuid,p_chunk,p_intent,r.environment_id,receipt->>'logical_key',
      c.requested_start,c.requested_end,next_version,receipt->>'fetch_disposition',
      receipt->>'stored_disposition',
      coalesce(receipt->'evidence','{}'::jsonb)||jsonb_build_object('full_membership',manifest),
      clock_timestamp());
  END LOOP;
  IF jsonb_array_length(p_receipts)=0 THEN RAISE EXCEPTION 'missing_coverage_receipt'; END IF;
  UPDATE app.ingestion_run SET accepted_profiles=accepted_profiles+accepted_new,
    accepted_levels=accepted_levels+accepted_level_total WHERE id=p_run;
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence); -- Final deadline/cancel guard.
  IF r.work_deadline-clock_timestamp()<interval '1 second' THEN RAISE EXCEPTION 'commit_reserve_exhausted'; END IF;
  -- Staged levels are consumed; the profile rows stay as submission evidence.
  DELETE FROM app.measurement_staging
    WHERE run_id=p_run AND chunk_id=p_chunk AND fence<=p_fence;
  UPDATE app.publication_intent SET status='committed' WHERE id=p_intent;
  UPDATE app.ingestion_chunk SET state='complete',completed_at=clock_timestamp(),reason='verified_publication'
    WHERE id=p_chunk;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,old_state,new_state,reason)
    VALUES(p_run,p_chunk,p_epoch,p_fence,'publishing','complete','verified_publication');
END $body$;

REVOKE ALL ON FUNCTION app.commit_publication(uuid,uuid,bigint,bigint,uuid,jsonb,jsonb) FROM PUBLIC;


-- Merge the active parts of a slot into one snapshot. The caller (Repository.compact) built the
-- snapshot from exactly the objects listed in "supersedes"; this transaction proves they
-- are still the active objects of the slot and that the membership of the snapshot is the
-- manifest of the slot, then swaps them. The snapshot row inherits intent/run/chunk from the newest
-- part it replaces, so foreign keys and the committed-intent joins of the view keep working.
CREATE FUNCTION app.compact_slot(p_environment uuid,p_logical_key text,p_generation jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE slot_row app.logical_partition_slot; last_part app.dataset_partition;
        active_ids uuid[]; listed_ids uuid[]; next_generation bigint;
        member_profiles integer; member_levels bigint;
BEGIN
  SELECT * INTO STRICT slot_row FROM app.logical_partition_slot
    WHERE environment_id=p_environment AND logical_key=p_logical_key FOR UPDATE;
  IF jsonb_typeof(p_generation)<>'object' THEN RAISE EXCEPTION 'invalid_publication_evidence'; END IF;
  IF p_generation->>'base_version' IS NULL
    OR slot_row.slot_version<>(p_generation->>'base_version')::bigint
    THEN RAISE EXCEPTION 'publication_base_changed'; END IF;
  IF p_generation->'membership_manifest' IS DISTINCT FROM slot_row.membership_manifest
    THEN RAISE EXCEPTION 'stored_snapshot_membership_mismatch'; END IF;
  SELECT coalesce(array_agg(d.id ORDER BY d.id),ARRAY[]::uuid[]) INTO active_ids
    FROM app.dataset_partition d
    WHERE d.environment_id=p_environment AND d.logical_key=p_logical_key AND d.status='active';
  SELECT coalesce(array_agg(e.value::uuid ORDER BY e.value::uuid),ARRAY[]::uuid[]) INTO listed_ids
    FROM jsonb_array_elements_text(p_generation->'supersedes') AS e(value);
  IF active_ids IS DISTINCT FROM listed_ids THEN RAISE EXCEPTION 'publication_base_changed'; END IF;
  member_profiles := jsonb_array_length(slot_row.membership_manifest);
  IF cardinality(active_ids)=0 THEN
    IF member_profiles>0 THEN RAISE EXCEPTION 'publication_base_changed'; END IF;
    RETURN;
  END IF;
  SELECT * INTO STRICT last_part FROM app.dataset_partition d
    WHERE d.id=ANY(active_ids) ORDER BY d.generation DESC LIMIT 1;
  IF member_profiles>0 THEN
    SELECT coalesce(sum((m.value->>'levels')::bigint),0) INTO member_levels
      FROM jsonb_array_elements(slot_row.membership_manifest) AS m(value);
    IF p_generation->'verification_evidence' IS NULL THEN
      RAISE EXCEPTION 'unverified_final_object'; END IF;
    IF member_profiles IS DISTINCT FROM (p_generation->>'profile_count')::integer
       OR member_levels IS DISTINCT FROM (p_generation->>'row_count')::bigint
       OR p_generation->>'schema_sha256' IS NULL
       OR (p_generation->>'verified_at')::timestamptz>clock_timestamp()
       OR p_generation->'verification_evidence'->>'schema_sha256'
          IS DISTINCT FROM p_generation->>'schema_sha256'
       OR (p_generation->'verification_evidence'->>'rows')::bigint IS DISTINCT FROM member_levels
       OR (p_generation->'verification_evidence'->>'profiles')::integer
          IS DISTINCT FROM member_profiles
       THEN RAISE EXCEPTION 'snapshot_count_or_schema_mismatch'; END IF;
  END IF;
  UPDATE app.dataset_partition AS d SET status='superseded' WHERE d.id=ANY(active_ids);
  IF member_profiles>0 THEN
    SELECT coalesce(max(d.generation),0)+1 INTO next_generation FROM app.dataset_partition d
      WHERE d.environment_id=p_environment AND d.logical_key=p_logical_key;
    INSERT INTO app.dataset_partition(id,environment_id,logical_key,generation,slot_version,status,
      intent_id,run_id,chunk_id,object_key,sha256,bytes,row_count,profile_count,schema_sha256,
      geometry_version,geometry_sha256,versions,membership_manifest,verified_at,
      verification_evidence,committed_at,kind,part_ordinal)
    VALUES((p_generation->>'id')::uuid,p_environment,p_logical_key,next_generation,
      slot_row.slot_version,'active',last_part.intent_id,last_part.run_id,last_part.chunk_id,
      p_generation->>'object_key',p_generation->>'sha256',(p_generation->>'bytes')::bigint,
      (p_generation->>'row_count')::bigint,(p_generation->>'profile_count')::integer,
      p_generation->>'schema_sha256',last_part.geometry_version,last_part.geometry_sha256,
      last_part.versions,slot_row.membership_manifest,(p_generation->>'verified_at')::timestamptz,
      p_generation->'verification_evidence',clock_timestamp(),'snapshot',next_generation::integer);
  END IF;
END $body$;

REVOKE ALL ON FUNCTION app.audit_slot_manifest(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.audit_levels(uuid,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.compact_slot(uuid,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.audit_slot_manifest(uuid,text),app.audit_levels(uuid,integer),
  app.compact_slot(uuid,text,jsonb) TO floatchat_ingestor;

-- Evidence and reporting functions: deterministic order with several objects per slot,
-- and reconciliation reads the slot manifests (parts overlap after a replacement).
CREATE OR REPLACE FUNCTION app.scientific_snapshot() RETURNS jsonb
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
    jsonb_agg(jsonb_build_array(id,logical_key,generation,sha256) ORDER BY logical_key,generation),'[]'::jsonb)::text,'UTF8')),'hex')
    FROM app.committed_active_partitions),
  'runs',(SELECT count(*) FROM app.ingestion_run),
  'attempts',(SELECT count(*) FROM app.ingestion_attempt),
  'audit_rows',(SELECT count(*) FROM app.ingestion_event)
);
$body$;

CREATE OR REPLACE FUNCTION app.reconciliation_snapshot(p_run uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
WITH r AS (SELECT requested_start AS first,requested_end AS last FROM app.ingestion_run WHERE id=p_run),
stored AS (SELECT id,content_hash,level_count,observed_at FROM app.argo_profile),
members AS (SELECT (m->>'profile_id')::uuid AS id,m->>'hash' AS hash,(m->>'levels')::integer AS levels
  FROM app.logical_partition_slot d,LATERAL jsonb_array_elements(d.membership_manifest) m),
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

CREATE OR REPLACE FUNCTION app.report_metrics_snapshot(p_run uuid) RETURNS jsonb
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
      'id',d.id,'logical_key',d.logical_key,'generation',d.generation,'kind',d.kind,
      'part_ordinal',d.part_ordinal,'slot_version',d.slot_version,'sha256',d.sha256,
      'object_key',d.object_key,'bytes',d.bytes,'profiles',d.profile_count,'levels',d.row_count,
      'verified_at',d.verified_at,'committed_at',d.committed_at,'versions',d.versions,
      'verification_evidence',d.verification_evidence) ORDER BY d.logical_key,d.generation),'[]'::jsonb)
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
