"""Offline per-stage CPU profile of one Stage 1 chunk on a labelled synthetic chunk.

No upstream, database or object-store access. Numbers are wall-clock seconds for
the pure Python/pyarrow stages; multiplicities per chunk come from reading
processor.py/landing.py/objects.py and are recorded, not inferred from timing.
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
from floatchat_core.ingestion.parquet import PublicationSnapshotVerifier, write_snapshot
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

    def write_temporary(self, key, data, deadline):
        self.data[key] = data

    def read(self, key, max_bytes, deadline):
        return self.data[key]

    def publish_if_absent(self, temporary, final, deadline):
        self.data.setdefault(final, self.data[temporary])


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=87)
    parser.add_argument("--levels", type=int, default=699)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--basis", choices=sorted(BASES), default="core6")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    timer = Timer()
    payload, inventory, metadata = synthetic_chunk(
        args.profiles, args.levels, basis=BASES[args.basis]
    )
    meta_map = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
    report = {
        "kind": "stage1_offline_chunk_cpu_profile",
        "scope": "Synthetic clone of authentic 1901094_109 core profile; CPU stages only, "
        "no HTTP/MinIO/PostgreSQL; multiplicities read from code at e1ba4f0",
        "basis": str(BASES[args.basis].relative_to(ROOT)),
        "basis_label": args.basis,
        "profiles": args.profiles,
        "levels_per_profile": args.levels,
        "raw_profile_payload_bytes": len(payload),
        "raw_inventory_payload_bytes": len(inventory),
        "python": sys.version.split()[0],
    }
    deadline = time.monotonic() + 3600

    # --- landing side (per raw landing of the profile role) ---
    cleaned = timer.run(
        "sanitize_raw(profile payload)", lambda: sanitize_raw(payload), profile=args.cprofile
    )
    timer.run("validate_raw(profile payload) x1", lambda: validate_raw(cleaned.payload))
    timer.run("sanitize_raw(inventory payload)", lambda: sanitize_raw(inventory))
    timer.run("validate_raw(inventory payload) x1", lambda: validate_raw(inventory))
    timer.run("sha256(profile payload)", lambda: hashlib.sha256(cleaned.payload).hexdigest())

    # --- decode (processor runs documents() over the profile payload several times) ---
    docs = timer.run(
        "documents() decode profile payload x1",
        lambda: list(documents(cleaned.payload)),
        profile=args.cprofile,
    )
    timer.run("documents() decode inventory payload x1", lambda: list(documents(inventory)))

    # --- map + canonical encode #1 ---
    budget = CanonicalBudget()
    profiles = timer.run(
        "map_profile + budget.encode (all profiles)",
        lambda: [map_profile(doc, meta_map, budget) for doc in docs],
        profile=args.cprofile,
    )
    canonical_bytes = sum(len(p.canonical_bytes) for p in profiles)
    report["canonical_bytes_per_profile"] = canonical_bytes // len(profiles)
    report["canonical_bytes_per_level"] = canonical_bytes // (len(profiles) * args.levels)
    report["canonical_bytes_chunk"] = canonical_bytes

    # --- spool add + prepare (restore certification = canonical encode #2) ---
    raw_id = uuid.uuid4()
    spool = ProfileSpool(args.work / (uuid.uuid4().hex + ".sqlite"))
    timer.run("spool.add (all)", lambda: [spool.add(p, raw_id, i) for i, p in enumerate(profiles)])
    timer.run(
        "spool.prepare (restore+certify, no DB)",
        lambda: spool.prepare(lambda p: (), identity_lookup=lambda p: (), load_science=None),
        profile=args.cprofile,
    )
    slot = owner_slot(profiles[0])
    assert spool.changed_slots == {slot}
    timer.run("spool.membership(slot)", lambda: spool.membership(slot))
    timer.run("spool.profiles(slot) re-read (receipts pass)", lambda: list(spool.profiles(slot)))

    # --- Parquet write + verify + storage comparison (canonical encode #3) ---
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
    file = args.work / (uuid.uuid4().hex + ".parquet")
    verified = timer.run(
        "write_snapshot (write+verify+storage_comparison)",
        lambda: write_snapshot(file, spool.profiles(slot), deadline=deadline),
        profile=args.cprofile,
    )
    parquet.verify_snapshot, parquet.storage_comparison = original_verify, original_compare
    timer.stages["  write_snapshot: verify_snapshot (local read-back)"] = {
        "wall_s": round(sub["verify_snapshot"], 3)
    }
    timer.stages["  write_snapshot: storage_comparison (to_pandas)"] = {
        "wall_s": round(sub["storage_comparison"], 3)
    }
    timer.stages["  write_snapshot: writer loop (rows+ipc spill+parquet)"] = {
        "wall_s": round(
            timer.stages["write_snapshot (write+verify+storage_comparison)"]["wall_s"]
            - sub["verify_snapshot"]
            - sub["storage_comparison"],
            3,
        )
    }
    report["parquet_bytes"] = file.stat().st_size
    report["parquet_rows"] = verified["rows"]
    digest = timer.run(
        "sha256(parquet file)", lambda: hashlib.sha256(file.read_bytes()).hexdigest()
    )

    # --- publish_verified: certificate first call = full verify (#4), then two light checks ---
    verifier = PublicationSnapshotVerifier(
        digest,
        file.stat().st_size,
        verified,
        deadline=deadline,
        budget_factory=lambda: __import__("contextlib").nullcontext(CanonicalBudget()),
    )
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
        ),
        profile=args.cprofile,
    )

    # --- staging NDJSON (candidate = canonical string + float levels, again) ---
    staged = args.work / (uuid.uuid4().hex + ".ndjson")
    timer.run("spool.write_candidates (NDJSON for COPY)", lambda: spool.write_candidates(staged))
    report["staging_ndjson_bytes"] = staged.stat().st_size
    spool.connection.close()

    total = sum(v["wall_s"] for k, v in timer.stages.items() if not k.startswith("  "))
    report["stages"] = timer.stages
    report["sum_measured_wall_s"] = round(total, 3)
    report["multiplicity_per_chunk_from_code"] = {
        "profile payload sanitize_raw": 1,
        "profile payload validate_raw (publish_verified: payload, temporary, final)": 3,
        "profile payload documents() decode in processor "
        "(inventory_accounting x2, inventory, metadata loop, map)": 5,
        "canonical encode per profile "
        "(map, spool certify, verify_snapshot in write_snapshot, certificate first payload)": 4,
        "parquet full read-back (write_snapshot verify, certificate first call)": 2,
        "parquet light read (certificate temporary+final)": 2,
        "spool.profiles(slot) restores (membership, write_snapshot, receipts)": 3,
    }
    report["max_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    report["cprofile_top"] = timer.profiles
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, value in timer.stages.items():
        print(f"{value['wall_s']:9.3f}s  {name}")
    print("sum", round(total, 2), "s; rss", report["max_rss_mib"], "MiB")


if __name__ == "__main__":
    main()
