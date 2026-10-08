"""Deterministic, bounded level snapshots with exact scientific-content verification.

Writers spill row groups to a private file. Verification scans row groups and holds
at most one profile's canonical content, rather than loading a full snapshot table.
Mutable upstream revisions, attempt times and retrieval evidence are deliberately
absent from this schema.
"""

import hashlib
import io
import json
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, nullcontext
from decimal import Decimal
from itertools import chain
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .argovis import VARIABLES, Profile
from .numeric import CanonicalBudget, Rejection, scientific_number
from .objects import MAX_OBJECT_BYTES

SCHEMA_VERSION = "core-parquet-v1"
ROW_GROUP_ROWS = 100_000
BATCH_ROWS = 64
WRITER_OPTIONS = {
    "version": "2.6",
    "compression": "zstd",
    "compression_level": 3,
    "use_dictionary": ["profile_id", "source_profile_id", "profile_hash", "profile_content"],
    "write_statistics": True,
    "store_schema": True,
    "data_page_size": 64 * 1024,
    "write_batch_size": BATCH_ROWS,
}


def schema() -> Any:
    fields = [
        pa.field("profile_id", pa.string(), nullable=False),
        pa.field("source_profile_id", pa.string()),
        pa.field("profile_hash", pa.string(), nullable=False),
        pa.field("profile_content", pa.string(), nullable=False),
        pa.field("canonical_level", pa.string(), nullable=False),
        pa.field("level_index", pa.int32(), nullable=False),
    ]
    for variable in VARIABLES:
        for suffix in ("", "_adjusted", "_error", "_original_error"):
            fields.append(pa.field(variable + suffix, pa.float64()))
        for suffix in (
            "_qc",
            "_adjusted_qc",
            "_qc_source",
            "_adjusted_qc_source",
            "_unit",
            "_unit_source",
            "_data_mode",
        ):
            fields.append(pa.field(variable + suffix, pa.string()))
        fields.append(
            pa.field(
                variable + "_flags", pa.list_(pa.field("element", pa.string())), nullable=False
            )
        )
    return pa.schema(
        fields,
        metadata={
            b"schema_version": SCHEMA_VERSION.encode(),
            b"hash_version": b"scientific-json-v2",
            b"mapping_version": b"argovis-core-v1",
        },
    )


def schema_hash() -> str:
    # Explicit logical schema representation: no runtime-dependent Arrow IPC bytes.
    value = {
        "fields": [(field.name, str(field.type), field.nullable) for field in schema()],
        "versions": {key.decode(): value.decode() for key, value in schema().metadata.items()},
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def rows(identifier: uuid.UUID, profile: Profile) -> Iterator[dict[str, Any]]:
    canonical = json.loads(profile.canonical_bytes)
    canonical_levels = canonical.pop("levels")
    header = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for level, content in zip(profile.levels, canonical_levels, strict=True):
        yield {
            "profile_id": str(identifier),
            "source_profile_id": profile.source_profile_id,
            "profile_hash": profile.content_hash,
            "profile_content": header,
            "canonical_level": json.dumps(content, sort_keys=True, separators=(",", ":")),
            **level,
        }


def write_snapshot(
    path: Path,
    profiles: Mapping[uuid.UUID, Profile] | Iterable[tuple[uuid.UUID, Profile]],
    *,
    deadline: float,
    max_bytes: int = MAX_OBJECT_BYTES,
    budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]] | None = None,
) -> dict[str, Any]:
    iterator = iter(sorted(profiles.items()) if isinstance(profiles, Mapping) else profiles)
    first = next(iterator, None)
    if first is None:
        raise Rejection("empty_snapshot_not_publishable")
    if not 0 < max_bytes <= MAX_OBJECT_BYTES:
        raise Rejection("invalid_object_budget")
    # Refuse accidental overwrite, even of a caller-provided temporary path.
    with (
        path.open("xb") as output,
        TemporaryDirectory(prefix="parquet-spill-", dir=path.parent) as private_spill,
    ):
        path.chmod(0o600)
        with pq.ParquetWriter(output, schema(), **WRITER_OPTIONS) as writer:
            batch: list[dict[str, Any]] = []
            group_rows = 0
            group_paths: list[Path] = []
            spill_bytes = 0
            group_path = Path(private_spill) / "group-000000.arrow"
            sink = group_path.open("xb")
            group_path.chmod(0o600)
            ipc = pa.ipc.new_file(sink, schema())

            def spill() -> None:
                nonlocal group_rows
                ipc.write_table(pa.Table.from_pylist(batch, schema=schema()))
                group_rows += len(batch)
                batch.clear()
                if spill_bytes + sink.tell() > 10 * 1024**3:
                    raise Rejection("snapshot_spill_limit")

            def flush_group() -> None:
                nonlocal group_rows, sink, ipc, spill_bytes, group_path
                ipc.close()
                sink.close()
                # Zero-copy chunked buffers remain backed by private disk files.
                # Dictionary encoding avoids expanding repeated profile headers
                # into the in-memory Parquet page buffers.
                with pa.memory_map(str(group_path), "r") as mapped:
                    table = pa.ipc.open_file(mapped).read_all()
                    writer.write_table(table, row_group_size=ROW_GROUP_ROWS)
                    del table
                spill_bytes += group_path.stat().st_size
                group_paths.append(group_path)
                group_rows = 0
                if output.tell() > max_bytes or time.monotonic() >= deadline:
                    raise Rejection(
                        "object_size_limit" if output.tell() > max_bytes else "snapshot_deadline"
                    )
                group_path = Path(private_spill) / f"group-{len(group_paths):06d}.arrow"
                sink = group_path.open("xb")
                group_path.chmod(0o600)
                ipc = pa.ipc.new_file(sink, schema())

            try:
                for identifier, profile in chain((first,), iterator):
                    for row in rows(identifier, profile):
                        if time.monotonic() >= deadline:
                            raise Rejection("snapshot_deadline")
                        batch.append(row)
                        if len(batch) >= min(BATCH_ROWS, ROW_GROUP_ROWS - group_rows):
                            spill()
                        if group_rows == ROW_GROUP_ROWS:
                            flush_group()
                if batch:
                    spill()
                if group_rows:
                    flush_group()
            finally:
                ipc.close()
                sink.close()
        if output.tell() > max_bytes:
            raise Rejection("object_size_limit")
        output.flush()
        verified = verify_snapshot(path, deadline=deadline, budget_factory=budget_factory)
        with ExitStack() as stack:
            tables = []
            for item in group_paths:
                mapped = stack.enter_context(pa.memory_map(str(item), "r"))
                tables.append(pa.ipc.open_file(mapped).read_all())
            table = pa.concat_tables(tables)
            comparison = storage_comparison(table, path.stat().st_size)
            if comparison["rows"] != verified["rows"]:
                raise Rejection("storage_comparison_mismatch")
            del table, tables
        if time.monotonic() >= deadline:
            raise Rejection("snapshot_deadline")
        return {**verified, "storage_comparison": comparison, "writer_options": WRITER_OPTIONS}


def storage_comparison(table: Any, parquet_bytes: int) -> dict[str, Any]:
    """Measure one whole nullable Arrow-backed frame of the exact ordered IPC rows.

    Spill-file buffers count toward logical deep memory even when not resident.
    https://pandas.pydata.org/pandas-docs/version/2.3.3/user_guide/pyarrow.html
    """
    if not table.schema.equals(schema(), check_metadata=True):
        raise Rejection("storage_comparison_schema_mismatch")
    frame = table.to_pandas(types_mapper=pd.ArrowDtype)
    measured = int(frame.memory_usage(index=True, deep=True).sum())
    return {
        "rows": len(frame),
        "columns": list(frame.columns),
        "nullable_dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
        "index": type(frame.index).__name__,
        "index_included": True,
        "pandas_version": pd.__version__,
        "pyarrow_version": pa.__version__,
        "pandas_deep_memory_bytes": measured,
        "parquet_bytes": parquet_bytes,
        "pandas_to_parquet_ratio": measured / parquet_bytes
        if len(frame) and parquet_bytes
        else None,
        "ratio_status": "measured" if len(frame) and parquet_bytes else "not-applicable",
        "parquet_index": "source level_index; pandas RangeIndex not stored",
        "availability": {
            variable: {
                suffix or "original": table.num_rows - table[variable + suffix].null_count
                for suffix in ("", "_adjusted", "_qc", "_adjusted_qc", "_error", "_original_error")
            }
            for variable in VARIABLES
        },
        "equivalence": "Same ordered typed IPC rows supplied to the writer; complete "
        "Parquet scientific/hash/scalar verification before measurement",
        "memory_scope": "Logical DataFrame deep memory; distinct from process RSS",
    }


def verify_snapshot(
    source: Any,
    *,
    deadline: float,
    budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]] | None = None,
) -> dict[str, int | str]:
    try:
        file = pq.ParquetFile(source)
        if not file.schema_arrow.equals(schema(), check_metadata=True):
            raise Rejection("parquet_schema_mismatch")
        if file.metadata.num_rows > 100_000_000:
            raise Rejection("snapshot_level_limit")
        previous: uuid.UUID | None = None
        current: uuid.UUID | None = None
        header: str | None = None
        digest: str | None = None
        alias: str | None = None
        levels: list[dict[str, Any]] = []
        canonical_size = 0
        membership: list[dict[str, Any]] = []
        seen_aliases: set[str] = set()
        count = 0

        def finish() -> None:
            if current is None:
                return
            if not levels or header is None:
                raise Rejection("invalid_snapshot_profile")
            content = json.loads(header)
            content["levels"] = levels
            with (budget_factory or (lambda: nullcontext(CanonicalBudget())))() as budget:
                _, actual = budget.encode(content)
            if actual != digest:
                raise Rejection("snapshot_scientific_hash_mismatch")
            membership.append({"profile_id": str(current), "hash": actual, "levels": len(levels)})
            if len(membership) > 100000:
                raise Rejection("snapshot_profile_limit")

        for group in range(file.num_row_groups):
            if time.monotonic() >= deadline:
                raise Rejection("snapshot_deadline")
            if file.metadata.row_group(group).num_rows > ROW_GROUP_ROWS:
                raise Rejection("parquet_row_group_limit")
        for batch in file.iter_batches(batch_size=BATCH_ROWS, use_threads=False):
            for row in batch.to_pylist():
                if time.monotonic() >= deadline:
                    raise Rejection("snapshot_deadline")
                identifier = uuid.UUID(row["profile_id"])
                if identifier != current:
                    finish()
                    previous = current
                    if previous is not None and identifier <= previous:
                        raise Rejection("snapshot_identity_order")
                    current, header, digest, alias = (
                        identifier,
                        row["profile_content"],
                        row["profile_hash"],
                        row["source_profile_id"],
                    )
                    if alias is not None:
                        if alias in seen_aliases:
                            raise Rejection("duplicate_snapshot_alias")
                        seen_aliases.add(alias)
                    if len(header.encode()) > 16 * 1024 * 1024:
                        raise Rejection(
                            "canonical_output_limit",
                            resource={
                                "scope": "profile",
                                "operation": "readback",
                                "limit_bytes": 16 * 1024 * 1024,
                                "used_bytes": 0,
                                "requested_bytes": len(header.encode()),
                            },
                        )
                    levels = []
                    canonical_size = len(header.encode())
                if (
                    row["profile_content"] != header
                    or row["profile_hash"] != digest
                    or row["source_profile_id"] != alias
                    or row["level_index"] != len(levels)
                ):
                    raise Rejection("snapshot_profile_inconsistency")
                canonical_size += len(row["canonical_level"].encode())
                if canonical_size > 16 * 1024 * 1024:
                    raise Rejection(
                        "canonical_output_limit",
                        resource={
                            "scope": "profile",
                            "operation": "readback",
                            "limit_bytes": 16 * 1024 * 1024,
                            "used_bytes": canonical_size - len(row["canonical_level"].encode()),
                            "requested_bytes": len(row["canonical_level"].encode()),
                        },
                    )
                if len(levels) >= 10000:
                    raise Rejection("canonical_output_limit")
                content = json.loads(row["canonical_level"])
                if content.get("level_index") != row["level_index"]:
                    raise Rejection("snapshot_level_mismatch")
                for variable in VARIABLES:
                    for suffix in ("", "_adjusted", "_error", "_original_error"):
                        exact = content.get(variable + suffix)
                        expected = None
                        if exact is not None and exact["exact"] is not None:
                            expected = scientific_number(Decimal(exact["exact"])).value
                        if row[variable + suffix] != expected:
                            raise Rejection("snapshot_numeric_mismatch")
                    for suffix in (
                        "_qc",
                        "_adjusted_qc",
                        "_qc_source",
                        "_adjusted_qc_source",
                        "_unit",
                        "_unit_source",
                        "_data_mode",
                        "_flags",
                    ):
                        if row[variable + suffix] != content.get(variable + suffix):
                            raise Rejection("snapshot_level_mismatch")
                levels.append(content)
                count += 1
        finish()
        if not membership:
            raise Rejection("empty_snapshot_not_publishable")
        manifest = json.dumps(membership, sort_keys=True, separators=(",", ":")).encode()
        return {
            "schema_sha256": schema_hash(),
            "rows": count,
            "profiles": len(membership),
            "membership_sha256": hashlib.sha256(manifest).hexdigest(),
        }
    except Rejection:
        raise
    except (ValueError, KeyError, TypeError, OSError, pa.ArrowException):
        raise Rejection("invalid_parquet") from None


class PublicationSnapshotVerifier:
    """One-publication certificate for scientifically verified immutable bytes.

    First payload receives the full scientific/scalar/hash verification. Every
    later payload is independently byte-count/SHA/schema/row-group/count checked;
    equal whole-object SHA proves identical certified profile membership/content.
    No payload/rows are cached. New intent/process/recovery must certify again.
    """

    def __init__(
        self,
        digest: str,
        byte_count: int,
        evidence: Mapping[str, Any],
        *,
        deadline: float,
        budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]],
    ) -> None:
        self.digest, self.byte_count = digest, byte_count
        self.expected = {
            name: evidence[name]
            for name in ("schema_sha256", "rows", "profiles", "membership_sha256")
        }
        self.deadline, self.budget_factory = deadline, budget_factory
        self._certified = False

    def __call__(self, payload: bytes) -> dict[str, int | str]:
        if time.monotonic() >= self.deadline:
            raise Rejection("snapshot_deadline")
        if len(payload) != self.byte_count or hashlib.sha256(payload).hexdigest() != self.digest:
            raise Rejection("object_checksum_mismatch")
        if not self._certified:
            actual = verify_snapshot(
                io.BytesIO(payload), deadline=self.deadline, budget_factory=self.budget_factory
            )
            if actual != self.expected:
                raise Rejection("object_validation_mismatch")
            self._certified = True
        else:
            try:
                file = pq.ParquetFile(io.BytesIO(payload))
                if not file.schema_arrow.equals(schema(), check_metadata=True):
                    raise Rejection("parquet_schema_mismatch")
                if file.metadata.num_rows != self.expected["rows"] or any(
                    file.metadata.row_group(group).num_rows > ROW_GROUP_ROWS
                    for group in range(file.num_row_groups)
                ):
                    raise Rejection("object_validation_mismatch")
            except (OSError, ValueError, pa.ArrowException):
                raise Rejection("invalid_parquet") from None
        return dict(self.expected)
