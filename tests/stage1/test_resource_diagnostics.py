import json
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decimal_text
from floatchat_core.ingestion.repository import Repository


@pytest.mark.parametrize(
    "budget,scope,repeats",
    [
        (CanonicalBudget(profile_limit=5), "profile", 1),
        (CanonicalBudget(profile_limit=100, chunk_limit=12), "chunk", 2),
        (CanonicalBudget(profile_limit=100, chunk_limit=100, run_limit=12), "run", 2),
    ],
)
def test_N08_exact_scope_without_scientific_content(budget, scope, repeats):
    with pytest.raises(Rejection) as caught:
        for _ in range(repeats):
            budget.encode({"x": "q"})
    error = caught.value
    assert error.category == str(error) == "canonical_output_limit"
    detail = error.resource_evidence
    assert detail["scope"] == scope and detail["operation"] == "encoding"
    assert detail["used_bytes"] + detail["requested_bytes"] > detail["limit_bytes"]
    assert set(detail) == {"scope", "operation", "limit_bytes", "used_bytes", "requested_bytes"}


def test_N02_number_scope_preflight_without_expansion():
    with pytest.raises(Rejection) as caught:
        decimal_text(Decimal("1e512"))
    assert caught.value.resource_evidence == {
        "scope": "number",
        "operation": "normalization",
        "limit_bytes": 512,
        "used_bytes": 0,
        "requested_bytes": 513,
    }


class DatabaseFailure(psycopg.Error):
    def __init__(self, detail):
        self.detail = detail

    @property
    def diag(self):
        return SimpleNamespace(message_primary="canonical_output_limit", message_detail=self.detail)


class Connection:
    @contextmanager
    def transaction(self):
        yield

    @contextmanager
    def cursor(self):
        yield SimpleNamespace(execute=lambda *args: None)


VALID = {
    "scope": "run",
    "operation": "reservation",
    "limit_bytes": 10737418240,
    "used_bytes": 10721657712,
    "requested_bytes": 16777216,
}


@pytest.mark.parametrize(
    "detail,expected",
    [
        (json.dumps(VALID), VALID),
        (None, {}),
        (json.dumps({**VALID, "headers": "synthetic-sensitive-sentinel"}), {}),
        (json.dumps({**VALID, "scope": "https://unexpected.invalid/?credential=sentinel"}), {}),
        (json.dumps({**VALID, "requested_bytes": True}), {}),
        (json.dumps({**VALID, "used_bytes": -1}), {}),
        (json.dumps({**VALID, "limit_bytes": 2**63}), {}),
        ("synthetic-sensitive-sentinel", {}),
        ("x" * 1025, {}),
        ('["unexpected-response-body"]', {}),
    ],
)
def test_B03_database_detail_is_fixed_shape_and_never_rendered(detail, expected):
    repository = Repository.__new__(Repository)
    repository.connection = Connection()
    with pytest.raises(Rejection) as caught:
        with repository.transaction():
            raise DatabaseFailure(detail)
    assert caught.value.resource_evidence == expected
    assert str(caught.value) == "canonical_output_limit"
    assert "sentinel" not in repr(caught.value) and "unexpected" not in repr(caught.value)
