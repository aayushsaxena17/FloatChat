"""Actual migration-0007 closing, with 1260 administrative state-model rows.

The scientific fixture is deliberately small, not a clone of owner scientific
values or objects. No original container, database, credential or live input.
"""

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import test_database
from test_database import CHUNK, ENV, PARTITION, PROFILE, RUN, SCIENCE

# The 0007-era schema still carries core_measurement.canonical_level (dropped by 0013).
MEASUREMENT = f"""
INSERT INTO app.core_measurement(observation_month,profile_id,level_index,pressure,
  pressure_unit,pressure_data_mode,pressure_flags,temperature_flags,salinity_flags,canonical_level)
VALUES('2025-01-01','{PROFILE}',0,1,'dbar','R','[]','[]','[]','{{}}');
"""

disposable_postgres = test_database.postgres

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.stage1_terminalize import definition_pins, finalization_sql  # noqa: E402


def interrupt_connection(postgres, database, source):
    application = "offline-terminal-fault-" + uuid.uuid4().hex
    client = subprocess.Popen(
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
            database,
            "-v",
            "ON_ERROR_STOP=1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert client.stdin is not None
    client.stdin.write("SET application_name='" + application + "';" + source)
    client.stdin.close()
    until = time.monotonic() + 15
    while True:
        pid = postgres(
            "SELECT pid FROM pg_stat_activity WHERE application_name='"
            + application
            + "' AND wait_event='PgSleep';",
            database=database,
        )
        if pid:
            break
        assert time.monotonic() < until, "disposable fault hook did not reach wait"
        time.sleep(0.1)
    assert pid.isdigit()
    assert postgres("SELECT pg_terminate_backend(" + pid + ");", database=database) == "t"
    client.stdin = None
    client.communicate(timeout=10)
    assert client.returncode != 0


def read_state(postgres, database):
    return json.loads(
        postgres(
            f"""SELECT jsonb_build_object(
      'run',(SELECT to_jsonb(r) FROM app.ingestion_run r WHERE id='{RUN}'),
      'science',app.scientific_snapshot(),
      'chunks',(SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM app.ingestion_chunk c),
      'frozen',(SELECT coalesce(jsonb_agg(evidence),'[]'::jsonb) FROM app.run_final_evidence),
      'active_ids',(SELECT coalesce(jsonb_agg(id::text ORDER BY id::text),'[]'::jsonb)
        FROM app.committed_active_partitions),
      'catalogue',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.id),'[]'::jsonb)
        FROM app.dataset_partition p),
      'attempts',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.id),'[]'::jsonb)
        FROM app.ingestion_attempt a),
      'intents',(SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY i.id),'[]'::jsonb)
        FROM app.publication_intent i),
      'states',(SELECT jsonb_object_agg(state,n) FROM
         (SELECT state,count(*) n FROM app.ingestion_chunk GROUP BY state) s));""",
            database=database,
        )
    )


@pytest.mark.integration
def test_exact_0007_1260_state_terminalization_before_after_commit_and_repeat(disposable_postgres):
    postgres = disposable_postgres
    database = "terminal_rehearsal"
    postgres("CREATE DATABASE " + database)
    postgres(
        "CREATE SCHEMA app; CREATE EXTENSION postgis; CREATE EXTENSION vector;", database=database
    )
    files = sorted((ROOT / "infra/migrations/versions").glob("*.sql"))
    for file in files:
        if file.name[:4] in {"0002", "0003", "0004", "0005", "0006", "0007"}:
            postgres(file.read_text(), database=database)
    postgres(
        "CREATE TABLE public.alembic_version(version_num text);"
        "INSERT INTO public.alembic_version VALUES('0007_http_replay');"
        "GRANT SELECT ON public.alembic_version TO floatchat_ingestor;",
        database=database,
    )
    seed = f"""
      INSERT INTO app.ingestion_environment VALUES('{ENV}','test','acceptance',true,
        'test','test','test');
      INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,
        created_at_actual_utc,requested_start,requested_end,geometry_version,geometry_sha256,
        policy_versions,limits,controller_lease_until,work_deadline,deadline,canonical_bytes,state)
      VALUES('{RUN}','{ENV}','acceptance','2025-04-01',now()-interval '7 hours',
        '2025-01-01','2025-04-01','indian-ocean-v1',repeat('a',64),'{{}}',
        '{{"canonical_bytes":10737418240}}',now()-interval '2 hours',
        now()-interval '61 minutes',now()-interval '1 hour',10721657712,'validating');
      INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,requested_end,
        tile,plan_version,state,reason,completed_at,fence)
      SELECT CASE WHEN n=1 THEN '{CHUNK}'::uuid ELSE gen_random_uuid() END,'{RUN}',n::text,
        '2025-01-01','2025-01-08','{{"west":70,"south":10,"width":10,"height":10}}',
        'synthetic-terminal-state-model',
        CASE WHEN n<=120 THEN 'complete' WHEN n<=164 THEN 'failed'
          WHEN n<=172 THEN 'quarantined' ELSE 'planned' END,
        CASE WHEN n<=120 THEN 'committed_model' WHEN n<=164 THEN 'upstream_http_status'
          WHEN n<=168 THEN 'upstream_data_warning' WHEN n<=172 THEN 'canonical_output_limit'
          ELSE NULL END,
        CASE WHEN n<=120 THEN now()-interval '2 hours' ELSE NULL END,
        CASE WHEN n<=172 THEN 1 ELSE 0 END
      FROM generate_series(1,1260) n;
      {SCIENCE} {PARTITION} {MEASUREMENT}
      UPDATE app.ingestion_attempt SET disposition='verified_raw',finished_at=now();
      INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,
        request_attempt,role,request_parameters,http_status,disposition,finished_at,error_category)
      SELECT gen_random_uuid(),id,1,id::text,1,'inventory_before','{{}}',404,'http_failure',now(),
        'upstream_http_status' FROM app.ingestion_chunk WHERE state='failed';
      INSERT INTO app.publication_intent(id,chunk_id,fence,control_epoch,status,
        object_references,expected_bases,expected_revisions)
      SELECT gen_random_uuid(),id,1,1,'prepared','["synthetic-unpublished-object"]','{{}}','{{}}'
        FROM app.ingestion_chunk WHERE state='planned' LIMIT 1;
      INSERT INTO app.logical_partition_slot VALUES('{ENV}','synthetic-terminal-slot',
        '2025-01-01','70:10',1,'[]');
      INSERT INTO app.publication_intent(id,chunk_id,fence,control_epoch,status,
        object_references,expected_bases,expected_revisions)
      VALUES('00000000-0000-4000-8000-000000000077','{CHUNK}',1,1,'committed','[]','{{}}','{{}}');
      INSERT INTO app.dataset_partition(id,environment_id,logical_key,generation,slot_version,
        status,intent_id,run_id,chunk_id,object_key,sha256,bytes,row_count,profile_count,
        schema_sha256,geometry_version,geometry_sha256,versions,membership_manifest,
        verified_at,verification_evidence,committed_at)
      VALUES(gen_random_uuid(),'{ENV}','synthetic-terminal-slot',1,1,'active',
        '00000000-0000-4000-8000-000000000077','{RUN}','{CHUNK}',
        'normalised/sha256/'||repeat('d',64)||'.parquet',repeat('d',64),12,1,1,
        repeat('e',64),'indian-ocean-v1',repeat('a',64),'{{}}',
        '[{{"profile_id":"{PROFILE}","hash":"{"c" * 64}","levels":1}}]',
        now(),'{{"synthetic_state_model":true}}',now());
    """
    postgres(seed, database=database)
    before = read_state(postgres, database)
    assert before["states"] == {"complete": 120, "failed": 44, "quarantined": 8, "planned": 1088}
    assert (
        postgres(
            f"SELECT clock_timestamp()>deadline FROM app.ingestion_run WHERE id='{RUN}';",
            database=database,
        )
        == "t"
    )
    run = before["run"]
    expected = {
        "database": database,
        "run": RUN,
        "environment": ENV,
        "project": "test",
        "bucket": "test",
        "queue": "test",
        "reference_time": run["run_reference_time_utc"],
        "work_deadline": run["work_deadline"],
        "deadline": run["deadline"],
        "canonical_bytes": run["canonical_bytes"],
        "open_state": "validating",
        "control_epoch": run["control_epoch"],
        "original_counters": {
            name: run[name]
            for name in (
                "raw_received_bytes",
                "http_attempts",
                "accepted_profiles",
                "accepted_levels",
                "controller_claims",
            )
        },
        "science": {
            k: before["science"][k]
            for k in (
                "profiles",
                "measurement_levels",
                "floats",
                "profile_manifest_sha256",
                "active_partitions",
                "active_generation_sha256",
            )
        },
        "chunks": before["chunks"],
        "active_ids": before["active_ids"],
        "functions": definition_pins(),
    }
    # Connection loss before COMMIT: same SQL, intentional rollback; no close,
    # fencing, reason, scientific or frozen evidence change survives.
    assert postgres(finalization_sql(expected, rollback=True), database=database) == "partial"
    assert read_state(postgres, database) == before
    interrupt_connection(
        postgres,
        database,
        finalization_sql(expected).replace("COMMIT;", "SELECT pg_sleep(20); COMMIT;"),
    )
    assert read_state(postgres, database) == before
    interrupt_connection(postgres, database, finalization_sql(expected) + "SELECT pg_sleep(20);")
    committed = read_state(postgres, database)
    assert committed["states"] == {"complete": 120, "failed": 1132, "quarantined": 8}
    assert committed["run"]["closed"] and committed["run"]["state"] == "partial"
    assert committed["run"]["control_epoch"] == run["control_epoch"] + 1
    for name in (
        "canonical_bytes",
        "work_deadline",
        "deadline",
        "limits",
        "http_attempts",
        "raw_received_bytes",
        "accepted_profiles",
        "accepted_levels",
        "controller_claims",
    ):
        assert committed["run"][name] == before["run"][name]
    original_chunks = {c["id"]: c for c in before["chunks"]}
    for chunk in committed["chunks"]:
        prior = original_chunks[chunk["id"]]
        if prior["state"] == "planned":
            assert chunk["state"] == "failed" and chunk["reason"] == "deadline_expired"
            assert chunk["fence"] == prior["fence"] + 1 and chunk["lease_until"] is None
        else:
            assert chunk == prior
    assert len(committed["frozen"]) == 1
    assert before["science"]["active_partitions"] == 1
    assert committed["catalogue"] == before["catalogue"]
    assert committed["attempts"] == before["attempts"]
    assert all(
        after["object_references"] == prior["object_references"]
        for after, prior in zip(committed["intents"], before["intents"], strict=True)
    )
    assert {i["status"] for i in committed["intents"]} == {"abandoned", "committed"}
    for name in (
        "profile_manifest_sha256",
        "active_generation_sha256",
        "profiles",
        "measurement_levels",
        "active_partitions",
    ):
        assert committed["science"][name] == before["science"][name]
    # Simulates a lost acknowledgement after successful COMMIT: it must validate
    # already-closed state against the original saved snapshot, not reject it.
    assert postgres(finalization_sql(expected), database=database) == "partial"
    assert read_state(postgres, database) == committed
    assert (
        postgres(
            "SELECT to_regprocedure('app.resource_limit_snapshot(uuid)') IS NULL;",
            database=database,
        )
        == "t"
    )
    altered = dict(expected, deadline="2099-01-01T00:00:00Z")
    postgres(finalization_sql(altered), database=database, expected=3)
    assert read_state(postgres, database) == committed
    evidence = {
        "kind": "migration_0007_exact_1260_state_shape_rehearsal",
        "migration": "0007_http_replay",
        "before": before["states"],
        "after": committed["states"],
        "database_clock_past_deadline": True,
        "closed": True,
        "state": "partial",
        "completed_failed_quarantine_rows_unchanged": True,
        "planned_fences_incremented": True,
        "scientific_and_catalogue_manifests_unchanged": True,
        "frozen_rows": 1,
        "before_commit_rollback_unchanged": True,
        "before_commit_connection_termination_unchanged": True,
        "after_commit_connection_termination_recognized": True,
        "after_commit_retry_recognized": True,
        "repeat_no_change": True,
        "wrong_identity_refused": True,
        "migration_0008_absent": True,
        "canonical_bytes_unchanged": run["canonical_bytes"],
        "deadline_budget_unchanged": True,
        "finalizer_definition_sha256": definition_pins(),
        "original_database_operated": False,
        "scientific_fixture": "one administrative profile/one level/one active generation; "
        "no authentic object clone",
        "scope": "exact state counts and atomic rollback/commit/retry; "
        "not original-run certification",
    }
    (ROOT / "reports/stage1-terminalization-0007-rehearsal.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )


def test_terminalization_default_refuses_execution_and_has_no_live_imports():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/stage1_terminalize.py"),
            "--session",
            "6f3e7301f9789059",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2 and "review_only" in result.stdout
    source = (ROOT / "scripts/stage1_terminalize.py").read_text()
    for forbidden in (
        "import os",
        "getenv",
        "ARGOVIS_API_KEY",
        "Controller",
        "process_ticket",
        "capture_stage1_fixtures",
        "compose up",
        "docker compose",
    ):
        assert forbidden not in source


def test_reviewed_finalizer_pins_cover_0007_definition_closure():
    pins = definition_pins()
    assert len(pins) == 5 and all(len(value) == 64 for value in pins.values())
    assert "0008" not in finalization_sql({"run": str(uuid.uuid4())})


def test_terminalization_argument_errors_never_echo_untrusted_arguments():
    sentinel = "synthetic-terminal-argument-secret"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/stage1_terminalize.py"),
            "--session",
            "6f3e7301f9789059",
            "--unexpected",
            sentinel,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert sentinel not in result.stdout + result.stderr
    assert result.stderr == "terminalization_arguments_invalid\n"
