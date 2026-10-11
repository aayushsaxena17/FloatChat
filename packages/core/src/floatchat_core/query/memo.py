"""Bounded in-process memo of finished query results and coverage (ADR-0067).

Not PRD section 8.4's persistent cache (Stage 5): entries live in the API process only, and every
key carries the dataset version, ``(environment id, latest completed run, completed run count)``,
so a newly completed ingestion run makes earlier entries unreachable. Values are deep-copied on
the way in and out, so a caller can never alter a stored answer.
"""

import copy
import json
import threading
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from .catalogue import EnvironmentInfo


def dataset_version(environment: EnvironmentInfo) -> tuple[str, str | None, int]:
    latest = None if environment.latest_run_id is None else str(environment.latest_run_id)
    return (str(environment.id), latest, environment.completed_runs)


class Memo:
    """Least-recently-used entries under an entry-count and an approximate byte bound."""

    def __init__(self, max_entries: int, max_bytes: int) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[Hashable, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return copy.deepcopy(entry[0])

    def put(self, key: Hashable, value: Any, size: int | None = None) -> None:
        if self.max_entries == 0:
            return
        if size is None:
            size = len(json.dumps(value, default=str, separators=(",", ":")))
        if size > self.max_bytes:
            return  # one oversized answer must not flush everything else
        stored = copy.deepcopy(value)
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= previous[1]
            self._entries[key] = (stored, size)
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                _key, (_value, evicted) = self._entries.popitem(last=False)
                self._bytes -= evicted

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def bytes(self) -> int:
        with self._lock:
            return self._bytes
