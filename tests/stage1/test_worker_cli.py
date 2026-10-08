import uuid
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Authority
from floatchat_workers import cli, ingestion
from floatchat_workers.app import app
from floatchat_workers.scheduler import SingleScheduler


def test_D01_Beat_lazy_banner_has_no_configuration_lock_or_dispatch(monkeypatch):
    monkeypatch.setattr(
        ingestion.Configuration, "load", lambda: pytest.fail("Lazy banner loaded configuration")
    )
    scheduler = SingleScheduler(app=app, lazy=True, schedule_filename="unused-banner-file")
    assert scheduler.repository is None and "unused-banner-file" in scheduler.info
    with pytest.raises(Rejection, match="beat_scheduler_not_initialized"):
        scheduler.tick()
    scheduler.close()
    scheduler.close()


def test_B03_D01_tasks_have_no_automatic_retry_and_utc_schedule():
    worker = app.tasks["floatchat.ingest_chunk"]
    scheduled = app.tasks["floatchat.schedule_ingestion"]
    assert worker.max_retries == scheduled.max_retries == 0
    assert not worker.autoretry_for and not scheduled.autoretry_for
    assert worker.ignore_result and worker.acks_late
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.timezone == "UTC" and app.conf.enable_utc
    schedule = app.conf.beat_schedule["stage1-utc-daily"]["schedule"]
    assert schedule.hour == {2} and schedule.minute == {0}


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


def test_C10_dispatch_carries_only_durable_ids_and_no_broker_retry(monkeypatch):
    authority = Authority(uuid.uuid4(), uuid.uuid4(), 1, 2)
    ticket = uuid.uuid4()

    class Repository:
        def ticket(self, value):
            assert value == authority
            return ticket

        def close(self):
            pass

    configuration = SimpleNamespace(repository=lambda: Repository(), queue="test-queue")
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    sent = []
    monkeypatch.setattr(app, "send_task", lambda name, **kwargs: sent.append((name, kwargs)))
    cli.dispatch(authority)
    assert sent == [
        (
            "floatchat.ingest_chunk",
            {
                "args": [str(authority.run), str(authority.chunk), str(ticket)],
                "queue": "test-queue",
                "retry": False,
            },
        )
    ]


def test_B07_unbounded_worker_is_rejected(monkeypatch):
    monkeypatch.setattr(ingestion.Path, "read_text", lambda *args, **kwargs: "max")
    with pytest.raises(Rejection, match="worker_requires_one_gib_cgroup"):
        ingestion.bounded_worker_memory()


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
