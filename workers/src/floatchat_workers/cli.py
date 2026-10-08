"""Internal Stage 1 commands. All upstream execution is explicit opt-in."""

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any, cast

from floatchat_core.ingestion.controller import ControlStore, Supervisor
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import month_interval
from floatchat_core.ingestion.reporting import markdown_report, persisted_report
from floatchat_core.ingestion.repository import Authority, Repository
from floatchat_core.ingestion.states import exit_code

from .ingestion import Configuration, live_enabled
from .queue import issue


class ControlConnection:
    """The Repository as the supervisor's ControlStore (one connection, all calls delegated).

    Controller ticks call extend_unstarted_leases. Until Repository carries that method
    (package F, see the package report) this class runs the same one statement itself, then
    defers to the Repository method as soon as it exists.
    """

    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)

    def extend_unstarted_leases(self, run: uuid.UUID, epoch: int) -> int:
        method = getattr(self.repository, "extend_unstarted_leases", None)
        if method is not None:
            return int(method(run, epoch))
        with self.repository.transaction() as cursor:
            cursor.execute("SELECT app.extend_unstarted_leases(%s,%s) AS n", (run, epoch))
            return int(cursor.fetchone()["n"])


def dispatch(authority: Authority, kind: str) -> None:
    # Creating the ticket row is the dispatch: a worker claims it from the PostgreSQL queue.
    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        issue(repository, authority, kind)
    finally:
        repository.close()


def scheduled_admission() -> str:
    """One UTC-daily admission, serialized by the environment advisory lock (164993423,2)."""
    if not live_enabled():
        return "live_ingestion_disabled"
    repository = None
    locked = False
    try:
        configuration = Configuration.load()
        repository = configuration.repository()
        if repository.environment(configuration.environment)["mode"] != "normal":
            return "acceptance_schedule_disabled"
        with repository.transaction() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(164993423,2) AS acquired")
            locked = bool(cursor.fetchone()["acquired"])
        if not locked:
            return "schedule_already_running"
        result = repository.admit(
            configuration.environment,
            uuid.uuid4(),
            "normal",
            None,
            {"execution_seconds": 21600},
            scheduled=True,
            input_kind="live",
            descriptor={"live_opt_in": True},
        )
        return str(result["kind"])
    except Exception:
        return "scheduling_failed_no_sensitive_diagnostics"
    finally:
        if repository is not None:
            if locked:
                try:
                    with repository.transaction() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(164993423,2)")
                except Exception:
                    pass  # closing the session below releases the lock
            repository.close()


def schedule_exit(outcome: str) -> int:
    """Timer exit status: an expected skip is success; only real faults fail the unit."""
    if outcome == "acceptance_schedule_disabled":
        return 2
    return 5 if outcome == "scheduling_failed_no_sensitive_diagnostics" else 0


def compact_slots(repository: Any, configuration: Configuration, seconds: int) -> dict[str, int]:
    """Merge every slot that has publication parts (package F's Repository.compact per slot).

    One shared time budget; a slot a commit touched meanwhile is left for the next run.
    """
    compact = getattr(repository, "compact", None)
    if compact is None:
        raise Rejection("compact_unavailable")
    with repository.transaction(readonly_snapshot=True) as cursor:
        cursor.execute(
            "SELECT DISTINCT logical_key FROM app.committed_active_partitions "
            "WHERE environment_id=%s AND kind='part' ORDER BY logical_key",
            (configuration.environment,),
        )
        keys = [row["logical_key"] for row in cursor.fetchall()]
    totals = {"compacted": 0, "unchanged": 0, "retry_later": 0, "not_attempted": 0}
    store, deadline = configuration.store(), time.monotonic() + seconds
    for key in keys:
        if time.monotonic() >= deadline:
            totals["not_attempted"] += 1
            continue
        try:
            outcome = str(compact(configuration.environment, key, store, deadline))
            totals[outcome] = totals.get(outcome, 0) + 1
        except Rejection as error:
            if error.category != "publication_base_changed":
                raise
            totals["retry_later"] += 1
    return totals


def fixture_descriptor(value: str) -> dict[str, Any]:
    # Only the fresh tree's recorded/synthetic fixture directory is approved.
    root = Path("/home/floatchat/FloatChat-stage1/tests/fixtures/argovis").resolve(strict=True)
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size > 16 * 1024**2:
        raise Rejection("unapproved_fixture_path")
    return {
        "fixture_index": str(path),
        "fixture_root": str(root),
        "index_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Internal Stage 1 ingestion control")
    sub = result.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--mode", choices=("normal", "acceptance"), required=True)
    ingest.add_argument("--region", choices=("indian-ocean",), default="indian-ocean")
    ingest.add_argument("--from", dest="first", required=True)
    ingest.add_argument("--to", dest="last", required=True)
    inputs = ingest.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--fixture-index")
    inputs.add_argument("--replay-run", type=uuid.UUID)
    inputs.add_argument("--live-opt-in", action="store_true")
    ingest.add_argument("--request-id", type=uuid.UUID)
    ingest.add_argument("--execution-seconds", type=int, default=21600)
    for name in ("status", "report", "cancel"):
        command = sub.add_parser(name)
        command.add_argument("run_id", type=uuid.UUID)
        if name == "report":
            command.add_argument("--format", choices=("json", "markdown"), default="json")
    sub.add_parser("supervise")
    sub.add_parser("schedule")
    compact = sub.add_parser("compact")
    compact.add_argument("--seconds", type=int, default=3600)
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--slots", type=int)
    process = sub.add_parser("process")
    process.add_argument("--workers", type=int)
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    repository = None
    try:
        if args.command == "schedule":
            # Cron/systemd timer entrypoint; scheduled_admission loads its own configuration.
            outcome = scheduled_admission()
            print(outcome)
            return schedule_exit(outcome)
        configuration = Configuration.load()
        if args.command == "acquire":
            from .acquire import main as acquire_main

            return acquire_main(configuration.acquire_slots if args.slots is None else args.slots)
        if args.command == "process":
            from .process import main as process_main

            return process_main(
                configuration.process_workers if args.workers is None else args.workers
            )
        repository = configuration.repository()
        if args.command == "supervise":
            supervisor = Supervisor(cast(ControlStore, ControlConnection(repository)), dispatch)
            while True:
                try:
                    supervisor.tick(repository.open_runs())
                except Rejection:
                    # Database loss neither succeeds nor creates new budgets.
                    print("supervisor_recovery_required", flush=True)
                time.sleep(10)
        if args.command == "compact":
            if not 1 <= args.seconds <= 43200:
                raise Rejection("invalid_compaction_bound")
            print(
                json.dumps(compact_slots(repository, configuration, args.seconds), sort_keys=True)
            )
            return 0
        if args.command == "ingest":
            interval = month_interval(args.first, args.last)
            descriptor: dict[str, Any]
            if not 61 <= args.execution_seconds <= 43200:
                raise Rejection("invalid_execution_bound")
            if args.live_opt_in:
                if not live_enabled():
                    raise Rejection("live_ingestion_disabled")
                kind, descriptor = "live", {"live_opt_in": True}
            elif args.fixture_index:
                kind, descriptor = "captured", fixture_descriptor(args.fixture_index)
            else:
                repository.validate_replay(
                    configuration.environment, args.mode, interval, args.replay_run
                )
                kind, descriptor = "replay", {"predecessor_run": str(args.replay_run)}
            result = repository.admit(
                configuration.environment,
                args.request_id or uuid.uuid4(),
                args.mode,
                interval,
                {"execution_seconds": args.execution_seconds},
                input_kind=kind,
                descriptor=descriptor,
            )
            print(json.dumps(result), flush=True)
            if result["kind"] == "overlap_skip":
                return 6
            run_id = uuid.UUID(result["run_id"])
            while not repository.run(run_id)["closed"]:
                time.sleep(10)
            report = persisted_report(repository, run_id)
            return exit_code(
                report["state"],
                cancellation_affected=report["cancellation_affected_unfinished_chunks"],
            )
        if args.command == "cancel":
            state = repository.finalize(args.run_id, "operator_cancelled")
            print(state)
            report = persisted_report(repository, args.run_id)
            return exit_code(
                state, cancellation_affected=report["cancellation_affected_unfinished_chunks"]
            )
        report = persisted_report(repository, args.run_id)
        print(
            markdown_report(report)
            if args.command == "report" and args.format == "markdown"
            else json.dumps(report, default=str, sort_keys=True)
        )
        return exit_code(report["state"]) if report["closed"] else 5
    except KeyboardInterrupt:
        # Stopping a CLI/supervisor is process loss, not operator cancellation.
        return 5
    except Rejection as error:
        print(error.category)
        return 5 if error.category in ("database_failure", "database_deadline") else 2
    except Exception:
        print("ingestion_command_failed_no_sensitive_diagnostics")
        return 5
    finally:
        if repository is not None:
            repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
