"""Reproduce a bounded scientific fixture from the preserved prototype file."""

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

LIMIT = 1_000_000
ROWS = 128


def sample(source: Path, destination: Path) -> dict[str, object]:
    parquet = pq.ParquetFile(source)
    batch = next(parquet.iter_batches(batch_size=ROWS))
    data = pa.Table.from_batches([batch]).slice(0, ROWS).replace_schema_metadata(None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(data, destination, compression="zstd", version="2.6")
    if destination.stat().st_size >= LIMIT:
        raise ValueError("fixture must be less than 1,000,000 bytes")
    return {
        "source": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_rows": parquet.metadata.num_rows,
        "selection": "First 128 physical rows of the first row group, original order",
        "rows": data.num_rows,
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "schema": [{"name": field.name, "type": str(field.type)} for field in data.schema],
        "writer": "pyarrow 23.0.1; parquet 2.6; zstd; no pandas metadata",
        "attribution": "Argo GDAC, DOI 10.17882/42182; access service Argovis",
        "retrieval_time": "Not recorded by the prototype; not inferred",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/profiles.parquet"))
    args = parser.parse_args()
    metadata = sample(args.source, args.output)
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Fixture generated:", metadata["rows"], "rows;", metadata["bytes"], "bytes")
