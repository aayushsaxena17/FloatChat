# Stage 1 offline remediation — review candidate

Current decision: **NO-GO for another live attempt or certification**. This review
does not authorize restarting session `6f3e7301f9789059`, changing its deadline,
terminalizing it, resealing it or creating a replacement live session. Stage 2
remains blocked. No credential or private capture original is required.

Latest review package: [authoritative blocker matrix](../reports/stage1-blocker-review.json)
and [consolidated report](../reports/stage1-blocker-review.md). The versioned
[source-policy proposal](stage1-source-policy-proposal.md) compares strict A with
qualified B and remains inactive. Its test-only oracle does not change ingestion.
The regional model supersedes the five-slice component as the current capacity
experiment, without converting either result into actual regional proof.

## Source-backed 404 policy

The official API release 2.36.2 resolves to repository revision
`13e634127a3ad51e7c237c1319dba4f56fcabf13`. Its
[Argo service](https://github.com/argovis/argovis_api/blob/13e634127a3ad51e7c237c1319dba4f56fcabf13/nodejs-server/service/ArgoService.js#L213-L219)
initializes the search response to 404. Its
[post-processing](https://github.com/argovis/argovis_api/blob/13e634127a3ad51e7c237c1319dba4f56fcabf13/nodejs-server/helpers/helpers.js#L721-L735)
discards documents with no data levels; a surviving document sets status 200,
then inventory mode removes measurement arrays. Thus 404 can describe an empty
returned stream, rather than exclusively an unknown URL or missing ID. The same
status can result after source documents were discarded. This is code evidence
for that release, **not an attestation of the deployed service version**.

Existing policy remains binding: **HTTP 404 is failed coverage** for every role.
The original 44 inventory_before failures have no admitted response bodies or
successful inventories. They stay failed; no report, receipt, chunk or catalogue
entry is relabelled. Land-looking tiles and unique returned pressures cannot
establish source absence. Metadata and single-ID 404s remain missing-entity errors.

A future empty-response amendment would require separate review. Its minimum
evidence would include the exact approved endpoint/request role and parameters,
numeric status, bounded complete framing/decompression, explicit content type,
an exact validated empty JSON array with no error object/HTML/trailing material,
source implementation/deployment compatibility, and coherent before/data=all/after
selections. It must distinguish **zero source documents** from **zero documents
surviving upstream filtering**; the latter cannot prove complete source coverage.
The pinned implementation does not supply that distinction for an empty stream.
Consequently even a newly obtained 404/empty-array combination is insufficient
to waive the current source-completeness requirement without a reviewed definition
of the accepted upstream population and its exclusions.

No such amendment is activated here. An official versioned upstream clarification
or independent completeness mechanism is still needed for a successful empty
policy. No support message or data request was sent. Static public GitHub source
was inspected without authentication; no Argovis data API was contacted. Checksums,
an offline execution of the official response functions with mocked database input,
and explicit deployment limitations are in
[source-semantics evidence](../reports/stage1-http-source-semantics.json).

## Scientific implications of discarded input

The approved translator revision and SHA-256 remain those in
[the exact fluorescence supplement](upstream/argovis-source-supplement-v1.json).
The source merge skips an entire input annotated degenerate_levels, preserving
the warning and the union of variable names/attributes. Four offline synthetic
input models executed the actual pinned merge/cleanup functions:

| Degenerate component | Scientific consequence |
|---|---|
| Neither | Core and BGC observations remain on the merged pressure axis. |
| Core only | Core temperature/salinity can be lost despite surviving unique BGC pressures. |
| BGC only | Valid core values can remain while non-core measurements are lost. |
| Both | The returned level set can be empty. |

These models establish possible losses, not the missing components of the four
authentic warning witnesses. Their returned core columns cannot identify the
discarded original input or certify that it contained only non-core science.
Keep whole-chunk quarantine and zero tolerance. Accepting only apparently healthy
returned core values would require a separately reviewed scientific/source policy
and attributable evidence of the discarded component. This turn creates no waiver
and adds no authentic coverage witness. See
[executed scientific models](../reports/stage1-discarded-input-science.json).

## Resource evidence and publication capacity

Diagnostic supplement S1-DIAG-1 preserves canonical_output_limit, all state
transitions, the numeric/profile/chunk/run ceilings and the single retry owner.
It adds allowlisted scope, operation and byte counters to rejection evidence.
Number normalization, profile/chunk/run encoding, profile read-back and the run's
16 MiB reservation are distinguishable. Raw source content, database exception
DETAIL, headers and arbitrary strings are never forwarded. Missing/invalid detail
remains unscoped, including historical records; no reason is inferred or backfilled.

Portable migration 0008 adds safe reservation/accounting DETAIL and bounded,
sanitized event snapshots, frozen in the same existing finalization transaction.
It is tested only in new disposable databases. **It is not applied to the preserved
acceptance database.** Stage 1 still quarantines generic canonical limits, including
aggregate exhaustion; a fail-fast run-closing policy would require a separate
lifecycle amendment. No limit is raised and canonical work is not credited back.

Within one private spool, a canonical document is round-trip certified once and
each later read verifies its actual SHA-256 before parsing. Later reads reuse the
existing certified bytes instead of producing new canonical encodings. A new
spool/recovery starts without that certification cache and charges conversion
again. Cache entries are bounded to the existing 100,000 retained plus 2,000
incoming-profile envelope. All canonical conversions actually performed remain
charged. Object temporary/final read-back, scientific hash checks and commit-time
revalidation are retained.

The capacity probe uses labelled derivatives of the admitted 2904014_040 A-mode
profile, preserving its 501-level values/QC/attributes while changing identity,
cycle, observation time and location. Five slices grow a single month's stored
slot from 8 to 40 profiles (20,040 levels). It exercises real restricted PostgreSQL,
private spill staging, full retained snapshots, MinIO temporary/final verification,
transactional activation and frozen reporting. Its persisted canonical ledger must
balance and remain below the unchanged 10 GiB cap. The test is run in a new offline
container under a 1 GiB cgroup; it does not claim a measured whole-pipeline peak.

This bounded workload cannot establish the unknown Jan–Mar regional population,
all 90 tiles, the whole run's conversion cost or sufficient capacity for the
original exhausted run. Individual-profile success and projected scaling are not
acceptance passes. The publication-capacity report must expose measured bytes,
operations, retained membership and these limitations. A regional capacity claim
remains blocked until it has a justified workload/population envelope within the
approved cap; do not reset the original allowance or spread one run over hidden
budgets to obtain a pass.

## Publication optimization and regional model

S1-RESOURCE-2 additionally avoids repeated scientific re-encoding of an already
certified publication after entire read-back byte-count/SHA equality. Local and
first-payload certification still charge their actual encodings, and object schema,
counts, row-group bounds and temporary/final whole-byte integrity are checked.
A fresh intent/recovery starts uncertified. Remaining amplification includes new
incoming normalization, comparison to current science, retained DB certification,
spool certification and at least two full snapshot scientific certifications per
publication. Slot growth, corrections and bounded rebuilds are measured explicitly;
the 10 GiB cap and six-hour deadline remain unchanged. See the measured one-run
model in `reports/stage1-regional-capacity-model.json` and certificate tests.

The encoder emits bounded individual levels using the C JSON encoder only when a
conservative output bound fits every remaining allowance. Large, unsupported or
near-boundary structures retain the streaming path. Exact sorted canonical bytes,
scientific hashes, first-exceeded scope and actual byte charging remain unchanged.
This reduces CPU overhead without reducing accounting. Differential tests include
the admitted 501-level profile, Unicode, nested values, each budget boundary,
nonfinite rejection and large/deep fallback. No enlarged budget or deadline is used.

The 1,260-root model uses all 90 tiles and the exact Jan–Mar month/slice plan, with
uneven populated slots. It is expressly a synthetic workload envelope, not a census.
Its 896 planned occurrences have 501 levels each; it exceeds the original 819
profile count but has fewer levels than the original 572,347 and only nine occupied
month/tile slots versus the original 67 active generations. Concentrated growth
stresses retained work; it does not dominate all possible regional distributions,
profile sizes, retry counts or revisions. Original regional feasibility remains
unproved even if this model completes within the cap. A failed envelope instead
requires a resource feasibility decision, never a hidden allowance or smaller region.
All derivatives reuse one platform and its metadata; the original run had 584
floats. Live HTTP latency, metadata diversity and the full allowed retry/rebuild
envelope remain additional uncertainties. The measured margin includes one injected
process-loss reservation/recovery and one publication-base rebuild, not every
permitted worst-case fault combination.
The memory measurement covers one worker pipeline at a time. Two simultaneously
large tasks and the deployment's aggregate worker cgroup require separate capacity
evidence; the small real-broker concurrency test does not establish that envelope.

## Separate terminalization review

The original run remains stopped and open. The
[terminalization procedure](stage1-terminalization-review.md) is a review candidate,
not an execution authorization. It uses the existing closing fence and frozen
incomplete-run evidence without ingestion, retries, a new plan or a deadline reset.
Its approval is separate from approval of any later live attempt.
