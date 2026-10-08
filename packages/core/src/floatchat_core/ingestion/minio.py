"""Local MinIO byte store with conditional immutable publication and no retries."""

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

    def write_temporary(self, key: str, data: bytes, deadline: float) -> None:
        if not key.startswith("tmp/"):
            raise Rejection("invalid_temporary_key")
        self._put(key, data, deadline)

    def read(self, key: str, max_bytes: int, deadline: float) -> bytes:
        validate_key(key)
        if not 0 <= max_bytes <= MAX_OBJECT_BYTES:
            raise Rejection("invalid_object_budget")
        body = None
        try:
            with operation_deadline(min(deadline, time.monotonic() + 120)):
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                body = response["Body"]
                expected = int(response["ContentLength"])
                if not 0 <= expected <= max_bytes:
                    raise Rejection("object_size_limit")
                result = bytearray()
                while True:
                    part = body.read(min(65536, max_bytes - len(result) + 1))
                    if not part:
                        break
                    result.extend(part)
                    if len(result) > max_bytes:
                        raise Rejection("object_size_limit")
                if len(result) != expected:
                    raise Rejection("object_length_mismatch")
                return bytes(result)
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
