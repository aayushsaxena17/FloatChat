"""Consolidate persisted offline evidence; never operate a service or live input."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.stage1_verify import source_hash  # noqa: E402

REPORTS = ROOT / "reports"


def read(name):
    return json.loads((REPORTS / name).read_text())


def reference(path, fragment):
    for number, line in enumerate((ROOT / path).read_text().splitlines(), 1):
        if fragment in line:
            return {"file": path, "line": number}
    raise ValueError("review_reference_missing")


def requirement(case):
    ref = reference("docs/stage1-contract.md", "| " + case + " |")
    row = (ROOT / ref["file"]).read_text().splitlines()[ref["line"] - 1]
    return {**ref, "case": case, "exact_assertion": row.split("|")[3].strip()}


def generate():
    current = source_hash()
    verification = read("stage1-verification.json")
    model = read("stage1-regional-capacity-model.json")
    terminal = read("stage1-terminalization-0007-rehearsal.json")
    failures = read("stage1-coverage-failure-review.json")
    assert verification["source_tree_sha256"] == current
    assert verification["source_unchanged_during_checks"]
    assert all(row["exit_code"] == 0 for row in verification["checks"].values())
    assert model["source_files_unchanged"] and model["budget_runs"] == 1
    for path, digest in model["source_file_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    assert terminal["migration"] == "0007_http_replay" and terminal["after_commit_retry_recognized"]
    blockers = [
        {
            "id": "BR-404",
            "priority": "P1",
            "state": "decision-and-evidence-required",
            "finding": "44 failed pre-inventory selections do not prove empty coverage",
            "requirements": [requirement(x) for x in ("G04", "G05", "F02")],
            "evidence": [
                "reports/stage1-coverage-failure-review.json",
                "reports/stage1-http-source-semantics.json",
            ],
            "limit": "Status-only historical responses; deployed compatibility/bodies unknown",
            "implementation": "Strict failure remains. Inactive exact-role proposal oracle tested",
            "decision": "Choose strict A or explicitly qualified S1-SOURCE-2 B; B is not active",
            "closure": "A: corrected coherent complete selections/independent source census. "
            "B: precise amendment approval plus deployment-attested complete bounded triples",
            "authorization": "Any new upstream validation/capture or policy activation",
        },
        {
            "id": "BR-SOURCE-LOSS",
            "priority": "P1",
            "state": "decision-and-evidence-required",
            "finding": "Four degenerate_levels selections cannot certify affected science",
            "requirements": [requirement(x) for x in ("C03", "S03", "F02")],
            "evidence": [
                "reports/stage1-coverage-failure-review.json",
                "reports/stage1-discarded-input-science.json",
            ],
            "limit": "Pinned translator models show possible losses, not authentic "
            "discarded inputs",
            "implementation": "Whole-chunk quarantine unchanged. Profile-exclusion proposal "
            "inactive",
            "decision": "A needs corrected complete science; B needs explicit "
            "exclusion/acceptance amendment",
            "closure": "Reconstruct discarded measurements under A, or approve qualified "
            "B and persist "
            "whole-profile raw provenance, IDs/selections/returned and unknown lost levels",
            "authorization": "Policy/exclusion activation and any independent source acquisition",
        },
        {
            "id": "BR-CAPACITY",
            "priority": "P1",
            "state": "evidence-required",
            "finding": "Original aggregate cap exhausted; actual regional envelope remains unknown",
            "requirements": [requirement(x) for x in ("B01", "B02", "B04", "N08", "F06")],
            "evidence": [
                "reports/stage1-regional-capacity-model.json",
                "reports/stage1-coverage-failure-review.json",
            ],
            "limit": "One synthetic admitted-fixture model cannot bound live profile "
            "count, depths, "
            "canonical sizes, hot-slot concentration or further recovery/rebuild amplification",
            "implementation": "Per-publication SHA-bound certificate removes redundant encodings; "
            "all actual work and conservative process-loss reservations stay charged",
            "decision": "No cap increase, new hidden budgets or smaller acceptance geometry",
            "closure": "Justified actual-region envelope including retained slot growth "
            "and retry/rebuild "
            "margin fits 10 GiB, 1 GiB/worker and unchanged six-hour run limit",
            "authorization": "Any live population measurement; no new acceptance run yet",
        },
        {
            "id": "BR-OPEN-RUN",
            "priority": "P1",
            "state": "decision-required",
            "finding": "Original run is still open without frozen incomplete evidence",
            "requirements": [requirement(x) for x in ("C02", "C08", "C11", "F03")],
            "evidence": [
                "reports/stage1-terminalization-0007-rehearsal.json",
                "docs/stage1-terminalization-review.md",
            ],
            "limit": "Migration-0007 replica inspected; original DB/functions/objects not operated",
            "implementation": "Concrete guarded restricted-role terminalizer and closed-state "
            "recovery tested",
            "decision": "Separately review/approve deadline-only closure; never restart ingestion",
            "closure": "Approved original operation validates exact saved "
            "identities/manifests/counters, "
            "closes partial with 120 complete/1132 failed/8 quarantined and one frozen report",
            "authorization": "Operating original database and calling its existing finalizer",
        },
        {
            "id": "BR-HTTP-REPLAY",
            "priority": "P1",
            "state": "closed-at-offline-component-scope",
            "finding": "Previously reported HTTP disposition and adaptive predecessor "
            "replay defects",
            "requirements": [requirement(x) for x in ("B03", "F04")],
            "evidence": [
                "reports/stage1-http-retry-evidence.json",
                "reports/stage1-verification.json",
            ],
            "limit": "Mocked HTTP and captured predecessors, not live regional success",
            "implementation": "Migration 0007 aligned dispositions and immutable validated "
            "topology bindings",
            "decision": "No source-policy waiver inferred",
            "closure": "Fresh restricted PG status/retry/exhaustion/frozen reporting and actual "
            "--replay-run temporal/spatial tests with credential/upstream access denied",
            "authorization": "None for completed offline tests",
        },
        {
            "id": "BR-TEST-SEED",
            "priority": "P2",
            "state": "closed-at-offline-component-scope",
            "finding": (
                "Shared SQL test seed lease expired after a long independent processor probe"
            ),
            "requirements": [requirement("F05")],
            "evidence": [
                "reports/stage1-first-final-64be1492/stage1-database.xml",
                "reports/stage1-verification.json",
            ],
            "limit": "First concurrent verification failed; never counted as a pass",
            "implementation": "Refresh only the disposable seed controller lease between "
            "independent SQL cases; production guards and all work deadlines/budgets unchanged",
            "decision": "Heavy model and final broker verification run separately on this small VM",
            "closure": "Complete fresh suite including controller expiry/fencing tests passes",
            "authorization": "None for isolated offline test setup",
        },
        {
            "id": "BR-CI",
            "priority": "P2",
            "state": "evidence-required",
            "finding": "Required CI has not run on the actual eventual Stage 1 head",
            "requirements": [requirement("F05")],
            "evidence": ["reports/stage1-verification.json"],
            "limit": "Local offline verification of an uncommitted source digest is "
            "not remote head CI",
            "implementation": "Local offline checks complete; no commit/push/PR",
            "decision": "Publishing remains prohibited in this task",
            "closure": "Separately authorized actual-head required CI passes and "
            "evidence is retained",
            "authorization": "Commit/push/PR or remote CI operation",
        },
        {
            "id": "BR-FULL-ACCEPTANCE",
            "priority": "P1",
            "state": "evidence-required",
            "finding": "No successful complete isolated Jan–Mar acceptance and captured replay",
            "requirements": [requirement(x) for x in ("T03", "T04", "F04", "F05", "X01")],
            "evidence": ["reports/stage1-acceptance-live-interrupted.json"],
            "limit": "Historical preparation GO withdrawn; incomplete original data "
            "stays preserved",
            "implementation": "No acceptance preparation/execution in this offline task",
            "decision": "Resolve all preceding policy/capacity/review gates before "
            "preparing a fresh run",
            "closure": "New reviewed isolated environment, explicit live opt-in, "
            "complete persisted "
            "coverage/reconciliation/replay evidence under the accepted policy and limits",
            "authorization": "Fresh preparation and live execution separately",
        },
    ]
    action_gates = {
        "original_terminalization": (
            "GO_for_separate_procedure_review_only; approval/execution pending"
        ),
        "bounded_source_validation_capture": (
            "NO_GO_execution; precise policy and capture scope unapproved"
        ),
        "fresh_acceptance_preparation": (
            "NO_GO; source-policy and actual-population feasibility unresolved"
        ),
        "live_acceptance_execution": "NO_GO; preparation, owner opt-in, CI and full evidence "
        "outstanding",
    }
    implementation_refs = {
        "BR-404": [
            reference("packages/core/src/floatchat_core/ingestion/landing.py", "http_failure")
        ],
        "BR-SOURCE-LOSS": [
            reference(
                "packages/core/src/floatchat_core/ingestion/argovis.py", "upstream_data_warning"
            )
        ],
        "BR-CAPACITY": [
            reference("packages/core/src/floatchat_core/ingestion/numeric.py", "run_limit: int"),
            reference("tests/stage1/regional_capacity_probe.py", "weights ="),
        ],
        "BR-OPEN-RUN": [reference("scripts/stage1_terminalize.py", "def finalization_sql")],
        "BR-HTTP-REPLAY": [
            reference("infra/migrations/versions/0007_http_replay.sql", "http_failure"),
            reference("packages/core/src/floatchat_core/ingestion/source.py", "predecessor_run"),
        ],
        "BR-CI": [reference(".github/workflows/stage0.yml", "name:")],
        "BR-TEST-SEED": [
            reference(
                "tests/stage1/test_database.py", "def fresh_seed_controller_for_independent_case"
            )
        ],
        "BR-FULL-ACCEPTANCE": [reference("docs/stage1-contract.md", "## 12.")],
    }
    for blocker in blockers:
        blocker["implementation_references"] = implementation_refs[blocker["id"]]
    evidence_paths = {
        *[path for b in blockers for path in b["evidence"]],
        "docs/stage1-source-policy-proposal.md",
        "reports/stage1-blocker-focused.xml",
        "reports/stage1-terminalization.xml",
        "reports/stage1-regional-capacity.xml",
        "reports/stage1-regional-superseded-attempt.json",
        "reports/stage1-regional-timeout-attempt/stage1-regional-capacity.xml",
    }
    inputs = [
        {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
        for path in sorted(evidence_paths)
    ]
    measured = {
        k: model[k]
        for k in (
            "run_id",
            "root_chunks",
            "planned_incoming_occurrences",
            "planned_current_profiles_after_8_moves",
            "planned_incoming_levels",
            "levels_per_occurrence",
            "occupied_month_tile_slots",
            "month_slices",
            "state",
            "canonical_bytes",
            "cap_bytes",
            "elapsed_seconds",
            "pipeline_peak_rss_bytes",
            "cgroup_memory_peak_bytes",
            "cgroup_memory_limit_bytes",
            "cgroup_memory_events",
            "operations",
            "measured_incoming_canonical_sizes",
            "bounded_recovery",
            "complete_delivery_noops",
            "current_science",
            "progress",
            "injected_publication_rebuild",
        )
    }
    envelope_completed = (
        model["state"] == "complete"
        and model["current_science"]["profiles"] == model["planned_current_profiles_after_8_moves"]
        and model["current_science"]["levels"]
        == model["planned_current_profiles_after_8_moves"] * model["levels_per_occurrence"]
        and model["deadlines_limits_unchanged"]
        and model["canonical_bytes"] <= model["cap_bytes"]
        and model["elapsed_seconds"] <= 21600
        and model["pipeline_peak_rss_bytes"] <= model["cgroup_memory_limit_bytes"]
        and "oom_kill 0" in model["cgroup_memory_events"]
    )
    strict_cgroup_peak = model["cgroup_memory_peak_bytes"] <= model["cgroup_memory_limit_bytes"]
    checks = verification["checks"]
    output = {
        "kind": "authoritative_stage1_offline_blocker_matrix_v1",
        "decision": "NO_GO",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_tree_sha256": current,
        "exact_source_verification": "Full local suite bound to this tree; capacity runtime source "
        "pins match",
        "checks": checks,
        "python_suites": verification["pytest_suites"],
        "component_gate_assessments": {
            "S1-G01": {
                "state": "supported_at_real_broker_prefork_component_scope",
                "fresh_evidence": "reports/stage1-broker-evidence.json",
                "qualifications": (
                    "Accelerated leases and explicit redelivery; no live regional proof"
                ),
            },
            "S1-G02": {
                "state": "supported_at_writer_readback_scope",
                "fresh_evidence": "reports/stage1-parquet-resource.json",
                "pipeline_evidence": "reports/stage1-regional-capacity-model.json",
                "qualifications": (
                    "Writer and synthetic whole-worker envelope are separate measures"
                ),
            },
            "S1-G03": {
                "state": "http_replay_reporting_components_supported_regional_gate_open",
                "fresh_evidence": "reports/stage1-http-retry-evidence.json",
                "qualifications": (
                    "Original frozen evidence, regional completeness and capacity pending"
                ),
            },
            "S1-G04": {
                "state": "owner_amended_F01_2_minimum_supported",
                "fresh_evidence": "reports/stage1-fixture-corpus-coverage.json",
                "qualifications": "Waived authentic gaps remain unobserved; no regional census",
            },
        },
        "historical_evidence_limits": {
            "original_forensics": (
                "Saved immutable reports, not fresh reads of the preserved database"
            ),
            "source_witnesses": (
                "Pinned previously executed translator models, not lost authentic inputs"
            ),
            "prior_verification": (
                "Previous source digest 582d4599 and its 412 tests are historical"
            ),
            "superseded_model": (
                "Stopped experiment; not a capacity pass or part of current run budget"
            ),
            "timed_out_model": "One-hour harness timeout; no completed capacity result",
            "first_final_verification": (
                "64be1492: 17 SQL cases failed after the shared lease expired; "
                "Beat teardown also exceeded its five-second test bound "
                "during concurrent model work. "
                "These failures are retained and never substituted for fresh serial verification."
            ),
        },
        "input_sha256": inputs,
        "blockers": blockers,
        "next_action_gates": action_gates,
        "capacity_model": measured,
        "capacity_feasibility": {
            "canonical_time_rss_envelope_completed": envelope_completed,
            "strict_cgroup_peak_within_limit": strict_cgroup_peak,
            "measured_envelope_completed_within_all_memory_bounds": (
                envelope_completed and strict_cgroup_peak
            ),
            "actual_regional_feasibility_proved": False,
            "remaining_limits": [
                "Unknown full regional profiles/levels/canonical sizes/slot distribution",
                "One platform/metadata set and no live transport latency",
                "One recovery and rebuild, not the complete permitted retry envelope",
                "One worker pipeline at a time, not two simultaneous large tasks",
            ],
        },
        "original_evidence": {
            "failed_404_selections": 44,
            "quarantines": 8,
            "canonical_bytes": failures["run"]["canonical_bytes"],
            "scientific_state": failures["science_after_review"],
            "run_open": True,
            "operated_this_turn": False,
        },
        "inactive_source_policy": "S1-SOURCE-2; strict A remains active; B requires exact approval",
        "f01_limitations": "F01-2 minimum preserved; descending/present-core-null authentic "
        "unobserved; "
        "repeated pressure synthetic; errors normalized/storage only, no verified wire mapping",
        "actual_head_ci": "outstanding",
        "full_acceptance": "outstanding",
        "stage2": "blocked",
    }
    (REPORTS / "stage1-blocker-review.json").write_text(json.dumps(output, indent=2) + "\n")
    rows = [
        "# Stage 1 consolidated offline review — NO-GO",
        "",
        f"Exact final source SHA-256: `{current}`. All "
        f"{sum(c['exit_code'] == 0 for c in checks.values())}/{len(checks)} local checks pass. "
        "The current capacity model's runtime source hashes match this tree. Historical "
        "preparation GO and the superseded partial model do not override this decision.",
        "",
        "## Authoritative blocker matrix",
        "",
        "| Finding | State | Required decision/evidence |",
        "|---|---|---|",
    ]
    for b in blockers:
        refs = ", ".join(f"[{r['case']}](../{r['file']}#L{r['line']})" for r in b["requirements"])
        rows.append(
            f"| {b['priority']} {b['id']}: {b['finding']} ({refs}) | "
            f"{b['state']} | {b['closure']} |"
        )
    rows += [
        "",
        "Exact acceptance wording, source limitations, implementation/policy separation, "
        "closure tests, authorization boundaries and input checksums are in "
        "[the single machine-readable matrix](stage1-blocker-review.json).",
        "",
        "## Source recommendation — inactive",
        "",
        "Review S1-SOURCE-2 option B as the smallest honest qualified delivered-population "
        "amendment. The [exact proposed wording](../docs/stage1-source-policy-proposal.md) "
        "does not activate either optional 404 receipt or whole-profile exclusion. "
        "Strict A remains binding. Historical 44 failures and eight quarantines stay unchanged. "
        "No authentic missing source science is inferred from pressure "
        "uniqueness or synthetic tests.",
        "",
        "## One-run resource envelope",
        "",
        f"The synthetic model plans {model['planned_incoming_occurrences']} full 501-level "
        f"occurrences ({model['planned_incoming_levels']:,} levels), uneven 40/16/8 populations "
        "per time slice across nine month/tile slots. All 1,260 roots are persisted at admission. "
        "The plan has five January, four February and five March slices; four stable IDs "
        "move with newer revisions across month boundaries. It includes one fenced process-loss "
        "reservation/recovery, one injected precommit base-change rebuild and three complete "
        "lost-ack redeliveries. It is one run and one 10 GiB budget, "
        "never combined independent runs.",
        f"Measured state `{model['state']}`; canonical bytes {model['canonical_bytes']:,} / "
        f"{model['cap_bytes']:,}; elapsed {model['elapsed_seconds']:.1f}s; "
        f"whole-pipeline peak RSS {model['pipeline_peak_rss_bytes'] / 1024**2:.1f} MiB; "
        f"cgroup peak {model['cgroup_memory_peak_bytes'] / 1024**2:.1f} MiB / 1,024 MiB. "
        "The database and MinIO have separate disposable service cgroups; this is worker pipeline "
        "memory, not whole-service aggregate memory. G02 writer memory remains a separate measure.",
        f"Measured canonical/time/RSS envelope fit: **{'YES' if envelope_completed else 'NO'}**. "
        f"Strict cgroup peak <=1 GiB: **{'YES' if strict_cgroup_peak else 'NO'}**. "
        "The cgroup was configured at exactly 1 GiB and recorded no OOM, but its peak counter "
        "exceeded that limit slightly. No strict whole-cgroup peak pass is claimed, and no "
        "memory limit is raised or silently reinterpreted. "
        "Actual regional feasibility: **unproved**. This memory measurement is one worker pipeline "
        "at a time; it does not prove two simultaneously large tasks fit the deployment cgroup.",
        f"Current committed science: {model['current_science']['profiles']:,} profiles and "
        f"{model['current_science']['levels']:,} levels. These counts are distinct from planned "
        "incoming occurrences and normalization work repeated during recovery/rebuilding. "
        "The derivatives reuse one platform and its recorded metadata; they do not stress the "
        "original run's 584-float metadata diversity or live request latency.",
        "Remaining amplification comes from incoming normalization, "
        "retained DB/spool certification "
        "and local/first-payload scientific verification. Per-operation/per-publication actual "
        "charges and profile canonical sizes reconcile against the "
        "persisted canonical_work ledger. "
        "Repeated scientific re-encoding of equal-byte temporary/final objects is removed without "
        "skipping their SHA/schema/count checks. Every fresh intent/recovery certifies again.",
        "Feasibility decision: this measured envelope is a capacity model "
        "only. The actual region's "
        "profile/level population, canonical sizes, occupied-slot concentration and required extra "
        "rebuilds are not bounded by current evidence. No arbitrary scaling factor or the model's "
        "unused allowance certifies them. If the required actual envelope exceeds 10 GiB or the "
        "six-hour/1 GiB bounds, acceptance is infeasible under the current contract; return that "
        "decision for review, without increasing caps or shrinking geography/time.",
        "",
        "## Terminalization",
        "",
        "[Concrete review-only command and recovery procedure]"
        "(../docs/stage1-terminalization-review.md), "
        "[migration-0007 rehearsal](stage1-terminalization-0007-rehearsal.json). "
        "Exactly 120 complete/44 failed/eight quarantine/1,088 planned model leaves reduce to "
        "120 complete/1,132 failed/eight quarantine, closed/partial with one frozen record. "
        "Actual connection termination before commit rolls back; after commit the original "
        "open-snapshot command recognizes the closed state and validates it idempotently. "
        "The small science/catalogue fixture is administrative, not an original object clone. "
        "Original deployed function equality remains a mandatory guarded post-approval preflight.",
        "",
        "## Separate next-action decisions",
        "",
    ]
    rows += [f"- {name}: **{decision}**." for name, decision in action_gates.items()]
    rows += [
        "",
        "S1-G01 remains supported at real broker/prefork component scope, with accelerated "
        "leases and explicit redelivery qualifications. S1-G02 remains "
        "supported at writer/read-back "
        "scope; the new pipeline measurement has its own envelope. S1-G03 HTTP/replay/reporting "
        "component regressions pass, while regional source/resource/frozen-original evidence stays "
        "blocked. S1-G04/F01-2 minimum passes only its owner-amended "
        "scope; authentic descending and "
        "present-core null remain unobserved, repeated pressure is "
        "synthetic, supplied-error evidence "
        "is normalized model/storage only. No fresh capture, private "
        "original or owner credential was read.",
        "",
        "Actual-head CI and full acceptance/replay remain outstanding. No original run operation, "
        "live call, policy activation, budget reset, commit/push/PR, "
        "cloud work or Stage 2 occurred.",
    ]
    (REPORTS / "stage1-blocker-review.md").write_text("\n".join(rows) + "\n")
    # The gate is generated, excluded from the source digest, and delegates to the
    # single authoritative matrix rather than repeating a conflicting decision.
    (ROOT / "docs/stage1-gate.md").write_text(
        "# Stage 1 implementation gate — NO-GO\n\n"
        "Current authority: [consolidated review](../reports/stage1-blocker-review.md) and "
        "[single blocker matrix](../reports/stage1-blocker-review.json). "
        "Historical preparation GO is withdrawn; the original run remains stopped/open.\n\n"
        "The matrix binds all fresh checks and measured-model source pins "
        "to the exact final source "
        f"`{current}`, records each violated requirement and separates implemented components "
        "from pending policy/source/population evidence. "
        "[Full offline verification](../reports/stage1-verification.json) and "
        "[F01-2 coverage](../reports/stage1-fixture-corpus-coverage.json) "
        "remain independently inspectable. "
        "S1-SOURCE-2 is inactive. Only the terminalization procedure is ready for separate review; "
        "no original operation or live action is authorized. Actual-head CI, complete regional "
        "acceptance and Stage 2 remain blocked.\n"
    )
    print(
        json.dumps(
            {
                "decision": "NO_GO",
                "source_tree_sha256": current,
                "blockers": len(blockers),
                "original_run_operated": False,
            }
        )
    )


if __name__ == "__main__":
    generate()
