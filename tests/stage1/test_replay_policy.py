"""Replay admission must reject incompatible predecessors before creating a run."""

import uuid

import pytest
from floatchat_core.ingestion.argovis import policy_versions
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import GEOMETRY_SHA256, month_interval, timestamp
from floatchat_core.ingestion.repository import Repository


@pytest.mark.parametrize(
    "change",
    [
        {"closed": False},
        {"state": "partial"},
        {"state": "quarantined"},
        {"environment_id": uuid.uuid4()},
        {"mode": "normal"},
        {"requested_start": timestamp("2025-01-02T00:00:00Z")},
        {"requested_end": timestamp("2025-01-31T00:00:00Z")},
        {"geometry_sha256": "0" * 64},
        {"policy_versions": {}},
    ],
)
def test_F04_replay_incompatible_predecessor_rejected_before_admission(monkeypatch, change):
    environment, predecessor = uuid.uuid4(), uuid.uuid4()
    interval = month_interval("2025-01", "2025-01")
    row = {
        "closed": True,
        "state": "complete",
        "environment_id": environment,
        "mode": "acceptance",
        "requested_start": interval.start,
        "requested_end": interval.end,
        "policy_versions": policy_versions(),
        "geometry_sha256": GEOMETRY_SHA256,
    }
    repository = object.__new__(Repository)
    monkeypatch.setattr(repository, "run", lambda value: row)
    repository.validate_replay(environment, "acceptance", interval, predecessor)
    row.update(change)
    with pytest.raises(Rejection, match="invalid_replay_predecessor"):
        repository.validate_replay(environment, "acceptance", interval, predecessor)
