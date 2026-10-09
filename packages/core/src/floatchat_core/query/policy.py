"""``qc-policy-v1`` (ADR-0057): value selection per variable and level, for both compilers.

Argovis delivers one variant per data mode: ``R`` fills the original columns, ``A``/``D`` the
adjusted ones (contract section 6). ``core-good-v1`` accepts QC ``1`` or ``2`` per value and never
substitutes adjusted QC for original QC. The policies below build on those two facts; the same
semantics are expressed once for SQLAlchemy and once for DuckDB SQL text with fixed identifiers.
"""

from typing import Any

from sqlalchemy import and_, case, null
from sqlalchemy.sql import ColumnElement

POLICY_VERSION = "qc-policy-v1"
GOOD_QC = ("1", "2")
ORIGINAL_MODES = ("R",)
ADJUSTED_MODES = ("A", "D")
POLICIES = {
    "science_ready": "the variant the data mode delivered (R original, A/D adjusted), kept only "
    "when that variant's QC is 1 or 2",
    "mode_selected": "the variant the data mode delivered, any QC; QC returned beside the value",
    "raw": "no selection; every stored column (profile reads only)",
}
AGGREGATION_UNITS = {
    "profile": "one value per profile (the mean of its selected levels in the depth band), "
    "metrics across profiles; count counts profiles",
    "measurement": "metrics over selected levels; count counts levels",
}


def describe(policy: str) -> dict[str, str]:
    return {"name": policy, "version": POLICY_VERSION, "description": POLICIES[policy]}


def sa_value(columns: Any, variable: str, policy: str) -> ColumnElement[Any]:
    """SQLAlchemy expression of the policy-selected value of ``variable``."""
    original = columns[variable]
    adjusted = columns[variable + "_adjusted"]
    mode = columns[variable + "_data_mode"]
    if policy == "science_ready":
        return case(
            (and_(mode.in_(ORIGINAL_MODES), columns[variable + "_qc"].in_(GOOD_QC)), original),
            (
                and_(mode.in_(ADJUSTED_MODES), columns[variable + "_adjusted_qc"].in_(GOOD_QC)),
                adjusted,
            ),
            else_=null(),
        )
    if policy == "mode_selected":
        return case(
            (mode.in_(ORIGINAL_MODES), original),
            (mode.in_(ADJUSTED_MODES), adjusted),
            else_=null(),
        )
    raise ValueError("raw has no selected value")


def sa_qc(columns: Any, variable: str) -> ColumnElement[Any]:
    """The QC code of the delivered variant (R original QC, A/D adjusted QC)."""
    mode = columns[variable + "_data_mode"]
    return case(
        (mode.in_(ORIGINAL_MODES), columns[variable + "_qc"]),
        (mode.in_(ADJUSTED_MODES), columns[variable + "_adjusted_qc"]),
        else_=null(),
    )


def _duck_list(values: tuple[str, ...]) -> str:
    return "(" + ", ".join("'" + value + "'" for value in values) + ")"


def duck_value(variable: str, policy: str, alias: str = "p") -> str:
    """DuckDB SQL text of the policy-selected value; identifiers are fixed, never from input."""
    if variable not in ("pressure", "temperature", "salinity"):
        raise ValueError("unknown variable")
    original = f"{alias}.{variable}"
    adjusted = f"{alias}.{variable}_adjusted"
    mode = f"{alias}.{variable}_data_mode"
    if policy == "science_ready":
        return (
            f"CASE WHEN {mode} IN {_duck_list(ORIGINAL_MODES)} AND {alias}.{variable}_qc IN "
            f"{_duck_list(GOOD_QC)} THEN {original} WHEN {mode} IN {_duck_list(ADJUSTED_MODES)} "
            f"AND {alias}.{variable}_adjusted_qc IN {_duck_list(GOOD_QC)} THEN {adjusted} "
            "ELSE NULL END"
        )
    if policy == "mode_selected":
        return (
            f"CASE WHEN {mode} IN {_duck_list(ORIGINAL_MODES)} THEN {original} WHEN {mode} IN "
            f"{_duck_list(ADJUSTED_MODES)} THEN {adjusted} ELSE NULL END"
        )
    raise ValueError("raw has no selected value")


def select_value(row: dict[str, Any], variable: str, policy: str) -> float | None:
    """Python reference implementation of the same rule, used by tests and the sanitiser."""
    mode = row.get(variable + "_data_mode")
    if mode in ORIGINAL_MODES:
        value, qc = row.get(variable), row.get(variable + "_qc")
    elif mode in ADJUSTED_MODES:
        value, qc = row.get(variable + "_adjusted"), row.get(variable + "_adjusted_qc")
    else:
        return None
    if policy == "science_ready" and qc not in GOOD_QC:
        return None
    if policy not in ("science_ready", "mode_selected"):
        raise ValueError("raw has no selected value")
    return value
