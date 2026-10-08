"""Durable controller/supervisor ticks. Broker messages carry only opaque IDs.

Ticks do no HTTP work. An independent supervisor calls them every ten seconds;
workers receive the already-persisted chunk claim, not a new retry budget. Any
database error escapes and cannot be converted into an apparent successful run.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from .numeric import Rejection
from .repository import Authority
from .states import TERMINAL


class ControlStore(Protocol):
    def run(self, identifier: uuid.UUID) -> dict[str, Any]: ...
    def start_controller(self, run: uuid.UUID, instance: uuid.UUID) -> int | None: ...
    def controller_heartbeat(self, run: uuid.UUID, epoch: int) -> None: ...
    def input(self, run: uuid.UUID) -> dict[str, Any] | None: ...
    def persist_plan(self, run: uuid.UUID, epoch: int) -> None: ...
    def chunks(self, run: uuid.UUID) -> tuple[dict[str, Any], ...]: ...
    def claim(self, run: uuid.UUID, chunk: uuid.UUID, epoch: int) -> Authority | None: ...
    def finalize(self, run: uuid.UUID, reason: str | None = None) -> str: ...


class Controller:
    def __init__(
        self,
        store: ControlStore,
        run: uuid.UUID,
        dispatch: Callable[[Authority], None],
        *,
        instance: uuid.UUID | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.run_id, self.dispatch = store, run, dispatch
        self.instance = instance or uuid.uuid4()
        self.clock = clock
        self.epoch: int | None = None
        self.last_heartbeat: datetime | None = None

    def tick(self) -> str:
        row = self.store.run(self.run_id)
        if row["closed"]:
            return str(row["state"])
        now = self.clock()
        # Closing wins before ownership/claims. Complete chunks are preserved by
        # the same row lock used by publication; the finalizer reduces all leaves.
        if row["cancellation_requested_at"] is not None:
            return self.store.finalize(self.run_id, "operator_cancelled")
        if now >= row["work_deadline"]:
            return self.store.finalize(self.run_id, "deadline_expired")
        if self.epoch == row["control_epoch"] and row["controller_lease_until"] <= now:
            self.epoch = None
            self.last_heartbeat = None
        if self.epoch is None:
            if row["controller_lease_until"] <= now and row["controller_claims"] >= 4:
                return self.store.finalize(self.run_id, "recovery_budget_exhausted")
            self.epoch = self.store.start_controller(self.run_id, self.instance)
            if self.epoch is None:
                return "controller_busy"
        if row["control_epoch"] != self.epoch:
            # start_controller may just have adopted the old epoch. Re-read; an
            # incumbent that was fenced later must never recover ownership here.
            row = self.store.run(self.run_id)
            if row["control_epoch"] != self.epoch:
                return "controller_fenced"
        if self.last_heartbeat is None or (now - self.last_heartbeat).total_seconds() >= 60:
            self.store.controller_heartbeat(self.run_id, self.epoch)
            self.last_heartbeat = now
        if not self.store.chunks(self.run_id):
            if self.store.input(self.run_id) is None:
                return self.store.finalize(self.run_id, "execution_failed")
            self.store.persist_plan(self.run_id, self.epoch)
        chunks = self.store.chunks(self.run_id)
        leaves = [chunk for chunk in chunks if chunk["leaf"]]
        if leaves and all(chunk["state"] in TERMINAL for chunk in leaves):
            return self.store.finalize(self.run_id)
        active = sum(
            chunk["state"] not in TERMINAL
            and chunk["control_epoch"] == self.epoch
            and chunk["lease_until"] is not None
            and chunk["lease_until"] > now
            for chunk in leaves
        )
        for chunk in leaves:
            if chunk["state"] in TERMINAL:
                continue
            leased = (
                chunk["control_epoch"] == self.epoch
                and chunk["lease_until"] is not None
                and chunk["lease_until"] > now
            )
            if leased:
                continue
            if chunk["processing_claims"] >= 4:
                return self.store.finalize(self.run_id, "recovery_budget_exhausted")
            if active >= 2:
                continue
            authority = self.store.claim(self.run_id, chunk["id"], self.epoch)
            if authority is None:
                continue
            active += 1
            try:
                self.dispatch(authority)
            except Exception:
                # A send failure has an unknown delivery outcome. Leave the
                # durable lease in place, never dispatch/claim it twice now.
                raise Rejection("worker_dispatch_unavailable") from None
        return "running"


class Supervisor:
    """Independent loop holds live controllers; replacements adopt persisted work."""

    def __init__(
        self,
        store: ControlStore,
        dispatch: Callable[[Authority], None],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.dispatch, self.clock = store, dispatch, clock
        self.controllers: dict[uuid.UUID, Controller] = {}

    def tick(self, unfinished: tuple[uuid.UUID, ...]) -> dict[uuid.UUID, str]:
        for identifier in tuple(self.controllers):
            if identifier not in unfinished:
                del self.controllers[identifier]
        results = {}
        for identifier in unfinished:
            controller = self.controllers.setdefault(
                identifier,
                Controller(self.store, identifier, self.dispatch, clock=self.clock),
            )
            results[identifier] = controller.tick()
        return results
