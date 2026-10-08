"""Controller-authorized HTTP retry owner and immutable, sanitized raw landing.

No HTTP adapter or queue worker retries independently. Every request reservation,
including interrupted attempts, is persisted before the single network call.
Recovery reuses verified landing for the same pinned logical request. Float metadata
landed by an earlier chunk or run is reused through a per-chunk `cache` manifest.
"""

import hashlib
import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .argovis import SOURCE_CONTRACT, policy_versions
from .json_stream import documents
from .numeric import Rejection
from .objects import ObjectStore, publish_verified
from .private import preserve_original
from .raw import sanitize_raw
from .repository import Authority, Repository
from .transport import (
    BASE,
    HTTPFailure,
    Response,
    UpstreamGovernor,
    fetch,
    retry_after_seconds,
    retry_delay,
    validate_endpoint,
)

# stage1-v4 policy, chosen pending measurement: float metadata rarely changes. The window
# is evidence freshness, anchored on the run's actual creation time; the reference time T
# governs scientific eligibility only.
CACHE_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class Landing:
    manifest: dict[str, Any]
    payload: bytes = field(repr=False)


def logical_request(path: str, parameters: dict[str, str], role: str) -> str:
    validate_endpoint(BASE + path)
    if role not in ("inventory_before", "inventory_after", "profile", "metadata"):
        raise Rejection("invalid_request_role")
    return hashlib.sha256(
        json.dumps(
            {
                "specification": "2.36.2",
                "source_contract": SOURCE_CONTRACT,
                "path": path,
                "parameters": parameters,
                "role": role,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate_raw(payload: bytes) -> dict[str, int | str]:
    count = sum(1 for _ in documents(payload))
    return {"schema": SOURCE_CONTRACT + "-object-array", "documents": count}


def cache_fresh(retrieved_at: datetime, anchor: datetime) -> bool:
    """Usable when retrieved at most 30 days before the run was created (no upper bound).

    Entries landed later, by this run's own earlier chunks, are the main saving.
    """
    return retrieved_at >= anchor - CACHE_WINDOW


def cached_payload(store: ObjectStore, row: dict[str, Any], deadline: float) -> bytes | None:
    """The cached object's bytes if they still verify, else None (a cache miss).

    Unlike the chunk's own landing, an unverifiable cache entry is not fatal: the
    caller fetches again and the upsert replaces the entry.
    """
    try:
        payload = store.read(row["object_key"], 128 * 1024**2, deadline)
    except Rejection:
        return None
    if (
        len(payload) != row["bytes"]
        or hashlib.sha256(payload).hexdigest() != row["sha256"]
        or row["versions"] != policy_versions()
    ):
        return None
    return payload


class MetadataCache:
    """Per-owner view of app.float_metadata_cache; the run row is read once."""

    def __init__(self, repository: Repository, authority: Authority) -> None:
        self.repository, self.authority = repository, authority
        self.policy: tuple[uuid.UUID, datetime] | None = None  # environment, run created

    @staticmethod
    def pointer(path: str, parameters: dict[str, str], role: str) -> str | None:
        if role == "metadata" and path == "/argo/meta" and set(parameters) == {"id"}:
            return parameters["id"]
        return None

    def environment(self) -> tuple[uuid.UUID, datetime]:
        if self.policy is None:
            run = self.repository.run(self.authority.run)
            self.policy = (run["environment_id"], run["created_at_actual_utc"])
        return self.policy

    def lookup(
        self, store: ObjectStore, pointer: str, deadline: float
    ) -> tuple[dict[str, Any], bytes] | None:
        environment, created = self.environment()
        row = self.repository.metadata_cache_get(environment, pointer)
        if row is None or not cache_fresh(row["retrieved_at"], created):
            return None
        payload = cached_payload(store, row, deadline)
        return None if payload is None else (row, payload)

    def record(self, pointer: str, manifest: str, retrieved_at: datetime) -> None:
        environment, _ = self.environment()
        self.repository.metadata_cache_put(
            environment, pointer, uuid.UUID(manifest), self.authority.run, retrieved_at
        )


def retry_after_hint(header: str | None) -> float | None:
    """Seconds a 429 asks us to wait, for the governor; invalid values are ignored here."""
    if header is None:
        return None
    try:
        return retry_after_seconds(header, datetime.now(UTC))
    except Rejection:
        return None


class RequestOwner:
    def __init__(
        self,
        repository: Repository,
        store: ObjectStore,
        authority: Authority,
        *,
        deadline: float,
        application_commit: str,
        enabled: Callable[[], bool],
        credential: Callable[[], str],
        transport: Callable[..., Response] = fetch,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        originals: Path | None = None,
        require_existing: bool = False,
        governor: UpstreamGovernor | None = None,
        slot: int = 1,
    ) -> None:
        self.repository, self.store, self.authority = repository, store, authority
        self.deadline, self.application_commit = deadline, application_commit
        self.enabled, self.credential, self.transport = enabled, credential, transport
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.originals, self.require_existing = originals, require_existing
        # Without a governor this owner uses the single advisory-lock `slot` (v3: 1).
        self.governor, self.slot = governor, slot
        self.cache = MetadataCache(repository, authority)

    def idle(self) -> None:
        """Runs while a governor permit is awaited: stop if disabled, keep the lease."""
        if not self.enabled():
            raise Rejection("live_ingestion_disabled")
        self.repository.heartbeat(self.authority)

    def wait(self, seconds: float) -> None:
        end = self.clock() + seconds
        if end >= self.deadline:
            raise Rejection("http_retry_deadline")
        while self.clock() < end:
            if not self.enabled():
                raise Rejection("live_ingestion_disabled")
            self.repository.heartbeat(self.authority)
            self.sleep(min(10, end - self.clock()))

    def restart_selection(self) -> None:
        if self.require_existing:
            raise Rejection("landing_unavailable")
        self.repository.restart_selection(self.authority)

    def obtain(self, path: str, parameters: dict[str, str], role: str) -> Landing:
        if not self.enabled():
            raise Rejection("live_ingestion_disabled")
        key = logical_request(path, parameters, role)
        existing = self.repository.verified_landing(self.authority, key)
        if existing is not None:
            payload = self.store.read(existing["object_key"], 128 * 1024**2, self.deadline)
            if (
                len(payload) != existing["bytes"]
                or hashlib.sha256(payload).hexdigest() != existing["sha256"]
                or existing["versions"] != policy_versions()
            ):
                raise Rejection("landing_unavailable")
            # Validated once when landed; the matching hash identifies those bytes.
            return Landing(existing, payload)
        if self.require_existing:
            raise Rejection("landing_unavailable")
        if self.originals is None:
            raise Rejection("private_originals_required")
        pointer = self.cache.pointer(path, parameters, role)
        if pointer is not None:
            hit = self.cache.lookup(self.store, pointer, self.deadline)
            if hit is not None:
                return self.cached(key, role, parameters, *hit)
        while True:
            if self.clock() >= self.deadline:
                raise Rejection("http_retry_deadline")
            if not self.enabled():
                raise Rejection("live_ingestion_disabled")
            slot = self.slot
            if self.governor is not None:
                slot = self.governor.acquire(self.deadline, self.idle)
            status: int | None = None
            hint: float | None = None
            delay = 0.0
            response: Response | None = None
            try:
                with self.repository.upstream_slot(self.authority, self.deadline, slot):
                    attempt, ordinal = self.repository.http_reserve(
                        self.authority, key, role, parameters
                    )
                    credential = self.credential()
                    try:
                        response = self.transport(
                            path,
                            parameters,
                            credential,
                            lambda size, attempt_id=attempt: self.repository.account_received(
                                self.authority, attempt_id, size
                            ),
                            deadline=self.deadline,
                            enabled=self.enabled,
                        )
                        status = response.status
                    except HTTPFailure as error:
                        status = error.status
                        if status == 429:
                            hint = retry_after_hint(error.retry_after)
                        self.repository.finish_attempt(
                            self.authority,
                            attempt,
                            "http_failure",
                            error.status,
                            "upstream_http_failure",
                        )
                        if ordinal >= 4 or not error.retryable:
                            raise Rejection("http_retry_exhausted") from None
                        delay = retry_delay(
                            ordinal, error.retry_after, datetime.now(UTC), self.jitter()
                        )
                    except Rejection as error:
                        self.repository.finish_attempt(
                            self.authority, attempt, "transport_failure", error=error.category
                        )
                        if ordinal >= 4 or error.category not in (
                            "upstream_transport_failure",
                            "io_deadline",
                        ):
                            raise
                        delay = retry_delay(ordinal, None, datetime.now(UTC), self.jitter())
            finally:
                # The permit is back (a 429 already halved it) before any retry delay.
                if self.governor is not None:
                    self.governor.release(slot, status, hint)
            if response is None:
                self.wait(delay)
                continue
            # Landing/publish failures do not manufacture another HTTP attempt.
            # Recovery marks this attempt interrupted and obtains a missing logical
            # request within its same persisted budget.
            preserve_original(self.originals, attempt, response.payload)
            cleaned = sanitize_raw(response.payload, credential)
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
                "retrieved_at": response.retrieved_at.isoformat(),
                "versions": policy_versions(),
                "sanitization": {**cleaned.manifest, "validation": evidence.validation},
                "application_commit": self.application_commit,
                "http_status": response.status,
            }
            self.repository.finish_attempt(
                self.authority, attempt, "verified_raw", response.status, manifest=manifest
            )
            if pointer is not None and response.status == 200:
                self.cache.record(pointer, str(attempt), response.retrieved_at)
            return Landing(manifest, cleaned.payload)

    def cached(
        self,
        key: str,
        role: str,
        parameters: dict[str, str],
        row: dict[str, Any],
        payload: bytes,
    ) -> Landing:
        """Record this chunk's own manifest for an already landed object (no request)."""
        attempt = self.repository.recorded_reserve(self.authority, key, role, parameters, "cache")
        manifest = {
            "id": str(attempt),
            "key": row["object_key"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "retrieved_at": row["retrieved_at"].isoformat(),
            "versions": policy_versions(),
            "sanitization": {
                "version": "raw-sanitization-v1",
                "input_origin": "cache",
                "cache_manifest": str(row["raw_manifest_id"]),
                "validation": {
                    "schema": SOURCE_CONTRACT + "-object-array",
                    "inherited_from": str(row["raw_manifest_id"]),
                },
            },
            "application_commit": self.application_commit,
            "http_status": row["http_status"],
        }
        self.repository.finish_attempt(
            self.authority, attempt, "verified_raw", row["http_status"], manifest=manifest
        )
        return Landing(manifest, payload)
