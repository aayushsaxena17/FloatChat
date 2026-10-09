"""Argo GDAC NetCDF bulk source: Indian Ocean daily basin files and the global profile index.

Mapping `gdac-core-v1` keeps the `argovis-core-v1` canonical structure (level keys, flags,
units, QC tokens, `scientific-json-v2` bytes) and changes only what is source specific:

- `source` is `gdac`, `mapping_version` is `gdac-core-v1`.
- Exact text: every stored measurement/coordinate is rendered with
  `numpy.format_float_positional(value, unique=True, trim="-")` of the stored dtype
  (float32 for PRES/TEMP/PSAL, float64 for LATITUDE/LONGITUDE), i.e. the shortest decimal
  that round-trips that dtype. `Decimal(text)` feeds `scientific_number`, so the canonical
  `exact` is that text. The float32 shortest text usually is not exactly representable in
  binary64, hence the `rounded` flag is expected on most measurements.
- The stored `_FillValue` (99999) is emitted as the token 99999 and becomes `argo_fill`;
  stored NaN/Inf become the quoted nonfinite tokens of contract 5.1. Trailing all-fill rows
  (PRES, TEMP and PSAL, original and adjusted) are dropped, interior fills are kept.
- Data mode is the profile's DATA_MODE (R/A/D) for pressure, temperature and salinity; A/D
  select the adjusted arrays and `_ADJUSTED_ERROR` (as `*_error`), R selects the originals.
- Identity is `gdac:<platform>_<cycle><direction>`; the revision is the file DATE_UPDATE
  (`Revision("gdac-date-update-v1", (("file", timestamp),))`).
- JULD (days since 1950-01-01 UTC) is rendered as UTC ISO 8601 with microseconds.
"""

import fcntl
import gzip
import hashlib
import http.client
import io
import ipaddress
import json
import os
import random
import re
import secrets
import socket
import ssl
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np

from .argovis import (
    PROFILE_FIELDS,
    UNITS,
    VARIABLES,
    Profile,
    bounded_text,
    integer,
    qc,
    request_parameters,
)
from .json_stream import documents
from .landing import Landing
from .numeric import (
    HASH_VERSION,
    MIB,
    CanonicalBudget,
    Rejection,
    exact_number,
    scientific_number,
)
from .objects import ObjectStore, publish_verified
from .planning import GEOMETRY_VERSION, Interval, PlannedChunk, Tile, timestamp
from .raw import sanitize_raw
from .repository import Authority, Repository
from .revisions import Revision
from .transport import HTTPFailure, retry_delay

GDAC_HOST = "data-argo.ifremer.fr"
GDAC_BASE = f"https://{GDAC_HOST}"
INDEX_KEY = "ar_index_global_prof.txt.gz"
ATTRIBUTION = (
    "Argo (2000). Argo float data and metadata from Global Data Assembly Centre (Argo GDAC). "
    "SEANOE. https://doi.org/10.17882/42182"
)
SOURCE = "gdac"
MAPPING_VERSION = "gdac-core-v1"
REVISION_KIND = "gdac-date-update-v1"
SCHEMA = "gdac-core-v1-object-array"
VERSIONS = {
    "geometry": GEOMETRY_VERSION,
    "mapping": MAPPING_VERSION,
    "hash": HASH_VERSION,
    "specification": "gdac-netcdf",
    "qc": "core-good-v1",
    "source_contract": MAPPING_VERSION,
}
MAX_FILE_BYTES = 128 * MIB
INDEX_MAX_BYTES = 2 * 1024**3
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
CORE = (("PRES", "pressure"), ("TEMP", "temperature"), ("PSAL", "salinity"))
PLAUSIBLE = {"pressure": (-5, 12000), "temperature": (-5, 50), "salinity": (0, 50)}
NONFINITE = frozenset({"NaN", "Infinity", "-Infinity"})

# Only the global index, a month directory listing and a daily basin file are fetchable.
GDAC_PATH = re.compile(
    r"(?:ar_index_global_prof\.txt\.gz|geo/indian_ocean/\d{4}/\d{2}/(?:\d{8}_prof\.nc)?)\Z"
)


def validate_path(path: str) -> str:
    if not isinstance(path, str) or not GDAC_PATH.fullmatch(path):
        raise Rejection("unapproved_upstream_endpoint")
    return "/" + path


def public_addresses() -> tuple[str, ...]:
    addresses = tuple(
        sorted(
            {
                str(row[4][0])
                for row in socket.getaddrinfo(
                    GDAC_HOST, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
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


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, address: str, timeout: float) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(GDAC_HOST, 443, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        # Never ask DNS a second time after checking the complete address set.
        plain = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(plain, server_hostname=GDAC_HOST)
        except BaseException:
            plain.close()
            raise


def read_file_body(response: http.client.HTTPResponse, absolute: float, max_bytes: int) -> bytes:
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
        if length > max_bytes:
            raise Rejection("gdac_file_size_limit")
    if transfers and transfers[0].lower() != "chunked":
        raise Rejection("unsupported_transfer_encoding")
    if response.getheader("Content-Encoding", "identity").lower() != "identity":
        raise Rejection("unsupported_content_encoding")
    result = bytearray()
    while True:
        if time.monotonic() >= absolute:
            raise Rejection("io_deadline")
        data = response.read(min(65536, max_bytes - len(result) + 1))
        if not data:
            break
        result.extend(data)
        if len(result) > max_bytes:
            raise Rejection("gdac_file_size_limit")
    if length is not None and len(result) != length:
        raise Rejection("truncated_http_body")
    return bytes(result)


def fetch_file(
    path: str, deadline: float, *, max_bytes: int = MAX_FILE_BYTES, attempt_seconds: float = 3600
) -> bytes:
    """One bounded anonymous GET of an approved GDAC file; the caller owns retries.

    No credential, proxy, redirect or compression is used. Socket timeouts and
    monotonic checks (no signals) keep it usable from any thread.
    """
    target = validate_path(path)
    if not 0 < max_bytes <= MAX_FILE_BYTES:
        raise Rejection("invalid_http_budget")
    # Bulk files need longer than the 120 s Argovis attempt bound (measured 30-50 KB/s here).
    absolute = min(deadline, time.monotonic() + attempt_seconds)
    if absolute <= time.monotonic():
        raise Rejection("io_deadline")
    connection = None
    try:
        last_error: Exception | None = None
        for address in public_addresses():
            candidate = PinnedConnection(address, max(0.1, min(10, absolute - time.monotonic())))
            try:
                candidate.connect()
            except (OSError, ssl.SSLError) as error:
                candidate.close()
                last_error = error
                continue
            connection = candidate
            break
        if connection is None:
            raise Rejection("upstream_transport_failure") from last_error
        assert connection.sock is not None
        connection.sock.settimeout(max(0.1, min(60, absolute - time.monotonic())))
        connection.request(
            "GET",
            target,
            headers={
                "Host": GDAC_HOST,
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if 300 <= response.status <= 399:
            raise Rejection("upstream_redirect_rejected")
        if response.status != 200:
            raise HTTPFailure(response.status, response.getheader("Retry-After"))
        return read_file_body(response, absolute, max_bytes)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise Rejection("upstream_transport_failure") from None
    finally:
        if connection is not None:
            connection.close()


# --- global profile index -------------------------------------------------------------------

INDEX_FILE = re.compile(r"[A-Z]{1,2}([0-9A-Za-z]+)_([0-9]{3,})(D?)\.nc\Z")


@dataclass(frozen=True)
class IndexEntry:
    file: str
    date: datetime
    latitude: Decimal
    longitude: Decimal
    ocean: str
    profiler: str
    institution: str
    date_update: datetime | None

    @property
    def identity(self) -> str | None:
        """`gdac:<platform>_<cycle><direction>` from the per-float profile file name."""
        match = INDEX_FILE.fullmatch(self.file.rsplit("/", 1)[-1])
        if match is None:
            return None
        return f"{SOURCE}:{match[1]}_{int(match[2])}{'D' if match[3] else 'A'}"


def _index_lines(raw: bytes) -> Iterator[bytes]:
    """Stream lines of a gzip or plain index with bounded line and decompressed sizes."""
    stream: Any = io.BytesIO(raw)
    if raw[:2] == b"\x1f\x8b":
        stream = gzip.GzipFile(fileobj=stream)
    total = 0
    try:
        while line := stream.readline(4097):
            total += len(line)
            if len(line) > 4096 or total > INDEX_MAX_BYTES:
                raise Rejection(
                    "decompressed_size_limit" if total > INDEX_MAX_BYTES else "invalid_index_line"
                )
            yield line
    except (OSError, EOFError):
        raise Rejection("invalid_gzip") from None


def _index_instant(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        raise Rejection("invalid_index_line") from None


def _index_decimal(text: str) -> Decimal:
    try:
        return exact_number(text)
    except Rejection:
        raise Rejection("invalid_index_line") from None


def scan_index(raw: bytes, interval: Interval | None = None) -> Iterator[IndexEntry]:
    """Profiles with date, latitude and longitude inside the operational box and interval.

    Rows without a date or position cannot be placed in any tile and are skipped. The
    date string compare is lexicographic on fixed-width UTC digits, before any parsing.
    """
    lower = interval.start.strftime("%Y%m%d%H%M%S") if interval else ""
    upper = interval.end.strftime("%Y%m%d%H%M%S") if interval else "99999999999999"
    for line in _index_lines(raw):
        if line.startswith((b"#", b"file,")):
            continue
        try:
            fields = line.rstrip(b"\r\n").decode("ascii").split(",")
        except UnicodeDecodeError:
            raise Rejection("invalid_index_line") from None
        if len(fields) != 8:
            raise Rejection("invalid_index_line")
        file, date, latitude, longitude, ocean, profiler, institution, update = fields
        if not (date and latitude and longitude):
            continue
        if len(date) != 14 or not date.isdigit():
            raise Rejection("invalid_index_line")
        if not lower <= date < upper:
            continue
        lat, lon = _index_decimal(latitude), _index_decimal(longitude)
        if not (-60 <= lat <= 30 and 20 <= lon <= 120):
            continue
        yield IndexEntry(
            file,
            _index_instant(date),
            lat,
            lon,
            ocean,
            profiler,
            institution,
            _index_instant(update) if update else None,
        )


def index_entries(raw_index_bytes: bytes, interval: Interval, tile: Tile) -> list[IndexEntry]:
    """Index rows owned by the tile inside [start, end), ordered by date and file."""
    return sorted(
        (
            entry
            for entry in scan_index(raw_index_bytes, interval)
            if interval.contains(entry.date) and tile.owns(entry.longitude, entry.latitude)
        ),
        key=lambda entry: (entry.date, entry.file),
    )


def daily_file_keys(interval: Interval) -> list[str]:
    """One Indian Ocean basin file per UTC day that intersects [start, end)."""
    day = interval.start.date()
    last = (interval.end - timedelta(microseconds=1)).date()
    if (last - day).days > 3660:
        raise Rejection("invalid_interval")
    keys = []
    while day <= last:
        keys.append(f"geo/indian_ocean/{day:%Y}/{day:%m}/{day:%Y%m%d}_prof.nc")
        day += timedelta(days=1)
    return keys


# --- NetCDF conversion ----------------------------------------------------------------------

VALUE_ARRAYS = tuple(f"{short}{suffix}" for short, _ in CORE for suffix in ("", "_ADJUSTED"))
EXTRA_ARRAYS = tuple(
    f"{short}{suffix}" for short, _ in CORE for suffix in ("_ADJUSTED_ERROR", "_QC", "_ADJUSTED_QC")
)
NETCDF_CELL_LIMIT = 200_000_000


def exact_text(value: Any) -> str:
    """Shortest decimal that round-trips the stored dtype (gdac-core-v1 exact text)."""
    if not np.isfinite(value):
        return "NaN" if np.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    return str(np.format_float_positional(value, unique=True, trim="-"))


def _open(source: str | Path | bytes) -> netCDF4.Dataset:
    try:
        if isinstance(source, bytes | bytearray):
            dataset = netCDF4.Dataset("gdac.nc", mode="r", memory=bytes(source))
        else:
            dataset = netCDF4.Dataset(str(source), mode="r")
    except (OSError, RuntimeError, ValueError):
        raise Rejection("invalid_netcdf") from None
    dataset.set_auto_maskandscale(False)  # stored dtype and fill values, never masked/scaled
    try:
        for name in ("PLATFORM_NUMBER", "CYCLE_NUMBER", "DIRECTION", "DATA_MODE", "JULD"):
            if name not in dataset.variables:
                raise Rejection("invalid_netcdf")
        for name in ("LATITUDE", "LONGITUDE"):
            if name not in dataset.variables:
                raise Rejection("invalid_netcdf")
        if "N_PROF" not in dataset.dimensions:
            raise Rejection("invalid_netcdf")
        levels = len(dataset.dimensions["N_LEVELS"]) if "N_LEVELS" in dataset.dimensions else 0
        if len(dataset.dimensions["N_PROF"]) * levels > NETCDF_CELL_LIMIT:
            raise Rejection("netcdf_size_limit")
        for name in (*VALUE_ARRAYS, *EXTRA_ARRAYS):
            if name in dataset.variables and {"scale_factor", "add_offset"} & set(
                dataset.variables[name].ncattrs()
            ):
                raise Rejection("unsupported_netcdf_packing")
    except BaseException:
        dataset.close()
        raise
    return dataset


def validate_netcdf(payload: bytes) -> dict[str, int | str]:
    dataset = _open(payload)
    try:
        return {"schema": "gdac-netcdf-v1", "profiles": len(dataset.dimensions["N_PROF"])}
    finally:
        dataset.close()


def _strings(array: Any) -> list[str]:
    """Decode a char array (n,) or (n, width) to stripped text, one string per profile."""
    data = np.ascontiguousarray(array)
    if data.ndim == 2:
        data = data.view(f"S{data.shape[1]}").reshape(data.shape[0])
    return [item.decode("utf-8", "replace").strip("\x00 ") for item in data.tolist()]


def _compact_instant(text: str, category: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        raise Rejection(category) from None


def _date_update(dataset: netCDF4.Dataset) -> str | None:
    if "DATE_UPDATE" not in dataset.variables:
        return None
    text = "".join(_strings(np.asarray(dataset.variables["DATE_UPDATE"][:]).reshape(1, -1)))
    return _compact_instant(text, "invalid_timestamp").isoformat() if text else None


def _fill(variable: Any) -> Any:
    declared = variable.getncattr("_FillValue") if "_FillValue" in variable.ncattrs() else 99999.0
    return variable.dtype.type(declared)


def _chars(row: Any) -> list[str]:
    text = np.ascontiguousarray(row).tobytes().decode("ascii", "replace")
    return ["" if char in " \x00" else char for char in text]


def profile_identities(source: str | Path | bytes) -> set[str]:
    """`gdac:<platform>_<cycle><direction>` of every profile in the file, located or not."""
    dataset = _open(source)
    try:
        platforms = _strings(dataset.variables["PLATFORM_NUMBER"][:])
        cycles = np.asarray(dataset.variables["CYCLE_NUMBER"][:]).tolist()
        directions = _strings(dataset.variables["DIRECTION"][:])
        return {
            f"{SOURCE}:{p}_{c}{d}" for p, c, d in zip(platforms, cycles, directions, strict=True)
        }
    finally:
        dataset.close()


def profiles_from_netcdf(
    source: str | Path | bytes,
    tile: Tile | None = None,
    interval: Interval | None = None,
    *,
    name: str | None = None,
    excluded: Counter[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """One document per profile owned by `tile` inside `interval` (all when omitted).

    Values are exact text (see the module docstring). Profiles without a usable position
    or time cannot belong to any tile and profiles without a single non-fill core level
    carry no science; both are skipped and counted in `excluded`
    (no_position, no_time, no_core_levels). Everything else is passed on unchanged so the
    mapper's strict validation decides.
    """
    dataset = _open(source)
    try:
        label = (
            name
            if name is not None
            else (Path(source).name if isinstance(source, str | Path) else "")
        )
        yield from _profiles(
            dataset, tile, interval, label, excluded if excluded is not None else Counter()
        )
    finally:
        dataset.close()


def _profiles(
    dataset: netCDF4.Dataset,
    tile: Tile | None,
    interval: Interval | None,
    label: str,
    excluded: Counter[str],
) -> Iterator[dict[str, Any]]:
    variables = dataset.variables
    count = len(dataset.dimensions["N_PROF"])
    if count == 0:
        return
    update = _date_update(dataset)
    platforms = _strings(variables["PLATFORM_NUMBER"][:])
    cycles = np.asarray(variables["CYCLE_NUMBER"][:]).tolist()
    cycle_fill = int(_fill(variables["CYCLE_NUMBER"]))
    directions = _strings(variables["DIRECTION"][:])
    modes = _strings(variables["DATA_MODE"][:])
    juld = variables["JULD"][:]
    juld_fill = _fill(variables["JULD"])
    latitude, longitude = variables["LATITUDE"][:], variables["LONGITUDE"][:]
    lat_fill, lon_fill = _fill(variables["LATITUDE"]), _fill(variables["LONGITUDE"])
    juld_qc = _strings(variables["JULD_QC"][:]) if "JULD_QC" in variables else [""] * count
    position_qc = (
        _strings(variables["POSITION_QC"][:]) if "POSITION_QC" in variables else [""] * count
    )
    centres = _strings(variables["DATA_CENTRE"][:]) if "DATA_CENTRE" in variables else [""] * count
    sampling = (
        _strings(variables["VERTICAL_SAMPLING_SCHEME"][:])
        if "VERTICAL_SAMPLING_SCHEME" in variables
        else [""] * count
    )
    present = [n for n in (*VALUE_ARRAYS, *EXTRA_ARRAYS) if n in variables]
    fills = {n: _fill(variables[n]) for n in present if variables[n].dtype.kind == "f"}
    units = {
        n: str(variables[n].getncattr("units")).strip()
        for n in present
        if n in fills and "units" in variables[n].ncattrs()
    }
    for index in range(count):
        lat, lon, instant = latitude[index], longitude[index], juld[index]
        if (
            not (np.isfinite(lat) and np.isfinite(lon))
            or lat == lat_fill
            or lon == lon_fill
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        ):
            excluded["no_position"] += 1
            continue
        if not np.isfinite(instant) or instant == juld_fill:
            excluded["no_time"] += 1
            continue
        try:
            observed = EPOCH + timedelta(microseconds=round(float(instant) * 86_400_000_000))
        except OverflowError:
            excluded["no_time"] += 1
            continue
        lon_text, lat_text = exact_text(lon), exact_text(lat)
        if interval is not None and not interval.contains(observed):
            continue
        if tile is not None and not tile.owns(Decimal(lon_text), Decimal(lat_text)):
            continue
        rows = {n: variables[n][index, :] for n in present}
        valid = np.zeros(len(rows[present[0]]), dtype=bool) if present else np.zeros(0, dtype=bool)
        for n in VALUE_ARRAYS:
            if n in rows:
                valid |= rows[n] != fills[n]
        levels = int(np.flatnonzero(valid)[-1]) + 1 if valid.any() else 0
        if not levels:
            excluded["no_core_levels"] += 1
            continue
        document: dict[str, Any] = {
            "platform": platforms[index],
            "cycle": None if cycles[index] == cycle_fill else int(cycles[index]),
            "direction": directions[index],
            "observed_at": observed.isoformat(timespec="microseconds"),
            "longitude": lon_text,
            "latitude": lat_text,
            "data_mode": modes[index],
            "position_qc": position_qc[index],
            "juld_qc": juld_qc[index],
            "date_update": update,
            "data_centre": centres[index],
            "file": label,
            "n_levels": levels,
            "sampling": sampling[index] or None,
            "units": dict(units),
        }
        for n in present:
            sliced = rows[n][:levels]
            if n in fills:
                fill = fills[n]
                document[n] = ["99999" if v == fill else exact_text(v) for v in sliced]
            else:
                document[n] = _chars(sliced)
        yield document


# --- Argovis wire shape and mapping ---------------------------------------------------------


class _Token(Decimal):
    """A JSON number carried as its exact written text."""

    source_token: str

    def __new__(cls, token: str) -> "_Token":
        exact_number(token)  # Same grammar, token, exponent and normalization limits.
        instance = super().__new__(cls, token)
        instance.source_token = token
        return instance


def _numbers(values: list[str]) -> list[Any]:
    return [value if value in NONFINITE else _Token(value) for value in values]


def _wire_text(value: Any) -> str:
    if isinstance(value, _Token):
        return value.source_token
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                f"{json.dumps(key, ensure_ascii=True)}:{_wire_text(item)}"
                for key, item in sorted(value.items())
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(_wire_text(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def encode_wire(document: dict[str, Any]) -> bytes:
    """JSON text of a wire document: sorted keys, numbers exactly as written."""
    return _wire_text(document).encode()


def wire_document(document: dict[str, Any], *, data: bool = True) -> dict[str, Any]:
    """Argovis wire shape of a `profiles_from_netcdf` document.

    `data=False` is the inventory form. The profile's DATA_MODE selects the arrays
    exactly as Argovis merges them: R the originals, A/D the adjusted values with their
    adjusted QC and `_ADJUSTED_ERROR` as `*_error`.
    """
    if not isinstance(document, dict):
        raise Rejection("unsupported_profile_schema")
    platform = bounded_text(document.get("platform"), 32, "missing_platform")
    if not re.fullmatch(r"[0-9A-Za-z]+", platform):
        raise Rejection("missing_platform")
    cycle, direction = document.get("cycle"), document.get("direction")
    if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 0:
        raise Rejection("invalid_cycle")
    if direction not in ("A", "D"):
        raise Rejection("invalid_direction")
    for key in ("longitude", "latitude"):
        if not isinstance(document.get(key), str):
            raise Rejection("invalid_coordinates")
    pointer = f"{SOURCE}:{platform}"
    wire: dict[str, Any] = {
        "_id": f"{pointer}_{cycle}{direction}",
        "metadata": [pointer],
        "geolocation": {
            "type": "Point",
            "coordinates": [_Token(document["longitude"]), _Token(document["latitude"])],
        },
        "timestamp": document.get("observed_at"),
        "cycle_number": _Token(str(cycle)),
        "profile_direction": direction,
    }
    if not data:
        return wire
    mode = document.get("data_mode")
    adjusted = mode in ("A", "D")
    names: list[str] = []
    columns: list[Any] = []
    attributes: list[list[str | None]] = []
    units = document.get("units", {})
    for short, variable in CORE:
        value = short + ("_ADJUSTED" if adjusted else "")
        if value not in document:
            continue
        names.append(variable)
        columns.append(_numbers(document[value]))
        attributes.append([units.get(value), mode])
        if value + "_QC" in document:
            names.append(variable + "_argoqc")
            columns.append(list(document[value + "_QC"]))
            attributes.append([None, None])
        if adjusted and value + "_ERROR" in document:
            names.append(variable + "_error")
            columns.append(_numbers(document[value + "_ERROR"]))
            attributes.append([units.get(value + "_ERROR"), None])
    update = document.get("date_update")
    file = document.get("file")
    source: dict[str, Any] = {"source": ["argo_gdac"]}
    if isinstance(file, str) and file.startswith("geo/"):
        source["url"] = f"{GDAC_BASE}/{file}"
    if update:
        source["date_updated"] = update
    wire.update(
        {
            "source": [source],
            "geolocation_argoqc": document.get("position_qc"),
            "timestamp_argoqc": document.get("juld_qc"),
            "data_info": [names, ["units", "data_keys_mode"], attributes],
            "data": columns,
        }
    )
    if document.get("sampling") is not None:
        wire["vertical_sampling_scheme"] = document["sampling"]
    return wire


GDAC_REQUIRED = frozenset(
    {
        "_id",
        "metadata",
        "geolocation",
        "timestamp",
        "source",
        "cycle_number",
        "profile_direction",
        "data_info",
        "data",
    }
)
GDAC_COLUMNS = frozenset(v + s for v in VARIABLES for s in ("", "_argoqc", "_error"))


def _columns(wire: dict[str, Any]) -> tuple[dict[str, list[Any]], dict[str, Any], int]:
    info, data = wire["data_info"], wire["data"]
    if not (
        isinstance(info, list)
        and len(info) == 3
        and all(isinstance(x, list) for x in info)
        and isinstance(data, list)
    ):
        raise Rejection("invalid_data_info")
    names, attrs, values = info
    if (
        not names
        or len(names) != len(data)
        or len(names) != len(values)
        or not all(isinstance(x, str) for x in names + attrs)
        or len(set(names)) != len(names)
        or len(set(attrs)) != len(attrs)
        or set(attrs) - {"units", "data_keys_mode"}
    ):
        raise Rejection("invalid_data_info")
    columns: dict[str, list[Any]] = {}
    metadata: dict[str, Any] = {}
    length: int | None = None
    for name, array, attributes in zip(names, data, values, strict=True):
        if not isinstance(array, list) or not 0 < len(array) <= 10000:
            raise Rejection("invalid_array_length")
        if length is not None and length != len(array):
            raise Rejection("mismatched_array_lengths")
        length = len(array)
        if not isinstance(attributes, list) or len(attributes) != len(attrs):
            raise Rejection("invalid_data_info")
        columns[name] = array
        metadata[name] = dict(zip(attrs, attributes, strict=True))
        if name not in GDAC_COLUMNS:
            raise Rejection("unknown_data_field")
    assert length is not None
    return columns, metadata, length


def _source_revision(sources: Any) -> Revision | None:
    if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
        raise Rejection("invalid_source")
    if set(sources[0]) - {"source", "url", "date_updated", "doi"}:
        raise Rejection("invalid_source")
    updated = sources[0].get("date_updated")
    if not updated:
        return None
    return Revision(REVISION_KIND, (("file", timestamp(updated)),))


def gdac_map_profile(
    document: dict[str, Any],
    budget: CanonicalBudget,
    metadata: dict[str, dict[str, Any]] | None = None,
) -> Profile:
    """Map one GDAC profile to the `gdac-core-v1` canonical form.

    `document` is a `profiles_from_netcdf` document or its wire form (`wire_document`,
    what GdacSource lands). `metadata`, when given, must resolve the profile's pointer
    like the Argovis mapper requires.
    """
    wire = (
        document
        if isinstance(document, dict) and "data_info" in document
        else wire_document(document)
    )
    if set(wire) - PROFILE_FIELDS or not GDAC_REQUIRED <= wire.keys():
        raise Rejection("unsupported_profile_schema")
    identifier = bounded_text(wire["_id"], 512, "invalid_profile_id")
    pointers = wire["metadata"]
    if not isinstance(pointers, list) or len(pointers) != 1:
        raise Rejection("missing_metadata")
    pointer = bounded_text(pointers[0], 512, "invalid_metadata_pointer")
    platform = pointer.removeprefix(f"{SOURCE}:")
    if platform == pointer or not re.fullmatch(r"[0-9A-Za-z]{1,32}", platform):
        raise Rejection("invalid_metadata_pointer")
    if metadata is not None:
        if pointer not in metadata:
            raise Rejection("unresolved_metadata")
        meta = metadata[pointer]
        if meta.get("_id") != pointer or meta.get("data_type") != "oceanicProfile":
            raise Rejection("invalid_metadata")
        if bounded_text(meta.get("platform"), 32, "missing_platform") != platform:
            raise Rejection("conflicting_platform")
    cycle = integer(wire["cycle_number"], "invalid_cycle")
    direction = wire["profile_direction"]
    if direction not in ("A", "D"):
        raise Rejection("invalid_direction")
    if identifier != f"{pointer}_{cycle}{direction}":
        raise Rejection("invalid_profile_id")
    observed = timestamp(wire["timestamp"]).isoformat(timespec="microseconds")
    point = wire["geolocation"]
    if not isinstance(point, dict) or set(point) != {"type", "coordinates"}:
        raise Rejection("invalid_coordinates")
    coordinates = point["coordinates"]
    if point["type"] != "Point" or not isinstance(coordinates, list) or len(coordinates) != 2:
        raise Rejection("invalid_coordinates")
    lon, lat = (scientific_number(x, coordinate=True) for x in coordinates)
    if not (lon.value is not None and lat.value is not None):
        raise Rejection("invalid_coordinates")
    if not (-180 <= lon.value <= 180 and -90 <= lat.value <= 90):
        raise Rejection("invalid_coordinates")
    columns, column_meta, count = _columns(wire)
    levels: list[dict[str, Any]] = []
    canonical_levels: list[dict[str, Any]] = []
    previous_pressure: float | None = None
    seen_pressure: set[float] = set()
    for index in range(count):
        row: dict[str, Any] = {"level_index": index}
        content: dict[str, Any] = {"level_index": index}
        for variable in VARIABLES:
            attr = column_meta.get(variable, {})
            unit, mode = attr.get("units"), attr.get("data_keys_mode")
            if (unit is not None and not isinstance(unit, str)) or (
                mode is not None and not isinstance(mode, str)
            ):
                raise Rejection("invalid_variable_metadata")
            present = variable in columns
            if not present and (variable + "_argoqc" in columns or variable + "_error" in columns):
                raise Rejection("qc_without_variable")
            if present and mode not in ("R", "A", "D"):
                raise Rejection("unknown_data_mode")
            number = scientific_number(columns[variable][index] if present else None)
            if number.value is not None and unit not in UNITS[variable][0]:
                raise Rejection("unknown_unit")
            for suffix in (
                "",
                "_adjusted",
                "_error",
                "_original_error",
                "_qc",
                "_adjusted_qc",
                "_qc_source",
                "_adjusted_qc_source",
            ):
                row[variable + suffix] = None
                content[variable + suffix] = None
            selected = variable + ("_adjusted" if mode in ("A", "D") else "")
            if present:
                row[selected] = number.value
                content[selected] = number.canonical()
                qc_array = columns.get(variable + "_argoqc")
                q = qc(None if qc_array is None else qc_array[index])
                selected_qc = variable + ("_adjusted_qc" if mode in ("A", "D") else "_qc")
                row[selected_qc], row[selected_qc + "_source"] = q[:2]
                content[selected_qc], content[selected_qc + "_source"] = q[:2]
                flags = list(number.flags + q[2])
                error_array = columns.get(variable + "_error")
                if error_array is not None:
                    if mode not in ("A", "D"):
                        raise Rejection("invalid_data_info")
                    error = scientific_number(error_array[index], error=True)
                    row[variable + "_error"] = error.value
                    content[variable + "_error"] = error.canonical()
            else:
                flags = ["variable_absent"]
            if number.value is not None:
                low, high = PLAUSIBLE[variable]
                if not low <= number.value <= high:
                    flags.append("outside_plausibility_range")
                if variable == "pressure":
                    if number.value in seen_pressure:
                        flags.append("repeated_pressure")
                    if previous_pressure is not None and number.value < previous_pressure:
                        flags.append("nonmonotonic_pressure")
                    previous_pressure = number.value
                    seen_pressure.add(number.value)
            for suffix, value in (
                ("_unit", UNITS[variable][1] if unit in UNITS[variable][0] else None),
                ("_unit_source", unit),
                ("_data_mode", mode),
                ("_flags", flags),
            ):
                row[variable + suffix] = value
                content[variable + suffix] = value
        levels.append(row)
        canonical_levels.append(content)
    canonical = {
        "source": SOURCE,
        "platform": platform,
        "cycle": cycle,
        "direction": direction,
        "observed_at": observed,
        "longitude": lon.canonical(),
        "latitude": lat.canonical(),
        "position_qc": qc(wire.get("geolocation_argoqc")),
        "time_qc": qc(wire.get("timestamp_argoqc")),
        "sampling": wire.get("vertical_sampling_scheme"),
        "levels": canonical_levels,
        "hash_version": HASH_VERSION,
        "mapping_version": MAPPING_VERSION,
    }
    canonical_bytes, digest = budget.encode(canonical)
    return Profile(
        identifier,
        platform,
        cycle,
        direction,
        observed,
        lon,
        lat,
        _source_revision(wire["source"]),
        tuple(levels),
        canonical_bytes,
        digest,
        len(set(columns) - {v + s for v in VARIABLES for s in ("", "_argoqc", "_error")}),
    )


# --- download cache -------------------------------------------------------------------------

Fetch = Callable[..., bytes]


@contextmanager
def _exclusive(path: Path, deadline: float) -> Iterator[None]:
    """Cross-thread and cross-process lock so each file is downloaded once."""
    with path.open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Rejection("io_deadline") from None
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _download(
    key: str,
    deadline: float,
    *,
    fetch: Fetch,
    heartbeat: Callable[[], None] | None,
    sleep: Callable[[float], None],
    jitter: Callable[[], float],
    clock: Callable[[], float],
) -> bytes:
    """Up to four attempts with the Stage 1 backoff; categories match RequestOwner."""
    attempt = 0
    while True:
        attempt += 1
        if clock() >= deadline:
            raise Rejection("http_retry_deadline")
        if heartbeat is not None:
            heartbeat()
        try:
            return bytes(fetch(key, deadline, max_bytes=MAX_FILE_BYTES))
        except HTTPFailure as error:
            if attempt >= 4 or not error.retryable:
                raise Rejection("http_retry_exhausted") from None
            delay = retry_delay(attempt, error.retry_after, datetime.now(UTC), jitter())
        except Rejection as error:
            if attempt >= 4 or error.category not in ("upstream_transport_failure", "io_deadline"):
                raise
            delay = retry_delay(attempt, None, datetime.now(UTC), jitter())
        end = clock() + delay
        if end >= deadline:
            raise Rejection("http_retry_deadline")
        while clock() < end:
            if heartbeat is not None:
                heartbeat()
            sleep(min(10, max(0.0, end - clock())))


def _store_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.part")
    try:
        with temporary.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cached_file(
    cache_dir: Path,
    key: str,
    deadline: float,
    *,
    fetch: Fetch = fetch_file,
    heartbeat: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    """The daily file in the cache, downloaded (and opened as NetCDF) at most once."""
    validate_path(key)
    path = cache_dir / key.rsplit("/", 1)[1]
    with _exclusive(path.with_name(path.name + ".lock"), deadline):
        if path.is_file():
            return path
        data = _download(
            key, deadline, fetch=fetch, heartbeat=heartbeat, sleep=sleep, jitter=jitter, clock=clock
        )
        validate_netcdf(data)
        _store_atomic(path, data)
    return path


def cached_index(
    cache_dir: Path,
    expected_sha256: str | None,
    deadline: float,
    *,
    fetch: Fetch = fetch_file,
    heartbeat: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Path, str]:
    """The global index in the cache; a digest other than the run's pinned one is refused."""
    path = cache_dir / INDEX_KEY
    with _exclusive(path.with_name(path.name + ".lock"), deadline):
        if not path.is_file():
            data = _download(
                INDEX_KEY,
                deadline,
                fetch=fetch,
                heartbeat=heartbeat,
                sleep=sleep,
                jitter=jitter,
                clock=clock,
            )
            if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
                raise Rejection("gdac_index_changed")
            _store_atomic(path, data)
        status = path.stat()
        # The 58 MB index is hashed once per file version, not once per landing.
        memo = (str(path), status.st_size, status.st_mtime_ns)
        if memo not in _DIGESTS:
            _DIGESTS[memo] = hashlib.sha256(path.read_bytes()).hexdigest()
        digest = _DIGESTS[memo]
    if expected_sha256 is not None and digest != expected_sha256:
        raise Rejection("gdac_index_changed")
    return path, digest


def prepare_cache(
    cache_dir: Path, interval: Interval, deadline: float, **options: Any
) -> dict[str, str]:
    """Fill the cache for a run (index and daily files); returns the input descriptor."""
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _, digest = cached_index(cache_dir, None, deadline, **options)
    for key in daily_file_keys(interval):
        cached_file(cache_dir, key, deadline, **options)
    return {"kind": "gdac", "cache_dir": str(cache_dir), "index_sha256": digest}


# --- landing source -------------------------------------------------------------------------

_INDEX_CACHE: dict[tuple[str, datetime, datetime], tuple[IndexEntry, ...]] = {}
_DIGESTS: dict[tuple[str, int, int], str] = {}
_INDEX_LOCK = threading.Lock()
ROLES = ("inventory_before", "inventory_after", "profile", "metadata")


def logical_key(path: str, parameters: dict[str, str], role: str) -> str:
    if role not in ROLES or path != ("/argo/meta" if role == "metadata" else "/argo"):
        raise Rejection("invalid_request_role")
    return hashlib.sha256(
        json.dumps(
            {
                "specification": "gdac-netcdf",
                "source_contract": MAPPING_VERSION,
                "path": path,
                "parameters": parameters,
                "role": role,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate_wire(payload: bytes) -> dict[str, int | str]:
    return {"schema": SCHEMA, "documents": sum(1 for _ in documents(payload))}


@dataclass
class Selection:
    """The derived landing of one chunk: wire pieces plus the files they came from."""

    inventory: list[bytes]
    profile: list[bytes]
    files: list[tuple[str, Path, str]]  # key, cache path, sha256
    evidence: dict[str, Any]
    retrieved: datetime


class GdacSource:
    """Serves Argovis-shaped landings derived from the cached GDAC daily files.

    Every role of a chunk is computed from the same immutable cached files, so the
    inventory triple agrees by construction; `restart_selection` therefore cannot help.
    """

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
        fetch: Fetch = fetch_file,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repository, self.store, self.authority = repository, store, authority
        self.deadline, self.application_commit = deadline, application_commit
        self.require_existing = require_existing
        self.fetch, self.sleep, self.jitter, self.clock = fetch, sleep, jitter, clock
        self.descriptor = descriptor
        index = descriptor.get("index_sha256")
        cache = descriptor.get("cache_dir")
        if (
            descriptor.get("kind") != SOURCE
            or not isinstance(index, str)
            or not re.fullmatch(r"[0-9a-f]{64}", index)
            or not isinstance(cache, str)
        ):
            raise Rejection("invalid_gdac_descriptor")
        self.cache = Path(cache).resolve()
        if str(self.cache).startswith(("/mnt/", "C:")):
            raise Rejection("unapproved_cache_path")
        self.index_sha256 = index
        self.selected: tuple[tuple[Interval, Tile], Selection] | None = None
        self.published: dict[str, str] = {}

    def restart_selection(self) -> None:
        # The cached files cannot become a different upstream snapshot.
        raise Rejection("incomplete_inventory")

    def heartbeat(self) -> None:
        self.repository.heartbeat(self.authority)

    def plan(self) -> PlannedChunk:
        row = self.repository.chunk(self.authority.chunk)
        return PlannedChunk(
            Interval(row["requested_start"], row["requested_end"]), Tile(**row["tile"])
        )

    def obtain(self, path: str, parameters: dict[str, str], role: str) -> Landing:
        key = logical_key(path, parameters, role)
        existing = self.repository.verified_landing(self.authority, key)
        if existing is not None:
            data = self.store.read(existing["object_key"], MAX_FILE_BYTES, self.deadline)
            if (
                len(data) != existing["bytes"]
                or hashlib.sha256(data).hexdigest() != existing["sha256"]
                or existing["versions"] != VERSIONS
            ):
                raise Rejection("landing_unavailable")
            validate_wire(data)
            return Landing(existing, data)
        if self.require_existing:
            raise Rejection("landing_unavailable")
        files: list[tuple[str, Path, str]] = []
        extra: dict[str, Any] = {}
        retrieved = datetime.now(UTC)
        if role == "metadata":
            payload = self.metadata(parameters)
        else:
            plan = self.plan()
            if parameters != request_parameters(plan, inventory=role != "profile"):
                raise Rejection("invalid_request_parameters")
            selection = self.select(plan)
            pieces = selection.profile if role == "profile" else selection.inventory
            payload = b"[" + b",".join(pieces) + b"]"
            files, extra, retrieved = selection.files, selection.evidence, selection.retrieved
        if len(payload) > MAX_FILE_BYTES:
            raise Rejection("decompressed_size_limit")
        attempt = self.repository.recorded_reserve(self.authority, key, role, parameters, SOURCE)
        cleaned = sanitize_raw(payload)
        derived = [
            {"file": name, "sha256": digest, "object_key": self.preserve(attempt, file, digest)}
            for name, file, digest in files
        ]
        evidence = publish_verified(
            self.store,
            cleaned.payload,
            attempt,
            validate_wire,
            deadline=self.deadline,
            raw=True,
            max_bytes=MAX_FILE_BYTES,
        )
        manifest = {
            "id": str(attempt),
            "key": evidence.key,
            "sha256": evidence.sha256,
            "bytes": evidence.byte_count,
            "retrieved_at": retrieved.isoformat(),
            "versions": VERSIONS,
            "sanitization": {
                **cleaned.manifest,
                "input_origin": SOURCE,
                "input_kind": SOURCE,
                "read_at_actual_utc": datetime.now(UTC).isoformat(),
                "validation": evidence.validation,
                "derived_from": derived,
                **extra,
            },
            "application_commit": self.application_commit,
            "http_status": 200,
        }
        self.repository.finish_attempt(
            self.authority, attempt, "verified_raw", 200, manifest=manifest
        )
        return Landing(manifest, cleaned.payload)

    def preserve(self, attempt: uuid.UUID, file: Path, digest: str) -> str:
        """Raw NetCDF object for a cached file; every tile of a month shares one object."""
        if digest not in self.published:
            key = f"raw/sha256/{digest}.nc"
            try:
                found: dict[str, Any] | None = self.store.stat(key, self.deadline)
            except Rejection as error:
                if error.category != "object_missing":
                    raise
                found = None
            # Content-addressed and written once: an existing object of the right size is it.
            if (
                found is not None
                and found.get("bytes") == file.stat().st_size
                and found.get("sha256") in (None, digest)
            ):
                self.published[digest] = key
            else:
                self.published[digest] = publish_verified(
                    self.store,
                    file.read_bytes(),
                    attempt,
                    validate_netcdf,
                    deadline=self.deadline,
                    raw="nc",
                    max_bytes=MAX_FILE_BYTES,
                ).key
        return self.published[digest]

    def metadata(self, parameters: dict[str, str]) -> bytes:
        if set(parameters) != {"id"}:
            raise Rejection("invalid_request_parameters")
        pointer = bounded_text(parameters["id"], 512, "invalid_metadata_pointer")
        platform = pointer.removeprefix(f"{SOURCE}:")
        if platform == pointer or not re.fullmatch(r"[0-9A-Za-z]{1,32}", platform):
            raise Rejection("invalid_metadata_pointer")
        return json.dumps(
            [{"_id": pointer, "data_type": "oceanicProfile", "platform": platform}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def index_entries(self, interval: Interval) -> tuple[IndexEntry, ...]:
        path, digest = cached_index(
            self.cache,
            self.index_sha256,
            self.deadline,
            fetch=self.fetch,
            heartbeat=self.heartbeat,
            sleep=self.sleep,
            jitter=self.jitter,
            clock=self.clock,
        )
        cache_key = (digest, interval.start, interval.end)
        with _INDEX_LOCK:
            if cache_key not in _INDEX_CACHE:
                if len(_INDEX_CACHE) >= 8:
                    _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
                _INDEX_CACHE[cache_key] = tuple(scan_index(path.read_bytes(), interval))
            return _INDEX_CACHE[cache_key]

    def select(self, plan: PlannedChunk) -> Selection:
        if self.selected is not None and self.selected[0] == (plan.interval, plan.tile):
            return self.selected[1]
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        files: list[tuple[str, Path, str]] = []
        present: set[str] = set()
        for name in daily_file_keys(plan.interval):
            self.pulse()
            self.heartbeat()
            file = cached_file(
                self.cache,
                name,
                self.deadline,
                fetch=self.fetch,
                heartbeat=self.heartbeat,
                sleep=self.sleep,
                jitter=self.jitter,
                clock=self.clock,
            )
            files.append((name, file, hashlib.sha256(file.read_bytes()).hexdigest()))
            present |= profile_identities(file)
        expected = {
            entry.identity
            for entry in self.index_entries(plan.interval)
            if entry.ocean == "I"
            and entry.identity is not None
            and plan.interval.contains(entry.date)
            and plan.tile.owns(entry.longitude, entry.latitude)
        }
        # Every indexed Indian Ocean profile of the chunk must be in the daily files.
        if expected - present:
            raise Rejection("incomplete_inventory")
        excluded: Counter[str] = Counter()
        inventory: list[bytes] = []
        profile: list[bytes] = []
        identities: set[str] = set()
        size = 0
        for name, file, _ in files:
            for document in profiles_from_netcdf(
                file, plan.tile, plan.interval, name=name, excluded=excluded
            ):
                self.pulse()
                full = wire_document(document)
                if full["_id"] in identities:
                    raise Rejection("duplicate_inventory_id")
                identities.add(full["_id"])
                if len(identities) > 2000:
                    raise Rejection("profile_count_limit")
                profile.append(encode_wire(full))
                inventory.append(encode_wire(wire_document(document, data=False)))
                size += len(profile[-1])
                if size > MAX_FILE_BYTES:
                    raise Rejection("decompressed_size_limit")
        retrieved = max(datetime.fromtimestamp(file.stat().st_mtime, UTC) for _, file, _ in files)
        selection = Selection(
            inventory,
            profile,
            files,
            {
                "excluded": dict(sorted(excluded.items())),
                "index_expected": len(expected),
                "index_sha256": self.index_sha256,
                "profiles": len(identities),
            },
            retrieved,
        )
        self.selected = ((plan.interval, plan.tile), selection)
        return selection

    def pulse(self) -> None:
        if time.monotonic() >= self.deadline:
            raise Rejection("work_deadline")
