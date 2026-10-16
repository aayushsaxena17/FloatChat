# Stage 5 plan - historical jobs and exports (reviewed 2026-10-16)

Status: **in progress on `codex/stage-5`** (owner instruction 2026-10-15: complete Stages 5 and
6 on separate branches, decide every open question without asking). Scope: build prompt
"Stage 5", PRD §2.3, §5.8, §5.9, §6.7, §8.4, §9.3, §13, §14, §17, §21.2, §22. Branch
`codex/stage-5` from `design/ocean-light` at `b688cd9` (the owner's current line of work:
Stage 4, the model fallback and the redesign, none of them merged into `main` yet); one pull
request, opened against `design/ocean-light` so the diff shows only this stage. Stage 6 builds
on this branch. Decisions taken in this review are ADR-0077 to ADR-0081.

## 0. What this review changed in the Stage 4 gate's proposed plan

The Stage 4 gate proposed `analysis_job` and `analysis_job_chunk`, separate Celery queues, the
five job endpoints with idempotency and attachment, chunked resumable retrieval over the Stage 1
pipeline, CSV and Parquet exports with manifests and signed URLs, the jobs UI, the §22 failure
tests and the ten-year report. Reviewing that against the merged code and this host changed:

1. **No Celery.** ADR-0047 removed Celery and Redis from the workers for a PostgreSQL work
   queue, and the build prompt's rule 8 forbids a new framework without an ADR. The §21.2
   queues are names on the job table; one worker process serves a configured set of queues
   with `FOR UPDATE SKIP LOCKED` claims, leases and heartbeats, the same pattern as the
   ingestion tickets (ADR-0077).
2. **Historical retrieval is a new ingestion run mode, not a new fetcher.** Stage 1 enforces
   the twelve-month window in SQL (the run trigger, `ensure_measurement_month`,
   `commit_publication`) and plans the whole envelope (`persist_plan` rejects a partial tile
   set). A `historical` run captures its reference time as the requested end, spans at most
   twelve months and plans only the tiles its input descriptor names, so every Stage 1
   eligibility rule holds unchanged for it. A ten-year job is ten such runs, one per calendar
   year of missing months, executed one at a time because the scope admits one open run
   (ADR-0078).
3. **Historical months land in PostgreSQL too.** The Stage 1 commit writes the identity
   registry, the levels and the Parquet part in one transaction; a Parquet-only tier would
   need a second commit path. The PRD's "materialised on demand" tier is therefore served by
   the same catalogue, and the DuckDB route (members from the registry, levels from the parts)
   reads it. The cost consequence is recorded with the trigger for changing it (ADR-0078).
4. **The dev stack grows the ingestion pool and a jobs worker.** `acquire`, `process`,
   `supervisor` and `jobs` services from the API image; the environment row of the imported
   dataset is adopted by the stack it runs in (bucket, queue namespace, compose project), an
   ingestion login is created by the bootstrap, and only the `acquire` service sees the
   Argovis key, from the restricted configuration file, with live ingestion opt-in
   (ADR-0078). `tests/test_compose.py` changes accordingly.
5. **Signed URLs are the API's.** The browser cannot reach MinIO (no published port), so
   `GET /v1/artefacts/{id}/download` streams the object and the "signed URL" is that route
   with an HMAC token (`ARTEFACT_SIGNING_KEY`, generated locally) that expires after fifteen
   minutes; artefacts expire after seven days and a reconciler marks them expired before
   deleting the objects (PRD §8.4 eviction order) (ADR-0079).
6. **Attachment is per client.** Jobs are scoped to the Stage 4 client identifier until Stage
   7 brings users; an identical active request from the same client attaches, from another
   client it becomes a new job that reuses the coverage the first one commits (ADR-0079).
7. **Exports are long tables of policy-selected values** with the QC and data-mode columns
   beside them, one row per level, produced by DuckDB in the worker over the verified parts
   (PRD §5.8), never by the API process (ADR-0080).
8. **The chat offers a job instead of refusing.** A plan the model produced that fails only
   the span rule becomes a `job_offer` outcome carrying the plan; the web shows a card that
   creates the export (ADR-0081).

## 1. Inputs the code provides

- Stage 1: `Repository.admit` (`app.admit_run`, idempotent by request id, `overlap_skip` while
  a run is open), `persist_plan`, the supervisor and the two worker pools
  (`floatchat supervise|acquire|process`), run and chunk states, the coverage receipts, the
  catalogue (`app.committed_active_partitions`), `MinioStore`.
- Stage 2: `validate_plan`, `QueryLimits`, `QueryCatalogue.tiles_for` and `.coverage`
  (slot states `covered`, `empty_verified`, `missing`), `PartCache`, `DuckEngine`,
  `compile_sql.profile_slot_statement`, `compile_duckdb.members_from_columns`, qc-policy-v1
  CASE expressions, provenance builder and attribution texts.
- Stage 4: the client header, the app-role store pattern, the SSE writer, `_Loose` models.
- Dev dataset: environment `a21ebf92…`, acceptance mode, T `2025-04-01`, Jan-Mar 2025, 5,814
  profiles, 206 parts; named regions with their tiles (Arabian Sea 10 tiles, Bay of Bengal 8,
  Laccadive Sea 4, Andaman Sea 2). The 2026-10-09 live run fetched the whole envelope for three
  months (1,260 chunks) in 22 minutes with four upstream slots.

## 2. Decisions (summary; full text in DECISIONS.md)

- ADR-0077: scope, branch, PostgreSQL queues, worker topology, no Celery.
- ADR-0078: `historical` ingestion runs, tile-restricted plans, PostgreSQL retention of
  historical months, environment adoption, dev-stack workers and the key.
- ADR-0079: job model, states, idempotency and attachment, events and SSE resume, artefact
  lifecycle and signed downloads.
- ADR-0080: export content, manifest, provenance sidecar, DuckDB in the worker.
- ADR-0081: API, web routes, chat job offer, failure tests, the ten-year report.

## 3. Work items

### W1. Migration `0019_jobs_exports`

- `app.ingestion_run.mode`, `app.scheduling_attempt.mode` CHECKs admit `historical`;
  `check_run_immutability` and `admit_run` accept a historical run in a normal or disposable
  acceptance environment, set its reference time to the requested end, require the end at
  or before now and the span at most twelve months; `persist_plan` takes the expected tile set
  from `ingestion_input.descriptor->'tiles'` for historical runs; `query_environment` keeps
  its reference time from non-historical runs (historical runs still count in
  `completed_runs`, which invalidates the ADR-0067 memo).
- `app.analysis_job` (id, kind `export`, queue, client_id, idempotency_key, request jsonb,
  request_sha256, plan jsonb, state `queued|fetching|exporting|completed|partial|cancelled|failed`,
  progress jsonb, error jsonb, version, lease_until, claimed_by, attempts, cancel_requested_at,
  timestamps; unique `(client_id, idempotency_key)`), `app.analysis_job_chunk` (job_id, seq,
  kind `fetch|export`, label, interval, tiles, state
  `pending|running|complete|reused|failed|cancelled`, attempts, ingestion_run_id, evidence,
  error, timestamps; unique `(job_id, seq)`), `app.analysis_job_event` (job_id, seq, kind,
  payload; unique `(job_id, seq)`), `app.analysis_artefact` (job_id, format `csv|parquet`,
  object_key, bytes, sha256, row_count, profile_count, manifest jsonb, state
  `available|expired|deleted`, expires_at, deleted_at).
- Grants: `floatchat_app` DML on the four tables; `STAGE5_APPLICATION_TABLES` in the bootstrap;
  `MIGRATION_HEAD` and the openapi path test updated.

### W2. Historical runs (`floatchat_core/ingestion`)

`RunPolicy` mode `historical` (reference = requested end, eligible = requested interval,
`validate` requires at most twelve months); `plan(interval, tiles=...)`; `persist_plan` reads
the descriptor's tiles for historical runs; `Repository.admit(..., mode="historical")`; the CLI
`ingest --mode historical --tiles 50:0,...` for operators.

### W3. Jobs core (`floatchat_core/jobs`)

`model.py` (request schema `export-request-v1`: the `stage2-plan-v1` fields without
operation, plus `format` csv|parquet and `idempotency_key`; the plan is validated with the
job limits, span up to 20 years), `store.py` (app-role store: create with attach, claim by
queue, heartbeat, chunk and event writes, cancel with version check, artefact rows, listing
by client with cursor), `planner.py` (required slots from months × tiles, coverage comparison,
fetch chunks per calendar year of missing months, the export chunk), `export.py` (DuckDB COPY
to Parquet and CSV over the verified parts with members from PostgreSQL, counts, sha256,
manifest and provenance sidecar), `artefacts.py` (object keys `exports/<job>/<artefact>.<ext>`,
signing and verification of download tokens, expiry).

### W4. Worker (`floatchat_workers/jobs.py`, `floatchat jobs --queues export`)

Claim, plan, run fetch chunks (admit a historical run per chunk with a fresh request id, wait
for it to close, record its counters, retries and leaf outcomes; `overlap_skip` waits), run
the export chunk, finish `completed` or `partial` (missing slots listed), honour cancellation
between steps (cancels the open run), heartbeat the lease, resume claimed jobs whose lease
lapsed (complete and reused chunks are never repeated; a running fetch chunk re-attaches to
its ingestion run). The reconciler tick expires artefacts, deletes their objects after the
state change, and removes export objects older than one hour that no artefact row names.

### W5. API (`apps/api/src/floatchat_api/jobs_api.py`)

`POST /v1/exports` (202, `Idempotency-Key` header or body field, attach on identical active
request), `GET /v1/jobs` (client's jobs, cursor), `GET /v1/jobs/{id}` (job, chunks, artefacts
with download URLs when available), `GET /v1/jobs/{id}/events` (SSE from the event table,
`id:` lines, `Last-Event-ID`, heartbeat comments, ends at a terminal event),
`POST /v1/jobs/{id}/cancel`, `GET /v1/artefacts/{id}/download?token=` (streams the object).
New codes: `job_not_found` 404, `job_conflict` 409, `artefact_unavailable` 410,
`token_invalid` 403, `jobs_unavailable` 503. `API_VERSION` 0.4.0; openapi and `schema.d.ts`.

### W6. Web (`apps/web/src/jobs`)

`/jobs` (list, state badges, progress), `/jobs/:jobId` (request summary, chunk table with
state, run outcome, retries and reuse, cancel button, artefact cards with size, counts,
checksum, expiry, citation, download), the dashboard's export button creates a job for the
current filters and navigates to it, the chat job-offer card. Nav gains Jobs.

### W7. Dev stack and tooling

Compose services `acquire`, `process`, `supervisor`, `jobs`; bootstrap creates the
`floatchat_ingest` login and adopts the environment row; `.env.example` gains
`DB_INGEST_PASSWORD`, `INGESTION_DATABASE_URL`, `ARTEFACT_SIGNING_KEY`, `ARGOVIS_API_KEY`
(empty), `FLOATCHAT_LIVE_INGESTION_ENABLED=false`; `scripts/integration.py` creates an export
job over the seeded months and checks its artefact; `scripts/stage5_report.py` runs the
ten-year request twice and writes `reports/historical_jobs_<date>.md`.

### W8. Tests

- `tests/stage5/test_planner.py`: slots, reuse, year grouping, partial coverage.
- `tests/stage5/test_store.py` (integration, disposable PostGIS): create, attach, claim,
  lease lapse and re-claim, cancel version conflict, events and resume, artefact lifecycle.
- `tests/stage5/test_worker.py`: the runner over doubles: a worker killed mid-chunk resumes
  without repeating complete chunks; an upstream that stays down ends partial with the missing
  slots listed; an object written whose artefact commit fails stays unreachable and is removed
  by the reconciler; cancellation.
- `tests/stage5/test_export.py`: DuckDB export over the seed parts, counts, sha256, manifest.
- `tests/stage5/test_jobs_api.py`: endpoints over a memory store, SSE order and resume,
  tokens, client scoping.
- `tests/stage1/test_historical.py`: policy, tile-restricted plans, SQL admission of a
  historical run (integration).
- Web: Vitest for the job list, detail and the offer card; Playwright `jobs.spec.ts` in the
  integration project.

### W9. Documents and gate

`docs/stage5-gate.md`, PROGRESS.md, DECISIONS.md, README (jobs section), the report.

## 4. Out of scope

NetCDF (deferred, §29.10), quotas and users (Stage 7), cross-client attachment, a
Parquet-only historical tier, Redis-backed progress, compaction of historical slots (the
operator command exists), forecasts (Stage 6).

## 5. Gate

The ten-year Arabian Sea request completes through the job system, survives a worker restart
and reuses every partition on the second run; CSV and Parquet exports open with their
manifests; lint, types and tests pass locally and in CI; the report is in `reports/`.
