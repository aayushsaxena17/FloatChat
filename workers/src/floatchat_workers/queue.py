"""PostgreSQL work-queue client (stage1-v4): claim, issue and poll tickets.

A ticket is an opaque row of app.processing_ticket; claiming only hands it to one worker.
State authority stays with the fenced chunk claim, lease and fence checked by
app.start_worker, so a lost, duplicated or abandoned claim never adds retry budget.
"""

import os
import socket
import threading
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.states import TICKET_KINDS

IDLE_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
# Database loss pauses claiming; every other rejection (unsafe environment, privileged
# login) is a configuration fault that retrying cannot repair.
TRANSIENT = frozenset({"database_failure", "database_deadline"})


class TicketStore(Protocol):
    def claim_ticket(self, kind: str, worker: str) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


def worker_name(kind: str, index: int = 0) -> str:
    """Opaque claimant label stored in claimed_by (<= 128 bytes, no credentials)."""
    host = socket.gethostname().encode()[:64].decode(errors="ignore")
    return f"{kind}:{host}:{os.getpid()}:{index}"


def claim(repository: TicketStore, kind: str, worker: str) -> dict[str, Any] | None:
    """Claim one unstarted ticket of `kind`, or None when the queue is empty."""
    if kind not in TICKET_KINDS:
        raise Rejection("invalid_ticket_kind")
    return repository.claim_ticket(kind, worker)


def issue(repository: Any, authority: Authority, kind: str) -> uuid.UUID:
    """Create the ticket for an already persisted claim; creating the row is the dispatch.

    Idempotent per (chunk, fence, kind). Repository.ticket takes the kind as its second
    argument once the integrator applies the one-line change recorded in the package report.
    """
    if kind not in TICKET_KINDS:
        raise Rejection("invalid_ticket_kind")
    ticket: uuid.UUID = repository.ticket(authority, kind)
    return ticket


def ticket_arguments(ticket: dict[str, Any]) -> tuple[str, str, str]:
    """(run, chunk, ticket) as strings, the process_ticket argument order."""
    return str(ticket["run_id"]), str(ticket["chunk_id"]), str(ticket["id"])


def poll(
    open_repository: Callable[[], TicketStore],
    kind: str,
    worker: str,
    handle: Callable[[dict[str, Any]], None],
    stop: threading.Event,
    *,
    idle: float = IDLE_SECONDS,
    ready: Callable[[], bool] = lambda: True,
) -> None:
    """Claim and handle tickets until `stop` is set.

    An empty queue waits `idle` seconds. Database loss closes the connection and retries
    with doubling waits up to 30 s; no claim or budget is created while it is down. `ready`
    gates each claim (a full process pool claims nothing). Lease heartbeats stay with the
    work itself (Processor.pulse, RequestOwner.wait): a claim neither extends nor shortens
    the chunk lease.
    """
    repository: TicketStore | None = None
    delay = idle
    try:
        while not stop.is_set():
            if not ready():
                stop.wait(0.2)
                continue
            try:
                if repository is None:
                    repository = open_repository()
                ticket = claim(repository, kind, worker)
            except Rejection as error:
                if error.category not in TRANSIENT:
                    raise
                if repository is not None:
                    try:
                        repository.close()
                    except Exception:
                        pass
                    repository = None
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
                stop.wait(delay)
                continue
            delay = idle
            if ticket is None:
                stop.wait(idle)
                continue
            handle(ticket)
    finally:
        if repository is not None:
            repository.close()
