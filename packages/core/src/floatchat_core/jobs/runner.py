"""The job runner (ADR-0079): claim, plan, fetch through historical runs, export, finish.

Every step is persisted before the next starts, so a worker that dies mid-chunk is replaced
by the next claim after the lease lapses: complete and reused chunks are never repeated, a
running fetch chunk re-attaches to its ingestion run, and an export that never committed its
artefact rows is produced again (the orphaned objects are reconciled later). The runner talks
to the catalogue, the ingestion runs and the exporter through small protocols so the §22
failure tests run over doubles.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from ..ingestion.planning import Interval, Tile, shift_months
from ..query.catalogue import Coverage, EnvironmentInfo, SlotCoverage
from ..query.errors import QueryError
from ..query.geography import ResolvedGeography, resolve_geography
from ..query.plan import QueryPlan
from .model import Job, JobChunk, JobLimits
from .planner import plan_chunks
from .store import JobStore


class Catalogue(Protocol):
    def environment(self) -> EnvironmentInfo: ...

    def tiles_for(self, geography: ResolvedGeography) -> tuple[Tile, ...]: ...

    def coverage(
        self, environment_id: uuid.UUID, interval: Interval, tiles: tuple[Tile, ...]
    ) -> Coverage: ...


@dataclass(frozen=True)
class RunStatus:
    closed: bool
    state: str
    evidence: dict[str, Any]


class IngestionRuns(Protocol):
    """Historical ingestion runs (ADR-0078) as the job runner sees them."""

    def admit(
        self, request_id: uuid.UUID, interval: Interval, tiles: list[list[int]], job_id: str
    ) -> tuple[str, str | None]:
        """``(kind, run_id)``: kind is created, existing, recover or overlap_skip."""
        ...

    def status(self, run_id: str) -> RunStatus: ...

    def cancel(self, run_id: str) -> None: ...

    def quarantined(self, interval: Interval, tiles: list[list[int]]) -> set[tuple[str, int, int]]:
        """``(month, west, south)`` of slots a closed run quarantined (Stage 1 source policy).

        A quarantined month-tile leaves no coverage receipt, so the catalogue reports it
        missing forever; fetching it again only quarantines it again.
        """
        ...


@dataclass(frozen=True)
class ArtefactSpec:
    format: str
    role: str
    object_key: str
    bytes: int
    sha256: str
    row_count: int
    profile_count: int
    manifest: dict[str, Any]


class Exporter(Protocol):
    def export(
        self,
        job: Job,
        plan: QueryPlan,
        geography: ResolvedGeography,
        coverage: Coverage,
        environment: EnvironmentInfo,
    ) -> list[ArtefactSpec]: ...


log = logging.getLogger("floatchat.jobs")


def _narrow(slots: list[SlotCoverage]) -> tuple[Interval, list[list[int]]]:
    """The smallest month interval and tile list that hold ``slots``."""
    months = sorted({slot.month for slot in slots})
    first = datetime.strptime(months[0], "%Y-%m").replace(tzinfo=UTC)
    last = datetime.strptime(months[-1], "%Y-%m").replace(tzinfo=UTC)
    cells = sorted({(slot.tile.west, slot.tile.south) for slot in slots})
    return Interval(first, shift_months(last, 1)), [[west, south] for west, south in cells]


class LeaseLost(RuntimeError):
    """Another worker owns the job now; stop touching it."""


class Cancelled(RuntimeError):
    pass


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        catalogue: Catalogue,
        ingestion: IngestionRuns,
        exporter: Exporter,
        *,
        limits: JobLimits | None = None,
        worker: str = "jobs",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.catalogue = catalogue
        self.ingestion = ingestion
        self.exporter = exporter
        self.limits = limits or JobLimits()
        self.worker = worker
        self.sleep = sleep
        self.clock = clock
        self._last_heartbeat = 0.0
        # True after this process saw one of its runs close: the next admission yields first.
        self._yield_before_admit = False

    # -- loop ------------------------------------------------------------------------------

    def run_once(self, queues: tuple[str, ...]) -> Job | None:
        job = self.store.claim(queues, self.worker, self.limits.lease_seconds)
        if job is None:
            return None
        try:
            self.process(job)
        except LeaseLost:
            pass
        return job

    # -- one job ---------------------------------------------------------------------------

    def process(self, job: Job) -> Job:
        self._last_heartbeat = time.monotonic()
        try:
            plan = QueryPlan.model_validate(
                {key: value for key, value in job.plan.items() if key != "plan_schema"}
            )
            geography = resolve_geography(plan.geography)
            interval = Interval(plan.time_range.start, plan.time_range.end)
            environment = self.catalogue.environment()
            tiles = self.catalogue.tiles_for(geography)
            chunks = self.store.chunks(job.id)
            if not chunks:
                coverage = self.catalogue.coverage(environment.id, interval, tiles)
                fetch_plan = plan_chunks(interval, tiles, coverage, now=self.clock())
                if (
                    sum(1 for c in fetch_plan.chunks if c.kind == "fetch")
                    > self.limits.max_fetch_chunks
                ):
                    raise QueryError("cost_over_budget", message="Too many missing months.")
                chunks = self.store.set_chunks(job.id, list(fetch_plan.chunks))
                self.store.update(job.id, progress=self._progress(chunks, fetch_plan.describe()))
                self.store.emit(job.id, "planned", fetch_plan.describe())
            self._check_cancel(job)
            fetch_chunks = [chunk for chunk in chunks if chunk.kind == "fetch"]
            if any(chunk.state in ("pending", "running") for chunk in fetch_chunks):
                self._set_state(job, "fetching")
            for chunk in fetch_chunks:
                if chunk.state in ("complete", "reused", "failed", "cancelled"):
                    continue
                self._check_cancel(job)
                self._fetch(job, chunk, environment)
                chunks = self.store.chunks(job.id)
                self.store.update(job.id, progress=self._progress(chunks))
            self._check_cancel(job)
            export_chunk = next(chunk for chunk in chunks if chunk.kind == "export")
            self._set_state(job, "exporting")
            self.store.update_chunk(export_chunk.id, state="running", attempt=True)
            self.store.emit(
                job.id, "chunk", {"seq": export_chunk.seq, "state": "running", "label": "export"}
            )
            coverage = self.catalogue.coverage(environment.id, interval, tiles)
            try:
                with self._keepalive(job):
                    artefacts = self.exporter.export(job, plan, geography, coverage, environment)
            except LeaseLost:
                raise
            except Exception as error:  # the export failed; the job says so and keeps its chunks
                # The stored message names the failure class only; the traceback goes to the
                # worker's log (never to the API) so no path or credential reaches a client.
                log.exception("export failed for job %s", job.id)
                message = (
                    error.text
                    if isinstance(error, QueryError)
                    else f"The export step failed ({type(error).__name__})."
                )
                self.store.update_chunk(
                    export_chunk.id,
                    state="failed",
                    error={"code": "export_failed", "message": message},
                )
                self.store.emit(job.id, "chunk", {"seq": export_chunk.seq, "state": "failed"})
                return self._finish(
                    job, "failed", error={"code": "export_failed", "message": message}
                )
            stored = []
            expires = self.clock() + timedelta(hours=self.limits.artefact_ttl_hours)
            for spec in artefacts:
                artefact = self.store.add_artefact(
                    job_id=job.id,
                    format=spec.format,
                    role=spec.role,
                    object_key=spec.object_key,
                    bytes=spec.bytes,
                    sha256=spec.sha256,
                    row_count=spec.row_count,
                    profile_count=spec.profile_count,
                    manifest=spec.manifest,
                    expires_at=expires,
                )
                stored.append(artefact)
                self.store.emit(
                    job.id,
                    "artefact",
                    {
                        "id": artefact.id,
                        "format": artefact.format,
                        "role": artefact.role,
                        "bytes": artefact.bytes,
                    },
                )
            self.store.update_chunk(
                export_chunk.id,
                state="complete",
                evidence={
                    "artefacts": [artefact.id for artefact in stored],
                    "slots_missing": len(coverage.missing),
                    "rows": max([a.row_count for a in stored], default=0),
                    "profiles": max([a.profile_count for a in stored], default=0),
                },
            )
            self.store.emit(job.id, "chunk", {"seq": export_chunk.seq, "state": "complete"})
            chunks = self.store.chunks(job.id)
            failed = [
                chunk for chunk in chunks if chunk.kind == "fetch" and chunk.state == "failed"
            ]
            final = "partial" if failed or coverage.missing else "completed"
            return self._finish(
                job,
                final,
                result={
                    "artefacts": [artefact.id for artefact in stored],
                    "missing_slots": [slot.describe() for slot in coverage.missing][:200],
                    "quarantined_slots": [
                        slot
                        for chunk in chunks
                        if chunk.kind == "fetch"
                        for slot in chunk.evidence.get("quarantined_slots", [])
                    ][:200],
                    "failed_chunks": [chunk.label for chunk in failed],
                },
                progress=self._progress(chunks),
            )
        except Cancelled:
            return self._cancel(job)
        except LeaseLost:
            raise
        except QueryError as error:
            return self._finish(job, "failed", error={"code": error.code, "message": error.text})

    # -- fetch chunk -----------------------------------------------------------------------

    def _fetch(self, job: Job, chunk: JobChunk, environment: EnvironmentInfo) -> None:
        """Fetch a chunk's missing months through historical runs, with bounded retries.

        A run that ends short (deadline, quarantine, upstream failure) leaves the slots it did
        commit in the catalogue; the chunk is re-planned against current coverage and a fresh
        run is admitted for the still-missing month × tile slots, at most ``fetch_attempts``
        runs in all. Every run is recorded in the chunk's evidence.
        """
        assert chunk.interval_start is not None and chunk.interval_end is not None
        interval = Interval(chunk.interval_start, chunk.interval_end)
        tiles = [list(pair) for pair in chunk.tiles]
        evidence = dict(chunk.evidence)
        runs: list[dict[str, Any]] = list(evidence.get("runs", []))
        run_id = chunk.ingestion_run_id if chunk.state == "running" else None
        if chunk.state != "running":
            self.store.update_chunk(chunk.id, state="running", attempt=True)
            self.store.emit(
                job.id, "chunk", {"seq": chunk.seq, "state": "running", "label": chunk.label}
            )

        def complete(run_state: str) -> None:
            self.store.update_chunk(chunk.id, state="complete", evidence=evidence)
            self.store.emit(
                job.id, "chunk", {"seq": chunk.seq, "state": "complete", "run_state": run_state}
            )

        while True:
            if run_id is None:
                # What is still missing is read from the catalogue as it is now (a resumed
                # chunk, a retry); slots a previous run quarantined are never fetched again.
                fetchable, quarantined = self._remaining(environment, interval, tiles)
                if quarantined:
                    evidence["quarantined_slots"] = [slot.describe() for slot in quarantined][:200]
                if not fetchable:
                    evidence["run_state"] = "quarantined" if quarantined else "reused"
                    evidence["missing_slots_after"] = len(quarantined)
                    complete(str(evidence["run_state"]))
                    return
                interval, tiles = _narrow(fetchable)
                run_id = self._admit(job, chunk, interval, tiles)
                self.store.update_chunk(chunk.id, ingestion_run_id=run_id)
            status = self._await_run(job, run_id)
            runs.append({"run_id": run_id, "state": status.state, **status.evidence})
            evidence["runs"] = runs
            evidence.update(status.evidence)
            evidence["run_state"] = status.state
            # The chunk is complete when the catalogue covers it, never because a run said
            # so: what is still missing is read from the catalogue as it is now.
            fetchable, quarantined = self._remaining(environment, interval, tiles)
            evidence["missing_slots_after"] = len(fetchable) + len(quarantined)
            if quarantined:
                evidence["quarantined_slots"] = [slot.describe() for slot in quarantined][:200]
            if not fetchable:
                complete(status.state)
                return
            if len(runs) >= self.limits.fetch_attempts:
                self.store.update_chunk(
                    chunk.id,
                    state="failed",
                    evidence=evidence,
                    error={
                        "code": "fetch_" + status.state,
                        "message": (
                            f"The ingestion run ended {status.state}"
                            + (
                                f" ({status.evidence.get('termination_reason')})"
                                if status.evidence.get("termination_reason")
                                else ""
                            )
                            + f"; {len(fetchable)} month-tile slots are still missing after "
                            f"{len(runs)} runs."
                        ),
                    },
                )
                self.store.emit(
                    job.id,
                    "chunk",
                    {"seq": chunk.seq, "state": "failed", "run_state": status.state},
                )
                return
            self.store.emit(
                job.id,
                "chunk",
                {
                    "seq": chunk.seq,
                    "state": "retrying",
                    "run_state": status.state,
                    "missing_slots": len(fetchable),
                    "attempt": len(runs) + 1,
                },
            )
            run_id = None

    def _remaining(
        self, environment: EnvironmentInfo, interval: Interval, tiles: list[list[int]]
    ) -> tuple[list[SlotCoverage], list[SlotCoverage]]:
        """The missing slots of ``interval`` × ``tiles`` split into fetchable and quarantined."""
        coverage = self.catalogue.coverage(
            environment.id, interval, tuple(Tile(w, s) for w, s in tiles)
        )
        missing = list(coverage.missing)
        if not missing:
            return [], []
        quarantined = self.ingestion.quarantined(interval, tiles)
        skipped = [
            slot for slot in missing if (slot.month, slot.tile.west, slot.tile.south) in quarantined
        ]
        fetchable = [slot for slot in missing if slot not in skipped]
        return fetchable, skipped

    def _admit(self, job: Job, chunk: JobChunk, interval: Interval, tiles: list[list[int]]) -> str:
        waited = 0
        if self._yield_before_admit and self.limits.yield_seconds > 0:
            # Fairness: a job that just held the scope lets a waiting job admit first.
            self._yield_before_admit = False
            self._pause(job, self.limits.yield_seconds)
        while True:
            self._check_cancel(job)
            kind, run_id = self.ingestion.admit(uuid.uuid4(), interval, tiles, job.id)
            if kind == "overlap_skip" or run_id is None:
                # Another run owns the scope (one open run per scope, ADR-0078): wait.
                waited += 1
                if waited == 1:
                    self.store.emit(job.id, "chunk", {"seq": chunk.seq, "state": "waiting"})
                self._pause(job, self.limits.overlap_wait_seconds)
                continue
            return run_id

    def _await_run(self, job: Job, run_id: str) -> RunStatus:
        status = self.ingestion.status(run_id)
        while not status.closed:
            try:
                self._check_cancel(job)
            except Cancelled:
                self.ingestion.cancel(run_id)
                raise
            self._pause(job, self.limits.run_poll_seconds)
            status = self.ingestion.status(run_id)
        self._yield_before_admit = True
        return status

    # -- bookkeeping -----------------------------------------------------------------------

    @contextmanager
    def _keepalive(self, job: Job) -> Iterator[None]:
        """Heartbeat from a thread while a long synchronous step runs.

        The export's DuckDB sort and the forecast fits do not return to the runner for
        minutes; without this the lease (120 s) lapsed, another replica claimed the job and
        both ran the step at once (seen on the ten-year Arabian Sea export). A lost lease is
        raised after the step returns; the step's result is discarded by the caller.
        """
        stop = threading.Event()
        lost = threading.Event()

        def beat() -> None:
            while not stop.wait(self.limits.heartbeat_seconds):
                try:
                    if not self.store.heartbeat(job.id, self.worker, self.limits.lease_seconds):
                        lost.set()
                        return
                except Exception:  # transient store failure: the next beat tries again
                    log.exception("heartbeat failed for job %s", job.id)

        thread = threading.Thread(target=beat, name=f"keepalive-{job.id[:8]}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=max(5.0, self.limits.heartbeat_seconds * 2))
            self._last_heartbeat = time.monotonic()
        if lost.is_set():
            raise LeaseLost(job.id)

    def _pause(self, job: Job, seconds: float) -> None:
        self.sleep(seconds)
        self._heartbeat(job, force=True)

    def _heartbeat(self, job: Job, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_heartbeat >= self.limits.heartbeat_seconds:
            if not self.store.heartbeat(job.id, self.worker, self.limits.lease_seconds):
                raise LeaseLost(job.id)
            self._last_heartbeat = now

    def _check_cancel(self, job: Job) -> None:
        self._heartbeat(job)
        if self.store.cancel_requested(job.id):
            raise Cancelled(job.id)

    def _set_state(self, job: Job, state: str) -> None:
        current = self.store.get(job.id)
        if current is not None and current.state != state:
            self.store.update(job.id, state=state)
            self.store.emit(job.id, "state", {"state": state})

    def _progress(
        self, chunks: list[JobChunk], extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        fetch = [chunk for chunk in chunks if chunk.kind == "fetch"]
        progress = {
            "chunks_total": len(chunks),
            "fetch_total": len(fetch),
            "fetch_complete": sum(1 for c in fetch if c.state == "complete"),
            "fetch_failed": sum(1 for c in fetch if c.state == "failed"),
            "fetch_running": sum(1 for c in fetch if c.state == "running"),
            "export_state": next((c.state for c in chunks if c.kind == "export"), "pending"),
        }
        if extra:
            progress.update(extra)
        else:
            current = self.store.get(chunks[0].job_id) if chunks else None
            if current is not None:
                for key in (
                    "slots_total",
                    "slots_reused",
                    "slots_missing",
                    "reuse_ratio",
                    "missing_months",
                ):
                    if key in current.progress:
                        progress[key] = current.progress[key]
        return progress

    def _finish(
        self,
        job: Job,
        state: str,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
    ) -> Job:
        finished = self.store.update(
            job.id, state=state, result=result, error=error, progress=progress, finished=True
        )
        self.store.emit(job.id, "finished", {"state": state, "error": error})
        return finished

    def _cancel(self, job: Job) -> Job:
        for chunk in self.store.chunks(job.id):
            if chunk.state in ("pending", "running"):
                self.store.update_chunk(chunk.id, state="cancelled")
        return self._finish(job, "cancelled", progress=self._progress(self.store.chunks(job.id)))
