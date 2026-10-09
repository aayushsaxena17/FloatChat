# Package H report: acceptance tooling and Compose for the queue workers

The isolated acceptance project now runs PostgreSQL, MinIO, a supervisor, one `acquire`
container (the only one that ever holds the Argovis key, on stdin, in the live overlay) and one
`process` container running the single-use worker pool. Redis and Celery are gone from every
acceptance file, wrapper, probe and test this package owns. Redis stays in the Stage 0 dev
stack only because the API needs it (see "Open items", 1).

## Services and variables (for the ADR writer)

| Item | Value | Where |
|---|---|---|
| `acquire` service | `python scripts/stage1_acceptance_runtime.py acquire`; `mem_limit: 1g`; internal network only; no key | `infra/docker-compose.acceptance.yml:91` |
| `process` service | `python scripts/stage1_acceptance_runtime.py process`; `mem_limit: ${ACCEPTANCE_PROCESS_MEMORY:-2g}`; internal network only; never the key | `infra/docker-compose.acceptance.yml:98` |
| `live-acquire` (overlay) | `extends: acquire`, command `... acquire --stdin-key`, `FLOATCHAT_LIVE_INGESTION_ENABLED=true`, networks `[default, upstream]`, profile `live`; replaces `live-worker` | `infra/docker-compose.acceptance-live.yml` |
| `INGESTION_ACQUIRE_SLOTS` | `${ACCEPTANCE_ACQUIRE_SLOTS:-4}`, acquire only. Must not exceed `ingestion_environment.upstream_slots` (default 4) | compose |
| `INGESTION_PROCESS_WORKERS` | `${ACCEPTANCE_PROCESS_WORKERS:-2}`, process only | compose |
| `INGESTION_WORKER_MEMORY_BYTES` | `"1073741824"` (1 GiB, `RLIMIT_DATA` per worker), process only | compose |
| `ACCEPTANCE_ACQUIRE_SLOTS`, `ACCEPTANCE_PROCESS_WORKERS`, `ACCEPTANCE_PROCESS_MEMORY` | written by `prepare` into `environment.env` from `stage1_acceptance.TOPOLOGY` (`4`, `2`, `2g`) and recorded as `worker_topology` in the manifest, so the sizing is covered by the environment-file hash | `scripts/stage1_acceptance.py:37` |
| Removed | `redis` service and volume, `ACCEPTANCE_REDIS_IMAGE`, `IMAGES["REDIS"]`, `INGESTION_REDIS_URL`, `REDIS_URL`, `ACCEPTANCE_REDIS_PREFIX`, manifest `redis_database`/`redis_prefix`, proof keys `redis_*`/`smoke_acknowledged` | |
| Unchanged | `db` 1g, `minio` 512m, read-only checkout mount, private directory mount, uid/gid, `pull_policy: never`, image digests, internal-only default network, supervisor | |

Sizing documented in the compose comment: production 8 GB host `process --workers 4` in a
`4g` container (`ACCEPTANCE_PROCESS_WORKERS=4`, `ACCEPTANCE_PROCESS_MEMORY=4g`); this 3.7 GB host
`--workers 2` in `2g`. The container needs 1 GiB per worker because each is bounded to 1 GiB by
`RLIMIT_DATA` (the acquire container's 1g cgroup is at the 1 GiB threshold `bounded_worker_memory`
accepts, so it leaves the cgroup as the bound there).

## What changed and why

- **Runtime** (`scripts/stage1_acceptance_runtime.py`): commands `initialize`, `proof`,
  `acquire`, `process`, `supervise`, `ingest`, `report`, `progress`, `compact`.
  `configure_broker`, the Celery/Redis imports and `import time` are gone. `acquire()` calls
  `floatchat_workers.acquire.main(Configuration.load().acquire_slots)` and `process()` calls
  `floatchat_workers.process.main(Configuration.load().process_workers)` (sizes come from the
  environment variables above). `--stdin-key` is accepted only for `acquire` and only when live
  ingestion is enabled (`:266`); every other command refuses it before stdin is touched.
  `compact` forwards to `floatchat compact [--seconds]`.
  - `proof` no longer pings a Celery worker. It asserts the migration head
    (`MIGRATION_HEAD = "0014_gdac_source"`, was `0011_set_based_publication`), `SELECT count(*) FROM
    app.processing_ticket` is 0 (the ingestor has SELECT), and `claim_ticket("acquire")` and
    `claim_ticket("process")` both return `None`. New proof keys: `queue_ticket_rows`,
    `queue_claims_empty`. `environment` already carries `upstream_slots`/`max_active_chunks`
    (`SELECT *`). There is no queue equivalent of "a worker acknowledged a task": worker liveness
    is now checked by the wrapper (below).
  - `progress` adds `tickets: {kind: {queued, started}}` from `app.processing_ticket`.
  - A `Rejection` escaping the entry point now prints its fixed category to stderr (for example
    `acquire_slots_exceed_environment`, `invalid_owner_credential`) instead of the generic message;
    other exceptions print the old generic message.
- **Wrapper** (`scripts/stage1_acceptance.py`): `prepare` starts `acquire process supervisor`
  and, after the proof, requires all three to be running (`running_services`,
  `acceptance_worker_not_running`; recorded as `workers_running_after_proof`). This replaces the
  liveness the Celery ping gave. `inspection` expects `db minio acquire process supervisor`.
  `execute`: `up db minio`, `stop acquire` (an offline acquire would claim and fail live
  tickets), key to `live-acquire` on stdin, then `up process supervisor`; the replay phase stops
  `<project>-live-owner` and starts `acquire process`. `print_progress` shows `acquire_queued=`
  and `process_queued=` when the runtime reports them (allow-listed keys and bounded ints only).
  The owner-result JSON gains `worker_topology` and `memory_evidence`. Evidence file names are
  unchanged (`preparation.json`, `manifest.json`, `owner-worker.log`, `last-cleanup.json`,
  `reports/stage1-acceptance-{live,replay,owner-result,preparation}.json`); one new file,
  `reports/stage1-acceptance-memory.json`, holds the full sampler report.
  - **Memory sampler wired into `execute`** (`start_sampler`, `stop_sampler`): after
    `up process supervisor` the wrapper starts `scripts/stage1_memory_sampler.py` in the
    background (project, `<session>/memory.json`, `<session>/memory.stop`, `--max-seconds 87000`,
    `safe_environment()`, output discarded; best effort, a launch failure never aborts the run).
    When both phases have passed it writes the stop file, waits (terminate after 30 s), copies the
    report to `reports/stage1-acceptance-memory.json` and puts `{available, pass, samples,
    by_service}` into the owner result as `memory_evidence`. If the run ends early (interrupt,
    worker exit, incomplete run) the cleanup path does the same and records it in
    `last-cleanup.json` as `memory_evidence`. A missing or unreadable report gives
    `{"available": false}`; it never fails the run or the cleanup. Stale `memory.stop` and
    `memory.json` from an earlier attempt of the same session are removed at start.
- **Memory sampler** (`scripts/stage1_memory_sampler.py`): samples `acquire`, `live-acquire` and
  `process` containers. Each `workers` entry keeps its keys and gains `service`; the report
  gains `by_service` (per-service maxima: `memory_max`, `anon_peak_bytes`,
  `memory_peak_counter_bytes`, `oom`, `oom_kill`, `containers`, `samples`). **ADR-0042 criterion
  change** (for the ADR writer): `pass` is true only if both halves were sampled (a `process`
  container and an `acquire` or `live-acquire` one) and every container has zero `oom` and
  `oom_kill`, an anonymous peak below its own `memory.max`, and `memory.max` equal to exactly
  1 GiB for the acquire containers but only finite for `process` (2g here, 4g in production). The
  per-worker 1 GiB bound inside the process container is `RLIMIT_DATA`, which cgroup counters
  cannot see.
- **Bootstrap** (`scripts/bootstrap_db.py:35-36`): `float_metadata_cache` and `measurement_staging`
  added to `STAGE1_TABLES`, so a bootstrap re-run revokes instead of granting DML to
  `floatchat_app`.
- **Integration probe and dev** (`scripts/integration_probe.py:134`, `scripts/dev.py`): the
  `from floatchat_workers.app import app` import is removed (it would have broken every mode).
  Mode `worker` (kept, because the unowned `scripts/integration.py:168` calls `probe("worker")`;
  `queue` is an alias) now checks the queue from the API container as `floatchat_app`:
  `processing_ticket`, `float_metadata_cache`, `measurement_staging` exist, the application role
  holds no privilege on them, and `app.claim_ticket(text,text)` exists without EXECUTE for it.
  This probes the queue's presence and its isolation, not a claim: that role cannot read the
  queue (migrations 0006/0012), so the brief's `SELECT count(*) FROM app.processing_ticket` would
  raise `InsufficientPrivilege` there. `scripts/dev.py restart` is now `api web`.
- **Dev Compose** (`infra/docker-compose.dev.yml`): the Celery `worker` service is removed. No
  `acquire`/`process` service replaces it: they need an ingestion login, an
  `app.ingestion_environment` row and `INGESTION_*` variables that the Stage 0 stack does not
  have, so they would crash-loop and fail `up --wait`. `redis` and `REDIS_URL` stay (API, below).
- **Probes** (`tests/stage1/regional_capacity_probe.py`, `split_replay_probe.py`):
  `process_ticket(..., "execute")` at the four serial call sites, Controller callback
  `dispatch(authority, kind)`, `INGESTION_REDIS_URL` removed. `repository.ticket(authority)` is
  kept (default `process` ticket).
- **Makefile**: `bench` target added (`STAGE1_BENCH=1 uv run --all-packages --frozen python -m
  pytest tests/stage1/test_chunk_scale.py -q -s`); there were no Celery/Redis targets.
- Not changed: `scripts/stage1_acceptance_storage.py`, `infra/docker/api.Dockerfile` (no Celery,
  Redis or worker command in either; the image runs the checkout through the mounted
  `PYTHONPATH`, and `uv sync --frozen` follows whatever lock the integrator produces).

## Governor counters (requirement 3, second half: not implemented)

Not added. `persisted_report` exposes no governor fields: `UpstreamGovernor.snapshot()`
(`transport.py`, `observed_429`, `lowest_permits`, `restored_permits`) is in-process only and the
acquire process never prints or persists it. The report's `payload_accounting` (origin x
disposition counts) is the only persisted trace of upstream behaviour, and origin `cache` shows
metadata cache hits. If the owner wants 429 counts in the evidence, package D/E would have to log
or persist `snapshot()` periodically; the wrapper could then copy it into the owner-result JSON.

## Tests

Mandatory command (shared lock, last run after all edits):

```
cd /home/floatchat/FloatChat-perf && flock /tmp/claude-1000/perf-test.lock nice -n 19 .venv/bin/python -m pytest tests/test_compose.py tests/test_bootstrap.py tests/stage1/test_acceptance_preparation.py tests/stage1/test_worker_cli.py -m "not integration" -q -p no:cacheprovider
```

Result: 95 passed.

| Check | Result |
|---|---|
| `ruff format --check` and `ruff check` on the 12 owned Python files | clean |
| YAML load (`yaml.safe_load`) of the three compose files | ok |
| `py_compile` of `regional_capacity_probe.py`, `split_replay_probe.py`, `integration_probe.py` | compiled (never executed) |
| Static check that every `${VAR}` in both acceptance compose files is written by `prepare` and every key it writes is used | no missing or unused variables |
| Mutation check (runtime allows `--stdin-key` for `process`) | the new test failed, then the file was restored |
| `tests/stage1/test_byte_identity.py` (mandatory per section 6 rule 2; H touches nothing in core) | 6 passed |
| Not run | docker, integration tests, `mypy` (scripts are outside the mypy `files`; the original sampler already has strict-mode errors) |

New or rewritten tests (`tests/stage1/test_acceptance_preparation.py` unless noted):
- compose: topology and sizing of `acquire`/`process`, no Redis/Celery text or variables, volumes
  `{postgres_data, minio_data}`, no `networks`/ports on base services, `--stdin-key` appears in
  exactly one command (the live overlay's) and that service extends `acquire`, session `TOPOLOGY`
  equals the compose defaults, `IMAGES` has no Redis pin.
- runtime: `--stdin-key` refused for every command but `acquire` and refused while live is
  disabled, a live `acquire` reads the key from stdin only, malformed keys rejected, `acquire` and
  `process` call `floatchat_workers.acquire.main(slots)` / `process.main(workers)` with the
  configured sizes and no key in the environment, `supervise`/`compact`/`ingest` forward exact CLI
  arguments, no Celery/Redis text, `MIGRATION_HEAD` equals the newest file in
  `infra/migrations/versions`.
- orchestration: the live Popen is the only call with `live-acquire`, order live acquire -> process
  pool -> memory sampler -> live ingest -> stop live owner -> internal acquire -> replay, owner
  result written with `memory_evidence` and `worker_topology`; on interrupt, worker exit and an
  incomplete run the figures land in `last-cleanup.json` and the memory report file.
- sampler wiring: stop is best effort (no sampler, stuck sampler terminated, missing or corrupt
  report gives `{"available": false}`), start clears stale state, survives a launch failure and
  never passes a credential.
- progress: queue depth printed; unexpected ticket kinds, extra fields and negative counts are
  suppressed.
- sampler: container selection, per-container figures and `by_service`, pass with 2g and 4g process
  limits, fail on oom, wrong acquire limit, anonymous peak over the limit, and a missing half.
- `tests/test_compose.py`: dev stack has no `worker`/Celery/`floatchat_workers`; paths are
  absolute from the file location.
- `tests/test_bootstrap.py`: every `app` table created by migrations 0012 and later is in
  `STAGE1_TABLES` (this will flag the next migration that adds a table).

All wrapper tests read this repository's files through `CHECKOUT` (convention of commit 03fe835);
they pass from any checkout path.

## Remaining Celery/Redis references outside my files

- `workers/pyproject.toml:5` (`celery[redis]==5.6.2`), `pyproject.toml:35` (`celery.*` mypy
  override), `uv.lock`: integrator, `uv lock`.
- `packages/core/src/floatchat_core/config.py:9` (`redis_url: SecretStr`, required),
  `apps/api/src/floatchat_api/health.py:9,69-91` (Redis readiness check), `apps/api/pyproject.toml:7`
  (`redis==6.4.0`), `.env.example:9` (`REDIS_URL`): the Stage 0 API still requires Redis. This is
  why the dev Compose keeps `redis`/`REDIS_URL`, and why `scripts/integration.py:151`
  (`for dependency in ["db", "redis", "minio"]` outage test) still holds.
- `scripts/integration.py:168` `probe("worker")` still works (alias kept); rename to `probe("queue")`
  whenever convenient.
- `scripts/stage1_verify.py:435,770,804` (descriptive text about Celery/Beat/Redis evidence).
- `packages/core/src/floatchat_core/ingestion/landing.py:3` (docstring), `tests/stage1/processor_probe.py:65`
  (`INGESTION_REDIS_URL`, harmless: `Configuration` ignores it; also its `process_ticket` calls need
  `"execute"` per D.md item 4), `tests/stage1/capacity_probe.py`.
- Documents (package I): `docs/stage1-contract.md`, `DECISIONS.md`, `README.md`, `PROGRESS.md`,
  `FLOATCHAT_PRD_v2.md`, `FLOATCHAT_BUILD_PROMPTS.md`, `docs/stage1-acceptance-preparation.md`
  (describes the worker/Redis topology and `live-worker`), `reports/stage1-live-memory-*.json`
  (historical `live-worker` labels, no change needed).

## Open items for the integrator

1. **Redis cannot disappear from the dev stack until the API drops it.** Removing `redis` or
   `REDIS_URL` from `infra/docker-compose.dev.yml` breaks `Settings()` (required `redis_url`) and
   `/v1/health/ready`. If the owner wants Redis gone repo-wide, the work is in `config.py`,
   `health.py`, `apps/api/pyproject.toml`, `.env.example`, `scripts/integration.py`, and this
   package's dev Compose/`tests/test_compose.py` (not in H's scope).
2. **Pre-existing grant gap, not fixed here:** `replay_chunk_source` (migration 0007, revoked from
   `floatchat_app`) is missing from `STAGE1_TABLES`, so a bootstrap re-run grants the application
   role DML on it. One line in `scripts/bootstrap_db.py`; the new bootstrap test deliberately only
   covers migrations 0012+.
3. **Migration head is hard-coded** (`MIGRATION_HEAD = "0014_gdac_source"`). A test fails if a
   newer migration lands without updating it. The acceptance `proof` is the only consumer.
4. **`upstream_slots` ceiling.** `ACCEPTANCE_ACQUIRE_SLOTS` above 4 makes `acquire` exit with
   `acquire_slots_exceed_environment` (now printed to stderr) because `initialize()` inserts the
   environment row with the column default. Raise it in `initialize()` if a larger acquire is wanted.
5. **`prepare` has no flags for the production sizing.** The 8 GB values are documented in the
   compose comment and can be applied by changing `TOPOLOGY` in `scripts/stage1_acceptance.py`
   (sizing is hash-bound in the environment file). Add `--process-workers`/`--process-memory`
   flags if the owner wants them.
6. **Nothing watches the `process` container during `execute`.** `progress_update` checks the live
   acquire only. If the container dies, chunks stall until the run deadline (the process pool
   survives a killed child; only a killed parent stops it).
7. **The sampler needs the host's cgroup v2 `docker` tree.** It reads
   `/sys/fs/cgroup/docker/<id>/` (cgroupfs driver), as before. On a host with the systemd driver
   it samples nothing, `memory_evidence` reports `pass: false` with zero samples, and the run
   itself is unaffected. First use of the wiring is untested against docker.
8. **First live use of the new topology is untested.** Nothing here ran docker: the compose files
   were checked statically (YAML, variable plumbing, tests) only. Watch the first `prepare` for
   `acceptance_worker_not_running`, `PYTHONPATH` coverage of pyarrow/netCDF4 in the mounted
   checkout's `.venv`, and spawn-context children re-importing the runtime script
   (`scripts/stage1_acceptance_runtime.py` as `__mp_main__`; its top-level imports are
   side-effect free).
9. **Dev `worker` service decision.** If the owner wants a dev ingestion worker pair it needs an
   ingestion login, environment row and `INGESTION_*` variables in `.env.example`; not done.
