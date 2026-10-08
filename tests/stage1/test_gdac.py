"""GDAC NetCDF source, offline: committed excerpts of real GDAC files, synthetic NetCDF edge cases.

The fixtures under tests/fixtures/gdac are verbatim downloads from data-argo.ifremer.fr
(scripts/gdac_fixtures.py); the index is a filtered excerpt. No test touches the network.
"""

import gzip
import hashlib
import http.client
import json
import socket
import ssl
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import netCDF4
import numpy as np
import pytest
from floatchat_core.ingestion import gdac
from floatchat_core.ingestion.argovis import (
    inventory_identities,
    map_profile,
    policy_versions,
    request_parameters,
    verify_inventory,
)
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.planning import Interval, PlannedChunk, Tile, plan
from floatchat_core.ingestion.repository import Authority
from floatchat_core.ingestion.transport import HTTPFailure

# netCDF4 1.7.4 trips a NumPy 2.5 reshape deprecation inside its own char-array writer.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array:DeprecationWarning"
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/gdac"
JAN = FIXTURES / "20250115_prof.nc"
FEB = FIXTURES / "20250214_prof.nc"
INDEX = FIXTURES / "ar_index_indian_2025q1.txt"
JAN_KEY = "geo/indian_ocean/2025/01/20250115_prof.nc"
FEB_KEY = "geo/indian_ocean/2025/02/20250214_prof.nc"
DAY = Interval(datetime(2025, 1, 15, tzinfo=UTC), datetime(2025, 1, 16, tzinfo=UTC))
TILE = Tile(70, -30)  # three profiles on 2025-01-15, five on 2025-02-14


# Recorded once from this implementation (gdac-core-v1); any change to the mapping, the exact
# text rule or the canonical form must change them deliberately (and needs a new ADR).
EXPECTED_HASHES = {
    "jan_d": (
        "gdac:1902253_166A",
        "2d0d9d8f2007be7f9df2f2dbc202b61ddaccf77f4a7566369e58d00421a86de9",
    ),
    "jan_r": (
        "gdac:7901004_78A",
        "677082860d396495a2cb849725be4f28a89d10ff9e1522e195b31ab2e8ab9656",
    ),
    "feb_first": (
        "gdac:2903466_60A",
        "4ce8d4d1c96daca1f7e09ee28b0de8cda6b9cfbaee034be0070e31495ed7e814",
    ),
}


# The excerpt holds only Indian Ocean ("I") rows: every profile in the box is in the basin files.
EXPECTED_INDEX_ROWS = 5961
EXPECTED_OCEANS = {"I": 5961}
EXPECTED_JANUARY = 2049


def at(day, hour=0):
    return datetime(2025, *day, hour, tzinfo=UTC)


# --- fixtures ---------------------------------------------------------------------------------


def test_fixture_manifest_matches_files_and_size_budget():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["host"] == gdac.GDAC_HOST
    assert manifest["attribution"] == gdac.ATTRIBUTION
    assert "doi.org/10.17882/42182" in manifest["attribution"]
    total = 0
    for entry in manifest["files"]:
        data = (FIXTURES / entry["path"]).read_bytes()
        total += len(data)
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]
        assert entry["url"].startswith(f"https://{gdac.GDAC_HOST}/")
    assert {e["path"] for e in manifest["files"]} == {JAN.name, FEB.name, INDEX.name}
    assert total < 12 * 1024 * 1024


# --- index ------------------------------------------------------------------------------------


def test_index_excerpt_is_bounded_and_parses_with_the_live_code_path():
    raw = INDEX.read_bytes()
    text = raw.decode("ascii")
    assert text.splitlines()[-1].count(",") == 7
    assert "file,date,latitude,longitude,ocean,profiler_type,institution,date_update" in text
    entries = list(gdac.scan_index(raw))
    rows = [x for x in text.splitlines() if x and not x.startswith(("#", "file,"))]
    assert len(entries) == len(rows) == EXPECTED_INDEX_ROWS
    assert all(-60 <= e.latitude <= 30 and 20 <= e.longitude <= 120 for e in entries)
    assert all(at((1, 1)) <= e.date < at((4, 1)) for e in entries)
    assert Counter(e.ocean for e in entries) == EXPECTED_OCEANS
    # The gzip form (as published) yields exactly the same entries.
    assert list(gdac.scan_index(gzip.compress(raw))) == entries


def test_index_entries_partition_the_month_across_tiles_without_overlap():
    raw = INDEX.read_bytes()
    january = Interval(at((1, 1)), at((2, 1)))
    everything = list(gdac.scan_index(raw, january))
    owned = Counter()
    for chunk in plan(january):
        for entry in gdac.index_entries(raw, january, chunk.tile):
            assert chunk.tile.owns(entry.longitude, entry.latitude)
            assert january.contains(entry.date)
            owned[entry.file + entry.date.isoformat()] += 1
    assert len(everything) == EXPECTED_JANUARY and sum(owned.values()) == len(everything)
    assert set(owned.values()) == {1}


def test_index_entries_respect_half_open_interval_and_tile_edges():
    lines = (
        b"file,date,latitude,longitude,ocean,profiler_type,institution,date_update\n"
        b"aoml/1/profiles/R1_001.nc,20250201000000,10.0,120,I,846,AO,20250202000000\n"
        b"aoml/2/profiles/R2_001.nc,20250131235959,30,110,I,846,AO,20250202000000\n"
        b"aoml/3/profiles/D3_002D.nc,20250115120000,-0.001,70.000,I,846,AO,\n"
        b"aoml/4/profiles/R4_001.nc,,,,I,846,AO,\n"
    )
    january = Interval(at((1, 1)), at((2, 1)))
    # 2025-02-01T00:00:00 belongs to February; the blank row has no place or time.
    got = gdac.index_entries(lines, january, Tile(110, 20))
    assert [e.file.rsplit("/", 1)[1] for e in got] == ["R2_001.nc"]  # lat == 30 is owned
    got = gdac.index_entries(lines, Interval(at((2, 1)), at((3, 1))), Tile(110, 10))
    assert [e.identity for e in got] == ["gdac:1_1A"]  # lon == 120 is owned by the last tile
    got = gdac.index_entries(lines, january, Tile(70, -10))
    assert [e.identity for e in got] == ["gdac:3_2D"] and got[0].date_update is None


@pytest.mark.parametrize(
    "line",
    [
        b"a,b,c\n",
        b"f,2025011512000,1,70,I,1,A,\n",
        b"f,20251315120000,1,70,I,1,A,\n",
        b"f,20250115120000,north,70,I,1,A,\n",
        b"f,20250115120000,1,70,I,1,A,notadate\n",
        b"f\xff,20250115120000,1,70,I,1,A,\n",
        b"f," + b"1" * 5000 + b",1,70,I,1,A,\n",
    ],
)
def test_index_rejects_malformed_rows(line):
    with pytest.raises(Rejection, match="invalid_index_line"):
        list(gdac.scan_index(line))


def test_index_size_and_gzip_bounds(monkeypatch):
    monkeypatch.setattr(gdac, "INDEX_MAX_BYTES", 100)
    with pytest.raises(Rejection, match="decompressed_size_limit"):
        list(gdac.scan_index(gzip.compress(b"#" + b"x" * 200 + b"\n")))
    monkeypatch.undo()
    with pytest.raises(Rejection, match="invalid_gzip"):
        list(gdac.scan_index(b"\x1f\x8b" + b"broken"))


def test_index_identity_parsing():
    def identity(name):
        return gdac.IndexEntry(
            name, at((1, 1)), Decimal(0), Decimal(30), "I", "1", "X", None
        ).identity

    assert identity("coriolis/6901000/profiles/R6901000_010.nc") == "gdac:6901000_10A"
    assert identity("aoml/13857/profiles/D13857_001D.nc") == "gdac:13857_1D"
    assert identity("meds/4900800/profiles/R4900800_1000.nc") == "gdac:4900800_1000A"
    assert identity("not-a-profile.txt") is None


def test_daily_file_keys_cover_the_days_a_chunk_intersects():
    month = Interval(at((2, 1)), at((3, 1)))
    keys = gdac.daily_file_keys(month)
    assert len(keys) == 28 and keys[0] == "geo/indian_ocean/2025/02/20250201_prof.nc"
    assert keys[-1] == "geo/indian_ocean/2025/02/20250228_prof.nc"
    # A split half-day chunk still needs its day; an end at midnight excludes the next day.
    assert gdac.daily_file_keys(Interval(at((1, 15), 6), at((1, 15), 18))) == [JAN_KEY]
    assert gdac.daily_file_keys(DAY) == [JAN_KEY]
    two = gdac.daily_file_keys(Interval(at((1, 31), 12), at((2, 1), 12)))
    assert two == [
        "geo/indian_ocean/2025/01/20250131_prof.nc",
        "geo/indian_ocean/2025/02/20250201_prof.nc",
    ]


# --- NetCDF conversion --------------------------------------------------------------------------


def jan_documents(**options):
    return list(gdac.profiles_from_netcdf(JAN, name=JAN_KEY, **options))


def test_conversion_of_a_known_profile():
    docs = jan_documents()
    assert (
        len(docs) == 97 and len({(d["platform"], d["cycle"], d["direction"]) for d in docs}) == 97
    )
    first = docs[0]
    assert (first["platform"], first["cycle"], first["direction"]) == ("1902253", 166, "A")
    assert first["observed_at"] == "2025-01-15T23:57:23.000000+00:00"
    assert (first["longitude"], first["latitude"]) == ("77.10333", "-23.17605")
    assert (first["data_mode"], first["position_qc"], first["juld_qc"]) == ("D", "1", "1")
    assert (first["data_centre"], first["file"], first["n_levels"]) == ("AO", JAN_KEY, 1011)
    # DATE_UPDATE is the file's own regeneration stamp, one value for every profile.
    assert {d["date_update"] for d in docs} == {"2026-10-07T02:02:08+00:00"}
    assert first["PRES"][:3] == ["0.96", "2", "3.04"] and first["TEMP"][:2] == ["26.02", "26.021"]
    assert first["PSAL_ADJUSTED_ERROR"][0] == "0.01" and first["PRES_ADJUSTED_QC"][0] == "1"
    assert first["units"]["PRES"] == "decibar" and first["units"]["PSAL"] == "psu"
    assert Counter(d["data_mode"] for d in docs) == {"D": 63, "A": 20, "R": 14}
    assert Counter(d["direction"] for d in docs) == {"A": 95, "D": 2}


def test_trimmed_levels_match_the_stored_arrays():
    dataset = netCDF4.Dataset(str(JAN))
    dataset.set_auto_maskandscale(False)
    docs = jan_documents()
    value_names = [f"{p}{s}" for p in ("PRES", "TEMP", "PSAL") for s in ("", "_ADJUSTED")]
    for index, doc in enumerate(docs):
        valid = np.zeros(dataset.dimensions["N_LEVELS"].size, dtype=bool)
        for name in value_names:
            valid |= dataset.variables[name][index, :] != np.float32(99999)
        assert doc["n_levels"] == int(np.flatnonzero(valid)[-1]) + 1
        for name in value_names + ["PRES_QC", "TEMP_ADJUSTED_ERROR"]:
            assert len(doc[name]) == doc["n_levels"]
    dataset.close()


def test_tile_and_interval_filters_use_ownership_and_the_half_open_interval():
    docs = jan_documents(tile=TILE, interval=DAY)
    assert len(docs) == 3
    owned = [
        d for d in jan_documents() if TILE.owns(Decimal(d["longitude"]), Decimal(d["latitude"]))
    ]
    assert docs == owned
    # The interval end is exclusive: 23:57:23 is excluded by an end at 23:57:23 exactly.
    cut = Interval(at((1, 15)), datetime(2025, 1, 15, 23, 57, 23, tzinfo=UTC))
    assert len(jan_documents(interval=cut)) == 96
    assert jan_documents(interval=Interval(at((1, 16)), at((1, 17)))) == []
    box = [
        d
        for d in jan_documents()
        if -60 <= Decimal(d["latitude"]) <= 30 and 20 <= Decimal(d["longitude"]) <= 120
    ]
    assert len(box) == 79


def test_feb_file_converts_and_carries_plausibility_outliers():
    docs = list(gdac.profiles_from_netcdf(FEB, name=FEB_KEY))
    assert len(docs) == 77
    assert max(Decimal(x) for d in docs for x in d["PSAL"] if x != "99999") > 50
    assert {d["date_update"] for d in docs} == {"2026-09-23T16:23:02+00:00"}


def synthetic(tmp_path, rows, *, levels=6, update="20260101000000", name="synthetic.nc"):
    """A GDAC-shaped file: rows are dicts, see PROFILES below."""
    path = tmp_path / name
    n = len(rows)
    with netCDF4.Dataset(str(path), "w") as ds:
        ds.createDimension("N_PROF", n)
        ds.createDimension("N_LEVELS", levels)
        for dim, size in (("DATE_TIME", 14), ("STRING8", 8), ("STRING2", 2), ("STRING256", 256)):
            ds.createDimension(dim, size)

        def text(variable, dims, values, width):
            padded = b"".join(v.ljust(width).encode() for v in values)
            ds.createVariable(variable, "S1", dims)[:] = np.frombuffer(padded, dtype="S1").reshape(
                len(values), width
            )

        def chars(variable, values):
            ds.createVariable(variable, "S1", ("N_PROF",))[:] = np.array(
                [v.encode() for v in values], dtype="S1"
            )

        ds.createVariable("DATE_UPDATE", "S1", ("DATE_TIME",))[:] = np.frombuffer(
            update.encode().ljust(14), dtype="S1"
        )
        text("PLATFORM_NUMBER", ("N_PROF", "STRING8"), [r["platform"] for r in rows], 8)
        text("DATA_CENTRE", ("N_PROF", "STRING2"), [r.get("centre", "IF") for r in rows], 2)
        text(
            "VERTICAL_SAMPLING_SCHEME",
            ("N_PROF", "STRING256"),
            [r.get("scheme", "") for r in rows],
            256,
        )
        chars("DIRECTION", [r["direction"] for r in rows])
        chars("DATA_MODE", [r["mode"] for r in rows])
        chars("JULD_QC", [r.get("juld_qc", "1") for r in rows])
        chars("POSITION_QC", [r.get("position_qc", "1") for r in rows])
        ds.createVariable("CYCLE_NUMBER", "i4", ("N_PROF",), fill_value=99999)[:] = [
            r["cycle"] for r in rows
        ]
        for variable, key in (("JULD", "juld"), ("LATITUDE", "lat"), ("LONGITUDE", "lon")):
            fill = 999999.0 if variable == "JULD" else 99999.0
            var = ds.createVariable(variable, "f8", ("N_PROF",), fill_value=fill)
            var[:] = [r[key] for r in rows]
        for short, unit in (("PRES", "decibar"), ("TEMP", "degree_Celsius"), ("PSAL", "psu")):
            for suffix in ("", "_ADJUSTED", "_ADJUSTED_ERROR"):
                var = ds.createVariable(
                    short + suffix, "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999)
                )
                var.units = unit
                var[:] = np.array(
                    [r.get(short + suffix, [99999.0] * levels) for r in rows], dtype=np.float32
                )
            for suffix in ("_QC", "_ADJUSTED_QC"):
                var = ds.createVariable(short + suffix, "S1", ("N_PROF", "N_LEVELS"))
                var[:] = np.array(
                    [list(r.get(short + suffix, " " * levels)) for r in rows], dtype="S1"
                )
    return path


FILL = 99999.0
NAN = float("nan")
JULD_NOON = (datetime(2025, 1, 15, 12, tzinfo=UTC) - datetime(1950, 1, 1, tzinfo=UTC)).days + 0.5


def profile(platform="5900001", cycle=7, direction="A", mode="D", **values):
    row = {
        "platform": platform,
        "cycle": cycle,
        "direction": direction,
        "mode": mode,
        "juld": JULD_NOON,
        "lat": 10.5,
        "lon": 60.25,
    }
    row.update(values)
    return row


EDGE_ROWS = [
    # D mode: interior all-fill row (index 2), NaN salinity, two trailing fill rows.
    profile(
        PRES_ADJUSTED=[5.0, 10.0, FILL, 20.0, FILL, FILL],
        PRES=[5.1, 10.1, FILL, 20.1, FILL, FILL],
        TEMP_ADJUSTED=[28.1, 27.9, FILL, 20.3, FILL, FILL],
        PSAL_ADJUSTED=[35.0, 35.1, FILL, NAN, FILL, FILL],
        PRES_ADJUSTED_ERROR=[2.4, 2.4, FILL, 2.4, FILL, FILL],
        TEMP_ADJUSTED_ERROR=[0.002, 0.002, FILL, 0.002, FILL, FILL],
        PRES_ADJUSTED_QC="11 2  ",
        TEMP_ADJUSTED_QC="11 1  ",
        PSAL_ADJUSTED_QC="11 4  ",
    ),
    # R mode: repeated and nonmonotonic pressure, out-of-range temperature and salinity.
    profile(
        platform="5900002",
        cycle=8,
        mode="R",
        PRES=[5.0, 10.0, 10.0, 8.0, 20.0, FILL],
        TEMP=[28.0, -6.0, 27.0, 26.0, 25.0, FILL],
        PSAL=[35.0, 61.5, 35.0, 35.0, 35.0, FILL],
        PRES_QC="111111",
        TEMP_QC="1 1 1 ",
    ),
    profile(platform="5900003", lat=FILL),  # no position
    profile(platform="5900004", juld=999999.0),  # no time
    profile(platform="5900005"),  # no core level at all
    profile(platform="5900006", mode=" ", PRES=[1.0] + [FILL] * 5),  # unknown data mode
    profile(platform="5900007", lon=130.0, PRES=[1.0] + [FILL] * 5, mode="R"),  # other tile
]


@pytest.fixture
def edge(tmp_path):
    return synthetic(tmp_path, EDGE_ROWS)


def test_edge_conversion_fill_trim_nonfinite_and_exclusions(edge):
    excluded = Counter()
    docs = list(gdac.profiles_from_netcdf(edge, excluded=excluded))
    assert excluded == {"no_position": 1, "no_time": 1, "no_core_levels": 1}
    assert [d["platform"] for d in docs] == ["5900001", "5900002", "5900006", "5900007"]
    first = docs[0]
    # Trailing all-fill rows are dropped; the interior all-fill row stays as the fill token.
    assert first["n_levels"] == 4
    assert first["PRES_ADJUSTED"] == ["5", "10", "99999", "20"]
    assert first["PRES"] == ["5.1", "10.1", "99999", "20.1"]
    assert first["PSAL_ADJUSTED"][3] == "NaN"
    assert first["PSAL"] == ["99999"] * 4
    # Blank QC characters are carried as the empty string.
    assert first["PRES_ADJUSTED_QC"] == ["1", "1", "", "2"] and first["TEMP_QC"] == [""] * 4
    assert first["date_update"] == "2026-01-01T00:00:00+00:00"
    assert first["observed_at"] == "2025-01-15T12:00:00.000000+00:00"
    assert first["sampling"] is None and first["data_centre"] == "IF"
    assert (first["longitude"], first["latitude"]) == ("60.25", "10.5")
    assert gdac.profile_identities(edge) == {
        "gdac:5900001_7A",
        "gdac:5900002_8A",
        "gdac:5900003_7A",
        "gdac:5900004_7A",
        "gdac:5900005_7A",
        "gdac:5900006_7A",
        "gdac:5900007_7A",
    }
    owned = list(gdac.profiles_from_netcdf(edge, tile=Tile(60, 10)))
    assert [d["platform"] for d in owned] == ["5900001", "5900002", "5900006"]


def test_edge_mapping_modes_flags_and_blank_qc(edge):
    docs = list(gdac.profiles_from_netcdf(edge))
    d_profile = gdac.gdac_map_profile(docs[0], CanonicalBudget())
    level = d_profile.levels
    assert level[0]["pressure"] is None and level[0]["pressure_adjusted"] == 5.0
    assert level[0]["pressure_error"] == 2.4 and level[0]["temperature_error"] == 0.002
    assert level[0]["salinity_error"] is None  # all fill: argo_fill, no value
    assert level[2]["pressure_adjusted"] is None and level[2]["pressure_adjusted_qc"] is None
    assert level[2]["pressure_adjusted_qc_source"] == ""  # blank is kept as source ""
    assert level[3]["salinity_adjusted"] is None  # NaN: nonfinite
    canonical = json.loads(d_profile.canonical_bytes)
    c = canonical["levels"]
    assert c[2]["pressure_adjusted"]["missing_reason"] == "argo_fill"
    assert c[3]["salinity_adjusted"] == {
        "exact": None,
        "missing_reason": "nonfinite",
        "nonfinite_kind": "nan",
        "flags": [],
    }
    assert c[0]["pressure_error"]["exact"] == "2.4"
    assert level[0]["pressure_data_mode"] == "D" and level[0]["temperature_unit"] == "degree_C"
    r_profile = gdac.gdac_map_profile(docs[1], CanonicalBudget())
    assert (
        r_profile.levels[0]["pressure"] == 5.0 and r_profile.levels[0]["pressure_adjusted"] is None
    )
    assert r_profile.levels[0]["pressure_error"] is None  # R carries no adjusted error
    flags = [x["pressure_flags"] for x in r_profile.levels]
    assert "repeated_pressure" in flags[2] and "nonmonotonic_pressure" in flags[3]
    assert "repeated_pressure" not in flags[1] and "nonmonotonic_pressure" not in flags[2]
    assert "outside_plausibility_range" in r_profile.levels[1]["temperature_flags"]
    assert "outside_plausibility_range" in r_profile.levels[1]["salinity_flags"]
    assert "outside_plausibility_range" not in r_profile.levels[0]["temperature_flags"]
    assert r_profile.levels[1]["temperature_qc_source"] == ""  # blank QC at a valid value
    with pytest.raises(Rejection, match="unknown_data_mode"):
        gdac.gdac_map_profile(docs[2], CanonicalBudget())


def test_a_mode_and_negative_uncertainty_and_absent_variable(tmp_path):
    rows = [
        profile(
            mode="A",
            PRES_ADJUSTED=[5.0],
            TEMP_ADJUSTED=[28.0],
            TEMP_ADJUSTED_ERROR=[-0.5],
            PRES_ADJUSTED_QC="1",
        ),
    ]
    path = synthetic(tmp_path, rows, levels=1)
    doc = next(gdac.profiles_from_netcdf(path))
    with pytest.raises(Rejection, match="negative_uncertainty"):
        gdac.gdac_map_profile(doc, CanonicalBudget())
    doc["TEMP_ADJUSTED_ERROR"] = ["0.5"]
    doc["PSAL_ADJUSTED"] = ["99999"]
    mapped = gdac.gdac_map_profile(doc, CanonicalBudget())
    assert mapped.levels[0]["temperature_adjusted"] == 28.0
    assert mapped.levels[0]["temperature_data_mode"] == "A"
    # A variable that is not in the document at all is variable_absent, not argo_fill.
    wire = gdac.wire_document(doc)
    names, attrs, values = wire["data_info"]
    keep = [i for i, n in enumerate(names) if not n.startswith("salinity")]
    wire["data_info"] = [[names[i] for i in keep], attrs, [values[i] for i in keep]]
    wire["data"] = [wire["data"][i] for i in keep]
    absent = gdac.gdac_map_profile(wire, CanonicalBudget())
    assert absent.levels[0]["salinity_flags"] == ["variable_absent"]
    assert absent.levels[0]["salinity_data_mode"] is None


@pytest.mark.parametrize(
    "change,category",
    [
        ({"direction": "U"}, "invalid_direction"),
        ({"direction": ""}, "invalid_direction"),
        ({"cycle": None}, "invalid_cycle"),
        ({"platform": ""}, "missing_platform"),
        ({"platform": "59/1"}, "missing_platform"),
        ({"units": {"PRES": "decibar", "TEMP": "kelvin", "PSAL": "psu"}}, "unknown_unit"),
        ({"observed_at": "2025-01-15T12:00:00"}, "timezone_required"),
        ({"latitude": "95"}, "invalid_coordinates"),
        ({"longitude": 70}, "invalid_coordinates"),
    ],
)
def test_mapper_rejection_categories(change, category):
    document = {**next(gdac.profiles_from_netcdf(JAN)), **change}
    with pytest.raises(Rejection, match=category):
        gdac.gdac_map_profile(document, CanonicalBudget())


def test_wire_input_rejections():
    wire = gdac.wire_document(next(gdac.profiles_from_netcdf(JAN)))
    for mutate, category in (
        (lambda w: w.update(extra=1), "unsupported_profile_schema"),
        (lambda w: w.pop("source"), "unsupported_profile_schema"),
        (lambda w: w.update(metadata=["gdac:1", "gdac:2"]), "missing_metadata"),
        (lambda w: w.update(metadata=["argovis:1902253"]), "invalid_metadata_pointer"),
        (lambda w: w.update(_id="gdac:1902253_167A"), "invalid_profile_id"),
        (lambda w: w.update(data=w["data"][:-1]), "invalid_data_info"),
        (lambda w: w["data_info"][0].__setitem__(0, "doxy"), "unknown_data_field"),
        (lambda w: w["data"][0].pop(), "mismatched_array_lengths"),
        (lambda w: w["data"].__setitem__(0, []), "invalid_array_length"),
        (lambda w: w["data"][0].__setitem__(0, "0.96"), "invalid_scientific_numeric_string"),
        (lambda w: w.update(source=[{"source": ["x"], "unknown": 1}]), "invalid_source"),
    ):
        broken = next(documents(b"[" + gdac.encode_wire(wire) + b"]"))
        mutate(broken)
        with pytest.raises(Rejection, match=category):
            gdac.gdac_map_profile(broken, CanonicalBudget())
    metadata = {"gdac:1902253": {"_id": "gdac:1902253", "data_type": "oceanicProfile"}}
    with pytest.raises(Rejection, match="missing_platform"):
        gdac.gdac_map_profile(wire, CanonicalBudget(), metadata)
    metadata["gdac:1902253"]["platform"] = "1902254"
    with pytest.raises(Rejection, match="conflicting_platform"):
        gdac.gdac_map_profile(wire, CanonicalBudget(), metadata)
    with pytest.raises(Rejection, match="unresolved_metadata"):
        gdac.gdac_map_profile(wire, CanonicalBudget(), {})
    metadata["gdac:1902253"]["platform"] = "1902253"
    assert gdac.gdac_map_profile(wire, CanonicalBudget(), metadata).platform == "1902253"


# --- exact text -------------------------------------------------------------------------------


def test_exact_text_is_the_shortest_round_trip_of_the_stored_dtype():
    rng = np.random.default_rng(20250115)
    values = rng.normal(20, 10, 3000).astype(np.float32)
    for value in values:
        text = gdac.exact_text(value)
        assert np.float32(text) == value
        digits = len(text.lstrip("-").replace(".", "").lstrip("0")) or 1
        if digits > 1:  # the correctly rounded value with one digit fewer must not round-trip
            shorter = np.format_float_scientific(value, precision=digits - 2, unique=False)
            assert np.float32(shorter) != value
    # A float32 is not its float64 neighbour's text: 0.1f is "0.1", not 0.10000000149011612.
    assert gdac.exact_text(np.float32(0.1)) == "0.1"
    assert gdac.exact_text(np.float64(np.float32(0.1))) == "0.10000000149011612"
    assert gdac.exact_text(np.float32(99999)) == "99999"
    assert gdac.exact_text(np.float32(-0.0)) == "-0"
    assert gdac.exact_text(np.float32("nan")) == "NaN"
    assert gdac.exact_text(np.float32("inf")) == "Infinity"
    assert gdac.exact_text(np.float32("-inf")) == "-Infinity"
    assert gdac.exact_text(np.float32(1e-10)) == "0.0000000001"


def test_exact_text_reaches_the_canonical_exact_field_and_float64_value():
    document = next(gdac.profiles_from_netcdf(JAN))
    mapped = gdac.gdac_map_profile(document, CanonicalBudget())
    canonical = json.loads(mapped.canonical_bytes)
    for index, text in enumerate(document["PRES_ADJUSTED"][:200]):
        exact = canonical["levels"][index]["pressure_adjusted"]["exact"]
        if text == "99999":
            assert exact is None
        else:
            assert exact == text
            assert mapped.levels[index]["pressure_adjusted"] == float(Decimal(text))
    # float32 stored values are generally not exact in binary64: that is the rounded flag.
    assert "rounded" in canonical["levels"][0]["pressure_adjusted"]["flags"]
    assert canonical["longitude"]["exact"] == "77.10333"
    assert canonical["latitude"]["exact"] == "-23.17605"


# --- canonical structure and hashes ------------------------------------------------------------


def test_canonical_structure_matches_argovis_core_v1(wire, linked_metadata):
    argovis = map_profile(
        decode_json(json.dumps(wire).encode()), linked_metadata, CanonicalBudget()
    )
    mapped = gdac.gdac_map_profile(next(gdac.profiles_from_netcdf(JAN)), CanonicalBudget())
    a, g = json.loads(argovis.canonical_bytes), json.loads(mapped.canonical_bytes)
    assert set(g) == set(a)
    assert set(g["levels"][0]) == set(a["levels"][0])
    assert set(mapped.levels[0]) == set(argovis.levels[0])
    assert (g["source"], g["mapping_version"], g["hash_version"]) == (
        "gdac",
        "gdac-core-v1",
        "scientific-json-v2",
    )
    assert (a["source"], a["mapping_version"]) == ("argovis", "argovis-core-v1")
    assert set(g["longitude"]) == set(a["longitude"]) and g["position_qc"] == ["1", "1", []]
    assert g["time_qc"] == ["1", "1", []] and g["sampling"].startswith("Primary sampling")
    # Same Python types in the level rows so parquet writing needs no change.
    for key, value in argovis.levels[0].items():
        other = mapped.levels[0][key]
        assert value is None or other is None or type(value) is type(other), key
    assert mapped.canonical_bytes == json.dumps(g, sort_keys=True, separators=(",", ":")).encode()
    assert (mapped.platform, mapped.cycle, mapped.direction) == ("1902253", 166, "A")
    assert mapped.source_profile_id == "gdac:1902253_166A"
    assert mapped.identity == "id:gdac:1902253_166A"
    assert mapped.revision is not None and mapped.revision.kind == "gdac-date-update-v1"
    assert dict(mapped.revision.components) == {"file": datetime(2026, 10, 7, 2, 2, 8, tzinfo=UTC)}
    assert mapped.outside_core_arrays == 0
    assert mapped.natural_key == ("1902253", 166, "A", mapped.observed_at, "single")


def test_profile_hashes_are_stable():
    jan = gdac.gdac_map_profile(jan_documents()[0], CanonicalBudget())
    r_mode = next(
        gdac.gdac_map_profile(d, CanonicalBudget())
        for d in jan_documents()
        if d["data_mode"] == "R"
    )
    feb = gdac.gdac_map_profile(next(gdac.profiles_from_netcdf(FEB)), CanonicalBudget())
    assert (jan.source_profile_id, jan.content_hash) == EXPECTED_HASHES["jan_d"]
    assert (r_mode.source_profile_id, r_mode.content_hash) == EXPECTED_HASHES["jan_r"]
    assert (feb.source_profile_id, feb.content_hash) == EXPECTED_HASHES["feb_first"]
    assert hashlib.sha256(jan.canonical_bytes).hexdigest() == jan.content_hash


def test_one_level_profile_equals_a_hand_written_canonical_document(tmp_path):
    path = synthetic(
        tmp_path,
        [
            profile(
                mode="R",
                PRES=[5.0],
                TEMP=[28.1],
                PSAL=[35.0],
                PRES_QC="1",
                TEMP_QC="1",
                PSAL_QC="2",
                scheme="Primary sampling: averaged []",
            )
        ],
        levels=1,
    )
    mapped = gdac.gdac_map_profile(next(gdac.profiles_from_netcdf(path)), CanonicalBudget())

    def number(exact, *flags):
        return {
            "exact": exact,
            "missing_reason": None,
            "nonfinite_kind": None,
            "flags": list(flags),
        }

    level = {"level_index": 0}
    for name, exact, units, unit, flags, quality in (
        ("pressure", "5", "decibar", "dbar", [], "1"),
        ("temperature", "28.1", "degree_Celsius", "degree_C", ["rounded"], "1"),
        ("salinity", "35", "psu", "1", [], "2"),
    ):
        for suffix in (
            "_adjusted",
            "_error",
            "_original_error",
            "_adjusted_qc",
            "_adjusted_qc_source",
        ):
            level[name + suffix] = None
        level.update(
            {
                name: number(exact, *flags),
                name + "_qc": quality,
                name + "_qc_source": quality,
                name + "_unit": unit,
                name + "_unit_source": units,
                name + "_data_mode": "R",
                name + "_flags": list(flags),
            }
        )
    expected = {
        "source": "gdac",
        "platform": "5900001",
        "cycle": 7,
        "direction": "A",
        "observed_at": "2025-01-15T12:00:00.000000+00:00",
        "longitude": number("60.25"),
        "latitude": number("10.5"),
        "position_qc": ["1", "1", []],
        "time_qc": ["1", "1", []],
        "sampling": "Primary sampling: averaged []",
        "levels": [level],
        "hash_version": "scientific-json-v2",
        "mapping_version": "gdac-core-v1",
    }
    assert json.loads(mapped.canonical_bytes) == expected
    written = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert mapped.canonical_bytes == written
    assert mapped.content_hash == hashlib.sha256(written).hexdigest()
    assert mapped.levels[0]["temperature"] == float(Decimal("28.1"))
    assert mapped.levels[0]["temperature_flags"] == ["rounded"]
    assert mapped.levels[0]["pressure_flags"] == []


def test_real_profiles_exercise_interior_fill_repeated_pressure_and_missing_adjusted_arrays():
    interior, repeated, adjusted_fill = [], [], []
    for doc in jan_documents():
        selected = "PRES_ADJUSTED" if doc["data_mode"] in ("A", "D") else "PRES"
        if "99999" in doc[selected]:
            interior.append(doc)
        if all(x == "99999" for x in doc["TEMP_ADJUSTED"]) and doc["data_mode"] in ("A", "D"):
            adjusted_fill.append(doc)
        values = [x for x in doc[selected] if x != "99999"]
        if len(set(values)) != len(values):
            repeated.append(doc)
    assert (len(interior), len(repeated), len(adjusted_fill)) == (10, 1, 1)
    mapped = gdac.gdac_map_profile(interior[0], CanonicalBudget())
    selected = "pressure_adjusted" if interior[0]["data_mode"] in ("A", "D") else "pressure"
    holes = [i for i, x in enumerate(mapped.levels) if x[selected] is None]
    assert holes and len(mapped.levels) == interior[0]["n_levels"]
    canonical = json.loads(mapped.canonical_bytes)["levels"]
    assert all(canonical[i][selected]["missing_reason"] == "argo_fill" for i in holes)
    flags = [
        f
        for x in gdac.gdac_map_profile(repeated[0], CanonicalBudget()).levels
        for f in x["pressure_flags"]
    ]
    assert "repeated_pressure" in flags
    # D mode with every adjusted temperature missing stays adjusted/argo_fill (nothing is invented).
    empty = gdac.gdac_map_profile(adjusted_fill[0], CanonicalBudget())
    assert all(x["temperature_adjusted"] is None and x["temperature"] is None for x in empty.levels)
    assert (
        json.loads(empty.canonical_bytes)["levels"][0]["temperature_adjusted"]["missing_reason"]
        == "argo_fill"
    )


def test_every_fixture_profile_maps_and_hashes_deterministically():
    budget = CanonicalBudget()
    seen = {}
    for path in (JAN, FEB):
        for doc in gdac.profiles_from_netcdf(path, tile=TILE):
            mapped = gdac.gdac_map_profile(doc, budget)
            seen[mapped.source_profile_id] = mapped.content_hash
            again = gdac.gdac_map_profile(doc, CanonicalBudget())
            assert again.content_hash == mapped.content_hash
    assert len(seen) == 8
    assert budget.chunk_used > 0


def test_policy_versions_match_the_fast_mapper_when_present():
    try:
        theirs = policy_versions("gdac-core-v1")
    except Rejection:
        pytest.skip("argovis.policy_versions has no gdac-core-v1 yet")
    assert theirs == gdac.VERSIONS


def test_validate_netcdf_counts_profiles_and_rejects_garbage():
    assert gdac.validate_netcdf(JAN.read_bytes()) == {"schema": "gdac-netcdf-v1", "profiles": 97}
    for payload in (b"", b"not netcdf", JAN.read_bytes()[:4096]):
        with pytest.raises(Rejection, match="invalid_netcdf"):
            gdac.validate_netcdf(payload)


def test_netcdf_without_gdac_variables_is_rejected(tmp_path):
    path = tmp_path / "other.nc"
    with netCDF4.Dataset(str(path), "w") as ds:
        ds.createDimension("N_PROF", 1)
    with pytest.raises(Rejection, match="invalid_netcdf"):
        list(gdac.profiles_from_netcdf(path))


# --- fetch_file guards --------------------------------------------------------------------------

ADDRESS = "134.246.232.86"


class FakeResponse:
    def __init__(self, status=200, headers=(), body=b"payload"):
        self.status, self.headers, self.body = status, list(headers), body
        self.offset = 0

    def getheaders(self):
        return self.headers

    def getheader(self, key, default=None):
        return next((v for k, v in self.headers if k.lower() == key.lower()), default)

    def read(self, amount):
        piece = self.body[self.offset : self.offset + amount]
        self.offset += len(piece)
        return piece


class FakeConnection:
    instances: list = []
    failing: set = set()
    response = FakeResponse()
    error: Exception | None = None

    def __init__(self, address, timeout):
        self.address, self.timeout, self.closed, self.sock = address, timeout, False, Mock()
        self.requests = []
        FakeConnection.instances.append(self)

    def connect(self):
        if self.address in FakeConnection.failing:
            raise OSError("unreachable")

    def request(self, method, target, headers=None):
        self.requests.append((method, target, dict(headers or {})))

    def getresponse(self):
        if FakeConnection.error is not None:
            raise FakeConnection.error
        return FakeConnection.response

    def close(self):
        self.closed = True


@pytest.fixture
def network(monkeypatch):
    FakeConnection.instances, FakeConnection.failing = [], set()
    FakeConnection.response, FakeConnection.error = FakeResponse(), None
    monkeypatch.setattr(gdac, "PinnedConnection", FakeConnection)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, (ADDRESS, 443))]
    )
    return FakeConnection


def run_fetch(max_bytes=1024, path=JAN_KEY, seconds=60):
    import time

    return gdac.fetch_file(path, time.monotonic() + seconds, max_bytes=max_bytes)


def test_fetch_file_sends_one_anonymous_pinned_get(network):
    network.response = FakeResponse(headers=[("Content-Length", "7")])
    assert run_fetch() == b"payload"
    (connection,) = network.instances
    assert connection.address == ADDRESS and connection.closed
    ((method, target, headers),) = connection.requests
    assert (method, target) == ("GET", "/" + JAN_KEY)
    assert {k.lower() for k in headers} == {"host", "accept", "accept-encoding", "connection"}
    assert headers["Host"] == gdac.GDAC_HOST and headers["Accept-Encoding"] == "identity"
    assert "credential" not in gdac.fetch_file.__code__.co_varnames


@pytest.mark.parametrize(
    "path",
    [
        "http://data-argo.ifremer.fr/ar_index_global_prof.txt.gz",
        "https://evil.test/ar_index_global_prof.txt.gz",
        "/ar_index_global_prof.txt.gz",
        "../ar_index_global_prof.txt.gz",
        "dac/aoml/13857/profiles/R13857_001.nc",
        "geo/pacific_ocean/2025/01/20250115_prof.nc",
        "geo/indian_ocean/2025/01/20250115_prof.nc?x=1",
        "geo/indian_ocean/2025/01/20250115_prof.nc#x",
        "geo/indian_ocean/2025/1/20250115_prof.nc",
        "geo/indian_ocean/2025/01/../../../etc/passwd",
        "ar_index_global_prof.txt.gz/extra",
        "",
        None,
    ],
)
def test_fetch_file_path_allowlist(network, path):
    with pytest.raises(Rejection, match="unapproved_upstream_endpoint"):
        run_fetch(path=path)
    assert network.instances == []


def test_fetch_file_accepts_the_three_approved_shapes(network):
    for path in (gdac.INDEX_KEY, JAN_KEY, "geo/indian_ocean/2025/01/"):
        network.response = FakeResponse()
        assert run_fetch(path=path) == b"payload"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_fetch_file_rejects_mixed_or_private_dns_answers(monkeypatch, network, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (None, None, None, None, (ADDRESS, 443)),
            (None, None, None, None, (address, 443)),
        ],
    )
    with pytest.raises(Rejection, match="upstream_dns_unsafe"):
        run_fetch()
    assert network.instances == []


def test_fetch_file_dns_failures(monkeypatch, network):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(Rejection, match="upstream_dns_empty"):
        run_fetch()

    def failing(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", failing)
    with pytest.raises(Rejection, match="upstream_transport_failure"):
        run_fetch()


def test_fetch_file_tries_next_validated_address(monkeypatch, network):
    other = "134.246.232.87"
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, (a_, 443)) for a_ in (ADDRESS, other)],
    )
    network.failing = {ADDRESS}
    assert run_fetch() == b"payload"
    assert [c.address for c in network.instances] == [ADDRESS, other]
    assert all(c.closed for c in network.instances)
    network.failing = {ADDRESS, other}
    with pytest.raises(Rejection, match="upstream_transport_failure"):
        run_fetch()


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_fetch_file_never_follows_redirects(network, status):
    network.response = FakeResponse(status, [("Location", "https://evil.test/")])
    with pytest.raises(Rejection, match="upstream_redirect_rejected"):
        run_fetch()
    assert len(network.instances) == 1 and network.instances[0].closed


def test_fetch_file_http_failures_keep_status_and_retry_after(network):
    network.response = FakeResponse(404)
    with pytest.raises(HTTPFailure) as error:
        run_fetch()
    assert error.value.status == 404 and not error.value.retryable
    network.response = FakeResponse(503, [("Retry-After", "30")])
    with pytest.raises(HTTPFailure) as error:
        run_fetch()
    assert error.value.retryable and error.value.retry_after == "30"


@pytest.mark.parametrize(
    "headers,body,category",
    [
        ([("Content-Length", "7"), ("Content-Length", "7")], b"payload", "ambiguous_http_framing"),
        (
            [("Content-Length", "7"), ("Transfer-Encoding", "chunked")],
            b"payload",
            "ambiguous_http_framing",
        ),
        ([("Content-Length", "abc")], b"", "invalid_content_length"),
        ([("Content-Length", "1" * 11)], b"", "invalid_content_length"),
        ([("Content-Length", "2000")], b"", "gdac_file_size_limit"),
        ([("Content-Length", "10")], b"short", "truncated_http_body"),
        ([("Transfer-Encoding", "gzip")], b"x", "unsupported_transfer_encoding"),
        ([("Content-Encoding", "gzip")], b"x", "unsupported_content_encoding"),
        ([], b"x" * 2000, "gdac_file_size_limit"),
    ],
)
def test_fetch_file_framing_and_size_guards(network, headers, body, category):
    network.response = FakeResponse(headers=headers, body=body)
    with pytest.raises(Rejection, match=category):
        run_fetch()
    assert network.instances[0].closed


def test_fetch_file_size_boundary_chunked_and_budget(network):
    network.response = FakeResponse(headers=[("Transfer-Encoding", "chunked")], body=b"x" * 1024)
    assert len(run_fetch(max_bytes=1024)) == 1024
    network.response = FakeResponse(headers=[], body=b"x" * 1025)
    with pytest.raises(Rejection, match="gdac_file_size_limit"):
        run_fetch(max_bytes=1024)
    for bad in (0, -1, gdac.MAX_FILE_BYTES + 1):
        with pytest.raises(Rejection, match="invalid_http_budget"):
            run_fetch(max_bytes=bad)


def test_fetch_file_transport_errors_and_deadline(network):
    network.error = http.client.IncompleteRead(b"x")
    with pytest.raises(Rejection, match="upstream_transport_failure"):
        run_fetch()
    network.error = ssl.SSLError("bad certificate")
    with pytest.raises(Rejection, match="upstream_transport_failure"):
        run_fetch()
    network.error = TimeoutError()
    with pytest.raises(Rejection, match="upstream_transport_failure"):
        run_fetch()
    network.error = None
    with pytest.raises(Rejection, match="io_deadline"):
        run_fetch(seconds=-1)


def test_fetch_file_idle_timeout_and_attempt_bound_are_socket_level(network):
    run_fetch(seconds=30)
    connection = network.instances[0]
    connection.sock.settimeout.assert_called_once()
    assert connection.sock.settimeout.call_args[0][0] <= 60
    assert connection.timeout <= 10  # DNS/connect/TLS budget


def test_pinned_connection_connects_to_the_validated_ip_with_sni(monkeypatch):
    seen = {}

    def create_connection(address, timeout=None):
        seen["address"] = address
        return Mock(name="plain")

    monkeypatch.setattr(socket, "create_connection", create_connection)
    connection = gdac.PinnedConnection(ADDRESS, 5)
    assert (
        connection.tls_context.check_hostname
        and connection.tls_context.verify_mode == ssl.CERT_REQUIRED
    )
    assert connection.host == gdac.GDAC_HOST and connection.port == 443
    connection.tls_context = Mock()
    connection.connect()
    assert seen["address"] == (ADDRESS, 443)
    connection.tls_context.wrap_socket.assert_called_once()
    assert connection.tls_context.wrap_socket.call_args.kwargs == {
        "server_hostname": gdac.GDAC_HOST
    }
    connection.tls_context.wrap_socket.side_effect = ssl.SSLError("handshake")
    plain = Mock()
    monkeypatch.setattr(socket, "create_connection", lambda a, timeout=None: plain)
    with pytest.raises(ssl.SSLError):
        connection.connect()
    plain.close.assert_called_once()


# --- download cache -----------------------------------------------------------------------------


class Downloads:
    """A fetch double serving the committed fixtures by key; counts calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.files = {JAN_KEY: JAN.read_bytes(), FEB_KEY: FEB.read_bytes()}
        self.files[gdac.INDEX_KEY] = gzip.compress(b"file,date,latitude,longitude\n" * 0 + b"#\n")

    def __call__(self, key, deadline, *, max_bytes):
        self.calls.append(key)
        if key not in self.files:
            raise HTTPFailure(404)
        return self.files[key]


def test_cached_file_downloads_once_and_validates(tmp_path):
    fetch = Downloads()
    first = gdac.cached_file(tmp_path, JAN_KEY, 1e12, fetch=fetch)
    second = gdac.cached_file(tmp_path, JAN_KEY, 1e12, fetch=fetch)
    assert first == second == tmp_path / JAN.name and fetch.calls == [JAN_KEY]
    assert first.read_bytes() == JAN.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.endswith(".lock")) == [JAN.name]
    fetch.files[FEB_KEY] = b"<html>error page</html>"
    with pytest.raises(Rejection, match="invalid_netcdf"):
        gdac.cached_file(tmp_path, FEB_KEY, 1e12, fetch=fetch)
    assert not (tmp_path / FEB.name).exists()
    with pytest.raises(Rejection, match="unapproved_upstream_endpoint"):
        gdac.cached_file(tmp_path, "dac/x.nc", 1e12, fetch=fetch)


def test_cached_file_is_shared_by_concurrent_threads(tmp_path):
    import threading
    import time

    calls = []

    def slow(key, deadline, *, max_bytes):
        calls.append(key)
        time.sleep(0.3)
        return JAN.read_bytes()

    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(gdac.cached_file(tmp_path, JAN_KEY, 1e12, fetch=slow))
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == [JAN_KEY] and results == [tmp_path / JAN.name] * 4


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_download_retries_follow_request_owner_categories(tmp_path):
    clock, beats = Clock(), []
    answers = [HTTPFailure(503, "2"), Rejection("upstream_transport_failure"), JAN.read_bytes()]

    def fetch(key, deadline, *, max_bytes):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    path = gdac.cached_file(
        tmp_path,
        JAN_KEY,
        1e12,
        fetch=fetch,
        sleep=clock.sleep,
        clock=clock,
        jitter=lambda: 0.0,
        heartbeat=lambda: beats.append(1),
    )
    assert path.exists() and not answers
    assert sum(clock.slept) == 30 + 90 and beats  # 60/2 and 180/2 floors from retry_delay
    for failure, category in (
        (HTTPFailure(404), "http_retry_exhausted"),
        (HTTPFailure(503), "http_retry_exhausted"),
        (Rejection("upstream_dns_unsafe"), "upstream_dns_unsafe"),
        (Rejection("gdac_file_size_limit"), "gdac_file_size_limit"),
    ):
        calls = []

        def failing(key, deadline, *, max_bytes, failure=failure, calls=calls):
            calls.append(key)
            raise failure

        with pytest.raises(Rejection, match=category):
            gdac.cached_file(
                tmp_path,
                FEB_KEY,
                1e12,
                fetch=failing,
                sleep=clock.sleep,
                clock=clock,
                jitter=lambda: 0.0,
            )
        assert len(calls) == (4 if isinstance(failure, HTTPFailure) and failure.retryable else 1)
    with pytest.raises(Rejection, match="http_retry_deadline"):
        gdac.cached_file(tmp_path, FEB_KEY, 0.0, fetch=Downloads(), clock=clock)
    slow = Clock()
    with pytest.raises(Rejection, match="http_retry_deadline"):  # the wait would pass the deadline
        gdac.cached_file(
            tmp_path,
            FEB_KEY,
            slow.now + 10,
            fetch=lambda *a, **k: (_ for _ in ()).throw(HTTPFailure(503)),
            clock=slow,
            sleep=slow.sleep,
            jitter=lambda: 0.0,
        )


def test_cached_index_hashes_each_file_version_once(tmp_path, monkeypatch):
    fetch = Downloads()
    digest = hashlib.sha256(fetch.files[gdac.INDEX_KEY]).hexdigest()
    gdac.cached_index(tmp_path, digest, 1e12, fetch=fetch)
    real, calls = hashlib.sha256, []
    monkeypatch.setattr(hashlib, "sha256", lambda *a, **k: calls.append(1) or real(*a, **k))
    for _ in range(3):
        assert gdac.cached_index(tmp_path, digest, 1e12, fetch=fetch)[1] == digest
    assert calls == []


def test_cached_index_pins_the_digest(tmp_path):
    fetch = Downloads()
    digest = hashlib.sha256(fetch.files[gdac.INDEX_KEY]).hexdigest()
    path, found = gdac.cached_index(tmp_path, digest, 1e12, fetch=fetch)
    assert found == digest and path.name == gdac.INDEX_KEY
    gdac.cached_index(tmp_path, digest, 1e12, fetch=fetch)
    assert fetch.calls == [gdac.INDEX_KEY]
    with pytest.raises(Rejection, match="gdac_index_changed"):
        gdac.cached_index(tmp_path, "0" * 64, 1e12, fetch=fetch)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(Rejection, match="gdac_index_changed"):
        gdac.cached_index(other, "0" * 64, 1e12, fetch=Downloads())
    assert not (other / gdac.INDEX_KEY).exists()


def test_prepare_cache_returns_the_run_input_descriptor(tmp_path):
    fetch = Downloads()
    descriptor = gdac.prepare_cache(tmp_path / "cache", DAY, 1e12, fetch=fetch)
    assert descriptor["kind"] == "gdac" and descriptor["cache_dir"] == str(tmp_path / "cache")
    assert descriptor["index_sha256"] == hashlib.sha256(fetch.files[gdac.INDEX_KEY]).hexdigest()
    assert fetch.calls == [gdac.INDEX_KEY, JAN_KEY]


# --- GdacSource ---------------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.data = {}
        self.writes = []

    def write_temporary(self, key, payload, deadline):
        raise AssertionError("write_immutable is the only write path")

    def write_immutable(self, key, data, sha256_hex, deadline):
        assert hashlib.sha256(data).hexdigest() == sha256_hex
        self.writes.append(key)
        assert self.data.setdefault(key, data) == data

    def stat(self, key, deadline):
        if key not in self.data:
            raise Rejection("object_missing")
        return {"bytes": len(self.data[key]), "sha256": None}

    def read(self, key, max_bytes, deadline):
        if key not in self.data:
            raise Rejection("object_missing")
        return self.data[key]

    def publish_if_absent(self, temporary, final, deadline):
        raise AssertionError("not used")


class Repository:
    def __init__(self, interval=DAY, tile=TILE):
        self.row = {
            "requested_start": interval.start,
            "requested_end": interval.end,
            "tile": {
                "west": tile.west,
                "south": tile.south,
                "width": tile.width,
                "height": tile.height,
            },
        }
        self.landings, self.reserved, self.finished, self.beats = {}, [], [], 0

    def chunk(self, chunk):
        return self.row

    def heartbeat(self, authority):
        self.beats += 1

    def verified_landing(self, authority, key):
        return self.landings.get(key)

    def recorded_reserve(self, authority, key, role, parameters, origin):
        attempt = uuid.uuid4()
        self.reserved.append((key, role, parameters, origin, attempt))
        return attempt

    def finish_attempt(
        self, authority, attempt, disposition, status=None, error=None, manifest=None
    ):
        self.finished.append((disposition, status, error))
        key = next(k for k, *_, a in self.reserved if a == attempt)
        self.landings[key] = {**manifest, "object_key": manifest["key"]}


AUTHORITY = Authority(uuid.UUID(int=1), uuid.UUID(int=2), 1, 1)


@pytest.fixture
def cache(tmp_path):
    """A cache primed like `prepare_cache` leaves it, and its pinned descriptor."""
    directory = tmp_path / "cache"
    directory.mkdir()
    (directory / JAN.name).write_bytes(JAN.read_bytes())
    (directory / FEB.name).write_bytes(FEB.read_bytes())
    index = gzip.compress(INDEX.read_bytes())
    (directory / gdac.INDEX_KEY).write_bytes(index)
    return {
        "kind": "gdac",
        "cache_dir": str(directory),
        "index_sha256": hashlib.sha256(index).hexdigest(),
    }


def no_fetch(key, deadline, *, max_bytes):
    raise AssertionError(f"unexpected download of {key}")


def source(repository, store, descriptor, **options):
    options.setdefault("fetch", no_fetch)
    return gdac.GdacSource(
        repository,
        store,
        AUTHORITY,
        descriptor,
        deadline=1e12,
        application_commit="abc123",
        **options,
    )


def gdac_parameters(chunk, inventory):
    return request_parameters(chunk, inventory=inventory)


def parameters(interval=DAY, tile=TILE, *, inventory):
    return gdac_parameters(PlannedChunk(interval, tile), inventory)


def test_source_lands_the_three_selection_roles_as_an_argovis_wire_array(cache):
    repository, store = Repository(), Store()
    s = source(repository, store, cache)
    landings = {
        role: s.obtain("/argo", parameters(inventory=role != "profile"), role)
        for role in ("inventory_before", "profile", "inventory_after")
    }
    docs = {role: list(documents(land.payload)) for role, land in landings.items()}
    assert {role: len(d) for role, d in docs.items()} == {
        "inventory_before": 3,
        "profile": 3,
        "inventory_after": 3,
    }
    # The Argovis inventory machinery accepts the arrays unchanged and the triple agrees.
    identities = inventory_identities(docs["profile"], DAY)
    assert len(identities) == 3 and all(x.startswith("gdac:") for x in identities)
    verify_inventory(docs["inventory_before"], docs["profile"], docs["inventory_after"], DAY)
    inventory = docs["inventory_before"][0]
    assert set(inventory) == {
        "_id",
        "timestamp",
        "geolocation",
        "metadata",
        "profile_direction",
        "cycle_number",
    }
    assert inventory["metadata"] == [f"gdac:{inventory['_id'].split(':')[1].split('_')[0]}"]
    full = docs["profile"][0]
    assert set(full) >= {"data_info", "data", "source", "geolocation_argoqc", "timestamp_argoqc"}
    names = full["data_info"][0]
    assert {"pressure", "pressure_argoqc", "temperature", "salinity_argoqc"} <= set(names)
    assert all(isinstance(x, Decimal) for x in full["data"][0] if x is not None)
    # Mapping the landed document equals mapping the converted one (exact tokens survive).
    converted = {
        f"gdac:{d['platform']}_{d['cycle']}{d['direction']}": d
        for d in gdac.profiles_from_netcdf(JAN, TILE, DAY, name=JAN_KEY)
    }
    assert set(converted) == identities
    for document in docs["profile"]:
        landed = gdac.gdac_map_profile(document, CanonicalBudget())
        direct = gdac.gdac_map_profile(converted[document["_id"]], CanonicalBudget())
        assert landed.content_hash == direct.content_hash
        assert landed.canonical_bytes == direct.canonical_bytes
        assert landed.revision == direct.revision
        resolved = gdac.gdac_map_profile(
            document, CanonicalBudget(), {m: s_meta(m) for m in document["metadata"]}
        )
        assert resolved.content_hash == landed.content_hash
    assert [r[3] for r in repository.reserved] == ["gdac"] * 3
    assert [f[0] for f in repository.finished] == ["verified_raw"] * 3 and repository.beats > 0


def s_meta(pointer):
    return {"_id": pointer, "data_type": "oceanicProfile", "platform": pointer.split(":")[1]}


def test_source_manifest_records_derived_files_and_preserves_raw_netcdf(cache):
    repository, store = Repository(), Store()
    s = source(repository, store, cache)
    landing = s.obtain("/argo", parameters(inventory=False), "profile")
    manifest = landing.manifest
    assert manifest["versions"] == gdac.VERSIONS and manifest["http_status"] == 200
    assert manifest["application_commit"] == "abc123"
    assert manifest["key"] == f"raw/sha256/{manifest['sha256']}.json"
    assert store.data[manifest["key"]] == landing.payload
    sanitization = manifest["sanitization"]
    assert sanitization["version"] == "raw-sanitization-v1"
    assert sanitization["input_origin"] == sanitization["input_kind"] == "gdac"
    assert sanitization["validation"] == {"schema": gdac.SCHEMA, "documents": 3}
    digest = hashlib.sha256(JAN.read_bytes()).hexdigest()
    assert sanitization["derived_from"] == [
        {"file": JAN_KEY, "sha256": digest, "object_key": f"raw/sha256/{digest}.nc"}
    ]
    assert store.data[f"raw/sha256/{digest}.nc"] == JAN.read_bytes()
    assert sanitization["excluded"] == {} and sanitization["profiles"] == 3
    assert (
        sanitization["index_expected"] > 0 and sanitization["index_sha256"] == cache["index_sha256"]
    )
    assert datetime.fromisoformat(manifest["retrieved_at"]).tzinfo is not None
    # Inventory roles of the same chunk reference the same raw object without rewriting it.
    again = s.obtain("/argo", parameters(inventory=True), "inventory_before")
    assert again.manifest["sanitization"]["derived_from"] == sanitization["derived_from"]


def test_raw_netcdf_is_uploaded_once_for_all_tiles_and_instances(cache):
    store = Store()
    digest = hashlib.sha256(JAN.read_bytes()).hexdigest()
    nc = f"raw/sha256/{digest}.nc"
    for tile in (TILE, Tile(60, 0), Tile(60, 10)):
        s = source(Repository(DAY, tile), store, cache)
        for inventory, role in ((True, "inventory_before"), (False, "profile")):
            landing = s.obtain("/argo", parameters(DAY, tile, inventory=inventory), role)
            assert landing.manifest["sanitization"]["derived_from"][0]["object_key"] == nc
    assert store.writes.count(nc) == 1
    # A stored object of the wrong size is not trusted: the file is written again.
    store.data[nc] = b"truncated"
    store.writes.clear()
    with pytest.raises(AssertionError):  # the fake refuses to overwrite a different object
        source(Repository(DAY, TILE), store, cache).obtain(
            "/argo", parameters(inventory=False), "profile"
        )
    assert store.writes == [nc]


def test_source_metadata_role_synthesizes_the_pointer_document(cache):
    repository, store = Repository(), Store()
    s = source(repository, store, cache)
    landing = s.obtain("/argo/meta", {"id": "gdac:1902253"}, "metadata")
    assert list(documents(landing.payload)) == [
        {"_id": "gdac:1902253", "data_type": "oceanicProfile", "platform": "1902253"}
    ]
    assert landing.manifest["sanitization"]["derived_from"] == []
    for bad in ({"id": "argovis:1902253"}, {"id": "gdac:"}, {"id": "gdac:59/1"}):
        with pytest.raises(Rejection, match="invalid_metadata_pointer"):
            s.obtain("/argo/meta", bad, "metadata")
    with pytest.raises(Rejection, match="invalid_request_parameters"):
        s.obtain("/argo/meta", {"id": "gdac:1", "x": "y"}, "metadata")


def test_source_replay_reads_the_recorded_landing_without_touching_the_cache(cache, tmp_path):
    repository, store = Repository(), Store()
    first = source(repository, store, cache).obtain("/argo", parameters(inventory=False), "profile")
    replay = source(
        repository, store, {**cache, "cache_dir": str(tmp_path / "gone")}, require_existing=True
    )
    again = replay.obtain("/argo", parameters(inventory=False), "profile")
    assert again.payload == first.payload and again.manifest["sha256"] == first.manifest["sha256"]
    assert len(repository.reserved) == 1
    with pytest.raises(Rejection, match="landing_unavailable"):
        replay.obtain("/argo", parameters(inventory=True), "inventory_before")
    repository.landings[next(iter(repository.landings))]["versions"] = {"mapping": "other"}
    with pytest.raises(Rejection, match="landing_unavailable"):
        replay.obtain("/argo", parameters(inventory=False), "profile")


def test_source_cannot_restart_a_selection(cache):
    with pytest.raises(Rejection, match="incomplete_inventory"):
        source(Repository(), Store(), cache).restart_selection()


def test_source_rejects_parameters_that_are_not_the_chunk(cache):
    s = source(Repository(), Store(), cache)
    other = parameters(Interval(at((1, 15)), at((1, 17))), inventory=False)
    with pytest.raises(Rejection, match="invalid_request_parameters"):
        s.obtain("/argo", other, "profile")
    with pytest.raises(Rejection, match="invalid_request_parameters"):
        s.obtain("/argo", parameters(inventory=True), "profile")
    for path, role in (
        ("/argo/meta", "profile"),
        ("/argo", "metadata"),
        ("/other", "profile"),
        ("/argo", "x"),
    ):
        with pytest.raises(Rejection, match="invalid_request_role"):
            s.obtain(path, {}, role)


@pytest.mark.parametrize(
    "descriptor",
    [
        {"kind": "live", "cache_dir": "/tmp/x", "index_sha256": "0" * 64},
        {"kind": "gdac", "cache_dir": "/tmp/x", "index_sha256": "xyz"},
        {"kind": "gdac", "index_sha256": "0" * 64},
        {"kind": "gdac", "cache_dir": 5, "index_sha256": "0" * 64},
    ],
)
def test_source_rejects_invalid_descriptors(descriptor):
    with pytest.raises(Rejection, match="invalid_gdac_descriptor"):
        source(Repository(), Store(), descriptor)
    with pytest.raises(Rejection, match="unapproved_cache_path"):
        source(
            Repository(),
            Store(),
            {"kind": "gdac", "cache_dir": "/mnt/c/x", "index_sha256": "0" * 64},
        )


def test_source_downloads_each_file_once_across_tiles(tmp_path):
    fetch = Downloads()
    index = fetch.files[gdac.INDEX_KEY]
    descriptor = {
        "kind": "gdac",
        "cache_dir": str(tmp_path / "cache"),
        "index_sha256": hashlib.sha256(index).hexdigest(),
    }
    store = Store()
    for tile in (TILE, Tile(60, 0)):
        repository = Repository(DAY, tile)
        s = source(repository, store, descriptor, fetch=fetch, sleep=lambda seconds: None)
        landing = s.obtain("/argo", gdac_parameters(PlannedChunk(DAY, tile), False), "profile")
        assert landing.manifest["sanitization"]["derived_from"][0]["file"] == JAN_KEY
    assert fetch.calls == [JAN_KEY, gdac.INDEX_KEY]


def test_source_flags_a_profile_the_index_has_but_the_files_lack(cache):
    index_path = Path(cache["cache_dir"]) / gdac.INDEX_KEY
    text = (
        INDEX.read_text()
        + "aoml/9999999/profiles/R9999999_001.nc,20250115120000,-25.0,75.0,I,846,AO,\n"
    )
    index_path.write_bytes(gzip.compress(text.encode()))
    descriptor = {**cache, "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}
    with pytest.raises(Rejection, match="incomplete_inventory"):
        source(Repository(), Store(), descriptor).obtain(
            "/argo", parameters(inventory=True), "inventory_before"
        )
    # Outside the chunk's tile, or not an Indian Ocean row, it is not this chunk's concern.
    for line in (
        "aoml/9999999/profiles/R9999999_001.nc,20250115120000,-25.0,95.0,I,846,AO,\n",
        "aoml/9999999/profiles/R9999999_001.nc,20250115120000,-25.0,75.0,P,846,AO,\n",
        "aoml/9999999/profiles/R9999999_001.nc,20250116000000,-25.0,75.0,I,846,AO,\n",
    ):
        index_path.write_bytes(gzip.compress((INDEX.read_text() + line).encode()))
        descriptor = {**cache, "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()}
        assert source(Repository(), Store(), descriptor).obtain(
            "/argo", parameters(inventory=True), "inventory_before"
        )


def test_source_index_digest_mismatch_is_refused(cache):
    with pytest.raises(Rejection, match="gdac_index_changed"):
        source(Repository(), Store(), {**cache, "index_sha256": "0" * 64}).obtain(
            "/argo", parameters(inventory=True), "inventory_before"
        )


def test_source_count_and_duplicate_guards(cache, monkeypatch):
    monkeypatch.setattr(gdac, "MAX_FILE_BYTES", 1024)
    with pytest.raises(Rejection, match="decompressed_size_limit"):
        source(Repository(), Store(), cache).obtain("/argo", parameters(inventory=False), "profile")
    monkeypatch.undo()
    real = gdac.profiles_from_netcdf

    def doubled(*args, **kwargs):
        for document in real(*args, **kwargs):
            yield document
            yield document

    monkeypatch.setattr(gdac, "profiles_from_netcdf", doubled)
    with pytest.raises(Rejection, match="duplicate_inventory_id"):
        source(Repository(), Store(), cache).obtain("/argo", parameters(inventory=False), "profile")


def test_source_empty_selection_is_a_valid_empty_array(cache):
    tile = Tile(110, 20)
    repository = Repository(DAY, tile)
    landing = source(repository, Store(), cache).obtain(
        "/argo", gdac_parameters(PlannedChunk(DAY, tile), False), "profile"
    )
    assert (
        landing.payload == b"[]"
        and landing.manifest["sanitization"]["validation"]["documents"] == 0
    )


def test_fixture_script_excerpt_keeps_comments_header_and_box_edges(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gdac_fixtures", ROOT / "scripts/gdac_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    head = (
        "# Title\n# Date of update : 20261008\n"
        "file,date,latitude,longitude,ocean,profiler_type,institution,date_update\n"
    )
    rows = {
        "edge_sw": "a/1/profiles/R1_001.nc,20250101000000,-60.0,20.0,I,846,AO,20260101000000\n",
        "edge_ne": "a/2/profiles/R2_001.nc,20250331235959,30.0,120.0,P,846,AO,20260101000000\n",
        "late": "a/3/profiles/R3_001.nc,20250401000000,0,70,I,846,AO,20260101000000\n",
        "early": "a/4/profiles/R4_001.nc,20241231235959,0,70,I,846,AO,20260101000000\n",
        "north": "a/5/profiles/R5_001.nc,20250201000000,30.001,70,I,846,AO,20260101000000\n",
        "west": "a/6/profiles/R6_001.nc,20250201000000,0,19.999,I,846,AO,20260101000000\n",
        "blank": "a/7/profiles/R7_001.nc,,,,I,846,AO,\n",
        "inside": "a/8/profiles/D8_001D.nc,20250215120000,-12.5,75.25,A,846,AO,\n",
    }
    kept = module.excerpt(gzip.compress((head + "".join(rows.values())).encode())).decode()
    assert kept == head + rows["edge_sw"] + rows["edge_ne"] + rows["inside"]
    assert "index lines read" in capsys.readouterr().out


# --- migration -----------------------------------------------------------------------------


def test_migration_0014_relaxes_exactly_the_source_checks():
    sql = (ROOT / "infra/migrations/versions/0014_gdac_source.sql").read_text()
    for fragment in (
        "CHECK (source IN ('argovis','gdac'))",
        "(source = 'argovis' AND mapping_version = 'argovis-core-v1')",
        "(source = 'gdac' AND mapping_version = 'gdac-core-v1')",
        "[0-9a-f]{64}\\.(json|nc)$",
        "|| '.nc'",
        "CHECK (origin IN ('http','captured','replay','gdac'))",
        "CHECK (kind IN ('live','captured','replay','gdac'))",
        "p_origin NOT IN ('captured','replay','gdac')",
        "'gdac/core/'",
        "'/indian-ocean-v1/gdac-core-v1/scientific-json-v2'",
    ):
        assert fragment in sql, fragment
    assert sql.count("DROP CONSTRAINT") == 1 and "DROP TABLE" not in sql and "DELETE" not in sql
    assert sql.count("$migration$") == 2 and sql.count("$body$") == 4
    stub = (ROOT / "infra/migrations/versions/0014_gdac_source.py").read_text()
    assert 'down_revision = "0013_publication_v4"' in stub
