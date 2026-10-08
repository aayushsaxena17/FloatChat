"""One bounded HTTP attempt. The durable controller alone decides whether to retry.

HTTPS connects to a prevalidated IP while preserving Argovis SNI and certificate
hostname verification. No proxy environment, redirect or client retry is used.
Deadlines use socket timeouts and monotonic checks, never POSIX alarms, so fetch and
the stage1-v4 governor work from any acquire thread. A single blocking read cannot be
interrupted between its socket timeouts; the checks run before and after every read.
"""

import http.client
import ipaddress
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
from urllib.parse import urlencode, urlsplit

from .numeric import MIB, Rejection, decode_json

HOST = "argovis-api.colorado.edu"
BASE = f"https://{HOST}"
# I/O bounds (contract §9; idle read per ADR-0043/0045): DNS+connect+TLS share 10 s.
CONNECT_BUDGET = 10.0
IDLE_READ = 110.0
ATTEMPT_BOUND = 120.0
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
    """Thread-safe bound: expired on entry or on a normal exit raises io_deadline.

    It cannot interrupt a blocked call; callers bound the call itself with socket or
    client timeouts. An exception from the body is never replaced by the exit check.
    """
    if time.monotonic() >= deadline:
        raise Rejection("io_deadline")
    yield
    if time.monotonic() >= deadline:
        raise Rejection("io_deadline")


_context_lock = threading.Lock()
_context: ssl.SSLContext | None = None


def tls_context() -> ssl.SSLContext:
    """One verified-default context per process; wrap_socket is thread-safe."""
    global _context
    with _context_lock:
        if _context is None:
            _context = ssl.create_default_context()
        return _context


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, timeout: float, *, until: float | None = None) -> None:
        self.tls_context = tls_context()
        super().__init__(HOST, 443, timeout=timeout, context=self.tls_context)
        self.address = address
        # Monotonic end of the shared connect+TLS budget (None: `timeout` per step).
        self.until = until

    def connect(self) -> None:
        # Never ask DNS a second time after checking the complete address set.
        plain = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            if self.until is not None:
                remaining = self.until - time.monotonic()
                if remaining <= 0:
                    raise Rejection("io_deadline")
                plain.settimeout(remaining)
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


# ADR-0045: retries must outlast measured upstream slow episodes (>=15 min), so the
# three backoffs use 60/180/300 s maxima with equal jitter (a guaranteed half-maximum
# floor). Four attempts per logical request and the 300 s Retry-After cap are unchanged.
RETRY_MAXIMA = {1: 60.0, 2: 180.0, 3: 300.0}


def retry_delay(attempt: int, retry_after: str | None, now: datetime, jitter: float) -> float:
    if not 1 <= attempt < 4 or not 0 <= jitter <= 1:
        raise Rejection("retry_exhausted")
    maximum = RETRY_MAXIMA[attempt]
    delay = maximum / 2 + maximum / 2 * jitter
    if retry_after is not None:
        delay = max(delay, retry_after_seconds(retry_after, now))
    return delay


def retry_after_seconds(retry_after: str, now: datetime) -> float:
    """The server-requested wait, bounded to 300 s; invalid values are rejected."""
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
    return requested


class UpstreamGovernor:
    """In-process adaptive cap on concurrent credentialed requests (stage1-v4).

    Permits start at the configured maximum, halve (minimum 1) on an HTTP 429 and come
    back one at a time after `restore_after` consecutive non-429 completions. After a 429
    no request starts for max(Retry-After, `pause`) seconds. A holder gets the lowest free
    slot number; the caller maps it to the advisory lock (164993423, slot), so another
    process still cannot exceed the environment's slots. Thread-safe.
    """

    pulse = 10.0  # seconds between `on_wait` calls (lease heartbeat, live-flag check)

    def __init__(self, permits: int, *, pause: float = 60.0, restore_after: int = 20) -> None:
        if not 1 <= permits <= 64 or pause < 0 or restore_after < 1:
            raise Rejection("invalid_upstream_slot")
        self.maximum, self.pause, self.restore_after = permits, pause, restore_after
        self._current = permits
        self._condition = threading.Condition()
        self._held: set[int] = set()
        self._streak = 0
        self.blocked_until = 0.0
        self.observed_429 = 0
        self.restored = 0
        self.lowest = permits

    @property
    def current_permits(self) -> int:
        with self._condition:
            return self._current

    def snapshot(self) -> dict[str, int]:
        with self._condition:
            return {
                "maximum_permits": self.maximum,
                "current_permits": self._current,
                "lowest_permits": self.lowest,
                "observed_429": self.observed_429,
                "restored_permits": self.restored,
            }

    def acquire(self, deadline: float, on_wait: Callable[[], None] | None = None) -> int:
        """Block for a permit until `deadline` (monotonic); `on_wait` runs every `pulse` s."""
        last = time.monotonic()
        while True:
            with self._condition:
                now = time.monotonic()
                if now >= deadline:
                    raise Rejection("upstream_slot_deadline")
                blocked = self.blocked_until - now
                if blocked <= 0 and len(self._held) < self._current:
                    slot = next(s for s in range(1, self.maximum + 1) if s not in self._held)
                    self._held.add(slot)
                    return slot
                nap = min(1.0, self.pulse)
                self._condition.wait(min(nap, deadline - now, blocked if blocked > 0 else nap))
            if on_wait is not None and time.monotonic() - last >= self.pulse:
                on_wait()
                last = time.monotonic()

    def release(self, slot: int, status: int | None, retry_after: float | None = None) -> None:
        """Return a permit; `status` is the HTTP status seen, None when none was.

        `retry_after` (seconds, already validated by retry_after_seconds) only matters
        for a 429, where it lengthens the block beyond `pause`.
        """
        with self._condition:
            if slot not in self._held:
                raise Rejection("invalid_upstream_slot")
            self._held.discard(slot)
            if status == 429:
                self.observed_429 += 1
                self._streak = 0
                self._current = max(1, self._current // 2)
                self.lowest = min(self.lowest, self._current)
                self.blocked_until = max(
                    self.blocked_until, time.monotonic() + max(retry_after or 0.0, self.pause)
                )
            elif self._current < self.maximum:
                self._streak += 1
                if self._streak >= self.restore_after:
                    self._current += 1
                    self.restored += 1
                    self._streak = 0
            self._condition.notify_all()


def read_body(
    response: http.client.HTTPResponse,
    account: Callable[[int], None],
    *,
    raw_limit: int = 16 * MIB,
    json_limit: int = 128 * MIB,
    tick: Callable[[], None] | None = None,
) -> tuple[bytes, int]:
    # `tick` runs before and after every read: it re-arms the socket timeout and raises
    # io_deadline once the attempt bound has passed (a late-returning read is rejected).
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
        if tick is not None:
            tick()
        data = response.read(min(65536, raw_limit - count + 1))
        if not data:
            if tick is not None:
                tick()
            break
        count += len(data)
        account(len(data))  # Persist/reserve unsuccessful bytes too; no counter reset.
        if tick is not None:
            tick()  # after accounting: a late read's bytes still count
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
    tick: Callable[[], None] | None = None,
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
            tick=tick,
        )
        body = decode_json(payload, max_bytes=EMPTY_RECEIPT_MAX_BYTES)
    except Rejection as error:
        if error.category == "io_deadline":
            raise  # the attempt bound, not a malformed receipt
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
    absolute = min(deadline, time.monotonic() + ATTEMPT_BOUND)
    connection = None
    connected = False
    try:
        # DNS/connect/TLS share one ten-second budget. getaddrinfo has no timeout of its
        # own: its overrun is rejected after it returns (OS resolver timeouts bound it).
        until = min(absolute, time.monotonic() + CONNECT_BUDGET)
        with operation_deadline(until):
            address = public_addresses()[0]
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise Rejection("io_deadline")
            connection = PinnedConnection(address, remaining, until=until)
            connection.connect()
        connected = True
        with operation_deadline(absolute):
            if not enabled():
                raise Rejection("live_ingestion_disabled")
            sock = connection.sock
            assert sock is not None

            def tick() -> None:
                # ADR-0043/0045: upstream slow episodes measured >60 s to first byte.
                left = absolute - time.monotonic()
                if left <= 0:
                    raise Rejection("io_deadline")
                sock.settimeout(min(IDLE_READ, left))

            tick()
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
            tick()
            if 300 <= response.status <= 399:
                # Do not render Location, which could itself carry a credential.
                raise Rejection("upstream_redirect_rejected")
            if response.status == 404 and empty_receipt_request(path, parameters):
                return empty_receipt(response, account, enabled, tick)
            if response.status != 200:
                raise HTTPFailure(response.status, response.getheader("Retry-After"))
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise Rejection("unsupported_content_type")
            payload, count = read_body(
                response, account, raw_limit=raw_limit, json_limit=json_limit, tick=tick
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
    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
        # A connect-phase timeout exhausted the shared budget; a read timeout is idle.
        if time.monotonic() >= absolute or (not connected and isinstance(error, TimeoutError)):
            raise Rejection("io_deadline") from None
        raise Rejection("upstream_transport_failure") from None
    finally:
        if connection is not None:
            connection.close()
