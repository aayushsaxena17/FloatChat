"""Migration 0012 in a real disposable PostgreSQL: work queue, bound and metadata cache.

Every case runs in a transaction that ROLLBACKs, except the SKIP LOCKED proof, which needs a
second committed session and removes its own rows afterwards.
"""

import subprocess
import time
import uuid

import pytest
import test_database
from test_database import ATTEMPT, CHUNK, ENV, RAW, RUN

postgres = test_database.postgres

OTHER = "00000000-0000-4000-8000-0000000000a1"
THIRD = "00000000-0000-4000-8000-0000000000a2"
TILE = '{"west":80,"south":10,"width":10,"height":10}'
# Only the manifest part of SCIENCE: a raw object of this run and chunk.
MANIFEST = test_database.SCIENCE.split("INSERT INTO app.argo_float")[0]
# The seeded chunk after its first claim (epoch 1, fence 1) and a ticket of a kind under it.
CLAIM = f"SELECT app.claim_chunk('{RUN}','{CHUNK}',1);"
EXPIRE_LEASE = (
    "UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()-interval '1 second' "
    f"WHERE id='{CHUNK}';"
)


def ticket(kind, identifier=CHUNK):
    return f"app.processing_ticket('{RUN}','{identifier}',1,1,'{kind}')"


def yes(condition):
    """psql prints booleans as t/f, but text || boolean prints true/false; avoid both."""
    return f"CASE WHEN {condition} THEN 'yes' ELSE 'no' END"


def chunk(identifier, key):
    return (
        "INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,"
        f"requested_end,tile,plan_version) VALUES('{identifier}','{RUN}','{key}','2025-01-01',"
        f"'2025-01-07','{TILE}','v1');"
    )


def claim_attempts(count):
    """Claim `count` fresh chunks one after another; reports `granted|last refusal`."""
    return f"""
      CREATE TEMP TABLE outcome(granted int, refusal text);
      DO $$ DECLARE c uuid; n int := 0; m text := 'none'; BEGIN
        FOR c IN SELECT gen_random_uuid() FROM generate_series(1,{count}) LOOP
          INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,
            requested_end,tile,plan_version)
            VALUES(c,'{RUN}','bulk-'||c,'2025-01-01','2025-01-07','{TILE}','v1');
          BEGIN
            PERFORM app.claim_chunk('{RUN}',c,1);
            n := n + 1;
          EXCEPTION WHEN OTHERS THEN m := SQLERRM;
          END;
        END LOOP;
        INSERT INTO outcome VALUES(n,m);
      END $$;
      SELECT granted||'|'||refusal FROM outcome;"""


def put(at, pointer="float-1"):
    """A DO block, not SELECT: a void result would print an empty line into the output."""
    return (
        f"DO $$ BEGIN PERFORM app.metadata_cache_put('{ENV}','{pointer}','{RAW}','{RUN}','{at}'); "
        "END $$;"
    )


# Schema --------------------------------------------------------------------------------


@pytest.mark.integration
def test_0012_columns_defaults_and_checks(postgres):
    assert postgres(
        "SELECT column_name||'|'||coalesce(column_default,'') FROM information_schema.columns "
        "WHERE table_schema='app' AND table_name='processing_ticket' "
        "AND column_name IN ('kind','claimed_by','claimed_at') ORDER BY column_name"
    ).splitlines() == ["claimed_at|", "claimed_by|", "kind|'process'::text"]
    assert (
        postgres("SELECT max_active_chunks||'|'||upstream_slots FROM app.ingestion_environment")
        == "8|4"
    )
    for statement in (
        "UPDATE app.ingestion_environment SET max_active_chunks=0",
        "UPDATE app.ingestion_environment SET max_active_chunks=65",
        "UPDATE app.ingestion_environment SET upstream_slots=0",
        "UPDATE app.ingestion_environment SET upstream_slots=17",
        "INSERT INTO app.processing_ticket(id,run_id,chunk_id,control_epoch,fence,kind) "
        f"VALUES(gen_random_uuid(),'{RUN}','{CHUNK}',1,1,'serve')",
    ):
        postgres("BEGIN; " + statement + ";", expected=3)
    for value in (1, 64):
        assert postgres(
            f"BEGIN; UPDATE app.ingestion_environment SET max_active_chunks={value}; "
            "SELECT max_active_chunks FROM app.ingestion_environment; ROLLBACK;"
        ) == str(value)


@pytest.mark.integration
def test_0012_ticket_function_has_one_form_and_defaults_to_process(postgres):
    assert (
        postgres(
            "SELECT count(*) FROM pg_proc WHERE proname='processing_ticket' "
            "AND pronamespace='app'::regnamespace"
        )
        == "1"
    )
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT app.processing_ticket('{RUN}','{CHUNK}',1,1);
      SELECT kind FROM app.processing_ticket WHERE chunk_id='{CHUNK}';
      ROLLBACK;""")
    assert result.splitlines()[-1] == "process"
    postgres(f"BEGIN; {CLAIM} SELECT {ticket('serve')};", expected=3)


@pytest.mark.integration
def test_0012_ticket_creation_still_asserts_the_fenced_claim(postgres):
    postgres(
        f"BEGIN; {CLAIM} SELECT app.processing_ticket('{RUN}','{CHUNK}',1,9,'acquire');", expected=3
    )
    postgres(f"BEGIN; SELECT {ticket('acquire')};", expected=3)  # never claimed


# claim_ticket --------------------------------------------------------------------------


@pytest.mark.integration
def test_claim_ticket_hands_a_ticket_to_exactly_one_worker(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      CREATE TEMP TABLE issued AS SELECT {ticket("acquire")} AS id;
      SELECT 'first|'||(app.claim_ticket('acquire','worker-a')).claimed_by;
      SELECT 'second|'||coalesce((app.claim_ticket('acquire','worker-b')).claimed_by,'empty');
      SELECT 'row|'||claimed_by||'|'||{yes("claimed_at IS NOT NULL")}||'|'||{yes("started")}
        FROM app.processing_ticket WHERE id=(SELECT id FROM issued);
      ROLLBACK;""")
    assert result.splitlines()[-3:] == ["first|worker-a", "second|empty", "row|worker-a|yes|no"]


@pytest.mark.integration
def test_claim_ticket_on_an_empty_queue_returns_a_row_without_id(postgres):
    assert postgres("SELECT (app.claim_ticket('process','worker')).id IS NULL") == "t"
    postgres("SELECT app.claim_ticket('execute','worker')", expected=3)
    postgres("SELECT app.claim_ticket('process','')", expected=3)


@pytest.mark.integration
def test_claim_ticket_routes_by_kind_and_hands_over_under_one_fence(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      SELECT 'process-empty|'||{yes("(app.claim_ticket('process','p')).id IS NULL")};
      SELECT 'acquire|'||(app.claim_ticket('acquire','a')).kind;
      -- phase hand-over: the same epoch and fence, another kind, no extra claim
      CREATE TEMP TABLE handover AS SELECT {ticket("process")} AS id;
      CREATE TEMP TABLE again AS SELECT {ticket("process")} AS id;
      SELECT 'idempotent|'||{yes("(SELECT id FROM handover)=(SELECT id FROM again)")};
      SELECT 'process|'||(app.claim_ticket('process','p')).kind;
      SELECT 'claims|'||processing_claims FROM app.ingestion_chunk WHERE id='{CHUNK}';
      SELECT 'tickets|'||count(*) FROM app.processing_ticket WHERE chunk_id='{CHUNK}';
      ROLLBACK;""")
    assert result.splitlines()[-6:] == [
        "process-empty|yes",
        "acquire|acquire",
        "idempotent|yes",
        "process|process",
        "claims|1",
        "tickets|2",
    ]


@pytest.mark.integration
def test_start_worker_admits_one_executor_and_removes_the_ticket_from_the_queue(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      CREATE TEMP TABLE issued AS SELECT {ticket("process")} AS id;
      SELECT 'claimed|'||(app.claim_ticket('process','a')).claimed_by;
      SELECT 'start1|'||{yes("app.start_worker((SELECT id FROM issued))")};
      SELECT 'start2|'||{yes("app.start_worker((SELECT id FROM issued))")};
      SELECT 'after|'||coalesce((app.claim_ticket('process','b')).claimed_by,'empty');
      ROLLBACK;""")
    assert result.splitlines()[-4:] == ["claimed|a", "start1|yes", "start2|no", "after|empty"]


@pytest.mark.integration
def test_unstarted_claim_is_handed_out_again_only_after_two_minutes(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("process")};
      SELECT app.claim_ticket('process','lost');
      SELECT 'fresh|'||coalesce((app.claim_ticket('process','b')).claimed_by,'empty');
      UPDATE app.processing_ticket SET claimed_at=clock_timestamp()-interval '3 minutes';
      SELECT 'stale|'||(app.claim_ticket('process','b')).claimed_by;
      ROLLBACK;""")
    assert result.splitlines()[-2:] == ["fresh|empty", "stale|b"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalidate",
    [
        # lease lapsed: the controller will re-claim under a new fence
        EXPIRE_LEASE,
        # chunk re-claimed (new fence/epoch): the old ticket can no longer pass start_worker
        f"UPDATE app.ingestion_chunk SET fence=fence+1 WHERE id='{CHUNK}';",
        f"UPDATE app.ingestion_chunk SET control_epoch=2 WHERE id='{CHUNK}';",
        f"UPDATE app.ingestion_chunk SET state='failed' WHERE id='{CHUNK}';",
        f"UPDATE app.ingestion_run SET control_epoch=2 WHERE id='{RUN}';",
        f"UPDATE app.ingestion_run SET cancellation_requested_at=clock_timestamp() "
        f"WHERE id='{RUN}';",
        f"UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()"
        f"-interval '1 second' WHERE id='{RUN}';",
    ],
)
def test_claim_ticket_never_hands_out_a_ticket_start_worker_would_refuse(postgres, invalidate):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      SELECT 'before|'||{yes("(app.claim_ticket('acquire','x')).id IS NOT NULL")};
      UPDATE app.processing_ticket SET claimed_by=NULL,claimed_at=NULL;
      {invalidate}
      SELECT 'after|'||{yes("(app.claim_ticket('acquire','x')).id IS NULL")};
      ROLLBACK;""")
    assert result.splitlines()[-2:] == ["before|yes", "after|yes"]


@pytest.mark.integration
def test_claim_ticket_serves_oldest_first(postgres):
    result = postgres(f"""BEGIN;
      {chunk(OTHER, "second")}
      SELECT app.claim_chunk('{RUN}','{OTHER}',1);
      {CLAIM}
      SELECT {ticket("acquire", OTHER)};
      SELECT {ticket("acquire")};
      SELECT 'oldest|'||{yes(f"(app.claim_ticket('acquire','a')).chunk_id='{OTHER}'")};
      ROLLBACK;""")
    assert result.splitlines()[-1] == "oldest|yes"


@pytest.mark.integration
def test_claim_ticket_skips_a_locked_row_instead_of_waiting_for_it(postgres):
    holder = None
    try:
        postgres(
            chunk(OTHER, "locked")
            + chunk(THIRD, "free")
            + f"SELECT app.claim_chunk('{RUN}','{OTHER}',1);"
            + f"SELECT app.claim_chunk('{RUN}','{THIRD}',1);"
            + f"SELECT {ticket('acquire', OTHER)};"
            + "SELECT pg_sleep(0.05);"
            + f"SELECT {ticket('acquire', THIRD)};"
        )
        # A second session holds the oldest ticket's row lock, as a claimant mid-transaction.
        holder = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                postgres.container_name,
                "psql",
                "-X",
                "-q",
                "-t",
                "-A",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert holder.stdin is not None
        holder.stdin.write(
            "BEGIN; SELECT id FROM app.processing_ticket "
            f"WHERE chunk_id='{OTHER}' FOR UPDATE; SELECT pg_sleep(25); ROLLBACK;\n"
        )
        holder.stdin.flush()
        deadline = time.monotonic() + 15
        while (
            postgres(
                "SELECT count(*) FROM pg_stat_activity WHERE state='active' "
                "AND query LIKE '%pg_sleep(25)%' AND pid<>pg_backend_pid()"
            )
            == "0"
        ):
            assert time.monotonic() < deadline, "lock holder never started"
            time.sleep(0.2)
        started = time.monotonic()
        claimed = postgres("SELECT (app.claim_ticket('acquire','a')).chunk_id")
        empty = postgres("SELECT (app.claim_ticket('acquire','b')).id IS NULL")
        elapsed = time.monotonic() - started
        assert claimed == THIRD and empty == "t"
        assert elapsed < 15, "claim_ticket waited for a locked row"
    finally:
        # Release the lock first: killing the docker client does not end the server session.
        postgres(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE query LIKE '%pg_sleep(25)%' AND pid<>pg_backend_pid()"
        )
        if holder is not None:
            holder.kill()
            holder.wait(timeout=10)
        postgres(
            f"DELETE FROM app.processing_ticket WHERE chunk_id IN ('{OTHER}','{THIRD}');"
            f"DELETE FROM app.ingestion_event WHERE chunk_id IN ('{OTHER}','{THIRD}');"
            f"DELETE FROM app.ingestion_chunk WHERE id IN ('{OTHER}','{THIRD}');"
        )


# extend_unstarted_leases ---------------------------------------------------------------

SHORT_LEASE = (
    "UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()+interval '1 minute' "
    f"WHERE id='{CHUNK}';"
)
EXTEND = f"app.extend_unstarted_leases('{RUN}',1)"


def lease_extended(chunk_id=CHUNK):
    """yes when the chunk's lease is now about a full 10 minute TTL, no when it is untouched."""
    return yes(
        f"(SELECT lease_until FROM app.ingestion_chunk WHERE id='{chunk_id}')"
        " > clock_timestamp()+interval '9 minutes'"
    )


@pytest.mark.integration
def test_extend_unstarted_leases_renews_a_chunk_waiting_for_a_worker(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      {SHORT_LEASE}
      SELECT 'before|'||{lease_extended()};
      SELECT 'count|'||{EXTEND};
      SELECT 'after|'||{lease_extended()};
      SELECT 'claims|'||processing_claims||'|fence|'||fence FROM app.ingestion_chunk
        WHERE id='{CHUNK}';
      ROLLBACK;""")
    assert result.splitlines()[-4:] == ["before|no", "count|1", "after|yes", "claims|1|fence|1"]


@pytest.mark.integration
def test_extend_unstarted_leases_covers_a_claimed_ticket_nobody_started_and_the_handover(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      CREATE TEMP TABLE acquired AS SELECT {ticket("acquire")} AS id;
      SELECT 'claim|'||(app.claim_ticket('acquire','a')).claimed_by;
      SELECT 'start|'||{yes("app.start_worker((SELECT id FROM acquired))")};
      CREATE TEMP TABLE handover AS SELECT {ticket("process")} AS id;
      {SHORT_LEASE}
      SELECT 'count|'||{EXTEND};
      SELECT 'after|'||{lease_extended()};
      ROLLBACK;""")
    # The acquire ticket is started, the same-fence process ticket is waiting: still extended.
    assert result.splitlines()[-4:] == ["claim|a", "start|yes", "count|1", "after|yes"]


@pytest.mark.integration
def test_extend_unstarted_leases_ignores_a_started_ticket(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      CREATE TEMP TABLE issued AS SELECT {ticket("acquire")} AS id;
      SELECT app.start_worker((SELECT id FROM issued));
      {SHORT_LEASE}
      SELECT 'count|'||{EXTEND};
      SELECT 'after|'||{lease_extended()};
      ROLLBACK;""")
    assert result.splitlines()[-2:] == ["count|0", "after|no"]


@pytest.mark.integration
def test_extend_unstarted_leases_ignores_a_ticket_of_a_superseded_fence(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      {EXPIRE_LEASE}
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      {SHORT_LEASE}
      SELECT 'fence|'||fence FROM app.ingestion_chunk WHERE id='{CHUNK}';
      SELECT 'count|'||{EXTEND};
      SELECT 'after|'||{lease_extended()};
      ROLLBACK;""")
    # Only the fence-1 ticket exists; the chunk is at fence 2.
    assert result.splitlines()[-3:] == ["fence|2", "count|0", "after|no"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalidate",
    [
        # a lapsed lease is recovered by a budgeted claim, never revived
        EXPIRE_LEASE,
        f"UPDATE app.ingestion_chunk SET state='failed' WHERE id='{CHUNK}';",
        f"UPDATE app.ingestion_chunk SET control_epoch=2 WHERE id='{CHUNK}';",
        f"UPDATE app.ingestion_run SET control_epoch=2 WHERE id='{RUN}';",
        "UPDATE app.ingestion_run SET cancellation_requested_at=clock_timestamp() "
        f"WHERE id='{RUN}';",
        "UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()"
        f"-interval '1 second' WHERE id='{RUN}';",
    ],
)
def test_extend_unstarted_leases_never_revives_or_extends_what_authority_would_refuse(
    postgres, invalidate
):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      {SHORT_LEASE}
      {invalidate}
      SELECT 'count|'||{EXTEND};
      SELECT 'after|'||{lease_extended()};
      ROLLBACK;""")
    assert result.splitlines()[-2:] == ["count|0", "after|no"]


@pytest.mark.integration
def test_extend_unstarted_leases_counts_every_waiting_chunk_of_the_run(postgres):
    result = postgres(f"""BEGIN;
      {chunk(OTHER, "second")}
      {CLAIM}
      SELECT app.claim_chunk('{RUN}','{OTHER}',1);
      SELECT {ticket("acquire")};
      SELECT {ticket("acquire", OTHER)};
      UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()+interval '1 minute';
      SELECT 'count|'||{EXTEND};
      SELECT 'both|'||{lease_extended()}||{lease_extended(OTHER)};
      ROLLBACK;""")
    assert result.splitlines()[-2:] == ["count|2", "both|yesyes"]


@pytest.mark.integration
def test_extend_unstarted_leases_privileges(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT {ticket("acquire")};
      SET LOCAL ROLE floatchat_ingestor;
      SELECT 'ingestor|'||{EXTEND};
      ROLLBACK;""")
    assert result.splitlines()[-1] == "ingestor|1"
    postgres(
        "BEGIN; GRANT USAGE ON SCHEMA app TO floatchat_app; "
        f"SET LOCAL ROLE floatchat_app; SELECT {EXTEND};",
        expected=3,
    )


# claim_chunk and the environment bound -------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("limit", [1, 2, 3])
def test_claim_chunk_enforces_the_environment_max_active_chunks(postgres, limit):
    result = postgres(
        f"BEGIN; UPDATE app.ingestion_environment SET max_active_chunks={limit};"
        + claim_attempts(limit + 2)
        + "ROLLBACK;"
    )
    assert result.splitlines()[-1] == f"{limit}|environment_concurrency_limit"


@pytest.mark.integration
def test_claim_chunk_default_bound_is_eight_and_the_stage1_v3_two_is_gone(postgres):
    result = postgres("BEGIN;" + claim_attempts(10) + "ROLLBACK;")
    assert result.splitlines()[-1] == "8|environment_concurrency_limit"


@pytest.mark.integration
def test_claim_chunk_keeps_its_claim_budget_fencing_and_error_categories(postgres):
    result = postgres(f"""BEGIN;
      SELECT 'first|'||app.claim_chunk('{RUN}','{CHUNK}',1);
      {EXPIRE_LEASE}
      SELECT 'second|'||app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT 'claims|'||processing_claims FROM app.ingestion_chunk WHERE id='{CHUNK}';
      UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()-interval '1 second',
        processing_claims=4 WHERE id='{CHUNK}';
      CREATE TEMP TABLE outcome(message text);
      DO $$ BEGIN
        PERFORM app.claim_chunk('{RUN}','{CHUNK}',1);
        INSERT INTO outcome VALUES('granted');
      EXCEPTION WHEN OTHERS THEN INSERT INTO outcome VALUES(SQLERRM);
      END $$;
      SELECT 'budget|'||message FROM outcome;
      ROLLBACK;""")
    assert result.splitlines()[-4:] == ["first|1", "second|2", "claims|2", "budget|claim_denied"]


# Attempt origin 'cache' ---------------------------------------------------------------


@pytest.mark.integration
def test_cache_hits_may_record_an_attempt_of_origin_cache(postgres):
    attempt = uuid.uuid4()
    result = postgres(f"""BEGIN;
      {CLAIM}
      SELECT app.reserve_recorded_attempt('{RUN}','{CHUNK}',1,1,'{attempt}','metadata-key',
        'metadata','{{}}','cache');
      SELECT 'origin|'||origin FROM app.ingestion_attempt WHERE id='{attempt}';
      ROLLBACK;""")
    assert result.splitlines()[-1] == "origin|cache"


@pytest.mark.integration
def test_recorded_attempts_still_refuse_http_and_unknown_origins(postgres):
    for origin in ("http", "other"):
        postgres(
            f"BEGIN; {CLAIM} SELECT app.reserve_recorded_attempt('{RUN}','{CHUNK}',1,1,"
            f"'{uuid.uuid4()}','k','metadata','{{}}','{origin}');",
            expected=3,
        )
    postgres(
        "BEGIN; INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,"
        f"request_attempt,role,request_parameters,origin) VALUES('{uuid.uuid4()}','{CHUNK}',1,'k',"
        "1,'metadata','{}','other');",
        expected=3,
    )
    for origin in ("http", "captured", "replay", "cache"):
        postgres(
            "BEGIN; INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,"
            f"logical_request_key,request_attempt,role,request_parameters,origin) "
            f"VALUES('{uuid.uuid4()}','{CHUNK}',1,'k',1,'metadata','{{}}','{origin}'); ROLLBACK;"
        )


# Metadata cache ------------------------------------------------------------------------


@pytest.mark.integration
def test_metadata_cache_put_upserts_and_only_moves_forward(postgres):
    day = "to_char(retrieved_at AT TIME ZONE 'UTC','YYYY-MM-DD')"
    result = postgres(
        "BEGIN;"
        + MANIFEST
        + put("2025-02-01T00:00:00Z")
        + f"SELECT 'first|'||{day} FROM app.float_metadata_cache;"
        + put("2025-01-01T00:00:00Z")
        + f"SELECT 'older|'||{day} FROM app.float_metadata_cache;"
        + put("2025-03-01T00:00:00Z")
        + f"SELECT 'newer|'||{day}||'|'||(SELECT count(*) FROM app.float_metadata_cache) "
        "FROM app.float_metadata_cache;"
        "ROLLBACK;"
    )
    assert result.splitlines()[-3:] == [
        "first|2025-02-01",
        "older|2025-02-01",
        "newer|2025-03-01|1",
    ]


@pytest.mark.integration
def test_metadata_cache_put_refuses_a_manifest_of_another_run_or_environment(postgres):
    unknown = uuid.uuid4()
    when = "'2025-02-01T00:00:00Z'"
    for arguments in (
        f"'{ENV}','float-1','{unknown}','{RUN}'",  # no such manifest
        f"'{ENV}','float-1','{RAW}','{unknown}'",  # the manifest belongs to RUN
        f"'{unknown}','float-1','{RAW}','{RUN}'",  # another environment
        f"'{ENV}','','{RAW}','{RUN}'",  # empty pointer
    ):
        postgres(
            f"BEGIN; {MANIFEST} SELECT app.metadata_cache_put({arguments},{when});", expected=3
        )


@pytest.mark.integration
def test_metadata_cache_references_are_restrictive(postgres):
    assert (
        postgres(
            "SELECT string_agg(confrelid::regclass::text||'|'||confdeltype::text,',' ORDER BY "
            "confrelid::regclass::text) FROM pg_constraint "
            "WHERE conrelid='app.float_metadata_cache'::regclass AND contype='f'"
        )
        == "app.ingestion_environment|r,app.ingestion_run|r,app.raw_manifest|r"
    )


# Privileges ----------------------------------------------------------------------------


@pytest.mark.integration
def test_ingestor_reaches_the_queue_only_through_the_security_definer_functions(postgres):
    result = postgres(f"""BEGIN;
      {CLAIM}
      {MANIFEST}
      SET LOCAL ROLE floatchat_ingestor;
      SELECT {ticket("acquire")};
      SELECT 'claim|'||(app.claim_ticket('acquire','w')).claimed_by;
      {put("2025-02-01T00:00:00Z")}
      SELECT 'cache|'||count(*) FROM app.float_metadata_cache;
      SELECT 'bound|'||max_active_chunks FROM app.ingestion_environment;
      ROLLBACK;""")
    assert result.splitlines()[-3:] == ["claim|w", "cache|1", "bound|8"]
    for statement in (
        "UPDATE app.processing_ticket SET started=true",
        "DELETE FROM app.processing_ticket",
        f"INSERT INTO app.float_metadata_cache VALUES('{ENV}','x','{RAW}','{RUN}',now())",
        "UPDATE app.float_metadata_cache SET retrieved_at=now()",
        "UPDATE app.ingestion_environment SET max_active_chunks=64",
    ):
        postgres(f"BEGIN; {MANIFEST} SET LOCAL ROLE floatchat_ingestor; {statement};", expected=3)


@pytest.mark.integration
def test_application_role_cannot_use_or_read_the_queue_or_cache(postgres):
    for statement in (
        "SELECT app.claim_ticket('acquire','w')",
        f"SELECT {ticket('acquire')}",
        f"SELECT app.metadata_cache_put('{ENV}','x','{RAW}','{RUN}',now())",
        "SELECT count(*) FROM app.float_metadata_cache",
        "SELECT count(*) FROM app.processing_ticket",
    ):
        postgres(
            "BEGIN; GRANT USAGE ON SCHEMA app TO floatchat_app; "
            f"SET LOCAL ROLE floatchat_app; {statement};",
            expected=3,
        )


def test_manifest_fragment_is_the_attempt_and_raw_manifest_only():
    assert MANIFEST.count("INSERT INTO") == 2
    assert ATTEMPT in MANIFEST and RAW in MANIFEST and "argo_float" not in MANIFEST
