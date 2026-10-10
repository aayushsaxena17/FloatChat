"""Content-addressed cache of verified Parquet parts (ADR-0058).

A part is served only after its bytes matched the catalogue's length and SHA-256; files are
written atomically and evicted least-recently-used above the configured size.
"""

import hashlib
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path

from .errors import QueryError

OBJECT_KEY = re.compile(r"^normalised/sha256/([0-9a-f]{64})\.parquet$")
Fetch = Callable[[str, int], bytes]


@dataclass(frozen=True)
class Fill:
    """Outcome of one cache fill: every path verified, counts of fetched and reused parts."""

    paths: list[Path]
    fetched: int
    fetched_bytes: int
    reused: int
    seconds: float


class PartCache:
    def __init__(self, directory: Path, max_bytes: int, fetch: Fetch) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self.fetch = fetch
        self.lock = threading.Lock()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, sha256: str) -> Path:
        return self.directory / (sha256 + ".parquet")

    def path(self, object_key: str, sha256: str, byte_count: int) -> Path:
        """The verified local file for a catalogue part, fetching and verifying if absent."""
        return self._resolve(object_key, sha256, byte_count)[0]

    def _resolve(self, object_key: str, sha256: str, byte_count: int) -> tuple[Path, bool]:
        """The verified file and whether this call fetched it (False: reused from the cache)."""
        match = OBJECT_KEY.fullmatch(object_key)
        if match is None or match.group(1) != sha256:
            raise QueryError("execution_failed", message="Catalogue object key is malformed.")
        target = self._path(sha256)
        try:
            if target.stat().st_size == byte_count:
                os.utime(target)
                return target, False
        except FileNotFoundError:
            pass
        payload = self.fetch(object_key, byte_count)
        if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != sha256:
            raise QueryError("execution_failed", message="Object bytes failed verification.")
        with self.lock:
            descriptor, temporary = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, target)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
            self._evict(keep=target)
        return target, True

    def _evict(self, *, keep: Path) -> None:
        """Least-recently-used eviction above the bound; the part just stored always survives."""
        files = [
            path
            for path in self.directory.iterdir()
            if path.suffix == ".parquet" and path.is_file() and path != keep
        ]
        total = keep.stat().st_size + sum(path.stat().st_size for path in files)
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if total <= self.max_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

    def fill(
        self,
        items: Sequence[tuple[str, str, int]],
        *,
        workers: int = 4,
        deadline_seconds: float = 120.0,
    ) -> Fill:
        """Verified local files for several parts, fetched in parallel under one time budget."""
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [
                pool.submit(self._resolve, key, sha256, byte_count)
                for key, sha256, byte_count in items
            ]
            paths: list[Path] = []
            fetched = fetched_bytes = reused = 0
            for future, (_key, _sha256, byte_count) in zip(futures, items, strict=True):
                remaining = deadline_seconds - (time.monotonic() - started)
                try:
                    path, was_fetched = future.result(timeout=max(0.0, remaining))
                except FutureTimeout:
                    for pending in futures:
                        pending.cancel()
                    raise QueryError(
                        "execution_failed", message="Object fetch exceeded its time budget."
                    ) from None
                paths.append(path)
                if was_fetched:
                    fetched += 1
                    fetched_bytes += byte_count
                else:
                    reused += 1
        return Fill(paths, fetched, fetched_bytes, reused, round(time.monotonic() - started, 3))

    def paths(
        self,
        items: Sequence[tuple[str, str, int]],
        *,
        workers: int = 4,
        deadline_seconds: float = 120.0,
    ) -> list[Path]:
        return self.fill(items, workers=workers, deadline_seconds=deadline_seconds).paths

    def size(self) -> int:
        return sum(
            path.stat().st_size
            for path in self.directory.iterdir()
            if path.suffix == ".parquet" and path.is_file()
        )
