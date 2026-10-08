# Package B report: fast mapper, `level_table`, `gdac-core-v1` contract

Worktree `/home/floatchat/FloatChat-perf`, base `272508b`. Owned files only; nothing committed.

## Open items for the integrator (read first)

1. **The combined stage "map_profile + budget.encode" reaches 2x only with package A's
   encoder.** `map_profile` itself is 4-5x faster on the benchmark clone and 2.9x on
   data with no repeated values, but `budget.encode` (package A) is about 43 us/level of
   the remaining 55, and I did not touch it. Measured like for like (interleaved,
   scratch harness, 87 x 699, CPU seconds, min of 4-5 repeats): HEAD encoder 1.83x
   combined (100.8 -> 55.2 us/level); with package A's work-in-progress `numeric.py` in
   the worktree 3.38x combined (89.4 -> 26.5 us/level). The script-produced stage time in
   `reports/stage1-v4-bench-B.json` is 8.25 s (baseline given) / 8.661 s (measured at
   the start of this work) -> 5.368 s with HEAD's encoder, i.e. 1.54-1.61x.
2. **The shared worktree cannot import right now, so the mandated test command fails at
   collection** (`ImportError: cannot import name 'copy_rows' / 'preview' from
   floatchat_core.ingestion.workflow`, package F's work in progress; earlier in the session
   `test_parquet.py::test_F06_repeatable_whole_frame_measurement_and_empty_ratio` failed
   on package C's `certificate` object in the evidence dict). I ran the mandated command in
   an export of `HEAD` with only my two files laid over it (`git archive HEAD`, then
   `argovis.py` and `test_mapper_fast.py` copied in, `PYTHONPATH` at the export): **90
   passed**. Re-run the real command once F and C settle. For the same reason
   `scripts/stage1_perf_profile.py` currently dies in the worktree (`KeyError:
   'verify_snapshot'`: the stage expects package C's old read-back), so the benchmark was
   run from that export too (see Measurements).
3. **Garbage collector pause inside `map_profile`** (`_levels`, `argovis.py:328`). The
   collector rescans the growing heap of level dicts while a profile is built; pausing it for
   the level build (restoring the caller's state in `finally`) takes the mapper from about
   22 to 13 us/level in the scratch harness. Levels are acyclic, outputs are unaffected
   (`test_collector_state_is_restored_after_success_and_rejection`). It is a process-level
   side effect for the duration of one profile's build. If you prefer a policy decision at
   the worker level (`gc.disable()` once in the process-pool worker, which handles one
   ticket per process), delete the `paused`/`gc.disable()`/`finally` lines in `_levels`;
   nothing else depends on them.
4. **`policy_versions("gdac-core-v1")` has no `specification_sha256`.** The brief lists
   `mapping`, `source_contract`, `specification: "gdac-netcdf"` and "no translator
   fields"; the Argovis `specification_sha256` hashes the Argovis OpenAPI document and
   would be wrong for GDAC, and no GDAC specification digest is pinned anywhere. Returned
   keys: `geometry`, `mapping`, `hash`, `specification`, `qc`, `source_contract`. If package G
   or the manifests need a digest key, add it there (G pins what it implements).
5. **Unique-valued data limits the mapper to about 3x, by `scientific_number`.** The memo
   removes repeated tokens (the benchmark clone tiles 92 levels to 699, so temperature and
   salinity repeat about 7.6x; real profiles repeat far less: 238 distinct of 501 salinity
   values and 472 of 501 temperatures in the recorded BGC profile). On data where every
   token is distinct, 3 `scientific_number` calls per level (about 12 us each, mostly
   `decimal_text`, `Decimal(99999)` rebuilt per call, the `kinds` dict rebuilt per call,
   `Decimal.from_float` and the frozen dataclass construction) are the floor. That is
   package A's file; whatever A makes cheaper flows through unchanged because the mapper
   calls `scientific_number` as it is.
6. `level_table` imports `pyarrow` and `parquet.schema()` lazily (`parquet.py` imports this
   module, so a top-level import would be circular, and `argovis` stays importable without
   pyarrow for `raw.py`/`planning` users). The returned table carries `parquet.schema()`'s
   metadata (`schema_version`, `hash_version`, `mapping_version`); its mapping version still
   reads `argovis-core-v1` for a GDAC profile, which is for package C/G to decide when a GDAC
   snapshot is written.
7. `test_wire.py` needed no change (it tests transport, nothing in `argovis`).

## What changed and why

`packages/core/src/floatchat_core/ingestion/argovis.py`

- `_variables` (`:275`) and `_Column` (`:259`): per profile, once, for each of pressure,
  temperature, salinity: the first level-independent rejection (`invalid_variable_metadata`,
  `qc_without_variable`, `unknown_data_mode`, in the original order), the column and QC
  column, whether the unit is allowed, the selected value/QC/QC-source/flags keys, the
  plausibility bounds, and a level template that already holds the final key order, the
  `None` scaffolding and the level-invariant `_unit`, `_unit_source`, `_data_mode` values.
- `_levels` (`:328`): the level loop. Per level it copies the template twice (row and
  canonical content) instead of rebuilding eight suffixes and four constants per variable
  in two dicts; per-profile memos for `scientific_number` (keyed by the Decimal value, which
  fully determines the result including the rejection) and for `qc` (keyed by the exact
  token text for Decimals, because `qc(Decimal("1.5"))` and `qc(Decimal("1.50"))` render
  different text; keyed by the string for strings). Only exact `Decimal`/`str`/`None`
  tokens use a memo, so `True`, `1`, `1.5`, Decimal subclasses and signaling NaN (unhashable)
  reach `scientific_number`/`qc` exactly as before. The checks run in the original order
  (pending metadata rejection, token, `unknown_unit`, QC), so the first rejection and its
  category are unchanged. `flags` lists are fresh per level and variable; the canonical
  number dicts are shared between levels, which only the encoder reads. Rejections are
  never memoised.
- `map_profile` (`:436`): signature unchanged; calls `_levels`; `source`/`mapping_version`
  follow the contract; `budget.encode` still runs before `source_revision`, so
  `canonical_output_limit` keeps precedence over `invalid_source` and the budget is charged
  as before.
- `GDAC_SOURCE_CONTRACT = "gdac-core-v1"` (`:23`): accepted by `_data_columns` (`:208`; the
  `ADDITIONAL_NONCORE` branch is guarded by `== SOURCE_CONTRACT`, so
  `chla_fluorescence*` are `unknown_data_field` as under the legacy contract); canonical
  document `"source": "gdac"`, `"mapping_version": "gdac-core-v1"`; pointer validation
  (`data_type == "oceanicProfile"`) unchanged. `policy_versions` (`:616`) returns the GDAC
  policy described in open item 4.
- `level_table` (`:559`), `_level_schema` (`:522`), `_level_texts` (`:534`): the Parquet
  schema without `profile_id`, `source_profile_id`, `profile_hash`, `profile_content` (38
  columns: `canonical_level`, `level_index`, the 36 variable columns, same Arrow types and
  nullability). `canonical_level` is cut from `profile.canonical_bytes` without re-encoding:
  a level is the only object starting `{"level_index":` and every `"` inside a JSON string is
  escaped, so splitting on `},{"level_index":` inside the `"levels":[...],"longitude":`
  region finds the level boundaries; the cut is checked (count, indexes), and any mismatch
  (for example hand-built, non-compact bytes) falls back to `json.loads` + `json.dumps(...,
  sort_keys=True, separators=(",", ":"))`, exactly what `parquet.rows()` does. Value columns
  come from one `itemgetter` pass over `profile.levels` and a transpose.
- Small constants: `PLAUSIBLE`, `LEVEL_SUFFIXES`, `LEVEL_PREFIX`, `PROFILE_COLUMNS`.

`tests/stage1/test_mapper_fast.py` (new, 42 tests)

- `reference_map_profile`: verbatim copy of the stage1-v3 `map_profile` (unchanged since
  `db5febb`, before the goldens at `90e1e67`) as an in-test oracle. Every synthetic document
  must give an equal `Profile`, the same `repr(profile.levels)` (key order and value types),
  the same budget counters, or the same exception type, category and args.
- Goldens: all recorded bundles and all mutations (`stage1_goldens.mutations`,
  `profile_record`) against `tests/fixtures/golden/stage1_v3_goldens.json`, plus oracle
  equality; both synthetic clones (699 levels).
- Targeted cases: key order and value/flag semantics (absent variables, R/A/D, nulls, "NaN",
  fill 99999, unknown QC, repeated and non-monotonic pressure, outside plausibility),
  per-level independence of mutable values, memo type guards (bool/int/float/NaN/sNaN),
  QC text representation (1.5 vs 1.50), seven rejection-precedence cases, encode-before-
  `source_revision`, collector state restore.
- Randomized comparison with the oracle: 1,500 seeded documents under both Argovis contracts
  (3,000 comparisons), asserting that it reaches over 500 successful mappings and 11
  rejection categories.
- `level_table`: schema (names, types, nullability), `to_pylist()` equality with
  `parquet.rows()`, column equality with `Table.from_pylist(rows, schema=parquet.schema())`
  for every recorded profile and mutation, a 699-level clone, 300 random documents,
  hostile QC/unit strings (`},{"level_index":` in values), no `json.loads` on the fast path,
  re-parse fallback, empty levels.
- `gdac-core-v1`: header, no non-core extras, metadata check, unsupported contract,
  `policy_versions` for all three contracts.

Mutation checks I ran by hand on `argovis.py` (each made a named test fail, then restored):
QC memo keyed by value, sNaN guard removed, memo for every token type, unit check on null
values, shared flags lists.

## Tests and checks

- `flock ... pytest tests/stage1/test_wire.py tests/stage1/test_mapper_fast.py
  tests/stage1/test_byte_identity.py tests/stage1/test_parquet.py -m "not integration" -q
  -p no:cacheprovider`: **90 passed** in the HEAD export + my two files; in the live worktree
  it fails at collection for the reason in open item 2 (not my files).
- `.venv/bin/ruff format --check` and `ruff check` on `argovis.py`, `test_mapper_fast.py`,
  `test_wire.py`: pass.
- `mypy packages/core/src/floatchat_core/ingestion/argovis.py` (strict): `Success: no issues
  found in 1 source file`, in the worktree and in the export.
- `test_byte_identity.py` passes unchanged (goldens not touched).

## Measurements

Script: `scripts/stage1_perf_profile.py --profiles 87 --levels 699`
(`reports/stage1-v4-bench-B.json`, stage "map_profile + budget.encode (all profiles)").
Host is shared and loaded; the same stage on the same code ranged 5.4-13.6 s between
runs, so only runs whose other stages agree are compared.

| Run | Stage wall time |
|---|---|
| Baseline given in the brief | 8.25 s |
| Script, start of work (worktree == HEAD), load comparable to the "after" run | 8.661 s |
| Script, HEAD export + `argovis.py` (final mapper), HEAD encoder | **5.368 s** (1.54x / 1.61x) |

In those two runs the unrelated stages match within 10 percent (documents decode 1.358 vs
1.399 s, validate_raw 1.346 vs 1.382 s, spool.prepare 5.612 vs 5.286 s), so the ratio is
like for like. The mapper-only and encoder-included splits below come from a scratch harness
(not a repository script; interleaved reference-vs-new in one process, `process_time`,
87 x 699 clone, `argovis_ref` = HEAD `map_profile`):

| Data | Numeric/encoder | Mapper only (min CPU) | Mapper + encode (min CPU) |
|---|---|---|---|
| benchmark clone (tiled, repeated values) | HEAD | 58.1 -> 12.3 us/level, 4.7x | 100.8 -> 55.2 us/level, 1.83x |
| benchmark clone | worktree with A's work in progress | 54.1 -> 9.6 us/level, 5.7x | 89.4 -> 26.5 us/level, 3.38x |
| every temperature/salinity token distinct | HEAD | 62.8 -> 21.5 us/level, 2.9x | 116.4 -> 65.8 us/level, 1.77x |

`level_table`: 16 us/level (scratch harness, 10 x 699 clone, loaded host), against 33 us/level
for `parquet.rows()` alone; `_level_texts` is about 4 us/level of that.

## Scientific rules and contract

No change to `argovis-core-v1` semantics, `scientific-json-v2`, rejection categories or
their precedence, hashes or goldens. New policy surface for package I: the
`gdac-core-v1` source contract (canonical `source: "gdac"`, `mapping_version:
"gdac-core-v1"`, `policy_versions` content in open item 4), covered by the `gdac` tests in
`test_mapper_fast.py`. The collector pause (open item 3) is an execution choice, not a rule.

## Integrator note
The garbage-collector pause in `_levels` and its test were removed at integration: collector policy belongs to the worker process (package D), not to a library function. Mapper outputs are unaffected.
