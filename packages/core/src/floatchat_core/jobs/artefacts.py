"""Download tokens and object keys for export artefacts (ADR-0079).

The API signs ``<expiry>.<hmac>`` with ``ARTEFACT_SIGNING_KEY``; the token binds one artefact
id and expires after the configured lifetime. The browser never reaches the object store.
"""

import hashlib
import hmac
import re
import uuid
from datetime import UTC, datetime

OBJECT_KEY = re.compile(r"^exports/([0-9a-f-]{36})/([A-Za-z0-9._-]{1,128})$")
TOKEN = re.compile(r"^(\d{1,12})\.([0-9a-f]{64})$")


def object_key(job_id: str, filename: str) -> str:
    key = f"exports/{uuid.UUID(job_id)}/{filename}"
    if OBJECT_KEY.fullmatch(key) is None:
        raise ValueError("invalid artefact filename")
    return key


def _digest(secret: str, artefact_id: str, expires: int) -> str:
    message = f"{uuid.UUID(artefact_id)}:{expires}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def sign(secret: str, artefact_id: str, expires_at: datetime) -> str:
    expires = int(expires_at.astimezone(UTC).timestamp())
    return f"{expires}.{_digest(secret, artefact_id, expires)}"


def verify(secret: str, artefact_id: str, token: str | None, now: datetime | None = None) -> bool:
    """True only for an unexpired token whose digest matches this artefact."""
    if not secret or not token:
        return False
    match = TOKEN.fullmatch(token)
    if match is None:
        return False
    expires = int(match.group(1))
    moment = now or datetime.now(UTC)
    if expires < int(moment.astimezone(UTC).timestamp()):
        return False
    try:
        expected = _digest(secret, artefact_id, expires)
    except ValueError:
        return False
    return hmac.compare_digest(expected, match.group(2))


def download_path(artefact_id: str, token: str) -> str:
    return f"/v1/artefacts/{artefact_id}/download?token={token}"
