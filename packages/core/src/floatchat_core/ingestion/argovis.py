"""Name-based mapping for the pinned Argovis core API 2.36.2 representation."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .numeric import HASH_VERSION, CanonicalBudget, Rejection, ScientificNumber, scientific_number
from .planning import GEOMETRY_VERSION, Interval, PlannedChunk, in_region, timestamp
from .revisions import Revision

MAPPING_VERSION = "argovis-core-v1"
LEGACY_SOURCE_CONTRACT = "argovis-core-2.36.2-v1"
SOURCE_CONTRACT = "argovis-core-2.36.2+ifremer-fluorescence-v1"
TRANSLATOR_REVISION = "cbf2bb48ed5d95532c18bb2cd5217e44618356cf"
TRANSLATOR_SHA256 = "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
ADDITIONAL_NONCORE = frozenset({"chla_fluorescence", "chla_fluorescence_qc"})
VARIABLES = ("pressure", "temperature", "salinity")
UNITS = {
    "pressure": ({"dbar", "decibar"}, "dbar"),
    "temperature": ({"degree_C", "degrees C", "degree_Celsius"}, "degree_C"),
    "salinity": ({"psu", "PSU", "PSS-78", "1"}, "1"),
}
# Taken from components.schemas.argo_data_keys, pinned spec 2.36.2.
OUTSIDE_CORE = frozenset(
    {
        "bbp470",
        "bbp532",
        "bbp700",
        "bbp700_2",
        "bisulfide",
        "cdom",
        "chla",
        "cndc",
        "cndx",
        "cp660",
        "down_irradiance380",
        "down_irradiance412",
        "down_irradiance442",
        "down_irradiance443",
        "down_irradiance490",
        "down_irradiance555",
        "down_irradiance670",
        "downwelling_par",
        "doxy",
        "doxy2",
        "doxy3",
        "molar_doxy",
        "nitrate",
        "ph_in_situ_total",
        "salinity_sfile",
        "temperature_sfile",
        "turbidity",
        "up_radiance412",
        "up_radiance443",
        "up_radiance490",
        "up_radiance555",
    }
)
PROFILE_FIELDS = frozenset(
    {
        "_id",
        "metadata",
        "geolocation",
        "basin",
        "timestamp",
        "date_updated_argovis",
        "source",
        "cycle_number",
        "data_info",
        "data",
        "data_warning",
        "profile_direction",
        "geolocation_argoqc",
        "timestamp_argoqc",
        "vertical_sampling_scheme",
    }
)
REQUIRED_FIELDS = frozenset(
    {
        "metadata",
        "geolocation",
        "basin",
        "timestamp",
        "date_updated_argovis",
        "source",
        "cycle_number",
        "data_info",
        "data",
    }
)


def bounded_text(value: Any, max_bytes: int, category: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > max_bytes:
        raise Rejection(category)
    return value


def integer(value: Any, category: str) -> int:
    if not isinstance(value, Decimal) or value < 0 or value != value.to_integral_value():
        raise Rejection(category)
    if value > 9223372036854775807:
        raise Rejection(category)
    return int(value)


def sanitize_source_url(value: Any) -> str:
    text = bounded_text(value, 65536, "invalid_source_url")
    try:
        url = urlsplit(text)
        # No URLs are fetched. Drop all query/fragment/userinfo regardless of key names.
        host = url.hostname
        if not host or not url.scheme:
            raise ValueError
        port = f":{url.port}" if url.port is not None else ""
        path = re.sub(r"[\x00-\x1f]", "", url.path)
        return urlunsplit((url.scheme, host.lower() + port, path, "", ""))
    except ValueError:
        raise Rejection("invalid_source_url") from None


def source_revision(sources: Any) -> Revision | None:
    if not isinstance(sources, list):
        raise Rejection("invalid_source")
    components: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) - {"source", "url", "date_updated", "doi"}:
            raise Rejection("invalid_source")
        labels = source.get("source")
        if (
            not isinstance(labels, list)
            or not labels
            or not all(isinstance(x, str) for x in labels)
        ):
            raise Rejection("invalid_source")
        path = sanitize_source_url(source.get("url"))
        key = json.dumps([sorted(labels), path], separators=(",", ":"))
        if key in components:
            raise Rejection("duplicate_revision_component")
        components[key] = timestamp(source["date_updated"]) if source.get("date_updated") else None
    if not components or any(value is None for value in components.values()):
        return None
    return Revision("argovis-source-vector-v1", tuple(sorted(components.items())))


def qc(value: Any) -> tuple[str | None, str | None, tuple[str, ...]]:
    if value is None or value == "":
        return None, None if value is None else "", ()
    if isinstance(value, Decimal):
        text = str(int(value)) if value == value.to_integral_value() else str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise Rejection("invalid_qc_shape")
    known = len(text) == 1 and text in "0123456789"
    return (text if known else None), text, (() if known else ("unknown_qc",))


@dataclass(frozen=True)
class Profile:
    source_profile_id: str | None
    platform: str
    cycle: int | None
    direction: str
    observed_at: str
    longitude: ScientificNumber
    latitude: ScientificNumber
    revision: Revision | None
    levels: tuple[dict[str, Any], ...]
    canonical_bytes: bytes
    content_hash: str
    outside_core_arrays: int

    @property
    def natural_key(self) -> tuple[str, int, str, str, str] | None:
        if self.cycle is None or self.direction not in ("A", "D"):
            return None
        return self.platform, self.cycle, self.direction, self.observed_at, "single"

    @property
    def identity(self) -> str:
        if self.source_profile_id is not None:
            return "id:" + self.source_profile_id
        return "natural:" + json.dumps(self.natural_key, separators=(",", ":"))


def _data_columns(
    document: dict[str, Any], *, source_contract: str = SOURCE_CONTRACT
) -> tuple[dict[str, list[Any]], dict[str, Any], int]:
    if source_contract not in (SOURCE_CONTRACT, LEGACY_SOURCE_CONTRACT):
        raise Rejection("unsupported_source_contract")
    info, data = document["data_info"], document["data"]
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
        if source_contract == SOURCE_CONTRACT and name in ADDITIONAL_NONCORE:
            if any(value is not None and not isinstance(value, Decimal | str) for value in array):
                raise Rejection("invalid_noncore_scalar")
            if any(value is not None and not isinstance(value, str) for value in attributes):
                raise Rejection("invalid_variable_metadata")
            continue
        base = re.sub(r"(_argoqc)$", "", name)
        base = re.sub(r"(_std|_med)$", "", base)
        if base not in set(VARIABLES) | OUTSIDE_CORE:
            raise Rejection("unknown_data_field")
    assert length is not None
    return columns, metadata, length


def map_profile(
    document: dict[str, Any],
    metadata: dict[str, dict[str, Any]],
    budget: CanonicalBudget,
    *,
    source_contract: str = SOURCE_CONTRACT,
) -> Profile:
    if not isinstance(document, dict):
        raise Rejection("unsupported_profile_schema")
    if set(document) - PROFILE_FIELDS or not REQUIRED_FIELDS <= document.keys():
        raise Rejection("unsupported_profile_schema")
    warnings = document.get("data_warning", [])
    if not isinstance(warnings, list) or warnings:
        raise Rejection("upstream_data_warning")
    identifier = document.get("_id")
    if identifier is not None:
        identifier = bounded_text(identifier, 512, "invalid_profile_id")
    pointers = document["metadata"]
    if not isinstance(pointers, list) or not pointers:
        raise Rejection("missing_metadata")
    platforms = set()
    for pointer in pointers:
        pointer = bounded_text(pointer, 512, "invalid_metadata_pointer")
        if pointer not in metadata:
            raise Rejection("unresolved_metadata")
        meta = metadata[pointer]
        if meta.get("_id") != pointer or meta.get("data_type") != "oceanicProfile":
            raise Rejection("invalid_metadata")
        platforms.add(bounded_text(meta.get("platform"), 32, "missing_platform"))
    if len(platforms) != 1:
        raise Rejection("conflicting_platform")
    platform = platforms.pop()
    cycle = document["cycle_number"]
    cycle = None if cycle is None and identifier else integer(cycle, "invalid_cycle")
    direction = document.get("profile_direction", "U")
    if direction not in ("A", "D", "U") or (direction == "U" and identifier is None):
        raise Rejection("invalid_direction")
    observed = timestamp(document["timestamp"]).isoformat(timespec="microseconds")
    timestamp(document["date_updated_argovis"])  # Provenance only, never hashed or ordered.
    point = document["geolocation"]
    if not isinstance(point, dict) or set(point) != {"type", "coordinates"}:
        raise Rejection("invalid_coordinates")
    coordinates = point["coordinates"]
    if point["type"] != "Point" or not isinstance(coordinates, list) or len(coordinates) != 2:
        raise Rejection("invalid_coordinates")
    lon, lat = (scientific_number(x, coordinate=True) for x in coordinates)
    in_region(coordinates[0], coordinates[1])  # Validate legal WGS84 even for filtered profiles.
    columns, column_meta, count = _data_columns(document, source_contract=source_contract)
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
            if not present and variable + "_argoqc" in columns:
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
            else:
                flags = ["variable_absent"]
            if number.value is not None:
                low, high = {"pressure": (-5, 12000), "temperature": (-5, 50), "salinity": (0, 50)}[
                    variable
                ]
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
        "source": "argovis",
        "platform": platform,
        "cycle": cycle,
        "direction": direction,
        "observed_at": observed,
        "longitude": lon.canonical(),
        "latitude": lat.canonical(),
        "position_qc": qc(document.get("geolocation_argoqc")),
        "time_qc": qc(document.get("timestamp_argoqc")),
        "sampling": document.get("vertical_sampling_scheme"),
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
        source_revision(document["source"]),
        tuple(levels),
        canonical_bytes,
        digest,
        len(set(columns) - {v + s for v in VARIABLES for s in ("", "_argoqc")}),
    )


def request_parameters(chunk: PlannedChunk, *, inventory: bool) -> dict[str, str]:
    result = {
        "startDate": chunk.interval.start.isoformat().replace("+00:00", "Z"),
        "endDate": chunk.interval.end.isoformat().replace("+00:00", "Z"),
        "polygon": chunk.tile.polygon(),
    }
    if not inventory:
        result["data"] = "all"
    return result


def inventory_identities(documents: Any, interval: Interval) -> frozenset[str]:
    if not isinstance(documents, list) or len(documents) > 2000:
        raise Rejection("invalid_inventory")
    result: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            raise Rejection("invalid_inventory")
        if not interval.contains(timestamp(document.get("timestamp", ""))):
            continue
        location = document.get("geolocation")
        if not isinstance(location, dict) or location.get("type") != "Point":
            raise Rejection("invalid_coordinates")
        point = location.get("coordinates", [])
        if not isinstance(point, list) or len(point) != 2:
            raise Rejection("invalid_coordinates")
        if not in_region(point[0], point[1]):
            continue
        identifier = bounded_text(document.get("_id"), 512, "inventory_missing_id")
        if identifier in result:
            raise Rejection("duplicate_inventory_id")
        result.add(identifier)
    return frozenset(result)


def verify_inventory(before: Any, data: Any, after: Any, interval: Interval) -> None:
    a, b, c = (inventory_identities(x, interval) for x in (before, data, after))
    if a != b or b != c:
        raise Rejection("incomplete_inventory")


def policy_versions(source_contract: str = SOURCE_CONTRACT) -> dict[str, str]:
    if source_contract not in (SOURCE_CONTRACT, LEGACY_SOURCE_CONTRACT):
        raise Rejection("unsupported_source_contract")
    result = {
        "geometry": GEOMETRY_VERSION,
        "mapping": MAPPING_VERSION,
        "hash": HASH_VERSION,
        "specification": "2.36.2",
        "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
        "qc": "core-good-v1",
    }
    if source_contract == SOURCE_CONTRACT:
        result.update(
            source_contract=SOURCE_CONTRACT,
            translator_revision=TRANSLATOR_REVISION,
            translator_sha256=TRANSLATOR_SHA256,
        )
    return result
