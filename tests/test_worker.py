"""Worker entrypoint over the PostgreSQL queue: ticket kinds, duplicate delivery, bounds.

Fakes only: no database, object store, broker or network. The SQL behaviour of the queue
itself is covered by the integration-marked tests/stage1/test_queue_sql.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_workers import ingestion

RUN, CHUNK, TICKET, ENV = (uuid.uuid4() for _ in range(4))
AUTHORITY = Authority(RUN, CHUNK, 3, 7)
SECRET = "synthetic-private-exception-sentinel"


class Repository:
    def __init__(self, state="planned", *, inputs=None, started=False, ticket_error=None):
        self.state, self.started, self.ticket_error = state, started, ticket_error
        self.inputs = inputs if inputs is not None else {"kind": "captured", "descriptor": {}}
        self.start_calls, self.tickets, self.transitions, self.closed = 0, [], [], 0

    def chunk(self, identifier):
        assert identifier == CHUNK
        return {"run_id": RUN, "state": self.state}

    def start_worker(self, run, chunk, ticket):
        self.start_calls += 1
        if self.started:
            return None
        self.started = True
        return AUTHORITY

    def run(self, identifier):
        return {
            "environment_id": ENV,
            "policy_versions": policy_versions(),
            "work_deadline": datetime.now(UTC) + timedelta(hours=1),
        }

    def input(self, identifier):
        return self.inputs

    def ticket(self, authority, kind="process"):
        if self.ticket_error:
            raise self.ticket_error
        self.tickets.append((authority, kind))
        return uuid.uuid4()

    def transition(self, authority, state, reason, evidence=None):
        self.transitions.append((authority, state, reason))

    def close(self):
        self.closed += 1


class Processor:
    """Records which phase ran; `result` is what land()/process()/execute() return."""

    result = "landed"
    error: Exception | None = None
    instances: list = []

    def __init__(self, repository, budget, store, source, authority, private, *, deadline):
        self.source, self.authority, self.calls = source, authority, []
        Processor.instances.append(self)

    def run(self, phase):
        self.calls.append(phase)
        if Processor.error is not None:
            raise Processor.error
        return Processor.result

    land = lambda self: self.run("land")  # noqa: E731
    process = lambda self: self.run("process")  # noqa: E731
    execute = lambda self: self.run("execute")  # noqa: E731


@pytest.fixture
def worker(monkeypatch, tmp_path):
    Processor.result, Processor.error, Processor.instances = "landed", None, []
    harness = SimpleNamespace(
        repository=Repository(), memory=[], recorded=[], owners=[], processor=Processor
    )

    def build(state=None, **options):
        harness.repository = Repository(**({"state": state} if state else {}), **options)
        return harness.repository

    configuration = SimpleNamespace(
        repository=lambda: harness.repository,
        environment=ENV,
        private=tmp_path,
        store=lambda: object(),
        application_commit="test",
        worker_memory_bytes=512 * 1024**2,
    )

    class Source:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

    class Recorded(Source):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            harness.recorded.append(self)

    class Owner(Source):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            harness.owners.append(self)

    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(ingestion, "bounded_worker_memory", harness.memory.append)
    monkeypatch.setattr(ingestion, "Processor", Processor)
    monkeypatch.setattr(ingestion, "RecordedSource", Recorded)
    monkeypatch.setattr(ingestion, "RequestOwner", Owner)
    harness.build = build
    return harness


def run_ticket(kind="process", **options):
    return ingestion.process_ticket(str(RUN), str(CHUNK), str(TICKET), kind, **options)


def test_default_kind_is_process_and_publishes_from_existing_landings_only(worker):
    repository = worker.build("landed")
    Processor.result = "complete"
    assert ingestion.process_ticket(str(RUN), str(CHUNK), str(TICKET)) == "complete"
    assert [p.calls for p in Processor.instances] == [["process"]]
    assert worker.recorded[0].kwargs["require_existing"] is True
    assert repository.tickets == [] and worker.memory == [512 * 1024**2]


@pytest.mark.parametrize("state", ["landed", "validating", "publishing"])
def test_process_kind_never_fetches_for_any_process_phase(worker, state):
    worker.build(state)
    Processor.result = "complete"
    assert run_ticket("process") == "complete"
    assert worker.recorded[0].kwargs["require_existing"] is True


def test_acquire_kind_lands_and_hands_the_chunk_to_the_process_pool_under_one_claim(worker):
    repository = worker.build("planned")
    assert run_ticket("acquire") == "landed"
    assert [p.calls for p in Processor.instances] == [["land"]]
    assert worker.recorded[0].kwargs["require_existing"] is False
    # Same epoch and fence: normal phase progress consumes no extra processing claim.
    assert repository.tickets == [(AUTHORITY, "process")]


@pytest.mark.parametrize("result", ["split_replaced", "failed", "quarantined", "complete"])
def test_acquire_hands_over_only_a_landed_chunk(worker, result):
    repository = worker.build("fetching")
    Processor.result = result
    assert run_ticket("acquire") == result
    assert repository.tickets == []


def test_failed_handover_leaves_the_landed_result_for_lease_recovery(worker, capsys):
    repository = worker.build("planned", ticket_error=RuntimeError(SECRET))
    assert run_ticket("acquire") == "landed"
    output = capsys.readouterr().out
    assert "process_handover_unavailable" in output and SECRET not in output
    assert repository.transitions == []


def test_execute_kind_is_the_serial_land_then_process_path(worker):
    worker.build("landed")
    Processor.result = "complete"
    assert run_ticket("execute") == "complete"
    assert [p.calls for p in Processor.instances] == [["execute"]]
    assert worker.recorded[0].kwargs["require_existing"] is True
    worker.build("planned")
    run_ticket("execute")
    assert worker.recorded[1].kwargs["require_existing"] is False


@pytest.mark.parametrize("kind", ["acquire", "process", "execute"])
@pytest.mark.parametrize("state", ["complete", "quarantined", "failed"])
def test_lost_acknowledgement_is_recognized_before_ticket_memory_or_source(
    worker, monkeypatch, kind, state
):
    repository = worker.build(state)
    monkeypatch.setattr(
        ingestion, "upstream_credential", lambda: pytest.fail("Terminal credential access")
    )
    monkeypatch.setattr(ingestion, "Processor", lambda *a, **k: pytest.fail("Terminal work"))
    assert run_ticket(kind) == state
    assert repository.start_calls == 0 and worker.memory == [] and repository.tickets == []


@pytest.mark.parametrize("kind", ["acquire", "process"])
def test_duplicate_delivery_is_recognized_and_does_no_work(worker, kind):
    repository = worker.build("landed", started=True)
    assert run_ticket(kind) == "duplicate_delivery"
    assert repository.start_calls == 1 and Processor.instances == []
    assert repository.tickets == [] and repository.transitions == []


def test_two_deliveries_of_one_ticket_execute_exactly_once(worker):
    worker.build("landed")
    Processor.result = "complete"
    assert [run_ticket("process"), run_ticket("process")] == ["complete", "duplicate_delivery"]
    assert len(Processor.instances) == 1


@pytest.mark.parametrize("state", ["planned", "fetching"])
def test_process_ticket_for_an_unlanded_chunk_is_refused_before_a_worker_starts(worker, state):
    repository = worker.build(state)
    assert run_ticket("process") == "recovery_required"
    assert repository.start_calls == 0 and Processor.instances == [] and worker.memory == []
    assert repository.transitions == []  # the chunk is not failed by a misrouted ticket


def test_acquire_ticket_for_an_already_landed_chunk_just_confirms_and_hands_over(worker):
    repository = worker.build("validating")
    assert run_ticket("acquire") == "landed"
    assert repository.tickets == [(AUTHORITY, "process")]


def test_unknown_kind_is_rejected_without_opening_anything(worker):
    repository = worker.build("planned")
    assert run_ticket("serve") == "recovery_required"
    assert repository.start_calls == 0 and worker.memory == []


def test_chunk_of_another_run_is_unknown(worker):
    repository = worker.build("landed")
    assert (
        ingestion.process_ticket(str(uuid.uuid4()), str(CHUNK), str(TICKET), "process")
        == "recovery_required"
    )
    assert repository.start_calls == 0


@pytest.mark.parametrize("kind", ["acquire", "process", "execute"])
def test_worker_failure_is_recorded_without_exception_text(worker, capsys, kind):
    repository = worker.build("landed" if kind == "process" else "planned")
    Processor.error = RuntimeError(SECRET)
    assert run_ticket(kind) == "failed"
    assert repository.transitions == [(AUTHORITY, "failed", "worker_execution_failed")]
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("category", ["publication_fenced", "run_fenced", "work_deadline"])
def test_fencing_and_deadline_leave_recoverable_work(worker, category):
    repository = worker.build("landed")
    Processor.error = Rejection(category)
    assert run_ticket("process") == "recovery_required"
    assert repository.transitions == []


def test_failure_before_a_claim_is_recovery_required_with_no_transition(worker, capsys):
    def explode():
        raise RuntimeError(SECRET)

    repository = worker.build("planned")
    repository.chunk = lambda identifier: explode()
    assert run_ticket("acquire") == "recovery_required"
    assert SECRET not in capsys.readouterr().out and repository.transitions == []


def test_every_connection_is_closed(worker):
    repository = worker.build("planned")
    run_ticket("acquire")
    assert repository.closed >= 1


@pytest.mark.parametrize(
    ("kind", "governor", "expected"),
    [
        ("acquire", "governor", {"governor": "governor", "slot": 3}),
        ("acquire", None, {}),
        ("process", None, {}),
    ],
)
def test_governor_and_slot_reach_only_a_live_acquire_source(worker, kind, governor, expected):
    worker.build("landed" if kind == "process" else "planned", inputs={"kind": "live"})
    options = {} if governor is None else {"governor": governor, "slot": 3}
    run_ticket(kind, **options)
    kwargs = worker.owners[0].kwargs
    assert {k: v for k, v in kwargs.items() if k in ("governor", "slot")} == expected
    assert kwargs["require_existing"] is (kind == "process")


def test_acquire_threads_share_only_the_governor(worker, monkeypatch, tmp_path):
    """Repository (a psycopg connection) is not thread-safe: each ticket builds its own."""
    import threading

    users, created = {}, []

    class Own(Repository):
        def __init__(self):
            super().__init__("planned", inputs={"kind": "live"})
            created.append(self)

        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if callable(value) and not name.startswith("_") and name != "close":
                users.setdefault(id(self), set()).add(threading.get_ident())
            return value

    configuration = SimpleNamespace(
        repository=Own,
        environment=ENV,
        private=tmp_path,
        store=lambda: object(),
        application_commit="test",
        worker_memory_bytes=512 * 1024**2,
    )
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    governor, outcomes = object(), []

    def acquire(index):
        outcomes.append(run_ticket("acquire", governor=governor, slot=index))

    threads = [threading.Thread(target=acquire, args=(index,)) for index in (1, 2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes == ["landed"] * 3
    # Per ticket: a work connection and a budget connection, never used by another thread.
    assert len(created) == 6 and all(len(owners) == 1 for owners in users.values())
    assert len(Processor.instances) == 3 and len({id(p) for p in Processor.instances}) == 3
    assert len(worker.owners) == 3
    assert {owner.kwargs["slot"] for owner in worker.owners} == {1, 2, 3}
    assert all(owner.kwargs["governor"] is governor for owner in worker.owners)
    assert len({id(owner.args[0]) for owner in worker.owners}) == 3  # own repository each


# Configuration -------------------------------------------------------------------------

ENVIRONMENT = {
    "INGESTION_DATABASE_URL": "postgresql://ingestion@db/floatchat",
    "INGESTION_ENVIRONMENT_ID": str(ENV),
    "INGESTION_BUCKET": "bucket",
    "INGESTION_QUEUE_NAMESPACE": "queue",
    "COMPOSE_PROJECT_NAME": "project",
    "OBJECT_STORAGE_ENDPOINT": "http://minio:9000",
    "OBJECT_STORAGE_ACCESS_KEY": "access",
    "OBJECT_STORAGE_SECRET_KEY": "secret",
    "INGESTION_APPLICATION_COMMIT": "abc",
}


@pytest.fixture
def environment(monkeypatch):
    for name in (
        "INGESTION_ACQUIRE_SLOTS",
        "INGESTION_PROCESS_WORKERS",
        "INGESTION_WORKER_MEMORY_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_configuration_needs_no_broker_and_has_queue_defaults(environment):
    configuration = ingestion.Configuration.load()
    assert not hasattr(configuration, "broker_url")
    assert configuration.acquire_slots == 4
    assert 1 <= configuration.process_workers <= 4
    assert configuration.worker_memory_bytes == 1024**3
    assert configuration.queue == "queue" and configuration.private == (
        Path.home() / "private/floatchat-stage1"
    )


def test_configuration_reads_queue_sizes_from_the_environment(environment):
    environment.setenv("INGESTION_ACQUIRE_SLOTS", "8")
    environment.setenv("INGESTION_PROCESS_WORKERS", "3")
    environment.setenv("INGESTION_WORKER_MEMORY_BYTES", str(512 * 1024**2))
    configuration = ingestion.Configuration.load()
    assert (configuration.acquire_slots, configuration.process_workers) == (8, 3)
    assert configuration.worker_memory_bytes == 512 * 1024**2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("INGESTION_ACQUIRE_SLOTS", "0"),
        ("INGESTION_ACQUIRE_SLOTS", "17"),
        ("INGESTION_ACQUIRE_SLOTS", "four"),
        ("INGESTION_PROCESS_WORKERS", "0"),
        ("INGESTION_PROCESS_WORKERS", "65"),
        ("INGESTION_WORKER_MEMORY_BYTES", str(1024**3 + 1)),  # contract: reduce, never raise
        ("INGESTION_WORKER_MEMORY_BYTES", "1024"),
    ],
)
def test_configuration_rejects_out_of_range_values_without_echoing_them(environment, name, value):
    environment.setenv(name, value)
    with pytest.raises(Rejection, match="invalid_ingestion_configuration") as error:
        ingestion.Configuration.load()
    assert value not in str(error.value)


def test_configuration_repr_never_contains_credentials(environment):
    text = repr(ingestion.Configuration.load())
    assert "secret" not in text and "postgresql://" not in text


# Memory bound --------------------------------------------------------------------------

LIMIT = 512 * 1024**2


@pytest.fixture
def rlimit(monkeypatch):
    state = SimpleNamespace(
        soft=ingestion.resource.RLIM_INFINITY, hard=ingestion.resource.RLIM_INFINITY, calls=[]
    )

    def getrlimit(which):
        assert which == ingestion.resource.RLIMIT_DATA
        return state.soft, state.hard

    def setrlimit(which, values):
        state.calls.append((which, values))

    monkeypatch.setattr(ingestion.resource, "getrlimit", getrlimit)
    monkeypatch.setattr(ingestion.resource, "setrlimit", setrlimit)
    return state


def cgroup(monkeypatch, value):
    if isinstance(value, Exception):

        def read(*args, **kwargs):
            raise value

    else:

        def read(*args, **kwargs):
            return value

    monkeypatch.setattr(ingestion.Path, "read_text", read)


def test_B07_cgroup_of_at_most_one_gib_is_the_memory_bound(monkeypatch, rlimit):
    cgroup(monkeypatch, str(1024**3) + "\n")
    ingestion.bounded_worker_memory(LIMIT)
    assert rlimit.calls == []


@pytest.mark.parametrize("value", ["max", str(1024**3 + 1), "0", "garbage"])
def test_B07_without_a_small_cgroup_rlimit_data_is_set(monkeypatch, rlimit, value):
    cgroup(monkeypatch, value)
    ingestion.bounded_worker_memory(LIMIT)
    assert rlimit.calls == [(ingestion.resource.RLIMIT_DATA, (LIMIT, rlimit.hard))]


def test_B07_unreadable_cgroup_falls_back_to_rlimit_data(monkeypatch, rlimit):
    cgroup(monkeypatch, FileNotFoundError())
    ingestion.bounded_worker_memory()
    assert rlimit.calls == [(ingestion.resource.RLIMIT_DATA, (1024**3, rlimit.hard))]


def test_B07_rlimit_as_is_never_used(monkeypatch, rlimit):
    cgroup(monkeypatch, "max")
    ingestion.bounded_worker_memory(LIMIT)
    assert rlimit.calls and all(
        which == ingestion.resource.RLIMIT_DATA for which, _ in rlimit.calls
    )


def test_B07_a_lower_existing_soft_limit_is_kept_and_calls_are_idempotent(monkeypatch, rlimit):
    cgroup(monkeypatch, "max")
    rlimit.soft = LIMIT // 2
    ingestion.bounded_worker_memory(LIMIT)
    rlimit.soft = LIMIT
    ingestion.bounded_worker_memory(LIMIT)
    assert rlimit.calls == []


def test_B07_failure_to_set_the_bound_rejects_the_worker(monkeypatch, rlimit):
    cgroup(monkeypatch, "max")

    def refuse(which, values):
        raise ValueError("not allowed")

    monkeypatch.setattr(ingestion.resource, "setrlimit", refuse)
    with pytest.raises(Rejection, match="worker_memory_bound_unavailable"):
        ingestion.bounded_worker_memory(LIMIT)
