"""ADR-0044 scale check: one maximum-depth profile commits well inside the 60 s bound."""

import json

import pytest
import test_database
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
from test_database import _literal, _publishing

postgres = test_database.postgres


@pytest.mark.integration
def test_ADR0044_ten_thousand_level_commit_seconds(postgres, wire, linked_metadata):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    wire["profile_direction"] = "A"
    columns = wire["data"]
    wire["data"] = [(column * (10000 // len(column) + 1))[:10000] for column in columns]
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    candidate = test_database.staged_candidate(
        profile,
        test_database.uuid.UUID(test_database.PROFILE),
        test_database.uuid.UUID(test_database.RAW),
    )
    assert len(candidate["levels"]) == 10000
    setup, _, generations, receipts = _publishing(profile, candidate)
    result = postgres(
        setup
        + "CREATE TEMP TABLE started AS SELECT clock_timestamp() AS at;"
        + f"SELECT app.commit_publication('{test_database.RUN}','{test_database.CHUNK}',1,1,"
        + f"'{test_database.INTENT}',{_literal(generations)},{_literal(receipts)});"
        + "SELECT extract(epoch FROM clock_timestamp()-(SELECT at FROM started));"
        + "SELECT count(*) FROM app.core_measurement; ROLLBACK;"
    )
    seconds, levels = result.splitlines()[-2:]
    print(json.dumps({"levels": int(levels), "commit_seconds": float(seconds)}))
    assert int(levels) == 10000
    assert float(seconds) < 10  # measured 1.3 s after ADR-0044; 23.5 s before the fix
