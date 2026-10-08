"""GDAC wiring (G2): source routing in admission, workers, processor and CLI. All offline."""

import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from floatchat_core.ingestion import gdac
from floatchat_core.ingestion import processor as processor_module
from floatchat_core.ingestion.argovis import SOURCE_CONTRACT, policy_versions, source_of
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.planning import MAPPINGS, Interval, month_interval, timestamp
from floatchat_core.ingestion.processor import FAILURES, SPLITTABLE, Processor
from floatchat_core.ingestion.repository import OWNER_FUNCTIONS, Authority, Repository
from floatchat_core.ingestion.spool import ProfileSpool
from floatchat_core.ingestion.workflow import StoredState, slot_key
from floatchat_workers import cli, ingestion

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY = Authority(uuid.UUID(int=1), uuid.UUID(int=2), 1, 1)


# --- policy versions -------------------------------------------------------------------------


def test_policy_versions_per_source_agree_with_the_gdac_module():
    assert policy_versions("gdac-core-v1") == gdac.VERSIONS
    assert policy_versions()["mapping"] == "argovis-core-v1"
    assert source_of(policy_versions("gdac-core-v1")) == "gdac"
    assert source_of(policy_versions()) == "argovis"
    assert source_of(policy_versions("argovis-core-2.36.2-v1")) == "argovis"


class AdmissionCursor:
    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))

    def fetchone(self):
        return {"result": {"kind": "created", "run_id": str(uuid.uuid4())}}


def admission_repository(monkeypatch):
    from contextlib import contextmanager

    cursor = AdmissionCursor()
    repository = Repository.__new__(Repository)

    @contextmanager
    def transaction(**options):
        yield cursor

    monkeypatch.setattr(repository, "transaction", transaction, raising=False)
    return repository, cursor


@pytest.mark.parametrize(
    ("kind", "mapping"),
    [("gdac", "gdac-core-v1"), ("captured", "argovis-core-v1"), (None, "argovis-core-v1")],
)
def test_admit_persists_the_versions_of_the_input_source(monkeypatch, kind, mapping):
    repository, cursor = admission_repository(monkeypatch)
    interval = month_interval("2025-01", "2025-02")
    repository.admit(
        uuid.uuid4(),
        uuid.uuid4(),
        "acceptance",
        interval,
        {"execution_seconds": 600},
        input_kind=kind,
        descriptor={"kind": kind},
    )
    admit = cursor.calls[0][1]
    assert admit[8].obj == policy_versions("gdac-core-v1" if kind == "gdac" else SOURCE_CONTRACT)
    assert admit[8].obj["mapping"] == mapping
    if kind is not None:
        assert cursor.calls[1][1][1] == kind
    else:
        assert len(cursor.calls) == 1


def test_validate_replay_compares_against_the_source_contract(monkeypatch):
    interval = month_interval("2025-01", "2025-02")
    environment = uuid.uuid4()
    from floatchat_core.ingestion.planning import GEOMETRY_SHA256

    def row(versions):
        return {
            "closed": True,
            "state": "complete",
            "environment_id": environment,
            "mode": "acceptance",
            "requested_start": interval.start,
            "requested_end": interval.end,
            "policy_versions": versions,
            "geometry_sha256": GEOMETRY_SHA256,
        }

    repository = Repository.__new__(Repository)
    monkeypatch.setattr(repository, "run", lambda predecessor: row(gdac.VERSIONS), raising=False)
    repository.validate_replay(environment, "acceptance", interval, uuid.uuid4(), "gdac-core-v1")
    with pytest.raises(Rejection) as error:
        repository.validate_replay(environment, "acceptance", interval, uuid.uuid4())
    assert error.value.category == "invalid_replay_predecessor"


# --- logical keys ----------------------------------------------------------------------------


def test_slot_keys_follow_the_sql_owner_functions():
    when = datetime(2025, 1, 15, 3, tzinfo=UTC)
    assert (
        slot_key(when, Decimal("75.5"), Decimal("-12.25"))
        == "argovis/core/2025-01/70:-20/indian-ocean-v1/argovis-core-v1/scientific-json-v2"
    )
    assert (
        slot_key(when, Decimal("120"), Decimal("30"), "gdac")
        == "gdac/core/2025-01/110:20/indian-ocean-v1/gdac-core-v1/scientific-json-v2"
    )
    assert set(MAPPINGS) == set(OWNER_FUNCTIONS) == {"argovis", "gdac"}


def test_stored_state_and_spool_use_the_run_source():
    state = StoredState(
        "h", None, datetime(2025, 1, 15, tzinfo=UTC), Decimal("75.5"), Decimal("-12.25")
    )
    assert state.slot.startswith("argovis/core/")
    assert state.slot_of("gdac").startswith("gdac/core/2025-01/")
    assert ProfileSpool("gdac").source == "gdac" and ProfileSpool().source == "argovis"


# --- processor routing -----------------------------------------------------------------------


class ProcessorRepository:
    def __init__(self, kind):
        self.kind = kind

    def chunk(self, identifier):
        return {
            "requested_start": timestamp("2025-01-15T00:00:00Z"),
            "requested_end": timestamp("2025-01-16T00:00:00Z"),
            "tile": {"west": 70, "south": 10, "width": 10, "height": 10},
        }

    def run(self, identifier):
        return {
            "run_reference_time_utc": timestamp("2025-04-01T00:00:00Z"),
            "mode": "acceptance",
            "environment_id": uuid.uuid4(),
        }

    def input(self, run):
        return None if self.kind is None else {"kind": self.kind, "descriptor": {}}

    def canonical_budget(self, authority):
        from contextlib import nullcontext

        return nullcontext(object())

    def heartbeat(self, authority):
        pass


def routed_processor(monkeypatch, tmp_path, kind):
    repository = ProcessorRepository(kind)
    processor = Processor(
        repository,  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        AUTHORITY,
        tmp_path,
        deadline=time.monotonic() + 60,
    )
    path = tmp_path / "profile.json"
    path.write_bytes(json.dumps([{"_id": "x", "metadata": ["m"]}]).encode())
    processor.raw_paths["profile"] = path
    processor.outcomes = [{"outcome": "blocked_uncommitted"}]
    monkeypatch.setattr(processor, "metadata", lambda doc: {})

    def mapper(name):
        def route(*arguments):
            raise Rejection("routed_" + name)

        return route

    monkeypatch.setattr(processor_module, "gdac_map_profile", mapper("gdac"))
    monkeypatch.setattr(processor_module, "map_profile", mapper("argovis"))
    return processor


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("gdac", "routed_gdac"),
        ("captured", "routed_argovis"),
        ("live", "routed_argovis"),
        ("replay", "routed_argovis"),
        (None, "routed_argovis"),
    ],
)
def test_map_routes_by_the_run_input_kind(monkeypatch, tmp_path, kind, expected):
    processor = routed_processor(monkeypatch, tmp_path, kind)
    assert processor.source_name == ("gdac" if kind == "gdac" else "argovis")
    with pytest.raises(Rejection) as error, ProfileSpool(processor.source_name) as spool:
        processor.map(spool)
    assert error.value.category == expected


def test_gdac_categories_are_classified():
    configuration = {
        "gdac_file_size_limit",
        "gdac_index_changed",
        "invalid_gdac_descriptor",
        "unapproved_cache_path",
        "invalid_request_parameters",
        "invalid_request_role",
    }
    data = {
        "invalid_netcdf",
        "netcdf_size_limit",
        "unsupported_netcdf_packing",
        "invalid_index_line",
    }
    assert configuration <= FAILURES
    assert not (data & FAILURES) and not (data & SPLITTABLE)
    assert not (configuration & SPLITTABLE)
    # Download failures reuse the existing failed categories; limits split like Argovis.
    assert {"http_retry_exhausted", "http_retry_deadline", "upstream_transport_failure"} <= FAILURES
    assert {"profile_count_limit", "decompressed_size_limit"} <= SPLITTABLE
    assert "incomplete_inventory" not in FAILURES


# --- process_ticket --------------------------------------------------------------------------


class TicketRepository:
    def __init__(self, kind, versions, run, chunk):
        self.kind, self.versions, self.run_id, self.chunk_id = kind, versions, run, chunk
        self.transitions = []
        self.environment = uuid.uuid4()

    def chunk(self, identifier):
        return {"run_id": self.run_id, "state": "landed"}

    def start_worker(self, run, chunk, ticket):
        return AUTHORITY

    def run(self, identifier):
        return {
            "environment_id": self.environment,
            "policy_versions": self.versions,
            "work_deadline": datetime(2100, 1, 1, tzinfo=UTC),
        }

    def input(self, run):
        return {"kind": self.kind, "descriptor": {"kind": self.kind, "marker": 1}}

    def transition(self, authority, state, reason, evidence=None):
        self.transitions.append((state, reason))

    def close(self):
        pass


def ticket_setup(monkeypatch, tmp_path, kind, versions):
    run, chunk = uuid.uuid4(), uuid.uuid4()
    repository = TicketRepository(kind, versions, run, chunk)
    configuration = SimpleNamespace(
        repository=lambda: repository,
        environment=repository.environment,
        worker_memory_bytes=1 << 30,
        private=tmp_path,
        store=lambda: "store",
        application_commit="abc",
    )
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(ingestion, "bounded_worker_memory", lambda limit: None)
    monkeypatch.setattr(
        ingestion, "upstream_credential", lambda: pytest.fail("GDAC never loads the key")
    )
    built = {}

    class FakeGdac:
        def __init__(self, repository, store, authority, descriptor, **options):
            built["gdac"] = (descriptor, options)

    class FakeRecorded:
        def __init__(self, *arguments, **options):
            built["recorded"] = arguments

    class FakeProcessor:
        def __init__(self, repository, budget, store, source, authority, private, **options):
            built["source"] = source

        def land(self):
            return "landed_marker"

        def process(self):
            return "complete"

    monkeypatch.setattr(ingestion, "GdacSource", FakeGdac)
    monkeypatch.setattr(ingestion, "RecordedSource", FakeRecorded)
    monkeypatch.setattr(ingestion, "Processor", FakeProcessor)
    monkeypatch.setattr(ingestion, "hand_over", lambda repository, authority: None)
    return repository, built, run, chunk


def test_process_ticket_builds_a_gdac_source_for_gdac_runs(monkeypatch, tmp_path):
    repository, built, run, chunk = ticket_setup(
        monkeypatch, tmp_path, "gdac", policy_versions("gdac-core-v1")
    )
    assert (
        ingestion.process_ticket(str(run), str(chunk), str(uuid.uuid4()), "process") == "complete"
    )
    descriptor, options = built["gdac"]
    assert descriptor == {"kind": "gdac", "marker": 1}
    assert options["require_existing"] is True and options["application_commit"] == "abc"
    assert isinstance(built["source"], ingestion.GdacSource) and "recorded" not in built


def test_process_ticket_keeps_recorded_sources_for_argovis_runs(monkeypatch, tmp_path):
    repository, built, run, chunk = ticket_setup(
        monkeypatch, tmp_path, "captured", policy_versions()
    )
    assert (
        ingestion.process_ticket(str(run), str(chunk), str(uuid.uuid4()), "process") == "complete"
    )
    assert "recorded" in built and "gdac" not in built


@pytest.mark.parametrize(
    ("kind", "versions"),
    [("gdac", policy_versions()), ("captured", policy_versions("gdac-core-v1"))],
)
def test_process_ticket_checks_the_policy_of_the_runs_own_source(
    monkeypatch, tmp_path, kind, versions
):
    repository, built, run, chunk = ticket_setup(monkeypatch, tmp_path, kind, versions)
    assert ingestion.process_ticket(str(run), str(chunk), str(uuid.uuid4()), "process") == "failed"
    assert repository.transitions == [("failed", "unsupported_policy_versions")]
    assert not built


# --- CLI -------------------------------------------------------------------------------------


class CliRepository:
    def __init__(self):
        self.admitted = []

    def admit(self, *args, **kwargs):
        self.admitted.append((args, kwargs))
        return {"kind": "created", "run_id": str(uuid.uuid4())}

    def run(self, identifier):
        return {"closed": True}

    def validate_replay(self, *arguments):
        pass

    def close(self):
        pass


def cli_setup(monkeypatch, tmp_path):
    repository = CliRepository()
    configuration = SimpleNamespace(
        repository=lambda: repository, environment=uuid.uuid4(), private=tmp_path
    )
    monkeypatch.setattr(ingestion.Configuration, "load", lambda: configuration)
    monkeypatch.setattr(
        cli,
        "persisted_report",
        lambda *a: {"state": "complete", "cancellation_affected_unfinished_chunks": 0},
    )
    return repository


BASE = ["ingest", "--mode", "acceptance", "--from", "2025-01", "--to", "2025-02"]


def test_parser_source_defaults_to_argovis_and_accepts_gdac():
    parsed = cli.parser().parse_args([*BASE, "--source", "gdac", "--gdac-cache", "/tmp/cache"])
    assert parsed.source == "gdac" and parsed.gdac_cache == Path("/tmp/cache")
    assert cli.parser().parse_args([*BASE, "--live-opt-in"]).source == "argovis"
    with pytest.raises(SystemExit):
        cli.parser().parse_args([*BASE, "--source", "other"])


def test_ingest_gdac_prepares_the_cache_and_admits_the_descriptor(monkeypatch, tmp_path, capsys):
    repository = cli_setup(monkeypatch, tmp_path)
    prepared = []

    def prepare(cache, interval, deadline):
        prepared.append((cache, interval, deadline))
        return {"kind": "gdac", "cache_dir": str(cache), "index_sha256": "0" * 64}

    monkeypatch.setattr(gdac, "prepare_cache", prepare)
    assert cli.main([*BASE, "--source", "gdac"]) == 0
    ((cache, interval, deadline),) = prepared
    assert cache == tmp_path / "gdac-cache"
    assert interval == Interval(
        timestamp("2025-01-01T00:00:00Z"), timestamp("2025-03-01T00:00:00Z")
    )
    assert deadline > time.monotonic()
    ((_, kwargs),) = repository.admitted
    assert kwargs["input_kind"] == "gdac"
    assert kwargs["descriptor"]["cache_dir"] == str(cache)
    explicit = tmp_path / "elsewhere"
    assert cli.main([*BASE, "--source", "gdac", "--gdac-cache", str(explicit)]) == 0
    assert prepared[1][0] == explicit
    capsys.readouterr()


@pytest.mark.parametrize("extra", [["--live-opt-in"], ["--fixture-index", "x"]])
def test_ingest_gdac_refuses_argovis_inputs(monkeypatch, tmp_path, capsys, extra):
    repository = cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(gdac, "prepare_cache", lambda *a: pytest.fail("no download"))
    assert cli.main([*BASE, "--source", "gdac", *extra]) == 2
    assert capsys.readouterr().out.strip() == "unsupported_gdac_input"
    assert not repository.admitted


def test_ingest_argovis_still_requires_an_input(monkeypatch, tmp_path, capsys):
    repository = cli_setup(monkeypatch, tmp_path)
    assert cli.main(BASE) == 2
    assert capsys.readouterr().out.strip() == "missing_ingest_input"
    assert not repository.admitted


# --- migration 0015 (static; execution is covered by test_gdac_sql.py) ------------------------


def test_migration_0015_is_source_aware_and_chained():
    sql = (ROOT / "infra/migrations/versions/0015_gdac_wiring.sql").read_text()
    for fragment in (
        "CREATE FUNCTION app.run_source",
        "CREATE FUNCTION app.profile_slot",
        "CREATE OR REPLACE FUNCTION app.commit_publication",
        "CREATE OR REPLACE FUNCTION app.admit_run",
        "CREATE OR REPLACE FUNCTION app.ensure_slot",
        "CREATE OR REPLACE FUNCTION app.audit_slot_manifest",
        "CREATE OR REPLACE FUNCTION app.report_metrics_snapshot",
        "science->>'source'",
        "'gdac-core-v1' ELSE 'argovis-core-v1'",
        "app.gdac_owner_slot",
    ):
        assert fragment in sql, fragment
    assert (
        "source='argovis'" not in sql.split("CREATE OR REPLACE FUNCTION app.commit_publication")[1]
    )
    stub = (ROOT / "infra/migrations/versions/0015_gdac_wiring.py").read_text()
    assert 'down_revision = "0014_gdac_source"' in stub and 'revision = "0015_gdac_wiring"' in stub
