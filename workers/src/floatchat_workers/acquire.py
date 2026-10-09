"""Acquire process (stage1-v4): one per environment, N threads, each landing one chunk.

Every thread claims `acquire` tickets from the PostgreSQL queue and runs the same ticket
setup as the serial worker, ending in Processor.land(). The in-process UpstreamGovernor
holds the N permits (halved on HTTP 429) and hands each request the lowest free slot number,
which RequestOwner maps to advisory lock (164993423, slot); so one acquire process never
exceeds N concurrent upstream requests and a second process is bounded by the same locks.
The thread index is passed as `slot` only together with a governor; without one every
thread uses RequestOwner's default slot 1, which serializes upstream requests.

Only the governor is shared between threads. A Repository wraps one psycopg connection and is
not thread-safe, so every ticket (process_ticket) builds its own work and budget Repository,
RequestOwner and Processor, and each polling thread owns its claim connection.
"""

import signal
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from types import FrameType
from typing import Any

from floatchat_core.ingestion import transport
from floatchat_core.ingestion.numeric import Rejection

from .ingestion import Configuration, bounded_worker_memory, process_ticket
from .queue import poll, ticket_arguments, worker_name


def make_governor(slots: int) -> Any | None:
    """transport.UpstreamGovernor(slots), or None while transport lacks it (package E).

    Without a governor the threads share RequestOwner's single default slot, which
    serializes upstream requests but never exceeds the one-request bound.
    """
    constructor = getattr(transport, "UpstreamGovernor", None)
    return None if constructor is None else constructor(slots)


def work(
    configuration: Configuration, governor: Any | None, index: int, stop: threading.Event
) -> None:
    """One acquire thread: claim a ticket, land its chunk, repeat until `stop`."""

    def handle(ticket: dict[str, Any]) -> None:
        run, chunk, identifier = ticket_arguments(ticket)
        state = process_ticket(run, chunk, identifier, "acquire", governor=governor, slot=index)
        print(f"acquire ticket={identifier} state={state}", flush=True)

    poll(configuration.repository, "acquire", worker_name("acquire", index), handle, stop)


def main(slots: int) -> int:
    if not 1 <= slots <= 16:
        raise Rejection("invalid_acquire_slots")
    configuration = Configuration.load()
    repository = configuration.repository()
    try:
        declared = int(repository.environment(configuration.environment)["upstream_slots"])
    finally:
        repository.close()
    if slots > declared:
        raise Rejection("acquire_slots_exceed_environment")
    bounded_worker_memory(configuration.worker_memory_bytes)
    governor = make_governor(slots)
    stop = threading.Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with ThreadPoolExecutor(slots, thread_name_prefix="acquire") as pool:
        futures = [
            pool.submit(work, configuration, governor, index, stop) for index in range(1, slots + 1)
        ]
        # A thread that ends before `stop` died of a fault; take the whole process down so
        # the service manager restarts it rather than running with fewer slots.
        while not stop.is_set():
            done, _ = wait(futures, timeout=1, return_when=FIRST_COMPLETED)
            if done:
                stop.set()
    for future in futures:
        future.result()
    return 0
