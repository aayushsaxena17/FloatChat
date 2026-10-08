"""Opaque-ticket worker entrypoint. The PostgreSQL queue owns no ingestion retry budget."""

import os
import resource
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.landing import RequestOwner
from floatchat_core.ingestion.minio import MinioStore
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.private import private_directory
from floatchat_core.ingestion.processor import Processor
from floatchat_core.ingestion.repository import Authority, Repository
from floatchat_core.ingestion.source import RecordedSource, Source
from floatchat_core.ingestion.states import ACQUIRE_STATES, PROCESS_STATES, TERMINAL

from .queue import issue

GIB = 1024**3
KINDS = ("acquire", "process", "execute")


def bounded_integer(name: str, default: int, low: int, high: int) -> int:
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(name)
    return value


@dataclass(frozen=True, repr=False)
class Configuration:
    database_url: str = field(repr=False)
    environment: uuid.UUID
    bucket: str
    queue: str
    project: str
    endpoint: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    application_commit: str
    private: Path
    acquire_slots: int = 4
    process_workers: int = 1
    worker_memory_bytes: int = GIB

    @classmethod
    def load(cls) -> "Configuration":
        # The upstream key is deliberately absent. Only a live request can load
        # it; argument/configuration diagnostics never contain environment input.
        try:
            return cls(
                os.environ["INGESTION_DATABASE_URL"],
                uuid.UUID(os.environ["INGESTION_ENVIRONMENT_ID"]),
                os.environ["INGESTION_BUCKET"],
                os.environ["INGESTION_QUEUE_NAMESPACE"],
                os.environ["COMPOSE_PROJECT_NAME"],
                os.environ["OBJECT_STORAGE_ENDPOINT"],
                os.environ["OBJECT_STORAGE_ACCESS_KEY"],
                os.environ["OBJECT_STORAGE_SECRET_KEY"],
                os.environ["INGESTION_APPLICATION_COMMIT"],
                Path.home() / "private/floatchat-stage1",
                bounded_integer("INGESTION_ACQUIRE_SLOTS", 4, 1, 16),
                bounded_integer("INGESTION_PROCESS_WORKERS", min(4, os.cpu_count() or 1), 1, 64),
                # Contract section 9: configuration may reduce the 1 GiB worker bound, not raise it.
                bounded_integer("INGESTION_WORKER_MEMORY_BYTES", GIB, 128 * 1024**2, GIB),
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


def bounded_worker_memory(limit: int = GIB) -> None:
    """A cgroup `memory.max` of at most 1 GiB, or else RLIMIT_DATA at `limit` bytes.

    RLIMIT_AS is never used: it counts address space, which pyarrow's allocator reserves far
    beyond what it touches. The soft limit is only ever lowered, so repeated calls in one
    process (every acquire thread) are idempotent.
    """
    try:
        value = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if value != "max" and 0 < int(value) <= GIB:
            return
    except (OSError, ValueError):
        pass
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
        if soft == resource.RLIM_INFINITY or soft > limit:
            resource.setrlimit(resource.RLIMIT_DATA, (limit, hard))
    except (OSError, ValueError):
        raise Rejection("worker_memory_bound_unavailable") from None


def upstream_credential() -> str:
    credential = os.environ.get("ARGOVIS_API_KEY")
    if not credential:
        raise Rejection("ARGOVIS_API_KEY")
    return credential


def hand_over(repository: Repository, authority: Authority) -> None:
    """Queue the landed chunk for the process pool under the claim that landed it.

    Normal phase progress consumes no processing claim (contract 8.1), so the process ticket
    reuses the acquire ticket's epoch and fence. Best effort: if it is not created, the
    chunk lease lapses and the controller re-queues the chunk by phase under a new claim.
    """
    try:
        issue(repository, authority, "process")
    except Exception:
        # Fixed category only: exception text never leaves the worker boundary.
        print("process_handover_unavailable", flush=True)


def process_ticket(
    run_id: str,
    chunk_id: str,
    ticket_id: str,
    kind: str = "process",
    *,
    governor: Any | None = None,
    slot: int = 1,
) -> str:
    """Run one ticket and return the chunk state reached (or a recognition marker).

    `acquire` lands the chunk (Processor.land) and hands it to the process queue; `process`
    validates and publishes a landed chunk from existing landings only (Processor.process);
    `execute` is the serial stage1-v3 path (land then process) for offline probes. A
    `governor` and `slot` (1..N) belong to one acquire thread and only reach a live source.
    """
    repository: Repository | None = None
    budget: Repository | None = None
    authority = None
    try:
        if kind not in KINDS:
            raise Rejection("invalid_ticket_kind")
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
        if kind == "process" and row["state"] in ACQUIRE_STATES:
            # Nothing has landed; a process worker may never reach the upstream source.
            raise Rejection("ticket_phase_mismatch")
        bounded_worker_memory(configuration.worker_memory_bytes)
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
        existing = kind == "process" or (kind == "execute" and row["state"] in PROCESS_STATES)
        if inputs["kind"] == "live":
            threaded: dict[str, Any] = (
                {} if governor is None else {"governor": governor, "slot": slot}
            )
            source = RequestOwner(
                repository,
                store,
                authority,
                deadline=deadline,
                application_commit=configuration.application_commit,
                enabled=live_enabled,
                credential=upstream_credential,
                originals=private / "originals",
                require_existing=existing,
                **threaded,
            )
        else:
            source = RecordedSource(
                repository,
                store,
                authority,
                inputs["descriptor"],
                deadline=deadline,
                application_commit=configuration.application_commit,
                require_existing=existing,
            )
        budget = configuration.repository()
        processor = Processor(
            repository, budget, store, source, authority, private, deadline=deadline
        )
        if kind == "execute":
            return processor.execute()
        if kind == "process":
            return processor.process()
        state = processor.land()
        if state == "landed":
            hand_over(repository, authority)
        return state
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
