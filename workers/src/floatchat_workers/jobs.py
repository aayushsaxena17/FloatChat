"""The jobs worker (ADR-0077, ADR-0079, ADR-0080): ``floatchat jobs --queues export``.

One process claims jobs of its queues from PostgreSQL, admits historical ingestion runs on
the ingestion login, exports with DuckDB over its own part cache and uploads the artefacts on
the application's object-storage credentials. A reconciler tick expires artefacts (state
before object), deletes their objects and removes export objects no artefact row names.
"""

import logging
import os
import signal
import socket
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

import boto3
from botocore.config import Config
from floatchat_core.chat.store import app_engine_from_url
from floatchat_core.config import Settings
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.jobs.artefacts import OBJECT_KEY
from floatchat_core.jobs.export import ExportWriter
from floatchat_core.jobs.ingestion import RepositoryRuns
from floatchat_core.jobs.model import JobLimits
from floatchat_core.jobs.runner import JobRunner
from floatchat_core.jobs.store import JobStore, PostgresJobStore
from floatchat_core.query.cache import PartCache
from floatchat_core.query.catalogue import QueryCatalogue, engine_from_url
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits

from .ingestion import Configuration

QUEUES = ("interactive-analysis", "bulk-analysis", "export", "forecast")
IDLE_SECONDS = 2.0
RECONCILE_SECONDS = 60.0


def storage(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key.get_secret_value(),
        aws_secret_access_key=settings.object_storage_secret_key.get_secret_value(),
        region_name=settings.object_storage_region,
        config=Config(
            connect_timeout=5,
            read_timeout=120,
            retries={"total_max_attempts": 3},
            s3={"addressing_style": "path"},
        ),
    )


class Reconciler:
    """Artefact expiry and orphan export objects (PRD §8.4 order, §22 row 7)."""

    def __init__(self, store: JobStore, client: Any, bucket: str, limits: JobLimits) -> None:
        self.store, self.client, self.bucket, self.limits = store, client, bucket, limits

    def tick(self, now: datetime | None = None) -> dict[str, int]:
        moment = now or datetime.now(UTC)
        expired = deleted = orphans = 0
        for artefact in self.store.expire_artefacts(moment):
            expired += 1
            try:
                self.client.delete_object(Bucket=self.bucket, Key=artefact.object_key)
                self.store.mark_deleted(artefact.id, moment)
                deleted += 1
            except Exception:
                continue  # the next tick retries; the row already says expired
        known = self.store.known_object_keys()
        threshold = moment - timedelta(seconds=self.limits.orphan_age_seconds)
        token: str | None = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": "exports/", "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                page = self.client.list_objects_v2(**kwargs)
            except Exception:
                break
            for item in page.get("Contents", []):
                key = item["Key"]
                modified = item.get("LastModified")
                if (
                    OBJECT_KEY.fullmatch(key)
                    and key not in known
                    and modified is not None
                    and modified.astimezone(UTC) <= threshold
                ):
                    try:
                        self.client.delete_object(Bucket=self.bucket, Key=key)
                        orphans += 1
                    except Exception:
                        continue
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")
        return {"expired": expired, "deleted": deleted, "orphans_removed": orphans}


def build(queues: tuple[str, ...]) -> tuple[JobRunner, Reconciler, Configuration]:
    settings = Settings()
    limits = JobLimits()
    configuration = Configuration.load()
    repository = configuration.repository()
    store = PostgresJobStore(app_engine_from_url(settings.database_url.get_secret_value()))
    if settings.query_database_url is None:
        raise Rejection("invalid_ingestion_configuration")
    query_limits = QueryLimits(time_span_days=limits.time_span_days)
    query_engine = engine_from_url(settings.query_database_url.get_secret_value(), query_limits)
    catalogue = QueryCatalogue(query_engine, query_limits)
    client = storage(settings)
    bucket = settings.object_storage_bucket

    def fetch(key: str, byte_count: int) -> bytes:
        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"]
            return bytes(body.read())
        except Exception as error:  # boto3 raises many classes; the cache verifies bytes
            raise QueryError("execution_failed", message="object fetch failed") from error

    cache_dir = Path(os.environ.get("JOBS_CACHE_DIR", "/var/lib/floatchat/jobs-cache"))
    export_dir = Path(os.environ.get("JOBS_EXPORT_DIR", "/var/lib/floatchat/jobs-export"))
    cache = PartCache(cache_dir, limits.cache_bytes, fetch)

    def upload(key: str, path: Path) -> None:
        with path.open("rb") as handle:
            client.put_object(Bucket=bucket, Key=key, Body=handle)

    writer = ExportWriter(
        query_engine=query_engine,
        cache=cache,
        export_directory=export_dir,
        upload=upload,
        limits=limits,
        application_commit=configuration.application_commit,
    )
    runs = RepositoryRuns(repository, configuration.environment, limits)
    worker = f"jobs:{socket.gethostname()[:64]}:{os.getpid()}"
    runner = JobRunner(store, catalogue, runs, writer, limits=limits, worker=worker)
    return runner, Reconciler(store, client, bucket, limits), configuration


def main(queues: tuple[str, ...]) -> int:
    unknown = set(queues) - set(QUEUES)
    if unknown or not queues:
        print("invalid_job_queues", flush=True)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    runner, reconciler, _configuration = build(queues)
    stop = False

    def request_stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    print(f"jobs worker serving {','.join(queues)}", flush=True)
    last_reconcile = 0.0
    while not stop:
        try:
            job = runner.run_once(queues)
            if job is not None:
                print(f"job={job.id} handled", flush=True)
                continue
            if time.monotonic() - last_reconcile >= RECONCILE_SECONDS:
                summary = reconciler.tick()
                last_reconcile = time.monotonic()
                if any(summary.values()):
                    print(f"reconcile {summary}", flush=True)
        except Exception as error:
            # Fixed categories only; the job rows carry the detail. A database outage pauses
            # claiming rather than failing the worker.
            category = error.category if isinstance(error, Rejection) else type(error).__name__
            print(f"jobs_worker_error {category}", flush=True)
            time.sleep(10)
            continue
        time.sleep(IDLE_SECONDS)
    return 0
