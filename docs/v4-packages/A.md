# Package A report: fast exact decode, sanitization and canonical encoder

Worktree `/home/floatchat/FloatChat-perf`, base `272508b`. Owned files only; nothing committed.
Scope (design section 3, interface 4.1): `exact_number`, `decode_json`, `documents`,
`sanitize_raw`, `CanonicalBudget.encode`, plus `decimal_text` (below). No limit, rejection
category, precedence, canonical byte or sanitized byte changed; every claim of identity is
backed by a differential test against a verbatim copy of the pre-v4 code.

## Open items for the integrator (read first)

1. **`tests/stage1/test_canonical_encoding_certificate.py` (not mine) needs one edit.** Variant
   A calls `JSONEncoder.encode(level)` for every level by design, so
   `test_large_or_deep_level_never_uses_c_encoding_before_limit` (lines 87-96), which patches
   `JSONEncoder.encode` to raise if it is ever called, now fails (`AssertionError: unbounded`
   is not one of the errors the encoder falls back on). I did not run that file (rule 2); the
   other tests in it exercise the same behaviour as my new sweep in `test_numeric.py` and
   should pass. Exact edit:
   ```
   - delete test_large_or_deep_level_never_uses_c_encoding_before_limit (lines 87-96)
   - drop `_small_json_bound,` from the import (line 13)
   - drop line 56: assert _small_json_bound(level) >= len(json.dumps(level, ...).encode())
   - `from unittest.mock import patch` (line 6) is then unused: drop it
   ```
   Then delete `_small_json_bound` from `numeric.py` (lines 439-472, the function only; `math`
   is still used by `scientific_number`). The task said to remove it if nothing else uses it;
   this file does, so I left it, with a docstring saying why. The intent of the deleted test
   (an oversized level is still rejected with streaming evidence) is covered by
   `test_N08_c_encoded_levels_charge_exactly_like_the_streaming_encoder`.
2. **Memory behaviour of the new encoder (rule 4 note).** A level is now C-encoded in full
   *before* the budget check, so one level's encoded text (at most about 6x the level's
   in-memory string size) is allocated even when it is then rejected. The old bound walk
   refused to do that for levels it could not bound. Mapper levels are tens of bytes to a few
   hundred, and a hostile level would already have to exist in memory as a decoded object, so
   the allocation is bounded by the object the caller already built; I added no further guard
   (the old walk cost more than the C encode it guarded: review section 3.3).
3. **`RawNumber` is now a `str` subclass and no longer validates by itself.** The decoder to
   pass is `raw.raw_number` (`documents(raw, number_decoder=raw_number)`); `RawNumber(token)` is
   a plain `str` constructor. Nothing else in the tree used `RawNumber`
   (`grep -rn RawNumber packages workers scripts tests`: only `raw.py` and
   `test_json_stream.py`, which I updated). `source_token` remains as a property.
4. **`decode_json` and `documents` annotate `number_decoder: Callable[[str], Any]`** (was
   `Callable[[str], Decimal]`) because the sanitizer's decoder returns a `str` subclass. Runtime
   signature unchanged.
5. **`decimal_text` is 8-12x faster, which the mapper (package B) gets for free.**
   `scientific_number` spends about 75% of its time in `decimal_text`; scratch timing, same
   host: `decimal_text` 3.2 us -> 0.27 us per call, `scientific_number` 4.2 -> 2.7 us. The
   remaining 2.5 us is `float(token)`, `Decimal.from_float(rounded) != token`, the frozen
   dataclass and the `Decimal(99999)` / `kinds` rebuilt per call; hoisting the two constants
   measured no gain, so I left `scientific_number` alone (it is in my file; B asked who owns it).
6. **Input must be `bytes`.** The old byte loop silently did nothing for a `str` argument to
   `decode_json`; the regex scan raises `TypeError`. The signature is `raw: bytes` and no
   caller in the tree passes `str`; mentioned because package G's NetCDF code might.
7. **Host noise.** The host is shared with other packages' test runs, and CPU time moves with
   the neighbours' load, so single runs vary. Ratios seen across script runs this session:
   encode 2.5-3.7x, `documents()` 2.3x (before the last optimizations) then 5.1-5.9x,
   `sanitize_raw` 2.5x (before) then 3.8-8.8x. `reports/stage1-v4-bench-A.json` is the last
   run (best of 15 interleaved, `gc.collect()` before every timed call). It sits in package
   J's `reports/stage1-v4-bench-*.json` glob; I wrote it because rule 6 and the brief's
   item 7 name it, nothing of J's was touched.
8. **Dense or huge input falls back to the old byte loop** (`_TOKEN_LIMIT`, `_SCAN_LIMIT`,
   peeling budget; see "Limits and policies"). A legitimate JSON document with more than
   262,144 quotes and brackets, or more than 8 MiB, is therefore decoded at the old speed
   (still correct). No Argovis response in the fixtures comes near that.

## What changed and why

| Item | Change | Where |
|---|---|---|
| 1 `exact_number` | Plain tokens (no exponent, by far the common case) skip the preflight altogether: without an exponent the normalized text is no longer than the token (at most 128 bytes), so the 512-byte check cannot fail. Exponent tokens compute the normalized length arithmetically from `Decimal.as_tuple()` (strip leading and trailing zero digits, add the trailing zeros to the exponent, shared `_layout_length`), no text built; `canonical_output_limit` keeps `requested_bytes`, scope `number`, operation `normalization`. Grammar, 128-byte, exponent checks and their precedence are unchanged (`PLAIN_NUMBER` + `_NUMBER` accept exactly `NUMERIC`'s tokens; the exponent comes from a capture group instead of `re.split`). | `numeric.py:58-118` |
| 1 `decimal_text` | Same text and same errors, but `str(value)` is used when it is plain positional notation (no `E`, at most 512 characters): strip trailing fraction zeros, `-0` is `0`. Everything else runs the old digit-tuple route. | `numeric.py:120-152` |
| 2 `decode_json` prepass | `_structural_caps`: a C-speed filter `_within_caps` (one regex split of the strings, then up to 32 regex splits that peel one bracket level each and count the commas of every array) *clears* an input only when it proves the old byte loop would not raise. Anything else (over a cap, unbalanced or mismatched brackets, input over 8 MiB, input that needs more than 4 scans' worth of peeling) is handed to `_byte_caps`, which is the old loop verbatim and raises the old category in the old byte order. So the scan is at least as strict as before by construction and precedence between `invalid_array_length`, `json_depth_limit`, `json_string_limit` is the old one. The proof obligations are in the `_within_caps` docstring. `_object` is `dict(pairs)` plus a length check (same first-duplicate rejection, same key order); the post-parse 64 KiB / surrogate walk is unchanged except that it queues only strings, lists and dicts, in the same order, with C-level iteration. | `numeric.py:155-323` |
| 3 `documents` | The splitter iterates a regex over strings and brackets only (`_TOKEN`), not over bytes; depth cap, `profile_count_limit` order, `unsupported_response_schema` and `invalid_json` branches are untouched. An unterminated string eats the rest of the input as the old state machine did. | `json_stream.py:9-74` |
| 4 `sanitize_raw` | Numbers are captured as `RawNumber(str)` tokens by `raw_number` (plain tokens within 128 bytes are accepted by regex alone; the rest call `exact_number` for the same rejections). `clean` and `encode` test `type(value) is RawNumber` before `str`, so a numeric credential cannot match number digits. Lists made only of number tokens are joined in one write; strings and keys use `json.encoder.encode_basestring_ascii`, the function `json.dumps(..., ensure_ascii=True)` calls. The 128 MiB output cap and `credential_in_source_content` precedence (clean before encode, per document) are unchanged. | `raw.py:19-131` |
| 5 encoder | Variant A: each level is `encoder.encode(level)`; yielded whole when `len(encoded) <= remaining()`, else streamed with `iterencode` so the first exceeding piece raises with the old scope, `used_bytes` and `requested_bytes`. `TypeError`/`ValueError`/`RecursionError` from the C call fall back to the stream, which raises at the same piece as before (after earlier pieces were charged), so non-finite floats and unsupported types keep their precedence. | `numeric.py:475-517` |
| 7 script | `scripts/stage1_perf_experiments.py` now vendors the pre-v4 code (copied from `272508b`), runs old and new interleaved on the same synthetic chunk, asserts identical output (exact `Decimal` form for decoded structures), records best-of-N wall and CPU, keeps the recorded reference lower bounds and prints the recorded numbers of `reports/stage1-perf-experiments.json` next to the fresh ones. | `scripts/stage1_perf_experiments.py` |

Limits and policies: none changed. Three *implementation* thresholds were added that only
choose the code path and never an outcome (rule 4):

- `_TOKEN_LIMIT` = 262,144 quotes and brackets (`numeric.py:174`): above it the old byte
  loop runs. The filter holds one `bytes` object per string and per innermost pair (about 50
  bytes each) while the byte loop holds none, so without this bound a hostile 8 MiB document
  of `"",` or `[],` would build millions of objects (about 250 MB) before being handed over,
  and a worker under a 1 GiB `RLIMIT_DATA` could die with `MemoryError` instead of
  quarantining with `invalid_array_length`. With it the filter's objects stay under about
  15 MB. The count is five `bytes.count` calls, no allocation. A real document has a few
  hundred quotes and brackets.
- `_SCAN_LIMIT` = 8 MiB (`numeric.py:175`): above it the byte loop runs, so the filter's
  copies of the input (strings split, skeleton) stay at about 3x of at most 8 MiB.
- A peeling budget of four scans of the string-free input (`_within_caps`): input that
  shrinks too slowly under per-level peeling (many side-by-side deep structures) is decided
  by the byte loop rather than scanned up to 32 times.

Dense or huge input therefore costs what it cost before (the byte loop), never more in memory
and at most one extra C-speed scan in time. No ADR needed; no contract clause (section 5,
5.1, 6 of `docs/stage1-contract.md`, `raw-sanitization-v1`, `scientific-json-v2`) is touched.

## Tests

Added (all against verbatim pre-v4 oracles kept in the test files):

- `tests/stage1/test_numeric.py`: `test_N01_N02_exact_number_agrees_with_pre_v4_on_swept_tokens`
  (6,000 random plus edge tokens, value and evidence), `test_N02_preflight_length_is_decimal_text_length`,
  `test_N02_signed_boundary_of_normalized_preflight` (512/513 with and without `-`),
  `test_N05_decimal_text_is_unchanged_for_every_decimal_shape` (20,000 random Decimals, tuple
  shapes, NaN/Infinity, 511-513 byte boundaries), `test_B01_structural_caps_categories`
  (depth 33 arrays/objects/mixed/unbalanced, 10,001 elements of numbers/strings/nested, string
  393,217 plain and escaped, unterminated, duplicate key beats a 100 KB string while a 400 KB
  string beats the duplicate key, `]`/`}` and escaped quotes in strings, lone surrogate),
  `test_B01_structural_caps_accept_within_caps` (also asserts the filter clears them without
  the byte loop), `test_B01_string_cap_is_exact_at_the_prepass_bound`,
  `test_B01_array_cap_is_exact_at_the_element_bound` (9,998-10,002 elements in five shapes),
  `test_B01_filter_hands_hostile_shapes_to_the_byte_loop`,
  `test_B01_token_dense_input_is_rejected_without_per_token_allocation` (140,000-unit documents of
  quotes, empty arrays, empty objects and object members: the filter declines, the outcome equals
  the byte loop's and `tracemalloc` peak stays under 1 MiB),
  `test_B01_structural_scan_agrees_with_byte_loop_on_fuzzed_input` (60,000 random and damaged
  documents with caps lowered to 3/4/7 so every boundary is reachable; asserts soundness: a
  cleared input is never one the byte loop rejects),
  `test_B01_decode_agrees_with_pre_v4_on_generated_and_damaged_documents` (8,000),
  `test_B01_string_walk_precedence_matches_pre_v4` (17 documents: walk order of oversized and
  surrogate strings), `test_N08_c_encoded_levels_charge_exactly_like_the_streaming_encoder`
  (every limit from 1 to total+2, three scopes, seven contents including NaN, Infinity,
  an unserializable object, non-dict levels; compares result, evidence, `run_used`,
  `chunk_used`), `test_N08_rejects_at_a_level_boundary_with_the_streaming_charges`,
  `test_N08_fitting_levels_are_c_encoded_and_only_oversized_levels_are_streamed`.
- `tests/stage1/test_json_stream.py`: updated the token test to `raw_number`; added
  `test_stream_agrees_with_pre_v4_splitter` (about 40 crafted responses x 3 document limits,
  including depth 28-34, brace/bracket/escaped quote in strings, unterminated strings,
  mismatched closers, extra and missing separators), the generated-and-damaged fuzz (12,000)
  and `test_stream_deep_document_after_the_count_limit_is_reported_by_depth_first`.
- `tests/stage1/test_raw.py`: `test_B04_recorded_fixtures_sanitize_byte_identically_to_pre_v4`
  (every JSON fixture under `tests/fixtures/argovis`, with and without a credential; recorded
  payloads are fixed points), crafted documents x 6 credentials (including digit credentials `1`, `5`, `e`),
  3,000 generated documents, the 128 MiB cap with a lowered limit,
  `test_B04_number_tokens_never_reach_the_credential_scan`,
  `test_B04_raw_number_rejects_exactly_what_exact_number_rejects`, and a coverage test that
  the crafted set really hits nine rejection categories.

I checked that the fuzz and category tests have teeth by mutating the filter (array bound
`>=` to `>`, string bound off by one, depth range plus one, bracket residue check removed,
array filter removed), the splitter (depth cap, unterminated alternative, string alternative,
break depth) and `decimal_text` (the `-0` rule, the length gate, integer stripping, the `E`
gate), and the token gate (removing it fails the allocation test): every unsound mutant was killed; the one survivor (`len(token) > limit` instead of
`len(token) - 1 > limit`) only declines more inputs to the byte loop and cannot change an
outcome.

Commands run (all through `flock /tmp/claude-1000/perf-test.lock nice -n 19`):

- `.venv/bin/python -m pytest tests/stage1/test_numeric.py tests/stage1/test_json_stream.py
  tests/stage1/test_raw.py tests/stage1/test_wire.py tests/stage1/test_byte_identity.py
  -m "not integration" -q -p no:cacheprovider`: **523 passed** (final run; byte identity
  `test_byte_identity.py` passed in every run). Baseline before any change: 109 passed.
- `.venv/bin/ruff format` and `ruff check` on the seven owned files: clean (`ruff format --check`:
  7 files already formatted).
- `.venv/bin/mypy packages/core/src/floatchat_core/ingestion/numeric.py .../raw.py .../json_stream.py`:
  `Success: no issues found in 3 source files` (strict).
- Not run: `tests/stage1/test_canonical_encoding_certificate.py` (not owned, rule 2; see open
  item 1), any `-m integration` test, anything touching docker, the key or the network.

## Measurements

`reports/stage1-v4-bench-A.json`, produced by `scripts/stage1_perf_experiments.py --repeat 15`
(30 x 699 = 20,970 levels, 126,000 number tokens, 626,131 raw bytes, 25.6 MB canonical,
interleaved best of 15, `gc.collect()` before each timed call, output identical to pre-v4
asserted in the script). Wall seconds; CPU seconds agree to 1%. The clone payload is a
fixed point of `sanitize_raw`, so one sanitize row covers both the raw and the landed case.

| Stage | pre-v4 | v4 | speedup |
|---|---|---|---|
| `CanonicalBudget.encode`, all profiles | 0.797 | 0.251 | 3.2x |
| `exact_number`, 126,000 tokens | 0.267 | 0.053 | 5.0x |
| `decimal_text`, 126,000 values | 0.139 | 0.019 | 7.2x |
| structural scan of the 626 KB payload | 0.066 | 0.004 | 17x |
| `decode_json`, one profile document | 0.011 | 0.002 | 5.3x |
| `documents()` over the payload | 0.392 | 0.070 | 5.6x |
| `sanitize_raw`, profile payload | 0.659 | 0.175 | 3.8x |

Against the recorded experiments (`reports/stage1-perf-experiments.json`, best of 3, same
chunk, earlier session): encode was 0.888 s (current) and 0.4275 s (variant A prototype); now
0.251 s, faster than the prototype and 1.5x off the 0.171 s one-`json.dumps`-per-profile bound
measured in the same run. `documents()` was 0.577 s (current) and 0.3856 s ("Decimal only"
prototype, no preflight); now 0.070 s, faster than the prototype because the byte prepass,
the object hook and most of the post-parse walk are gone too. The remaining floor is one
`Decimal(token)` per number (about 0.29 us) plus the scanner's Python callback; `json.loads`
with token capture is 0.010 s. `sanitize_raw` is bound by the same per-number Python
callback (`raw_number`: one regex, one length check, one `str` subclass construction); the
document-level work (`clean`, `encode`, joins) is about 6% of it under cProfile.

Against review section 3.3 (87x699, µs per level incl. repeats, review host): `documents()`
x5 was 211 and `sanitize_raw` 94. The local ratios above (5.6x and 3.8x) put those rows at
about 38 and 25; the "map_profile + encode" row (136) also depends on package B's mapper,
which now inherits the faster `decimal_text`.

## Notes for other packages

- B: `decimal_text` / `scientific_number` are faster now (open item 5); `map_profile` needs no
  change. `decode_json` still returns `Decimal` for numbers.
- E / D: `documents()` count in `validate_raw` (`landing.py:54`) is cheaper for free; no
  interface change.
- F: `CanonicalBudget.encode` has the same charging at the boundary (`used_bytes` and
  `requested_bytes` of the first exceeding piece), so persisted `run_used` / `chunk_used`
  counters recover identically.
