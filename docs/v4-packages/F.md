# Package F report: publication v4 (candidates, parts, slim staging, commit, selector, compaction)

Status: Python side done and unit-tested; **migration 0013 has never run against PostgreSQL**
(no `psql`, no docker, per the rules). Every SQL claim below is by reading; the integration
tests listed in "Awaiting the integrator" are the first real check.

## Summary

A chunk now publishes only its own accepted profiles, one Parquet *part* per changed slot, with
no read-back of the retained population:

```
map -> ProfileSpool.prepare (2 batched reads) -> per changed slot: write_snapshot(part)
    -> prepare_intent -> publish_verified -> stage_candidates (slim COPY)
    -> stage_levels (binary COPY) -> receipts -> commit_publication v4 (one fenced txn)
```

`commit_publication` inserts levels set-based from `app.measurement_staging`, edits
`logical_partition_slot.membership_manifest` incrementally, bumps `slot_version` once per
changed slot and activates each generation as a `part`. `app.compact_slot` + `Repository.compact`
merge a slot's parts into one snapshot later.

## Data-model changes (for the ADR writer)

Migration `infra/migrations/versions/0013_publication_v4.sql` (generated once from a template;
the three copied evidence functions differ from 0006 only where listed).

| Change | Contract clause / ADR touched |
|---|---|
| `app.measurement_staging(run_id, chunk_id, fence, occurrence_index, level_index, 36 value columns)`, `UNLOGGED`, PK `(run_id,chunk_id,fence,occurrence_index,level_index)`, domains `finite_float8`/`qc_code` as in `core_measurement`, `CHECK` on index ranges; statement-level `AFTER INSERT ... REFERENCING NEW TABLE` trigger asserts the fenced authority once per COPY (a per-row trigger took the run row lock 60,000 times) | §7 step 7 (staging); ADR-0044 |
| `app.ingestion_staging.candidate` shrinks to identity fields, `content_hash`, `revision`, `raw_manifest_id`, `canonical` (text), `level_count`: no `levels` array (review §4.6: 143.8 MB NDJSON became about 83 MB for 87x699) | §7 step 7 |
| `core_measurement.canonical_level` dropped; `app.canonical_level_values` dropped. The per-level content check against the canonical becomes the sampled audit `app.audit_levels(p_chunk, p_sample)` (raises `measurement_content_mismatch`, reuses `app.level_mismatch`). **Rule change to record**: stored floats are now the staged Python values, not re-derived from the canonical in SQL; ADR-0044's positive-zero rule holds because `scientific_number` normalizes zero in Python (`token == 0 -> 0.0`, exact text `"0"`). `level_set_mismatch` and `invalid_level_index` stay in the commit; `index_missing` cannot exist (NOT NULL key) | ADR-0044 amendment, §6 mapping, §7 step 7 |
| `dataset_partition.kind text NOT NULL DEFAULT 'snapshot' CHECK IN ('part','snapshot')`, `part_ordinal integer`; unique index `one_active_generation` replaced by `one_active_snapshot` (one active snapshot per slot) plus a non-unique active index | §7 "a generation contains the full accepted set" becomes: the catalogue state of a slot is its membership manifest plus the active parts and at most one snapshot that hold those rows; §7.2 selection |
| `generation` is allocated as `max(generation)+1` per slot for parts and snapshots (it can no longer equal `slot_version`: compaction adds a generation without a membership change); `part_ordinal` = that generation | ADR-0022/0025/0026 (generations) |
| `committed_active_partitions` keeps its predicate (including `slot_version = current`); to keep that valid with several objects per slot, `commit_publication` and `compact_slot` re-stamp every active object of a changed slot with the new `slot_version`. A stale object still never selects | §7.2 |
| `commit_publication` v4: same signature, same identity / revision / eligibility / raw-provenance / outcome / receipt / fence / deadline checks and categories. Differences: levels set-based from staging; for every changed slot the generation must declare exactly this chunk's accepted profiles in the slot (`stored_snapshot_membership_mismatch` otherwise); the slot manifest is edited (drop replaced and moved-out ids, add own entries, ordered by profile_id) and then verified against the stored population with `app.audit_slot_manifest` (index-backed recompute); nothing is superseded except a slot whose manifest becomes empty (§7 outcome 3: "old slot returns no active generation"); the receipt evidence gets `full_membership` from the slot manifest; a receipt-only slot may carry `base_version` (mismatch -> `publication_base_changed`); `selection_profiles` is counted only when a disposition depends on it; slots of generations and receipts are locked in one ordered statement (removes a deadlock class between concurrent chunk commits); staged levels are deleted at the end | §7 steps 6-8, outcomes 1-3 |
| `app.clear_staging` also deletes `measurement_staging` rows of this and older fences | §7 |
| `app.compact_slot(p_environment, p_logical_key, p_generation jsonb)`: one transaction proves base version, membership manifest equality and that the active objects are exactly `supersedes`, supersedes them and inserts the snapshot (`kind='snapshot'`). The snapshot row inherits `intent_id/run_id/chunk_id` from the newest part it replaces (the columns stay NOT NULL; the alternative is nullable ids plus a `LEFT JOIN` view) | §7.2 |
| `reconciliation_snapshot` reads members from `logical_partition_slot.membership_manifest` (parts overlap after a replacement); `scientific_snapshot` and `report_metrics_snapshot` order by `logical_key, generation` and the latter lists `kind`, `part_ordinal`, `slot_version` | §11 reconciliation |
| New functions `audit_slot_manifest`, `audit_levels`, `compact_slot`, `check_measurement_staging_authority`: `REVOKE ... FROM PUBLIC`, `GRANT EXECUTE` to `floatchat_ingestor` (staging: `SELECT, INSERT`, revoked from `floatchat_app`) | security bounds |

Readers (for the ADR and Stage 2): keep a row of a part or snapshot only if its
`(profile_id, profile_hash)` is in `Selection.manifests[slot]`; if the same pair is in two
objects (a profile reverted to older content) rows are identical, keep one. Part rows of
replaced or moved profiles stay in older parts until compaction.

## Python changes

- `spool.py`: `ProfileSpool()` is an in-memory candidate set (no SQLite, no re-encode, no
  `retain`). `prepare(identities_batch, science_hashes)` does two batched reads, then the old
  sequential identity/revision logic. It exposes `profiles(slot)` (own accepted profiles in id
  order = the part), `membership(slot)`, `departed(slot)` (stored profiles this chunk replaces
  or moves out of the slot), `candidates()`, `level_tables()`, `outcomes`, `conflicts`,
  `changed_slots`. `restore_profile`, `revision_json` kept; new `parse_revision`, `merge_parts`.
- `workflow.py`: slim `staged_candidate`, `staging_table`, `MEASUREMENT_COLUMNS`/`STAGING_SCHEMA`
  (test-checked against the migration), `slot_key`, `StoredState`, `snapshot_certificate`
  (uses the writer's own certificate, else certifies the first payload), `evidence_json`.
  `preview`, `Preview`, `copy_rows` removed.
- `repository.py`: `stage_candidates`, `stage_levels` (binary COPY, accepts a table or an
  iterable of tables), `identities_batch`, `science_hashes`, `slot_state` (bases and, only where
  needed, stored counts, in one snapshot), `compact`, `compactable_slots`, `audit_levels`,
  catalogue snapshot with parts and manifests. Removed: `stage`, `stage_file`,
  `retained_snapshot`, `load_science`, `science_row`, `slot_members`. `commit` signature
  unchanged. Kept verbatim: `claim_ticket`, `metadata_cache_get/put`, `upstream_slot`. Also
  applied the two requests D and G routed to this file: `ticket(authority, kind="process")` and
  `extend_unstarted_leases(run, epoch)`.
- `processor.py` (`map`, `publish`, `receipts` only): see flow above. `map()`'s lifecycle-review
  check uses `science_hashes` (no budget charge for re-encoding the stored profile any more).
  Receipts predict the post-commit population as stored-now minus departures plus arrivals and
  read stored counts only for slots where the answer is not certain; SQL rechecks them.
- `objects.py` (only my four names): `CatalogueRecord.kind/part_ordinal`,
  `CatalogueSnapshot.manifests`, `Selection.manifests` (all defaulted, positional constructions
  unchanged); selection returns every active object of a slot and treats one unreadable object
  as a gap of the whole slot.
- `coverage.resolve`, `reporting`: several objects per slot; `persisted_report` adds
  `active_partitions`, `active_part_count`, `active_snapshot_count`. `catalogue.py` unchanged.

## Edits needed in files I do not own

1. `scripts/bootstrap_db.py`: add `"measurement_staging",` to `STAGE1_TABLES` (otherwise a
   bootstrap re-run grants `floatchat_app` DML on it).
2. `scripts/stage1_perf_profile.py` (J): line 167 `spool = ProfileSpool()`; line 171
   `lambda: spool.prepare(lambda profiles: {}, lambda ids: {})`; line 249 replace
   `spool.write_candidates(staged)` by `list(spool.candidates()); list(spool.level_tables())`
   and drop `staged.stat()` (line 250, or measure `sum(len(json.dumps(c)) for c in
   spool.candidates())`); delete line 251 `spool.connection.close()`; the multiplicity table at
   line 265 no longer has three `profiles(slot)` restores.
3. `scripts/stage1_perf_db_probe.py`: line 158 `ProfileSpool()`; lines 165-167
   `spool.prepare(repository.identities_batch, repository.science_hashes)`; replace the
   `retained_snapshot` block (183-186) by `bases = {slot: repository.slot_state(authority,
   [slot], piece)[slot].version}`; line 189 stays; `generations[0]` gets `"kind": "part"` and
   `"verification_evidence": evidence_json(verified)`; lines 223-228 become
   `repository.stage_candidates(authority, spool.candidates())` then
   `repository.stage_levels(authority, spool.level_tables())`; the post-commit block
   (272-290) uses `repository.science_hashes([id])` and `repository.slot_state(..., counts=[slot])`
   instead of `retained_snapshot`/`load_science`/`slot_members`; delete line 306.
4. `tests/stage1/split_replay_probe.py`, `regional_capacity_probe.py`: D's `"execute"` and
   `(authority, kind)` edits (D.md item 4); I applied them to `processor_probe.py` and
   `capacity_probe.py`.
5. **Delete `tests/stage1/test_parquet.py::test_I02_chunk_internal_natural_alias_conflict`**
   (package C's file): it skips forever because `workflow.preview` is gone. Its logic is
   re-homed, same name, in `test_spool.py` against `ProfileSpool.prepare`.
6. Applied on integrator instruction: `SAFE_DATABASE_CATEGORIES` now contains every
   `RAISE EXCEPTION` name of 0012 and 0013 (`invalid_ticket_kind`, `invalid_ticket_worker`,
   `invalid_recorded_origin`, `landing_retry_exhausted`, `invalid_metadata_cache_entry`,
   `level_set_mismatch`, `invalid_level_index`, `invalid_level_count`,
   `measurement_content_mismatch`, `measurement_count_limit`, `profile_count_limit`,
   `candidate_outside_eligibility`, `duplicate_publication_slot`, `invalid_publication_evidence`,
   `missing_coverage_receipt`, `unverified_final_object`, `invalid_audit_sample`); a unit test
   (`test_every_exception_category_of_the_publication_migrations_is_a_safe_category`) keeps
   the set in step with both files. **Behaviour change to know**: these used to surface as
   `database_failure` (chunk `failed`); `terminal()` now classifies them as `quarantined`
   because none is in `FAILURES`. Add `landing_retry_exhausted` (and any other you want
   retried or failed rather than quarantined) to `FAILURES` in `processor.py` if that is wrong
   for them. `object_stat_failure` was added to `FAILURES` as instructed (transient HEAD
   failure after the PUT fails the chunk). The publish path already uses the writer's own
   `certificate` as the validator (`workflow.snapshot_certificate`) and strips it from the
   stored evidence (`workflow.evidence_json`).
7. The migration message addressed to package G (0014 origin CHECK / `reserve_recorded_attempt`
   including `cache`) does not concern 0013; nothing in 0013 touches either.

## Tests

Mandatory command (shared lock, not-integration):
`tests/stage1/test_spool.py test_coverage.py test_resources.py test_publication_certificate.py
test_objects.py test_byte_identity.py test_identity.py` : **all pass** (final run recorded at
the end of this file). `ruff format`/`ruff check` on every owned file: clean. `mypy` strict on
`processor spool workflow repository coverage reporting objects`: clean.

New or rewritten offline tests (run): `test_spool.py` (caps, batched reads, own-profile
parts, replacement/ownership correction, duplicate and conflict outcomes, slim staging and
typed level tables, migration column check, `merge_parts`, fake-cursor tests of
`identities_batch`/`stage_levels`/`stage_candidates`/`compactable_slots`/`ticket`, an
end-to-end `Repository.compact` with real Parquet and a fake store, and `Processor.process()`
/`publish()` over a fake repository: one part, rebuild loop of four attempts, manifest-only
slot, replay of stored profiles, empty fetch dispositions), `test_coverage.py` (snapshot plus
parts, duplicates, selector gaps), `test_publication_certificate.py` (per-part certificates,
fallback certificate, compacted snapshot equals a direct write). `test_resources.py` needed no
change (it proves the Parquet writer's memory, which this package does not alter).

Awaiting the integrator (integration-marked, syntactically valid, consistent with the SQL I
wrote, never executed): `test_database.py` (all, notably the rewritten
`test_ADR0044_level_set_checks_in_commit_content_checks_in_audit`, and the new
`test_v4_*` cases: parts and manifest, replacement, wrong part manifest, receipt base version,
manifest drift, `compact_slot`, staging authority and clearing, every rejection category
including `fallback_observation_time_correction`, `identity_conflict`, `raw_provenance_mismatch`,
`missing_affected_slot`, `coverage_disposition_mismatch`, `publication_base_changed`,
`commit_reserve_exhausted`), `test_publication_scale.py` (10,000-level profile and 87 x 699
chunk under 10 s with inline COPY), `repository_probe.py`, `processor_probe.py` and
`capacity_probe.py` (parts, compaction to a snapshot, `"execute"` kind). First failures are
more likely test or SQL typos than design problems; the SQL was written without a server.

## Expected before / after (commit path, 87 x 699 = 60,813 levels)

Measured offline here (ad hoc script below, host loaded, `nice 19`; no database):
map 4.2 s (package B), spool add + prepare 0.004 s (was 4.85 s in J's profile: re-encode),
part write + verification 6.9 s (package C), typed level tables 0.5 s, candidate JSON
83.2 MB in 1.0 s (was 143.8 MB, 4.1 s), client side of the binary COPY 2.7-4.1 CPU-s
(`to_pylist` 1.3-2.6 s + `write_row` 1.4 s; the strings are the slow part), peak RSS 487 MiB.
Removed from the path: three `spool.profiles` re-reads, the retained read-back (19.9 s per 87
profiles in the review) and its re-certification, the second canonical encode, 74 MB of
`canonical_level` jsonb written to `core_measurement`, the per-level jsonb expansion in SQL.

Not measured (needs PostgreSQL): commit. Review baseline 16.5 s (empty partition) to 34.0 s
(partition holding 15k rows) and COPY 4.0 s. Expectation from the work removed, to be checked by
`test_publication_scale.py`: commit under 10 s and flat in the retained slot size (the only
O(slot) work left is the manifest edit and `audit_slot_manifest`, both index-backed and
detoast-free). Costs added: the audit recompute per changed slot, `UPDATE` of the slot's
active objects, one `DELETE` of staged levels.

Throwaway script used for the numbers: `.../scratchpad/bench_publish.py` (maps
`synthetic_chunk(87, 699)`, runs `ProfileSpool`, `write_snapshot`, `staging_table`, and formats
the rows with `psycopg._copy_base.BinaryFormatter`); not added to the repository.

## Open items and risks

1. **SQL unexecuted.** Highest risk: plpgsql name clashes (variables `generation`, `slot`,
   `ordinal`, `n` against column names; I qualified every column), the `UPDATE ... RETURNING
   INTO`, the transition-table trigger on an UNLOGGED table, `PERFORM ... ORDER BY ... FOR
   UPDATE`. Alembic runs the file through `text()`: I checked there is no `:word` token.
2. **Concurrency of receipts.** Python predicts receipt dispositions from counts read before
   commit; changed slots are protected by the generation base check, receipt-only slots by the
   new `base_version` field. A mismatch rebuilds (`publication_base_changed`, four attempts)
   instead of quarantining as `coverage_disposition_mismatch` would.
3. **Memory.** The in-memory set holds `Profile.levels` dicts (about 2 KB per level, 487 MiB
   peak for 87 x 699). At the contractual cap (256 MiB canonical, 2,000,000 levels) it would
   exceed the 1 GiB worker bound; a chunk like that fails with `MemoryError` or the cgroup,
   not a clean category. Lowering `LEVEL_LIMIT` or staging Arrow instead of dicts needs a
   decision; the contract caps are unchanged here.
4. **Compaction** reads all active objects of a slot (guard: 256 MiB total) and rebuilds
   `Profile`s from Parquet rows with `restore_profile` (hash-checked); it is CPU-heavy in
   Python (a writer that accepted Arrow tables would remove it). It charges no canonical
   budget (no run authority) and the snapshot inherits `intent/run/chunk` of the newest part.
   `Repository.compactable_slots(environment, min_parts=2)` is the work list for D's `compact`
   command, which currently enumerates slots itself.
5. **Stage1 deployments**: existing slots have consistent manifests (old code wrote them equal
   to the generation); `commit_publication` now fails with `stored_snapshot_membership_mismatch`
   on any slot whose manifest drifted from its stored population, as the old check did.
6. `audit_levels` is available (`Repository.audit_levels`) but no worker calls it; the choice
   of sample size and cadence (for example every Nth chunk, acceptance mode) is the integrator's.
7. `measurement_staging` is UNLOGGED on purpose (transient, rebuilt by every staging call,
   truncated on crash recovery; a retried chunk fails `level_set_mismatch` if only the
   candidates survived, which cannot happen since both calls restage).

## Final run (live worktree, after all edits)

| Check | Result |
|---|---|
| mandatory pytest command (spool, coverage, resources, publication_certificate, objects, byte_identity, identity; `-m "not integration"`) | 86 passed, 1 deselected |
| `ruff format --check` / `ruff check` on all 17 owned files | clean |
| `mypy` strict: processor, spool, workflow, repository, coverage, reporting, objects | no issues |
| whole `pytest tests -m "not integration"` | 1252 passed, 2 skipped, 11 failed, none in my files: `test_chunk_scale.py::test_chunk_profile_smoke` (`ProfileSpool(path)` in `scripts/stage1_perf_profile.py`, edit 2 above), `test_acceptance_preparation.py` and `tests/test_compose.py` (compose still has `redis_data`, package H), `test_canonical_encoding_certificate.py` (package A), `tests/test_refetch.py` x3 and `tests/test_security.py` x4 (pre-existing, gitleaks/timing) |
