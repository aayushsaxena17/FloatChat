-- ADR-0044: commit_publication validated and inserted levels one at a time; each
-- level indexed into the profile's whole canonical array, so commit time grew with
-- depth squared and monthly chunks of deep profiles exceeded the 60 s transaction
-- bound (reports/stage1-live-commit-5f59c62f.json). Same checks, set-based.
-- Explicit single expressions (no subqueries, no SET clause) so the planner can
-- inline them per level; the field lists are the same 12 numeric and 24 other fields.
CREATE FUNCTION app.level_mismatch(p_level jsonb,p_canonical jsonb,p_index integer) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $body$
  SELECT (p_canonical->>'level_index')::integer IS DISTINCT FROM p_index
    OR (p_canonical->'pressure'->>'exact')::double precision IS DISTINCT FROM (p_level->>'pressure')::double precision
    OR (p_canonical->'pressure_adjusted'->>'exact')::double precision IS DISTINCT FROM (p_level->>'pressure_adjusted')::double precision
    OR (p_canonical->'pressure_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'pressure_error')::double precision
    OR (p_canonical->'pressure_original_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'pressure_original_error')::double precision
    OR (p_canonical->'temperature'->>'exact')::double precision IS DISTINCT FROM (p_level->>'temperature')::double precision
    OR (p_canonical->'temperature_adjusted'->>'exact')::double precision IS DISTINCT FROM (p_level->>'temperature_adjusted')::double precision
    OR (p_canonical->'temperature_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'temperature_error')::double precision
    OR (p_canonical->'temperature_original_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'temperature_original_error')::double precision
    OR (p_canonical->'salinity'->>'exact')::double precision IS DISTINCT FROM (p_level->>'salinity')::double precision
    OR (p_canonical->'salinity_adjusted'->>'exact')::double precision IS DISTINCT FROM (p_level->>'salinity_adjusted')::double precision
    OR (p_canonical->'salinity_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'salinity_error')::double precision
    OR (p_canonical->'salinity_original_error'->>'exact')::double precision IS DISTINCT FROM (p_level->>'salinity_original_error')::double precision
    OR p_level->'pressure_qc' IS DISTINCT FROM p_canonical->'pressure_qc'
    OR p_level->'pressure_adjusted_qc' IS DISTINCT FROM p_canonical->'pressure_adjusted_qc'
    OR p_level->'pressure_qc_source' IS DISTINCT FROM p_canonical->'pressure_qc_source'
    OR p_level->'pressure_adjusted_qc_source' IS DISTINCT FROM p_canonical->'pressure_adjusted_qc_source'
    OR p_level->'pressure_unit' IS DISTINCT FROM p_canonical->'pressure_unit'
    OR p_level->'pressure_unit_source' IS DISTINCT FROM p_canonical->'pressure_unit_source'
    OR p_level->'pressure_data_mode' IS DISTINCT FROM p_canonical->'pressure_data_mode'
    OR p_level->'pressure_flags' IS DISTINCT FROM p_canonical->'pressure_flags'
    OR p_level->'temperature_qc' IS DISTINCT FROM p_canonical->'temperature_qc'
    OR p_level->'temperature_adjusted_qc' IS DISTINCT FROM p_canonical->'temperature_adjusted_qc'
    OR p_level->'temperature_qc_source' IS DISTINCT FROM p_canonical->'temperature_qc_source'
    OR p_level->'temperature_adjusted_qc_source' IS DISTINCT FROM p_canonical->'temperature_adjusted_qc_source'
    OR p_level->'temperature_unit' IS DISTINCT FROM p_canonical->'temperature_unit'
    OR p_level->'temperature_unit_source' IS DISTINCT FROM p_canonical->'temperature_unit_source'
    OR p_level->'temperature_data_mode' IS DISTINCT FROM p_canonical->'temperature_data_mode'
    OR p_level->'temperature_flags' IS DISTINCT FROM p_canonical->'temperature_flags'
    OR p_level->'salinity_qc' IS DISTINCT FROM p_canonical->'salinity_qc'
    OR p_level->'salinity_adjusted_qc' IS DISTINCT FROM p_canonical->'salinity_adjusted_qc'
    OR p_level->'salinity_qc_source' IS DISTINCT FROM p_canonical->'salinity_qc_source'
    OR p_level->'salinity_adjusted_qc_source' IS DISTINCT FROM p_canonical->'salinity_adjusted_qc_source'
    OR p_level->'salinity_unit' IS DISTINCT FROM p_canonical->'salinity_unit'
    OR p_level->'salinity_unit_source' IS DISTINCT FROM p_canonical->'salinity_unit_source'
    OR p_level->'salinity_data_mode' IS DISTINCT FROM p_canonical->'salinity_data_mode'
    OR p_level->'salinity_flags' IS DISTINCT FROM p_canonical->'salinity_flags';
$body$;

-- Canonical zero is positive; numeric fields always take the derived canonical value,
-- never an untrusted staging float, exactly as the per-level jsonb_set did.
CREATE FUNCTION app.canonical_level_values(p_level jsonb,p_canonical jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $body$
  SELECT p_level || jsonb_build_object(
    'pressure',coalesce(to_jsonb((p_canonical->'pressure'->>'exact')::double precision),'null'::jsonb),
    'pressure_adjusted',coalesce(to_jsonb((p_canonical->'pressure_adjusted'->>'exact')::double precision),'null'::jsonb),
    'pressure_error',coalesce(to_jsonb((p_canonical->'pressure_error'->>'exact')::double precision),'null'::jsonb),
    'pressure_original_error',coalesce(to_jsonb((p_canonical->'pressure_original_error'->>'exact')::double precision),'null'::jsonb),
    'temperature',coalesce(to_jsonb((p_canonical->'temperature'->>'exact')::double precision),'null'::jsonb),
    'temperature_adjusted',coalesce(to_jsonb((p_canonical->'temperature_adjusted'->>'exact')::double precision),'null'::jsonb),
    'temperature_error',coalesce(to_jsonb((p_canonical->'temperature_error'->>'exact')::double precision),'null'::jsonb),
    'temperature_original_error',coalesce(to_jsonb((p_canonical->'temperature_original_error'->>'exact')::double precision),'null'::jsonb),
    'salinity',coalesce(to_jsonb((p_canonical->'salinity'->>'exact')::double precision),'null'::jsonb),
    'salinity_adjusted',coalesce(to_jsonb((p_canonical->'salinity_adjusted'->>'exact')::double precision),'null'::jsonb),
    'salinity_error',coalesce(to_jsonb((p_canonical->'salinity_error'->>'exact')::double precision),'null'::jsonb),
    'salinity_original_error',coalesce(to_jsonb((p_canonical->'salinity_original_error'->>'exact')::double precision),'null'::jsonb));
$body$;
REVOKE ALL ON FUNCTION app.level_mismatch(jsonb,jsonb,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.canonical_level_values(jsonb,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.commit_publication(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
                                       p_intent uuid,p_generations jsonb,p_receipts jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app, public AS $body$
DECLARE r app.ingestion_run; c app.ingestion_chunk; i app.publication_intent;
        candidate jsonb; science jsonb; level jsonb; generation jsonb; receipt jsonb;
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
  SELECT coalesce(sum(jsonb_array_length(s.candidate->'levels')),0) INTO staged_levels
    FROM app.ingestion_staging s WHERE s.run_id=p_run AND s.chunk_id=p_chunk AND s.fence=p_fence;
  IF staged_levels>2000000 THEN RAISE EXCEPTION 'measurement_count_limit'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_generations) g
      GROUP BY g->>'logical_key' HAVING count(*)>1)
    OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_receipts) g
      GROUP BY g->>'logical_key' HAVING count(*)>1)
    THEN RAISE EXCEPTION 'duplicate_publication_slot'; END IF;
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
    n := jsonb_array_length(candidate->'levels');
    IF n NOT BETWEEN 1 AND 10000 OR jsonb_array_length(science->'levels')<>n
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
      -- ADR-0044: set-based level validation/insert. Identical checks and error
      -- categories; canonical levels are expanded once instead of once per level.
      IF EXISTS(SELECT 1 FROM jsonb_array_elements(candidate->'levels') l
          WHERE (l.value->>'level_index')::integer IS NULL
             OR (l.value->>'level_index')::integer NOT BETWEEN 0 AND n-1)
        THEN RAISE EXCEPTION 'invalid_level_index'; END IF;
      IF EXISTS(SELECT 1 FROM jsonb_array_elements(candidate->'levels') l
          JOIN jsonb_array_elements(science->'levels') WITH ORDINALITY k(canonical,ordinal)
            ON k.ordinal-1=(l.value->>'level_index')::integer
          WHERE app.level_mismatch(l.value,k.canonical,(l.value->>'level_index')::integer))
        THEN RAISE EXCEPTION 'measurement_content_mismatch'; END IF;
      -- LATERAL evaluates the record once per level; (f(...)).* would call it per column.
      INSERT INTO app.core_measurement
        SELECT row_value.*
        FROM jsonb_array_elements(candidate->'levels') l
        JOIN jsonb_array_elements(science->'levels') WITH ORDINALITY k(canonical,ordinal)
          ON k.ordinal-1=(l.value->>'level_index')::integer
        CROSS JOIN LATERAL jsonb_populate_record(NULL::app.core_measurement,
          app.canonical_level_values(l.value,k.canonical) || jsonb_build_object('profile_id',profile_uuid,
            'observation_month',incoming_month,'canonical_level',k.canonical)) row_value;
      IF (SELECT count(*) FROM app.core_measurement WHERE profile_id=profile_uuid
          AND observation_month=incoming_month)<>n THEN RAISE EXCEPTION 'level_set_mismatch'; END IF;
      changed := array_append(changed,slot);
      IF old_slot IS NOT NULL THEN changed := array_append(changed,old_slot); END IF;
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
    -- Compare the complete accepted stored population, never run-eligible-only rows.
    IF generation->'membership_manifest' IS DISTINCT FROM (
      SELECT coalesce(jsonb_agg(jsonb_build_object('profile_id',p.id,'hash',p.content_hash,
        'levels',p.level_count) ORDER BY p.id),'[]'::jsonb) FROM app.argo_profile p
      WHERE app.owner_slot(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,
        (p.scientific_content->'latitude'->>'exact')::numeric)=slot)
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
    UPDATE app.logical_partition_slot SET slot_version=slot_version+1,
      membership_manifest=generation->'membership_manifest'
      WHERE environment_id=r.environment_id AND logical_key=slot RETURNING slot_version INTO next_version;
    UPDATE app.dataset_partition SET status='superseded'
      WHERE environment_id=r.environment_id AND logical_key=slot AND status='active';
    IF jsonb_array_length(generation->'membership_manifest')>0 THEN
      IF NOT i.object_references @> jsonb_build_array(generation->>'object_key')
        OR generation->'verification_evidence' IS NULL THEN RAISE EXCEPTION 'unverified_final_object'; END IF;
      INSERT INTO app.dataset_partition(id,environment_id,logical_key,generation,slot_version,status,
        intent_id,run_id,chunk_id,object_key,sha256,bytes,row_count,profile_count,schema_sha256,
        geometry_version,geometry_sha256,versions,membership_manifest,verified_at,
        verification_evidence,committed_at)
      VALUES((generation->>'id')::uuid,r.environment_id,slot,next_version,next_version,'active',
        p_intent,p_run,p_chunk,generation->>'object_key',generation->>'sha256',
        (generation->>'bytes')::bigint,(generation->>'row_count')::bigint,
        (generation->>'profile_count')::integer,generation->>'schema_sha256',
        r.geometry_version,r.geometry_sha256,r.policy_versions,generation->'membership_manifest',
        (generation->>'verified_at')::timestamptz,generation->'verification_evidence',clock_timestamp());
    END IF;
  END LOOP;
  FOR receipt IN SELECT value FROM jsonb_array_elements(p_receipts) LOOP
    slot := receipt->>'logical_key';
    SELECT count(*) INTO member_profiles FROM app.argo_profile p
      WHERE app.owner_slot(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,
        (p.scientific_content->'latitude'->>'exact')::numeric)=slot;
    -- Subdivided requests prove only their exact owned rectangle, not every
    -- profile in the parent ten-degree catalogue slot.
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
    IF (receipt->>'stored_disposition'='active_generation' AND member_profiles=0)
       OR (receipt->>'stored_disposition'='empty_stored_selection' AND selection_profiles<>0)
       OR (receipt->>'stored_disposition'='empty_stored_domain'
           AND (member_profiles<>0 OR NOT slot=ANY(changed)))
       OR (receipt->>'fetch_disposition'='verified_empty_fetch' AND selection_profiles<>0)
       OR (receipt->>'fetch_disposition'='source_absence_over_retained' AND selection_profiles=0)
       OR (receipt->>'fetch_disposition' IN ('verified_empty_fetch','source_absence_over_retained')
           AND count_staged<>0)
       THEN RAISE EXCEPTION 'coverage_disposition_mismatch'; END IF;
    SELECT slot_version INTO STRICT next_version FROM app.logical_partition_slot
      WHERE environment_id=r.environment_id AND logical_key=receipt->>'logical_key' FOR UPDATE;
    INSERT INTO app.coverage_receipt(id,chunk_id,intent_id,environment_id,logical_key,
      requested_start,requested_end,slot_version,fetch_disposition,stored_disposition,evidence,committed_at)
    VALUES((receipt->>'id')::uuid,p_chunk,p_intent,r.environment_id,receipt->>'logical_key',
      c.requested_start,c.requested_end,next_version,receipt->>'fetch_disposition',
      receipt->>'stored_disposition',receipt->'evidence',clock_timestamp());
  END LOOP;
  IF jsonb_array_length(p_receipts)=0 THEN RAISE EXCEPTION 'missing_coverage_receipt'; END IF;
  UPDATE app.ingestion_run SET accepted_profiles=accepted_profiles+accepted_new,
    accepted_levels=accepted_levels+accepted_level_total WHERE id=p_run;
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence); -- Final deadline/cancel guard.
  IF r.work_deadline-clock_timestamp()<interval '1 second' THEN RAISE EXCEPTION 'commit_reserve_exhausted'; END IF;
  UPDATE app.publication_intent SET status='committed' WHERE id=p_intent;
  UPDATE app.ingestion_chunk SET state='complete',completed_at=clock_timestamp(),reason='verified_publication'
    WHERE id=p_chunk;
  INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,fence,old_state,new_state,reason)
    VALUES(p_run,p_chunk,p_epoch,p_fence,'publishing','complete','verified_publication');
END $body$;

REVOKE ALL ON FUNCTION app.commit_publication(uuid,uuid,bigint,bigint,uuid,jsonb,jsonb) FROM PUBLIC;

-- Every catalogue membership/receipt query filters on exactly this expression; the
-- index removes a per-commit scan over all stored profiles.
CREATE INDEX argo_profile_owner_slot_idx ON app.argo_profile (app.owner_slot(observed_at,
  (scientific_content->'longitude'->>'exact')::numeric,
  (scientific_content->'latitude'->>'exact')::numeric));
