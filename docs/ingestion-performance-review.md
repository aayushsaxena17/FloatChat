# Stage 1 ingestion performance review (Phase A: analysis only)

Branch `codex/stage-1-perf` from `e1ba4f0`; written 2026-10-08 while live acceptance
session `7153be6379df84de` was running. Nothing in this review touched that session,
the live checkout, the Argovis key or any shared container. Every number below comes
from a script in `scripts/stage1_perf_*.py` whose output is saved under `reports/`,
or from an existing committed report, and each is cited.

## 1. Summary

1. **The Jan-Mar backfill is upstream-bound, not CPU-bound.** The census-weighted
   model ([run model](../reports/stage1-perf-run-model.json)) puts one serial run at
   3.1-4.5 h: HTTP 1.7-3.0 h (selection 1.1-2.5 h depending on Argovis latency, plus
   0.55 h of per-float metadata requests), worker CPU 1.14 h, PostgreSQL COPY+commit
   0.33 h. The live run's first 70 chunks took 66 min, inside the model's 58-77 min
   bracket for those chunks.
2. **"Jan-Mar under 1 hour" is not reliably reachable through Argovis under the
   current contract.** §9 allows one credentialed request in flight; selection latency
   alone is 1.1-2.5 h for 206 non-empty chunks at the measured role means, and the
   optimistic floor (post-episode 1-2 s inventories, data=all unmeasured at its fast
   end) is about 0.8-1.1 h, which depends on upstream latency the client does not
   control. Only an ADR raising in-flight concurrency (owner to check Argovis usage
   terms first) or the GDAC bulk source (candidate 13) makes it reliable. Realistic
   targets with the no-ADR items: live backfill bounded by HTTP at about 1-2.6 h;
   **captured replay 1.5 h to about 0.5 h**; daily 14-day runs dominated today by
   month-slot rewrites (candidate 11).
3. **The worker does the same work 4-5 times per chunk.** The profile payload is
   decoded with exact decimals five times and validated three more, each profile is
   canonically encoded four times, and the Parquet object is fully read back twice.
   Removing the repeats, plus two byte-identical encoder/decoder fixes, cuts worker
   CPU from about 1,425 to about 650 µs per level (-55%) with no contract change.
4. **Two findings outside the optimization list are worth checking after the run**
   (section 6): a synthetic clone of the densest January slot (87 x 699 levels)
   committed in 16.5 s into an empty partition but 34 s into one already holding an
   earlier chunk's rows, against the 60 s bound (the real chunk has since completed in
   the live run); and the next chunk touching a populated slot pays a 20 s retained
   read-back.

## 2. Method and scope

- Code reading of `packages/core/src/floatchat_core/ingestion/`, `workers/`, migrations
  0002-0011 and the contract/ADRs at `e1ba4f0`; multiplicities in section 3 are counted
  from the code, not inferred from timings.
- Offline CPU profile: `scripts/stage1_perf_profile.py` runs every pure-Python/pyarrow
  stage on a labelled synthetic chunk cloned from the authentic 1901094_109 core profile
  (6 columns) tiled to 699 levels, 87 and 22 profiles, with cProfile hot spots
  ([87x699](../reports/stage1-perf-chunk-cpu-87x699.json),
  [87x699 with cProfile](../reports/stage1-perf-chunk-cpu-87x699-cprofile.json),
  [22x699](../reports/stage1-perf-chunk-cpu-22x699.json)). A 24-column BGC clone of
  2904014_040 calibrates the raw-side stages
  ([22x699 bgc24](../reports/stage1-perf-chunk-cpu-22x699-bgc24.json)).
- Disposable PostgreSQL: `scripts/stage1_perf_db_probe.py` starts one 768 MiB,
  2-CPU container from the cached foundation image, applies the migration SQL exactly
  as `tests/stage1/test_database.py` does, stages and commits synthetic chunks through
  the real `Repository` and `app.commit_publication`, measures the retained read-back a
  successor chunk would pay, and removes only its own container
  ([three shapes](../reports/stage1-perf-db-probe.json),
  [87x699 alone](../reports/stage1-perf-db-probe-87-alone.json)).
- Encoder/decoder variants: `scripts/stage1_perf_experiments.py` asserts byte-identical
  canonical output and hashes before timing ([experiments](../reports/stage1-perf-experiments.json)).
- Model: `scripts/stage1_perf_model.py` weights the census slot populations
  (January 699 levels/profile, Feb/Mar 384, ADR-0041) by the measured per-level costs
  and the live transport means ([run model](../reports/stage1-perf-run-model.json)).
- Live context, read-only: `docker stats` samples of the live containers
  ([sample](../reports/stage1-perf-live-cpu-sample.txt)) and the acceptance log's
  chunk counter.
- Everything ran at `nice -n 19` with the live run active and the host at about 2.1 GB
  available; absolute numbers are therefore conservative, ratios are reliable.
  Synthetic basis limits: real profiles vary in depth and column count (the model's
  raw-side factor of 1.63 corrects the 6-column basis to the census average of about
  34 KB raw per profile); no BGC profile deeper than 699 levels was measured.

## 3. Where time and work go

### 3.1 Per run (Jan-Mar 2025, 270 chunks, 206 non-empty, 2.88 M levels)

| Component | Hours (serial) | Basis |
|---|---|---|
| HTTP selection (3 `/argo` per chunk) | 1.12 fast / 2.45 slow | role means from the 8e8da1d4 episode (inventory_before 24.6 s, data=all 12.2 s, inventory_after 2.9 s; empty 404 triples 10.1 s); "fast" = 5+10+1.5 s per ADR-0045's post-episode 1.2-1.6 s inventories |
| HTTP metadata (`/argo/meta`, ~2,000 per run) | 0.55 | 0.99 s mean per request, 103 samples |
| Worker CPU | 1.14 | 1,425 µs/level, section 3.3 |
| PostgreSQL COPY + commit | 0.33 | 408 µs/level pooled, section 3.4 |
| **Serial total** | **3.14-4.47** | live first 70 chunks: 66 min measured vs 58-77 min modelled |
| Captured replay (no HTTP; MinIO reads instead) | 1.47 | CPU + DB only; MinIO unmeasured offline |

The `docker stats` sample shows the live worker alternating between 90-100% of one
core and 10-40% while waiting on the upstream or the database, the database mostly
under 40%, and MinIO in bursts: a single serial pipeline on an 8-core host.
Celery/Redis overhead is negligible: planned-to-fetching took 0.1-5 s when the worker
was idle in c9af101a; the 68 s mean "queue" time there is the one worker being busy.

### 3.2 Per chunk: the pipeline as executed, with repeat counts (from code)

| Step | Where | Work on the profile payload (P) or canonical bytes (C) |
|---|---|---|
| Land each of 3 selection requests + 1 metadata per float | `landing.RequestOwner.obtain`, `objects.publish_verified` | per request: DNS+TLS (`Connection: close`), `sanitize_raw` (full exact-decimal decode + re-encode), `validate_raw` x3 (payload, temporary read-back, final read-back; each a full decode), 4 MinIO ops (put tmp, get tmp, put final, get final), 3-4 DB transactions (`upstream_slot` lock, `http_reserve`, `account_bytes` per 64 KiB, `finish_attempt`) |
| Inventory accounting | `processor.inventory_accounting` | decode P (1) |
| Inventory identity sets | `processor.inventory` x3 | decode P (2) + the two small inventories; `metadata()` re-reads each metadata file from disk and decodes it per profile |
| Metadata resolution loop | `processor.execute` | decode P (3) |
| Publish attempt: accounting again | `processor.publish` | decode P (4) |
| Map | `processor.map` | decode P (5); `map_profile` + canonical encode C (1); `canonical_budget` = 2 DB round trips per profile |
| Spool prepare | `spool.prepare` | `restore_profile` with `verify_encoding=True`: sha256 + `json.loads` + encode C (2); `repository.identities` query per profile |
| Membership, snapshot rows, receipts | `spool.membership`, `write_snapshot`, `processor.receipts` | three separate `spool.profiles(slot)` passes, each sha256 + `json.loads` + Profile rebuild per profile |
| Parquet write | `parquet.write_snapshot` | `rows()` re-parses C and `json.dumps` each level; IPC spill; `verify_snapshot` reads the file back row by row, `json.loads` per level, encode C (3); `storage_comparison` converts the whole table to pandas |
| Object publication | `objects.publish_verified` + `PublicationSnapshotVerifier` | sha256 of payload; first `validate` = full `verify_snapshot` again, encode C (4); temporary and final read-backs = sha256 + light Parquet checks; 4 MinIO ops |
| Staging | `spool.write_candidates`, `repository.stage_file` | candidates carry the canonical string **and** the float levels array: 143.8 MB NDJSON for 74.3 MB of canonical content (87x699); COPY parses it all as jsonb |
| Commit | `app.commit_publication` | per candidate: `::jsonb` parse of the canonical, sha256 in SQL, set-based level checks and insert, outcome row; per slot: membership aggregate; per receipt: two owner_slot counts |

### 3.3 Worker CPU per level (87x699 clone, raw-side stages scaled by 1.63)

| Stage | µs/level incl. repeats | Share | Hot spot (cProfile) |
|---|---|---|---|
| `write_snapshot` | 376 (verify 228, writer loop 144, pandas 3) | 26% | `verify_snapshot`: per-row dict conversion, `json.loads` per level, 4th canonical encode |
| `documents()` decode x5 | 211 | 15% | `exact_number`: regex + `Decimal` + `decimal_text` preflight that builds and discards the normalized string |
| `publish_verified` | 186 | 13% | certificate's first call = full `verify_snapshot` of bytes already verified from the local file |
| `validate_raw` x3 | 171 | 12% | full exact-decimal decode just to count documents |
| `map_profile` + encode | 136 | 10% | `_small_json_bound` costs more than the C encode it guards (12.1 of 16.0 s under cProfile) |
| `spool.prepare` | 96 | 7% | second canonical encode of bytes produced moments earlier |
| `sanitize_raw` | 94 | 7% | decode with `RawNumber` + Python re-encode |
| `membership` + `profiles` re-read | 82 | 6% | three restores of the same spool rows |
| `write_candidates` | 67 | 5% | duplicating levels into the staging JSON |
| `spool.add` | 8 | 1% | |
| **Total** | **1,425** | | 87x699: 65 s single-counted, about 76 s with repeats; RSS 689 MiB |

Experiments ([experiments](../reports/stage1-perf-experiments.json), 30x699 = 20,970 levels):
encoding a level with the C encoder and checking its length afterwards (falling back
to the streaming encoder only when it does not fit) is byte-identical and 2.1x faster
(0.888 to 0.428 s); a whole-profile `json.dumps` bounds the gain at 3.8x (0.233 s).
Dropping only the normalized-text preflight makes decoding 1.5x faster (0.577 to
0.386 s); `json.loads` with token capture (`parse_float=str`) is 41x faster (0.014 s),
which bounds what a lazy exact-decimal path could reach.

### 3.4 PostgreSQL

| Chunk | COPY | commit | COPY+commit µs/level | retained read-back by the next chunk in the slot |
|---|---|---|---|---|
| 22x699 (15,378 levels) | 0.75 s | 3.0 s | 244 | 3.9 s |
| 35x1211 (42,385) | 2.8 s | 8.2 s | 262 | 8.9 s |
| 87x699 (60,813), partition already holding 15k rows | 3.8 s | **34.0 s** | 622 | 16.7 s |
| 87x699 alone, empty partition | 4.0 s | 16.5 s | 337 | 19.9 s |

Pooled 408 µs/level. Other DB calls are cheap: `identities` 18-80 ms per profile
(1.6-7.2 s per chunk, counted in `spool.prepare` above when it includes the DB),
`canonical_budget` 8 ms per round trip, heartbeat 3 ms, `load_science` 130 ms per
profile, `slot_members` 20 ms. The 34 s versus 16.5 s difference for the same chunk
was not isolated (cache state, dead staging tuples or planner choice are candidates);
see section 6.

### 3.5 HTTP and object store

Per request the fixed cost is a fresh DNS lookup and TLS handshake (`Connection:
close`), two uploads and two downloads to MinIO, three or four PostgreSQL
transactions and, for the profile role, three full decodes of the payload. Metadata
requests average 0.99 s of which the upstream round trip is a fraction; about 2,000
of them are issued per run because `Processor.meta` is per chunk and the same float
appears in many chunks. Selection latency is dominated by Argovis query time and is
episodic (ADR-0043/0045): 1-2 s for cached month inventories, 25-80 s during slow
episodes, so no client change moves it other than fewer or concurrent requests.

### 3.6 Memory

Worker anonymous peak is 280-335 MiB in live runs (`stage1-live-memory-*.json`); the
87x699 offline chunk peaked at 689 MiB RSS in one process because the profile list,
spool and Parquet verification coexist. The live host (3.7 GB) carried the run's six
containers at about 1.0-1.3 GB (worker 330, db 255-355, minio 150, supervisor 75,
clients 100) with 2.1 GB available, which is the budget for any second container.

## 4. Candidates, ranked

Ranking weighs expected wall-clock gain on the three workloads (live backfill, captured
replay, daily run), confidence from measurement, risk to hashes/replay identity and
effort. "No contract change" means no clause, limit or policy wording changes; tests
may still change. Cited clauses are in `docs/stage1-contract.md`.

| # | Candidate | Expected effect | Risk | Effort | Contract |
|---|---|---|---|---|---|
| 1 | Verify once: seed the publication certificate from `write_snapshot`'s verification; validate raw bytes once per landing | CPU -360 µs/level (-25%) | low | S | no contract change (S1-RESOURCE-2 reading, section 4.1) |
| 2 | Decode the profile payload once per chunk and reuse; cheaper numeric preflight | CPU -240 µs/level (-17%) | low | S | no contract change |
| 3 | Encoder: C-encode level then length-check (variant A) | CPU -90 µs/level (-6%), byte-identical | low | S | no contract change (ADR-0037 wording already permits) |
| 4 | Float-metadata cache | HTTP -0.5 h/run, -2,000 requests, -8,000 MinIO ops | medium | M | within-run reuse: no contract change on the §11 reading "identical blobs may serve many attempts" (reading to confirm in review: the attempt row records a `verified_raw` landing that made no HTTP request); cross-run: needs ADR |
| 5 | Decouple fetch from processing (landing worker + processing worker, two 1 GiB containers) | run 3.1-4.5 h to max(HTTP, CPU+DB) ~1.7-3.0 h; with #4 ~1.2-2.5 h | medium | L | no clause change (§9 allows 2 active chunk workers); ADR to supersede ADR-0043's deferral with measured host memory |
| 6 | Two processing containers | CPU wall halves (matters for replay and after #5) | medium | M | same as #5 |
| 7 | Slim staging: send the canonical only, derive float levels in SQL | COPY/commit -30-50%, `write_candidates` -50 µs/level | medium | M | no contract change; migration 0012 |
| 8 | Vectorized Parquet verification (Arrow table equality + per-profile hash) | CPU -180 µs/level | medium | M | no contract change (§7 step 4 checks preserved) |
| 9 | Skip spool re-certification of bytes produced in the same process | CPU -65 µs/level | low | S | needs ADR (§9 "reused after round-trip certification within that spool") |
| 10 | Upstream concurrency > 1 in flight | HTTP /N; only path to <1 h via Argovis | high (fair use, episodes) | M | needs ADR; owner checks Argovis terms |
| 11 | Append-then-compact Parquet publication | daily runs: avoid 4-20 s retained read-back + rewrite per touched slot | high | L | needs ADR (§7 catalogue model, selector) |
| 12 | Partial-predecessor replay reusing saved raw landings | re-runs after a failed/partial run skip HTTP for landed chunks | medium | M | needs ADR (§11 replay requires a closed complete predecessor) |
| 13 | GDAC NetCDF bulk source | backfill without Argovis latency | high | XL | new source: owner approval, ADR, migrations, canonical rules |
| 14 | Keep-alive to the pinned address | -0.2-0.4 s x 2,800 requests (~15 min) | medium | M | §9 transport wording ("one bounded attempt"); ADR-light |
| 15 | Vectorized mapping (Polars/Arrow) | map is 10% of CPU after #1-3; defer | high | XL | no contract change if hashes byte-identical, but exact-decimal path is the hard part |
| 16 | Chunk-scale benchmark + hash/replay identity regression tests | no speed-up; required to ship any of the above | low | S | tests only |

Combined no-ADR CPU estimate (#1, #2, #3, #7, #8): 1,425 to about 650 µs/level, i.e.
worker CPU 1.14 h to 0.5 h for Jan-Mar and replay 1.47 h to about 0.7 h; with #6, replay
about 0.45 h. Live backfill stays HTTP-bound at 1.3-2.6 h after #4 and #5.

### 4.1 Verify once (#1, plus #9)

Today the Parquet bytes are fully verified three times: `verify_snapshot` inside
`write_snapshot` (local file), then `PublicationSnapshotVerifier.__call__` on the
first `validate(payload)` in `publish_verified` (same bytes: `file.read_bytes()`,
digest already compared), then two light checks. The raw payload is decoded by
`validate_raw` three times for the same reason, after an equal SHA-256 was already
established. Change: `write_snapshot` returns the certificate already certified for the
exact digest/byte count it verified; `publish_verified` keeps the SHA-256 and byte
count comparison on every read-back and the light schema/row-group/count check;
`validate_raw` runs once per landing and read-backs compare SHA-256 and length only.
Keep a sampled full re-verification (for example every Nth chunk, or every chunk in
acceptance mode) as the periodic audit the brief asks for.

- Contract: §7 step 4 ("read back all bytes; verify SHA-256, byte length, Parquet
  readability, exact schema, counts...") is still done: SHA-256 equality of the full
  object is the proof that the certified checks hold for the read-back bytes, which is
  precisely the S1-RESOURCE-2 implementation note's reuse rule ("only after full
  byte-count and SHA-256 equality of the complete object, plus schema/count/row-group
  checks. The first payload still undergoes full... verification"). The first payload
  is the one `write_snapshot` verified. Certificates still do not cross an intent or
  process; recovery/rebuild starts uncertified. #9 (skipping the `restore_profile`
  re-encode in `spool.prepare` for bytes `map_profile` produced in the same process)
  reads against §9's "reused after round-trip certification within that spool", so it
  is marked needs ADR even though every later read still checks SHA-256.
- ADRs: ADR-0037 (certification), ADR-0034 (spool reuse). Tests:
  `test_publication_certificate.py`, `test_objects.py` (first-call behaviour,
  corruption of temporary/final), `test_parquet.py`, `test_canonical_encoding_certificate.py`,
  `test_landing.py` (validate_raw calls), `test_resources.py` (budget charging).
- Hashes/replay: no canonical byte or hash changes; charged canonical bytes per chunk
  drop (one fewer encode per profile per full verify), which the run budget records
  but does not require to stay constant.
- Failure/recovery: a corrupt read-back still fails on SHA-256/length
  (`object_checksum_mismatch`); a corrupt local file before publication still fails in
  `write_snapshot`. Process loss between verification and publication discards the
  certificate (unchanged).
- Before/after (87x699): `publish_verified` 11.3 s to about 0.3 s; `validate_raw` 6.4 s
  (x3, scaled) to 2.1 s; replay and backfill CPU -25%.

### 4.2 Decode once, cheaper preflight (#2)

`Processor` calls `documents(self.raw_paths["profile"].read_bytes())` five times per
chunk; the decoded documents fit in memory (a 2,000-document chunk is bounded at
128 MiB decoded) or can be re-read from the private file once and held as a list for
the chunk. `exact_number` calls `decimal_text` on every number to preflight the
normalized length, then `scientific_number` builds the same text again; the preflight
can be computed from `as_tuple()` digits and exponent (the same arithmetic
`decimal_text` uses for `length`) without materializing the string, preserving the
§5.1 rule "preflight length before expansion" and the `canonical_output_limit`
precedence. This is "make the preflight cheaper", not "remove it".

- Contract: §5.1 (unchanged semantics), §9 structure/numeric bounds (unchanged).
  Tests: `test_numeric.py`, `test_json_stream.py`, `test_wire.py`,
  `test_canonical_encoding_certificate.py`.
- Hashes/replay: canonical text is produced by the same `decimal_text`; the preflight
  only decides rejection. Add the byte-identity regression on the recorded fixtures.
- Failure/recovery: none; memory for the held documents is already within the chunk's
  bounds (87x699 BGC: 1.9 MB raw).
- Before/after: decode 211 to about 42 µs/level (once, cheaper); sanitize unchanged.

### 4.3 Encoder bound (#3)

`_small_json_bound` (ADR-0037's guard for using the C encoder per level) costs more
than the encoding it guards. Variant A encodes the level with the C encoder, yields it
if `len(encoded) <= remaining()`, otherwise streams the level with `iterencode` so the
first exceeding piece raises exactly as today. Output and charging are identical
(asserted in the experiment); the only change is one transient C-encoded level (bounded
by §9's 64 KiB string and 512-node shape).

- Contract: §7 implementation note ("bounded per-level encoding may reduce CPU overhead
  only with identical canonical bytes/hashes and budget boundary behaviour") already
  authorizes this. ADR-0037. Tests: `test_numeric.py` budget-boundary cases (add one that
  rejects exactly at a level boundary and compares the charged bytes with the streaming
  path), `test_canonical_encoding_certificate.py`.
- Before/after: each encode pass 42 to 20 µs/level; four passes today, two after #1.

### 4.4 Float-metadata cache (#4)

`Processor.meta` is per chunk; `RequestOwner.obtain` only reuses a landing for the same
chunk (`verified_landing` filters `a.chunk_id`). Within a run, a metadata response for a
float already landed by another chunk can be reused by recording a new attempt for the
current chunk whose manifest points at the same immutable raw object (like
`recorded_reserve` with an origin such as `run_cache`), so `raw_manifest`, outcomes and
replay identity are unchanged: `RecordedSource`'s replay path looks up predecessor
`raw_manifest` rows by chunk and `logical_request_key`, so every chunk must still own a
`verified_raw` attempt per metadata request or replay fails with
`replay_selection_unavailable`. Across runs, reuse needs a staleness policy (metadata
can change; the run reference time is the natural bound) and is an ADR.

- Contract: §3.2 (metadata pointer resolution), §11 ("identical blobs may serve many
  attempts"), §9 attempt accounting (reused attempts count against the 50,000 bound or
  are recorded as reuse; decide in the ADR for cross-run). ADR-0032 (persisted HTTP
  outcomes). Tests: `test_landing.py`, `test_capture.py`, `test_replay_policy.py`,
  `test_worker_cli.py`, `test_database.py` (replay bindings).
- Hashes/replay: metadata affects `platform` only; the bytes are the same object, so
  canonical output is identical. Replay of a run that used the cache must find a
  per-chunk manifest, which the attempt row provides.
- Failure/recovery: a missing cached object falls back to a live request within the
  existing four attempts; no new retry owner.
- Before/after: about 2,000 requests x 0.99 s = 0.55 h to minutes; 8,000 fewer MinIO
  operations and 6,000 fewer DB transactions per run.

### 4.5 Decouple fetch from processing (#5) and two processing containers (#6)

The state machine already separates the phases: `fetching -> landed -> validating ->
publishing`, §8.1 recovers a `landed` chunk "without upstream refetch", and
`process_ticket` already constructs the source with `require_existing=True` for
landed/validating/publishing chunks. Design: a landing worker (the only process holding
the key and the §9 upstream slot) runs `execute()` up to the `landed` transition for
chunks in controller order and stops; processing workers (no key, `require_existing`)
pick landed chunks and run `publish()`. The controller dispatches two ticket kinds; the
contract's "at most 2 active chunk workers per environment" holds with one landing and
one processing worker, and a third container needs that limit raised (ADR). Each worker
is its own container with its own 1 GiB cgroup (ADR-0042's criterion is per worker;
`bounded_worker_memory` already refuses otherwise). Host budget from the live sample:
worker 330 MiB anonymous, so two or three workers plus db/minio/redis fit in the 2.1 GB
currently free, with the memory sampler proving it.

- Contract: §8/§8.1 states and recovery (unchanged transitions; a chunk can now sit in
  `landed` for a long time, so the 10-minute chunk lease must be released by the landing
  worker at `landed`, or the lease/heartbeat rules need wording), §9 concurrency row,
  §2 isolation (processing workers never load the key). ADR-0043 deferred two
  containers "as riskier orchestration on a 3 GB host": a new ADR records the measured
  memory and the topology. Tests: `test_controller.py` (two ticket kinds, claim limits),
  `test_worker_cli.py`, `test_acceptance_preparation.py` and `scripts/stage1_acceptance*.py`
  (compose services, memory sampler per container), `test_broker.py`.
- Hashes/replay: none; the same code paths run, in a different process.
- Failure/recovery: process loss of the landing worker leaves verified landings for
  reuse (§8.1 fetching/landed rows); loss of a processing worker is today's
  validating/publishing recovery. Two processing workers publishing different slots
  cannot conflict; the same slot is serialized by `commit_publication`'s slot locks and
  `publication_base_changed` rebuilds (budget of 4), so dispatch should avoid handing
  two chunks of one slot to two workers at once.
- Before/after: serial 3.1-4.5 h to max(HTTP 1.7-3.0, CPU+DB 1.5) h; with #1-#4 and
  two processing workers, HTTP-bound at about 1.2-2.5 h; replay 1.47 h to about 0.45 h.

### 4.6 Slim staging and DB bulk path (#7)

The staging candidate repeats every level twice (canonical object plus the float row),
so `write_candidates` emits 143.8 MB for 74.3 MB of canonical content and COPY parses
both as jsonb; `commit_publication` then derives the row values itself with
`app.canonical_level_values`. Sending only the canonical string (plus identity fields)
halves the staged bytes and the jsonb work, and the SQL already holds the authoritative
derivation. Further: `science := (candidate->>'canonical')::jsonb` and the SQL sha256
are needed; the per-receipt owner_slot counts and the membership aggregate are indexed
and cheap. Investigate the 34 s versus 16.5 s commit difference (section 6) before
tuning anything else.

- Contract: §7 step 6/7 unchanged; `level_mismatch`/`measurement_content_mismatch`
  categories keep their meaning (the float row is now derived, not compared; the
  comparison becomes a self-check of the derivation). ADR-0044. Migration 0012. Tests:
  `test_database.py` level-category cases, `test_publication_scale.py` (extend to an
  87x699 chunk), `test_spool.py`.
- Hashes/replay: canonical bytes unchanged; stored `core_measurement` rows must stay
  identical (the ADR-0044 canonical-value rule already stores derived values).
- Before/after: COPY 4.0 s to about 2 s and commit 16.5 s to an estimated 10-12 s for
  87x699; `write_candidates` 4.1 s to about 2 s.

### 4.7 Vectorized verification and mapping (#8, #15)

`verify_snapshot` converts every row to a dict, re-parses each `canonical_level`, and
recomputes `scientific_number` per value: 228 µs/level. The writer already holds the
exact Arrow batches it spilled; reading the Parquet back as Arrow and checking
`table.equals` against the spilled IPC table (plus the per-profile canonical hash from
the concatenated `canonical_level` strings and the identity/order checks) performs the
same §7 step 4 checks in C++. Vectorizing `map_profile` itself is deferred: it is 10%
of CPU after #1-#3, the exact-decimal rules (§5.1) are per token, Polars is not in the
lock file, and the token-capture experiment shows the decode floor is reachable with a
lazy exact path in plain Python first.

- Contract: §7 step 4, §5 canonical rules (unchanged), ADR-0037. Tests:
  `test_parquet.py` (every mismatch category must still be raised; add Arrow-level
  corruption cases), `test_resources.py`.
- Hashes/replay: none; the Parquet schema (`core-parquet-v1`) is unchanged.
- Before/after: verify 228 to about 40 µs/level; with #1 that pass happens once.

### 4.8 Append-then-compact publication (#11)

With plan v2 the backfill publishes each month x tile slot once, so retained rewrites
are not the backfill's cost; they are the daily run's. Each daily 14-day run touches up
to two months per tile and re-reads every retained profile of the slot (19.9 s for 87
profiles in the probe), re-certifies them in the spool, rewrites the Parquet object and
re-verifies it. Appending a per-chunk object and compacting later changes §7's
generation definition ("a generation contains the full currently accepted stored
profile/level set"), the selector (several active objects per slot, or a manifest of
parts), supersession and the membership manifest check in `commit_publication`. It is an
ADR with catalogue, selector and reporting changes; a cheaper first step is #9's
certified reuse of retained bytes plus #1, which removes two of the three retained
re-encodes without changing the catalogue.

- Contract: §7 (generations, selection, supersession), §11 reconciliation. ADR-0022,
  ADR-0025, ADR-0026. Tests: `test_objects.py` selection, `test_coverage.py`,
  `test_database.py` catalogue cases, `test_terminalization_review.py`.
- Hashes/replay: per-profile hashes unchanged; `membership_sha256` and object identity
  change shape, so replay-identity comparison must compare membership, not object keys.
- Before/after: daily run per touched dense slot from about 20 s read-back + 2 encodes
  + rewrite to one small object; needs its own measurement on a populated database.

### 4.9 GDAC NetCDF bulk source (#13): design and trade-offs only

Why: Argovis latency is the backfill floor; GDAC (ifremer/usgodae) serves whole-float
NetCDF without per-selection query time, so a region x period backfill is bounded by
download bandwidth and local CPU.

Facts from the code that constrain the design: `app.argo_float` and `app.argo_profile`
carry `CHECK (source = 'argovis')`, `policy_versions()` pins `argovis-core-v1` and
`argovis-core-2.36.2+ifremer-fluorescence-v1`, and `scientific-json-v2` canonicalizes
exact source decimal strings. NetCDF stores binary float32/64, so the "exact" text for
a GDAC value is a rendering choice; a GDAC-sourced profile of the same observation will
not hash equal to its Argovis-sourced counterpart by design (`source` is a canonical
field) and Stage 2 must treat them as two populations or define a cross-source
identity rule. Argovis is itself a translator over GDAC (the pinned ifremer-sync
revision in `argovis.py`); re-implementing its merge/QC semantics is the main risk.
Options: (a) a separate `gdac-core-v1` mapping with its own canonical rules and
identity (platform/cycle/direction from the file), Argovis kept for daily increments
and reconciliation by observation identity; (b) use GDAC only as a landing accelerator
feeding the existing Argovis mapping, which is not possible because the wire schemas
differ. Only (a) is honest. Needs: owner approval, an ADR for the new source and its
canonical/numeric rules, migrations relaxing the source checks and adding
`platform/cycle` identity for the new source, a new transport allowlist (§9 pins one
host), fixtures and acceptance cases. Unverifiable offline and left to the owner to
check: GDAC file layout and sizes for the Indian Ocean Jan-Mar window, download
policy/attribution, and mirror choice. Estimated effort XL; benefit: backfill bounded by
local CPU (about 0.5 h after the no-ADR items) rather than upstream latency.

### 4.10 Other items considered

- **Upstream concurrency (#10).** `upstream_slot` is one advisory lock; N slots would
  need an ADR (§9), owner confirmation of Argovis terms, and the ADR-0045 episode
  behaviour (N concurrent requests during a slow episode amplify retries).
- **Partial-predecessor replay (#12).** Today `validate_replay` requires a closed
  complete predecessor; letting a new live run reuse `verified_raw` landings from a
  failed/partial predecessor for chunks with identical logical requests would make
  re-runs after an episode cost only the missing chunks. ADR under §11.
- **Keep-alive (#14).** `transport.fetch` opens and closes a TLS connection per
  request to a re-resolved address; reusing a validated connection to the pinned
  address for consecutive requests of one chunk saves a few hundred ms each. It changes
  the "one bounded attempt" shape in §9 and the DNS re-validation story; small gain.
- **DB round trips.** `canonical_budget` (2 transactions per encode), `pulse`,
  `account_received` per 64 KiB and `identities` per profile total a few seconds per
  chunk; batching `account_received` and `identities` is a minor cleanup, not a
  priority.
- **`storage_comparison`** (pandas deep memory) is 0.2 s per chunk; leave it.
- **Celery/Redis**: negligible; no change.

## 5. Recommended order, milestones and targets

| Milestone | Content | Exit evidence |
|---|---|---|
| M0 harness | 87x699 chunk benchmark test (CPU and disposable DB), byte-identity regression on the four recorded fixtures (canonical bytes, hashes, Parquet `membership_sha256`, staged candidates), per-stage timing output under `reports/` | tests green, baseline numbers committed |
| M1 no-ADR CPU | #3 encoder, #2 decode once + preflight, #1 verify once with sampled audit, #8 vectorized verification | CPU 1,425 to about 650 µs/level on the benchmark; identical hashes; replay projection about 0.7 h |
| M2 metadata cache | #4 within-run reuse; ADR draft for cross-run | about 2,000 fewer requests on a fixture run; replay of a cached run passes |
| M3 topology | #5 landing/processing split, #6 second processing container, acceptance tooling and memory sampler per container; ADR superseding ADR-0043's deferral | fixture run with two containers under 1 GiB each; zero OOM |
| M4 DB | #7 slim staging (migration 0012), resolve the commit anomaly (section 6) | 87x699 commit well under 20 s regardless of partition state |
| M5 ADR proposals for the owner | #10 concurrency, #11 append/compact, #12 partial replay, #13 GDAC design | decisions recorded in DECISIONS.md |

Targets on this host (measured infeasibility stated where it applies):

- Live Jan-Mar backfill via Argovis, one request in flight: 3.1-4.5 h today; after
  M1-M3 about 1-2.5 h, bounded by upstream latency (optimistic floor about 0.8-1.1 h).
  Under 1 h is not reliable without #10 or #13.
- Captured replay: 1.47 h today; after M1 about 0.7 h; after M3 about 0.45 h.
- Daily 14-day run (~900 profiles): HTTP for ~60 touched slots plus month-slot rewrites;
  M1/M2 help, #11 is the structural fix.

Phase B must keep every `tests/stage1` test green (opt-in capacity model excepted), add
an ADR per contract change, and re-run the live acceptance only after the current run
has finished and the owner agrees.

## 6. Findings that need attention regardless of this review

1. **Dense-slot commit sensitivity.** The same synthetic 87x699 chunk committed in
   16.5 s into an empty January partition but 34 s when the partition already held one
   earlier chunk's 15,378 rows (different DB state, same container size). The live run
   has already bounded the real case: January 70:-10 (87 real profiles) is the 64th
   chunk in controller order and the run passed 98 complete with zero failures, so the
   real commit stayed under the 60 s bound (ADR-0044) with about two thirds of January
   in the partition. The sensitivity itself is unexplained; the first post-run check is
   that chunk's publishing-to-complete duration from `app.ingestion_event` in the
   acceptance evidence, then a populated disposable-database measurement.
2. **Retained read-back cost.** A chunk touching a slot that already holds 87 profiles
   pays 19.9 s of `retained_snapshot` (PostgreSQL + `science_row` verification) before
   any of its own work. Splits and daily runs hit this; the backfill mostly does not.
3. **Partition-state dependence of COPY.** `ingestion_staging` accumulates dead tuples
   across chunks (`clear_staging` deletes); confirm autovacuum keeps it small over a
   270-chunk run.

## 7. Reproduction

```bash
cd /home/floatchat/FloatChat-perf
uv sync --all-packages --frozen
nice -n 19 .venv/bin/python scripts/stage1_perf_profile.py --profiles 87 --levels 699 --output reports/stage1-perf-chunk-cpu-87x699.json --work /tmp/perf-work
nice -n 19 .venv/bin/python scripts/stage1_perf_profile.py --profiles 22 --levels 699 --basis bgc24 --output reports/stage1-perf-chunk-cpu-22x699-bgc24.json --work /tmp/perf-work-bgc
nice -n 19 .venv/bin/python scripts/stage1_perf_experiments.py --output reports/stage1-perf-experiments.json
nice -n 19 .venv/bin/python scripts/stage1_perf_db_probe.py --output reports/stage1-perf-db-probe.json --work /tmp/perf-db --scenario 22:699 --scenario 87:699 --scenario 35:1211
.venv/bin/python scripts/stage1_perf_model.py --output reports/stage1-perf-run-model.json
```

The DB probe needs the cached `floatchat-stage0-wsl-dev-db:latest` image and starts one
container at a time with `--memory`; do not run it while host memory is below about
1.5 GB available.
