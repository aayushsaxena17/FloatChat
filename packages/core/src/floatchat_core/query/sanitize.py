"""Result sanitiser (PRD section 8.5): types, bounds, finiteness and no internal strings."""

import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .errors import QueryError
from .limits import QueryLimits

FORBIDDEN = re.compile(
    r"(normalised/|raw/sha256|s3://|postgres(ql)?://|minio|traceback|\bselect\b|\binsert\b|"
    r"password|secret)",
    re.IGNORECASE,
)
UNITS = {"pressure": "dbar", "temperature": "degree_C", "salinity": "1", "distance_m": "m"}


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str  # string | number | integer | timestamp | date | boolean
    unit: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "unit": self.unit}


@dataclass(frozen=True)
class SanitizedResult:
    columns: tuple[ColumnSpec, ...]
    rows: list[list[Any]]
    non_finite: int
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": [column.as_dict() for column in self.columns],
            "rows": self.rows,
            "row_count": len(self.rows),
            "missing_value_policy": "null",
            "non_finite_values": self.non_finite,
        }


def unit_for(column: str) -> str | None:
    for variable, unit in UNITS.items():
        if column == variable or column.startswith(variable + "_"):
            if column.endswith("_count"):
                return None
            if column.endswith(("_qc", "_data_mode", "_unit")):
                return None
            return unit
    return None


def _scalar(value: Any, spec: ColumnSpec) -> tuple[Any, int]:
    if value is None:
        return None, 0
    if isinstance(value, bool):
        if spec.type != "boolean":
            raise QueryError("internal_error", message="Result sanitisation failed.")
        return value, 0
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if spec.type not in ("number",):
            raise QueryError("internal_error", message="Result sanitisation failed.")
        if not math.isfinite(value):
            return None, 1
        return value, 0
    if isinstance(value, int):
        if spec.type not in ("number", "integer"):
            raise QueryError("internal_error", message="Result sanitisation failed.")
        return value, 0
    if isinstance(value, datetime):
        if spec.type != "timestamp":
            raise QueryError("internal_error", message="Result sanitisation failed.")
        return value.isoformat().replace("+00:00", "Z"), 0
    if isinstance(value, date):
        if spec.type != "date":
            raise QueryError("internal_error", message="Result sanitisation failed.")
        return value.isoformat(), 0
    if isinstance(value, uuid.UUID):
        value = str(value)
    if isinstance(value, str):
        if spec.type != "string":
            raise QueryError("internal_error", message="Result sanitisation failed.")
        if len(value) > 512 or FORBIDDEN.search(value):
            raise QueryError("internal_error", message="Result sanitisation failed.")
        return value, 0
    raise QueryError("internal_error", message="Result sanitisation failed.")


def sanitize(
    rows: list[dict[str, Any]], columns: tuple[ColumnSpec, ...], limits: QueryLimits
) -> SanitizedResult:
    """Validate every value against its column type; non-finite numbers become null."""
    if len(rows) > limits.max_rows:
        raise QueryError("result_too_large")
    names = [column.name for column in columns]
    output: list[list[Any]] = []
    non_finite = 0
    for row in rows:
        if set(row) != set(names):
            raise QueryError("internal_error", message="Result sanitisation failed.")
        cleaned = []
        for column in columns:
            value, missing = _scalar(row[column.name], column)
            non_finite += missing
            cleaned.append(value)
        output.append(cleaned)
    encoded = len(json.dumps(output, separators=(",", ":")).encode())
    if encoded > limits.response_bytes:
        raise QueryError("result_too_large")
    return SanitizedResult(columns, output, non_finite, encoded)


def check_text(value: str, *, max_length: int = 512) -> str:
    """Free text that reaches a client (labels, descriptions) never carries internals."""
    if len(value) > max_length or FORBIDDEN.search(value):
        raise QueryError("internal_error", message="Result sanitisation failed.")
    return value
