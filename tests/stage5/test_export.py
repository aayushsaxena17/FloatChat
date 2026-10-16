"""The export writer over seed parts: columns, policy values, counts, hashes, empty exports."""

import csv
import hashlib
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from floatchat_core.jobs.export import ExportWriter, export_columns, export_select
from floatchat_core.jobs.model import JobLimits, parse_export_request, plan_for
from floatchat_core.query.cache import PartCache
from floatchat_core.query.errors import QueryError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.science_seed import LEVELS, content_hash, parquet_bytes  # noqa: E402

P1, P2 = "00000000-0000-4000-8000-000000000101", "00000000-0000-4000-8000-000000000102"


def members_table(*identifiers: str) -> pa.Table:
    from floatchat_core.jobs.export import MEMBERS_SCHEMA

    rows = list(identifiers)
    return pa.Table.from_pydict(
        {
            "profile_id": rows,
            "profile_hash": [content_hash(i) for i in rows],
            "platform_number": ["5900001"] * len(rows),
            "cycle_number": list(range(1, len(rows) + 1)),
            "direction": ["A"] * len(rows),
            "observed_at": [datetime(2025, 1, 10 + n, tzinfo=UTC).replace(tzinfo=None) for n in range(len(rows))],
            "longitude": [65.0] * len(rows),
            "latitude": [15.0] * len(rows),
        },
        schema=MEMBERS_SCHEMA,
    )


@pytest.fixture
def writer(tmp_path: Path) -> tuple[ExportWriter, list[Path]]:
    cache = PartCache(tmp_path / "cache", 10**9, lambda key, size: b"")
    paths = []
    for identifier, mode in ((P1, "D"), (P2, "R")):
        payload = parquet_bytes(identifier, mode)
        path = cache.directory / (hashlib.sha256(payload).hexdigest() + ".parquet")
        path.write_bytes(payload)
        paths.append(path)
    export_writer = ExportWriter(
        query_engine=None,  # type: ignore[arg-type]
        cache=cache,
        export_directory=tmp_path / "out",
        upload=lambda key, path: None,
        limits=JobLimits(export_memory_mib=128, export_threads=1),
    )
    return export_writer, paths


def request(**extra):
    return parse_export_request(
        {
            "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
            "geography": {"kind": "named_region", "value": "Arabian Sea"},
            **extra,
        }
    )


def test_parquet_export_has_one_row_per_level_with_policy_values_and_audit_columns(writer) -> None:
    export_writer, paths = writer
    plan = plan_for(request(format="parquet"))
    written = export_writer.write(plan, members_table(P1, P2), paths, "parquet", "x.parquet")
    table = pq.read_table(written.path)
    assert table.column_names == export_columns(plan)
    assert written.row_count == table.num_rows == 2 * len(LEVELS)
    assert written.profile_count == 2
    assert written.sha256 == hashlib.sha256(written.path.read_bytes()).hexdigest()
    rows = table.to_pylist()
    first = [row for row in rows if row["profile_id"] == P1]
    # Delayed-mode profile: the adjusted value is the selected one; original is null.
    assert first[0]["temperature"] == first[0]["temperature_adjusted"] and first[0]["temperature_original"] is None
    assert first[0]["temperature_data_mode"] == "D" and first[0]["temperature_adjusted_qc"] == "1"
    real = [row for row in rows if row["profile_id"] == P2]
    assert real[0]["salinity"] == real[0]["salinity_original"] and real[0]["salinity_adjusted"] is None
    assert [row["level_index"] for row in first] == list(range(len(LEVELS)))


def test_csv_export_and_depth_filter_and_variable_selection(writer) -> None:
    export_writer, paths = writer
    plan = plan_for(request(format="csv", depth_dbar={"min": 0, "max": 50}, variables=["temperature"]))
    written = export_writer.write(plan, members_table(P1, P2), paths, "csv", "x.csv")
    with written.path.open() as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == export_columns(plan)
    assert "salinity" not in rows[0]
    shallow = [level for level in LEVELS if level[0] <= 50]
    assert written.row_count == len(rows) == 2 * len(shallow)
    assert "pressure" not in rows[0]  # only the requested variable is exported
    assert {row["temperature"] for row in rows} == {"28.0", "25.0"}


def test_members_outside_the_manifest_or_parts_are_dropped_and_empty_exports_keep_the_header(writer) -> None:
    export_writer, paths = writer
    plan = plan_for(request(format="csv"))
    stranger = str(uuid.uuid4())
    written = export_writer.write(plan, members_table(stranger), paths, "csv", "y.csv")
    assert written.row_count == 0 and written.profile_count == 0
    with written.path.open() as handle:
        rows = list(csv.reader(handle))
    assert rows == [export_columns(plan)]
    empty = export_writer.write(plan, members_table(P1), [], "parquet", "z.parquet")
    assert empty.row_count == 0 and pq.read_table(empty.path).column_names == export_columns(plan)


def test_the_select_is_a_fixed_template_with_named_parameters() -> None:
    plan = plan_for(request(depth_dbar={"min": 10, "max": 100}, qc_policy="raw"))
    sql, parameters = export_select(plan)
    assert parameters == {"depth_min": 10.0, "depth_max": 100.0}
    assert "$parts_files" in sql and "ORDER BY m.observed_at, m.profile_id, p.level_index" in sql
    assert "'" not in sql.replace("'R'", "").replace("'A'", "").replace("'D'", "").replace("'1'", "").replace("'2'", "")


def test_paths_outside_the_cache_are_refused(writer, tmp_path: Path) -> None:
    export_writer, _paths = writer
    plan = plan_for(request())
    foreign = tmp_path / ("a" * 64 + ".parquet")
    foreign.write_bytes(b"")
    with pytest.raises(QueryError, match="internal_error"):
        export_writer.write(plan, members_table(P1), [foreign], "csv", "w.csv")
