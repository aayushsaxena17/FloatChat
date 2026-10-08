"""Controller-authorized HTTP retry owner and immutable, sanitized raw landing.

No HTTP adapter or Celery task retries independently. Every request reservation,
including interrupted attempts, is persisted before the single network call.
Recovery reuses verified landing for the same pinned logical request.
"""

import hashlib
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .argovis import SOURCE_CONTRACT, policy_versions
from .json_stream import documents
from .numeric import Rejection
from .objects import ObjectStore, publish_verified
from .private import preserve_original
from .raw import sanitize_raw
from .repository import Authority, Repository
from .transport import BASE, HTTPFailure, Response, fetch, retry_delay, validate_endpoint


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
    ) -> None:
        self.repository, self.store, self.authority = repository, store, authority
        self.deadline, self.application_commit = deadline, application_commit
        self.enabled, self.credential, self.transport = enabled, credential, transport
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.originals, self.require_existing = originals, require_existing

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
            validate_raw(payload)
            return Landing(existing, payload)
        if self.require_existing:
            raise Rejection("landing_unavailable")
        if self.originals is None:
            raise Rejection("private_originals_required")
        while True:
            if self.clock() >= self.deadline:
                raise Rejection("http_retry_deadline")
            if not self.enabled():
                raise Rejection("live_ingestion_disabled")
            with self.repository.upstream_slot(self.authority, self.deadline):
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
                except HTTPFailure as error:
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
                else:
                    # Landing/publish failures do not manufacture another HTTP
                    # attempt. Recovery marks this attempt interrupted and obtains
                    # a missing logical request within its same persisted budget.
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
                    return Landing(manifest, cleaned.payload)
            self.wait(delay)
