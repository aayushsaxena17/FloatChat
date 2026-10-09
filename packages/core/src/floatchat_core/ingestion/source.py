"""Recorded-input adapter. A profile-ID sample cannot prove regional coverage.

Fixture indexes explicitly bind each response to a logical request. Missing
requests fail; the adapter never synthesizes an empty response from a sample.
Only sanitized bytes are published. The worker's verified landing is authoritative
on recovery and no new source read occurs after the landed phase.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .argovis import policy_versions
from .landing import Landing, logical_request, validate_raw
from .numeric import Rejection
from .objects import ObjectStore, publish_verified
from .raw import sanitize_raw
from .repository import Authority, Repository


class Source(Protocol):
    def obtain(self, path: str, parameters: dict[str, str], role: str) -> Landing: ...
    def restart_selection(self) -> None: ...


class RecordedSource:
    def restart_selection(self) -> None:
        # Fixed captured input cannot become a different upstream snapshot.
        raise Rejection("incomplete_inventory")

    def __init__(
        self,
        repository: Repository,
        store: ObjectStore,
        authority: Authority,
        descriptor: dict[str, Any],
        *,
        deadline: float,
        application_commit: str,
        require_existing: bool = False,
    ) -> None:
        self.repository, self.store, self.authority = repository, store, authority
        self.deadline, self.application_commit = deadline, application_commit
        self.require_existing = require_existing
        self.descriptor = descriptor
        self.index: dict[str, Any] | None = None
        self.root: Path | None = None
        if "fixture_index" in descriptor:
            index = Path(descriptor["fixture_index"]).resolve(strict=True)
            approved = Path(descriptor["fixture_root"]).resolve(strict=True)
            if not index.is_relative_to(approved) or str(approved).startswith(("/mnt/", "C:")):
                raise Rejection("unapproved_fixture_path")
            if index.stat().st_size > 16 * 1024**2:
                raise Rejection("fixture_index_limit")
            if hashlib.sha256(index.read_bytes()).hexdigest() != descriptor["index_sha256"]:
                raise Rejection("fixture_index_changed")
            self.index = json.loads(index.read_bytes())
            if not isinstance(self.index, dict) or not isinstance(
                self.index.get("responses"), list
            ):
                raise Rejection("invalid_fixture_index")
            if self.index.get("kind") not in (
                "synthetic_offline_chunk_fixture",
                "live_recorded_chunk_fixture",
            ):
                raise Rejection("profile_sample_is_not_chunk_coverage")
            if self.index.get("versions") != policy_versions():
                raise Rejection("unsupported_fixture_versions")
            self.root = index.parent

    def obtain(self, path: str, parameters: dict[str, str], role: str) -> Landing:
        key = logical_request(path, parameters, role)
        existing = self.repository.verified_landing(self.authority, key)
        if existing is not None:
            data = self.store.read(existing["object_key"], 128 * 1024**2, self.deadline)
            if (
                len(data) != existing["bytes"]
                or hashlib.sha256(data).hexdigest() != existing["sha256"]
                or existing["versions"] != policy_versions()
            ):
                raise Rejection("landing_unavailable")
            # Validated once when landed; the matching hash identifies those bytes.
            return Landing(existing, data)
        if self.require_existing:
            raise Rejection("landing_unavailable")
        origin = "captured"
        if self.index is not None:
            matches = [
                r
                for r in self.index["responses"]
                if r["role"] == role and r["path"] == path and r["parameters"] == parameters
            ]
            if len(matches) != 1 or self.root is None:
                raise Rejection("fixture_selection_unavailable")
            record = matches[0]
            file = (self.root / record["file"]).resolve(strict=True)
            if not file.is_relative_to(self.root) or file.stat().st_size > 128 * 1024**2:
                raise Rejection("invalid_fixture_file")
            data = file.read_bytes()
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise Rejection("fixture_checksum_mismatch")
            retrieved = record["retrieved_at_utc"]
            status = record.get("http_status", 200)
            if status not in (200, 404) or (status == 404 and validate_raw(data)["documents"]):
                raise Rejection("invalid_fixture_status")
        else:
            origin = "replay"
            predecessor = uuid.UUID(self.descriptor["predecessor_run"])
            current = self.repository.chunk(self.authority.chunk)
            with self.repository.transaction(readonly_snapshot=True) as cursor:
                cursor.execute(
                    "SELECT m.* FROM app.raw_manifest m "
                    "JOIN app.ingestion_attempt a ON a.id=m.attempt_id "
                    "JOIN app.ingestion_chunk c ON c.id=a.chunk_id "
                    "JOIN app.replay_chunk_source binding ON binding.predecessor_chunk_id=c.id "
                    "JOIN app.ingestion_run r ON r.id=c.run_id "
                    "WHERE r.id=%s AND binding.chunk_id=%s AND binding.run_id=%s "
                    "AND r.environment_id="
                    "(SELECT environment_id FROM app.ingestion_run WHERE id=%s) "
                    "AND c.requested_start=%s AND c.requested_end=%s AND c.tile=%s::jsonb "
                    "AND a.logical_request_key=%s AND a.disposition='verified_raw' "
                    "AND a.attempt_number>coalesce((SELECT through_attempt FROM app.landing_reset "
                    "WHERE chunk_id=c.id),0) AND c.state='complete' "
                    "ORDER BY a.attempt_number DESC LIMIT 1",
                    (
                        predecessor,
                        self.authority.chunk,
                        self.authority.run,
                        self.authority.run,
                        current["requested_start"],
                        current["requested_end"],
                        json.dumps(current["tile"]),
                        key,
                    ),
                )
                record = cursor.fetchone()
                if record is None:
                    raise Rejection("replay_selection_unavailable")
            data = self.store.read(record["object_key"], 128 * 1024**2, self.deadline)
            if (
                len(data) != record["bytes"]
                or hashlib.sha256(data).hexdigest() != record["sha256"]
                or record["versions"] != policy_versions()
            ):
                raise Rejection("landing_unavailable")
            retrieved = record["retrieved_at"].astimezone(UTC).isoformat()
            status = record["http_status"]
        attempt = self.repository.recorded_reserve(self.authority, key, role, parameters, origin)
        cleaned = sanitize_raw(data)
        evidence = publish_verified(
            self.store,
            cleaned.payload,
            attempt,
            validate_raw,
            deadline=self.deadline,
            raw=True,
            max_bytes=128 * 1024**2,
        )
        manifest = {
            "id": str(attempt),
            "key": evidence.key,
            "sha256": evidence.sha256,
            "bytes": evidence.byte_count,
            "retrieved_at": retrieved,
            "versions": policy_versions(),
            "sanitization": {
                **cleaned.manifest,
                "input_origin": origin,
                "input_kind": None if self.index is None else self.index["kind"],
                "read_at_actual_utc": datetime.now(UTC).isoformat(),
                "validation": evidence.validation,
            },
            "application_commit": self.application_commit,
            "http_status": status,
        }
        self.repository.finish_attempt(
            self.authority, attempt, "verified_raw", status, manifest=manifest
        )
        return Landing(manifest, cleaned.payload)
