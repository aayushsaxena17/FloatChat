"""Job store (ADR-0079): the application login owns jobs, chunks, events and artefacts.

``PostgresJobStore`` is used by the API and the jobs worker; ``MemoryJobStore`` has the same
semantics for tests. Claims use ``FOR UPDATE SKIP LOCKED`` with a lease; a lapsed lease makes
a running job claimable again, which is how a job survives a worker that died mid-chunk.
"""

import json
import threading
import uuid
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine, Row

from ..query.errors import QueryError
from .model import TERMINAL_STATES, Artefact, Job, JobChunk, JobEvent


class ChunkSpec(Protocol):
    kind: str
    label: str
    interval_start: datetime | None
    interval_end: datetime | None
    tiles: list[list[int]]


class JobStore(Protocol):
    def create(
        self,
        *,
        client_id: str,
        kind: str,
        queue: str,
        request: dict[str, Any],
        request_sha256: str,
        plan: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[Job, bool, bool]: ...

    def get(self, job_id: str, client_id: str | None = None) -> Job | None: ...

    def list_for(self, client_id: str, limit: int) -> list[Job]: ...

    def chunks(self, job_id: str) -> list[JobChunk]: ...

    def events(self, job_id: str, after: int = 0) -> list[JobEvent]: ...

    def artefacts(self, job_id: str) -> list[Artefact]: ...

    def artefact(self, artefact_id: str) -> Artefact | None: ...

    def cancel(self, job_id: str, client_id: str, version: int | None) -> Job: ...

    def claim(self, queues: Iterable[str], worker: str, lease_seconds: int) -> Job | None: ...

    def heartbeat(self, job_id: str, worker: str, lease_seconds: int) -> bool: ...

    def cancel_requested(self, job_id: str) -> bool: ...

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> Job: ...

    def set_chunks(self, job_id: str, specs: list[Any]) -> list[JobChunk]: ...

    def update_chunk(
        self,
        chunk_id: str,
        *,
        state: str | None = None,
        evidence: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        ingestion_run_id: str | None = None,
        attempt: bool = False,
    ) -> JobChunk: ...

    def emit(self, job_id: str, kind: str, payload: dict[str, Any]) -> JobEvent: ...

    def add_artefact(
        self,
        *,
        job_id: str,
        format: str,
        role: str,
        object_key: str,
        bytes: int,
        sha256: str,
        row_count: int,
        profile_count: int,
        manifest: dict[str, Any],
        expires_at: datetime,
    ) -> Artefact: ...

    def expire_artefacts(self, now: datetime) -> list[Artefact]: ...

    def mark_deleted(self, artefact_id: str, now: datetime) -> None: ...

    def known_object_keys(self) -> set[str]: ...


def validate_job_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise QueryError("job_not_found") from None


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryJobStore:
    """In-memory store with the PostgreSQL semantics (claims, leases, versions, sequences)."""

    def __init__(self, clock: Any = _now) -> None:
        self.clock = clock
        self._jobs: dict[str, Job] = {}
        self._chunks: dict[str, list[JobChunk]] = {}
        self._events: dict[str, list[JobEvent]] = {}
        self._artefacts: dict[str, Artefact] = {}
        self._lock = threading.RLock()

    def create(
        self,
        *,
        client_id: str,
        kind: str,
        queue: str,
        request: dict[str, Any],
        request_sha256: str,
        plan: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[Job, bool, bool]:
        with self._lock:
            if idempotency_key is not None:
                for job in self._jobs.values():
                    if job.client_id == client_id and job.idempotency_key == idempotency_key:
                        return job, False, False
            for job in sorted(self._jobs.values(), key=lambda j: j.created_at):
                if (
                    job.client_id == client_id
                    and job.request_sha256 == request_sha256
                    and job.active
                ):
                    return job, False, True
            now = self.clock()
            job = Job(
                id=str(uuid.uuid4()),
                kind=kind,
                queue=queue,
                client_id=client_id,
                idempotency_key=idempotency_key,
                request=request,
                request_sha256=request_sha256,
                plan=plan,
                state="queued",
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.id] = job
            self._chunks[job.id] = []
            self._events[job.id] = []
            return job, True, False

    def get(self, job_id: str, client_id: str | None = None) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or (client_id is not None and job.client_id != client_id):
            return None
        return job

    def list_for(self, client_id: str, limit: int) -> list[Job]:
        with self._lock:
            rows = [job for job in self._jobs.values() if job.client_id == client_id]
        rows.sort(key=lambda job: (job.created_at, job.id), reverse=True)
        return rows[:limit]

    def chunks(self, job_id: str) -> list[JobChunk]:
        with self._lock:
            return sorted(self._chunks.get(job_id, []), key=lambda chunk: chunk.seq)

    def events(self, job_id: str, after: int = 0) -> list[JobEvent]:
        with self._lock:
            return [event for event in self._events.get(job_id, []) if event.seq > after]

    def artefacts(self, job_id: str) -> list[Artefact]:
        with self._lock:
            rows = [a for a in self._artefacts.values() if a.job_id == job_id]
        return sorted(rows, key=lambda a: (a.created_at, a.id))

    def artefact(self, artefact_id: str) -> Artefact | None:
        with self._lock:
            return self._artefacts.get(artefact_id)

    def cancel(self, job_id: str, client_id: str, version: int | None) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.client_id != client_id:
                raise QueryError("job_not_found")
            if job.state in TERMINAL_STATES:
                raise QueryError("job_conflict", message="The job has already finished.")
            if version is not None and version != job.version:
                raise QueryError("job_conflict", message="The job changed; reload and retry.")
            if job.cancel_requested_at is not None:
                return job
            now = self.clock()
            if job.state == "queued":
                job = replace(
                    job,
                    state="cancelled",
                    cancel_requested_at=now,
                    finished_at=now,
                    updated_at=now,
                    version=job.version + 1,
                )
                self._jobs[job_id] = job
                self._append_event(job_id, "finished", {"state": "cancelled"})
                return job
            job = replace(job, cancel_requested_at=now, updated_at=now, version=job.version + 1)
            self._jobs[job_id] = job
            return job

    def claim(self, queues: Iterable[str], worker: str, lease_seconds: int) -> Job | None:
        wanted = set(queues)
        with self._lock:
            now = self.clock()
            candidates = [
                job
                for job in self._jobs.values()
                if job.queue in wanted
                and job.active
                and (job.lease_until is None or job.lease_until <= now)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda job: (job.created_at, job.id))
            job = candidates[0]
            job = replace(
                job,
                claimed_by=worker,
                lease_until=now + timedelta(seconds=lease_seconds),
                attempts=job.attempts + 1,
                started_at=job.started_at or now,
                updated_at=now,
            )
            self._jobs[job.id] = job
            return job

    def heartbeat(self, job_id: str, worker: str, lease_seconds: int) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.claimed_by != worker or not job.active:
                return False
            now = self.clock()
            self._jobs[job_id] = replace(
                job, lease_until=now + timedelta(seconds=lease_seconds), updated_at=now
            )
            return True

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        return job is not None and job.cancel_requested_at is not None

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            now = self.clock()
            job = replace(
                job,
                state=state or job.state,
                progress=job.progress if progress is None else progress,
                result=job.result if result is None else result,
                error=job.error if error is None else error,
                finished_at=now if finished else job.finished_at,
                lease_until=None if finished else job.lease_until,
                updated_at=now,
                version=job.version + 1,
            )
            self._jobs[job_id] = job
            return job

    def set_chunks(self, job_id: str, specs: list[Any]) -> list[JobChunk]:
        with self._lock:
            existing = self._chunks.get(job_id, [])
            if existing:
                return sorted(existing, key=lambda chunk: chunk.seq)
            rows = [
                JobChunk(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    seq=index,
                    kind=spec.kind,
                    label=spec.label,
                    interval_start=spec.interval_start,
                    interval_end=spec.interval_end,
                    tiles=[list(pair) for pair in spec.tiles],
                    state=getattr(spec, "state", "pending"),
                    evidence=dict(getattr(spec, "evidence", {}) or {}),
                )
                for index, spec in enumerate(specs, start=1)
            ]
            self._chunks[job_id] = rows
            return list(rows)

    def update_chunk(
        self,
        chunk_id: str,
        *,
        state: str | None = None,
        evidence: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        ingestion_run_id: str | None = None,
        attempt: bool = False,
    ) -> JobChunk:
        with self._lock:
            for rows in self._chunks.values():
                for index, chunk in enumerate(rows):
                    if chunk.id != chunk_id:
                        continue
                    now = self.clock()
                    started = chunk.started_at or (now if state == "running" else None)
                    finished = (
                        now if state in ("complete", "reused", "failed", "cancelled") else None
                    )
                    updated = replace(
                        chunk,
                        state=state or chunk.state,
                        evidence=chunk.evidence if evidence is None else evidence,
                        error=chunk.error if error is None else error,
                        ingestion_run_id=ingestion_run_id or chunk.ingestion_run_id,
                        attempts=chunk.attempts + (1 if attempt else 0),
                        started_at=started,
                        finished_at=finished or chunk.finished_at,
                    )
                    rows[index] = updated
                    return updated
        raise KeyError(chunk_id)

    def emit(self, job_id: str, kind: str, payload: dict[str, Any]) -> JobEvent:
        with self._lock:
            return self._append_event(job_id, kind, payload)

    def _append_event(self, job_id: str, kind: str, payload: dict[str, Any]) -> JobEvent:
        rows = self._events.setdefault(job_id, [])
        event = JobEvent(job_id, len(rows) + 1, kind, payload, self.clock())
        rows.append(event)
        return event

    def add_artefact(
        self,
        *,
        job_id: str,
        format: str,
        role: str,
        object_key: str,
        bytes: int,
        sha256: str,
        row_count: int,
        profile_count: int,
        manifest: dict[str, Any],
        expires_at: datetime,
    ) -> Artefact:
        with self._lock:
            artefact = Artefact(
                id=str(uuid.uuid4()),
                job_id=job_id,
                format=format,
                role=role,
                object_key=object_key,
                bytes=bytes,
                sha256=sha256,
                row_count=row_count,
                profile_count=profile_count,
                manifest=manifest,
                state="available",
                created_at=self.clock(),
                expires_at=expires_at,
            )
            self._artefacts[artefact.id] = artefact
            return artefact

    def expire_artefacts(self, now: datetime) -> list[Artefact]:
        with self._lock:
            expired = []
            for key, artefact in self._artefacts.items():
                if artefact.state == "available" and artefact.expires_at <= now:
                    artefact = replace(artefact, state="expired")
                    self._artefacts[key] = artefact
                    expired.append(artefact)
            return expired

    def mark_deleted(self, artefact_id: str, now: datetime) -> None:
        with self._lock:
            artefact = self._artefacts[artefact_id]
            self._artefacts[artefact_id] = replace(artefact, state="deleted", deleted_at=now)

    def known_object_keys(self) -> set[str]:
        with self._lock:
            return {artefact.object_key for artefact in self._artefacts.values()}


JOB_COLUMNS = (
    "id, kind, queue, client_id, idempotency_key, request, request_sha256, plan, state,"
    " progress, result, error, version, attempts, claimed_by, lease_until,"
    " cancel_requested_at, created_at, updated_at, started_at, finished_at"
)
CHUNK_COLUMNS = (
    "id, job_id, seq, kind, label, interval_start, interval_end, tiles, state, attempts,"
    " ingestion_run_id, evidence, error, started_at, finished_at"
)
ARTEFACT_COLUMNS = (
    "id, job_id, format, role, object_key, bytes, sha256, row_count, profile_count, manifest,"
    " state, created_at, expires_at, deleted_at"
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _job(row: Row[Any]) -> Job:
    return Job(
        id=str(row.id),
        kind=row.kind,
        queue=row.queue,
        client_id=row.client_id,
        idempotency_key=row.idempotency_key,
        request=dict(row.request),
        request_sha256=row.request_sha256,
        plan=dict(row.plan),
        state=row.state,
        progress=dict(row.progress or {}),
        result=dict(row.result or {}),
        error=None if row.error is None else dict(row.error),
        version=int(row.version),
        attempts=int(row.attempts),
        claimed_by=row.claimed_by,
        lease_until=row.lease_until,
        cancel_requested_at=row.cancel_requested_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _chunk(row: Row[Any]) -> JobChunk:
    return JobChunk(
        id=str(row.id),
        job_id=str(row.job_id),
        seq=int(row.seq),
        kind=row.kind,
        label=row.label,
        interval_start=row.interval_start,
        interval_end=row.interval_end,
        tiles=[list(pair) for pair in (row.tiles or [])],
        state=row.state,
        attempts=int(row.attempts),
        ingestion_run_id=None if row.ingestion_run_id is None else str(row.ingestion_run_id),
        evidence=dict(row.evidence or {}),
        error=None if row.error is None else dict(row.error),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _artefact(row: Row[Any]) -> Artefact:
    return Artefact(
        id=str(row.id),
        job_id=str(row.job_id),
        format=row.format,
        role=row.role,
        object_key=row.object_key,
        bytes=int(row.bytes),
        sha256=row.sha256,
        row_count=int(row.row_count),
        profile_count=int(row.profile_count),
        manifest=dict(row.manifest or {}),
        state=row.state,
        created_at=row.created_at,
        expires_at=row.expires_at,
        deleted_at=row.deleted_at,
    )


class PostgresJobStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create(
        self,
        *,
        client_id: str,
        kind: str,
        queue: str,
        request: dict[str, Any],
        request_sha256: str,
        plan: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[Job, bool, bool]:
        with self.engine.begin() as connection:
            # One transaction, the client's rows locked: a concurrent identical request from
            # the same client waits and then finds the job this one created.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:client))"), {"client": client_id}
            )
            if idempotency_key is not None:
                row = connection.execute(
                    text(
                        f"SELECT {JOB_COLUMNS} FROM app.analysis_job"
                        " WHERE client_id = :client AND idempotency_key = :key"
                    ),
                    {"client": client_id, "key": idempotency_key},
                ).one_or_none()
                if row is not None:
                    return _job(row), False, False
            row = connection.execute(
                text(
                    f"SELECT {JOB_COLUMNS} FROM app.analysis_job"
                    " WHERE client_id = :client AND request_sha256 = :digest"
                    " AND state IN ('queued','fetching','exporting','analysing')"
                    " ORDER BY created_at LIMIT 1"
                ),
                {"client": client_id, "digest": request_sha256},
            ).one_or_none()
            if row is not None:
                return _job(row), False, True
            row = connection.execute(
                text(
                    "INSERT INTO app.analysis_job(kind, queue, client_id, idempotency_key,"
                    " request, request_sha256, plan) VALUES (:kind, :queue, :client, :key,"
                    " CAST(:request AS jsonb), :digest, CAST(:plan AS jsonb))"
                    f" RETURNING {JOB_COLUMNS}"
                ),
                {
                    "kind": kind,
                    "queue": queue,
                    "client": client_id,
                    "key": idempotency_key,
                    "request": _json(request),
                    "digest": request_sha256,
                    "plan": _json(plan),
                },
            ).one()
            job = _job(row)
            self._emit(connection, job.id, "created", {"state": "queued"})
        return job, True, False

    def get(self, job_id: str, client_id: str | None = None) -> Job | None:
        statement = f"SELECT {JOB_COLUMNS} FROM app.analysis_job WHERE id = CAST(:id AS uuid)"
        parameters: dict[str, Any] = {"id": job_id}
        if client_id is not None:
            statement += " AND client_id = :client"
            parameters["client"] = client_id
        with self.engine.connect() as connection:
            row = connection.execute(text(statement), parameters).one_or_none()
        return None if row is None else _job(row)

    def list_for(self, client_id: str, limit: int) -> list[Job]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {JOB_COLUMNS} FROM app.analysis_job WHERE client_id = :client"
                    " ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                {"client": client_id, "limit": limit},
            ).all()
        return [_job(row) for row in rows]

    def chunks(self, job_id: str) -> list[JobChunk]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {CHUNK_COLUMNS} FROM app.analysis_job_chunk"
                    " WHERE job_id = CAST(:id AS uuid) ORDER BY seq"
                ),
                {"id": job_id},
            ).all()
        return [_chunk(row) for row in rows]

    def events(self, job_id: str, after: int = 0) -> list[JobEvent]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT job_id, seq, kind, payload, created_at FROM app.analysis_job_event"
                    " WHERE job_id = CAST(:id AS uuid) AND seq > :after ORDER BY seq"
                ),
                {"id": job_id, "after": after},
            ).all()
        return [
            JobEvent(str(row.job_id), int(row.seq), row.kind, dict(row.payload), row.created_at)
            for row in rows
        ]

    def artefacts(self, job_id: str) -> list[Artefact]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {ARTEFACT_COLUMNS} FROM app.analysis_artefact"
                    " WHERE job_id = CAST(:id AS uuid) ORDER BY created_at, id"
                ),
                {"id": job_id},
            ).all()
        return [_artefact(row) for row in rows]

    def artefact(self, artefact_id: str) -> Artefact | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {ARTEFACT_COLUMNS} FROM app.analysis_artefact"
                    " WHERE id = CAST(:id AS uuid)"
                ),
                {"id": artefact_id},
            ).one_or_none()
        return None if row is None else _artefact(row)

    def cancel(self, job_id: str, client_id: str, version: int | None) -> Job:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    f"SELECT {JOB_COLUMNS} FROM app.analysis_job WHERE id = CAST(:id AS uuid)"
                    " AND client_id = :client FOR UPDATE"
                ),
                {"id": job_id, "client": client_id},
            ).one_or_none()
            if row is None:
                raise QueryError("job_not_found")
            job = _job(row)
            if job.state in TERMINAL_STATES:
                raise QueryError("job_conflict", message="The job has already finished.")
            if version is not None and version != job.version:
                raise QueryError("job_conflict", message="The job changed; reload and retry.")
            if job.cancel_requested_at is not None:
                return job
            if job.state == "queued":
                row = connection.execute(
                    text(
                        "UPDATE app.analysis_job SET state = 'cancelled',"
                        " cancel_requested_at = clock_timestamp(), finished_at = clock_timestamp(),"
                        " updated_at = clock_timestamp(), version = version + 1"
                        f" WHERE id = CAST(:id AS uuid) RETURNING {JOB_COLUMNS}"
                    ),
                    {"id": job_id},
                ).one()
                self._emit(connection, job_id, "finished", {"state": "cancelled"})
                return _job(row)
            row = connection.execute(
                text(
                    "UPDATE app.analysis_job SET cancel_requested_at = clock_timestamp(),"
                    " updated_at = clock_timestamp(), version = version + 1"
                    f" WHERE id = CAST(:id AS uuid) RETURNING {JOB_COLUMNS}"
                ),
                {"id": job_id},
            ).one()
            return _job(row)

    def claim(self, queues: Iterable[str], worker: str, lease_seconds: int) -> Job | None:
        names = sorted(set(queues))
        if not names:
            return None
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT id FROM app.analysis_job WHERE queue = ANY(:queues)"
                    " AND state IN ('queued','fetching','exporting','analysing')"
                    " AND (lease_until IS NULL OR lease_until <= clock_timestamp())"
                    " ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1"
                ),
                {"queues": names},
            ).one_or_none()
            if row is None:
                return None
            claimed = connection.execute(
                text(
                    "UPDATE app.analysis_job SET claimed_by = :worker,"
                    " lease_until = clock_timestamp() + make_interval(secs => :lease),"
                    " attempts = attempts + 1,"
                    " started_at = coalesce(started_at, clock_timestamp()),"
                    " updated_at = clock_timestamp()"
                    f" WHERE id = :id RETURNING {JOB_COLUMNS}"
                ),
                {"worker": worker, "lease": lease_seconds, "id": row.id},
            ).one()
        return _job(claimed)

    def heartbeat(self, job_id: str, worker: str, lease_seconds: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE app.analysis_job SET"
                    " lease_until = clock_timestamp() + make_interval(secs => :lease),"
                    " updated_at = clock_timestamp()"
                    " WHERE id = CAST(:id AS uuid) AND claimed_by = :worker"
                    " AND state IN ('queued','fetching','exporting','analysing')"
                ),
                {"lease": lease_seconds, "id": job_id, "worker": worker},
            )
        return bool(result.rowcount)

    def cancel_requested(self, job_id: str) -> bool:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT cancel_requested_at FROM app.analysis_job WHERE id = CAST(:id AS uuid)"
                ),
                {"id": job_id},
            ).one_or_none()
        return row is not None and row.cancel_requested_at is not None

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        progress: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> Job:
        assignments = ["updated_at = clock_timestamp()", "version = version + 1"]
        parameters: dict[str, Any] = {"id": job_id}
        if state is not None:
            assignments.append("state = :state")
            parameters["state"] = state
        if progress is not None:
            assignments.append("progress = CAST(:progress AS jsonb)")
            parameters["progress"] = _json(progress)
        if result is not None:
            assignments.append("result = CAST(:result AS jsonb)")
            parameters["result"] = _json(result)
        if error is not None:
            assignments.append("error = CAST(:error AS jsonb)")
            parameters["error"] = _json(error)
        if finished:
            assignments.append("finished_at = clock_timestamp()")
            assignments.append("lease_until = NULL")
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    f"UPDATE app.analysis_job SET {', '.join(assignments)}"
                    f" WHERE id = CAST(:id AS uuid) RETURNING {JOB_COLUMNS}"
                ),
                parameters,
            ).one()
        return _job(row)

    def set_chunks(self, job_id: str, specs: list[Any]) -> list[JobChunk]:
        with self.engine.begin() as connection:
            connection.execute(
                text("SELECT id FROM app.analysis_job WHERE id = CAST(:id AS uuid) FOR UPDATE"),
                {"id": job_id},
            )
            existing = connection.execute(
                text(
                    f"SELECT {CHUNK_COLUMNS} FROM app.analysis_job_chunk"
                    " WHERE job_id = CAST(:id AS uuid) ORDER BY seq"
                ),
                {"id": job_id},
            ).all()
            if existing:
                return [_chunk(row) for row in existing]
            rows = []
            for index, spec in enumerate(specs, start=1):
                row = connection.execute(
                    text(
                        "INSERT INTO app.analysis_job_chunk(job_id, seq, kind, label,"
                        " interval_start, interval_end, tiles, state, evidence)"
                        " VALUES (CAST(:job AS uuid), :seq, :kind, :label, :start, :end,"
                        " CAST(:tiles AS jsonb), :state, CAST(:evidence AS jsonb))"
                        f" RETURNING {CHUNK_COLUMNS}"
                    ),
                    {
                        "job": job_id,
                        "seq": index,
                        "kind": spec.kind,
                        "label": spec.label,
                        "start": spec.interval_start,
                        "end": spec.interval_end,
                        "tiles": _json([list(pair) for pair in spec.tiles]),
                        "state": getattr(spec, "state", "pending"),
                        "evidence": _json(dict(getattr(spec, "evidence", {}) or {})),
                    },
                ).one()
                rows.append(_chunk(row))
        return rows

    def update_chunk(
        self,
        chunk_id: str,
        *,
        state: str | None = None,
        evidence: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        ingestion_run_id: str | None = None,
        attempt: bool = False,
    ) -> JobChunk:
        assignments = []
        parameters: dict[str, Any] = {"id": chunk_id}
        if state is not None:
            assignments.append("state = :state")
            parameters["state"] = state
            if state == "running":
                assignments.append("started_at = coalesce(started_at, clock_timestamp())")
            if state in ("complete", "reused", "failed", "cancelled"):
                assignments.append("finished_at = clock_timestamp()")
        if evidence is not None:
            assignments.append("evidence = CAST(:evidence AS jsonb)")
            parameters["evidence"] = _json(evidence)
        if error is not None:
            assignments.append("error = CAST(:error AS jsonb)")
            parameters["error"] = _json(error)
        if ingestion_run_id is not None:
            assignments.append("ingestion_run_id = CAST(:run AS uuid)")
            parameters["run"] = ingestion_run_id
        if attempt:
            assignments.append("attempts = attempts + 1")
        if not assignments:
            assignments.append("attempts = attempts")
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    f"UPDATE app.analysis_job_chunk SET {', '.join(assignments)}"
                    f" WHERE id = CAST(:id AS uuid) RETURNING {CHUNK_COLUMNS}"
                ),
                parameters,
            ).one()
        return _chunk(row)

    def emit(self, job_id: str, kind: str, payload: dict[str, Any]) -> JobEvent:
        with self.engine.begin() as connection:
            return self._emit(connection, job_id, kind, payload)

    @staticmethod
    def _emit(connection: Any, job_id: str, kind: str, payload: dict[str, Any]) -> JobEvent:
        connection.execute(
            text("SELECT id FROM app.analysis_job WHERE id = CAST(:id AS uuid) FOR UPDATE"),
            {"id": job_id},
        )
        row = connection.execute(
            text(
                "INSERT INTO app.analysis_job_event(job_id, seq, kind, payload)"
                " SELECT CAST(:id AS uuid), coalesce(max(seq), 0) + 1, :kind,"
                " CAST(:payload AS jsonb) FROM app.analysis_job_event"
                " WHERE job_id = CAST(:id AS uuid)"
                " RETURNING job_id, seq, kind, payload, created_at"
            ),
            {"id": job_id, "kind": kind, "payload": _json(payload)},
        ).one()
        return JobEvent(str(row.job_id), int(row.seq), row.kind, dict(row.payload), row.created_at)

    def add_artefact(
        self,
        *,
        job_id: str,
        format: str,
        role: str,
        object_key: str,
        bytes: int,
        sha256: str,
        row_count: int,
        profile_count: int,
        manifest: dict[str, Any],
        expires_at: datetime,
    ) -> Artefact:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "INSERT INTO app.analysis_artefact(job_id, format, role, object_key, bytes,"
                    " sha256, row_count, profile_count, manifest, expires_at)"
                    " VALUES (CAST(:job AS uuid), :format, :role, :key, :bytes, :sha256, :rows,"
                    " :profiles, CAST(:manifest AS jsonb), :expires)"
                    f" RETURNING {ARTEFACT_COLUMNS}"
                ),
                {
                    "job": job_id,
                    "format": format,
                    "role": role,
                    "key": object_key,
                    "bytes": bytes,
                    "sha256": sha256,
                    "rows": row_count,
                    "profiles": profile_count,
                    "manifest": _json(manifest),
                    "expires": expires_at,
                },
            ).one()
        return _artefact(row)

    def expire_artefacts(self, now: datetime) -> list[Artefact]:
        with self.engine.begin() as connection:
            rows = connection.execute(
                text(
                    "UPDATE app.analysis_artefact SET state = 'expired'"
                    " WHERE state = 'available' AND expires_at <= :now"
                    f" RETURNING {ARTEFACT_COLUMNS}"
                ),
                {"now": now},
            ).all()
        return [_artefact(row) for row in rows]

    def mark_deleted(self, artefact_id: str, now: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE app.analysis_artefact SET state = 'deleted', deleted_at = :now"
                    " WHERE id = CAST(:id AS uuid)"
                ),
                {"id": artefact_id, "now": now},
            )

    def known_object_keys(self) -> set[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT object_key FROM app.analysis_artefact")).all()
        return {row.object_key for row in rows}
