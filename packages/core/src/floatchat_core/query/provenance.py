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
    versions: dict[str, Any] = {
        "mapping": MAPPINGS[SOURCE],
        "hash": "scientific-json-v2",
        "qc": "core-good-v1",
        "qc_policy": f"{POLICY_VERSION}/{plan.qc_policy}",
        "geometry": GEOMETRY_VERSION,
        "schema": SCHEMA_VERSION,
        "plan_schema": PLAN_SCHEMA,
    }
    if geography.region is not None:
        versions["region"] = {
            "name": geography.region.name,
            "version": geography.region.version,
            "sha256": geography.region.sha256,
        }
    return {
        "source": SOURCE,
        "environment": environment.describe(),
        "versions": versions,
        "geography": geography.describe(),
        "coverage": coverage.describe(),
        "execution": execution,
        "plan_sha256": plan.plan_sha256,
        "result_sha256": result_sha256(rows),
        "application_commit": application_commit,
        "transformation": transformation,
        "attribution": {
            "argo": "Argo (2000). Argo float data and metadata from Global Data Assembly Centre "
            "(Argo GDAC). SEANOE. https://doi.org/10.17882/42182",
            "argovis": "Tucker, Giglio, Scanderbeg and Shen (2020), Argovis, "
            "https://doi.org/10.1175/JTECH-D-19-0041.1",
        },
    }
