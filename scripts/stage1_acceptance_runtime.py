"""Container-side acceptance setup/proof and owner-only runtime entrypoint.

No Argovis key is loaded in initialize/proof/offline worker/supervisor modes.
All exception output is a fixed category, never a representation or traceback.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

import psycopg
import redis
from botocore.exceptions import ClientError
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.reporting import persisted_report
from floatchat_workers.ingestion import Configuration, live_enabled
from psycopg import sql


def configure_broker():
    from floatchat_workers.app import app

    prefix = os.environ["ACCEPTANCE_REDIS_PREFIX"]
    app.conf.broker_transport_options = {"global_keyprefix": prefix, "visibility_timeout": 43200}
    app.conf.result_backend_transport_options = {"global_keyprefix": prefix}
    return app


def initialize():
    # A fresh database does not inherit Stage 0's application role. Its NOLOGIN
    # placeholder is required by the accepted migrations' explicit revokes.
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            name = os.environ["ACCEPTANCE_DATABASE"]
            if cursor.fetchone()[0] != name or not name.startswith("floatchat_s1_"):
                raise Rejection("unsafe_acceptance_database")
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='floatchat_app'")
            if cursor.fetchone() is None:
                cursor.execute(
                    "CREATE ROLE floatchat_app NOLOGIN NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                )
    subprocess.run(
        ["alembic", "-c", "infra/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        timeout=90,
    )
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            name = os.environ["ACCEPTANCE_DATABASE"]
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != name or not name.startswith("floatchat_s1_"):
                raise Rejection("unsafe_acceptance_database")
            cursor.execute(
                "CREATE ROLE acceptance_ingestion LOGIN INHERIT NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOBYPASSRLS"
            )
            cursor.execute(
                sql.SQL("ALTER ROLE acceptance_ingestion PASSWORD {}").format(
                    sql.Literal(os.environ["ACCEPTANCE_DB_PASSWORD"])
                )
            )
            cursor.execute("GRANT floatchat_ingestor TO acceptance_ingestion")
            cursor.execute("GRANT SELECT ON public.alembic_version TO floatchat_ingestor")
            cursor.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO acceptance_ingestion").format(
                    sql.Identifier(name)
                )
            )
            cursor.execute(
                "INSERT INTO app.ingestion_environment VALUES(%s,%s,'acceptance',true,%s,%s,%s)",
                (
                    uuid.UUID(os.environ["INGESTION_ENVIRONMENT_ID"]),
                    os.environ["COMPOSE_PROJECT_NAME"],
                    os.environ["INGESTION_BUCKET"],
                    os.environ["INGESTION_QUEUE_NAMESPACE"],
                    os.environ["COMPOSE_PROJECT_NAME"],
                ),
            )
    print("isolated_acceptance_database_initialized")


def proof():
    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT current_database() AS database,session_user AS login,current_user AS role"
            )
            identity = dict(cursor.fetchone())
            cursor.execute("SELECT version_num FROM public.alembic_version")
            revision = cursor.fetchone()["version_num"]
            cursor.execute(
                "SELECT (SELECT count(*) FROM app.ingestion_run) AS runs, "
                "(SELECT count(*) FROM app.argo_profile) AS profiles, "
                "(SELECT count(*) FROM app.core_measurement) AS levels"
            )
            counts = dict(cursor.fetchone())
        assert identity["database"].startswith("floatchat_s1_")
        assert (
            identity["login"] == "acceptance_ingestion" and identity["role"] == "floatchat_ingestor"
        )
        assert revision == "0010_stage1_v3_runtime" and counts == {
            "runs": 0,
            "profiles": 0,
            "levels": 0,
        }
        assert not live_enabled()
        store = configuration.store()
        marker = b"isolated-acceptance-storage-proof-v1"
        key = "isolation-proof/" + hashlib.sha256(marker).hexdigest() + ".json"
        store.client.put_object(Bucket=configuration.bucket, Key=key, Body=marker)
        response = store.client.get_object(Bucket=configuration.bucket, Key=key)
        assert response["Body"].read() == marker
        response["Body"].close()
        try:
            store.client.list_objects_v2(Bucket=os.environ["ACCEPTANCE_CONTROL_BUCKET"], MaxKeys=1)
        except ClientError as error:
            if error.response["Error"]["Code"] != "AccessDenied":
                raise Rejection("acceptance_storage_scope_unproved") from None
            scoped = True
        else:
            raise Rejection("unscoped_acceptance_storage_identity")
        broker = redis.Redis(host="redis", port=6379, db=13)
        assert broker.ping()
        app = configure_broker()
        until = time.monotonic() + 60
        while not app.control.ping(timeout=1):
            assert time.monotonic() < until
            time.sleep(0.5)
        result = app.send_task(
            "floatchat.smoke", args=["acceptance-isolation"], queue=configuration.queue, retry=False
        )
        assert result.get(timeout=20) == "ok:acceptance-isolation"
        assert broker.llen(os.environ["ACCEPTANCE_REDIS_PREFIX"] + configuration.queue) == 0
        from floatchat_workers.cli import main

        assert (
            main(
                [
                    "ingest",
                    "--mode",
                    "acceptance",
                    "--from",
                    "2025-01",
                    "--to",
                    "2025-03",
                    "--live-opt-in",
                ]
            )
            == 2
        )
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute("SELECT count(*) AS n FROM app.ingestion_run")
            assert cursor.fetchone()["n"] == 0
        print(
            json.dumps(
                {
                    "kind": "offline_acceptance_isolation_proof",
                    "identity": identity,
                    "migration": revision,
                    "science_counts": counts,
                    "environment": dict(repository.environment(configuration.environment)),
                    "bucket_readback_sha256": hashlib.sha256(marker).hexdigest(),
                    "bucket_scoped_identity": scoped,
                    "denied_control_bucket": os.environ["ACCEPTANCE_CONTROL_BUCKET"],
                    "redis_database": 13,
                    "redis_prefix": os.environ["ACCEPTANCE_REDIS_PREFIX"],
                    "queue": configuration.queue,
                    "smoke_acknowledged": True,
                    "live_disabled_admission_refused": True,
                    "run_created": False,
                },
                default=str,
            )
        )
    finally:
        repository.close()


def report(run):
    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        evidence = persisted_report(repository, uuid.UUID(run))
        print(json.dumps(evidence, default=str, sort_keys=True))
    finally:
        repository.close()


def progress(request):
    """Bounded read-only counters; no payloads, source fields or credentials."""
    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        with repository.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT id,state,closed,http_attempts,accepted_profiles,accepted_levels,"
                "deadline FROM app.ingestion_run WHERE request_id=%s",
                (uuid.UUID(request),),
            )
            row = cursor.fetchone()
            if row is None:
                print(json.dumps({"state": "awaiting_admission", "leaf_states": {}}))
                return
            result = dict(row)
            cursor.execute(
                "SELECT state,count(*) AS n FROM app.ingestion_chunk "
                "WHERE run_id=%s AND leaf GROUP BY state",
                (row["id"],),
            )
            result["leaf_states"] = {item["state"]: item["n"] for item in cursor.fetchall()}
        print(json.dumps(result, default=str))
    finally:
        repository.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("initialize", "proof", "worker", "supervise", "ingest", "report", "progress"),
    )
    parser.add_argument("--stdin-key", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--request-id")
    parser.add_argument("--replay-run")
    args = parser.parse_args()
    if args.stdin_key:
        if args.command != "worker" or not live_enabled():
            raise Rejection("live_acceptance_opt_in_required")
        # Owner execution only. The preparation path never reads this stream/key.
        key = sys.stdin.buffer.readline(4097).decode().rstrip("\n")
        if not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise Rejection("invalid_owner_credential")
        os.environ["ARGOVIS_API_KEY"] = key
    if args.command == "initialize":
        initialize()
    elif args.command == "proof":
        proof()
    elif args.command == "report":
        report(args.run_id)
    elif args.command == "progress":
        progress(args.request_id)
    else:
        app = configure_broker()
        if args.command == "worker":
            app.worker_main(
                [
                    "worker",
                    "--loglevel=WARNING",
                    "--concurrency=1",
                    "-Q",
                    os.environ["INGESTION_QUEUE_NAMESPACE"],
                    "--hostname=acceptance@%h",
                ]
            )
        else:
            from floatchat_workers.cli import main as cli

            arguments = (
                ["supervise"]
                if args.command == "supervise"
                else [
                    "ingest",
                    "--mode",
                    "acceptance",
                    "--region",
                    "indian-ocean",
                    "--from",
                    "2025-01",
                    "--to",
                    "2025-03",
                    "--execution-seconds",
                    "43200",
                    "--request-id",
                    args.request_id,
                ]
            )
            if args.command == "ingest":
                arguments += (
                    ["--replay-run", args.replay_run] if args.replay_run else ["--live-opt-in"]
                )
            raise SystemExit(cli(arguments))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("acceptance_runtime_failed_no_sensitive_diagnostics", file=sys.stderr)
        raise SystemExit(5) from None
