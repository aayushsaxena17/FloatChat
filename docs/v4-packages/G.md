# Package G report: GDAC NetCDF source, migration 0014, fixtures

## Summary

`floatchat_core.ingestion.gdac` adds a second source population (`source='gdac'`,
mapping `gdac-core-v1`) that backfills from the Argo GDAC Indian Ocean daily basin files.
It downloads the daily NetCDF files once into a cache, converts each profile to a
document, maps it with `scientific-json-v2` canonical bytes in the `argovis-core-v1` level
structure, and lands it through the unchanged Stage 1 landing pipeline as an
Argovis-shaped wire array (`GdacSource`). The unmodified `Processor` methods `landing`,
`inventory`, `inventory_accounting` and `metadata` were exercised against a `GdacSource`
(scratch script, offline): the inventory triple agrees, outcomes are produced and
`gdac_map_profile` accepts the landed documents. Only the mapper call in `Processor.map`
and the CLI/admission wiring remain (see "Integrator items").

Checks (all offline, under the shared lock):

- `tests/stage1/test_gdac.py` (105 tests) + `tests/stage1/test_byte_identity.py`:
  `111 passed in 25.56s` with the mandated command.
- `ruff format --check` and `ruff check` on the three owned Python files: clean.
- `mypy packages/core/src/floatchat_core/ingestion/gdac.py` (strict, repo config): `Success: no
  issues found in 1 source file`. netCDF4 1.7.4 ships `py.typed` and `.pyi`, so no
  `[[tool.mypy.overrides]]` for `netCDF4.*` is needed.
- Migration 0014 was NOT executed: there is no PostgreSQL on this host and docker is
  forbidden. It is covered by a static test only (`test_migration_0014_...`). The first
  real execution will be `tests/stage1/test_database.py` (integration) in the integrator's run.

## What the GDAC server layout actually was

Listing `https://data-argo.ifremer.fr/geo/indian_ocean/2025/01/` (Apache autoindex, fetched
2026-10-08):

- One file per UTC day: `YYYYMMDD_prof.nc` (anchor `href="20250101_prof.nc"`), with a
  last-modified column and a size column (`4.7M`, `5.2M`, ...). January 2025 has 31 files,
  February 2025 has 28 (every calendar day is present, including quiet days).
  Size range in these two months: 2.8M to 8.0M (`20250215_prof.nc` is 8.0M).
- The path layout is exactly `geo/indian_ocean/<yyyy>/<mm>/<yyyymmdd>_prof.nc`, as designed.
- Last-modified times of 2025 files are 2026-09-08 .. 2026-10-07: the daily files are
  regenerated periodically, they are not immutable upstream.
- The global index is `https://data-argo.ifremer.fr/ar_index_global_prof.txt.gz`,
  `Content-Type: application/x-gzip`, `Content-Length: 58734918`, `Accept-Ranges: bytes`
  (no Content-Encoding). 3,418,915 lines when decompressed, 8 `#` comment lines, a header
  `file,date,latitude,longitude,ocean,profiler_type,institution,date_update`, `date` and
  `date_update` as `YYYYMMDDHHMMSS`, `file` is the per-float path
  (`aoml/1901514/profiles/R1901514_484.nc`, a trailing `D` before `.nc` for descending),
  rows with blank date/lat/lon exist.
- Throughput from this WSL host was poor and variable: 5 to 47 KB/s (probe: 1.3 MB in 42 s on
  the index, 1.2 MB in 26 s on a daily file; `ss` counters showed 28 to 36 KB/s later). The
  index took about 26 minutes, each daily file 2 to 3 minutes. The first run died at my
  initial 600 s attempt bound; the default is now 3600 s with a 60 s idle read. For a
  one-year backfill (about 365 files, 1.8 GB) this host would need many hours; the
  production server must be measured. Use `gdac.prepare_cache` before admitting a run.

NetCDF content (both fixture days, FORMAT_VERSION 3.1, Argo-3.1 CF-1.6):

- Dimensions `N_PROF` (97 on 2025-01-15, 77 on 2025-02-14), `N_LEVELS` (1193 / 1015),
  `N_PARAM=3`, `N_CALIB=3`, `N_HISTORY=0`.
- PRES, TEMP, PSAL and their `_ADJUSTED`, `_ADJUSTED_ERROR` are float32 with `_FillValue`
  99999.0 and units `decibar` / `degree_Celsius` / `psu`; `_QC` / `_ADJUSTED_QC` are char,
  blank is the fill. JULD, LATITUDE, LONGITUDE are float64 (JULD fill 999999.0, position
  fill 99999.0). There is no `PARAMETER_DATA_MODE`: only the per-profile `DATA_MODE` exists.
- `DATE_UPDATE` is a file-level scalar, not per profile: `20261007020208` in the Jan 15 file
  whose `DATE_CREATION` is `20250115024218`; `20260923162302` in the Feb 14 file.
- Files are ordered by JULD descending. Profiles of a file all fall on the file's UTC day.
- The basin file is larger than the project region: 79 of 97 (Jan 15) and 61 of 77 (Feb 14)
  profiles lie inside `[-60,30] x [20,120]`; the rest extend to 145E and 67.7S.
- Jan 15: DATA_MODE D 63, A 20, R 14; DIRECTION A 95, D 2; no duplicate
  (platform, cycle, direction); no fill positions or times; 10 profiles with interior
  all-fill rows, 1 with repeated pressure, 1 D-mode profile whose adjusted TEMP is entirely
  fill (3 for adjusted PSAL). Feb 14: same patterns; raw PSAL reaches 61.439 (outside the
  plausibility range) and POSITION_QC 8 occurs on two profiles.

## Fixtures and attribution

`tests/fixtures/gdac/` (total 10,590,378 bytes, limit 12 MB), created by
`scripts/gdac_fixtures.py` (run once, `retrieved_at_utc` in the manifest):

| File | Bytes | Origin |
|---|---|---|
| `20250115_prof.nc` | 5,632,396 | verbatim `geo/indian_ocean/2025/01/20250115_prof.nc` |
| `20250214_prof.nc` | 4,402,816 | verbatim `geo/indian_ocean/2025/02/20250214_prof.nc` |
| `ar_index_indian_2025q1.txt` | 555,166 | excerpt of `ar_index_global_prof.txt.gz` (58,734,918 bytes, sha256 `f547dc51...`): lat [-60,30], lon [20,120], date 2025-01-01..2025-03-31; 5,970 lines = 8 comments + header + 5,961 rows |
| `manifest.json` | 1,294 | url, sha256, bytes, retrieved_at_utc, attribution |

Deviation from the brief: 2025-02-15 is 8.0M, on the 8 MB limit and it would have pushed
the total past 12 MB, so 2025-02-14 (4.2M) is used instead.
Attribution (also in `manifest.json` and `gdac.ATTRIBUTION`): "Argo (2000). Argo float
data and metadata from Global Data Assembly Centre (Argo GDAC). SEANOE.
https://doi.org/10.17882/42182".

All 5,961 index rows in the box have `ocean == 'I'`, and for both fixture days the Indian
Ocean index rows equal the NetCDF profiles per tile for all 100 tiles (zero mismatches).
Re-running the script fetches the then-current upstream files, so hashes in the manifest
and the pinned hashes in the test would change; the committed bytes are the baseline.

## gdac-core-v1 canonical rules (for the ADR writer)

The canonical document has exactly the `argovis-core-v1` profile keys and per-level keys
(`test_canonical_structure_matches_argovis_core_v1` compares the key sets with a real
`map_profile` output); `hash_version` is `scientific-json-v2` and the encoder is the same
`CanonicalBudget.encode`.

1. Identifiers: `source: "gdac"`, `mapping_version: "gdac-core-v1"`. Versions dict
   (`gdac.VERSIONS`, equals B's `argovis.policy_versions("gdac-core-v1")`; a test checks it):
   `{"geometry": "indian-ocean-v1", "mapping": "gdac-core-v1", "hash": "scientific-json-v2",
   "specification": "gdac-netcdf", "qc": "core-good-v1", "source_contract": "gdac-core-v1"}`.
2. Exact text: `numpy.format_float_positional(value, unique=True, trim="-")` of the stored
   numpy scalar, so the shortest decimal that round-trips float32 (PRES/TEMP/PSAL and
   errors) or float64 (LATITUDE/LONGITUDE). `Decimal(text)` feeds `scientific_number`, so
   `exact` is that text; `-0` becomes `0`. Because the float32 shortest text is rarely
   exactly representable in binary64, the `rounded` flag is expected on most measurements
   (as it is for most Argovis decimals). Verified on 3000 random float32 values (round-trip
   and one-digit-shorter fails) in `test_exact_text_...`.
3. Fills and non-finite: the variable's declared `_FillValue` (99999.0 here) is emitted as
   the token `99999` and becomes `argo_fill`; stored NaN/Inf become the quoted nonfinite
   tokens of contract 5.1. A fill in the middle of a profile stays a level with `argo_fill`.
4. Level trimming: a trailing row is dropped when PRES, PRES_ADJUSTED, TEMP, TEMP_ADJUSTED,
   PSAL and PSAL_ADJUSTED are all fill; every array of the document is cut to the same
   `n_levels`. A profile with no non-fill level at all is excluded (see 9).
5. Mode: the profile's `DATA_MODE` (R/A/D) is the `data_keys_mode` of pressure,
   temperature and salinity. R maps PRES/TEMP/PSAL (+`_QC`) to the original columns; A and D
   map `*_ADJUSTED` (+`_ADJUSTED_QC`) to the adjusted columns and `*_ADJUSTED_ERROR` to
   `*_error`. Only the selected variant is populated (like Argovis); `*_original_error` is
   always null; R never fills `*_error`. Negative error -> `negative_uncertainty`
   (contract 6). Blank/unknown mode with the variable present -> `unknown_data_mode`.
   Divergence from Argovis: Argovis never carries errors, so `*_error` is non-null for A/D
   GDAC levels (all-fill errors become an `argo_fill` dict with null value). A D-mode
   profile whose adjusted array is all fill stays all `argo_fill` (nothing falls back to the
   original; 1 such profile per fixture day for TEMP).
6. Units: source spelling from the file (`decibar`, `degree_Celsius`, `psu`) is the
   `*_unit_source`; canonical `dbar`, `degree_C`, `1` via the same `UNITS` table; unknown
   unit with a value -> `unknown_unit`. Plausibility bounds, `repeated_pressure`,
   `nonmonotonic_pressure`, `variable_absent`: identical to Argovis.
7. QC: characters through `argovis.qc`; digit 0..9 known, other characters `unknown_qc`.
   Blank (and NUL) becomes `""`: normalized QC null, `*_qc_source` `""`, no flag. (Argovis
   null is `None` for both; I kept the distinction because `qc("")` exists for it.)
   `position_qc` = POSITION_QC, `time_qc` = JULD_QC, `sampling` = VERTICAL_SAMPLING_SCHEME
   stripped (null when blank).
8. Time and position: JULD days since 1950-01-01 UTC, converted by
   `round(juld * 86_400_000_000)` microseconds, `isoformat(timespec="microseconds")`.
   Longitude/latitude exact text of the float64.
9. Identity and revision: `source_profile_id = "gdac:<platform>_<cycle><direction>"` (platform
   stripped, direction A/D), natural key unchanged. Revision
   `Revision("gdac-date-update-v1", (("file", DATE_UPDATE),))`. DATE_UPDATE is the
   regeneration time of the whole daily file, so every profile of a file shares it and a
   regenerated file advances every profile's revision (equal hash -> `revision_only`,
   different hash -> `newer`). The index carries a per-profile `date_update` that would be
   a finer revision; not used, per the brief.
10. Exclusions before the mapper (counted in the landing manifest `sanitization.excluded`):
    `no_position` / `no_time` (fill or illegal LATITUDE/LONGITUDE/JULD; these belong to no
    tile and the counts are file-level, repeated in each chunk's manifest) and
    `no_core_levels` (chunk-level). Argovis would have quarantined a zero-level profile
    (`invalid_array_length`); GDAC drops it with a count. Everything else reaches the
    mapper and quarantines the chunk on any `Rejection`, as for Argovis.
11. Ownership: `Tile.owns` on the exact-text coordinates and `Interval.contains` on the
    microsecond time, applied in the source. No epsilon polygon, so GDAC chunks never
    produce `overlap_duplicate` outcomes.
12. Completeness: every index row with `ocean == 'I'` owned by the chunk's tile and inside
    its interval must exist (by identity) among the profiles of the chunk's daily files, else
    `incomplete_inventory`. Profiles in the files and absent from the index are tolerated.
    Duplicate `_id` within a chunk -> `duplicate_inventory_id`. More than 2000 documents ->
    `profile_count_limit`, more than 128 MiB -> `decompressed_size_limit` (both split the
    chunk exactly as for Argovis).

## Interfaces added (all in `gdac.py`)

- `GDAC_HOST`, `GDAC_BASE`, `INDEX_KEY`, `ATTRIBUTION`, `VERSIONS`, `MAX_FILE_BYTES`.
- `fetch_file(path, deadline, *, max_bytes=128 MiB, attempt_seconds=3600) -> bytes`: path
  allow-list (index, a month directory listing, a daily basin file), DNS answer must be all
  global addresses, connection pinned to the validated IP with SNI/hostname check for
  `data-argo.ifremer.fr`, no proxy, no redirect (`upstream_redirect_rejected`), no
  credential or cookie, `Accept-Encoding: identity`, Content-Length / Transfer-Encoding
  framing checks, size limit while streaming (`gdac_file_size_limit`), truncated body,
  socket timeouts + monotonic checks (no signals, thread safe). It reimplements
  `public_addresses` / `PinnedConnection` / `read_body` because the `transport.py` versions
  are hard-wired to Argovis and capped at 16 MiB.
- `index_entries(raw, interval, tile) -> list[IndexEntry]` (also `scan_index`),
  `daily_file_keys(interval)`, `profiles_from_netcdf(source, tile=None, interval=None, *,
  name=None, excluded=None)`, `profile_identities`, `validate_netcdf`, `exact_text`,
  `wire_document`, `encode_wire`, `gdac_map_profile(document, budget, metadata=None)`
  (accepts a `profiles_from_netcdf` document or the landed wire document),
  `cached_file`, `cached_index`, `prepare_cache(cache_dir, interval, deadline)`,
  `GdacSource`.
- `GdacSource(repository, store, authority, descriptor, *, deadline, application_commit,
  require_existing=False, fetch=fetch_file, sleep, jitter, clock)`; descriptor
  `{"kind": "gdac", "cache_dir": ..., "index_sha256": ...}` (`prepare_cache` returns it).
  `obtain` roles: the three selection roles are derived from the chunk's daily files
  (parameters must equal `request_parameters(plan, ...)`, interval/tile come from
  `repository.chunk`), `metadata` synthesizes
  `[{"_id": "gdac:<p>", "data_type": "oceanicProfile", "platform": "<p>"}]`. Attempts use
  `recorded_reserve(..., "gdac")` and `finish_attempt(..., "verified_raw", 200, manifest)`;
  the manifest `sanitization` carries `derived_from: [{file, sha256, object_key}]`,
  `excluded`, `profiles`, `index_expected`, `index_sha256`. `restart_selection` raises
  `incomplete_inventory`. Reload with `require_existing=True` reads the recorded landing
  only (no cache access).
- Raw NetCDF preservation uses `publish_verified(..., raw="nc", validate=validate_netcdf)`
  (package C's actual API; the brief said `raw=True`), writing `raw/sha256/<sha>.nc`
  once per file for all tiles and source instances: `preserve` first calls
  `store.stat(raw/sha256/<sha>.nc)` and skips the PUT when an object of the right size exists
  (C's `MinioStore.write_immutable` sends the whole body even when the key exists, so
  without this a month would upload 100 tiles x 31 files x ~5 MB). The `.nc` objects have
  no `raw_manifest` row; they are referenced from the manifest JSON only.
- Wire shape: `_id`, `metadata ["gdac:<platform>"]`, `geolocation` (exact number tokens),
  `timestamp`, `cycle_number`, `profile_direction` for inventory; plus `source`
  (`[{"source": ["argo_gdac"], "url": ".../geo/...", "date_updated": DATE_UPDATE}]`),
  `geolocation_argoqc`, `timestamp_argoqc`, `vertical_sampling_scheme`, `data_info`
  (`pressure`, `pressure_argoqc`, `pressure_error` (A/D only), ... with `units` and
  `data_keys_mode`) and `data` for role `profile`. No `basin` or `date_updated_argovis`
  (the argovis `map_profile` cannot map this shape; use `gdac_map_profile`).

## Migration 0014 (`infra/migrations/versions/0014_gdac_source.sql`)

Drops and re-adds, with explicit names, the CHECKs (found by definition in a `DO` block that
raises `unexpected_check_constraints` unless exactly the expected number is found):
`argo_float.source`, `argo_profile.source`, `argo_profile.mapping_version` (now
`(argovis, argovis-core-v1) OR (gdac, gdac-core-v1)`), `ingestion_scope.source`,
`raw_manifest.object_key` (regex accepts `.json|.nc` and the digest check accepts both),
`ingestion_attempt.origin` (adds `gdac`), `ingestion_input.kind` (adds `gdac`).
`CREATE OR REPLACE app.reserve_recorded_attempt` identical to 0006 except origin `gdac` is
accepted (without it the first `recorded_reserve(..., "gdac")` raises `invalid_recorded_origin`).
New `app.gdac_owner_slot(timestamptz, numeric, numeric)` = `app.owner_slot` with prefix
`gdac/core/` and `/gdac-core-v1/` (there is no logical-key CHECK to relax; the key is only
produced by functions). Beyond the brief: `ingestion_scope`, `ingestion_attempt.origin`,
`ingestion_input.kind`, the recorded-origin function and `gdac_owner_slot`; each is
required for a gdac run to get past the database.
It assumes 0013 adds no CHECK matching `%argovis%` on `argo_float`/`argo_profile`/
`ingestion_scope` or `%captured%` on `ingestion_attempt`/`ingestion_input`.

## Files changed

- `packages/core/src/floatchat_core/ingestion/gdac.py` (new)
- `infra/migrations/versions/0014_gdac_source.sql`
- `scripts/gdac_fixtures.py` (new)
- `tests/stage1/test_gdac.py` (new, 105 tests)
- `tests/fixtures/gdac/{20250115_prof.nc,20250214_prof.nc,ar_index_indian_2025q1.txt,manifest.json}` (new)
- `docs/v4-packages/G.md` (this file)

## Tests added (tests/stage1/test_gdac.py)

Manifest/size; index excerpt counts (5,961 rows, all `I`), gz == plain, January partitions
across the 100 tiles with every row owned once (2,049), half-open interval and edge cases
(lat 30, lon 120), malformed rows, size/gzip bounds, identity parsing; `daily_file_keys`
(month, split half-day, midnight edges); NetCDF conversion of the real files (profile
count, a known profile's platform/cycle/direction/time/position/mode/first values, trimmed
levels against the raw arrays, tile/interval filters, Feb outlier); a synthetic NetCDF
builder for interior/trailing fill, NaN, blank QC, fill position/time, zero-level,
unknown mode, A/D/R selection, negative error, absent variable; mapper rejection
categories and wire rejections; exact-text property test; a hand-written one-level
canonical document compared byte for byte with its SHA-256; key-set equality with a real
`map_profile` output and type equality of level values; pinned hashes for three real
profiles (`jan_d` 2d0d9d8f..., `jan_r` 67708286..., `feb_first` 4ce8d4d1...); `fetch_file`
guards with monkeypatched sockets (allow-list, mixed/private DNS, address fallback,
redirects, 404/503, framing, sizes, transport errors, deadline, TLS/SNI, no credentials);
cache download-once with a thread test, `.nc` uploaded once across tiles/instances, index hashed once per file version, retry categories and backoff with a fake clock,
index digest pin, `prepare_cache`; `GdacSource` (three roles parse with
`json_stream.documents`, `inventory_identities` and `verify_inventory` accept them,
landed-document hash == converted-document hash, manifest/`derived_from`/raw `.nc` object,
metadata role, replay without cache, parameter/role/descriptor validation, index
completeness failure and non-failures, size and duplicate guards, empty selection);
the fixture script's `excerpt`; a static migration check.

## Measurements (ad hoc scratch scripts, not recorded under reports/)

- Offline, this host: converting one 97-profile file 3.0 s; mapping the 97 profiles
  10.6 s (about 0.11 s and 0.7 to 1.5 MB of canonical bytes per profile).
- `scan_index` over a synthetic 3.4M-line, 64 MB gzip index (real rows replicated with
  out-of-window years) for one month window: 6.4 s.
- Download rates: see "layout" above.

## Integration items for the integrator

1. Mapper routing. `Processor.map` calls `map_profile(doc, self.metadata(doc), budget)`.
   For runs whose input kind is `gdac` call
   `gdac.gdac_map_profile(doc, budget, self.metadata(doc))` instead (works on the landed
   documents). Do not use B's `map_profile(..., source_contract="gdac-core-v1")` for the
   landed shape: it reads revisions from `source` as `argovis-source-vector-v1` and
   requires `basin`/`date_updated_argovis`, which the GDAC wire does not carry.
2. Source construction: `GdacSource(repository, store, authority, descriptor, deadline=...,
   application_commit=..., require_existing=<state at/after landed>)` where the descriptor
   is the persisted run input. `persist_input(kind='gdac', descriptor)` needs migration 0014.
   `descriptor["cache_dir"]` must be a path both acquire and (if reloading) process hosts can
   read; with `require_existing=True` the cache is not touched.
3. CLI/admission: `ingest --source gdac --cache-dir ...` should call
   `gdac.prepare_cache(cache_dir, interval, deadline)` first (it returns the descriptor with
   `index_sha256`), then admit. `policy_versions("gdac-core-v1")` already exists in B's
   `argovis.py` and equals `gdac.VERSIONS`.
4. The admission functions in 0005/0010 hard-code
   `'argovis'`/`'indian-ocean-v1'` scope rows; a gdac run needs a gdac scope row (the CHECK is
   relaxed, the functions are not).
5. Publication SQL (F's 0013 `commit_publication`, and 0011): `source='argovis'` lookups and
   inserts on `argo_float`/`argo_profile`, the `science->>'mapping_version' IS DISTINCT FROM
   'argovis-core-v1'` check, and `app.owner_slot` (`argovis/core/...`) must be parameterized
   by `science->>'source'`; use `app.gdac_owner_slot` for gdac. Logical keys for gdac are
   `gdac/core/<yyyy-mm>/<west>:<south>/indian-ocean-v1/gdac-core-v1/scientific-json-v2`. The
   Python side (`objects`, `catalogue`, `coverage`, reporting key builders) must produce the
   same keys; I did not check them, they are other packages' files.
6. `processor.py` `FAILURES` (state `failed`, retryable) vs quarantine: categories raised by
   the GDAC source and not in `FAILURES`: `gdac_index_changed`, `invalid_gdac_descriptor`,
   `unapproved_cache_path`, `invalid_netcdf`, `netcdf_size_limit`,
   `unsupported_netcdf_packing`, `gdac_file_size_limit`, `invalid_index_line`,
   `invalid_request_parameters`, `invalid_request_role`. Download problems already use
   existing failure categories (`http_retry_exhausted`, `http_retry_deadline`,
   `upstream_transport_failure`, `io_deadline`), 404 included. Decide whether
   `gdac_index_changed` is `failed`.
7. Metadata: `Processor.metadata` lands one synthetic `/argo/meta` document per platform
   with its own recorded attempt (3 DB round trips). The package-E metadata cache does not
   apply to `GdacSource`; the integrator may skip metadata landings for gdac (the pointer
   `gdac:<platform>` is self-describing; `gdac_map_profile` works with `metadata=None`).
8. Leases: a single `fetch_file` blocks up to `attempt_seconds` (3600) without a heartbeat;
   `GdacSource` heartbeats per file and in retry waits only. Prefetch with `prepare_cache`
   before the run, or make sure the lease outlasts the longest download.
9. Memory: a chunk holds at most 128 MiB of wire pieces, plus the joined payload and the
   `sanitize_raw` output at once (about 3x) per acquire thread; each concurrent chunk of a
   month shares the cache files through an `flock`, so downloads are serialized per file.
10. The reporting SQL (0006/0013) groups attempts by `origin` and filters `origin='http'` for
    HTTP request counts, and reads `input_kind` from `ingestion_input`; gdac attempts show up
    under their own origin. I did not review it beyond that.
11. Optional: use `scan_index`/`index_entries` for the per-profile `date_update` if a finer
    revision than the file-level DATE_UPDATE is wanted (changes `gdac-date-update-v1`).

## Open questions and risks

- DATE_UPDATE is a file-level regeneration stamp (see rule 9); revisions therefore move
  for every profile whenever upstream rebuilds a daily file.
- DATA_MODE is per profile and applied to all three variables because the merged files have
  no PARAMETER_DATA_MODE; a profile with mixed per-parameter modes would be mis-selected.
- Multi-profile cycles (several N_PROF with the same platform/cycle/direction) did not occur
  in the two fixture days. If they occur, the chunk is quarantined with
  `duplicate_inventory_id`; check more days before the full backfill.
- netCDF4/HDF5 parses downloaded files in-process. Files come from the pinned HTTPS host,
  are size-capped and must open before entering the cache, but a malformed HDF5 file can
  still crash the process; subprocess isolation would remove that risk.
- Migration 0014 has not run against PostgreSQL. `test_database.py` is the first real check.
- Messages for package F arrived on my channel (a `Repository.ticket(authority, kind)`
  5-argument `app.processing_ticket` call, `SAFE_DATABASE_CATEGORIES` additions from
  D.md, and `Repository.extend_unstarted_leases(run, epoch)`). I own no part of
  `repository.py` and the task forbids editing outside my files, so I did not apply them;
  they need re-routing to package F.

## Integrator note
Migration 0014 now keeps the `cache` attempt origin introduced by 0012 (the routing note never reached this package).
