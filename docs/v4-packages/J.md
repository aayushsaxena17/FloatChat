# Package J: benchmark harness (report persisted by the integrator from the worker's hand-back)

## Files changed
- `scripts/stage1_perf_profile.py`: `main()` body moved into `profile_chunk(profiles, levels, work, *, basis="core6", cprofile=False) -> dict` (same report keys); `print_table(report)`; `MemoryStore` gains `write_immutable(key, data, sha256_hex, deadline)` and `stat(key, deadline)`; the parquet monkeypatch restore is now in `try/finally`.
- `scripts/stage1_perf_model.py`: new `--cpu <path>` option (default `reports/stage1-perf-chunk-cpu-87x699.json`); output keys unchanged.
- `tests/stage1/test_chunk_scale.py` (new): `test_chunk_cpu_budget_87x699` (opt-in with `STAGE1_BENCH=1`, writes `reports/stage1-v4-bench-chunk.json` with `git_head`, asserts `sum_measured_wall_s < 120`) and `test_chunk_profile_smoke` (always runs, 2x50).
- `reports/stage1-v4-bench-chunk.json` (new): baseline at `272508b` before any other package landed.

## Commands and results
- `pytest tests/stage1/test_chunk_scale.py`: 1 passed, 1 skipped.
- `STAGE1_BENCH=1 pytest tests/stage1/test_chunk_scale.py -s`: 2 passed; `sum_measured_wall_s = 58.225` (87x699, core6; rss 683 MiB).
- `pytest tests/stage1/test_byte_identity.py`: 6 passed.
- `stage1_perf_model.py --cpu reports/stage1-v4-bench-chunk.json`: 1,382.3 µs/level (default report: 1,425.4).
- `ruff format`/`ruff check` on owned files: clean.

## Baseline stage table (wall s, 87x699 at 272508b)
write_snapshot 17.69 (verify_snapshot 10.85), map_profile + budget.encode 9.96, publish_verified 9.83, spool.prepare 4.85, spool.write_candidates 4.45, spool.profiles re-read 2.36, sanitize_raw 2.33, documents() decode 2.30, validate_raw 2.05, spool.membership 1.86.

## Notes
- `parquet_bytes` varies by about 10 bytes between runs because `profile_id` uuid4 values are embedded; not a regression signal.
- The full offline suite was not run by the worker (rule 2); the integrator runs it after each package lands.
