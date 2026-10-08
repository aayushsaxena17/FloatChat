# stage1-v4 execution design (owner decisions 2026-10-08)

Owner decisions (Aayush, 2026-10-08, after `docs/ingestion-performance-review.md`):
rewrite the execution model and keep the science rules; adaptive parallel Argovis
requests on one key (start 4, back off on 429; no multi-key rotation); build the GDAC
NetCDF bulk source now, downloads from data-argo.ifremer.fr allowed; production
target is a dedicated Linux server with 8 GB+ RAM, validated here on a 3.7 GB WSL
host; Celery/Redis replaced by a PostgreSQL work queue. ADRs for every contract
change are written under the owner's authority (ADR-0039).

This document is the brief for every implementation package. Read it fully before
touching code. Section 6 lists the rules every package follows.

## 1. Invariants (science rules kept, byte for byte)

- `scientific-json-v2` canonical bytes and content hashes, `argovis-core-v1` mapping
  semantics, exact-decimal rules (§5, §5.1, §6 of `docs/stage1-contract.md`).
  `tests/stage1/test_byte_identity.py` compares every scientific output against
  `tests/fixtures/golden/stage1_v3_goldens.json` (generated at `90e1e67` by
  `scripts/stage1_goldens.py`); it must pass after every package.
- Immutable, hash-addressed raw and normalised objects; sanitized raw bytes
  (`raw-sanitization-v1`) byte-identical to today (goldens cover them).
- One fenced PostgreSQL transaction publishes a chunk: identity resolution, revision
  comparison, outcomes, coverage receipts, catalogue activation and completion
  happen together or not at all. Control epochs, fences, leases, claim budgets and
  the recovery table in §8.1 keep their meaning.
- Geometry, slots, ownership (`indian-ocean-v1`, plan v2), run reference time,
  eligibility windows, quarantine categories and reporting units (§3, §4, §8, §11).
- Security bounds: pinned HTTPS hosts, no redirects, size/depth limits, credential
  never in arguments, logs, fixtures, reports or Git.

## 2. Architecture

```
controller (supervise) ──plans chunks, issues tickets──▶ app.processing_ticket (queue)
                                                             │ kind=acquire        │ kind=process
                                                             ▼                     ▼
                                       acquire process (1 per env, N threads)   process pool (M processes)
                                       Argovis/GDAC → raw objects → landed      landed → map → parts → commit
                                                             │                     │
                                                             └──────── PostgreSQL + object store ────────┘
                                                                         compact job (periodic)
```

- **Queue.** `app.processing_ticket` gains `kind` (`acquire`|`process`), `claimed_by`,
  `claimed_at`. Workers claim with `SELECT ... FOR UPDATE SKIP LOCKED` through
  `app.claim_ticket(kind, worker_name)`. The controller issues an `acquire` ticket
  for `planned`/`fetching` chunks and a `process` ticket for `landed`/`validating`/
  `publishing` chunks, bounded by `app.ingestion_environment.max_active_chunks`
  (default 8; migration 0012). No Celery, no Redis.
- **Acquire process.** One per environment, `--slots N` threads (default 4). Each
  thread runs `Processor.land()` for one chunk. An in-process `UpstreamGovernor`
  holds the permits: on HTTP 429 it halves the permits, waits the Retry-After or 60 s,
  and restores one permit per 20 consecutive successes up to N. Each permit maps to
  advisory lock `(164993423, slot)` so a second acquire process cannot exceed N.
  Metadata responses are cached per float (`app.float_metadata_cache`); a hit records
  a `verified_raw` attempt for the current chunk that points at the cached object
  (origin `cache`), so replay identity is unchanged.
- **Process pool.** `--workers M` processes (default `min(4, cpu)`), each claims one
  `process` ticket at a time and runs `Processor.process()`; `maxtasksperchild=1`
  bounds memory; `RLIMIT_AS` per process replaces the cgroup check.
- **Transform.** Decode the landed payload once; map with the fast mapper; encode
  canonical bytes once and hash once; keep candidates in memory (chunk cap 256 MiB);
  resolve identities with one batched query per chunk; build the Parquet part from
  Arrow arrays; verify by Arrow equality and per-profile hash; upload with a
  server-verified SHA-256 checksum; COPY slim profile rows and binary level rows;
  commit.
- **Publication parts.** A chunk publishes one Parquet *part* per changed slot
  containing only its accepted profiles. `logical_partition_slot.membership_manifest`
  is maintained incrementally in the commit. The selector returns every active part
  of a slot plus the manifest; readers filter rows by manifest. `compact` merges a
  slot's active parts into one snapshot and supersedes them in one transaction. No
  retained-profile read-back at publish time.
- **GDAC source.** Month x tile chunks as today; acquire downloads the GDAC daily
  basin files (`geo/indian_ocean/<yyyy>/<mm>/<yyyymmdd>_prof.nc`) once per month
  (shared by all tiles through the raw-object cache) and the global profile index
  for completeness; transform filters the tile and maps with `gdac-core-v1`, whose
  "exact" text is the shortest round-trip decimal of the stored float32/64 value.
  GDAC profiles form a separate source population (`source='gdac'`, logical keys
  `gdac/core/...`); Argovis stays the daily-increment source.

## 3. Packages, owners and file ownership

Each package edits only the files it owns. If a change is needed elsewhere, write it
in the package's report (`docs/v4-packages/<package>.md`) and stop; the integrator
applies it. Interfaces in section 4 are fixed: code to them even if the other side
has not landed yet.

| Pkg | Scope | Owned files |
|---|---|---|
| A | fast exact decode, sanitize, encoder | `numeric.py`, `raw.py`, `json_stream.py`, `tests/stage1/test_numeric.py`, `test_json_stream.py`, `test_raw.py`, `scripts/stage1_perf_experiments.py` |
| B | fast mapper | `argovis.py`, `tests/stage1/test_wire.py`, `tests/stage1/test_mapper_fast.py` (new) |
| C | Parquet write-once, Arrow verification, checksum upload | `parquet.py`, `objects.py`, `minio.py`, `tests/stage1/test_parquet.py`, `test_objects.py`, `test_minio.py`, `tests/stage1/minio_probe.py` |
| D | queue, controller, worker processes, CLI, migration 0012 | `workers/src/floatchat_workers/*`, `controller.py`, `states.py`, `infra/migrations/versions/0012_work_queue.sql`, `tests/stage1/test_controller.py`, `test_broker.py`, `test_worker_cli.py`, `tests/stage1/broker_*.py`, `tests/test_worker.py` |
| E | threaded transport, governor, metadata cache, validate-once landing | `transport.py`, `landing.py`, `source.py`, `tests/stage1/test_landing.py`, `test_capture.py`, `test_replay_policy.py`, `tests/stage1/request_owner_probe.py` |
| F | publication v4: candidates, parts, slim staging, commit, selector, compaction, migration 0013 | `processor.py` (process/publish path only), `spool.py`, `workflow.py`, `repository.py`, `coverage.py`, `reporting.py`, `catalogue.py`, `infra/migrations/versions/0013_publication_v4.sql`, `tests/stage1/test_database.py`, `test_spool.py`, `test_coverage.py`, `test_publication_scale.py`, `test_publication_certificate.py`, `test_resources.py`, `tests/stage1/processor_probe.py`, `capacity_probe.py`, `repository_probe.py` |
| G | GDAC source, migration 0014, deps, fixtures | `packages/core/src/floatchat_core/ingestion/gdac.py` (new), `infra/migrations/versions/0014_gdac_source.sql`, `tests/fixtures/gdac/**`, `tests/stage1/test_gdac.py` (new), `pyproject.toml`, `packages/core/pyproject.toml`, `uv.lock`, `scripts/gdac_fixtures.py` (new) |
| H | acceptance tooling and compose for the new workers | `scripts/stage1_acceptance*.py`, `infra/docker-compose*.yml`, `infra/docker/*`, `tests/stage1/test_acceptance_preparation.py`, `tests/test_compose.py`, `Makefile` |
| I | ADRs, contract, PROGRESS | `DECISIONS.md`, `docs/stage1-contract.md`, `PROGRESS.md`, `FLOATCHAT_BUILD_PROMPTS.md` |
| J | benchmark tests and reports | `tests/stage1/test_chunk_scale.py` (new), `scripts/stage1_perf_profile.py`, `scripts/stage1_perf_model.py`, `reports/stage1-v4-bench-*.json` |

Paths without a directory are under `packages/core/src/floatchat_core/ingestion/`.
Integrator (main session): `processor.py` `land()`, wiring between packages, commits.

## 4. Interfaces (fixed)

### 4.1 Numeric and raw (A)

- `decode_json(raw, *, max_bytes, number_decoder) -> Any`: unchanged signature and
  rejection categories (`json_depth_limit`, `invalid_array_length`,
  `json_string_limit`, `invalid_json`, `duplicate_json_key`, numeric categories).
  Numbers still arrive as `Decimal` (or the caller's decoder type).
- `exact_number(token) -> Decimal`: same categories and precedence; the normalized
  length preflight is computed arithmetically, not by building the text.
- `sanitize_raw(raw, credential=None) -> SanitizedRaw`: byte-identical output;
  internally may capture number tokens with a `str` subclass instead of `Decimal`.
- `CanonicalBudget.encode(content) -> (bytes, hexdigest)`: byte-identical; levels are
  C-encoded then length-checked, streaming only when a level does not fit
  (`canonical_output_limit` precedence and charged bytes unchanged at the boundary).
- `documents(raw, *, max_documents, number_decoder)`: unchanged.

### 4.2 Mapper (B)

- `map_profile(document, metadata, budget, *, source_contract) -> Profile`: identical
  `Profile` fields for every input (levels tuple of dicts with the same keys and
  values, canonical bytes, hash, revision, outside_core_arrays) and identical
  rejection categories. Target: at least 2x faster on `scripts/stage1_perf_profile.py`
  "map_profile + budget.encode".
- New helper `level_table(profile) -> pyarrow.Table` (columns exactly `parquet.schema()`
  minus `profile_id`, `source_profile_id`, `profile_hash`, `profile_content`), used by C.

### 4.3 Parquet and objects (C)

- `write_snapshot(path, profiles, *, deadline, max_bytes, budget_factory, audit=False)`
  -> evidence dict with the same keys (`schema_sha256`, `rows`, `profiles`,
  `membership_sha256`, `storage_comparison`, `writer_options`) plus
  `verification: "arrow-equality-v4"` and `certificate: PublicationSnapshotVerifier`
  already certified for the file's digest/byte count. `audit=True` runs the full
  row-by-row re-decode (the periodic audit). Membership and schema hashes unchanged
  (goldens).
- `publish_verified(store, payload, publication_id, validate, *, deadline, raw=False,
  max_bytes, temporary_key=None, audit=False)`: same signature; single conditional
  PUT to the final key with a server-verified SHA-256 checksum (`ChecksumSHA256`),
  then `stat` to confirm existence and size; `audit=True` additionally GETs and
  revalidates. Raw keys also accept `raw/sha256/<hex>.nc`.
- `ObjectStore` protocol adds `write_immutable(key, data, sha256_hex, deadline)` and
  `stat(key, deadline) -> {"bytes": int, "sha256": str | None}`; `read` stays;
  `write_temporary`/`publish_if_absent` remain for one release and are unused.
- `PublicationSnapshotVerifier(digest, byte_count, evidence, *, deadline, budget_factory,
  certified=False)`.

### 4.4 Queue and workers (D)

- Migration 0012: `processing_ticket.kind text NOT NULL DEFAULT 'process' CHECK (kind IN
  ('acquire','process'))`, `claimed_by text`, `claimed_at timestamptz`;
  `ingestion_environment.max_active_chunks integer NOT NULL DEFAULT 8`,
  `ingestion_environment.upstream_slots integer NOT NULL DEFAULT 4`;
  `app.claim_ticket(p_kind text, p_worker text) RETURNS app.processing_ticket` (SKIP
  LOCKED, sets claimed_by/at, returns NULL when empty); `app.claim_chunk` reads
  `max_active_chunks` instead of the constant 2; `app.float_metadata_cache(
  environment_id uuid, pointer text, raw_manifest_id uuid NOT NULL, run_id uuid NOT NULL,
  retrieved_at timestamptz NOT NULL, PRIMARY KEY(environment_id, pointer))`.
- `Controller.tick()` issues tickets by phase: `dispatch(authority, kind)`.
- `floatchat_workers.queue.claim(repository, kind, worker) -> Ticket | None`,
  `floatchat_workers.acquire.main(slots)`, `floatchat_workers.process.main(workers)`,
  CLI: `floatchat-stage1 acquire --slots N`, `process --workers M`, `supervise`,
  `compact`, `ingest ...` (unchanged arguments), `report`, `status`, `cancel`.
  `process_ticket(run, chunk, ticket, kind)` returns the chunk state string.
- Environment: `INGESTION_ACQUIRE_SLOTS`, `INGESTION_PROCESS_WORKERS`,
  `INGESTION_WORKER_MEMORY_BYTES` (RLIMIT_AS, default 1 GiB). `INGESTION_REDIS_URL`
  removed; Configuration no longer requires it.

### 4.5 Acquire side (E)

- `transport.fetch(...)`: same signature; no `signal`; usable from any thread; the
  attempt bound (120 s) and idle read (110 s) enforced with socket timeouts and
  monotonic checks. `HTTPFailure.retryable` unchanged.
- `transport.UpstreamGovernor(permits)` with `acquire(deadline)`/`release(status)`;
  `landing.RequestOwner` takes `governor` and uses per-slot advisory locks
  `(164993423, slot_index)` through `Repository.upstream_slot(authority, deadline, slot)`.
- Metadata cache in `RequestOwner.obtain(role="metadata")`: hit when the cache row's
  `retrieved_at` is within 30 days before the run's `run_reference_time_utc` and the
  object verifies; miss fetches and upserts. `validate_raw` runs once per landing.

### 4.6 Publication v4 (F)

- Migration 0013: `app.measurement_staging(run_id, chunk_id, fence, occurrence_index,
  level_index, <the 36 core_measurement value columns>)` filled by COPY;
  `app.ingestion_staging.candidate` shrinks to identity fields, `content_hash`,
  `revision`, `raw_manifest_id`, `canonical` (text), `level_count`;
  `core_measurement.canonical_level` dropped; `dataset_partition.kind text NOT NULL
  DEFAULT 'snapshot' CHECK (kind IN ('part','snapshot'))`, `part_ordinal integer`;
  `commit_publication` v4 (levels inserted set-based from `measurement_staging`,
  manifest maintained incrementally, generations are parts); view
  `committed_active_partitions` lists parts and snapshots; `app.compact_slot(...)`.
- `spool.py` replaced by `candidates.py`-style in-memory `ChunkCandidates` (keep the
  module name `spool.py` and the names `ProfileSpool`, `restore_profile`,
  `revision_json` for callers; `ProfileSpool` no longer uses SQLite or re-encodes).
- `Repository.stage_levels(authority, table: pyarrow.Table)` (binary COPY),
  `Repository.identities_batch(profiles) -> dict`, `Repository.commit(...)` unchanged
  signature, `Repository.compact(...)`.
- `objects.select_active_partitions` returns parts and snapshots; `Selection` gains
  `manifests: dict[slot, list]`.
- `Processor.process()` body: map -> candidates -> parts -> publish -> stage -> commit.

### 4.7 GDAC (G)

- `gdac.py`: `GDAC_HOST = "data-argo.ifremer.fr"`, `index_entries(raw_index_bytes,
  interval, tile) -> list`, `daily_file_keys(interval) -> list[str]`,
  `profiles_from_netcdf(path, tile, interval) -> Iterator[dict]` yielding documents in
  the Argovis wire shape (`_id = "gdac:<platform>_<cycle><direction>"`, `metadata`
  pointer synthesized, `data_info`/`data` columns PRES/TEMP/PSAL with `_argoqc`),
  so `map_profile(..., source_contract="gdac-core-v1")` reuses the mapper with
  `source: "gdac"`, `mapping_version: "gdac-core-v1"`, `hash_version:
  "scientific-json-v2"`. Exact text: `numpy.format_float_positional(value,
  unique=True, trim="-")` of the stored dtype. Fill values -> `argo_fill`.
- Migration 0014: `source` CHECKs on `argo_float`, `argo_profile`, and object key
  regexes accept `gdac`; `raw_manifest.object_key` accepts `.nc`.
- Dependencies: add `netCDF4` and `numpy` to `packages/core` (only package G runs
  `uv add`/`uv lock`).

## 5. Migrations

0012 (D), 0013 (F), 0014 (G): stubs exist with alembic wrappers; fill the `.sql`.
`tests/stage1/test_database.py` and `scripts/stage1_perf_db_probe.py` load every
`infra/migrations/versions/*.sql` in order.

## 6. Rules for every package

1. Work only in `/home/floatchat/FloatChat-perf` with `.venv/bin/python`; never touch
   `/home/floatchat/FloatChat-stage1`, any `floatchat-s1-acceptance-*` container, the
   Argovis key, or `.env.txt`.
2. No `docker` commands and no `-m integration` tests until the integrator says the
   live run has finished. Run only the test files you own plus
   `tests/stage1/test_byte_identity.py`, with `nice -n 19 .venv/bin/python -m pytest
   <files> -m "not integration" -q -p no:cacheprovider`. Before each run, check
   `free -m`; if "available" is below 900 MB, wait and retry.
3. Do not run `git commit`, `git stash`, `git checkout` or `uv add` (G excepted for
   `uv add`). Edit only owned files. `ruff format` and `ruff check` only owned files.
   Keep mypy strict clean for owned package/worker modules
   (`.venv/bin/mypy <file>`).
4. Every change to a limit, policy or scientific rule is written down in your
   package report (`docs/v4-packages/<pkg>.md`): what changed, why, measured
   evidence, which contract clause/ADR it affects, which tests cover it. Package I
   turns these into ADRs.
5. Byte identity: `test_byte_identity.py` must pass. If you believe a golden must
   change, stop and report; never regenerate goldens.
6. Record before/after timings for anything you optimize with the existing scripts
   (`scripts/stage1_perf_profile.py`, `scripts/stage1_perf_experiments.py`) into
   `reports/stage1-v4-bench-<pkg>.json`; numbers in reports come only from scripts.
7. Style: match surrounding code (terse comments, exact error categories, no silent
   behaviour changes, credentials never rendered). Rejection categories are an API.
8. Finish with the report file: summary, files changed, tests run and results,
   measurements, open items for the integrator.
