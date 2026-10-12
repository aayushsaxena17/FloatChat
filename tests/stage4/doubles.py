"""Stage 4 doubles shared by the fixtures and the tests (importable, unlike a conftest)."""

from datetime import UTC, datetime
from typing import Any

from floatchat_core.llm.config import LlmSettings
from floatchat_core.llm.ledger import MemoryLedger
from floatchat_core.llm.offline import OfflineProvider
from floatchat_core.llm.policy import ResilientProvider
from floatchat_core.query.errors import QueryError
from floatchat_core.query.plan import validate_plan
from floatchat_core.query.regions import load_regions

REFERENCE_TIME = "2025-04-01T00:00:00Z"
ENVIRONMENT = {
    "id": "00000000-0000-4000-8000-000000000003",
    "name": "dev",
    "mode": "dev",
    "reference_time": REFERENCE_TIME,
    "completed_runs": 1,
    "hot_tier": {"start": "2025-01-01T00:00:00Z", "end": REFERENCE_TIME},
    "postgresql_window": {"start": "2024-04-01T00:00:00Z", "end": REFERENCE_TIME},
}


class EngineDouble:
    """What the chat calls on the query service: parameters, environment and query."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure: QueryError | None = None

    def parameters(self) -> dict[str, Any]:
        return {"geography": {"named_region": [record.public() for record in load_regions()]}}

    def environment_info(self) -> dict[str, Any]:
        return dict(ENVIRONMENT)

    def query(self, payload: Any) -> dict[str, Any]:
        self.calls.append(payload)
        plan = validate_plan(payload)
        if self.failure is not None:
            raise self.failure
        canonical = plan.canonical()
        operation = plan.operation.model_dump()
        if operation["kind"] == "aggregate":
            columns = [
                {"name": "month", "type": "string", "unit": None},
                {"name": "temperature_mean", "type": "number", "unit": "degree_C"},
                {"name": "temperature_count", "type": "integer", "unit": None},
            ]
            rows = [["2025-01", 27.123, 12], ["2025-02", 27.9, 15], ["2025-03", 28.5, 9]]
        else:
            columns = [
                {"name": "platform_number", "type": "string", "unit": None},
                {"name": "observed_at", "type": "timestamp", "unit": None},
                {"name": "longitude", "type": "number", "unit": "degrees_east"},
                {"name": "latitude", "type": "number", "unit": "degrees_north"},
            ]
            rows = [["5900001", "2025-01-10T00:00:00Z", 65.0, 15.0]]
        return {
            "plan": canonical,
            "result": {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "missing_value_policy": "null",
                "non_finite_values": 0,
            },
            "next_cursor": None,
            "chart": None,
            "coverage": {
                "requested": canonical["time_range"],
                "months": ["2025-01"],
                "tiles": [],
                "slots_total": 6,
                "slots_covered": 6,
                "slots_empty_verified": 0,
                "slots_missing": 0,
                "missing": [],
                "estimated_profiles": 36,
                "estimated_levels": 360,
                "partial": False,
            },
            "partial": False,
            "missing": [],
            "execution": {"source": "duckdb", "elapsed_ms": 12.0, "rows": len(rows)},
            "interpretation": {
                "time_range": canonical["time_range"],
                "geography": {"kind": "named_region", "name": "Arabian Sea"},
                "depth_dbar": None,
                "variables": list(plan.ordered_variables),
                "qc_policy": {"name": plan.qc_policy, "version": "qc-policy-v1"},
                "operation": operation,
                "presentation": plan.presentation.model_dump(),
                "transformation": "monthly means (test double)",
            },
            "provenance": {
                "source": "argovis",
                "environment": ENVIRONMENT,
                "versions": {"plan_schema": "stage2-plan-v1"},
                "execution": {"source": "duckdb"},
                "result_sha256": "0" * 64,
                "application_commit": "test",
                "transformation": "monthly means (test double)",
                "attribution": {"argo": "https://doi.org/10.17882/42182"},
            },
        }


def offline_provider(ledger: MemoryLedger | None = None, **overrides: Any) -> ResilientProvider:
    settings = LlmSettings(provider="offline", **overrides)
    return ResilientProvider(
        OfflineProvider(),
        settings,
        ledger or MemoryLedger(),
        clock=lambda: datetime(2026, 10, 12, tzinfo=UTC),
    )
