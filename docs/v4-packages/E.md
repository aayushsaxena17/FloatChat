# Package E report: threaded transport, governor, metadata cache, validate-once landing

Worktree `/home/floatchat/FloatChat-perf`, base `272508b`. Owned files only; nothing committed.
Revised after the integrator's decision on the cache predicate and the fixture-path cache.

## Open items for the integrator (read first)

1. **BLOCKING: migration 0012 must accept origin `cache`.** `0006_ingestion_runtime.sql` has
   `CHECK(origin IN ('http','captured','replay'))` on `app.ingestion_attempt` and
   `app.reserve_recorded_attempt` raises `invalid_recorded_origin` for anything else, so the
   first real cache hit fails against a live database (the fake-repository tests cannot see
   it). This also holds for the v3 serial live path (`RequestOwner` without a governor): it
   consults the cache too. 0012 (package D) needs:
   ```sql
   ALTER TABLE app.ingestion_attempt DROP CONSTRAINT ingestion_attempt_origin_check;
   ALTER TABLE app.ingestion_attempt ADD CONSTRAINT ingestion_attempt_origin_check
     CHECK (origin IN ('http','captured','replay','cache'));
   -- CREATE OR REPLACE app.reserve_recorded_attempt(...) with the 0006 body and the line
   --   IF p_origin NOT IN ('captured','replay','cache') THEN RAISE EXCEPTION 'invalid_recorded_origin'; END IF;
   ```
   (The inline column CHECK of 0006 gets the name `ingestion_attempt_origin_check`.)
2. **Cache predicate (decided by the integrator, implemented).** `landing.cache_fresh(
   retrieved_at, anchor)` is `retrieved_at >= anchor - 30 days`, lower bound only, where
   `anchor` is the run row's `created_at_actual_utc` (exists: `0002_ingestion_foundation.sql`
   line 28, `DEFAULT clock_timestamp()`), read once per `MetadataCache`. The first version
   (`T - 30 d <= retrieved_at <= T`) almost never hit: chunks are fetched after T, and an
   acceptance run's T (2025-04-01) lies a year before any live fetch. ADR rationale: reuse
   inside a run (the same float in many chunks) is the main saving; the reference time T
   governs scientific eligibility, not evidence freshness; 30 days is a policy value chosen
   pending measurement. No upper bound: entries landed by this run's own earlier chunks, or by
   a concurrent run, are newer than the anchor and must hit. Tests pin it
   (`test_E04_cache_freshness_is_a_lower_bound_*`, `test_E04_entries_from_earlier_runs_*`,
   `test_E04_the_reference_time_does_not_bound_evidence_freshness`).
3. **`operation_deadline` can no longer interrupt a blocked call** (package C, `minio.py`).
   `minio.py` already sets `Config(connect_timeout=10, read_timeout=20,
   retries={"total_max_attempts": 1})`, so each socket operation is bounded, but the whole
   120 s object bound is now only checked when the `with` exits normally. Replacement for
   `MinioStore.read` (HEAD lines 89-110; same shape for any other loop over a body):
   ```python
           bound = min(deadline, time.monotonic() + 120)
           try:
               with operation_deadline(bound):
                   response = self.client.get_object(Bucket=self.bucket, Key=key)
                   ...
                   while True:
                       if time.monotonic() >= bound:
                           raise Rejection("io_deadline")
                       part = body.read(min(65536, max_bytes - len(result) + 1))
   ```
   so a slow download stops between 64 KiB parts. `_put` stays bounded per socket operation
   only (botocore timeouts), not in total.
4. `Repository` is not thread-safe (one psycopg connection). Each acquire thread needs its own
   `Repository`, `RequestOwner` and budget repository; only `UpstreamGovernor` and the
   process-wide TLS context are shared. `workers/.../ingestion.py` already passes
   `governor=`/`slot=` the way `RequestOwner` expects (the governor's returned slot wins; `slot`
   is only used without a governor).
5. `Repository.metadata_cache_get` returns no `m.sanitization`, so a hit manifest carries a
   synthesized `sanitization` (`version`, `input_origin: "cache"`, `cache_manifest`,
   `validation.inherited_from`). If the original evidence should be copied instead, add
   `m.sanitization` to that SELECT (package F) and use it in `RequestOwner.cached`.
6. Not done: in-process single-flight for one pointer (two threads missing the same float
   fetch it twice; `app.metadata_cache_put` only moves forward in time, so it is harmless).
   HTTPS connection reuse (optional, skipped). Process-level slot spreading: two acquire
   processes both start at slot 1 and wait for the advisory lock instead of trying slot 2..N
   (correct, not optimal).
7. Residual timing gaps (no signals): `getaddrinfo` has no timeout, so a DNS overrun is
   rejected as `io_deadline` only after it returns (OS resolver timeouts bound it); a single
   `response.read(65536)` that dribbles bytes inside the idle timeout cannot be interrupted
   until it returns, so the attempt bound is exact between reads, not inside one.
8. `request_owner_probe.verify_metadata_cache` (real tables, chained from
   `verify_http_path`) was written but **not executed** (needs the database, MinIO and item
   1). Expect to run it with `processor_probe.py`. Its fetch is stamped `datetime.now(UTC)`,
   so it is fresh against the run's actual creation time whatever the run's T.
9. Test fakes outside package E: `grep -rln "def recorded_reserve\|def verified_landing"
   tests/ scripts/` finds only my files and `tests/stage1/broker_fault_app.py`, which wraps the
   real `Repository.recorded_reserve`; no D/F/J fake needs `run()`/`metadata_cache_get()`
   stubs. Real-`Repository` probes need the 0012 `float_metadata_cache` table once a live
   (`RequestOwner`) metadata request runs; fixture and replay runs no longer touch the cache.
10. `validate_raw` per landing depends on package C: with E's modules on the HEAD
    `objects.py` it is 3 per landing; the worktree tree (C's `objects.py`, hash differs from
    baseline) shows 1. Package E removed the redundant decode on every reload (0).

## What changed

### `packages/core/src/floatchat_core/ingestion/transport.py`
- No `signal` import. `CONNECT_BUDGET=10`, `IDLE_READ=110`, `ATTEMPT_BOUND=120` (:29-31);
  `operation_deadline` (:74) raises `io_deadline` on entry and on normal exit, never replaces a
  body exception, nests freely. `unsupported_worker_runtime` and `overlapping_io_deadline` are
  gone (nothing referenced them).
- `fetch` (:387) keeps its signature and behaviour. DNS+connect+TLS share one 10 s budget
  (`PinnedConnection(..., until=)` shrinks the socket timeout before the handshake). Before
  every body read `tick()` re-arms `settimeout(min(110, left))`; after each read (once its
  bytes are accounted) it raises `io_deadline` if the 120 s (or run) bound passed;
  `read_body`/`empty_receipt` take an optional `tick`. Error mapping: connect-phase timeout or
  any error after the bound -> `io_deadline`; idle-read timeout and other socket errors ->
  `upstream_transport_failure` (as in ADR-0045); both retryable. `empty_receipt` lets
  `io_deadline` through instead of turning it into a permanent HTTP 404.
- `tls_context()` (:91): one process-wide `ssl.SSLContext` instead of one per connection.
- `UpstreamGovernor(permits, *, pause=60, restore_after=20)` (:180): `acquire(deadline,
  on_wait=None) -> slot` (lowest free index; blocks; `upstream_slot_deadline`; `on_wait` runs
  every `pulse`=10 s so the owner can heartbeat and honour the live flag),
  `release(slot, status, retry_after=None)` (`retry_after` is an extension of the fixed
  signature; 429 halves to a floor of 1, blocks new acquires `max(Retry-After, 60)` s, resets
  the streak; any other completion, `None` included, counts toward one restored permit per 20),
  `current_permits`, `observed_429`, `restored`, `lowest`, `snapshot()` for the acceptance
  report. Each 429 halves, so a burst of in-flight 429s can go 4 -> 2 -> 1 at once.

### `packages/core/src/floatchat_core/ingestion/landing.py`
- `RequestOwner(..., governor=None, slot=1)` (:147). With a governor it acquires a permit,
  takes `upstream_slot(authority, deadline, slot_index)`, reserves, calls the transport, then
  leaves the lock and releases the permit (`release(slot, status, retry-after hint)`)
  **before** any retry delay and before sanitize/publish. Sanitize, `publish_verified` and
  `finish_attempt` now run after the lock instead of inside it (the permit/lock cover the
  request, not local work; otherwise slots would collide). Without a governor: slot
  `self.slot` (default 1).
- Reload of an existing landing no longer calls `validate_raw` (bytes/sha/versions identify a
  validated object). The `publish_verified(..., validate_raw, ...)` call is unchanged.
- Metadata cache: `cache_fresh` (:74), `cached_payload` (:82), `MetadataCache` (:101; run
  row read once per owner, environment and `created_at_actual_utc`), `RequestOwner.obtain`
  (:197), `RequestOwner.cached` (:316). Miss: fetch as before, then
  `metadata_cache_put(env, pointer, manifest_id, run, retrieved_at)` after `finish_attempt`
  (200 only). Hit: object read back and verified (len/sha/versions),
  `recorded_reserve(..., "cache")`, `finish_attempt(verified_raw, row.http_status, manifest)`
  with the same key/sha/bytes/retrieved_at, new manifest id, `sanitization.input_origin =
  "cache"`; no request, no PUT, no `validate_raw`. An unverifiable cache entry is a miss
  (refetch and replace), not `landing_unavailable`. Only `/argo/meta?id=` with role
  `metadata` is cached.

### `packages/core/src/floatchat_core/ingestion/source.py`
- Only change: reload of an existing landing skips `validate_raw` (same reason). The
  fixture-path cache lookup of the first version was removed (60 reads for zero hits); fixture
  and replay never touch the cache, replay still resolves predecessor manifests.

### Tests and tooling
- `tests/stage1/test_transport_threads.py` (new, 33 tests): fetch from worker threads over
  socketpairs (no network, no `http.server`), signals never used, 404 receipt, redirect,
  live flag, concurrency, real idle-read and attempt-bound expiry, late read charged then
  refused, connect/DNS budget, `operation_deadline`, governor (slots, halving, restore, 60 s /
  Retry-After blocks, threads, pulse), cache hit/miss/stale/damaged/other-role/other-
  environment, within-run hit, hit 20 days after an earlier run, stale after 30 days,
  T ignored, per-chunk manifest, reload by `verified_landing`, fixture and replay never
  consult the cache.
- `tests/stage1/test_landing.py`: fake `upstream_slot(..., slot=1)`, v4 store methods,
  4 new tests (validate once and never on reload, default/explicit slot, governor wraps the
  request and is free during the retry delay, governor slot index selects the lock).
- `tests/stage1/request_owner_probe.py`: `verify_metadata_cache` (not executed, item 8).
- `scripts/stage1_perf_landing.py` writes `reports/stage1-v4-bench-E.json`.
- `test_capture.py`, `test_replay_policy.py`: unchanged, pass.

## Checks run (all from `/home/floatchat/FloatChat-perf`)
- `flock /tmp/claude-1000/perf-test.lock nice -n 19 .venv/bin/python -m pytest
  tests/stage1/test_landing.py test_capture.py test_replay_policy.py test_transport_threads.py
  test_source_supplement.py test_byte_identity.py -m "not integration" -q -p no:cacheprovider`
  -> 110 passed. `tests/stage1/test_wire.py` -> 35 passed.
- `.venv/bin/ruff format --check` and `ruff check` on all owned files and the bench script -> clean.
- `flock ... .venv/bin/mypy` on `transport.py`, `landing.py`, `source.py` (strict) -> no issues.
- `scripts/stage1_perf_landing.py` -> `reports/stage1-v4-bench-E.json`.

## Measurements (`reports/stage1-v4-bench-E.json`; fake transport, 12 chunks, 16 floats)
Run created 2026-10-08, reference time T 2025-04-01 (acceptance-like); every fetch is stamped
after run creation. "E modules" = baseline plus E's three files (isolates E); "worktree" also
carries package C's `objects.py`.

| Scenario | Counter | Baseline 272508b | E modules | Worktree |
|---|---|---|---|---|
| one run | HTTP attempts (metadata) | 96 (60) | 52 (16) | 52 (16) |
| one run | cache-origin attempts | 0 | 44 | 44 |
| one run | validate_raw (landing + reload) | 384 | 156 | 52 |
| second run, 20 days later | HTTP attempts | 96 | 36 | 36 |
| second run, 45 days later (stale) | HTTP attempts | 96 | 52 | 52 |
| fixture RecordedSource, 60 metadata | validate_raw | 240 | 180 | 60 |
| fixture RecordedSource, 60 metadata | cache reads | 0 | 0 | 0 |

Within a run the 60 metadata requests fall to the 16 distinct floats. A run created within 30
days of an earlier one needs no metadata request at all (36 = 3 selection requests x 12
chunks). The reload saving is one decode per landing; the rest of the validate_raw drop in the
worktree column is package C. Scaled to the measured ~2,000 metadata requests per run, the
saving is bounded by the share of repeated floats, which this synthetic scenario fixes at
16 distinct of 60; the real ratio is not measured here.

## Contract clauses affected (for the ADR writer)
- **§9 Concurrency/memory row**: "1 credentialed upstream request in flight" becomes at most
  N (acquire `--slots`, default 4) in flight, one per advisory-lock slot `(164993423, slot)`,
  governed in process: halve on HTTP 429 (floor 1), no new request for max(Retry-After, 60 s),
  +1 permit per 20 consecutive non-429 completions up to N. The 1 GiB per worker and the
  other limits are untouched.
- **§9 I/O deadlines row**: bounds (10 s / 110 s / 120 s) unchanged, now enforced by socket
  timeouts and monotonic checks, not a POSIX alarm; DNS and a single blocking read are the
  two documented gaps (item 7); object operations rely on client timeouts plus checks (item 3).
- **§9 Retry wording**: the durable controller/owner stays the only retry owner; the
  governor is advisory pacing, not a retry owner. 429 stays retryable within four attempts;
  `retry_delay` and the 300 s Retry-After cap are unchanged; Retry-After additionally lengthens
  the governor's block.
- **§9 Requests row / metadata reuse (new)**: a cache hit is a recorded attempt with origin
  `cache`, not an HTTP attempt, so the 50,000 HTTP attempts limit counts only real requests.
  Reuse rule: a cached float metadata object is reused when retrieved at most 30 days before
  the run's actual creation time (no upper bound); the reference time T governs scientific
  eligibility, not evidence freshness; 30 days is "chosen pending measurement".
- **§11 raw evidence**: a metadata raw manifest may point at an object landed by another
  chunk or run (objects are content-addressed; the earlier replay path already did this);
  `sanitization.input_origin` gains `cache`; reload and replay resolve each chunk's own
  manifest, so replay identity is unchanged. Fixture and replay inputs never use the cache.
- **Landing validation**: validated once at landing; reloads trust the hash.
