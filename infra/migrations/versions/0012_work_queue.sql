-- Phase-based work queue, configurable worker concurrency and metadata cache (stage1-v4)
-- Queue rows stay in app.processing_ticket: authority (run, chunk, epoch, fence) is still
-- asserted by app.processing_ticket()/app.start_worker(); a claim only hands a ticket to
-- one worker, it is never state authority. Claim budgets, fences and leases are unchanged.
ALTER TABLE app.processing_ticket
  ADD COLUMN kind text NOT NULL DEFAULT 'process' CHECK (kind IN ('acquire','process')),
  ADD COLUMN claimed_by text CHECK (claimed_by IS NULL OR octet_length(claimed_by) BETWEEN 1 AND 128),
  ADD COLUMN claimed_at timestamptz,
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ADD CONSTRAINT processing_ticket_claim_pair CHECK ((claimed_by IS NULL) = (claimed_at IS NULL));
-- One ticket per (chunk, fence, kind): the acquire worker that lands a chunk hands it to the
-- process pool under the same claim (contract 8.1: normal phase progress consumes no claim).
ALTER TABLE app.processing_ticket DROP CONSTRAINT processing_ticket_chunk_id_fence_key;
ALTER TABLE app.processing_ticket
  ADD CONSTRAINT processing_ticket_chunk_fence_kind_key UNIQUE(chunk_id,fence,kind);
CREATE INDEX processing_ticket_queue ON app.processing_ticket(kind,created_at,id) WHERE NOT started;

ALTER TABLE app.ingestion_environment
  ADD COLUMN max_active_chunks integer NOT NULL DEFAULT 8
    CHECK (max_active_chunks BETWEEN 1 AND 64),
  ADD COLUMN upstream_slots integer NOT NULL DEFAULT 4
    CHECK (upstream_slots BETWEEN 1 AND 16);

-- Metadata cache hits record a per-chunk attempt of origin 'cache' (package E). The column
-- CHECK of 0006 is unnamed in the file, so it is found by its definition before it is replaced.
DO $$ DECLARE old record; BEGIN
  FOR old IN SELECT conname FROM pg_constraint WHERE conrelid='app.ingestion_attempt'::regclass
      AND contype='c' AND pg_get_constraintdef(oid) LIKE '%origin%' LOOP
    EXECUTE format('ALTER TABLE app.ingestion_attempt DROP CONSTRAINT %I',old.conname);
  END LOOP;
END $$;
ALTER TABLE app.ingestion_attempt
  ADD CONSTRAINT ingestion_attempt_origin_check CHECK (origin IN ('http','captured','replay','cache'));

-- Same body as 0006 except the recorded origin 'cache'.
CREATE OR REPLACE FUNCTION app.reserve_recorded_attempt(p_run uuid,p_chunk uuid,p_epoch bigint,
  p_fence bigint,p_attempt uuid,p_key text,p_role text,p_parameters jsonb,p_origin text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE ordinal integer; attempts integer;
BEGIN
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  IF p_origin NOT IN ('captured','replay','cache') THEN RAISE EXCEPTION 'invalid_recorded_origin'; END IF;
  SELECT coalesce(max(attempt_number),0)+1 INTO ordinal FROM app.ingestion_attempt WHERE chunk_id=p_chunk;
  SELECT count(*)+1 INTO attempts FROM app.ingestion_attempt WHERE chunk_id=p_chunk AND logical_request_key=p_key;
  IF attempts>4 THEN RAISE EXCEPTION 'landing_retry_exhausted'; END IF;
  INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
    role,request_parameters,origin) VALUES(p_attempt,p_chunk,ordinal,p_key,attempts,p_role,p_parameters,p_origin);
END $body$;

-- The 4-argument form is dropped first: with a defaulted 5th parameter both would match a
-- 4-argument call and PostgreSQL would reject it as ambiguous.
DROP FUNCTION app.processing_ticket(uuid,uuid,bigint,bigint);
CREATE FUNCTION app.processing_ticket(p_run uuid,p_chunk uuid,p_epoch bigint,p_fence bigint,
  p_kind text DEFAULT 'process')
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE ticket uuid;
BEGIN
  IF p_kind NOT IN ('acquire','process') THEN RAISE EXCEPTION 'invalid_ticket_kind'; END IF;
  PERFORM app.assert_authority(p_run,p_chunk,p_epoch,p_fence);
  INSERT INTO app.processing_ticket(id,run_id,chunk_id,control_epoch,fence,kind)
    VALUES(gen_random_uuid(),p_run,p_chunk,p_epoch,p_fence,p_kind) ON CONFLICT DO NOTHING;
  SELECT id INTO STRICT ticket FROM app.processing_ticket
    WHERE chunk_id=p_chunk AND fence=p_fence AND kind=p_kind;
  RETURN ticket;
END $body$;

-- Hands one unstarted ticket of a kind to one worker. Only tickets that app.start_worker()
-- would accept (mirrors app.assert_authority) are eligible, so a ticket that lost its fence,
-- lease, run or chunk is inert instead of being claimed forever. Only the ticket row is
-- locked here: start_worker locks run/chunk before the ticket, so this cannot invert order.
-- A claim whose worker vanished before start_worker is handed out again after two minutes;
-- `started` still admits exactly one executor. An empty queue returns a row of NULLs.
CREATE FUNCTION app.claim_ticket(p_kind text,p_worker text) RETURNS app.processing_ticket
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
DECLARE t app.processing_ticket;
BEGIN
  IF p_kind NOT IN ('acquire','process') THEN RAISE EXCEPTION 'invalid_ticket_kind'; END IF;
  IF p_worker IS NULL OR octet_length(p_worker) NOT BETWEEN 1 AND 128 THEN
    RAISE EXCEPTION 'invalid_ticket_worker'; END IF;
  UPDATE app.processing_ticket q SET claimed_by=p_worker,claimed_at=clock_timestamp()
  WHERE q.id=(
    SELECT pt.id FROM app.processing_ticket pt
    JOIN app.ingestion_chunk c ON c.id=pt.chunk_id
    JOIN app.ingestion_run r ON r.id=pt.run_id
    WHERE pt.kind=p_kind AND NOT pt.started
      AND (pt.claimed_at IS NULL OR pt.claimed_at<clock_timestamp()-interval '2 minutes')
      AND NOT r.closed AND r.cancellation_requested_at IS NULL
      AND r.state NOT IN ('complete','partial','quarantined','failed')
      AND r.control_epoch=pt.control_epoch AND r.controller_lease_until>clock_timestamp()
      AND r.work_deadline>clock_timestamp()
      AND c.control_epoch=pt.control_epoch AND c.fence=pt.fence
      AND c.state NOT IN ('complete','quarantined','failed')
      AND c.lease_until>clock_timestamp()
    ORDER BY pt.created_at,pt.id
    LIMIT 1 FOR UPDATE OF pt SKIP LOCKED)
  RETURNING q.* INTO t;
  RETURN t;
END $body$;

-- Same body as 0003 except the concurrency bound, read from the environment (was constant 2).
CREATE OR REPLACE FUNCTION app.claim_chunk(p_run uuid, p_chunk uuid, p_epoch bigint) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, app AS $body$
DECLARE r app.ingestion_run; c app.ingestion_chunk; next_fence bigint; active_bound integer;
BEGIN
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id = p_run FOR UPDATE;
  SELECT * INTO STRICT c FROM app.ingestion_chunk WHERE id = p_chunk AND run_id = p_run FOR UPDATE;
  IF c.state IN ('complete','quarantined','failed') THEN RETURN NULL; END IF;
  IF r.closed OR r.control_epoch <> p_epoch OR r.cancellation_requested_at IS NOT NULL
     OR r.controller_lease_until <= clock_timestamp() OR r.work_deadline <= clock_timestamp()
     OR (c.lease_until > clock_timestamp() AND c.control_epoch = p_epoch)
     OR c.processing_claims >= 4 THEN RAISE EXCEPTION 'claim_denied'; END IF;
  SELECT e.max_active_chunks INTO STRICT active_bound FROM app.ingestion_environment e
    WHERE e.id = r.environment_id;
  IF (SELECT count(*) FROM app.ingestion_chunk active WHERE active.run_id=p_run
      AND active.control_epoch=p_epoch AND active.lease_until>clock_timestamp()
      AND active.state NOT IN ('complete','quarantined','failed'))>=active_bound
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

-- Per-float metadata responses shared by chunks of one environment. The row points at the
-- immutable raw object; a cache hit still records a per-chunk attempt (package E).
CREATE TABLE app.float_metadata_cache (
  environment_id uuid NOT NULL REFERENCES app.ingestion_environment(id) ON DELETE RESTRICT,
  pointer text NOT NULL CHECK (octet_length(pointer) BETWEEN 1 AND 1024),
  raw_manifest_id uuid NOT NULL REFERENCES app.raw_manifest(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES app.ingestion_run(id) ON DELETE RESTRICT,
  retrieved_at timestamptz NOT NULL,
  PRIMARY KEY(environment_id,pointer)
);
REVOKE ALL ON app.float_metadata_cache FROM PUBLIC,floatchat_app;
GRANT SELECT ON app.float_metadata_cache TO floatchat_ingestor;

-- Upsert that only moves forward in time, so a slow older writer cannot replace a newer
-- entry. The manifest must be this run's own raw manifest in this environment.
CREATE FUNCTION app.metadata_cache_put(p_environment uuid,p_pointer text,p_manifest uuid,
  p_run uuid,p_retrieved timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,app AS $body$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM app.raw_manifest m JOIN app.ingestion_run r ON r.id=m.run_id
      WHERE m.id=p_manifest AND m.run_id=p_run AND r.environment_id=p_environment) THEN
    RAISE EXCEPTION 'invalid_metadata_cache_entry'; END IF;
  INSERT INTO app.float_metadata_cache AS c(environment_id,pointer,raw_manifest_id,run_id,retrieved_at)
    VALUES(p_environment,p_pointer,p_manifest,p_run,p_retrieved)
    ON CONFLICT (environment_id,pointer) DO UPDATE SET raw_manifest_id=EXCLUDED.raw_manifest_id,
      run_id=EXCLUDED.run_id,retrieved_at=EXCLUDED.retrieved_at
      WHERE c.retrieved_at<=EXCLUDED.retrieved_at;
END $body$;

REVOKE ALL ON FUNCTION app.processing_ticket(uuid,uuid,bigint,bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.claim_ticket(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.metadata_cache_put(uuid,text,uuid,uuid,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.processing_ticket(uuid,uuid,bigint,bigint,text),
  app.claim_ticket(text,text),app.metadata_cache_put(uuid,text,uuid,uuid,timestamptz)
  TO floatchat_ingestor;
