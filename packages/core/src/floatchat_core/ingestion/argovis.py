"""Name-based mapping for the pinned Argovis core API 2.36.2 representation."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from operator import itemgetter
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import urlsplit, urlunsplit

from .numeric import HASH_VERSION, CanonicalBudget, Rejection, ScientificNumber, scientific_number
from .planning import GEOMETRY_VERSION, Interval, PlannedChunk, in_region, timestamp
from .revisions import Revision

if TYPE_CHECKING:
    import pyarrow as pa

MAPPING_VERSION = "argovis-core-v1"
LEGACY_SOURCE_CONTRACT = "argovis-core-2.36.2-v1"
SOURCE_CONTRACT = "argovis-core-2.36.2+ifremer-fluorescence-v1"
GDAC_SOURCE_CONTRACT = "gdac-core-v1"
TRANSLATOR_REVISION = "cbf2bb48ed5d95532c18bb2cd5217e44618356cf"
TRANSLATOR_SHA256 = "279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f"
ADDITIONAL_NONCORE = frozenset({"chla_fluorescence", "chla_fluorescence_qc"})
VARIABLES = ("pressure", "temperature", "salinity")
PLAUSIBLE = {"pressure": (-5, 12000), "temperature": (-5, 50), "salinity": (0, 50)}
LEVEL_SUFFIXES = (
    "",
    "_adjusted",
    "_error",
    "_original_error",
    "_qc",
    "_adjusted_qc",
    "_qc_source",
    "_adjusted_qc_source",
)
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
    if source_contract not in (SOURCE_CONTRACT, LEGACY_SOURCE_CONTRACT, GDAC_SOURCE_CONTRACT):
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


class _Column(NamedTuple):
    """Level-invariant facts about one core variable, fixed once per profile."""

    error: str | None
    array: list[Any] | None
    qc_array: list[Any] | None
    unit_ok: bool
    selected: str
    selected_qc: str
    selected_qc_source: str
    flags_key: str
    low: float
    high: float
    track: bool


def _variables(
    columns: dict[str, list[Any]], column_meta: dict[str, Any]
) -> tuple[dict[str, Any], list[_Column]]:
    """Per-variable constants and the level template.

    The template carries the final key order: None-filled value and QC slots and the
    level-invariant unit and mode entries. A pending metadata rejection is recorded, not
    raised, so map_profile raises it at the same point of the first level as before.
    """
    template: dict[str, Any] = {"level_index": None}
    result: list[_Column] = []
    for variable in VARIABLES:
        attr = column_meta.get(variable, {})
        unit, mode = attr.get("units"), attr.get("data_keys_mode")
        present = variable in columns
        error = None
        if (unit is not None and not isinstance(unit, str)) or (
            mode is not None and not isinstance(mode, str)
        ):
            error = "invalid_variable_metadata"
        elif not present and variable + "_argoqc" in columns:
            error = "qc_without_variable"
        elif present and mode not in ("R", "A", "D"):
            error = "unknown_data_mode"
        units, canonical_unit = UNITS[variable]
        unit_ok = error != "invalid_variable_metadata" and unit in units
        for suffix in LEVEL_SUFFIXES:
            template[variable + suffix] = None
        template[variable + "_unit"] = canonical_unit if unit_ok else None
        template[variable + "_unit_source"] = unit
        template[variable + "_data_mode"] = mode
        template[variable + "_flags"] = None
        adjusted = mode in ("A", "D")
        selected_qc = variable + ("_adjusted_qc" if adjusted else "_qc")
        low, high = PLAUSIBLE[variable]
        result.append(
            _Column(
                error,
                columns.get(variable),
                columns.get(variable + "_argoqc"),
                unit_ok,
                variable + ("_adjusted" if adjusted else ""),
                selected_qc,
                selected_qc + "_source",
                variable + "_flags",
                low,
                high,
                variable == "pressure",
            )
        )
    return template, result


def _levels(
    columns: dict[str, list[Any]], column_meta: dict[str, Any], count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Level rows and their canonical content, in the key order of the stage1-v3 mapper."""
    template, variables = _variables(columns, column_meta)
    no_number = scientific_number(None)
    null_entry = (no_number.value, no_number.canonical(), no_number.flags)
    no_qc = qc(None)
    # Per-profile memo of pure per-token results. scientific_number depends on the numeric
    # value alone. qc renders a non-integral Decimal's own text (1.5 versus 1.50), so
    # Decimal QC tokens are keyed by that text rather than by value.
    numbers: dict[Decimal, tuple[float | None, dict[str, Any], tuple[str, ...]]] = {}
    qc_texts: dict[str, tuple[str | None, str | None, tuple[str, ...]]] = {}
    qc_decimals: dict[str, tuple[str | None, str | None, tuple[str, ...]]] = {}
    levels: list[dict[str, Any]] = []
    canonical_levels: list[dict[str, Any]] = []
    previous_pressure: float | None = None
    seen_pressure: set[float] = set()
    for index in range(count):
        row = template.copy()
        row["level_index"] = index
        content = template.copy()
        content["level_index"] = index
        # Checks keep their original order: a pending metadata rejection surfaces only
        # after the earlier variables passed this level.
        for (
            error,
            array,
            qc_array,
            unit_ok,
            selected,
            selected_qc,
            selected_qc_source,
            flags_key,
            low,
            high,
            track,
        ) in variables:
            if error is not None:
                raise Rejection(error)
            if array is None:
                row[flags_key] = content[flags_key] = ["variable_absent"]
                continue
            token = array[index]
            if token.__class__ is Decimal:
                try:
                    entry = numbers.get(token)
                except TypeError:
                    entry = None  # Signaling NaN is unhashable; scientific_number rejects it.
                if entry is None:
                    number = scientific_number(token)
                    entry = numbers[token] = (number.value, number.canonical(), number.flags)
            elif token is None:
                entry = null_entry
            else:
                number = scientific_number(token)
                entry = (number.value, number.canonical(), number.flags)
            value = entry[0]
            if value is not None and not unit_ok:
                raise Rejection("unknown_unit")
            row[selected] = value
            content[selected] = entry[1]
            if qc_array is None:
                q = no_qc
            else:
                token = qc_array[index]
                if token.__class__ is Decimal:
                    text = str(token)
                    hit = qc_decimals.get(text)
                    if hit is None:
                        hit = qc_decimals[text] = qc(token)
                    q = hit
                elif token.__class__ is str:
                    hit = qc_texts.get(token)
                    if hit is None:
                        hit = qc_texts[token] = qc(token)
                    q = hit
                elif token is None:
                    q = no_qc
                else:
                    q = qc(token)
            row[selected_qc] = content[selected_qc] = q[0]
            row[selected_qc_source] = content[selected_qc_source] = q[1]
            flags = [*entry[2], *q[2]]
            if value is not None:
                if not low <= value <= high:
                    flags.append("outside_plausibility_range")
                if track:
                    if value in seen_pressure:
                        flags.append("repeated_pressure")
                    if previous_pressure is not None and value < previous_pressure:
                        flags.append("nonmonotonic_pressure")
                    previous_pressure = value
                    seen_pressure.add(value)
            row[flags_key] = content[flags_key] = flags
        levels.append(row)
        canonical_levels.append(content)
    return levels, canonical_levels


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
    levels, canonical_levels = _levels(columns, column_meta, count)
    gdac = source_contract == GDAC_SOURCE_CONTRACT
    canonical = {
        "source": "gdac" if gdac else "argovis",
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
        "mapping_version": GDAC_SOURCE_CONTRACT if gdac else MAPPING_VERSION,
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


LEVEL_PREFIX = '{"level_index":'
PROFILE_COLUMNS = frozenset({"profile_id", "source_profile_id", "profile_hash", "profile_content"})


@cache
def _level_schema() -> Any:
    import pyarrow as pa

    from .parquet import schema  # parquet imports this module, so load it on first use

    full = schema()
    return pa.schema(
        [field for field in full if field.name not in PROFILE_COLUMNS], metadata=full.metadata
    )


def _level_texts(profile: Profile) -> list[str]:
    """Canonical JSON of every level, cut from the profile's canonical bytes.

    A level is the only object whose first key is level_index, and a quote inside a JSON
    string is always escaped, so the marker occurs only between two levels. The cut is
    checked against the level count and indexes; any mismatch re-parses the profile and
    encodes each level as parquet.rows() does.
    """
    text = profile.canonical_bytes.decode()
    opening = text.find('"levels":[')
    closing = text.find('],"longitude":', opening)
    if opening >= 0 and closing > opening:
        region = text[opening + len('"levels":[') : closing]
        if region.startswith(LEVEL_PREFIX) and region.endswith("}"):
            parts = region[len(LEVEL_PREFIX) : -1].split("}," + LEVEL_PREFIX)
            if len(parts) == len(profile.levels) and all(
                part.startswith(f"{index},") for index, part in enumerate(parts)
            ):
                return [LEVEL_PREFIX + part + "}" for part in parts]
    return [
        json.dumps(level, sort_keys=True, separators=(",", ":"))
        for level in json.loads(profile.canonical_bytes)["levels"]
    ]


def level_table(profile: Profile) -> "pa.Table":
    """The profile's levels as Parquet rows without the per-profile columns."""
    import pyarrow as pa

    schema = _level_schema()
    names = [field.name for field in schema if field.name != "canonical_level"]
    # One C-level pass per level, then a transpose, instead of a Python loop per column.
    per_level = map(itemgetter(*names), profile.levels)
    transposed = list(zip(*per_level, strict=True)) or [()] * len(names)
    columns = dict(zip(names, transposed, strict=True))
    columns["canonical_level"] = _level_texts(profile)
    return pa.Table.from_arrays(
        [pa.array(columns[field.name], type=field.type) for field in schema], schema=schema
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


def source_of(versions: dict[str, Any]) -> str:
    """The source population a run's policy versions belong to (mirror of app.run_source)."""
    return "gdac" if versions.get("mapping") == GDAC_SOURCE_CONTRACT else "argovis"


def policy_versions(source_contract: str = SOURCE_CONTRACT) -> dict[str, str]:
    if source_contract == GDAC_SOURCE_CONTRACT:
        return {
            "geometry": GEOMETRY_VERSION,
            "mapping": GDAC_SOURCE_CONTRACT,
            "hash": HASH_VERSION,
            "specification": "gdac-netcdf",
            "qc": "core-good-v1",
            "source_contract": GDAC_SOURCE_CONTRACT,
        }
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
