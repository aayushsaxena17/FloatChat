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
