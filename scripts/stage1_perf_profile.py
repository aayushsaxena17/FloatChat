"""Offline per-stage CPU profile of one Stage 1 chunk on a labelled synthetic chunk.

No upstream, database or object-store access. Numbers are wall-clock seconds for
the pure Python/pyarrow stages; multiplicities per chunk come from reading
processor.py/landing.py/objects.py and are recorded, not inferred from timing.

Runs the stage1-v4 code path: in-memory ProfileSpool, write-once Parquet with Arrow
verification, the writer's own certificate for publish_verified (single PUT + stat), and
the slim candidate JSON plus typed level tables that replace the NDJSON staging file.
--audit passes audit=True to write_snapshot and publish_verified (row-by-row re-decode
and object read-back), the periodic-audit cost.
"""

import argparse
import copy
import cProfile
import hashlib
import io
import json
import pstats
import resource
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from floatchat_core.ingestion import parquet
from floatchat_core.ingestion.argovis import map_profile
from floatchat_core.ingestion.json_stream import documents
from floatchat_core.ingestion.landing import validate_raw
from floatchat_core.ingestion.numeric import CanonicalBudget, decode_json
from floatchat_core.ingestion.objects import publish_verified
from floatchat_core.ingestion.parquet import write_snapshot
from floatchat_core.ingestion.raw import sanitize_raw
from floatchat_core.ingestion.spool import ProfileSpool
from floatchat_core.ingestion.workflow import owner_slot

ROOT = Path(__file__).resolve().parents[1]
BASES = {
    "core6": ROOT
    / "tests/fixtures/argovis/recorded/6a8ffa52f6db4954b974c449e68c54bc",  # 1901094_109, 6 columns
    "bgc24": ROOT
    / "tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45",  # 2904014_040, 24 columns
}
BASIS = BASES["core6"]


class MemoryStore:
    def __init__(self):
        self.data = {}
        self.sha256 = {}

    def write_temporary(self, key, data, deadline):
        self.data[key] = data

    def read(self, key, max_bytes, deadline):
        return self.data[key]

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])

    def write_immutable(self, key, data, sha256_hex, deadline):
        self.data[key] = data
        self.sha256[key] = sha256_hex

    def stat(self, key, deadline):
        return {"bytes": len(self.data[key]), "sha256": self.sha256.get(key) or None}


def synthetic_chunk(profiles: int, levels: int, offset: int = 0, basis: Path = BASIS):
    """Tile the authentic 92-level core profile to `levels` and clone it `profiles` times."""
    authentic = json.loads((basis / "02-profile.json").read_bytes())[0]
    metadata = json.loads((basis / "04-metadata.json").read_bytes())
    columns = authentic["data"]
    tiled = [(column * (levels // len(column) + 1))[:levels] for column in columns]
    pressure = authentic["data_info"][0].index("pressure")
    # Keep pressure monotonic so flags match a realistic deep profile.
    step = 2000 / levels
    tiled[pressure] = [round(step * (index + 1), 1) for index in range(levels)]
    start = datetime(2025, 1, 1, tzinfo=UTC)
    docs = []
    for ordinal in range(profiles):
        value = copy.deepcopy(authentic)
        value["_id"] = f"synthetic-perf-{offset + ordinal:04d}"
        value["cycle_number"] = 5000 + offset + ordinal
        value["timestamp"] = (
            (start + timedelta(hours=1 + offset + ordinal)).isoformat().replace("+00:00", "Z")
        )
        value["geolocation"]["coordinates"] = [75.5, 15.5]
        value["data"] = tiled
        docs.append(value)
    payload = json.dumps(docs, separators=(",", ":")).encode()
    inventory = [{k: v for k, v in doc.items() if k not in ("data", "data_info")} for doc in docs]
    return payload, json.dumps(inventory, separators=(",", ":")).encode(), metadata


class Timer:
    def __init__(self):
        self.stages = {}
        self.profiles = {}

    def run(self, name, function, *, profile=False):
        started = time.perf_counter()
        cpu = time.process_time()
        if profile:
            profiler = cProfile.Profile()
            result = profiler.runcall(function)
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(14)
            self.profiles[name] = stream.getvalue()
        else:
            result = function()
        self.stages[name] = {
            "wall_s": round(time.perf_counter() - started, 3),
            "cpu_s": round(time.process_time() - cpu, 3),
        }
        return result


def profile_chunk(
    profiles: int,
    levels: int,
    work: Path,
    *,
    basis: str = "core6",
    cprofile: bool = False,
    audit: bool = False,
) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    timer = Timer()
    payload, inventory, metadata = synthetic_chunk(profiles, levels, basis=BASES[basis])
    meta_map = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    report = {
        "kind": "stage1_offline_chunk_cpu_profile",
        "scope": "Synthetic clone of authentic 1901094_109 core profile; CPU stages only, "
        "no HTTP/MinIO/PostgreSQL; stage1-v4 code path, multiplicities read from the "
        "stage1-v4 processor/landing/objects code (see git_head in the benchmark report)",
        "audit": audit,
        "basis": str(BASES[basis].relative_to(ROOT)),
        "basis_label": basis,
        "profiles": profiles,
        "levels_per_profile": levels,
        "raw_profile_payload_bytes": len(payload),
        "raw_inventory_payload_bytes": len(inventory),
        "python": sys.version.split()[0],
    }
    deadline = time.monotonic() + 3600

    # --- landing side (per raw landing of the profile role) ---
    cleaned = timer.run(
        "sanitize_raw(profile payload)", lambda: sanitize_raw(payload), profile=cprofile
    )
    timer.run("validate_raw(profile payload) x1", lambda: validate_raw(cleaned.payload))
    timer.run("sanitize_raw(inventory payload)", lambda: sanitize_raw(inventory))
    timer.run("validate_raw(inventory payload) x1", lambda: validate_raw(inventory))
    timer.run("sha256(profile payload)", lambda: hashlib.sha256(cleaned.payload).hexdigest())

    # --- decode (processor runs documents() over the profile payload several times) ---
    docs = timer.run(
        "documents() decode profile payload x1",
        lambda: list(documents(cleaned.payload)),
        profile=cprofile,
    )
    timer.run("documents() decode inventory payload x1", lambda: list(documents(inventory)))

    # --- map + canonical encode #1 ---
    budget = CanonicalBudget()
    mapped = timer.run(
        "map_profile + budget.encode (all profiles)",
        lambda: [map_profile(doc, meta_map, budget) for doc in docs],
        profile=cprofile,
    )
    canonical_bytes = sum(len(p.canonical_bytes) for p in mapped)
    report["canonical_bytes_per_profile"] = canonical_bytes // len(mapped)
    report["canonical_bytes_per_level"] = canonical_bytes // (len(mapped) * levels)
    report["canonical_bytes_chunk"] = canonical_bytes

    # --- spool add + prepare (v4: in-memory set, two batched lookups, no restore/re-encode) ---
    raw_id = uuid.uuid4()
    spool = ProfileSpool()
    timer.run("spool.add (all)", lambda: [spool.add(p, raw_id, i) for i, p in enumerate(mapped)])
    timer.run(
        "spool.prepare (restore+certify, no DB)",
        lambda: spool.prepare(lambda profiles: {}, lambda ids: {}),
        profile=cprofile,
    )
    slot = owner_slot(mapped[0])
    assert spool.changed_slots == {slot}
    timer.run("spool.membership(slot)", lambda: spool.membership(slot))

    # --- Parquet part write + Arrow-equality verification + storage comparison ---
    sub = {}
    original_verify, original_compare = parquet.verify_snapshot, parquet.storage_comparison

    def timed(name, function):
        def wrapper(*a, **k):
            started = time.perf_counter()
            try:
                return function(*a, **k)
            finally:
                sub[name] = sub.get(name, 0) + time.perf_counter() - started

        return wrapper

    parquet.verify_snapshot = timed("verify_snapshot", original_verify)
    parquet.storage_comparison = timed("storage_comparison", original_compare)
    original_scan = getattr(parquet, "_verify_written", None)
    if original_scan is not None:
        parquet._verify_written = timed("_verify_written", original_scan)
    file = work / (uuid.uuid4().hex + ".parquet")
    try:
        verified = timer.run(
            "write_snapshot (write+verify+storage_comparison)",
            lambda: write_snapshot(file, spool.profiles(slot), deadline=deadline, audit=audit),
            profile=cprofile,
        )
    finally:
        parquet.verify_snapshot, parquet.storage_comparison = original_verify, original_compare
        if original_scan is not None:
            parquet._verify_written = original_scan
    # v4: verify_snapshot runs only with audit=True; the always-on verification is the Arrow
    # equality scan (_verify_written, which contains the storage_comparison call).
    timer.stages["  write_snapshot: verify_snapshot (local read-back)"] = {
        "wall_s": round(sub.get("verify_snapshot", 0), 3)
    }
    timer.stages["  write_snapshot: storage_comparison (to_pandas)"] = {
        "wall_s": round(sub.get("storage_comparison", 0), 3)
    }
    timer.stages["  write_snapshot: writer loop (rows+ipc spill+parquet)"] = {
        "wall_s": round(
            timer.stages["write_snapshot (write+verify+storage_comparison)"]["wall_s"]
            - sub.get("verify_snapshot", 0)
            - sub.get("storage_comparison", 0),
            3,
        )
    }
    if original_scan is not None:
        timer.stages["  write_snapshot: _verify_written (Arrow equality scan, informational)"] = {
            "wall_s": round(sub.get("_verify_written", 0), 3)
        }
    report["parquet_bytes"] = file.stat().st_size
    report["parquet_rows"] = verified["rows"]
    timer.run("sha256(parquet file)", lambda: hashlib.sha256(file.read_bytes()).hexdigest())

    # --- publish_verified: the writer's certificate runs the light check once; one PUT + stat ---
    verifier = verified["certificate"]
    store = MemoryStore()
    intent = uuid.uuid4()
    timer.run(
        "publish_verified (certificate full verify + 2 light verifies; memory store)",
        lambda: publish_verified(
            store,
            file.read_bytes(),
            intent,
            verifier,
            deadline=deadline,
            temporary_key=f"tmp/{intent.hex}/{uuid.uuid4().hex}",
            audit=audit,
        ),
        profile=cprofile,
    )

    # --- staging: slim candidate JSON and typed Arrow level tables (the COPY inputs) ---
    # The binary COPY itself (to_pylist + write_row) is client CPU that this offline
    # profile does not time; stage1_perf_db_probe.py times it against a real server.
    report["staging_json_bytes"] = timer.run(
        "spool.candidates (slim JSON)",
        lambda: sum(
            len(json.dumps(candidate, separators=(",", ":"))) for candidate in spool.candidates()
        ),
    )
    report["staging_level_rows"] = timer.run(
        "spool.level_tables (Arrow)",
        lambda: sum(table.num_rows for table in spool.level_tables()),
    )
    assert report["staging_level_rows"] == verified["rows"]

    total = sum(v["wall_s"] for k, v in timer.stages.items() if not k.startswith("  "))
    report["stages"] = timer.stages
    report["sum_measured_wall_s"] = round(total, 3)
    # Counts for a serial landing + processing of one chunk, read from the code (stage1-v4):
    # landing.py:289 publish_verified -> objects.py:89 validate() once (audit adds the
    # read-back validate at objects.py:104); processor.py land() decodes the profile
    # payload in inventory_accounting (190), inventory (135) and the metadata loop (345),
    # publish() in inventory_accounting (190) and map (223); map() is the only canonical
    # encode (spool.prepare restores nothing; write_snapshot re-frames, never re-encodes).
    report["multiplicity_per_chunk_from_code"] = {
        "profile payload sanitize_raw": 1,
        "profile payload validate_raw (publish_verified validates once; audit adds 1)": 1,
        "profile payload documents() decode in processor "
        "(land: inventory_accounting, inventory, metadata loop; publish: "
        "inventory_accounting, map)": 5,
        "canonical encode per profile (map only; audit adds verify_snapshot's re-encode)": 1,
        "parquet row-by-row verify_snapshot re-decode (audit only)": 1 if audit else 0,
        "parquet Arrow-equality scan inside write_snapshot (always; inside its stage)": 1,
        "parquet light read (publish_verified validate with the writer's certificate)": (
            2 if audit else 1
        ),
        "spool.profiles(slot) restores (in-memory generator in v4, no decode)": 0,
    }
    report["stage_multiplicity"] = {
        "sanitize_raw(profile payload)": 1,
        "validate_raw(profile payload) x1": 1,
        "documents() decode profile payload x1": 5,
        "map_profile + budget.encode (all profiles)": 1,
        "spool.add (all)": 1,
        "spool.prepare (restore+certify, no DB)": 1,
        "spool.membership(slot)": 1,
        "write_snapshot (write+verify+storage_comparison)": 1,
        "publish_verified (certificate full verify + 2 light verifies; memory store)": 1,
        "spool.candidates (slim JSON)": 1,
        "spool.level_tables (Arrow)": 1,
    }
    report["stage_notes"] = {
        "spool.prepare (restore+certify, no DB)": "v4: two batched lookups (stubbed empty here) "
        "and identity resolution; nothing is restored or re-certified. Name kept so v3/v4 "
        "reports line up.",
        "write_snapshot (write+verify+storage_comparison)": "v4: verification is the Arrow "
        "equality scan inside the stage; the 'writer loop' sub-stage therefore includes it "
        "(see the informational _verify_written line); verify_snapshot is 0 unless --audit.",
        "publish_verified (certificate full verify + 2 light verifies; memory store)": "v4: "
        "the writer's certificate runs one light check; one write_immutable and one stat. "
        "Name kept for comparison with the v3 report.",
        "spool.candidates (slim JSON)": "replaces 'spool.write_candidates (NDJSON for COPY)'",
        "spool.level_tables (Arrow)": "typed level rows for the binary COPY; the COPY's "
        "client-side formatting is not timed here",
    }
    report["max_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    report["cprofile_top"] = timer.profiles
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    return report


def print_table(report: dict) -> None:
    for name, value in report["stages"].items():
        print(f"{value['wall_s']:9.3f}s  {name}")
    print("sum", round(report["sum_measured_wall_s"], 2), "s; rss", report["max_rss_mib"], "MiB")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=87)
    parser.add_argument("--levels", type=int, default=699)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--basis", choices=sorted(BASES), default="core6")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="audit=True for write_snapshot and publish_verified (row-by-row re-decode, read-back)",
    )
    args = parser.parse_args()
    report = profile_chunk(
        args.profiles,
        args.levels,
        args.work,
        basis=args.basis,
        cprofile=args.cprofile,
        audit=args.audit,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print_table(report)


if __name__ == "__main__":
    main()
