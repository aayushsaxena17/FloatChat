# Stage 1 consolidated offline review — NO-GO

Exact final source SHA-256: `ec68cfc082b2e54e1c165b634fe60f6baff464099ad2a80149cc092a0195ba7b`. All 19/19 local checks pass. The current capacity model's runtime source hashes match this tree. Historical preparation GO and the superseded partial model do not override this decision.

## Authoritative blocker matrix

| Finding | State | Required decision/evidence |
|---|---|---|
| P1 BR-404: 44 failed pre-inventory selections do not prove empty coverage ([G04](../docs/stage1-contract.md#L1034), [G05](../docs/stage1-contract.md#L1035), [F02](../docs/stage1-contract.md#L1096)) | decision-and-evidence-required | A: corrected coherent complete selections/independent source census. B: precise amendment approval plus deployment-attested complete bounded triples |
| P1 BR-SOURCE-LOSS: Four degenerate_levels selections cannot certify affected science ([C03](../docs/stage1-contract.md#L1071), [S03](../docs/stage1-contract.md#L1052), [F02](../docs/stage1-contract.md#L1096)) | decision-and-evidence-required | Reconstruct discarded measurements under A, or approve qualified B and persist whole-profile raw provenance, IDs/selections/returned and unknown lost levels |
| P1 BR-CAPACITY: Original aggregate cap exhausted; actual regional envelope remains unknown ([B01](../docs/stage1-contract.md#L1080), [B02](../docs/stage1-contract.md#L1081), [B04](../docs/stage1-contract.md#L1083), [N08](../docs/stage1-contract.md#L1109), [F06](../docs/stage1-contract.md#L1100)) | evidence-required | Justified actual-region envelope including retained slot growth and retry/rebuild margin fits 10 GiB, 1 GiB/worker and unchanged six-hour run limit |
| P1 BR-OPEN-RUN: Original run is still open without frozen incomplete evidence ([C02](../docs/stage1-contract.md#L1070), [C08](../docs/stage1-contract.md#L1076), [C11](../docs/stage1-contract.md#L1079), [F03](../docs/stage1-contract.md#L1097)) | decision-required | Approved original operation validates exact saved identities/manifests/counters, closes partial with 120 complete/1132 failed/8 quarantined and one frozen report |
| P1 BR-HTTP-REPLAY: Previously reported HTTP disposition and adaptive predecessor replay defects ([B03](../docs/stage1-contract.md#L1082), [F04](../docs/stage1-contract.md#L1098)) | closed-at-offline-component-scope | Fresh restricted PG status/retry/exhaustion/frozen reporting and actual --replay-run temporal/spatial tests with credential/upstream access denied |
| P2 BR-TEST-SEED: Shared SQL test seed lease expired after a long independent processor probe ([F05](../docs/stage1-contract.md#L1099)) | closed-at-offline-component-scope | Complete fresh suite including controller expiry/fencing tests passes |
| P2 BR-CI: Required CI has not run on the actual eventual Stage 1 head ([F05](../docs/stage1-contract.md#L1099)) | evidence-required | Separately authorized actual-head required CI passes and evidence is retained |
| P1 BR-FULL-ACCEPTANCE: No successful complete isolated Jan–Mar acceptance and captured replay ([T03](../docs/stage1-contract.md#L1027), [T04](../docs/stage1-contract.md#L1028), [F04](../docs/stage1-contract.md#L1098), [F05](../docs/stage1-contract.md#L1099), [X01](../docs/stage1-contract.md#L1110)) | evidence-required | New reviewed isolated environment, explicit live opt-in, complete persisted coverage/reconciliation/replay evidence under the accepted policy and limits |

Exact acceptance wording, source limitations, implementation/policy separation, closure tests, authorization boundaries and input checksums are in [the single machine-readable matrix](stage1-blocker-review.json).

## Source recommendation — inactive

Review S1-SOURCE-2 option B as the smallest honest qualified delivered-population amendment. The [exact proposed wording](../docs/stage1-source-policy-proposal.md) does not activate either optional 404 receipt or whole-profile exclusion. Strict A remains binding. Historical 44 failures and eight quarantines stay unchanged. No authentic missing source science is inferred from pressure uniqueness or synthetic tests.

## One-run resource envelope

The synthetic model plans 896 full 501-level occurrences (448,896 levels), uneven 40/16/8 populations per time slice across nine month/tile slots. All 1,260 roots are persisted at admission. The plan has five January, four February and five March slices; four stable IDs move with newer revisions across month boundaries. It includes one fenced process-loss reservation/recovery, one injected precommit base-change rebuild and three complete lost-ack redeliveries. It is one run and one 10 GiB budget, never combined independent runs.
Measured state `complete`; canonical bytes 7,225,605,264 / 10,737,418,240; elapsed 4129.9s; whole-pipeline peak RSS 455.1 MiB; cgroup peak 1024.6 MiB / 1,024 MiB. The database and MinIO have separate disposable service cgroups; this is worker pipeline memory, not whole-service aggregate memory. G02 writer memory remains a separate measure.
Measured canonical/time/RSS envelope fit: **YES**. Strict cgroup peak <=1 GiB: **NO**. The cgroup was configured at exactly 1 GiB and recorded no OOM, but its peak counter exceeded that limit slightly. No strict whole-cgroup peak pass is claimed, and no memory limit is raised or silently reinterpreted. Actual regional feasibility: **unproved**. This memory measurement is one worker pipeline at a time; it does not prove two simultaneously large tasks fit the deployment cgroup.
Current committed science: 888 profiles and 444,888 levels. These counts are distinct from planned incoming occurrences and normalization work repeated during recovery/rebuilding. The derivatives reuse one platform and its recorded metadata; they do not stress the original run's 584-float metadata diversity or live request latency.
Remaining amplification comes from incoming normalization, retained DB/spool certification and local/first-payload scientific verification. Per-operation/per-publication actual charges and profile canonical sizes reconcile against the persisted canonical_work ledger. Repeated scientific re-encoding of equal-byte temporary/final objects is removed without skipping their SHA/schema/count checks. Every fresh intent/recovery certifies again.
Feasibility decision: this measured envelope is a capacity model only. The actual region's profile/level population, canonical sizes, occupied-slot concentration and required extra rebuilds are not bounded by current evidence. No arbitrary scaling factor or the model's unused allowance certifies them. If the required actual envelope exceeds 10 GiB or the six-hour/1 GiB bounds, acceptance is infeasible under the current contract; return that decision for review, without increasing caps or shrinking geography/time.

## Terminalization

[Concrete review-only command and recovery procedure](../docs/stage1-terminalization-review.md), [migration-0007 rehearsal](stage1-terminalization-0007-rehearsal.json). Exactly 120 complete/44 failed/eight quarantine/1,088 planned model leaves reduce to 120 complete/1,132 failed/eight quarantine, closed/partial with one frozen record. Actual connection termination before commit rolls back; after commit the original open-snapshot command recognizes the closed state and validates it idempotently. The small science/catalogue fixture is administrative, not an original object clone. Original deployed function equality remains a mandatory guarded post-approval preflight.

## Separate next-action decisions

- original_terminalization: **GO_for_separate_procedure_review_only; approval/execution pending**.
- bounded_source_validation_capture: **NO_GO_execution; precise policy and capture scope unapproved**.
- fresh_acceptance_preparation: **NO_GO; source-policy and actual-population feasibility unresolved**.
- live_acceptance_execution: **NO_GO; preparation, owner opt-in, CI and full evidence outstanding**.

S1-G01 remains supported at real broker/prefork component scope, with accelerated leases and explicit redelivery qualifications. S1-G02 remains supported at writer/read-back scope; the new pipeline measurement has its own envelope. S1-G03 HTTP/replay/reporting component regressions pass, while regional source/resource/frozen-original evidence stays blocked. S1-G04/F01-2 minimum passes only its owner-amended scope; authentic descending and present-core null remain unobserved, repeated pressure is synthetic, supplied-error evidence is normalized model/storage only. No fresh capture, private original or owner credential was read.

Actual-head CI and full acceptance/replay remain outstanding. No original run operation, live call, policy activation, budget reset, commit/push/PR, cloud work or Stage 2 occurred.
