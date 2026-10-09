# Package C: Parquet write-once, Arrow verification, checksum upload

Scope: `write_snapshot` builds Arrow arrays once and verifies the file by Arrow equality
and per-profile hash (`arrow-equality-v4`); it returns a certificate for the exact bytes;
`publish_verified` is one server-verified conditional PUT plus a `stat`; `MinioStore`
implements both. Design: `docs/stage1-v4-execution-design.md` section 4.3; review
sections 3.2, 3.3, 4.1, 4.7.

## Summary

### `write_snapshot` (packages/core/src/floatchat_core/ingestion/parquet.py)

- Signature: `write_snapshot(path, profiles, *, deadline, max_bytes=MAX_OBJECT_BYTES,
  budget_factory=None, audit=False)`. Evidence keys and values are unchanged
  (`schema_sha256`, `rows`, `profiles`, `membership_sha256`, `storage_comparison`,
  `writer_options`) plus `verification: "arrow-equality-v4"` and
  `certificate: PublicationSnapshotVerifier(..., certified=True)` for the file's SHA-256
  and byte count.
- Rows: package B's `argovis.level_table(profile)` supplies every level column
  including `canonical_level`; this module adds the four per-profile columns per block
  with `pa.repeat` (blocks of about 8 MiB so a 65 KiB sampling header repeated over
  10,000 levels never materialises per profile) and the profile header, cut from the
  canonical bytes and accepted only if `_frame(header)` reproduces the text around the
  levels, else `json.loads`/`json.dumps` exactly as `rows()` does. `rows()` is kept
  unchanged: it is the oracle in the tests and in B's `test_mapper_fast.py`.
- Spill and writer: unchanged. IPC spill per 100,000-row group, memory-mapped back and
  handed to `ParquetWriter` with the unchanged `WRITER_OPTIONS`. The IPC batches are
  re-cut to 64 rows counted from the group start (`spill`), because Parquet page cuts
  depend on Arrow chunk edges: a per-profile chunk layout produced different file bytes.
  With the re-cut, **the Parquet bytes, `normalised/sha256/<hex>` keys and the
  `storage_comparison` block are identical to the stage1-v3 writer** (checked on 5-profile
  and 235-profile inputs with uneven level counts across a row-group boundary, and as a permanent test,
  `test_arrow_rows_equal_rows_oracle_and_file_bytes_equal_v3`).
- Verification (`_verify_written`, `_Scan`): open the file through the module-level seam
  `_open_written(path)`; `schema_arrow.equals(schema(), check_metadata=True)`
  (`parquet_schema_mismatch`); total rows bound (`snapshot_level_limit`); row-group size
  bound (`parquet_row_group_limit`); row-group count and sizes equal the spill's
  (`storage_comparison_mismatch`); then per row group, batches of at most
  `VERIFY_BATCH_ROWS`/`VERIFY_BATCH_BYTES` (sized from the largest row seen while writing)
  are scanned: profile segments by `profile_id` change, header/hash/alias constant inside
  a segment and `level_index` equal to position (`snapshot_profile_inconsistency`), and
  the profile hash recomputed from the stored header re-framed around the concatenated
  `canonical_level` strings, never re-encoded from dicts
  (`snapshot_scientific_hash_mismatch`). `Table.equals` against the spilled rows runs per
  batch; its verdict is raised only after every profile hash was checked, and is named by
  the first differing column (`snapshot_numeric_mismatch` for float64,
  `snapshot_level_mismatch` for qc/unit/mode/flags strings and lists,
  `snapshot_profile_inconsistency` for id/alias/hash/index, hash mismatch for header and
  canonical text). Identity order and alias uniqueness (`snapshot_identity_order`,
  `duplicate_snapshot_alias`, equal consecutive ids as `snapshot_profile_inconsistency`)
  and the resource bounds (`canonical_output_limit` with the same `readback` resource
  evidence for header and profile bytes, 10,000 levels, `snapshot_profile_limit`,
  `snapshot_level_limit`) are applied while writing, from the strings in hand; Arrow
  equality proves the file holds what was checked.
- `audit=True` additionally runs `verify_snapshot` (unchanged, row by row) on the file
  and requires its four evidence values to equal the Arrow ones (`object_validation_mismatch`).
  `budget_factory` is used only there (and by an uncertified verifier): canonical budget is
  charged only for encodes actually performed, i.e. none on the default path.
- `PublicationSnapshotVerifier(digest, byte_count, evidence, *, deadline, budget_factory,
  certified=False)`: `certified=True` makes every call the light check (SHA-256, length,
  schema, row groups, counts); uncertified keeps the full first call. No payload cache; the
  certificate does not cross a process.

### `publish_verified`, `ObjectStore`, `ObjectEvidence` (objects.py)

- Signature unchanged plus `audit=False`; `raw` widened from `bool` to `bool | str`
  (`True` = `.json`, `"nc"` = `raw/sha256/<hex>.nc`; anything else fails `validate_key`).
- Flow: size check, SHA-256, `temporary_key` still validated (`invalid_temporary_key`) but no
  temporary object is written, `validate(payload)` once, `store.write_immutable(final,
  payload, sha256, deadline)`, `store.stat(final, deadline)` must report the byte count and,
  when the store returns one, the same SHA-256 (`object_checksum_mismatch`). `audit=True`
  also reads the object back and revalidates (`object_checksum_mismatch`,
  `object_validation_mismatch`).
- `ObjectStore` protocol: `write_immutable(key, data, sha256_hex, deadline)` (create only if
  absent; an existing key is never overwritten and its content must equal `sha256_hex`, else
  `object_checksum_mismatch`) and `stat(key, deadline) -> {"bytes": int, "sha256": str | None}`;
  `read`, `write_temporary`, `publish_if_absent` stay (the last two unused).
- `KEY` accepts `raw/sha256/<64 hex>.nc`. `ObjectEvidence.temporary_key` is now `str | None`
  (the caller's reserved name, or `None`).

### `MinioStore` (minio.py)

- `write_immutable`: `put_object(IfNoneMatch="*", ChecksumAlgorithm="SHA256",
  ChecksumSHA256=<base64 of the raw digest>)`. 412 means the key exists: it is not trusted;
  `stat` (HEAD with `ChecksumMode="ENABLED"`) must agree on size and stored checksum, and
  when the server stored no SHA-256 (an object written by an earlier release, or by a plain
  `put_object`) the bytes are read back and hashed. This closes the equal-length hole of a
  length-only comparison.
- `BadDigest`, `InvalidDigest`, `XAmzContentChecksumMismatch`, `XAmzContentSHA256Mismatch`
  mean the bytes did not match: `object_checksum_mismatch`, never a fallback.
- Guarded fallback for a server that refuses the parameters (HTTP 501, `NotImplemented`, or
  400 whose code or message mentions the checksum): `self.checksums` is cleared for the life
  of the store, one plain conditional PUT follows, and every plain write is verified by a
  full read-back (HEAD, then GET and SHA-256). `stat` drops `ChecksumMode` the same way on 400/501.
- `stat`: `object_missing` (404), `object_stat_failure` (other failures, malformed
  checksum). `read`: per the coordinator's note on the thread-safe `operation_deadline`, the
  streaming loop now checks `bound = min(deadline, monotonic()+120)` at the top of each
  iteration and raises `io_deadline`; `io_deadline` is the only `Rejection` that now passes
  through `read` (every other category raised inside it is still folded into
  `object_read_failure`, as before).

## Files changed

- `packages/core/src/floatchat_core/ingestion/parquet.py`: `write_snapshot`, `_Parts`,
  `_header`, `_check_limits`, `_block`, `_open_written`, `_file_digest`, `_frame`, `_Scan`,
  `_verify_written`, `PublicationSnapshotVerifier(certified=)`; `rows`, `storage_comparison`,
  `verify_snapshot`, `schema`, `schema_hash`, `WRITER_OPTIONS` untouched.
- `packages/core/src/floatchat_core/ingestion/objects.py`: `KEY`, `ObjectStore`,
  `ObjectEvidence`, `publish_verified` only (package F's `Selection`/`CatalogueRecord`/
  `CatalogueSnapshot`/`select_active_partitions` edits in the same file are theirs).
- `packages/core/src/floatchat_core/ingestion/minio.py`.
- `tests/stage1/test_parquet.py`, `test_objects.py`, `test_minio.py`, `minio_probe.py`.
- `reports/stage1-v4-bench-C.json` (measurements, below).
- Not edited: `scripts/stage1_perf_profile.py` (package J, see open items), any other file.

## Tests

Added or rewritten (all offline, all pass):

- `test_objects.py`: single put then stat order (`["write_immutable", "stat"]`), validate once,
  reserved temporary key checked and never written, invalid bytes/budget/deadline never reach
  the store, corrupted stat byte count, checksum mismatch reported by stat, stat without
  checksum, missing object after write, audit read-back detects a corrupted object and
  revalidates, existing key never overwritten (store that compares and store that does not),
  identical republication, raw `.json`/`.nc` keys, `validate_key` accepts/rejects `.nc` forms.
- `test_parquet.py`: exact equality with `rows()` and byte equality with the v3 writer across
  row-group and profile edges (row-group size patched to 1,000), hostile text in header and
  levels, header cut and parsing fallback, evidence keys and certificate (certified digest/
  byte count, no row-by-row pass, light checks reject other bytes), `certified=True` skips and
  `certified=False` performs the full first call, budget charged only for encodes performed,
  `audit=True` runs `verify_snapshot` and must agree, 12 tampered-file cases through the
  `_open_written` seam (hash, header, canonical text, pressure, qc, flags, level_index, one
  row of hash, profile_id, dropped row, dropped column, schema metadata) each with its
  category, regrouped files, tamper beyond the first read-back batch, identity order/alias/
  equal-id checks, canonical limit categories with `readback` evidence, deadline/budget/empty/
  existing-path rejections.
- `test_minio.py` (stubbed S3 client; the integration test is unchanged in shape): wire
  headers (`x-amz-checksum-sha256`, `x-amz-sdk-checksum-algorithm: SHA256`, `If-None-Match: *`,
  no CRC/trailer, `x-amz-checksum-mode: ENABLED` on HEAD), one PUT, `publish_verified` over
  PUT+HEAD (and +GET with audit), 412 with equal/different/absent checksum and with equal-
  length corrupt bytes, the four mismatch codes without fallback, three refusal shapes with
  fallback and its read-back, remembered fallback, other server errors without fallback,
  transport failure, argument validation, `stat` parsing and failures and its 400 retry,
  dribbling read bound, `read` categories.
- `minio_probe.py` (runs only inside the integration container): extended, see the MinIO
  confirmation below.

Results (exact commands; `cd /home/floatchat/FloatChat-perf`; host shared, `nice -n 19`):

- `flock /tmp/claude-1000/perf-test.lock nice -n 19 .venv/bin/python -m pytest
  tests/stage1/test_parquet.py tests/stage1/test_objects.py tests/stage1/test_byte_identity.py
  tests/stage1/test_resources.py tests/stage1/test_publication_certificate.py -m "not integration"
  -q -p no:cacheprovider`: 78 passed, 1 skipped, 1 deselected (the cgroup test). The skip is
  `test_I02_chunk_internal_natural_alias_conflict`: `workflow.preview` no longer exists in
  package F's working tree, so the test imports it lazily and skips; it tests identity
  resolution, not Parquet, and should move to package F's tests.
- `... pytest tests/stage1/test_minio.py tests/stage1/test_fixture_derivatives.py
  tests/stage1/test_landing.py -m "not integration"`: 48 passed, 1 deselected.
- `.venv/bin/ruff format` and `ruff check` on the seven owned files: clean.
- `flock /tmp/claude-1000/perf-test.lock .venv/bin/mypy packages/core/src/floatchat_core/
  ingestion/parquet.py .../objects.py .../minio.py` (strict): no issues.
- Whole suite `pytest tests -m "not integration"`: 1243 passed, 6 failed, none in my area:
  `test_canonical_encoding_certificate.py::test_large_or_deep_level_never_uses_c_encoding_before_limit`
  (package A), `test_chunk_scale.py::test_chunk_profile_smoke` (`ProfileSpool(path)` in the shipped
  profile script, package F/J), four `test_security.py` cases (pinned gitleaks not installed).
- Not run, by rule: integration tests, `make integration`, docker, the 1 GiB cgroup proof
  (`test_resources.py` integration). Offline emulation of its input (4 and 2 profiles of
  10,000 levels with a 65,536-byte sampling header, so rows of about 66 KiB) with
  `RssAnon` sampled every 20 ms: anonymous peak 257 MiB for 4 profiles and 290 MiB for 2 profiles (v3 writer, 2
  profiles: 212 MiB), 38.7 s CPU against 57.0 s for the v3 writer on the 20,000-row input, identical
  Parquet bytes (1,342,779). The 100,001-row proof is therefore expected to stay under both the 1 GiB bound and
  its 400 s deadline.

## Measurements

`reports/stage1-v4-bench-C.json` (87 profiles x 699 levels = 60,813 levels, MemoryStore, no
MinIO). The shipped `scripts/stage1_perf_profile.py` cannot run unmodified on this tree
(`sub["verify_snapshot"]` is never populated on the Arrow path; `ProfileSpool(path)` no longer
exists; it builds an uncertified verifier), so the numbers come from a scratch copy with only
those edits plus the certified publish stage (the diff is in the report's `notes`). The host is shared
with the other packages' test runs, so spread is large: the same code took 1.7 to 14.7 s.

| Stage | Baseline (272508b, this host) | After (best of 3 script runs) | After (3 runs) |
|---|---|---|---|
| `write_snapshot` wall / CPU | 25.6 s / 24.7 s (421 us/level; review: 22.9 s) | 2.75 s / 2.74 s (45 us/level) | 2.75, 14.72, 12.76 s |
| of which verification (`verify_snapshot` before, Arrow equality now) | 15.2 s | not timed separately | n/a |
| `publish_verified` (memory store) | 12.0 s / 11.6 s (review: 11.3 s) | 0.013 s | 0.013, 0.021, 0.013 s |
| informational: uncertified verifier call | n/a | 9.4 s | 9.4, 6.9, 9.8 s |
| informational: `write_snapshot(audit=True)` | n/a | 10.2 s | 10.2, 9.5, 11.0 s |

Same-session repeats of `write_snapshot` alone (v3 module copy against this one, same profiles,
`same_session_repeats` in the JSON): v3 16.3 to 20.0 s (min 16.3), package C 2.1 to 5.9 s (min 2.1,
median 3.9); steady runs of the new writer in quieter minutes were 1.7 to 2.0 s (28 to 33 us/level).
Note that the v3 module now benefits from package A/B's faster encoder and scalar code, so
its own time on this tree is lower than the 25.6 s baseline.

## Contract effects (for package I / ADRs)

- Contract section 7 step 4 ("read back all bytes...") for normalised objects: replaced by
  the server-verified SHA-256 on the PUT plus `stat` size and checksum; the full read-back only
  with `audit=True` or on the collision path of an existing key without stored checksum. This
  needs an ADR (ADR-0037 certification reuse rule: the first payload is now the one
  `write_snapshot` verified in Arrow; raw landing is untouched by this package but now also gets
  PUT + stat when package E calls `publish_verified`).
- Verification method `arrow-equality-v4` replaces the row-by-row first verification. Two
  checks that `verify_snapshot` made per row are now only in the audit: each numeric column
  value re-derived from its exact text, and each level's embedded `level_index` against the
  column. On the Arrow path they hold by construction: the float columns and the canonical text
  are both outputs of one `map_profile`/`level_table`, and the Parquet read-back must equal
  those columns. A mapper that emitted a float column inconsistent with its canonical text would
  be caught by the audit only.
- Canonical budget: the default path no longer charges the run counter for a verification
  re-encode (one fewer encode per profile); `audit=True` charges as before.
- New or surfaced rejection categories: `object_missing` (already in `processor.FAILURES`),
  `object_stat_failure` and `invalid_object_checksum` (new), and `io_deadline` from
  `MinioStore.read` (already in `FAILURES`; it used to be folded into `object_read_failure`).
  `object_size_limit`/`object_length_mismatch` inside `read` are still folded into
  `object_read_failure`, so `processor.FAILURES` classification of reads is unchanged.
  `PublicationSnapshotVerifier`'s light check
  used to report schema/count mismatches as `invalid_parquet` for the same reason; it now
  raises `parquet_schema_mismatch`/`object_validation_mismatch`. `write_snapshot` no longer
  masks `object_size_limit`/`snapshot_deadline` raised at a group edge with
  `ValueError: write to closed file` (present in v3, reproduced with `max_bytes=8`).
- `raw="nc"`/`.nc` keys: contract section on object keys and migration 0014's key regex.
- The `tmp/<intent>/<id>` names listed by `prepare_intent` are no longer ever created in the
  store; tmp cleanup is a no-op for new intents.

## Open items for the integrator

1. **MinIO live confirmation (not run: no MinIO here).** Pinned `RELEASE.2025-10-15T17-29-55Z`
   must be shown to accept `If-None-Match: *` together with `x-amz-checksum-sha256`, to reject a
   wrong checksum with a 4xx (which code? the probe prints it to stderr as
   `wrong-checksum-error-code`; if it is not in `minio.CHECKSUM_MISMATCH` it must be added or the
   store will fall back and write the object), and to return `x-amz-checksum-sha256` on HEAD with
   `x-amz-checksum-mode: ENABLED`. `tests/stage1/minio_probe.py` (run by the integration test
   `test_P02_P03_P04_real_minio_conditional_publication_and_corrupt_final`) asserts all of this
   and that `store.checksums` stays `True`; it also covers an equal-length corrupt squatter key,
   `.nc` publication, audit mode and the existing corrupt-final case. Expect a first run to
   possibly fail on the assertions; each failure names what MinIO did. The refusal predicate is
   deliberately narrow (it never treats text containing "match" as a refusal), so an unexpected
   error code on a refused-checksum server shows up as `object_write_failure`, not as a silent
   fallback.
2. `scripts/stage1_perf_profile.py` (package J; after the fixes, re-run it once and replace
   `stages` in `reports/stage1-v4-bench-C.json`): (a) `sub["verify_snapshot"]` -> `sub.get(
   "verify_snapshot", 0)` at two places; (b) replace the `PublicationSnapshotVerifier(...)`
   construction with `verifier = verified["certificate"]` (otherwise the stage still runs a
   full row-by-row verify, about 9 s); (c) `ProfileSpool(path)` no longer exists (package F). The
   MemoryStore already has `write_immutable`/`stat`.
3. `processor.py` / package F: use `verified["certificate"]` instead of building a verifier
   (`workflow.snapshot_certificate` already does); keep `certificate` out of JSON
   (`workflow.evidence_json` does; `tests/stage1/resource_probe.py` does `json.dumps` of the
   whole evidence and must drop it: `"verification": {k: v for k, v in result.items() if k !=
   "certificate"}`); `audit=True` for `write_snapshot` and `publish_verified` is not plumbed
   anywhere (suggest a processor setting for acceptance mode and every Nth chunk); calls that
   pass `temporary_key=` keep working but nothing is written there.
4. `processor.FAILURES` (package F, `processor.py:34`): add `object_stat_failure`; without it
   a transient HEAD failure after the PUT quarantines the chunk instead of failing it
   (`object_missing` from `stat` is already listed).
5. `test_I02` (above) should be re-homed with package F.
6. GDAC acquisition publishes NetCDF through `publish_verified(..., raw="nc")`; `gdac.py` (package G)
   already calls it that way. `raw` taking a `str` is the only signature change beyond `audit`.
   `ObjectStore` implementations other than `MinioStore` must provide the collision semantics in
   the protocol docstring (compare existing content, never overwrite).
7. Deliberately not done: `ObjectStore.write_temporary` and `publish_if_absent` are kept (unused)
   for one release as briefed; `Selection`, `CatalogueRecord`, `CatalogueSnapshot` and
   `select_active_partitions` are untouched.
