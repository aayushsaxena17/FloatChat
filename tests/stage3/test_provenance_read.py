"""Provenance of the read endpoints (ADR-0064): no plan, no coverage, same versions and digests."""

import uuid
from datetime import UTC, datetime

from floatchat_core.query import provenance
from floatchat_core.query.catalogue import EnvironmentInfo
from floatchat_core.query.geography import resolve_geography
from floatchat_core.query.plan import NamedRegion

ENVIRONMENT = EnvironmentInfo(
    uuid.UUID("00000000-0000-4000-8000-000000000003"),
    "dev",
    "acceptance",
    datetime(2025, 4, 1, tzinfo=UTC),
    2,
    uuid.UUID("00000000-0000-4000-8000-000000000001"),
    datetime(2025, 4, 1, 1, tzinfo=UTC),
    datetime(2025, 4, 1, 0, 10, tzinfo=UTC),
    datetime(2025, 4, 1, 0, 50, tzinfo=UTC),
)


def _read(**overrides):
    arguments = {
        "environment": ENVIRONMENT,
        "geography": None,
        "qc_policy": None,
        "execution": {"source": "postgresql", "rows": 1},
        "rows": [["5900001"]],
        "application_commit": "abc123",
        "transformation": "floats",
    }
    arguments.update(overrides)
    return provenance.build_read(**arguments)


def test_read_provenance_has_the_section_17_fields_without_a_plan() -> None:
    record = _read()
    assert set(record) == {
        "source",
        "environment",
        "versions",
        "geography",
        "execution",
        "result_sha256",
        "application_commit",
        "transformation",
        "attribution",
    }
    assert record["source"] == "argovis" and record["geography"] is None
    assert record["application_commit"] == "abc123"
    assert record["result_sha256"] == provenance.result_sha256([["5900001"]])
    assert "10.17882/42182" in record["attribution"]["argo"]
    assert "JTECH-D-19-0041.1" in record["attribution"]["argovis"]


def test_environment_timestamps_are_described() -> None:
    environment = _read()["environment"]
    assert environment["latest_run"] == "00000000-0000-4000-8000-000000000001"
    assert environment["ingested_at"] == "2025-04-01T01:00:00Z"
    assert environment["source_retrieved"] == {
        "start": "2025-04-01T00:10:00Z",
        "end": "2025-04-01T00:50:00Z",
    }
    assert environment["hot_tier"] == {
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-04-01T00:00:00Z",
    }


def test_single_raw_input_gives_an_equal_bounded_retrieval_window() -> None:
    moment = datetime(2025, 4, 1, 0, 10, tzinfo=UTC)
    one = EnvironmentInfo(ENVIRONMENT.id, "one", "normal", None, 1, None, moment, moment, moment)
    assert one.describe()["source_retrieved"] == {
        "start": "2025-04-01T00:10:00Z",
        "end": "2025-04-01T00:10:00Z",
    }


def test_environment_without_a_completed_run_describes_nulls() -> None:
    bare = EnvironmentInfo(ENVIRONMENT.id, "empty", "normal", None, 0)
    described = bare.describe()
    assert described["reference_time"] is None and described["hot_tier"] is None
    assert described["latest_run"] is None and described["ingested_at"] is None
    assert described["source_retrieved"] is None


def test_versions_carry_the_policy_and_region_only_when_given() -> None:
    plain = _read()["versions"]
    assert plain["mapping"] == "argovis-core-v1" and plain["plan_schema"] == "stage2-plan-v1"
    assert "qc_policy" not in plain and "region" not in plain
    region = resolve_geography(NamedRegion(kind="named_region", value="Arabian Sea"))
    rich = _read(geography=region, qc_policy="raw")["versions"]
    assert rich["qc_policy"] == "qc-policy-v1/raw"
    assert rich["region"]["name"] == "Arabian Sea" and len(rich["region"]["sha256"]) == 64
    assert _read(geography=region)["geography"]["kind"] == "named_region"


def test_query_provenance_shares_the_builders() -> None:
    # The same attribution and version table serve POST /v1/query (no divergence between reads
    # and plans).
    assert provenance.ATTRIBUTION["argo"].startswith("Argo (2000)")
