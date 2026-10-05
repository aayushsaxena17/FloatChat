"""Optional bounded snapshot reproduction. Never invoked by dev or tests."""

import argparse
import hashlib
import multiprocessing
import os
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

MAX_BYTES = 15_000_000
DEADLINE_SECONDS = 30
REAP_RESERVE_SECONDS = 0.05


def remaining(deadline: float) -> float:
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise TimeoutError("snapshot deadline exceeded")
    return budget


def transfer(
    url: str,
    temporary: str,
    expected_sha256: str,
    opener: Callable[..., Any],
    deadline: float,
    maximum_bytes: int,
    result: Connection,
) -> None:
    """Isolated I/O worker. Only the supervising parent can replace the output."""
    status = "failed"
    try:
        digest = hashlib.sha256()
        size = 0
        with open(temporary, "wb") as target:
            with opener(url, timeout=remaining(deadline)) as response:
                # read1 avoids read(n)'s repeated receives when a peer trickles bytes.
                read = getattr(response, "read1", response.read)
                while True:
                    budget = remaining(deadline)
                    raw = getattr(getattr(response, "fp", None), "raw", None)
                    transport = getattr(raw, "_sock", None)
                    if transport is not None:
                        transport.settimeout(budget)
                    chunk = read(65536)
                    remaining(deadline)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise ValueError("snapshot exceeds byte limit")
                    digest.update(chunk)
                    target.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("snapshot checksum mismatch")
        remaining(deadline)
        status = "ok"
    except TimeoutError:
        status = "deadline"
    except ValueError:
        status = "invalid"
    except Exception:
        status = "failed"
    finally:
        # Never send upstream diagnostics, URLs or response contents to the parent.
        result.send(status)
        result.close()


def download(
    url: str,
    output: Path,
    expected_sha256: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    """Download with a hard total deadline; injected openers must be spawn-picklable."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    io_deadline = deadline - min(REAP_RESERVE_SECONDS, DEADLINE_SECONDS / 4)
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("HTTPS source required")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = None
    try:
        descriptor, name = tempfile.mkstemp(dir=output.parent)
        os.close(descriptor)
        temporary = Path(name)
        worker = context.Process(
            target=transfer,
            args=(url, name, expected_sha256, opener, io_deadline, MAX_BYTES, sender),
        )
        worker.start()
        sender.close()
        if not receiver.poll(remaining(io_deadline)):
            raise TimeoutError("snapshot deadline exceeded")
        try:
            status = receiver.recv()
        except EOFError:
            raise OSError("snapshot worker failed") from None
        worker.join(max(0, io_deadline - time.monotonic()))
        if worker.is_alive():
            raise TimeoutError("snapshot deadline exceeded")
        remaining(deadline)
        if status == "deadline":
            raise TimeoutError("snapshot deadline exceeded")
        if status == "invalid":
            raise ValueError("snapshot exceeds byte limit or checksum mismatch")
        if status != "ok" or worker.exitcode != 0:
            raise OSError("snapshot download failed")
        os.replace(temporary, output)
        temporary = None
    finally:
        if worker is not None and worker.pid is not None:
            if worker.is_alive():
                # Kill/reap before unlink so no worker can keep writing a partial file.
                worker.kill()
            worker.join()
            worker.close()
        receiver.close()
        sender.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url",
        required=True,
        help="Owner-provided public HTTPS URL for the exact prototype snapshot",
    )
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, default=Path(".cache/prototype.parquet"))
    args = parser.parse_args()
    download(args.source_url, args.output, args.sha256)
