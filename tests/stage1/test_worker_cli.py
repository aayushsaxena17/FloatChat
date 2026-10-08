import importlib.util
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_workers import acquire, cli, ingestion, process

WORKERS = Path(cli.__file__).parent


def test_queue_workers_have_no_broker_app_or_scheduler_modules():
    for module in ("app", "scheduler"):
        assert importlib.util.find_spec(f"floatchat_workers.{module}") is None
    # Spelled in pieces so this guard does not itself contain the removed names.
    removed = ("cel" + "ery", "re" + "dis", "be" + "at_scheduler")
    for path in WORKERS.glob("*.py"):
        text = path.read_text().lower()
        assert not any(name in text for name in removed), path.name


def test_D02_disabled_scheduler_does_not_load_configuration_or_credential(monkeypatch):
    monkeypatch.setattr(cli, "live_enabled", lambda: False)
    monkeypatch.setattr(
        ingestion.Configuration, "load", lambda: pytest.fail("Disabled live config")
    )
    assert cli.scheduled_admission() == "live_ingestion_disabled"


def test_B05_worker_boundary_redacts_nested_exception(monkeypatch, capsys):
    def fail():
        raise RuntimeError("synthetic-private-exception-sentinel")

    monkeypatch.setattr(ingestion.Configuration, "load", fail)
    assert ingestion.process_ticket(*(str(uuid.uuid4()) for _ in range(3))) == "recovery_required"
    assert "synthetic-private" not in capsys.readouterr().out


def test_C04_complete_delivery_reads_completion_before_key_or_ticket(monkeypatch):
    run, chunk = uuid.uuid4(), uuid.uuid4()

    class Repository:
        def chunk(self, value):
            assert value == chunk
            return {"run_id": run, "state": "complete"}

        def start_worker(self, *args):
            pytest.fail("Complete work claimed again")

        def close(self):
            pass

    configuration = SimpleNamespace(repository=lambda: Repository())
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(
        ingestion, "bounded_worker_memory", lambda: pytest.fail("Complete memory check")
    )
    monkeypatch.setattr(
        ingestion, "upstream_credential", lambda: pytest.fail("Complete credential access")
    )
    assert ingestion.process_ticket(str(run), str(chunk), str(uuid.uuid4())) == "complete"


class Repository:
    """Just enough of Repository for the command layer; every call is recorded."""

    def __init__(self, **overrides):
        self.calls, self.closed = [], 0
        self.admission = {"kind": "created", "run_id": str(uuid.uuid4())}
        self.lock = True
        self.mode = "normal"
        self.slots = []
        self.__dict__.update(overrides)

    def environment(self, identifier):
        return {"mode": self.mode}

    @contextmanager
    def transaction(self, **options):
        calls = self.calls

        class Cursor:
            def execute(self, statement, parameters=None):
                calls.append(statement)

            def fetchone(self):
                return {"acquired": self.owner.lock}

            def fetchall(self):
                return [{"logical_key": key} for key in self.owner.slots]

        cursor = Cursor()
        cursor.owner = self
        yield cursor

    def admit(self, *args, **kwargs):
        self.calls.append(("admit", args, kwargs))
        if isinstance(self.admission, Exception):
            raise self.admission
        return self.admission

    def ticket(self, authority, kind="process"):
        self.calls.append(("ticket", authority, kind))
        return uuid.uuid4()

    def close(self):
        self.closed += 1


def configure(monkeypatch, repository, **fields):
    configuration = SimpleNamespace(
        repository=lambda: repository,
        environment=uuid.uuid4(),
        acquire_slots=4,
        process_workers=2,
        **fields,
    )
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(cli, "live_enabled", lambda: True)
    return configuration


@pytest.mark.parametrize("kind", ["acquire", "process"])
def test_C10_dispatch_creates_the_ticket_row_of_its_kind_and_sends_nothing(monkeypatch, kind):
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 2)
    repository = Repository()
    configure(monkeypatch, repository)
    cli.dispatch(authority, kind)
    assert repository.calls == [("ticket", authority, kind)] and repository.closed == 1


def test_C10_dispatch_failure_still_closes_its_connection(monkeypatch):
    repository = Repository()
    repository.ticket = lambda *args: (_ for _ in ()).throw(Rejection("database_failure"))
    configure(monkeypatch, repository)
    with pytest.raises(Rejection, match="database_failure"):
        cli.dispatch(Authority(uuid.uuid4(), uuid.uuid4(), 1, 2), "process")
    assert repository.closed == 1


def test_dispatch_rejects_an_unknown_kind_before_writing(monkeypatch):
    repository = Repository()
    configure(monkeypatch, repository)
    with pytest.raises(Rejection, match="invalid_ticket_kind"):
        cli.dispatch(Authority(uuid.uuid4(), uuid.uuid4(), 1, 2), "execute")
    assert repository.calls == []


def test_supervise_dispatches_through_the_ticket_queue(monkeypatch):
    repository = Repository(open_runs=lambda: ())
    configure(monkeypatch, repository)
    built = []

    class Supervisor:
        def __init__(self, store, dispatch):
            built.append((store, dispatch))

        def tick(self, runs):
            raise Rejection("database_failure")

    monkeypatch.setattr(cli, "Supervisor", Supervisor)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", sleep)
    assert cli.main(["supervise"]) == 5  # stopping the supervisor is process loss
    assert built == [(repository, cli.dispatch)] and sleeps == [10]
    assert repository.closed == 1


def test_D02_schedule_command_prints_the_outcome_and_exits_zero_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(cli, "live_enabled", lambda: False)
    monkeypatch.setattr(
        ingestion.Configuration, "load", lambda: pytest.fail("Disabled live config")
    )
    assert cli.main(["schedule"]) == 0
    assert capsys.readouterr().out.strip() == "live_ingestion_disabled"


def test_schedule_admits_once_under_the_environment_advisory_lock(monkeypatch, capsys):
    repository = Repository()
    configuration = configure(monkeypatch, repository)
    assert cli.main(["schedule"]) == 0
    assert capsys.readouterr().out.strip() == "created"
    lock = [call for call in repository.calls if isinstance(call, str)]
    assert lock == [
        "SELECT pg_try_advisory_lock(164993423,2) AS acquired",
        "SELECT pg_advisory_unlock(164993423,2)",
    ]
    (admit,) = [call for call in repository.calls if isinstance(call, tuple)]
    _, arguments, options = admit
    assert arguments[0] == configuration.environment and arguments[2] == "normal"
    assert arguments[3] is None and options["scheduled"] is True
    assert options["input_kind"] == "live" and repository.closed == 1
    # The advisory lock is taken before the admission and released after it.
    assert repository.calls.index(lock[0]) < repository.calls.index(admit)
    assert repository.calls.index(admit) < repository.calls.index(lock[1])


def test_schedule_skips_while_another_scheduler_holds_the_lock(monkeypatch, capsys):
    repository = Repository(lock=False)
    configure(monkeypatch, repository)
    assert cli.main(["schedule"]) == 0
    assert capsys.readouterr().out.strip() == "schedule_already_running"
    assert not any(isinstance(call, tuple) for call in repository.calls)  # no admission
    assert "SELECT pg_advisory_unlock(164993423,2)" not in repository.calls


def test_schedule_is_refused_in_an_acceptance_environment(monkeypatch, capsys):
    repository = Repository(mode="acceptance")
    configure(monkeypatch, repository)
    assert cli.main(["schedule"]) == 2
    assert capsys.readouterr().out.strip() == "acceptance_schedule_disabled"
    assert not any(isinstance(call, tuple) for call in repository.calls)


def test_overlap_skip_is_a_recorded_event_not_a_failed_timer_unit(monkeypatch, capsys):
    repository = Repository(admission={"kind": "overlap_skip", "event_id": str(uuid.uuid4())})
    configure(monkeypatch, repository)
    assert cli.main(["schedule"]) == 0
    assert capsys.readouterr().out.strip() == "overlap_skip"


def test_schedule_failure_is_sanitized_and_still_releases_the_lock(monkeypatch, capsys):
    repository = Repository(admission=RuntimeError("synthetic-private-sentinel"))
    configure(monkeypatch, repository)
    assert cli.main(["schedule"]) == 5
    output = capsys.readouterr().out
    assert output.strip() == "scheduling_failed_no_sensitive_diagnostics"
    assert "synthetic-private" not in output
    assert "SELECT pg_advisory_unlock(164993423,2)" in repository.calls


def test_acquire_and_process_commands_take_pool_sizes_from_arguments_or_configuration(
    monkeypatch,
):
    configure(monkeypatch, Repository())
    started = []
    monkeypatch.setattr(acquire, "main", lambda slots: started.append(("acquire", slots)) or 0)
    monkeypatch.setattr(process, "main", lambda workers: started.append(("process", workers)) or 0)
    assert cli.main(["acquire", "--slots", "3"]) == 0
    assert cli.main(["acquire"]) == 0
    assert cli.main(["process", "--workers", "6"]) == 0
    assert cli.main(["process"]) == 0
    assert cli.main(["acquire", "--slots", "0"]) == 0  # zero is passed on, then rejected
    assert started == [
        ("acquire", 3),
        ("acquire", 4),
        ("process", 6),
        ("process", 2),
        ("acquire", 0),
    ]


def test_pool_commands_do_not_hold_a_command_connection_while_they_run(monkeypatch):
    configuration = configure(monkeypatch, Repository())
    configuration.repository = lambda: pytest.fail("Pool command opened a command repository")
    monkeypatch.setattr(acquire, "main", lambda slots: 0)
    monkeypatch.setattr(process, "main", lambda workers: 0)
    assert cli.main(["acquire"]) == 0 and cli.main(["process"]) == 0


@pytest.mark.parametrize("command", [["acquire", "--slots", "0"], ["process", "--workers", "0"]])
def test_pool_command_argument_faults_exit_two_with_a_category(monkeypatch, capsys, command):
    configure(monkeypatch, Repository())
    assert cli.main(command) == 2
    assert capsys.readouterr().out.strip() in ("invalid_acquire_slots", "invalid_process_workers")


def test_compact_is_unavailable_until_publication_v4_provides_it(monkeypatch, capsys):
    repository = Repository()
    configure(monkeypatch, repository)
    assert cli.main(["compact"]) == 2
    assert capsys.readouterr().out.strip() == "compact_unavailable"
    assert repository.closed == 1


def test_compact_merges_each_slot_with_parts_and_reports_the_outcomes(monkeypatch, capsys):
    calls = []

    def compact(environment, key, store, deadline):
        calls.append((environment, key, store, deadline))
        if key == "slot-b":
            raise Rejection("publication_base_changed")
        return "unchanged" if key == "slot-c" else "compacted"

    repository = Repository(compact=compact, slots=["slot-a", "slot-b", "slot-c"])
    configuration = configure(monkeypatch, repository, store=lambda: "store")
    assert cli.main(["compact"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "compacted": 1,
        "unchanged": 1,
        "retry_later": 1,
        "not_attempted": 0,
    }
    assert [(c[0], c[1], c[2]) for c in calls] == [
        (configuration.environment, key, "store") for key in ("slot-a", "slot-b", "slot-c")
    ]
    assert "kind='part'" in repository.calls[0] and repository.closed == 1


def test_compact_stops_at_its_time_budget_and_propagates_real_faults(monkeypatch, capsys):
    clock = iter([0.0, 0.0, 99999.0, 99999.0])
    # cli.time is the real module: replace the name, not the module's clock.
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    repository = Repository(compact=lambda *args: "compacted", slots=["a", "b"])
    configure(monkeypatch, repository, store=lambda: "store")
    assert cli.main(["compact", "--seconds", "60"]) == 0
    assert json.loads(capsys.readouterr().out)["not_attempted"] == 1
    failing = Repository(
        compact=lambda *args: (_ for _ in ()).throw(Rejection("object_write_failure")),
        slots=["a"],
    )
    configure(monkeypatch, failing, store=lambda: "store")
    monkeypatch.setattr(cli, "time", SimpleNamespace(monotonic=lambda: 0.0))
    assert cli.main(["compact"]) == 2
    assert capsys.readouterr().out.strip() == "object_write_failure"


def test_compact_rejects_an_unbounded_time_budget(monkeypatch, capsys):
    configure(monkeypatch, Repository(compact=lambda *args: "compacted", slots=[]))
    assert cli.main(["compact", "--seconds", "0"]) == 2
    assert capsys.readouterr().out.strip() == "invalid_compaction_bound"


@pytest.mark.parametrize(
    "command",
    [
        ["supervise"],
        ["schedule"],
        ["compact"],
        ["acquire", "--slots", "2"],
        ["process", "--workers", "2"],
    ],
)
def test_parser_knows_every_queue_command(command):
    assert cli.parser().parse_args(command).command == command[0]


def test_T03_parser_half_open_arguments_and_excludes_reference_override():
    args = cli.parser().parse_args(
        [
            "ingest",
            "--mode",
            "acceptance",
            "--from",
            "2025-01",
            "--to",
            "2025-03",
            "--replay-run",
            str(uuid.uuid4()),
        ]
    )
    assert args.first == "2025-01" and args.last == "2025-03"
    assert not hasattr(args, "reference_time")
