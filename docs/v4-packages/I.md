# Package I report: ADRs, contract text, PROGRESS and documentation

Numbering note: the task asked for ADR-0046 through ADR-0052; the entries are ADR-0047 through
ADR-0053 because the live checkout (`/home/floatchat/FloatChat-stage1`, branch `codex/stage-1`) has an
uncommitted ADR-0046, "missing_basin is an informational source warning". To use the requested
numbers, shift every `ADR-00NN` for NN 47 to 53 down by one, in ascending order so no number is changed
twice (the digits appear only in `DECISIONS.md`, `docs/stage1-contract.md`, `PROGRESS.md`, `README.md`,
`FLOATCHAT_BUILD_PROMPTS.md`, `docs/stage1-acceptance-preparation.md` and this file), then delete the
last bullet of the `PROGRESS.md` entry, which explains the collision.

Documentation only. No code, test, Docker or Git command was run. I read (never wrote) the
live checkout's uncommitted `DECISIONS.md` and `PROGRESS.md` diff to look for number collisions,
although the design brief says packages should not touch that checkout; I read nothing else there and
imported none of its figures.

## ADRs written (DECISIONS.md, appended)

| ADR | Topic | Package reports |
|---|---|---|
| ADR-0047 | PostgreSQL work queue, acquire and process pools, per-environment concurrency, ADR-0042 criterion for two containers, `schedule` replacing Beat | D, H |
| ADR-0048 | Adaptive upstream concurrency (governor, advisory-lock slots) and thread-safe transport | E |
| ADR-0049 | Float-metadata cache with per-chunk `cache`-origin manifests | E, D (table and function) |
| ADR-0050 | Verification by hash: write-once Parquet, Arrow equality, checksum-verified upload, audit mode | C, E (validate once) |
| ADR-0051 | Publication parts, slim staging, binary level COPY, jsonb-free commit, compaction, in-memory candidates | F |
| ADR-0052 | GDAC NetCDF source, `gdac-core-v1` exact-text rule, migration 0014, fixtures | G, B (policy hooks) |
| ADR-0053 | Fast decode, encode and mapper; byte identity by `tests/stage1/test_byte_identity.py` | A, B |

Each ADR has measured inputs with report file names, numbered decisions, rejected alternatives, unchanged
items and a "Not verified" (or "Not done") paragraph. None says an advisor agreed: no record of that exists
on this branch.

## Contract clauses changed (docs/stage1-contract.md, annotated in place, "stage1-v4, ADR-00NN; stage1-v3: ...")

- Version line and new §1 "Amendment stage1-v4" paragraph (not on the requested list; needed so the
  annotations resolve). Applies to runs executed by the stage1-v4 software.
- §3.2 (second section): metadata cache reuse rule (ADR-0049) and GDAC roles (ADR-0052); not on the
  requested list.
- §7: generation/parts definition (ADR-0051); raw object keys `.nc` (ADR-0050/0052); publication steps 3-5
  replaced (ADR-0050); step 7 staging and manifest (ADR-0051); S1-RESOURCE-2 implementation note
  (ADR-0050, ADR-0053).
- §7.2: selection of parts, snapshot and manifest (ADR-0051).
- §8.1: no Celery in the retry-owner sentence; acquire-to-process hand-over, lease renewal and re-claim
  (ADR-0047).
- §9: spool-reuse paragraph (ADR-0051); table rows numeric/canonical (ADR-0053), requests/data
  (ADR-0049), concurrency/memory (ADR-0047/0048), I/O deadlines (ADR-0048), retry/recovery (ADR-0047);
  retry-owner paragraph (ADR-0047/0048); host allow-list for `data-argo.ifremer.fr` (ADR-0052; not on the
  requested list).
- §10: Celery Beat replaced by `floatchat schedule` (ADR-0047).
- §11: payload-attempt origins, full stored-snapshot reconciliation through the manifest, GDAC fixtures
  and evidence paragraph (ADR-0049/0051/0052).

Celery, Redis or broker wording left unannotated (outside the amended clauses; line numbers are after
the edits): contract lines 95 (§2
"Redis namespace/queue"), 547 (§7 "broker deliveries"), 713 (§8 "broker delivery"), 928 (§9 "broker
results"), 972 (§10 "failed Celery task"), 1072 (§11 CI "Redis"), 1218, 1220, 1230 (§12 rows B03, B05,
D06) and 1314 (§13). Also `README.md:92` (target-architecture queue for analysis and forecast workers),
`FLOATCHAT_BUILD_PROMPTS.md:428` (a later-stage prompt about Celery queues), `FLOATCHAT_PRD_v2.md`, and
the historical ADRs.

## Other files

- `PROGRESS.md`: new top entry for 2026-10-08. The live-session facts are exactly the five the task gave.
- `README.md` (line 9 and the queue edge of the architecture diagram), `FLOATCHAT_BUILD_PROMPTS.md`
  (Stage 0 item 4, Stage 1 item 8 and the Stage 0 remains bullet), `docs/stage1-acceptance-preparation.md`
  (Redis, volumes, memory, smoke task, live worker and concurrency sentences; "migrates through 0007" was
  stale and sits in the same sentence, so it now says the current head, 0014). I left that document's
  21,600-second budget sentence, which predates ADR-0043.

## Could not source from a report (stated as open or unmeasured in the ADRs)

- Advisor or owner confirmation of the ADR wording.
- The cause of the quarantine in session 7153be6379df84de, and any of its numbers: the evidence files
  are not on this branch.
- Any check of Argovis usage terms or rate limits (review candidate 10 asked for one), any measured effect
  of concurrent requests, and persisted governor counters.
- The real share of repeated floats in a Jan-Mar run (bench E fixes 16 distinct of 60), and any
  measurement behind the 30-day cache window.
- Commit and COPY time on the new publication path; all of migrations 0012, 0013 and 0014; the integration
  tests, probes and the 1 GiB writer proof; MinIO behaviour for conditional PUT with a checksum.
- The audit cadence (no report proposes a number and nothing calls the audit), and the sample size of
  `app.audit_levels`.
- Values chosen without measurement: re-claim after 2 minutes, 1 s poll, 30 s backoff cap, 3,600 s
  `compact` budget, `max_active_chunks` 8, default 4 slots, 30-day cache window.
- Benchmarks for D, F, G and H (no files under `reports/`); F's 487 MiB peak and G's download and
  conversion figures are from scratch scripts and are labelled as such.
- A full offline suite result on the integrated head. The package reports each give their own results
  (D 160 passed, E 110, G 111, H 95, C and F as listed there); the later full-suite figures in F.md predate
  the integration fixes.
- The default value of `INGESTION_PROCESS_WORKERS`: the design says `min(4, cpu)`; D.md does not restate it.
- GDAC download policy beyond the attribution string, and GDAC throughput on the production host.

## Checked in code (read-only) while writing

- `audit=True` is not passed by `processor.py` or `workers/`; only the library supports it.
- `landing.cache_fresh` is `retrieved_at >= anchor - 30 days` with the run's actual creation time as the
  anchor, not the reference time that the design document describes.
- No GDAC reference exists in `processor.py`, `source.py` or `workers/`.
- `_small_json_bound` and the test package A said needed deleting are gone from the tree.

## Conflicts and inconsistencies between sources (resolved as stated)

- Design §4.4 says `RLIMIT_AS`; design §2 and package D say `RLIMIT_DATA`: ADR-0047 follows `RLIMIT_DATA`.
- Design §4.5 bounds cache reuse by the run reference time; package E and the integrator use the run's
  actual creation time: ADR-0049 follows E.
- Package B's `policy_versions("gdac-core-v1")` has no `specification_sha256`: recorded in ADR-0053.
- Design §2 says "decode the landed payload once"; the benchmark still records five decodes
  (`documents()` multiplicity 5): ADR-0053 records it as not done.
- The live checkout's PROGRESS.md has two uncommitted bullets (runs 3-5, the fifth run) that this branch's
  PROGRESS.md lacks; not reconciled.
- Contract §10 (line 972, left as written) says the scheduled path records an overlap "without a CLI
  exit or failed Celery task"; ADR-0047 decision 8 records that `floatchat schedule` exits 0 on
  `overlap_skip`. The durable event is the same; only the exit code now exists.

## Open questions for the integrator

- Audit cadence (`audit=True`, `app.audit_levels`) and its sample size.
- Whether GDAC rejection categories (`gdac_index_changed`, `invalid_netcdf`, ...) should fail or
  quarantine a chunk; whether `landing_retry_exhausted` and other newly safe database categories should
  still quarantine.
- Memory behaviour at the contractual chunk cap (256 MiB canonical, 2,000,000 levels) with in-memory
  candidates.
- The `INGESTION_PROCESS_WORKERS` default (the design says `min(4, cpu)`).
- The worktree's earlier uncommitted script, test and report changes (`scripts/stage1_perf_*`,
  `tests/stage1/*`, `reports/stage1-v4-*`, `reports/stage1-v3-bench-chunk-baseline.json`) are not mine and
  were not touched.
