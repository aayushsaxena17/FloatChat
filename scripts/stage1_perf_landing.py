"""Offline landing counts for package E: HTTP attempts, validate_raw calls, object I/O.

A synthetic multi-chunk run (shared floats across chunks) lands through the real
RequestOwner/RecordedSource with fake repository, store and transport, then reloads
every landing. The same scenario runs against three source trees in subprocesses:
the pre-change commit, that commit plus package E's three modules, and this worktree.
No network, database or object store; counts come from wrapping the real functions.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = Path("packages/core/src/floatchat_core/ingestion")
E_MODULES = ("transport.py", "landing.py", "source.py")
CHUNKS, FLOATS, PER_CHUNK = 12, 16, 5
# T (scientific eligibility, here in the past as in acceptance) is not the cache anchor:
# freshness counts from the run's actual creation time.
REFERENCE = datetime(2025, 4, 1, tzinfo=UTC)
CREATED = datetime(2026, 10, 8, 12, tzinfo=UTC)
ENVIRONMENT = uuid.UUID(int=1)


def pointers(chunk):
    return [f"float-{(chunk * 3 + step) % FLOATS}" for step in range(PER_CHUNK)]


def requests(chunk):
    selections = [
        ("/argo", {"id": f"chunk-{chunk}-{role}"}, role)
        for role in ("inventory_before", "profile", "inventory_after")
    ]
    return selections + [("/argo/meta", {"id": pointer}, "metadata") for pointer in pointers(chunk)]


def worker():
    """Run the scenario in this interpreter; the parent chose the source tree."""
    import time

    from floatchat_core.ingestion import landing, source, transport
    from floatchat_core.ingestion.argovis import policy_versions
    from floatchat_core.ingestion.numeric import Rejection
    from floatchat_core.ingestion.repository import Authority

    class Counters(dict):
        def __missing__(self, key):
            return 0

    class Store:
        def __init__(self, counters):
            self.data, self.counters = {}, counters

        def write_temporary(self, key, payload, deadline):
            self.counters["object_puts"] += 1
            self.data[key] = payload

        def publish_if_absent(self, temporary, final, deadline):
            self.counters["object_publishes"] += 1
            self.data.setdefault(final, self.data[temporary])

        def write_immutable(self, key, data, sha256_hex, deadline):
            self.counters["object_puts"] += 1
            self.data.setdefault(key, data)

        def stat(self, key, deadline):
            return {"bytes": len(self.data[key]), "sha256": None}

        def read(self, key, max_bytes, deadline):
            self.counters["object_reads"] += 1
            if key not in self.data:
                raise Rejection("object_missing")
            return self.data[key]

    class Repository:
        def __init__(self, counters):
            self.counters, self.created = counters, CREATED
            self.manifests, self.by_id, self.cache, self.pending = {}, {}, {}, {}

        def run(self, identifier):
            self.counters["run_row_reads"] += 1
            return {
                "environment_id": ENVIRONMENT,
                "run_reference_time_utc": REFERENCE,
                "created_at_actual_utc": self.created,
            }

        def verified_landing(self, authority, key):
            return self.manifests.get((authority.chunk, key))

        def http_reserve(self, authority, key, role, parameters):
            self.pending[(attempt := uuid.uuid4())] = (authority.chunk, key)
            return attempt, 1

        def recorded_reserve(self, authority, key, role, parameters, origin):
            self.counters[f"attempts_origin_{origin}"] += 1
            self.pending[(attempt := uuid.uuid4())] = (authority.chunk, key)
            return attempt

        def heartbeat(self, authority):
            pass

        def account_received(self, authority, attempt, count):
            pass

        @contextmanager
        def upstream_slot(self, authority, deadline, slot=1):
            yield

        def finish_attempt(
            self, authority, attempt, disposition, status=None, error=None, manifest=None
        ):
            if manifest:
                self.counters["manifests_recorded"] += 1
                row = {**manifest, "object_key": manifest["key"]}
                self.manifests[self.pending[attempt]] = row
                self.by_id[manifest["id"]] = row

        def metadata_cache_get(self, environment, pointer):
            self.counters["cache_reads"] += 1
            return self.cache.get((environment, pointer))

        def metadata_cache_put(self, environment, pointer, raw_manifest, run, retrieved_at):
            self.counters["cache_upserts"] += 1
            manifest = self.by_id[str(raw_manifest)]
            self.cache[(environment, pointer)] = {
                "environment_id": environment,
                "pointer": pointer,
                "raw_manifest_id": raw_manifest,
                "run_id": run,
                "retrieved_at": retrieved_at,
                "object_key": manifest["key"],
                "sha256": manifest["sha256"],
                "bytes": manifest["bytes"],
                "versions": manifest["versions"],
                "http_status": manifest["http_status"],
            }

    def payload(path, parameters):
        if path == "/argo/meta":
            return f'[{{"_id":"{parameters["id"]}","depth":1.50,"api_key":"removed"}}]'.encode()
        return f'[{{"_id":"{parameters["id"]}-profile","n":2.50}}]'.encode()

    @contextmanager
    def instrumented(counters):
        modules = [landing] + ([source] if hasattr(source, "validate_raw") else [])
        originals = [(module, module.validate_raw) for module in modules]
        for module, original in originals:

            def counted(data, original=original):
                counters["validate_raw_calls"] += 1
                return original(data)

            module.validate_raw = counted
        try:
            yield
        finally:
            for module, original in originals:
                module.validate_raw = original

    def owner(repository, store, authority, transport_function, originals, **kwargs):
        return landing.RequestOwner(
            repository,
            store,
            authority,
            deadline=time.monotonic() + 600,
            application_commit="offline-bench",
            enabled=lambda: True,
            credential=lambda: "synthetic-bench-sentinel",
            transport=transport_function,
            jitter=lambda: 0,
            originals=originals,
            **kwargs,
        )

    def live_run(repository, store, counters, originals, retrieved_at, chunks):
        def transport_function(path, parameters, credential, account, **kwargs):
            counters["http_attempts"] += 1
            counters[
                "http_attempts_metadata" if path == "/argo/meta" else "http_attempts_other"
            ] += 1
            data = payload(path, parameters)
            account(len(data))
            return transport.Response(data, len(data), retrieved_at(), {})

        authorities = {}
        for chunk in chunks:
            authorities[chunk] = Authority(uuid.uuid4(), uuid.uuid4(), 1, 1)
            current = owner(repository, store, authorities[chunk], transport_function, originals)
            for path, parameters, role in requests(chunk):
                current.obtain(path, parameters, role)
        return authorities

    def reload_run(repository, store, counters, originals, authorities):
        def refuse(*args, **kwargs):
            raise AssertionError("reload must not request")

        for chunk, authority in authorities.items():
            current = owner(repository, store, authority, refuse, originals, require_existing=True)
            for path, parameters, role in requests(chunk):
                current.obtain(path, parameters, role)

    def measure(name, function):
        counters = Counters()
        started = time.perf_counter()
        with instrumented(counters):
            function(counters)
        counters["wall_seconds"] = round(time.perf_counter() - started, 4)
        return {key: counters[key] for key in sorted(counters)}

    results = {}
    originals = Path(tempfile.mkdtemp(prefix="floatchat-bench-originals-"))

    def same_run(counters):
        repository, store = Repository(counters), Store(counters)
        # Every fetch happens after the run was created, as in any run.
        tick = iter(range(10**6))
        authorities = live_run(
            repository,
            store,
            counters,
            originals / "same",
            lambda: CREATED + timedelta(minutes=next(tick)),
            range(CHUNKS),
        )
        counters["phase_landing_validate_raw_calls"] = counters["validate_raw_calls"]
        reload_run(repository, store, counters, originals / "same", authorities)

    results["same_run"] = measure("same_run", same_run)

    def second_run(gap):
        def run(counters):
            # Run 1 fills the cache; run 2 is created `gap` later and is the one counted.
            first = Counters()
            repository, store = Repository(first), Store(first)
            tick = iter(range(10**6))
            live_run(
                repository,
                store,
                first,
                originals / f"first-{gap.days}",
                lambda: CREATED + timedelta(minutes=next(tick)),
                range(CHUNKS),
            )
            counters["first_run_http_attempts"] = first["http_attempts"]
            counters["first_run_validate_raw_calls"] = counters["validate_raw_calls"]
            counters["validate_raw_calls"] = 0
            repository.counters = store.counters = counters
            repository.created = CREATED + gap
            authorities = live_run(
                repository,
                store,
                counters,
                originals / f"second-{gap.days}",
                lambda: CREATED + gap + timedelta(minutes=next(tick)),
                range(CHUNKS),
            )
            counters["phase_landing_validate_raw_calls"] = counters["validate_raw_calls"]
            reload_run(repository, store, counters, originals / f"second-{gap.days}", authorities)

        return run

    results["second_run_within_30_days"] = measure("second_run", second_run(timedelta(days=20)))
    results["second_run_after_30_days"] = measure("stale_run", second_run(timedelta(days=45)))

    def fixtures(counters):
        directory = Path(tempfile.mkdtemp(prefix="floatchat-bench-fixture-"))
        entries = []
        for number in range(FLOATS):
            parameters = {"id": f"float-{number}"}
            data = payload("/argo/meta", parameters)
            (directory / f"m{number}.json").write_bytes(data)
            entries.append(
                {
                    "role": "metadata",
                    "path": "/argo/meta",
                    "parameters": parameters,
                    "file": f"m{number}.json",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "retrieved_at_utc": "2025-03-01T00:00:00+00:00",
                }
            )
        index = directory / "index.json"
        index.write_text(
            json.dumps(
                {
                    "kind": "synthetic_offline_chunk_fixture",
                    "versions": policy_versions(),
                    "responses": entries,
                }
            )
        )
        descriptor = {
            "fixture_index": str(index),
            "fixture_root": str(directory),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        }
        repository, store = Repository(counters), Store(counters)
        authorities = {}
        for chunk in range(CHUNKS):
            authorities[chunk] = Authority(uuid.uuid4(), uuid.uuid4(), 1, 1)
            recorded = source.RecordedSource(
                repository,
                store,
                authorities[chunk],
                descriptor,
                deadline=time.monotonic() + 600,
                application_commit="offline-bench",
            )
            for pointer in pointers(chunk):
                recorded.obtain("/argo/meta", {"id": pointer}, "metadata")
        counters["phase_landing_validate_raw_calls"] = counters["validate_raw_calls"]
        for chunk, authority in authorities.items():
            recorded = source.RecordedSource(
                repository,
                store,
                authority,
                descriptor,
                deadline=time.monotonic() + 600,
                application_commit="offline-bench",
                require_existing=True,
            )
            for pointer in pointers(chunk):
                recorded.obtain("/argo/meta", {"id": pointer}, "metadata")

    results["fixture_metadata_recorded_source"] = measure("fixtures", fixtures)
    print(
        json.dumps(
            {
                "module_files": {
                    "transport": transport.__file__,
                    "landing": landing.__file__,
                    "source": source.__file__,
                },
                "results": results,
            }
        )
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tree(source_root, label):
    environment = {**os.environ, "PYTHONPATH": str(source_root / "packages/core/src")}
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=source_root,
    )
    if completed.returncode:
        return {"label": label, "error": completed.stderr.strip().splitlines()[-1:]}
    output = json.loads(completed.stdout.strip().splitlines()[-1])
    imported = {name: path for name, path in output["module_files"].items()}
    expected = str((source_root / CORE).resolve())
    assert all(str(Path(path).resolve()).startswith(expected) for path in imported.values()), (
        label,
        imported,
    )
    return {"label": label, "results": output["results"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help="run the scenario in this process")
    parser.add_argument("--base", default="272508b")
    parser.add_argument("--output", default=str(ROOT / "reports/stage1-v4-bench-E.json"))
    arguments = parser.parse_args()
    if arguments.worker:
        worker()
        return
    with tempfile.TemporaryDirectory(prefix="floatchat-bench-trees-") as scratch:
        baseline = Path(scratch) / "baseline"
        baseline.mkdir()
        archive = subprocess.run(
            ["git", "-C", str(ROOT), "archive", arguments.base, "--", "packages/core/src"],
            capture_output=True,
            check=True,
        )
        subprocess.run(["tar", "-x", "-C", str(baseline)], input=archive.stdout, check=True)
        e_only = Path(scratch) / "e_only"
        subprocess.run(["cp", "-a", str(baseline), str(e_only)], check=True)
        for name in E_MODULES:
            (e_only / CORE / name).write_bytes((ROOT / CORE / name).read_bytes())
        trees = {
            "baseline": run_tree(baseline, "baseline"),
            "e_modules_on_baseline": run_tree(e_only, "e_modules_on_baseline"),
            "worktree": run_tree(ROOT, "worktree"),
        }
        hashes = {
            "baseline": {n: digest(baseline / CORE / n) for n in ("objects.py", *E_MODULES)},
            "e_modules_on_baseline": {
                n: digest(e_only / CORE / n) for n in ("objects.py", *E_MODULES)
            },
            "worktree": {n: digest(ROOT / CORE / n) for n in ("objects.py", *E_MODULES)},
        }
    report = {
        "kind": "stage1-v4-bench-E",
        "package": "E",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_commit": arguments.base,
        "scenario": {
            "chunks": CHUNKS,
            "distinct_floats": FLOATS,
            "metadata_requests_per_chunk": PER_CHUNK,
            "selection_requests_per_chunk": 3,
            "reference_time_utc": REFERENCE.isoformat(),
            "run_created_at_utc": CREATED.isoformat(),
            "transport": "fake; no network, database or object store",
        },
        "scenario_notes": {
            "counters": "validate_raw_calls covers landing plus the reload of every landing; "
            "phase_landing_validate_raw_calls is landing only; http_attempts counts transport "
            "calls; object_puts counts write_temporary/write_immutable",
            "same_run": "one run: every fetch is stamped after the run was created, so later "
            "chunks reuse earlier chunks' metadata; the reference time T (2025-04-01) does not "
            "enter the window",
            "second_run_within_30_days": "run 2 is created 20 days after run 1; first_run_* "
            "keys describe run 1, the other keys run 2",
            "second_run_after_30_days": "run 2 is created 45 days after run 1: run 1's entries "
            "are stale, run 2 refetches each float once and then reuses it",
            "fixture_metadata_recorded_source": "RecordedSource fixture path: no cache access",
            "objects_py": "identical hashes across trees mean publish_verified (package C) "
            "has not changed, so validate_raw still runs three times per landing",
        },
        "trees": trees,
        "source_sha256": hashes,
    }
    Path(arguments.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": arguments.output, "trees": list(trees)}))


if __name__ == "__main__":
    main()
