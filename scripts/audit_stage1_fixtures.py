"""Offline audit of sanitized recorded bundles only. Never reads private originals."""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from floatchat_core.ingestion.argovis import (
    ADDITIONAL_NONCORE,
    LEGACY_SOURCE_CONTRACT,
    SOURCE_CONTRACT,
    VARIABLES,
    map_profile,
    policy_versions,
)
from floatchat_core.ingestion.numeric import CanonicalBudget, Rejection, decode_json
from floatchat_core.ingestion.planning import in_region
from floatchat_core.ingestion.raw import sanitize_raw

ROOT = Path(__file__).resolve().parents[1]
RECORDED = ROOT / "tests/fixtures/argovis/recorded"
DISCOVERY = ROOT / "tests/fixtures/argovis/discovery"


def audit_discovery(bundle: Path) -> dict:
    """Candidate inventory evidence is always excluded from the F01 profile union."""
    if (
        bundle.is_symlink()
        or bundle.absolute().parent != DISCOVERY.absolute()
        or not re.fullmatch(r"[0-9a-f]{32}", bundle.name)
    ):
        raise Rejection("unapproved_sanitized_discovery")
    bundle = bundle.resolve(strict=True)
    if bundle.parent != DISCOVERY.resolve() or set(p.name for p in bundle.iterdir()) != {
        "manifest.json",
        "01-inventory_discovery.json",
    }:
        raise Rejection("unapproved_sanitized_discovery")
    for name, ceiling in (("manifest.json", 1024**2), ("01-inventory_discovery.json", 8 * 1024**2)):
        path = bundle / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > ceiling:
            raise Rejection("unsafe_discovery_reference")
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    specification = json.loads((ROOT / "docs/upstream/argovis-2.36.2.json").read_bytes())
    field_pattern = specification["components"]["schemas"]["argo_data_keys"]["items"]["pattern"]
    parameters = {
        "startDate": "2026-09-28T00:00:00Z",
        "endDate": "2026-10-05T00:00:00Z",
        "polygon": "[[65,-5],[70,-5],[70,0],[65,0],[65,-5]]",
    }
    expected_bounds = {
        "requests": 1,
        "concurrency": 1,
        "automatic_retries": 0,
        "compressed_bytes": 1024**2,
        "decompressed_bytes": 8 * 1024**2,
        "inventory_documents": 20,
        "http_seconds": 120,
        "scanner_seconds": 60,
        "owner_command_seconds": 300,
    }
    if (
        manifest["capture_id"] != bundle.name
        or manifest["kind"] != "live_recorded_argovis_inventory_discovery"
        or manifest["scope"] != "candidate_discovery_only_not_F01_or_regional_coverage"
        or manifest["endpoint"] != "https://argovis-api.colorado.edu/argo"
        or manifest["request_role"] != "inventory_discovery"
        or manifest["request_parameters"] != parameters
        or manifest["status"] != 200
        or manifest["bounds"] != expected_bounds
        or manifest["specification"]
        != {
            "release": "2.36.2",
            "sha256": hashlib.sha256(
                (ROOT / "docs/upstream/argovis-2.36.2.json").read_bytes()
            ).hexdigest(),
            "url": "https://github.com/argovis/argovis_api/blob/2.36.2/core-spec.json",
        }
    ):
        raise Rejection("discovery_provenance_mismatch")
    retrieved = datetime.fromisoformat(manifest["retrieved_at_utc"])
    if retrieved.tzinfo is None or retrieved.utcoffset() != UTC.utcoffset(retrieved):
        raise Rejection("discovery_retrieval_time_mismatch")
    response = manifest["response"]
    data = (bundle / "01-inventory_discovery.json").read_bytes()
    if (
        response["path"] != "01-inventory_discovery.json"
        or response["representation"] != "sanitized_decompressed_json"
        or response["sanitization"]["version"] != "raw-sanitization-v1"
        or len(data) != response["bytes"]
        or not 0 <= response["received_compressed_bytes"] <= 1024**2
        or hashlib.sha256(data).hexdigest() != response["sha256"]
        or sanitize_raw(data).payload != data
    ):
        raise Rejection("discovery_response_mismatch")
    rows = decode_json(data, max_bytes=8 * 1024**2)
    if not isinstance(rows, list) or len(rows) > 20:
        raise Rejection("discovery_inventory_document_limit")
    summaries = []
    for row in rows:
        identifier = row["_id"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identifier)
            or "data" in row
        ):
            raise Rejection("discovery_invalid_inventory")
        names, attributes, values = row["data_info"]
        if len(names) != len(values) or len(set(names)) != len(names):
            raise Rejection("discovery_data_info_mismatch")
        mode_index = attributes.index("data_keys_mode")
        modes = {}
        for name, attrs in zip(names, values, strict=True):
            if len(attrs) != len(attributes):
                raise Rejection("discovery_data_info_mismatch")
            if name in VARIABLES:
                if attrs[mode_index] not in ("R", "A", "D", None):
                    raise Rejection("discovery_data_info_mismatch")
                modes[name] = attrs[mode_index]
        lon, lat = row["geolocation"]["coordinates"]
        observed = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if (
            not 65 <= lon <= 70
            or not -5 <= lat <= 0
            or observed.tzinfo is None
            or not datetime(2026, 9, 28, tzinfo=UTC)
            <= observed
            <= datetime(2026, 10, 5, tzinfo=UTC)
            or not in_region(lon, lat)
        ):
            raise Rejection("discovery_selection_mismatch")
        summaries.append(
            {
                "source_profile_id": identifier,
                "inventory_core_data_keys_modes": modes,
                "inventory_direction": row["profile_direction"],
                "observed_at_utc": observed.isoformat(),
                "longitude_latitude": [float(lon), float(lat)],
                "metadata_pointers": row["metadata"],
                "unsupported_inventory_columns": [
                    name for name in names if re.fullmatch(field_pattern, name) is None
                ],
                "inventory_schema_compatible": all(
                    re.fullmatch(field_pattern, name) is not None for name in names
                ),
                "supplemented_source_contract": SOURCE_CONTRACT,
                "supplemented_source_contract_compatible": all(
                    re.fullmatch(field_pattern, name) is not None or name in ADDITIONAL_NONCORE
                    for name in names
                ),
                "measurement_levels": "not_fetched",
                "complete_capture": False,
            }
        )
    identifiers = [row["source_profile_id"] for row in summaries]
    if (
        identifiers != manifest["candidate_ids"]
        or len(identifiers) != len(set(identifiers))
        or manifest["candidate_count"] != len(identifiers)
    ):
        raise Rejection("discovery_candidate_mismatch")
    return {
        "kind": "persisted_sanitized_inventory_discovery_audit",
        "bundle": str(bundle.relative_to(ROOT)),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "response_sha256": response["sha256"],
        "verified_response_bytes": len(data),
        "received_compressed_bytes": response["received_compressed_bytes"],
        "retrieved_at_utc": manifest["retrieved_at_utc"],
        "endpoint": manifest["endpoint"],
        "request_parameters": parameters,
        "specification": manifest["specification"],
        "bounds": expected_bounds,
        "attribution": manifest["attribution"],
        "candidates": summaries,
        "F01_representations_closed": [],
        "F01_scope": "Inventory modes are candidate evidence only; complete matching "
        "inventory/profile/metadata capture and scientific assertions are still required",
        "regional_completeness": "not_proven_by_inventory_discovery",
        "private_originals": "not_accessed",
    }


def representation_gaps(profiles: list[dict]) -> list[str]:
    modes = {
        mode
        for item in profiles
        for variable in item["variables"].values()
        for mode in variable["modes"]
    }
    directions = {item["direction"] for item in profiles}
    gaps = ["data_mode_" + mode for mode in ("R", "A", "D") if mode not in modes]
    gaps += ["direction_" + direction for direction in ("A", "D") if direction not in directions]
    # These two representations have separately labelled synthetic obligations;
    # neither is an authentic-wire requirement under the approved F01 clarification.
    # Missing QC, an absent variable, and an absent original counterpart are
    # separate observations, not evidence of a null source measurement cell.
    if not any(item["source_core_value_null_cells"] for item in profiles):
        gaps.append("source_core_measurement_null")
    return gaps


def audit(bundle: Path) -> dict:
    bundle = bundle.resolve(strict=True)
    if bundle.parent != RECORDED.resolve() or not re.fullmatch(r"[0-9a-f]{32}", bundle.name):
        raise Rejection("unapproved_sanitized_bundle")
    manifest_bytes = (bundle / "manifest.json").read_bytes()
    if len(manifest_bytes) > 1024**2:
        raise Rejection("fixture_manifest_limit")
    manifest = json.loads(manifest_bytes)
    source_contract = manifest["versions"].get("source_contract", LEGACY_SOURCE_CONTRACT)
    if (
        manifest["kind"] != "live_recorded_argovis_raw_json"
        or manifest["scope"] != "small_profile_id_capture_not_region_ingestion"
        or manifest["versions"] != policy_versions(source_contract)
        or manifest["specification"]["sha256"]
        != hashlib.sha256((ROOT / "docs/upstream/argovis-2.36.2.json").read_bytes()).hexdigest()
    ):
        raise Rejection("fixture_provenance_mismatch")
    responses = manifest["responses"]
    if not 1 <= len(responses) <= 24:
        raise Rejection("fixture_response_limit")
    verified = []
    metadata = {}
    selections = {}
    total = 0
    seen_files = set()
    for evidence in responses:
        name = evidence["path"]
        if not re.fullmatch(
            r"[0-9]{2}-(inventory_before|profile|inventory_after|metadata)\.json", name
        ):
            raise Rejection("unsafe_fixture_filename")
        source = bundle / name
        if source.resolve().parent != bundle or name in seen_files:
            raise Rejection("unsafe_fixture_reference")
        seen_files.add(name)
        data = source.read_bytes()
        total += evidence["received_compressed_bytes"]
        if (
            len(data) != evidence["bytes"]
            or hashlib.sha256(data).hexdigest() != evidence["sha256"]
            or len(data) > 8 * 1024**2
            or evidence["received_compressed_bytes"] > 1024**2
            or total > 16 * 1024**2
            or evidence["status"] != 200
            or evidence["kind"] != manifest["kind"]
            or set(evidence["response_headers"]) - {"content-type", "content-encoding"}
        ):
            raise Rejection("fixture_response_mismatch")
        documents = decode_json(data, max_bytes=8 * 1024**2)
        if not isinstance(documents, list) or len(documents) != 1:
            raise Rejection("fixture_identity_mismatch")
        document = documents[0]
        identifier = document["_id"]
        role = evidence["role"]
        expected = {"id": identifier}
        if role == "profile":
            expected["data"] = "all"
        endpoint = "https://argovis-api.colorado.edu/argo"
        if role == "metadata":
            endpoint += "/meta"
            metadata[identifier] = document
        else:
            selection = selections.setdefault(identifier, {})
            if role in selection:
                raise Rejection("duplicate_fixture_role")
            selection[role] = document
        if evidence["endpoint"] != endpoint or evidence["request_parameters"] != expected:
            raise Rejection("fixture_request_mismatch")
        verified.append(
            {key: evidence[key] for key in ("path", "role", "sha256", "bytes", "retrieved_at_utc")}
        )
    summaries = []
    expected_profiles = {row["identity"]: row for row in manifest["expected_profiles"]}
    for selection in selections.values():
        if set(selection) != {"inventory_before", "profile", "inventory_after"}:
            raise Rejection("fixture_inventory_missing")
        raw = selection["profile"]
        inventory = {key: value for key, value in raw.items() if key != "data"}
        if selection["inventory_before"] != inventory or selection["inventory_after"] != inventory:
            raise Rejection("fixture_inventory_changed")
        profile = map_profile(raw, metadata, CanonicalBudget(), source_contract=source_contract)
        expected = expected_profiles[profile.identity]
        if (
            expected["levels"] != len(profile.levels)
            or expected["content_hash"] != profile.content_hash
        ):
            raise Rejection("fixture_scientific_mismatch")
        names = raw["data_info"][0]
        pressures = [
            row["pressure"] if row["pressure"] is not None else row["pressure_adjusted"]
            for row in profile.levels
        ]
        summaries.append(
            {
                "source_profile_id": profile.source_profile_id,
                "identity": profile.identity,
                "levels": len(profile.levels),
                "scientific_sha256": profile.content_hash,
                "direction": profile.direction,
                "observed_at_utc": profile.observed_at,
                "in_indian_ocean_geometry": in_region(*raw["geolocation"]["coordinates"]),
                "source_revision_components": 0
                if profile.revision is None
                else len(profile.revision.components),
                "source_columns": names,
                "source_null_cells_by_column": {
                    name: column.count(None)
                    for name, column in zip(names, raw["data"], strict=True)
                    if None in column
                },
                "supplementary_noncore_columns": {
                    name: {
                        "levels": len(column),
                        "null_cells": column.count(None),
                        "source_attributes": dict(zip(raw["data_info"][1], attrs, strict=True)),
                        "disposition": "immutable_raw_only_no_canonical_chlorophyll_mapping",
                    }
                    for name, column, attrs in zip(
                        names, raw["data"], raw["data_info"][2], strict=True
                    )
                    if name in ADDITIONAL_NONCORE
                },
                "source_null_cells": sum(
                    value is None for column in raw["data"] for value in column
                ),
                "source_core_null_cells": sum(
                    value is None
                    for name, column in zip(names, raw["data"], strict=True)
                    if name in VARIABLES or name in {variable + "_argoqc" for variable in VARIABLES}
                    for value in column
                ),
                "source_core_value_null_cells": sum(
                    value is None
                    for name, column in zip(names, raw["data"], strict=True)
                    if name in VARIABLES
                    for value in column
                ),
                "source_core_qc_null_cells": sum(
                    value is None
                    for name, column in zip(names, raw["data"], strict=True)
                    if name in {variable + "_argoqc" for variable in VARIABLES}
                    for value in column
                ),
                "repeated_nonnull_pressure": len([x for x in pressures if x is not None])
                != len(set(x for x in pressures if x is not None)),
                "variables": {
                    variable: {
                        "modes": sorted(
                            set(
                                row[variable + "_data_mode"]
                                for row in profile.levels
                                if row[variable + "_data_mode"] is not None
                            )
                        ),
                        "source_column_present": variable in names,
                        "raw_data_keys_modes": sorted(
                            {
                                attributes[raw["data_info"][1].index("data_keys_mode")]
                                for name, attributes in zip(names, raw["data_info"][2], strict=True)
                                if name == variable
                                and "data_keys_mode" in raw["data_info"][1]
                                and attributes[raw["data_info"][1].index("data_keys_mode")]
                                is not None
                            }
                        ),
                        "available": {
                            suffix or "original": sum(
                                row[variable + suffix] is not None for row in profile.levels
                            )
                            for suffix in (
                                "",
                                "_adjusted",
                                "_qc",
                                "_adjusted_qc",
                                "_error",
                                "_original_error",
                            )
                        },
                        "qc_values": sorted(
                            set(
                                row[variable + suffix]
                                for row in profile.levels
                                for suffix in ("_qc", "_adjusted_qc")
                                if row[variable + suffix] is not None
                            )
                        ),
                    }
                    for variable in VARIABLES
                },
            }
        )
    gaps = representation_gaps(summaries)
    return {
        "kind": "persisted_sanitized_fixture_audit",
        "bundle": str(bundle.relative_to(ROOT)),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "versions": manifest["versions"],
        "attribution": manifest["attribution"],
        "verified_responses": verified,
        "profiles": summaries,
        "representation_gaps": gaps,
        "F01_representative_corpus": "pending"
        if gaps
        else "representations_present_not_regional_acceptance",
        "regional_completeness": "not_proven_by_profile_id_samples",
        "live_regional_acceptance": "not_executed",
        "private_originals": "not_accessed",
    }


def audit_corpus() -> dict:
    """Union only authentic sanitized recorded bundles; never published/synthetic inputs."""
    policy_path = ROOT / "docs/stage1-f01-evidence-v2.json"
    policy_bytes = policy_path.read_bytes()
    policy = json.loads(policy_bytes)
    if (
        policy["version"] != "F01-2"
        or set(policy["waived_authentic_representations"])
        != {"direction_D", "source_core_measurement_null"}
        or set(policy["required_authentic_representations"])
        != {"data_mode_R", "data_mode_A", "data_mode_D", "direction_A"}
    ):
        raise Rejection("unsupported_F01_evidence_policy")
    bundles = sorted(RECORDED.iterdir())
    if not 1 <= len(bundles) <= 32 or any(
        item.is_symlink() or not item.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", item.name)
        for item in bundles
    ):
        raise Rejection("unapproved_sanitized_corpus")
    audits = [audit(item) for item in bundles]
    profiles = [
        {"bundle": result["bundle"], "manifest_sha256": result["manifest_sha256"], **profile}
        for result in audits
        for profile in result["profiles"]
    ]

    def witnesses(predicate):
        return [
            {key: item[key] for key in ("bundle", "source_profile_id", "scientific_sha256")}
            for item in profiles
            if predicate(item)
        ]

    matrix = {}
    for mode in ("R", "A", "D"):
        matrix["data_mode_" + mode] = witnesses(
            lambda row, mode=mode: any(
                mode in variable["modes"] for variable in row["variables"].values()
            )
        )
    for direction in ("A", "D"):
        matrix["direction_" + direction] = witnesses(
            lambda row, direction=direction: row["direction"] == direction
        )
    matrix["source_core_measurement_null"] = witnesses(
        lambda row: row["source_core_value_null_cells"] > 0
    )
    matrix["supplied_measurement_error"] = witnesses(
        lambda row: any(
            variable["available"]["_error"] or variable["available"]["_original_error"]
            for variable in row["variables"].values()
        )
    )
    matrix["repeated_nonnull_pressure"] = witnesses(lambda row: row["repeated_nonnull_pressure"])
    matrix["supplied_core_qc"] = witnesses(
        lambda row: any(variable["qc_values"] for variable in row["variables"].values())
    )
    matrix["source_revision_metadata"] = witnesses(
        lambda row: row["source_revision_components"] > 0
    )
    gaps = representation_gaps(profiles)
    waived_gaps = [name for name in gaps if name in policy["waived_authentic_representations"]]
    required_gaps = [name for name in gaps if name in policy["required_authentic_representations"]]
    discovery_bundles = sorted(DISCOVERY.iterdir()) if DISCOVERY.exists() else []
    if len(discovery_bundles) > 32:
        raise Rejection("discovery_bundle_limit")
    discovery_audits = [audit_discovery(item) for item in discovery_bundles]
    return {
        "kind": "persisted_authentic_sanitized_fixture_corpus_audit",
        "contract": "stage1-v2",
        "minimum_basis": "docs/stage1-contract.md section 11 and F01",
        "evidence_amendment": policy,
        "evidence_amendment_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "F01_evidence_policy": {
            "data_mode_A": "authentic complete profile, matching inventory and metadata",
            "direction_D": "authentic requirement waived; labelled admitted-fixture "
            "direction/identity parser/canonical/database/Parquet tests",
            "source_core_measurement_null": "authentic requirement waived; labelled R/A "
            "present-core-null parser/canonical/database/Parquet tests",
            "repeated_nonnull_pressure": "labelled derivative; preservation, ordinal "
            "and diagnostics tests",
            "supplied_measurement_error": "labelled normalized-model/storage tests; "
            "no authentic parser claim",
        },
        "bundle_audits": audits,
        "profiles": profiles,
        "response_count": sum(len(item["verified_responses"]) for item in audits),
        "distinct_profile_count": len({item["source_profile_id"] for item in profiles}),
        "captured_level_occurrences": sum(item["levels"] for item in profiles),
        "coverage_matrix": {
            key: {
                "status": "observed"
                if rows
                else policy["waiver_observation_status"]
                if key in policy["waived_authentic_representations"]
                else "authentic_not_required"
                if key in {"repeated_nonnull_pressure", "supplied_measurement_error"}
                else "missing",
                "witnesses": rows,
            }
            for key, rows in matrix.items()
        },
        "inventory_candidate_discovery": discovery_audits,
        "inventory_candidate_scope": "Excluded from coverage_matrix witnesses, scientific "
        "profiles, level counts and minimum F01 satisfaction",
        "representation_gaps": gaps,
        "required_authentic_gaps": required_gaps,
        "waived_authentic_coverage_gaps": waived_gaps,
        "minimum_F01_satisfied": not required_gaps,
        "minimum_F01_scope": "F01-2 remaining required authentic portion only; "
        "waived gaps stay unobserved. Labelled derivative/model/storage "
        "obligations "
        "require persisted test results, and regional acceptance remains separate",
        "synthetic_obligations": {
            "basis_bundle": "tests/fixtures/argovis/recorded/25f21e056e7c4db7bc1e21b0a28ea45f",
            "direction_and_core_null_tests": "tests/stage1/test_fixture_derivatives.py "
            "and tests/stage1/test_database.py F01-2",
            "repeated_pressure_tests": "tests/stage1/test_fixture_derivatives.py F01/I04/S05",
            "error_model_parquet_tests": "tests/stage1/test_fixture_derivatives.py F01/S01",
            "error_storage_tests": "tests/stage1/test_database.py F01/S01",
            "test_outcomes": "Read persisted JUnit/verification; this corpus audit "
            "does not execute tests",
        },
        "F01_representative_corpus": "pending"
        if required_gaps
        else "amended_authentic_minimum_present_derivative_tests_required_not_regional_acceptance",
        "revision_evidence_scope": "Source revision vectors observed; no same-profile revision "
        "transition or metadata absence is inferred",
        "missingness_scope": "Source value nulls exclude missing QC, absent variables "
        "and mapped counterpart nulls",
        "regional_completeness": "not_proven_by_profile_id_samples",
        "live_regional_acceptance": "not_executed",
        "private_originals": "not_accessed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, nargs="?")
    parser.add_argument("--corpus", action="store_true")
    parser.add_argument("--discovery", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.corpus == (args.bundle is not None) or (args.corpus and args.discovery):
        parser.error("Provide one sanitized bundle (optionally --discovery) or --corpus")
    result = (
        audit_corpus()
        if args.corpus
        else audit_discovery(args.bundle)
        if args.discovery
        else audit(args.bundle)
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("sanitized_fixture_audit_persisted")


if __name__ == "__main__":
    main()
