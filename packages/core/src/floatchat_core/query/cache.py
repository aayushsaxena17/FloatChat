"""Content-addressed cache of verified Parquet parts (ADR-0058).

A part is served only after its bytes matched the catalogue's length and SHA-256; files are
written atomically and evicted least-recently-used above the configured size.
"""

import hashlib
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from .errors import QueryError

OBJECT_KEY = re.compile(r"^normalised/sha256/([0-9a-f]{64})\.parquet$")
Fetch = Callable[[str, int], bytes]


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
        match = OBJECT_KEY.match(object_key)
        if match is None or match.group(1) != sha256:
            raise QueryError("execution_failed", message="Catalogue object key is malformed.")
        target = self._path(sha256)
        try:
            if target.stat().st_size == byte_count:
                os.utime(target)
                return target
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
            self._evict()
        return target

    def _evict(self) -> None:
        files = [
            path
            for path in self.directory.iterdir()
            if path.suffix == ".parquet" and path.is_file()
        ]
        total = sum(path.stat().st_size for path in files)
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if total <= self.max_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

    def size(self) -> int:
        return sum(
            path.stat().st_size
            for path in self.directory.iterdir()
            if path.suffix == ".parquet" and path.is_file()
        )
