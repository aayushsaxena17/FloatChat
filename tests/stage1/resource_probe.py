"""Synthetic maximum-sampling-header format proof, in a 1 GiB offline container."""

import hashlib
import json
import resource
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
from floatchat_core.ingestion.parquet import ROW_GROUP_ROWS, WRITER_OPTIONS, write_snapshot


def main():
    root = Path("/test/tests/fixtures/argovis/recorded/6a8ffa52f6db4954b974c449e68c54bc")
    wire = json.loads((root / "02-profile.json").read_bytes())[0]
    metadata = {row["_id"]: row for row in decode_json((root / "04-metadata.json").read_bytes())}
    wire["vertical_sampling_scheme"] = "s" * 65536
    original_columns = wire["data"]
    cgroup_limit = int(Path("/sys/fs/cgroup/memory.max").read_text())
    assert cgroup_limit == 1024**3  # contract worker bound (ADR-0042)

    def profiles():
        for index in range(11):
            levels = 10000 if index < 10 else 1
            wire["_id"] = f"synthetic-resource-{index}"
            wire["cycle_number"] = index
            wire["data"] = [
                (column * (levels // len(column) + 1))[:levels] for column in original_columns
            ]
            profile = map_profile(
                decode_json(json.dumps(wire).encode()), metadata, CanonicalBudget()
            )
            yield uuid.UUID(int=index + 1), profile

    # ADR-0042: anonymous memory is sampled; ru_maxrss and memory.peak also count
    # file-backed pages (the read-back Parquet file) and are recorded, not judged.
    anon_peak = 0
    sampling = threading.Event()

    def sample_anon() -> None:
        nonlocal anon_peak
        while not sampling.is_set():
            for line in Path("/sys/fs/cgroup/memory.stat").read_text().splitlines():
                if line.startswith("anon "):
                    anon_peak = max(anon_peak, int(line.split()[1]))
            sampling.wait(0.02)

    sampler = threading.Thread(target=sample_anon, daemon=True)
    sampler.start()
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot.parquet"
        result = write_snapshot(path, profiles(), deadline=start + 400)
        file = pq.ParquetFile(path)
        groups = [file.metadata.row_group(i).num_rows for i in range(file.num_row_groups)]
        assert groups == [ROW_GROUP_ROWS, 1]
        assert all(
            file.metadata.row_group(i).column(j).compression == "ZSTD"
            for i in range(file.num_row_groups)
            for j in range(file.metadata.num_columns)
        )
        assert result["rows"] == 100001 and result["profiles"] == 11
        assert not list(Path(directory).glob("parquet-spill-*"))
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        peak = int(Path("/sys/fs/cgroup/memory.peak").read_text())
        events = dict(
            line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines()
        )
        sampling.set()
        sampler.join()
        assert anon_peak < 1024**3, (anon_peak, rss, peak)
        assert int(events["oom"]) == int(events["oom_kill"]) == 0
        print(
            json.dumps(
                {
                    "kind": "offline_cgroup_parquet_resource_proof",
                    "input": "synthetic derivative of authentic 1901094_109; 11 identities, "
                    "maximum 65536-byte sampling header",
                    "rows": result["rows"],
                    "profiles": result["profiles"],
                    "row_groups": groups,
                    "writer_options": WRITER_OPTIONS,
                    "pyarrow_version": pa.__version__,
                    "parquet_bytes": path.stat().st_size,
                    "parquet_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "verification": {k: v for k, v in result.items() if k != "certificate"},
                    "anonymous_peak_bytes": anon_peak,
                    "criterion": "ADR-0042: anonymous peak < 1 GiB and zero oom/oom_kill",
                    "peak_rss_bytes": rss,
                    "cgroup_memory_peak_bytes": peak,
                    "cgroup_limit_bytes": cgroup_limit,
                    "maximum_memory_budget_bytes": 1024**3,
                    "memory_events": events,
                    "seconds": time.monotonic() - start,
                    "scope": "Writer and read-back verifier in one memory-limited process; "
                    "not regional acceptance",
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
