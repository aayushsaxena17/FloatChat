"""Process pool (stage1-v4): M single-use spawned workers, each publishing one landed chunk.

The parent claims `process` tickets (so an idle queue never costs an interpreter start) and
runs each in a fresh spawn-context process that exits afterwards: the semantics of
Pool(M, maxtasksperchild=1) and its bounded memory. multiprocessing.Pool itself is not used
because it never completes a task whose worker was killed (OOM kill, SIGKILL), which would
leak a slot forever. Here a lost worker frees its slot at once; its chunk lease expires and
the controller recovers the chunk under a new claim (contract 8.1).
"""

import multiprocessing
import signal
import threading
import time
from multiprocessing.context import SpawnProcess
from types import FrameType
from typing import Any

from floatchat_core.ingestion.numeric import Rejection

from .ingestion import Configuration, process_ticket
from .queue import poll, ticket_arguments, worker_name


def run_ticket(run: str, chunk: str, identifier: str) -> None:
    """Child entrypoint. process_ticket applies the memory bound and never raises."""
    state = process_ticket(run, chunk, identifier, "process")
    print(f"process ticket={identifier} state={state}", flush=True)


def reap(running: dict[str, SpawnProcess]) -> None:
    """Free the slots of finished children; a non-zero exit is process loss, not a result."""
    for identifier, child in tuple(running.items()):
        if child.is_alive():
            continue
        child.join()
        del running[identifier]
        if child.exitcode != 0:
            print(f"process ticket={identifier} state=worker_lost", flush=True)


def main(workers: int) -> int:
    if not 1 <= workers <= 64:
        raise Rejection("invalid_process_workers")
    configuration = Configuration.load()
    context = multiprocessing.get_context("spawn")
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    running: dict[str, SpawnProcess] = {}

    def ready() -> bool:
        reap(running)
        return len(running) < workers

    def handle(ticket: dict[str, Any]) -> None:
        arguments = ticket_arguments(ticket)
        child = context.Process(target=run_ticket, args=arguments)
        child.start()
        running[arguments[2]] = child

    try:
        poll(
            configuration.repository,
            "process",
            worker_name("process"),
            handle,
            stop,
            ready=ready,
        )
    finally:
        # Claimed work finishes; each child is bounded by its run deadline.
        while running:
            reap(running)
            time.sleep(0.2)
    return 0
