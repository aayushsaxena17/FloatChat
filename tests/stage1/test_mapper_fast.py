"""The fast mapper and level_table against the stage1-v3 mapper and the byte-identity goldens.

`reference_map_profile` is a verbatim copy of `map_profile` at 90e1e67 (the per-level
mapper the goldens were recorded with). Every synthetic document is mapped by both and
must give an identical Profile or an identical rejection. The goldens pin the same
behaviour across commits; the oracle covers inputs the recorded bundles do not.
"""

import dataclasses
import json
import random
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from floatchat_core.ingestion import parquet
from floatchat_core.ingestion.argovis import (
    GDAC_SOURCE_CONTRACT,
    HASH_VERSION,
    LEGACY_SOURCE_CONTRACT,
    MAPPING_VERSION,
    PROFILE_FIELDS,
    REQUIRED_FIELDS,
    SOURCE_CONTRACT,
    TRANSLATOR_REVISION,
    TRANSLATOR_SHA256,
    UNITS,
    VARIABLES,
    Profile,
    _data_columns,
    bounded_text,
    integer,
    level_table,
    map_profile,
    policy_versions,
    qc,
    source_revision,
)
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import (
    CanonicalBudget,
    Rejection,
    decode_json,
    scientific_number,
)
from floatchat_core.ingestion.planning import in_region, timestamp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from stage1_goldens import mutations, profile_record  # noqa: E402
from stage1_perf_profile import BASES, synthetic_chunk  # noqa: E402

GOLDENS = json.loads((ROOT / "tests/fixtures/golden/stage1_v3_goldens.json").read_text())
RECORDED = ROOT / "tests/fixtures/argovis/recorded"
PER_PROFILE = {"profile_id", "source_profile_id", "profile_hash", "profile_content"}
CONTRACTS = (SOURCE_CONTRACT, LEGACY_SOURCE_CONTRACT)


def reference_map_profile(
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


# --- synthetic documents -----------------------------------------------------------------------

POINTER = "1901094_m0"
METADATA = {POINTER: {"_id": POINTER, "data_type": "oceanicProfile", "platform": "1901094"}}


def make_document(columns, attributes=None, **fields):
    """An Argovis document; attributes maps column name to (units, data_keys_mode)."""
    attributes = attributes or {}
    names = list(columns)
    document = {
        "_id": "1901094_109",
        "basin": Decimal(1),
        "cycle_number": Decimal(109),
        "data_info": [
            names,
            ["units", "data_keys_mode"],
            [list(attributes.get(name, (None, None))) for name in names],
        ],
        "data": [list(columns[name]) for name in names],
        "date_updated_argovis": "2025-01-31T07:45:11.114Z",
        "geolocation": {"coordinates": [Decimal("75.5"), Decimal("15.5")], "type": "Point"},
        "geolocation_argoqc": Decimal(1),
        "metadata": [POINTER],
        "profile_direction": "A",
        "source": [
            {
                "date_updated": "2025-01-30T15:11:24.000Z",
                "source": ["argo_core"],
                "url": "ftp://ftp.ifremer.fr/ifremer/argo/dac/coriolis/1901094/profiles/D1.nc",
            }
        ],
        "timestamp": "2011-05-31T04:48:00.000Z",
        "timestamp_argoqc": Decimal(1),
        "vertical_sampling_scheme": "Primary sampling: averaged",
    }
    document.update(fields)
    return document


def decimals(*texts):
    return [None if text is None else Decimal(text) for text in texts]


def core(pressure, temperature, salinity, qcs=("1", "1", "1"), modes="RRR"):
    """Three core variables with QC columns; a None column is left out entirely."""
    columns, attributes = {}, {}
    units = ("decibar", "degree_Celsius", "psu")
    for variable, values, qc_value, mode, unit in zip(
        VARIABLES, (pressure, temperature, salinity), qcs, modes, units, strict=True
    ):
        if values is None:
            continue
        columns[variable] = values
        columns[variable + "_argoqc"] = [Decimal(qc_value) for _ in values]
        attributes[variable] = (unit, mode)
    return make_document(columns, attributes)


def outcome(function, document, contract):
    budget = CanonicalBudget()
    try:
        profile = function(document, METADATA, budget, source_contract=contract)
    except Exception as error:  # the comparison covers every exception type
        return "raised", type(error), getattr(error, "category", None), error.args
    return "mapped", profile, repr(profile.levels), budget.run_used, budget.chunk_used


def assert_same_as_oracle(document, contract=SOURCE_CONTRACT):
    expected = outcome(reference_map_profile, document, contract)
    actual = outcome(map_profile, document, contract)
    assert actual == expected
    return actual


def levels_of(document, contract=SOURCE_CONTRACT):
    profile = map_profile(document, METADATA, CanonicalBudget(), source_contract=contract)
    assert profile == reference_map_profile(
        document, METADATA, CanonicalBudget(), source_contract=contract
    )
    return profile.levels


def test_levels_keep_key_order_values_and_types():
    document = core(
        decimals("5.0", "5", "4.5", "12000.5"),
        decimals("27.200001", None, "-5.1", "0"),
        decimals("34.9990001", "99999", "50.1", "-0"),
        qcs=("1", "2", "4"),
        modes="RAD",
    )
    levels = levels_of(document)
    assert [list(level) for level in levels] == [list(levels[0])] * 4
    assert list(levels[0])[:3] == ["level_index", "pressure", "pressure_adjusted"]
    assert len(levels[0]) == 1 + 3 * 12
    first, second, third, fourth = levels
    assert first["pressure"] == 5.0 and type(first["pressure"]) is float
    assert first["pressure_flags"] == [] and second["pressure_flags"] == ["repeated_pressure"]
    assert third["pressure_flags"] == ["nonmonotonic_pressure"]
    assert fourth["pressure_flags"] == ["outside_plausibility_range"]
    assert first["pressure_unit"] == "dbar" and first["pressure_unit_source"] == "decibar"
    assert first["pressure_data_mode"] == "R" and first["pressure_qc"] == "1"
    assert first["pressure_adjusted"] is None and first["pressure_adjusted_qc"] is None
    # Adjusted mode moves value, QC and QC source to the adjusted slots.
    assert first["temperature_adjusted"] == 27.200001 and first["temperature"] is None
    assert first["temperature_adjusted_qc"] == "2" and first["temperature_qc"] is None
    assert first["temperature_adjusted_qc_source"] == "2"
    assert first["temperature_flags"] == ["rounded"]
    assert second["temperature_adjusted"] is None and second["temperature_flags"] == []
    assert third["temperature_flags"] == ["rounded", "outside_plausibility_range"]
    assert fourth["temperature_adjusted"] == 0.0
    assert fourth["salinity"] is None  # mode D selects the adjusted slot
    assert second["salinity_adjusted"] is None and second["salinity_flags"] == []
    assert third["salinity_flags"] == ["rounded", "outside_plausibility_range"]
    assert fourth["salinity_adjusted"] == 0.0
    assert [level["level_index"] for level in levels] == [0, 1, 2, 3]


def test_absent_variable_nonfinite_fill_and_unknown_qc():
    columns = {
        "pressure": decimals("1", "2", "3"),
        "pressure_argoqc": [Decimal(1), "X", None],
        "salinity": ["NaN", "-Infinity", Decimal("99999")],
        "salinity_argoqc": ["", "7", Decimal("10")],
    }
    attributes = {"pressure": ("dbar", "R"), "salinity": ("1", "A")}
    levels = levels_of(make_document(columns, attributes))
    for level in levels:
        assert level["temperature_flags"] == ["variable_absent"]
        assert level["temperature_unit"] is None and level["temperature_data_mode"] is None
    assert [level["pressure_qc"] for level in levels] == ["1", None, None]
    assert [level["pressure_qc_source"] for level in levels] == ["1", "X", None]
    assert levels[1]["pressure_flags"] == ["unknown_qc"]
    assert levels[2]["pressure_flags"] == []
    assert [level["salinity_adjusted_qc"] for level in levels] == [None, "7", None]
    assert [level["salinity_adjusted_qc_source"] for level in levels] == ["", "7", "10"]
    assert [level["salinity_flags"] for level in levels] == [[], [], ["unknown_qc"]]
    assert_same_as_oracle(make_document(columns, attributes))


def test_repeated_values_share_no_mutable_state():
    levels = levels_of(core(decimals("1", "1", "1"), decimals("5", "5", "5"), None))
    assert levels[0]["pressure_flags"] is not levels[1]["pressure_flags"]
    levels[0]["temperature_flags"].append("poison")
    assert levels[1]["temperature_flags"] == []
    assert levels[0] is not levels[1]


def test_equal_decimals_with_different_text_and_qc_representations():
    # Value-equal pressure tokens hit one memo entry; their canonical text is the same.
    document = core(decimals("5.0", "5", "5.00", "1E+1"), None, None)
    profile = map_profile(document, METADATA, CanonicalBudget())
    exact = json.loads(profile.canonical_bytes)["levels"]
    assert [level["pressure"]["exact"] for level in exact] == ["5", "5", "5", "10"]
    assert [level["pressure_flags"] for level in profile.levels] == [
        [],
        ["repeated_pressure"],
        ["repeated_pressure"],
        [],
    ]
    # QC text of a non-integral Decimal keeps its own representation (1.5 vs 1.50).
    columns = {
        "pressure": decimals("1", "2", "3", "4", "5", "6"),
        "pressure_argoqc": decimals("1.5", "1.50", "1.5", "1.0", "1", "1E+1"),
    }
    levels = levels_of(make_document(columns, {"pressure": ("dbar", "R")}))
    assert [level["pressure_qc_source"] for level in levels] == [
        "1.5",
        "1.50",
        "1.5",
        "1",
        "1",
        "10",
    ]
    assert_same_as_oracle(make_document(columns, {"pressure": ("dbar", "R")}))


@pytest.mark.parametrize("bad", [True, 1, 1.5, "abc", "nan", Decimal("NaN"), Decimal("sNaN")])
def test_memo_never_lets_other_types_inherit_a_decimal_result(bad):
    document = core([Decimal(1), Decimal(2)], [Decimal(1), bad], [Decimal(1), Decimal(1)])
    expected = assert_same_as_oracle(document)
    assert expected[0] == "raised" and expected[2] in (
        "invalid_scientific_number",
        "invalid_scientific_numeric_string",
        "invalid_json_number",
    )
    columns = {"pressure": [Decimal(1)] * 2, "pressure_argoqc": [Decimal(1), bad]}
    result = assert_same_as_oracle(make_document(columns, {"pressure": ("dbar", "R")}))
    # Strings and a quiet NaN are valid (unknown) QC text; the rest has no QC shape.
    text_like = isinstance(bad, str) or (isinstance(bad, Decimal) and not bad.is_snan())
    assert result[0] == ("mapped" if text_like else "raised")


PRECEDENCE = [
    # The first failing check wins, scanning level by level and, within a level, pressure,
    # then temperature, then salinity; metadata checks fire on the first level.
    ("bad_mode_before_later_bad_pressure", "unknown_data_mode"),
    ("bad_pressure_token_first", "invalid_scientific_numeric_string"),
    ("pressure_qc_before_salinity_unit", "invalid_qc_shape"),
    ("temperature_token_before_later_pressure_unit", "invalid_scientific_number"),
    ("pressure_unit_before_same_level_temperature_token", "unknown_unit"),
    ("metadata_type_before_later_qc_without_variable", "invalid_variable_metadata"),
    ("qc_without_variable_before_later_metadata_type", "qc_without_variable"),
    ("unit_only_matters_for_values", None),
]


def add_column(document, name, values, attributes=(None, None)):
    document["data_info"][0].append(name)
    document["data_info"][2].append(list(attributes))
    document["data"].append(values)


def column_of(document, name):
    return document["data"][document["data_info"][0].index(name)]


def attributes_of(document, name):
    return document["data_info"][2][document["data_info"][0].index(name)]


def precedence_document(name):
    one, two = Decimal(1), Decimal(2)
    if name == "bad_mode_before_later_bad_pressure":
        document = core([one, "garbage"], [one, two], [one, two], modes="RXR")
    elif name == "bad_pressure_token_first":
        document = core(["garbage", one], [one, two], [one, two], modes="RXR")
    elif name == "pressure_qc_before_salinity_unit":
        document = core([one, two], [one, two], [one, two])
        column_of(document, "pressure_argoqc")[0] = 1
        attributes_of(document, "salinity")[0] = "bogus"
    elif name == "temperature_token_before_later_pressure_unit":
        document = core([None, two], [True, two], [one, two])
        attributes_of(document, "pressure")[0] = "furlong"
    elif name == "pressure_unit_before_same_level_temperature_token":
        document = core([one, two], [one, True], [one, two])
        attributes_of(document, "pressure")[0] = "furlong"
        column_of(document, "pressure")[0] = None
    elif name == "metadata_type_before_later_qc_without_variable":
        document = core([one], None, [one])
        add_column(document, "temperature_argoqc", [one])
        attributes_of(document, "pressure")[1] = 7  # mode is not text
    elif name == "qc_without_variable_before_later_metadata_type":
        document = core([one], None, [one])
        add_column(document, "temperature_argoqc", [one])
        attributes_of(document, "salinity")[1] = 7
    else:
        document = core([None, None], [None, "NaN"], [None, None])
        attributes_of(document, "pressure")[0] = "furlong"
    return document


@pytest.mark.parametrize(("name", "category"), PRECEDENCE)
def test_rejection_precedence(name, category):
    result = assert_same_as_oracle(precedence_document(name))
    assert (result[2] if result[0] == "raised" else None) == category


def test_source_revision_error_comes_after_canonical_encoding():
    document = core(decimals("1", "2"), decimals("3", "4"), None, modes="RRR")
    document["source"] = [{"source": "not-a-list", "url": "ftp://x/y"}]
    assert outcome(map_profile, document, SOURCE_CONTRACT)[2] == "invalid_source"
    budget = CanonicalBudget(profile_limit=200)
    with pytest.raises(Rejection) as caught:
        map_profile(document, METADATA, budget)
    assert caught.value.category == "canonical_output_limit"
    expected = CanonicalBudget(profile_limit=200)
    with pytest.raises(Rejection):
        reference_map_profile(document, METADATA, expected)
    assert (budget.run_used, budget.chunk_used) == (expected.run_used, expected.chunk_used)


# --- randomized comparison with the oracle -----------------------------------------------------

VALUES = [
    *("-5.1", "-5", "0", "0.0", "-0", "1E+2", "5", "5.0", "5.00", "12.5", "50", "50.1"),
    *("12000", "12000.1", "34.9990001", "27.200001", "1.5", "99998.9", "3E-3", "1E-310"),
    *("1.7976931348623157E+308", "123456789012345678901234567890.123456789"),
]
FILLS = ["99999", "99999.0", "9.9999E+4"]
NONFINITE = ["NaN", "Infinity", "+Infinity", "-Infinity"]
BAD_VALUES = [
    *("abc", "nan", "", True, 1, 1.5, Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")),
    *(Decimal("1E+400"), Decimal("1E-400"), Decimal("1E+2000"), Decimal("-1E-400")),
]
QC_VALUES = [
    *(Decimal(digit) for digit in "0123456789"),
    *(Decimal(text) for text in ("1.0", "1.5", "1.50", "10", "-1", "1E+1", "0.0", "-0")),
    *("1", "X", "", "12", "1.5", None),
]
BAD_QC = [1, 1.0, True, Decimal("Infinity"), Decimal("sNaN"), Decimal("NaN"), ["1"]]
BAD_META = [5, ["x"], 1.5]


def random_token(rng):
    roll = rng.random()
    if roll < 0.72:
        return Decimal(rng.choice(VALUES))
    if roll < 0.82:
        return None
    if roll < 0.88:
        return rng.choice(NONFINITE)
    if roll < 0.97:
        return Decimal(rng.choice(FILLS))
    return rng.choice(BAD_VALUES)


def random_qc(rng):
    return rng.choice(BAD_QC) if rng.random() < 0.02 else rng.choice(QC_VALUES)


def random_document(rng):
    count = rng.randint(1, 9)
    columns, attributes = {}, {}
    units = {
        "pressure": ["dbar", "decibar"],
        "temperature": ["degree_C", "degrees C", "degree_Celsius"],
        "salinity": ["psu", "PSU", "PSS-78", "1"],
    }
    for variable in VARIABLES:
        present = rng.random() < 0.85
        if present:
            values = [random_token(rng) for _ in range(count)]
            if variable == "pressure" and rng.random() < 0.5:
                values = [Decimal(rng.choice(VALUES[:14])) for _ in range(count)]
            columns[variable] = values
        if present or rng.random() < 0.08:
            unit = (
                rng.choice(units[variable])
                if rng.random() < 0.95
                else rng.choice(["furlong", None, *BAD_META])
            )
            mode = (
                rng.choices(["R", "A", "D"], [3, 3, 3])[0]
                if rng.random() < 0.94
                else rng.choice(["X", None, *BAD_META])
            )
            attributes[variable] = (unit, mode)
        if (present and rng.random() < 0.9) or (not present and rng.random() < 0.06):
            columns[variable + "_argoqc"] = [random_qc(rng) for _ in range(count)]
    if rng.random() < 0.3:
        columns["doxy"] = [random_token(rng) for _ in range(count)]
        columns["doxy_argoqc"] = [random_qc(rng) for _ in range(count)]
        attributes["doxy"] = ("micromole/kg", "A")
    if rng.random() < 0.1:
        columns["chla_fluorescence"] = [Decimal(1) if rng.random() < 0.7 else None] * count
        attributes["chla_fluorescence"] = ("ru", "A")
    if rng.random() < 0.03:
        columns["bogus"] = [Decimal(1)] * count
    names = list(columns)
    rng.shuffle(names)
    shuffled = {name: columns[name] for name in names}
    return make_document(shuffled, attributes)


def test_randomized_documents_match_the_oracle():
    rng = random.Random(20251008)
    mapped = 0
    categories = set()
    for _ in range(1500):
        document = random_document(rng)
        for contract in CONTRACTS:
            result = assert_same_as_oracle(document, contract)
            if result[0] == "mapped":
                mapped += 1
            else:
                categories.add(result[2] or result[1].__name__)
    assert mapped > 500
    assert {
        "unknown_unit",
        "unknown_data_mode",
        "invalid_variable_metadata",
        "qc_without_variable",
        "invalid_qc_shape",
        "invalid_scientific_number",
        "invalid_scientific_numeric_string",
        "invalid_json_number",
        "float64_overflow",
        "float64_underflow",
        "unknown_data_field",
    } <= categories


# --- goldens: recorded bundles, mutations and synthetic clones ---------------------------------


def metadata_of(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text())
    metadata = {}
    for response in manifest["responses"]:
        if response["role"] == "metadata":
            for item in decode_json((bundle / response["path"]).read_bytes()):
                metadata[item["_id"]] = item
    return manifest, metadata


@pytest.mark.parametrize("name", sorted(GOLDENS["bundles"]))
def test_goldens_for_recorded_bundles_and_mutations(name):
    bundle = RECORDED / name
    manifest, metadata = metadata_of(bundle)
    expected = GOLDENS["bundles"][name]
    seen = 0
    for response in manifest["responses"]:
        if response["role"] != "profile":
            continue
        for document in documents((bundle / response["path"]).read_bytes()):
            profile = map_profile(document, metadata, CanonicalBudget())
            assert profile_record(profile) == expected["profiles"][document["_id"]]
            reference = reference_map_profile(document, metadata, CanonicalBudget())
            assert profile == reference and repr(profile.levels) == repr(reference.levels)
            for label, mutated in mutations(document).items():
                key = document["_id"] + ":" + label
                try:
                    actual = profile_record(map_profile(mutated, metadata, CanonicalBudget()))
                except Rejection as error:
                    actual = {"rejection": error.category}
                assert actual == expected["mutations"][key], key
                seen += 1
    assert seen == len(expected["mutations"])


@pytest.mark.parametrize("label", sorted(BASES))
def test_synthetic_clone_matches_the_oracle_and_levels_are_independent(label):
    payload, _, metadata = synthetic_chunk(2, 699, basis=BASES[label])
    meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    for document in documents(payload):
        profile = map_profile(document, meta, CanonicalBudget())
        reference = reference_map_profile(document, meta, CanonicalBudget())
        assert profile == reference and repr(profile.levels) == repr(reference.levels)


# --- level_table -------------------------------------------------------------------------------


def expected_rows(profile):
    return [
        {key: value for key, value in row.items() if key not in PER_PROFILE}
        for row in parquet.rows(uuid.UUID(int=1), profile)
    ]


def assert_level_table(profile):
    table = level_table(profile)
    schema = [
        (field.name, field.type, field.nullable)
        for field in parquet.schema()
        if field.name not in PER_PROFILE
    ]
    assert [(field.name, field.type, field.nullable) for field in table.schema] == schema
    assert table.column_names[:2] == ["canonical_level", "level_index"] and len(schema) == 38
    rows = expected_rows(profile)
    assert table.to_pylist() == rows
    full = pa.Table.from_pylist(
        list(parquet.rows(uuid.UUID(int=1), profile)), schema=parquet.schema()
    )
    for name in table.column_names:
        assert table[name].equals(full[name]), name
    table.validate(full=True)
    return table


@pytest.mark.parametrize("name", sorted(GOLDENS["bundles"]))
def test_level_table_round_trips_recorded_profiles_and_mutations(name):
    bundle = RECORDED / name
    manifest, metadata = metadata_of(bundle)
    for response in manifest["responses"]:
        if response["role"] != "profile":
            continue
        for document in documents((bundle / response["path"]).read_bytes()):
            assert_level_table(map_profile(document, metadata, CanonicalBudget()))
            for mutated in mutations(document).values():
                try:
                    profile = map_profile(mutated, metadata, CanonicalBudget())
                except Rejection:
                    continue
                assert_level_table(profile)


def test_level_table_of_a_699_level_clone_and_concatenation():
    payload, _, metadata = synthetic_chunk(2, 699)
    meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    profiles = [map_profile(d, meta, CanonicalBudget()) for d in documents(payload)]
    tables = [assert_level_table(profile) for profile in profiles]
    assert pa.concat_tables(tables).num_rows == 2 * 699


def test_level_table_randomized_documents_and_hostile_strings():
    rng = random.Random(7)
    checked = 0
    for _ in range(300):
        try:
            profile = map_profile(random_document(rng), METADATA, CanonicalBudget())
        except Exception:  # rejected documents have no profile to tabulate
            continue
        assert_level_table(profile)
        checked += 1
    assert checked > 50
    hostile = ['},{"level_index":2,', '"],"longitude":{', "\\", '\\"', "é\U0001f600", "}"]
    # QC text and the unit of a null-only column are free text in the canonical level.
    columns = {
        "pressure": decimals("1", "2", "3"),
        "pressure_argoqc": [hostile[0], hostile[1], hostile[2]],
        "temperature": [None, "NaN", None],
        "temperature_argoqc": [hostile[3], hostile[4], hostile[5]],
    }
    attributes = {"pressure": ("dbar", "R"), "temperature": ('x},{"level_index":1,', "A")}
    profile = map_profile(make_document(columns, attributes), METADATA, CanonicalBudget())
    assert profile.levels[0]["temperature_unit_source"] == 'x},{"level_index":1,'
    assert_level_table(profile)


def test_level_table_cuts_levels_from_the_canonical_bytes_without_parsing(monkeypatch):
    columns = {
        "pressure": decimals("1", "2", "3"),
        "pressure_argoqc": ['},{"level_index":2,', '"],"longitude":{', "}"],
        "temperature": [None, "NaN", None],
    }
    attributes = {"pressure": ("dbar", "R"), "temperature": ('x},{"level_index":1,', "A")}
    profile = map_profile(make_document(columns, attributes), METADATA, CanonicalBudget())
    clone = synthetic_chunk(1, 50)
    meta = {m["_id"]: m for m in decode_json(json.dumps(clone[2]).encode())}
    profiles = [profile, map_profile(next(documents(clone[0])), meta, CanonicalBudget())]

    def refuse(*args, **kwargs):
        raise AssertionError("canonical bytes were re-parsed")

    monkeypatch.setattr(json, "loads", refuse)
    for item in profiles:
        assert level_table(item).num_rows == len(item.levels)
    monkeypatch.undo()
    for item in profiles:
        expected = [row["canonical_level"] for row in expected_rows(item)]
        assert level_table(item)["canonical_level"].to_pylist() == expected


def test_level_table_reparses_when_the_canonical_bytes_are_not_compact():
    document = core(decimals("1", "2"), decimals("3", "4"), decimals("35", "36"))
    profile = map_profile(document, METADATA, CanonicalBudget())
    spaced = dataclasses.replace(
        profile, canonical_bytes=json.dumps(json.loads(profile.canonical_bytes)).encode()
    )
    assert spaced.canonical_bytes != profile.canonical_bytes
    assert level_table(spaced).equals(level_table(profile))
    assert_level_table(spaced)


# --- gdac-core-v1 ------------------------------------------------------------------------------


def test_gdac_contract_header_and_levels():
    document = core(decimals("1", "2"), decimals("3", "4"), decimals("35", "36"))
    argovis = map_profile(document, METADATA, CanonicalBudget())
    gdac = map_profile(document, METADATA, CanonicalBudget(), source_contract=GDAC_SOURCE_CONTRACT)
    header = json.loads(gdac.canonical_bytes)
    assert (header["source"], header["mapping_version"]) == ("gdac", "gdac-core-v1")
    assert header["hash_version"] == HASH_VERSION == "scientific-json-v2"
    reference = json.loads(argovis.canonical_bytes)
    assert (reference["source"], reference["mapping_version"]) == ("argovis", MAPPING_VERSION)
    for key in ("source", "mapping_version"):
        header.pop(key), reference.pop(key)
    assert header == reference
    assert gdac.levels == argovis.levels and gdac.content_hash != argovis.content_hash
    assert_level_table(gdac)


def test_gdac_contract_has_no_additional_noncore_columns():
    columns = {
        "pressure": decimals("1"),
        "pressure_argoqc": decimals("1"),
        "chla_fluorescence": decimals("5"),
    }
    document = make_document(columns, {"pressure": ("dbar", "R"), "chla_fluorescence": ("ru", "A")})
    assert map_profile(document, METADATA, CanonicalBudget()).outside_core_arrays == 1
    for contract in (LEGACY_SOURCE_CONTRACT, GDAC_SOURCE_CONTRACT):
        with pytest.raises(Rejection) as caught:
            map_profile(document, METADATA, CanonicalBudget(), source_contract=contract)
        assert caught.value.category == "unknown_data_field"


def test_gdac_contract_validates_metadata_like_argovis():
    document = core(decimals("1"), None, None)
    wrong = {POINTER: {**METADATA[POINTER], "data_type": "other"}}
    for contract in (SOURCE_CONTRACT, GDAC_SOURCE_CONTRACT):
        with pytest.raises(Rejection) as caught:
            map_profile(document, wrong, CanonicalBudget(), source_contract=contract)
        assert caught.value.category == "invalid_metadata"
    with pytest.raises(Rejection) as caught:
        map_profile(document, METADATA, CanonicalBudget(), source_contract="other-v1")
    assert caught.value.category == "unsupported_source_contract"


def test_policy_versions():
    base = {
        "geometry": policy_versions()["geometry"],
        "mapping": "argovis-core-v1",
        "hash": "scientific-json-v2",
        "specification": "2.36.2",
        "specification_sha256": "0d824a0722c9155b5fcf091f315429a634ed99a1310652271730954f901a3dc9",
        "qc": "core-good-v1",
    }
    assert policy_versions(LEGACY_SOURCE_CONTRACT) == base
    assert (
        policy_versions()
        == policy_versions(SOURCE_CONTRACT)
        == {
            **base,
            "source_contract": SOURCE_CONTRACT,
            "translator_revision": TRANSLATOR_REVISION,
            "translator_sha256": TRANSLATOR_SHA256,
        }
    )
    gdac = policy_versions(GDAC_SOURCE_CONTRACT)
    assert gdac == {
        "geometry": base["geometry"],
        "mapping": "gdac-core-v1",
        "hash": "scientific-json-v2",
        "specification": "gdac-netcdf",
        "qc": "core-good-v1",
        "source_contract": "gdac-core-v1",
    }
    with pytest.raises(Rejection) as caught:
        policy_versions("other-v1")
    assert caught.value.category == "unsupported_source_contract"


def test_level_table_of_a_profile_without_levels_is_an_empty_table():
    profile = dataclasses.replace(
        map_profile(core(decimals("1"), None, None), METADATA, CanonicalBudget()),
        levels=(),
        canonical_bytes=b'{"levels":[],"longitude":{}}',
    )
    table = level_table(profile)
    assert table.num_rows == 0 and table.schema.names == [
        field.name for field in parquet.schema() if field.name not in PER_PROFILE
    ]
