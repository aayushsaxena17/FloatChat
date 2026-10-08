"""Local MinIO byte store with conditional immutable publication and no retries."""

import base64
import hashlib
import re
import time
from typing import Any
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .numeric import Rejection
from .objects import MAX_OBJECT_BYTES, validate_key
from .transport import operation_deadline

# A checksum the server computed differently from ours: real corruption, never a fallback.
CHECKSUM_MISMATCH = frozenset(
    {"BadDigest", "InvalidDigest", "XAmzContentChecksumMismatch", "XAmzContentSHA256Mismatch"}
)


class MinioStore:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        try:
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme not in ("http", "https")
                or parsed.hostname not in ("minio", "localhost", "127.0.0.1", "::1")
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in ("", "/")
                or parsed.port is None
            ):
                raise ValueError
        except ValueError:
            raise Rejection("nonlocal_object_storage_endpoint") from None
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise Rejection("invalid_bucket")
        self.bucket = bucket
        # PutObject carries a SHA-256 the server verifies. Cleared for good the first time
        # the server refuses the checksum parameters; writes then verify by full read-back.
        self.checksums = True
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                retries={"total_max_attempts": 1, "mode": "standard"},
                connect_timeout=10,
                read_timeout=20,
                proxies={},
                s3={"addressing_style": "path"},
            ),
        )
        self.client.meta.events.register_first("needs-retry.s3", self._reject_redirect)

    @staticmethod
    def _reject_redirect(response: Any = None, **kwargs: Any) -> None:
        if response is not None and 300 <= response[0].status_code <= 399:
            raise Rejection("object_redirect_rejected")

    def _put(self, key: str, data: bytes, deadline: float) -> None:
        validate_key(key)
        if len(data) > MAX_OBJECT_BYTES:
            raise Rejection("object_size_limit")
        try:
            with operation_deadline(min(deadline, time.monotonic() + 120)):
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentLength=len(data),
                    IfNoneMatch="*",
                    ContentType="application/octet-stream",
                )
        except ClientError as error:
            # A racing publisher's object is not trusted until caller read-back.
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise Rejection("object_write_failure") from None
        except (BotoCoreError, OSError):
            raise Rejection("object_write_failure") from None

    @staticmethod
    def _error(error: ClientError) -> tuple[int | None, str, str]:
        response = error.response
        return (
            response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
            str(response.get("Error", {}).get("Code", "")),
            str(response.get("Error", {}).get("Message", "")),
        )

    @staticmethod
    def _checksum_refused(status: int | None, code: str, message: str) -> bool:
        """The server does not accept checksum parameters (not: it found our bytes wrong)."""
        said = (code + " " + message).lower()
        return code not in CHECKSUM_MISMATCH and (
            status == 501
            or code == "NotImplemented"
            or (status == 400 and "checksum" in said and "match" not in said)
        )

    def write_temporary(self, key: str, data: bytes, deadline: float) -> None:
        if not key.startswith("tmp/"):
            raise Rejection("invalid_temporary_key")
        self._put(key, data, deadline)

    def write_immutable(self, key: str, data: bytes, sha256_hex: str, deadline: float) -> None:
        """Create a final key only if absent, in one PutObject whose SHA-256 the server checks.

        An existing key is never overwritten; its content is compared to sha256_hex.
        """
        validate_key(key)
        if key.startswith("tmp/"):
            raise Rejection("invalid_publication_key")
        if len(data) > MAX_OBJECT_BYTES:
            raise Rejection("object_size_limit")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256_hex):
            raise Rejection("invalid_object_checksum")
        checksum = (
            {
                "ChecksumAlgorithm": "SHA256",
                "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256_hex)).decode(),
            }
            if self.checksums
            else {}
        )
        created = True
        try:
            with operation_deadline(min(deadline, time.monotonic() + 120)):
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentLength=len(data),
                    IfNoneMatch="*",
                    ContentType="application/octet-stream",
                    **checksum,
                )
        except ClientError as error:
            status, code, message = self._error(error)
            if status == 412:
                created = False
            elif code in CHECKSUM_MISMATCH:
                raise Rejection("object_checksum_mismatch") from None
            elif checksum and self._checksum_refused(status, code, message):
                # Parameter refused, not bytes: one plain conditional PUT, verified by
                # reading everything back, and every later write skips the parameters.
                self.checksums = False
                self.write_immutable(key, data, sha256_hex, deadline)
                return
            else:
                raise Rejection("object_write_failure") from None
        except (BotoCoreError, OSError):
            raise Rejection("object_write_failure") from None
        if not created or not self.checksums:
            self._same_content(key, data, sha256_hex, deadline)

    def _same_content(self, key: str, data: bytes, sha256_hex: str, deadline: float) -> None:
        """A racing publisher's object, or bytes the server did not check, must equal ours."""
        stored = self.stat(key, deadline)
        if stored["bytes"] != len(data) or stored["sha256"] not in (None, sha256_hex):
            raise Rejection("object_checksum_mismatch")
        if stored["sha256"] is None:
            received = self.read(key, len(data), deadline)
            if len(received) != len(data) or hashlib.sha256(received).hexdigest() != sha256_hex:
                raise Rejection("object_checksum_mismatch")

    def _head(self, key: str) -> Any:
        if self.checksums:
            try:
                return self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
            except ClientError as error:
                if self._error(error)[0] not in (400, 501):
                    raise
                self.checksums = False  # The server does not report checksums at all.
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def stat(self, key: str, deadline: float) -> dict[str, Any]:
        """Byte count and stored SHA-256 (hex, None when the server keeps none) of a key."""
        validate_key(key)
        try:
            with operation_deadline(min(deadline, time.monotonic() + 120)):
                response = self._head(key)
            encoded = response.get("ChecksumSHA256")
            digest = None if encoded is None else base64.b64decode(encoded, validate=True)
            if digest is not None and len(digest) != 32:
                raise ValueError
            return {
                "bytes": int(response["ContentLength"]),
                "sha256": None if digest is None else digest.hex(),
            }
        except Rejection:
            raise
        except ClientError as error:
            raise Rejection(
                "object_missing" if self._error(error)[0] == 404 else "object_stat_failure"
            ) from None
        except (BotoCoreError, OSError, ValueError, KeyError, TypeError):
            raise Rejection("object_stat_failure") from None

    def read(self, key: str, max_bytes: int, deadline: float) -> bytes:
        validate_key(key)
        if not 0 <= max_bytes <= MAX_OBJECT_BYTES:
            raise Rejection("invalid_object_budget")
        body = None
        bound = min(deadline, time.monotonic() + 120)
        try:
            with operation_deadline(bound):
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                body = response["Body"]
                expected = int(response["ContentLength"])
                if not 0 <= expected <= max_bytes:
                    raise Rejection("object_size_limit")
                result = bytearray()
                while True:
                    # operation_deadline cannot interrupt a blocked read: a dribbling
                    # object must not outlast the operation bound (client timeouts bound
                    # each single read).
                    if time.monotonic() >= bound:
                        raise Rejection("io_deadline")
                    part = body.read(min(65536, max_bytes - len(result) + 1))
                    if not part:
                        break
                    result.extend(part)
                    if len(result) > max_bytes:
                        raise Rejection("object_size_limit")
                if len(result) != expected:
                    raise Rejection("object_length_mismatch")
                return bytes(result)
        except Rejection as error:
            # Every other category raised here has always read as a read failure.
            if error.category == "io_deadline":
                raise
            raise Rejection("object_read_failure") from None
        except (BotoCoreError, OSError, ValueError, KeyError):
            raise Rejection("object_read_failure") from None
        finally:
            if body is not None:
                body.close()

    def publish_if_absent(self, temporary: str, final: str, deadline: float) -> None:
        if not temporary.startswith("tmp/") or final.startswith("tmp/"):
            raise Rejection("invalid_publication_key")
        validate_key(final)
        data = self.read(temporary, MAX_OBJECT_BYTES, deadline)
        # Conditional PutObject is publication, not an unconditional CopyObject.
        # All data comes from the already-verified temporary object.
        self._put(final, data, deadline)
