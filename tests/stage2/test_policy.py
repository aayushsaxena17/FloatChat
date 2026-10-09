"""``qc-policy-v1`` (ADR-0057): the Python rule, and the SQLAlchemy and DuckDB expressions of it."""

import itertools
import re

import duckdb
import pytest
from floatchat_core.query import policy
from floatchat_core.query.compile_sql import measurement
from sqlalchemy import Column, Float, Integer, MetaData, Table, Text, create_engine, select
from sqlalchemy.dialects.postgresql.base import PGDialect

MODES = ("R", "A", "D", None, "X")
QCS = ("1", "2", "3", "4", "9", None)
ORIGINAL, ADJUSTED = 10.0, 11.0
COLUMNS = (
    "temperature",
    "temperature_adjusted",
    "temperature_qc",
    "temperature_adjusted_qc",
    "temperature_data_mode",
)


def row(mode, original_qc, adjusted_qc, original=ORIGINAL, adjusted=ADJUSTED):
    return {
        "temperature": original,
        "temperature_adjusted": adjusted,
        "temperature_qc": original_qc,
        "temperature_adjusted_qc": adjusted_qc,
        "temperature_data_mode": mode,
    }


def grid():
    return [row(*combination) for combination in itertools.product(MODES, QCS, QCS)]


@pytest.mark.parametrize("mode", ["R", "A", "D"])
@pytest.mark.parametrize("qc", ["1", "2", "3", "4", "9", None])
def test_select_value_science_ready_keeps_only_good_qc_of_the_delivered_variant(mode, qc):
    # Only the delivered variant's QC counts; the other variant carries a good code as a decoy.
    original_mode = mode == "R"
    cell = row(mode, qc, "1") if original_mode else row(mode, "1", qc)
    expected = (ORIGINAL if original_mode else ADJUSTED) if qc in ("1", "2") else None
    assert policy.select_value(cell, "temperature", "science_ready") == expected


@pytest.mark.parametrize("mode", ["R", "A", "D"])
@pytest.mark.parametrize("qc", ["1", "2", "3", "4", "9", None])
def test_select_value_mode_selected_ignores_qc(mode, qc):
    cell = row(mode, qc, qc)
    expected = ORIGINAL if mode == "R" else ADJUSTED
    assert policy.select_value(cell, "temperature", "mode_selected") == expected


@pytest.mark.parametrize("policy_name", ["science_ready", "mode_selected"])
@pytest.mark.parametrize("mode", [None, "", "X", "r"])
def test_select_value_without_a_known_data_mode_is_null(policy_name, mode):
    assert policy.select_value(row(mode, "1", "1"), "temperature", policy_name) is None


def test_select_value_nulls_and_missing_columns():
    assert (
        policy.select_value(row("R", "1", "1", original=None), "temperature", "science_ready")
        is None
    )
    assert policy.select_value({}, "temperature", "science_ready") is None
    assert policy.select_value({"salinity_data_mode": "A"}, "temperature", "mode_selected") is None


@pytest.mark.parametrize("mode", ["R", "A", "D"])
@pytest.mark.parametrize("policy_name", ["raw", "gold"])
def test_select_value_raw_and_unknown_policies_raise(mode, policy_name):
    with pytest.raises(ValueError, match="raw has no selected value"):
        policy.select_value(row(mode, "1", "1"), "temperature", policy_name)


def test_describe_and_registries():
    assert set(policy.POLICIES) == {"science_ready", "mode_selected", "raw"}
    assert policy.describe("raw") == {
        "name": "raw",
        "version": "qc-policy-v1",
        "description": policy.POLICIES["raw"],
    }
    assert set(policy.AGGREGATION_UNITS) == {"profile", "measurement"}


def render(expression):
    return str(expression.compile(dialect=PGDialect(), compile_kwargs={"literal_binds": True}))


def referenced(text):
    return set(re.findall(r"query_measurement\.(\w+)", text))


@pytest.mark.parametrize("variable", ["pressure", "temperature", "salinity"])
def test_sa_value_renders_case_over_fixed_columns(variable):
    science = render(policy.sa_value(measurement.c, variable, "science_ready"))
    assert science.startswith("CASE WHEN") and science.endswith("ELSE NULL END")
    assert referenced(science) == {
        variable,
        variable + "_adjusted",
        variable + "_qc",
        variable + "_adjusted_qc",
        variable + "_data_mode",
    }
    assert "IN ('R')" in science and "IN ('A', 'D')" in science and "IN ('1', '2')" in science
    selected = render(policy.sa_value(measurement.c, variable, "mode_selected"))
    assert referenced(selected) == {variable, variable + "_adjusted", variable + "_data_mode"}
    quality = render(policy.sa_qc(measurement.c, variable))
    assert referenced(quality) == {
        variable + "_qc",
        variable + "_adjusted_qc",
        variable + "_data_mode",
    }


def test_sa_value_raw_raises():
    with pytest.raises(ValueError, match="raw has no selected value"):
        policy.sa_value(measurement.c, "temperature", "raw")


@pytest.mark.parametrize("policy_name", ["science_ready", "mode_selected"])
@pytest.mark.parametrize("variable", ["pressure", "temperature", "salinity"])
def test_duck_value_is_built_from_fixed_tokens_only(variable, policy_name):
    text = policy.duck_value(variable, policy_name)
    allowed = {"CASE", "WHEN", "THEN", "ELSE", "NULL", "END", "IN", "AND", "R", "A", "D", "1", "2"}
    prefix = "p." + variable
    allowed |= {prefix, prefix + "_adjusted", prefix + "_data_mode"}
    allowed |= {prefix + "_qc", prefix + "_adjusted_qc"}
    assert set(re.findall(r"[A-Za-z0-9_.]+", text)) <= allowed
    assert text.startswith("CASE WHEN") and text.endswith("ELSE NULL END")
    assert policy.duck_value(variable, policy_name, alias="q").count("q.") >= 4


@pytest.mark.parametrize(
    ("variable", "policy_name"),
    [
        ("temperature; DROP TABLE x", "science_ready"),
        ("temperature'", "mode_selected"),
        ("oxygen", "science_ready"),
        ("temperature", "raw"),
        ("temperature", "science_ready'; --"),
    ],
)
def test_duck_value_rejects_anything_outside_the_allow_lists(variable, policy_name):
    with pytest.raises(ValueError, match="unknown variable|raw has no selected value"):
        policy.duck_value(variable, policy_name)


@pytest.mark.parametrize("policy_name", ["science_ready", "mode_selected"])
def test_sqlalchemy_expressions_agree_with_the_reference(policy_name):
    metadata = MetaData()
    table = Table(
        "levels",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("temperature", Float),
        Column("temperature_adjusted", Float),
        Column("temperature_qc", Text),
        Column("temperature_adjusted_qc", Text),
        Column("temperature_data_mode", Text),
    )
    rows = grid()
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    statement = select(
        table.c.id,
        policy.sa_value(table.c, "temperature", policy_name),
        policy.sa_qc(table.c, "temperature"),
    ).order_by(table.c.id)
    with engine.begin() as connection:
        connection.execute(table.insert(), [dict(item, id=i) for i, item in enumerate(rows)])
        result = connection.execute(statement).all()
    assert len(result) == len(rows) == len(MODES) * len(QCS) ** 2
    for (_, value, quality), item in zip(result, rows, strict=True):
        assert value == policy.select_value(item, "temperature", policy_name)
        mode = item["temperature_data_mode"]
        delivered = {"R": "temperature_qc", "A": "temperature_adjusted_qc"}
        delivered["D"] = delivered["A"]
        assert quality == (item[delivered[mode]] if mode in delivered else None)


@pytest.mark.parametrize("policy_name", ["science_ready", "mode_selected"])
def test_duckdb_expression_agrees_with_the_reference(policy_name):
    rows = grid()
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE levels(id INTEGER, temperature DOUBLE, temperature_adjusted DOUBLE, "
        "temperature_qc VARCHAR, temperature_adjusted_qc VARCHAR, temperature_data_mode VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO levels VALUES (?, ?, ?, ?, ?, ?)",
        [(i, *(item[name] for name in COLUMNS)) for i, item in enumerate(rows)],
    )
    expression = policy.duck_value("temperature", policy_name)
    result = connection.execute(f"SELECT id, {expression} FROM levels p ORDER BY id").fetchall()
    connection.close()
    for (_, value), item in zip(result, rows, strict=True):
        assert value == policy.select_value(item, "temperature", policy_name)
