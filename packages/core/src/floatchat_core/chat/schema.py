"""The planner's structured output (plan section 4) and its translation to a plan document.

The schema is flat on purpose: no unions or references, so every provider's JSON-schema subset
accepts it. ``to_plan_document`` keeps only the keys that belong to each ``kind`` and drops
nulls; everything else is left for ``validate_plan`` to reject (the validator is the authority).
"""

from typing import Any

from ..query.plan import (
    DEPTH_BIN_SIZES,
    GROUP_KEYS,
    METRICS,
    PRESENTATIONS,
    QC_POLICIES,
    VARIABLES,
)

ESSENTIAL_FIELDS = ("time_range", "geography")
CLARIFIABLE_FIELDS = (
    "time_range",
    "geography",
    "depth_dbar",
    "variables",
    "qc_policy",
    "operation",
    "presentation",
)

_number = {"type": "number"}
_integer = {"type": "integer"}
_string = {"type": "string"}

PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["plan", "clarify", "reply", "unsupported"]},
        "reason": {"type": "string", "description": "One sentence; required for unsupported."},
        "reply": {
            "type": "string",
            "description": "One to four plain sentences; required for reply.",
        },
        "clarification": {
            "type": "object",
            "properties": {
                "missing": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(CLARIFIABLE_FIELDS)},
                },
                "question": {"type": "string"},
            },
            "required": ["missing", "question"],
        },
        "plan": {
            "type": "object",
            "properties": {
                "time_range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "UTC ISO-8601, inclusive"},
                        "end": {"type": "string", "description": "UTC ISO-8601, exclusive"},
                    },
                    "required": ["start", "end"],
                },
                "geography": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["named_region", "bbox", "point_radius"],
                        },
                        "value": {"type": "string", "description": "named_region: the name"},
                        "west": _number,
                        "south": _number,
                        "east": _number,
                        "north": _number,
                        "longitude": _number,
                        "latitude": _number,
                        "radius_km": _number,
                    },
                    "required": ["kind"],
                },
                "depth_dbar": {
                    "type": "object",
                    "properties": {"min": _number, "max": _number},
                    "required": ["min", "max"],
                },
                "variables": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(VARIABLES)},
                },
                "qc_policy": {"type": "string", "enum": list(QC_POLICIES)},
                "operation": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["profiles", "aggregate", "nearest"]},
                        "limit": _integer,
                        "group_by": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(GROUP_KEYS)},
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(METRICS)},
                        },
                        "unit": {"type": "string", "enum": ["profile", "measurement"]},
                        "depth_bin_size": {"type": "integer", "enum": list(DEPTH_BIN_SIZES)},
                        "longitude": _number,
                        "latitude": _number,
                        "radius_km": _number,
                        "k": _integer,
                    },
                    "required": ["kind"],
                },
                "presentation": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(PRESENTATIONS)},
                        "bins": _integer,
                    },
                    "required": ["kind"],
                },
            },
            "required": ["time_range", "geography", "variables", "operation"],
        },
    },
    "required": ["kind"],
}

GEOGRAPHY_KEYS = {
    "named_region": ("kind", "value"),
    "bbox": ("kind", "west", "south", "east", "north"),
    "point_radius": ("kind", "longitude", "latitude", "radius_km"),
}
OPERATION_KEYS = {
    "profiles": ("kind", "limit"),
    "aggregate": ("kind", "group_by", "metrics", "unit", "depth_bin_size"),
    "nearest": ("kind", "longitude", "latitude", "radius_km", "k"),
}


def _strip_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_nulls(item) for item in value]
    return value


def _keep(document: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: document[key] for key in keys if key in document}


def to_plan_document(flat: Any) -> dict[str, Any]:
    """The plan the validator sees. Unknown kinds and types pass through to be rejected."""
    if not isinstance(flat, dict):
        return {"plan": flat}
    plan = _strip_nulls(flat)
    geography = plan.get("geography")
    if isinstance(geography, dict) and geography.get("kind") in GEOGRAPHY_KEYS:
        plan["geography"] = _keep(geography, GEOGRAPHY_KEYS[geography["kind"]])
    operation = plan.get("operation")
    if isinstance(operation, dict) and operation.get("kind") in OPERATION_KEYS:
        kept = _keep(operation, OPERATION_KEYS[operation["kind"]])
        if kept.get("kind") == "aggregate":
            kept.setdefault("group_by", [])
            kept.setdefault("metrics", [])
            # A bin size without the depth_bin key is a stray default, not an intent (seen
            # live: a count question answered with depth_bin_size and no depth_bin).
            if "depth_bin" not in (kept.get("group_by") or []):
                kept.pop("depth_bin_size", None)
        plan["operation"] = kept
    presentation = plan.get("presentation")
    if isinstance(presentation, dict):
        plan["presentation"] = _keep(presentation, ("kind", "bins"))
    plan.setdefault("dataset", "core")
    plan.setdefault("qc_policy", "science_ready")
    return dict(plan)
