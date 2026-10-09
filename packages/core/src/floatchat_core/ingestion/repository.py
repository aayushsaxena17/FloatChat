"""Restricted PostgreSQL access; no application-side target-table DML or DDL."""

import hashlib
import io
import json
import tempfile
import time
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .argovis import GDAC_SOURCE_CONTRACT, SOURCE_CONTRACT, Profile, policy_versions
from .coverage import Receipt, resolve
from .identity import StoredIdentity
from .numeric import CanonicalBudget, Rejection, ScientificNumber
from .objects import (
    MAX_OBJECT_BYTES,
    CatalogueRecord,
    CatalogueSnapshot,
    ObjectStore,
    publish_verified,
)
from .parquet import SCHEMA_VERSION, write_snapshot
from .planning import (
    GEOMETRY_SHA256,
    RUN_POLICY,
    Interval,
    RunPolicy,
    Tile,
    month_start,
    plan,
    timestamp,
)
from .revisions import Revision
from .spool import merge_parts, parse_revision
from .workflow import (
    MEASUREMENT_COLUMNS,
    StoredScience,
    StoredState,
    evidence_json,
    snapshot_certificate,
)

# SQL owner-slot function of each source population (never interpolated from input).
OWNER_FUNCTIONS = {"argovis": "app.owner_slot", "gdac": "app.gdac_owner_slot"}

SAFE_DATABASE_CATEGORIES = frozenset(
    {
        "publication_fenced",
        "run_fenced",
        "claim_denied",
        "controller_claim_denied",
        "environment_concurrency_limit",
        "revision_conflict",
        "identity_conflict",
        "fallback_observation_time_correction",
        "publication_base_changed",
        "scientific_hash_mismatch",
        "candidate_content_mismatch",
        "missing_affected_slot",
        "raw_provenance_mismatch",
        "stored_snapshot_membership_mismatch",
        "snapshot_count_or_schema_mismatch",
        "coverage_disposition_mismatch",
        "http_retry_exhausted",
        "publication_budget_exhausted",
        "commit_reserve_exhausted",
        "unsafe_environment",
        "outside_rolling_window",
        "unsafe_run_configuration",
        "controller_busy",
        "canonical_output_limit",
        "canonical_reservation_final",
        "invalid_state_transition",
        "chunk_split_denied",
        "invalid_split_coverage",
        "immutable_input_descriptor",
        "input_must_precede_plan",
        "incomplete_initial_plan",
        "unsafe_measurement_month",
        "measurement_partition_mismatch",
        "staging_resource_limit",
        "invalid_replay_predecessor",
        "invalid_replay_plan",
        "candidate_outside_eligibility",
        "duplicate_publication_slot",
        "invalid_audit_sample",
        "invalid_level_count",
        "invalid_level_index",
        "invalid_metadata_cache_entry",
        "invalid_publication_evidence",
        "invalid_recorded_origin",
        "invalid_ticket_kind",
        "invalid_ticket_worker",
        "landing_retry_exhausted",
        "level_set_mismatch",
        "measurement_content_mismatch",
        "measurement_count_limit",
        "missing_coverage_receipt",
        "profile_count_limit",
        "unverified_final_object",
    }
)


@dataclass(frozen=True)
class Authority:
    run: uuid.UUID
    chunk: uuid.UUID
    epoch: int
    fence: int

    @property
    def arguments(self) -> tuple[Any, ...]:
        return self.run, self.chunk, self.epoch, self.fence


@dataclass(frozen=True)
class SlotState:
    """Catalogue version of a slot and, when requested, its stored population now."""

    version: int
    members: int | None = None
    selected: int | None = None


class Repository:
    def __init__(self, database_url: str) -> None:
        try:
            address = urlsplit(database_url)
            if address.scheme not in ("postgresql", "postgres") or address.hostname not in (
                "db",
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                raise ValueError
            self.connection: Any = psycopg.connect(
                database_url, connect_timeout=3, autocommit=True, row_factory=dict_row
            )
        except (ValueError, psycopg.Error):
            raise Rejection("local_ingestion_database_unavailable") from None

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(
        self,
        *,
        remaining: float = 60,
        publication: bool = False,
        readonly_snapshot: bool = False,
    ) -> Iterator[Any]:
        reserve = 1 if publication else 0
        milliseconds = int(min(60, remaining - reserve) * 1000)
        if milliseconds < 1:
            raise Rejection("database_deadline")
        started = time.monotonic()
        try:
            with self.connection.transaction():
                with self.connection.cursor() as cursor:
                    if readonly_snapshot:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    cursor.execute(
                        "SELECT set_config('statement_timeout',%s,true)", (str(milliseconds),)
                    )
                    # stage1-v4: concurrent acquire threads and process workers queue on the
                    # run row behind a publication commit (seconds); a lock wait is bounded by
                    # the same per-transaction bound as every statement, not a fixed 5 s.
                    cursor.execute(
                        "SELECT set_config('lock_timeout',%s,true)", (str(milliseconds),)
                    )
                    cursor.execute(
                        "SELECT set_config('transaction_timeout',%s,true)", (str(milliseconds),)
                    )
                    yield cursor
                    if time.monotonic() - started >= milliseconds / 1000:
                        raise Rejection("database_deadline")
        except psycopg.Error as error:
            message = error.diag.message_primary
            category = message if message in SAFE_DATABASE_CATEGORIES else "database_failure"
            resource = None
            detail = error.diag.message_detail
            if category == "canonical_output_limit" and detail and len(detail) <= 1024:
                try:
                    resource = json.loads(detail)
                except (ValueError, TypeError):
                    pass
            # Rejection validates the complete fixed-shape numeric record. Older
            # databases without DETAIL remain unscoped; never infer or backfill.
            raise Rejection(category, resource=resource) from None

    def run(self, identifier: uuid.UUID) -> dict[str, Any]:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM app.ingestion_run WHERE id=%s", (identifier,))
            row = cursor.fetchone()
            if row is None:
                raise Rejection("unknown_run")
            return dict(row)

    def admit(
        self,
        environment: uuid.UUID,
        request: uuid.UUID,
        mode: str,
        interval: Interval | None,
        limits: dict[str, int],
        *,
        scheduled: bool = False,
        input_kind: str | None = None,
        descriptor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # A gdac run carries the gdac-core-v1 contract; the SQL derives the scope from it.
        contract = GDAC_SOURCE_CONTRACT if input_kind == "gdac" else SOURCE_CONTRACT
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.admit_run(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS result",
                (
                    environment,
                    request,
                    mode,
                    scheduled,
                    None if interval is None else interval.start,
                    None if interval is None else interval.end,
                    limits["execution_seconds"],
                    GEOMETRY_SHA256,
                    Jsonb(policy_versions(contract)),
                    Jsonb({**limits, **RUN_POLICY}),
                ),
            )
            result = dict(cursor.fetchone()["result"])
            if result["kind"] == "created" and input_kind is not None:
                cursor.execute(
                    "SELECT app.persist_input(%s,1,%s,%s)",
                    (uuid.UUID(result["run_id"]), input_kind, Jsonb(descriptor or {})),
                )
            return result

    def environment(self, identifier: uuid.UUID) -> dict[str, Any]:
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute("SELECT * FROM app.ingestion_environment WHERE id=%s", (identifier,))
            row = cursor.fetchone()
            if row is None:
                raise Rejection("unsafe_environment")
            return dict(row)

    def validate_replay(
        self,
        environment: uuid.UUID,
        mode: str,
        interval: Interval,
        predecessor: uuid.UUID,
        source_contract: str = SOURCE_CONTRACT,
    ) -> None:
        """The predecessor must be complete and carry the policy versions of its own source
        contract (the new run's contract, Argovis by default)."""
        row = self.run(predecessor)
        if (
            not row["closed"]
            or row["state"] != "complete"
            or row["environment_id"] != environment
            or row["mode"] != mode
            or row["requested_start"] != interval.start
            or row["requested_end"] != interval.end
            or row["policy_versions"] != policy_versions(source_contract)
            or row["geometry_sha256"] != GEOMETRY_SHA256
        ):
            raise Rejection("invalid_replay_predecessor")

    def chunk(self, identifier: uuid.UUID) -> dict[str, Any]:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM app.ingestion_chunk WHERE id=%s", (identifier,))
            row = cursor.fetchone()
            if row is None:
                raise Rejection("unknown_chunk")
            return dict(row)

    def ticket(self, authority: Authority, kind: str = "process") -> uuid.UUID:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.processing_ticket(%s,%s,%s,%s,%s) AS id", (*authority.arguments, kind)
            )
            return cursor.fetchone()["id"]  # type: ignore[no-any-return]

    def start_worker(self, run: uuid.UUID, chunk: uuid.UUID, ticket: uuid.UUID) -> Authority | None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM app.processing_ticket WHERE id=%s AND run_id=%s AND chunk_id=%s",
                (ticket, run, chunk),
            )
            row = cursor.fetchone()
            if row is None:
                raise Rejection("unknown_processing_ticket")
            cursor.execute("SELECT app.start_worker(%s) AS started", (ticket,))
            if not cursor.fetchone()["started"]:
                return None
            return Authority(run, chunk, row["control_epoch"], row["fence"])

    def recorded_reserve(
        self, authority: Authority, key: str, role: str, parameters: dict[str, str], origin: str
    ) -> uuid.UUID:
        attempt = uuid.uuid4()
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.reserve_recorded_attempt(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, attempt, key, role, Jsonb(parameters), origin),
            )
        return attempt

    def split(self, authority: Authority) -> None:
        from .planning import PlannedChunk, split

        row = self.chunk(authority.chunk)
        children = split(
            PlannedChunk(
                Interval(row["requested_start"], row["requested_end"]), Tile(**row["tile"])
            )
        )
        values = [
            {
                "id": str(uuid.uuid4()),
                "key": str(uuid.uuid4()),
                "start": item.interval.start.isoformat(),
                "end": item.interval.end.isoformat(),
                "tile": {
                    "west": item.tile.west,
                    "south": item.tile.south,
                    "width": item.tile.width,
                    "height": item.tile.height,
                },
            }
            for item in children
        ]
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.split_chunk(%s,%s,%s,%s,%s)", (*authority.arguments, Jsonb(values))
            )

    def persist_plan(self, run: uuid.UUID, epoch: int) -> None:
        row = self.run(run)
        policy = RunPolicy(row["run_reference_time_utc"], row["mode"], str(row["environment_id"]))
        interval = Interval(row["requested_start"], row["requested_end"])
        policy.validate(interval)
        inputs = self.input(run)
        if inputs is not None and inputs["kind"] == "replay":
            with self.transaction() as cursor:
                cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
                cursor.execute("SELECT app.persist_replay_plan(%s,%s)", (run, epoch))
            return
        chunks = plan(interval)
        values = [
            {
                "id": str(uuid.uuid4()),
                "start": item.interval.start.isoformat(),
                "end": item.interval.end.isoformat(),
                "key": item.interval.start.isoformat()
                + "/"
                + item.interval.end.isoformat()
                + "/"
                + item.tile.key,
                "tile": {
                    "west": item.tile.west,
                    "south": item.tile.south,
                    "width": item.tile.width,
                    "height": item.tile.height,
                },
            }
            for item in chunks
        ]
        with self.transaction() as cursor:
            cursor.execute("SELECT app.persist_baseline(%s,%s)", (run, epoch))
            cursor.execute("SELECT app.persist_plan(%s,%s,%s)", (run, epoch, Jsonb(values)))

    def chunks(self, run: uuid.UUID) -> tuple[dict[str, Any], ...]:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM app.ingestion_chunk WHERE run_id=%s "
                "ORDER BY requested_start,logical_chunk_key",
                (run,),
            )
            return tuple(dict(row) for row in cursor.fetchall())

    def start_controller(self, run: uuid.UUID, instance: uuid.UUID) -> int | None:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.start_controller(%s,%s) AS epoch", (run, instance))
            result = cursor.fetchone()["epoch"]
            return None if result is None else int(result)

    def controller_heartbeat(self, run: uuid.UUID, epoch: int) -> None:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.controller_heartbeat(%s,%s)", (run, epoch))

    def extend_unstarted_leases(self, run: uuid.UUID, epoch: int) -> int:
        """Keep the lease of chunks whose ticket nobody has started (migration 0012)."""
        with self.transaction() as cursor:
            cursor.execute("SELECT app.extend_unstarted_leases(%s,%s) AS n", (run, epoch))
            return int(cursor.fetchone()["n"])

    def heartbeat(self, authority: Authority) -> None:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.heartbeat(%s,%s,%s,%s)", authority.arguments)

    def persist_input(
        self, run: uuid.UUID, epoch: int, kind: str, descriptor: dict[str, Any]
    ) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.persist_input(%s,%s,%s,%s)", (run, epoch, kind, Jsonb(descriptor))
            )

    def input(self, run: uuid.UUID) -> dict[str, Any] | None:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM app.ingestion_input WHERE run_id=%s", (run,))
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def open_runs(self) -> tuple[uuid.UUID, ...]:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT id FROM app.ingestion_run WHERE NOT closed ORDER BY created_at_actual_utc"
            )
            return tuple(row["id"] for row in cursor.fetchall())

    def canonical_reserve(self, authority: Authority) -> uuid.UUID:
        work = uuid.uuid4()
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.reserve_canonical(%s,%s,%s,%s,%s)", (*authority.arguments, work)
            )
        return work

    def canonical_finish(self, authority: Authority, work: uuid.UUID, count: int) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.finish_canonical(%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, work, count),
            )

    @contextmanager
    def canonical_budget(self, authority: Authority) -> Iterator[CanonicalBudget]:
        work = self.canonical_reserve(authority)
        budget = CanonicalBudget()
        try:
            yield budget
        finally:
            # Charge partial/rejected output. Process death leaves the full
            # reservation for conservative takeover; it cannot reset the budget.
            self.canonical_finish(authority, work, min(budget.run_used, 16 * 1024**2))

    def http_reserve(
        self, authority: Authority, key: str, role: str, parameters: dict[str, str]
    ) -> tuple[uuid.UUID, int]:
        attempt = uuid.uuid4()
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.reserve_http_attempt(%s,%s,%s,%s,%s,%s,%s,%s) AS ordinal",
                (*authority.arguments, attempt, key, role, Jsonb(parameters)),
            )
            ordinal = int(cursor.fetchone()["ordinal"])
        return attempt, ordinal

    def account_received(self, authority: Authority, attempt: uuid.UUID, count: int) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.account_bytes(%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, attempt, count),
            )

    def finish_attempt(
        self,
        authority: Authority,
        attempt: uuid.UUID,
        disposition: str,
        status: int | None = None,
        error: str | None = None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.finish_attempt(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    *authority.arguments,
                    attempt,
                    disposition,
                    status,
                    error,
                    None if manifest is None else Jsonb(manifest),
                ),
            )

    @contextmanager
    def upstream_slot(self, authority: Authority, deadline: float, slot: int = 1) -> Iterator[None]:
        """Session lock outlives lease expiry; one actual HTTP request per slot at once.

        Slot 1 is the stage1-v3 single credentialed request; stage1-v4 acquire
        threads hold slots 1..N (ingestion_environment.upstream_slots). All admitted
        runs share the single physical environment. A crashed client loses this
        session lock on disconnect; a live old HTTP call retains it. Do not keep an
        open PostgreSQL transaction over network I/O.
        """
        if not 1 <= slot <= 64:
            raise Rejection("invalid_upstream_slot")
        locked = False
        try:
            while not locked:
                if time.monotonic() >= deadline:
                    raise Rejection("upstream_slot_deadline")
                self.heartbeat(authority)
                with self.transaction() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(164993423,%s) AS locked", (slot,))
                    locked = bool(cursor.fetchone()["locked"])
                if not locked:
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
            yield
        finally:
            if locked:
                with self.transaction() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(164993423,%s)", (slot,))

    # stage1-v4 queue and cache access (SQL in migration 0012, package D).
    def claim_ticket(self, kind: str, worker: str) -> dict[str, Any] | None:
        """Claim one unstarted ticket of `kind` with SKIP LOCKED; None when the queue is empty."""
        if kind not in ("acquire", "process"):
            raise Rejection("invalid_ticket_kind")
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM app.claim_ticket(%s,%s)", (kind, worker))
            row = cursor.fetchone()
            return None if row is None or row.get("id") is None else dict(row)

    def metadata_cache_get(self, environment: uuid.UUID, pointer: str) -> dict[str, Any] | None:
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT c.*,m.object_key,m.sha256,m.bytes,m.versions,m.http_status "
                "FROM app.float_metadata_cache c JOIN app.raw_manifest m ON m.id=c.raw_manifest_id "
                "WHERE c.environment_id=%s AND c.pointer=%s",
                (environment, pointer),
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def metadata_cache_put(
        self,
        environment: uuid.UUID,
        pointer: str,
        raw_manifest: uuid.UUID,
        run: uuid.UUID,
        retrieved_at: datetime,
    ) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.metadata_cache_put(%s,%s,%s,%s,%s)",
                (environment, pointer, raw_manifest, run, retrieved_at),
            )

    def verified_landing(self, authority: Authority, key: str) -> dict[str, Any] | None:
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT m.* FROM app.raw_manifest m JOIN app.ingestion_attempt a "
                "ON a.id=m.attempt_id WHERE a.chunk_id=%s AND a.logical_request_key=%s "
                "AND a.disposition='verified_raw' AND a.attempt_number>coalesce("
                "(SELECT through_attempt FROM app.landing_reset WHERE chunk_id=a.chunk_id),0) "
                "ORDER BY a.attempt_number DESC LIMIT 1",
                (authority.chunk, key),
            )
            row = cursor.fetchone()
            return None if row is None else dict(row)

    def restart_selection(self, authority: Authority) -> None:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.restart_selection(%s,%s,%s,%s)", authority.arguments)

    def claim(self, run: uuid.UUID, chunk: uuid.UUID, epoch: int) -> Authority | None:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.claim_chunk(%s,%s,%s) AS fence", (run, chunk, epoch))
            fence = cursor.fetchone()["fence"]
            return None if fence is None else Authority(run, chunk, epoch, fence)

    def transition(
        self, authority: Authority, state: str, reason: str, evidence: dict[str, Any] | None = None
    ) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.transition_chunk(%s,%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, state, reason, Jsonb(evidence or {})),
            )

    def stage_candidates(self, authority: Authority, candidates: Iterable[dict[str, Any]]) -> None:
        """Replace this fence's staged candidates: slim rows, levels travel in stage_levels."""
        with self.transaction() as cursor:
            cursor.execute("SELECT app.clear_staging(%s,%s,%s,%s)", authority.arguments)
            with cursor.copy(
                "COPY app.ingestion_staging(run_id,chunk_id,fence,occurrence_index,candidate) "
                "FROM STDIN"
            ) as copy:
                for index, candidate in enumerate(candidates):
                    if index >= 2000:
                        raise Rejection("profile_count_limit")
                    occurrence = candidate.get("occurrence_index", index)
                    if type(occurrence) is not int or not 0 <= occurrence < 2000:
                        raise Rejection("invalid_occurrence_index")
                    data = json.dumps(candidate, allow_nan=False)
                    if len(data) > 64 * 1024**2:
                        raise Rejection("staging_resource_limit")
                    copy.write_row((*authority.arguments[:2], authority.fence, occurrence, data))

    def stage_levels(self, authority: Authority, tables: "pa.Table | Iterable[pa.Table]") -> None:
        """Binary COPY of typed level rows into app.measurement_staging, one transaction.

        Tables carry occurrence_index, level_index and the 36 value columns (extra
        columns are ignored). Call after stage_candidates, which clears earlier rows.
        """
        columns = ("occurrence_index", "level_index", *(name for name, _ in MEASUREMENT_COLUMNS))
        types = ["uuid", "uuid", "int8", "int4", "int4", *(kind for _, kind in MEASUREMENT_COLUMNS)]
        if isinstance(tables, pa.Table):
            tables = (tables,)
        total = 0
        with self.transaction() as cursor:
            with cursor.copy(
                "COPY app.measurement_staging(run_id,chunk_id,fence,"
                + ",".join(columns)
                + ") FROM STDIN WITH (FORMAT BINARY)"
            ) as copy:
                copy.set_types(types)
                for table in tables:
                    if not set(columns) <= set(table.schema.names):
                        raise Rejection("invalid_level_table")
                    total += table.num_rows
                    if total > 2_000_000:
                        raise Rejection("chunk_scientific_resource_limit")
                    fixed = (authority.run, authority.chunk, authority.fence)
                    for row in zip(
                        *(table.column(name).to_pylist() for name in columns), strict=True
                    ):
                        copy.write_row((*fixed, *row))

    @staticmethod
    def identity_row(row: dict[str, Any]) -> StoredIdentity:
        key = (
            None
            if not row["fallback_complete"]
            else (
                row["platform_number"],
                row["cycle_number"],
                row["direction"],
                row["identity_observed_at"].astimezone(UTC).isoformat(timespec="microseconds"),
                row["observation_segment"],
            )
        )
        return StoredIdentity(
            row["id"],
            row["platform_number"],
            row["source_profile_id"],
            row["cycle_number"],
            row["direction"],
            key,
        )

    def identities(self, profile: Profile, source: str = "argovis") -> tuple[StoredIdentity, ...]:
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT p.id,p.source_profile_id,p.cycle_number,p.direction,p.fallback_complete,"
                "p.identity_observed_at,p.observation_segment,f.platform_number "
                "FROM app.argo_profile p "
                "JOIN app.argo_float f ON f.id=p.float_id WHERE p.source=%s AND "
                "((%s::text IS NOT NULL AND p.source_profile_id=%s) OR "
                "(f.platform_number=%s AND p.cycle_number=%s AND p.direction=%s)) "
                "ORDER BY p.id LIMIT 100001",
                (
                    source,
                    profile.source_profile_id,
                    profile.source_profile_id,
                    profile.platform,
                    profile.cycle,
                    profile.direction,
                ),
            )
            rows = cursor.fetchall()
            if len(rows) > 100000:
                raise Rejection("identity_registry_limit")
            return tuple(self.identity_row(dict(row)) for row in rows)

    def identities_batch(
        self, profiles: Sequence[Profile], source: str = "argovis"
    ) -> dict[str, tuple[StoredIdentity, ...]]:
        """Stored identities matching each profile (stable id or platform/cycle/direction).

        One query for the whole chunk; per profile the rows are the same ones identities()
        returns, in id order, keyed by Profile.identity.
        """
        if not profiles:
            return {}
        stable = sorted({p.source_profile_id for p in profiles if p.source_profile_id is not None})
        keys = sorted({(p.platform, p.cycle, p.direction) for p in profiles if p.cycle is not None})
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT p.id,p.source_profile_id,p.cycle_number,p.direction,p.fallback_complete,"
                "p.identity_observed_at,p.observation_segment,f.platform_number "
                "FROM app.argo_profile p "
                "JOIN app.argo_float f ON f.id=p.float_id WHERE "
                "(p.source_profile_id=ANY(%s) OR (f.platform_number,p.cycle_number,p.direction) "
                "IN (SELECT * FROM unnest(%s::text[],%s::bigint[],%s::text[]))) "
                "AND p.source=%s ORDER BY p.id LIMIT 100001",
                (stable, [k[0] for k in keys], [k[1] for k in keys], [k[2] for k in keys], source),
            )
            rows = cursor.fetchall()
        if len(rows) > 100000:
            raise Rejection("identity_registry_limit")
        found = [self.identity_row(dict(row)) for row in rows]
        by_stable: dict[str, list[StoredIdentity]] = {}
        by_key: dict[tuple[str, int | None, str], list[StoredIdentity]] = {}
        for identity in found:
            if identity.source_profile_id is not None:
                by_stable.setdefault(identity.source_profile_id, []).append(identity)
            by_key.setdefault((identity.platform, identity.cycle, identity.direction), []).append(
                identity
            )
        result: dict[str, tuple[StoredIdentity, ...]] = {}
        for profile in profiles:
            matched: dict[uuid.UUID, StoredIdentity] = {}
            if profile.source_profile_id is not None:
                for identity in by_stable.get(profile.source_profile_id, ()):
                    matched[identity.id] = identity
            if profile.cycle is not None:
                for identity in by_key.get(
                    (profile.platform, profile.cycle, profile.direction), ()
                ):
                    matched[identity.id] = identity
            result[profile.identity] = tuple(matched[key] for key in sorted(matched))
        return result

    def science_hashes(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, StoredState]:
        """Hash, source revision and position of stored profiles; no levels, no canonical."""
        if not ids:
            return {}
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT p.id,p.content_hash,p.source_revision,p.observed_at,"
                "p.scientific_content#>>'{longitude,exact}' AS longitude,"
                "p.scientific_content#>>'{latitude,exact}' AS latitude "
                "FROM app.argo_profile p WHERE p.id=ANY(%s)",
                (list(ids),),
            )
            rows = cursor.fetchall()
        return {
            row["id"]: StoredState(
                row["content_hash"],
                parse_revision(row["source_revision"]),
                row["observed_at"],
                None if row["longitude"] is None else Decimal(row["longitude"]),
                None if row["latitude"] is None else Decimal(row["latitude"]),
            )
            for row in rows
        }

    def slot_state(
        self,
        authority: Authority,
        slots: Sequence[str],
        piece: Any,
        *,
        counts: Iterable[str] = (),
        source: str = "argovis",
    ) -> dict[str, SlotState]:
        """Versions of the slots (the publication bases) and, for `counts`, the stored
        population now: all profiles of the slot and those inside the chunk selection.

        One consistent snapshot. The counts predict the receipt dispositions SQL rechecks;
        they are valid only while the slot version is unchanged, which commit verifies.
        """
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT logical_key,slot_version FROM app.logical_partition_slot "
                "WHERE environment_id=(SELECT environment_id FROM app.ingestion_run WHERE id=%s) "
                "AND logical_key=ANY(%s)",
                (authority.run, list(slots)),
            )
            result = {
                row["logical_key"]: SlotState(row["slot_version"]) for row in cursor.fetchall()
            }
            if set(slots) - result.keys():
                raise Rejection("publication_base_changed")
            tile = piece.tile
            for slot in counts:
                cursor.execute(
                    "SELECT count(*) AS members,count(*) FILTER (WHERE "
                    "p.observed_at>=%s AND p.observed_at<%s "
                    "AND (p.scientific_content#>>'{longitude,exact}')::numeric>=%s "
                    "AND ((p.scientific_content#>>'{longitude,exact}')::numeric<%s OR "
                    "(%s=120 AND (p.scientific_content#>>'{longitude,exact}')::numeric=120)) "
                    "AND (p.scientific_content#>>'{latitude,exact}')::numeric>=%s "
                    "AND ((p.scientific_content#>>'{latitude,exact}')::numeric<%s OR "
                    "(%s=30 AND (p.scientific_content#>>'{latitude,exact}')::numeric=30))"
                    ") AS selected FROM app.argo_profile p WHERE p.source=%s AND "
                    + OWNER_FUNCTIONS[source]
                    + "(p.observed_at,"
                    "(p.scientific_content->'longitude'->>'exact')::numeric,"
                    "(p.scientific_content->'latitude'->>'exact')::numeric)=%s",
                    (
                        piece.interval.start,
                        piece.interval.end,
                        tile.west,
                        tile.west + tile.width,
                        tile.west + tile.width,
                        tile.south,
                        tile.south + tile.height,
                        tile.south + tile.height,
                        source,
                        slot,
                    ),
                )
                row = cursor.fetchone()
                result[slot] = replace(
                    result[slot], members=int(row["members"]), selected=int(row["selected"])
                )
        return result

    def ensure_slot(self, authority: Authority, month: datetime, tile: Tile) -> str:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.ensure_slot(%s,%s,%s,%s,%s,%s,%s) AS slot",
                (*authority.arguments, month.date(), tile.west, tile.south),
            )
            return str(cursor.fetchone()["slot"])

    def prepare_intent(
        self,
        authority: Authority,
        intent: uuid.UUID,
        keys: list[str],
        bases: dict[str, int],
        revisions: dict[str, Any],
    ) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.prepare_intent(%s,%s,%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, intent, Jsonb(keys), Jsonb(bases), Jsonb(revisions)),
            )

    def outcomes(self, authority: Authority, outcomes: list[dict[str, Any]]) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.record_profile_outcomes(%s,%s,%s,%s,%s)",
                (*authority.arguments, Jsonb(outcomes)),
            )

    def accounting(self, authority: Authority, evidence: dict[str, Any]) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.record_accounting(%s,%s,%s,%s,%s)",
                (*authority.arguments, Jsonb(evidence)),
            )

    def commit(
        self,
        authority: Authority,
        intent: uuid.UUID,
        generations: list[dict[str, Any]],
        receipts: list[dict[str, Any]],
    ) -> None:
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT state FROM app.ingestion_chunk WHERE id=%s AND run_id=%s",
                (authority.chunk, authority.run),
            )
            chunk = cursor.fetchone()
            if chunk is not None and chunk["state"] == "complete":
                return
        row = self.run(authority.run)
        remaining = (row["work_deadline"] - datetime.now(UTC)).total_seconds()
        # The SQL procedure also checks DB time at entry and immediately before
        # the final updates. The context commits immediately with its reserve.
        with self.transaction(remaining=remaining, publication=True) as cursor:
            cursor.execute(
                "SELECT app.commit_publication(%s,%s,%s,%s,%s,%s,%s)",
                (*authority.arguments, intent, Jsonb(generations), Jsonb(receipts)),
            )

    def compact(
        self, environment: uuid.UUID, logical_key: str, store: ObjectStore, deadline: float
    ) -> str:
        """Merge the active parts of one slot into a snapshot and supersede them.

        Reads the active objects, keeps the rows whose (profile_id, hash) is in the slot
        manifest, writes and verifies one snapshot, then app.compact_slot swaps them in a
        single transaction that also proves the manifest and the active set are unchanged.
        Returns "compacted", or "unchanged" when the slot has no part to merge. Raises
        publication_base_changed if a commit touched the slot meanwhile (retry later).
        """
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT slot_version,membership_manifest FROM app.logical_partition_slot "
                "WHERE environment_id=%s AND logical_key=%s",
                (environment, logical_key),
            )
            slot = cursor.fetchone()
            if slot is None:
                raise Rejection("publication_base_changed")
            cursor.execute(
                "SELECT id,kind,object_key,sha256,bytes FROM app.committed_active_partitions "
                "WHERE environment_id=%s AND logical_key=%s ORDER BY generation",
                (environment, logical_key),
            )
            objects = [dict(row) for row in cursor.fetchall()]
        if not any(item["kind"] == "part" for item in objects):
            return "unchanged"
        manifest = slot["membership_manifest"]
        generation: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "kind": "snapshot",
            "logical_key": logical_key,
            "base_version": slot["slot_version"],
            "membership_manifest": manifest,
            "supersedes": [str(item["id"]) for item in objects],
        }
        if manifest:
            if sum(item["bytes"] for item in objects) > MAX_OBJECT_BYTES:
                raise Rejection("object_size_limit")
            tables = []
            for item in objects:
                data = store.read(item["object_key"], item["bytes"], deadline)
                if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise Rejection("object_checksum_mismatch")
                try:
                    tables.append(pq.read_table(io.BytesIO(data)))
                except (OSError, ValueError, pa.ArrowException):
                    raise Rejection("invalid_parquet") from None
            with tempfile.TemporaryDirectory(prefix="compact-") as directory:
                path = Path(directory) / "snapshot.parquet"
                verified = write_snapshot(
                    path,
                    merge_parts(tables, manifest),
                    deadline=deadline,
                    max_bytes=MAX_OBJECT_BYTES,
                )
                payload = path.read_bytes()
            written = publish_verified(
                store,
                payload,
                uuid.uuid4(),
                snapshot_certificate(verified, payload, deadline=deadline),
                deadline=deadline,
            )
            generation.update(
                object_key=written.key,
                sha256=written.sha256,
                bytes=written.byte_count,
                row_count=verified["rows"],
                profile_count=verified["profiles"],
                schema_sha256=verified["schema_sha256"],
                verification_evidence=evidence_json(verified),
                verified_at=datetime.now(UTC).isoformat(),
            )
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT app.compact_slot(%s,%s,%s)", (environment, logical_key, Jsonb(generation))
            )
        return "compacted"

    def compactable_slots(self, environment: uuid.UUID, *, min_parts: int = 2) -> list[str]:
        """Slots with at least `min_parts` active parts: the work list of the compact job."""
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute(
                "SELECT logical_key FROM app.committed_active_partitions "
                "WHERE environment_id=%s AND kind='part' GROUP BY logical_key "
                "HAVING count(*)>=%s ORDER BY logical_key",
                (environment, min_parts),
            )
            return [row["logical_key"] for row in cursor.fetchall()]

    def audit_levels(self, chunk: uuid.UUID, sample: int = 20) -> dict[str, Any]:
        """Sampled check of stored typed levels against canonical content (raises on mismatch)."""
        with self.transaction(readonly_snapshot=True) as cursor:
            cursor.execute("SELECT app.audit_levels(%s,%s) AS evidence", (chunk, sample))
            return dict(cursor.fetchone()["evidence"])

    def finalize(self, run: uuid.UUID, reason: str | None = None) -> str:
        with self.transaction() as cursor:
            cursor.execute("SELECT app.finalize_run(%s,%s) AS state", (run, reason))
            return str(cursor.fetchone()["state"])

    def stored(self) -> tuple[StoredScience, ...]:
        """Bounded foundation read; later indexing may narrow affected-slot loading."""
        result = []
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT p.*,f.platform_number FROM app.argo_profile p "
                "JOIN app.argo_float f ON f.id=p.float_id ORDER BY p.id LIMIT 100001"
            )
            rows = cursor.fetchall()
            if len(rows) > 100000:
                raise Rejection("stored_snapshot_profile_limit")
            byte_count = 0
            for row in rows:
                science = row["scientific_content"]
                canonical, digest = CanonicalBudget().encode(science)
                byte_count += len(canonical)
                if byte_count > 256 * 1024 * 1024:
                    raise Rejection("stored_snapshot_memory_limit")
                if digest != row["content_hash"]:
                    raise Rejection("stored_scientific_hash_mismatch")
                cursor.execute(
                    "SELECT * FROM app.core_measurement WHERE profile_id=%s "
                    "AND observation_month=%s ORDER BY level_index",
                    (row["id"], row["observation_month"]),
                )
                levels = tuple(
                    {
                        key: value
                        for key, value in level.items()
                        if key not in ("observation_month", "profile_id")
                    }
                    for level in cursor.fetchall()
                )
                if len(levels) != row["level_count"]:
                    raise Rejection("stored_level_set_mismatch")

                def number(name: str, content: dict[str, Any] = science) -> ScientificNumber:
                    item = content[name]
                    exact = item["exact"]
                    return ScientificNumber(
                        None if exact is None else float(Decimal(exact)),
                        exact,
                        item["missing_reason"],
                        item["nonfinite_kind"],
                        tuple(item["flags"]),
                    )

                revision = row["source_revision"]
                vector = (
                    None
                    if revision is None
                    else Revision(
                        revision["kind"],
                        tuple(
                            sorted(
                                (key, timestamp(value))
                                for key, value in revision["components"].items()
                            )
                        ),
                    )
                )
                profile = Profile(
                    row["source_profile_id"],
                    row["platform_number"],
                    science["cycle"],
                    science["direction"],
                    science["observed_at"],
                    number("longitude"),
                    number("latitude"),
                    vector,
                    levels,
                    canonical,
                    digest,
                    0,
                )
                key = (
                    None
                    if not row["fallback_complete"]
                    else (
                        row["platform_number"],
                        row["cycle_number"],
                        row["direction"],
                        row["identity_observed_at"]
                        .astimezone(UTC)
                        .isoformat(timespec="microseconds"),
                        row["observation_segment"],
                    )
                )
                identity = StoredIdentity(
                    row["id"],
                    row["platform_number"],
                    row["source_profile_id"],
                    row["cycle_number"],
                    row["direction"],
                    key,
                )
                result.append(StoredScience(identity, profile))
        return tuple(result)

    def catalogue_snapshot(
        self,
        environment: uuid.UUID,
        interval: Interval,
        *,
        tiles: tuple[Tile, ...] | None = None,
        max_seconds: float = 60,
        source: str = "argovis",
    ) -> CatalogueSnapshot:
        """One consistent snapshot resolves committed fetch and stored-domain evidence."""
        if not 0 < max_seconds <= 60:
            raise Rejection("invalid_catalogue_budget")
        deadline = time.monotonic() + max_seconds
        with self.transaction(readonly_snapshot=True, remaining=max_seconds) as cursor:
            cursor.execute(
                "SELECT logical_key,slot_version FROM app.logical_partition_slot "
                "WHERE environment_id=%s",
                (environment,),
            )
            versions = {row["logical_key"]: row["slot_version"] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT * FROM app.committed_active_partitions WHERE environment_id=%s "
                "ORDER BY logical_key,generation",
                (environment,),
            )
            records = tuple(
                CatalogueRecord(
                    row["id"],
                    row["environment_id"],
                    row["logical_key"],
                    row["generation"],
                    row["slot_version"],
                    row["status"],
                    True,
                    True,
                    row["geometry_version"],
                    SCHEMA_VERSION,
                    row["object_key"],
                    row["sha256"],
                    row["bytes"],
                    row["kind"],
                    row["part_ordinal"],
                )
                for row in cursor.fetchall()
            )
            cursor.execute(
                "SELECT cr.*,c.tile FROM app.coverage_receipt cr "
                "JOIN app.ingestion_chunk c ON c.id=cr.chunk_id AND c.state='complete' "
                "JOIN app.publication_intent i ON i.id=cr.intent_id AND i.status='committed' "
                "JOIN app.logical_partition_slot s ON s.environment_id=cr.environment_id "
                "AND s.logical_key=cr.logical_key "
                "WHERE cr.environment_id=%s AND ((cr.requested_start<%s AND cr.requested_end>%s) "
                "OR (cr.stored_disposition='empty_stored_domain' "
                "AND cr.slot_version=s.slot_version "
                "AND s.observation_month BETWEEN %s AND %s)) "
                "ORDER BY cr.committed_at,cr.id LIMIT 16385",
                (
                    environment,
                    interval.end,
                    interval.start,
                    month_start(interval.start).date(),
                    month_start(interval.end - timedelta(microseconds=1)).date(),
                ),
            )
            receipts = tuple(
                Receipt(
                    row["id"],
                    Interval(row["requested_start"], row["requested_end"]),
                    Tile(**row["tile"]),
                    row["logical_key"],
                    row["slot_version"],
                    row["fetch_disposition"],
                    row["stored_disposition"],
                    row["committed_at"].isoformat(),
                )
                for row in cursor.fetchall()
            )

            def members(piece: Interval, slot: str) -> int:
                cursor.execute(
                    "SELECT count(*) AS n FROM app.argo_profile p "
                    "WHERE p.source=%s AND p.observed_at>=%s AND p.observed_at<%s AND "
                    + OWNER_FUNCTIONS[source]
                    + "(p.observed_at,(p.scientific_content->'longitude'->>'exact')::numeric,"
                    "(p.scientific_content->'latitude'->>'exact')::numeric)=%s",
                    (source, piece.start, piece.end, slot),
                )
                return int(cursor.fetchone()["n"])

            result = resolve(
                interval,
                records,
                versions,
                receipts,
                members,
                tiles=tiles,
                deadline=deadline,
                source=source,
            )
            # Manifests only for the slots the selection returns; readers filter part rows by them.
            cursor.execute(
                "SELECT logical_key,membership_manifest FROM app.logical_partition_slot "
                "WHERE environment_id=%s AND logical_key=ANY(%s)",
                (environment, sorted({record.logical_key for record in result.records})),
            )
            return replace(
                result, manifests={row["logical_key"]: row["membership_manifest"] for row in cursor}
            )
