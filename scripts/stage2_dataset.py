"""Copy the accepted Stage 1 science of a preserved acceptance session into the dev project.

ADR-0059. The preserved session is read only: this script starts only its ``db-1`` and
``minio-1`` containers, never a worker, applies no migration to it, attaches nothing to it and
stops it again. The copy lands in the local dev Compose project (``make dev`` must be running)
as derived evidence for development and the latency report; it is never pushed.

    uv run --all-packages --frozen python scripts/stage2_dataset.py import --session <id>

Credentials are read from the restricted session and development environment files and
passed to one-off containers through 0600 env files; nothing is printed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.dev import configuration_root  # noqa: E402

SESSIONS = ROOT / ".cache/stage1-acceptance"
BASE_TABLES = [
    "ingestion_environment",
    "ingestion_run",
    "ingestion_chunk",
    "ingestion_attempt",
    "raw_manifest",
    "argo_float",
    "argo_profile",
    "logical_partition_slot",
    "publication_intent",
    "dataset_partition",
    "coverage_receipt",
]
WORKERS = ("acquire", "process", "supervisor", "worker", "client")
API_IMAGE = "floatchat-stage0-wsl-dev-api:latest"
COPY_SCRIPT = r"""
import hashlib, json, os, sys
import boto3
from botocore.config import Config
mode, listing, directory = sys.argv[1], sys.argv[2], sys.argv[3]
client = boto3.client(
    "s3",
    endpoint_url=os.environ["ENDPOINT"],
    aws_access_key_id=os.environ["KEY"],
    aws_secret_access_key=os.environ["SECRET"],
    region_name="us-east-1",
    config=Config(
        connect_timeout=5,
        read_timeout=120,
        retries={"total_max_attempts": 3},
        s3={"addressing_style": "path"},
    ),
)
bucket = os.environ["BUCKET"]
items = json.load(open(listing))
done = 0
for item in items:
    key, digest, size = item["object_key"], item["sha256"], int(item["bytes"])
    path = os.path.join(directory, digest + ".parquet")
    if mode == "download":
        payload = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    else:
        with open(path, "rb") as handle:
            payload = handle.read()
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise SystemExit("verification failed for " + key)
    if mode == "download":
        with open(path, "wb") as handle:
            handle.write(payload)
    else:
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            if int(head["ContentLength"]) == size:
                done += 1
                continue
        except Exception:
            pass
        client.put_object(Bucket=bucket, Key=key, Body=payload, ContentLength=size)
    done += 1
print(json.dumps({"mode": mode, "objects": done, "bytes": sum(int(i["bytes"]) for i in items)}))
"""


class Failure(RuntimeError):
    pass


def run(args: list[str], *, timeout: int = 600, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(args, capture_output=True, timeout=timeout, input=input_bytes)
    if result.returncode != 0:
        raise Failure(
            f"{args[0]} {args[1] if len(args) > 1 else ''} failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')[-800:]}"
        )
    return result.stdout.decode()


def env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    return values


def container_state(name: str) -> str | None:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def psql(container: str, user: str, database: str, sql: str, *, timeout: int = 600) -> str:
    return run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-X",
            "-q",
            "-t",
            "-A",
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
        ],
        timeout=timeout,
        input_bytes=sql.encode(),
    ).strip()


def wait_postgres(container: str, user: str, database: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", user, "-d", database],
            capture_output=True,
            timeout=15,
        )
        if probe.returncode == 0:
            return
        time.sleep(1)
    raise Failure(f"{container} did not become ready")


def wait_minio(container: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        probe = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen("
                "'http://127.0.0.1:9000/minio/health/ready', timeout=2)",
            ],
            capture_output=True,
            timeout=15,
        )
        if probe.returncode == 0:
            return
        time.sleep(1)
    raise Failure(f"{container} did not become ready")


def fk_closure(container: str, database: str, tables: list[str]) -> list[str]:
    """Tables plus every ``app`` table they reference through foreign keys, transitively."""
    wanted = list(tables)
    index = 0
    while index < len(wanted):
        table = wanted[index]
        index += 1
        referenced = psql(
            container,
            "floatchat_admin",
            database,
            "SELECT DISTINCT confrelid::regclass::text FROM pg_constraint WHERE contype='f' "
            f"AND conrelid='app.{table}'::regclass",
        )
        for name in referenced.splitlines():
            name = name.strip().removeprefix("app.")
            if name and name not in wanted:
                wanted.append(name)
    return wanted


def ordered_for_restore(container: str, database: str, tables: list[str]) -> list[str]:
    """Order by foreign-key dependencies (referenced tables first); pg_dump also orders."""
    remaining = list(tables)
    ordered: list[str] = []
    deps: dict[str, set[str]] = {}
    for table in remaining:
        referenced = psql(
            container,
            "floatchat_admin",
            database,
            "SELECT DISTINCT confrelid::regclass::text FROM pg_constraint WHERE contype='f' "
            f"AND conrelid='app.{table}'::regclass AND confrelid<>conrelid",
        )
        deps[table] = {n.strip().removeprefix("app.") for n in referenced.splitlines() if n.strip()}
    while remaining:
        progress = [t for t in remaining if deps[t] <= set(ordered)]
        if not progress:
            raise Failure("circular foreign keys among " + ", ".join(remaining))
        ordered.extend(progress)
        remaining = [t for t in remaining if t not in progress]
    return ordered


def stream_table(
    source: str, source_database: str, target: str, table: str, predicate: str, digest: Any
) -> int:
    """COPY one table (or one month of it) in binary form from source to target."""
    reader = subprocess.Popen(
        [
            "docker",
            "exec",
            source,
            "psql",
            "-X",
            "-q",
            "-U",
            "floatchat_admin",
            "-d",
            source_database,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            f"COPY (SELECT * FROM app.{table} WHERE {predicate}) TO STDOUT (FORMAT binary)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    writer = subprocess.Popen(
        [
            "docker",
            "exec",
            "-i",
            target,
            "psql",
            "-X",
            "-q",
            "-U",
            "floatchat_admin",
            "-d",
            "floatchat",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SET session_replication_role = replica",
            "-c",
            f"COPY app.{table} FROM STDIN (FORMAT binary)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert reader.stdout is not None and writer.stdin is not None
    total = 0
    try:
        while True:
            block = reader.stdout.read(1 << 20)
            if not block:
                break
            digest.update(block)
            total += len(block)
            writer.stdin.write(block)
    except BrokenPipeError:
        pass
    finally:
        try:
            writer.stdin.close()
        except BrokenPipeError:
            pass
    reader_status = reader.wait(timeout=3600)
    writer_status = writer.wait(timeout=3600)
    if reader_status != 0:
        error = reader.stderr.read().decode(errors="replace") if reader.stderr else ""
        raise Failure(f"COPY out of app.{table} ({predicate}) failed: {error[-600:]}")
    if writer_status != 0:
        error = writer.stderr.read().decode(errors="replace") if writer.stderr else ""
        raise Failure(f"COPY into app.{table} ({predicate}) failed: {error[-600:]}")
    return total


def copy_objects(
    network: str, env: dict[str, str], listing: list[dict[str, object]], objects: Path, mode: str
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(dir=objects.parent) as scratch:
        work = Path(scratch)
        (work / "copy.py").write_text(COPY_SCRIPT)
        (work / "listing.json").write_text(json.dumps(listing))
        env_path = work / "env"
        env_path.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
        env_path.chmod(0o600)
        os.chmod(work, 0o755)
        output = run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--env-file",
                str(env_path),
                "-v",
                f"{work}:/work:ro",
                "-v",
                f"{objects}:/objects",
                API_IMAGE,
                "python",
                "/work/copy.py",
                mode,
                "/work/listing.json",
                "/objects",
            ],
            timeout=3600,
        )
    return json.loads(output.strip().splitlines()[-1])


def import_session(session: str, report_path: Path | None) -> None:
    started = time.monotonic()
    if re.fullmatch(r"[a-f0-9]{16}", session) is None:
        raise Failure("invalid session identifier")
    session_env = env_file(SESSIONS / session / "environment.env")
    project = f"floatchat-s1-acceptance-{session}"
    source_db, source_minio = f"{project}-db-1", f"{project}-minio-1"
    source_network = f"{project}_default"
    source_database = session_env["ACCEPTANCE_DATABASE"]
    for role in WORKERS:
        if container_state(f"{project}-{role}-1") == "running":
            raise Failure(f"{project}-{role}-1 is running; the session must be at rest")
    dev_env = env_file(configuration_root() / ".env")
    dev_project = dev_env.get("COMPOSE_PROJECT_NAME", "floatchat-dev")
    target_db, target_minio = f"{dev_project}-db-1", f"{dev_project}-minio-1"
    target_network = f"{dev_project}_default"
    if container_state(target_db) != "running" or container_state(target_minio) != "running":
        raise Failure(f"dev project {dev_project} is not running; run make dev first")
    existing = psql(
        target_db, "floatchat_admin", "floatchat", "SELECT count(*) FROM app.ingestion_environment"
    )
    if existing != "0":
        raise Failure("the dev database already holds an ingestion environment; refusing")
    head = psql(
        target_db, "floatchat_admin", "floatchat", "SELECT version_num FROM alembic_version"
    )
    if head != "0016_query_access":
        raise Failure(f"dev database migration head is {head}, expected 0016_query_access")

    started_source = []
    try:
        for name in (source_db, source_minio):
            if container_state(name) != "running":
                run(["docker", "start", name], timeout=120)
                started_source.append(name)
        wait_postgres(source_db, "floatchat_admin", source_database)
        wait_minio(source_minio)
        tables = fk_closure(source_db, source_database, BASE_TABLES)
        tables = ordered_for_restore(source_db, source_database, tables)
        months = psql(
            source_db,
            "floatchat_admin",
            source_database,
            "SELECT DISTINCT observation_month FROM app.argo_profile ORDER BY 1",
        ).splitlines()
        source_counts = {
            table: int(
                psql(
                    source_db,
                    "floatchat_admin",
                    source_database,
                    f"SELECT count(*) FROM app.{table}",
                )
            )
            for table in tables
        }
        source_counts["core_measurement"] = int(
            psql(
                source_db,
                "floatchat_admin",
                source_database,
                "SELECT count(*) FROM app.core_measurement",
            )
        )
        run_rows = psql(
            source_db,
            "floatchat_admin",
            source_database,
            "SELECT id||'|'||state||'|'||run_reference_time_utc FROM app.ingestion_run "
            "ORDER BY created_at_actual_utc",
        )
        listing_text = psql(
            source_db,
            "floatchat_admin",
            source_database,
            "SELECT json_agg(json_build_object('object_key',object_key,'sha256',sha256,"
            "'bytes',bytes)) "
            "FROM app.committed_active_partitions",
        )
        listing = json.loads(listing_text or "[]")

        # Partitions first: data-only restores need the monthly children to exist.
        for month in months:
            name = "core_measurement_" + month.replace("-", "")[:6]
            psql(
                target_db,
                "floatchat_admin",
                "floatchat",
                f"CREATE TABLE IF NOT EXISTS app.{name} PARTITION OF app.core_measurement "
                f"FOR VALUES FROM ('{month}') TO (('{month}'::date + interval '1 month')::date); "
                f"REVOKE ALL ON app.{name} FROM PUBLIC, floatchat_app, floatchat_ingestor; "
                f"GRANT SELECT ON app.{name} TO floatchat_ingestor;",
            )

        work_root = configuration_root().parent / "stage2-dataset" / session
        work_root.mkdir(parents=True, exist_ok=True)
        # Streamed binary COPY, table by table and month by month for the two large tables:
        # no temp file on the host, bounded memory on both servers, FK triggers off on the
        # target for the duration (session_replication_role = replica, superuser only).
        stream_sha256 = hashlib.sha256()
        copied_bytes = 0
        for table in [*tables, "core_measurement"]:
            predicates = ["TRUE"]
            if table in ("argo_profile", "core_measurement"):
                predicates = [f"observation_month = '{month}'" for month in months]
            for predicate in predicates:
                copied_bytes += stream_table(
                    source_db, source_database, target_db, table, predicate, stream_sha256
                )
        psql(
            target_db,
            "floatchat_admin",
            "floatchat",
            "; ".join(f"ANALYZE app.{table}" for table in [*tables, "core_measurement"]),
            timeout=1800,
        )

        objects = work_root / "objects"
        objects.mkdir(exist_ok=True)
        objects.chmod(0o777)
        downloaded = copy_objects(
            source_network,
            {
                "ENDPOINT": "http://minio:9000",
                "KEY": session_env["OBJECT_STORAGE_ACCESS_KEY"],
                "SECRET": session_env["OBJECT_STORAGE_SECRET_KEY"],
                "BUCKET": session_env["INGESTION_BUCKET"],
            },
            listing,
            objects,
            "download",
        )
        uploaded = copy_objects(
            target_network,
            {
                "ENDPOINT": dev_env.get("OBJECT_STORAGE_ENDPOINT", "http://minio:9000"),
                "KEY": dev_env["OBJECT_STORAGE_ACCESS_KEY"],
                "SECRET": dev_env["OBJECT_STORAGE_SECRET_KEY"],
                "BUCKET": dev_env.get("OBJECT_STORAGE_BUCKET", "floatchat-dev"),
            },
            listing,
            objects,
            "upload",
        )
    finally:
        for name in started_source:
            subprocess.run(["docker", "stop", name], capture_output=True, timeout=120)

    target_counts = {
        table: int(
            psql(target_db, "floatchat_admin", "floatchat", f"SELECT count(*) FROM app.{table}")
        )
        for table in [*tables, "core_measurement"]
    }
    mismatches = {
        t: (source_counts[t], target_counts[t])
        for t in target_counts
        if source_counts[t] != target_counts[t]
    }
    if mismatches:
        raise Failure(f"row counts differ after restore: {mismatches}")
    active = psql(
        target_db,
        "floatchat_admin",
        "floatchat",
        "SELECT count(*)||'|'||coalesce(sum(bytes),0) FROM app.committed_active_partitions",
    )
    report = {
        "kind": "stage2_dataset_import",
        "adr": "ADR-0059",
        "session": session,
        "source_project": project,
        "source_database": source_database,
        "source_runs": [
            dict(zip(("id", "state", "reference_time"), r.split("|"), strict=True))
            for r in run_rows.splitlines()
        ],
        "target_project": dev_project,
        "tables": tables,
        "row_counts": target_counts,
        "measurement_months": months,
        "stream_sha256": stream_sha256.hexdigest(),
        "stream_bytes": copied_bytes,
        "objects": {"downloaded": downloaded, "uploaded": uploaded, "active_partitions": active},
        "git_head": run(["git", "rev-parse", "--short=12", "HEAD"], timeout=30).strip(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "seconds": round(time.monotonic() - started, 1),
        "scope": "derived copy of accepted science for development and the latency report; "
        "never pushed; the preserved session was not modified",
    }
    report_path = report_path or ROOT / "reports" / f"stage2-dataset-{session}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    shutil.rmtree(objects, ignore_errors=True)
    print(
        f"imported session {session} into {dev_project}: {target_counts['argo_profile']} profiles, "
        f"{target_counts['core_measurement']} levels, objects {active}; "
        f"report {report_path.relative_to(ROOT)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import")
    importer.add_argument("--session", required=True)
    importer.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    try:
        import_session(args.session, args.report)
    except Failure as error:
        print(f"stage2 dataset import failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
