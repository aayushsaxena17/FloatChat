"""Development-stack worker entrypoint (Stage 5, ADR-0078).

The ingestion pool and the jobs worker need the id of the one ingestion environment of the
database, which the bootstrap adopts into this stack (bucket, queue namespace, compose
project). A fresh stack has no environment yet, so this entrypoint waits, polling every ten
seconds, until exactly one environment exists and its marker matches the service
configuration; then it runs the requested role in-process. No credential is printed.
"""

import os
import sys
import time

import psycopg
from floatchat_workers.cli import main

ROLES = ("acquire", "process", "supervise", "jobs")


def resolve_environment() -> str | None:
    """The single adopted environment id, or None while the stack is not ready."""
    expected = (
        os.environ["INGESTION_BUCKET"],
        os.environ["INGESTION_QUEUE_NAMESPACE"],
        os.environ["COMPOSE_PROJECT_NAME"],
    )
    try:
        with psycopg.connect(os.environ["INGESTION_DATABASE_URL"], connect_timeout=5) as link:
            with link.cursor() as cursor:
                cursor.execute("SET ROLE floatchat_ingestor")
                cursor.execute(
                    "SELECT id, bucket, queue_namespace, compose_project "
                    "FROM app.ingestion_environment"
                )
                rows = cursor.fetchall()
    except psycopg.Error:
        return None
    if len(rows) != 1 or tuple(rows[0][1:]) != expected:
        return None
    return str(rows[0][0])


def run(role: str) -> int:
    if role not in ROLES:
        print("invalid_worker_role", flush=True)
        return 2
    while True:
        identifier = resolve_environment()
        if identifier is not None:
            break
        print(f"{role}: waiting for one adopted ingestion environment", flush=True)
        time.sleep(10)
    os.environ["INGESTION_ENVIRONMENT_ID"] = identifier
    arguments = [role]
    if role == "jobs":
        arguments += ["--queues", os.environ.get("JOBS_QUEUES", "export")]
    return main(arguments)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1] if len(sys.argv) > 1 else ""))
