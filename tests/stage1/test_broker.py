"""PostgreSQL work-queue clients and worker pools (stage1-v4).

The unit tests use an in-memory stand-in for the atomic `app.claim_ticket`; the SQL itself
(SKIP LOCKED, fencing, claim budgets) is proved by test_queue_sql.py. The integration test
runs real acquire/process/supervise processes in a disposable stack: no ports, production
volumes or upstream route.
"""

import json
import os
import secrets
import signal
import subprocess
import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion import transport
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_workers import acquire, process, queue
from test_database import ROOT
from test_database import postgres as postgres_fixture

postgres = postgres_fixture


class Queue:
    """Atomic claim over (kind, unclaimed, not locked), the contract of app.claim_ticket."""

    def __init__(self):
        self.guard = threading.Lock()
        self.tickets, self.locked, self.closed = [], set(), 0

    def add(self, kind, count=1):
        added = []
        for _ in range(count):
            ticket = {
                "id": uuid.uuid4(),
                "run_id": uuid.uuid4(),
                "chunk_id": uuid.uuid4(),
                "kind": kind,
                "claimed_by": None,
            }
            self.tickets.append(ticket)
            added.append(ticket)
        return added

    def repository(self):
        return Repository(self)


class Repository:
    def __init__(self, source):
        self.source = source

    def claim_ticket(self, kind, worker):
        with self.source.guard:
            for ticket in self.source.tickets:
                if (
                    ticket["kind"] == kind
                    and ticket["claimed_by"] is None
                    and ticket["id"] not in self.source.locked
                ):
                    ticket["claimed_by"] = worker
                    return dict(ticket)
        return None

    def close(self):
        self.source.closed += 1


class Stop(threading.Event):
    """Records waits; ends the loop after `limit` waits (the real wait would sleep)."""

    def __init__(self, limit=None):
        super().__init__()
        self.waits, self.limit = [], limit

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.limit is not None and len(self.waits) >= self.limit:
            self.set()
        return self.is_set()


def eventually(predicate, seconds=10):
    until = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < until, "condition not reached"
        time.sleep(0.01)


# Claim semantics -----------------------------------------------------------------------


def test_each_ticket_is_claimed_exactly_once_across_competing_workers():
    source = Queue()
    source.add("acquire", 30)
    source.add("process", 30)
    claimed = []

    def drain(kind, name):
        repository = source.repository()
        while (ticket := queue.claim(repository, kind, name)) is not None:
            claimed.append((kind, ticket["id"], ticket["claimed_by"]))

    workers = [
        threading.Thread(target=drain, args=(kind, f"{kind}:{index}"))
        for kind in ("acquire", "process")
        for index in range(6)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert len(claimed) == 60 and len({identifier for _, identifier, _ in claimed}) == 60
    assert all(by.startswith(kind) for kind, _, by in claimed)


def test_claim_routes_by_kind_and_leaves_the_other_queue_untouched():
    source = Queue()
    (acquire_ticket,) = source.add("acquire")
    repository = source.repository()
    assert queue.claim(repository, "process", "process:1") is None
    assert queue.claim(repository, "acquire", "acquire:1")["id"] == acquire_ticket["id"]
    assert queue.claim(repository, "acquire", "acquire:2") is None


def test_claim_skips_locked_tickets_instead_of_waiting_for_them():
    source = Queue()
    first, second = source.add("process", 2)
    source.locked.add(first["id"])  # another transaction is mid-claim
    repository = source.repository()
    assert queue.claim(repository, "process", "process:1")["id"] == second["id"]
    assert queue.claim(repository, "process", "process:2") is None


@pytest.mark.parametrize("kind", ["execute", "", "Acquire"])
def test_claim_refuses_unknown_kinds_before_touching_the_database(kind):
    class Closed:
        def claim_ticket(self, kind, worker):
            pytest.fail("Unknown kind reached the database")

    with pytest.raises(Rejection, match="invalid_ticket_kind"):
        queue.claim(Closed(), kind, "worker")


def test_worker_names_are_opaque_bounded_labels():
    name = queue.worker_name("acquire", 3)
    assert name.startswith("acquire:") and name.endswith(f":{os.getpid()}:3")
    assert len(name.encode()) <= 128


def test_ticket_arguments_are_the_process_ticket_argument_order():
    (ticket,) = Queue().add("process")
    assert queue.ticket_arguments(ticket) == (
        str(ticket["run_id"]),
        str(ticket["chunk_id"]),
        str(ticket["id"]),
    )


def test_issue_is_the_dispatch_and_passes_the_kind():
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 2)
    identifier = uuid.uuid4()
    calls = []

    class Writer:
        def ticket(self, value, kind):
            calls.append((value, kind))
            return identifier

    assert queue.issue(Writer(), authority, "acquire") == identifier
    assert calls == [(authority, "acquire")]
    with pytest.raises(Rejection, match="invalid_ticket_kind"):
        queue.issue(Writer(), authority, "execute")


# Polling loop --------------------------------------------------------------------------


def test_poll_handles_every_ticket_once_then_waits_one_second_when_idle():
    source = Queue()
    tickets = source.add("process", 3)
    handled, stop = [], Stop(limit=2)
    queue.poll(source.repository, "process", "w", lambda ticket: handled.append(ticket["id"]), stop)
    assert handled == [ticket["id"] for ticket in tickets]
    assert stop.waits == [1.0, 1.0] and source.closed == 1


def test_poll_waits_before_claiming_while_the_pool_is_full():
    source = Queue()
    source.add("process")
    permits, handled = iter([False, False, True]), []
    stop = Stop(limit=3)
    queue.poll(
        source.repository,
        "process",
        "w",
        lambda ticket: handled.append(ticket),
        stop,
        ready=lambda: next(permits, True),
    )
    assert stop.waits[:2] == [0.2, 0.2] and len(handled) == 1


def test_poll_backs_off_on_database_loss_and_reconnects():
    source = Queue()
    source.add("acquire")
    failures, opened, handled = [3], [], []

    class Flaky(Repository):
        def claim_ticket(self, kind, worker):
            if failures[0]:
                failures[0] -= 1
                raise Rejection("database_failure")
            return super().claim_ticket(kind, worker)

    def open_repository():
        opened.append(1)
        return Flaky(source)

    stop = Stop(limit=5)
    queue.poll(open_repository, "acquire", "w", handled.append, stop)
    # Doubling waits from the 1 s idle interval, capped at 30 s; a new connection each time.
    assert stop.waits[:3] == [2.0, 4.0, 8.0] and len(handled) == 1 and len(opened) == 4
    assert source.closed == 4


def test_poll_backoff_is_capped():
    class Down:
        def claim_ticket(self, kind, worker):
            raise Rejection("database_deadline")

        def close(self):
            pass

    stop = Stop(limit=9)
    queue.poll(Down, "acquire", "w", lambda ticket: None, stop)
    assert max(stop.waits) == queue.MAX_BACKOFF_SECONDS


def test_poll_does_not_retry_configuration_faults():
    source = Queue()

    class Unsafe(Repository):
        def claim_ticket(self, kind, worker):
            raise Rejection("unsafe_environment")

    stop = Stop()
    with pytest.raises(Rejection, match="unsafe_environment"):
        queue.poll(lambda: Unsafe(source), "process", "w", lambda ticket: None, stop)
    assert stop.waits == [] and source.closed == 1


def test_poll_stops_promptly_when_asked():
    source = Queue()
    stop = threading.Event()
    stop.set()
    queue.poll(source.repository, "acquire", "w", lambda ticket: pytest.fail("claimed"), stop)


def test_ticket_handler_errors_are_not_swallowed():
    source = Queue()
    source.add("acquire")

    def explode(ticket):
        raise RuntimeError("handler fault")

    with pytest.raises(RuntimeError):
        queue.poll(source.repository, "acquire", "w", explode, Stop())
    assert source.closed == 1


# Acquire process -----------------------------------------------------------------------


def test_governor_is_constructed_with_the_slot_count_when_transport_has_one(monkeypatch):
    built = []

    class Governor:
        def __init__(self, permits):
            built.append(permits)

    monkeypatch.setattr(transport, "UpstreamGovernor", Governor, raising=False)
    assert isinstance(acquire.make_governor(4), Governor) and built == [4]


def test_missing_governor_degrades_to_the_single_default_slot(monkeypatch):
    monkeypatch.delattr(transport, "UpstreamGovernor", raising=False)
    assert acquire.make_governor(4) is None


def test_acquire_threads_run_acquire_tickets_with_the_shared_governor_and_own_slot(monkeypatch):
    source = Queue()
    tickets = source.add("acquire", 2)
    source.add("process")  # never taken by an acquire thread
    calls, stop = [], threading.Event()

    def record(run, chunk, identifier, kind, **options):
        calls.append((run, chunk, identifier, kind, options))
        if len(calls) == 2:
            stop.set()
        return "landed"

    monkeypatch.setattr(acquire, "process_ticket", record)
    governor = object()
    configuration = SimpleNamespace(repository=source.repository)
    acquire.work(configuration, governor, 3, stop)
    assert [call[2] for call in calls] == [str(t["id"]) for t in tickets]
    assert all(call[3] == "acquire" for call in calls)
    assert all(call[4] == {"governor": governor, "slot": 3} for call in calls)
    assert source.tickets[2]["claimed_by"] is None


def acquire_environment(monkeypatch, *, upstream_slots=4):
    memory = []
    repository = SimpleNamespace(
        environment=lambda identifier: {"upstream_slots": upstream_slots}, close=lambda: None
    )
    configuration = SimpleNamespace(
        environment=uuid.uuid4(),
        repository=lambda: repository,
        worker_memory_bytes=123,
    )
    monkeypatch.setattr(acquire.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(acquire, "bounded_worker_memory", memory.append)
    handlers = {}
    monkeypatch.setattr(
        acquire.signal, "signal", lambda number, handler: handlers.update({number: handler})
    )
    return configuration, memory, handlers


@pytest.mark.parametrize("slots", [0, 17, -1])
def test_acquire_rejects_slot_counts_outside_the_database_range(monkeypatch, slots):
    acquire_environment(monkeypatch)
    with pytest.raises(Rejection, match="invalid_acquire_slots"):
        acquire.main(slots)


def test_acquire_slots_cannot_exceed_the_environment_declaration(monkeypatch):
    _, memory, _ = acquire_environment(monkeypatch, upstream_slots=2)
    with pytest.raises(Rejection, match="acquire_slots_exceed_environment"):
        acquire.main(3)
    assert memory == []  # nothing started


def test_acquire_main_runs_one_thread_per_slot_sharing_one_governor(monkeypatch):
    configuration, memory, handlers = acquire_environment(monkeypatch)
    seen, release = {}, threading.Event()
    monkeypatch.setattr(acquire, "make_governor", lambda slots: ("governor", slots))

    def work(config, governor, index, stop):
        seen[index] = (config, governor)
        if index == 1:
            release.wait(5)
            stop.set()  # a SIGTERM-style shutdown
        else:
            stop.wait(5)

    monkeypatch.setattr(acquire, "work", work)
    runner = threading.Thread(target=lambda: seen.update(code=acquire.main(2)))
    runner.start()
    eventually(lambda: {1, 2} <= seen.keys())
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
    release.set()
    runner.join(10)
    assert not runner.is_alive() and seen["code"] == 0
    assert seen[1] == seen[2] == (configuration, ("governor", 2)) and memory == [123]


def test_acquire_main_fails_when_a_thread_dies_instead_of_running_degraded(monkeypatch):
    acquire_environment(monkeypatch)
    started = threading.Barrier(2, timeout=5)

    def work(config, governor, index, stop):
        started.wait()
        if index == 1:
            raise Rejection("unsafe_environment")
        stop.wait(10)

    monkeypatch.setattr(acquire, "work", work)
    with pytest.raises(Rejection, match="unsafe_environment"):
        acquire.main(2)


# Process pool --------------------------------------------------------------------------


class Child:
    """A spawn-context child that stays alive until the test releases it."""

    registry = []

    def __init__(self, target, args):
        self.target, self.args, self.alive, self.exitcode = target, args, True, None
        Child.registry.append(self)

    def start(self):
        pass

    def is_alive(self):
        return self.alive

    def join(self):
        pass

    def finish(self, code=0):
        self.alive, self.exitcode = False, code


def test_child_entrypoint_runs_one_process_ticket_and_reports_only_the_state(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(process, "process_ticket", lambda *args: calls.append(args) or "complete")
    process.run_ticket("run", "chunk", "ticket")
    assert calls == [("run", "chunk", "ticket", "process")]
    assert capsys.readouterr().out.strip() == "process ticket=ticket state=complete"


def test_reaping_frees_slots_and_reports_a_killed_worker_as_lost(capsys):
    done, lost, live = Child(None, ()), Child(None, ()), Child(None, ())
    done.finish(0)
    lost.finish(-9)
    running = {"done": done, "lost": lost, "live": live}
    process.reap(running)
    assert list(running) == ["live"]
    assert capsys.readouterr().out.strip() == "process ticket=lost state=worker_lost"


def test_process_pool_never_runs_more_than_its_workers_and_refills_freed_slots(monkeypatch):
    Child.registry = []
    source = Queue()
    source.add("process", 5)
    source.add("acquire", 2)
    handlers = {}
    monkeypatch.setattr(
        process.signal, "signal", lambda number, handler: handlers.update({number: handler})
    )
    configuration = SimpleNamespace(repository=source.repository)
    monkeypatch.setattr(process.Configuration, "load", lambda: configuration)
    context = SimpleNamespace(Process=lambda target, args: Child(target, args))
    contexts = []
    monkeypatch.setattr(
        process.multiprocessing, "get_context", lambda method: contexts.append(method) or context
    )
    result = []
    runner = threading.Thread(target=lambda: result.append(process.main(2)))
    runner.start()
    eventually(lambda: len(Child.registry) == 2)
    time.sleep(0.5)
    assert len(Child.registry) == 2  # a full pool claims nothing
    assert sum(t["claimed_by"] is not None for t in source.tickets) == 2
    Child.registry[0].finish()
    eventually(lambda: len(Child.registry) == 3)
    Child.registry[1].finish(-9)
    eventually(lambda: len(Child.registry) == 4)
    assert all(child.target is process.run_ticket for child in Child.registry)
    assert all(t["kind"] == "process" for t in source.tickets if t["claimed_by"])
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    for child in Child.registry:
        child.finish()
    runner.join(10)
    assert result == [0] and contexts == ["spawn"]
    assert [t["claimed_by"] is not None for t in source.tickets[:5]].count(True) == 4
    assert source.tickets[5]["claimed_by"] is None


def test_process_workers_are_bounded():
    for workers in (0, 65):
        with pytest.raises(Rejection, match="invalid_process_workers"):
            process.main(workers)


# Real processes ------------------------------------------------------------------------


@pytest.mark.integration
def test_C05_C06_C07_C08_C11_P07_D01_D05_D06_B02_real_queue_process_faults(postgres):
    client = os.environ.get("STAGE1_API_IMAGE", "floatchat-stage0-wsl-dev-api:latest")
    minio = os.environ.get("STAGE1_MINIO_IMAGE", "floatchat-stage0-wsl-dev-minio:latest")
    for image in (client, minio):
        assert (
            subprocess.run(
                ["docker", "image", "inspect", image], capture_output=True, timeout=20
            ).returncode
            == 0
        ), "Prepare caches separately; never pull in offline tests"
    for database_name in ("broker_probe", "schedule_probe"):
        postgres("CREATE DATABASE " + database_name)
        migration = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--mount",
                f"type=bind,source={ROOT / 'infra'},target=/app/infra,readonly",
                "--env",
                "DATABASE_ADMIN_URL=postgresql://postgres@127.0.0.1/" + database_name,
                client,
                "alembic",
                "-c",
                "infra/alembic.ini",
                "upgrade",
                "head",
            ],
            capture_output=True,
            timeout=60,
        )
        assert migration.returncode == 0, "Disposable queue database migration failed"
    environment = {name: os.environ[name] for name in os.environ if name != "ARGOVIS_API_KEY"}
    environment.update(
        MINIO_ROOT_USER=secrets.token_hex(12), MINIO_ROOT_PASSWORD=secrets.token_hex(24)
    )
    names = []
    try:
        name = "floatchat-stage1-queue-minio-" + uuid.uuid4().hex
        names.append(name)
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--pull=never",
                "--memory=512m",
                "--network=container:" + postgres.container_name,
                "--name",
                name,
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                minio,
                "minio",
                "server",
                "/data",
            ],
            env=environment,
            capture_output=True,
            check=True,
            timeout=30,
        )
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull=never",
                "--memory=1g",
                "--network=container:" + postgres.container_name,
                "--user",
                str(os.getuid()),
                "--mount",
                f"type=bind,source={ROOT},target=/test,readonly",
                "--env",
                "INGESTION_DATABASE_URL=postgresql://postgres@127.0.0.1/broker_probe",
                "--env",
                "MINIO_ROOT_USER",
                "--env",
                "MINIO_ROOT_PASSWORD",
                "--env",
                "PYTHONPATH=/test/tests/stage1:/test/packages/core/src:/test/workers/src:/test/.venv/lib/python3.12/site-packages",
                client,
                "python",
                "/test/tests/stage1/broker_probe.py",
            ],
            env=environment,
            capture_output=True,
            timeout=450,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-5000:]
        evidence = json.loads(result.stdout)
        (ROOT / "reports/stage1-broker-evidence.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        from floatchat_core.ingestion.reporting import markdown_report

        final = next(
            item["report"]
            for item in evidence["cases"]
            if item["case"] == "C08_real_deadline_expiry"
        )
        (ROOT / "reports/stage1-ingestion-example.json").write_text(
            json.dumps(final, indent=2) + "\n"
        )
        (ROOT / "reports/stage1-ingestion-example.md").write_text(markdown_report(final))
    finally:
        for name in reversed(names):
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", name], capture_output=True, timeout=30
            )
