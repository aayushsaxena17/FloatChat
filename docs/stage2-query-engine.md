# Stage 2 query engine: compiled statements, explained

Every request becomes one validated `stage2-plan-v1` document (plan section 4), then application
code compiles it: never a second prompt, never request text in SQL. This page shows the statements
the two compilers emit for the PRD section 8.1 example, exactly as rendered by
`compile_sql.render()` and `compile_duckdb.aggregate_statement()` at the commit that wrote it
(`scripts/stage2_query_examples.py` regenerates it).

## The plan

```json
{
  "dataset": "core",
  "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
  "geography": {"kind": "named_region", "value": "Arabian Sea"},
  "depth_dbar": {"min": 0, "max": 100},
  "variables": ["temperature", "salinity"],
  "qc_policy": "science_ready",
  "operation": {"kind": "aggregate", "group_by": ["month"], "metrics": ["mean", "count"], "unit": "profile"},
  "presentation": {"kind": "line_chart"}
}
```

## PostgreSQL route (SQLAlchemy Core over the `app.query_*` views)

```sql
SELECT per_profile.key_month AS month, avg(per_profile.temperature_value) AS temperature_mean, count(per_profile.temperature_value) AS temperature_count, avg(per_profile.salinity_value) AS salinity_mean, count(per_profile.salinity_value) AS salinity_count 
FROM (SELECT app.query_profile.id AS profile_id, to_char(timezone(%(timezone_1)s, app.query_profile.observed_at), %(to_char_1)s) AS key_month, avg(CASE WHEN (app.query_measurement.temperature_data_mode IN (__[POSTCOMPILE_temperature_data_mode_1]) AND app.query_measurement.temperature_qc IN (__[POSTCOMPILE_temperature_qc_1])) THEN app.query_measurement.temperature WHEN (app.query_measurement.temperature_data_mode IN (__[POSTCOMPILE_temperature_data_mode_2]) AND app.query_measurement.temperature_adjusted_qc IN (__[POSTCOMPILE_temperature_adjusted_qc_1])) THEN app.query_measurement.temperature_adjusted ELSE NULL END) AS temperature_value, avg(CASE WHEN (app.query_measurement.salinity_data_mode IN (__[POSTCOMPILE_salinity_data_mode_1]) AND app.query_measurement.salinity_qc IN (__[POSTCOMPILE_salinity_qc_1])) THEN app.query_measurement.salinity WHEN (app.query_measurement.salinity_data_mode IN (__[POSTCOMPILE_salinity_data_mode_2]) AND app.query_measurement.salinity_adjusted_qc IN (__[POSTCOMPILE_salinity_adjusted_qc_1])) THEN app.query_measurement.salinity_adjusted ELSE NULL END) AS salinity_value 
FROM app.query_measurement JOIN app.query_profile ON app.query_measurement.profile_id = app.query_profile.id AND app.query_measurement.observation_month = app.query_profile.observation_month 
WHERE app.query_profile.source = %(source_1)s AND app.query_profile.observed_at >= %(observed_at_1)s AND app.query_profile.observed_at < %(observed_at_2)s AND (EXISTS (SELECT * 
FROM app.named_region 
WHERE app.named_region.name = %(name_1)s AND app.named_region.version = %(version_1)s AND ST_Covers(app.named_region.geometry, app.query_profile.position))) AND CASE WHEN (app.query_measurement.pressure_data_mode IN (__[POSTCOMPILE_pressure_data_mode_1]) AND app.query_measurement.pressure_qc IN (__[POSTCOMPILE_pressure_qc_1])) THEN app.query_measurement.pressure WHEN (app.query_measurement.pressure_data_mode IN (__[POSTCOMPILE_pressure_data_mode_2]) AND app.query_measurement.pressure_adjusted_qc IN (__[POSTCOMPILE_pressure_adjusted_qc_1])) THEN app.query_measurement.pressure_adjusted ELSE NULL END BETWEEN %(param_1)s AND %(param_2)s GROUP BY app.query_profile.id, to_char(timezone(%(timezone_1)s, app.query_profile.observed_at), %(to_char_1)s)) AS per_profile GROUP BY per_profile.key_month ORDER BY per_profile.key_month 
 LIMIT %(param_3)s
```

Reading it from the inside out:

1. `app.query_measurement` joined to `app.query_profile` on `(profile_id, observation_month)`:
   the composite key matches the monthly partitions of `app.core_measurement`, so PostgreSQL prunes
   to the three partitions of the request.
2. `source = %(source_1)s` binds the constant `argovis`: the GDAC population is never visible
   (ADR-0056).
3. `observed_at >= start AND observed_at < end`: a half-open UTC interval on the indexed column.
4. `EXISTS (SELECT ... FROM app.named_region WHERE name = ... AND version = ... AND
   ST_Covers(geometry, position))`: planar membership against the committed polygon (ADR-0060),
   the same rule Stage 1 used for ownership; the GiST index on `position` answers the bounding-box
   stage of `ST_Covers`.
5. The depth filter and every value go through `qc-policy-v1/science_ready` (ADR-0057): `CASE WHEN
   data_mode IN ('R') AND qc IN ('1','2') THEN original WHEN data_mode IN ('A','D') AND adjusted_qc
   IN ('1','2') THEN adjusted ELSE NULL END`. The `__[POSTCOMPILE_...]` markers are SQLAlchemy's
   expanding bound lists; the literal mode and QC codes come from the policy module, not the
   request.
6. `per_profile`: with `unit = profile` the inner query averages each profile's selected levels in
   the depth band and keys it by `to_char(timezone('UTC', observed_at), 'YYYY-MM')`; the outer
   query takes the mean across profiles and counts profiles. Dense profiles cannot dominate a
   monthly mean (PRD section 12.1).
7. `LIMIT %(param_1)s` is `max_rows + 1`, so an overflow is detected and answered as
   `result_too_large` instead of truncated.

Every `%(...)s` is a bound parameter; the role `floatchat_query` can only `SELECT` from the views
and `app.named_region`, under a 15 s statement timeout (ADR-0058).

## Nearest profiles (PRD section 9.4)

```sql
SELECT app.query_profile.id, app.query_profile.source, app.query_profile.source_profile_id, app.query_profile.platform_number, app.query_profile.cycle_number, app.query_profile.direction, app.query_profile.observed_at, app.query_profile.observation_month, ST_X(app.query_profile.position) AS longitude, ST_Y(app.query_profile.position) AS latitude, app.query_profile.level_count, app.query_profile.content_hash, app.query_profile.last_scientific_run_id, ST_Distance(CAST(app.query_profile.position AS geography), CAST(ST_SetSRID(ST_MakePoint(%(ST_MakePoint_1)s, %(ST_MakePoint_2)s), %(ST_SetSRID_1)s) AS geography)) AS distance_m 
FROM app.query_profile 
WHERE app.query_profile.source = %(source_1)s AND app.query_profile.observed_at >= %(observed_at_1)s AND app.query_profile.observed_at < %(observed_at_2)s AND ST_DWithin(CAST(app.query_profile.position AS geography), CAST(ST_SetSRID(ST_MakePoint(%(ST_MakePoint_1)s, %(ST_MakePoint_2)s), %(ST_SetSRID_1)s) AS geography), %(ST_DWithin_1)s) ORDER BY distance_m, app.query_profile.id 
 LIMIT %(param_1)s
```

`ST_DWithin` on `geography` uses the functional GiST index `profile_position_geog` created by
migration 0016; `ST_Distance` orders the survivors geodesically; `distance_m` is returned in
metres.

## DuckDB route (hot-tier aggregates over verified Parquet parts)

Named parameters: `{'row_limit': 50001, 'depth_min': 0.0, 'depth_max': 100.0}`

```sql
SELECT key_month AS month, avg(temperature_value) AS temperature_mean, count(temperature_value) AS temperature_count, avg(salinity_value) AS salinity_mean, count(salinity_value) AS salinity_count FROM (SELECT m.profile_id AS profile_id, strftime(m.observed_at, '%Y-%m') AS key_month, avg(CASE WHEN p.temperature_data_mode IN ('R') AND p.temperature_qc IN ('1', '2') THEN p.temperature WHEN p.temperature_data_mode IN ('A', 'D') AND p.temperature_adjusted_qc IN ('1', '2') THEN p.temperature_adjusted ELSE NULL END) AS temperature_value, avg(CASE WHEN p.salinity_data_mode IN ('R') AND p.salinity_qc IN ('1', '2') THEN p.salinity WHEN p.salinity_data_mode IN ('A', 'D') AND p.salinity_adjusted_qc IN ('1', '2') THEN p.salinity_adjusted ELSE NULL END) AS salinity_value FROM parts p JOIN members m ON p.profile_id = m.profile_id AND p.profile_hash = m.profile_hash WHERE m.profile_id IS NOT NULL AND (CASE WHEN p.pressure_data_mode IN ('R') AND p.pressure_qc IN ('1', '2') THEN p.pressure WHEN p.pressure_data_mode IN ('A', 'D') AND p.pressure_adjusted_qc IN ('1', '2') THEN p.pressure_adjusted ELSE NULL END) BETWEEN $depth_min AND $depth_max GROUP BY m.profile_id, strftime(m.observed_at, '%Y-%m')) per_profile GROUP BY key_month ORDER BY key_month LIMIT $row_limit
```

1. `parts` is a `pyarrow.dataset` over the verified local copies of the catalogue parts of every
   covered slot; pyarrow reads only the projected columns (never `profile_content`). DuckDB is
   opened with `enable_external_access = false`, no extension autoload and a locked configuration:
   it cannot open a path or a URL.
2. `members` holds the profiles PostgreSQL selected for the same plan (time, geography, source),
   intersected with the slot membership manifests: a row of a part is kept only if its
   `(profile_id, profile_hash)` is a current member (contract section 7.2, ADR-0051).
3. The value expressions are the same `qc-policy-v1` CASE rule as above; keys and limits are
   `$named` parameters.

On the seeded integration data and on the acceptance copy both routes return the same rows
(`tests/stage2/test_integration.py::test_aggregate_routes_agree_between_postgresql_and_duckdb`),
which is expected: the PostgreSQL rows and the Parquet parts are two outputs of one mapping call,
proven byte-identical by ADR-0053.
