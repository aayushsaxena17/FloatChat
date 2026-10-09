"""The committed OpenAPI file is the live schema, and the surface is the planned one (W4/W5)."""

import json
from pathlib import Path
from typing import Any

from floatchat_api.main import create_app

COMMITTED = Path(__file__).resolve().parents[2] / "apps/api/openapi.json"
PATHS = {
    "/v1/health/live",
    "/v1/health/ready",
    "/v1/catalog/parameters",
    "/v1/catalog/coverage",
    "/v1/floats",
    "/v1/floats/{platform_number}",
    "/v1/profiles",
    "/v1/profiles/{profile_id}",
    "/v1/query",
}
FORBIDDEN = {"sql", "query_sql"}
METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def schema() -> dict[str, Any]:
    return create_app().openapi()


def test_committed_file_equals_the_live_schema() -> None:
    expected = json.dumps(schema(), indent=2, sort_keys=True) + "\n"
    assert COMMITTED.read_text(encoding="utf-8") == expected, (
        "run: uv run --all-packages --frozen python scripts/export_openapi.py"
    )


def test_declares_exactly_the_planned_paths() -> None:
    assert set(schema()["paths"]) == PATHS
    assert set(json.loads(COMMITTED.read_text(encoding="utf-8"))["paths"]) == PATHS


def test_methods_are_the_planned_ones() -> None:
    operations = {
        path: {method for method in item if method in METHODS}
        for path, item in schema()["paths"].items()
    }
    assert operations.pop("/v1/query") == {"post"}
    assert all(methods == {"get"} for methods in operations.values())


def _property_names(node: Any) -> set[str]:
    """Every property name declared anywhere below ``node`` (nested schemas included)."""
    names: set[str] = set()
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in properties)
        for value in node.values():
            names |= _property_names(value)
    elif isinstance(node, list):
        for value in node:
            names |= _property_names(value)
    return names


def test_no_raw_sql_in_any_parameter_or_body_field() -> None:
    document = schema()
    parameters = {
        parameter["name"].lower()
        for item in document["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict)
        for parameter in operation.get("parameters", [])
    }
    assert not parameters & FORBIDDEN
    # Request bodies, and every component schema they or a response reference.
    fields = {name.lower() for name in _property_names(document["components"]["schemas"])}
    assert not fields & FORBIDDEN
    bodies = [
        operation["requestBody"]
        for item in document["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict) and "requestBody" in operation
    ]
    assert bodies
    assert not {name.lower() for name in _property_names(bodies)} & FORBIDDEN
    # The plan document is a structured description, never a statement.
    assert not any(
        "sql" in name.lower()
        for name in _property_names(document["components"]["schemas"]["QueryRequest"])
    )
