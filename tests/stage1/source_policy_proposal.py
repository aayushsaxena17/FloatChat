"""Test-only S1-SOURCE-2 oracle. Never imported by ingestion or capture code."""

import json

from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection

VERSION = "S1-SOURCE-2-PROPOSED-INACTIVE"
ROLES = ("inventory_before", "profile", "inventory_after")


def empty_delivery(responses, *, deployed_compatible=False):
    if not deployed_compatible or len(responses) != 3:
        return False
    selections = []
    statuses = []
    for role, value in zip(ROLES, responses, strict=True):
        fields = {
            "parameters",
            "role",
            "path",
            "complete_framing",
            "compressed_bytes",
            "body",
            "content_type",
            "status",
        }
        if (
            not isinstance(value, dict)
            or not fields <= value.keys()
            or not isinstance(value["parameters"], dict)
            or type(value["body"]) is not bytes
            or type(value["content_type"]) is not str
            or len(value["content_type"]) > 128
            or type(value["status"]) is not int
        ):
            return False
        parameters = value["parameters"]
        required = {"startDate", "endDate", "polygon"} | ({"data"} if role == "profile" else set())
        if (
            value["role"] != role
            or value["path"] != "/argo"
            or set(parameters) != required
            or (role == "profile" and parameters["data"] != "all")
            or value["complete_framing"] is not True
            or type(value["compressed_bytes"]) is not int
            or not 0 <= value["compressed_bytes"] <= 32 * 1024**2
            or not len(value["body"]) <= 128 * 1024**2
            or value["content_type"].lower()
            not in ("application/json", "application/json; charset=utf-8")
        ):
            return False
        if any(type(v) is not str or not v for v in parameters.values()):
            return False
        try:
            content = json.loads(value["body"])
        except (ValueError, UnicodeError):
            return False
        if content != [] or value["status"] not in (200, 404):
            return False
        selections.append({k: parameters[k] for k in ("startDate", "endDate", "polygon")})
        statuses.append(value["status"])
    return selections[0] == selections[1] == selections[2] and len(set(statuses)) == 1


def exclusion(profile, selections, raw_sha256, metadata):
    if (
        profile.get("data_warning") != ["degenerate_levels"]
        or not profile.get("_id")
        or not selections
        or len(raw_sha256) != 64
        or any(c not in "0123456789abcdef" for c in raw_sha256)
    ):
        raise ValueError("whole_chunk_quarantine")
    # Test-only candidate: validate the full current schema with only the known
    # warning removed. This does not bypass production's strict warning policy.
    try:
        mapped = map_profile({**profile, "data_warning": []}, metadata, CanonicalBudget())
    except Rejection:
        raise ValueError("whole_chunk_quarantine") from None
    return {
        "source_id": profile["_id"],
        "outcome": "profile_excluded_source_loss",
        "selections": selections,
        "raw_sha256": raw_sha256,
        "warning": "degenerate_levels",
        "returned_levels": len(mapped.levels),
        "lost_input_levels": None,
        "lost_input_levels_known": False,
        "scientific_measurements_accepted": False,
        "previous_science_deletion_authorized": False,
    }
