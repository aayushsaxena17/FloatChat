# Stage progress

## Stage 2 - plan reviewed and authorized (ADR-0056..0060), 2026-10-09

`codex/stage-1` merged into `main` by PR #5 (squash `91f7dd5`, tree equal to `a4d6a01`); the remote
Stage 1 branch is deleted. Stage 2 works on `codex/stage-2` from `main`. The draft plan was reviewed
against the merged code and rewritten: [docs/stage2-plan.md](docs/stage2-plan.md). The advisor
reviewed the findings before the rewrite and agreed with the rewritten plan and ADR-0056..0060 on
2026-10-09 (ADR-0039 convention); implementation may start.

- [x] Plan corrections recorded in the plan's section 0: migration `0016` (not 0010), parts plus
  membership manifests, the `argovis`-only population, `qc-policy-v1`, the environment reference
  time, the development dataset copy, the read-only role and views, the geography index,
  `/v1/floats` scope, partial labelling without jobs, bounded in-process DuckDB, named-region
  source and definitions, unchanged dev Compose service set.
- [x] ADR-0056 (scope, branch, population, router reference time), ADR-0057 (`qc-policy-v1`, owner
  to confirm), ADR-0058 (`floatchat_query`, views, DuckDB over a verified cache), ADR-0059 (dataset
  copy from session `302412131a7c99fb`, owner to confirm), ADR-0060 (IHO Sea Areas v3 regions).
- [x] W2 migration `0016_query_access`: `floatchat_query` login, `app.query_*` views,
  `app.named_region` (7 regions from IHO Sea Areas v3 through `scripts/build_named_regions.py`,
  0.05 degree simplification, parts and holes under 50 km² removed, 337 KB fixture), indexes
  `profile_float_time` and `profile_position_geog`.
- [x] W3 `floatchat_core.query`: plan model with registered rejections, `qc-policy-v1`, geography and
  tiles, SQLAlchemy Core compiler, catalogue coverage on the query login, SHA-256-verified part
  cache, bounded DuckDB compiler with the manifest semi-join, router, sanitiser, chart contract,
  provenance. `docs/stage2-query-engine.md` shows the compiled statements.
- [x] W4 API routes with correlation IDs, closed error registry, request bound; W1 bootstrap, dev
  configuration (additive keys), Compose cache volume, `scripts/stage2_dataset.py` (streamed binary
  COPY per month, verified object mirror).
- [x] Integration suite `tests/stage2/test_integration.py` (11 cases on a disposable PostGIS server:
  migration, read-only login, regions, coverage labelling without job creation, pagination,
  geodesic nearest with the geography index, PostgreSQL and DuckDB agreement, manifest exclusion,
  float and profile reads, charts and provenance) passes locally.
- [ ] W5 TypeScript client, OpenAPI artefact and CI wiring; W6 unit suites; W7 latency report on the
  imported dataset; W8 gate report with measured numbers, CI on the pushed head, advisor agreement.
- [ ] Needs from Aayush: confirm ADR-0057, ADR-0059 and the region definitions in ADR-0060.

## Stage 1 - live and captured-replay acceptance passed on stage1-v4 (ADR-0054, ADR-0055), 2026-10-09

`codex/stage-1-perf` merged into `codex/stage-1` (PR #4, `6c88a0a`). Gate report:
[docs/stage1-gate.md](docs/stage1-gate.md).

- [x] Session `302412131a7c99fb` on `499b821`: live run 270/270 complete in 23.1 min (5,814
  profiles, 4,144,346 levels, 31 source exclusions, 64 receipts per role, 0 HTTP 429), captured
  replay 270/270 with scientific and active-partition no-change in 13.5 min; memory evidence
  passes (acquire 237 MiB, process 673 MiB anonymous peak, 0 OOM).
- [x] Five live-only defects found and fixed with regression tests: `222f437`, `7bec2c0`,
  `d0e6565`, `b426f62`, `499b821` (ADR-0054); CI green on each pushed head.
- [x] Advisor review of ADR-0047..0053 with dispositions for audit cadence, governor counters and
  memory at the chunk cap (ADR-0055).
- [x] v3 and v4 live runs agree byte for byte on all 5,792 shared profiles; full level audit of the
  acceptance population passed.
- [ ] Follow-ups listed under "Known limitations" in the gate report.
- [ ] Stage 2 per [docs/stage2-plan.md](docs/stage2-plan.md).

## Stage 1 - stage1-v4 execution rewrite implemented offline (ADR-0047..0053), 2026-10-08

Branch `codex/stage-1-perf` from `e1ba4f0`. Scientific rules are unchanged (ADR-0053,
`tests/stage1/test_byte_identity.py`); execution model, verification, catalogue model and sources
changed under owner decisions recorded in `docs/stage1-v4-execution-design.md` (ADR-0039 authority).
Advisor agreement for these ADRs is not recorded here.

- [x] Live acceptance session 7153be6379df84de (stage1-v3 code) finished: 269 leaves complete, 1
  quarantined, CLI exit 5, no captured replay run. The cause of the quarantine is to be read from the
  preserved database; the session's evidence files and the cause analysis live in the live checkout,
  not on this branch.
- [x] Phase A review, analysis only ([review](docs/ingestion-performance-review.md), commit
  `90e1e67`): the Jan-Mar backfill is upstream-bound (serial model 3.14-4.47 h: HTTP selection
  1.12-2.45 h, metadata 0.55 h, worker CPU 1.14 h, COPY and commit 0.33 h,
  [model](reports/stage1-perf-run-model.json)); the worker repeated the same work 4-5 times per
  chunk (1,425 µs per level); one synthetic 87 x 699 commit took 16.5 s into an empty partition and 34.0 s
  into a populated one, unexplained ([probe](reports/stage1-perf-db-probe.json)); "under 1 hour"
  was judged not reliably reachable through Argovis with one request in flight.
- [x] Owner decisions and the package brief: [execution design](docs/stage1-v4-execution-design.md);
  per-package reports in `docs/v4-packages/` (A-J); ADR numbers, clauses changed and unsourced items
  in [I.md](docs/v4-packages/I.md).
- [x] A, decode/sanitize/encode (ADR-0053): 126,000 tokens, 20,970 levels,
  [bench](reports/stage1-v4-bench-A.json): encode 0.797 s to 0.251 s, `documents()` 0.392 s to
  0.070 s, `sanitize_raw` 0.659 s to 0.175 s, output identical to the pre-v4 code.
- [x] B, fast mapper (ADR-0053), [bench](reports/stage1-v4-bench-B.json): map plus encode stage
  8.661 s to 5.368 s with the old encoder (1.61x); 9.963 s to 4.617 s in the whole-chunk benchmark
  with package A's encoder.
- [x] C, write-once Parquet, Arrow-equality verification, checksum-verified upload (ADR-0050),
  [bench](reports/stage1-v4-bench-C.json): `write_snapshot` 25.6 s to a best of three of 2.75 s (a
  loaded host gave 1.7-14.7 s), `publish_verified` 12.0 s to 0.013 s.
- [x] D, PostgreSQL work queue, acquire and process pools, `schedule` command, migration 0012
  (ADR-0047): Celery, Beat and Redis removed from the workers; 160 offline tests passed; no
  benchmark.
- [x] E, thread-safe transport, adaptive governor, float-metadata cache (ADR-0048, ADR-0049),
  [bench](reports/stage1-v4-bench-E.json) with a fake transport (12 chunks, 16 floats): HTTP attempts
  96 to 52, `validate_raw` calls 384 to 52; no real upstream measurement.
- [x] F, publication parts, slim staging, binary level COPY, compaction, migration 0013 (ADR-0051):
  staged bytes 143,764,696 to 83,222,450 and `spool.prepare` 4.852 s to 0.006 s
  ([baseline](reports/stage1-v3-bench-chunk-baseline.json), [v4](reports/stage1-v4-bench-chunk.json));
  the commit on the new path is unmeasured.
- [x] G, GDAC NetCDF source, `gdac-core-v1`, migration 0014, fixtures (ADR-0052): 105 offline tests;
  observed download rates 5-47 KB/s from this host; not wired into the processor, CLI or publication
  SQL.
- [x] H, acceptance Compose with `acquire` and `process` services, memory sampler per service (ADR-0047):
  95 offline tests; no Docker run.
- [x] J, whole-chunk benchmark (87 x 699, synthetic, CPU only): `sum_measured_wall_s` 58.225 s to
  9.57 s after packages A-F and 4.75 s after decode-once (commit 65eb3fc); RSS 683.0 to 524 MiB
  ([bench](reports/stage1-v4-bench-chunk.json), [v3 baseline](reports/stage1-v3-bench-chunk-baseline.json)).
- [x] Database on the new path ([probe](reports/stage1-v4-perf-db-probe.json)): 87 x 699 staging
  COPY 3.8 s plus commit 3.2 s (was 4.0 s plus 16.5-34 s); pooled COPY+commit 107 µs per level (was
  408); successor-chunk slot reads in milliseconds (was 20 s). The run model on v4 inputs
  ([model](reports/stage1-v4-run-model.json)) projects worker CPU 126 µs per level (0.10 h for
  Jan-Mar, was 1.14 h), database 0.09 h (was 0.33 h), captured replay 0.19 h (was 1.47 h); its HTTP
  rows are still the serial one-request measurements, so the live wall time with four slots and
  decoupled pools is not projected and must be measured.
- [x] Integration suite on the integrated head: migrations 0012-0014 apply; `tests/stage1 -m
  integration` 114 passed, 0 failed, plus the combined processor/MinIO case (passed, 61 s) and the
  1 GiB writer proof; MinIO checksum behaviour confirmed by `minio_probe`
  ([INTEGRATION-1](docs/v4-packages/INTEGRATION-1.md)). Offline: `pytest tests -m "not integration"`
  1,295 passed; the four `test_security` cases need `gitleaks`, absent on this host. `ruff check`,
  `ruff format --check` and strict `mypy` are clean repository-wide.
- [ ] Benchmarks still missing: concurrent Argovis requests (no measurement of the governor) and the
  cache's real hit ratio; both need a live run.
- [ ] Live re-run of the Jan-Mar acceptance and its replay on the new topology: not scheduled; it
  needs the owner's agreement, and the acceptance Compose topology and memory sampler have not run
  under Docker.
- [ ] Redis is still required by the Stage 0 API (`redis_url`, readiness check) and stays in the dev
  stack; only the Stage 1 workers dropped it.
- [x] GDAC wired end to end ([G2](docs/v4-packages/G2.md)): `ingest --source gdac` with
  `prepare_cache`, source-aware admission and policy versions, `GdacSource` in `process_ticket`,
  `gdac_map_profile` routing, migration 0015 (`app.run_source`, `app.profile_slot`, source-aware
  `admit_run`/`ensure_slot`/`commit_publication`); offline fixture run publishes gdac profiles;
  `test_gdac_sql.py` 6 integration cases pass. Not done: skipping the synthetic metadata landings,
  gdac replay, Parquet schema metadata still names `argovis-core-v1`.
- [ ] Not implemented: the audit cadence (`audit=True`, `app.audit_levels`), persisted governor
  counters, and a decision on memory at the contractual chunk cap.
- [x] ADR-0046 (`missing_basin` informational warning, codex/stage-1 50dbdbc) merged into this
  branch; the v4 ADRs are ADR-0047..0053.

## Stage 1 - stage1-v3 implemented (ADR-0040..0042), 2026-10-08

- [x] Original session terminalized with the reviewed command: exit 3,
  `terminalized_incomplete`, closed/partial, 120 complete/1,132 failed/8 quarantined,
  science unchanged at 819 profiles/572,347 levels/67 partitions
  ([frozen evidence](reports/stage1-original-terminalization.json)).
- [x] Live empty-selection probe: both re-requested historical 404 selections return
  404 `application/json` `[\n\n]\n` for all three roles; a control tile returns 200
  ([probe](reports/stage1-live-empty-semantics.json)).
- [x] Inventory-only census of all 1,260 weekly Jan-Mar 2025 leaves: 922 with documents,
  338 empty (all the same 404 body), zero failures, 5,845 unique owned profiles, densest
  month/tile slot 87 ([census](reports/stage1-inventory-census.json)). Depth spot-check
  outside January: 384 levels/profile; one full-month request on the densest slot:
  200, 87 profiles, 2.66 MB.
- [x] Measured canonical content 1,214 B/level; weekly slices republish month slots
  (~13 conversions/profile). ADR-0041 adopts monthly plan v2 and a 40 GiB run cap.
- [x] ADR-0040 activates S1-SOURCE-2 (empty-delivery receipt, `excluded_source_loss`);
  ADR-0042 defines the worker memory criterion. Migration 0009, transport/landing/
  processor/reporting changes, contract/PRD/build-prompt text updated.
- [x] Offline suite 424 passed; previously failing DB/processor integration tests pass,
  including 404-receipt, mixed-triple, exclusion and combined-warning scenarios.
- [x] Full stage1 suite 445 passed/1 opt-in skip; committed on `codex/stage-1` and
  pushed for actual-head CI evidence (advisor-agreed push, not a gate decision).
- [x] First CI run: secrets, web and docker passed. Three wrapper tests assumed the WSL
  path, the writer memory probe used an 896 MiB container (OOM on the hosted runner;
  locally 929 MiB RSS at the edge) and Stage 0 integration failed because a fresh dev
  database lacked `floatchat_app` before migrating. All three fixed; local
  `make integration` passes. The probe now uses the contract's 1 GiB (ADR-0042).
- [x] First stage1-v3 live run (session c9af101ab1d458b9) interrupted after 14 minutes
  as a measurement: S1-SOURCE-2 receipts completed empty chunks, ~4.3 MB canonical per
  profile, 319 MiB worker anonymous peak, but ~10.5 h projected and 20 s idle-read
  transport failures. ADR-0043: 12 h run bound and 60 s idle read (migration 0010).
- [x] Live runs 3-5 found and fixed: the quadratic per-level publication commit
  (ADR-0044, 23.5 s -> 1.3 s per 10,000 levels), a >=15 minute upstream slow episode
  outlasting the retry window (ADR-0045), and host sleep (keep-awake during runs).
- [x] Fifth live run (7153be6379df84de): 269/270 leaves complete in 3.79 h, 5,792
  profiles, 4,128,567 levels, 205 partitions, 64 empty receipts, 28 source exclusions,
  20.4 GB canonical work, 3,009 HTTP attempts, 328 MiB worker anonymous peak, no OOM.
  One chunk quarantined on `missing_basin`; ADR-0046 makes it informational.
- [ ] Re-verify, fresh preparation, live acceptance and captured replay, CI on the
  final head, gate report.

## Stage 1 - owner authorization for completion (ADR-0039), 2026-10-07

The owner authorized live Argovis access with the key in the git-ignored `.env.txt`,
operation of the preserved session and pushing/gate decisions on advisor (Fable)
agreement, and asked for Stage 1 completion followed by Stage 2. Baseline before any
change: lint, type checks and `make test` pass (410 Python passed, 45 integration
deselected; 3 web). Planned order: terminalize the preserved run with the reviewed
command; bounded live validation of empty-selection/404 behaviour; canonical-work
amplification analysis and an inventory-only regional census; source-policy and
capacity ADRs from measured evidence; fresh isolated acceptance and captured replay;
commits, push and actual-head CI; gate report; then Stage 2. The current NO-GO stands
until that evidence exists.

## Stage 1 - consolidated offline blocker review; original run remains stopped

The [single authoritative matrix](reports/stage1-blocker-review.json) and
[review package](reports/stage1-blocker-review.md) distinguish implemented components,
source/policy decisions and missing regional evidence. Current NO-GO supersedes every
historical preparation GO. The 44 failures, eight quarantines, original deadlines,
scientific state and budget remain untouched; no original service is operated.

ADR-0036/S1-SOURCE-2 proposes exact inactive wording for a qualified Argovis-delivered
population. Strict A stays active. Optional empty-delivery receipts and explicit
whole-profile source-loss exclusions each need separate review, deployment evidence
and bounded authorization. Offline proposal tests cannot close missing source science.
F01-2 remains unchanged, with authentic descending/present-core-null limitations
visible and repeated-pressure/error evidence retaining its synthetic/model scope.

ADR-0037 optimizes bounded canonical encoding and publication certification while
charging every actual conversion. The [regional-plan model](reports/stage1-regional-capacity-model.json)
measures one 10 GiB run under a 1 GiB worker cgroup with all 1,260 roots, uneven
retained growth, month-moving revisions, no-op deliveries and bounded recovery/rebuild.
Results describe its labelled synthetic envelope, never the unknown regional population.
Superseded and timed-out experiments are retained separately and are not passes.

ADR-0038 provides a separately reviewable migration-0007 terminalizer with exact
identity/deadline/manifests, closed-state retry and stop-only cleanup. Disposable
connection-loss rehearsal retains protected records and one frozen partial result.
The original procedure has not run. Its approval would close an incomplete record,
not authorize another attempt. Fresh final-tree verification and source-pinned model
evidence are linked by the consolidated generator; earlier reports below are historical.
Actual-head CI, full isolated acceptance/replay and Stage 2 remain outstanding.

The first final-tree verification failed: its shared SQL seed's ten-minute
controller lease expired after a long independent processor probe, and a Beat
teardown exceeded a five-second harness bound while the capacity model ran in
parallel. Those artifacts remain archived as failures. Each independent SQL case
now receives a fresh disposable seed lease; expiry assertions, production leases,
work deadlines and budgets remain unchanged. The final heavy verification runs
separately from the model, and only its actual results can support closure.

## Stage 1 - offline resource diagnostics and source-policy review

Following the owner/Astra NO-GO, the stopped acceptance project is not restarted
or modified. The [offline remediation review](docs/stage1-offline-remediation.md)
pins official API/translator sources and distinguishes source facts from unknown
deployment behavior. The documented implementation starts at HTTP 404 and can
drop empty-data documents before inventory projection. No body was persisted for
the 44 historical pre-inventory failures; none becomes verified empty coverage.
An offline witness using the pinned translator demonstrates discarded core or
BGC inputs despite unique returned pressures. The warning quarantines remain.

S1-DIAG-1/ADR-0034 adds bounded, sanitized number/profile/chunk/run diagnostics and
frozen reporting, with portable migration 0008 tested only on disposable databases.
Within a process, repeated spill restores verify SHA-256 and reuse an already
certified canonical representation; every actual encoding remains charged and a
new process certifies again. No run counter, cap or old deadline is reset.
A five-slice growing-slot publication probe uses labelled 501-level authentic
derivatives and real restricted PostgreSQL/MinIO. Its persisted measurements and
explicit aggregate-exhaustion model are component evidence, not proof of complete
Jan–Mar publication capacity or whole-pipeline memory.

The [terminalization procedure](docs/stage1-terminalization-review.md) is a
separate review-only proposal. A disposable synthetic-state rehearsal preserves
completed science/catalogue/deadlines and freezes one partial report on repeat
finalization, without ingestion. It does not authorize operating the original
database. Fresh verification is recorded at its own source digest; older forensic
and component evidence retains its stated scope. All three regional blockers,
unfrozen original-run evidence and actual-head CI remain outstanding. The old live
command remains withdrawn and Stage 2 remains blocked.

## Stage 1 - coverage-failure investigation; live NO-GO

Following Astra's NO-GO, fresh restricted-repository reads and checksum-verified
sanitized MinIO landings account for every failed selection and quarantine in
[the coverage review](reports/stage1-coverage-failure-review.md). All 44 HTTP 404s
are inventory_before (23 January 1–8 tiles, 21 January 8–15 tiles), attempt 1;
none establishes empty coverage. Four warned profiles carry degenerate_levels;
the pinned translator discards degenerate input before returning merged science.
Their unique returned pressures do not justify a warning waiver.

The canonical-work ledger exactly balances 10,721,657,712 bytes against the
10 GiB run limit. Only 15,760,528 bytes remain, below the 16 MiB reservation.
All 18 candidates from the four limit chunks map offline below individual/chunk
limits. The first failed in publication, the next three in validation without
canonical reservations. Splitting cannot replenish a run-wide budget; no bound,
accounting policy or quarantine treatment is changed. Scoped resource diagnostics
and bounded publication-capacity evidence remain prerequisites for another attempt.

Fresh forensic assertions, source checksums, warning witnesses, phase events and
every failed time/tile selection are persisted separately from historical tests.
Scientific and exact active-generation manifest hashes match before/after review:
819 profiles, 572,347 levels, 67 active partitions. Only existing isolated DB/MinIO
were briefly started for offline reads and stopped. No worker, supervisor, live
call, credential/private-original access, original deadline reset, cancellation,
finalization, new session or owner retry preparation occurred. The old command
stays withdrawn. Original-run terminal/frozen evidence, 404 coverage resolution,
warning safety and canonical capacity remain blockers; full acceptance and actual-head
CI are outstanding. The gate now leads with current NO-GO and clearly labels
historical component closure evidence. Stage 2 remains blocked.

## Stage 1 - owner execution interrupted; acceptance incomplete

The owner ran prepared session `6f3e7301f9789059` and interrupted the silent
wrapper after approximately 80 minutes. Read-only persisted inspection found
120 complete, 44 HTTP-404-failed and 8 quarantined leaves out of 1,260, with
819 profiles/572,347 levels/67 active generations committed. The provisional
[run report](reports/stage1-acceptance-live-interrupted.json) proves incomplete
coverage. No replay or success result is claimed. The run remains open with its
original six-hour deadline; stopping processes does not infer operator cancellation.

Stop leftover project-labelled controller/client/service containers, retain data,
and record [interruption evidence](reports/stage1-acceptance-interruption-evidence.json).
Correct the wrapper to show safe persisted progress counters, reap an interrupted
client, ignore repeated Ctrl+C during cleanup, stop one-off clients and services,
record cleanup outcome and exit 130 without a traceback. Offline tests cover these
paths and credential/output guards. No live worker is restarted, no credential or
private original is inspected, and no source/retention/resource bound is relaxed.
The prior prepared source seal remains unchanged; its retry command is withdrawn
pending review of failed/quarantined coverage and the corrected wrapper. Full
acceptance and actual-head CI remain outstanding; Stage 2 stays blocked.

## Stage 1 - isolated acceptance preparation after Astra GO

The owner supplied Astra's GO for preparation only on 2026-10-07. The isolated
preparation proof and reviewable owner command are documented in
[acceptance preparation](docs/stage1-acceptance-preparation.md) and persisted in
[preparation evidence](reports/stage1-acceptance-preparation.json). Each session
has a separate physical PostgreSQL database/server, MinIO bucket/server, Redis
server/database/prefix, ingestion queue, internal network, Compose project and
three persistent volumes, with no shared development volumes or exposed ports.
An existing empty private control bucket verifies actual scoped IAM denial.
The restricted-login database proof verifies migration 0007, the disposable
acceptance marker and zero ingestion runs/profiles/measurement levels. A broker
smoke task is acknowledged; disabled live admission is refused. All prepared
services are stopped and their disposable data retained for review.

Preparation uses only immutable cached local images, offline dependencies and
live-disabled workers. No Argovis credential or private capture original is
accessed; no upstream call, regional ingestion, scheduler, destructive retention,
cloud resource, commit/push/PR or Stage 2 work occurs. Local disposable service
credentials remain in ignored restricted files. A separately opted-in owner
command transfers the upstream credential through stdin only, enforces a sealed
source digest, and later requires complete regional live and captured replay
evidence; preparing that command does not authorize running it.

Fresh preparation checks are separate from the reviewed 372-test implementation
snapshot: guard/orchestration tests, offline unit suite, lint/format/type checks,
real isolated service initialization/proof and redacted secret scans. The earlier
fault/memory/integration evidence remains historical at its stated component
scope. Actual-head CI and full acceptance remain outstanding. F01-2's waived
authentic descending/core-null limitations remain visible. Stage 2 stays blocked.

## Stage 1 - contract accepted; implementation in progress

The owner supplied Astra's GO for stage1-v2 and explicitly authorized Stage 1
implementation. Work remains in `/home/floatchat/FloatChat-stage1`, baseline `619411a`,
branch `codex/stage-1`. The preserved Windows checkout is untouched. Docker was resumed
by the owner; integration verification uses fresh UUID-named containers without external
network access, host ports, existing database volumes or production migrations.

- [x] Owner-confirmed Astra contract GO, 86 unique acceptance requirements.
- [x] Exact decimal/JSON rules, scientific/QC mapping, time/geometry/identity/revision policies.
- [x] Additive portable PostgreSQL migrations with restricted ingestion procedures,
  fencing, atomic level replacement/catalogue activation and late-conflict quarantine.
- [x] Offline PostgreSQL constraint/publication/recovery and MinIO read-back tests.
- [x] Internal catalogue coverage selection with retained/empty/source-absence distinctions.
- [x] Bounded pinned-address HTTP adapter, durable request reservations and sanitized raw
  landing; component checks include process-loss budgets and corrupt landing rejection.
- [x] Durable controller/supervisor tick logic; worker and controller heartbeats are separate.
- [x] Private disk spool and streamed Parquet writer; full retained snapshot membership
  survives an eligible correction while the rolling cutoff advances.
- [x] Truthfully attributed official published examples and labelled synthetic derivatives.
- [x] Implement a separately opt-in, small raw fixture recorder with private originals,
  matching inventory/profile/metadata, SHA-256, sanitization and secret-scan gating.
- [x] Connect ticket-based worker execution, synchronous ingest CLI, independent supervisor
  command and a UTC Beat class with a PostgreSQL singleton lock. Celery autoretry is off;
  messages carry opaque IDs and workers require a <=1 GiB cgroup.
- [x] Connect affected-slot streaming, transactional month partitions, canonical reservations,
  persisted payload/profile/level accounting and full/eligible membership comparisons.
- [x] Execute a combined restricted-login PostgreSQL/MinIO worker proof in network-isolated
  disposable containers: publication, identical replay, retained empty refresh, shortened
  level replacement, conflict quarantine and immutable reports after later revisions.
- [x] Test the tiny capture recorder offline with synthetic responses: private originals,
  credential sanitization, checksum/provenance and scan-before-copy rejection.
- [x] Inspect only the owner's sanitized recorded bundle
  `6a8ffa52f6db4954b974c449e68c54bc`; verify eight checksummed raw responses, matching
  inventory/metadata, source revision components and 515 mapped levels from two profiles.
  Persist actual representation coverage and F01 gaps; add offline authentic-fixture tests.
- [x] Add real offline Redis/Celery prefork/supervisor fault evidence for worker/controller
  loss, recovery, acknowledgement/redelivery, cancellation, deadlines, two-worker capacity,
  manual/scheduled overlap and actual Beat singleton/lock-loss/replacement behavior.
  Disposable lease acceleration is explicit; this is component evidence, not the full gate.
- [x] Correct Beat startup lifecycle: the temporary lazy banner scheduler opens no database
  or lock; only the running scheduler acquires it. Add regression coverage and rerun proofs.
- [x] Implement spill-backed 100,000-row Parquet groups with Zstd level 3, bounded read-back
  and a 100,001-level maximum-header memory probe under a 896 MiB cgroup, no swap/OOM,
  measured RSS below 1 GiB. Persist writer options, typed pandas deep memory/index and ratio.
- [x] Freeze full reporting metrics at finalization: provenance, availability, timings,
  retry/quarantine reasons, coverage/gaps, generation IDs and scientific replacement deltas.
  Reproduce JSON/Markdown after later revisions; unknown source counts remain unknown.
- [x] Add credential-free numeric HTTP status/profile/request-role recorder diagnostics,
  bounded optional 429 Retry-After and hostile offline redaction tests. Autoretry stays off.
- [x] Audit successful owner bundle `10b19b21ac4d4d8ba69a4fc95e87de3c` with persisted
  raw/inventory/metadata and hash assertions. `13857_068` supplies 103 D-mode pressure/
  temperature levels with adjusted QC 2 and absent salinity. Expected R-mode is not observed;
  no mode is relabelled and derived nulls are not treated as supplied source value nulls.
- [x] Update complete authentic corpus coverage: two bundles, 12 responses, three profiles,
  618 captured levels at that earlier point. Persist six gaps and 86-case fixture traceability.
  Prior full-suite evidence is archived with its source/time, not claimed as rerun.
- [x] Record the owner's safe `5903649_077D` diagnostic: HTTP 404 at `inventory_before`.
  No complete fixture bundle or representation evidence resulted. Withdraw the documented
  filename candidate and its retry command; do not infer a credential failure from 404.
- [x] At the owner's request, prepare a separate one-request inventory-discovery script
  for a fixed 5-degree Indian Ocean square and seven-day window. Offline synthetic tests
  cover fixed documented parameters, 20-document and payload bounds, zero retries,
  safe failure diagnostics and scan-before-copy. The owner-run command is in the gate
  report; no agent live call occurs and discovery evidence cannot pass F01.
- [x] Inspect only sanitized discovery `e5b3f14e549d49e69ed77fde03d40d8c`;
  verify checksum/provenance and persist raw inventory-mode assertions for `6990616_100`
  (core R) and `2904014_040` (core A), both ascending. These are candidate evidence,
  not complete scientific captures; all six F01 gaps remain. Propose one bounded
  owner-run capture for `6990616_100` based on its current inventory declaration.
- [x] Audit successful sanitized capture `25f21e056e7c4db7bc1e21b0a28ea45f` and add
  persisted authentic assertions: `6990616_100` proves 43 original pressure/temperature/
  salinity levels in R-mode with QC 1. Matching inventory and metadata/checksums verify.
  Exactly the core R-mode gap closes; adjusted/error/null/repeated-pressure representations
  are absent. Corpus now has three bundles, 16 responses, four profiles and 661 levels.
- [x] Record the owner's `2904014_040` capture rejection, `unknown_data_field`.
  Its previously sanitized inventory contains `chla_fluorescence` and
  `chla_fluorescence_qc`, outside the pinned 2.36.2 field contract. Add explicit inventory
  compatibility flags and a labelled synthetic shape regression. Withdraw the candidate
  and retry command; no failed private response is inspected and no scientific gap closes.
- [x] Audit owner capture `9efe8f4e713c44a1a2964407e52b9a45`: matching inventory/profile/
  metadata and supplemented provenance verify `2904014_040`, 501 A-mode adjusted core
  values/QC (pressure QC 1; temperature/salinity QC 1/4). Exact fluorescence fields remain
  non-core raw values/QC/attributes. This supersedes the earlier candidate withdrawal.
  Its 1002 null cells belong only to nitrate and nitrate QC, not core measurements.
  Four bundles now contain 20 responses, five distinct profiles and 1162 level occurrences.
- [x] Apply the owner's F01-2/ADR-0033 amendment: retain authentic R/A/D and ascending;
  waive further descending/core-null discovery while retaining both as unobserved authentic
  coverage limitations. Add labelled admitted-fixture derivatives with exact basis checksums
  and mutations. Fresh persisted test results, not waiver text, determine component closure.
- [x] Verify labelled descending and R/A present-core-null parser/canonical/Parquet tests,
  plus restricted PostgreSQL publication and A/D natural-key enforcement. Basis checksums,
  attribution, source pins and exact mutations are persisted separately from authentic data.
  Retain 21 focused unit and three focused database passes as component evidence.
- [x] Independently rerun migration/HTTP/replay regressions: five selected database tests
  passed. Production 429/503→200, terminal 401/403, four-503 exhaustion, finished timings,
  counters and frozen reporting passed. Actual split predecessor replay used 466 nodes,
  458 leaves, upstream/credential access denied, identical science and exact active IDs;
  1375 recorded-origin attempts and 4582 audit rows are explained separately.
- [x] Implement amended F01 fixture gate checks requiring remaining authentic evidence
  AND fresh passed derivative/model/storage cases. All five authentic samples are ascending,
  three D-mode, one R-mode and one A-mode, with QC 1/2/4. Under the owner's supplied Astra
  F01-2 amendment, descending and source core-value null remain authentic coverage gaps
  but require labelled derivative tests rather than further live recording.
  Repeated pressure and supplied errors have separate labelled synthetic obligations;
  their absence is not concealed as authentic coverage. Historical six/five-gap counts
  above describe the earlier contract, not the current F01 minimum.
  S1-G04 closure depends on fresh derivative/database/Parquet evidence and the remaining
  authentic minimum. No agent live call or full acceptance preparation is authorized here.
  The owner keeps
  `ARGOVIS_API_KEY` in a private WSL terminal; this agent has not inspected it.
  The completed small captures are audited in the gate report. Published examples
  and synthetic component inputs do not pass F01 or prove complete regional coverage.
- [x] Adopt narrowly pinned source supplement and F01 evidence split in contract, PRD,
  build prompts and ADR-0030–0032, preserving data=all and unknown-field rejection.
- [x] Add portable migration 0007 for real HTTP-failure dispositions and durable validated
  predecessor split-tree bindings; wire actual CLI replay to the cloned topology.
- [x] Add exact-field/legacy-rejection/alignment/unknown-field recorder regressions and
  labelled authentic-derived repeated-pressure and normalized-error Parquet tests.
- [x] Verify production HTTP retry/status/report persistence and actual temporal/spatial
  CLI replay in disposable PostgreSQL/MinIO: 466 nodes, 458 leaves, upstream denied,
  unchanged science/active generations and increased persisted attempts/audits.
- [x] Rebuild verification and gate generation from persisted check/JUnit/corpus evidence,
  distinguishing historical proofs, authentic gaps and labelled synthetic obligations.
  Current full-suite/migration/error-storage/broker/memory/scan outcomes are reported in
  the generated verification and gate documents; no successful outcome is inferred
  before its evidence exists. Ubuntu restart was owner-approved after WSL timeouts;
  saved changes survived and Docker Ubuntu integration is restored.
- [ ] Execute the full 86-case acceptance matrix and required CI on the actual PR head.
- [ ] Separately authorize and run isolated Jan-Mar 2025 live acceptance/captured-input replay.
- [ ] Astra reviews implemented evidence before Stage 2.

Current check results are generated from logs and JUnit in
[the partial verification report](reports/stage1-verification.md). Component test counts
are not completed acceptance-case counts. No full Stage 1 implementation GO, actual
agent-executed Argovis call, production migration, cloud resource, destructive retention or
publication of this branch is claimed. The owner executed the bounded capture separately.
The local changes remain uncommitted. The generated current gate determines readiness
specifically for isolated acceptance preparation from fresh evidence. Stop for owner/Astra
implementation review; full Stage 1 acceptance and Stage 2 remain outstanding. This turn
does not prepare or execute historical acceptance.

### Historical contract amendment record, before owner-confirmed GO

Authorized scope remains CONTRACT HARDENING ONLY. Work uses the sanitized WSL2 checkout
`/home/floatchat/FloatChat-stage1`, baseline `619411a`, branch `codex/stage-1`.
The preserved Windows project is untouched and was not used, merged or published.

Astra's stage1-v1 review remains NO-GO. It accepted most earlier corrections but identified
five material lifecycle/numeric blockers. This revision supersedes that unapproved candidate.

- [x] Read and map all five follow-up blockers while retaining the original review cross-check.
- [x] Separate full retained stored-snapshot reconciliation from fixed-T run eligibility.
- [x] Distinguish verified empty initial fetch, empty refresh over retained science and
  accepted last-profile ownership correction, including selector/receipt outcomes.
- [x] Define publishing -> quarantined after rollback, fenced evidence commit and
  unpublished intent abandonment with preserved references.
- [x] Define recovery ownership for every nonterminal phase; distinguish worker/controller
  loss from cancellation/deadline fencing and retain already complete chunks.
- [x] Define overlap_skip persistence/no-run semantics, manual exit 6 and unchanged watermark.
- [x] Bound exact numeric tokens/exponents/canonical bytes; define binary64 rounding,
  overflow/nonzero-underflow quarantine and exact quoted/bare nonfinite outcomes/hashes.
- [x] Expand future acceptance plan to 86 cases, including split P09a/P09b/P09c,
  T06/P11, C05-C11, D05-D06 and N01-N08.
- [x] Align PRD/build prompts and append ADR-0025 through ADR-0029.
- [ ] Astra accepts stage1-v2 after re-review.
- [ ] Separate owner instruction authorizes Stage 1 implementation.
- [ ] Implement and execute offline acceptance cases/required CI.
- [ ] Separately opt in to isolated Jan-Mar 2025 WSL2 live acceptance and captured-input
  replay using owner-provided Argovis credentials, then generate persisted evidence.
- [ ] Astra reviews implemented results before Stage 2.

Contract-review report: all five supplied blockers now have explicit outcomes, legal
transitions and linked objective test assertions in [the contract](docs/stage1-contract.md).
Retained old dates survive snapshot rebuilding; source absence cannot erase science.
Late conflicts quarantine legally; process loss can recover but closing fences prevent
late publication. Numeric handling cannot depend on parser defaults or unbounded expansion.
The original temporal/isolation/scientific/publication/security/local-service decisions
remain; Stage 2+ features, destructive retention and cloud provisioning remain deferred.

Validation for this revision: 18 documentation consistency checks passed, including
86 unique acceptance IDs, all five follow-up blockers, the original eight review
sections/twelve test areas, legal late-quarantine transition, recovery for all five
nonterminal phases, removal of the three conflicting v1 rules, authority/ADR/count
alignment, unchanged Stage 2+ scope, table widths and Markdown delimiters.
Seven local Markdown links resolved; git diff --check passed. Exactly the five
requested Markdown files remain changed; baseline/branch are unchanged.
Stage1-v1's earlier 65-case/14-check document validation was not an Astra approval and
is not reported as validation of this revision. No production code, migration, scheduler,
fixture, credential, cloud resource or live upstream data call is created here.
No runtime acceptance or CI result is claimed. Stop for Astra contract re-review.

---

## Stage 0 - corrective branch verified locally; review gate remains

Owner confirmed revocation.

- [x] Inventory and verify preservation of tracked, untracked, ignored configuration and Git data outside Git and OneDrive; durable restricted copy retained.
- [x] Sanitize prototype sources and notebooks before archiving; preserve original working inputs.
- [x] Scan current files and all advertised branch/tag history separately, with fully redacted evidence.
- [x] Test isolated rewrite and independent validation, preserve private commit mapping, and publish seven affected refs atomically with explicit leases.
- [x] Verify fresh published clone, removed January dataset paths/blobs, and unchanged unrelated refs.
- [x] Implement local uv/pnpm foundation, pinned toolchains, locked dependencies, safe configuration and persistent Compose services.
- [x] Verify deterministic 128-row, 5,617-byte attributed fixture and mocked bounded refetch behavior.
- [x] Verify WSL2 Ubuntu 24.04 Make setup, empty and repeat startup, lint/format, type checks, tests, image builds and acceptance matrix.
- [x] Merge foundation PR #1 only after all six required checks execute successfully.
- [x] Verify fresh merged-main current/history scans and complete CI-equivalent suite on Ubuntu.
- [x] Verify main CI and strict required GitHub Actions checks, two reviews, administrator enforcement and force-push/deletion prohibitions.
- [x] Record final evidence and old-clone recovery in the Stage 0 gate report.

At that Stage 0 gate, Stage 1 implementation had not started. No cloud infrastructure, production credentials, real LLM calls or required Argovis access were introduced.

The preceding checklist records the original foundation execution. Astra subsequently identified
four defects in readiness cancellation, metadata permissions, hook interpreter selection and
refetch deadlines. The corrective branch starts cleanly from sanitized main 7e642a1.
All four now have regression coverage and local full-suite verification; see
reports/stage0-review-verification.json. Required CI must pass on the actual PR head.
Do not merge until Astra reports no remaining P1 or P2 findings. No review approval is inferred
from local tests, and no published history is rewritten by this correction.

See [the complete gate report](docs/stage0-gate.md). The tested foundation commit is `608e4356b312f4422ad40996e1604fb1ef28a640`; verified merged main is `dc3d409c5fc9605c48ec0e7f8ca230d6c5e719b2`. A documentation-only follow-up records the post-merge evidence without changing tested runtime source.
