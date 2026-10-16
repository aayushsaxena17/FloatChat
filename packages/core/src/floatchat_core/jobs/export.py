"""Export production (ADR-0080): DuckDB over the verified parts, one row per level.

The writer owns a locked DuckDB connection whose ``allowed_directories`` are the part cache
and a private export directory; external access is off, so ``COPY ... TO`` can reach nothing
else. Members (the profiles the plan selects) come from PostgreSQL through the query login;
the levels come from the Parquet parts; the qc-policy-v1 CASE picks the exported value and
the audit columns stay beside it.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..ingestion.planning import Interval
from ..query import compile_sql, provenance
from ..query.cache import PartCache
from ..query.catalogue import Coverage, EnvironmentInfo, translate_error
from ..query.compile_duckdb import PART_NAME
from ..query.errors import QueryError
from ..query.geography import ResolvedGeography
from ..query.plan import QueryPlan
from ..query.policy import duck_value
from .artefacts import object_key
from .model import MANIFEST_SCHEMA, Job, JobLimits
from .runner import ArtefactSpec

log = logging.getLogger("floatchat.jobs.export")

HEADER_COLUMNS = (
    "profile_id",
    "platform_number",
    "cycle_number",
    "direction",
    "observed_at",
    "longitude",
    "latitude",
    "level_index",
)
AUDIT_SUFFIXES = ("_original", "_adjusted", "_qc", "_adjusted_qc", "_data_mode")
UNITS = {"pressure": "dbar", "temperature": "degree_C", "salinity": "1"}
MEMBERS_SCHEMA = pa.schema(
    [
        pa.field("profile_id", pa.string(), nullable=False),
        pa.field("profile_hash", pa.string(), nullable=False),
        pa.field("platform_number", pa.string(), nullable=False),
        pa.field("cycle_number", pa.int64()),
        pa.field("direction", pa.string()),
        pa.field("observed_at", pa.timestamp("us")),
        pa.field("longitude", pa.float64()),
        pa.field("latitude", pa.float64()),
    ]
)
PART_READ_COLUMNS = (
    "profile_id",
    "profile_hash",
    "level_index",
    *(
        f"{v}{s}"
        for v in ("pressure", "temperature", "salinity")
        for s in ("", "_adjusted", "_qc", "_adjusted_qc", "_data_mode")
    ),
)
Upload = Callable[[str, Path], None]


def export_columns(plan: QueryPlan) -> list[str]:
    columns = list(HEADER_COLUMNS)
    for variable in plan.ordered_variables:
        columns.append(variable)
        columns.extend(variable + suffix for suffix in AUDIT_SUFFIXES)
    return columns


def _part_type(column: str) -> str:
    if column == "level_index":
        return "INTEGER"
    if column.endswith(("_qc", "_adjusted_qc", "_data_mode")) or column in (
        "profile_id",
        "profile_hash",
    ):
        return "VARCHAR"
    return "DOUBLE"


def export_select(plan: QueryPlan, *, empty: bool = False) -> tuple[str, dict[str, Any]]:
    """The SELECT behind every export (fixed template, named parameters).

    With ``empty`` the parts CTE is a typed empty relation: an export over no committed part
    still produces a file with the right header and schema.
    """
    policy = plan.qc_policy
    parameters: dict[str, Any] = {}
    selects = [
        "m.profile_id",
        "m.platform_number",
        "m.cycle_number",
        "m.direction",
        "m.observed_at",
        "m.longitude",
        "m.latitude",
        "p.level_index",
    ]
    for variable in plan.ordered_variables:
        # raw exports the original value regardless of QC (qc-policy-v1); the other two
        # policies select through the same CASE the query engine uses.
        selected = f"p.{variable}" if policy == "raw" else duck_value(variable, policy)
        selects.append(f"({selected}) AS {variable}")
        selects.append(f"p.{variable} AS {variable}_original")
        selects.append(f"p.{variable}_adjusted AS {variable}_adjusted")
        selects.append(f"p.{variable}_qc AS {variable}_qc")
        selects.append(f"p.{variable}_adjusted_qc AS {variable}_adjusted_qc")
        selects.append(f"p.{variable}_data_mode AS {variable}_data_mode")
    where = ["m.profile_id IS NOT NULL"]
    if plan.depth_dbar is not None:
        depth_policy = "mode_selected" if policy == "raw" else policy
        where.append(f"({duck_value('pressure', depth_policy)}) BETWEEN $depth_min AND $depth_max")
        parameters["depth_min"] = plan.depth_dbar.min
        parameters["depth_max"] = plan.depth_dbar.max
    if empty:
        typed = ", ".join(f"CAST(NULL AS {_part_type(c)}) AS {c}" for c in PART_READ_COLUMNS)
        parts_cte = f"WITH parts AS (SELECT {typed} WHERE false) "
    else:
        parts_cte = (
            f"WITH parts AS (SELECT {', '.join(PART_READ_COLUMNS)} "
            "FROM read_parquet($parts_files)) "
        )
    sql = (
        parts_cte + f"SELECT {', '.join(selects)} FROM parts p JOIN members m"
        " ON p.profile_id = m.profile_id AND p.profile_hash = m.profile_hash"
        f" WHERE {' AND '.join(where)} ORDER BY m.observed_at, m.profile_id, p.level_index"
    )
    return sql, parameters


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class WrittenFile:
    path: Path
    bytes: int
    sha256: str
    row_count: int
    profile_count: int


class ExportWriter:
    """Writes the data file, the manifest and the provenance sidecar, then uploads them."""

    def __init__(
        self,
        *,
        query_engine: Engine,
        cache: PartCache,
        export_directory: Path,
        upload: Upload,
        limits: JobLimits | None = None,
        application_commit: str = "unknown",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.query_engine = query_engine
        self.cache = cache
        self.directory = export_directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.upload = upload
        self.limits = limits or JobLimits()
        self.application_commit = application_commit
        self.clock = clock

    # -- members and parts -----------------------------------------------------------------

    def members(
        self, plan: QueryPlan, geography: ResolvedGeography, coverage: Coverage
    ) -> pa.Table:
        statement = compile_sql.export_members_statement(plan, geography)
        try:
            with self.query_engine.connect() as connection:
                rows = connection.execute(statement).all()
        except SQLAlchemyError as error:
            raise translate_error(error) from None
        allowed = {
            (str(entry["profile_id"]), str(entry["hash"]))
            for manifest in coverage.manifests.values()
            for entry in manifest
        }
        kept = [row for row in rows if (row.profile_id, row.profile_hash) in allowed]
        return pa.Table.from_pydict(
            {
                "profile_id": [row.profile_id for row in kept],
                "profile_hash": [row.profile_hash for row in kept],
                "platform_number": [row.platform_number for row in kept],
                "cycle_number": [row.cycle_number for row in kept],
                "direction": [row.direction for row in kept],
                "observed_at": [
                    row.observed_at.astimezone(UTC).replace(tzinfo=None) for row in kept
                ],
                "longitude": [row.longitude for row in kept],
                "latitude": [row.latitude for row in kept],
            },
            schema=MEMBERS_SCHEMA,
        )

    def _connection(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(
            database=":memory:",
            config={
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
                "memory_limit": f"{self.limits.export_memory_mib}MiB",
                "threads": str(self.limits.export_threads),
            },
        )
        cache = str(self.cache.directory.resolve()).replace("'", "''") + "/"
        out = str(self.directory).replace("'", "''") + "/"
        connection.execute(f"SET allowed_directories = ['{cache}', '{out}']")
        # Sorting a multi-year export under the memory limit spills to disk; the spill
        # directory must be one of the allowed directories (DuckDB would otherwise try
        # ".tmp" in the working directory and fail with an I/O error).
        spill = self.directory / ".duckdb-tmp"
        spill.mkdir(parents=True, exist_ok=True)
        connection.execute(f"SET temp_directory = '{str(spill).replace(chr(39), chr(39) * 2)}'")
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        return connection

    def _verified(self, paths: Sequence[Path]) -> list[str]:
        files = []
        for path in paths:
            resolved = Path(path).resolve()
            if resolved.parent != self.cache.directory.resolve() or not PART_NAME.match(
                resolved.name
            ):
                raise QueryError("internal_error", message="A part path is outside the cache.")
            files.append(str(resolved))
        return files

    def write(
        self, plan: QueryPlan, members: pa.Table, paths: Sequence[Path], fmt: str, name: str
    ) -> WrittenFile:
        sql, parameters = export_select(plan, empty=not paths)
        if paths:
            parameters["parts_files"] = self._verified(paths)
        target = self.directory / name
        if target.exists():
            target.unlink()
        literal = str(target).replace("'", "''")
        options = (
            "FORMAT parquet, COMPRESSION zstd" if fmt == "parquet" else "FORMAT csv, HEADER true"
        )
        connection = self._connection()
        try:
            connection.register("members", members)
            connection.execute(f"COPY ({sql}) TO '{literal}' ({options})", parameters)
            counted = connection.execute(
                f"SELECT count(*), count(DISTINCT profile_id) FROM ({sql})", parameters
            ).fetchone()
            rows, profiles = int(counted[0]), int(counted[1])  # type: ignore[index]
        except duckdb.OutOfMemoryException:
            raise QueryError(
                "cost_over_budget", message="The export exceeded the worker's memory."
            ) from None
        except duckdb.Error as error:
            # The worker log keeps DuckDB's own text (paths, never credentials); the job
            # record carries the class only.
            log.warning("export COPY failed: %s: %s", type(error).__name__, str(error)[:500])
            raise QueryError(
                "execution_failed", message=f"DuckDB: {type(error).__name__}"
            ) from None
        finally:
            connection.close()
        return WrittenFile(target, target.stat().st_size, _sha256(target), rows, profiles)

    # -- the whole export ------------------------------------------------------------------

    def export(
        self,
        job: Job,
        plan: QueryPlan,
        geography: ResolvedGeography,
        coverage: Coverage,
        environment: EnvironmentInfo,
    ) -> list[ArtefactSpec]:
        fmt = str(job.request.get("format", "parquet"))
        parts = [part for slot in coverage.covered for part in slot.parts]
        fill = self.cache.fill(
            [(part.key, part.sha256, part.byte_count) for part in parts],
            workers=self.limits.object_fetch_workers,
            deadline_seconds=self.limits.object_fetch_seconds,
        )
        members = self.members(plan, geography, coverage)
        stem = f"floatchat-export-{job.id[:8]}"
        written = self.write(plan, members, fill.paths, fmt, f"{stem}.{fmt}")
        created = self.clock()
        execution = {
            "source": "duckdb",
            "members": members.num_rows,
            "objects_fetched": fill.fetched,
            "objects_reused": fill.reused,
            "object_fetch_ms": round(fill.seconds * 1000, 1),
            "partitions": [{"id": str(part.partition_id), "sha256": part.sha256} for part in parts],
            "rows": written.row_count,
        }
        sidecar = provenance.build(
            plan=plan,
            environment=environment,
            geography=geography,
            coverage=coverage,
            execution=execution,
            rows=[[written.sha256]],
            application_commit=self.application_commit,
            transformation=(
                f"export {fmt}: one row per level, {plan.qc_policy} values with audit columns"
            ),
        )
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "job_id": job.id,
            "request": job.request,
            "plan": plan.canonical(),
            "plan_sha256": plan.plan_sha256,
            "format": fmt,
            "filename": written.path.name,
            "bytes": written.bytes,
            "sha256": written.sha256,
            "row_count": written.row_count,
            "profile_count": written.profile_count,
            "columns": [
                {
                    "name": name,
                    "unit": UNITS.get(name.split("_")[0])
                    if name.split("_")[0] in UNITS and not name.endswith(("_qc", "_data_mode"))
                    else None,
                }
                for name in export_columns(plan)
            ],
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "expires_at": None,
            "coverage": coverage.describe(),
            "partitions": execution["partitions"],
            "environment": environment.describe(),
            "citation": dict(provenance.ATTRIBUTION),
            "application_commit": self.application_commit,
            "interval": _interval(Interval(plan.time_range.start, plan.time_range.end)),
        }
        manifest_path = self.directory / f"{stem}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n")
        provenance_path = self.directory / f"{stem}.provenance.json"
        provenance_path.write_text(
            json.dumps(sidecar, indent=2, sort_keys=True, default=str) + "\n"
        )
        specs = []
        for path, role, format_name in (
            (written.path, "data", fmt),
            (manifest_path, "manifest", "json"),
            (provenance_path, "provenance", "json"),
        ):
            key = object_key(job.id, path.name)
            self.upload(key, path)
            specs.append(
                ArtefactSpec(
                    format=format_name,
                    role=role,
                    object_key=key,
                    bytes=path.stat().st_size,
                    sha256=_sha256(path) if path != written.path else written.sha256,
                    row_count=written.row_count if role == "data" else 0,
                    profile_count=written.profile_count if role == "data" else 0,
                    manifest=manifest
                    if role == "data"
                    else {"schema": MANIFEST_SCHEMA, "role": role},
                )
            )
        for path in (written.path, manifest_path, provenance_path):
            path.unlink(missing_ok=True)
        return specs


def _interval(interval: Interval) -> dict[str, str]:
    return {
        "start": interval.start.isoformat().replace("+00:00", "Z"),
        "end": interval.end.isoformat().replace("+00:00", "Z"),
    }


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
