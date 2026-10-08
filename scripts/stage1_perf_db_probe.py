"""Disposable PostgreSQL timings for one chunk's staging COPY, commit and retained read.

Starts exactly one memory-limited container from the locally cached foundation
image on a loopback-only random port, applies the migration SQL like
tests/stage1/test_database.py, commits labelled synthetic chunks and removes the
container. No upstream, MinIO or shared service is touched.
"""

import argparse
import contextlib
import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from floatchat_core.ingestion.argovis import map_profile  # noqa: E402
from floatchat_core.ingestion.json_stream import documents  # noqa: E402
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json  # noqa: E402
from floatchat_core.ingestion.parquet import write_snapshot  # noqa: E402
from floatchat_core.ingestion.repository import Authority, Repository  # noqa: E402
from floatchat_core.ingestion.spool import ProfileSpool  # noqa: E402
from floatchat_core.ingestion.workflow import owner_slot  # noqa: E402
from stage1_perf_profile import synthetic_chunk  # noqa: E402

ENV = "00000000-0000-4000-8000-000000000003"
RUN = "00000000-0000-4000-8000-000000000001"
IMAGE = "floatchat-stage0-wsl-dev-db:latest"


def sql(connection, text, *params):
    with connection.cursor() as cursor:
        cursor.execute(text, params or None)
        try:
            return cursor.fetchall()
        except psycopg.ProgrammingError:
            return None


def start_container(memory):
    name = "floatchat-perf-db-" + uuid.uuid4().hex
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--pull=never",
            f"--memory={memory}",
            "--cpus=2",
            "--publish",
            "127.0.0.1::5432",
            "--name",
            name,
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            IMAGE,
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    deadline = time.monotonic() + 60
    while True:
        ready = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
            capture_output=True,
            timeout=10,
        )
        if ready.returncode == 0:
            break
        assert time.monotonic() < deadline
        time.sleep(0.5)
    port = (
        subprocess.run(
            ["docker", "port", name, "5432/tcp"], capture_output=True, text=True, check=True
        )
        .stdout.strip()
        .splitlines()[0]
        .rsplit(":", 1)[1]
    )
    return name, int(port)


def migrate(url):
    with psycopg.connect(url, autocommit=True) as connection:
        sql(
            connection,
            "CREATE EXTENSION postgis; CREATE EXTENSION vector; CREATE SCHEMA app; "
            "CREATE TABLE app.stage0_sentinel(value text); "
            "INSERT INTO app.stage0_sentinel VALUES('preserved'); "
            "CREATE ROLE floatchat_app NOLOGIN; "
            "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL ON TABLES TO floatchat_app;",
        )
        for number in range(2, 12):
            file = next((ROOT / "infra/migrations/versions").glob(f"{number:04d}_*.sql"))
            sql(connection, file.read_text())
        sql(
            connection,
            f"""
            INSERT INTO app.ingestion_environment
              VALUES('{ENV}','test','acceptance',true,'test','test','test');
            INSERT INTO app.ingestion_run(id,environment_id,mode,run_reference_time_utc,
              requested_start,requested_end,geometry_version,geometry_sha256,policy_versions,limits,
              controller_lease_until,work_deadline,deadline)
            VALUES('{RUN}','{ENV}','acceptance','2025-04-01','2025-01-01','2025-04-01',
              'indian-ocean-v1',repeat('a',64),'{{}}','{{}}',now()+interval '10 minutes',
              now()+interval '5 hours 59 minutes',now()+interval '6 hours');
            CREATE TABLE IF NOT EXISTS app.core_measurement_202501 PARTITION OF app.core_measurement
              FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
        """,
        )


def timed(stages, name, function):
    started = time.perf_counter()
    result = function()
    stages[name] = round(time.perf_counter() - started, 3)
    return result


def scenario(url, work, profiles_count, levels, west, south, label, offset):
    stages = {}
    chunk_id, attempt_id, raw_id, intent_id = (uuid.uuid4() for _ in range(4))
    payload, _, metadata = synthetic_chunk(profiles_count, levels, offset)
    payload = payload.replace(b"[75.5,15.5]", f"[{west + 5.5},{south + 5.5}]".encode())
    meta_map = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    with psycopg.connect(url, autocommit=True) as admin:
        sql(
            admin,
            f"""
            INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,
              requested_end,tile,plan_version)
            VALUES('{chunk_id}','{RUN}','{label}','2025-01-01','2025-02-01',
              '{{"west":{west},"south":{south},"width":10,"height":10}}','v2');
            SELECT app.claim_chunk('{RUN}','{chunk_id}',1);
            SELECT app.transition_chunk('{RUN}','{chunk_id}',1,1,'fetching','probe');
            INSERT INTO app.ingestion_attempt(id,chunk_id,attempt_number,logical_request_key,
              request_attempt,role,request_parameters)
              VALUES('{attempt_id}','{chunk_id}',1,'{label}',1,'profile','{{}}');
            INSERT INTO app.raw_manifest(id,run_id,chunk_id,attempt_id,object_key,sha256,bytes,
              retrieved_at,versions,sanitization,application_commit)
              VALUES('{raw_id}','{RUN}','{chunk_id}','{attempt_id}','raw/sha256/'||repeat('b',64)||'.json',repeat('b',64),2,now(),'{{}}','{{}}','probe');
            SELECT app.transition_chunk('{RUN}','{chunk_id}',1,1,'landed','probe');
            SELECT app.transition_chunk('{RUN}','{chunk_id}',1,1,'validating','probe');
        """,
        )
    repository = Repository(url)
    budget_repository = Repository(url)
    authority = Authority(uuid.UUID(RUN), chunk_id, 1, 1)
    budget = CanonicalBudget()
    docs = list(documents(payload))
    profiles = [map_profile(doc, meta_map, budget) for doc in docs]
    spool = ProfileSpool(work / (uuid.uuid4().hex + ".sqlite"))
    for index, profile in enumerate(profiles):
        spool.add(profile, raw_id, index)
    # Identity lookups are one read-only query per profile against the live schema.
    timed(
        stages,
        "spool.prepare with repository.identities per profile",
        lambda: spool.prepare(
            lambda p: (), identity_lookup=repository.identities, load_science=None
        ),
    )
    slot = owner_slot(profiles[0])
    del profiles, docs
    timed(
        stages,
        "canonical_budget round trip x20",
        lambda: [budget_repository.canonical_budget(authority).__enter__() for _ in range(20)],
    )
    timed(stages, "heartbeat x20", lambda: [repository.heartbeat(authority) for _ in range(20)])
    repository.transition(authority, "publishing", "probe")
    repository.ensure_slot(
        authority,
        datetime(2025, 1, 1, tzinfo=UTC),
        __import__("floatchat_core.ingestion.planning", fromlist=["Tile"]).Tile(west, south),
    )
    with repository.retained_snapshot(authority, (slot,), budget_repository) as (bases, rows):
        retained = timed(
            stages, "retained_snapshot read (before commit; expect 0 rows)", lambda: list(rows)
        )
    file = work / (uuid.uuid4().hex + ".parquet")
    verified = write_snapshot(file, spool.profiles(slot), deadline=time.monotonic() + 3600)
    membership = spool.membership(slot)
    digest = __import__("hashlib").sha256(file.read_bytes()).hexdigest()
    key = f"normalised/sha256/{digest}.parquet"
    generations = [
        {
            "id": str(uuid.uuid4()),
            "logical_key": slot,
            "base_version": bases[slot],
            "membership_manifest": membership,
            "object_key": key,
            "sha256": digest,
            "bytes": file.stat().st_size,
            "row_count": verified["rows"],
            "profile_count": verified["profiles"],
            "schema_sha256": verified["schema_sha256"],
            "verification_evidence": verified,
            "verified_at": datetime.now(UTC).isoformat(),
        }
    ]
    receipts = [
        {
            "id": str(uuid.uuid4()),
            "logical_key": slot,
            "fetch_disposition": "profiles_returned",
            "stored_disposition": "active_generation",
            "evidence": {"probe": True},
        }
    ]
    timed(
        stages,
        "prepare_intent",
        lambda: repository.prepare_intent(authority, intent_id, [key], bases, {}),
    )
    staged = work / (uuid.uuid4().hex + ".ndjson")
    timed(stages, "spool.write_candidates", lambda: spool.write_candidates(staged))
    timed(
        stages,
        "stage_file COPY to ingestion_staging",
        lambda: repository.stage_file(authority, staged),
    )
    outcome = None
    try:
        timed(
            stages,
            "commit_publication",
            lambda: repository.commit(authority, intent_id, generations, receipts),
        )
        outcome = "complete"
    except Exception as error:  # Rejection category only
        outcome = getattr(error, "category", type(error).__name__)
        stages["commit_publication"] = stages.get("commit_publication", "failed:" + outcome)
    with psycopg.connect(url, autocommit=True) as admin:
        stored = sql(
            admin, "SELECT count(*) FROM app.core_measurement WHERE observation_month='2025-01-01'"
        )[0][0]
        state = sql(admin, "SELECT state FROM app.ingestion_chunk WHERE id=%s", chunk_id)[0][0]
        sizes = sql(
            admin,
            "SELECT pg_total_relation_size('app.core_measurement_202501'),"
            " pg_total_relation_size('app.argo_profile'),"
            " pg_total_relation_size('app.ingestion_staging')",
        )[0]
    print(json.dumps(stages, indent=1), flush=True)
    if outcome == "complete":
        # The next chunk touching this slot must read every retained profile back;
        # a fresh claimed chunk stands in for it (the completed chunk is fenced).
        successor = uuid.uuid4()
        with psycopg.connect(url, autocommit=True) as admin:
            sql(
                admin,
                f"""
                INSERT INTO app.ingestion_chunk(id,run_id,logical_chunk_key,requested_start,
                  requested_end,tile,plan_version)
                VALUES('{successor}','{RUN}','{label}-next','2025-01-01','2025-02-01',
                  '{{"west":{west},"south":{south},"width":10,"height":10}}','v2');
                SELECT app.claim_chunk('{RUN}','{successor}',1);
                SELECT app.transition_chunk('{RUN}','{successor}',1,1,'fetching','probe');
                SELECT app.transition_chunk('{RUN}','{successor}',1,1,'landed','probe');
                SELECT app.transition_chunk('{RUN}','{successor}',1,1,'validating','probe');
                SELECT app.transition_chunk('{RUN}','{successor}',1,1,'publishing','probe');
            """,
            )
        authority = Authority(uuid.UUID(RUN), successor, 1, 1)
        with repository.retained_snapshot(authority, (slot,), budget_repository) as (bases2, rows2):
            retained = timed(
                stages,
                "retained_snapshot read after commit (all slot profiles, science_row verify)",
                lambda: list(rows2),
            )
        first = retained[0].identity.id
        timed(
            stages,
            "load_science x5 (one profile)",
            lambda: [repository.load_science(first, CanonicalBudget()) for _ in range(5)],
        )
        timed(
            stages,
            "slot_members query",
            lambda: repository.slot_members(
                authority,
                slot,
                __import__(
                    "floatchat_core.ingestion.planning", fromlist=["PlannedChunk"]
                ).PlannedChunk(
                    __import__("floatchat_core.ingestion.planning", fromlist=["Interval"]).Interval(
                        datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)
                    ),
                    __import__("floatchat_core.ingestion.planning", fromlist=["Tile"]).Tile(
                        west, south
                    ),
                ),
            ),
        )
        # Release the stand-in so the environment's two-active-chunk bound holds.
        repository.transition(authority, "failed", "probe_released")
    else:
        repository.transition(authority, "failed", "probe_" + outcome)
    spool.connection.close()
    repository.close()
    budget_repository.close()
    return {
        "label": label,
        "profiles": profiles_count,
        "levels_per_profile": levels,
        "levels": profiles_count * levels,
        "staging_ndjson_bytes": staged.stat().st_size,
        "parquet_bytes": file.stat().st_size,
        "chunk_state": state,
        "outcome": outcome,
        "core_measurement_rows_in_month": stored,
        "relation_bytes": {
            "core_measurement_202501": sizes[0],
            "argo_profile": sizes[1],
            "ingestion_staging": sizes[2],
        },
        "stages_s": stages,
        "retained_profiles_read_back": len(retained),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--memory", default="768m")
    parser.add_argument("--scenario", action="append", default=[], help="profiles:levels")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    name, port = start_container(args.memory)
    url = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    report = {
        "kind": "stage1_disposable_db_commit_timings",
        "image": IMAGE,
        "container_memory": args.memory,
        "scope": "Synthetic clone chunks; disposable PostgreSQL only; not acceptance evidence",
        "scenarios": [],
    }
    try:
        migrate(url)
        tiles = [(70, 10), (80, 10), (90, 10), (60, 10)]
        offset = 0
        for index, item in enumerate(args.scenario or ["22:699", "87:699"]):
            count, levels = (int(x) for x in item.split(":"))
            west, south = tiles[index]
            report["scenarios"].append(
                scenario(url, args.work, count, levels, west, south, f"probe-{index}", offset)
            )
            offset += count
            stats = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
                capture_output=True,
                text=True,
            ).stdout.strip()
            report["scenarios"][-1]["db_container_memory_after"] = stats
            print(json.dumps(report["scenarios"][-1], indent=1))
    finally:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", name],
                check=True,
                capture_output=True,
                timeout=60,
            )
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
