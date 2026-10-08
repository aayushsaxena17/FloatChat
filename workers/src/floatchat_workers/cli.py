"""Internal Stage 1 commands. All upstream execution is explicit opt-in."""

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from floatchat_core.ingestion.controller import Supervisor
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import month_interval
from floatchat_core.ingestion.reporting import markdown_report, persisted_report
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.states import exit_code

from .ingestion import Configuration, live_enabled


def dispatch(authority: Authority) -> None:
    from .app import app

    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        ticket = repository.ticket(authority)
    finally:
        repository.close()
    app.send_task(
        "floatchat.ingest_chunk",
        args=[str(authority.run), str(authority.chunk), str(ticket)],
        queue=configuration.queue,
        retry=False,
    )


def scheduled_admission() -> str:
    if not live_enabled():
        return "live_ingestion_disabled"
    repository = None
    try:
        configuration = Configuration.load()
        repository = configuration.repository()
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
            repository.close()


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
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    repository = None
    try:
        configuration = Configuration.load()
        repository = configuration.repository()
        if args.command == "supervise":
            supervisor = Supervisor(repository, dispatch)
            while True:
                try:
                    supervisor.tick(repository.open_runs())
                except Rejection:
                    # Database/broker loss neither succeeds nor creates new budgets.
                    print("supervisor_recovery_required", flush=True)
                time.sleep(10)
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
