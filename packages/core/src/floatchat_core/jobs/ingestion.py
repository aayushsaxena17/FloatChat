"""Historical ingestion runs for the job runner (ADR-0078) over the Stage 1 Repository."""

import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from ..ingestion.numeric import Rejection
from ..ingestion.planning import Interval
from ..ingestion.repository import Repository
from ..ingestion.states import TERMINAL
from .model import JobLimits
from .runner import RunStatus

T = TypeVar("T")


TRANSIENT = frozenset({"database_failure", "database_deadline"})


class RepositoryRuns:
    """Admits, observes and cancels historical runs through the ingestion login.

    The Stage 1 ``Repository`` holds one connection and never reconnects; a database
    restart (Stage 5 saw one under memory pressure) would otherwise leave every later call
    failing. Each call is retried once over a fresh connection when ``reconnect`` is given.
    """

    def __init__(
        self,
        repository: Repository,
        environment: uuid.UUID,
        limits: JobLimits | None = None,
        reconnect: Callable[[], Repository] | None = None,
    ):
        self.repository = repository
        self.environment = environment
        self.limits = limits or JobLimits()
        self.reconnect = reconnect

    def _call(self, operation: Callable[[Repository], T]) -> T:
        try:
            return operation(self.repository)
        except Rejection as error:
            if error.category not in TRANSIENT or self.reconnect is None:
                raise
            try:
                self.repository.close()
            except Exception:
                pass
            self.repository = self.reconnect()
            return operation(self.repository)

    def admit(
        self, request_id: uuid.UUID, interval: Interval, tiles: list[list[int]], job_id: str
    ) -> tuple[str, str | None]:
        try:
            result = self._call(
                lambda repository: repository.admit(
                    self.environment,
                    request_id,
                    "historical",
                    interval,
                    {"execution_seconds": self.limits.run_execution_seconds},
                    input_kind="live",
                    descriptor={"live_opt_in": True, "tiles": tiles, "job_id": job_id},
                )
            )
        except Rejection as error:
            if error.category in ("unsafe_run_configuration", *TRANSIENT):
                raise
            return "overlap_skip", None
        kind = str(result["kind"])
        return kind, (str(result["run_id"]) if "run_id" in result else None)

    def status(self, run_id: str) -> RunStatus:
        run = self._call(lambda repository: repository.run(uuid.UUID(run_id)))
        if not run["closed"]:
            return RunStatus(False, str(run["state"]), {})
        chunks = self._call(lambda repository: repository.chunks(uuid.UUID(run_id)))
        leaves = [chunk for chunk in chunks if chunk["leaf"]]
        counts: dict[str, int] = {}
        for chunk in leaves:
            counts[chunk["state"]] = counts.get(chunk["state"], 0) + 1
        missing = [
            chunk["logical_chunk_key"]
            for chunk in leaves
            if chunk["state"] in TERMINAL and chunk["state"] != "complete"
        ]

        def counters(repository: Repository) -> tuple[Any, Any]:
            with repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute(
                    "SELECT count(*) FILTER (WHERE a.request_attempt > 1) AS retries,"
                    " count(*) AS attempts FROM app.ingestion_attempt a"
                    " JOIN app.ingestion_chunk c ON c.id = a.chunk_id WHERE c.run_id = %s",
                    (uuid.UUID(run_id),),
                )
                attempts = cursor.fetchone()
                cursor.execute(
                    "SELECT max(occurred_at) AS finished FROM app.ingestion_event"
                    " WHERE run_id = %s",
                    (uuid.UUID(run_id),),
                )
                return attempts, cursor.fetchone()

        attempts, last_event = self._call(counters)
        finished = None if last_event is None else last_event["finished"]
        evidence: dict[str, Any] = {
            "run_id": run_id,
            "termination_reason": run.get("termination_reason"),
            "leaf_states": counts,
            "missing_chunks": missing[:500],
            "http_attempts": int(run.get("http_attempts") or 0),
            "request_attempts": int(attempts["attempts"]) if attempts else 0,
            "http_retries": int(attempts["retries"]) if attempts else 0,
            "accepted_profiles": int(run.get("accepted_profiles") or 0),
            "accepted_levels": int(run.get("accepted_levels") or 0),
            "received_bytes": int(run.get("raw_received_bytes") or 0),
            "controller_claims": int(run.get("controller_claims") or 0),
            "created_at": run["created_at_actual_utc"].isoformat(),
            "finished_at": None if finished is None else finished.isoformat(),
        }
        return RunStatus(True, str(run["state"]), evidence)

    def cancel(self, run_id: str) -> None:
        try:
            self._call(
                lambda repository: repository.finalize(uuid.UUID(run_id), "operator_cancelled")
            )
        except Rejection:
            pass
