"""PostgreSQL compiler: SQLAlchemy Core over the ``app.query_*`` views (ADR-0058).

Identifiers come from the table definitions below and from closed allow-lists; every request
value is a bound parameter. No statement text is ever built from strings.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Uuid,
    and_,
    cast,
    column,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
    values,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.types import UserDefinedType

from .geography import ResolvedGeography
from .plan import (
    VARIABLES,
    AggregateOperation,
    DepthRange,
    NearestOperation,
    ProfilesOperation,
    QueryPlan,
)
from .policy import sa_qc, sa_value

SOURCE = "argovis"


class Geometry(UserDefinedType[Any]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "geometry"


class Geography(UserDefinedType[Any]):
    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "geography"


metadata = MetaData(schema="app")
environment = Table(
    "query_environment",
    metadata,
    Column("id", Uuid),
    Column("name", Text),
    Column("mode", Text),
    Column("disposable", Boolean),
    Column("reference_time", DateTime(timezone=True)),
    Column("completed_runs", BigInteger),
)
floats = Table(
    "query_float",
    metadata,
    Column("id", Uuid),
    Column("source", Text),
    Column("platform_number", Text),
)
profile = Table(
    "query_profile",
    metadata,
    Column("id", Uuid),
    Column("source", Text),
    Column("source_profile_id", Text),
    Column("float_id", Uuid),
    Column("platform_number", Text),
    Column("cycle_number", BigInteger),
    Column("direction", Text),
    Column("observed_at", DateTime(timezone=True)),
    Column("observation_month", Date),
    Column("position", Geometry),
    Column("level_count", Integer),
    Column("content_hash", Text),
    Column("last_scientific_run_id", Uuid),
)
_measurement_columns: list[Column[Any]] = [
    Column("observation_month", Date),
    Column("profile_id", Uuid),
    Column("level_index", Integer),
]
for _variable in VARIABLES:
    _measurement_columns += [
        Column(_variable, Float),
        Column(_variable + "_adjusted", Float),
        Column(_variable + "_qc", Text),
        Column(_variable + "_adjusted_qc", Text),
        Column(_variable + "_error", Float),
        Column(_variable + "_original_error", Float),
        Column(_variable + "_unit", Text),
        Column(_variable + "_data_mode", Text),
    ]
measurement = Table("query_measurement", metadata, *_measurement_columns)
slot = Table(
    "query_slot",
    metadata,
    Column("environment_id", Uuid),
    Column("logical_key", Text),
    Column("observation_month", Date),
    Column("tile_key", Text),
    Column("slot_version", BigInteger),
    Column("membership_manifest", JSONB),
)
partition = Table(
    "query_partition",
    metadata,
    Column("id", Uuid),
    Column("environment_id", Uuid),
    Column("logical_key", Text),
    Column("generation", BigInteger),
    Column("slot_version", BigInteger),
    Column("kind", Text),
    Column("part_ordinal", Integer),
    Column("object_key", Text),
    Column("sha256", Text),
    Column("bytes", BigInteger),
    Column("row_count", BigInteger),
    Column("profile_count", Integer),
    Column("schema_sha256", Text),
    Column("geometry_version", Text),
    Column("versions", JSONB),
    Column("verified_at", DateTime(timezone=True)),
    Column("committed_at", DateTime(timezone=True)),
)
receipt = Table(
    "query_coverage_receipt",
    metadata,
    Column("id", Uuid),
    Column("environment_id", Uuid),
    Column("logical_key", Text),
    Column("requested_start", DateTime(timezone=True)),
    Column("requested_end", DateTime(timezone=True)),
    Column("slot_version", BigInteger),
    Column("fetch_disposition", Text),
    Column("stored_disposition", Text),
    Column("committed_at", DateTime(timezone=True)),
    Column("tile", JSONB),
    Column("observation_month", Date),
)
region = Table(
    "named_region",
    metadata,
    Column("name", Text),
    Column("version", Text),
    Column("kind", Text),
    Column("source", Text),
    Column("source_id", Text),
    Column("citation", Text),
    Column("simplify_tolerance_deg", Numeric),
    Column("clipped", Boolean),
    Column("wkt", Text),
    Column("sha256", Text),
    Column("geometry", Geometry),
    Column("bbox_west", Float),
    Column("bbox_south", Float),
    Column("bbox_east", Float),
    Column("bbox_north", Float),
    Column("is_current", Boolean),
)

METRIC_NAMES = ("mean", "count", "min", "max", "stddev", "median")


def _geography(expression: ColumnElement[Any]) -> ColumnElement[Any]:
    return cast(expression, Geography())


def _point(longitude: float, latitude: float) -> ColumnElement[Any]:
    return _geography(func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326))


def spatial_predicate(geography: ResolvedGeography) -> ColumnElement[Any]:
    """Planar ``ST_Covers`` membership (the Stage 1 rule) or a geodesic ``ST_DWithin``."""
    if geography.kind == "named_region":
        assert geography.region is not None
        return exists().where(
            and_(
                region.c.name == geography.region.name,
                region.c.version == geography.region.version,
                func.ST_Covers(region.c.geometry, profile.c.position),
            )
        )
    if geography.kind == "bbox":
        return or_(
            *[
                func.ST_Covers(func.ST_MakeEnvelope(w, s, e, n, 4326), profile.c.position)
                for w, s, e, n in geography.boxes
            ]
        )
    assert geography.point is not None and geography.radius_m is not None
    return func.ST_DWithin(
        _geography(profile.c.position), _point(*geography.point), geography.radius_m
    )


def time_predicate(start: datetime, end: datetime) -> ColumnElement[Any]:
    """Half-open interval ``start <= observed_at < end``."""
    return and_(profile.c.observed_at >= start, profile.c.observed_at < end)


def source_predicate() -> ColumnElement[Any]:
    return profile.c.source == SOURCE


def pressure_value(policy: str) -> ColumnElement[Any]:
    return sa_value(measurement.c, "pressure", "mode_selected" if policy == "raw" else policy)


def depth_predicate(depth: DepthRange, policy: str) -> ColumnElement[Any]:
    return pressure_value(policy).between(depth.min, depth.max)


def _level_join() -> ColumnElement[Any]:
    return and_(
        measurement.c.profile_id == profile.c.id,
        measurement.c.observation_month == profile.c.observation_month,
    )


def has_levels_in_depth(depth: DepthRange, policy: str) -> ColumnElement[Any]:
    return exists().where(and_(_level_join(), depth_predicate(depth, policy)))


def profile_columns() -> list[ColumnElement[Any]]:
    return [
        profile.c.id,
        profile.c.source,
        profile.c.source_profile_id,
        profile.c.platform_number,
        profile.c.cycle_number,
        profile.c.direction,
        profile.c.observed_at,
        profile.c.observation_month,
        func.ST_X(profile.c.position).label("longitude"),
        func.ST_Y(profile.c.position).label("latitude"),
        profile.c.level_count,
        profile.c.content_hash,
        profile.c.last_scientific_run_id,
    ]


def _base_predicates(
    plan: QueryPlan, geography: ResolvedGeography, *, levels: bool
) -> list[ColumnElement[Any]]:
    predicates = [
        source_predicate(),
        time_predicate(plan.time_range.start, plan.time_range.end),
        spatial_predicate(geography),
    ]
    if plan.depth_dbar is not None:
        predicates.append(
            depth_predicate(plan.depth_dbar, plan.qc_policy)
            if levels
            else has_levels_in_depth(plan.depth_dbar, plan.qc_policy)
        )
    return predicates


def profiles_statement(
    plan: QueryPlan,
    geography: ResolvedGeography,
    *,
    limit: int,
    after: tuple[datetime, str] | None = None,
) -> Select[Any]:
    """Profile headers newest first with keyset pagination on ``(observed_at, id)``."""
    assert isinstance(plan.operation, ProfilesOperation)
    statement = select(*profile_columns()).where(*_base_predicates(plan, geography, levels=False))
    if after is not None:
        statement = statement.where(
            tuple_(profile.c.observed_at, profile.c.id)
            < tuple_(literal(after[0]), literal(uuid.UUID(after[1])))
        )
    return statement.order_by(profile.c.observed_at.desc(), profile.c.id.desc()).limit(limit + 1)


def nearest_statement(plan: QueryPlan, geography: ResolvedGeography) -> Select[Any]:
    """Indexed ``ST_DWithin`` prefilter, geodesic ``ST_Distance`` ordering (PRD section 9.4)."""
    assert isinstance(plan.operation, NearestOperation)
    operation = plan.operation
    point = _point(operation.longitude, operation.latitude)
    distance = func.ST_Distance(_geography(profile.c.position), point).label("distance_m")
    predicates = [
        source_predicate(),
        time_predicate(plan.time_range.start, plan.time_range.end),
        func.ST_DWithin(_geography(profile.c.position), point, operation.radius_km * 1000.0),
    ]
    if plan.depth_dbar is not None:
        predicates.append(has_levels_in_depth(plan.depth_dbar, plan.qc_policy))
    return (
        select(*profile_columns(), distance)
        .where(*predicates)
        .order_by(distance, profile.c.id)
        .limit(operation.k)
    )


def _key_expression(
    key: str, policy: str, depth_bin_size: int | None, label: str
) -> ColumnElement[Any]:
    expression: ColumnElement[Any]
    if key == "month":
        expression = func.to_char(func.timezone("UTC", profile.c.observed_at), "YYYY-MM")
    elif key == "day":
        expression = func.to_char(func.timezone("UTC", profile.c.observed_at), "YYYY-MM-DD")
    elif key == "profile":
        expression = cast(profile.c.id, Text)
    elif key == "float":
        expression = profile.c.platform_number
    elif key == "depth_bin":
        assert depth_bin_size is not None
        expression = func.floor(pressure_value(policy) / depth_bin_size) * depth_bin_size
    elif key == "region":
        expression = literal(label)
    else:
        raise ValueError("unknown group key")
    return expression


def _metric(name: str, value: ColumnElement[Any]) -> ColumnElement[Any]:
    result: ColumnElement[Any]
    if name == "mean":
        result = func.avg(value)
        return result
    if name == "count":
        return func.count(value)
    if name == "min":
        return func.min(value)
    if name == "max":
        return func.max(value)
    if name == "stddev":
        return func.stddev_samp(value)
    if name == "median":
        result = func.percentile_cont(0.5).within_group(value)
        return result
    raise ValueError("unknown metric")


def aggregate_statement(
    plan: QueryPlan, geography: ResolvedGeography, *, max_rows: int
) -> Select[Any]:
    """Grouped metrics over policy-selected values; ``unit`` chooses levels or profiles."""
    assert isinstance(plan.operation, AggregateOperation)
    operation = plan.operation
    keys = list(operation.group_by)
    key_expressions = {
        key: _key_expression(key, plan.qc_policy, operation.depth_bin_size, geography.label)
        for key in keys
    }
    variables = [v for v in plan.ordered_variables]
    joined = measurement.join(profile, _level_join())
    predicates = _base_predicates(plan, geography, levels=True)
    if operation.unit == "measurement":
        columns: list[ColumnElement[Any]] = [key_expressions[key].label(key) for key in keys]
        for variable in variables:
            value = sa_value(measurement.c, variable, plan.qc_policy)
            for metric in operation.metrics:
                columns.append(_metric(metric, value).label(f"{variable}_{metric}"))
        statement = select(*columns).select_from(joined).where(*predicates)
        grouped = [key for key in keys if key != "region"]  # a constant label is not grouped
        if grouped:
            statement = statement.group_by(*[key_expressions[key] for key in grouped])
            statement = statement.order_by(*[key_expressions[key] for key in grouped])
        return statement.limit(max_rows + 1)
    inner_columns: list[ColumnElement[Any]] = [profile.c.id.label("profile_id")]
    inner_columns += [key_expressions[key].label("key_" + key) for key in keys]
    inner_columns += [
        func.avg(sa_value(measurement.c, variable, plan.qc_policy)).label(variable + "_value")
        for variable in variables
    ]
    inner = (
        select(*inner_columns)
        .select_from(joined)
        .where(*predicates)
        .group_by(profile.c.id, *[key_expressions[key] for key in keys if key != "region"])
        .subquery("per_profile")
    )
    outer_columns: list[ColumnElement[Any]] = [inner.c["key_" + key].label(key) for key in keys]
    for variable in variables:
        for metric in operation.metrics:
            outer_columns.append(
                _metric(metric, inner.c[variable + "_value"]).label(f"{variable}_{metric}")
            )
    statement = select(*outer_columns)
    if keys:
        statement = statement.group_by(*[inner.c["key_" + key] for key in keys])
        statement = statement.order_by(*[inner.c["key_" + key] for key in keys])
    return statement.limit(max_rows + 1)


def _first_ordered(expression: ColumnElement[Any], order: Any) -> ColumnElement[Any]:
    """``(array_agg(expression ORDER BY order))[1]``: the value of the newest profile."""
    aggregate: Any = postgresql.array_agg(  # type: ignore[no-untyped-call]
        aggregate_order_by(expression, order)
    )
    first: ColumnElement[Any] = aggregate[1]
    return first


def floats_statement(
    start: datetime,
    end: datetime,
    geography: ResolvedGeography | None,
    *,
    limit: int,
    after: str | None = None,
    platform_number: str | None = None,
) -> Select[Any]:
    """Per-float statistics derived from profiles (plan section 5.2)."""
    predicates = [source_predicate(), time_predicate(start, end)]
    if geography is not None:
        predicates.append(spatial_predicate(geography))
    if platform_number is not None:
        predicates.append(profile.c.platform_number == platform_number)
    if after is not None:
        predicates.append(profile.c.platform_number > after)
    newest = profile.c.observed_at.desc()
    statement = (
        select(
            profile.c.platform_number,
            profile.c.source,
            func.count().label("profile_count"),
            func.min(profile.c.observed_at).label("first_observed_at"),
            func.max(profile.c.observed_at).label("last_observed_at"),
            func.min(profile.c.cycle_number).label("first_cycle"),
            func.max(profile.c.cycle_number).label("last_cycle"),
            _first_ordered(func.ST_X(profile.c.position), newest).label("last_longitude"),
            _first_ordered(func.ST_Y(profile.c.position), newest).label("last_latitude"),
        )
        .where(*predicates)
        .group_by(profile.c.platform_number, profile.c.source)
        .order_by(profile.c.platform_number)
    )
    return statement.limit(limit + 1)


def trajectory_statement(
    platform_number: str,
    start: datetime,
    end: datetime,
    *,
    limit: int,
    after: tuple[datetime, str] | None = None,
) -> Select[Any]:
    statement = select(
        profile.c.id,
        profile.c.cycle_number,
        profile.c.direction,
        profile.c.observed_at,
        func.ST_X(profile.c.position).label("longitude"),
        func.ST_Y(profile.c.position).label("latitude"),
    ).where(
        source_predicate(), profile.c.platform_number == platform_number, time_predicate(start, end)
    )
    if after is not None:
        statement = statement.where(
            tuple_(profile.c.observed_at, profile.c.id)
            < tuple_(literal(after[0]), literal(uuid.UUID(after[1])))
        )
    return statement.order_by(profile.c.observed_at.desc(), profile.c.id.desc()).limit(limit + 1)


def profile_statement(profile_id: uuid.UUID) -> Select[Any]:
    return select(*profile_columns()).where(source_predicate(), profile.c.id == profile_id)


def levels_statement(
    profile_id: uuid.UUID,
    observation_month: Any,
    *,
    policy: str,
    depth: DepthRange | None,
    limit: int,
) -> Select[Any]:
    """Levels of one profile: policy-selected values with QC and mode, or every raw column."""
    columns: list[ColumnElement[Any]] = [measurement.c.level_index]
    for variable in VARIABLES:
        if policy == "raw":
            for suffix in (
                "",
                "_adjusted",
                "_qc",
                "_adjusted_qc",
                "_error",
                "_original_error",
                "_unit",
                "_data_mode",
            ):
                columns.append(measurement.c[variable + suffix])
        else:
            columns.append(sa_value(measurement.c, variable, policy).label(variable))
            columns.append(sa_qc(measurement.c, variable).label(variable + "_qc"))
            columns.append(measurement.c[variable + "_data_mode"])
            columns.append(measurement.c[variable + "_unit"])
    predicates = [
        measurement.c.profile_id == profile_id,
        measurement.c.observation_month == observation_month,
    ]
    if depth is not None:
        predicates.append(depth_predicate(depth, policy))
    return select(*columns).where(*predicates).order_by(measurement.c.level_index).limit(limit)


def environment_statement() -> Select[Any]:
    return select(environment)


def regions_statement() -> Select[Any]:
    return select(
        region.c.name,
        region.c.version,
        region.c.kind,
        region.c.source,
        region.c.source_id,
        region.c.citation,
        region.c.simplify_tolerance_deg,
        region.c.clipped,
        region.c.sha256,
        region.c.bbox_west,
        region.c.bbox_south,
        region.c.bbox_east,
        region.c.bbox_north,
    ).where(region.c.is_current)


def region_tiles_statement(name: str, version: str, tiles: list[tuple[int, int]]) -> Select[Any]:
    """The candidate tiles whose cell intersects the region polygon (one query, VALUES list)."""
    candidates = values(column("west", Integer), column("south", Integer), name="tiles").data(tiles)
    cell = func.ST_MakeEnvelope(
        candidates.c.west, candidates.c.south, candidates.c.west + 10, candidates.c.south + 10, 4326
    )
    return (
        select(candidates.c.west, candidates.c.south)
        .select_from(candidates)
        .where(
            exists().where(
                and_(
                    region.c.name == name,
                    region.c.version == version,
                    func.ST_Intersects(region.c.geometry, cell),
                )
            )
        )
        .order_by(candidates.c.west, candidates.c.south)
    )


def profile_slot_statement(
    plan: QueryPlan, geography: ResolvedGeography, logical_keys: list[str]
) -> Select[Any]:
    """Profiles of the selected slots that match the plan, for the DuckDB route (ADR-0058)."""
    predicates = _base_predicates(plan, geography, levels=False)
    return select(
        cast(profile.c.id, Text).label("profile_id"),
        profile.c.content_hash.label("profile_hash"),
        profile.c.platform_number,
        profile.c.observed_at,
        profile.c.observation_month,
    ).where(*predicates)


def render(statement: Select[Any]) -> str:
    """The parameterised statement text (placeholders only), for documentation and tests."""
    return str(statement.compile(dialect=PGDialect()))  # type: ignore[no-untyped-call]
