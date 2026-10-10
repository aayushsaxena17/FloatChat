"""Provenance object attached to every result (PRD section 17; plan section 5.4)."""

import hashlib
import json
from typing import Any

from ..ingestion.parquet import SCHEMA_VERSION
from ..ingestion.planning import GEOMETRY_VERSION, MAPPINGS
from .catalogue import Coverage, EnvironmentInfo
from .geography import ResolvedGeography
from .plan import PLAN_SCHEMA, QueryPlan
from .policy import POLICY_VERSION

SOURCE = "argovis"


def result_sha256(rows: list[list[Any]]) -> str:
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


ATTRIBUTION = {
    "argo": "Argo (2000). Argo float data and metadata from Global Data Assembly Centre "
    "(Argo GDAC). SEANOE. https://doi.org/10.17882/42182",
    "argovis": "Tucker, Giglio, Scanderbeg and Shen (2020), Argovis, "
    "https://doi.org/10.1175/JTECH-D-19-0041.1",
}


def _versions(qc_policy: str | None, geography: ResolvedGeography | None) -> dict[str, Any]:
    versions: dict[str, Any] = {
        "mapping": MAPPINGS[SOURCE],
        "hash": "scientific-json-v2",
        "qc": "core-good-v1",
        "geometry": GEOMETRY_VERSION,
        "schema": SCHEMA_VERSION,
        "plan_schema": PLAN_SCHEMA,
    }
    if qc_policy is not None:
        versions["qc_policy"] = f"{POLICY_VERSION}/{qc_policy}"
    if geography is not None and geography.region is not None:
        versions["region"] = {
            "name": geography.region.name,
            "version": geography.region.version,
            "sha256": geography.region.sha256,
        }
    return versions


def build_read(
    *,
    environment: EnvironmentInfo,
    geography: ResolvedGeography | None,
    qc_policy: str | None,
    execution: dict[str, Any],
    rows: list[list[Any]],
    application_commit: str,
    transformation: str,
) -> dict[str, Any]:
    """Provenance of a read endpoint (ADR-0064): no plan, no coverage resolution.

    The reads answer from PostgreSQL only; the run identifiers in ``execution`` name the
    scientific runs whose rows were returned, when the result carries them.
    """
    return {
        "source": SOURCE,
        "environment": environment.describe(),
        "versions": _versions(qc_policy, geography),
        "geography": None if geography is None else geography.describe(),
        "execution": execution,
        "result_sha256": result_sha256(rows),
        "application_commit": application_commit,
        "transformation": transformation,
        "attribution": dict(ATTRIBUTION),
    }


def build(
    *,
    plan: QueryPlan,
    environment: EnvironmentInfo,
    geography: ResolvedGeography,
    coverage: Coverage,
    execution: dict[str, Any],
    rows: list[list[Any]],
    application_commit: str,
    transformation: str,
) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "environment": environment.describe(),
        "versions": _versions(plan.qc_policy, geography),
        "geography": geography.describe(),
        "coverage": coverage.describe(),
        "execution": execution,
        "plan_sha256": plan.plan_sha256,
        "result_sha256": result_sha256(rows),
        "application_commit": application_commit,
        "transformation": transformation,
        "attribution": dict(ATTRIBUTION),
    }
