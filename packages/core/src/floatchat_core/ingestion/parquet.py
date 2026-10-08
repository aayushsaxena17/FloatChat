"""Deterministic, bounded level snapshots with exact scientific-content verification.

Writers build Arrow arrays per profile and spill row groups to a private file. The
Parquet file is then verified once, in Arrow (arrow-equality-v4): the read-back must
equal the spilled rows and every profile's scientific hash must follow from its stored
header and canonical_level strings. verify_snapshot is the row-by-row audit and holds at
most one profile's canonical content, rather than loading a full snapshot table.
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
from typing import Any, NamedTuple

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .argovis import VARIABLES, Profile, level_table
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
VERIFICATION = "arrow-equality-v4"
PROFILE_CANONICAL_LIMIT = 16 * 1024 * 1024
PROFILE_LEVEL_LIMIT = 10_000
BLOCK_BYTES = 8 * 1024 * 1024  # Arrow arrays are built for about this much text at a time
BLOCK_ROW_OVERHEAD = 1024  # estimate for the non-text columns of one row
VERIFY_BATCH_BYTES = 32 * 1024 * 1024
VERIFY_BATCH_ROWS = 2048


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


class _Parts(NamedTuple):
    """One profile before it becomes Arrow rows: its constants and its level table."""

    identifier: uuid.UUID
    alias: str | None
    digest: str
    header: str
    levels: Any


def _header(profile: Profile) -> str:
    """profile_content: the canonical object without its levels, as rows() encodes it."""
    text = profile.canonical_bytes.decode()
    opening = text.find('"levels":[')
    closing = text.find('],"longitude":', opening)
    if opening > 0 and closing > opening:
        # The canonical bytes are already in this encoding; cut instead of parsing every
        # level, and accept the cut only if the header re-frames the text it came from.
        header = text[: opening - 1] + text[closing + 1 :]
        try:
            prefix, suffix = _frame(header)
        except ValueError:
            prefix = suffix = ""
        if text.startswith(prefix) and text.endswith(suffix) and prefix and suffix:
            return header
    canonical = json.loads(profile.canonical_bytes)
    canonical.pop("levels")
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _readback_limit(used: int, requested: int) -> Rejection:
    return Rejection(
        "canonical_output_limit",
        resource={
            "scope": "profile",
            "operation": "readback",
            "limit_bytes": PROFILE_CANONICAL_LIMIT,
            "used_bytes": used,
            "requested_bytes": requested,
        },
    )


def _check_limits(parts: _Parts, sizes: Any) -> None:
    """The per-profile bounds verify_snapshot enforces on read-back, from the strings in hand."""
    header = len(parts.header.encode())
    if header > PROFILE_CANONICAL_LIMIT:
        raise _readback_limit(0, header)
    if header + (pc.sum(sizes).as_py() or 0) > PROFILE_CANONICAL_LIMIT or (
        len(sizes) > PROFILE_LEVEL_LIMIT
    ):
        used = header
        for index, size in enumerate(sizes.to_pylist()):
            if used + size > PROFILE_CANONICAL_LIMIT:
                raise _readback_limit(used, size)
            if index >= PROFILE_LEVEL_LIMIT:
                raise Rejection("canonical_output_limit")
            used += size


def _block(parts: _Parts, start: int, stop: int, fields: Any) -> Any:
    """Arrow arrays for levels [start, stop) of one profile, columns in schema() order."""
    count = stop - start
    levels = parts.levels.slice(start, count)
    constants = {
        "profile_id": pa.repeat(str(parts.identifier), count),
        "source_profile_id": pa.repeat(parts.alias, count)
        if parts.alias is not None
        else pa.nulls(count, pa.string()),
        "profile_hash": pa.repeat(parts.digest, count),
        "profile_content": pa.repeat(parts.header, count),
    }
    return pa.Table.from_arrays(
        [
            constants[field.name] if field.name in constants else levels[field.name]
            for field in fields
        ],
        schema=fields,
    )


def _open_written(path: Path) -> Any:
    # Read-back seam: the file as the object store will receive it.
    return pq.ParquetFile(path)


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def write_snapshot(
    path: Path,
    profiles: Mapping[uuid.UUID, Profile] | Iterable[tuple[uuid.UUID, Profile]],
    *,
    deadline: float,
    max_bytes: int = MAX_OBJECT_BYTES,
    budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]] | None = None,
    audit: bool = False,
) -> dict[str, Any]:
    iterator = iter(sorted(profiles.items()) if isinstance(profiles, Mapping) else profiles)
    first = next(iterator, None)
    if first is None:
        raise Rejection("empty_snapshot_not_publishable")
    if not 0 < max_bytes <= MAX_OBJECT_BYTES:
        raise Rejection("invalid_object_budget")
    fields = schema()
    # Refuse accidental overwrite, even of a caller-provided temporary path.
    with (
        path.open("xb") as output,
        TemporaryDirectory(prefix="parquet-spill-", dir=path.parent) as private_spill,
    ):
        path.chmod(0o600)
        with pq.ParquetWriter(output, fields, **WRITER_OPTIONS) as writer:
            pending: list[Any] = []
            pending_rows = 0
            group_rows = 0
            group_paths: list[Path] = []
            spill_bytes = 0
            group_path = Path(private_spill) / "group-000000.arrow"
            sink = group_path.open("xb")
            group_path.chmod(0o600)
            ipc = pa.ipc.new_file(sink, fields)

            def spill(final: bool) -> None:
                # The writer sees BATCH_ROWS-row IPC batches counted from the group start,
                # whatever the profile boundaries: Parquet page cuts depend on chunk edges.
                nonlocal group_rows, pending_rows
                take = pending_rows if final else pending_rows - pending_rows % BATCH_ROWS
                if not take:
                    return
                combined = pa.concat_tables(pending).combine_chunks()
                ipc.write_table(combined.slice(0, take), max_chunksize=BATCH_ROWS)
                group_rows += take
                pending[:] = [combined.slice(take)] if take < pending_rows else []
                pending_rows -= take
                if spill_bytes + sink.tell() > 10 * 1024**3:
                    raise Rejection("snapshot_spill_limit")

            def flush_group() -> None:
                nonlocal group_rows, sink, ipc, spill_bytes, group_path
                spill(True)
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
                ipc = pa.ipc.new_file(sink, fields)

            def feed(block: Any) -> None:
                nonlocal pending_rows
                offset = 0
                while offset < block.num_rows:
                    take = min(ROW_GROUP_ROWS - group_rows - pending_rows, block.num_rows - offset)
                    pending.append(block.slice(offset, take))
                    pending_rows += take
                    offset += take
                    if group_rows + pending_rows == ROW_GROUP_ROWS:
                        flush_group()
                    elif pending_rows >= BATCH_ROWS:
                        spill(False)

            previous: uuid.UUID | None = None
            aliases: set[str] = set()
            profile_count = rows_total = row_bytes = 0
            try:
                for identifier, profile in chain((first,), iterator):
                    if time.monotonic() >= deadline:
                        raise Rejection("snapshot_deadline")
                    parts = _Parts(
                        identifier,
                        profile.source_profile_id,
                        profile.content_hash,
                        _header(profile),
                        level_table(profile),
                    )
                    count = parts.levels.num_rows
                    if not count:
                        continue
                    # Order and alias uniqueness follow from the input, which the Arrow
                    # equality below proves is what the file holds.
                    if previous is not None:
                        if identifier == previous:
                            raise Rejection("snapshot_profile_inconsistency")
                        if identifier < previous:
                            raise Rejection("snapshot_identity_order")
                    previous = identifier
                    if parts.alias is not None:
                        if parts.alias in aliases:
                            raise Rejection("duplicate_snapshot_alias")
                        aliases.add(parts.alias)
                    profile_count += 1
                    rows_total += count
                    if profile_count > 100000:
                        raise Rejection("snapshot_profile_limit")
                    if rows_total > 100_000_000:
                        raise Rejection("snapshot_level_limit")
                    sizes = pc.binary_length(parts.levels["canonical_level"])
                    _check_limits(parts, sizes)
                    row = len(parts.header) + pc.max(sizes).as_py() + BLOCK_ROW_OVERHEAD
                    row_bytes = max(row_bytes, row)
                    step = max(BATCH_ROWS, BLOCK_BYTES // row // BATCH_ROWS * BATCH_ROWS)
                    for start in range(0, count, step):
                        if time.monotonic() >= deadline:
                            raise Rejection("snapshot_deadline")
                        feed(_block(parts, start, min(start + step, count), fields))
                spill(True)
                if group_rows:
                    flush_group()
            finally:
                if not sink.closed:  # flush_group closes both before it can reject
                    ipc.close()
                    sink.close()
        if output.tell() > max_bytes:
            raise Rejection("object_size_limit")
        output.flush()
        verified, comparison = _verify_written(path, group_paths, deadline, row_bytes)
        if audit:
            # Periodic audit: the independent row-by-row re-decode of the same file.
            audited = verify_snapshot(path, deadline=deadline, budget_factory=budget_factory)
            if audited != verified:
                raise Rejection("object_validation_mismatch")
        digest, byte_count = _file_digest(path)
        if time.monotonic() >= deadline:
            raise Rejection("snapshot_deadline")
        certificate = PublicationSnapshotVerifier(
            digest,
            byte_count,
            verified,
            deadline=deadline,
            budget_factory=budget_factory or (lambda: nullcontext(CanonicalBudget())),
            certified=True,
        )
        return {
            **verified,
            "storage_comparison": comparison,
            "writer_options": WRITER_OPTIONS,
            "verification": VERIFICATION,
            "certificate": certificate,
        }


def _frame(header: str) -> tuple[str, str]:
    """Canonical text around the level list, from the stored header (keys sort around "levels")."""
    content = json.loads(header)
    before = json.dumps(
        {key: value for key, value in content.items() if key < "levels"},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    after = json.dumps(
        {key: value for key, value in content.items() if key > "levels"},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        before[:-1] + ("," if len(before) > 2 else "") + '"levels":[',
        "]" + ("," + after[1:-1] if len(after) > 2 else "") + "}",
    )


def _uniform(column: Any, start: int, length: int) -> bool:
    part = column.slice(start, length)
    if part.null_count:
        return bool(part.null_count == length)
    return bool(pc.all(pc.equal(part, part[0])).as_py())


def _mismatch(actual: Any, expected: Any) -> str:
    """Name a failed Arrow equality by the first differing column, as verify_snapshot would."""
    if actual.num_rows != expected.num_rows:
        return "storage_comparison_mismatch"
    for field in expected.schema:
        if not actual[field.name].equals(expected[field.name]):
            if field.name in ("profile_id", "source_profile_id", "profile_hash", "level_index"):
                return "snapshot_profile_inconsistency"
            if field.name in ("profile_content", "canonical_level"):
                return "snapshot_scientific_hash_mismatch"
            if pa.types.is_floating(field.type):
                return "snapshot_numeric_mismatch"
            return "snapshot_level_mismatch"
    return "storage_comparison_mismatch"


class _Scan:
    """One pass over the stored batches: per-profile hash and consistency, then equality.

    The canonical text of a profile is its stored header around the concatenated
    canonical_level strings, hashed without decoding a single level. Arrow equality
    with the spilled rows runs per batch, but its verdict is raised only after every
    profile's hash has been checked, so a corrupted file reports the finer category.
    """

    def __init__(self) -> None:
        self.rows = 0
        self.membership: list[dict[str, Any]] = []
        self.failure: str | None = None
        self.identifier: str | None = None
        self.header = self.digest = self.suffix = ""
        self.alias: str | None = None
        self.levels = 0
        self.hasher = hashlib.sha256()

    def batch(self, batch: Any, expected: Any) -> None:
        size = batch.num_rows
        if not size:
            return
        self.rows += size
        ids = batch.column("profile_id")
        starts = [0]
        if size > 1:
            changed = pc.indices_nonzero(pc.not_equal(ids.slice(1), ids.slice(0, size - 1)))
            starts.extend(index + 1 for index in changed.to_pylist())
        starts.append(size)
        for begin, end in zip(starts, starts[1:], strict=False):
            self.segment(batch, begin, end)
        if self.failure is None:
            actual = pa.Table.from_batches([batch])
            if not actual.equals(expected):
                self.failure = _mismatch(actual, expected)

    def segment(self, batch: Any, begin: int, end: int) -> None:
        length = end - begin
        identifier = batch.column("profile_id")[begin].as_py()
        header = batch.column("profile_content")[begin].as_py()
        digest = batch.column("profile_hash")[begin].as_py()
        alias = batch.column("source_profile_id")[begin].as_py()
        if identifier != self.identifier:
            self.finish()
            uuid.UUID(identifier)
            self.identifier, self.header, self.digest, self.alias = (
                identifier,
                header,
                digest,
                alias,
            )
            prefix, self.suffix = _frame(header)
            self.hasher = hashlib.sha256(prefix.encode())
            self.levels = 0
        elif (header, digest, alias) != (self.header, self.digest, self.alias):
            raise Rejection("snapshot_profile_inconsistency")
        if not all(
            _uniform(batch.column(name), begin, length)
            for name in ("profile_content", "profile_hash", "source_profile_id")
        ) or not batch.column("level_index").slice(begin, length).equals(
            pa.array(range(self.levels, self.levels + length), pa.int32())
        ):
            raise Rejection("snapshot_profile_inconsistency")
        texts = ",".join(batch.column("canonical_level").slice(begin, length).to_pylist())
        self.hasher.update(("," + texts if self.levels else texts).encode())
        self.levels += length

    def finish(self) -> None:
        if self.identifier is None:
            return
        self.hasher.update(self.suffix.encode())
        actual = self.hasher.hexdigest()
        if actual != self.digest:
            raise Rejection("snapshot_scientific_hash_mismatch")
        self.membership.append(
            {"profile_id": str(uuid.UUID(self.identifier)), "hash": actual, "levels": self.levels}
        )


def _verify_written(
    path: Path, group_paths: list[Path], deadline: float, row_bytes: int
) -> tuple[dict[str, int | str], dict[str, Any]]:
    """Arrow-equality verification (arrow-equality-v4) of the file just written.

    Reads the Parquet back with pyarrow, checks schema and row-group bounds, compares
    every stored batch with the spilled rows the writer was given and recomputes each
    profile's scientific hash from the stored header and canonical_level strings.
    """
    try:
        file = _open_written(path)
        if not file.schema_arrow.equals(schema(), check_metadata=True):
            raise Rejection("parquet_schema_mismatch")
        if file.metadata.num_rows > 100_000_000:
            raise Rejection("snapshot_level_limit")
        for group in range(file.num_row_groups):
            if time.monotonic() >= deadline:
                raise Rejection("snapshot_deadline")
            if file.metadata.row_group(group).num_rows > ROW_GROUP_ROWS:
                raise Rejection("parquet_row_group_limit")
        batch_rows = max(
            BATCH_ROWS, min(VERIFY_BATCH_ROWS, VERIFY_BATCH_BYTES // max(row_bytes, 1))
        )
        with ExitStack() as stack:
            tables = []
            for item in group_paths:
                mapped = stack.enter_context(pa.memory_map(str(item), "r"))
                tables.append(pa.ipc.open_file(mapped).read_all())
            if file.num_row_groups != len(tables) or any(
                file.metadata.row_group(group).num_rows != table.num_rows
                for group, table in enumerate(tables)
            ):
                raise Rejection("storage_comparison_mismatch")
            scan = _Scan()
            for group, expected in enumerate(tables):
                position = 0
                for batch in file.iter_batches(
                    batch_size=batch_rows, row_groups=[group], use_threads=False
                ):
                    if time.monotonic() >= deadline:
                        raise Rejection("snapshot_deadline")
                    scan.batch(batch, expected.slice(position, batch.num_rows))
                    position += batch.num_rows
                if position != expected.num_rows:
                    raise Rejection("storage_comparison_mismatch")
            scan.finish()
            if scan.failure is not None:
                raise Rejection(scan.failure)
            if not scan.membership:
                raise Rejection("empty_snapshot_not_publishable")
            manifest = json.dumps(scan.membership, sort_keys=True, separators=(",", ":")).encode()
            verified: dict[str, int | str] = {
                "schema_sha256": schema_hash(),
                "rows": scan.rows,
                "profiles": len(scan.membership),
                "membership_sha256": hashlib.sha256(manifest).hexdigest(),
            }
            table = pa.concat_tables(tables)
            comparison = storage_comparison(table, path.stat().st_size)
            if comparison["rows"] != verified["rows"]:
                raise Rejection("storage_comparison_mismatch")
            del table, tables
        return verified, comparison
    except Rejection:
        raise
    except (ValueError, KeyError, TypeError, OSError, pa.ArrowException):
        raise Rejection("invalid_parquet") from None


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

    Uncertified, the first payload receives the full scientific/scalar/hash
    verification. write_snapshot returns a verifier already certified for the exact
    digest and byte count it verified, so every payload is only byte-count/SHA/schema/
    row-group/count checked; equal whole-object SHA proves identical certified profile
    membership/content. No payload/rows are cached. New intent/process/recovery must
    certify again: the certificate does not cross a process.
    """

    def __init__(
        self,
        digest: str,
        byte_count: int,
        evidence: Mapping[str, Any],
        *,
        deadline: float,
        budget_factory: Callable[[], AbstractContextManager[CanonicalBudget]],
        certified: bool = False,
    ) -> None:
        self.digest, self.byte_count = digest, byte_count
        self.expected = {
            name: evidence[name]
            for name in ("schema_sha256", "rows", "profiles", "membership_sha256")
        }
        self.deadline, self.budget_factory = deadline, budget_factory
        self._certified = certified

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
            except Rejection:
                raise
            except (OSError, ValueError, pa.ArrowException):
                raise Rejection("invalid_parquet") from None
        return dict(self.expected)
