# Interrupted Stage 1 acceptance — incomplete

The owner command waited silently while the isolated worker processed the full
Indian Ocean Jan–Mar 2025 plan. Its per-run cap was six hours. Two Ctrl+C presses
interrupted both waiting and the original cleanup. This did not establish a hang
or a successful run.

Read-only persisted evidence captured at `2026-10-07T08:26:31.637809+00:00`:

| Outcome | Leaf chunks |
|---|---:|
| Complete | 120 |
| Failed, HTTP 404 | 44 |
| Quarantined, upstream_data_warning | 4 |
| Quarantined, canonical_output_limit | 4 |
| Planned | 1088 |
| Total | 1260 |

Committed: 819 profiles, 572,347 measurement levels and 67 active partitions.
The provisional persisted report shows incomplete coverage and no final frozen
evidence. No 404 is converted to verified empty coverage and no quarantine is waived.

Remaining controller/client/service containers were stopped. Database science,
objects and catalogue records remain intact. The run remains open under its
original budget: process interruption does not infer operator cancellation or
extend the deadline. No live worker was restarted, no upstream call was made, and
no credential, worker log or private capture original was accessed during diagnosis.

P2 wrapper defect: silent waiting and repeated Ctrl+C could leave service/one-off
containers running. Corrected in scripts/stage1_acceptance.py: bounded periodic
read-only progress counters, live-worker exit detection, interrupted client reaping,
SIGINT-protected cleanup, project-labelled service/one-off stops, persisted cleanup
results and a fixed exit-130 message without a traceback. No production HTTP policy,
scientific mapping, source contract, resource/retry limit or cancellation semantics
changed.

Fresh verification: 354 offline unit tests, zero failures/errors/skips; 22 wrapper
tests cover real child-process interruption, repeated SIGINT, worker loss,
incomplete-report rejection and safe output/credential guards. The real restricted
repository progress query returned the leaf counts above without source access.
Lint, formatting, type checks and redacted current/history secret scans passed.
Historical integration/fault/memory suites were not relabelled as rerun this turn.

**NO-GO for acceptance certification or another live attempt pending review.**
The 44 failed and 8 quarantined chunks require source/coverage review. The old
prepared source seal is unchanged and intentionally fails the changed-source
guard; its owner command is withdrawn. No new session or owner retry was prepared.
Actual-head CI and full acceptance remain outstanding; Stage 2 stays blocked.
Nothing was staged, committed, pushed or provisioned in the cloud.

[Persisted counters](stage1-acceptance-interruption-evidence.json),
[provisional report](stage1-acceptance-live-interrupted.json),
[fresh checks](stage1-acceptance-interruption-checks.json),
[read-only progress](stage1-acceptance-progress-check.json).
