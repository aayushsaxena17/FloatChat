"""Opaque-ticket worker entrypoint. Celery owns no ingestion retry budget."""

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.private import private_directory
from floatchat_core.ingestion.processor import Processor
from floatchat_core.ingestion.repository import Repository
from floatchat_core.ingestion.source import RecordedSource, Source
from floatchat_core.ingestion.states import TERMINAL


@dataclass(frozen=True, repr=False)
class Configuration:
    database_url: str = field(repr=False)
    environment: uuid.UUID
    bucket: str
    queue: str
    project: str
    broker_url: str = field(repr=False)
    endpoint: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    application_commit: str
    private: Path

    @classmethod
    def load(cls) -> "Configuration":
        # The upstream key is deliberately absent. Only a live request can load
        # it; argument/configuration diagnostics never contain environment input.
        try:
            broker = os.environ["INGESTION_REDIS_URL"]
            parsed = urlsplit(broker)
            if (
                parsed.scheme != "redis"
                or parsed.hostname not in ("redis", "localhost", "127.0.0.1", "::1")
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            return cls(
                os.environ["INGESTION_DATABASE_URL"],
                uuid.UUID(os.environ["INGESTION_ENVIRONMENT_ID"]),
                os.environ["INGESTION_BUCKET"],
                os.environ["INGESTION_QUEUE_NAMESPACE"],
                os.environ["COMPOSE_PROJECT_NAME"],
                broker,
                os.environ["OBJECT_STORAGE_ENDPOINT"],
                os.environ["OBJECT_STORAGE_ACCESS_KEY"],
                os.environ["OBJECT_STORAGE_SECRET_KEY"],
                os.environ["INGESTION_APPLICATION_COMMIT"],
                Path.home() / "private/floatchat-stage1",
            )
        except (KeyError, ValueError):
            raise Rejection("invalid_ingestion_configuration") from None

    def repository(self) -> Repository:
        repository = Repository(self.database_url)
        try:
            with repository.transaction() as cursor:
                cursor.execute(
                    "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls AS unsafe "
                    "FROM pg_roles WHERE rolname=session_user"
                )
                if cursor.fetchone()["unsafe"]:
                    raise Rejection("privileged_ingestion_login_rejected")
                cursor.execute("SET ROLE floatchat_ingestor")
                cursor.execute(
                    "SELECT has_table_privilege(session_user,'app.argo_profile',"
                    "'INSERT,UPDATE,DELETE') "
                    "AS unsafe"
                )
                if cursor.fetchone()["unsafe"]:
                    raise Rejection("privileged_ingestion_login_rejected")
            marker = repository.environment(self.environment)
            if (marker["bucket"], marker["queue_namespace"], marker["compose_project"]) != (
                self.bucket,
                self.queue,
                self.project,
            ):
                raise Rejection("unsafe_environment")
            if marker["mode"] == "acceptance" and not marker["disposable"]:
                raise Rejection("unsafe_environment")
            return repository
        except Exception:
            repository.close()
            raise

    def store(self) -> MinioStore:
        return MinioStore(self.endpoint, self.bucket, self.access_key, self.secret_key)


def live_enabled() -> bool:
    return os.environ.get("FLOATCHAT_LIVE_INGESTION_ENABLED", "false") == "true"


def bounded_worker_memory() -> None:
    try:
        value = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if value == "max" or not 0 < int(value) <= 1024**3:
            raise ValueError
    except (OSError, ValueError):
        raise Rejection("worker_requires_one_gib_cgroup") from None


def upstream_credential() -> str:
    credential = os.environ.get("ARGOVIS_API_KEY")
    if not credential:
        raise Rejection("ARGOVIS_API_KEY")
    return credential


def process_ticket(run_id: str, chunk_id: str, ticket_id: str) -> str:
    repository: Repository | None = None
    budget: Repository | None = None
    authority = None
    try:
        run, chunk, ticket = (uuid.UUID(value) for value in (run_id, chunk_id, ticket_id))
        configuration = Configuration.load()
        repository = configuration.repository()
        row = repository.chunk(chunk)
        if row["run_id"] != run:
            raise Rejection("unknown_chunk")
        # Lost acknowledgement recognition precedes tickets, deadlines and live
        # enablement. A completed scientific transaction is never repeated.
        if row["state"] in TERMINAL:
            return str(row["state"])
        bounded_worker_memory()
        authority = repository.start_worker(run, chunk, ticket)
        if authority is None:
            return "duplicate_delivery"
        current = repository.run(run)
        if current["environment_id"] != configuration.environment:
            raise Rejection("unsafe_environment")
        if current["policy_versions"] != policy_versions():
            raise Rejection("unsupported_policy_versions")
        remaining = (current["work_deadline"] - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise Rejection("work_deadline")
        deadline = time.monotonic() + remaining
        inputs = repository.input(run)
        if inputs is None:
            raise Rejection("missing_input_descriptor")
        private = private_directory(configuration.private / str(run) / str(chunk) / ticket.hex)
        store = configuration.store()
        source: Source
        if inputs["kind"] == "live":
            source = RequestOwner(
                repository,
                store,
                authority,
                deadline=deadline,
                application_commit=configuration.application_commit,
                enabled=live_enabled,
                credential=upstream_credential,
                originals=private / "originals",
                require_existing=row["state"] in ("landed", "validating", "publishing"),
            )
        else:
            source = RecordedSource(
                repository,
                store,
                authority,
                inputs["descriptor"],
                deadline=deadline,
                application_commit=configuration.application_commit,
                require_existing=row["state"] in ("landed", "validating", "publishing"),
            )
        budget = configuration.repository()
        return Processor(
            repository, budget, store, source, authority, private, deadline=deadline
        ).execute()
    except Exception as error:
        # No exception text/traceback, task result, argument or environment secret
        # leaves this boundary. A failed evidence write leaves recoverable work.
        category = error.category if isinstance(error, Rejection) else "worker_execution_failed"
        if (
            repository is not None
            and authority is not None
            and category not in ("publication_fenced", "run_fenced", "work_deadline")
        ):
            try:
                repository.transition(authority, "failed", category)
            except Rejection:
                return "recovery_required"
        return (
            "recovery_required"
            if authority is None
            or category in ("publication_fenced", "run_fenced", "work_deadline")
            else "failed"
        )
    finally:
        if budget is not None:
            budget.close()
        if repository is not None:
            repository.close()
