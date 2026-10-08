"""Offline component verification evidence; never a substitute for ingestion reports.

Requires already prepared uv dependencies and local foundation Docker images.
No installation, downloads, upstream credentials, ingestion or deployment occurs.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

F01_DERIVATIVE_CASES = [
    "test_F01_I01_I02_I03_labelled_descending_identity_canonical_parquet",
    "test_F01_I01_I02_I03_labelled_descending_database_direction_and_natural_key",
    "test_F01_S01_labelled_null_distinctions_absence_QC_counterpart_noncore",
    "test_F01_I04_S05_labelled_repeated_pressure_derivative_preserves_ordinals",
    "test_F01_I04_S05_labelled_authentic_pressure_derivative_storage",
    "test_F01_S01_labelled_normalized_errors_parquet_not_Argovis_wire",
    "test_F01_S01_normalized_error_storage_not_Argovis_parser_support",
    *[
        prefix + "[" + mode + "]"
        for prefix in (
            "test_F01_S01_S03_S04_labelled_present_core_null_parser_canonical_parquet",
            "test_F01_S01_S03_labelled_present_core_null_restricted_database_publication",
        )
        for mode in ("R", "A")
    ],
]


def source_hash() -> str:
    digest = hashlib.sha256()
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    for path in sorted(set(paths)):
        if (
            not path
            or path.startswith("reports/")
            or path == "docs/stage1-gate.md"
            or not (ROOT / path).is_file()
        ):
            continue
        digest.update(path.encode() + b"\0")
        digest.update(hashlib.sha256((ROOT / path).read_bytes()).digest())
    return digest.hexdigest()


def run() -> int:
    REPORTS.mkdir(exist_ok=True)
    environment = {name: os.environ[name] for name in os.environ if name != "ARGOVIS_API_KEY"}
    environment["UV_OFFLINE"] = "true"
    tested_source = source_hash()
    commands = {
        "python_lint": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "ruff",
            "check",
            ".",
        ],
        "python_format": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "ruff",
            "format",
            "--check",
            ".",
        ],
        "python_types": ["uv", "run", "--all-packages", "--frozen", "--offline", "mypy"],
        "unit": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "-m",
            "not integration",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-unit.xml",
        ],
        "database": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_database.py",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-database.xml",
        ],
        "object_store": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_minio.py",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-object_store.xml",
        ],
        "terminalization": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_terminalization_review.py",
            "-m",
            "integration",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-terminalization.xml",
        ],
        "resource": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_resources.py",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-resource.xml",
        ],
        "broker": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_broker.py",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-broker.xml",
        ],
        "fixture_audit": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "scripts/audit_stage1_fixtures.py",
            "--corpus",
            "--output",
            "reports/stage1-fixture-corpus-coverage.json",
        ],
        "secrets_recorded_bundle": [
            str(ROOT / ".cache/tools/gitleaks"),
            "dir",
            "tests/fixtures/argovis/recorded",
            "--redact=100",
            "--no-banner",
            "--max-decode-depth=3",
            "--config",
            str(ROOT / ".gitleaks.toml"),
        ],
        "web_lint": ["pnpm", "lint"],
        "web_format": ["pnpm", "format:check"],
        "web_types": ["pnpm", "typecheck"],
        "web_tests": ["pnpm", "test"],
        "web_build": ["pnpm", "build"],
        "secrets_current": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "scripts/security/scan.py",
            "current",
        ],
        "secrets_history": [
            "uv",
            "run",
            "--all-packages",
            "--frozen",
            "--offline",
            "python",
            "scripts/security/scan.py",
            "history",
        ],
        "diff_whitespace": ["git", "diff", "--check"],
    }

    def check(name: str, command: list[str]) -> dict:
        print(f"Stage 1 verification: {name}", flush=True)
        start = time.monotonic()
        timeout = {"database": 900, "resource": 480, "broker": 510}.get(name, 180)
        with (REPORTS / f"stage1-{name}.log").open("wb") as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write(f"\nVerification exceeded its {timeout}-second bound.\n".encode())
        return {
            "exit_code": code,
            "seconds": time.monotonic() - start,
            "evidence": f"reports/stage1-{name}.log",
        }

    checks = {}
    for name, command in commands.items():
        # The bounded memory proof consumes a large disk-backed mapping. Run
        # it separately from the multi-process broker stack on small WSL VMs.
        checks[name] = check(name, command)
    suites = {}
    component_tests = []
    for name in ("unit", "database", "object_store", "resource", "broker", "terminalization"):
        path = REPORTS / f"stage1-{name}.xml"
        if checks[name]["exit_code"] != 0 or not path.exists():
            continue
        tree = ET.parse(path)
        suite = tree.find("testsuite")
        assert suite is not None
        suites[name] = {
            key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")
        }
        component_tests.extend(
            case.attrib["name"]
            for case in suite.findall("testcase")
            if "stage1" in case.attrib.get("classname", "")
            and not any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))
        )
    ids = re.findall(
        r"^\| ([TGISRPCBDFNX]\d{2}[a-c]?) \|", (ROOT / "docs/stage1-contract.md").read_text(), re.M
    )
    assert len(ids) == len(set(ids)) == 86
    acceptance = {
        case_id: {
            "status": "pending_end_to_end_acceptance",
            "component_tests": [name for name in component_tests if case_id in name],
        }
        for case_id in ids
    }
    fixture_audit_path = REPORTS / "stage1-fixture-corpus-coverage.json"
    fixture_audit = (
        json.loads(fixture_audit_path.read_text())
        if checks["fixture_audit"]["exit_code"] == 0 and fixture_audit_path.exists()
        else None
    )
    acceptance["F01"]["recorded_input_evidence"] = "reports/stage1-fixture-corpus-coverage.json"
    acceptance["F01"]["remaining_representation_gaps"] = (
        fixture_audit["representation_gaps"] if fixture_audit else "audit_failed"
    )
    acceptance["F01"]["evidence_policy"] = (
        fixture_audit["F01_evidence_policy"] if fixture_audit else None
    )
    f01_obligations = {name: name in component_tests for name in F01_DERIVATIVE_CASES}
    f01_pass = bool(
        fixture_audit and fixture_audit["minimum_F01_satisfied"] and all(f01_obligations.values())
    )
    acceptance["F01"].update(
        evidence_version="F01-2",
        amended_fixture_gate_passed=f01_pass,
        derivative_test_passes=f01_obligations,
        waived_authentic_coverage_gaps=fixture_audit["waived_authentic_coverage_gaps"]
        if fixture_audit
        else None,
        authentic_gaps_are_not_test_passes=True,
    )
    path = REPORTS / "stage1-http-retry-evidence.json"
    production_regressions = (
        json.loads(path.read_text())
        if checks["database"]["exit_code"] == 0 and path.exists()
        else None
    )
    for case_id in ("B03", "F03", "F04", "F07"):
        acceptance[case_id]["production_regression_evidence"] = (
            "reports/stage1-http-retry-evidence.json" if production_regressions else None
        )
    broker_path = REPORTS / "stage1-broker-evidence.json"
    broker_evidence = (
        json.loads(broker_path.read_text())
        if checks["broker"]["exit_code"] == 0 and broker_path.exists()
        else None
    )
    resource_path = REPORTS / "stage1-parquet-resource.json"
    resource_evidence = (
        json.loads(resource_path.read_text())
        if checks["resource"]["exit_code"] == 0 and resource_path.exists()
        else None
    )
    if broker_evidence:
        for item in broker_evidence["cases"]:
            for case_id in set(re.findall(r"[A-Z]\d{2}[a-c]?", item["case"])):
                if case_id in acceptance:
                    acceptance[case_id].setdefault("persisted_process_evidence", []).append(
                        {
                            "path": "reports/stage1-broker-evidence.json",
                            "case": item["case"],
                            "scope": "Offline component fault; seeded plans and accelerated leases",
                        }
                    )
    for case_id in ("B01", "F06"):
        acceptance[case_id]["persisted_resource_evidence"] = (
            "reports/stage1-parquet-resource.json" if resource_evidence else None
        )
    for case_id in ("F02", "F03", "F07"):
        acceptance[case_id]["persisted_report_evidence"] = (
            "reports/stage1-ingestion-example.json" if broker_evidence else None
        )
    spec_bytes = (ROOT / "docs/upstream/argovis-2.36.2.json").read_bytes()
    unchanged_source = source_hash() == tested_source
    preparation_go = bool(
        unchanged_source
        and all(item["exit_code"] == 0 for item in checks.values())
        and f01_pass
        and production_regressions
        and broker_evidence
        and resource_evidence
    )
    # Passing components cannot override the unresolved owner-run failures or
    # authorize a new live attempt. This report remains withdrawn until review.
    coverage_blocked = (REPORTS / "stage1-coverage-failure-review.json").exists()
    preparation_go = preparation_go and not coverage_blocked
    evidence = {
        "status": "GO_isolated_acceptance_preparation_only" if preparation_go else "NO_GO",
        "acceptance_preparation_decision": "GO" if preparation_go else "NO_GO",
        "acceptance_prepared_or_executed": False,
        "owner_previous_acceptance_attempt": "stopped_incomplete"
        if coverage_blocked
        else "not_reported",
        "regional_blockers": [
            "Original run budget exhausted; component publication is not regional capacity",
            "44 pre-inventory HTTP 404s do not establish empty coverage",
            "Discarded source inputs remain quarantined; no scientific policy waiver",
            "Original run needs separately reviewed terminalization and frozen incomplete evidence",
        ]
        if coverage_blocked
        else [],
        "verification_scope": "Fresh complete offline verification; no historical pass substituted",
        "verified_at_actual_utc": datetime.now(UTC).isoformat(),
        "source_tree_sha256": tested_source,
        "source_unchanged_during_checks": unchanged_source,
        "source_tree_scope": "Tracked/unignored files; generated reports "
        "and gate document excluded.",
        "contract": "stage1-v2",
        "contract_gate": "owner_confirmed_Astra_GO",
        "F01_amendment": "F01-2_owner_authorized_ADR-0033",
        "checks": checks,
        "pytest_suites": suites,
        "acceptance_case_count": len(acceptance),
        "acceptance": acceptance,
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "uncommitted_work": True,
        "specification": {
            "version": "2.36.2",
            "byte_sha256": hashlib.sha256(spec_bytes).hexdigest(),
            "path": "docs/upstream/argovis-2.36.2.json",
        },
        "source_supplement": json.loads(
            (ROOT / "docs/upstream/argovis-source-supplement-v1.json").read_text()
        ),
        "production_regressions": production_regressions,
        "fixtures": fixture_audit,
        "F01_derivative_provenance": {
            name: json.loads((REPORTS / ("stage1-f01-" + name + ".json")).read_text())
            for name in (
                "descending-unit",
                "descending-database",
                "core-null-unit-R",
                "core-null-unit-A",
                "core-null-database-R",
                "core-null-database-A",
            )
            if f01_pass
        },
        "fixture_coverage_evidence": "reports/stage1-fixture-corpus-coverage.json",
        "live_capture": "owner_completed_bounded_capture_private_originals_not_accessed",
        "live_acceptance": "stopped_incomplete_retry_withdrawn"
        if coverage_blocked
        else "pending_gate_isolation_and_separate_opt_in",
        "CI": "not_run_on_remote_head",
        "ingestion_evidence_report": {
            "json": "reports/stage1-ingestion-example.json",
            "markdown": "reports/stage1-ingestion-example.md",
            "scope": "Frozen component-run evidence; explicit regional gaps; not live acceptance",
        },
        "gate_findings": {
            "S1-G01": {
                "status": "offline_fault_evidence_verified" if broker_evidence else "open",
                "evidence": "reports/stage1-broker-evidence.json",
                "scope": "Real prefork workers, supervisor, Redis and Beat; process loss, "
                "acknowledgement, cancellation, deadline, admission overlap and singleton lock",
            },
            "S1-G02": {
                "status": "offline_format_memory_evidence_verified"
                if resource_evidence
                else "open",
                "evidence": "reports/stage1-parquet-resource.json",
                "scope": "Writer/read-back memory only; no whole-pipeline memory certification",
            },
            "S1-G03": {
                "status": "offline_persisted_metrics_verified"
                if broker_evidence
                and production_regressions
                and production_regressions["split_replay"]["actual_cli_exit"] == 0
                else "open",
                "evidence": [
                    "reports/stage1-ingestion-example.json",
                    "reports/stage1-http-retry-evidence.json",
                ],
            },
            "S1-G04": {
                "status": "closed_amended_F01_fixture_scope" if f01_pass else "open_F01",
                "evidence": "reports/stage1-fixture-corpus-coverage.json",
                "amendment": "F01-2",
                "authentic_limitations": fixture_audit["waived_authentic_coverage_gaps"]
                if fixture_audit
                else None,
                "derivative_obligations": f01_obligations,
            },
        },
        "gate_report": "docs/stage1-gate.md",
        "limitations": [
            "Offline process/memory/report proofs use component plans and synthetic "
            "derivatives, not a full-region dataset or exhaustive end-to-end certification. "
            "Disposable leases are accelerated explicitly; actual process kills and "
            "deadlines are real.",
            "F01-2 waives authentic descending and present-core-null evidence only. "
            "Both remain unobserved; derivative passes do not become source observations. "
            "Repeated pressure is synthetic and errors have no verified wire mapping.",
            "No ingestion login/credential or existing environment was provisioned. "
            "All migration/object integration tests use disposable isolated containers.",
            "86 end-to-end case IDs are requirements, not the number of passed component tests.",
        ],
        "offline_remediation": {
            "diagnostic_contract": "S1-DIAG-1_ADR-0034",
            "migration": "0008_resource_evidence_fresh_disposable_only",
            "publication_capacity": "reports/stage1-publication-capacity.json"
            if checks["database"]["exit_code"] == 0
            else None,
            "http_source_review": "reports/stage1-http-source-semantics.json",
            "discarded_input_science": "reports/stage1-discarded-input-science.json",
            "terminalization_rehearsal": "reports/stage1-terminalization-rehearsal.json"
            if checks["database"]["exit_code"] == 0
            else None,
            "original_run_operated": False,
            "terminalization_approved_or_executed": False,
        },
    }
    (REPORTS / "stage1-verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
    rows = [
        "# Stage 1 implementation verification — " + evidence["status"],
        "",
        "Generated from fresh persisted check logs and JUnit evidence. "
        "This decides preparation readiness only, not full Stage 1 acceptance.",
        f"Source unchanged during verification: {unchanged_source}.",
        "",
        "| Check | Exit | Evidence |",
        "|---|---:|---|",
    ]
    rows.extend(
        f"| {name} | {check['exit_code']} | [{name}]({Path(check['evidence']).name}) |"
        for name, check in checks.items()
    )
    rows.extend(
        [
            "",
            "```json",
            json.dumps(suites, indent=2),
            "```",
            "",
            "All 86 end-to-end acceptance IDs remain pending; component evidence "
            "does not complete a case.",
            "Owner-recorded sanitized raw captures are audited separately from published "
            "examples and synthetic derivatives. Private originals and credentials were "
            "not accessed. Owner F01-2 waives further descending/core-null capture; "
            "authentic gaps remain separate from labelled derivative passes.",
            "This verifier made no live calls or operations against the stopped owner run. "
            "The owner's earlier incomplete live attempt is reported separately. "
            "No remote CI, production migrations, cloud provisioning "
            "or destructive retention was performed.",
            "",
            "Remaining work:",
            "",
        ]
    )
    rows.extend("- " + item for item in evidence["limitations"])
    (REPORTS / "stage1-verification.md").write_text("\n".join(rows) + "\n")
    write_gate_report(evidence)
    return (
        0 if unchanged_source and all(check["exit_code"] == 0 for check in checks.values()) else 1
    )


def write_gate_report(evidence: dict) -> None:
    """Render preparation readiness, authentic limitations and fresh test evidence separately."""
    decision = evidence.get("acceptance_preparation_decision", "NO_GO")
    fixtures = evidence["fixtures"]
    checks = evidence["checks"]
    rows = [
        "# Stage 1 implementation gate — " + decision + " for isolated acceptance preparation",
        "",
        "Generated from persisted checks, JUnit, corpus audits and derivative provenance. "
        "This is an implementation review report for Astra, not full acceptance approval.",
        "Fresh sanitized checkout: `/home/floatchat/FloatChat-stage1`; baseline `619411a`, "
        "branch `codex/stage-1`. Historical preparation is withdrawn after the incomplete "
        "owner-run findings. Full live acceptance remains "
        "outstanding; Stage 2 remains blocked.",
        "",
        f"Verified UTC: `{evidence['verified_at_actual_utc']}`; source SHA-256: "
        f"`{evidence['source_tree_sha256']}`; unchanged during checks: "
        f"`{evidence['source_unchanged_during_checks']}`.",
        f"Snapshot checks: **{sum(x['exit_code'] == 0 for x in checks.values())}/{len(checks)}**; "
        f"Python tests: **{sum(x['tests'] for x in evidence['pytest_suites'].values())}**. "
        "Consult JUnit for failures/errors/skips. All 86 end-to-end case IDs remain pending.",
        "[Verification](../reports/stage1-verification.md), "
        "[traceability and provenance](../reports/stage1-verification.json).",
        "",
    ]
    coverage_review_path = REPORTS / "stage1-coverage-failure-review.json"
    if coverage_review_path.exists():
        review = json.loads(coverage_review_path.read_text())
        failures = review["http_404"]
        roles = sorted({failure["role"] for failure in failures})
        warning_count = sum(
            chunk["reason"] == "upstream_data_warning" for chunk in review["quarantines"]
        )
        canonical_chunks = [
            chunk for chunk in review["quarantines"] if chunk["reason"] == "canonical_output_limit"
        ]
        mapped_count = sum(
            profile["offline_mapping"]["outcome"] == "mapped_with_uncharged_offline_budget"
            for chunk in canonical_chunks
            for profile in chunk["profiles"]
        )
        used = review["run"]["canonical_bytes"]
        science = review["science_after_review"]
        rows[0] = "# Stage 1 implementation gate — NO-GO for another live attempt or certification"
        rows[2:2] = [
            "## Current coverage review",
            "",
            f"Read-only review UTC: `{review['reviewed_at_utc']}`. "
            f"All {len(failures)} HTTP 404 attempts occurred in {', '.join(roles)}. "
            "They remain failed coverage, never verified empty selections. "
            f"{warning_count} source-warning chunks contain degenerate_levels; "
            "their quarantines remain. "
            f"{len(canonical_chunks)} canonical-limit chunks are blocked by the "
            f"aggregate run budget; {mapped_count} recorded profiles map within "
            "individual limits offline. "
            "Splitting cannot restore the run allowance.",
            f"Canonical work charged: {used:,} / {10 * 1024**3:,} bytes; "
            f"remaining {10 * 1024**3 - used:,} bytes is below the 16 MiB reservation. "
            f"Committed data remains {science['profiles']} profiles, {science['levels']} "
            f"levels and {science['active_partitions']} active partitions. "
            "The original deadline, data and withdrawn session seal remain intact; "
            "no live worker was restarted and no policy or budget was relaxed.",
            "[Coverage findings and every failed selection]"
            "(../reports/stage1-coverage-failure-review.md), "
            "[fresh persisted/raw-object evidence]"
            "(../reports/stage1-coverage-failure-review.json). "
            "The run remains open without frozen final evidence. Actual-head CI and full "
            "acceptance remain outstanding; Stage 2 remains blocked.",
            "",
            "## Component verification — regional blockers remain",
            "",
            "The tests below belong to their stated source/time. Fresh offline passes "
            "and historical component evidence must be read separately; neither overrides "
            "the current regional NO-GO. The original services remain stopped.",
            "",
        ]
        remediation = evidence.get("offline_remediation")
        if remediation:
            rows.extend(
                [
                    "## Offline remediation and review-only terminalization",
                    "",
                    "S1-DIAG-1 separates number/profile/chunk/run limits without changing "
                    "any budget, charging rule, quarantine or identity. Migration 0008 was "
                    "tested only in fresh disposable databases. Sanitized diagnostic fields "
                    "are persisted and frozen; unrecognized database details are discarded.",
                    "[Source-backed 404 and discarded-input review]"
                    "(stage1-offline-remediation.md), "
                    "[publication-capacity evidence](../reports/stage1-publication-capacity.json). "
                    "The five-slice growing-slot probe measures component publication within "
                    "10 GiB, not complete Jan–Mar capacity. It does not replenish the old run.",
                    "[Terminalization draft](stage1-terminalization-review.md) is neither "
                    "approved nor executed. A disposable synthetic-state rehearsal proves "
                    "partial/frozen/idempotent closing without ingestion. The preserved run "
                    "still requires separate procedure review.",
                    "",
                ]
            )
    if "previous_full_verification" in evidence:
        prior = evidence["previous_full_verification"]
        rows.extend(
            [
                "This fixture-only update does not establish preparation readiness. "
                "G01–G03 proofs are historical at the archived source/time, not rerun here.",
                f"[Historical full evidence](../{prior['path']}).",
                "",
            ]
        )
    else:
        rows.extend(
            [
                "Every check above was rerun on the reported source tree. Earlier 18/18 and "
                "362-test results remain historical in the archived reports, not substituted "
                "for current checks. The initial independent regression run also remains in "
                "stage1-independent-regressions.xml/log and stage1-independent-http-replay.json.",
                "",
            ]
        )
    rows.extend(["| Gate | Closure status | Evidence |", "|---|---|---|"])
    for name, item in evidence["gate_findings"].items():
        rows.append(f"| {name} | {item['status']} | Verification JSON |")
    rows.extend(
        [
            "",
            "## Findings in priority order",
            "",
            "P1/P2: no remaining HTTP/replay defect or amended F01 fixture blocker was "
            "reproduced in the fresh passing checks."
            if decision == "GO"
            else "P1/P2: preparation remains blocked. Inspect failed checks and open gate entries; "
            "no closure is inferred from older reports.",
            "P3 evidence limitations: authentic descending/core-value-null observations remain "
            "unavailable and explicitly waived by F01-2. No verified measurement-error wire "
            "mapping or regional completeness is claimed. G01 uses component plans, accelerated "
            "leases and explicit redelivery; G02 is writer/read-back memory, "
            "not whole-pipeline memory.",
            "[F01-2 contract](stage1-contract.md#11-fixtures-evidence-and-reconciliation), "
            "[ADR-0033](../DECISIONS.md#adr-0033---owner-authorized-f01-2-authentic-evidence-waiver).",
            "",
            "## Independently rerun HTTP and captured replay",
            "",
        ]
    )
    regressions = evidence.get("production_regressions")
    if regressions:
        replay = regressions["split_replay"]
        rows.extend(
            [
                "Migration 0007 admits http_failure before retry decisions. Real restricted "
                "repository/MinIO checks, mocking only transport, verify 429/503→200 (3 attempts, "
                "2 retries), terminal 401/403 (1 attempt, 0 retries each) and four-503 exhaustion "
                "(4 attempts, 3 retries). Numeric statuses/dispositions and safe "
                "categories persist; timings finish with positive elapsed duration; "
                "resource counters and JSON/Markdown "
                "reports stay frozen after later runs.",
                f"Actual --replay-run exits {replay['actual_cli_exit']}, preserves "
                f"{replay['plan_nodes']} predecessor nodes/{replay['completed_leaves']} leaves and "
                "one-to-one bindings after temporal/spatial splitting, with upstream transport "
                "and credential access denied. Scientific manifests and exact active generation "
                "IDs are unchanged. Full-retained and run-eligible reconciliation balance.",
                f"Replay adds {replay.get('attempt_increase', 'see evidence')} recorded-origin "
                f"attempts and {replay.get('audit_increase', 'see evidence')} audit rows. "
                "These are new-run landing/ticket/fenced-state evidence, not new science. "
                "The deterministic source plan is labelled synthetic, "
                "not regional live acceptance.",
                "[Persisted HTTP/replay assertions](../reports/stage1-http-retry-evidence.json).",
                "",
            ]
        )
    rows.extend(
        [
            "## F01-2 amendment and coverage",
            "",
            "The owner waived further authentic descending/core-null capture as disproportionate. "
            "This supersedes only those F01-1 requirements. Source/mapping/hash versions and "
            "admitted captures remain unchanged. Authentic R/A/D and ascending remain required; "
            "waivers and derivative passes never become authentic observations.",
            "[Versioned policy](stage1-f01-evidence-v2.json), "
            "[source supplement](upstream/argovis-source-supplement-v1.json). "
            "data=all, the exact fluorescence/QC supplement, attribution, source pins and "
            "fail-closed rejection of every other unsupported field remain in force.",
            "",
        ]
    )
    if fixtures:
        rows.extend(
            [
                f"Authentic corpus: {len(fixtures['bundle_audits'])} bundles, "
                f"{fixtures['response_count']} responses, {fixtures['distinct_profile_count']} "
                f"profiles, {fixtures['captured_level_occurrences']} level occurrences. "
                "2904014_040 proves 501 A-mode pressure/temperature/salinity levels with "
                "adjusted QC 1/4. Its 1002 nitrate/nitrate-QC nulls are non-core.",
                "",
                "| Representation | Authentic status | Witness IDs |",
                "|---|---|---|",
            ]
        )
        for name, item in fixtures["coverage_matrix"].items():
            witnesses = ", ".join(row["source_profile_id"] for row in item["witnesses"]) or "None"
            rows.append(f"| {name} | {item['status']} | {witnesses} |")
        rows.extend(
            [
                "",
                "Remaining required authentic gaps: "
                + (", ".join(fixtures["required_authentic_gaps"]) or "None")
                + ".",
                "Waived but unobserved authentic limitations: "
                + ", ".join(fixtures["waived_authentic_coverage_gaps"])
                + ".",
                "[Corpus evidence](../reports/stage1-fixture-corpus-coverage.json).",
                "",
            ]
        )
    f01 = evidence["acceptance"]["F01"]
    rows.extend(
        [
            "Labelled derivatives of admitted R/A captures verify descending direction in "
            "parser/canonical/Parquet/database, stable-ID preference and distinct A/D fallback "
            "keys with duplicate-key enforcement. R/A derivatives introduce JSON nulls in "
            "present pressure/temperature/salinity value columns; matching QC/unit/mode and "
            "ordinals survive parser, canonical missing_reason/hash, restricted PostgreSQL "
            "publication and Parquet. Tests distinguish absent variables, missing QC, counterpart "
            "nulls and non-core nitrate nulls. Persisted provenance enumerates synthetic "
            "direction/identity/time/location/value changes and basis checksums.",
            "Repeated pressure remains a labelled derivative. Errors remain model/storage/Parquet "
            "tests, without an invented source field or authentic wire-parser claim.",
            f"Amended fixture gate passed: **{f01.get('amended_fixture_gate_passed', False)}**. "
            "Passed derivative cases and provenance are separate fields in the verification JSON.",
            "",
            "## Component scope and next gate",
            "",
            "G01: real Redis/Celery prefork ACK/fault/recovery/cancellation/deadline/Beat "
            "evidence. "
            "G02: spill-backed [100000,1] Parquet groups, Zstd 3, 100001 rows under the enforced "
            "memory cgroup, measured RSS below 1 GiB, typed pandas deep-memory/index and ratio. "
            "G03: persisted accounting, timings, availability, coverage/gaps and frozen reports "
            "plus the independently reproduced HTTP/replay paths.",
            "[Broker](../reports/stage1-broker-evidence.json), "
            "[memory/format](../reports/stage1-parquet-resource.json), "
            "[persisted reporting](../reports/stage1-ingestion-example.json).",
            "",
            f"**{decision} specifically for preparing isolated Jan–Mar 2025 acceptance.** "
            "No acceptance environment or live run was created during this implementation "
            "verification snapshot. Subsequent preparation is reported separately below. "
            "Full acceptance/owner opt-in "
            "and actual-head CI remain outstanding; Stage 2 remains blocked. No live "
            "discovery/capture, credential/private-original access, cloud provisioning, "
            "commit, push or PR occurred.",
        ]
    )
    preparation_path = REPORTS / "stage1-acceptance-preparation.json"
    if preparation_path.exists():
        preparation = json.loads(preparation_path.read_text())
        rows += [
            "",
            "## Historical isolated preparation evidence — command withdrawn",
            "",
            "This earlier preparation GO does not override the current NO-GO. Its source "
            "digest and tests are historical; the command remains withdrawn.",
            f"Prepared UTC: `{preparation['prepared_at_utc']}`; session "
            f"`{preparation['session']}`; prepared source SHA-256 "
            f"`{preparation['source_sha256']}`. Matches current source: "
            f"`{preparation['source_sha256'] == source_hash()}`.",
            "The persisted preparation proof records restricted PostgreSQL/database marker "
            "and zero runs/science, private bucket read-back and IAM control denial, "
            "Redis database/prefix, acknowledged queue task, live-disabled admission refusal, "
            "actual Compose labels/internal network and disjoint development volume IDs.",
            f"Services stopped: `{preparation['services_stopped']}`; live executed: "
            f"`{preparation['live_executed']}`. No exposed ports or upstream network "
            "were created during preparation. Disposable data is retained for review.",
            "[Preparation policy and owner command](stage1-acceptance-preparation.md), "
            "[persisted isolation proof](../reports/stage1-acceptance-preparation.json), "
            "[historical preparation checks]"
            "(../reports/stage1-acceptance-preparation-checks.json).",
            "",
            "**Prepared for review; live execution requires separate owner opt-in.** "
            "Actual-head CI, full acceptance and its gate review remain outstanding. "
            "Stage 2 remains blocked.",
        ]
    interruption_path = REPORTS / "stage1-acceptance-interruption-evidence.json"
    if interruption_path.exists():
        interruption = json.loads(interruption_path.read_text())
        leaf_counts = {}
        for chunk in interruption["chunks"]:
            if chunk["leaf"]:
                state = chunk["state"]
                leaf_counts[state] = leaf_counts.get(state, 0) + chunk["count"]
        science = interruption["science"][0]
        rows += [
            "",
            "## Subsequent owner execution — incomplete",
            "",
            f"The owner interrupted the prepared run. Persisted evidence shows "
            f"{leaf_counts.get('complete', 0)} complete, {leaf_counts.get('failed', 0)} "
            f"failed and {leaf_counts.get('quarantined', 0)} quarantined leaves out of "
            f"{sum(leaf_counts.values())}; {science['profiles']} profiles and "
            f"{science['levels']} levels were committed. Coverage is incomplete; "
            "there is no full-acceptance or replay success claim.",
            f"Evidence captured UTC: `{interruption['captured_at_utc']}`. "
            "The agent stopped remaining isolated containers without deleting data, "
            "accessing credentials/private originals or restarting live ingestion. "
            "The provisional run remains open with its existing budget.",
            "The historical owner execution command is withdrawn pending review. "
            "Progress and interruption cleanup were corrected and tested offline; "
            "the old session source seal is not silently changed. Failed/quarantined "
            "coverage requires review before a new owner live decision.",
            "[Persisted interruption evidence]"
            "(../reports/stage1-acceptance-interruption-evidence.json), "
            "[provisional report](../reports/stage1-acceptance-live-interrupted.json). "
            "Full acceptance and actual-head CI remain outstanding; Stage 2 stays blocked.",
        ]
    (ROOT / "docs/stage1-gate.md").write_text("\n".join(rows) + "\n")


def fixture_gate_run() -> int:
    """Refresh authentic F01 evidence; preserve full-suite results with their source/time."""
    REPORTS.mkdir(exist_ok=True)
    previous_path = REPORTS / "stage1-verification.json"
    previous = json.loads(previous_path.read_text())
    if "previous_full_verification" in previous:
        prior_path = ROOT / previous["previous_full_verification"]["path"]
        prior = json.loads(prior_path.read_text())
    else:
        prior = previous
        prior_path = REPORTS / ("stage1-full-verification-" + prior["source_tree_sha256"] + ".json")
        if not prior_path.exists():
            prior_path.write_bytes(previous_path.read_bytes())
    tested_source = source_hash()
    environment = {name: os.environ[name] for name in os.environ if name != "ARGOVIS_API_KEY"}
    environment["UV_OFFLINE"] = "true"
    uv = ["uv", "run", "--all-packages", "--frozen", "--offline"]
    commands = {
        "python_lint": [*uv, "ruff", "check", "."],
        "python_format": [*uv, "ruff", "format", "--check", "."],
        "python_types": [*uv, "mypy"],
        "fixture_assertions": [
            *uv,
            "python",
            "-m",
            "pytest",
            "tests/stage1/test_recorded_fixtures.py",
            "tests/stage1/test_discovery.py",
            "tests/stage1/test_capture.py",
            "tests/stage1/test_source_supplement.py",
            "tests/stage1/test_fixture_derivatives.py",
            "-q",
            "--tb=short",
            "--junitxml=reports/stage1-fixture-gate.xml",
        ],
        "new_bundle_audit": [
            *uv,
            "python",
            "scripts/audit_stage1_fixtures.py",
            "tests/fixtures/argovis/recorded/9efe8f4e713c44a1a2964407e52b9a45",
            "--output",
            "reports/stage1-fixture-9efe8f4e-coverage.json",
        ],
        "corpus_audit": [
            *uv,
            "python",
            "scripts/audit_stage1_fixtures.py",
            "--corpus",
            "--output",
            "reports/stage1-fixture-corpus-coverage.json",
        ],
        "discovery_audit": [
            *uv,
            "python",
            "scripts/audit_stage1_fixtures.py",
            "tests/fixtures/argovis/discovery/e5b3f14e549d49e69ed77fde03d40d8c",
            "--discovery",
            "--output",
            "reports/stage1-discovery-e5b3f14e-coverage.json",
        ],
        "secrets_recorded_corpus": [
            str(ROOT / ".cache/tools/gitleaks"),
            "dir",
            "tests/fixtures/argovis",
            "--redact=100",
            "--no-banner",
            "--max-decode-depth=3",
            "--config",
            str(ROOT / ".gitleaks.toml"),
        ],
        "secrets_current": [*uv, "python", "scripts/security/scan.py", "current"],
        "secrets_history": [*uv, "python", "scripts/security/scan.py", "history"],
        "diff_whitespace": ["git", "diff", "--check"],
    }
    checks = {}
    for name, command in commands.items():
        start = time.monotonic()
        log = REPORTS / ("stage1-fixture-gate-" + name + ".log")
        with log.open("wb") as output:
            try:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=180,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write(b"Verification exceeded its 180-second bound.\n")
        checks[name] = {
            "exit_code": code,
            "seconds": time.monotonic() - start,
            "evidence": str(log.relative_to(ROOT)),
        }
    corpus = json.loads((REPORTS / "stage1-fixture-corpus-coverage.json").read_text())
    suite = ET.parse(REPORTS / "stage1-fixture-gate.xml").getroot().find("testsuite")
    assert suite is not None
    names = [
        item.attrib["name"]
        for item in suite.findall("testcase")
        if not any(item.find(tag) is not None for tag in ("failure", "error", "skipped"))
    ]
    ids = re.findall(
        r"^\| ([TGISRPCBDFNX]\d{2}[a-c]?) \|", (ROOT / "docs/stage1-contract.md").read_text(), re.M
    )
    assert len(ids) == len(set(ids)) == 86
    acceptance = {
        case_id: {
            "status": "pending_end_to_end_acceptance",
            "component_tests": [name for name in names if case_id in name]
            if checks["fixture_assertions"]["exit_code"] == 0
            else [],
            "prior_component_tests": prior["acceptance"][case_id]["component_tests"],
            "prior_evidence_source_sha256": prior["source_tree_sha256"],
        }
        for case_id in ids
    }
    acceptance["F01"].update(
        recorded_input_evidence="reports/stage1-fixture-corpus-coverage.json",
        remaining_representation_gaps=corpus["representation_gaps"],
        minimum_recorded_corpus_satisfied=corpus["minimum_F01_satisfied"],
        authentic_A_evidence="reports/stage1-fixture-9efe8f4e-coverage.json",
        synthetic_obligations=corpus["synthetic_obligations"],
    )
    unchanged = source_hash() == tested_source
    green = unchanged and all(item["exit_code"] == 0 for item in checks.values())
    findings = {
        name: {**item, "verification_scope": "historical_full_suite"}
        for name, item in prior["gate_findings"].items()
        if name != "S1-G04"
    }
    findings["S1-G04"] = {
        "priority": "P1",
        "status": "open_authentic_representation_gaps"
        if not corpus["minimum_F01_satisfied"]
        else "authentic_minimum_observed",
        "remaining_representation_gaps": corpus["representation_gaps"],
        "evidence": "reports/stage1-fixture-corpus-coverage.json",
        "candidate_capture": "2904014_040_complete_A_mode_not_descending_or_core_null",
        "next_candidate": None,
        "disposition": "F01-2: no further descending/core-null discovery; "
        "full derivative and database verification required",
    }
    evidence = {
        "status": "NO_GO_fixture_verification_failed"
        if not green
        else (
            "NO_GO_incomplete_F01_corpus"
            if not corpus["minimum_F01_satisfied"]
            else "F01_observed_full_verification_required"
        ),
        "verification_scope": "Fixture-gate update only; full-suite proofs are historical",
        "verified_at_actual_utc": datetime.now(UTC).isoformat(),
        "source_tree_sha256": tested_source,
        "source_unchanged_during_checks": unchanged,
        "contract": "stage1-v2",
        "contract_gate": "owner_confirmed_Astra_GO",
        "checks": checks,
        "pytest_suites": {
            "fixture_assertions": {
                key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")
            }
        },
        "acceptance_case_count": 86,
        "acceptance": acceptance,
        "fixtures": corpus,
        "previous_full_verification": {
            "path": str(prior_path.relative_to(ROOT)),
            "source_tree_sha256": prior["source_tree_sha256"],
            "verified_at_actual_utc": prior["verified_at_actual_utc"],
            "scope": "Historical; not rerun after fixture-only changes",
            "passing_checks": sum(item["exit_code"] == 0 for item in prior["checks"].values()),
            "check_count": len(prior["checks"]),
            "python_tests": sum(item["tests"] for item in prior["pytest_suites"].values()),
        },
        "production_regressions": prior["production_regressions"],
        "production_regressions_scope": "historical_full_suite",
        "gate_findings": findings,
        "source_supplement": prior["source_supplement"],
        "uncommitted_work": True,
        "gate_report": "docs/stage1-gate.md",
        "live_acceptance": "not_executed; F01 blocks acceptance preparation",
        "private_originals": "not_accessed",
        "credential_access": "none",
        "CI": "not_run_on_remote_head",
    }
    previous_path.write_text(json.dumps(evidence, indent=2) + "\n")
    rows = [
        "# Stage 1 fixture-gate verification — " + evidence["status"],
        "",
        "Generated from persisted audits, JUnit and redacted scan logs.",
        "",
        evidence["verification_scope"] + ".",
        f"Source SHA-256: `{tested_source}`; unchanged during checks: {unchanged}.",
        "",
        "| Check | Exit | Evidence |",
        "|---|---:|---|",
    ]
    rows.extend(
        f"| {name} | {item['exit_code']} | [{name}]({Path(item['evidence']).name}) |"
        for name, item in checks.items()
    )
    rows.extend(
        [
            "",
            f"Authentic corpus: {len(corpus['bundle_audits'])} bundles, "
            f"{corpus['response_count']} responses, {corpus['distinct_profile_count']} "
            f"profiles, {corpus['captured_level_occurrences']} level occurrences.",
            "2904014_040 proves 501 A-mode adjusted pressure/temperature/salinity "
            "values/QC. Direction is ascending; nitrate/nitrate QC account for all "
            "1002 null cells. Non-core fluorescence is preserved under the exact supplement.",
            "",
            "Missing authentic representations:",
            "",
        ]
    )
    rows.extend("- " + gap for gap in corpus["representation_gaps"])
    rows.extend(
        [
            "",
            "[Corpus matrix](stage1-fixture-corpus-coverage.json). "
            "All 86 end-to-end cases remain pending. F01-2 keeps waived authentic gaps "
            "unobserved; no further descending/core-null capture. A fixture-only update "
            "does not establish preparation readiness; fresh full offline evidence is required.",
            "",
            f"[Historical full verification]({prior_path.name}) retains its "
            "18 successful checks and 362 Python tests at the archived source/time. "
            "Database, broker, memory and web checks were not rerun in this F01-stop branch.",
            "",
            "No agent live call, private-original/credential access, "
            "full acceptance preparation, cloud provisioning or Git publication occurred.",
        ]
    )
    (REPORTS / "stage1-verification.md").write_text("\n".join(rows) + "\n")
    write_gate_report(evidence)
    return 0 if green else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    raise SystemExit(fixture_gate_run() if args.fixtures_only else run())
