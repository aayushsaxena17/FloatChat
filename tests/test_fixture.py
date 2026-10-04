import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


def test_fixture_schema_size_checksum() -> None:
    fixture = Path("tests/fixtures/profiles.parquet")
    metadata = json.loads(fixture.with_suffix(".json").read_text())
    assert 0 < fixture.stat().st_size < 1_000_000
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == metadata["sha256"]
    table = pq.read_table(fixture)
    assert table.num_rows == metadata["rows"] == 128
    assert [{"name": f.name, "type": str(f.type)} for f in table.schema] == metadata["schema"]
    assert table.schema.metadata is None
