"""Real PostgreSQL/PostGIS constraints and fences in an offline disposable DB.

No host ports, mounted source/config, network access or existing volumes are used.
Provision the pinned foundation image separately; tests refuse to pull one.
"""

import copy
import json
import os
import secrets
import subprocess
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from derivative_evidence import core_null, descending, persist
from floatchat_core.ingestion.argovis import map_profile, policy_versions
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
from floatchat_core.ingestion.planning import (
    GEOMETRY_SHA256,
    Interval,
    PlannedChunk,
    plan,
    timestamp,
)
from floatchat_core.ingestion.workflow import owner_slot, staged_candidate

ROOT = Path(__file__).resolve().parents[2]
RUN = "00000000-0000-4000-8000-000000000001"
CHUNK = "00000000-0000-4000-8000-000000000002"
ENV = "00000000-0000-4000-8000-000000000003"
ATTEMPT = "00000000-0000-4000-8000-000000000004"
RAW = "00000000-0000-4000-8000-000000000005"
FLOAT = "00000000-0000-4000-8000-000000000006"
PROFILE = "00000000-0000-4000-8000-000000000007"
SECOND_PROFILE = "00000000-0000-4000-8000-0000000000a7"  # sorts after PROFILE
INTENT = "00000000-0000-4000-8000-000000000008"
SEED = f"""
INSERT INTO app.ingestion_environment VALUES('{ENV}','test','acceptance',true,'test','test','test');
INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,
  requested_start,requested_end,geometry_version,geometry_sha256,policy_versions,limits,
  controller_lease_until,work_deadline,deadline)
VALUES('{RUN}','{ENV}','acceptance','2025-04-01','2025-01-01','2025-04-01',
       'indian-ocean-v1',repeat('a',64),'{{}}','{{}}',now()+interval '10 minutes',
       now()+interval '5 hours 59 minutes',now()+interval '6 hours');
INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,
  requested_start,requested_end,tile,plan_version)
VALUES('{CHUNK}','{RUN}','test','2025-01-01','2025-01-07',
  '{{"west":70,"south":10,"width":10,"height":10}}','v1');
"""
SCIENCE = f"""
INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,request_attempt,
  role,request_parameters) VALUES('{ATTEMPT}','{CHUNK}',1,'test',1,'profile','{{}}');
INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,retrieved_at,
  versions,sanitization,application_commit) VALUES('{RAW}','{RUN}','{CHUNK}','{ATTEMPT}',
  'raw/sha256/'||repeat('b',64)||'.json',repeat('b',64),2,now(),'{{}}','{{}}','test');
INSERT INTO app.argo_float VALUES('{FLOAT}','argovis','test-platform');
INSERT INTO app.argo_profile(id,source,source_profile_id,float_id,cycle_number,direction,
  identity_observed_at,observation_segment,fallback_complete,observed_at,observation_month,
  position,content_hash,hash_version,mapping_version,level_count,scientific_content,
  created_run_id,last_scientific_run_id,last_chunk_id,raw_manifest_id)
VALUES('{PROFILE}','argovis','source-id','{FLOAT}',1,'A','2025-01-02','single',true,
  '2025-01-02','2025-01-01',ST_SetSRID(ST_MakePoint(70,10),4326),repeat('c',64),
  'scientific-json-v2','argovis-core-v1',1,'{{}}','{RUN}','{RUN}','{CHUNK}','{RAW}');
"""
MEASUREMENT = f"""
INSERT INTO app.core_measurement(observation_month,profile_id,level_index,pressure,
  pressure_unit,pressure_data_mode,pressure_flags,temperature_flags,salinity_flags)
VALUES('2025-01-01','{PROFILE}',0,1,'dbar','R','[]','[]','[]');
"""
PARTITION = """
CREATE TABLE app.core_measurement_202501 PARTITION OF app.core_measurement
FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
"""


@pytest.mark.integration
def test_C06_same_controller_instance_after_lease_expiry_adopts_new_epoch(postgres):
    instance = uuid.uuid4()
    result = postgres(f"""
      BEGIN;
      SET ROLE floatchat_ingestor;
      SELECT app.start_controller('{RUN}','{instance}');
      RESET ROLE;
      UPDATE app.ingestion_run SET controller_lease_until=clock_timestamp()-interval '1 second'
        WHERE id='{RUN}';
      SET ROLE floatchat_ingestor;
      SELECT app.start_controller('{RUN}','{instance}');
      SELECT control_epoch||'|'||controller_claims FROM app.ingestion_run WHERE id='{RUN}';
      ROLLBACK;
    """)
    assert result.splitlines() == ["1", "2", "2|2"]


@pytest.mark.integration
def test_C05_canonical_reservations_survive_process_loss_without_reset(postgres):
    work = uuid.uuid4()
    result = postgres(f"""
      BEGIN;
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT app.reserve_canonical('{RUN}','{CHUNK}',1,1,'{work}');
      UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()-interval '1 second'
        WHERE id='{CHUNK}';
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT canonical_bytes FROM app.ingestion_run WHERE id='{RUN}';
      SELECT status||'|'||actual_bytes FROM app.canonical_work WHERE id='{work}';
      ROLLBACK;
    """)
    assert [line for line in result.splitlines() if line] == [
        "1",
        "2",
        "16777216",
        "process_loss|16777216",
    ]


@pytest.mark.integration
def test_N08_restricted_run_limit_scope_and_frozen_safe_reporting(postgres):
    work = uuid.uuid4()
    result = postgres(f"""
      BEGIN;
      UPDATE app.ingestion_run SET canonical_bytes=42933912432 WHERE id='{RUN}';
      CREATE FUNCTION pg_temp.capture_limit() RETURNS jsonb LANGUAGE plpgsql AS $body$
      DECLARE detail text;
      BEGIN
        PERFORM app.reserve_canonical('{RUN}','{CHUNK}',1,1,'{work}');
        RAISE EXCEPTION 'expected_budget_rejection';
      EXCEPTION WHEN raise_exception THEN
        IF SQLERRM<>'canonical_output_limit' THEN RAISE; END IF;
        GET STACKED DIAGNOSTICS detail=PG_EXCEPTION_DETAIL;
        RETURN detail::jsonb;
      END $body$;
      SET ROLE floatchat_ingestor;
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','diagnostic_probe','{{}}');
      SELECT pg_temp.capture_limit();
      SELECT canonical_bytes FROM app.ingestion_run WHERE id='{RUN}';
      SELECT count(*) FROM app.canonical_work WHERE id='{work}';
      SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'quarantined','canonical_output_limit',
        jsonb_build_object('resource_limit',pg_temp.capture_limit()));
      SELECT app.finalize_run('{RUN}');
      SELECT evidence->'report_metrics'->'resource_limits'
        FROM app.run_final_evidence WHERE run_id='{RUN}';
      RESET ROLE;
      CREATE TEMP TABLE frozen_before AS SELECT evidence FROM app.run_final_evidence
        WHERE run_id='{RUN}';
      INSERT INTO app.ingestion_event(run_id,chunk_id,control_epoch,reason,evidence)
        VALUES('{RUN}','{CHUNK}',1,'canonical_output_limit',
          '{{"resource_limit":{{"headers":"synthetic-sensitive-sentinel"}}}}');
      SELECT app.capture_final_evidence('{RUN}');
      SELECT (SELECT evidence FROM frozen_before)=
        (SELECT evidence FROM app.run_final_evidence WHERE run_id='{RUN}');
      ROLLBACK;
    """)
    lines = [line for line in result.splitlines() if line]
    detail = json.loads(lines[1])
    assert detail == {
        "scope": "run",
        "operation": "reservation",
        "limit_bytes": 42949672960,
        "used_bytes": 42933912432,
        "requested_bytes": 16777216,
    }
    assert lines[2:5] == ["42933912432", "0", "quarantined"]
    assert json.loads(lines[5])[0]["resource_limit"] == detail
    assert lines[-1] == "t"


@pytest.mark.integration
def test_B03_SQL_resource_detail_rejects_unknown_text_and_extra_fields(postgres):
    valid = {
        "scope": "run",
        "operation": "reservation",
        "limit_bytes": 10737418240,
        "used_bytes": 10721657712,
        "requested_bytes": 16777216,
    }
    assert json.loads(postgres("SELECT app.safe_resource_limit(" + _literal(valid) + ")")) == valid
    for invalid in (
        {**valid, "scope": "https://unexpected.invalid/"},
        {**valid, "headers": "synthetic-sensitive-sentinel"},
        {**valid, "used_bytes": True},
        {**valid, "used_bytes": -1},
        {**valid, "requested_bytes": 2**63},
        None,
    ):
        assert postgres("SELECT app.safe_resource_limit(" + _literal(invalid) + ") IS NULL") == "t"


@pytest.mark.integration
def test_C08_reviewed_deadline_procedure_freezes_partial_without_ingestion(postgres):
    run, done, planned, quarantine, failed = (uuid.uuid4() for _ in range(5))
    result = postgres(f"""
      BEGIN;
      {SCIENCE}
      CREATE TEMP TABLE before_science AS SELECT app.scientific_snapshot() AS value;
      INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,
        created_at_actual_utc,requested_start,requested_end,geometry_version,geometry_sha256,
        policy_versions,limits,controller_lease_until,work_deadline,deadline,canonical_bytes)
      VALUES('{run}','{ENV}','acceptance','2025-04-01',now()-interval '7 hours',
        '2025-01-01','2025-04-01','indian-ocean-v1',repeat('a',64),'{{}}','{{}}',
        now()-interval '2 hours',now()-interval '61 minutes',now()-interval '1 hour',10721657712);
      INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,
        requested_end,tile,plan_version,state,reason,completed_at)
      SELECT id,'{run}',id::text,'2025-01-01','2025-01-07',
        '{{"west":70,"south":10,"width":10,"height":10}}'::jsonb,'synthetic-model',state,
        reason,CASE WHEN state='complete' THEN now()-interval '2 hours' ELSE NULL END
      FROM (VALUES('{done}'::uuid,'complete','committed_model'),
        ('{planned}'::uuid,'planned',NULL),('{quarantine}'::uuid,'quarantined','upstream_data_warning'),
        ('{failed}'::uuid,'failed','http_retry_exhausted')) v(id,state,reason);
      CREATE TEMP TABLE before_deadline AS SELECT work_deadline,deadline FROM app.ingestion_run
        WHERE id='{run}';
      CREATE TEMP TABLE before_complete AS SELECT to_jsonb(c) AS value FROM app.ingestion_chunk c
        WHERE id='{done}';
      SET ROLE floatchat_ingestor;
      SELECT app.finalize_run('{run}','deadline_expired');
      SELECT app.finalize_run('{run}','deadline_expired');
      RESET ROLE;
      SELECT jsonb_build_object('states',(SELECT jsonb_object_agg(state,n) FROM
        (SELECT state,count(*) n FROM app.ingestion_chunk WHERE run_id='{run}' GROUP BY state) s),
        'science_unchanged',(SELECT value->'profile_manifest_sha256' FROM before_science)=
          app.scientific_snapshot()->'profile_manifest_sha256',
        'active_unchanged',(SELECT value->'active_generation_sha256' FROM before_science)=
          app.scientific_snapshot()->'active_generation_sha256',
        'complete_unchanged',(SELECT value FROM before_complete)=
          (SELECT to_jsonb(c) FROM app.ingestion_chunk c WHERE id='{done}'),
        'deadlines_unchanged',(SELECT ROW(work_deadline,deadline) FROM before_deadline)=
          (SELECT ROW(work_deadline,deadline) FROM app.ingestion_run WHERE id='{run}'),
        'canonical_bytes',(SELECT canonical_bytes FROM app.ingestion_run WHERE id='{run}'),
        'frozen_records',(SELECT count(*) FROM app.run_final_evidence WHERE run_id='{run}'),
        'http_attempts',(SELECT http_attempts FROM app.ingestion_run WHERE id='{run}'),
        'closed',(SELECT closed FROM app.ingestion_run WHERE id='{run}'));
      ROLLBACK;
    """)
    rows = [line for line in result.splitlines() if line]
    assert rows[:2] == ["partial", "partial"]
    evidence = json.loads(rows[-1])
    assert evidence == {
        "states": {"complete": 1, "failed": 2, "quarantined": 1},
        "science_unchanged": True,
        "active_unchanged": True,
        "complete_unchanged": True,
        "deadlines_unchanged": True,
        "canonical_bytes": 10721657712,
        "frozen_records": 1,
        "http_attempts": 0,
        "closed": True,
    }
    # Admin-seeded state/science models test the procedure, not authentic input
    # completeness or physical object integrity. The owner run is never opened.
    (ROOT / "reports/stage1-terminalization-rehearsal.json").write_text(
        json.dumps(
            {
                "kind": "disposable_postgresql_deadline_finalizer_model",
                "evidence": evidence,
                "repeat_finalization": "partial",
                "owner_run_operated": False,
                "input": "explicit synthetic administrative states; "
                "not capture or original-run clone",
                "scope": "Existing closing/freeze procedure; zero ingestion or HTTP work",
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.integration
def test_C07_cancellation_before_plan_is_failed_not_verified_empty_coverage(postgres):
    result = postgres(f"""
      BEGIN;
      DELETE FROM app.ingestion_chunk WHERE id='{CHUNK}';
      SET ROLE floatchat_ingestor;
      SELECT app.finalize_run('{RUN}','operator_cancelled');
      SELECT state||'|'||closed||'|'||termination_reason FROM app.ingestion_run WHERE id='{RUN}';
      SELECT count(*) FROM app.coverage_receipt;
      ROLLBACK;
    """)
    assert result.splitlines() == ["failed", "failed|true|operator_cancelled", "0"]


@pytest.fixture(autouse=True)
def fresh_seed_controller_for_independent_case(postgres):
    """Each rollback-based SQL case gets its own initial controller lease.

    The module shares a disposable server for speed. A slow separate processor
    probe must not consume the next case's ten-minute seed lease. This resets
    only test initial conditions, never a work deadline, budget or real/model run.
    Expiry/fencing tests still explicitly expire the lease inside their own case.
    """
    postgres(
        f"UPDATE app.ingestion_run SET controller_lease_until="
        f"clock_timestamp()+interval '10 minutes' WHERE id='{RUN}';"
    )


@pytest.fixture(scope="module")
def postgres():
    image = os.environ.get("STAGE1_POSTGRES_IMAGE", "floatchat-stage0-wsl-dev-db:latest")
    assert (
        subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=20
        ).returncode
        == 0
    ), "Prepare STAGE1_POSTGRES_IMAGE separately: offline tests never pull images"
    name = "floatchat-stage1-offline-" + uuid.uuid4().hex
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--network=none",
            "--memory=1g",
            "--name",
            name,
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                result = subprocess.run(
                    ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
                    capture_output=True,
                    timeout=5,
                )
            except subprocess.TimeoutExpired:
                assert time.monotonic() < deadline, "Disposable database readiness deadline"
                continue
            if result.returncode == 0:
                break
            assert time.monotonic() < deadline, "Disposable database did not become ready"
            time.sleep(0.25)

        def execute(source, *, expected=0, database="postgres", timeout=30):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    name,
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
                input=source,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            assert result.returncode == expected, result.stderr
            return result.stdout.strip()

        execute(
            "CREATE EXTENSION postgis; CREATE EXTENSION vector; CREATE SCHEMA app; "
            "CREATE TABLE app.stage0_sentinel(value text); "
            "INSERT INTO app.stage0_sentinel VALUES('preserved'); "
            "CREATE ROLE floatchat_app NOLOGIN; "
            "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO floatchat_app;"
        )
        for migration in sorted((ROOT / "infra/migrations/versions").glob("*.sql")):
            execute(migration.read_text())
        execute(SEED)
        execute.container_name = name
        yield execute
    finally:
        # Only the exact newly-created UUID-named test container/anonymous volume.
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=True,
            capture_output=True,
            timeout=30,
        )


@pytest.mark.integration
def test_B09_additive_migration_and_extensions(postgres):
    assert postgres("SELECT value FROM app.stage0_sentinel") == "preserved"
    assert (
        postgres("SELECT count(*) FROM pg_extension WHERE extname IN ('postgis','vector')") == "2"
    )


@pytest.mark.integration
def test_F02_retry_ledger_replaces_obsolete_ordinals_and_counts(postgres):
    items = [
        {
            "index": 0,
            "identity": "id:one",
            "outcome": "blocked_uncommitted",
            "levels": 3,
            "hash": None,
            "evidence": {},
        },
        {
            "index": 1,
            "identity": "id:two",
            "outcome": "blocked_uncommitted",
            "levels": 4,
            "hash": None,
            "evidence": {},
        },
    ]
    updated = [{**items[0], "levels": 2, "outcome": "outside_time"}]
    result = postgres(f"""
      BEGIN;
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT app.record_profile_outcomes('{RUN}','{CHUNK}',1,1,{_literal(items)});
      SELECT app.record_profile_outcomes('{RUN}','{CHUNK}',1,1,{_literal(updated)});
      SELECT count(*)||'|'||sum(source_levels)||'|'||min(outcome) FROM app.profile_outcome;
      ROLLBACK;
    """)
    assert result.splitlines()[-1] == "1|2|outside_time"


@pytest.mark.integration
def test_P01_P05_R02_B03_F02_F03_F04_F06_F07_combined_processor_publication_replay(postgres):
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    minio = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    name = "floatchat-stage1-processor-minio-" + uuid.uuid4().hex
    for cached in (image, minio):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", cached], capture_output=True, timeout=20
            ).returncode
            == 0
        )
    postgres("CREATE DATABASE processor_probe")
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--memory=1g",
            "--network=container:" + postgres.container_name,
            "--mount",
            f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
            "--env",
            "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/processor_probe",
            image,
            "alembic",
            "-c",
            "infra/alembic.ini",
            "upgrade",
            "head",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    environment = dict(
        os.environ, MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--memory=512m",
            "--network=container:" + postgres.container_name,
            "--name",
            name,
            "--env",
            "MINIO_ROOT_USER",
            "--env",
            "MINIO_ROOT_PASSWORD",
            minio,
            "minio",
            "server",
            "/data",
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--user",
                str(os.getuid()),
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--env",
                "HOME=/tmp/offline-stage1-home",
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/processor_probe",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/packages/core/src:/test/workers/src:"
                "/test/.venv/lib/python3.12/site-packages",
                image,
                "python",
                "/test/tests/stage1/processor_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            logs = subprocess.run(
                ["docker", "logs", postgres.container_name], capture_output=True, timeout=10
            )
            errors = [line for line in logs.stderr.decode().splitlines() if "ERROR:" in line]
            raise AssertionError(str(errors[-5:]) + result.stderr.decode())
        output = result.stdout.splitlines()
        assert output[-1] == b"offline-combined-processor-verified"
        request_evidence = json.loads(output[-2])
        (ROOT / "reports/stage1-http-retry-evidence.json").write_text(
            json.dumps(request_evidence, indent=2) + "\n"
        )
        (ROOT / "reports/stage1-publication-capacity.json").write_text(
            json.dumps(request_evidence["publication_capacity"], indent=2) + "\n"
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            check=True,
            capture_output=True,
            timeout=30,
        )
    assert (
        postgres(
            "SELECT count(*) FROM pg_inherits WHERE inhparent='app.core_measurement'::regclass"
        )
        == "0"
    )


@pytest.mark.integration
def test_B09_actual_alembic_repeat_and_refused_downgrade(postgres):
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    assert (
        subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0
    )
    postgres("CREATE DATABASE migration_probe;")
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--memory=1g",
        "--network=container:" + postgres.container_name,
        "--mount",
        f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
        "--env",
        "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/migration_probe",
        image,
        "alembic",
        "-c",
        "infra/alembic.ini",
    ]
    for _ in range(2):
        result = subprocess.run([*command, "upgrade", "head"], capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode()
    head = sorted(path.stem for path in (ROOT / "infra/migrations/versions").glob("[0-9]*.py"))[-1]
    assert postgres("SELECT version_num FROM alembic_version", database="migration_probe") == head
    result = subprocess.run([*command, "downgrade", "base"], capture_output=True, timeout=60)
    assert result.returncode != 0
    assert b"Downgrade refused" in result.stderr
    assert postgres("SELECT version_num FROM alembic_version", database="migration_probe") == head


@pytest.mark.integration
def test_B07_repeat_bootstrap_cannot_regrant_scientific_writes(postgres):
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    postgres(
        "CREATE ROLE floatchat_admin LOGIN SUPERUSER; "
        "CREATE DATABASE floatchat OWNER floatchat_admin;"
    )
    environment = dict(os.environ, DB_APP_PASSWORD=secrets.token_hex(24))
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--memory=1g",
        "--network=container:" + postgres.container_name,
        "--mount",
        f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
        "--mount",
        f"type=bind,source={ROOT / 'scripts/bootstrap_db.py'},"
        "target=/app/scripts/bootstrap_db.py,readonly",
        "--env",
        "DB_APP_PASSWORD",
        "--env",
        "DATABASE_ADMIN_URL=postgresql://floatchat_admin@127.0.0.1/floatchat",
        image,
        "python",
        "scripts/bootstrap_db.py",
    ]
    for _ in range(2):
        result = subprocess.run(command, env=environment, capture_output=True, timeout=60)
        assert result.returncode == 0, "Restricted bootstrap verification failed"
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_app','app.argo_profile','INSERT,UPDATE,DELETE')",
            database="floatchat",
        )
        == "f"
    )
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_app',"
            "'app.committed_active_partitions','SELECT')",
            database="floatchat",
        )
        == "t"
    )
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_app',"
            "'public.spatial_ref_sys','INSERT,UPDATE,DELETE')",
            database="floatchat",
        )
        == "f"
    )
    postgres(
        "SET ROLE floatchat_admin; CREATE TABLE app.core_measurement_202501 "
        "PARTITION OF app.core_measurement FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');",
        database="floatchat",
    )
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_app',"
            "'app.core_measurement_202501','INSERT,UPDATE,DELETE')",
            database="floatchat",
        )
        == "f"
    )


@pytest.mark.integration
def test_T04_immutable_reference_environment_deadline(postgres):
    assert postgres("SELECT mode,disposable FROM app.ingestion_environment") == "acceptance|t"
    assert (
        postgres(
            "SELECT run_reference_time_utc < created_at_actual_utc "
            f"FROM app.ingestion_run WHERE id='{RUN}'"
        )
        == "t"
    )
    postgres(
        f"BEGIN; UPDATE app.ingestion_run SET run_reference_time_utc=now() WHERE id='{RUN}';",
        expected=3,
    )
    postgres(
        "BEGIN; UPDATE app.ingestion_run SET deadline=deadline+interval '1 second' "
        f"WHERE id='{RUN}';",
        expected=3,
    )
    postgres(
        f"BEGIN; UPDATE app.ingestion_run SET environment_id=gen_random_uuid() WHERE id='{RUN}';",
        expected=3,
    )


@pytest.mark.integration
def test_I01_I04_database_identity_unique(postgres):
    assert (
        postgres(
            "BEGIN;"
            + SCIENCE
            + f"SELECT count(*) FROM app.argo_profile WHERE id='{PROFILE}'; ROLLBACK;"
        )
        == "1"
    )
    postgres(
        "BEGIN;"
        + SCIENCE
        + "INSERT INTO app.argo_profile SELECT gen_random_uuid(),source,source_profile_id,"
        "float_id,cycle_number,direction,identity_observed_at,observation_segment,"
        "fallback_complete,observed_at,observation_month,position,content_hash,hash_version,"
        "mapping_version,level_count,scientific_content,source_revision,created_run_id,"
        "last_scientific_run_id,last_chunk_id,raw_manifest_id "
        f"FROM app.argo_profile WHERE id='{PROFILE}';",
        expected=3,
    )
    postgres(
        "BEGIN;" + SCIENCE + "UPDATE app.argo_profile SET source_profile_id=NULL,cycle_number=NULL,"
        f"fallback_complete=false WHERE id='{PROFILE}';",
        expected=3,
    )


@pytest.mark.integration
def test_I05_partition_fk_and_numeric_constraints(postgres):
    postgres("BEGIN;" + SCIENCE + MEASUREMENT, expected=3)  # No monthly child.
    assert (
        postgres(
            "BEGIN;"
            + SCIENCE
            + PARTITION
            + MEASUREMENT
            + "SELECT count(*) FROM app.core_measurement; ROLLBACK;"
        )
        == "1"
    )
    postgres("BEGIN;" + SCIENCE + PARTITION + MEASUREMENT * 2, expected=3)
    postgres(
        "BEGIN;" + SCIENCE + PARTITION + MEASUREMENT.replace("',0,1,", "',0,'NaN',"), expected=3
    )
    postgres(
        "BEGIN;"
        + SCIENCE
        + PARTITION
        + MEASUREMENT
        + "UPDATE app.core_measurement SET temperature_error=-1;",
        expected=3,
    )
    postgres(
        "BEGIN;"
        + SCIENCE
        + PARTITION
        + MEASUREMENT
        + "UPDATE app.core_measurement SET profile_id=gen_random_uuid(); COMMIT;",
        expected=3,
    )
    postgres(
        "BEGIN;"
        + SCIENCE
        + f"UPDATE app.argo_profile SET observation_month='2025-02-01' WHERE id='{PROFILE}';",
        expected=3,
    )


@pytest.mark.integration
def test_I06_provenance_restrict_and_testonly_cascade(postgres):
    assert (
        postgres(
            "BEGIN;"
            + SCIENCE
            + PARTITION
            + MEASUREMENT
            + f"DELETE FROM app.argo_profile WHERE id='{PROFILE}'; "
            "SELECT count(*) FROM app.core_measurement; ROLLBACK;"
        )
        == "0"
    )
    postgres("BEGIN;" + SCIENCE + f"DELETE FROM app.argo_float WHERE id='{FLOAT}';", expected=3)
    postgres("BEGIN;" + SCIENCE + f"DELETE FROM app.ingestion_run WHERE id='{RUN}';", expected=3)


@pytest.mark.integration
def test_F01_I04_S05_labelled_authentic_pressure_derivative_storage(postgres):
    bundle = ROOT / "tests/fixtures/argovis/recorded/25f21e056e7c4db7bc1e21b0a28ea45f"
    # This labelled derivative uses the helper's JSON-serializable fixture form;
    # _candidate reparses exact JSON decimals before scientific mapping.
    wire = json.loads((bundle / "02-profile.json").read_bytes())[0]
    metadata = json.loads((bundle / "04-metadata.json").read_bytes())[0]
    # Labelled synthetic time/position/pressure changes; immutable capture is untouched.
    wire["timestamp"] = "2025-01-15T00:00:00Z"
    wire["geolocation"]["coordinates"] = [70, 10]
    column = wire["data_info"][0].index("pressure")
    wire["data"][column][1] = wire["data"][column][0]
    profile, candidate = _candidate(wire, {metadata["_id"]: metadata})
    assert "repeated_pressure" in profile.levels[1]["pressure_flags"]
    setup, commit, _, _ = _publishing(profile, candidate)
    result = postgres(
        setup + commit + "SELECT count(*)||'|'||min(level_index)||'|'||max(level_index) "
        "FROM app.core_measurement; "
        "SELECT count(DISTINCT pressure)||'|'||count(*) FROM app.core_measurement "
        "WHERE level_index IN (0,1); "
        "SELECT pressure_flags FROM app.core_measurement WHERE level_index=1; ROLLBACK;"
    )
    assert result.splitlines()[-3:-1] == ["43|0|42", "1|2"]
    assert "repeated_pressure" in result.splitlines()[-1]


@pytest.mark.integration
def test_F01_S01_normalized_error_storage_not_Argovis_parser_support(postgres):
    # Explicit normalized storage values, not invented raw API columns.
    result = postgres(
        "BEGIN;"
        + SCIENCE
        + PARTITION
        + MEASUREMENT
        + "UPDATE app.core_measurement SET pressure_original_error=0.05,pressure_error=0.1,"
        "temperature_original_error=0.03,temperature_error=0.02,"
        "salinity_original_error=0.06,salinity_error=0.04; "
        "SELECT pressure_original_error||'|'||pressure_error||'|'||"
        "temperature_original_error||'|'||temperature_error||'|'||"
        "salinity_original_error||'|'||salinity_error FROM app.core_measurement; ROLLBACK;"
    )
    assert result == "0.05|0.1|0.03|0.02|0.06|0.04"


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["R", "A"])
def test_F01_S01_S03_labelled_present_core_null_restricted_database_publication(postgres, mode):
    raw, metadata, provenance = core_null(mode)
    # Enumerated publication-only synthetic selection changes; no recorded file changes.
    raw["timestamp"] = "2025-01-02T00:00:00Z"
    raw["geolocation"]["coordinates"] = [Decimal("70"), Decimal("10")]
    provenance["mutations"] += [
        {"field": "timestamp", "to": raw["timestamp"]},
        {"field": "geolocation.coordinates", "to": [70, 10]},
    ]
    profile = map_profile(raw, metadata, CanonicalBudget())
    candidate = staged_candidate(profile, uuid.UUID(PROFILE), uuid.UUID(RAW))
    setup, commit, _, _ = _publishing(profile, candidate)
    suffix = "" if mode == "R" else "_adjusted"
    queries = [
        setup,
        "SET LOCAL ROLE floatchat_ingestor;",
        commit,
        "SELECT current_user;",
        "SELECT count(*) FROM app.core_measurement;",
    ]
    for index, variable in enumerate(("pressure", "temperature", "salinity"), start=1):
        queries.append(
            f"SELECT jsonb_build_object('nulls',count(*) FILTER (WHERE {variable}{suffix} IS NULL),"
            f"'present',count(*) FILTER (WHERE {variable}{suffix} IS NOT NULL)) "
            "FROM app.core_measurement;"
        )
        queries.append(
            f"SELECT jsonb_build_object('value',{variable}{suffix},'qc',{variable}{suffix}_qc,"
            f"'unit',{variable}_unit,'mode',{variable}_data_mode,'canonical',"
            f"(SELECT scientific_content->'levels'->{index}->'{variable}{suffix}' "
            f"FROM app.argo_profile)) FROM app.core_measurement "
            f"WHERE level_index={index};"
        )
    queries += ["SELECT scientific_content->'direction' FROM app.argo_profile;", "ROLLBACK;"]
    result = postgres("\n".join(queries)).splitlines()
    assert result[-9:-7] == ["floatchat_ingestor", str(len(profile.levels))]
    for index, variable in enumerate(("pressure", "temperature", "salinity")):
        assert json.loads(result[-7 + index * 2]) == {
            "nulls": 1,
            "present": len(profile.levels) - 1,
        }
        row = json.loads(result[-6 + index * 2])
        assert row["value"] is None and row["qc"] is not None
        assert row["unit"] == profile.levels[index + 1][variable + "_unit"]
        assert row["mode"] == mode
        assert row["canonical"] == {
            "exact": None,
            "missing_reason": "null",
            "nonfinite_kind": None,
            "flags": [],
        }
    assert result[-1] == '"A"'
    persist(
        "core-null-database-" + mode,
        provenance,
        scientific_sha256=profile.content_hash,
        effective_publication_role="floatchat_ingestor",
        rows=len(profile.levels),
        selected_value_nulls_per_core_variable=1,
        canonical_missing_reason="null",
        matching_QC_unit_mode_preserved=True,
    )


@pytest.mark.integration
def test_F01_I01_I02_I03_labelled_descending_database_direction_and_natural_key(postgres):
    raw, metadata, provenance = descending()
    raw["timestamp"] = "2025-01-02T00:00:00Z"
    raw["geolocation"]["coordinates"] = [Decimal("70"), Decimal("10")]
    del raw["_id"]
    provenance["mutations"] += [
        {"field": "timestamp", "to": raw["timestamp"]},
        {"field": "geolocation.coordinates", "to": [70, 10]},
        {"field": "_id", "operation": "remove_for_fallback_identity_test"},
    ]
    profile = map_profile(raw, metadata, CanonicalBudget())
    assert profile.source_profile_id is None and profile.direction == "D"
    candidate = staged_candidate(profile, uuid.UUID(PROFILE), uuid.UUID(RAW))
    setup, commit, _, _ = _publishing(profile, candidate)
    opposite = (
        "INSERT INTO app.argo_profile SELECT gen_random_uuid(),source,NULL,float_id,"
        "cycle_number,'A',identity_observed_at,observation_segment,fallback_complete,"
        "observed_at,observation_month,position,content_hash,hash_version,mapping_version,"
        "level_count,jsonb_set(scientific_content,'{direction}','\"A\"'),source_revision,"
        "created_run_id,last_scientific_run_id,last_chunk_id,raw_manifest_id "
        f"FROM app.argo_profile WHERE id='{PROFILE}';"
    )
    result = postgres(
        setup
        + "SET LOCAL ROLE floatchat_ingestor;"
        + commit
        + "SELECT direction||'|'||(scientific_content->>'direction') FROM app.argo_profile;"
        + "RESET ROLE;"
        + opposite
        + "SELECT count(*) FROM app.argo_profile;ROLLBACK;"
    ).splitlines()
    assert result[-2:] == ["D|D", "2"]
    # A/D fallback rows coexist; another identical A tuple is rejected by the index.
    postgres(setup + commit + opposite + opposite, expected=3)
    persist(
        "descending-database",
        provenance,
        scientific_sha256=profile.content_hash,
        direction="D",
        canonical_direction="D",
        fallback_A_D_coexist=True,
        identical_fallback_A_rejected_by_database=True,
        additional_identity_constraint_mutation=(
            "clone A counterpart with new UUID and null source ID"
        ),
    )


@pytest.mark.integration
def test_B07_worker_has_no_unrestricted_dml_or_ddl(postgres):
    assert (
        postgres("SELECT has_table_privilege('floatchat_app','app.argo_profile','INSERT')") == "f"
    )
    assert (
        postgres(
            "SELECT has_function_privilege('floatchat_app','app.finalize_run(uuid,text)','EXECUTE')"
        )
        == "f"
    )
    postgres(
        "BEGIN; SET ROLE floatchat_app; INSERT INTO app.argo_float "
        "VALUES(gen_random_uuid(),'argovis','evil');",
        expected=3,
    )
    postgres("BEGIN; SET ROLE floatchat_app; CREATE TABLE app.evil(id int);", expected=3)
    postgres(
        "BEGIN; SET ROLE floatchat_app; UPDATE public.spatial_ref_sys SET auth_name='evil';",
        expected=3,
    )


@pytest.mark.integration
def test_F02_F03_B03_persisted_retry_status_reason_and_timing_metrics(postgres):
    # Persist transport evidence without sending a request or creating a raw body.
    attempts = [uuid.uuid4() for _ in range(3)]
    commands = [
        "BEGIN;",
        f"SELECT app.claim_chunk('{RUN}','{CHUNK}',1);",
        f"SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','test');",
    ]
    for identifier, key, status in zip(
        attempts, ("inventory", "inventory", "profile"), (429, 503, 403), strict=True
    ):
        commands.extend(
            [
                f"SELECT app.reserve_http_attempt('{RUN}','{CHUNK}',1,1,'{identifier}',"
                f"'{key}','profile','{{}}');",
                f"SELECT app.finish_attempt('{RUN}','{CHUNK}',1,1,'{identifier}',"
                f"'http_failure',{status},'upstream_http_failure',NULL);",
            ]
        )
    commands.extend(
        [
            f"SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'failed','http_retry_exhausted');",
            f"SELECT app.finalize_run('{RUN}');",
            f"SELECT evidence->'report_metrics' FROM app.run_final_evidence WHERE run_id='{RUN}';",
            "ROLLBACK;",
        ]
    )
    evidence = json.loads(postgres("\n".join(commands)).splitlines()[-1])
    assert evidence["http_retries"] == 1
    assert evidence["resource_counters"]["http_attempts"] == 3
    assert {item["http_status"] for item in evidence["attempt_reasons"]} == {429, 503, 403}
    assert all(
        item["error_category"] == "upstream_http_failure" for item in evidence["attempt_reasons"]
    )
    assert evidence["attempt_timing"][0]["elapsed_seconds_sum"] > 0
    assert evidence["attempt_timing"][0]["unfinished_attempts"] == 0
    assert any(item["reason"] == "http_retry_exhausted" for item in evidence["state_reasons"])
    assert not evidence["coverage_receipts"] and not evidence["active_generations"]


@pytest.mark.integration
def test_C01_C05_claim_fence_and_recovery(postgres):
    # Claims and expiry are restored by ROLLBACK; no test shares mutated run state.
    query = f"""
    BEGIN;
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','test');
    SELECT app.reserve_http_attempt('{RUN}','{CHUNK}',1,1,'{ATTEMPT}',
      'inventory','inventory_before','{{}}');
    UPDATE app.ingestion_chunk SET lease_until=clock_timestamp()-interval '1 second'
      WHERE id='{CHUNK}';
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    SELECT disposition FROM app.ingestion_attempt WHERE id='{ATTEMPT}';
    SELECT http_attempts FROM app.ingestion_run WHERE id='{RUN}';
    ROLLBACK;
    """
    assert postgres(query).splitlines() == ["1", "", "1", "2", "interrupted", "1"]
    postgres(
        f"BEGIN; SELECT app.transition_chunk('{RUN}','{CHUNK}',1,0,'fetching','unclaimed');",
        expected=3,
    )


@pytest.mark.integration
def test_C06_controller_adoption_fences_old_workers(postgres):
    query = f"""BEGIN;
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    UPDATE app.ingestion_run SET controller_lease_until=now()-interval '1 second' WHERE id='{RUN}';
    SELECT app.adopt_controller('{RUN}');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','stale_controller');"""
    postgres(query, expected=3)
    assert postgres(f"SELECT control_epoch FROM app.ingestion_run WHERE id='{RUN}'") == "1"


@pytest.mark.integration
def test_P11_legal_late_quarantine_intent_disposition(postgres):
    query = f"""BEGIN;
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'landed','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'validating','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'publishing','test');
    INSERT INTO app.publication_intent VALUES('{INTENT}','{CHUNK}',1,1,
      'prepared',now(),'[]','{{}}','{{}}',NULL);
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'quarantined',
      'revision_conflict','{{"winner":"evidence"}}');
    SELECT c.state||'|'||i.status FROM app.ingestion_chunk c
      JOIN app.publication_intent i ON i.chunk_id=c.id WHERE c.id='{CHUNK}';
    SELECT count(*) FROM app.committed_active_partitions;
    ROLLBACK;"""
    result = postgres(query).splitlines()
    assert result[-2:] == ["quarantined|abandoned", "0"]


@pytest.mark.integration
def test_C07_cancellation_finalizes_and_fences(postgres):
    query = f"""BEGIN;
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    SELECT app.finalize_run('{RUN}','operator_cancelled');
    SELECT state||'|'||cancellation_affected FROM app.ingestion_run WHERE id='{RUN}';
    SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK}';
    ROLLBACK;"""
    assert postgres(query).splitlines() == ["1", "failed", "failed|true", "failed"]
    postgres(
        f"BEGIN; SELECT app.claim_chunk('{RUN}','{CHUNK}',1); "
        f"SELECT app.finalize_run('{RUN}','operator_cancelled'); "
        f"SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','late');",
        expected=3,
    )


@pytest.mark.integration
def test_B03_persisted_retry_exhaustion(postgres):
    begin = f"BEGIN; SELECT app.claim_chunk('{RUN}','{CHUNK}',1);"
    commands = "".join(
        f"SELECT app.reserve_http_attempt('{RUN}','{CHUNK}',1,1,'{uuid.uuid4()}',"
        f"'same-request','profile','{{}}');"
        for _ in range(4)
    )
    assert postgres(begin + commands + "ROLLBACK;").splitlines() == ["1", "1", "2", "3", "4"]
    postgres(
        begin + commands + f"SELECT app.reserve_http_attempt('{RUN}','{CHUNK}',1,1,"
        f"'{uuid.uuid4()}','same-request','profile','{{}}');",
        expected=3,
    )


def _literal(value):
    return (
        "'"
        + json.dumps(value, separators=(",", ":"), allow_nan=False).replace("'", "''")
        + "'::jsonb"
    )


@pytest.mark.integration
def test_T05_initial_plan_rejects_omitted_and_duplicated_tiles(postgres):
    request = uuid.uuid4()
    interval = Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-01-02T00:00:00Z"))
    rows = [
        {
            "id": str(uuid.uuid4()),
            "key": item.tile.key,
            "start": item.interval.start.isoformat(),
            "end": item.interval.end.isoformat(),
            "tile": {
                "west": item.tile.west,
                "south": item.tile.south,
                "width": item.tile.width,
                "height": item.tile.height,
            },
        }
        for item in plan(interval)
    ]
    admission = (
        f"BEGIN; SET ROLE floatchat_ingestor; SELECT app.admit_run('{ENV}','{request}',"
        f"'acceptance',false,'2025-01-01','2025-01-02',21600,'{GEOMETRY_SHA256}',"
        f"{_literal(policy_versions())},'{{}}');"
    )
    target = f"(SELECT id FROM app.ingestion_run WHERE request_id='{request}')"
    assert (
        postgres(
            admission + f"SELECT app.persist_plan({target},1,{_literal(rows)});"
            f"SELECT count(*) FROM app.ingestion_chunk WHERE run_id={target}; ROLLBACK;"
        ).splitlines()[-1]
        == "90"
    )
    for bad in (rows[:-1], rows + [dict(rows[-1], id=str(uuid.uuid4()), key="duplicated-tile")]):
        postgres(admission + f"SELECT app.persist_plan({target},1,{_literal(bad)});", expected=3)


def _plan_rows(chunks):
    return [
        {
            "id": str(uuid.uuid4()),
            "key": f"{item.interval.start.isoformat()}/{item.tile.key}",
            "start": item.interval.start.isoformat(),
            "end": item.interval.end.isoformat(),
            "tile": {
                "west": item.tile.west,
                "south": item.tile.south,
                "width": item.tile.width,
                "height": item.tile.height,
            },
        }
        for item in chunks
    ]


@pytest.mark.integration
def test_stage1_v3_monthly_plan_v2_and_rejects_weekly_v1_shape(postgres):
    request = uuid.uuid4()
    interval = Interval(timestamp("2025-01-01T00:00:00Z"), timestamp("2025-03-01T00:00:00Z"))
    admission = (
        f"BEGIN; SET ROLE floatchat_ingestor; SELECT app.admit_run('{ENV}','{request}',"
        f"'acceptance',false,'2025-01-01','2025-03-01',21600,'{GEOMETRY_SHA256}',"
        f"{_literal(policy_versions())},'{{}}');"
    )
    target = f"(SELECT id FROM app.ingestion_run WHERE request_id='{request}')"
    monthly = _plan_rows(plan(interval))
    assert len(monthly) == 180
    lines = postgres(
        admission + f"SELECT app.persist_plan({target},1,{_literal(monthly)});"
        f"SELECT count(*)||'|'||min(plan_version)||'|'||max(plan_version) FROM app.ingestion_chunk "
        f"WHERE run_id={target}; ROLLBACK;"
    ).splitlines()
    assert lines[-1] == "180|indian-ocean-plan-v2|indian-ocean-plan-v2"
    weekly = [
        PlannedChunk(Interval(start, min(start + timedelta(days=7), end)), chunk.tile)
        for chunk in plan(interval)
        for start, end in [(chunk.interval.start, chunk.interval.end)]
    ]
    # A root that does not match the monthly population fails admission planning.
    postgres(
        admission + f"SELECT app.persist_plan({target},1,{_literal(_plan_rows(weekly))});",
        expected=3,
    )


@pytest.mark.integration
def test_stage1_v3_twelve_hour_run_bound(postgres):
    def admit(seconds):
        return (
            f"BEGIN; SET ROLE floatchat_ingestor; SELECT app.admit_run('{ENV}','{uuid.uuid4()}',"
            f"'acceptance',false,'2025-01-01','2025-01-02',{seconds},'{GEOMETRY_SHA256}',"
            f"{_literal(policy_versions())},'{{}}');"
        )

    lines = postgres(
        admit(43200) + "SELECT extract(epoch FROM max(deadline-created_at_actual_utc))::integer "
        "FROM app.ingestion_run; ROLLBACK;"
    ).splitlines()
    assert lines[-1] == "43200"
    postgres(admit(43201), expected=3)
    postgres(
        f"BEGIN; UPDATE app.ingestion_run SET deadline=created_at_actual_utc+interval '13 hours',"
        f"work_deadline=created_at_actual_utc+interval '13 hours'-interval '60 seconds' "
        f"WHERE id='{RUN}';",
        expected=3,
    )


@pytest.mark.integration
def test_stage1_v3_raw_status_exclusion_outcome_and_40_gib_cap(postgres):
    result = postgres("""
      SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conname='ingestion_run_canonical_bytes_check';
      SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='app.raw_manifest'::regclass AND contype='c'
        AND pg_get_constraintdef(oid) LIKE '%http_status%';
      SELECT position('excluded_source_loss' IN pg_get_constraintdef(oid))>0 FROM pg_constraint
        WHERE conname='profile_outcome_outcome_check';
      SELECT position('invalid_verified_status' IN prosrc)>0 FROM pg_proc
        WHERE proname='finish_attempt';
      SELECT position('42949672960' IN prosrc)>0 FROM pg_proc WHERE proname='reserve_canonical';
    """)
    lines = [line for line in result.splitlines() if line]
    assert "42949672960" in lines[0]
    assert "200" in lines[1] and "404" in lines[1]
    assert lines[2:] == ["t", "t", "t"]
    postgres(
        f"BEGIN; UPDATE app.ingestion_run SET canonical_bytes=42949672961 WHERE id='{RUN}';",
        expected=3,
    )


@pytest.mark.integration
def test_B09_month_creation_and_failed_publication_roll_back_together(
    postgres, wire, linked_metadata
):
    value, candidate = _candidate(wire, linked_metadata)
    setup, commit, generations, receipts = _publishing(value, candidate)
    setup = setup.replace(PARTITION, "")
    result = postgres(
        setup + commit + "SELECT count(*) FROM app.core_measurement; "
        "SELECT has_table_privilege('floatchat_ingestor',"
        "'app.core_measurement_202501','INSERT'); ROLLBACK;"
    )
    assert result.splitlines()[-2:] == ["3", "f"]
    assert postgres("SELECT to_regclass('app.core_measurement_202501') IS NULL") == "t"


def _candidate(wire, metadata, proposed=PROFILE, when="2025-01-02T00:00:00Z"):
    wire["timestamp"] = when
    wire["profile_direction"] = "A"  # Explicit synthetic derivative for fallback tests.
    profile = map_profile(decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget())
    return profile, staged_candidate(profile, uuid.UUID(proposed), uuid.UUID(RAW))


def _staged_levels(levels, *, occurrence=0, chunk=CHUNK, fence=1):
    """One statement staging typed level rows exactly as binary COPY would."""
    rows = [
        {
            **level,
            "run_id": RUN,
            "chunk_id": chunk,
            "fence": fence,
            "occurrence_index": occurrence,
        }
        for level in levels
    ]
    return (
        "INSERT INTO app.measurement_staging SELECT * FROM "
        f"jsonb_populate_recordset(NULL::app.measurement_staging,{_literal(rows)});"
    )


def _publishing(profile, candidate, *, levels=None, base=0):
    """SQL component fixture: object evidence is synthetic, not a MinIO acceptance proof.

    levels overrides the typed level rows staged for the candidate (default: the profile's);
    base is the slot version the part is built on.
    """
    slot = owner_slot(profile)
    profile_id = candidate["proposed_profile_id"]
    digest = "d" * 64
    key = f"normalised/sha256/{digest}.parquet"
    membership = [
        {"profile_id": profile_id, "hash": profile.content_hash, "levels": len(profile.levels)}
    ]
    verification = {"schema_sha256": "e" * 64, "rows": len(profile.levels), "profiles": 1}
    generations = [
        {
            "id": str(uuid.uuid4()),
            "logical_key": slot,
            "kind": "part",
            "base_version": base,
            "membership_manifest": membership,
            "sha256": digest,
            "object_key": key,
            "bytes": 12,
            "row_count": len(profile.levels),
            "profile_count": 1,
            "schema_sha256": "e" * 64,
            "verified_at": "2025-04-01T00:00:00Z",
            "verification_evidence": verification,
        }
    ]
    receipts = [
        {
            "id": str(uuid.uuid4()),
            "logical_key": slot,
            "fetch_disposition": "profiles_returned",
            "stored_disposition": "active_generation",
            "evidence": {"component_fixture": True},
        }
    ]
    setup = f"""
    BEGIN;
    SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'fetching','test');
    INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,
      request_attempt,role,request_parameters)
      VALUES('{ATTEMPT}','{CHUNK}',1,'test',1,'profile','{{}}');
    INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,retrieved_at,
      versions,sanitization,application_commit) VALUES('{RAW}','{RUN}','{CHUNK}','{ATTEMPT}',
      'raw/sha256/'||repeat('b',64)||'.json',repeat('b',64),2,now(),'{{}}','{{}}','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'landed','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'validating','test');
    SELECT app.transition_chunk('{RUN}','{CHUNK}',1,1,'publishing','test');
    {PARTITION}
    INSERT INTO app.logical_partition_slot(environment_id,logical_key,observation_month,tile_key)
      VALUES('{ENV}','{slot}','2025-01-01','70:10') ON CONFLICT DO NOTHING;
    INSERT INTO app.publication_intent VALUES('{INTENT}','{CHUNK}',1,1,'prepared',now(),
      {_literal([key])},{_literal({slot: base})},'{{}}',NULL);
    INSERT INTO app.ingestion_staging VALUES('{RUN}','{CHUNK}',1,0,{_literal(candidate)});
    {_staged_levels(profile.levels if levels is None else levels)}
    """
    commit = f"SELECT app.commit_publication('{RUN}','{CHUNK}',1,1,'{INTENT}'," + (
        _literal(generations) + "," + _literal(receipts) + ");"
    )
    return setup, commit, generations, receipts


@pytest.mark.integration
def test_P06_P07_atomic_publication_and_complete_retry(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(profile, candidate)
    result = postgres(
        setup
        + commit
        + commit
        + f"""
      SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK}';
      SELECT status FROM app.publication_intent WHERE id='{INTENT}';
      SELECT count(*) FROM app.committed_active_partitions;
      SELECT count(*) FROM app.core_measurement;
      SELECT accepted_profiles||'|'||accepted_levels FROM app.ingestion_run WHERE id='{RUN}';
      SELECT count(*) FROM app.profile_outcome;
      ROLLBACK;
    """
    )
    assert result.splitlines()[-6:] == ["complete", "committed", "1", "3", "1|3", "1"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "mutation,commit_result,audit_result",
    [
        # Set checks that stay in the commit.
        ("index_out_of_range", "invalid_level_index", None),
        ("level_missing", "level_set_mismatch", None),
        # Content checks moved to the sampled audit (ADR-0044 amendment, stage1-v4).
        ("numeric_value", "committed", "measurement_content_mismatch"),
        ("qc_flag", "committed", "measurement_content_mismatch"),
        ("unit_source", "committed", "measurement_content_mismatch"),
        ("flags", "committed", "measurement_content_mismatch"),
        ("none", "committed", "audited"),
    ],
)
def test_ADR0044_level_set_checks_in_commit_content_checks_in_audit(
    postgres, wire, linked_metadata, mutation, commit_result, audit_result
):
    profile, candidate = _candidate(wire, linked_metadata)
    levels = [dict(level) for level in profile.levels]
    level = levels[1]
    if mutation == "index_out_of_range":
        level["level_index"] = len(levels)
    elif mutation == "level_missing":
        levels.pop()
    elif mutation == "numeric_value":
        level["temperature"] = (level["temperature"] or 0) + 1
    elif mutation == "qc_flag":
        level["temperature_qc"] = "9" if level.get("temperature_qc") != "9" else "1"
    elif mutation == "unit_source":
        level["pressure_unit_source"] = "synthetic-unit-source"
    elif mutation == "flags":
        level["pressure_flags"] = [*level["pressure_flags"], "synthetic_flag"]
    setup, _, generations, receipts = _publishing(profile, candidate, levels=levels)
    result = postgres(
        setup
        + f"""
      CREATE FUNCTION pg_temp.attempt() RETURNS text LANGUAGE plpgsql AS $body$
      BEGIN
        PERFORM app.commit_publication('{RUN}','{CHUNK}',1,1,'{INTENT}',
          {_literal(generations)},{_literal(receipts)});
        RETURN 'committed';
      EXCEPTION WHEN raise_exception THEN RETURN SQLERRM;
      END $body$;
      CREATE FUNCTION pg_temp.audit() RETURNS text LANGUAGE plpgsql AS $body$
      BEGIN
        PERFORM app.audit_levels('{CHUNK}',10);
        RETURN 'audited';
      EXCEPTION WHEN raise_exception THEN RETURN SQLERRM;
      END $body$;
      SELECT pg_temp.attempt();
      SELECT pg_temp.audit();
      SELECT count(*) FROM app.core_measurement;
      ROLLBACK;
    """
    )
    lines = result.splitlines()
    assert lines[-3] == commit_result
    if commit_result == "committed":
        assert lines[-2:] == [audit_result, "3"]
    else:
        assert lines[-1] == "0"  # a failed commit leaves no level behind


@pytest.mark.integration
def test_ADR0044_stored_levels_equal_the_canonical_values_and_indexes_exist(
    postgres, wire, linked_metadata
):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(profile, candidate)
    result = postgres(
        setup
        + commit
        + "SELECT app.audit_levels('"
        + CHUNK
        + "',5); SELECT count(*) FROM pg_indexes WHERE indexname='argo_profile_owner_slot_idx';"
        # Typed rows are the staged Python values: positive zero holds because the mapper
        # normalizes it; the audit is what proves stored value == canonical exact value.
        "SELECT bool_and(m.pressure IS NOT DISTINCT FROM "
        "(p.scientific_content->'levels'->m.level_index->'pressure'->>'exact')::float8) "
        "FROM app.core_measurement m JOIN app.argo_profile p ON p.id=m.profile_id; ROLLBACK;"
    )
    audit, indexes, equal = result.splitlines()[-3:]
    assert json.loads(audit) == {"profiles": 1, "levels": 3}
    assert (indexes, equal) == ("1", "t")


@pytest.mark.integration
def test_v4_staged_level_rows_need_the_fenced_authority_and_are_cleared(
    postgres, wire, linked_metadata
):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, _, _ = _publishing(profile, candidate)
    # A stale fence cannot stage levels: the statement-level authority check raises.
    stale = _staged_levels(profile.levels, fence=2)
    postgres(setup + stale, expected=3)
    result = postgres(
        setup
        + f"""
      SELECT count(*) FROM app.measurement_staging;
      SELECT app.clear_staging('{RUN}','{CHUNK}',1,1);
      SELECT count(*) FROM app.measurement_staging;
      SELECT count(*) FROM app.ingestion_staging;
      ROLLBACK;
    """
    )
    assert result.splitlines()[-4:] == ["3", "", "0", "0"]


@pytest.mark.integration
def test_P06_failed_publication_rolls_back_all_science(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, generations, receipts = _publishing(profile, candidate)
    generations[0]["row_count"] = 2  # True level population is three.
    commit = f"SELECT app.commit_publication('{RUN}','{CHUNK}',1,1,'{INTENT}'," + (
        _literal(generations) + "," + _literal(receipts) + ");"
    )
    postgres(setup + commit, expected=3)
    assert postgres("SELECT count(*) FROM app.argo_profile") == "0"
    assert postgres("SELECT count(*) FROM app.dataset_partition") == "0"
    assert postgres(f"SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK}'") == "planned"


@pytest.mark.integration
def test_R02_R06_publication_replaces_entire_shortened_set(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, commit, generations, receipts = _publishing(profile, candidate)
    # Seed the previously committed scientific row under the same provenance.
    # It is a component transaction, so no invented live object claim is made.
    seed = SCIENCE[SCIENCE.index("INSERT INTO app.argo_float") :]
    seed = seed.replace("'source-id'", "'" + profile.source_profile_id + "'")
    seed = seed.replace("'test-platform'", "'" + profile.platform + "'")
    seed = seed.replace("1,'A'", f"{profile.cycle},'{profile.direction}'")
    candidate["revision"] = {"kind": "test", "components": {"core": "2025-01-03T00:00:00Z"}}
    initial_revision = {"kind": "test", "components": {"core": "2025-01-01T00:00:00Z"}}
    initial_science = json.loads(profile.canonical_bytes)
    # Stored old science has five levels, candidate has three.
    source = (
        setup
        + seed
        + f"""
      UPDATE app.argo_profile SET scientific_content={_literal(initial_science)},level_count=5,
        source_revision={_literal(initial_revision)} WHERE id='{PROFILE}';
    """
        + "".join(MEASUREMENT.replace("',0,1,", f"',{index},1,") for index in range(5))
    )
    source += (
        f"UPDATE app.ingestion_staging SET candidate={_literal(candidate)} "
        f"WHERE chunk_id='{CHUNK}';"
    )
    source += (
        commit
        + f"""
      SELECT count(*)||'|'||max(level_index) FROM app.core_measurement WHERE profile_id='{PROFILE}';
      SELECT outcome FROM app.profile_outcome WHERE chunk_id='{CHUNK}';
      ROLLBACK;
    """
    )
    assert postgres(source).splitlines()[-2:] == ["3|2", "newer"]


def _second_publication(setup, commit):
    chunk, intent, raw, attempt = [str(uuid.uuid4()) for _ in range(4)]
    setup = setup.replace("BEGIN;", "").replace(PARTITION, "")
    for old, new in ((CHUNK, chunk), (INTENT, intent), (RAW, raw), (ATTEMPT, attempt)):
        setup = setup.replace(old, new)
        commit = commit.replace(old, new)
    prefix = f"""
      INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,
        requested_end,tile,plan_version) VALUES('{chunk}','{RUN}','{chunk}',
        '2025-01-01','2025-01-07',
        '{{"west":70,"south":10,"width":10,"height":10}}','v1');
    """
    return prefix + setup, commit, chunk, intent


@pytest.mark.integration
def test_P11_late_conflict_preserves_winner_and_abandons_loser(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    initial, first, _, _ = _publishing(profile, candidate)
    wire["data"][0][0] += 0.25
    conflicting, bad_candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(conflicting, bad_candidate)
    setup, commit, chunk, intent = _second_publication(setup, commit)
    source = (
        initial
        + first
        + setup
        + f"""
      DO $test$ BEGIN
        BEGIN
          {commit}
          RAISE EXCEPTION 'unexpected_publication_success';
        EXCEPTION WHEN OTHERS THEN
          IF SQLERRM<>'revision_conflict' THEN RAISE; END IF;
        END;
      END $test$;
      SELECT app.transition_chunk('{RUN}','{chunk}',1,1,'quarantined','revision_conflict',
        '{{"component_evidence":"winning_revision_preserved"}}');
      SELECT content_hash FROM app.argo_profile WHERE id='{PROFILE}';
      SELECT state FROM app.ingestion_chunk WHERE id='{chunk}';
      SELECT status||'|'||jsonb_array_length(object_references) FROM app.publication_intent
        WHERE id='{intent}';
      SELECT count(*) FROM app.committed_active_partitions;
      SELECT count(*) FROM app.core_measurement;
      ROLLBACK;
    """
    )
    assert postgres(source).splitlines()[-5:] == [
        profile.content_hash,
        "quarantined",
        "abandoned|1",
        "1",
        "3",
    ]


@pytest.mark.integration
def test_P09b_empty_refresh_retains_active_generation(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    initial, first, _, _ = _publishing(profile, candidate)
    setup, _, _, receipts = _publishing(profile, candidate)
    setup, _, chunk, intent = _second_publication(setup, "")
    receipts[0]["fetch_disposition"] = "source_absence_over_retained"
    receipt_sql = _literal(receipts)
    source = (
        initial
        + first
        + setup
        + f"""
      DELETE FROM app.ingestion_staging WHERE chunk_id='{chunk}';
      SELECT app.commit_publication('{RUN}','{chunk}',1,1,'{intent}','[]',{receipt_sql});
      SELECT count(*)||'|'||max(generation) FROM app.committed_active_partitions;
      SELECT count(*) FROM app.argo_profile;
      SELECT count(*) FROM app.core_measurement;
      SELECT fetch_disposition FROM app.coverage_receipt WHERE chunk_id='{chunk}';
      ROLLBACK;
    """
    )
    assert postgres(source).splitlines()[-4:] == ["1|1", "1", "3", "source_absence_over_retained"]


@pytest.mark.integration
def test_D05_D06_admission_overlap_and_redelivery_without_new_run(postgres):
    first, second = uuid.uuid4(), uuid.uuid4()

    def call(request):
        return (
            f"SELECT app.admit_run('{ENV}','{request}','acceptance',false,'2025-01-01',"
            f"'2025-01-07',21600,'{GEOMETRY_SHA256}',{_literal(policy_versions())},'{{}}');"
        )

    result = postgres(
        "BEGIN; SET ROLE floatchat_ingestor;"
        + call(first)
        + call(second)
        + call(second)
        + "SELECT count(*) FROM app.ingestion_run;"
        + "SELECT count(*) FROM app.scheduling_attempt; ROLLBACK;"
    ).splitlines()
    assert json.loads(result[0])["kind"] == "created"
    assert json.loads(result[1])["kind"] == "overlap_skip"
    assert json.loads(result[1]) == json.loads(result[2])
    assert result[-2:] == ["2", "1"]


@pytest.mark.integration
def test_B07_ingestor_cannot_write_scientific_targets_or_extensions(postgres):
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_ingestor',"
            "'app.argo_profile','INSERT,UPDATE,DELETE')"
        )
        == "f"
    )
    assert (
        postgres(
            "SELECT has_table_privilege('floatchat_ingestor','app.ingestion_staging','INSERT')"
        )
        == "t"
    )
    postgres("BEGIN; SET ROLE floatchat_ingestor; DELETE FROM app.argo_profile;", expected=3)
    postgres("BEGIN; SET ROLE floatchat_ingestor; CREATE TABLE app.evil(value int);", expected=3)
    postgres(
        "BEGIN; SET ROLE floatchat_ingestor; UPDATE public.spatial_ref_sys SET auth_name='bad';",
        expected=3,
    )


@pytest.mark.integration
def test_C06_worker_heartbeat_does_not_keep_dead_controller_alive(postgres):
    assert (
        postgres(f"""BEGIN;
      SELECT app.claim_chunk('{RUN}','{CHUNK}',1);
      SELECT controller_lease_until INTO TEMP original_lease
        FROM app.ingestion_run WHERE id='{RUN}';
      SELECT app.heartbeat('{RUN}','{CHUNK}',1,1);
      SELECT controller_lease_until=(SELECT controller_lease_until FROM original_lease)
        FROM app.ingestion_run WHERE id='{RUN}';
      ROLLBACK;
    """).splitlines()[-1]
        == "t"
    )


@pytest.mark.integration
def test_P09a_empty_initial_fetch_has_receipt_and_no_partition(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, _, receipts = _publishing(profile, candidate)
    receipts[0]["fetch_disposition"] = "verified_empty_fetch"
    receipts[0]["stored_disposition"] = "empty_stored_selection"
    source = (
        setup
        + f"""
      DELETE FROM app.ingestion_staging WHERE chunk_id='{CHUNK}';
      SELECT app.commit_publication('{RUN}','{CHUNK}',1,1,'{INTENT}','[]',{_literal(receipts)});
      SELECT count(*) FROM app.committed_active_partitions;
      SELECT slot_version FROM app.logical_partition_slot;
      SELECT fetch_disposition||'|'||stored_disposition FROM app.coverage_receipt;
      SELECT state FROM app.ingestion_chunk WHERE id='{CHUNK}';
      ROLLBACK;
    """
    )
    assert postgres(source).splitlines()[-4:] == [
        "0",
        "0",
        "verified_empty_fetch|empty_stored_selection",
        "complete",
    ]


@pytest.mark.integration
def test_P09c_last_profile_correction_deactivates_old_slot(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    initial, first, _, _ = _publishing(profile, candidate)
    wire["geolocation"]["coordinates"] = [80, 10]
    for source in wire["source"]:
        source["date_updated"] = "2025-02-01T00:00:00Z"
    moved, moved_candidate = _candidate(wire, linked_metadata)
    setup, _, generations, receipts = _publishing(moved, moved_candidate)
    setup, _, chunk, intent = _second_publication(setup, "")
    # Existing source slot is version 1; the destination starts empty at version 0.
    generations.append(
        {"logical_key": owner_slot(profile), "base_version": 1, "membership_manifest": []}
    )
    receipts.append(
        {
            "id": str(uuid.uuid4()),
            "logical_key": owner_slot(profile),
            "fetch_disposition": "profiles_returned",
            "stored_disposition": "empty_stored_domain",
            "evidence": {"reason": "accepted_ownership_correction"},
        }
    )
    # A rebuild abandons the old intent and preserves its object references.
    replacement = str(uuid.uuid4())
    source = (
        initial
        + first
        + setup
        + f"""
      SELECT app.transition_chunk('{RUN}','{chunk}',1,1,'publishing','bounded_rebuild');
      SELECT app.prepare_intent('{RUN}','{chunk}',1,1,'{replacement}',
        {_literal([generations[0]["object_key"]])},
        {_literal({owner_slot(profile): 1, owner_slot(moved): 0})},'{{}}');
      SELECT app.commit_publication('{RUN}','{chunk}',1,1,'{replacement}',
        {_literal(generations)},{_literal(receipts)});
      SELECT count(*) FROM app.committed_active_partitions;
      SELECT logical_key FROM app.committed_active_partitions;
      SELECT status FROM app.dataset_partition WHERE chunk_id='{CHUNK}';
      SELECT stored_disposition FROM app.coverage_receipt WHERE chunk_id='{chunk}'
        AND logical_key='{owner_slot(profile)}';
      SELECT count(*) FROM app.core_measurement;
      ROLLBACK;
    """
    )
    assert postgres(source).splitlines()[-5:] == [
        "1",
        owner_slot(moved),
        "superseded",
        "empty_stored_domain",
        "3",
    ]


def _attempt(generations, receipts, *, chunk=CHUNK, intent=INTENT):
    """A pg_temp function returning the commit's exception category (or 'committed')."""
    return f"""
      CREATE FUNCTION pg_temp.attempt() RETURNS text LANGUAGE plpgsql AS $body$
      BEGIN
        PERFORM app.commit_publication('{RUN}','{chunk}',1,1,'{intent}',
          {_literal(generations)},{_literal(receipts)});
        RETURN 'committed';
      EXCEPTION WHEN raise_exception THEN RETURN SQLERRM;
      END $body$;
    """


def _two_parts(wire, linked_metadata):
    """Two commits into one slot: a part per chunk, the second built on slot version 1."""
    second = copy.deepcopy(wire)
    second["_id"] = "second-part-profile"
    second["cycle_number"] += 1
    profile, candidate = _candidate(wire, linked_metadata)
    initial, first, _, _ = _publishing(profile, candidate)
    other, other_candidate = _candidate(second, linked_metadata, proposed=SECOND_PROFILE)
    setup, commit, _, _ = _publishing(other, other_candidate, base=1)
    setup, commit, chunk, intent = _second_publication(setup, commit)
    return owner_slot(profile), initial + first + setup + commit, profile, other


@pytest.mark.integration
def test_v4_each_commit_adds_a_part_and_edits_the_slot_manifest(postgres, wire, linked_metadata):
    slot, source, profile, other = _two_parts(wire, linked_metadata)
    result = postgres(
        source
        + f"""
      SELECT count(*) FROM app.committed_active_partitions;
      SELECT string_agg(kind||':'||slot_version||':'||generation||':'||part_ordinal,','
        ORDER BY generation) FROM app.committed_active_partitions;
      SELECT slot_version||'|'||jsonb_array_length(membership_manifest)
        FROM app.logical_partition_slot WHERE logical_key='{slot}';
      SELECT string_agg(m.e->>'profile_id',',' ORDER BY m.pos) FROM app.logical_partition_slot s,
        jsonb_array_elements(s.membership_manifest) WITH ORDINALITY AS m(e,pos)
        WHERE s.logical_key='{slot}';
      SELECT app.audit_slot_manifest('{ENV}','{slot}');
      SELECT count(*) FROM app.core_measurement;
      SELECT count(*) FROM app.measurement_staging;
      ROLLBACK;
    """
    )
    assert result.splitlines()[-7:] == [
        "2",
        "part:2:1:1,part:2:2:2",  # both active objects carry the slot's current version
        "2|2",
        f"{PROFILE},{SECOND_PROFILE}",  # ordered by profile_id
        "t",
        "6",
        "0",  # staged levels are consumed by the commit
    ]


@pytest.mark.integration
def test_v4_replacement_drops_the_old_manifest_entry_and_adds_a_second_part(
    postgres, wire, linked_metadata
):
    profile, candidate = _candidate(wire, linked_metadata)
    initial, first, _, _ = _publishing(profile, candidate)
    wire["data"][0][0] += 0.25
    for source in wire["source"]:
        source["date_updated"] = "2025-02-01T00:00:00Z"
    newer, newer_candidate = _candidate(wire, linked_metadata)
    assert newer.content_hash != profile.content_hash
    setup, commit, _, _ = _publishing(newer, newer_candidate, base=1)
    setup, commit, chunk, intent = _second_publication(setup, commit)
    slot = owner_slot(profile)
    result = postgres(
        initial
        + first
        + setup
        + commit
        + f"""
      SELECT count(*)||'|'||string_agg(kind,',') FROM app.committed_active_partitions;
      SELECT jsonb_array_length(membership_manifest)||'|'||(membership_manifest->0->>'hash')
        FROM app.logical_partition_slot WHERE logical_key='{slot}';
      SELECT outcome FROM app.profile_outcome WHERE chunk_id='{chunk}';
      SELECT count(*) FROM app.core_measurement;
      SELECT app.audit_slot_manifest('{ENV}','{slot}');
      ROLLBACK;
    """
    )
    assert result.splitlines()[-5:] == [
        "2|part,part",
        f"1|{newer.content_hash}",
        "newer",
        "3",
        "t",
    ]


@pytest.mark.integration
def test_v4_part_must_declare_exactly_the_accepted_profiles_of_the_slot(
    postgres, wire, linked_metadata
):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, generations, receipts = _publishing(profile, candidate)
    generations[0]["membership_manifest"][0]["hash"] = "0" * 64
    result = postgres(
        setup + _attempt(generations, receipts) + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == "stored_snapshot_membership_mismatch"
    generations[0]["membership_manifest"] = []  # the slot is changed but the part is empty
    result = postgres(
        setup + _attempt(generations, receipts) + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == "stored_snapshot_membership_mismatch"


@pytest.mark.integration
def test_v4_receipt_only_slot_is_guarded_by_its_base_version(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, _, receipts = _publishing(profile, candidate)
    receipts[0]["fetch_disposition"] = "verified_empty_fetch"
    receipts[0]["stored_disposition"] = "empty_stored_selection"
    outcomes = []
    for base in (7, 0):
        receipts[0]["base_version"] = base
        outcomes.append(
            postgres(
                setup
                + f"DELETE FROM app.ingestion_staging WHERE chunk_id='{CHUNK}';"
                + _attempt([], receipts)
                + "SELECT pg_temp.attempt(); ROLLBACK;"
            ).splitlines()[-1]
        )
    # A moved slot means the caller counted a population that no longer exists: rebuild.
    assert outcomes == ["publication_base_changed", "committed"]


@pytest.mark.integration
def test_v4_manifest_audit_detects_drift(postgres, wire, linked_metadata):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(profile, candidate)
    slot = owner_slot(profile)
    result = postgres(
        setup
        + commit
        + f"""
      SELECT app.audit_slot_manifest('{ENV}','{slot}');
      UPDATE app.logical_partition_slot SET membership_manifest='[]' WHERE logical_key='{slot}';
      SELECT app.audit_slot_manifest('{ENV}','{slot}');
      ROLLBACK;
    """
    )
    assert result.splitlines()[-2:] == ["t", "f"]


@pytest.mark.integration
def test_v4_compact_slot_swaps_parts_for_one_snapshot_and_refuses_stale_input(
    postgres, wire, linked_metadata
):
    slot, source, _, _ = _two_parts(wire, linked_metadata)
    result = postgres(
        source
        + f"""
      CREATE FUNCTION pg_temp.compact(p_base bigint,p_drop_listed boolean,p_alter boolean)
      RETURNS text LANGUAGE plpgsql AS $body$
      DECLARE slot_row app.logical_partition_slot; listed jsonb; manifest jsonb; total bigint;
      BEGIN
        SELECT * INTO STRICT slot_row FROM app.logical_partition_slot WHERE logical_key='{slot}';
        SELECT jsonb_agg(d.id ORDER BY d.generation) INTO listed FROM app.dataset_partition d
          WHERE d.logical_key='{slot}' AND d.status='active';
        IF p_drop_listed THEN listed := listed - 0; END IF;
        manifest := slot_row.membership_manifest;
        IF p_alter THEN manifest := manifest - 0; END IF;
        SELECT sum((m->>'levels')::bigint) INTO total
          FROM jsonb_array_elements(slot_row.membership_manifest) m;
        PERFORM app.compact_slot('{ENV}','{slot}',jsonb_build_object(
          'id',gen_random_uuid(),'kind','snapshot','logical_key','{slot}',
          'base_version',coalesce(p_base,slot_row.slot_version),'membership_manifest',manifest,
          'supersedes',listed,'object_key','normalised/sha256/'||repeat('f',64)||'.parquet',
          'sha256',repeat('f',64),'bytes',20,'row_count',total,
          'profile_count',jsonb_array_length(slot_row.membership_manifest),
          'schema_sha256',repeat('e',64),'verified_at','2025-04-01T00:00:00Z',
          'verification_evidence',jsonb_build_object('schema_sha256',repeat('e',64),
            'rows',total,'profiles',jsonb_array_length(slot_row.membership_manifest))));
        RETURN 'compacted';
      EXCEPTION WHEN raise_exception THEN RETURN SQLERRM;
      END $body$;
      SELECT pg_temp.compact(99,false,false);
      SELECT pg_temp.compact(NULL,true,false);
      SELECT pg_temp.compact(NULL,false,true);
      SELECT pg_temp.compact(NULL,false,false);
      SELECT count(*)||'|'||min(kind)||'|'||min(slot_version) FROM app.committed_active_partitions;
      SELECT count(*) FROM app.dataset_partition WHERE status='superseded';
      SELECT jsonb_array_length(membership_manifest) FROM app.logical_partition_slot
        WHERE logical_key='{slot}';
      ROLLBACK;
    """
    )
    assert result.splitlines()[-7:] == [
        "publication_base_changed",  # the slot moved since the snapshot was built
        "publication_base_changed",  # the active objects are not the ones that were merged
        "stored_snapshot_membership_mismatch",  # the snapshot does not hold the manifest
        "compacted",
        "1|snapshot|2",
        "2",
        "2",
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    "mutation,category",
    [
        ("hash", "scientific_hash_mismatch"),
        ("direction", "candidate_content_mismatch"),
        ("level_count", "invalid_level_count"),
        ("raw_manifest", "raw_provenance_mismatch"),
        ("no_generation", "missing_affected_slot"),
        ("base_version", "publication_base_changed"),
        ("empty_domain", "coverage_disposition_mismatch"),
        ("absence_with_candidates", "coverage_disposition_mismatch"),
    ],
)
def test_v4_commit_keeps_its_rejection_categories(
    postgres, wire, linked_metadata, mutation, category
):
    profile, candidate = _candidate(wire, linked_metadata)
    base = 5 if mutation == "base_version" else 0
    if mutation == "hash":
        candidate["content_hash"] = "0" * 64
    elif mutation == "direction":
        candidate["direction"] = "D"
    elif mutation == "level_count":
        candidate["level_count"] = 0
    elif mutation == "raw_manifest":
        candidate["raw_manifest_id"] = str(uuid.uuid4())
    setup, _, generations, receipts = _publishing(profile, candidate, base=base)
    if mutation == "no_generation":
        generations = []
    elif mutation == "empty_domain":
        receipts[0]["stored_disposition"] = "empty_stored_domain"  # the slot is not empty
    elif mutation == "absence_with_candidates":
        receipts[0]["fetch_disposition"] = "source_absence_over_retained"  # but rows are staged
    result = postgres(
        setup + _attempt(generations, receipts) + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == category


@pytest.mark.integration
def test_v4_fallback_identity_time_correction_and_identity_conflict_are_rejected(
    postgres, wire, linked_metadata
):
    # An ID-less profile whose cycle/direction already exists at another observation time.
    anonymous = copy.deepcopy(wire)
    del anonymous["_id"]
    first, candidate = _candidate(anonymous, linked_metadata)
    initial, first_commit, _, _ = _publishing(first, candidate)
    later = copy.deepcopy(anonymous)
    again, again_candidate = _candidate(
        later, linked_metadata, proposed=SECOND_PROFILE, when="2025-01-03T00:00:00Z"
    )
    setup, _, generations, receipts = _publishing(again, again_candidate, base=1)
    setup, _, chunk, intent = _second_publication(setup, "")
    result = postgres(
        initial
        + first_commit
        + setup
        + _attempt(generations, receipts, chunk=chunk, intent=intent)
        + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == "fallback_observation_time_correction"
    # A stable id of one stored profile together with the natural key of another.
    named = copy.deepcopy(wire)
    first_named, first_candidate = _candidate(named, linked_metadata)
    one, one_commit, _, _ = _publishing(first_named, first_candidate)
    other_wire = copy.deepcopy(wire)
    other_wire["_id"], other_wire["cycle_number"] = "other-stable-id", wire["cycle_number"] + 1
    other, other_candidate = _candidate(other_wire, linked_metadata, proposed=SECOND_PROFILE)
    two, two_commit, _, _ = _publishing(other, other_candidate, base=1)
    two, two_commit, _, _ = _second_publication(two, two_commit)
    crossed_wire = copy.deepcopy(wire)  # the first stable id, the second cycle
    crossed_wire["cycle_number"] = wire["cycle_number"] + 1
    crossed, crossed_candidate = _candidate(
        crossed_wire, linked_metadata, proposed="00000000-0000-4000-8000-0000000000b7"
    )
    three, _, generations, receipts = _publishing(crossed, crossed_candidate, base=2)
    three, _, chunk, intent = _second_publication(three, "")
    result = postgres(
        one
        + one_commit
        + two
        + two_commit
        + three
        + _attempt(generations, receipts, chunk=chunk, intent=intent)
        + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == "identity_conflict"


@pytest.mark.integration
def test_v4_commit_reserve_is_enforced_after_the_final_authority_check(
    postgres, wire, linked_metadata
):
    profile, candidate = _candidate(wire, linked_metadata)
    setup, _, generations, receipts = _publishing(profile, candidate)
    # Less than the one-second final reserve remains, but the work deadline has not passed.
    result = postgres(
        setup
        + "ALTER TABLE app.ingestion_run DISABLE TRIGGER ingestion_run_immutable;"
        + "UPDATE app.ingestion_run SET "
        + "work_deadline=clock_timestamp()+interval '990 milliseconds' "
        + f"WHERE id='{RUN}';"
        + _attempt(generations, receipts)
        + "SELECT pg_temp.attempt(); ROLLBACK;"
    )
    assert result.splitlines()[-1] == "commit_reserve_exhausted"


@pytest.mark.integration
def test_P01_B07_restricted_repository_and_catalogue_snapshot(postgres, wire, linked_metadata):
    image = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    postgres("CREATE DATABASE repository_probe;")
    command = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--memory=1g",
        "--network=container:" + postgres.container_name,
        "--mount",
        f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
        "--env",
        "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/repository_probe",
        image,
        "alembic",
        "-c",
        "infra/alembic.ini",
        "upgrade",
        "head",
    ]
    migration = subprocess.run(command, capture_output=True, timeout=60)
    assert migration.returncode == 0, "Disposable repository migration failed"
    postgres(SEED, database="repository_probe")
    profile, candidate = _candidate(wire, linked_metadata)
    setup, commit, _, _ = _publishing(profile, candidate)
    postgres(setup + commit + "COMMIT;", database="repository_probe")
    environment = dict(os.environ, EXPECTED_SCIENTIFIC_HASH=profile.content_hash)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--memory=1g",
            "--network=container:" + postgres.container_name,
            "--mount",
            f"type=bind,source={ROOT},target=/test,readonly",
            "--env",
            "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/repository_probe",
            "--env",
            "EXPECTED_SCIENTIFIC_HASH",
            "--env",
            "PYTHONPATH=/test/packages/core/src:/test/workers/src:"
            "/test/.venv/lib/python3.12/site-packages",
            image,
            "python",
            "/test/tests/stage1/repository_probe.py",
        ],
        env=environment,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, "Disposable restricted repository verification failed"
    assert result.stdout.strip() == b"offline-restricted-repository-verified"
