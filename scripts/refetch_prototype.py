"""Optional bounded snapshot reproduction. Never invoked by dev or tests."""

import argparse
import hashlib
import os
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_BYTES = 15_000_000
DEADLINE_SECONDS = 30


def download(
    url: str,
    output: Path,
    expected_sha256: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("HTTPS source required")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as target:
            temporary = Path(target.name)
            digest = hashlib.sha256()
            size = 0
            with opener(url, timeout=10) as response:
                while chunk := response.read(65536):
                    if time.monotonic() > deadline:
                        raise TimeoutError("snapshot deadline exceeded")
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("snapshot exceeds byte limit")
                    digest.update(chunk)
                    target.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("snapshot checksum mismatch")
        os.replace(temporary, output)
        temporary = None
    finally:
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
