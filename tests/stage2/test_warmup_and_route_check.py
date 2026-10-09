"""Stage 2 fixes: cache warm-up, the cold-fill retry, the start-up hook, the route check."""

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from floatchat_core.ingestion.objects import CatalogueRecord
from floatchat_core.query.cache import PartCache
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.router import QueryService

ROOT = Path(__file__).resolve().parents[2]


def _payloads(count: int) -> dict[str, bytes]:
    return {
        hashlib.sha256(bytes([index]) * 64).hexdigest(): bytes([index]) * 64
        for index in range(count)
    }


def _record(digest: str, month: str, generation: int) -> CatalogueRecord:
    return CatalogueRecord(
        uuid.uuid4(),
        uuid.uuid4(),
        f"argovis/core/{month}/60:10/indian-ocean-v1/argovis-core-v1/scientific-json-v2",
        generation,
        1,
        "active",
        True,
        True,
        "indian-ocean-v1",
        "core-parquet-v1",
        f"normalised/sha256/{digest}.parquet",
        digest,
        64,
        "part",
        generation,
    )


class FakeCatalogue:
    def __init__(self, parts: list[CatalogueRecord], *, environment: bool = True) -> None:
        self.parts = parts
        self.has_environment = environment
        self.engine = None

    def environment(self) -> Any:
        if not self.has_environment:
            raise QueryError("coverage_missing")
        return SimpleNamespace(id=uuid.uuid4(), name="fake")

    def active_parts(self, environment_id: uuid.UUID) -> tuple[CatalogueRecord, ...]:
        return tuple(self.parts)


def test_fill_reports_fetched_and_reused_parts(tmp_path: Path) -> None:
    payloads = _payloads(4)
    calls: list[str] = []

    def fetch(key: str, byte_count: int) -> bytes:
        calls.append(key)
        return payloads[key.split("/")[-1].split(".")[0]]

    cache = PartCache(tmp_path / "cache", 10_000, fetch)
    items = [(f"normalised/sha256/{d}.parquet", d, 64) for d in payloads]
    first = cache.fill(items, workers=2, deadline_seconds=5)
    assert (first.fetched, first.reused, first.fetched_bytes) == (4, 0, 256)
    assert [p.name for p in first.paths] == [d + ".parquet" for d in payloads]
    second = cache.fill(items, workers=2, deadline_seconds=5)
    assert (second.fetched, second.reused) == (0, 4) and len(calls) == 4
    assert cache.paths(items) == second.paths


def test_warm_cache_fills_newest_months_within_the_budget(tmp_path: Path) -> None:
    payloads = _payloads(3)
    digests = list(payloads)
    parts = [
        _record(digests[0], "2025-01", 1),
        _record(digests[1], "2025-03", 2),
        _record(digests[2], "2025-02", 3),
    ]
    fetched: list[str] = []

    def fetch(key: str, byte_count: int) -> bytes:
        fetched.append(key.split("/")[-1].split(".")[0])
        return payloads[key.split("/")[-1].split(".")[0]]

    # One worker keeps the fetch order observable: the newest month is filled first.
    limits = QueryLimits(object_cache_bytes=1024 * 1024, object_fetch_workers=1)
    cache = PartCache(tmp_path / "cache", limits.object_cache_bytes, fetch)
    service = QueryService(FakeCatalogue(parts), limits, cache, "test")  # type: ignore[arg-type]
    record = service.warm_cache()
    assert record["parts"] == 3 and record["warmed"] == 3 and record["fetched"] == 3
    assert fetched == [digests[1], digests[2], digests[0]]  # March, February, January
    again = service.warm_cache()
    assert again["fetched"] == 0 and again["reused"] == 3


def test_warm_cache_skips_over_budget_parts_and_empty_databases(tmp_path: Path) -> None:
    payloads = _payloads(2)
    digests = list(payloads)
    parts = [_record(digests[0], "2025-03", 1), _record(digests[1], "2025-02", 2)]

    def fetch(key: str, byte_count: int) -> bytes:
        return payloads[key.split("/")[-1].split(".")[0]]

    # A cache budget of 100 bytes holds one 64-byte part: the newest warms, the other is skipped.
    limits = QueryLimits(object_cache_bytes=1024 * 1024)
    cache = PartCache(tmp_path / "cache", limits.object_cache_bytes, fetch)
    service = QueryService(FakeCatalogue(parts), limits, cache, "test")  # type: ignore[arg-type]
    service.limits = limits.model_construct(**{**limits.model_dump(), "object_cache_bytes": 100})
    record = service.warm_cache()
    assert record["warmed"] == 1 and record["skipped_over_budget"] == 1
    empty = QueryService(FakeCatalogue([], environment=False), limits, cache, "test")  # type: ignore[arg-type]
    assert empty.warm_cache() == {"skipped": "no ingestion environment"}
    no_cache = QueryService(FakeCatalogue(parts), limits, None, "test")  # type: ignore[arg-type]
    assert no_cache.warm_cache() == {"skipped": "no part cache configured"}


def test_cold_fill_timeout_is_retried_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from floatchat_core.query import router as router_module

    payloads = _payloads(1)
    digest = next(iter(payloads))
    part = _record(digest, "2025-01", 1)
    cache = PartCache(tmp_path / "cache", 10_000, lambda key, n: payloads[digest])
    limits = QueryLimits()
    service = QueryService(FakeCatalogue([part]), limits, cache, "test")  # type: ignore[arg-type]
    attempts: list[int] = []

    def run(statement: Any, parts: Any, members: Any, run_limits: Any, timeout: float) -> list:
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise QueryError("statement_timeout")
        return [("2025-01", 1.5, 2)]

    monkeypatch.setattr(router_module.compile_duckdb, "run", run)
    monkeypatch.setattr(
        router_module.compile_duckdb, "parts_dataset", lambda paths: ("dataset", tuple(paths))
    )
    monkeypatch.setattr(
        router_module.compile_duckdb, "members_table", lambda rows, m: SimpleNamespace(num_rows=0)
    )
    monkeypatch.setattr(service, "_rows", lambda statement: [])
    plan = router_module.validate_plan(
        {
            "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
            "geography": {"kind": "named_region", "value": "Indian Ocean"},
            "variables": ["temperature"],
            "operation": {"kind": "aggregate", "group_by": ["month"], "metrics": ["mean", "count"]},
        }
    )
    geography = router_module.resolve_geography(plan.geography)
    slot = SimpleNamespace(
        logical_key=part.logical_key, parts=(part,), state="covered", profiles=1, levels=10
    )
    coverage = SimpleNamespace(
        covered=(slot,),
        manifests={},
        estimated_levels=limits.postgres_level_budget + 1,
        estimated_profiles=1,
        object_bytes=64,
    )
    execution: dict[str, Any] = {}
    result, description = service._aggregate_operation(plan, geography, coverage, execution)  # type: ignore[arg-type]
    assert len(attempts) == 2 and execution["retried_after_cold_fill"] is True
    assert execution["objects_fetched"] == 1 and result.rows == [["2025-01", 1.5, 2]]
    # A warm fill (nothing fetched) is never retried: the second service call sees reused parts.
    attempts.clear()
    execution = {}
    with pytest.raises(QueryError) as failure:
        service._aggregate_operation(plan, geography, coverage, execution)  # type: ignore[arg-type]
    assert failure.value.code == "statement_timeout" and len(attempts) == 1
    assert "retried_after_cold_fill" not in execution


def test_start_warmup_runs_in_the_background_and_tolerates_missing_service(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from floatchat_api.query_api import QueryRuntime

    monkeypatch.delenv("QUERY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    runtime = QueryRuntime()
    with caplog.at_level(logging.INFO, logger="floatchat.api"):
        thread = runtime.start_warmup()
        assert thread is not None
        thread.join(timeout=10)
    records = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    assert any(
        r.get("event") == "warm_cache" and r.get("skipped") == "service_unavailable"
        for r in records
    )

    class Service:
        def warm_cache(self) -> dict[str, Any]:
            return {"warmed": 2, "fetched": 2}

    runtime = QueryRuntime(service=Service())  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger="floatchat.api"):
        thread = runtime.start_warmup()
        assert thread is not None
        thread.join(timeout=10)
    assert any('"warmed": 2' in r.message for r in caplog.records)
    runtime.limits = QueryLimits(warm_cache_on_start=False)
    assert runtime.start_warmup() is None


def test_app_lifespan_starts_the_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from floatchat_api.main import create_app

    started: list[str] = []

    class Service:
        def warm_cache(self) -> dict[str, Any]:
            started.append("warm")
            return {"warmed": 0}

        def parameters(self) -> dict[str, Any]:
            return {"plan_schema": "stage2-plan-v1"}

    with TestClient(create_app(query_service=Service())) as client:  # type: ignore[arg-type]
        assert client.get("/v1/health/live").status_code == 200
        deadline = time.monotonic() + 10
        while not started and time.monotonic() < deadline:
            time.sleep(0.05)
    assert started == ["warm"]


def test_route_check_comparison_and_rendering() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stage2_route_check", ROOT / "scripts/stage2_route_check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    same = module.compare_rows([["2025-01", 1.0, 3]], [["2025-01", 1.0 + 1e-12, 3]])
    assert same["agree"] and same["max_rel"] < 1e-9
    assert not module.compare_rows([["a", 1.0]], [["a", 1.1]])["agree"]
    assert not module.compare_rows([["a", 1.0]], [["b", 1.0]])["agree"]
    assert not module.compare_rows([["a", 1.0]], [])["agree"]
    assert module.compare_rows([["a", None]], [["a", None]])["agree"]
    report = {
        "date": "2026-10-09",
        "git_head": "abc",
        "container": "api",
        "rel_tol": 1e-9,
        "abs_tol": 1e-9,
        "dataset": None,
        "plans": [
            {
                "label": "D01",
                "status": "ok",
                "rows": 3,
                "estimated_levels": 10,
                "postgresql_ms": 5.0,
                "duckdb_ms": 2.0,
                "max_rel": 1e-15,
            },
            {"label": "D02", "status": "mismatch", "reason": "row 0 column 1: 1.0 != 2.0"},
        ],
        "total": 2,
        "agreeing": 1,
        "pass": False,
    }
    text = module.render_markdown(report)
    assert "| D01 | 10 | 3 | 5.0 | 2.0 | 1.00e-15 | ok |" in text
    assert "**FAIL** (1 of 2 plans agree)" in text and "D02: row 0 column 1" in text
    plans = module.duckdb_plans()
    assert len(plans) == 10 and all(p["expected_route"] == "duckdb" for p in plans)
    assert datetime.now(UTC).year >= 2026


def test_route_check_dependencies_exist() -> None:
    """The check runs only on demand; a rename of what it imports must fail here, not there."""
    from floatchat_api import query_api
    from floatchat_core.query import cache, catalogue, router

    assert callable(query_api.object_fetcher)
    assert callable(router.QueryService.query) and callable(router.QueryService.warm_cache)
    assert callable(cache.PartCache.fill) and callable(catalogue.engine_from_url)
