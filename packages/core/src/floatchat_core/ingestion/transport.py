"""One bounded HTTP attempt. The durable controller alone decides whether to retry.

HTTPS connects to a prevalidated IP while preserving Argovis SNI and certificate
hostname verification. No proxy environment, redirect or client retry is used.
The POSIX alarm is intentional: Stage 1 workers run in Linux prefork processes.
"""

import http.client
import ipaddress
import signal
import socket
import ssl
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import FrameType
from urllib.parse import urlencode, urlsplit

from .numeric import MIB, Rejection, decode_json

HOST = "argovis-api.colorado.edu"
BASE = f"https://{HOST}"
PARAMETERS = {"/argo": {"startDate", "endDate", "polygon", "data", "id"}, "/argo/meta": {"id"}}


def validate_endpoint(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != HOST
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in PARAMETERS
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
    except ValueError:
        raise Rejection("unapproved_upstream_endpoint") from None
    return parsed.path


def public_addresses() -> tuple[str, ...]:
    addresses = tuple(
        sorted(
            {
                str(row[4][0])
                for row in socket.getaddrinfo(
                    HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
                )
            }
        )
    )
    if not addresses:
        raise Rejection("upstream_dns_empty")
    # Reject the entire answer if it mixes public and unsafe destinations.
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise Rejection("upstream_dns_unsafe")
    return addresses


@contextmanager
def operation_deadline(deadline: float) -> Iterator[None]:
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        raise Rejection("unsupported_worker_runtime")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Rejection("io_deadline")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise Rejection("overlapping_io_deadline")

    def expired(_: int, __: FrameType | None) -> None:
        raise Rejection("io_deadline")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, timeout: float) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(HOST, 443, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        # Never ask DNS a second time after checking the complete address set.
        plain = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(plain, server_hostname=HOST)
        except BaseException:
            plain.close()
            raise


@dataclass(frozen=True)
class Response:
    payload: bytes = field(repr=False)
    received_bytes: int
    retrieved_at: datetime
    headers: dict[str, str] = field(repr=False)
    # 200, or 404 only for a validated S1-SOURCE-2 empty-delivery receipt.
    status: int = 200


class HTTPFailure(Rejection):
    def __init__(self, status: int, retry_after: str | None = None) -> None:
        super().__init__("upstream_http_status")
        self.status = status
        # It is never part of the rendered exception and is validated before use.
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status in (408, 429) or 500 <= self.status <= 599


def retry_delay(attempt: int, retry_after: str | None, now: datetime, jitter: float) -> float:
    if not 1 <= attempt < 4 or not 0 <= jitter <= 1:
        raise Rejection("retry_exhausted")
    delay = float(2**attempt) * jitter
    if retry_after is not None:
        if len(retry_after) > 128:
            raise Rejection("invalid_retry_after")
        try:
            if retry_after.isascii() and retry_after.isdigit():
                requested = float(int(retry_after))
            else:
                instant = parsedate_to_datetime(retry_after)
                if instant.tzinfo is None:
                    raise ValueError
                requested = max(0.0, (instant - now).total_seconds())
            if not 0 <= requested <= 300:
                raise ValueError
        except (ValueError, OverflowError, TypeError):
            raise Rejection("invalid_retry_after") from None
        delay = max(delay, requested)
    return delay


def read_body(
    response: http.client.HTTPResponse,
    account: Callable[[int], None],
    *,
    raw_limit: int = 16 * MIB,
    json_limit: int = 128 * MIB,
) -> tuple[bytes, int]:
    if not 0 < raw_limit <= 16 * MIB or not 0 < json_limit <= 128 * MIB:
        raise Rejection("invalid_http_budget")
    headers = response.getheaders()
    lengths = [value for key, value in headers if key.lower() == "content-length"]
    transfers = [value for key, value in headers if key.lower() == "transfer-encoding"]
    if len(lengths) > 1 or (lengths and transfers) or len(transfers) > 1:
        raise Rejection("ambiguous_http_framing")
    length = None
    if lengths:
        if not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
            raise Rejection("invalid_content_length")
        length = int(lengths[0])
        if length > raw_limit:
            raise Rejection("compressed_size_limit")
    if transfers and transfers[0].lower() != "chunked":
        raise Rejection("unsupported_transfer_encoding")
    encoding = response.getheader("Content-Encoding", "identity").lower()
    if encoding not in ("identity", "gzip"):
        raise Rejection("unsupported_content_encoding")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    result = bytearray()
    count = 0
    while True:
        data = response.read(min(65536, raw_limit - count + 1))
        if not data:
            break
        count += len(data)
        account(len(data))  # Persist/reserve unsuccessful bytes too; no counter reset.
        if count > raw_limit:
            raise Rejection("compressed_size_limit")
        if decoder is None:
            piece = data
        else:
            try:
                piece = decoder.decompress(data, json_limit - len(result) + 1)
            except zlib.error:
                raise Rejection("invalid_gzip") from None
            if decoder.unused_data:
                raise Rejection("gzip_trailing_data")
        result.extend(piece)
        if len(result) > json_limit or (decoder is not None and decoder.unconsumed_tail):
            raise Rejection("decompressed_size_limit")
    if length is not None and count != length:
        raise Rejection("truncated_http_body")
    if decoder is not None and not decoder.eof:
        raise Rejection("truncated_gzip")
    return bytes(result), count


EMPTY_RECEIPT_PARAMETERS = frozenset({"startDate", "endDate", "polygon"})
EMPTY_RECEIPT_MAX_BYTES = 64


def empty_receipt_request(path: str, parameters: dict[str, str]) -> bool:
    """S1-SOURCE-2: only /argo selections by exactly startDate/endDate/polygon (+data=all)."""
    names = set(parameters)
    return path == "/argo" and (
        names == EMPTY_RECEIPT_PARAMETERS
        or (names == EMPTY_RECEIPT_PARAMETERS | {"data"} and parameters["data"] == "all")
    )


def empty_receipt(
    response: http.client.HTTPResponse,
    account: Callable[[int], None],
    enabled: Callable[[], bool],
) -> Response:
    """A 404 is an empty delivery only as complete application/json [] within 64 bytes.

    Anything else (error envelope, nonempty or malformed body, other content type,
    oversize or truncated framing) remains an ordinary failed HTTP 404.
    """
    content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPFailure(404)
    try:
        payload, count = read_body(
            response,
            account,
            raw_limit=EMPTY_RECEIPT_MAX_BYTES,
            json_limit=EMPTY_RECEIPT_MAX_BYTES,
        )
        body = decode_json(payload, max_bytes=EMPTY_RECEIPT_MAX_BYTES)
    except Rejection:
        raise HTTPFailure(404) from None
    if not isinstance(body, list) or body:
        raise HTTPFailure(404)
    if not enabled():
        raise Rejection("live_ingestion_disabled")
    return Response(
        payload,
        count,
        datetime.now(UTC),
        {
            "content-type": "application/json",
            "content-encoding": response.getheader("Content-Encoding", "identity"),
        },
        status=404,
    )


def fetch(
    path: str,
    parameters: dict[str, str],
    credential: str,
    account: Callable[[int], None],
    *,
    deadline: float,
    enabled: Callable[[], bool],
    raw_limit: int = 16 * MIB,
    json_limit: int = 128 * MIB,
) -> Response:
    validate_endpoint(BASE + path)
    if set(parameters) - PARAMETERS[path] or any(
        not isinstance(value, str) or len(value.encode()) > 65536 for value in parameters.values()
    ):
        raise Rejection("invalid_request_parameters")
    if parameters.get("data") not in (None, "all"):
        raise Rejection("unsupported_data_selection")
    if (
        not credential
        or len(credential) > 4096
        or any(ord(char) < 33 or ord(char) > 126 for char in credential)
    ):
        raise Rejection("invalid_argovis_credential")
    if not enabled():
        raise Rejection("live_ingestion_disabled")
    absolute = min(deadline, time.monotonic() + 120)
    connection = None
    try:
        # DNS/connect/TLS share one ten-second budget.
        with operation_deadline(min(absolute, time.monotonic() + 10)):
            address = public_addresses()[0]
            connection = PinnedConnection(address, min(10, absolute - time.monotonic()))
            connection.connect()
        with operation_deadline(absolute):
            if not enabled():
                raise Rejection("live_ingestion_disabled")
            assert connection.sock is not None
            connection.sock.settimeout(min(20, absolute - time.monotonic()))
            connection.request(
                "GET",
                path + "?" + urlencode(parameters),
                headers={
                    "Host": HOST,
                    "x-argokey": credential,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if 300 <= response.status <= 399:
                # Do not render Location, which could itself carry a credential.
                raise Rejection("upstream_redirect_rejected")
            if response.status == 404 and empty_receipt_request(path, parameters):
                return empty_receipt(response, account, enabled)
            if response.status != 200:
                raise HTTPFailure(response.status, response.getheader("Retry-After"))
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise Rejection("unsupported_content_type")
            payload, count = read_body(
                response, account, raw_limit=raw_limit, json_limit=json_limit
            )
            # A flag change stops an in-flight response from being reported successful.
            if not enabled():
                raise Rejection("live_ingestion_disabled")
            return Response(
                payload,
                count,
                datetime.now(UTC),
                {
                    "content-type": "application/json",
                    "content-encoding": response.getheader("Content-Encoding", "identity"),
                },
            )
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise Rejection("upstream_transport_failure") from None
    finally:
        if connection is not None:
            connection.close()
