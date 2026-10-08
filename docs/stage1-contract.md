# Stage 1 data-foundation contract

Status: **Astra GO for stage1-v2**, confirmed by the owner on 2026-10-06.
The owner separately instructed Stage 1 implementation; the contract gate is passed.
Implementation/offline CI/live acceptance and implementation review remain separate gates.
The implementation NO-GO after the incomplete owner run is historical. ADR-0039 replaced
the Astra gate with advisor review, and ADR-0040 activated the
[S1-SOURCE-2 proposal](stage1-source-policy-proposal.md) as **stage1-v3** (see §1).
The [consolidated blocker matrix](../reports/stage1-blocker-review.json) controls
current implementation readiness; historical preparation GO is withdrawn.
Contract version: stage1-v3 amends stage1-v2 (§1); stage1-v2 superseded the unapproved stage1-v1 candidate. Prepared against fresh sanitized Stage 0 commit
`619411a` on `codex/stage-1`, in `/home/floatchat/FloatChat-stage1`.

## 1. Authority, boundary and review evidence

The owner's original contract-hardening instruction controlled preparation. The latest owner
instruction authorizes Stage 1 implementation after Astra GO. For Stage 1
implementation, this contract and ADR-0018 through ADR-0032 override ambiguous Stage 1
wording in the PRD and build prompts. Stage 0 security, permissions, isolation and
local-service decisions remain in force. The wider PRD describes later product scope.

The original preparation turn changed only this document, the PRD, build prompts,
decisions and progress; it created no implementation or resources. Implementation now
follows the approved scope, without cloud provisioning or destructive lifecycle work.
Only the fresh sanitized checkout is a source;
the preserved Windows checkout is neither read as source, merged nor published.

Future Stage 1 supplies internal ingestion, its CLI, scientific storage, publication,
durable evidence and an internal catalogue-selection function. Stage 2 owns the query
API, SQL/DuckDB query engine and public query plans. Dashboards, RAG, exports, forecasting
and user-facing historical jobs remain in their existing later stages. An isolated
historical acceptance ingestion is an engineering demonstration, not a user-facing job.

The owner's twelve requirement groups and Astra's complete eight-section NO-GO review
are review evidence for this candidate. The attachment was read completely, read-only;
its recommendations do not authorize implementation. Section 12 traces both the review's
findings and its twelve missing-test areas to explicit tests. No Astra approval,
implemented test result or live acceptance result is inferred here.

Astra's subsequent five-blocker contract review is also evidence for this revision.
Sections 2, 5-11 and the follow-up cross-check in §12 resolve retained-snapshot populations,
empty refreshes, publication-time conflicts, recovery/cancellation/overlap and bounded
numeric conversion. Stage1-v1's inconsistent wording is replaced, not an alternate policy.

**Amendment stage1-v3 (ADR-0039 through ADR-0042).** stage1-v3 is stage1-v2 plus
ADR-0040 (S1-SOURCE-2 qualified delivered population), ADR-0041 (S1-RESOURCE-3:
monthly plan v2, 40 GiB run canonical cap) and ADR-0042 (worker memory criterion).
It is effective only for runs admitted with the stage1-v3 run policy
(`RUN_POLICY.source_policy = "S1-SOURCE-2"`); earlier runs and their recorded 44 failures
and 8 quarantines keep stage1-v2 unchanged. Advisor review replaces the Astra gate (ADR-0039).
Where a rule below differs, the text marked stage1-v3 applies to stage1-v3 runs.

## 2. Time and environment contract

At run creation, capture exactly one immutable `run_reference_time_utc` (T), store it
with mode and environment identity before planning, and use it for every chunk,
retry, recovery, inclusion calculation and retention proposal. Retries of the same run
reuse T; a separately created run captures its own T. Capture actual UTC from the
system clock in normal mode. Do not recalculate T at month boundaries during a run.

Normal-mode PostgreSQL eligibility is `[T minus 12 calendar months, T)`; the hot Parquet
eligibility is `[T minus 3 calendar months, T)`. Calendar subtraction preserves UTC
time of day and clamps an invalid day to the last day of the destination month.
Membership uses observation time, not arrival time. Reject normal CLI intervals outside
the PostgreSQL interval rather than silently loading historical observations. A month
argument includes that entire named month; a range extending beyond T is rejected.
Daily ingestion uses explicit timestamps ending at T instead of a future month end.
No normal-mode reference-time override is exposed.

The acceptance demonstration uses T = `2025-04-01T00:00:00Z`, exclusively in a disposable,
isolated acceptance environment. Its `--from 2025-01 --to 2025-03` interval is exactly
`[2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z)`. Thus PostgreSQL eligibility is
`[2024-04-01T00:00:00Z, 2025-04-01T00:00:00Z)`, and all demonstration months fall in
the acceptance hot tier. End boundaries are excluded; UTC offsets are normalized
without losing supported microsecond precision.

The future command is:

`floatchat ingest --mode acceptance --region indian-ocean --from 2025-01 --to 2025-03`

Acceptance mode requires a matching environment marker in a separate database and
separate MinIO buckets, Redis namespace/queue, Compose project/volumes and restricted
configuration. A production or unmarked environment rejects it before any write.
Production configuration never imports this reference time or demonstration watermarks.
Acceptance teardown requires separately explicit disposal of that environment.

Stage 1 records retention eligibility and dry-run proposals only. It does not delete,
detach, expire, archive away or hide old production science as rolling retention.
Previously accepted out-of-window observations remain in PostgreSQL and full stored
snapshots until separately authorized lifecycle action. A later cutoff never removes
them from a rebuilt snapshot. Normal runs admit new/changed scientific candidates only
when eligible under that run's immutable T. Run eligibility and full stored-snapshot
membership are separate populations and reconciliation scopes (§11). Ingestion supersession of verified revisions is
allowed and is distinct from retention destruction.

## 3. Geography and selected upstream contract

### 3.1 Versioned operational geometry

`indian-ocean-v1` is an explicit operational envelope, not a claim to reproduce a
hydrographic basin boundary. Its WGS84/SRID 4326 polygon is:

`POLYGON((20 -60,120 -60,120 30,20 30,20 -60))`

Equivalent GeoJSON coordinates are
`[[[20,-60],[120,-60],[120,30],[20,30],[20,-60]]]`.
Coordinates always mean longitude then latitude in decimal degrees. Accepted source
longitude range is [-180,180], latitude [-90,90], both finite. Reject out-of-range
coordinates; do not swap axes or silently modulo-wrap them. Normalize signed zero.
The geometry has no antimeridian crossing. Region membership uses planar WGS84
polygon coverage, equivalent to PostGIS `ST_Covers` on geometry, including all four
outer edges and corners. Use geography for distance in later stages, not for changing
this membership rule. Missing-location warnings invalidate source placeholder points.

Persist the version and SHA-256 of the UTF-8 WKT exactly as printed above (without
backticks or newline) in each plan and catalogue snapshot. Geometry changes create a
new version; never reuse a version for a different shape.

Planning divides the requested interval into contiguous UTC slices. stage1-v3 plan v2
(`indian-ocean-plan-v2`, ADR-0041) uses whole UTC calendar months clipped to the request
(270 roots for Jan-Mar 2025); stage1-v2 runs used <=7-day slices additionally split at
month boundaries. Tiles and slices cover the complete requested space/time with
no gaps; sort and persist the full bounded plan before fetching. Adaptive subdivision
preserves that coverage and records parent/child relationships. Observation ownership,
not expanded fetch coverage, determines scientific membership.

Initial tiles are 10-degree rectangles inside the envelope, starting at (20,-60).
Fetch polygons include their edges and a 0.000001-degree expansion, clipped only to
legal WGS84 coordinate ranges, including expansion past the region's outer envelope
to avoid source-edge exclusion. Reapply exact local geometry and UTC
filters after parsing. Tile ownership is west/south inclusive, east/north exclusive,
except the outer east/north edges remain included. Repeated results in adjacent
expanded tiles have one owning tile and one profile identity. Record other tile
occurrences as overlap duplicates, not extra scientific rows. Never merge different
directions or distinct profile IDs because they share position or pressure.

### 3.2 HTTP wire contract and completeness

Use the [Argovis core OpenAPI contract at release 2.36.2](https://github.com/argovis/argovis_api/blob/2.36.2/core-spec.json)
as the selected request specification. GET `https://argovis-api.colorado.edu/argo`
supports `startDate`, `endDate`, `polygon` and `data`; `polygon` is a JSON string of
closed [longitude,latitude] vertices, not a GeoJSON request body. Use a URL encoder.
Select `data=all`; this avoids filtering away profiles missing one core variable.
Omitting `data` returns inventory metadata; `id` selects a profile, and
`/argo/meta?id=...` resolves metadata pointers. Do not request `compression=minimal`,
invent cursor/page parameters, or reuse legacy box routes.
[Official Argovis download example](https://github.com/argovis/ocean_pipeline/blob/main/argovis-dl.sh)
documents credential transport in the `x-argokey` header.

Freeze the selected specification release, its downloaded-byte SHA-256 and the parser
mapping version in fixture manifests during later implementation. Fail closed on
unsupported schema drift; a future source version requires a contract update.

### 3.2 Translator-backed source supplement S1-SOURCE-1

The owner's supplied Astra implementation review selects resolution B. The new source
contract is `argovis-core-2.36.2+ifremer-fluorescence-v1`; its base remains the pinned
OpenAPI 2.36.2. Recognize only the two exact additive names `chla_fluorescence` and
`chla_fluorescence_qc`. These names are absent from the base OpenAPI enumeration;
this is an explicit supplement, not a claim that upgrading OpenAPI resolves the mismatch.
[Official translator](https://github.com/argovis/ifremer-sync/blob/cbf2bb48ed5d95532c18bb2cd5217e44618356cf/util/helpers.py#L49-L90)
maps CHLA_FLUORESCENCE separately from CHLA and likewise their QC.
Pin revision `cbf2bb48ed5d95532c18bb2cd5217e44618356cf`, file `util/helpers.py`,
downloaded-byte SHA-256 `279af8ef7b2adabad38d94ca71de02d86dd11efe28e3c1f174f874b7ed73224f`.
The machine-readable pin is `docs/upstream/argovis-source-supplement-v1.json`.

Validate the same unique column names, equal level lengths and aligned unit/data-mode
attribute vectors as other source columns. Supplementary values/QC are scalar numbers,
strings or null; unit/data-mode attributes are strings or null. Malformed structures
quarantine. Preserve exact values, QC and attributes in immutable sanitized raw evidence
as non-core fields. Perform no chlorophyll aliasing or canonical scientific mapping.
Core mapping/hash versions remain unchanged. New request identities and provenance pin
the supplemented source contract and translator revision/checksum. Previously recorded
manifests remain immutable and validate under their original version.
`argovis-core-2.36.2-v1` rejects these additions. Keep `data=all`; every other unsupported
field, including invented aliases or error columns, still rejects. Candidate inventory
under the supplement does not prove a complete profile, A-mode values or current availability.

Each bounded chunk fetches inventory without data before and after its full-data
response. All locally eligible identity sets must match; use upstream IDs normally and
complete natural keys only for the explicitly versioned ID-less fallback exception in §4.
Every identity must have one resolvable,
complete profile document. Retry a changing inventory within the same budgets.
Check transport EOF, declared byte length where present, JSON termination, supported
schema, upstream warnings/errors and inventory/data agreement. This contract assumes
the documented array response represents the full requested selection: Argovis does
not provide a transactional snapshot guarantee here. Record inventory hashes and
this limitation; do not claim a global historical census. Syntactically valid
data missing an inventoried ID is incomplete, not empty.

The selected endpoint has no documented pagination parameter. Unexpected pagination,
continuation or truncation indicators fail closed; a missing page in a later supported
paged adapter must likewise fail. Never follow an undocumented continuation URL.
Successful empty coverage requires verified terminal 200 responses with empty matching
inventories and data, valid structure and zero truncation/error indicators; 404, a
timeout, missing data, exhausted retries or an unparseable response is never empty,
except the stage1-v3 S1-SOURCE-2 empty-delivery receipt (ADR-0040). Only `/argo` selections
with exactly startDate/endDate/polygon (both inventory roles) or those plus `data=all`
(profile role) qualify, and a response qualifies only as HTTP 404, `application/json`
(any charset), complete framing and a raw body of at most 64 bytes that parses to exactly
an empty JSON array (the deployment sends `[\n\n]\n`). All three roles must share one status;
a mixed 200/404 triple is retried like a changing inventory and fails after the selection
budget. Error envelopes, nonempty/malformed bodies, other content types, truncation, `id`
requests and `/argo/meta` remain failed 404s. The receipt is persisted as verified raw
evidence with `raw_manifest.http_status = 404` and proves "no service-returned eligible
documents", never "no source science".

## 4. Scientific identity and relational constraints

All domain tables belong to the Stage 0 `app` schema and migration role. Extension
metadata remains read-only outside it. Use UUID identifiers, UTC timestamptz, finite
float64 scientific values and explicit checks. The following is a future schema
contract, not a migration in this turn.

| Entity | Required identity and database constraints |
|---|---|
| argo_float | UUID primary key; non-null source and platform_number; UNIQUE(source, platform_number) and UNIQUE(id,source). Never change platform identity through a metadata refresh. |
| argo_profile | Unpartitioned identity registry; UUID primary key; non-null source, float_id, observed_at, observation_month, position, content_hash, hash_version, positive level_count and committed provenance. Composite FK (float_id,source) to argo_float(id,source). Partial UNIQUE(source, source_profile_id) WHERE source_profile_id IS NOT NULL. |
| Fallback natural key | UNIQUE(source, float_id, cycle_number, direction, identity_observed_at, observation_segment) WHERE fallback_complete. Non-null fallback_complete must equal the predicate that all six fields are non-null and direction is A or D; a CHECK requires it when source_profile_id is absent. Thus stable-ID profiles with complete fallback fields cannot bypass this index by setting the flag false. |
| core_measurement | Monthly RANGE partition on observation_month. Primary key (observation_month, profile_id, level_index). Non-negative level_index; composite FK (profile_id, observation_month) to the profile registry. No pressure-based uniqueness. |
| Profile/month link | Registry UNIQUE(id, observation_month); CHECK observation_month equals the UTC month start of observed_at. Every monthly child bound is [month_start,next_month_start), including the partition key in every child PK/unique constraint. No default catch-all partition; an absent child fails before publication. |
| Runs/chunks/attempts | Run UUID PK; chunk UUID PK and UNIQUE(run_id, logical_chunk_key); non-null run FK, interval, tile, plan_version, state; attempt PK with UNIQUE(chunk_id, attempt_number). All FK links RESTRICT deletion. State events and outcome rows have durable sequence identities. |
| Logical partition slot | Non-null environment/logical-key composite PK; non-negative monotonic slot_version and current stored membership manifest reference. All catalogue generations/stored-domain evidence link the slot with RESTRICT deletion. |
| Catalogue | Partition UUID PK; UNIQUE(environment_id, logical_partition_key, generation); non-null object key, SHA-256, byte/count/schema/geometry evidence and state for materialized generations. Partial UNIQUE(environment_id, logical_partition_key) WHERE status=active. FK to publication/chunk/run evidence with RESTRICT deletion. |

Source = `argovis`. Prefer the upstream `_id` as an opaque stable identifier; do not
regenerate it by concatenating platform/cycle. Resolve platform from the linked metadata
document, retain the original ID, and preserve explicit `profile_direction`.
IDs/platform/segments must be non-empty when present, with maximum UTF-8 lengths
512/32/128 bytes respectively; cycles are non-negative integers. Database CHECKs enforce
these limits, finite coordinate ranges and non-negative scientific uncertainty values.
Direction is A or D; U (unknown) is allowed only with a stable upstream ID. Never default
missing direction to ascending. Opposite directions must remain distinct even within
one cycle.

Fallback uses immutable source observation identity: source/platform, cycle integer,
direction, observation timestamp captured as `identity_observed_at`, and observation
segment. The segment is an explicit source discriminator when supplied; otherwise
`single` is used for the selected Argovis single-document profile representation.
Do not use retrieval time, `date_updated_argovis`, source update time, location, data
mode or content hash as identity. FloatChat normalization permits a missing stable ID only
when all fallback fields are complete, as a versioned internal exception to the selected
API's required _id. Record the exception; do not claim Argovis documents ID-less responses.
Synthetic missing-ID tests exercise it; other required schema losses quarantine.
A profile with neither a stable ID nor a complete fallback is quarantined.
Scientific corrections to a fallback identity field cannot be
guessed to be the same profile; quarantine and require a reviewed alias decision.

Match stable ID first, then a complete natural key. A later stable ID matching an
existing fallback row attaches an alias transactionally without creating science.
A stable ID and natural key resolving to different rows, or a second differing stable
ID for the same natural key, is an identity conflict; quarantine, never coalesce.
Concurrent insert conflicts are re-evaluated under locks and these unique constraints.
Changing explicit A to D under the same stable ID is an identity conflict.
For an ID-less candidate with no exact key match, check source/platform/cycle/direction/
segment under a lock on that context before insertion. An existing fallback with a
different observation timestamp is a possible correction and quarantines; never create
a second identity to evade the correction rule. Concurrent admissions lock the same
context as well as the full key. A genuinely distinct observation needs an explicit
source segment discriminator, not an invented retrieval timestamp.

Cycle_number may be null only with a stable upstream ID. Direction is non-null A/D/U;
U requires that stable ID. Fallback timestamps/segments may be null only when a stable
ID exists and the fallback is incomplete. Timestamp,
platform and position are required for publication. Revision tokens and optional source
metadata may be null; missingness is recorded, never fabricated. Profile provenance uses
non-null created_run_id, last_scientific_run_id and last_chunk_id FKs with RESTRICT deletion
and a reference to the verified raw manifest; raw manifests link attempts/chunks/runs
with RESTRICT. SHA-256 fields CHECK exactly 64 lowercase hex characters. Composite keys prevent
a measurement from belonging to a different month/profile. Profile deletion cascades
only to its measurement children after explicit lifecycle authorization; float deletion
is RESTRICT. Runs, raw provenance, quarantine and catalogue references are RESTRICT,
never erased by scientific replacement. Ordinary Stage 1 roles do not delete profile
registries. Replacing a level set within a locked profile is allowed.

Loading uses client-streamed COPY FROM STDIN into fixed migration-owned staging tables
in app, followed by parameterized SQL. Identifiers are an internal allowlist, never
request-derived; SQL values are bound parameters. The ingestion role can insert staging
rows and execute only the controlled merge/state procedures required here. Do not grant
CREATE/ALTER/DROP, server-file/program access, superuser, extension writes, bootstrap
credentials or unrestricted target-table DML to workers. Staging rows are run/chunk-scoped;
cleanup deletes only those rows through the controlled procedure. Object privileges are
limited to private configured raw/tmp/normalised prefixes, without bucket administration.
Controlled merge procedures fix their search_path to trusted migration/extension schemas,
bind values and check caller/run ownership; workers cannot replace the procedures.

Future migrations are additive from the accepted Stage 0 baseline and preserve extension,
configuration, fixture and existing application data. If any existing scientific rows are
encountered, preflight identity/month constraints and fail with a diagnostic rather than
truncate or guess a backfill. Repeat upgrade is idempotent; unsafe downgrade is refused.
An unused bgc_measurement schema may be created later, with explicit keys/FKs and without
BGC ingestion; it is not required to demonstrate core scientific ingestion.

## 5. Revisions and canonical content

Store source revision kind/token separately from identity and audit timestamps.
For Argovis use a sorted vector of source-document identifiers and their
`source[].date_updated` values when all contributing source documents provide them.
Identifiers use source labels and a sanitized stable source path, never credentials.
Do not reduce multiple source dates to their maximum: that can conceal a stale component.
Mirror/retrieval update timestamps remain provenance, not ordering authority.

Vectors are comparable only with identical source-document keys and revision kind.
A new vector is newer if every component is >= stored and at least one is >; stale
if every component is <= stored and at least one is <. Mixed component movement,
changed key sets/kinds or missing metadata on one side is unordered. Unordered equal
content is a no-op with a warning; unordered different content is quarantined.
When both sides lack usable revision metadata, compare scientific hashes.

Canonical hash `scientific-json-v2` is SHA-256 of UTF-8 canonical JSON with sorted object
keys, no whitespace and explicit nulls. Parse finite JSON numbers as exact decimal only after the bounds in §5.1 are checked.
Encode accepted numeric values as bounded normalized decimal strings (no exponent,
no trailing fractional zeros, exact signed zero becomes 0), not float64 renderings.
This retains exact source decimals even when two decimals round to the same stored float. Order levels by source
index and fields by the schema. Include observation time/position/QC, platform/cycle/
direction, sampling metadata, every scientific column, units, data modes, missing-value
reason and unknown-QC tokens. Exclude fetch/run IDs, credentials, raw byte formatting,
revision tokens and mutable retrieval/update timestamps. Hash the normalized content
before float64 storage conversion; retain the canonical document in evidence. Normalize
timestamps as UTC ISO 8601 with exactly six fractional digits. Internal UUIDs/aliases
are not scientific hash fields. The canonical document has a profile metadata object
and a levels array; every declared scientific field appears, including explicit nulls.
Null reasons are distinct from absent original/adjusted fields. Pin hash/schema versions;
a hash-version change requires explicit comparison/reprocessing, never blind replacement. The v2 numeric rules apply to this not-yet-implemented contract;
there are no approved v1 scientific rows to migrate. A future hash-policy upgrade cannot
silently compare unlike hash versions.

### 5.1 Bounded decimal conversion and nonfinite representations

The decoder accepts strict JSON numeric grammar, never a permissive parser's default
NaN/Infinity extensions. Validate tokens before constructing Decimal or expanding exponents:
- At most 128 ASCII bytes per finite numeric token, including sign, dot and exponent.
- Written exponent magnitude at most 400, checked on its bounded digit string.
- At most 512 UTF-8 bytes per normalized exponent-free numeric string, including sign
  and leading 0. Estimate required length using digit count/decimal scale before expansion.
- At most 16 MiB per canonical profile document, 256 MiB per chunk's canonical documents,
  and 10 GiB (stage1-v3: 40 GiB, ADR-0041) canonical bytes per run including repeated
  conversion work. Count while streaming/hashing; do not assemble an unbounded intermediate string.

Check order is strict JSON grammar, token length, written exponent, estimated normalized
numeric length, field semantics/fills, float64 conversion, then streamed document/chunk/
run canonical-output budgets. Do not use context-sensitive Decimal.normalize/quantize
to round the source before hashing; exact coefficient/scale operations preserve it.

Token/exponent/output-limit violations quarantine the whole chunk with
numeric_token_limit, numeric_exponent_limit or canonical_output_limit evidence. They
are not retries, fill values or empty coverage. No scientific profile hash is certified
for a rejected profile; its raw SHA-256 and validation reason are retained. These limits
apply even to a numeric token that would otherwise denote a fill marker.

Apply field-specific exact integer/range/fill checks first. For non-fill scientific values
and coordinates, convert the exact decimal to IEEE-754 binary64 using round-to-nearest,
ties-to-even, independent of locale and ambient Decimal context. Store the resulting
binary64 bits identically in PostgreSQL and Parquet. Exact decimal zero stores positive
zero; an accepted nonzero value may never silently become zero. If conversion would
produce infinity, quarantine as float64_overflow. If a nonzero exact decimal rounds
to either signed zero, quarantine as float64_underflow. Finite nonzero subnormal results
are accepted, with a subnormal flag. Other finite rounding is accepted with a rounded
flag iff the exact binary64 value differs from the source decimal; plausibility warnings
still apply. Flags are deterministic scientific content and part of the canonical hash.
Identity integers/QC codes are validated exactly, never rounded to invent identity/QC.

Quoted measurement tokens exactly "NaN", "Infinity", "+Infinity" or "-Infinity" are
accepted only in core scientific value/error array cells. Map them to null with
missing_reason=nonfinite and nonfinite_kind=nan/positive_infinity/negative_infinity;
"Infinity" and "+Infinity" share the same canonical scientific representation and hash.
Bare NaN, Infinity, +Infinity and -Infinity are invalid JSON: quarantine the payload
without generating normalized scientific rows/hashes. Other quoted spellings, whitespace,
case variants, "inf", "+NaN" and quoted finite numbers are rejected as invalid scientific
numeric strings. Nonfinite coordinates/identity fields quarantine regardless of spelling.
Nulls/fills remain distinct missing reasons; no nonfinite case writes float64 NaN/infinity.

Canonical hashes are SHA-256 of the exact accepted decimal strings plus the declared
flags/null reasons, not of rounded float64 text. Equivalent finite tokens (1, 1.0, 1e0)
hash equally in the same profile; distinct exact decimals that round to the same binary64
can hash differently. Future fixture expectations must hard-code independently derived
canonical bytes, their SHA-256 and expected float64 bit patterns. Rejected conversions
have no scientific hash, not a hash of coerced zero/null.

| Incoming comparison | Scientific outcome |
|---|---|
| No stored identity | Insert validated profile and complete level set. |
| Equal comparable revision and equal hash | Scientific no-op; no new active generation. |
| Equal comparable revision and different hash | Conflict; quarantine incoming evidence, retain stored science. |
| Newer comparable revision | Replace the entire profile level set transactionally, even if shortened; update the revision. Equal scientific hash updates revision metadata only and reuses the active scientific snapshot. |
| Stale comparable revision, equal or different hash | Record stale_skip; never overwrite newer science or change active partitions. |
| Both revisions absent, equal hash | Scientific no-op. |
| Both revisions absent, different hash | Unordered conflict; quarantine. A hash proves difference, not which version is newer. |
| Other unordered revision, equal/different hash | No-op warning / quarantined conflict respectively. |

Decide under row locks in a transaction. A newer replacement deletes that profile's old
levels and inserts exactly indices 0..N-1 in the same transaction; a zero-level replacement
is quarantined as structurally unusable. A crash rolls back both removal and insertion.
A timestamp/position correction using a stable ID reassigns month/tile ownership and
rebuilds every affected partition; fallback identity remains frozen. A correction
moving a known normal profile outside the run's eligible interval or configured geometry
is quarantined for later
lifecycle review instead of leaving mismatched PostgreSQL and Parquet states.
Absence from a later source selection is not a deletion instruction; retain committed
science and report the source-selection change. Stage 1 does not infer tombstones.

Scientific no-op includes zero inserts, deletes or changes to profile scientific fields,
measurement levels, float identities and active catalogue generations. Revision metadata
may advance; ingestion run, chunk, attempt, audit, duplicate and warning rows may grow.
An exact replay keeps scientific hashes/level sets and active generation IDs unchanged;
raw blobs may be reused by SHA-256. Do not promise that every table's row count is unchanged.

## 6. Scientific mapping and validation

Mapping version `argovis-core-v1` follows the
[official JSON structure example](https://github.com/argovis/demo_notebooks/blob/main/introduction/Argovis_JSON.ipynb):
names and units/data modes are resolved from `data_info`, never fixed array positions;
matching indices in the measurement arrays refer to the same source level.
The documented [Argovis Argo merge policy](https://argovis.github.io/hackathon22-docs/data_management/argo_merge.html)
selects adjusted data for A/D modes and original data for R. Argovis may omit the other
variant and error arrays. Preserve upstream availability; do not claim to reconstruct
the original NetCDF or invent adjusted/error request names.

For each core variable, require the following columns in PostgreSQL and Parquet.
Every numeric/scientific metadata column below is nullable where absent upstream;
`level_index` is non-null and retains source order, including repeated pressures.

| Variable | Original | Adjusted | Original QC | Adjusted QC | Adjusted error | Unit | Data mode |
|---|---|---|---|---|---|---|---|
| Pressure | pressure | pressure_adjusted | pressure_qc | pressure_adjusted_qc | pressure_error | pressure_unit | pressure_data_mode |
| Temperature | temperature | temperature_adjusted | temperature_qc | temperature_adjusted_qc | temperature_error | temperature_unit | temperature_data_mode |
| Practical salinity | salinity | salinity_adjusted | salinity_qc | salinity_adjusted_qc | salinity_error | salinity_unit | salinity_data_mode |

Also preserve `*_unit_source`, `*_qc_source`, `*_adjusted_qc_source` and per-field
missingness/validation flags; preserve any separately supplied original error as
`*_original_error`. Error means standard uncertainty only when the source declares
that meaning; otherwise preserve it with an error-kind flag. Never copy adjusted error
to original error. Supplied finite uncertainties must be non-negative; negative error
values quarantine the profile, while missing/nonfinite errors use the missingness policy.
Profile-wide mode is nullable provenance; per-variable mode wins.

For the selected wire format a variable with R mode maps its value/QC to original
columns; A or D maps to adjusted columns. If an explicitly documented alternate source
field supplies the other variant, preserve it with a separately versioned mapping and
fixture. Unknown/missing mode with a supplied value cannot safely choose a variant and
quarantines the profile. Missing a variable entirely produces null columns, not a
discarded profile. Map QC and errors to the same variant as their declared source.
Modes are R/A/D, independently for pressure, temperature and salinity.

Canonical units are dbar, degree_C and dimensionless practical salinity (PSS-78,
represented as `1`). Whitelist source spellings decibar/dbar, degree_C/degrees C and
psu/PSU/PSS-78/1 for practical salinity; also accept degree_Celsius for temperature
as documented in the official JSON example. Retain the exact source unit. No numerical
conversion is performed for those spellings. Any other unit with a supplied numeric
value quarantines the profile; do not assume Kelvin or absolute salinity is equivalent.
Absent units with supplied numbers also quarantine. Entirely absent variables may have
null units/modes.

Fill handling: JSON null, declared source fill markers and Argo numeric 99999 are mapped
to SQL/Parquet null with distinct missingness reasons and original tokens in raw evidence.
Only the exact quoted nonfinite measurement/error tokens accepted by §5.1 become null
with a nonfinite warning and canonical kind. Bare nonstandard JSON NaN/Infinity tokens
quarantine the payload; finite decimal overflow and nonzero underflow quarantine rather
than becoming null or zero. Other quoted numeric strings are rejected. Decimal bounds,
rounding and scientific-hash semantics are normative in §5.1.
Magnitude alone is not a fill test. Fixed diagnostics flag pressure outside [-5,12000]
dbar, temperature outside [-5,50] degree_C and salinity outside [0,50], without deleting
or changing finite values; Stage 1 acceptance accounts for warnings.

All present original/adjusted/QC/error arrays must have the identical positive N and
align with `data_info`; data-document metadata takes precedence over linked metadata
for optional unit/mode attributes, while required structural fields must still exist; absent arrays are expanded to N nulls. Reject mismatched lengths,
duplicate variable names, unknown core field shape and excessive N. Never zip-truncate,
pad a short supplied array or sort away duplicate pressures. Recognized non-core arrays
from `data=all` are retained raw and counted as outside core scope; their scientific
ingestion is deferred. Unknown shape or names absent from the pinned schema quarantine.

QC vocabulary is strings 0..9. Null/blank is missing; 0 is a present unknown-quality code.
Unknown QC tokens are retained verbatim in source columns, normalized QC becomes null
and a warning marks them ineligible for good-QC selection. Ingestion retains known poor
QC levels too. Good-QC policy `core-good-v1` selects 1 or 2 only, independently per value,
and never substitutes adjusted QC for original QC. QC filtering in later queries does
not delete stored source levels. Repeated/non-monotonic pressures produce diagnostics;
a malformed entire profile is quarantined, not partially rewritten.

## 7. Publication, catalogue selection and recovery

SHA-256 of actual object bytes is the content checksum. An S3/MinIO ETag is optional
transport metadata only, never an integrity hash, including multipart uploads.
Raw and scientific objects are immutable and content-addressed. A catalogue logical
partition is (environment, source, core dataset, UTC observation month, owning tile,
geometry version, mapping/schema/hash version). A generation contains the full currently
accepted stored profile/level set of that logical month/tile, including observations
retained outside a later run's eligibility window, not just the chunk's eligible increment.
Only superseded profile revisions/obsolete levels are excluded as "older scientific state";
old observation dates are retained until separately authorized lifecycle action.

Persist two distinct coverage records in the chunk's publication transaction:
- Fetch receipts: exact requested interval/tile, inventories/raw hashes, run T and upstream
  disposition (profiles_returned, verified_empty_fetch or source_absence_over_retained).
  They prove completed source-request coverage at that fetch, never deletion authority.
- Stored-domain evidence: active generation ID/full stored membership manifest;
  empty_stored_selection verified under locks for an exact selection without stored
  profiles; or empty_stored_domain for a full slot after an accepted ownership correction.
  It describes accepted stored science, not the upstream inventory.

A monthly slot name never proves a full month was fetched. Selection reports completed
fetch-receipt coverage, matching stored generations/empty-domain evidence and any gaps
separately. An empty fetch receipt cannot override a nonempty stored generation. Evidence
is versioned and receipt IDs/times are returned; no promise of a permanent upstream census.
Supersession preserves completed fetch receipts as historical evidence, and updates
stored-domain membership in the same transaction as the accepted correction. A persisted
logical-slot version exists even without an active object; increment it only for accepted
scientific membership changes. Tie generations and empty evidence to that version.
Selection uses one consistent catalogue snapshot and current slot membership; older
empty evidence cannot conceal subsequently accepted profiles. Empty/no-op fetches retain
slot versions, and historical fetch receipts never overwrite stored membership.

Persist a publication intent with chunk, candidate hashes, base generation IDs, expected
profile revisions and lease before writing. Chunk/publication lease TTL is 10 minutes with 60-second
heartbeats; fencing applies independently of broker deliveries and the environment lease. This record is not selectable. Build the
candidate monthly/tile snapshots from committed state plus validated proposed changes;
they contain profiles and levels, including profile-level scientific fields and hashes
in the schema. Mutable attempts/retrieval/revision timestamps live in separate provenance
manifests, not scientific Parquet rows; revision-only metadata advancement therefore
can reuse the unchanged scientific object.
For a level-bearing Parquet file row_count means measurement levels and profile_count
means distinct profile identities. No zero-level profiles publish.

Object keys are generated only from validated UUIDs and lowercase 64-hex SHA-256 values
under fixed configured prefixes. Raw final keys are raw/sha256/<sha256>.json; quarantine
refers to those same sanitized immutable blobs through opaque manifests.
Region labels, source URLs and CLI text never become
path components. Reject traversal, absolute keys, embedded slashes in identifiers and
cross-environment bucket references. No filesystem rename semantics are assumed.

Publication steps:
1. Land bounded sanitized raw bytes, checksum and request/response evidence.
2. Parse, validate, assign ownership and classify revisions; quarantine invalid chunks.
3. Write each candidate to `tmp/<publication_uuid>/<opaque_file_id>`.
4. Read back all bytes; verify SHA-256, byte length, Parquet readability, exact schema,
   level/profile counts, identity uniqueness, scientific manifest hashes and coverage.
5. Copy/publish to `normalised/sha256/<sha256>.parquet` using create-if-absent semantics.
   Re-read the final object and repeat verification. An existing key is reusable only
   if its verified bytes match; never overwrite different bytes at an immutable key.
6. Start one PostgreSQL transaction; lock affected profile identities and partition
   slots in deterministic order, validate publication lease/fencing token and recheck
   revisions/base generations and the open run's control epoch/cancellation/deadline.
   On non-conflicting drift roll back and rebuild within the same budgets; publication
   revalidation conflicts follow the quarantine path below, never a failed-success retry.
7. In that same transaction merge float/profile identities, replace complete newer level
   sets, enforce window/month/FK constraints, persist validation/catalogue evidence,
   activate all changed generations, supersede their prior generations, record outcome
   totals and mark the chunk complete. Commit once. A transaction failure publishes
   no scientific change, active catalogue change or chunk completion.
8. Mark the publication intent committed in that transaction as well; optional temp
   reconciliation afterward must not determine success.

Implementation note S1-RESOURCE-2: a certificate scoped to one publication may
reuse previously verified scientific content only after full byte-count and
SHA-256 equality of the complete object, plus schema/count/row-group checks.
The first payload still undergoes full canonical/scalar/scientific-membership
verification. Every actual canonical encoding is charged; no budget credit or
separate hidden run allowance is allowed. Certificates contain no payload/row
cache, cannot cross an intent or process, and are discarded on recovery/rebuild.
Raw verification, final read-back, database fencing and atomic commit are unchanged.
Corruption, mismatched evidence, expiry and fresh-certificate charging tests are
required. Bounded per-level encoding may reduce CPU overhead only with identical
canonical bytes/hashes and budget boundary behavior. This is an implementation
optimization, not a source or resource waiver; N08 remains binding.

Unchanged partitions keep their generation IDs and objects. A stale replay never
creates an active snapshot of stale data. Empty refreshes and accepted ownership changes
have different outcomes:
1. Verified empty fetch with no stored science in the exact selection: commit a
   verified_empty_fetch plus locked empty_stored_selection evidence and completion;
   create no new object or supersession. The selector returns
   no profiles/partitions for that selection with explicit empty-fetch/stored-domain
   evidence and no gap, provided receipt coverage is complete.
2. Verified empty fetch over retained stored science: preserve every profile/level and
   active generation, record source_absence_over_retained with retained membership IDs,
   and complete the chunk. The selector still returns those active generations and a
   source-absence annotation; it must not label the accepted dataset empty.
3. Accepted identity-preserving ownership correction removes the last stored profile
   from an old slot: atomically move/replace the profile/levels, supersede the old
   active generation and activate the new owner snapshot. Record empty_stored_domain
   with correction/provenance and completed fetch coverage. Selection of the old slot
   returns no active generation and explicit corrected-empty evidence, never the
   superseded object; an uncovered requested interval still reports a gap.

If a slot contains profiles outside the exact empty-fetch selection, preserve that
slot too; an empty subset does not deactivate a full month/tile snapshot. Supersession
because of accepted revisions/ownership changes is permitted; source absence alone
never causes supersession or tombstones.

### 7.1 Publication-time conflicts and intent disposition

A conflict discovered under publication locks (including equal revision/different hash)
rolls back the entire scientific/catalogue transaction. The current authorized controller
then performs a separate fenced evidence-only transaction: revalidate open run/epoch
and database clock before D_work,
lock the chunk, transition publishing -> quarantined, store incoming/stored revision/hash
and winner generation IDs, mark valid peers blocked, and mark every uncommitted intent
for this chunk abandoned with reason revision_conflict. Preserve candidate final/raw
object references in the abandoned intent and quarantine evidence; none is activated
and Stage 1 deletes nothing. Quarantine outcome and intent abandonment commit together.
A committed winner's science/catalogue remains unchanged.

Intent states are prepared -> committed or abandoned; committed/abandoned are terminal.
A rebuild abandons its replaced prepared intent with preserved references and creates
a new bounded intent. A recovered publisher may adopt the same prepared intent with a
new fencing token after verifying objects/bases; it cannot resurrect an abandoned intent.
If a crash occurs between rollback and evidence-only quarantine commit, recovery repeats
revalidation and records the same quarantine exactly once. If cancellation/deadline
fencing wins first, finalization records failed with its termination reason and attaches
the observed conflict evidence without allowing a late quarantine/publication mutation.
Terminal complete chunks are never changed by this path.

### 7.2 Selection and recovery

Catalogue states are pending (intent only), active, superseded and quarantined.
Only committed active records with non-null final verified object evidence and matching
schema/geometry versions are selectable. Superseded records remain for provenance.
The internal `select_active_partitions(environment, time_interval, region_version,
schema_version)` function consults PostgreSQL, never a bucket listing. It returns only
matching committed active records with no coverage gaps, or an explicit gap result.
Selection rechecks object availability/byte length and SHA-256 by bounded read-back;
a missing/corrupt object or expired verification budget yields an unavailable/gap
result, never a stale substitute. Cap a selector call at 600 seconds and 10 GiB read;
large calls return an explicit budget gap and can be verified in smaller internal
slices. This correctness proof does not claim Stage 2 query latency.
It does not implement SQL/DuckDB queries or a public API. Quarantined/failed chunk evidence never manufactures a partition; empty-fetch evidence
has exactly the three selector outcomes above and cannot erase retained science. Completed no-op chunks may reference
existing active generations.

A crash before step 7's commit may leave final objects or prepared intents, but no
queryable new partition. Recovery reads persisted chunk/run control first: complete
means already committed, so return success without re-merging. Lost acknowledgement
after commit has the same outcome. Process loss without a persisted cancellation is
recoverable under §8.1; it is not automatic failed/partial finalization. A publishing
chunk may be reclaimed only while the run is open, uncancelled, before its work deadline
and within persisted claim/request/publication budgets. Verify/reuse objects, recheck
science and commit once. An object alone never proves completion. Old run epochs or
chunk fencing tokens cannot commit. Cancellation/deadline paths use §8.2 instead.

Orphan reconciliation is dry-run/non-destructive in Stage 1. Minimum candidate age is
48 hours from server-side object creation (unknown creation time means keep).
Protect any object referenced by any catalogue state, raw evidence, quarantine or
publication manifest, including superseded records. Protect any key in an uncompleted
publication intent regardless of lease expiry until recovery records it abandoned;
also exclude keys with in-flight uploads/copies or active leases. Proposals record
reference checks, intent status and age evidence. Future authorized deletion must
lock/check references and publication intents again immediately before conditional
deletion; age alone is never proof of orphanhood. No destructive lifecycle rule is
enabled in MinIO or PostgreSQL by Stage 1.

## 8. Durable states, quarantine and CLI outcomes

Persist every transition with timestamp, attempt, reason and fencing token. State
changes are checked compare-and-set operations; broker delivery is not state authority.

| Chunk state | Allowed next states |
|---|---|
| planned | fetching, failed |
| fetching | fetching (bounded retry), landed, quarantined, failed |
| landed | landed (bounded recovery), validating, quarantined, failed |
| validating | validating (bounded recovery), publishing, quarantined, failed |
| publishing | publishing (bounded recovery/rebuild), complete, quarantined (publication revalidation), failed |
| complete | Terminal; a retry recognizes completion without mutation. |
| quarantined | Terminal; a separate reviewed replay uses a new run/chunk identity. |
| failed | Terminal; a separately requested retry run records its predecessor. |
| partial | Reserved for aggregate runs, never a chunk's successful terminal state. |

A run follows planned -> fetching -> landed -> validating -> publishing -> complete
for barriered sequential execution. For interleaved chunks, fetching/landed/validating/
publishing may transition among those active states as persisted child work changes;
they describe current work, not completed coverage. From any nonterminal run state a
finalizer can transition to complete, partial, quarantined or failed when all children
are terminal. Runs never leave a terminal state.

Terminal chunk states are complete, quarantined and failed. The supervisor/finalizer
must record a terminal outcome for every planned chunk, including unstarted chunks
failed with persisted cancellation/deadline/budget reason when finalization is required. Adaptive splitting first atomically replaces one
unstarted plan slot with bounded child slots; an attempted parent is recorded failed
with `split_replaced` and explicit child links, excluded only from leaf coverage.
Report all ancestors and leaves; never drop a failed chunk from the accounting.
No dynamic work is scheduled after the run deadline.

Run reduction: complete only if all coverage leaf chunks complete, with no quarantine
or gaps; partial if at least one leaf complete and another quarantined/failed; quarantined
if no leaf complete, some quarantine and none failed; otherwise failed. A warning alone
(e.g. unknown QC retained) is not quarantine. Zero profiles can be complete only with
the verified empty evidence in section 3 (stage1-v3: or the S1-SOURCE-2 receipt).

Stage 1 uses zero tolerated quarantined profiles/payloads for a successful acceptance
run. A single invalid/conflicting profile quarantines that whole chunk during initial
validation or publication revalidation;
other chunks may finish, but the run is non-success. Existing science remains intact.
Valid parsed peers are recorded as blocked-by-chunk-quarantine, never called committed.
No `--ignore-quarantine` success override exists. A reviewed corrective replay is a new
run linked to the quarantined evidence; original terminal records remain unchanged.

stage1-v3 whole-profile source-loss exclusion (ADR-0040). A profile whose only warning is
`degenerate_levels`, with a source `_id`, whose remaining schema validates and which the
chunk's tile owns, gets outcome `excluded_source_loss` instead of quarantining the chunk:
never published, returned levels recorded, lost levels `unknown`, and its warning, source
ID, selection and raw landing kept in an exclusion ledger. Any other or additional warning,
missing identity or schema drift still quarantines the whole chunk. Acceptance still needs
zero quarantines and zero coverage gaps; with exclusions the report states
`acceptance_qualified_with_source_exclusions` and never `scientific_source_complete = true`.
Stage1-v2 runs and the historical 8 quarantines are unchanged.

### 8.1 Recovery owner and every nonterminal phase

One active durable ingestion controller per run owns retry/recovery decisions. Its
PostgreSQL run-control record includes control_epoch, controller lease/heartbeat, claim
counts, work deadline, cancellation_requested_at/reason and finalization status.
Controller lease TTL is 10 minutes with 60-second heartbeats, matching scope/chunk
lease timing. Scope admission and controller ownership are separate from chunk leases. An independent
local supervisor checks every 10 seconds; when a controller lease expires it claims
the same unfinished run with a higher control_epoch and scope fencing token, invalidates
old chunk authority and dispatches bounded resumptions. This adopts the existing run,
T, plan and counters; it creates no fresh run/budget. A worker lease expiry while the
controller lives is recovered by that controller. The supervisor performs no upstream
work itself and does not add another HTTP/Celery retry owner.

At most 4 controller claims and 4 processing claims per chunk, including the initial
claims, and 4 publication attempts per chunk are permitted. Normal phase progress under
one claim consumes no extra claim; worker/controller takeovers do. All logical HTTP
attempt counters persist across claims. If a takeover budget is exhausted, fenced
finalization fails unfinished chunks with recovery_budget_exhausted.

| Nonterminal phase at loss | Controller-authorized recovery while run remains open |
|---|---|
| planned | Keep the same plan slot; dispatch its first processing claim, no invented HTTP attempt. |
| fetching | Mark interrupted in-flight attempt with unknown response outcome; discard unverified partial bytes. Reuse only fully landed verified responses; retry missing logical requests within their existing <=4 attempts. |
| landed | Verify persisted raw/inventory/metadata manifests and bytes; proceed to validation without upstream refetch. Missing/corrupt landed evidence fails as landing_unavailable. |
| validating | Re-run deterministic validation/mapping from verified landing, using the same policy versions/T; reuse only verified persisted candidate artifacts. Do not refetch or reset counters. |
| publishing | Read completion first; otherwise adopt/reverify prepared intent objects/bases and revalidate under current epoch. Rebuild only within publication budget, or quarantine a conflict under §7.1. |

Every recovery claim is persisted before work. Complete/quarantined/failed chunks stay
terminal under every takeover. Worker death, controller death or a CLI process hard kill
without a successfully persisted cancellation request is process loss, not evidence of
operator cancellation. A vanished CLI supplies no synthetic success/130 exit; reattached
observers obtain the eventual persisted run result.

### 8.2 Cancellation and deadline finalization

Let D be persisted created_at_actual_utc plus the run's frozen execution limit (default
and hard maximum 6 hours; a reduced limit must exceed the 60-second finalization reserve
or configuration is rejected). It is measured from the database's
actual run-creation clock, never from acceptance run_reference_time_utc. The acceptance
reference freezes scientific eligibility only, not watchdog/deadline clocks.
Work deadline D_work = D minus 60 seconds.
All effective resource limits/deadlines are frozen in run control at creation; recovery
cannot reload configuration to enlarge them. No new fetch/validation/publication starts
at or after D_work. Nonterminal processing/quarantine transitions also guard current
epoch, cancellation and D_work; only termination finalization and terminal read/recognition
may proceed after closing. Independent supervision
uses the last 60 seconds for bounded fenced finalization. A persisted operator cancellation
request or D_work expiry closes the run to further processing claims/publication.
Finalization revokes run/chunk authority, records termination reason, marks every unfinished
chunk failed and abandons its prepared intents while preserving object/evidence references.
Already committed complete chunks remain complete and selectable; existing terminal
quarantine/failure evidence also remains unchanged. Run reduction then gives partial
when some leaves completed, otherwise failed, subject to the all-complete case below.

Publication and cancellation/finalization serialize on the same PostgreSQL run-control
row. Publication checks the open epoch, chunk fence, absence of cancellation and database
clock against D_work both at entry and in its final commit guard; transaction timeouts
are capped by remaining work time minus a one-second commit reserve; refuse publication
when no such reserve remains. Cancellation linearizes when
its fenced closing transaction wins that lock and commits. A science transaction that
committed first is already complete; no transaction after the closing fence may activate
science, receipts, catalogue or completion. An expired work deadline is rejected even
if the supervisor has not yet run. Never accept a late publisher merely because its
object/lease was valid earlier. An operator request racing an already committing publisher
may preserve that completed chunk; its other unfinished chunks cannot publish afterward.

If all leaves committed before closing (including a lost final acknowledgement), reduce
the run to complete and cancellation is recorded as no_effect_already_complete. Normal
scheduled-complete watermark advancement may occur exactly once with run finalization;
a partial/failed/quarantined or overlap-skipped run never advances it. These internal
controls do not introduce Stage 5 user job APIs.

If PostgreSQL is unavailable, do not claim final evidence was persisted or return success.
Deadlines remain immutable; on restoration the supervisor finalizes overdue unfinished
chunks instead of permitting new publication. Failed evidence persistence is a recovery
requirement, with no inference of successful coverage.

### 8.3 CLI and admission outcomes

CLI exits: 0 complete (including verified empty/no-op); 2 invalid arguments/configuration/
unsafe environment before run planning; 3 partial; 4 quarantined; 5 failed, including
exhausted budgets/deadlines or inability to persist final evidence; 6 overlap_skip with
a persisted admission event and no new run. Operator cancellation returns 130 only after
its closing/terminal evidence commits and at least one unfinished chunk is failed due
to cancellation, regardless of partial/failed aggregate state. Cancellation after all
leaves completed returns 0 with no_effect_already_complete evidence. Deadline finalization
returns the aggregate code 3 or 5, never 130. A process killed before recording cancellation
has no contract-assigned final exit; its run is recovered as process loss under §8.1.

## 9. Resource, retry and credential bounds

Diagnostic supplement **S1-DIAG-1** adds evidence, without changing stage1-v2
limits, scientific hashes, state transitions or quarantine outcomes. Retain the
canonical_output_limit category and attach only fixed resource scope
(number/profile/chunk/run), operation (normalization/encoding/reservation/accounting/
readback), limit_bytes, used_bytes and requested_bytes. Counters are nonnegative
signed-bigint-range integers. Unknown scopes, unexpected keys, malformed or missing
database DETAIL and arbitrary strings are dropped; historical failures stay unscoped,
not backfilled. Diagnostics are sanitized and frozen with final report evidence.
Distinguish run reservation exhaustion from invalid/oversize scientific content;
never make this generic category splittable or reset counters after splitting.

An existing private-spool canonical byte sequence may be reused after round-trip
certification within that spool, with SHA-256 verification on every subsequent read.
Reusing bytes produces no new canonical encoding. Charge every conversion actually
performed, including certification again after recovery/new spool and full object
read-back reconstruction. The certification cache is process-local and bounded to
100,000 retained plus 2,000 incoming distinct documents; do not export a cache waiver,
skip object verification or exempt newly produced canonical output from the cap.

Limits are explicit upper bounds for stage1-v3 (stage1-v2 limits except the run canonical
cap, ADR-0041); configuration may reduce but cannot raise them without a reviewed contract
version. MiB/GiB are binary units.

| Resource | Bound and response on exceedance |
|---|---|
| Compressed/raw HTTP body | 16 MiB per response, streaming enforced even without Content-Length. |
| Decompressed JSON body | 128 MiB per response; incremental decompression stops at bound. |
| JSON structure | Depth 32; individual string 64 KiB; unknown complex structures quarantine. |
| Numeric/canonical output | Numeric token <=128 ASCII bytes; written exponent magnitude <=400; normalized numeric text <=512 bytes; canonical profile/chunk/run <=16 MiB/256 MiB/40 GiB (stage1-v2: 10 GiB; ADR-0041) including repeated work. Preflight length before expansion; violations quarantine. |
| Profile documents | 2,000 per chunk and 100,000 unique accepted profiles per run. |
| Levels | 10,000 per profile, 2,000,000 per chunk and 100,000,000 accepted levels per run. |
| Plan/chunks | Initial time slices: whole UTC calendar months clipped to the request in plan v2 (stage1-v3, ADR-0041; stage1-v2 <=7 days split at months), 10-degree tiles; at most 16,384 total persisted plan slots including split parents. Split down to 1 hour and 1-degree tiles, then fail if still too large. |
| Requests/data | 50,000 HTTP attempts per run including retries and metadata; 10 GiB cumulative raw received bytes including unsuccessful attempts. |
| Concurrency/memory | At most 2 active chunk workers per environment and 1 credentialed upstream request in flight; 1 GiB memory per worker, streaming/spill before bulk staging. stage1-v3 compliance (ADR-0042): worker cgroup `memory.max` = 1 GiB enforced, zero `oom`/`oom_kill` events and pipeline anonymous RSS peak <1 GiB; page-cache-inclusive `memory.peak` is recorded, not the pass criterion. |
| Wall time | Default 6 hours, hard maximum 12 hours (stage1-v3, ADR-0043; stage1-v2: 6 hours) from actual run creation, including queue/waits/retries/recovery; frozen reduced limits must exceed 60s. D_work = D minus 60s; final 60s reserved for fenced terminal evidence. |
| I/O deadlines | DNS/connect/TLS <=10 s, idle read <=60 s (stage1-v3, ADR-0043; stage1-v2: 20 s), whole HTTP attempt <=120 s; object operation <=120 s; DB lock wait <=5 s and transaction <=60 s, each capped by remaining run budget. |
| Retry/recovery | <=4 HTTP attempts per logical request, <=4 controller claims per run, <=4 processing claims per chunk and <=4 publication attempts per chunk, all including the initial claim/attempt and persisted across deliveries. |

The durable ingestion controller is the only retry owner. HTTP library automatic
retries and Celery autoretry are disabled. Celery carries only opaque run/chunk IDs;
redelivery consults durable attempts and lease state and adds no fresh budget. Timeouts,
connection faults, 408, 429 and 5xx may retry with full jitter over exponential maxima
2,4,8 seconds; Retry-After replaces that delay if longer, bounded to 300 seconds and
the remaining deadline. Invalid/oversized Retry-After or insufficient time fails.
401/403, other 4xx, invalid schema and conflicts do not retry. Repeated delivery of a
complete chunk succeeds immediately; attempt exhaustion is not reset by process restart.
Stream limits are hard safety checks. Split planning is a new bounded request, not
permission to redownload an oversized chunk four times.

Fetch credentials at execution from owner-controlled restricted non-synced configuration;
do not put them in URLs, fixtures, task arguments, broker results, database evidence,
logs, exception strings or reports. Logging uses an allowlist of opaque IDs, sanitized
host/path, state, counts and error category; never serialize client request/response
objects, headers, configuration or raw exceptions. Scrub credential-bearing URL queries
and source URLs before raw evidence is committed; preserve a sanitization manifest without
the removed value or a derived credential hash. Test headers, encoded URLs and nested
exceptions using synthetic sentinels.

Allow only HTTPS, port 443, exact hostname `argovis-api.colorado.edu`, no userinfo,
and approved /argo routes. Validate DNS-resolved addresses against loopback/private/
link-local/reserved destinations, pin the validated connection address and verify TLS
hostname to prevent rebinding. Do not fetch arbitrary URLs from source metadata.
Disable automatic redirects; Stage 1 rejects all redirects and forwards no credential
to a Location target. Parse and validate destinations for diagnostics without following
them; a same-host redirect requires a later explicit adapter change. Never trust suffix
matches such as argovis-api.colorado.edu.attacker.example.

## 10. Scheduling, catch-up and lifecycle boundary

Future Stage 1 defines one Celery Beat scheduler per environment, UTC, daily at 02:00.
Live ingestion is disabled by default via `FLOATCHAT_LIVE_INGESTION_ENABLED=false`;
both scheduler enqueue and worker execution check the flag. A manual live acceptance
command additionally requires an explicit opt-in and owner-provided Argovis credential.
Offline fixture mode never needs that credential. Acceptance Beat remains disabled.

Acquire a PostgreSQL environment/source/region admission lease with a monotonically
increasing fencing token before creating any live scheduled/manual run. Lease TTL is
10 minutes, renewed every 60 seconds. Also check the durable unfinished-run marker:
an expired lease with unfinished work triggers recovery of that same run, never a
competing fresh run. Recovery admission is not overlap_skip.

A fresh manual/scheduled request encountering the occupied scope persists one
scheduling_attempt record (UUID PK; UNIQUE request_id) with status=overlap_skip,
scope, requested mode, observation time, conflicting run ID and cause. It creates
no ingestion_run, chunk plan, run reference time or scientific/catalogue changes.
A manual request returns CLI exit 6 with that event ID; Beat records the same durable
event without a CLI exit or failed Celery task. Redelivery reuses request_id and the
existing event. Watermarks/backlog remain unchanged. This is an admission event,
not a run/chunk state. Expired workers cannot commit, and per-partition locks in §7
also protect cross-scope collisions.

Daily normal runs request `[T minus 14 days, T)` clipped to the run's 12-month interval.
Persist a watermark only after a fully complete scheduled run; partial/quarantine/
failure never advances it. Let W be the prior contiguous successfully covered scheduling endpoint (not the
maximum observation timestamp). Catch-up starts at max(T minus 12 months, W minus
14 days) and ends at min(T, start plus 31 days). Thus a long backlog is processed
oldest first with a 14-day overlap inside the 31-day cap. Persist remaining backlog
and process it on a later daily tick. A complete run advances W only to its requested
end, not automatically to T; an expired historical gap outside the eligible window
is recorded as excluded, not ingested or deleted. First enablement starts with the 14-day window; an explicit
bounded internal seed run is required for older eligible data. Do not loop until
all history is filled or advance the watermark past an unprocessed gap. Watermarks
are environment-specific and never imported from acceptance.

Configuration disable is not operator cancellation and does not set the closing fence.
It prevents new upstream operations; in-flight HTTP operations stop at their
deadlines and record non-success, while already verified publication may commit under
an intact lease. No new chunk starts after disable. Stage 1 scheduler performs no
destructive rolling retention, hot-object expiry, dashboard refresh or re-embedding.
A retention lifecycle ADR and separate owner acceptance are required before implementing
or enabling destructive maintenance. Superseded snapshots remain referenced.

## 11. Fixtures, evidence and reconciliation

Later implementation must add sanitized recorded raw Argovis JSON, not merely derived
Parquet. The Stage 0 processed fixture is a regression sample, not proof of an Argovis
adapter. Record authorized offline captures of full profile responses, matching
inventory responses and linked metadata, with observed capture time, sanitized request
parameters, response status/headers allowlist, specification/mapping/policy/hash versions, application Git commit, source revision
or explicit absence, immutable raw/partition references, byte SHA-256,
licensing/attribution, expected IDs and levels and sanitization manifest. Capture no
headers containing credentials or private configuration. Keep representative R/A/D,
ascending/descending, null/QC availability and revision examples according to the evidence
policy below; error and repeated-pressure obligations have explicitly different evidence.
Artificial mutations for malformed/conflicting cases must be labeled synthetic derivatives
of a recorded fixture; never label invented JSON a recorded upstream response.
An owner-provided sanitized capture may substitute for a live recording.

F01 acceptance amendment **F01-2**, owner-authorized on 2026-10-07 (Asia/Calcutta),
supersedes F01-1 for descending direction and present-core-value null evidence.
The owner removes further discovery/capture for those two representations because
obtaining authentic examples is disproportionate. This is an explicit evidence waiver,
not an observation or claim about what the service supplies. ADR-0033 and
`docs/stage1-f01-evidence-v2.json` version the amendment; source/mapping/hash versions
and previously admitted manifests remain unchanged. No further live discovery/capture
for either waived representation is required or authorized by this amendment.

| Representation | Required evidence |
|---|---|
| Core R/A/D modes | Authentic complete profiles with matching inventory before/after and linked metadata; retain 2904014_040's 501 A-mode core levels. Non-core modes and inventory alone are insufficient. |
| Ascending direction | Authentic complete profile and explicit source direction; mode and direction are independent. |
| Descending direction | Authentic evidence waived and still unobserved. Labelled derivative of an admitted authentic profile changes only direction for parser/canonical/Parquet proof. Verify stable upstream ID preference, distinct A/D fallback identities and database-enforced direction/key preservation. Synthetic identity/time/location changes needed by disposable publication tests must be enumerated. |
| Source core-measurement null | Authentic evidence waived and still unobserved. Labelled R- and A-mode derivatives set a cell to JSON null in each present pressure/temperature/salinity value column, retaining matching QC, unit, mode, arrays and ordinals. Prove selected original/adjusted null and canonical missing_reason=null through parser, canonical hash, PostgreSQL and Parquet. Distinguish missing QC, absent variables, unused counterpart nulls and authentic non-core nitrate nulls. |
| Repeated nonnull pressure | Labelled synthetic derivative of an authentic fixture, proving preservation, ordinal indexing and diagnostics through normalized storage/Parquet. No authentic witness is required. |
| Supplied measurement error | Labelled synthetic normalized-model/storage/Parquet tests, with no invented wire column and no claim of authentic parser support. Authentic parser support needs a separately verified wire mapping and corresponding complete capture. |

This distinction follows the [Argovis merge policy](https://argovis.github.io/hackathon22-docs/data_management/argo_merge.html)
which rejects degenerate pressure repetitions and merges by pressure, and the
[pinned extraction code](https://github.com/argovis/ifremer-sync/blob/cbf2bb48ed5d95532c18bb2cd5217e44618356cf/util/helpers.py#L350-L402)
which extracts measurements/QC without establishing a supplied-error wire representation.
Corpus audits retain all authentic coverage gaps and empty witness lists. Show the two
waived gaps separately from still-required authentic gaps and from derivative test passes;
never convert a waiver or passing test to "authentic observed". F01-2's amended fixture
gate passes only when the remaining authentic minimum (core R/A/D and ascending direction)
and all persisted derivative/model/database/Parquet obligations pass. A corpus audit alone
cannot certify these tests. Reports include amendment version, basis checksums, exact
synthetic transformations and separate test evidence. Neither profile samples nor F01-2
establish regional completeness, authentic descending/core-null parser evidence, a supplied
error wire mapping, or full Stage 1 acceptance. GO for isolated acceptance preparation is
a separate bounded gate decision; it is not preparation/execution or Stage 2 permission.

Captured-input `--replay-run` requires a closed complete predecessor in the same environment,
mode, interval, geometry and policy/source versions. Clone its entire validated immutable
split tree with fresh chunk IDs and durable one-to-one predecessor bindings: retain failed
split-replaced ancestors and the exact completed leaf bounds/tiles/request identities.
Revalidate full deterministic root coverage, parent/child topology, terminal states and
the 16,384-node cap before work. A fresh unsplit plan cannot substitute for the predecessor.
Reject incomplete, foreign, incompatible or component-only predecessors before replay work;
recheck in the planning transaction. Replay fetches only verified predecessor raw objects,
never upstream/credentials, and uses normal validation/publication. Reports distinguish
this actual replay from a new fixture-mode run using equal scientific content.

Stage 1 CI execution is fully offline: deny external egress and permit only local
ephemeral PostgreSQL, MinIO and Redis. Mock HTTP or use recorded in-process transport
fixtures. Use pinned pre-fetched dependency/source/image caches for checks and builds;
a missing cache is a setup failure, never permission for an online fallback. Preparing
caches is separate from ingestion acceptance. CI never needs credentials, cloud or live
upstream access. A separate opt-in Ubuntu 24.04 WSL2 live acceptance run is performed
only after Astra contract approval, later implementation and owner-supplied credential.
No live result is claimed by this turn. Persist before/after evidence for Jan-Mar
acceptance and its replay, environment markers, run references and catalogue generations.

Reconcile three different units; never equate payloads, profiles and measurement levels:
- Payload attempts: every HTTP attempt has exactly one disposition (verified raw,
  HTTP failure, transport failure, size limit, interrupted). Persist `http_failure` with
  numeric status and safe reason before the single retry owner decides retry/termination;
  schema permits precisely these application dispositions. Verified raw payloads link SHA-256,
  bytes, schema result and inventory/content role; identical blobs may serve many attempts.
- Profile occurrences: received = outside-time/region/core-scope + overlap/identical
  duplicates + structurally quarantined + eligible unique candidates. Eligible candidates
  are classified insert/newer/no-op/stale/conflict; conflict moves the chunk to quarantine,
  and valid peers are blocked. Partition ownership and outcome tables make duplicates
  traceable across chunks. No conflicting occurrence is hidden as a harmless duplicate.
- Measurement levels: sum source lengths per parseable occurrence = filtered levels +
  duplicate levels + quarantined/blocked levels + candidate levels. Unparseable source
  length is explicitly unknown with reason, never zero. Candidates divide into newly
  inserted/replacement levels, reused no-op levels and stale-skipped levels. Committed
  new total = old total - replaced old levels + inserted/replacement levels. This handles
  shortened profiles; original/adjusted numeric availability is a separate per-variable count.

Reconcile two explicitly named populations at the same committed publication snapshot:
1. Full stored-snapshot reconciliation: compare all currently accepted stored PostgreSQL
   profile/level identities in the logical month/tile to the entire active Parquet
   generation's identities/canonical manifests, including retained out-of-window
   observations. Both sides exclude superseded profile revisions, not old dates.
   Capture the PostgreSQL membership/hash manifest at publication commit; later reports
   compare that immutable manifest to the matching generation, not a different live DB
   state after subsequent revisions. Full counts may exceed this run's eligible counts.
2. Run-eligibility accounting: apply this run's fixed T/region/request bounds identically
   to its candidates, filters, outcomes and, when compared, both the stored manifest and
   Parquet membership. An eligibility-filtered Parquet view is an accounting operation,
   not a rewritten retained snapshot. Report before/after eligible totals separately
   from retained-outside-window totals and full stored totals.

For example, a new cutoff of 2025-10-06 keeps previously accepted October 1-5 rows in a
rebuilt October month/tile snapshot while updating an eligible October 6+ profile.
Full PostgreSQL/Parquet membership must agree including October 1-5; both eligible
projections exclude those rows. Retained counts are unchanged by the cutoff alone.
A moved/shortened accepted correction changes full source/destination membership and
level deltas explicitly; an empty source refresh changes neither stored population.

Run-wide committed insert/replacement totals exclude blocked/quarantined/failed peers
and include no-op/stale explicitly. Keep proposed outcomes distinct from committed ones:
valid candidates blocked by cancellation/deadline/infrastructure failure are recorded as
blocked_uncommitted with reason, not counted as inserted/replaced science. Empty-fetch, source-absence-over-retained and corrected-empty
outcomes are separate persisted categories. Attempt-level bytes/counts are not summed
as distinct science; row counts without identity/hash agreement are insufficient.

Generate machine-readable and Markdown reports exclusively from persisted run/chunk/
attempt/event/outcome, raw-manifest, verification and catalogue evidence, with immutable
snapshot/run IDs. Reports include plan leaves/ancestors, requested/proved coverage/gaps,
three-unit reconciliation, duplicates/filtering/quarantine reasons, before/after scientific
hashes and active generation IDs, revision outcomes, bytes, timings, retries, versions,
environment/reference time and source attribution. Unknown observations remain unknown.
stage1-v3 reports (ADR-0040) also state `S1-SOURCE-2`, empty-delivery receipts by role and the
exclusion ledger, and never `scientific_source_complete = true`.
For the storage comparison, build one pandas DataFrame from exactly the same ordered
core rows/columns/dtypes as the verified Parquet snapshot and measure
`df.memory_usage(index=True, deep=True).sum()` bytes. Record pandas/PyArrow versions,
index type, nullable dtypes and included columns. Write Parquet with Zstandard level 3,
100,000-row groups and a pinned writer version; record all options and read-back object
byte length. Compare equivalent null/QC/metadata columns and compute the measured byte
ratio. This is logical DataFrame memory, not peak process RSS; measure peak RSS separately
if reported. Include the pandas index in the memory numerator and state that Parquet
stores source level_index, not the pandas index. Zero rows gives a ratio marked
not-applicable, not an invented infinity. Reports never estimate size from row count.
Reports are reproducible after restarting the reporter,
without access to worker memory, a live upstream or secret configuration.

## 12. Acceptance-test plan and Astra blocker traceability

These are required future acceptance tests, not tests executed in this contract-only turn.
Every row must have a deterministic fixture/input, persisted evidence and explicit assertion.
All offline cases run with networking to upstream denied. Fault cases assert both scientific
state and catalogue state, not just an exception. Test IDs are stable review references.
Rows below describe stage1-v3 behavior (ADR-0040 through ADR-0042) where they say so; stage1-v2
wording is kept only where marked.

| ID | Input/fault | Required assertion |
|---|---|---|
| T01 | Normal run with a clock advancing through midnight/month-end and a retry | One persisted actual-UTC T; every chunk uses the same 12-month eligibility interval. |
| T02 | Leap day/calendar subtraction, records on both window boundaries | Calendar clamping correct; lower bound included, T excluded; out-of-window normal CLI rejected with 2. |
| T03 | Jan-Mar acceptance CLI | Exact half-open interval and fixed T; all three months eligible; matching isolated environment required. |
| T04 | Acceptance mode against production/unmarked DB or bucket; acceptance watermark import | Reject before writes; normal T/retention/watermarks unchanged. |
| T05 | Multi-month interval (plan v2: whole UTC months clipped to the request, 270 roots for Jan-Mar, ADR-0041) and adaptive time/tile split | Persisted owner chunks cover every requested instant/tile once, no gaps; parent/leaf accounting preserved. |
| T06 | Populate Oct 1-5/6+ 2025, advance T to Oct 6 2026, request exact internal interval [2025-10-06,2025-11-01) and ingest an eligible Oct 6+ correction | Oct 1-5 retained in DB/full snapshot unchanged; full manifests include them, run-eligible projections exclude them; both scopes balance, including replacement level deltas. |
| G01 | Exact geometry, corners/edges/just outside, swapped/out-of-range/nonfinite coordinates | Version/hash and lon/lat order correct; edges included; invalid coordinates quarantined; outside valid points filtered. |
| G02 | Adjacent expanded tiles return identical profiles; A and D at same point | One owner/identity per profile; counted overlap duplicates; both directions survive. |
| G03 | HTTP request recorded against pinned specification | Proper encoded closed polygon and UTC dates, data=all, no invented routes/pages/adjusted request keys. |
| G04 | Missing inventory ID, changed inventory (including a mixed 200/404 triple), truncated JSON/body, unexpected cursor/page | Bounded retry or terminal non-success; no successful empty coverage. |
| G05 | Verified three empty responses and the S1-SOURCE-2 receipt (three 404 `application/json` bodies of <=64 bytes parsing to `[]`) versus other 404s (error envelope, nonempty/malformed body, other content type, truncation, `id`, `/argo/meta`), mixed 200/404, timeout, exhaustion | Only verified matching terminal empties or ADR-0040 receipts complete with 0 and no fabricated active object; receipt stored as raw evidence with `http_status = 404`; every other case fails. |
| I01 | Stable-ID replay, fallback replay, missing fallback fields, missing direction | Stable/fallback uniqueness enforced in DB; incomplete fallback quarantined; U only with stable ID. |
| I02 | Retrieval/update times change without observation change | Same identity; scientific no-op if content equal. |
| I03 | Stable ID introduced for fallback; ID/key resolve different rows | Alias without extra science / conflict quarantine respectively. |
| I04 | Two writers insert same identity; A/D cycles and repeated pressures | DB prevents duplicates; directions distinct; level_index preserves repeated pressures. |
| I05 | Null required fields, dangling/mismatched-month FK, duplicate level index and absent monthly partition | DB rejects every invalid write atomically; no active catalogue or completion. |
| I06 | Unauthorized profile/float/run/catalogue deletion; authorized test-only profile deletion | RESTRICT/role denial preserves provenance; measurement-only cascade demonstrated in disposable test transaction. |
| R01 | Equal revision/equal content and JSON key/number-format reorder | Same scientific hash, zero new scientific entities or active generations; audit/attempt rows allowed. |
| R02 | Equal revision/different content | Quarantined conflict; stored profile, levels and active catalogue unchanged. |
| R03 | Newer revision with N levels then N-2 levels | Exactly N-2 current levels; no obsolete levels; catalogue snapshot agrees, all in one commit. |
| R04 | Stale retry after a newer commit | stale_skip; no newer scientific value or active generation overwritten. |
| R05 | Revision absent: equal content / changed content | Hash no-op / unordered conflict quarantine; hash never invents chronology. |
| R06 | Mixed source-date vectors, missing components, source-set change | Unordered comparison; equal science warning, differing science quarantine. |
| R07 | Concurrent revisions/candidate based on old catalogue | Lock/recheck prevents stale commit; rebuild bounded; no lost update. |
| R08 | Newer revision equal science; changed observation month/tile; fallback timestamp correction | Revision-only update reuses generations; stable-ID move rebuilds affected slots atomically; fallback correction quarantines. |
| S01 | R/A/D per-variable arrays, explicit supplied variants and errors | Original/adjusted/QC/error/unit/mode mapped independently; absent counterpart null, no manufactured values. |
| S02 | JSON null, fill 99999, declared fills, nonfinite numbers and signed zero | Missingness reasons retained, finite columns only, deterministic canonical hash. |
| S03 | Unequal/zero/excessive arrays, duplicate names, malformed data_info, absent variables | Entire malformed chunk quarantines; no zip truncation; genuinely absent variable gets N nulls. |
| S04 | QC 0..9, missing/unknown QC, unknown mode or unit | Known QC retained; unknown token warning/source preservation; unsafe mode/unit quarantines. |
| S05 | Poor QC, implausible finite values, duplicate/non-monotonic pressures | Retained with diagnostics; good-QC policy only 1/2 and never mixes variants. |
| S06 | Reordered data/data_info variables, metadata precedence and missing optional fields | Name-based mapping unchanged; data-document metadata wins; absent optional columns remain null with reasons. |
| P01 | Multipart ETag differs from SHA-256 | Only SHA-256 of read-back bytes determines integrity. |
| P02 | Temp/final checksum, byte, schema, count or manifest mismatch | No activation/completion; verified existing immutable key reused only if equal. |
| P03 | Crash after raw/temp write, after final copy, before DB transaction or during it | No new selectable partition/scientific partial write; unreferenced objects are evidence, not completion. |
| P04 | Crash/lost acknowledgement after atomic commit | Retry reads complete; zero scientific duplication and unchanged active generations. |
| P05 | Catalogue commit or scientific replacement or chunk completion fails | Entire transaction rolls back all three; previous catalogue/science survives. |
| P06 | Naked object, pending/superseded/quarantined catalogue, valid active records | Internal selector returns only committed verified active records and explicit gaps. |
| P07 | Two active generations for one slot; expired publisher commits | DB uniqueness/fencing rejects; old active stays valid. |
| P08 | Young/unknown-age/referenced/superseded/in-flight/abandoned old objects | Dry-run proposes only >=48h unreferenced, abandoned, not in-flight candidates; deletes nothing. |
| P09a | Verified empty fetch with no accepted science in that exact selection, then later insert matching science | Complete with verified_empty_fetch/empty_stored_selection; no new object; selector initially reports covered empty. After the insert raises slot_version, selector returns the new active generation: old empty evidence cannot hide it. |
| P09b | Empty refresh over retained accepted profiles, including a subinterval of a populated month | Source-absence receipt; profile/level hashes and active generation IDs unchanged; selector returns retained partitions with source-absence annotation, never dataset-empty or superseded. |
| P09c | Accepted ownership correction moves the last stored profile out of a slot | Source slot superseded and destination activated atomically; corrected-empty stored evidence; selector returns empty old slot with correction provenance/no superseded object and unchanged unrelated coverage gaps. |
| P10 | Object disappears before verification or after commit | Before commit no activation; after commit selector returns explicit unavailable/gap and never stale substitute; corruption/missing object recorded and gates acceptance. |
| P11 | Two valid chunk candidates (e.g. different owning-tile corrections) initially pass with equal source revisions/different hashes; one commits first | Loser revalidation rolls back then publishing -> quarantined with revision_conflict; winner science/active generations unchanged; loser intent abandoned with retained object references, no activation/completion. Inject a crash between rollback and evidence commit and verify the same terminal disposition on recovery. |
| C01 | Every valid/invalid transition and repeated terminal delivery | State machine rejects illegal transitions; complete is idempotent. |
| C02 | Mixed good/quarantine/failure chunks; no-good/all-quarantine/all-failure | Correct run reduction and exits 3/4/5; every planned chunk has recorded terminal outcome. |
| C03 | One bad profile (any invalid/conflicting profile, or `degenerate_levels` plus another warning, without `_id` or with schema drift) alongside valid peers | Whole chunk quarantined, peers counted blocked; zero tolerance prevents exit 0. A sole `degenerate_levels` profile with `_id` follows F02/F05 exclusion instead (ADR-0040). |
| C04 | Split parents/leaves, exhausted logical retries and unstarted plan slots | Every slot accounted, split-replaced parents retained, exhausted/unstarted failed leaves never treated as empty success; termination/loss cases are C05-C11. |
| C05 | Kill a worker without cancellation during fetching or publishing | Same run/T/plan recovered within unchanged counters; interrupted attempts recorded; new chunk fence invalidates old worker; eventual valid completion is allowed, not forced failed/partial. |
| C06 | Kill the controller while workers exist and some chunks have committed | Supervisor adopts same run after lease expiry with higher control_epoch/scope fence; completed chunks remain complete; no new run/T/budget, stale workers cannot commit. |
| C07 | Persist operator cancellation with complete and unfinished chunks | Closing fence prevents every late science/catalogue/receipt/completion commit; complete chunks/objects retained, unfinished failed, prepared intents abandoned; aggregate partial/failed and observing cancellation CLI exits 130. |
| C08 | Advance database clock to D_work with queued/fetching/landed/validating/publishing work | No new processing/publication past cutoff; supervisor finalizes unfinished leaves in reserved 60s, preserves complete chunks; exit 3/5, never 130; no watermark advance for non-complete run. |
| C09 | Race cancellation/deadline finalization with a commit; all chunks already committed before lost acknowledgement | Serialize on control row; only pre-fence/pre-deadline science may commit; completed chunks preserved, all-complete run reduces complete/no_effect_already_complete and returns 0, watermark advances at most once. |
| C10 | Lose process authority in each planned/fetching/landed/validating/publishing state; corrupt landed evidence | Exercise every §8.1 recovery-table row; no refetch after verified landing, no counter reset; missing/corrupt landing fails landing_unavailable; only verified intent reuse, conflict quarantines. |
| C11 | Exhaust controller/processing/publication claim budgets or DB unavailable during finalization | <=4 each with initial claim included; no fresh run/budget on restart; unfinished leaves failed with precise reason. DB outage cannot report persisted terminal success; on restore overdue work finalizes, never publishes late. |
| B01 | Each compressed/decompressed/profile/level/array/string/depth/chunk/count cap, and the run canonical cap (40 GiB, ADR-0041), at limit and +1 | Limit accepted when otherwise valid; exceedance bounded, no publication, appropriate size split/failure or schema quarantine. |
| B02 | Decompression bomb, slow DNS/TLS/headers/body/EOF and DB/object stalls | Independent deadlines and worker memory bound enforced including cleanup (cgroup `memory.max` 1 GiB, zero oom/oom_kill, pipeline anonymous RSS <1 GiB; `memory.peak` recorded only, ADR-0042); run finalizer persists failures within reserved budget. |
| B03 | 429/Retry-After, transient errors, 401/403, Celery redeliveries/restarts | Single owner; <=4 attempts per logical request across deliveries; no multiplied retries; nonretryable errors fail. |
| B04 | Duplicate workers, queue delay, request/byte/run budget exhaustion | <=2 chunk workers, <=1 upstream request; no budget reset; six-hour run limit includes queue time. |
| B05 | Synthetic credential in headers, URLs, nested exceptions, broker args/results and reports | Sentinel absent from all committed/logged outputs; only opaque IDs in tasks; fixture sanitation evidence safe. |
| B06 | Redirect to same/other host, hostname suffix attack, private DNS/rebinding, source URL | No forwarding/fetching; TLS/host/address validation enforced before credentials. |
| B07 | Worker attempts server COPY/file/program access, DDL/admin/extension writes and target DML | Denied; client COPY to approved staging and controlled merge work; fixed identifiers resist injection. |
| B08 | Traversal/absolute/object-key injection and wrong bucket/environment | Rejected before object operation; only opaque generated keys inside permitted private prefixes. |
| B09 | Upgrade Stage 0 with preserved sentinel data/extensions; repeat and unsafe downgrade | Additive portable migration preserves all sentinels; repeat safe; unsafe downgrade refused, no destructive backfill. |
| D01 | Two Beat instances, UTC/daylight-saving boundary and lease expiry | One effective schedule; scope/control/chunk fencing respected, UTC 02:00 without doubled jobs; overlap persistence/exit tested separately in D05-D06. |
| D02 | Live disabled/missing credential and separate offline fixture mode | No upstream operation; explicit opt-in/credential needed only for live mode. |
| D03 | 14-day overlap, 90-day outage, first enablement, partial scheduled run | Bounded oldest 31-day catch-up, backlog persisted; no false watermark advance. |
| D04 | Old observations/partitions and cleanup invocation | Dry-run only; no detach/delete/expire/hide, regardless of acceptance T. |
| D05 | Fresh manual live invocation while an unfinished scope is occupied or its lease has expired | Persist idempotent scheduling_attempt overlap_skip; CLI exit 6, no new run/T/chunks; no science/generation/watermark/backlog changes. Expired incumbent is recoverable, not replaced by a new run. |
| D06 | Beat overlap plus duplicate delivery of the same scheduling request | One scheduling_attempt by request_id, no run/chunks or failed Celery task; no CLI exit for Beat; unchanged watermark/backlog. Recovery adoption instead records a controller claim on the incumbent. |
| F01 | Recorded JSON/inventory/metadata plus §11 F01-2 and ADR-0033 | Authentic R/A/D and ascending source direction; descending/core-null authentic waivers remain visible without witnesses. Labelled authentic derivatives pass direction/identity and present-core-null parser/canonical/database/Parquet assertions. Repeated-pressure and normalized-error obligations pass separately; no regional completeness or authentic error parser claim. |
| F02 | Duplicate/filter/quarantine/excluded_source_loss/stale/no-op/new/shortened inputs | Separate payload/profile/level equations and identity-manifest agreement balance; excluded profiles are never published and have returned levels recorded, lost levels unknown (ADR-0040); unknown levels remain unknown. |
| F03 | Reporter restarted without worker memory or upstream | Identical evidence-derived report; no fabricated counts/timing/storage claims. |
| F04 | Actual --replay-run after temporal/spatial adaptive splitting, upstream/credential access denied | Validated complete predecessor topology and immutable bindings preserved; profile/measurement scientific state and active generations unchanged; attempt/run/audit increases explained separately. Reject invalid predecessors. |
| F05 | CI with upstream network denied; separate WSL2 live command; sole-`degenerate_levels` profile with `_id` versus any other/additional warning | Offline suite succeeds without credentials; live acceptance remains explicitly opt-in and isolated. Sole warning yields `excluded_source_loss`, ledger and `acceptance_qualified_with_source_exclusions` (never `scientific_source_complete = true`); any other warning quarantines the chunk (ADR-0040). |
| F06 | Same dataset serialized to pinned Zstd Parquet and typed pandas frame twice | Reproducible measured sizes/options, equivalent content verified; DataFrame measure distinct from RSS; empty ratio not-applicable. |
| F07 | Fixture/run/catalogue provenance audit | Sanitized request/retrieval/revision-or-absence/raw hash, parser/schema/policy/app commit and immutable partition references all present. |
| N01 | Valid strict numeric token at 128 bytes and token at 129; malformed JSON numeric grammar | Bound checked before Decimal construction; malformed/oversized tokens quarantine with raw hash/reason, no certified scientific hash or stored mutation. Otherwise valid <=128-byte values proceed through remaining checks. |
| N02 | 1e100000000, written exponent 400/401, and <=128-byte coefficient whose normalized output needs 513 bytes | No exponential allocation; exponent/output limits enforced before expansion/conversion; no stored change/scientific hash on rejection. At-limit forms still undergo overflow/underflow checks rather than bypassing them. |
| N03 | 1e309 and a value rounding to max finite binary64 | Overflow candidate quarantined with float64_overflow, never stored null/infinity; finite boundary accepted with exact-source canonical hash, expected binary64 bits and appropriate rounding/plausibility flags. |
| N04 | 1e-400, -1e-400, 5e-324, exact 0 and -0 | Nonzero values rounding to zero quarantine; 5e-324 stores min positive subnormal (0x0000000000000001) with rounded/subnormal flags; exact zero stores positive zero and equivalent hashes for signed zeros. |
| N05 | 0.1; 1/1.0/1e0; exact halfway 1.00000000000000011102230246251565404236316680908203125; adjacent decimals around that halfway | nearest/ties-even bits verified independently; halfway stores 1 (0x3ff0000000000000) with rounded flag. Equivalent decimals hash equally; distinct exact decimals with the same stored bits retain distinct canonical hashes. |
| N06 | Quoted scientific value/error tokens NaN, Infinity, +Infinity, -Infinity | Null stored with fixed nonfinite reason/kind and independent expected canonical hashes; positive Infinity spellings hash equally, signed infinity/nan kinds remain distinguishable. No float NaN/infinity is written. |
| N07 | Bare NaN/Infinity/+Infinity/-Infinity; quoted inf/nan/+NaN/whitespace/finite numeric strings; nonfinite coordinates/identity | Whole chunk quarantines according to grammar/field rules, raw hash/reason retained, no certified scientific profile hash or scientific/catalogue mutation. |
| N08 | Canonical number/profile/chunk/run output (run cap 40 GiB in stage1-v3, ADR-0041) exactly at limit and +1, including repeated conversion after recovery | Stream/preflight counters bounded, no oversized allocation; exceeded limit quarantines before publication and does not reset on recovery. Assert unchanged DB/generation state and no certified hash for rejected profile. |
| X01 | File/service/API scope review | Stage 1 has internal selector only; no Stage 2+ feature/cloud provision/destructive retention; migrations remain portable PostgreSQL. |


### Complete-review cross-check

| Astra review section / case | Contract decision | Required test IDs |
|---|---|---|
| 1: Historical dates vs rolling retention; request month boundaries | Fixed run T, exact half-open interval and isolated acceptance (§2) | T01-T04, D04 |
| 1: Zero new rows vs audits/live revisions | Captured-input science and active-generation invariance (§5); live refresh tested separately | R01-R08, F04 |
| 1: Incomplete schema/fallback timestamp | Required keys, FKs, nulls, deletion/month constraints, immutable identity (§4) | I01-I06, B09 |
| 1: Missing revision and shortened level sets | Ordered source vector/hash fallback and complete replacement (§5) | R01-R08 |
| 1: Original/adjusted QC | Explicit per-variable columns and variant mapping (§6) | S01, S04, S06 |
| 1: Geographic requests | Versioned envelope, edge ownership, pinned API format (§3) | G01-G05, T05 |
| 1: Promotion/commit/recovery; not-queryable scope | Final verification, single transaction, internal selector (§7) | P01-P08, P09a-P09c, P10, X01 |
| 2: Wrong checkout | Sanitized 619411a only; archival ancestry excluded (§1) | X01 plus documentation diff/baseline review |
| 2: Partial publication, revision corruption and duplicate results | Atomic commit/replacement, one active slot and concurrency rechecks (§4-7) | R02-R08, P03-P07 |
| 2: Cleanup/retention races | 48-hour/reference/in-flight checks, dry-run only (§2,7,10) | P08, D04 |
| 2: Credentials/destinations | Restricted config, redaction, hostname/DNS/redirect checks (§9) | B05-B06 |
| 2: Resource exhaustion/nested retries | Hard input/memory/time/concurrency budgets and single retry owner (§9) | B01-B04 |
| 2: Unsafe DB loading | COPY FROM STDIN, fixed identifiers, least privilege (§4) | B07, B09 |
| 2: ETag/copy assumptions | SHA-256 read-back and immutable S3-style copy (§7) | P01-P02 |
| 3: Completeness and reconciliation including unknown schema | Terminal chunks and separate unit equations (§8,11); stage1-v3 receipt/exclusion (ADR-0040) | G04-G05, C01-C04, F02 |
| 3: Provenance and persisted reporting | Versioned raw/partition evidence and reproducible reporter (§11) | F01-F03, F07 |
| 3: Outcomes/quarantine and scheduler | Explicit exits, zero tolerated quarantine, UTC singleton/lease/catch-up (§8,10) | C02-C04, D01-D03 |
| 3: Compression/equivalent DataFrame size vs RSS | Fixed measurement method and serialization settings (§11) | F06 |
| 3: Offline CI vs separate WSL2 live verification | CI egress denied; live isolated/opt-in/owner credential (§11-12) | F05 |
| 4: Request-planning cases | Month/UTC/edge/overlap/complete plan contract | T01-T05, G01-G02 |
| 4: Source-contract cases | Name-based arrays, absent optionals, empty/schema/truncation handling | G03-G05, S03, S06 |
| 4: Scientific-mapping cases | Values/QC/units/fill/nonfinite/array/pressure diagnostics | S01-S06, N01-N08 |
| 4: Identity cases, including corrected timestamps | Stable IDs, fallback/aliases, direction and ownership corrections | I01-I04, R08 |
| 4: Revision cases | Identical/newer/stale/reduced/absent metadata outcomes | R01-R08 |
| 4: Concurrency cases | Lease/fencing, slot locks, durable duplicate-delivery budgets | R07, P07, B03-B04, D01 |
| 4: Crash-recovery cases | Object/merge/precommit/postcommit-ack faults | P03-P05 |
| 4: Publication cases including missing object | Selector verification, corrupt/missing object, pending/superseded, orphan safety | P01-P08, P09a-P09c, P10 |
| 4: Retention cases | Frozen T/exact cutoff/historical rejection/isolation, no destruction | T01-T04, D04 |
| 4: HTTP-resilience cases | Auth/429/transients/timeouts/decompressed/retry caps | B01-B04 |
| 4: Security/migrations cases | Redaction/controlled keys/privileges/additive upgrade | B05-B09 |
| 4: Reporting cases | Equations, terminal outcomes, replay deltas and size reproducibility | C02-C03, F02-F04, F06 |
| 5: Stage 0 dependencies and missing Beat service | Preserve foundation and privileges; Beat configuration defined for future implementation only | B07, B09, D01-D03, F01, F05 |
| 6: Later-stage boundaries; BGC schema only | Internal status/recovery retained; query/UI/embedding/user jobs/cloud deferred (§1,4,10,13) | X01 |
| 7: Seven recommended corrections | Baseline, dates, isolation, idempotency, atomicity, policy, reviewed offline/live gate | T01-T05, I01-I06, R01-R08, P01-P08, P09a-P09c, P10, F01-F07, X01 |
| 8: NO-GO verdict | Contract candidate replaces ambiguous decisions; no implementation or approval claimed | Astra contract review required |


### Follow-up Astra contract review: five remaining blockers

This table supersedes the reviewed v1 ambiguity; the original review cross-check above
remains for traceability. P09 is retired as a single case and split into P09a/P09b/P09c;
no empty-fetch test may assert an implicit tombstone.

| Follow-up finding | Explicit v2 decision | Required acceptance cases |
|---|---|---|
| 1. Full snapshots vs rolling eligibility | Full retained stored population and fixed-T run eligibility reconcile independently against identical populations; only superseded revisions excluded (§2,7,11). | T06, F02, F04 |
| 2. Empty refresh vs no tombstones | Empty initial selection, empty refresh over retained science and accepted last-profile ownership correction have distinct receipts/selector outcomes (§7). | P09a, P09b, P09c |
| 3. Late equal-revision conflict | publishing -> quarantined after scientific rollback; fenced evidence-only quarantine/intent abandonment retains references; cancellation fence precedence explicit (§7.1,8). | P11, C09-C10 |
| 4. Recovery/termination/overlap | Every nonterminal phase has an owner/resume rule; process loss recovers, cancellation/deadline close and fence; complete chunks remain complete. overlap_skip is a scheduling_attempt/no-run event, manual exit 6, no watermark change (§8-10). | C05-C11, D05-D06, D01 |
| 5. Decimal conversion/output bounds | Strict JSON, bounded exact decimals/canonical bytes, deterministic ties-even binary64, overflow/nonzero-underflow quarantine; exact quoted nonfinite policy/hash rules (§5.1,6,9). | N01-N08, S02, B01 |

Future implementation gate: every listed offline case passes against implemented code,
DB constraints and local object store; lint/types/current/history secret scans and required
CI checks pass. Isolated opt-in Jan-Mar acceptance and replay produce persisted evidence,
zero quarantine/gaps and balanced reconciliation. An upstream outage or unavailable owner
credential leaves live acceptance pending, never fabricated or waived by processed fixtures.
Astra must accept this contract before implementation, and review implemented evidence
before Stage 2 starts (stage1-v3: the advisor's recorded agreement replaces Astra, ADR-0039).

## 13. Local services, portability and contract-review report

Keep local PostgreSQL/PostGIS/pgvector, MinIO, Redis and Celery from Stage 0. Define
portable PostgreSQL constraints/migrations in later implementation; no Supabase-specific
schemas, hosted auth/storage functions or cloud-only features. Supabase, Azure and other
cloud provisioning are deferred to deployment planning (Stage 8).

Historical contract-review result, before the owner-confirmed GO recorded above:
stage1-v2 adds explicit decisions and acceptance cases for all
five follow-up blockers, retaining the original twelve requirement groups/eight-section
review traceability. Full retained membership, empty-fetch/source-absence/corrected-empty
selection, late-conflict quarantine, phase-by-phase recovery/cancellation/overlap and
bounded numeric semantics are defined. Stage 1 remains an internal data foundation.
The candidate is ready for another Astra review; neither a GO verdict nor implementation
readiness approval is inferred. Only documentation is changed. No acceptance tests or live data runs are executed
or claimed in this turn.
