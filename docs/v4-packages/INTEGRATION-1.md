# Integration round 1: six failing integration tests (all test-side, no SQL changed)

Owner of this round: the integration-test fixer. Files edited: `tests/stage1/test_queue_sql.py`,
`tests/stage1/test_database.py`, `tests/stage1/capacity_probe.py`. Migrations 0012 and 0013 were
read and **not changed**, so no SQL semantics changed and no semantic justification is needed.

## Per failure

1. `test_P01_P05_R02_B03_F02_F03_F04_F06_F07_combined_processor_publication_replay`
   (`tests/stage1/capacity_probe.py`)
   - Cause: `persisted_report` lists every active object of the environment. The earlier
     component slot (`argovis/core/2025-01/70:10/...`, compacted in `processor_probe`) still
     holds one snapshot, so `(parts, snapshots)` was `(5, 1)`, not `(5, 0)`. The same fact would
     also have broken the two later fetches `(slot,) = SELECT DISTINCT logical_key ...` and
     `(merged,) = SELECT ... FROM committed_active_partitions` (two slots, two rows).
   - Fix (test): the capacity slot is computed with `slot_key(start, 85, -25)`; the report's
     `active_partitions` is split into this slot's rows (exactly five `part`) and the rest
     (exactly one `snapshot`, tile `70:10`); the report counts must be `5` and `1`. The
     compaction and the merged-row query are scoped to that slot (`WHERE logical_key=%s`).
   - Note: the test took 4 min 48 s under `nice -n 19` behind other tests, not about a minute.

2. `test_v4_commit_reserve_is_enforced_after_the_final_authority_check`
   (`tests/stage1/test_database.py`)
   - Cause: `ingestion_run` has `CHECK (work_deadline = deadline - interval '60 seconds')`
     (0002, still in force after 0010). The test moved only `work_deadline`.
   - Fix (test): one instant `w.at = clock_timestamp()+990 ms` sets `work_deadline=w.at` and
     `deadline=w.at+60 s` in the same UPDATE (the immutability trigger was already disabled by the
     test). Less than the one-second reserve remains and the deadline has not passed, so the
     final guard raises `commit_reserve_exhausted`.

3. `test_extend_unstarted_leases_covers_a_claimed_ticket_nobody_started_and_the_handover`
   (`tests/stage1/test_queue_sql.py`)
   - Cause: not `claim_ticket`; the bare `SELECT {ticket("process")}` for the same-fence
     hand-over printed its uuid, one line too many for `splitlines()[-3:]`.
   - Fix (test): the hand-over ticket goes into a temp table (as in the sibling tests), and the
     `claim_ticket` call now prints `claim|a`, asserted too: `[-4:] == ["claim|a", "start|yes",
     "count|1", "after|yes"]`.

4. `test_metadata_cache_put_upserts_and_only_moves_forward` (`tests/stage1/test_queue_sql.py`)
   - Cause: neither the SQL nor the labels. The `put()` helper was
     `SELECT app.metadata_cache_put(...)`; under `psql -t -A` a void-returning SELECT prints an
     empty line, which shifted the last-three-lines window by one (`older|...` landed at index 0).
   - Fix (test): `put()` is now `DO $$ BEGIN PERFORM app.metadata_cache_put(...); END $$;`,
     which prints nothing. `app.metadata_cache_put` is correct: an older `retrieved_at` did not
     replace the row (`WHERE c.retrieved_at<=EXCLUDED.retrieved_at`), a newer one did. The
     equal-timestamp replace branch is implemented by `<=` but not exercised by a test here (it
     needs a second raw manifest of the run; not added).

5. `test_metadata_cache_references_are_restrictive` (`tests/stage1/test_queue_sql.py`)
   - Cause: `text || "char"` is ambiguous in PostgreSQL.
   - Fix (test): `confdeltype::text`.

6. `test_ingestor_reaches_the_queue_only_through_the_security_definer_functions`
   (`tests/stage1/test_queue_sql.py`)
   - Cause: the same void-`SELECT` blank line from `put()` as in failure 4; the real output was
     `[..., "claim|w", "", "cache|1", "bound|8"]`. `claim_ticket` did return the row: its
     eligibility predicate is correct for a freshly claimed chunk under the ingestor role, and the
     test setup was complete. The assertion is untouched and passes with the `put()` fix.
   - The `put()` change affects every caller (only failures 4 and 6 use it); both pass.

## Final runs

- Per-test reruns after each fix: all six passed.
- `tests/stage1/test_queue_sql.py tests/stage1/test_database.py tests/stage1/test_publication_scale.py
  -m integration`: **111 passed, 0 failed, 1 deselected** in 538 s (exit 0).
- `tests/stage1/test_byte_identity.py tests/stage1/test_spool.py -m "not integration"`:
  **32 passed, 0 failed**.
- `ruff format --check` and `ruff check` on the three edited files: clean.

## Side effects and leftovers

- The combined processor test rewrites `reports/stage1-http-retry-evidence.json` and
  `reports/stage1-publication-capacity.json` (about 2,500 changed lines against HEAD each time).
  They were restored to their pre-run content afterwards (file copy, no git command). The
  regenerated v4 evidence from the final run is kept in
  `/tmp/claude-1000/-home-floatchat-FloatChat-stage1/a9029f79-fae6-4ae1-bea1-5f629708f1a8/scratchpad/reports-after/`
  (it shows `parts_before_compaction: 5`, the `80:-30` slot compacted to one snapshot of 40
  profiles / 20,040 rows, and the `70:10` snapshot untouched); the originals are in
  `.../scratchpad/reports-before/`. Adopt the new evidence by copying from `reports-after` if wanted.
- Containers: every `floatchat-stage1-offline-*` / `floatchat-stage1-processor-minio-*` of this
  run was removed by its fixture; none left. A `floatchat-stage1-offline-870795a5...` container
  and an unnamed `sleepy_kare` seen at the start were not started by this work and were left alone.
- `tests/stage1/test_chunk_scale.py` and `reports/stage1-v4-bench-chunk.json` show as modified in
  `git status`; they are not from this round.
