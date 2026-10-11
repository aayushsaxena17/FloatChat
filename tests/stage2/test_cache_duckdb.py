"""Part cache (ADR-0058) and the bounded DuckDB runner on synthetic Parquet, fully offline."""

import hashlib
import os
import time
from datetime import UTC, datetime

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from floatchat_core.query import compile_duckdb
from floatchat_core.query.cache import PartCache
from floatchat_core.query.compile_duckdb import PARTS_COLUMNS, DuckStatement
from floatchat_core.query.errors import QueryError
from floatchat_core.query.limits import QueryLimits
from floatchat_core.query.plan import validate_plan

LIMITS = QueryLimits()


def part(content: bytes) -> tuple[str, str, bytes]:
    digest = hashlib.sha256(content).hexdigest()
    return f"normalised/sha256/{digest}.parquet", digest, content


def cache_with(tmp_path, *parts, max_bytes=10**6):
    store = {key: content for key, _, content in parts}
    calls = []

    def fetch(key, byte_count):
        calls.append((key, byte_count))
        return store[key]

    return PartCache(tmp_path / "cache", max_bytes, fetch), calls


def test_cache_stores_a_verified_file_atomically_and_reuses_it(tmp_path):
    key, digest, content = part(b"parquet bytes" * 10)
    cache, calls = cache_with(tmp_path, (key, digest, content))
    path = cache.path(key, digest, len(content))
    assert path == tmp_path / "cache" / f"{digest}.parquet" and path.read_bytes() == content
    assert [item.name for item in (tmp_path / "cache").iterdir()] == [path.name]  # no .tmp left
    assert cache.size() == len(content)
    assert cache.path(key, digest, len(content)) == path and calls == [(key, len(content))]


def test_cache_refetches_a_file_with_the_wrong_size(tmp_path):
    key, digest, content = part(b"complete part")
    cache, calls = cache_with(tmp_path, (key, digest, content))
    path = cache.path(key, digest, len(content))
    path.write_bytes(b"trunc")
    assert cache.path(key, digest, len(content)).read_bytes() == content and len(calls) == 2


@pytest.mark.parametrize(
    "template",
    [
        "normalised/sha256/{short}.parquet",
        "normalised/sha256/{upper}.parquet",
        "normalised/sha256/{digest}.parq",
        "normalised/sha256/../{digest}.parquet",
        "normalised/sha256/{digest}.parquet/../x",
        "/normalised/sha256/{digest}.parquet",
        "raw/sha256/{digest}.parquet",
        "s3://bucket/normalised/sha256/{digest}.parquet",
        "normalised/sha256/{other}.parquet",
        "",
    ],
)
def test_cache_rejects_malformed_keys_and_wrong_digests_before_fetching(tmp_path, template):
    _, digest, content = part(b"x" * 20)
    other = hashlib.sha256(b"other").hexdigest()
    key = template.format(digest=digest, short=digest[:60], upper=digest.upper(), other=other)
    cache, calls = cache_with(tmp_path, (key, digest, content))
    with pytest.raises(QueryError) as caught:
        cache.path(key, digest, len(content))
    assert caught.value.code == "execution_failed" and caught.value.status == 502
    assert (not key or key not in str(caught.value.as_dict("c"))) and not calls
    assert list((tmp_path / "cache").iterdir()) == []


def test_cache_rejects_a_key_with_a_trailing_newline(tmp_path):
    key, digest, content = part(b"x" * 20)
    cache, _ = cache_with(tmp_path, (key + "\n", digest, content))
    with pytest.raises(QueryError):
        cache.path(key + "\n", digest, len(content))


@pytest.mark.parametrize("damage", ["bytes", "short", "long"])
def test_cache_refuses_bytes_that_fail_verification(tmp_path, damage):
    key, digest, content = part(b"the real part bytes")
    served = {"bytes": b"X" * len(content), "short": content[:-1], "long": content + b"!"}[damage]
    cache = PartCache(tmp_path / "cache", 10**6, lambda _key, _count: served)
    with pytest.raises(QueryError) as caught:
        cache.path(key, digest, len(content))
    assert caught.value.code == "execution_failed" and list((tmp_path / "cache").iterdir()) == []


def test_cache_evicts_the_least_recently_used_file_above_the_limit(tmp_path):
    parts = [part(bytes([index]) * 100) for index in range(3)]
    cache, calls = cache_with(tmp_path, *parts, max_bytes=250)
    paths = []
    for index, (key, digest, content) in enumerate(parts[:2]):
        paths.append(cache.path(key, digest, len(content)))
        os.utime(paths[-1], (1000 + index, 1000 + index))
    a, b = paths
    cache.path(parts[0][0], parts[0][1], 100)  # reuse bumps a to now, so b is the oldest
    c = cache.path(parts[2][0], parts[2][1], 100)  # 300 bytes > 250: evict b only
    assert a.exists() and c.exists() and not b.exists() and cache.size() == 200
    cache.path(parts[1][0], parts[1][1], 100)
    assert len(calls) == 4  # b had to be fetched again


def test_a_part_larger_than_the_cache_is_still_usable_after_path(tmp_path):
    key, digest, content = part(b"z" * 500)
    cache, _ = cache_with(tmp_path, (key, digest, content), max_bytes=100)
    assert cache.path(key, digest, len(content)).exists()


# ----- DuckDB runner -----------------------------------------------------------------------------
STRINGS = ("profile_id", "profile_hash", "profile_content")
SCHEMA = pa.schema(
    [
        pa.field(
            name,
            pa.string()
            if name in STRINGS or name.endswith(("_qc", "_data_mode"))
            else pa.float64(),
        )
        for name in (*PARTS_COLUMNS, "profile_content")
    ]
)
P1, P2, P3, P4 = (f"00000000-0000-4000-8000-00000000010{n}" for n in range(1, 5))
JAN = datetime(2025, 1, 10, tzinfo=UTC)
# (profile_id, hash, mode, [(pressure, temperature, salinity, temperature QC)])
LEVELS = [
    (P1, "h1", "R", [(5.0, 20.0, 35.0, "1"), (50.0, 18.0, 35.2, "2"), (500.0, 5.0, 34.8, "4")]),
    (P2, "h2", "D", [(5.0, 22.0, 35.1, "1"), (60.0, 21.0, 35.3, "1"), (400.0, 19.0, 34.9, "1")]),
    (P3, "h3", "R", [(5.0, 100.0, 40.0, "1")]),  # missing from the manifest
    (P2, "h2-old", "D", [(5.0, 99.0, 99.0, "1")]),  # a replaced version of P2
]


def parts_table(levels=LEVELS) -> pa.Table:
    columns = {field.name: [] for field in SCHEMA}
    for profile_id, digest, mode, rows in levels:
        for pressure, temperature, salinity, qc in rows:
            adjusted = mode != "R"
            columns["profile_id"].append(profile_id)
            columns["profile_hash"].append(digest)
            columns["profile_content"].append("{}")
            for variable, value, variable_qc in (
                ("pressure", pressure, "1"),
                ("temperature", temperature, qc),
                ("salinity", salinity, "1"),
            ):
                columns[variable].append(None if adjusted else value)
                columns[variable + "_adjusted"].append(value if adjusted else None)
                columns[variable + "_qc"].append(None if adjusted else variable_qc)
                columns[variable + "_adjusted_qc"].append(variable_qc if adjusted else None)
                columns[variable + "_data_mode"].append(mode)
    return pa.table(columns, schema=SCHEMA)


def cache_dir(tmp_path):
    directory = tmp_path / "cache"
    directory.mkdir(exist_ok=True)
    return directory


def write_part(tmp_path, levels=LEVELS):
    """A part written into the cache directory under its content address, as PartCache does."""
    import io

    buffer = io.BytesIO()
    pq.write_table(parts_table(levels), buffer)
    payload = buffer.getvalue()
    path = cache_dir(tmp_path) / f"{hashlib.sha256(payload).hexdigest()}.parquet"
    path.write_bytes(payload)
    return [path]


def engine(tmp_path, limits=LIMITS):
    return compile_duckdb.DuckEngine(cache_dir(tmp_path), limits)


def members(*profiles):
    rows = [
        {"profile_id": pid, "profile_hash": digest, "platform_number": platform, "observed_at": JAN}
        for pid, digest, platform in profiles
    ]
    manifest = {"slot": [{"profile_id": pid, "hash": digest} for pid, digest, _ in profiles]}
    return compile_duckdb.members_table(rows, manifest)


MEMBERS = (P1, "h1", "5900001"), (P2, "h2", "5900002")


def plan_for(operation, **changes):
    document = {
        "time_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-02-01T00:00:00Z"},
        "geography": {"kind": "named_region", "value": "Arabian Sea"},
        "variables": ["temperature"],
        "operation": {"kind": "aggregate", "metrics": ["mean", "count"]} | operation,
    }
    return validate_plan(document | changes)


def run(tmp_path, operation, *, levels=LEVELS, profiles=MEMBERS, **changes):
    statement = compile_duckdb.aggregate_statement(
        plan_for(operation, **changes), label="Arabian Sea", max_rows=100
    )
    paths = write_part(tmp_path, levels)
    return engine(tmp_path).run(statement, paths, members(*profiles), 10)


def test_science_ready_aggregates_and_the_manifest_semi_join(tmp_path):
    # P1: 20 and 18 (QC 4 level dropped); P2 adjusted: 22, 21, 19. P3 and P2's old hash excluded.
    measurement = run(tmp_path, {"unit": "measurement", "group_by": ["month"]})
    assert measurement == [("2025-01", pytest.approx(20.0), 5)]
    per_profile = run(tmp_path, {"unit": "profile", "group_by": ["month"]})
    assert per_profile == [("2025-01", pytest.approx((19.0 + 62 / 3) / 2), 2)]
    assert run(tmp_path, {"unit": "measurement"}) == [(pytest.approx(20.0), 5)]


def test_semi_join_drops_profiles_missing_from_the_manifest(tmp_path):
    only_p1 = run(tmp_path, {"unit": "measurement"}, profiles=[MEMBERS[0]])
    assert only_p1 == [(pytest.approx(19.0), 2)]
    everything = (*MEMBERS, (P3, "h3", "5900003"), (P2, "h2-old", "5900002"))
    with_rest = run(tmp_path, {"unit": "measurement"}, profiles=everything)
    assert with_rest == [(pytest.approx((20 + 18 + 22 + 21 + 19 + 100 + 99) / 7), 7)]
    assert run(tmp_path, {"unit": "measurement"}, profiles=[]) == [(None, 0)]
    table = members((P1, "h1", "5900001"))
    assert table.schema == compile_duckdb.MEMBERS_SCHEMA and table.num_rows == 1
    rows = [{"profile_id": P3, "profile_hash": "h3", "platform_number": "x", "observed_at": JAN}]
    assert (
        compile_duckdb.members_table(rows, {"slot": [{"profile_id": P1, "hash": "h1"}]}).num_rows
        == 0
    )


def test_mode_selected_depth_band_and_group_keys(tmp_path):
    selected = run(tmp_path, {"unit": "measurement"}, qc_policy="mode_selected")
    assert selected == [(pytest.approx((20 + 18 + 5 + 22 + 21 + 19) / 6), 6)]
    banded = run(tmp_path, {"unit": "measurement"}, depth_dbar={"min": 0, "max": 100})
    assert banded == [(pytest.approx((20 + 18 + 22 + 21) / 4), 4)]
    by_float = run(tmp_path, {"unit": "profile", "group_by": ["float"]})
    assert by_float == [("5900001", pytest.approx(19.0), 1), ("5900002", pytest.approx(62 / 3), 1)]
    by_bin = run(tmp_path, {"unit": "measurement", "group_by": ["depth_bin"], "depth_bin_size": 50})
    assert by_bin == [
        (0.0, pytest.approx(21.0), 2),
        (50.0, pytest.approx(19.5), 2),
        (400.0, 19.0, 1),
        (500.0, None, 0),  # selected pressure is good, temperature QC 4 is dropped
    ]
    labelled = run(tmp_path, {"unit": "profile", "group_by": ["region", "day"]})
    assert labelled[0][:2] == ("Arabian Sea", "2025-01-10") and len(labelled) == 1


@pytest.mark.parametrize("unit", ["profile", "measurement"])
@pytest.mark.parametrize(
    "keys",
    [[], ["month"], ["day"], ["profile"], ["float"], ["region"], ["month", "region", "float"]],
)
def test_every_metric_and_key_combination_executes(tmp_path, unit, keys):
    metrics = ["mean", "count", "min", "max", "stddev", "median"]
    operation = {"unit": unit, "group_by": keys, "metrics": metrics}
    rows = run(tmp_path, operation, variables=["temperature", "salinity"])
    assert rows and all(len(row) == len(keys) + 12 for row in rows)


def test_all_null_adjusted_columns_still_aggregate(tmp_path):
    originals = [LEVELS[0]]  # an original-mode part: every *_adjusted column is entirely null
    assert parts_table(originals).schema.field("pressure_adjusted").type == pa.float64()
    rows = run(tmp_path, {"unit": "measurement"}, levels=originals, profiles=[MEMBERS[0]])
    assert rows == [(pytest.approx(19.0), 2)]


EXTERNAL = [
    "SELECT * FROM read_parquet('{path}')",
    "SELECT * FROM read_csv('{path}')",
    "COPY (SELECT 1) TO '{path}.out'",
    "ATTACH '{path}.db' AS other",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access = true",
    "SET lock_configuration = false",
]
CONFIG = {
    "enable_external_access": "false",
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
    "memory_limit": "512MiB",
    "threads": "2",
}


def test_a_locked_connection_cannot_read_an_external_file(tmp_path):
    outside = tmp_path / "outside.parquet"
    pq.write_table(pa.table({"x": [1]}), outside)
    assert duckdb.connect(":memory:").execute(
        f"SELECT x FROM read_parquet('{outside}')"
    ).fetchall() == [(1,)]
    connection = duckdb.connect(database=":memory:", config=CONFIG)
    with pytest.raises(duckdb.Error):
        connection.execute(f"SELECT x FROM read_parquet('{outside}')")
    connection.close()


@pytest.mark.parametrize("template", EXTERNAL)
def test_run_refuses_external_access_and_reconfiguration(tmp_path, template):
    outside = tmp_path / "outside.parquet"
    pq.write_table(pa.table({"x": [1]}), outside)
    statement = DuckStatement(template.format(path=outside), {}, ())
    with pytest.raises(QueryError) as caught:
        engine(tmp_path).run(statement, write_part(tmp_path), members(*MEMBERS), 10)
    assert caught.value.code == "execution_failed" and str(outside) not in caught.value.text
    assert not (tmp_path / "outside.parquet.out").exists()


def test_run_interrupts_a_statement_that_cannot_finish(tmp_path):
    sql = "SELECT sum(a.range + b.range) FROM range(100000000) a, range(100000000) b"
    started = time.monotonic()
    with pytest.raises(QueryError) as caught:
        engine(tmp_path).run(
            DuckStatement(sql, {}, ()), write_part(tmp_path), members(*MEMBERS), 0.2
        )
    assert caught.value.code == "statement_timeout" and caught.value.status == 504
    assert time.monotonic() - started < 15


def test_run_maps_memory_exhaustion_to_cost_over_budget(tmp_path):
    sql = "SELECT string_agg(range::VARCHAR, ',') FROM range(100000000)"
    with pytest.raises(QueryError) as caught:
        engine(tmp_path, QueryLimits(duckdb_memory_mib=64)).run(
            DuckStatement(sql, {}, ()), write_part(tmp_path), members(*MEMBERS), 20
        )
    assert caught.value.code == "cost_over_budget"


def test_engine_reads_the_cache_and_nothing_else(tmp_path):
    duck = engine(tmp_path)
    inside = write_part(tmp_path)[0]
    assert duck.run(
        DuckStatement("SELECT count(*) FROM read_parquet($f)", {"f": [str(inside)]}, ()),
        [],
        members(*MEMBERS),
        10,
    ) == [(sum(len(rows) for *_head, rows in LEVELS),)]
    sibling = tmp_path / "cache-sibling"
    sibling.mkdir()
    for outside in (tmp_path / "outside.parquet", sibling / "x.parquet"):
        pq.write_table(pa.table({"x": [1]}), outside)
        statement = DuckStatement(f"SELECT * FROM read_parquet('{outside}')", {}, ())
        with pytest.raises(QueryError) as caught:
            duck.run(statement, [], members(*MEMBERS), 10)
        assert caught.value.code == "execution_failed"
    for setting in (
        "SET enable_external_access = true",
        f"SET allowed_directories = ['{tmp_path}/']",
        "SET threads = 1",
        "SET lock_configuration = false",
    ):
        with pytest.raises(QueryError):
            duck.run(DuckStatement(setting, {}, ()), [], members(*MEMBERS), 10)


def test_engine_only_passes_content_addressed_cache_files(tmp_path):
    duck = engine(tmp_path)
    template = compile_duckdb.aggregate_statement(
        plan_for({"unit": "measurement"}), label="Arabian Sea", max_rows=10
    )
    good = write_part(tmp_path)
    assert duck.verified_files(good) == [str(good[0].resolve())]
    renamed = cache_dir(tmp_path) / "part.parquet"
    renamed.write_bytes(good[0].read_bytes())
    elsewhere = tmp_path / good[0].name
    elsewhere.write_bytes(good[0].read_bytes())
    for bad in (renamed, elsewhere, cache_dir(tmp_path) / ".." / good[0].name):
        with pytest.raises(QueryError) as caught:
            duck.run(template, [bad], members(*MEMBERS), 10)
        assert caught.value.code == "internal_error"


def test_engine_is_reused_across_executions_and_threads(tmp_path):
    import threading

    duck = engine(tmp_path, QueryLimits(duckdb_concurrency=2))
    statement = compile_duckdb.aggregate_statement(
        plan_for({"unit": "measurement", "group_by": ["month"]}), label="Arabian Sea", max_rows=10
    )
    paths = write_part(tmp_path)
    expected = duck.run(statement, paths, members(*MEMBERS), 10)
    results, errors = [], []

    def work():
        try:
            results.append(duck.run(statement, paths, members(*MEMBERS), 10))
        except Exception as error:  # pragma: no cover - surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(6)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert not errors and results == [expected] * 6


def test_engine_bounds_concurrency_within_the_deadline(tmp_path):
    import threading

    duck = engine(tmp_path, QueryLimits(duckdb_concurrency=1))
    slow = DuckStatement(
        "SELECT sum(a.range + b.range) FROM range(100000000) a, range(100000000) b", {}, ()
    )
    blocker = threading.Thread(
        target=lambda: pytest.raises(QueryError, duck.run, slow, [], members(*MEMBERS), 1.5)
    )
    blocker.start()
    time.sleep(0.2)
    started = time.monotonic()
    with pytest.raises(QueryError) as caught:
        duck.run(DuckStatement("SELECT 1", {}, ()), [], members(*MEMBERS), 0.3)
    assert caught.value.code == "statement_timeout"
    assert time.monotonic() - started < 1.0
    blocker.join()
    assert duck.run(DuckStatement("SELECT 1", {}, ()), [], members(*MEMBERS), 5) == [(1,)]


def test_threads_default_to_every_visible_cpu(tmp_path):
    assert engine(tmp_path).threads == compile_duckdb.default_threads() >= 1
    assert engine(tmp_path, QueryLimits(duckdb_threads=3)).threads == 3


def test_members_from_columns_matches_members_table():
    rows = [
        {"profile_id": P1, "profile_hash": "h1", "platform_number": "5900001", "observed_at": JAN},
        {"profile_id": P3, "profile_hash": "h3", "platform_number": "5900003", "observed_at": JAN},
    ]
    manifest = {"slot": [{"profile_id": P1, "hash": "h1"}]}
    names = list(rows[0])
    tuples = [tuple(row.values()) for row in rows]
    assert compile_duckdb.members_from_columns(names, tuples, manifest) == (
        compile_duckdb.members_table(rows, manifest)
    )


def test_paths_fetches_each_part_once_in_order_and_times_out(tmp_path):
    import hashlib
    import threading
    import time

    from floatchat_core.query.cache import PartCache
    from floatchat_core.query.errors import QueryError

    payloads = {hashlib.sha256(bytes([i]) * 10).hexdigest(): bytes([i]) * 10 for i in range(5)}
    calls = []
    lock = threading.Lock()

    def fetch(key, byte_count):
        with lock:
            calls.append(key)
        return payloads[key.split("/")[-1].split(".")[0]]

    cache = PartCache(tmp_path / "cache", 10_000, fetch)
    items = [(f"normalised/sha256/{d}.parquet", d, 10) for d in payloads]
    paths = cache.paths(items, workers=3, deadline_seconds=5)
    assert [p.name for p in paths] == [d + ".parquet" for d in payloads]
    assert sorted(calls) == sorted(k for k, _, _ in items)
    assert cache.paths(items, workers=3, deadline_seconds=5) == paths and len(calls) == 5

    def slow(key, byte_count):
        time.sleep(0.5)
        return payloads[key.split("/")[-1].split(".")[0]]

    stalled = PartCache(tmp_path / "slow", 10_000, slow)
    with pytest.raises(QueryError) as failure:
        stalled.paths(items, workers=1, deadline_seconds=0.2)
    assert failure.value.code == "execution_failed"
