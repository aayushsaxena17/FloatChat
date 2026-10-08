"""Record stage1-v3 scientific outputs at a fixed commit as byte-identity goldens.

The execution model may change; these values may not. Regenerate only with an
ADR that changes a scientific rule, and record the commit in the file.
"""

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from floatchat_core.ingestion.argovis import map_profile  # noqa: E402
from floatchat_core.ingestion.json_stream import documents  # noqa: E402
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json  # noqa: E402
from floatchat_core.ingestion.parquet import write_snapshot  # noqa: E402
from floatchat_core.ingestion.raw import sanitize_raw  # noqa: E402
from floatchat_core.ingestion.spool import revision_json  # noqa: E402
from floatchat_core.ingestion.workflow import owner_slot  # noqa: E402
from stage1_perf_profile import BASES, synthetic_chunk  # noqa: E402

RECORDED = ROOT / "tests/fixtures/argovis/recorded"


def profile_record(profile):
    return {
        "content_hash": profile.content_hash,
        "canonical_sha256": hashlib.sha256(profile.canonical_bytes).hexdigest(),
        "canonical_bytes": len(profile.canonical_bytes),
        "levels": len(profile.levels),
        "levels_sha256": hashlib.sha256(
            json.dumps(list(profile.levels), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "identity": profile.identity,
        "revision": revision_json(profile.revision),
        "owner_slot": owner_slot(profile)
        if 20 <= float(profile.longitude.value or 0) <= 120
        else None,
    }


def mutations(document):
    """Labelled synthetic derivatives covering the numeric and QC edge rules."""
    names = document["data_info"][0]
    out = {}
    null = copy.deepcopy(document)
    for variable in ("pressure", "temperature", "salinity"):
        if variable in names:
            null["data"][names.index(variable)][1] = None
    out["core_null_level_1"] = null
    descending = copy.deepcopy(document)
    descending["profile_direction"] = "D"
    out["descending"] = descending
    nan = copy.deepcopy(document)
    if "temperature" in names:
        nan["data"][names.index("temperature")][0] = "NaN"
    out["nonfinite_temperature_0"] = nan
    qc = copy.deepcopy(document)
    if "pressure_argoqc" in names:
        qc["data"][names.index("pressure_argoqc")][0] = "X"
    out["unknown_pressure_qc_0"] = qc
    repeated = copy.deepcopy(document)
    if "pressure" in names and len(repeated["data"][names.index("pressure")]) > 2:
        column = repeated["data"][names.index("pressure")]
        column[2] = column[1]
    out["repeated_pressure_2"] = repeated
    fill = copy.deepcopy(document)
    if "salinity" in names:
        fill["data"][names.index("salinity")][0] = 99999
    out["argo_fill_salinity_0"] = fill
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "tests/fixtures/golden/stage1_v3_goldens.json"
    )
    args = parser.parse_args()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    goldens = {
        "kind": "stage1_v3_scientific_goldens",
        "commit": commit,
        "bundles": {},
        "synthetic": {},
    }
    for bundle in sorted(RECORDED.iterdir()):
        manifest = json.loads((bundle / "manifest.json").read_text())
        metadata = {}
        for response in manifest["responses"]:
            if response["role"] == "metadata":
                for item in decode_json((bundle / response["path"]).read_bytes()):
                    metadata[item["_id"]] = item
        entry = {"raw": {}, "profiles": {}, "mutations": {}}
        for response in manifest["responses"]:
            raw = (bundle / response["path"]).read_bytes()
            cleaned = sanitize_raw(raw, "synthetic-credential-sentinel")
            entry["raw"][response["path"]] = {
                "input_sha256": hashlib.sha256(raw).hexdigest(),
                "sanitized_sha256": hashlib.sha256(cleaned.payload).hexdigest(),
                "sanitized_bytes": len(cleaned.payload),
                "documents": sum(1 for _ in documents(raw)) if raw.lstrip().startswith(b"[") else 1,
            }
            if response["role"] != "profile":
                continue
            for document in documents(raw):
                profile = map_profile(document, metadata, CanonicalBudget())
                entry["profiles"][document["_id"]] = profile_record(profile)
                for label, mutated in mutations(document).items():
                    try:
                        entry["mutations"][document["_id"] + ":" + label] = profile_record(
                            map_profile(mutated, metadata, CanonicalBudget())
                        )
                    except Rejection as error:
                        entry["mutations"][document["_id"] + ":" + label] = {
                            "rejection": error.category
                        }
        goldens["bundles"][bundle.name] = entry
    for label, basis in BASES.items():
        payload, inventory, metadata = synthetic_chunk(3, 699, basis=basis)
        meta = {m["_id"]: m for m in decode_json(json.dumps(metadata).encode())}
        profiles = [map_profile(d, meta, CanonicalBudget()) for d in documents(payload)]
        work = Path("/tmp") / ("goldens-" + uuid.uuid4().hex)
        work.mkdir()
        file = work / "snapshot.parquet"
        verified = write_snapshot(
            file,
            [(uuid.UUID(int=index + 1), profile) for index, profile in enumerate(profiles)],
            deadline=time.monotonic() + 600,
        )
        goldens["synthetic"][f"{label}-3x699"] = {
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "sanitized_sha256": hashlib.sha256(sanitize_raw(payload).payload).hexdigest(),
            "profiles": [profile_record(p) for p in profiles],
            "snapshot": {
                k: verified[k] for k in ("schema_sha256", "rows", "profiles", "membership_sha256")
            },
        }
    args.output.write_text(json.dumps(goldens, indent=1, sort_keys=True) + "\n")
    print(args.output, commit)


if __name__ == "__main__":
    main()
