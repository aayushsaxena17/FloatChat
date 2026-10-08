"""Explicit opt-in, tiny official capture; no scientific ingestion or DB writes.

Original responses remain under ~/private/argovis-captures, outside Git. Only a
complete, sanitized, scanned bundle is copied into the fresh fixture directory.
The script never reads or imports a preserved checkout and never prints secrets.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion.argovis import map_profile, policy_versions
from floatchat_core.ingestion.numeric import MIB, CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.raw import sanitize_raw
from floatchat_core.ingestion.transport import BASE, HTTPFailure, fetch, retry_delay

ROOT = Path(__file__).resolve().parents[1]


class SafeHTTPDiagnostic(Rejection):
    """Only allowlisted scalar context survives the transport failure boundary."""

    def __init__(self, failure: HTTPFailure, profile_id: str, role: str) -> None:
        super().__init__("upstream_http_status")
        if type(failure.status) is not int or not 100 <= failure.status <= 599:
            raise Rejection("upstream_http_status") from None
        self.evidence: dict[str, str | int | float] = {
            "category": "upstream_http_status",
            "http_status": failure.status,
            "selected_profile_id": profile_id,
            "request_role": role,
        }
        if failure.status == 429 and isinstance(failure.retry_after, str):
            try:
                duration = retry_delay(1, failure.retry_after, datetime.now(UTC), 0)
            except Rejection:
                pass
            else:
                self.evidence["retry_after_seconds"] = duration


def capture(identifiers: list[str], *, opted_in: bool) -> Path:
    if not opted_in:
        raise Rejection("live_capture_opt_in_required")
    credential = os.environ.get("ARGOVIS_API_KEY")
    if not credential:
        raise Rejection("ARGOVIS_API_KEY")
    if (
        not 1 <= len(identifiers) <= 3
        or len(set(identifiers)) != len(identifiers)
        or any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item) for item in identifiers)
    ):
        raise Rejection("invalid_small_capture_selection")
    recorder = ROOT / ".cache/tools/gitleaks"
    if not recorder.is_file():
        raise Rejection("prepare_pinned_secret_scanner_separately")
    capture_id = uuid.uuid4().hex
    private = Path.home() / "private/argovis-captures" / capture_id
    private.mkdir(parents=True, mode=0o700)
    private.chmod(0o700)
    originals, sanitized = private / "originals", private / "sanitized"
    originals.mkdir(mode=0o700)
    sanitized.mkdir(mode=0o700)
    records = []
    original_records = []
    received = requests = 0
    deadline = time.monotonic() + 300

    def account(amount: int) -> None:
        nonlocal received
        received += amount
        if received > 16 * MIB:
            raise Rejection("small_capture_total_size_limit")

    def request(path: str, parameters: dict[str, str], role: str) -> list:
        nonlocal requests
        requests += 1
        if requests > 24 or time.monotonic() >= deadline:
            raise Rejection("small_capture_budget_exhausted")
        try:
            response = fetch(
                path,
                parameters,
                credential,
                account,
                deadline=deadline,
                enabled=lambda: True,
                raw_limit=MIB,
                json_limit=8 * MIB,
            )
        except HTTPFailure as failure:
            # Never stringify/repr the failure or retain transport attributes.
            # Metadata failures name the selected parent profile, not its pointer.
            raise SafeHTTPDiagnostic(failure, identifier, role) from None
        filename = f"{requests:02d}-{role}.json"
        original_path = originals / filename
        original_path.write_bytes(response.payload)
        original_path.chmod(0o600)
        original_records.append(
            {
                "path": filename,
                "role": role,
                "sha256": hashlib.sha256(response.payload).hexdigest(),
                "bytes": len(response.payload),
                "retrieved_at_utc": response.retrieved_at.isoformat(),
            }
        )
        original_manifest = originals / "manifest.json"
        original_manifest.write_text(
            json.dumps(
                {"representation": "original_decompressed_json", "responses": original_records},
                indent=2,
            )
            + "\n"
        )
        original_manifest.chmod(0o600)
        clean = sanitize_raw(response.payload, credential)
        parsed = decode_json(clean.payload, max_bytes=8 * MIB)
        if not isinstance(parsed, list) or not 1 <= len(parsed) <= 3:
            raise Rejection("small_capture_missing_or_excess_documents")
        clean_path = sanitized / filename
        clean_path.write_bytes(clean.payload)
        clean_path.chmod(0o600)
        records.append(
            {
                "path": filename,
                "kind": "live_recorded_argovis_raw_json",
                "role": role,
                "endpoint": BASE + path,
                "request_parameters": parameters,
                "retrieved_at_utc": response.retrieved_at.isoformat(),
                "status": 200,
                "response_headers": response.headers,
                "representation": "sanitized_decompressed_json",
                "sha256": hashlib.sha256(clean.payload).hexdigest(),
                "bytes": len(clean.payload),
                "received_compressed_bytes": response.received_bytes,
                "sanitization": clean.manifest,
            }
        )
        return parsed

    metadata = {}
    summaries = []
    for identifier in identifiers:
        before = request("/argo", {"id": identifier}, "inventory_before")
        data = request("/argo", {"id": identifier, "data": "all"}, "profile")
        after = request("/argo", {"id": identifier}, "inventory_after")
        if any(
            len(group) != 1 or group[0].get("_id") != identifier for group in (before, data, after)
        ):
            raise Rejection("capture_inventory_identity_mismatch")
        pointers = data[0].get("metadata")
        if not isinstance(pointers, list) or not 1 <= len(pointers) <= 4:
            raise Rejection("small_capture_metadata_limit")
        for pointer in pointers:
            if not isinstance(pointer, str) or len(pointer.encode()) > 512:
                raise Rejection("invalid_metadata_pointer")
            if pointer not in metadata:
                rows = request("/argo/meta", {"id": pointer}, "metadata")
                if len(rows) != 1 or rows[0].get("_id") != pointer:
                    raise Rejection("capture_metadata_identity_mismatch")
                metadata[pointer] = rows[0]
        profile = map_profile(data[0], metadata, CanonicalBudget())
        # ID fetches have no region/time filtering; compare the immutable source
        # inventory fields directly, and include scientific content verification.
        for name in ("timestamp", "geolocation", "metadata", "cycle_number", "profile_direction"):
            if before[0].get(name) != data[0].get(name) or data[0].get(name) != after[0].get(name):
                raise Rejection("capture_inventory_changed")
        summaries.append(
            {
                "identity": profile.identity,
                "levels": len(profile.levels),
                "content_hash": profile.content_hash,
                "source_revision": "present" if profile.revision else "absent",
            }
        )
    specification = ROOT / "docs/upstream/argovis-2.36.2.json"
    manifest = {
        "capture_id": capture_id,
        "kind": "live_recorded_argovis_raw_json",
        "scope": "small_profile_id_capture_not_region_ingestion",
        "versions": policy_versions(),
        "specification": {
            "release": "2.36.2",
            "sha256": hashlib.sha256(specification.read_bytes()).hexdigest(),
            "url": "https://github.com/argovis/argovis_api/blob/2.36.2/core-spec.json",
        },
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "application_uncommitted": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
        ),
        "responses": records,
        "expected_profiles": summaries,
        "attribution": {
            "provider": "International Argo Program and national contributors, via Argovis",
            "argo_doi": "https://doi.org/10.17882/42182",
            "terms_and_acknowledgement": "https://argo.ucsd.edu/data/acknowledging-argo/",
            "argovis_contract_citation": "https://zenodo.org/records/15708506",
        },
        "acceptance": "Sample capture does not certify the full F01 corpus or Jan-Mar acceptance.",
    }
    (sanitized / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (sanitized / "manifest.json").chmod(0o600)
    scan = subprocess.run(
        [
            str(recorder),
            "dir",
            str(sanitized),
            "--redact=100",
            "--no-banner",
            "--max-decode-depth=3",
            "--config",
            str(ROOT / ".gitleaks.toml"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    if scan.returncode != 0:
        raise Rejection("sanitized_capture_secret_scan_failed")
    destination = ROOT / "tests/fixtures/argovis/recorded" / capture_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(sanitized, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture at most three official Argovis profile IDs"
    )
    parser.add_argument("--profile-id", action="append", required=True)
    parser.add_argument("--live-opt-in", action="store_true")
    args = parser.parse_args()
    try:
        destination = capture(args.profile_id, opted_in=args.live_opt_in)
        print("Sanitized, scanned fixture bundle: " + str(destination.relative_to(ROOT)))
        return 0
    except SafeHTTPDiagnostic as error:
        print(json.dumps(error.evidence, sort_keys=True))
        return 2
    except Rejection as error:
        print(error.category)
        return 2
    except Exception:
        print("capture_failed_no_sensitive_diagnostics")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
