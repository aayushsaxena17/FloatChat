"""The result and coverage memo (ADR-0067): hits, dataset-version keys, bounds, isolation."""

import uuid
from datetime import UTC, datetime

from floatchat_core.query.catalogue import EnvironmentInfo
from floatchat_core.query.memo import Memo, dataset_version


def environment(run: str | None, completed: int) -> EnvironmentInfo:
    return EnvironmentInfo(
        uuid.UUID("00000000-0000-4000-8000-000000000003"),
        "dev",
        "acceptance",
        datetime(2025, 4, 1, tzinfo=UTC),
        completed,
        None if run is None else uuid.UUID(run),
    )


RUN_A = "00000000-0000-4000-8000-00000000000a"
RUN_B = "00000000-0000-4000-8000-00000000000b"


def test_hit_returns_an_independent_copy() -> None:
    memo = Memo(4, 10_000)
    value = {"execution": {"source": "duckdb"}, "rows": [[1, 2]]}
    memo.put("k", value)
    value["rows"].append([3, 4])  # the caller's later edits do not reach the store
    first = memo.get("k")
    assert first == {"execution": {"source": "duckdb"}, "rows": [[1, 2]]}
    first["execution"]["cached"] = True  # nor do edits to a returned copy
    assert memo.get("k") == {"execution": {"source": "duckdb"}, "rows": [[1, 2]]}
    assert memo.get("missing") is None and (memo.hits, memo.misses) == (2, 1)


def test_a_new_completed_run_changes_the_key() -> None:
    before = dataset_version(environment(RUN_A, 1))
    assert before == dataset_version(environment(RUN_A, 1))
    assert before != dataset_version(environment(RUN_B, 2))
    assert before != dataset_version(environment(RUN_A, 2))
    assert dataset_version(environment(None, 0))[1] is None
    memo = Memo(4, 10_000)
    memo.put(("query", before, "plan"), {"v": 1})
    assert memo.get(("query", dataset_version(environment(RUN_B, 2)), "plan")) is None


def test_entry_and_byte_bounds_evict_least_recently_used() -> None:
    memo = Memo(2, 10_000)
    memo.put("a", 1)
    memo.put("b", 2)
    assert memo.get("a") == 1  # a becomes most recent
    memo.put("c", 3)
    assert memo.get("b") is None and memo.get("a") == 1 and memo.get("c") == 3
    small = Memo(10, 100)
    small.put("x", "y" * 60)
    small.put("z", "w" * 60)
    assert len(small) == 1 and small.get("z") is not None and small.bytes <= 100
    small.put("huge", "q" * 500)  # larger than the whole bound: not stored, nothing evicted
    assert small.get("huge") is None and small.get("z") is not None
    assert Memo(0, 100).get("anything") is None
    disabled = Memo(0, 100)
    disabled.put("k", 1)
    assert len(disabled) == 0
