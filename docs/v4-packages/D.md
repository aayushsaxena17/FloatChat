# Package D report: PostgreSQL work queue, controller, worker pools, CLI, migration 0012

Celery and Redis are gone from every file this package owns. A chunk's ticket is a row in
`app.processing_ticket`; one acquire process (N threads) lands chunks, a pool of M single-use
processes publishes them.

## Read this first (integrator, blocking and design-relevant)

1. **`Repository.ticket` needs the kind argument (package F's file).** `queue.issue()`,
   `cli.dispatch()` and the acquire to process hand-over all call `repository.ticket(authority,
   kind)`. Until the one-line change below is applied, `dispatch` raises `TypeError`, which the
   controller turns into `worker_dispatch_unavailable`, and the hand-over silently falls back to
   lease expiry (it prints `process_handover_unavailable`).

   `packages/core/src/floatchat_core/ingestion/repository.py`, method `ticket` (lines 233-236
   at HEAD, 259-262 in the current worktree):
   ```python
   def ticket(self, authority: Authority, kind: str = "process") -> uuid.UUID:
       with self.transaction() as cursor:
           cursor.execute(
               "SELECT app.processing_ticket(%s,%s,%s,%s,%s) AS id", (*authority.arguments, kind)
           )
           return cursor.fetchone()["id"]  # type: ignore[no-any-return]
   ```
   The SQL function keeps a defaulted fifth parameter, so a four-argument call still works.
2. **Migration 0014 (package G) overwrites two things this migration adds.** 0012 now accepts
   attempt origin `cache` (per package E's blocking request) in the `ingestion_attempt` origin
   CHECK and in `app.reserve_recorded_attempt`. 0014 recreates both with
   `('http','captured','replay','gdac')` and `('captured','replay','gdac')`, which would drop
   `cache` again. In `infra/migrations/versions/0014_gdac_source.sql` change line 49 to
   `CHECK (origin IN ('http','captured','replay','cache','gdac'))` and line 60 to
   `IF p_origin NOT IN ('captured','replay','cache','gdac') THEN ...`. The chain itself holds:
   0014's opening DO block drops the `ingestion_attempt` CHECK by definition
   (`LIKE '%captured%'`, expecting exactly one) and the CHECK 0012 recreates still contains
   `captured` and is the only one on that table that does, so 0014 finds it and its
   `ADD CONSTRAINT ingestion_attempt_origin_check` does not collide.
3. **Security: `scripts/bootstrap_db.py` would grant the application role DML on the new cache
   table.** `STAGE1_TABLES` (line 10) lists the tables the bootstrap revokes from `floatchat_app`;
   every other `app` table gets `SELECT, INSERT, UPDATE, DELETE` (lines 121-135). Add
   `"float_metadata_cache",` after `"processing_ticket",` (line 34). Migration 0012 itself
   revokes it, and `tests/stage1/test_queue_sql.py` proves the revocation, but a bootstrap
   re-run would undo it. (Package F's 0013 tables, for example `measurement_staging`, need the
   same entry.)
4. **Probes and scripts that call `process_ticket(run, chunk, ticket)` on a planned chunk now
   need `"execute"`.** The default kind is `process`, which refuses an unlanded chunk
   (`ticket_phase_mismatch`, returned as `recovery_required`, no worker started). `execute` is the
   serial `Processor.execute()` path (land then process) that existed before; it is not part of
   the queue. Files (all outside package D):
   - `tests/stage1/processor_probe.py:162-163`
   - `tests/stage1/capacity_probe.py:125` and `:212`
   - `tests/stage1/regional_capacity_probe.py:303`, `:313`, `:341`
   - `tests/stage1/split_replay_probe.py:142` and `:204` (pass `"execute"`). Its Controller
     callback at `:202`, `def dispatch(authority)`, must take `(authority, kind)`; keep
     `repository.ticket(authority)` at `:203` (the SQL function only knows `acquire` and
     `process`; the default `process` ticket is fine for the serial `execute` path).

## What changed and why

### Queue design decisions (for the ADR writer)
- **Phase hand-over under one claim.** Contract section 8.1 says normal phase progress consumes
  no extra claim. The brief's literal reading (the controller issues the `process` ticket for a
  `landed` chunk only after the lease expires) would leave a landed chunk idle for up to 10
  minutes and spend one of the four `processing_claims` per chunk on every healthy chunk. Instead,
  after `Processor.land()` returns `landed`, `process_ticket(kind="acquire")` creates the `process`
  ticket under the same epoch and fence (`ingestion.hand_over`). To allow it,
  `processing_ticket` is now unique on `(chunk_id, fence, kind)`. The controller still issues
  tickets by phase for every recovery claim (expired lease): `acquire` for planned/fetching,
  `process` for landed/validating/publishing. If the hand-over fails or the acquire worker dies
  between `landed` and the hand-over, the lease lapses and the controller re-queues the chunk
  under a new claim. Happy path: 1 claim per chunk (as in v3).
- **Eligibility mirrors `assert_authority`.** `app.claim_ticket` only returns a ticket that
  `app.start_worker` would accept: matching epoch and fence, live chunk lease and controller
  lease, run open, not cancelled, before the work deadline, chunk not terminal. Without this, a
  ticket whose chunk was re-claimed would be claimed forever (`start_worker` raises, `started`
  never flips).
- **Claimed but never started.** A claim whose worker vanished before `start_worker` is handed
  out again after two minutes. `started` still admits exactly one executor, so a double claim
  cannot execute twice (`duplicate_delivery`). The two minutes is a chosen value without a
  measurement behind it.
- **Lock order.** `claim_ticket` locks only the ticket row (`FOR UPDATE OF pt SKIP LOCKED`) and
  never waits on a run or chunk lock, so it cannot invert `start_worker`'s run, chunk, ticket
  order.
- **Process pool is not `multiprocessing.Pool`.** `process.py` runs M single-use spawn-context
  processes managed by hand (the semantics of `Pool(M, maxtasksperchild=1)`). `Pool` never
  completes a task whose worker was killed, which leaks a slot for good on an OOM kill. The
  parent claims the ticket (deviation from "each child claims": an idle queue would otherwise
  cost one interpreter start per poll), a killed child frees its slot at once and prints
  `worker_lost`, and the chunk lease expires to recovery.
- **Acquire threads share only the governor** (package E's request). Each ticket builds its own
  work `Repository`, budget `Repository`, source (`RequestOwner(..., governor=, slot=<1..N>)`) and
  `Processor`; each polling thread owns its claim connection
  (`test_acquire_threads_share_only_the_governor`). `UpstreamGovernor` hands out the lowest free
  slot itself; `process_ticket` passes `slot` only together with a governor, so without one
  every thread uses RequestOwner's default slot 1 (requests serialize). `acquire.make_governor`
  looks the class up with `getattr`, so the module imports even without it; with the governor
  present now, nothing is skipped.
- **Slots bound by the environment.** `acquire --slots N` is rejected with
  `acquire_slots_exceed_environment` when N exceeds `ingestion_environment.upstream_slots`
  (default 4, 1..16), so the column is the declared ceiling for all acquire processes.
- **Memory bound.** `bounded_worker_memory(limit)` accepts a cgroup `memory.max` of at most
  1 GiB, otherwise lowers the soft `RLIMIT_DATA` to `INGESTION_WORKER_MEMORY_BYTES` (default
  1 GiB). It never uses `RLIMIT_AS`, never raises an existing lower limit, and is idempotent per
  process. The design document's section 4.4 says "RLIMIT_AS"; section 2 and the brief say
  `RLIMIT_DATA`. I followed `RLIMIT_DATA`; section 4.4 is the inconsistent text. One acquire
  process shares a single data limit across its N threads.
- **Configured memory can only be reduced.** Contract section 9 says configuration may reduce
  but not raise the 1 GiB worker bound, so `INGESTION_WORKER_MEMORY_BYTES` is accepted only in
  128 MiB to 1 GiB (otherwise `invalid_ingestion_configuration`). If the owner wants more per
  worker, change the upper bound in `Configuration.load` together with an ADR.
- **`schedule` replaces Celery Beat.** `floatchat schedule` runs one UTC-daily admission
  (`scheduled_admission`), serialized by advisory lock `(164993423, 2)`, for a cron or systemd
  timer. Outcomes and exit codes: `live_ingestion_disabled` 0, `created`/`existing`/`recover`/
  `overlap_skip` 0 (an overlap is a durable admission event, not a failed unit),
  `schedule_already_running` 0 (a peer holds the lock), `acceptance_schedule_disabled` 2,
  `scheduling_failed_no_sensitive_diagnostics` 5. The category
  `beat_scheduler_already_running` is replaced by `schedule_already_running`, and the
  acceptance refusal moved from a raised `Rejection` to a printed outcome.

### Files
- `infra/migrations/versions/0012_work_queue.sql` (SQL summary below).
- `packages/core/src/floatchat_core/ingestion/states.py:11-13` `ACQUIRE_STATES`,
  `PROCESS_STATES`, `TICKET_KINDS`; `:32` `ticket_kind(state)` (shared by controller, tests).
- `packages/core/src/floatchat_core/ingestion/controller.py`: `ControlStore.environment`
  (`:25`), `dispatch: Callable[[Authority, str], None]`, active bound from
  `environment(row["environment_id"])["max_active_chunks"]` (`:87`, replaces the constant 2),
  ticket kind by phase before the claim (`:109`) and `self.dispatch(authority, kind)` (`:115`).
  Claim budget (4), fencing, epochs and finalization are untouched. The real `Repository`
  already has `environment()`, so no new `Repository` method is needed for the bound.
- `workers/src/floatchat_workers/queue.py` (new): `claim`, `issue`, `ticket_arguments`,
  `worker_name`, `poll` (1 s idle wait, doubling backoff to 30 s on `database_failure` or
  `database_deadline`, other rejections propagate, `ready` gate, interruptible by an `Event`).
- `workers/src/floatchat_workers/acquire.py` (new): `main(slots)`, `work`, `make_governor`.
- `workers/src/floatchat_workers/process.py` (new): `main(workers)`, `run_ticket`, `reap`.
- `workers/src/floatchat_workers/ingestion.py`: `Configuration` (no broker fields; adds
  `acquire_slots`, `process_workers`, `worker_memory_bytes`; `queue` stays: it is the
  `queue_namespace` identity check of the environment marker), `bounded_worker_memory`,
  `hand_over`, `process_ticket(run, chunk, ticket, kind="process", *, governor=None, slot=1)`.
  Kinds: `acquire` runs `land()` and hands over, `process` runs `process()` with
  `require_existing=True` sources, `execute` runs `Processor.execute()`. Terminal recognition,
  `duplicate_delivery`, the no-secrets exception boundary and the category set
  (`publication_fenced`, `run_fenced`, `work_deadline` stay recoverable) are unchanged.
  `Processor` is only called through `land()`, `process()` and `execute()`.
- `workers/src/floatchat_workers/cli.py`: `dispatch(authority, kind)` (creating the ticket row is
  the dispatch), `scheduled_admission` + `schedule_exit`, commands `acquire --slots`,
  `process --workers`, `supervise`, `schedule`, `compact [--seconds]`, `ingest` (unchanged
  arguments), `report`, `status`, `cancel`. `compact` calls package F's
  `Repository.compact(environment, logical_key, store, deadline)` for every slot that has
  `kind='part'` rows in `app.committed_active_partitions`, within one time budget (default
  3600 s, 1..43200), and prints `{"compacted","unchanged","retry_later","not_attempted"}`;
  without `Repository.compact` it prints `compact_unavailable` and exits 2. **This goes
  beyond the stub the brief asked for**: it enumerates the slots itself with one SQL query
  against the 0013 view (not verifiable here). If package F wants to own the enumeration,
  replace `cli.compact_slots` with a single `Repository` call; the CLI contract (`compact`,
  `compact_unavailable` exit 2) stays.
- Deleted: `workers/src/floatchat_workers/app.py` (Celery app, `smoke` task) and
  `workers/src/floatchat_workers/scheduler.py` (Beat). `__init__.py` docstring updated.
- Tests (below).

### SQL summary (migration 0012)
- `app.processing_ticket`: `kind` (default `process`, CHECK acquire|process), `claimed_by`
  (1..128 bytes), `claimed_at` (both set or both null), `created_at` (FIFO order); unique key
  changed from `(chunk_id, fence)` to `(chunk_id, fence, kind)`; partial index
  `processing_ticket_queue (kind, created_at, id) WHERE NOT started`.
- `app.ingestion_environment`: `max_active_chunks` (default 8, 1..64), `upstream_slots`
  (default 4, 1..16).
- `app.processing_ticket(run, chunk, epoch, fence, kind DEFAULT 'process')`: the four-argument
  function is dropped first (a defaulted fifth parameter would make a four-argument call
  ambiguous). Still asserts the fenced claim; idempotent per `(chunk, fence, kind)`.
- `app.claim_ticket(kind, worker) RETURNS app.processing_ticket`: SKIP LOCKED, oldest first,
  eligibility and re-claim rules above; an empty queue returns a row of NULLs, which
  `Repository.claim_ticket` already maps to `None`.
- `app.claim_chunk`: `CREATE OR REPLACE`, identical to 0003 except the concurrency bound is the
  environment's `max_active_chunks` (the error category `environment_concurrency_limit`, the
  claim budget of 4 and the fencing are unchanged).
- `app.float_metadata_cache(environment_id, pointer, raw_manifest_id NOT NULL, run_id NOT NULL,
  retrieved_at NOT NULL, PRIMARY KEY (environment_id, pointer))` with RESTRICT foreign keys to
  environment, raw manifest and run (the brief named only the manifest FK; the other two follow
  the table pattern of 0002); `app.metadata_cache_put(uuid, text, uuid, uuid, timestamptz)`
  upserts but only forward in time (`retrieved_at` never decreases) and refuses a manifest that is
  not this run's in this environment (`invalid_metadata_cache_entry`).
- Attempt origin `cache` (package E): the origin CHECK on `app.ingestion_attempt` (found by
  definition, then recreated as `ingestion_attempt_origin_check` allowing
  http, captured, replay, cache) and `app.reserve_recorded_attempt` with the 0006 body accepting
  `cache`.
- Grants follow 0006: all new functions `REVOKE ... FROM PUBLIC`, `GRANT EXECUTE ... TO
  floatchat_ingestor`; the cache table `REVOKE ALL FROM PUBLIC, floatchat_app`, `GRANT SELECT TO
  floatchat_ingestor`. All functions are SECURITY DEFINER with `search_path=pg_catalog,app`.
- **The SQL was not executed**: there is no PostgreSQL on this host and Docker was off limits.
  It was reviewed by hand against 0003/0006 and covered by the integration tests below, which
  have not run.

## Tests

Mandatory command, run in the worktree through the shared lock:

```
cd /home/floatchat/FloatChat-perf && flock /tmp/claude-1000/perf-test.lock nice -n 19 \
  .venv/bin/python -m pytest tests/stage1/test_controller.py tests/stage1/test_broker.py \
  tests/stage1/test_worker_cli.py tests/test_worker.py tests/stage1/test_byte_identity.py \
  -m "not integration" -q -p no:cacheprovider
```
Result (last full run): see "Results" at the end of this file.

New or rewritten:
- `tests/stage1/test_controller.py`: fakes take `dispatch(authority, kind)` and
  `environment()`; bound = environment `max_active_chunks` (1, 2, 8), landed chunks count against
  it, kind by phase (new claim and recovery), `ticket_kind` for terminal/unknown phases.
- `tests/stage1/test_broker.py`: queue semantics with an in-memory stand-in for the atomic
  claim: each ticket claimed exactly once under 12 competing threads, kind routing, locked rows
  skipped, unknown kinds refused before the database, `issue`, `poll` (1 s idle, ready gate,
  backoff 2/4/8 and cap 30 s, reconnect, non-transient rejection propagates, handler errors not
  swallowed, prompt stop), acquire (governor with and without `UpstreamGovernor`, slot bounds,
  environment ceiling, one thread per slot sharing one governor, dying thread fails the
  process), process pool (never more than M children, refill on exit, killed child =
  `worker_lost`, spawn context, claims nothing when full). The `@pytest.mark.integration` test
  is rewritten to drive real acquire/process/supervise/schedule processes (not run).
- `tests/test_worker.py`: `process_ticket` routing (acquire lands and hands over under one
  claim; process publishes from existing landings only; execute is serial), hand-over only after
  `landed`, failed hand-over leaves the result, lost acknowledgement recognized for every kind
  and terminal state before ticket/memory/source, duplicate delivery executes once, unlanded
  chunk refused for `process`, unknown kind, wrong run, redacted failures, fencing categories,
  governor/slot only reach a live acquire source, threads share only the governor,
  `Configuration` (no broker, defaults, ranges, repr without credentials), memory bound
  (cgroup, `RLIMIT_DATA`, never `RLIMIT_AS`, idempotent, failure).
- `tests/stage1/test_worker_cli.py`: no app/scheduler modules and no removed names in
  `workers/src`; `dispatch` writes the ticket of its kind and sends nothing; `supervise` uses
  it; `schedule` (disabled, lock order, peer holds lock, acceptance refusal, overlap, sanitized
  failure and unlock); `acquire`/`process` take sizes from arguments or configuration and open no
  command connection; `compact` (unavailable, per-slot merge, time budget, real faults, bound);
  parser.
- `tests/stage1/test_queue_sql.py` (new, integration, NOT run): schema/defaults/checks, one
  `processing_ticket` form, fenced creation, claim once, empty queue, routing by kind and
  hand-over under one fence with no extra claim, `start_worker` removes from the queue,
  two-minute re-claim, no claim of an invalid ticket (7 invalidations), oldest first, SKIP LOCKED
  against a real second session, `max_active_chunks` 1/2/3 and the default 8, claim budget and
  `claim_denied` preserved, attempt origin `cache`, cache upsert forward-only and refusals,
  restrictive foreign keys, ingestor/application privileges.
- `tests/stage1/broker_fault_app.py`, `broker_probe.py`: rewritten for the queue, only compiled
  and linted (never executed). The fault app is now an entry point (`main`) that wraps the real
  CLI; pool children import `broker_fault_app.run_ticket`, so they install the same barriers.
  The probe asserts what the queue adds: a recovery claim is exactly +1 (the acquire to process
  hand-over costs none), recovery tickets are queued by phase, a started ticket is never
  claimed again, redelivery of a completed ticket is recognized, the environment bound caps
  active chunks, and `schedule` obeys the advisory lock.

Other checks:
- `ruff format --check` and `ruff check` on every file listed under "Files" and the test files:
  clean.
- `flock /tmp/claude-1000/perf-test.lock .venv/bin/mypy workers/src
  packages/core/src/floatchat_core/ingestion/controller.py`: success (also with `states.py`).
- Midway, package F's `workflow.py` was briefly unimportable in the shared worktree; I ran the
  same suite against a scratch copy (HEAD for files I do not own, my files on top):
  149 passed. The final run in the live worktree is recorded below.

## Remaining references to Celery or Redis outside package D (integrator)

`grep -rIn -i celery` (excluding reports, legacy, docs, lock files):
- `workers/pyproject.toml:5` `dependencies = ["floatchat-core", "celery[redis]==5.6.2"]`: drop
  celery (then `uv lock`); `[project.scripts] floatchat = "floatchat_workers.cli:main"` stays.
- `pyproject.toml:35` mypy override lists `celery.*`: remove it.
- `infra/docker-compose.dev.yml:84` (worker `command: [celery, -A, floatchat_workers.app:app,
  ...]`) and `:88` (healthcheck `celery ... inspect ping`): replace with `floatchat acquire`
  and `floatchat process` services (no import of `floatchat_workers.app` is possible any more).
- `infra/docker-compose.acceptance.yml:19` `INGESTION_REDIS_URL`; the Redis service and
  `ACCEPTANCE_REDIS_PREFIX` plumbing (package H).
- `scripts/stage1_acceptance_runtime.py:26` imports `floatchat_workers.app` and `:142` uses
  `app.send_task`, `redis`/`configure_broker` around it; `scripts/integration_probe.py:11,136`
  imports `app` and sends `floatchat.smoke`; `scripts/stage1_verify.py:435,770` describe the
  Celery/Beat evidence in text; `scripts/stage1_acceptance.py:34,292,361-407,498` Redis service
  pins (package H).
- `tests/stage1/processor_probe.py:65` and `tests/stage1/regional_capacity_probe.py:125` set
  `INGESTION_REDIS_URL` (harmless now: `Configuration` ignores it; delete the line);
  `tests/stage1/test_acceptance_preparation.py:74` asserts it in the acceptance compose.
- `packages/core/src/floatchat_core/ingestion/landing.py:3` docstring mentions Celery.
- `apps/api` (`health.py`, `config.py`, `pyproject.toml`) keeps a Redis health check: Redis is
  still a Stage 0 service for the API; not a worker dependency any more.
- Documents (package I): `docs/stage1-contract.md` lines 720, 839, 870, 887, 1118, 1130, 1214,
  `DECISIONS.md` 207, 217, 232, 385, `README.md` 9, 92, `PROGRESS.md`.

Also from package D's grep for `INGESTION_REDIS_URL` and `floatchat_workers.app`: only the files
above remain.

## ADR inputs (contract clauses touched)
- Section 8.1 (phase progress consumes no claim): kept, now by the same-fence hand-over.
- Section 9 "At most 2 active chunk workers per environment": now
  `ingestion_environment.max_active_chunks` (default 8, 1..64), enforced in
  `app.claim_chunk` and mirrored by the controller. Chunks in flight include landed chunks that
  wait for the process pool.
- Section 9 memory and ADR-0042: cgroup `memory.max` of at most 1 GiB OR `RLIMIT_DATA`;
  configuration may only reduce it.
- Section 9/10 "Celery carries only opaque IDs", "one Celery Beat scheduler per environment":
  opaque IDs in a PostgreSQL ticket; Beat replaced by a timer-driven `schedule` command under
  the same advisory lock.
- New policy values chosen without measurement: re-claim after 2 minutes, queue poll 1 s,
  backoff cap 30 s, default `compact` budget 3600 s.

## Open items and risks
1. **Lease while a claimed chunk waits for a worker.** Nothing heartbeats a chunk between
   `claim_chunk` (or the acquire worker's last pulse) and the next worker's first pulse. That
   covers both queues: chunks claimed but waiting for an *acquire* thread (with the default
   `max_active_chunks` 8 and `--slots 4`, up to four are always waiting; under governor
   back-off after a 429 the wait grows by the 60 s pauses) and landed chunks waiting for a
   *process* worker. If the wait outlasts the remaining lease (up to 10 minutes), the
   controller re-claims the chunk (one claim, new fence; the waiting ticket becomes inert)
   and issues a fresh ticket of the phase's kind; four such claims end the run with
   `recovery_budget_exhausted`. A remedy, if measurement shows it matters: a small SQL
   function that extends the lease of chunks whose current-fence ticket is still unstarted,
   called from the controller tick. The same exposure existed with Celery prefetch; nothing
   here makes it worse.
2. **Dead tickets are not purged.** A ticket that lost its fence stays in the table with
   `started = false` (inert, never handed out, but present in the partial index). Bounded by
   claims (4 per chunk, 16,384 chunks per run). A retention job could mark them.
3. **`transport.fetch` and threads.** Package E has made fetch thread-safe and added
   `UpstreamGovernor`; the acquire threads were exercised only through fakes (no live HTTP).
4. **Garbage-collector policy.** `docs/v4-packages/B.md` item 3 left a possible `gc.disable()`
   to the worker process. Not applied: it trades mapper time for memory under the 1 GiB bound
   and has no measurement here. The place is `process.run_ticket` (single-use child); measure
   with `scripts/stage1_perf_profile.py` before adding it.
5. **`compact` assumes `app.committed_active_partitions` has `environment_id`, `logical_key`
   and `kind`** (0013, package F's view); `Repository.compact` reads the same columns.
6. **SQL error categories.** `invalid_ticket_kind`, `invalid_ticket_worker` and
   `invalid_metadata_cache_entry` are not in `SAFE_DATABASE_CATEGORIES` (repository.py) and
   surface as `database_failure` (the Python layer validates kinds first, so only
   `invalid_metadata_cache_entry` is reachable). Add them if the distinction matters.
7. **`process_ticket(kind="execute")`** is an addition to the interface in section 4.4.
8. **`broker_probe.py` (the real-process queue proof) has never run**; expect small fixes on
   its first execution (timing around the acquire restart, the `-c` launcher, and the
   `max_active_chunks=2` case).

## Results

Final run in the live worktree (after all edits):

| Check | Result |
|---|---|
| `pytest tests/stage1/test_controller.py tests/stage1/test_broker.py tests/stage1/test_worker_cli.py tests/test_worker.py tests/stage1/test_byte_identity.py -m "not integration" -q -p no:cacheprovider` (mandatory form, shared lock) | 150 passed, 1 deselected (the rewritten broker integration test) |
| `tests/stage1/test_queue_sql.py -m "not integration"` | 1 passed (fragment guard); 29 integration tests deselected, NOT run |
| `ruff format --check` and `ruff check` on all 15 owned source/test files | clean |
| `mypy workers/src packages/core/src/floatchat_core/ingestion/controller.py` (strict) | no issues in 7 source files |
| `py_compile` of `broker_probe.py`, `broker_fault_app.py` | compiled (never executed) |
| Not run: integration tests, Docker, live capture, anything touching PostgreSQL | per the hard rules |
