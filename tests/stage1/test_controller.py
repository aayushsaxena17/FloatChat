import copy
import uuid
from datetime import timedelta

import pytest
from floatchat_core.ingestion.controller import Controller, Supervisor
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import timestamp
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.states import ticket_kind

NOW = timestamp("2026-10-06T12:00:00Z")
RUN = uuid.uuid4()
ENVIRONMENT = uuid.uuid4()


def recorder():
    """dispatch(authority, kind) callback and the (authority, kind) calls it recorded."""
    calls = []
    return calls, lambda authority, kind: calls.append((authority, kind))


class Store:
    def __init__(self, count=3, limit=2):
        # limit is ingestion_environment.max_active_chunks (2 keeps the stage1-v3 bound).
        self.limit = limit
        self.row = {
            "state": "planned",
            "environment_id": ENVIRONMENT,
            "closed": False,
            "control_epoch": 1,
            "controller_claims": 1,
            "cancellation_requested_at": None,
            "controller_lease_until": NOW + timedelta(minutes=10),
            "work_deadline": NOW + timedelta(hours=6),
        }
        self.items = [
            {
                "id": uuid.uuid4(),
                "leaf": True,
                "state": "planned",
                "control_epoch": 1,
                "lease_until": None,
                "processing_claims": 0,
                "fence": 0,
            }
            for _ in range(count)
        ]
        self.owner = None
        self.heartbeats = 0
        self.final_reason = None
        self.input_evidence = {"kind": "captured"}

    def run(self, identifier):
        return copy.deepcopy(self.row)

    def start_controller(self, identifier, instance):
        if self.owner is not None and self.owner != instance:
            if self.row["controller_lease_until"] > NOW:
                return None
        if self.row["controller_lease_until"] <= NOW:
            self.row["control_epoch"] += 1
            self.row["controller_claims"] += 1
        self.owner = instance
        return self.row["control_epoch"]

    def controller_heartbeat(self, identifier, epoch):
        assert epoch == self.row["control_epoch"]
        self.heartbeats += 1
        self.row["controller_lease_until"] = NOW + timedelta(minutes=10)

    def environment(self, identifier):
        assert identifier == ENVIRONMENT
        return {"max_active_chunks": self.limit, "upstream_slots": 4}

    def input(self, identifier):
        return self.input_evidence

    def persist_plan(self, identifier, epoch):
        raise AssertionError("Existing plan must survive takeover")

    def chunks(self, identifier):
        return copy.deepcopy(tuple(self.items))

    def claim(self, identifier, chunk, epoch):
        row = next(row for row in self.items if row["id"] == chunk)
        row["fence"] += 1
        row["processing_claims"] += 1
        row["control_epoch"] = epoch
        row["lease_until"] = NOW + timedelta(minutes=10)
        return Authority(identifier, chunk, epoch, row["fence"])

    def finalize(self, identifier, reason=None):
        self.final_reason = reason
        if reason:
            for chunk in self.items:
                if chunk["state"] not in ("complete", "quarantined", "failed"):
                    chunk["state"] = "failed"
        states = [row["state"] for row in self.items]
        result = (
            "complete"
            if states and all(s == "complete" for s in states)
            else ("partial" if "complete" in states else "failed")
        )
        self.row.update(closed=True, state=result)
        return result


def test_controller_dispatches_only_two_persisted_claims_and_no_duplicate_delivery():
    store = Store()
    dispatches, dispatch = recorder()
    controller = Controller(store, RUN, dispatch, clock=lambda: NOW)
    assert controller.tick() == "running"
    assert len(dispatches) == 2 and all(a.fence == 1 for a, _ in dispatches)
    # Planned chunks are acquire work; the process pool gets them only after landing.
    assert [kind for _, kind in dispatches] == ["acquire", "acquire"]
    controller.tick()
    assert len(dispatches) == 2 and store.heartbeats == 1


@pytest.mark.parametrize(("limit", "count", "expected"), [(1, 4, 1), (2, 4, 2), (8, 10, 8)])
def test_active_chunk_bound_is_the_environment_max_active_chunks(limit, count, expected):
    store = Store(count=count, limit=limit)
    dispatches, dispatch = recorder()
    assert Controller(store, RUN, dispatch, clock=lambda: NOW).tick() == "running"
    assert len(dispatches) == expected
    assert sum(row["processing_claims"] for row in store.items) == expected


def test_landed_chunks_awaiting_the_process_pool_count_against_the_bound():
    store = Store(count=3, limit=2)
    for row in store.items[:2]:
        row.update(state="landed", fence=1, processing_claims=1)
        row["lease_until"] = NOW + timedelta(minutes=5)
    dispatches, dispatch = recorder()
    Controller(store, RUN, dispatch, clock=lambda: NOW).tick()
    assert dispatches == [] and store.items[2]["processing_claims"] == 0


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("planned", "acquire"),
        ("fetching", "acquire"),
        ("landed", "process"),
        ("validating", "process"),
        ("publishing", "process"),
    ],
)
def test_ticket_kind_follows_the_persisted_phase(state, kind):
    assert ticket_kind(state) == kind


@pytest.mark.parametrize("state", ["complete", "quarantined", "failed", "unknown"])
def test_ticket_kind_rejects_terminal_and_unknown_phases(state):
    with pytest.raises(Rejection, match="invalid_ticket_phase"):
        ticket_kind(state)


@pytest.mark.parametrize("state", ["fetching", "landed", "validating", "publishing"])
def test_C05_worker_death_resumes_exact_phase_with_new_fence(state):
    store = Store()
    dispatches, dispatch = recorder()
    row = store.items[0]
    row.update(state=state, fence=1, processing_claims=1, lease_until=NOW)
    controller = Controller(store, RUN, dispatch, clock=lambda: NOW)
    controller.tick()
    authority, kind = dispatches[0]
    assert authority.fence == 2 and store.items[0]["state"] == state
    # The recovery ticket matches the phase that was lost: fetching is re-acquired,
    # landed/validating/publishing go to the process pool without any upstream request.
    assert kind == ("acquire" if state == "fetching" else "process")
    assert store.final_reason is None


def test_C06_controller_death_invalidates_old_claims_without_new_plan():
    store = Store()
    dispatches, dispatch = recorder()
    store.row["controller_lease_until"] = NOW
    store.items[0].update(state="publishing", lease_until=NOW + timedelta(minutes=5), fence=1)
    controller = Controller(store, RUN, dispatch, clock=lambda: NOW)
    assert controller.tick() == "running"
    authority, kind = dispatches[0]
    assert controller.epoch == 2 and authority.epoch == 2 and authority.fence == 2
    assert kind == "process" and store.items[0]["state"] == "publishing"


@pytest.mark.parametrize("reason", ["operator_cancelled", "deadline_expired"])
def test_C07_C08_closing_preserves_committed_chunks_and_fails_every_unstarted_chunk(reason):
    store = Store()
    store.items[0]["state"] = "complete"
    if reason == "operator_cancelled":
        store.row["cancellation_requested_at"] = NOW
    else:
        store.row["work_deadline"] = NOW
    controller = Controller(
        store, RUN, lambda *_: pytest.fail("No dispatch after closing"), clock=lambda: NOW
    )
    assert controller.tick() == "partial" and store.final_reason == reason
    assert [r["state"] for r in store.items] == ["complete", "failed", "failed"]


def test_C09_cancel_after_all_commits_reduces_to_complete():
    store = Store()
    for row in store.items:
        row["state"] = "complete"
    store.row["cancellation_requested_at"] = NOW
    assert Controller(store, RUN, lambda *_: None, clock=lambda: NOW).tick() == "complete"


@pytest.mark.parametrize("kind", ["worker", "controller"])
def test_C11_takeover_budget_exhaustion_terminates_all_remaining_work(kind):
    store = Store()
    if kind == "worker":
        store.items[0].update(processing_claims=4, lease_until=NOW)
    else:
        store.row.update(controller_claims=4, controller_lease_until=NOW)
    controller = Controller(
        store, RUN, lambda *_: pytest.fail("Budget exhaustion dispatch"), clock=lambda: NOW
    )
    assert controller.tick() == "failed" and store.final_reason == "recovery_budget_exhausted"


def test_dispatch_failure_preserves_unknown_delivery_lease_and_consumed_claim():
    store = Store()
    controller = Controller(
        store, RUN, lambda *_: (_ for _ in ()).throw(RuntimeError("private")), clock=lambda: NOW
    )
    with pytest.raises(Rejection, match="worker_dispatch_unavailable") as error:
        controller.tick()
    assert "private" not in str(error.value)
    assert store.items[0]["processing_claims"] == 1 and store.items[0]["lease_until"] > NOW
    assert not store.row["closed"]


def test_supervisor_never_steals_live_incumbent_controller():
    store = Store()
    store.owner = uuid.uuid4()
    supervisor = Supervisor(
        store, lambda *_: pytest.fail("Stole live controller"), clock=lambda: NOW
    )
    assert supervisor.tick((RUN,)) == {RUN: "controller_busy"}
    assert supervisor.tick(()) == {} and not supervisor.controllers


def test_controller_missing_input_before_plan_is_failed_not_empty_success():
    store = Store()
    store.items = []
    store.input_evidence = None
    assert Controller(store, RUN, lambda *_: None, clock=lambda: NOW).tick() == "failed"
    assert store.final_reason == "execution_failed"
