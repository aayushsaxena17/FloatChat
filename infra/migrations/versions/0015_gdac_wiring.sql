-- GDAC wiring (stage1-v4, integrator): the admission, slot and publication functions become
-- source-aware. Additive for Argovis: every Argovis rule, category and logical key is kept
-- (the argovis branch of each function is the 0010/0013 body). The source of a run is read
-- from its policy_versions mapping; the source of a candidate from its canonical content,
-- and the two must agree (otherwise scientific_hash_mismatch).

-- 'gdac' for a run admitted with gdac-core-v1 policy versions, else 'argovis'.
CREATE FUNCTION app.run_source(p_versions jsonb) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, app AS $body$
SELECT CASE WHEN p_versions->>'mapping' = 'gdac-core-v1' THEN 'gdac' ELSE 'argovis' END;
$body$;

-- Logical partition key of a profile of either population.
CREATE FUNCTION app.profile_slot(p_source text,p_time timestamptz,p_longitude numeric,p_latitude numeric)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, app AS $body$
SELECT CASE WHEN p_source = 'gdac' THEN app.gdac_owner_slot(p_time,p_longitude,p_latitude)
            ELSE app.owner_slot(p_time,p_longitude,p_latitude) END;
$body$;

-- Same role as argo_profile_owner_slot_idx (0011) for the GDAC population.
CREATE INDEX argo_profile_gdac_slot_idx ON app.argo_profile (app.gdac_owner_slot(observed_at,
  (scientific_content->'longitude'->>'exact')::numeric,
  (scientific_content->'latitude'->>'exact')::numeric)) WHERE source = 'gdac';

REVOKE ALL ON FUNCTION app.run_source(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.profile_slot(text,timestamptz,numeric,numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.gdac_owner_slot(timestamptz,numeric,numeric),
  app.run_source(jsonb),app.profile_slot(text,timestamptz,numeric,numeric) TO floatchat_ingestor;

-- True when the incrementally maintained manifest equals the stored population of the slot.
-- Dynamic only in the (whitelisted) owner function, so each population uses its own index.
CREATE OR REPLACE FUNCTION app.audit_slot_manifest(p_environment uuid,p_logical_key text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE stored jsonb; population jsonb; slot_source text; slot_fn text;
BEGIN
  SELECT s.membership_manifest INTO stored FROM app.logical_partition_slot s
    WHERE s.environment_id=p_environment AND s.logical_key=p_logical_key;
  IF NOT FOUND THEN RETURN false; END IF;
  slot_source := CASE WHEN p_logical_key LIKE 'gdac/%' THEN 'gdac' ELSE 'argovis' END;
  slot_fn := CASE slot_source WHEN 'gdac' THEN 'app.gdac_owner_slot' ELSE 'app.owner_slot' END;
  EXECUTE format('SELECT coalesce(jsonb_agg(jsonb_build_object(''profile_id'',p.id,''hash'',p.content_hash,'
    || '''levels'',p.level_count) ORDER BY p.id),''[]''::jsonb) FROM app.argo_profile p '
    || 'WHERE p.source=%L AND %s(p.observed_at,(p.scientific_content->''longitude''->>''exact'')::numeric,'
    || '(p.scientific_content->''latitude''->>''exact'')::numeric)=$1',slot_source,slot_fn)
    INTO population USING p_logical_key;
  RETURN stored IS NOT DISTINCT FROM population;
END $body$;

-- ensure_slot with the owner slot of the run's source (0005 body otherwise).
CREATE OR REPLACE FUNCTION app.ensure_slot(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                               p_month date,p_west integer,p_south integer) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; slot text;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  IF p_month<>date_trunc('month',p_month)::date OR p_west NOT BETWEEN 20 AND 110
     OR (p_west-20)%10<>0 OR p_south NOT BETWEEN -60 AND 20 OR (p_south+60)%10<>0
     THEN RAISE EXCEPTION 'invalid_slot'; END IF;
  slot := app.profile_slot(app.run_source(r.policy_versions),
    p_month::timestamp AT TIME ZONE 'UTC',p_west,p_south);
  INSERT INTO app.logical_partition_slot(environment_id,logical_key,observation_month,tile_key)
    VALUES(r.environment_id,slot,p_month,p_west||':'||p_south) ON CONFLICT DO NOTHING;
  RETURN slot;
END $body$;

-- commit_publication: identical to 0013 except the source of the candidate (science->>'source')
-- selects the argo_float/argo_profile rows, the accepted mapping version, the lock namespace
-- and the owner slot function (app.profile_slot); receipt counts use the slot's own function.

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
        run_source text; cand_source text; slot_source text; slot_fn text;
BEGIN
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id=p_chunk AND run_id=p_run;
  IF c.state='complete' THEN RETURN; END IF; -- Lost acknowledgement is already complete.
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id=p_chunk AND run_id=p_run;
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=p_run;
  run_source := app.run_source(r.policy_versions);
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
    cand_source := science->>'source';
    IF actual_hash IS DISTINCT FROM candidate->>'content_hash'
      OR science->>'hash_version' IS DISTINCT FROM 'scientific-json-v2'
      OR cand_source IS DISTINCT FROM run_source
      OR science->>'mapping_version' IS DISTINCT FROM
         (CASE cand_source WHEN 'gdac' THEN 'gdac-core-v1' ELSE 'argovis-core-v1' END)
      THEN RAISE EXCEPTION 'scientific_hash_mismatch'; END IF;
    platform := candidate->>'platform'; stable_id := candidate->>'source_profile_id';
    obs := (candidate->>'observed_at')::timestamptz;
    identity_obs := (candidate->>'identity_observed_at')::timestamptz;
    incoming_month := date_trunc('month',obs AT TIME ZONE 'UTC')::date;
    longitude := (science->'longitude'->>'exact')::numeric;
    latitude := (science->'latitude'->>'exact')::numeric;
    slot := app.profile_slot(cand_source,obs,longitude,latitude);
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
    PERFORM pg_advisory_xact_lock(hashtextextended(cand_source||'/'||platform||'/'||
      coalesce(candidate->>'cycle','')||'/'||coalesce(candidate->>'direction','')||'/single',0));
    SELECT id INTO float_uuid FROM app.argo_float WHERE source=cand_source AND platform_number=platform;
    stored := NULL; matched := NULL; old_slot := NULL;
    IF stable_id IS NOT NULL THEN
      SELECT * INTO stored FROM app.argo_profile WHERE source=cand_source AND source_profile_id=stable_id FOR UPDATE;
    END IF;
    IF float_uuid IS NOT NULL AND candidate->>'cycle' IS NOT NULL AND candidate->>'direction' IN ('A','D') THEN
      SELECT * INTO matched FROM app.argo_profile WHERE source=cand_source AND float_id=float_uuid
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
      old_slot := app.profile_slot(stored.source,stored.observed_at,
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
        INSERT INTO app.argo_float(id,source,platform_number) VALUES(gen_random_uuid(),cand_source,platform)
          ON CONFLICT(source,platform_number) DO NOTHING;
        SELECT id INTO STRICT float_uuid FROM app.argo_float WHERE source=cand_source AND platform_number=platform;
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
        VALUES(profile_uuid,cand_source,stable_id,float_uuid,(candidate->>'cycle')::bigint,candidate->>'direction',
          identity_obs,'single',candidate->>'cycle' IS NOT NULL AND candidate->>'direction' IN ('A','D'),
          obs,incoming_month,ST_SetSRID(ST_MakePoint(longitude::float8,latitude::float8),4326),
          actual_hash,'scientific-json-v2',science->>'mapping_version',n,science,candidate->'revision',
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
    slot_source := CASE WHEN slot LIKE 'gdac/%' THEN 'gdac' ELSE 'argovis' END;
    slot_fn := CASE slot_source WHEN 'gdac' THEN 'app.gdac_owner_slot' ELSE 'app.owner_slot' END;
    EXECUTE format('SELECT count(*) FROM app.argo_profile p WHERE p.source=%L AND '
      || '%s(p.observed_at,(p.scientific_content->''longitude''->>''exact'')::numeric,'
      || '(p.scientific_content->''latitude''->>''exact'')::numeric)=$1',slot_source,slot_fn)
      INTO member_profiles USING slot;
    -- Subdivided requests prove only their exact owned rectangle, not every
    -- profile in the parent ten-degree catalogue slot. Counted only when a disposition
    -- depends on it: the selection filter reads scientific_content of each profile.
    need_selection := receipt->>'stored_disposition'='empty_stored_selection'
      OR receipt->>'fetch_disposition' IN ('verified_empty_fetch','source_absence_over_retained');
    selection_profiles := NULL;
    IF need_selection THEN
      EXECUTE format('SELECT count(*) FROM app.argo_profile p WHERE p.source=%L AND '
        || '%s(p.observed_at,(p.scientific_content->''longitude''->>''exact'')::numeric,'
        || '(p.scientific_content->''latitude''->>''exact'')::numeric)=$1 '
        || 'AND p.observed_at>=$2 AND p.observed_at<$3 '
        || 'AND (p.scientific_content->''longitude''->>''exact'')::numeric>=$4 '
        || 'AND ((p.scientific_content->''longitude''->>''exact'')::numeric<$4+$5 OR '
        || '($4+$5=120 AND (p.scientific_content->''longitude''->>''exact'')::numeric=120)) '
        || 'AND (p.scientific_content->''latitude''->>''exact'')::numeric>=$6 '
        || 'AND ((p.scientific_content->''latitude''->>''exact'')::numeric<$6+$7 OR '
        || '($6+$7=30 AND (p.scientific_content->''latitude''->>''exact'')::numeric=30))',
        slot_source,slot_fn)
        INTO selection_profiles USING slot,c.requested_start,c.requested_end,
          (c.tile->>'west')::numeric,(c.tile->>'width')::numeric,
          (c.tile->>'south')::numeric,(c.tile->>'height')::numeric;
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

-- admit_run (0010 body): scope row, overlap record and scope update per source of the run.

CREATE OR REPLACE FUNCTION app.admit_run(p_environment uuid,p_request uuid,p_mode text,p_scheduled boolean,
  p_start timestamptz,p_end timestamptz,p_seconds integer,p_geometry_hash text,p_versions jsonb,p_limits jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE e app.ingestion_environment; s app.ingestion_scope; r app.ingestion_run;
        reference timestamptz; actual timestamptz; first timestamptz; last timestamptz;
        run_uuid uuid; admission_uuid uuid; src text;
BEGIN
  src := app.run_source(p_versions);
  SELECT * INTO STRICT e FROM app.ingestion_environment WHERE id=p_environment;
  IF e.mode<>p_mode OR (p_mode='acceptance' AND NOT e.disposable)
     OR (p_scheduled AND p_mode<>'normal') OR p_seconds NOT BETWEEN 61 AND 43200
     OR p_geometry_hash<>encode(sha256(convert_to('POLYGON((20 -60,120 -60,120 30,20 30,20 -60))','UTF8')),'hex')
     THEN RAISE EXCEPTION 'unsafe_run_configuration'; END IF;
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
    WHERE environment_id=p_environment AND source=src AND region_version='indian-ocean-v1';
  INSERT INTO app.ingestion_event(run_id,control_epoch,reason)
    VALUES(run_uuid,1,'run_admitted_reference_captured');
  RETURN jsonb_build_object('kind','created','run_id',run_uuid);
END $body$;

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
      (SELECT app.profile_slot(source,observed_at,(scientific_content->'longitude'->>'exact')::numeric,
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
