"""Scale checks: the set-based commit stays far inside the 60 s transaction bound.

ADR-0044: one maximum-depth profile. stage1-v4: a chunk of the measured size (87 profiles
x 699 levels = 60,813 levels, the retained read-back case of the performance review)
committed from slim candidate rows plus COPY-staged level rows.
"""

import json
import sys
import uuid
from pathlib import Path

import pytest
import test_database
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
from floatchat_core.ingestion.workflow import MEASUREMENT_COLUMNS, owner_slot, staged_candidate
from test_database import _literal, _publishing

postgres = test_database.postgres
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def copy_text(value):
    """One COPY text-format field."""
    if value is None:
        return r"\N"
    if isinstance(value, (list, dict)):
        value = json.dumps(value, separators=(",", ":"))
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def copy_levels(levels_by_occurrence, chunk=test_database.CHUNK):
    """Inline COPY of typed level rows, the shape stage_levels sends in binary."""
    columns = ",".join(name for name, _ in MEASUREMENT_COLUMNS)
    lines = [
        "COPY app.measurement_staging(run_id,chunk_id,fence,occurrence_index,level_index,"
        + columns
        + ") FROM STDIN;"
    ]
    for occurrence, levels in levels_by_occurrence:
        for level in levels:
            fields = [test_database.RUN, chunk, 1, occurrence, level["level_index"]]
            fields += [level[name] for name, _ in MEASUREMENT_COLUMNS]
            lines.append("\t".join(copy_text(field) for field in fields))
    return "\n".join(lines) + "\n\\.\n"


def copy_candidates(candidates, chunk=test_database.CHUNK):
    lines = [
        "COPY app.ingestion_staging(run_id,chunk_id,fence,occurrence_index,candidate) FROM STDIN;"
    ]
    for occurrence, candidate in candidates:
        fields = [test_database.RUN, chunk, 1, occurrence, json.dumps(candidate)]
        lines.append("\t".join(copy_text(field) for field in fields))
    return "\n".join(lines) + "\n\\.\n"


@pytest.mark.integration
def test_ADR0044_ten_thousand_level_commit_seconds(postgres, wire, linked_metadata):
    wire["timestamp"] = "2025-01-02T00:00:00Z"
    wire["profile_direction"] = "A"
    columns = wire["data"]
    wire["data"] = [(column * (10000 // len(column) + 1))[:10000] for column in columns]
    profile = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    candidate = staged_candidate(
        profile, uuid.UUID(test_database.PROFILE), uuid.UUID(test_database.RAW)
    )
    assert candidate["level_count"] == 10000
    setup, _, generations, receipts = _publishing(profile, candidate, levels=[])
    result = postgres(
        setup
        + copy_levels([(0, profile.levels)])
        + "CREATE TEMP TABLE started AS SELECT clock_timestamp() AS at;"
        + f"SELECT app.commit_publication('{test_database.RUN}','{test_database.CHUNK}',1,1,"
        + f"'{test_database.INTENT}',{_literal(generations)},{_literal(receipts)});"
        + "SELECT extract(epoch FROM clock_timestamp()-(SELECT at FROM started));"
        + "SELECT count(*) FROM app.core_measurement; ROLLBACK;",
        timeout=300,
    )
    seconds, levels = result.splitlines()[-2:]
    print(json.dumps({"levels": int(levels), "commit_seconds": float(seconds)}))
    assert int(levels) == 10000
    assert float(seconds) < 10  # measured 1.3 s after ADR-0044; 23.5 s before the fix


@pytest.mark.integration
def test_v4_chunk_of_87_profiles_x_699_levels_commits_under_ten_seconds(postgres):
    from stage1_perf_profile import synthetic_chunk

    payload, _, metadata = synthetic_chunk(87, 699)
    linked = {item["_id"]: item for item in decode_json(json.dumps(metadata).encode())}
    mapped = [map_profile(doc, linked, CanonicalBudget()) for doc in documents(payload)]
    assert len(mapped) == 87 and {len(value.levels) for value in mapped} == {699}
    slot = owner_slot(mapped[0])
    assert {owner_slot(value) for value in mapped} == {slot}
    ids = [uuid.UUID(int=index + 1) for index in range(len(mapped))]
    candidates = [
        (index, {**staged_candidate(value, ids[index], uuid.UUID(test_database.RAW))})
        for index, value in enumerate(mapped)
    ]
    # The fixture stages the first candidate; the rest and every level row go through COPY.
    setup, _, generations, receipts = _publishing(mapped[0], candidates[0][1], levels=[])
    setup = setup[: setup.rindex("INSERT INTO app.ingestion_staging")]
    levels = sum(len(value.levels) for value in mapped)
    generations[0].update(
        membership_manifest=[
            {"profile_id": str(ids[index]), "hash": value.content_hash, "levels": 699}
            for index, value in enumerate(mapped)
        ],
        row_count=levels,
        profile_count=len(mapped),
        verification_evidence={"schema_sha256": "e" * 64, "rows": levels, "profiles": len(mapped)},
    )
    result = postgres(
        setup
        + copy_candidates(candidates)
        + copy_levels([(index, value.levels) for index, value in enumerate(mapped)])
        + "CREATE TEMP TABLE started AS SELECT clock_timestamp() AS at;"
        + f"SELECT app.commit_publication('{test_database.RUN}','{test_database.CHUNK}',1,1,"
        + f"'{test_database.INTENT}',{_literal(generations)},{_literal(receipts)});"
        + "SELECT extract(epoch FROM clock_timestamp()-(SELECT at FROM started));"
        + "SELECT count(*) FROM app.core_measurement;"
        + "SELECT count(*) FROM app.argo_profile;"
        + "SELECT count(*)||'|'||min(kind) FROM app.committed_active_partitions;"
        + f"SELECT jsonb_array_length(membership_manifest) FROM app.logical_partition_slot "
        f"WHERE logical_key='{slot}';"
        + f"SELECT app.audit_slot_manifest('{test_database.ENV}','{slot}');"
        + f"SELECT app.audit_levels('{test_database.CHUNK}',3);"
        + "ROLLBACK;",
        timeout=900,
    )
    seconds, stored_levels, profiles, active, manifest, audit, sampled = result.splitlines()[-7:]
    print(json.dumps({"levels": int(stored_levels), "commit_seconds": float(seconds)}))
    assert (int(stored_levels), int(profiles)) == (87 * 699, 87)
    assert active == "1|part" and int(manifest) == 87 and audit == "t"
    assert json.loads(sampled) == {"profiles": 3, "levels": 3 * 699}
    assert float(seconds) < 10  # review: 16.5-34 s before; target 10-12 s then, <10 s now
