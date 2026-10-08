# Stage 1 coverage-failure review — NO-GO

Fresh restricted-repository and immutable sanitized-object review: `2026-10-07T09:21:46.274535+00:00`. Run `fee47d4d-8e91-4cd4-ace2-a1c3d1129fdb`, session `6f3e7301f9789059`, baseline `619411a`.

Do not resume the withdrawn command or certify acceptance. All isolated containers are stopped. The original run remains open without frozen final evidence. No deadline, counter, scientific row, generation, object or original session source seal was reset. No live source call, credential, worker log or private capture original was accessed. Only existing DB/MinIO were briefly started for offline reads, then stopped.

## Findings in priority order

**P1 — aggregate canonical budget exhausted; adaptive splitting cannot recover it.** The persisted ledger has 12,597 completed operations and exactly 10,721,657,712 charged bytes, with zero outstanding reservations. Of the 10,737,418,240-byte allowance, 15,760,528 bytes remain, below the 16,777,216-byte next reservation. The first affected chunk had already entered publishing; its 47 canonical operations charged 49,319,173 bytes. The next three reached validation and have no canonical_work rows: admission could not reserve another profile. All 18 captured candidates map offline under local, uncharged budgets: largest 1,244,214 bytes, total 15,227,184 bytes. Each candidate is below 16 MiB and each chunk below 256 MiB. These are parser measurements, not a whole-publication cost or pipeline-memory proof.

[Reservation guard](../infra/migrations/versions/0005_ingestion_admission.sql#L298), [charging](../packages/core/src/floatchat_core/ingestion/repository.py#L368), [whole-slot rebuild](../packages/core/src/floatchat_core/ingestion/processor.py#L378). The reservation predicate and ledger prove aggregate exhaustion. Persisted events locate the first failure in publication, but lack a precise sub-operation/limit-scope marker; do not invent a stack location from its generic category. Scientific rollback and fail-closed quarantine remain intact.

Splitting does not replenish global counters and can add conversion work. Do not add this generic category to SPLITTABLE, reset the budget, raise the cap, relax read-back verification or extend the deadline. Before another attempt, reduce redundant canonical work within the approved accounting semantics and prove a representative retained-snapshot workload fits offline. Global exhaustion admission/termination and typed number/profile/chunk/run limit evidence require review if changed: the present contract N08 explicitly quarantines these limits.

**P1 — 44 source selections lack successful coverage.** All failures are inventory_before, HTTP 404, disposition http_failure, with one request attempt and finished timing. No profile, inventory_after or metadata 404 occurred. There are 44 distinct chunk IDs: 23 for January 1–8 and 21 for January 8–15 (half-open UTC intervals). They cover 23 distinct 10-degree ownership tiles, including land/edge areas inside the approved operational envelope. Their empty/nonempty population is unknown; land-looking tiles do not establish verified emptiness.

[Pinned OpenAPI notFound](../docs/upstream/argovis-2.36.2.json#L3213) specifies a generic error, not an empty-coverage receipt. The approved empty rule requires successful coherent inventories and profile data. No sanitized failure response body is available in the raw manifest, and none was sought from private originals. HTTP status alone cannot distinguish service semantics or a source problem. Keep these gaps failed until a reviewed source-backed empty rule or successful complete selection evidence exists; neither is established here.

**P1 — four source-warning chunks remain unacceptable under zero quarantine.** Exactly four profile witnesses carry only degenerate_levels; all also have location and timestamp. Their returned pressure columns have no repeated nonnull pressures. All four still reject with upstream_data_warning; other chunk peers remain blocked for that chunk, not silently accepted.

The approved pinned translator detects duplicate pressure levels in an input and skips that input during merging while retaining the annotation. Therefore clean returned pressures do not prove that discarded source science was complete or safe to omit. The returned JSON does not identify the discarded input sufficiently for reconstruction. [Pinned extraction/merge source](https://github.com/argovis/ifremer-sync/blob/cbf2bb48ed5d95532c18bb2cd5217e44618356cf/util/helpers.py#L399-L580). Revision `cbf2bb48ed5d95532c18bb2cd5217e44618356cf`; SHA-256 `279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f` independently matches the locally cached official source. No warning-policy change is made.

**P2 — evidence/admission diagnostics need scope precision.** [landing.py:145–146](../packages/core/src/floatchat_core/ingestion/landing.py#L145) uses http_retry_exhausted also for immediate nonretryable failures. The persisted status/ordinal shows the 404s were not four-attempt exhaustion. Similarly canonical_output_limit combines numeric, per-profile/chunk/run, reservation and read-back limits. [numeric.py:248](../packages/core/src/floatchat_core/ingestion/numeric.py#L248), [processor.py:310](../packages/core/src/floatchat_core/ingestion/processor.py#L310). After exhaustion the worker fetched three additional selections before quarantining them. A distinct resource scope plus bounded offline exhausted-budget tests should precede any reviewed fail-fast lifecycle change; do not infer bad scientific values from this category.

**P3 — evidence scope.** This review is fresh read-only investigation and real-parser execution on checksum-verified sanitized landings, not a rerun of historical full integration/broker/memory checks. No whole-pipeline memory or regional completeness is proved. F01-2 authentic descending/core-null limitations and normalized-only error support remain unchanged. The warning witnesses do not establish authentic repeated-pressure wire support.

## HTTP 404 affected coverage

Every row is inventory_before, http_failure, HTTP 404, attempt 1. Tiles are west/south, longitude/latitude; each is 10×10 degrees, with the contracted fetch-edge expansion. All intervals below are UTC and half-open. Exact attempt IDs, timestamps, logical keys and finished timings are in the JSON evidence.

| Start | End | West | South | Chunk ID |
|---|---|---:|---:|---|
| 2025-01-01 | 2025-01-08 | 20 | -30 | bf3bb212-6bfe-4966-9227-2e74e8a8027e |
| 2025-01-01 | 2025-01-08 | 20 | -20 | 529ce3e9-e673-43ee-8eac-97a3722eb3f8 |
| 2025-01-01 | 2025-01-08 | 20 | -10 | a38e3450-58cf-4ded-9166-847c0d2ee55f |
| 2025-01-01 | 2025-01-08 | 20 | 0 | b6e78abe-208a-481f-be71-9e6d13bd0368 |
| 2025-01-01 | 2025-01-08 | 20 | 10 | 4c43a9bf-67b7-4d52-a403-0c836f44e605 |
| 2025-01-01 | 2025-01-08 | 20 | 20 | 6bc68a2a-72ae-4032-8ac8-713ca2004fc4 |
| 2025-01-01 | 2025-01-08 | 30 | -20 | c0391bcc-28c6-4cec-ab51-53939592d9ce |
| 2025-01-01 | 2025-01-08 | 30 | -10 | a0f843e2-3362-4293-b3c3-938d42633255 |
| 2025-01-01 | 2025-01-08 | 30 | 0 | 2966fcfc-af08-44ed-88cd-d4c30b4fcd92 |
| 2025-01-01 | 2025-01-08 | 30 | 10 | edf03501-bdd8-4bb7-9f35-6521b4fc1ba8 |
| 2025-01-01 | 2025-01-08 | 30 | 20 | 122bd588-6f1b-45cf-be1b-af86a5e184f4 |
| 2025-01-01 | 2025-01-08 | 40 | 0 | 5cd7d5da-85c2-4355-afa1-1cab4a9ec8b8 |
| 2025-01-01 | 2025-01-08 | 40 | 20 | 0259610c-f5b8-4a1c-a98f-b98b919f9881 |
| 2025-01-01 | 2025-01-08 | 70 | 20 | df519ac9-08c7-467d-9f5f-67c6c8f0ff4e |
| 2025-01-01 | 2025-01-08 | 80 | 20 | 042f7822-2911-41b9-bf8d-bc3859c69db8 |
| 2025-01-01 | 2025-01-08 | 90 | 20 | ce224978-cdbc-4710-b726-db99a81dd1bf |
| 2025-01-01 | 2025-01-08 | 100 | 0 | faabc5f2-327c-4c12-af31-eeb5ef56eed1 |
| 2025-01-01 | 2025-01-08 | 100 | 10 | 75eb3c40-ee7a-4e04-a870-00acfea0cf2b |
| 2025-01-01 | 2025-01-08 | 100 | 20 | 87392cd1-0751-48ee-96a3-bfd9cfe0ff0c |
| 2025-01-01 | 2025-01-08 | 110 | -10 | fa98f93d-37f0-4d85-9467-4db07879a7db |
| 2025-01-01 | 2025-01-08 | 110 | 0 | 036f9405-4ae8-4f04-945a-17a655e2c7dd |
| 2025-01-01 | 2025-01-08 | 110 | 10 | fd1f7811-cbaf-401d-aae2-1d31bddf4a3b |
| 2025-01-01 | 2025-01-08 | 110 | 20 | 1fdb8f18-8e5f-4fcf-8cd7-3cade70b7983 |
| 2025-01-08 | 2025-01-15 | 20 | -30 | eb5ec3c4-64df-403c-986c-7f5f9efc5b99 |
| 2025-01-08 | 2025-01-15 | 20 | -20 | 20d92d8c-0632-463e-b6bf-a0e2baebb084 |
| 2025-01-08 | 2025-01-15 | 20 | -10 | 3d5062d2-c181-4f29-b94b-651724429354 |
| 2025-01-08 | 2025-01-15 | 20 | 0 | c69fbcc1-abdc-4536-80aa-ad45c1f953df |
| 2025-01-08 | 2025-01-15 | 20 | 10 | a9b0de8b-8604-4032-8d9e-f5c4d446360f |
| 2025-01-08 | 2025-01-15 | 20 | 20 | afbae7de-33fc-4d85-b2b5-ce7de6b8d6e8 |
| 2025-01-08 | 2025-01-15 | 30 | -20 | 42ce01b6-8662-44ca-9177-60350d363b5d |
| 2025-01-08 | 2025-01-15 | 30 | -10 | cd2b1cfc-3a81-4fca-b997-cd6fccaa8527 |
| 2025-01-08 | 2025-01-15 | 30 | 0 | 9ded36d8-c92c-48b3-902c-0fc764af0eb2 |
| 2025-01-08 | 2025-01-15 | 30 | 10 | e4e6d041-ad18-4102-bec9-73f18dd12523 |
| 2025-01-08 | 2025-01-15 | 30 | 20 | 6e2e12c6-6619-4342-8423-ad675aa66864 |
| 2025-01-08 | 2025-01-15 | 40 | 20 | 6061ebff-a119-44a3-a0b3-f85d5ec8dfa9 |
| 2025-01-08 | 2025-01-15 | 70 | 20 | 248ff809-b29f-422f-bf00-4ddbf6304c71 |
| 2025-01-08 | 2025-01-15 | 80 | 20 | 40ec690a-5e05-41df-b7fa-c599c0c541f3 |
| 2025-01-08 | 2025-01-15 | 100 | 0 | 87b4c40c-f68f-480b-8a5e-9315cb8bce89 |
| 2025-01-08 | 2025-01-15 | 100 | 10 | 806dd929-f952-48b4-8e85-a9bbd198f307 |
| 2025-01-08 | 2025-01-15 | 100 | 20 | c6371c0b-e9fc-47be-83b5-4f6b668176ad |
| 2025-01-08 | 2025-01-15 | 110 | -10 | bd032e53-ad81-4d80-a234-69435aa44c02 |
| 2025-01-08 | 2025-01-15 | 110 | 0 | f561504a-eebc-4cec-8cf5-2b312fa62674 |
| 2025-01-08 | 2025-01-15 | 110 | 10 | 57f593c1-6371-4423-a4a1-cefb9d5e2877 |
| 2025-01-08 | 2025-01-15 | 110 | 20 | 77f935ac-1bfd-4816-94b2-a3b3d882ab84 |

## Warning witnesses

| Profile ID | UTC interval | West/South | Returned levels | Profile raw SHA-256 |
|---|---|---|---:|---|
| 6990505_085 | [2025-01-01, 2025-01-08) | 40/-20 | 240 | 14833d8b99084e8fa3e50bb91dda27096bb00708af6d8b9eb76aa0ce55f33913 |
| 5906970_085 | [2025-01-08, 2025-01-15) | 50/-20 | 239 | 25ffd9d5ba76f2946090ac90e9660669c23d53928f344af3fe235579284b29a7 |
| 5906971_084 | [2025-01-08, 2025-01-15) | 50/-50 | 242 | 6841a64009bf241e90cef43df75f584ce8e92adbc61395c3edc6c5ef7d3566f4 |
| 6990505_086 | [2025-01-08, 2025-01-15) | 40/-20 | 240 | ae5ef44decf5e94e34e4a6dc757f5aa7d5462682f700941b31bd9cdd32871f96 |

## Canonical candidate replay

| Chunk ID | West/South | Profiles | Local canonical bytes | Largest profile bytes | Failure phase |
|---|---|---:|---:|---:|---|
| 24804298-a89a-4959-9616-b75e6ed5b1db | 80/-40 | 5 | 4,936,215 | 1,244,214 | publishing |
| 31df39ef-80bc-42b8-9d77-cb49521ff6d4 | 80/-50 | 7 | 6,229,032 | 1,241,031 | validating |
| ce2dc560-f358-4afb-862e-bdf0dc2e5e37 | 90/0 | 2 | 729,713 | 604,398 | validating |
| d0a23b0f-e75c-4ffc-8103-ef989882f381 | 80/-60 | 4 | 3,332,224 | 1,228,530 | validating |

## Independent closure and next review

| Gate | Current assessment |
|---|---|
| S1-G01 | Historical component fault/recovery evidence retained; not rerun here. Original run remains open and unfrozen. |
| S1-G02 | Historical writer/read-back evidence retained; not whole-pipeline memory proof. Aggregate canonical capacity blocks this live plan. |
| S1-G03 | Historical HTTP/replay fixes retained; 404 statuses persist correctly. Current resource reason scope and complete/frozen regional reporting remain unresolved. |
| S1-G04 | F01-2 amended fixture scope unchanged; source-warning safety is a separate coverage blocker. No new authentic coverage or waiver. |

Fresh forensic assertions: **29/29 passed**. The restricted DB science manifest and exact active ID/hash manifest are equal before/after inspection: 819 profiles, 572,347 levels, 67 active partitions. These assertions do not certify acceptance. [Raw-object/persisted summary](stage1-coverage-failure-review.json), [assertions and source pins](stage1-coverage-failure-assertions.json).

Separately, **354 offline unit tests passed, zero failures/errors/skips**, on the updated report-generator/document source tree. Lint, formatting, mypy, diff whitespace checks and redacted current/history/all-reports scans passed. [Fresh source digest and checks](stage1-coverage-review-checks.json), [JUnit](stage1-coverage-review-offline-unit.xml). No integration/fault/memory suite was rerun and no synthetic result closes a live coverage gap.

Original work deadline `2026-10-07 13:03:38.284791+00:00`; final deadline `2026-10-07 13:04:38.284791+00:00`. They remain unchanged even if wall time passes them while services are stopped. No agent finalization, cancellation, replay, deletion or new session was performed. Terminalization under the original closing fence remains outstanding; committed chunks must stay complete.

**NO-GO for another live attempt or certification.** Required next decisions/evidence: a documented 404 coverage resolution; a reviewed treatment for source-degenerate missing input consistent with zero-quarantine acceptance; bounded canonical publication capacity and scoped resource admission evidence; original-run terminal/frozen evidence. No live retry command is prepared. Full acceptance and actual-head CI remain outstanding. Stage 2 remains blocked.
