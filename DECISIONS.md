# Decisions

## ADR-0030 - Approved Stage 1 implementation and explicit application grants

On 2026-10-06 the owner supplied Astra's GO for stage1-v2 and separately instructed
Stage 1 implementation in the sanitized WSL checkout. The contract gate is passed;
the implementation, offline CI and isolated live acceptance gates are not inferred.
The approved 86-case matrix remains authoritative. This supersedes the preparation-only
authorization in ADR-0018, without changing any accepted scientific/lifecycle policy.

Implementation begins with deterministic policies, additive schema and fenced control
primitives. Keep these procedures inaccessible to PUBLIC and the existing application
role until the complete controlled ingestion path is implemented and verified. The
application receives read access to committed catalogue records only. Repeated bootstrap
must not regrant blanket DML on science/evidence tables or their monthly children.
Remove inherited future app-schema write defaults; preserve explicit grants on existing
Stage 0 application objects. The disposable Stage 0 permission probe explicitly grants
its own test table rather than relying on blanket defaults. Alternative: allow the
Stage 0 bootstrap loop to grant unrestricted writes to new science; rejected by contract §4.

The owner authorized minimum representative live fixture capture, conditional on an
available ARGOVIS_API_KEY, with original bytes outside Git and sanitized attributed
responses/scanning before commit. No credential was available. Published notebook outputs
are explicitly development examples, not live or matching recorded raw responses; F01
and the full adapter acceptance remain pending. No full Jan-Mar live run is authorized
by that limited capture instruction.

## ADR-0001 — Stage 0 amendments override stale build prompts

The approved execution contract and owner amendments govern Stage 0. `FLOATCHAT_PRD_v2.md` governs target architecture and layout; PRD §0 overrides its later sections. The supplied build prompts are historical planning inputs, with obsolete secret-prefix and completion language. `Prototype/FLOATCHAT_PRODUCTION_ARCHITECTURE.md` is archival reference, not an alternate Stage 0 specification. No supplied planning document is overwritten.

## ADR-0002 — Local services with zero required cloud infrastructure cost

Use WSL2 Ubuntu 24.04 and Docker Desktop with local PostgreSQL/PostGIS/pgvector, Redis, MinIO, FastAPI, Celery, and React/Vite. No Azure, Supabase, OpenAI API, cloud database, cloud object store, or paid resource is created. Portable environment configuration preserves a later migration path; demonstrations and deployment belong in Stage 8. Docker installation is owner-managed. Docker acceptance passed from Windows and from the supported Ubuntu 24.04 WSL2 checkout using Make.

## ADR-0003 — Preserve originals; sanitize before archiving

The existing dirty tree was backed up and verified before source edits. Current `Prototype/python.py` matched HEAD; the working notebook differed and was preserved as the current input. Sanitized copies are in `legacy/prototype`. Notebook outputs/metadata/attachments are removed rather than carried into an archive. The original folder and large Parquet remain preserved and excluded from Git/runtime packaging pending final owner-controlled disposition. No blanket directory removal is performed.

## ADR-0004 — Separate preparation from completion

The original inventory was expanded into a tested candidate and a separate validation clone. The owner subsequently explicitly authorized the tested isolated rewrite, affected-ref publication, Stage 0 PR and checked merge. Seven branches were published atomically with exact leases; the dirty checkout remained intact. Known leaks are not allowlisted. All six checks passed on the sanitized foundation PR and merged main; fresh-clone Ubuntu verification passed. Stage 1 has not started.

## ADR-0005 — MinIO community source build

The [official MinIO project](https://github.com/minio/minio) is archived and distributed as source only. Registry requests for historical images were unavailable. Build pinned upstream server/client releases from checksum-verified archives, with the preferred Go 1.24.8 compiler and upstream Go module sums. Preserve upstream licenses in the image. This adds a build prerequisite, not a cloud account or service. Image build and private-bucket runtime validation passed using Docker's Linux engine from Windows.

## ADR-0006 — Safe migration and configuration lifecycle

Administrative DB and MinIO identities are limited to initialization services. API/worker identities are distinct and buckets are private. Readiness checks run concurrently with a four-second overall budget; diagnostics are sanitized. Migration upgrade is idempotent; downgrade refuses extension removal. Configuration is generated outside the repository in a restricted non-synced directory and never overwritten. Ordinary lifecycle commands preserve volumes.

## ADR-0007 — Bounded fixture reproduction only

Commit a deterministic sample from preserved scientific data with byte/schema/checksum/provenance validation. Refetch is an optional owner-specified snapshot download, not an Argovis adapter. A durable snapshot URL remains unresolved; production source discovery, adapters, normalization and scheduling belong in Stage 1. No fabricated retrieval dates or production schema are introduced.

## ADR-0008 — Compatible PostgreSQL extension image

The original PostGIS image used Debian Bullseye repositories that failed during the extension build. Use digest-pinned official PostgreSQL 17.6 on Bookworm, install PostGIS from the configured package repository, and compile checksum-pinned pgvector 0.8.2 in a separate build stage. Runtime SQL verified PostgreSQL 17.6, PostGIS 3.6.4 and vector 0.8.2, including geometry/vector operations. The compiler headers resolved to PostgreSQL 17.11; runtime compatibility passed. Actual versions and built image IDs are recorded in `reports/stage0-runtime.json`.

## ADR-0009 — Windows driver and isolated acceptance diagnostics

Detect Docker Desktop's per-user installation and expose its credential helpers only in the driver's process PATH. Preserve restricted integration configuration and logs outside Git alongside retained volumes; prevent ambient application configuration from redirecting integration tests to cloud services. Run uv commands with `--all-packages --frozen` so workspace package dependencies remain installed. Windows-driven Docker acceptance and Ubuntu 24.04 Make setup, builds, checks, empty/repeat startup and full acceptance passed.

## ADR-0010 — Authorized publication and repository controls

Publish only the seven inventoried affected branch refs after rechecking remote IDs; use one atomic push with an explicit force-with-lease for each ref. Temporarily permit force updates only for that publication window, restore the force-push prohibition immediately, and add all six required CI checks while preserving the existing two-review rule. Preserve old/new commit mapping and raw diagnostics only outside Git. New foundation commits use the account's GitHub noreply identity and current timestamps. Old clones and forks require the documented recovery procedure.

## ADR-0011 — Complete Windows/Ubuntu verification and formatting

Install Ubuntu 24.04 in WSL2 and verify the documented Make commands from a separate Linux-filesystem checkout using Docker Desktop integration. Pin Prettier 3.8.1 and include frontend formatting in Make lint and the web CI job. Match driver health URLs to configured loopback API/web ports, including Compose environment overrides. Optional live scientific refetch is not required for Stage 0; the deterministic fixture and mocked timeout/error/atomic-download tests supply the required contract evidence.

## ADR-0012 — Scan the committing repository's index

The scanner originally defaulted to the script's repository. A hook invoked in a separate repository therefore scanned the wrong index; the original dirty index concealed that defect by containing an unrelated known leak. Default the scan source to the caller's working directory, retain explicit `--source` for isolated scans, and verify rejection with the script's checkout clean. The disposable hook test exercises an actual Git commit and must fail because of that disposable repository's synthetic finding.

## ADR-0013 — Portable test invocation and preserved document formatting

Invoke tests through `python -m pytest` in Make and CI so the workspace root is on Python's import path. The standalone pytest launcher on Linux otherwise failed to import the root scripts package. Preserve the original PRD's Markdown hard breaks and archived prototype whitespace; their attributes exempt only those whitespace checks, never secret scanning.

## ADR-0014 - Post-merge evidence and protected Stage 0 integration

A documentation-only follow-up on the same Stage 0 branch records the fresh merged-main checks and final gate after foundation PR #1. This additional PR is necessary because evidence measured after the first merge cannot be recorded honestly beforehand. Runtime source remains identical to tested commit 608e4356b312f4422ad40996e1604fb1ef28a640; documentation checks run again. Published implementation commits are not cosmetically rewritten; the evidence commit uses a conventional message.

The owner-authorized foundation merge used the administrator exception for the pre-existing two-review requirement only after every required check actually passed. Administrator enforcement was strengthened immediately afterward. If the evidence-only merge needs that same narrowly scoped exception, retain all required checks and force-push prohibitions, then restore administrator enforcement immediately. Ordinary development must satisfy the final protected rule. No failed check is bypassed.

Twenty-nine original commits had signatures tied to their old IDs. Rewriting invalidates those signatures; original records remain in the restricted preservation copy. Authors and timestamps of the 31 retained commits were preserved. New commits use the account's GitHub noreply identity and honest current timestamps.

## ADR-0015 - Hard I/O deadlines include cleanup

Readiness uses independently timed concurrent tasks rather than waiting for gather cancellation.
Each database probe tracks connections by task, uses autocommit and a server statement timeout
bounded by remaining readiness budget (maximum one second), and disposes its libpq socket without
a network cancellation round trip. Retained cleanup tasks receive a second cancellation after
50 ms and have exceptions drained. Cleanup is outside the response deadline; concurrent requests
do not share connection ownership.

The optional snapshot downloader uses a spawned I/O worker with a parent watchdog. Socket
timeouts and read1 bound ordinary reads; process isolation also bounds slow DNS, TLS/header
trickles and response cleanup. A 50 ms termination/reaping reserve comes out of the existing
total budget. Only the parent atomically replaces a verified output; failure kills/reaps the
worker before deleting its partial file. Injected test openers must be spawn-picklable.

## ADR-0016 - Application grants are separated from extension metadata

Extensions and Alembic metadata remain in public. Application tables belong to the migration
role in the dedicated app schema; future table/sequence defaults apply only there. Bootstrap
removes old public write/default grants and restores read-only access to extension members in
any schema. Repeated initialization repairs legacy grant drift without dropping extensions.
Future extension installation must stay outside the reserved application schema.

## ADR-0017 - Verify the actual managed hook and committed evidence

The pre-commit hook uses the frozen uv workspace, not a system executable named python.
Regression tests copy the exact YAML unchanged and exercise real clean/rejected Git commits
with no activated environment or python on PATH.
The hook fixture exposes only explicit uv/git/bash/sh symlinks: hosted Ubuntu also installs
/usr/bin/python, so inheriting /usr/bin would invalidate the absence test. The assertions and
committed hook entry are unchanged by this test-environment correction.

Dirty Ubuntu reports were preserved and inspected privately, not reused as source or copied
into this correction. New corrective
evidence contains measured results and relative repository references, without private
configuration paths. CI and a clean Astra review remain explicit merge gates.

## ADR-0018 - Stage 1 contract authority and sanitized source

The owner authorized contract hardening only, based on Astra's complete Stage 1 NO-GO
review and twelve explicit requirement groups. Work uses the fresh WSL2 sanitized
Stage 0 checkout at 619411a on codex/stage-1. The preserved Windows project is archival
material and is not a development source, merge parent or publication target.

[docs/stage1-contract.md](docs/stage1-contract.md) is the Stage 1 decision contract;
its explicit policies override ambiguous Stage 1 PRD/build-prompt language. This ADR
amends ADR-0001's earlier preservation of supplied planning text only for the owner's
now-requested targeted document corrections. Stage 0's historical decisions/evidence
are retained. Alternative: implement directly from the older prompt; rejected because
the temporal, identity and publication guarantees were incomplete. No implementation,
migration, live ingestion, schedule, cloud provisioning or credential is created here.
Astra contract review and separate implementation instruction remain the next gate.

## ADR-0019 - Immutable run time and isolated historical acceptance

Normal mode captures actual UTC once per run and admits only observations in
[T minus 12 calendar months,T). Retries reuse T; latest-three-month hot classification
uses the same T. Month ranges include every named month, so Jan-Mar 2025 means
[2025-01-01T00:00:00Z,2025-04-01T00:00:00Z).

Demonstrate those historical months only with T=2025-04-01T00:00:00Z in a disposable
acceptance database/buckets/queue/configuration/project carrying an isolation marker.
It cannot change production clocks, watermarks or retention proposals. Alternative:
override production's current clock to load old data; rejected because it corrupts
window semantics. Stage 1 cleanup/rolling retention is dry-run only until separate
lifecycle acceptance. Contract §§2,8,10 define boundaries, terminal outcomes and exits.

## ADR-0020 - Versioned geometry and documented Argovis JSON

Select indian-ocean-v1 as the explicit WGS84 envelope 20..120 longitude,
-60..30 latitude. It is an operational envelope, not a basin-mask claim. Coordinates
are lon/lat, outer edges included; expanded fetch tiles have deterministic ownership
and deduplication. Persist geometry version/hash.

Pin the Argovis core OpenAPI release 2.36.2, GET /argo with encoded closed polygon,
UTC dates and data=all, and its documented metadata/ID routes. No invented pagination,
GeoJSON request body or adjusted-field query names. Inventory/data verification guards
incomplete coverage. Alternatives: use the old prototype request format or processed
Parquet as adapter proof; rejected. Later fixtures require sanitized recorded raw JSON,
inventory and metadata with pinned versions and source attribution (contract §§3,6,11).

## ADR-0021 - Enforced identity, conservative revisions and complete scientific mapping

Prefer opaque upstream profile ID; enforce immutable fallback source/platform/cycle/
direction/observation-time/segment identity with PostgreSQL unique/check constraints.
Use an unpartitioned profile identity registry and monthly measurement children with
partition-aware primary/composite foreign keys. Ascending/descending cycles cannot
collide; unsafe identity aliases quarantine. COPY FROM STDIN, controlled staging/merge
and restricted workers preserve Stage 0 privileges. Migrations will be additive/portable.

Use comparable source-document revision vectors; stale inputs cannot overwrite science.
Canonical scientific-content SHA-256 supplies no-op/conflict detection when revision
ordering is absent. Equal revision/different content quarantines. Newer revisions
replace complete level sets atomically, removing obsolete levels. Audit/attempt/run
growth is allowed during replay; science and active generations remain unchanged for
identical captured inputs. Unconditional upsert and conflict-ignore were rejected.

Explicit pressure/temperature/salinity original, adjusted, separate QC, error, unit
and per-variable mode columns preserve what Argovis supplies. Its selected values
are original in R and adjusted in A/D; absent counterparts remain null, not fabricated.
Contract §§4-6 define all null/fill/nonfinite/length/QC/error and validation decisions.

## ADR-0022 - Verified immutable publication with one PostgreSQL commit

SHA-256 of object bytes is the integrity checksum, not ETag. Verify temporary object
bytes/schema/count/manifests, publish by immutable content-addressed copy, then verify
the final object. One PostgreSQL transaction locks/rechecks revisions and generations,
merges/replaces science, activates/supersedes catalogue snapshots, commits coverage
receipts and completes the chunk. Concurrent/stale publishers are fenced.

Only committed verified active catalogue snapshots are selectable through a bounded
internal selector; no Stage 2 query API or DuckDB engine is added. Precommit crashes
can leave orphan objects but no new selectable science; postcommit retries recognize
completion. Reconciliation is dry-run with a 48-hour age threshold and all-reference/
publication/in-flight checks. Alternatives: independent merge/catalogue commits,
filesystem rename assumptions and age-only cleanup; rejected (contract §7).

## ADR-0023 - Bounded single-owner retries and disabled-by-default UTC scheduling

A durable ingestion controller alone owns retries; HTTP automatic retry and Celery
autoretry are disabled. Attempt counters, leases/fencing and deadlines survive delivery
duplication/restarts. Contract §9 fixes compressed/decompressed/profile/level/chunk/
memory/concurrency/request/time bounds and credential/hostname/redirect protections.

Later scheduling uses one Beat instance at UTC 02:00, a 14-day overlap, at most 31-day
oldest-first catch-up and environment/source/region fencing. Live ingestion defaults
off. Partial runs cannot advance contiguous coverage watermarks. Beat is a future
implementation requirement; no scheduler is installed/enabled by this turn. Destructive
retention, dashboard aggregates and semantic re-embedding remain outside Stage 1
(contract §§8-10). Multiplying HTTP/Celery retries and unbounded catch-up were rejected.

## ADR-0024 - Offline acceptance, persisted reconciliation and local cloud boundary

Every Astra finding/test area is traced to stable test IDs in contract §12. Later CI
uses sanitized raw fixtures and local ephemeral services without upstream credentials
or network access. Live acceptance is separate, explicitly opt-in on supported WSL2,
with an owner-provided Argovis credential and isolated historical environment.

Reports derive solely from persisted payload/profile/level evidence, including
duplicates, filtering, blocked/quarantined outcomes and unknown counts. Equivalent
Parquet and pandas size comparisons pin serialization/dtypes/measurement method and
do not label DataFrame logical size as peak RSS. Replays compare scientific manifests
and active generations separately from attempts/audits.

Preserve local PostgreSQL/PostGIS/pgvector, MinIO, Redis and Celery (ADR-0002).
Keep future migrations portable to managed PostgreSQL. Supabase/Azure/other cloud
provisioning waits for Stage 8 deployment planning. This contract does not pull query
APIs, DuckDB, dashboards, RAG, exports, forecasts or user-facing historical jobs into
Stage 1. No future test or live result is claimed as executed.

## ADR-0025 - Full retained snapshots and run eligibility are separate populations

Astra's follow-up blocker 1 found a mismatch between full stored snapshots and eligible-only
reconciliation. Stage1-v2 retains every previously accepted observation in a full month/tile
snapshot until separately authorized lifecycle action. "Older scientific state" means
superseded revisions/obsolete levels, not observations outside a later run's window.

Full reconciliation compares the committed PostgreSQL membership manifest with the entire
matching Parquet generation, including retained old dates. Run eligibility applies fixed
T/time/region/request filters identically to candidate/outcome accounting and to both
projections when compared; it never rewrites retention. Reports name both populations and
their retained/eligible counts. Alternative: discard cutoff-crossed observations when
rebuilding; rejected because Stage 1 has no destructive retention authorization.
This clarifies ADR-0019/0022/0024; contract §§2,7,11 and T06 cover the populated-month cutoff
and eligible-correction case.

## ADR-0026 - Empty fetches preserve science; accepted ownership changes may empty a slot

Astra's follow-up blocker 2 exposed the old P09 conflation. Fetch receipts and stored-domain
evidence now have different meanings. Verified empty fetch over an empty stored selection
records verified_empty_fetch and creates no object. Empty refresh over accepted retained
science records source_absence_over_retained, preserving science and active generation IDs.
An accepted identity-preserving ownership correction moving the last stored profile
atomically supersedes the old slot and records empty_stored_domain, activating its destination.

The internal selector returns covered-empty evidence for the first, retained active partitions
with a source-absence annotation for the second, and corrected-empty evidence with no old
active generation for the third; uncovered intervals still report gaps. Empty fetches never
imply tombstones, including empty subintervals of populated month/tile snapshots.
Empty stored-selection/domain evidence is tied to a monotonic logical-slot version;
the selector prefers current accepted membership over old empty receipts.
Alternative: supersede a slot on any empty response; rejected as unauthorized data loss.
Contract §7 and P09a/P09b/P09c replace P09 and amend ADR-0022.

## ADR-0027 - Late revision conflicts quarantine through a fenced evidence transaction

Astra's follow-up blocker 3 identified a missing publishing -> quarantined transition.
Publication revalidation conflicts roll back the complete scientific/catalogue transaction.
A separate current-epoch evidence-only transaction persists the chunk's quarantined state,
winner/incoming revision/hash/generation evidence and abandoned unpublished intent references
together. Winning science/active generations remain unchanged; candidate objects remain
referenced and are not selectable/deleted. Prepared intent becomes committed or abandoned,
never resurrected. Recovery after rollback repeats this decision without double activation.

If cancellation/deadline closing wins first, terminal failure remains authoritative and conflict
evidence is attached without late state/scientific mutation. Alternative: call a revision
conflict an infrastructure failure or restart validation without a legal transition; rejected.
Contract §7.1/§8, P11 and C09-C10 amend ADR-0021/0022/0023.

## ADR-0028 - Recover process loss; fence cancellation/deadline; record overlap without a run

Astra's follow-up blocker 4 distinguished loss of a worker/controller/CLI process from
persisted operator cancellation. One durable controller owns recovery; an independent local
supervisor adopts an expired controller's same run with new epoch/fences. Every planned,
fetching, landed, validating and publishing phase has an explicit resume rule. Reuse verified
landing without refetch; interrupted requests keep their attempt count. Complete and other
terminal chunks remain terminal. Controller claims/run, processing claims/chunk and publication
attempts/chunk are each capped at four including the initial claim/attempt.

Actual database run creation, independent of acceptance reference time, plus the frozen
execution limit (default/hard maximum six hours; reduced limits must exceed 60 seconds)
bounds execution, with the final 60 seconds for terminal
evidence. Cancellation or work-deadline expiry closes/fences publication on the same control
row, fails unfinished chunks and abandons prepared intents; already committed chunks stay
complete. CLI cancellation is 130 only with persisted cancellation/final evidence and affected
unfinished work; deadline uses aggregate 3/5. All-complete cancellation is no-effect/exit 0.
Unpersisted process death has no fabricated contract exit and can recover.

overlap_skip is a scheduling_attempt admission event with unique request_id and incumbent
run reference, no new run/T/chunks. Manual exit is 6; scheduled Beat overlap records the event
without a CLI exit or failed task. Watermark/backlog remain unchanged. Expired unfinished scope
ownership resumes the incumbent rather than making a fresh competing run. Alternative:
automatically fail every process loss or treat skipped scheduling as completed ingestion;
rejected. Contract §§8-10, C05-C11 and D05-D06 amend ADR-0023.

## ADR-0029 - Bounded exact decimals, deterministic binary64 and explicit nonfinite grammar

Astra's follow-up blocker 5 exposed unbounded exponent expansion and unspecified conversion.
scientific-json-v2 accepts strict JSON finite numeric tokens <=128 ASCII bytes with written
exponent magnitude <=400 and normalized exponent-free strings <=512 bytes, checking length
before allocation. Canonical profile/chunk/run output is bounded to 16 MiB/256 MiB/10 GiB,
including repeated conversion work. Limit violations quarantine, never silently coerce.

Exact decimals convert to binary64 with nearest/ties-even independent of locale/Decimal context.
Overflow and nonzero values rounding to zero quarantine; finite rounding and nonzero subnormals
are accepted with deterministic flags. Exact signed zero stores positive zero. Hashes retain
exact decimal strings plus flags/null reasons, not rounded float64 text. Distinct source
decimals can share stored bits while retaining different scientific hashes.

Only exact quoted NaN, Infinity, +Infinity and -Infinity in scientific value/error cells
map to null/nonfinite kind. Bare nonstandard JSON tokens and other quoted numeric strings
quarantine; no NaN/infinity is stored. Positive Infinity spellings share canonical content,
while distinct kinds remain distinguishable. Rejected profiles have no certified scientific
hash, but retain raw checksum/reasons and no scientific/catalogue mutation. Alternative:
parser defaults, float-first parsing or unbounded Decimal formatting; rejected.
Contract §5.1/§6/§9 and N01-N08 amend ADR-0021. None of these rules is implemented in this
documentation turn; Astra review remains the gate.

### Stage 1 implementation review status — 2026-10-06

The owner subsequently confirmed Astra GO for stage1-v2 and authorized implementation.
The base contract is supplemented by ADR-0030–0032 below. Worker/CLI/supervisor/Beat entrypoints,
restricted transactional storage, immutable publication and evidence snapshots now have
offline component and combined worker/PostgreSQL/MinIO coverage. The combined proof is
an explicitly seeded one-tile component test, not full regional acceptance.

Implementation remains NO-GO. Astra independently accepted S1-G01 at component scope
and S1-G02 at writer/read-back scope (100,000-row Zstd-3 groups and bounded memory),
without certifying whole-pipeline memory. Its latest review identified HTTP persistence,
split replay and incomplete F01 as blockers. `docs/stage1-gate.md` records the current
fixes, verified evidence and remaining gates. The owner keeps the Argovis key in a private WSL terminal; the agent neither
probes it nor runs live capture. The bounded one-shot capture is owner-run and cannot
substitute for F01's complete authentic corpus or isolated Jan–Mar live acceptance.

## ADR-0030 - Exact translator-backed additive source fields

Adopt Astra's resolution B from the owner-supplied implementation review. Supplement
OpenAPI 2.36.2 with only `chla_fluorescence` and `chla_fluorescence_qc`, supported by
official ifremer-sync revision `cbf2bb48ed5d95532c18bb2cd5217e44618356cf`, helpers.py
SHA-256 `279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f`.
New source version is `argovis-core-2.36.2+ifremer-fluorescence-v1`; preserve aligned
scalar values/QC/attributes only in immutable non-core raw evidence. No CHLA alias,
core mapping/hash change, wildcard allowance or other unknown field acceptance.
Keep data=all. Old source versions reject the additions and retain original manifests.
Contract §3.2 and the machine-readable supplement pin govern provenance and recorder tests.
Inventory declaration is neither complete scientific evidence nor availability assurance.

## ADR-0031 - F01 authentic and labelled synthetic evidence obligations (historical F01-1)

Adopt the explicit evidence split recommended by the owner-supplied Astra review.
Authentic complete inventory/profile/metadata must cover core R/A/D, both directions
and a null in a present core value column. Repeated nonnull pressure requires labelled
derivative preservation/index/diagnostic tests. Supplied errors require labelled
normalized-model/storage/Parquet tests, without inventing API fields or claiming an
authentic parser mapping. A verified mapping and complete capture would be required
for such a later claim. Contract §11 cites the source merge/extraction basis.
This clarifies two obligations rather than waiving F01. Corpus audit witnesses stay
authentic; persisted test evidence accounts for synthetic obligations separately.
At that earlier four-profile audit, core A, descending and source core-value null were
missing. The subsequent admitted 2904014_040 capture proves core A. ADR-0033 supersedes
only the descending/core-null authentic requirements; retain this historical rationale.

## ADR-0032 - Persist HTTP outcomes and preserve validated replay topology

Add portable migration 0007 rather than rewriting prior schema history: admit the
application's `http_failure` attempt disposition with safe numeric status/reason before
retry decisions. The single durable HTTP retry owner retains its four-attempt bound;
Celery automatic retry remains off. Verify mocked 429/503→200, terminal 401/403 and
exhaustion through the real restricted repository and persisted report path.

Actual --replay-run clones a closed complete predecessor's validated split tree and
durable one-to-one predecessor chunk bindings, preserving leaf selection and replaced
ancestors. Require same environment/mode/interval/geometry/source policies, valid full
root coverage, topology/terminal states and node bound. Recheck in a fenced planning
transaction. Reject incompatible, incomplete or component-only plans. Replay raw objects
through normal worker publication with upstream/credential access denied; require
unchanged science/active generations and separately increasing attempts/audits.
Repeating equal fixture-mode inputs is not evidence of this replay path.

## ADR-0033 - Owner-authorized F01-2 authentic-evidence waiver

On 2026-10-07 (Asia/Calcutta) the owner explicitly removed further discovery/capture
for descending direction and nulls in present core measurement columns because obtaining
authentic examples is disproportionate. Version F01-2 supersedes those two authentic
requirements in F01-1; this is a limited acceptance amendment, not a source-contract
change or an authentic observation. Retain both gaps with no authentic witnesses and the
status `authentic_unobserved_requirement_waived` separately from passing component tests.
The policy is machine-readable in docs/stage1-f01-evidence-v2.json and contract §11.

Retain complete recorded R/A/D and ascending evidence, including 2904014_040's 501
A-mode levels. Derive labelled descending and present-core-value-null cases from admitted
R/A captures, retaining attribution, manifest/payload checksums and exact transformations.
Verify direction in parser/canonical/Parquet/database, stable-ID preference, A/D fallback
separation and database uniqueness. Verify null cells in all three present core columns
for both R and A modes through parser, canonical missing reason/hash, PostgreSQL and
Parquet, with ordinal/QC/unit/mode preservation. Distinguish absent variables, missing
QC, counterpart nulls and authentic non-core nitrate nulls.

Repeated-pressure tests remain labelled derivatives. Errors remain normalized-model/
storage/Parquet tests without an invented API column or authentic wire-parser claim.
Keep data=all, source versions/attribution, exactly the two fluorescence supplement
names and fail-closed unknown fields. An amended F01 fixture gate needs both the remaining
authentic minimum and persisted derivative/model/database/Parquet passes; audit alone
cannot certify it. No waiver certifies regional completeness or full Stage 1 acceptance.
The current turn may decide readiness for isolated Jan–Mar acceptance preparation but
must not prepare/execute it. Stage 2 remains blocked pending full acceptance.

## ADR-0034 - S1-DIAG-1 scoped resource evidence and certified spool reuse

The owner-supplied Astra NO-GO requires offline resource-scope diagnostics and
publication-capacity evidence. Retain every existing ceiling, canonical_output_limit
category, quarantine transition and conservative recovery charge. Portable migration
0008 adds fixed numeric scope/operation DETAIL and sanitized frozen resource events;
it is applied only in fresh disposable tests, never to the preserved acceptance DB
in this turn. Invalid/missing/unexpected diagnostic fields are dropped; historical
records are not relabelled. Exception text contains only the safe category.

Round-trip certify each canonical document once per private spool, then verify its
actual SHA-256 before every reuse without regenerating canonical output. Charge
every actual conversion and begin a fresh certification cache on recovery. Keep the
cache bounded by the existing retained/incoming population limits and preserve
temporary/final read-back, commit-time revalidation and complete level replacement.
The resource contract's accounting definition is unchanged; no bytes are credited
back, and neither the original run budget nor its deadline is reset. A bounded
growing-slot publication probe is component capacity evidence, not regional capacity
or whole-pipeline memory proof. See [offline remediation](docs/stage1-offline-remediation.md).

## ADR-0035 - Source-backed fail-closed 404/warning policy and separate terminalization review

Official release 2.36.2 API code initializes search status 404 and switches to 200
only after a document survives post-processing. Empty source arrays can be discarded
even in inventory mode. Pin the source revision/checksums in persisted review evidence;
do not confuse source-code behavior with deployed-version attestation. Keep the
existing 404 failure policy: the 44 saved inventory_before requests have no admitted
successful inventory or response bodies and cannot become verified-empty receipts.
A future empty-policy amendment needs separate review and evidence distinguishing
zero source documents from zero surviving documents. No automatic exception is added.

Executing pinned merge/cleanup functions on labelled synthetic core/BGC inputs
demonstrates that degenerate_levels can accompany discarded core or non-core science,
or an empty result. It does not identify what was discarded in the four authentic
warning profiles. Keep whole-chunk quarantine and zero tolerance; F01-2 waivers and
the exact two-field fluorescence allowance remain unchanged.

The [terminalization procedure](docs/stage1-terminalization-review.md) is **proposed,
not approved or executed**. It targets only the original run with its deployed
migration 0007 finalizer, requires separate owner/Astra review, closes only after its
immutable work deadline (unless explicit operator cancellation is separately chosen),
preserves complete science/catalogue/chunk records, and freezes a partial report under
the existing closing fence. No worker, scheduler, admission, replay, new plan, budget
reset, ingestion restart, migration or object cleanup is part of that procedure.
Terminalizing an incomplete run never certifies full acceptance or authorizes Stage 2.

## ADR-0036 - S1-SOURCE-2 proposed qualified delivery population; inactive

Status: proposed for separate owner/Astra decision, not approved or effective.
[Exact amendment wording](docs/stage1-source-policy-proposal.md) compares strict
scientific completeness (A, still binding) with an explicitly qualified population
delivered by Argovis (B, recommended for review). The latter cannot certify underlying
GDAC science or discarded inputs. Approval of B's population alone would not activate
the optional three-response 404-empty rule or whole-profile source-loss exclusion.
Each requires its exact acceptance/reporting change, deployment evidence and tests.

The narrow 404 proposal requires coherent complete bounded inventory-before,
data=all and inventory-after responses for the identical supported collection
selection. Metadata/id requests, mixed outcomes, framing/schema ambiguity and
unattested deployment behavior fail closed. Historical 44 status-only failures stay
failed. The exclusion proposal preserves entire affected profiles as raw evidence,
IDs/selections and a ledger with unknown lost levels; it cannot accept their returned
science as complete or silently pass quarantine acceptance. Unknown warnings and
schema drift still block the whole chunk. Existing eight quarantines remain intact.
Test-only proposal oracles do not alter production, fixtures or the F01-2 waiver.
No alternate source adapter, live capture or policy activation occurs in this task.

## ADR-0037 - S1-RESOURCE-2 bounded canonical encoding and publication certification

Every actual canonical byte remains charged under the same profile/chunk/run caps.
Bounded per-level C encoding uses a conservative output preflight and only runs
when the result fits every remaining allowance; otherwise the original streaming
path applies. Sorted canonical bytes, numeric semantics, scientific hashes,
rejection precedence and resource diagnostics remain unchanged. The preflight emits
no canonical output and allocates no unbounded encoded profile.

A publication-scoped certificate verifies full scientific membership once for the
first object payload, then requires complete byte-count/SHA-256 equality and
schema/count/row-group checks on subsequent read-backs. Local certification and
first payload remain fully verified and charged. Recovery or rebuilding an intent
creates a new certificate and charges certification again. No payload/row cache,
budget credits, waived raw verification or weakened transactional fences are allowed.
Corruption, cache invalidation, fresh-process/rebuild and exact-boundary tests apply.

The current capacity model uses one persisted run, the actual 1,260-root Jan–Mar
plan and unchanged 10 GiB/six-hour limits, uneven growing slots, revisions, no-op
deliveries and bounded fault/rebuild overhead. Its admitted-authentic derivatives
are labelled synthetic. Whole-worker pipeline memory and writer-only memory are
separate evidence. Even successful measured capacity is not a regional census or
a bound on unknown profile depths, occupied slots or additional retries. No original
budget/deadline is changed; regional feasibility remains a separate gate.

## ADR-0038 - Concrete migration-0007 terminalization candidate; review only

[The guarded command and recovery runbook](docs/stage1-terminalization-review.md)
target only the stopped preserved session. They require separate approval, exact
database/run/environment/scientific manifests, source/function pins and counters,
and database time past the immutable final deadline. Only the existing finalizer
may mutate state; no migration 0008, controller tick, dispatch or ingestion runs.

A serializable transaction retains complete/failed/quarantined rows, fences planned
work to deadline failures and freezes one closed/partial incomplete record. Retry
validates either the original open snapshot or the exact already-closed result;
successful commit is never rejected merely because planned rows are now terminal.
Disposable tests model the 120/44/8/1,088 state shape and terminate real connections
before/after commit. Their small labelled science/catalogue fixture does not clone
or certify the original data. The original procedure remains unexecuted. Expected
exit 3 records incomplete acceptance; stop-only cleanup retains every volume/object.

## ADR-0039 - Owner authorization for Stage 1 completion and Stage 2 (2026-10-07)

Decision recorded from the owner's (Aayush's) instruction in the agent session on
2026-10-07, which the owner confirmed in writing in the same session:

- The owner provided `ARGOVIS_API_KEY` in the git-ignored file `.env.txt` in this
  checkout and authorized its use for live Argovis calls and other network access
  needed to finish Stage 1 and Stage 2.
- The owner authorized operating the preserved acceptance session, including its
  documented terminalization, as part of finishing Stage 1.
- The owner replaced the Astra review gate with the advisor model (Fable): pushing,
  closing the Stage 1 gate and starting Stage 2 follow the advisor's agreement, and
  each such agreement is recorded in PROGRESS.md.
- The owner asked for Stage 1 to be completed and then Stage 2.

Alternatives: keep per-step owner/Astra approvals (rejected by the owner). Unchanged
by this decision: credentials stay out of commands, arguments, logs, fixtures,
reports and Git; limits and scientific/source rules change only through ADRs that
cite measured evidence; historical evidence keeps its stated scope.

## ADR-0040 - Activate S1-SOURCE-2: qualified delivered population (stage1-v3)

Decision under ADR-0039, advisor (Fable) agreed 2026-10-08. The inactive ADR-0036
proposal becomes active for runs admitted with `RUN_POLICY.source_policy =
"S1-SOURCE-2"`, with the receipt clause matched to the observed deployment.

Evidence: `reports/stage1-live-empty-semantics.json` (two of the 44 historical 404
selections, all three roles, repeated three times) and
`reports/stage1-inventory-census.json` (all 1,260 Jan-Mar 2025 weekly leaves): every
empty selection, 338 of 338, returned HTTP 404, `application/json; charset=utf-8`,
chunked, with the same 5-byte body `[\n\n]\n` (an empty JSON array). Non-empty
selections returned 200. The 44 historical 404s are land-dominated tiles.

1. Empty-delivery receipt (§3.2/G05). Only `/argo` requests with exactly
   startDate/endDate/polygon (inventory roles) or those plus `data=all` (profile)
   qualify. A response qualifies only as HTTP 404, `application/json` (any charset),
   complete framing, raw body at most 64 bytes that parses to exactly an empty JSON
   array. Error envelopes, nonempty or malformed bodies, other content types,
   truncation, `id` requests and `/argo/meta` remain failed HTTP 404s. All three
   roles must share one status; a mixed 200/404 triple is retried like a changing
   inventory and fails after the existing selection budget. The receipt is
   persisted as verified raw evidence with `raw_manifest.http_status = 404` and
   proves "no service-returned eligible documents", never "no source science".
2. Whole-profile source-loss exclusion (§8/F04/F05). A profile whose only warning is
   `degenerate_levels`, with a source `_id`, whose remaining schema validates and
   which the chunk's tile owns, gets outcome `excluded_source_loss`: never published,
   returned levels recorded, lost levels `unknown`, and its warning, source ID,
   selection and raw landing kept in the ledger. Any other or additional warning,
   missing identity or schema drift still quarantines the whole chunk.
3. Reports state `S1-SOURCE-2`, receipts by role, the exclusion ledger,
   `acceptance_qualified_with_source_exclusions` when exclusions exist, and never
   `scientific_source_complete = true`. Acceptance still needs zero quarantines and
   zero coverage gaps.

Historical runs are unchanged: their 44 failures and 8 quarantines stay as recorded.

## ADR-0041 - S1-RESOURCE-3: monthly plan v2 and a 40 GiB run canonical-work cap

Decision under ADR-0039, advisor (Fable) agreed 2026-10-08. Measured inputs:

- Census (`reports/stage1-inventory-census.json`): 5,845 unique owned profiles in
  Jan-Mar 2025, 922 non-empty and 338 empty leaves, densest month/tile slot 87.
- Canonical size: 1,214 bytes per level over five authentic profiles (1,162 levels).
- Depth: 699 levels/profile in the original January run; 384 in a February/March
  spot-check (`reports/stage1-depth-spotcheck.json`, 38 profiles, max 1,450). The
  higher January figure is used.
- Amplification: weekly slices republish the whole month/tile slot, about 13
  canonical conversions per profile (capacity model operations; 10.72 GB charged
  for 0.69 GB of content in the original run). With one publication per slot the
  same pipeline performs four (normalization, spool certification, local and object
  read-back).

Decisions:

1. Plan v2 (`indian-ocean-plan-v2`): initial slices are whole UTC calendar months
   clipped to the request, 10-degree tiles unchanged (270 roots for Jan-Mar).
   Adaptive splitting, slot keys, ownership and catalogue semantics are unchanged.
   A full-month `data=all` request on the densest slot returned 200 with 87
   profiles in 2.66 MB (`reports/stage1-monthly-request-check.json`), inside the
   16 MiB response and 256 MiB chunk caps. Splits remain possible and are why the
   cap below carries margin.
2. Run canonical cap 10 GiB to 40 GiB: 5,845 x 699 x 1,214 B x 4 conversions x 2
   margin = 39.7e9 bytes, about 37 GiB, rounded up. Profile 16 MiB, chunk 256 MiB, the
   16 MiB reservation and every request, attempt, level and profile bound stay.
3. The six-hour run limit, two workers and one credentialed request in flight are
   unchanged and are now the binding guard. The time projection is not evidence;
   only the acceptance run measures it.

Week-bucket slots were rejected: they need plan alignment, scheme versioning,
migration of month-keyed catalogue rows and more cross-slot revision moves.

## ADR-0042 - Worker memory compliance criterion

The 1 GiB per-worker bound is enforced, not reinterpreted upward: each worker runs
with cgroup `memory.max` = 1 GiB (the worker refuses to start otherwise). Compliance
means zero `oom` and `oom_kill` events for the worker cgroup during the run and a
pipeline anonymous RSS peak below 1 GiB. The kernel's page-cache-inclusive
`memory.peak` counter is recorded but is not the pass criterion, because reclaimable
file cache is charged to the cgroup and can touch the limit without memory pressure.
The earlier capacity model (peak counter 1024.6 MiB, pipeline RSS 455.1 MiB, no OOM)
is reported under this criterion with both numbers shown.

## ADR-0043 - Run wall-time 12 h and 60 s idle read (stage1-v3 runtime amendment)

Decision under ADR-0039, advisor (Fable) agreed 2026-10-08. ADR-0041 kept the six-hour
run limit as the binding guard and called its time projection unverified. The first
stage1-v3 live run measured it (`reports/stage1-live-throughput-c9af101a.json`,
interrupted after 14 minutes, measurement only):

- About 4.3 MB canonical work per profile (plan v2 works; 5,845 profiles need about
  25 GB, inside the 40 GiB cap), processed at about 0.9 MB/s by one worker: roughly
  5-7 s per profile including fetch and publication, about 10.5 hours for the region.
- Six inventory-before attempts failed as `upstream_transport_failure` after about 21 s:
  full-month inventory queries can take Argovis more than 20 s to the first byte, so
  the 20 s idle-read bound tripped while the 120 s attempt bound had room.
- One worker's anonymous memory peaked at 319 MiB with zero OOM events
  (`reports/stage1-live-memory-c9af101a.json`).

Decisions: the idle-read timeout becomes 60 s inside the unchanged 120 s attempt bound
(a correctness fix for monthly inventories), and the hard run wall-time bound becomes
12 hours (CLI, runtime, migration 0010 table constraint and `admit_run`). One live
worker and one credentialed request in flight stay; two workers in one 1 GiB cgroup
were rejected (would halve the per-worker bound), and two separate worker containers
were deferred as riskier orchestration on a 3 GB host. The 60-second final evidence
reserve, retry counts and every other bound are unchanged.

## ADR-0044 - Set-based publication level checks and an owner-slot index

Advisor (Fable) agreed 2026-10-08. The third live run (session 5f59c62f122295a7) failed
one leaf with `database_deadline` (`reports/stage1-live-commit-5f59c62f.json`): a chunk
of 35 deep profiles (42,374 levels) held the publication transaction past 60 s, and the
controller heartbeat timed out waiting for the run row lock meanwhile. Cause:
`commit_publication` validated and inserted levels one at a time and fetched each
level's canonical value with `science->'levels'->i`, copying the profile's whole level
array per level. A disposable benchmark measured 312 ms for one 1,210-level profile
against 2 ms set-based; cost grew with depth squared, which monthly chunks exposed.

Migration 0011 replaces only that block: one set-based index check
(`invalid_level_index`), one set-based content check (`measurement_content_mismatch`,
same 12 numeric and 24 non-numeric fields), one set-based insert that always stores
the canonical exact values (positive zero), and the unchanged `level_set_mismatch`
count. New tests assert each category and the canonical-value rule. It also adds an
expression index on exactly the `app.owner_slot(...)` expression every catalogue
membership and receipt query uses, so those no longer scan all stored profiles.

Measured on one 10,000-level profile (`tests/stage1/test_publication_scale.py`): the
first set-based version still took 23.5 s because `(jsonb_populate_record(...)).*`
evaluates the function once per output column (about 45); the per-level loop had the
same pattern. Evaluating it once per level through `LATERAL` brought the commit to
1.3 s. The scale test fails above 10 s.

Rejected: raising the 60 s transaction bound (keeps the run row locked and the
controller heartbeat failing), splitting on a level budget (reintroduces retained
re-certification and refetches) and reverting to weekly slices (13x amplification).

## ADR-0045 - Retry window sized to upstream slow episodes

Advisor (Fable) agreed 2026-10-08. The fourth live run (session 8e8da1d40a8ba7f9) failed
one leaf with `upstream_transport_failure`: all four `inventory_after` attempts for
January 110E/-50S timed out at the 60 s idle read between 11:14 and 11:18 UTC
(`reports/stage1-live-transport-8e8da1d4.json`). A bounded probe during the episode
took 80.2 s for that month inventory; uncached month and week inventories took 1.2-1.6 s
afterwards. The slowness was a server episode of at least 15 minutes, not request
size, so splitting would not help. The 2/4/8 s backoff let four attempts span only
about four minutes.

Decisions: backoff maxima become 60/180/300 s with equal jitter (half the maximum plus
a random half), a contract wording change from full jitter, so four attempts span
about 9-16 minutes; Retry-After still wins when longer and stays capped at 300 s; four
attempts per logical request are unchanged. The idle read becomes 110 s inside the
unchanged 120 s attempt bound; the first-byte latency distribution during episodes is
unmeasured, so the backoff, not this value, carries the robustness. Waits heartbeat
every 10 s, so the 10-minute chunk lease holds. With one worker an episode now stalls
the run instead of failing it; the 12-hour bound and the stall alarm cover that.
Credentialed probes are not run while an acceptance run is live.

## ADR-0046 - missing_basin is an informational source warning

The fifth live run (session 7153be6379df84de) completed 269 of 270 leaves; one chunk
(March, 50E/-20S) quarantined with `upstream_data_warning` because profile
`1902191_253` (50.50E, 14.00S) carried `missing_basin`
(`reports/stage1-live-warning-census-7153be63.json`). Across all 5,931 landed profile
documents the only warnings were 31 `degenerate_levels` and this one `missing_basin`.
The pinned OpenAPI 2.36.2 enumerates exactly four warnings: `degenerate_levels`,
`missing_basin`, `missing_location` and `missing_timestamp`.

The pinned translator (revision cbf2bb48, `util/helpers.py`, SHA-256 279af8ef...,
re-verified 2026-10-08) adds `missing_basin` only when the location is present and the
0.5-degree basin mask is land at every surrounding point (basin = -1). Position, time
and measurements are unchanged; FloatChat does not use the basin label.

Decision (stage1-v3, S1-SOURCE-2): a profile whose warnings are a duplicate-free subset
of {`degenerate_levels`, `missing_basin`} and that has a source `_id` validates with the
warnings stripped. `degenerate_levels` keeps the whole-profile exclusion (ADR-0040);
`missing_basin` alone publishes normally, with the warning kept in the immutable raw
landing and in the pre-commit outcome evidence. `missing_location`, `missing_timestamp`,
any repeated or unknown warning, a missing identity or schema drift keep the strict
whole-chunk quarantine, because ownership cannot be established without a real
position and time. The processor probe covers all five cases.

## ADR-0047 - PostgreSQL work queue with acquire and process pools; per-environment concurrency

Decision under ADR-0039 per the owner decisions of 2026-10-08 recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/D.md` (queue, controller, worker pools, migration 0012) and
`docs/v4-packages/H.md` (acceptance topology and memory sampler). Amends contract §8.1
(acquire-to-process hand-over), the §9 concurrency/memory row, the §9 retry paragraph
(Celery autoretry, opaque task IDs) and §10 (Celery Beat). Supersedes ADR-0043's deferral of
two worker containers, the "two workers" part of ADR-0041 decision 3 and the
single-container reading of ADR-0042's criterion.

Measured inputs:

- The serial pipeline is one worker alternating between 90-100% of one core and 10-40% while
  it waits on the upstream or the database (`reports/stage1-perf-live-cpu-sample.txt`,
  `docs/ingestion-performance-review.md` §3.1). The census-weighted serial model is
  3.14-4.47 h: HTTP selection 1.12-2.45 h, metadata 0.55 h, worker CPU 1.14 h, COPY and
  commit 0.33 h (`reports/stage1-perf-run-model.json`).
- Celery and Redis overhead was measured as negligible (planned-to-fetching 0.1-5 s with an
  idle worker in session c9af101a). This change is therefore not a speed measure; the owner
  decision of 2026-10-08 is its authority.
- One worker's anonymous peak was 280-335 MiB in live runs (`reports/stage1-live-memory-*.json`);
  the 3.7 GB host carried the six live containers at about 1.0-1.3 GB with 2.1 GB available
  (review §3.6). No measurement exists for the two-container topology: package H ran no
  Docker command.

Decisions:

1. Queue. `app.processing_ticket` gains `kind` (`acquire` or `process`), `claimed_by`,
   `claimed_at` and `created_at`; it is unique on `(chunk_id, fence, kind)` and has a partial
   index on unstarted tickets. `app.claim_ticket(kind, worker)` claims the oldest ticket with
   `FOR UPDATE ... SKIP LOCKED` and returns only a ticket that `app.start_worker` would accept:
   matching epoch and fence, live chunk and controller leases, open and uncancelled run, before
   the work deadline, chunk not terminal. A claimed ticket whose worker never started is handed
   out again after two minutes; `started` still admits exactly one executor
   (`duplicate_delivery`). Tickets carry opaque IDs only, as Celery tasks did. Celery, Celery
   Beat and Redis are removed from the workers and the acceptance Compose project.
2. Two worker kinds. One acquire process per environment runs `Processor.land()` in N threads
   (ADR-0048). A pool of M single-use spawn-context processes runs `Processor.process()` with
   sources that must find existing landings (`require_existing`); the parent claims the ticket,
   a killed child frees its slot at once and prints `worker_lost`, and its chunk lease expires
   into recovery. Only the acquire process ever holds the Argovis key.
3. Hand-over under one claim. After `land()` returns `landed`, the acquire worker creates the
   `process` ticket under the same epoch and fence, so normal phase progress still consumes no
   extra claim (§8.1) and a healthy chunk costs one claim. The controller issues tickets by
   phase only for recovery claims: `acquire` for planned and fetching chunks, `process` for
   landed, validating and publishing chunks. If the hand-over fails or the acquire worker dies
   between `landed` and the hand-over, the lease lapses and the chunk is re-queued under a new
   budgeted claim.
4. Leases while waiting. Every controller tick calls `app.extend_unstarted_leases(run, epoch)`,
   which renews the 10-minute lease of nonterminal chunks whose newest fence has an unstarted
   ticket. It never revives a lapsed lease and never touches a started or superseded ticket, so
   queue wait spends no processing claim and a worker that dies after starting is still
   recovered by a claim. Consequence: when no worker consumes a queue, the waiting chunks stay
   leased and count against `max_active_chunks`, and the run ends at its work deadline
   (`deadline_expired`) or by cancellation instead of `recovery_budget_exhausted` after four
   lapses.
5. Per-environment concurrency. `ingestion_environment.max_active_chunks` (default 8, range
   1-64) replaces the constant 2 in `app.claim_chunk` and in the controller; chunks that wait
   `landed` for the process pool count against it. `ingestion_environment.upstream_slots`
   (default 4, range 1-16) is the ceiling for `acquire --slots`; a larger request exits with
   `acquire_slots_exceed_environment`. Process workers come from `INGESTION_PROCESS_WORKERS`
   (design default `min(4, cpu)`), acquire threads from `INGESTION_ACQUIRE_SLOTS`. The
   acceptance Compose defaults are 4 acquire slots and 2 process workers on this 3.7 GB host;
   the documented production sizing for an 8 GB host is 4 process workers in a 4 GiB container.
   The defaults 8 and 4, the two-minute re-claim, the 1 s idle poll, the 30 s backoff cap and
   the 3,600 s default `compact` budget were chosen without a measurement behind them.
6. Memory. Each process worker is bounded to 1 GiB. `bounded_worker_memory` accepts a cgroup
   `memory.max` of at most 1 GiB, otherwise lowers the soft `RLIMIT_DATA` to
   `INGESTION_WORKER_MEMORY_BYTES` (default 1 GiB, accepted range 128 MiB to 1 GiB, so
   configuration can reduce the bound but not raise it). It never uses `RLIMIT_AS`, which breaks
   pyarrow's allocator (design §2); design §4.4 still says `RLIMIT_AS` and is the inconsistent
   text. One acquire process shares a single data limit across its threads.
7. ADR-0042 criterion for the two-container topology (package H). The memory report passes only
   if both an acquire (or live-acquire) container and a process container were sampled and every
   container shows zero `oom` and `oom_kill` events and an anonymous peak below its own
   `memory.max`. `memory.max` must equal exactly 1 GiB for the acquire containers; for the
   process container it must only be finite (2 GiB here, 4 GiB in production). The per-worker
   1 GiB bound inside the process container is `RLIMIT_DATA`, which the cgroup counters cannot
   see; the report therefore proves the container, not each worker.
8. Scheduling. `floatchat schedule` replaces Celery Beat: one UTC-daily admission run by cron or
   a systemd timer, serialized by advisory lock `(164993423, 2)`. Outcomes `created`, `existing`,
   `recover`, `overlap_skip`, `live_ingestion_disabled` and `schedule_already_running` exit 0;
   `acceptance_schedule_disabled` exits 2; `scheduling_failed_no_sensitive_diagnostics` exits 5.
   `beat_scheduler_already_running` is renamed `schedule_already_running`. The §10 admission
   lease, overlap record, watermark and live-disabled flag rules are unchanged.
9. Redis. Stage 1 workers and the acceptance project need no Redis. The Stage 0 API still
   requires it (`redis_url` configuration and the readiness check), so the dev Compose keeps
   `redis`; it no longer starts a worker service.

Rejected: issuing the `process` ticket only after the lease expires (a landed chunk would idle
up to 10 minutes and spend one of four processing claims per chunk); `multiprocessing.Pool`
(never completes a task whose worker was killed, which leaks the slot on an OOM kill); each
child claiming its own ticket (an idle queue would cost an interpreter start per poll); keeping
Celery on a speed argument (negligible overhead); two workers inside one 1 GiB cgroup (ADR-0043).

Unchanged: control epochs, fencing, 10-minute leases with 60-second heartbeats, the four
controller, processing and publication claims, the §8.1 recovery table, the state machine, run
bounds, credential handling, the 12-hour bound.

Verified on the integrated head (2026-10-08): migration 0012 applies on the foundation image and
`tests/stage1/test_queue_sql.py` passes inside the stage1 integration suite (114 passed, 0
failed, `docs/v4-packages/INTEGRATION-1.md`); offline, 160 tests passed for the queue,
controller, CLI and worker. Not verified: the acceptance Compose topology and the memory-sampler
wiring have not run under Docker (the next `prepare` is their first run); nothing watches the
process container during `execute`, so a dead parent stalls chunks until the run deadline;
tickets that lost their fence stay in the table (inert, bounded by claims).

## ADR-0048 - Adaptive upstream concurrency and thread-safe transport

Decision under ADR-0039 per the owner decisions of 2026-10-08 (adaptive parallel Argovis
requests on one key, start at 4, back off on HTTP 429, no multi-key rotation) recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/E.md`. Amends the §9 concurrency/memory row ("1 credentialed upstream request
in flight"), the §9 I/O deadlines row and the §9 retry paragraph. The review
(`docs/ingestion-performance-review.md` candidate 10) asked that the owner check the Argovis
usage terms first; no report on this branch records that check or any Argovis-side rate limit.

Measured inputs:

- HTTP selection is 1.12-2.45 h of the serial 3.14-4.47 h run and metadata 0.55 h
  (`reports/stage1-perf-run-model.json`; role means from
  `reports/stage1-live-transport-8e8da1d4.json`: inventory_before 24.6 s, data=all 12.2 s,
  inventory_after 2.9 s). With one request in flight the optimistic floor for Jan-Mar through
  Argovis is about 0.8-1.1 h (review §1).
- No measurement of the effect of concurrency exists. `reports/stage1-v4-bench-E.json` uses a
  fake transport; the 33 thread tests in `tests/stage1/test_transport_threads.py` use
  socketpairs; the acquire threads were exercised only through fakes. The real Argovis
  behaviour at 4 requests in flight, including during a slow episode (ADR-0045), is unmeasured.

Decisions:

1. Up to N credentialed requests may be in flight, where N is the acquire process's `--slots`
   and at most `ingestion_environment.upstream_slots` (default 4). Each permit maps to advisory
   lock `(164993423, slot)` through `Repository.upstream_slot(authority, deadline, slot)`, so a
   second acquire process cannot exceed N. One key is used; there is no key rotation.
2. `UpstreamGovernor(permits, pause=60, restore_after=20)` paces the requests in process.
   `acquire` blocks and returns the lowest free slot; on HTTP 429 the permits halve (floor 1;
   a burst of in-flight 429s can go 4, 2, 1) and no new request starts for the larger of
   Retry-After and 60 s; every 20 consecutive non-429 completions restore one permit up to N.
   Only 429 reduces permits. Timeouts, 5xx and transport failures count as completions toward
   restoration. This is the stated behaviour, and the review's warning that concurrent requests
   amplify retries during a slow episode is not mitigated by the governor itself; the backoff of
   ADR-0045 is.
3. The governor is advisory pacing, not a retry owner. The durable controller and owner stay the
   only retry owner: at most four attempts per logical request, equal-jitter delays over maxima
   60, 180 and 300 s, Retry-After capped at 300 s (ADR-0045). Retry-After additionally lengthens
   the governor's pause.
4. The permit and the advisory lock cover the request only. They are released before any retry
   delay and before sanitization, publication and `finish_attempt`, which now run after the
   lock.
5. The transport is thread-safe and no longer uses a POSIX alarm. DNS, connect and TLS share the
   10 s budget; the 110 s idle read is re-armed with `settimeout(min(110, left))` before each
   read; the 120 s attempt bound (or the run bound) is checked after each read. Connect-phase
   timeouts and errors after the bound map to `io_deadline`; idle-read timeouts and other socket
   errors map to `upstream_transport_failure`; both stay retryable. `empty_receipt` lets
   `io_deadline` through instead of making it a permanent 404. One process-wide TLS context
   replaces one per connection. The numeric bounds of §9 are unchanged.
6. Known gaps of the timing model: `getaddrinfo` has no timeout, so a DNS overrun is rejected as
   `io_deadline` only after it returns; a single `read(65536)` that dribbles bytes inside the
   idle timeout cannot be interrupted until it returns, so the 120 s bound is exact between
   reads, not inside one; object writes are bounded per socket operation, not in total. Reads
   from the object store check the bound between 64 KiB parts (ADR-0050).
7. Each acquire thread owns its `Repository`, budget repository, `RequestOwner` and `Processor`;
   only the governor and the TLS context are shared.

Rejected: key rotation (owner decision); reusing HTTPS connections to the pinned address (review
candidate 14, not implemented: still `Connection: close`); single-flight per metadata pointer
(two threads that miss the same float both fetch it; the cache upsert only moves forward, so
this is harmless).

Unchanged: the pinned host, port 443, address validation and no redirects (§9), the credential
rules, the 16 MiB response bound, 50,000 HTTP attempts per run, the retry counts.

Not verified: the governor's counters (`snapshot()`: observed 429s, lowest permits, restored
permits) exist in process only; no report or persisted evidence carries them (package H did not
implement it), so a live run cannot show whether the governor engaged. Two acquire processes
both start at slot 1 and wait on its lock instead of trying slot 2 (correct, not optimal). No
wall-clock claim is made for this ADR.

## ADR-0049 - Float-metadata cache with per-chunk cache-origin manifests

Decision under ADR-0039 per the owner decisions of 2026-10-08 recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/E.md` (cache logic) and `docs/v4-packages/D.md` (migration 0012 table and
function). Amends contract §3.2 (metadata pointer resolution), the §9 requests/data row and the
§11 raw-evidence rule that identical blobs may serve many attempts.

Measured inputs:

- About 2,000 `/argo/meta` requests per Jan-Mar run at a 0.99 s mean (103 samples) are 0.55 h of
  serial time, and each request costs four object-store operations and three or four database
  transactions: about 8,000 and 6,000 per run (review §3.5 and §4.4,
  `reports/stage1-perf-run-model.json`).
- `reports/stage1-v4-bench-E.json` (fake transport, 12 chunks, 16 distinct floats, 5 metadata
  requests per chunk, 3 selection requests per chunk): HTTP attempts in one run fall from 96 (60
  metadata) to 52 (16 metadata) with 44 attempts of origin `cache`; a second run created 20 days
  later needs 36 (no metadata request); a second run created 45 days later needs 52 again.
  The 16-of-60 repeat ratio is fixed by the scenario. The real share of repeated floats in a
  Jan-Mar run has not been measured, so the saving at 2,000 requests is unknown.

Decisions:

1. `app.float_metadata_cache(environment_id, pointer, raw_manifest_id, run_id, retrieved_at)`,
   primary key `(environment_id, pointer)`, restrictive foreign keys to the environment, raw
   manifest and run. `app.metadata_cache_put` upserts only forward in time and refuses a manifest
   that is not this run's in this environment (`invalid_metadata_cache_entry`). The application
   role has no privilege on the table. Only `/argo/meta?id=` requests of role `metadata` are
   cached.
2. Reuse predicate: a cache row is usable when `retrieved_at >= created_at_actual_utc - 30 days`
   of the current run, with no upper bound, where the anchor is the run row's actual creation time
   read once per owner. The reference time T bounds scientific eligibility, not evidence
   freshness: a first version bounded by T almost never hit, because chunks are fetched after T
   and an acceptance run's T (2025-04-01) lies a year before a live fetch. The design brief's
   wording (within 30 days before T) is replaced by this predicate. The 30 days are a policy value
   chosen pending measurement; the stated reason (metadata rarely changes) is not measured.
3. A hit is still a per-chunk landing. The owner reads the cached object back and verifies length,
   SHA-256 and versions, records an attempt with origin `cache` (`recorded_reserve`), and finishes
   it as `verified_raw` with a new manifest id that points at the same immutable object
   (`sanitization.input_origin = "cache"`, the cache manifest and inherited validation). No
   request, no object write and no `validate_raw` happen. Every chunk therefore owns a
   `verified_raw` attempt per metadata request, `verified_landing` finds it on reload, and replay,
   which resolves each chunk's own manifest by logical request key, keeps its identity. An
   unverifiable cache entry is a miss (refetch and replace), not `landing_unavailable`.
4. A hit is not an HTTP attempt: the 50,000 HTTP attempts per run count real requests only, and
   reports show hits as origin `cache` in `payload_accounting`.
5. Fixture and replay inputs and the GDAC source never consult the cache. Replay still resolves
   predecessor manifests.
6. A metadata raw manifest may point at an object landed by another chunk or another run
   (objects are content-addressed), which §11 already allows.

Rejected: bounding reuse by T (nearly never hits); reusing an object without a per-chunk attempt
(replay would fail with `replay_selection_unavailable`); caching the three selection roles
(only metadata is stable enough to share; the selections are the data).

Unchanged: the metadata bytes, canonical output and hashes (metadata affects `platform` only),
`argovis-core-v1` mapping, the four attempts per logical request.

Verified on the integrated head (2026-10-08): migration 0012 (table, function, `cache` origin)
applies on the foundation image and `request_owner_probe.verify_metadata_cache` executed inside
the combined processor integration case (`tests/stage1/processor_probe.py`, passed). Open:
`Repository.metadata_cache_get` returns no stored `sanitization`, so a hit manifest carries a
synthesized one rather than a copy of the original evidence.

## ADR-0050 - Verification by hash: write-once Parquet, Arrow-equality verification, checksum-verified upload, sampled audit

Decision under ADR-0039 per the owner decisions of 2026-10-08 recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/C.md` (Parquet, objects, MinIO) and the validate-once part of
`docs/v4-packages/E.md`. Amends contract §7 publication steps 3-5 and the S1-RESOURCE-2
implementation note; keeps ADR-0037's certification reuse rule (the first payload is now the one
`write_snapshot` verified).

Measured inputs (87 profiles x 699 levels = 60,813 levels, synthetic clone, memory store, shared
host, so absolute times are noisy):

- stage1-v3 baseline (`reports/stage1-v3-bench-chunk-baseline.json`): `write_snapshot` 17.69 s of
  which `verify_snapshot` 10.85 s; `publish_verified` 9.83 s; `validate_raw` 2.05 s.
- stage1-v4 (`reports/stage1-v4-bench-chunk.json`): `write_snapshot` 3.117 s including a 1.065 s
  Arrow-equality scan; `publish_verified` 0.011 s; `validate_raw` 0.215 s.
- Package C (`reports/stage1-v4-bench-C.json`): `write_snapshot` 25.6 s to a best of three of
  2.75 s (the same code ranged 1.7-14.7 s under neighbours' load; interleaved in one session the
  v3 module took at least 16.29 s and the new one at least 2.12 s); `publish_verified` 12.0 s to
  0.013 s. Informational: an uncertified verifier call 9.4 s and `write_snapshot(audit=True)`
  10.2 s.
- Package C's offline emulation of the 1 GiB writer proof input (4 and 2 profiles of 10,000
  levels with a 65,536-byte sampling header) peaked at 257 and 290 MiB anonymous (v3 writer, 2
  profiles: 212 MiB) with identical Parquet bytes; this was a scratch run, not a report, and the
  integration test itself was not run.

Decisions:

1. `write_snapshot` builds Arrow arrays once (the mapper's `level_table` plus the per-profile
   columns) and writes with the unchanged `WRITER_OPTIONS`. The Parquet bytes, the
   `normalised/sha256/<hex>` keys, `membership_sha256`, `schema_sha256` and `storage_comparison`
   are identical to the stage1-v3 writer (permanent test
   `test_arrow_rows_equal_rows_oracle_and_file_bytes_equal_v3`). The spilled Arrow batches are
   re-cut to 64 rows from each row-group start, because Parquet page cuts depend on Arrow chunk
   edges.
2. Verification method `arrow-equality-v4` replaces the row-by-row first verification. The file
   is reopened and checked: schema equality including metadata, the total-row and row-group
   bounds, row-group sizes equal to the spill's, profile segments and their constant header,
   hash and alias, `level_index` equal to position, the profile hash recomputed from the stored
   header re-framed around the concatenated `canonical_level` strings (never re-encoded from
   dicts), and `Table.equals` against the spilled rows per batch. The verdict is raised after
   every profile hash has been checked and is named by the first differing column. Identity
   order, alias uniqueness and the resource bounds are applied while writing, from the strings in
   hand. Rejection categories keep their meaning.
3. Two checks of the old row-by-row pass now run only in the audit: each numeric column value
   re-derived from its exact text, and each level's embedded `level_index` against its column.
   On the Arrow path they hold by construction, because the float columns and the canonical text
   are both outputs of one `map_profile`/`level_table` and the read-back must equal those
   columns. A mapper that emitted a float column inconsistent with its canonical text would be
   caught by the audit only.
4. Certificate: `write_snapshot` returns a `PublicationSnapshotVerifier` certified for the file's
   exact SHA-256 and byte count. A certified verifier runs the light check (SHA-256, length,
   schema, row groups, counts); an uncertified one still performs the full first call. There is no
   payload cache, a certificate does not cross a process or an intent, and recovery or a rebuild
   writes and certifies a new file.
5. `publish_verified` validates the payload once, then `write_immutable`: one conditional PUT
   (`If-None-Match: *`) with `ChecksumAlgorithm=SHA256` and the payload digest, which the server
   verifies. `stat` (HEAD with checksum mode) must then report the byte count and, when the store
   returns one, the same SHA-256 (`object_checksum_mismatch`). No `tmp/<intent>/<id>` object is
   written any more and the temporary-to-final copy with a second read-back is gone; a
   `temporary_key` is still validated. A 412 (key exists) is not trusted: `stat` must agree on
   size and stored checksum, and when the server holds no SHA-256 the bytes are read back and
   hashed, which closes the equal-length hole of a length-only comparison. An existing key is
   never overwritten. The codes `BadDigest`, `InvalidDigest`, `XAmzContentChecksumMismatch` and
   `XAmzContentSHA256Mismatch` mean the bytes did not match and never fall back. A server that
   refuses the parameters (HTTP 501, `NotImplemented`, or a 400 naming the checksum) disables
   checksums for the life of the store and every later plain write is verified by a full
   read-back.
6. Raw objects use the same path. `raw` widens from a boolean to `.json` (true) or `"nc"`
   (`raw/sha256/<hex>.nc`, used by ADR-0052). Raw bytes are decoded by `validate_raw` once per
   landing; reloading an existing landing trusts the stored bytes, SHA-256 and versions. In the
   12-chunk scenario of `reports/stage1-v4-bench-E.json` the `validate_raw` calls fall from 384
   (baseline) to 156 (package E's modules) and to 52 (with package C's objects as well).
7. Audit. `write_snapshot(audit=True)` additionally runs `verify_snapshot` row by row and
   requires its four evidence values to equal the Arrow ones (`object_validation_mismatch`);
   `publish_verified(audit=True)` additionally reads the object back and revalidates. The review
   proposed running this on every Nth chunk or on every chunk in acceptance mode. This ADR does
   not set the cadence, no measurement supports a value, and nothing calls `audit=True` today
   (no processor setting exists): the periodic audit is a capability, not a running control, until
   the cadence is decided and wired.
8. The default path no longer charges the run counter for a verification re-encode (one fewer
   encode per profile); `audit=True` charges as before. Every canonical conversion actually
   performed is still charged (ADR-0037).
9. Categories. New or surfaced: `object_stat_failure` (added to `FAILURES`, so a transient HEAD
   failure after the PUT fails the chunk instead of quarantining it), `invalid_object_checksum`,
   and `io_deadline` from `MinioStore.read`, whose stream loop now checks the bound before every
   64 KiB part. The light certificate check reports `parquet_schema_mismatch` or
   `object_validation_mismatch` where it used to say `invalid_parquet`. `write_snapshot` no longer
   masks `object_size_limit` or `snapshot_deadline` at a group edge with a closed-file error.

Rejected: keeping the temporary object and its copy (two extra round trips for a proof the server
checksum now gives); a length-only comparison on an existing key; trusting a 412 without a stat;
dropping verification of the stored object (the stat after the PUT is required).

Unchanged: SHA-256 of the actual object bytes as the content checksum, immutable
content-addressed keys, raw verification, database fencing and the single atomic commit, the
Parquet schema (`core-parquet-v1`) and writer options.

Verified on the integrated head (2026-10-08): the pinned MinIO release
(`RELEASE.2025-10-15T17-29-55Z`) accepts `If-None-Match: *` together with the SHA-256 checksum,
rejects a wrong checksum and stores nothing, and returns the checksum on HEAD
(`tests/stage1/test_minio.py` integration case running `tests/stage1/minio_probe.py`, passed);
the 1 GiB cgroup writer proof in `tests/stage1/test_resources.py` passed on the v4 writer
(`reports/stage1-parquet-resource.json`). The chunk benchmark records `write_snapshot` 3.1 s and
`publish_verified` 0.011 s on 87x699 (`reports/stage1-v4-bench-chunk.json`).

## ADR-0051 - Per-chunk publication parts, slim staging with binary level COPY, jsonb-free commit, compaction, in-memory candidates

Decision under ADR-0039 per the owner decisions of 2026-10-08 recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/F.md` (migration 0013, repository, spool, processor publish path, selector,
compaction) and its downstream effects on `docs/v4-packages/D.md` (`compact` command). Amends
contract §7 (the definition of a generation, publication steps 6-8), §7.2 (selection),
§9 (certified spool reuse), §11 (stored-snapshot reconciliation) and ADR-0044 (the commit-time
level content check). Supersedes ADR-0034's certified spool reuse for candidate bytes produced
in the same process.

Measured inputs:

- Review §3.2 and §3.4: staging repeated every level, 143.8 MB of NDJSON for 74.3 MB of canonical
  content (87 x 699); COPY 4.0 s; commit 16.5 s into an empty partition but 34.0 s into one
  already holding 15,378 rows (unexplained); a successor chunk in a populated slot paid a 19.9 s
  retained read-back (`reports/stage1-perf-db-probe.json`,
  `reports/stage1-perf-db-probe-87-alone.json`).
- Offline, no database (`reports/stage1-v3-bench-chunk-baseline.json` against
  `reports/stage1-v4-bench-chunk.json`): staged bytes 143,764,696 to 83,222,450;
  `spool.prepare` 4.852 s to 0.006 s; `spool.membership` 1.863 s to 0.0 s; the 2.359 s
  `spool.profiles` re-read no longer exists; `spool.write_candidates` 4.449 s replaced by
  `spool.candidates` 0.378 s plus `spool.level_tables` 0.263 s.
- Package F's scratch script (not under `reports/`): client side of the binary COPY 2.7-4.1 CPU-s
  and a 487 MiB peak RSS for 87 x 699.
- Not measured: the commit on the new path. It needs PostgreSQL, and `test_publication_scale.py`
  (10,000-level profile and an 87 x 699 chunk under 10 s) has not run. The expectation, from the
  work removed, is a commit under 10 s that does not grow with the retained slot size.

Decisions:

1. Parts. A chunk publishes one Parquet part per changed slot containing only its accepted
   profiles; the retained population is not read back. `dataset_partition` gains `kind`
   (`part` or `snapshot`) and `part_ordinal`; the unique `one_active_generation` index becomes
   `one_active_snapshot` (at most one active snapshot per slot) plus a non-unique active index.
   The catalogue state of a slot is its membership manifest together with the active parts and
   the at most one snapshot that hold those rows; this replaces §7's "a generation contains the
   full currently accepted stored profile/level set". Generations are allocated as
   `max(generation) + 1` per slot for parts and snapshots and no longer equal `slot_version`,
   because compaction adds a generation without a membership change. Every commit or compaction
   re-stamps all active objects of the slot with the new `slot_version`, so
   `committed_active_partitions` keeps its predicate and a stale object still never selects.
2. Incremental manifest. `commit_publication` edits `logical_partition_slot.membership_manifest`
   (drops replaced and moved-out ids, adds the chunk's entries, orders by profile id) and checks
   it against the stored population with the index-backed `app.audit_slot_manifest`. For every
   changed slot the generation must declare exactly this chunk's accepted profiles in the slot
   (`stored_snapshot_membership_mismatch` otherwise). Nothing is superseded except a slot whose
   manifest becomes empty (§7 outcome 3). Slots of generations and receipts are locked in one
   ordered statement, which removes a deadlock class between concurrent chunk commits.
3. Slim staging. `ingestion_staging.candidate` holds identity fields, `content_hash`,
   `revision`, `raw_manifest_id`, the canonical text and `level_count`, with no `levels` array.
   Levels go through binary `COPY` into the UNLOGGED `app.measurement_staging` (key run, chunk,
   fence, occurrence, level; 36 value columns; one statement-level trigger asserts the fenced
   authority per COPY instead of per row). The commit inserts levels set-based from that table
   with no jsonb expansion, then deletes them; `core_measurement.canonical_level` and
   `app.canonical_level_values` are dropped. UNLOGGED is deliberate: the rows are transient and
   every staging call restages both candidates and levels.
4. Rule change to ADR-0044. Stored floats are the staged Python values, not values re-derived from
   the canonical text in SQL. ADR-0044's positive-zero rule holds because `scientific_number`
   normalizes zero in Python. The per-level content comparison (`measurement_content_mismatch`)
   leaves the commit and becomes the sampled audit `app.audit_levels(chunk, sample)`; the
   commit keeps `level_set_mismatch` and `invalid_level_index`. As a result nothing in the commit
   path compares each stored float with its canonical text. `Repository.audit_levels` exists; no
   worker calls it, and its sample size and cadence are not decided here.
5. Selection and readers. `select_active_partitions` returns every active part and snapshot of a
   slot plus `Selection.manifests[slot]`; one unreadable object is a gap for the whole slot. A
   reader keeps a row of a part or snapshot only if its `(profile_id, profile_hash)` is in the
   manifest; the same pair in two objects (a profile reverted to older content) has identical
   rows, keep one. Rows of replaced or moved profiles stay in older parts until compaction. This
   binds Stage 2.
6. Compaction. `app.compact_slot`, `Repository.compact` and `floatchat compact` merge a slot's
   active objects into one snapshot in one transaction that proves the base version, manifest
   equality and that the active objects are exactly the superseded set. The snapshot row inherits
   `intent_id`, `run_id` and `chunk_id` from the newest part it replaces (the columns stay NOT
   NULL). Compaction reads all active objects of the slot (guard: 256 MiB), rebuilds profiles
   from Parquet rows with hash-checked `restore_profile`, charges no canonical budget (it has no
   run authority) and is CPU-heavy in Python. Nothing schedules it yet.
7. In-memory candidates. `ProfileSpool` keeps the module and class names but holds the chunk's
   candidates in memory: no SQLite, no re-encoding, no retained read-back. Canonical bytes
   produced by `map_profile` in the process are reused without a round-trip certification, which
   ADR-0034's certified reuse (§9) had required; stored profiles are compared by hash
   (`science_hashes`) and charge no budget. The certification cache of §9 no longer exists
   because no retained population is read. The Parquet part is verified by hash (ADR-0050).
8. Receipts. Python predicts the post-commit population (stored now, minus departures, plus
   arrivals) and reads stored counts only where unsure; SQL rechecks. Changed slots are protected
   by the generation base check and receipt-only slots by a new `base_version`; a mismatch
   rebuilds (`publication_base_changed`, four publication attempts) instead of quarantining as
   `coverage_disposition_mismatch`.
9. Failure classification. `SAFE_DATABASE_CATEGORIES` now contains every `RAISE EXCEPTION` name
   of migrations 0012 and 0013. Those used to surface as `database_failure` (chunk failed); none
   of them is in `FAILURES`, so `terminal()` now classifies them as quarantined. Whether
   `landing_retry_exhausted` or others should fail instead is open.
10. Reports. `reconciliation_snapshot` reads members from the manifest (parts overlap after a
    replacement); the persisted report adds `active_partitions`, `active_part_count` and
    `active_snapshot_count`.

Rejected: weekly slices (ADR-0041); nullable ids with a `LEFT JOIN` view for snapshots (kept the
columns NOT NULL and inherit); keeping jsonb levels in staging; reading back the retained
population at publish time.

Unchanged: per-profile hashes and canonical bytes, `core-parquet-v1`, identity resolution,
revision comparison, outcomes, coverage receipts, fences and leases, the one fenced transaction
per chunk.

Verified on the integrated head (2026-10-08): migration 0013 applies on the foundation image;
the v4 cases of `test_database.py`, `test_publication_scale.py` (87x699 chunk committed under
10 s), `repository_probe.py`, `processor_probe.py` and `capacity_probe.py` (five parts compacted
into one 40-profile snapshot, `reports/stage1-publication-capacity.json`) pass in the stage1
integration suite. Measured in a disposable database (`reports/stage1-v4-perf-db-probe.json`):
87x699 staging COPY 3.8 s plus commit 3.2 s against 4.0 s plus 16.5-34 s before (ADR-0044 path);
pooled COPY+commit 107 µs per level against 408; the successor chunk's slot reads take
milliseconds against the 20 s retained read-back. Memory: the in-memory set holds level dictionaries of about 2 KB per level, so at
the contractual cap (256 MiB canonical, 2,000,000 levels) a chunk would exceed the 1 GiB worker
bound and end in `MemoryError` or a cgroup kill rather than a clean category; the caps are
unchanged here and lowering them or staging Arrow instead of dictionaries needs a decision.
Existing slots must have manifests equal to their stored population or the commit fails with
`stored_snapshot_membership_mismatch`. `compact` enumerates slots with its own SQL against the
0013 view, which is unverified; `Repository.compactable_slots` is the alternative list.

## ADR-0052 - GDAC NetCDF bulk source with the gdac-core-v1 exact-text rule

Decision under ADR-0039 per the owner decisions of 2026-10-08 (build the GDAC bulk source now;
downloads from data-argo.ifremer.fr allowed) recorded in `docs/stage1-v4-execution-design.md`;
contract version stage1-v4. Summarizes `docs/v4-packages/G.md`; mapper hooks are in
`docs/v4-packages/B.md`. Amends contract §9 (the approved host and routes), §11 (fixtures and
evidence) and §3.2 (completeness and the three roles). Adds a second source population; the
Argovis source is unchanged.

Observed inputs (package G, 2026-10-08, scratch scripts, not recorded under `reports/`):

- The listing `https://data-argo.ifremer.fr/geo/indian_ocean/2025/01/` has one file per UTC day,
  `YYYYMMDD_prof.nc`, 31 files for January and 28 for February 2025, 2.8-8.0 MB each. The global
  index `ar_index_global_prof.txt.gz` is 58,734,918 bytes and 3,418,915 lines. The 2025 daily files
  were last modified between 2026-09-08 and 2026-10-07: they are regenerated upstream, not
  immutable.
- Download rates from this WSL host were 5-47 KB/s (the index took about 26 minutes, a daily file
  2-3 minutes); the production host is unmeasured, and a one-year backfill (about 365 files,
  1.8 GB) would take many hours at those rates.
- A basin file is larger than the project region: 79 of 97 (2025-01-15) and 61 of 77 (2025-02-14)
  profiles lie inside `[-60,30] x [20,120]`. For both fixture days the index rows equal the
  NetCDF profiles per tile for all 100 tiles.
- Offline cost: converting one 97-profile file 3.0 s; mapping its 97 profiles 10.6 s (about 0.11 s
  and 0.7-1.5 MB of canonical bytes per profile); scanning a synthetic 3.4M-line index for one
  month 6.4 s.
- The review (§4.9) could not verify the file layout, the download policy or the mirror choice
  offline. The layout is now observed for this one host. No report records a download-policy
  check beyond the attribution string, and no other mirror was examined.

Decisions:

1. Population. GDAC profiles are a separate source population: `source = 'gdac'`, mapping
   `gdac-core-v1`, hash `scientific-json-v2`, specification `gdac-netcdf`, logical keys
   `gdac/core/<yyyy-mm>/<west>:<south>/indian-ocean-v1/gdac-core-v1/scientific-json-v2`.
   Because `source` is a canonical field, a GDAC profile never hashes equal to the Argovis
   profile of the same observation. No cross-source identity rule is defined; Stage 2 must treat
   them as two populations or define one. Argovis stays the daily-increment source.
2. Acquisition. Month x tile chunks as before. The daily basin files are downloaded once into a
   cache shared by all tiles (an `flock` serializes each file) together with the global index
   used for completeness. The NetCDF files are preserved as `raw/sha256/<sha>.nc` through
   `publish_verified(raw="nc")`, once per file for all tiles (a `stat` first skips an existing
   object); they have no `raw_manifest` row and are referenced from the landing manifest
   (`derived_from`). Each chunk lands an Argovis-shaped wire array so the unchanged landing and
   inventory code runs.
3. Transport. A second pinned host, `data-argo.ifremer.fr`, HTTPS port 443, with its own path
   allow-list (the index, a month directory listing, a daily basin file), the same address
   validation and pinned connection with SNI check, no proxy, no redirect, no cookie, identity
   encoding, a streaming size limit (128 MiB default, `gdac_file_size_limit`) and an attempt bound
   of 3,600 s with a 60 s idle read. The Argovis credential is never sent. `gdac.fetch_file`
   reimplements the pinning because the `transport.py` versions are hard-wired to Argovis and
   capped at 16 MiB.
4. The exact-text rule. The "exact" text of a stored value is
   `numpy.format_float_positional(value, unique=True, trim="-")` of the stored numpy scalar: the
   shortest decimal that round-trips float32 (pressure, temperature, salinity and their errors)
   or float64 (latitude, longitude). `Decimal(text)` feeds `scientific_number`, `-0` becomes `0`,
   and the `rounded` flag is expected on most float32 measurements (shown on 3,000 random
   float32 values). The declared `_FillValue` (99999.0) becomes the token `99999` and `argo_fill`;
   stored NaN and Inf become the quoted nonfinite tokens of §5.1.
5. Remaining gdac-core-v1 rules. The canonical document has exactly the `argovis-core-v1` profile
   and level keys. Trailing levels where all six core arrays are fill are dropped; a profile with
   no non-fill level is excluded with a count (Argovis would quarantine a zero-level profile).
   The profile `DATA_MODE` (R, A, D) is the mode of all three variables: R maps the original
   columns, A and D the adjusted columns, with `*_ADJUSTED_ERROR` to `*_error` (non-null for A and
   D, a divergence from Argovis, which carries no errors); a blank or unknown mode with the
   variable present is `unknown_data_mode`. Source unit spellings map through the same table as
   Argovis. A blank QC becomes `""`. Time is `JULD` days since 1950-01-01 UTC rounded to
   microseconds. Identity is `gdac:<platform>_<cycle><direction>`. Revision is
   `Revision("gdac-date-update-v1", (("file", DATE_UPDATE),))`. Profiles with fill position or
   time are excluded and counted. Ownership uses `Tile.owns` and `Interval.contains` on the exact
   text, with no epsilon polygon, so GDAC chunks produce no `overlap_duplicate`. Every index row
   of the Indian Ocean owned by the tile and interval must exist among the chunk's profiles
   (`incomplete_inventory` otherwise); profiles absent from the index are tolerated.
   `profile_count_limit` and `decompressed_size_limit` split chunks as for Argovis.
6. Migration 0014 relaxes the `source` CHECKs (`argo_float`, `argo_profile`, `ingestion_scope`),
   makes the `(source, mapping_version)` pair `(argovis, argovis-core-v1)` or
   `(gdac, gdac-core-v1)`, lets `raw_manifest.object_key` end in `.json` or `.nc`, adds attempt
   origin `gdac` while keeping `cache` (ADR-0049) and input kind `gdac`, lets
   `app.reserve_recorded_attempt` accept `gdac`, and adds `app.gdac_owner_slot`.
7. Fixtures and attribution (§11). `tests/fixtures/gdac/` (10,590,378 bytes, under the 12 MB
   limit): `20250115_prof.nc` (5,632,396 bytes), `20250214_prof.nc` (4,402,816 bytes), an index
   excerpt `ar_index_indian_2025q1.txt` (555,166 bytes, 5,970 lines: 8 comment lines, the header
   and 5,961 rows of lat -60..30, lon 20..120, 2025-01-01..2025-03-31) and `manifest.json` with
   URL, SHA-256, size and retrieval time, created once by `scripts/gdac_fixtures.py`.
   2025-02-14 replaces the planned 2025-02-15, which is 8.0 MB and would have exceeded the budget.
   Re-running the script fetches the then-current upstream files, so the committed bytes are the
   baseline. Attribution: "Argo (2000). Argo float data and metadata from Global Data Assembly
   Centre (Argo GDAC). SEANOE. https://doi.org/10.17882/42182".

Rejected: reusing the Argovis mapper on GDAC data (the wire schemas differ; `map_profile` reads
revisions as `argovis-source-vector-v1` and requires `basin` and `date_updated_argovis`); the
per-profile index `date_update` as revision (the brief asked for the file stamp; not used);
using GDAC as a landing accelerator for the Argovis mapping (review §4.9 option b, not possible).

Unchanged: the Argovis source, `argovis-core-v1`, the canonical encoder and hash, the geometry
and ownership rules, the pinned Argovis host and its credential rules.

Not wired end to end (a grep of `processor.py`, `source.py` and `workers/` finds no GDAC
reference at this commit): `Processor.map` still calls the Argovis `map_profile`; routing for
`gdac` inputs to `gdac_map_profile`, the `ingest --source gdac` command and admission with
`prepare_cache`, the admission functions of migrations 0005 and 0010 (they hard-code the Argovis
scope row), and the publication SQL (it looks up `source = 'argovis'`, checks
`mapping_version = 'argovis-core-v1'` and calls the Argovis `app.owner_slot`) all still need
changes, as do the Python key builders in `objects`, `catalogue`, `coverage` and `reporting`,
which were not checked. The classification of GDAC rejection categories (for example
`gdac_index_changed`, `invalid_netcdf`) between failed and quarantined is undecided. Migration
0014 and the GDAC source have not run against PostgreSQL or a live host. Known risks: `DATE_UPDATE`
is a file-level stamp, so an upstream regeneration advances the revision of every profile in the
file; `DATA_MODE` is per profile, so a profile with mixed per-parameter modes would be
mis-selected (the merged files carry no `PARAMETER_DATA_MODE`); several profiles of one cycle in
one file would quarantine the chunk as `duplicate_inventory_id` (not seen in the two fixture
days); one `fetch_file` can block up to 3,600 s without a heartbeat (the source heartbeats per
file and in retry waits, so prefetch with `prepare_cache` before admitting a run); each acquire
thread may hold about three times 128 MiB of wire pieces; netCDF4/HDF5 parses downloaded files in
process, so a malformed file could crash it.

## ADR-0053 - Fast decode, encode and mapper; byte identity proven by tests/stage1/test_byte_identity.py

Decision under ADR-0039 per the owner decisions of 2026-10-08 recorded in
`docs/stage1-v4-execution-design.md`; contract version stage1-v4. Summarizes
`docs/v4-packages/A.md` (exact decode, sanitization, encoder) and `docs/v4-packages/B.md`
(mapper, `level_table`). Amends the S1-RESOURCE-2 implementation note in contract §7 and the §9
numeric/canonical output row (how the preflight is computed). Supersedes the "conservative
output preflight" and "allocates no unbounded encoded profile" wording of ADR-0037 for the
encoder. No scientific rule, limit or rejection category changes.

Measured inputs:

- `reports/stage1-v4-bench-A.json` (30 x 699 = 20,970 levels, 126,000 number tokens, interleaved
  best of 15, output identical to the vendored pre-v4 code asserted): `CanonicalBudget.encode`
  0.797 s to 0.251 s (3.17x); `exact_number` 0.267 to 0.053 (5.03x); `decimal_text` 0.139 to
  0.019 (7.21x); structural scan 0.066 to 0.004 (17x); `decode_json` of one document 0.011 to
  0.002 (5.29x); `documents()` 0.392 to 0.070 (5.64x); `sanitize_raw` 0.659 to 0.175 (3.77x).
- `reports/stage1-v4-bench-B.json`: the `map_profile` plus `budget.encode` stage, 87 x 699, went
  from 8.25 s (baseline given) or 8.661 s (measured at the start) to 5.368 s with the old
  encoder, 1.54x and 1.61x. Mapper-only figures of 4-5x on the tiled clone and 2.9x on data with
  every value distinct come from package B's scratch harness, not a report. Real profiles repeat
  fewer values than the clone (a recorded profile has 238 distinct of 501 salinity values and 472
  of 501 temperatures), so the memo helps less on real data.
- Whole chunk (`reports/stage1-v3-bench-chunk-baseline.json` to
  `reports/stage1-v4-bench-chunk.json`, 87 x 699, synthetic): `sanitize_raw` 2.329 s to 0.418 s;
  `validate_raw` 2.05 s to 0.215 s; one `documents()` decode 2.301 s to 0.507 s; map plus encode
  9.963 s to 4.617 s.

Decisions:

1. Rule. The execution model may change; the scientific rules may not. `scientific-json-v2`
   canonical bytes and hashes, `argovis-core-v1` semantics, `raw-sanitization-v1` output, the
   exact-decimal rules (§5, §5.1, §6) and every rejection category and its precedence are
   unchanged. The proof is `tests/stage1/test_byte_identity.py` against
   `tests/fixtures/golden/stage1_v3_goldens.json`, generated at `90e1e67` by
   `scripts/stage1_goldens.py` and never regenerated for these changes. It runs six tests: four
   recorded Argovis bundles (5 profiles, 30 labelled mutations) compare the input and sanitized
   SHA-256, canonical SHA-256 and length, content hash, level hash, identity, revision, owner
   slot and rejection category; two synthetic 3 x 699 clones (core6 and bgc24) additionally
   compare the Parquet snapshot's `membership_sha256`, `schema_sha256`, rows and profiles. It
   must pass after every package. Golden regeneration needs an ADR that changes a scientific
   rule.
2. Beyond the goldens, each rewrite is proven by a differential test against a verbatim copy of
   the pre-v4 code kept in the test file: package A for `exact_number` (6,000 tokens),
   `decimal_text` (20,000 random decimals), `decode_json` (8,000 generated and damaged documents,
   60,000 structural fuzz cases), the document splitter, `sanitize_raw` (every recorded fixture
   with and without a credential, 3,000 generated documents) and the encoder (every limit from 1
   to total plus 2, three scopes, seven contents); package B for `map_profile` against a verbatim
   stage1-v3 copy (42 tests, 1,500 seeded documents under both Argovis contracts).
3. Numeric preflight (§5.1: preflight length before expansion). A token without an exponent skips
   the normalized-length check because its normalized text cannot exceed the token (at most 128
   bytes), so the 512-byte check cannot fail. A token with an exponent has the normalized length
   computed arithmetically from `Decimal.as_tuple()`, without building the text. Grammar, bounds,
   precedence and the `canonical_output_limit` evidence are unchanged.
4. Structural prepass. A C-speed filter clears an input only when it proves the old byte loop
   would not raise; anything else goes to the old loop verbatim, which raises the old category in
   the old order. Three implementation thresholds choose the path and never an outcome: 262,144
   quotes and brackets, 8 MiB, and a peeling budget of four scans. `decode_json` and `documents`
   now require `bytes` (a `str` raises `TypeError`; the old loop silently did nothing).
5. Encoder. Each level is C-encoded in full and yielded if its length fits the remaining
   allowance; otherwise the level is streamed with `iterencode` so the first exceeding piece
   raises with the old scope, `used_bytes` and `requested_bytes`. `TypeError`, `ValueError` and
   `RecursionError` from the C call fall back to the stream. Charged bytes and precedence are
   identical at every boundary. This replaces ADR-0037's preflight before encoding: one level's
   C-encoded text (at most about six times its in-memory size) is now allocated even when it is
   then rejected, bounded by the object the caller already built; no further guard was added.
   `_small_json_bound` and the test that forbade C encoding before the limit are deleted.
6. Sanitization. Numbers are captured as `RawNumber` tokens, a `str` subclass; the sanitizer's
   decoder is `raw.raw_number`, and a numeric credential cannot match number digits because
   `clean` and `encode` test the type before `str`. Output bytes, the 128 MiB cap and
   `credential_in_source_content` precedence are unchanged.
7. Mapper. Per profile the mapper builds, once, the first level-independent rejection (in the
   original order), the columns and a level template that already has the final key order. Per
   profile memos for `scientific_number` and `qc` are keyed so the result is fully determined
   (QC by exact token text, because `qc(Decimal("1.5"))` and `qc(Decimal("1.50"))` differ);
   `True`, `1`, floats, `Decimal` subclasses and signaling NaN bypass the memo; rejections are
   never memoized; checks run in the original order. Canonical number dictionaries are shared
   between levels and only the encoder reads them. `budget.encode` still runs before
   `source_revision`, so `canonical_output_limit` keeps precedence. The mapper's garbage-collector
   pause was removed at integration: collector policy belongs to the worker process.
8. `argovis.level_table(profile)` returns the Parquet level columns (38 columns, same Arrow types)
   with `canonical_level` cut from `profile.canonical_bytes` at checked level boundaries, with a
   `json.loads`/`json.dumps` fallback identical to `parquet.rows()`. `gdac-core-v1` is accepted
   as a source contract by the column helpers; its `policy_versions` entry carries no
   `specification_sha256` because no GDAC specification digest is pinned (ADR-0052).

Rejected: vectorized mapping with Polars or Arrow (review candidate 15; Polars is not in the lock
file and the exact-decimal path is per token); dropping the structural prepass or the numeric
preflight; weakening any limit to gain speed.

Unchanged: all numeric, string, depth, array, profile, chunk and run bounds of §9, canonical field
set and order, hash version, rejection categories.

Decode once: the integrator added `Processor.documents_of(role)` (commit 65eb3fc) so each landed
payload is decoded once per role and reused by inventory accounting, the inventory triple,
metadata resolution and mapping; payloads above 8 MiB stream as before (the census maximum
chunk was 2.66 MB; decoded exact-decimal objects are several times the raw size and share the
process with the candidate set), and the cache is cleared when `process()` returns. The chunk benchmark
(`reports/stage1-v4-bench-chunk.json`) records 4.75 s single-counted for 87x699 against 58.2 s
for stage1-v3 (`reports/stage1-v3-bench-chunk-baseline.json`), and the run model
(`reports/stage1-v4-run-model.json`) projects 126.2 µs per level of worker CPU against 1,425.4,
worker CPU 0.10 h and captured replay 0.19 h for Jan-Mar 2025; the review's 650 µs target was a
no-ADR estimate, not a measurement. Package A reported that `test_canonical_encoding_certificate.py` needed an edit for
the new encoder; the tree no longer contains `_small_json_bound` or the test it named.

## ADR-0054 - stage1-v4 live-only defects found by the first live sessions

Status: accepted (owner authority, ADR-0039); 2026-10-09.

The first three live Jan-Mar 2025 sessions on the merged stage1-v4 code (`6c88a0a`) each exposed
one defect that the offline fakes could not show. Each session was stopped through the wrapper's
interrupt path, with science, objects and the database preserved and persisted budgets unchanged.

1. `689a21527ccf01de` (run `402c6eda`): every attempt ended as `upstream_transport_failure`.
   Argovis answers `Connection: close`, so `http.client` closes the socket once the body is read;
   the per-read idle-timeout refresh then called `settimeout` on the closed socket (EBADF).
   Fixed in `222f437`: the refresh skips a closed socket; the attempt bound is still checked.
   The fake wire now sends `Connection: close`.
2. `610e1592a7c98390`: every landed chunk failed as `live_ingestion_disabled` in the process pool.
   `RequestOwner.obtain` checked the live flag before the persisted-landing lookup, and the
   process pool runs with live ingestion disabled (ADR-0047). Fixed in `7bec2c0`: an owner built
   with `require_existing`, which cannot reach upstream, does not need the flag; an acquiring
   owner still stops when it is disabled.
3. `716d72e226e49f75`: 58 leaves (1,144 profiles, 884,135 levels) published in about 9 minutes
   with no quarantine, then three acquire chunks failed as `database_failure`.
   `commit_publication` holds the `ingestion_run` row from its first `assert_authority` to
   COMMIT; one 40-profile commit held it for at least 10 s while acquire threads waited on the
   same row for per-read byte accounting, past the fixed 5 s `lock_timeout`. Fixed in
   `d0e6565`: `lock_timeout` equals the transaction's existing statement and transaction bound
   (at most 60 s). PostgreSQL deadlock detection is independent of it. The restricted repository
   probe now waits behind a 7 s lock.

4. `a34ff8267e859b85`: 268 of 270 leaves complete in about 54 minutes (10:11 to 11:05 UTC),
   5,788 profiles and 4,124,043 levels committed, 27 source exclusions, 64 empty-delivery
   receipts per role, no quarantine; 1,529 verified HTTP payloads plus 1,464 metadata cache hits
   (stage1-v3 run `7153be63`: 3,009 HTTP attempts in 3.79 h). Two acquire chunks in
   transport-retry back-off failed together as `worker_execution_failed` at 10:53:12 UTC, the
   moment a publication commit released the run row: `RequestOwner.wait` heartbeated past the
   end of the retry delay and passed a negative interval to `time.sleep` (ValueError). Fixed in
   `b426f62`: the remaining sleep is clamped at zero. The run's 26 transport failures were
   spread through the run (connect-phase `io_deadline` at 10 s and idle reads near 116 s with no
   bytes received), all retried; these upstream slow episodes under four concurrent requests are
   not 429s, so the governor (ADR-0048) does not react to them.
5. The same session left no ADR-0042 memory evidence: both cgroup samplers exited at 10:23 UTC
   when one `docker ps` exceeded its 20 s timeout under load. Fixed in `499b821`: a failed listing
   keeps sampling the known containers and is counted as `missed_container_listings`.

Not changed: `assert_authority` locking, the per-read accounting cadence and the position of the
run-row update in `commit_publication`. Shortening the run-row hold is a follow-up if acquire
attempts start to reach `io_deadline` while waiting.

## ADR-0055 - Review of ADR-0047 through ADR-0053, deferred items and the contract label

Status: accepted (owner authority, ADR-0039; advisor review recorded 2026-10-09).

The advisor reviewed ADR-0047 through ADR-0053 against the live sessions of 2026-10-09 and agreed
to each, with the dispositions below. Evidence is session `302412131a7c99fb` (live run
`edebccd8`, replay run `8562e75d`) on `499b821`, see `docs/stage1-gate.md`.

1. ADR-0047: verified under Docker by sessions `716d72e2`, `a34ff826` and `30241213`. Open: no
   watchdog observes the process container during `execute`, so a dead pool parent stalls chunks
   until the run deadline.
2. ADR-0048: the first live measurement of four requests in flight. Runs `a34ff826` and
   `30241213` saw no HTTP 429; upstream slow episodes appeared as connect-phase `io_deadline`
   and idle reads near 116 s, which the governor does not react to, and all were retried.
3. ADR-0049: the live run of `30241213` resolved 2,194 metadata requests, 1,470 (67 %) from the
   cache and 724 over HTTP. Open: a cache hit manifest carries a synthesized `sanitization`, not
   a copy of the original evidence.
4. ADR-0050 and ADR-0051, audit: deferred. No cadence is wired. The property the audit guards
   (each stored float equals its canonical text) holds for this code because the float columns
   and canonical text are two outputs of one `map_profile`/`level_table` call, proven by byte
   identity (ADR-0053) and Arrow-equality verification (ADR-0050 decision 2); the audit guards
   future mapper changes. It was executed once on the acceptance population: `app.audit_levels`
   over all 206 committed chunks of `30241213` checked 5,814 profiles and 4,144,346 levels with
   no mismatch, at about 0.6 ms per level, too slow to run on every commit as written.
5. ADR-0048, governor counters: deferred; with no 429 observed there was nothing to count.
6. ADR-0051, memory at the chunk cap: deferred and recorded as a known limit. The largest
   Jan-Mar chunk held 87 profiles and 52,238 levels against the 2,000,000-level cap; the
   process container peaked at 673 MiB anonymous for two workers (limit 2 GiB). At the cap a
   chunk would exceed the 1 GiB worker bound. Decision 9 of ADR-0051 (new SQL categories
   quarantine rather than fail) stays open.
7. ADR-0052: the GDAC source is a capability outside this acceptance and stays uncertified; the
   source-aware SQL of migrations 0014 and 0015 (`admit_run`, `ensure_slot`,
   `commit_publication`) is verified by the Argovis acceptance run. ADR-0052's "Not wired end to
   end" paragraph predates package G2.
8. ADR-0053: shown on live data. All 5,792 profiles of the stage1-v3 live run `7153be63` have
   identical content hashes in `30241213`; the 22 further profiles are the leaf that `7153be63`
   quarantined for `missing_basin` (ADR-0046).
9. Contract label. Reports, `planning.RUN_POLICY` and the acceptance validator keep
   `contract = "stage1-v3"`: the scientific contract is unchanged and the canonical bytes are
   identical. `stage1-v4` names the execution amendment in `docs/stage1-contract.md` §1.
