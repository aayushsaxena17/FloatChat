"""Closed registry of machine-readable error codes (PRD section 13.2, plan section 5.5).

Every error that can reach a client carries one of these codes; messages are fixed text or
built from plan field names, never from request values, SQL, object keys or exception text.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType

# Detail codes: one entry per violation inside a plan_invalid error.
DETAIL_CODES = frozenset(
    {
        "unknown_field",
        "missing_field",
        "invalid_value",
        "unknown_variable",
        "unknown_region",
        "unknown_function",
        "invalid_time_range",
        "invalid_depth_range",
        "invalid_geography",
        "unbounded_request",
        "disallowed_format",
        "cost_over_budget",
        "operation_variable_mismatch",
    }
)

# Top-level codes with their HTTP status and a fixed user-visible message.
REGISTRY = MappingProxyType(
    {
        "plan_invalid": (422, "The query plan is invalid; see details."),
        "unknown_region": (422, "The named region is not in the catalogue."),
        "cost_over_budget": (422, "The estimated cost of this request exceeds the budget."),
        "coverage_missing": (422, "No committed coverage exists for the requested scope."),
        "not_found": (404, "The requested resource does not exist."),
        "method_not_allowed": (405, "The method is not allowed on this resource."),
        "invalid_cursor": (400, "The pagination cursor is invalid."),
        "invalid_parameter": (400, "A query parameter is invalid; see details."),
        "payload_too_large": (413, "The request body exceeds the configured limit."),
        "result_too_large": (422, "The result exceeds the synchronous result limit."),
        "statement_timeout": (504, "The query exceeded its time budget."),
        "execution_failed": (502, "The query could not be executed."),
        "internal_error": (500, "An internal error occurred."),
        "service_unavailable": (503, "The query service is not configured."),
    }
)


@dataclass(frozen=True)
class Detail:
    field: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in DETAIL_CODES:
            raise ValueError("unregistered detail code")

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


class QueryError(Exception):
    """A client-visible failure with a registered code; safe to serialize as is."""

    def __init__(
        self, code: str, details: Sequence[Detail] = (), message: str | None = None
    ) -> None:
        if code not in REGISTRY:
            raise ValueError("unregistered error code")
        super().__init__(code)
        self.code = code
        self.details = tuple(details)
        self.message = message

    @property
    def status(self) -> int:
        return REGISTRY[self.code][0]

    @property
    def text(self) -> str:
        return self.message or REGISTRY[self.code][1]

    def as_dict(self, correlation_id: str) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.text,
                "details": [detail.as_dict() for detail in self.details],
                "correlation_id": correlation_id,
            }
        }
