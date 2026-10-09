# Handoff prompt: FloatChat ingestion performance work (paste into a new session)

---

You are working on **FloatChat** for the owner, Aayush. Read this whole brief before acting.
Your first deliverable is an **analysis and optimization report, not code**. Implementation
comes after that report, on a separate branch, under the constraints in section 6. Another
long-running process (a live acceptance run) must not be disturbed.

## 1. Project and authority

- Repository: `aayushsaxena17/FloatChat`, WSL2 Ubuntu 24.04 checkout
  `/home/floatchat/FloatChat-stage1`, branch `codex/stage-1`, head `e1ba4f0` (CI green on
  GitHub for all seven jobs).
- FloatChat is an Argo ocean-float data platform. The PRD is `FLOATCHAT_PRD_v2.md`.
  The staged build plan is `FLOATCHAT_BUILD_PROMPTS.md`, and Stage 1 (data foundation) is
  nearly done. The Stage 1 contract is `docs/stage1-contract.md` (now **stage1-v3**).
  Decisions are in `DECISIONS.md` (read ADR-0039 to ADR-0045 closely) and status is in
  `PROGRESS.md`.
- ADR-0039: the owner authorized live Argovis calls with the key in the git-ignored
  `.env.txt`, and pushing or gate decisions after advisor agreement. The key is only
  ever loaded through `scripts/with_argovis_key.sh <command>`. Never print it, never put
  it in arguments, logs or reports, and never commit it.
- Contract rule: every limit, policy or scientific rule changes only through a new ADR
  that cites measured evidence. Measured infeasibility is recorded, never waived silently.
  Historical evidence keeps its stated scope.

## 2. What the ingestion pipeline does (one run)

Code is in `packages/core/src/floatchat_core/ingestion/`, with the worker and CLI in
`workers/src/floatchat_workers/`. Migrations 0002–0011 are in `infra/migrations/versions/`
(PostgreSQL + PostGIS, restricted `SECURITY DEFINER` functions).

1. **Plan** (`planning.py`, `repository.py`, SQL `persist_plan`): an immutable reference
   time, budgets, and a 12 h deadline. Plan v2 splits the request into whole UTC
   months × 10° tiles over the Indian Ocean envelope (20–120E, 60S–30N). Jan–Mar 2025
   gives 270 root chunks. Adaptive splitting halves time, then space, on size limits.
2. **Dispatch** (`controller.py`, `workers/.../ingestion.py`): a supervisor and controller
   with leases and fencing hand opaque chunk tickets to a Celery worker over Redis.
   There is one worker with concurrency 1 and one credentialed upstream request in
   flight per environment.
3. **Fetch and land** (`transport.py`, `landing.py`, `source.py`): per chunk,
   inventory-before, `data=all` profile and inventory-after `GET /argo` requests. The
   identity sets must match, and a mixed or changing selection restarts the selection
   up to 4 times. Then one `/argo/meta` request per float.
   - Every response is a pinned, validated HTTPS request with streaming size limits
     (16 MiB raw, 128 MiB decoded). The idle read is 110 s, an attempt is capped at
     120 s, and retries use 4 attempts with 60/180/300 s equal-jitter backoff (ADR-0045).
   - The private original is kept, then sanitized and published to MinIO as an
     immutable SHA-256 raw object. A durable `raw_manifest` row is written via
     `app.finish_attempt`.
   - A 404 whose body is exactly an empty JSON array is a verified empty-delivery
     receipt (S1-SOURCE-2, ADR-0040).
4. **Validate and map** (`processor.py`, `argovis.py`, `numeric.py`, `spool.py`):
   - JSON is decoded with exact decimals and bounded numbers.
   - Fields are mapped to core science: pressure, temperature and salinity, plus
     adjusted values, errors, QC, units and data modes.
   - Warnings are checked. A profile whose only warning is `degenerate_levels` is
     excluded with outcome `excluded_source_loss`.
   - Ownership, region, time and identity are resolved and revisions compared.
   - Each profile is encoded to canonical `scientific-json-v2` with a SHA-256 content
     hash and spooled into a private SQLite file.
   - Every canonical encoding is charged against a run budget (40 GiB, ADR-0041).
5. **Publish** (`parquet.py`, `objects.py`, `processor.publish`, SQL
   `app.commit_publication`):
   - The full month×tile slot snapshot, including retained profiles, is written as
     Parquet (Zstd-3, 100k-row groups).
   - The temporary object is verified from the local file and again from object
     storage, then made the immutable final object.
   - One DB transaction (≤60 s) inserts profiles and levels, activates the catalogue
     generation, writes coverage receipts and completes the chunk. ADR-0044 made the
     level insert set-based and added an `owner_slot` expression index.
6. **Finalize and report** (`reporting.py`, SQL `finalize_run`): full and run-eligible
   reconciliation, frozen evidence, JSON and Markdown reports.
7. **Captured replay**: a second run reprocesses the saved raw landings without upstream
   access. It must leave the science and active generations unchanged.

Acceptance tooling: `scripts/stage1_acceptance.py` (`prepare` and `execute`) builds an
isolated Compose project per session. It has a separate PostgreSQL, MinIO, Redis,
network and volumes, and mounts the checkout **read-only**. `scripts/stage1_terminalize.py`,
`stage1_inventory_census.py`, `probe_argovis_empty_semantics.py`, `stage1_depth_spotcheck.py`
and `stage1_memory_sampler.py` produce evidence under `reports/`.

## 3. Measurements so far (cite these; all are in `reports/`)

- **Census of Jan–Mar 2025** (`stage1-inventory-census.json`): 5,845 unique profiles
  (2,010 in January, 1,798 in February, 2,037 in March) across 1,260 weekly leaves.
  922 leaves had data and 338 were empty; every empty one returned 404 `[\n\n]\n`.
  The densest month×tile holds 87 profiles.
- Depth averages 699 levels/profile in January and 384 in February/March samples, with a
  maximum around 1,450. That is roughly 4.1M levels in total. About 200 MB of raw JSON is
  downloaded. Canonical content is 1,214 bytes/level, about 5 GB in total.
- **Amplification:** weekly slices republished whole month slots, about 13 canonical
  conversions per profile; plan v2 brought this to about 4–5. Single-worker canonical
  throughput is about 0.9 MB/s.
- **Commit:** a 10,000-level profile took 23.5 s before ADR-0044 and 1.3 s after
  (`tests/stage1/test_publication_scale.py`). Root cause: per-level PL/pgSQL work plus
  `(jsonb_populate_record(...)).*` being evaluated once per column.
- **Live runs** (`stage1-live-*.json`):
  - Pre-fix pace was about 28 chunks/h. After the fixes it is about 60–90 chunks/h, so
    the live phase is about 3–4.5 h for 270 chunks, followed by replay.
  - Worker anonymous memory peaks at about 280–330 MiB with zero OOM events. WSL has
    only about 3 GB of RAM in total.
- **HTTP:** about 810 selection requests and about 2,000+ metadata requests per run.
  Metadata for the same float is re-fetched in every chunk where the float appears.
  - Inventory latency normally runs 1–30 s. During an upstream slow episode lasting at
    least 15 minutes it exceeded 60–80 s (`stage1-live-transport-8e8da1d4.json`).
  - `data=all` for a month×tile takes 10–50 s.
- **Writer probe:** a synthetic 100,001-level maximum-header profile set has an anonymous
  peak of 288 MiB. File-backed RSS is about 1.06 GB, from the mmap'd Parquet read-back.
- In steady-state production, daily scheduled runs only fetch the last 14 days (about
  900 profiles). The slow case is bulk backfill.

## 4. Goals

**Phase A — analysis only (your first deliverable).** Produce
`docs/ingestion-performance-review.md` (on the new branch, see section 6) containing:

1. A profile of where time and work go per profile and per chunk. Base it on code
   reading plus offline measurement on synthetic or recorded fixtures (CPU profiling with
   `cProfile`/`py-spy` of `processor`, `spool`, `numeric`, `parquet` and `objects`;
   DB timings in a disposable PostgreSQL). Do not touch the live run.
2. **Every** optimization you can find, ranked by expected speed-up, risk and effort,
   and marked "no contract change" or "needs ADR". Include at least these six candidates,
   which the owner already approved in principle:
   1. **Decouple fetch from processing:** land raw responses as fast as the upstream
      allows, then process from landed data with N parallel workers. Today one worker
      runs fetch→process→publish serially, so CPU idles on HTTP and vice versa.
   2. **Shared, versioned float-metadata cache** across chunks and runs.
   3. **Verify once:** produce canonical bytes once, verify later steps by hash, row
      count and schema, and keep full re-decode as a periodic or sampled audit. Today
      each profile is canonically re-encoded about 4 times and Parquet is read back twice.
   4. **Vectorized mapping and encoding** (Arrow/Polars, columnar), keeping exact
      decimal-string semantics and `scientific-json-v2` hashes byte-identical.
   5. **Bulk backfill source** (Argo GDAC NetCDF) for historical loads, with Argovis kept
      for daily increments. This is a new data source and needs owner approval: design
      and trade-offs only.
   6. **Append-then-compact Parquet publication** instead of rewriting month-slot
      snapshots.

   Also consider: two separate worker containers, each with its own 1 GiB cgroup (never
   `--concurrency=2` inside one 1 GiB container); partial-predecessor replay reusing
   saved raw landings; DB bulk-load paths; the Celery/Redis overhead; and anything else
   you find.
3. For each candidate: which contract clauses, ADRs and tests it touches, how scientific
   hashes and replay identity stay byte-identical, the failure and recovery implications,
   and an estimated before/after based on measurements.
4. A recommended implementation order with milestones and a target such as "Jan–Mar
   backfill under 1 hour on this 3 GB WSL host".

Stop after Phase A and present the report to the owner, or to the advisor if one is
configured, before any implementation.

**Phase B — implementation (after review).** On the new branch, implement the agreed
items in order:
- Add an ADR for every contract change.
- Add tests: unit, integration in disposable containers, and offline benchmark tests
  with recorded before/after numbers under `reports/`.
- Every existing `tests/stage1` test must keep passing, with the opt-in capacity model
  excepted. Scientific content hashes and replay identity must remain byte-identical to
  the current implementation on the same inputs. Add a regression test that proves it on
  recorded fixtures.

## 5. Definition of done for Phase B

- `make lint`, `make typecheck`, `make test` and `uv run --all-packages --frozen python -m
  pytest tests/stage1` are green, and GitHub CI is green on the branch head.
- Benchmarks show the measured speed-up. A live Jan–Mar acceptance plus replay is
  re-run **only after the current run has finished and the owner agrees**.
- `PROGRESS.md` is updated and the ADRs are written. Push only after review. Never
  force-push, never push to `codex/stage-1` or `main` directly, and open a PR from the
  new branch.

## 6. HARD CONSTRAINTS — a live acceptance run is in progress

A Stage 1 live acceptance run is running **now**. It is the evidence that closes Stage 1.
Do nothing that could disturb it.

- **Session and processes:**
  - Session `7153be6379df84de`, Compose project
    `floatchat-s1-acceptance-7153be6379df84de` (containers `...-db-1`, `...-minio-1`,
    `...-redis-1`, `...-supervisor-1`, `...-live-owner`, `...-client-run-*`).
  - It runs detached through `setsid`. The wrapper is
    `scripts/stage1_acceptance.py execute`, with its log at
    `/tmp/claude-1000/-home-floatchat-FloatChat-stage1/work/acceptance.log`.
  - A memory sampler (`scripts/stage1_memory_sampler.py`) and a Windows keep-awake
    PowerShell process (`floatchat-keepawake.ps1`) are also running.
  - After the live phase, the same wrapper starts the **captured replay** with new
    worker and client processes. They import code from the checkout at that moment.
- **Do not modify anything under `/home/floatchat/FloatChat-stage1`.** It is mounted
  read-only into the acceptance containers, and the replay imports `packages/`,
  `workers/`, `scripts/` and `infra/` from it. Work only in a **separate git worktree**:
  ```bash
  git -C /home/floatchat/FloatChat-stage1 worktree add /home/floatchat/FloatChat-perf -b codex/stage-1-perf e1ba4f0
  ```
  Use your own virtualenv there (`uv sync --all-packages --frozen` inside the worktree).
- **Do not** stop, restart, `exec` into, or `compose down` any container labelled
  `floatchat-s1-acceptance-*`. Do not run `docker system prune`, `docker volume rm`, or
  anything that removes images, volumes or networks. Earlier sessions' containers and
  volumes are preserved evidence too.
- **Do not use the Argovis key or make any upstream request** while the run is live. The
  contract allows one credentialed request in flight, and the run is using it. Work
  offline with recorded fixtures (`tests/fixtures/argovis/recorded/...`) and synthetic
  data.
- **Memory:** the WSL host has about 3 GB RAM shared with Docker, and the run's
  containers use about 1–1.5 GB.
  - Do not run the integration suite (`tests/stage1` integration tests start PostgreSQL,
    MinIO and Redis containers), heavy benchmarks, or `make integration` until the run
    finishes.
  - Offline unit tests (`pytest -m 'not integration'`) and lightweight profiling of
    single functions are fine.
  - Keep any disposable container to one at a time with `--memory` limits, or wait.
- **Do not** let Windows sleep: leave the keep-awake process running, and don't touch
  power settings.
- **Do not** push to `codex/stage-1` or modify its history. Do not edit `.env.txt`,
  `.claude/settings.local.json` or permission settings.
- The run is finished when the log shows `acceptance exit=` (success is
  `live_and_captured_replay_evidence_ready_for_review` and `acceptance exit=0`). Only then
  are integration tests, live probes and Docker-heavy work allowed again. Coordinate with
  the owner first: the original session closes the Stage 1 gate from that run's evidence.

## 7. Environment notes

- Tooling:
  - uv: `/opt/floatchat-tools/uv/bin/uv` (also on PATH).
  - Make targets: `setup test lint typecheck integration secrets-current`.
  - Node and pnpm for `apps/web`.
- Docker comes from Docker Desktop through WSL integration. If `docker` disappears,
  Docker Desktop on Windows has stopped.
- GitHub: there's no `gh` in WSL. Use the Windows CLI `"/mnt/c/Program Files/GitHub CLI/gh.exe"`.
  Push with:
  ```bash
  git -c credential.helper= -c credential.helper='!"/mnt/c/Program Files/GitHub CLI/gh.exe" auth git-credential' push origin <branch>
  ```
- Auto-mode permission checks may refuse writing migration files from the shell. Create
  or edit those with the editor tools instead.
- Style: match the surrounding code (terse comments, exact error categories, no silent
  behaviour changes). Committed numbers must come from scripts whose output is saved
  under `reports/`.
