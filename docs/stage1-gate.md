# Stage 1 gate — Jan-Mar 2025 Indian Ocean acceptance

**Result: live and captured-replay acceptance passed** on session `302412131a7c99fb`, code
`499b821` (stage1-v4 execution, stage1-v3 scientific contract, ADR-0055 item 9). Advisor review of
ADR-0047 through ADR-0055 is recorded in ADR-0055. The gate closes with this evidence commit once
CI on it is green.

## Acceptance evidence

| Check | Live run `edebccd8` | Replay run `8562e75d` |
|---|---|---|
| Leaves | 270 of 270 complete, 0 failed, 0 quarantined | 270 of 270 complete |
| Run state | complete, closed, 0 coverage gaps | complete, closed, 0 coverage gaps |
| Profiles | 5,814 inserted | 5,814 `noop` |
| Levels | 4,144,346 | no change |
| Source policy (S1-SOURCE-2) | 31 `excluded_source_loss`, 64 empty-delivery receipts per role | same |
| Accounting | full snapshot, run-eligible and level-delta balanced | same; scientific and active-partition no-change |
| Catalogue | 206 active parts, 0 snapshots | unchanged |
| HTTP | 1,534 verified (1,342 HTTP 200, 192 HTTP 404 receipts), 2 transport failures retried, 0 HTTP 429 | 3,004 replayed payloads, no upstream request |
| Metadata cache | 1,470 of 2,194 metadata landings from the cache (67 %) | not used (replay) |
| Wall time | 23.1 min (11:35:29 to 11:58:35 UTC) | 13.5 min |

Reports: [live](../reports/stage1-acceptance-live.json), [replay](../reports/stage1-acceptance-replay.json),
[owner result](../reports/stage1-acceptance-owner-result.json),
[memory](../reports/stage1-acceptance-memory.json).

Memory (ADR-0042 as amended by ADR-0047), `pass: true`, 1,987 samples, 0 missed listings:

| Service | Limit | Anonymous peak | memory.peak | OOM |
|---|---|---|---|---|
| live-acquire | 1 GiB | 237 MiB | 308 MiB | 0 |
| acquire (replay) | 1 GiB | 234 MiB | 333 MiB | 0 |
| process (2 workers) | 2 GiB | 673 MiB | 883 MiB | 0 |

Cross-run checks on the preserved databases (read-only):

- Byte identity on live data: all 5,792 profiles of the stage1-v3 live run `7153be63` (3.79 h)
  have identical content hashes in `edebccd8`; the 22 further profiles are tile `50:-20`,
  March 2025, the leaf `7153be63` quarantined for `missing_basin` (ADR-0046).
- Full level audit: `app.audit_levels` over all 206 committed chunks checked 5,814 profiles and
  4,144,346 levels against their canonical text, no mismatch.
- No HTTP 429 in sessions `a34ff826` and `30241213`.

CI (all seven jobs) passed on every pushed head of this session: `222f437`, `7bec2c0`,
`d0e6565`, `499b821`.

## Session ledger, 2026-10-09

All sessions were prepared and executed on this host; every stopped session was interrupted
through the wrapper, with science, objects and database preserved and budgets unchanged.

| Session | Code | Outcome | Cause, fix |
|---|---|---|---|
| `689a21527ccf01de` | `6c88a0a` | stopped, 0 complete | EBADF on idle-read refresh after `Connection: close`; `222f437` |
| `610e1592a7c98390` | `222f437` | stopped, 0 complete | live flag checked on process-pool reload; `7bec2c0` |
| `716d72e226e49f75` | `7bec2c0` | stopped, 58 complete, 3 failed | run-row lock timeout 5 s; `d0e6565` |
| `a34ff8267e859b85` | `d0e6565` | 268 complete, 2 failed, about 54 min | negative retry sleep `b426f62`; sampler crash `499b821`; [report](../reports/stage1-acceptance-live-a34ff8267e859b85.json) |
| `53523f35276d8511`, `1d092dd2d805e6dd` | `499b821` | `prepare` failed, no containers | Docker address pools exhausted (see limitations) |
| `302412131a7c99fb` | `499b821` | **passed**, live and replay | — |

Details of the five live-only defects: ADR-0054.

## Known limitations carried forward

- `commit_publication` holds the `ingestion_run` row for the whole commit (observed above 10 s);
  acquire threads queue behind it (ADR-0054). Shortening the hold is a follow-up.
- The governor reacts only to HTTP 429; upstream slow episodes (connect timeouts, 116 s idle
  reads) are retried but do not reduce concurrency (ADR-0055 item 2).
- The level audit is not wired into any cadence and costs about 0.6 ms per level (ADR-0055 item 4).
- A metadata cache hit carries a synthesized `sanitization` (ADR-0055 item 3).
- Memory at the contractual chunk cap would exceed the 1 GiB worker bound (ADR-0055 item 6).
- Nothing watches the process container during `execute` (ADR-0055 item 1).
- The wrapper has no replay-only entry and refuses a changed source digest, so a replay failure
  after a code fix needs a fresh session and a new live run.
- Docker Desktop's default address pools allow about 31 networks and each session uses one or two.
  To free room, the networks of session `b16db7a1bcbebef5` (prepare-only) and of a leftover Stage 0
  test project were removed; their containers and volumes are intact, but `b16db7a1` containers
  need `docker network create` plus a reconnect before `docker start`. Adding a
  `default-address-pools` entry to the Docker Engine configuration is the durable fix.
- GDAC (ADR-0052) is uncertified; only its source-aware SQL ran in this acceptance.
- Stale text: `docs/stage1-acceptance-preparation.md` (historical NO-GO header, 21,600 s budget,
  migration head 0014; current values are 43,200 s and 0015) and the items listed in
  `docs/v4-packages/I.md` under unannotated Celery and Redis wording.

## Earlier history

The stage1-v1 to stage1-v3 reviews, the original session's terminalization and the stage1-v3 live
runs are recorded in [PROGRESS.md](../PROGRESS.md), DECISIONS.md (ADR-0033 to ADR-0046) and the
reports they link. The previous NO-GO text of this file is superseded by this gate.

## Commit IDs after the 2026-10-09 history rewrite

Commit messages on this branch were rewritten to drop co-author trailers; authors, dates and
every tree are unchanged (`git rev-parse <old>^{tree}` equals the new commit's tree). Reports,
ADRs and this document cite the original IDs; they map as follows.

| Original | Current | Subject |
|---|---|---|
| `1cecd46` | `74ef714` | chore: add delegation agents and ignore local Claude settings |
| `03ba2cd` | `eec2dc2` | feat(stage1): add ingestion migrations 0002-0009 |
| `db5febb` | `118bd86` | feat(stage1): ingestion core, worker runtime and stage1-v3 policy |
| `82968db` | `b4e4031` | feat(stage1): acceptance, terminalization, census and probe scripts |
| `5c4a2ac` | `5b1dbea` | test(stage1): offline, database and processor coverage incl. stage1-v3 |
| `5ebb758` | `3a642a8` | docs(stage1): stage1-v3 contract, ADR-0033..0042 and progress |
| `59021c9` | `8c283e2` | chore(stage1): persisted evidence reports |
| `09bf91d` | `9441156` | fix(stage1): preparation expects migration head 0009 and records git HEAD |
| `03fe835` | `4834e32` | test(stage1): run acceptance-wrapper tests from any checkout path |
| `ccecfd2` | `f20ca1f` | fix(stage1): 12 h run bound, 60 s idle read and CI portability |
| `35ce9e1` | `d699397` | perf(stage1): set-based publication commit and owner-slot index (ADR-0044) |
| `e1ba4f0` | `f4c8708` | fix(stage1): retry window that outlasts upstream slow episodes (ADR-0045) |
| `50dbdbc` | `9223445` | fix(stage1): missing_basin is an informational source warning (ADR-0046) |
| `6c88a0a` | `e0f7a58` | stage1-v4: parallel acquire/process pipeline, verify-once publication, GDAC source (#4) |
| `222f437` | `6365049` | fix(stage1-v4): idle-read refresh must not fail a Connection: close response |
| `7bec2c0` | `daf9952` | fix(stage1-v4): process-pool reload must not require the live flag |
| `d0e6565` | `1ec3875` | fix(stage1-v4): bound run-row lock waits by the transaction bound, not 5 s |
| `b426f62` | `d1482df` | fix(stage1-v4): retry wait never sleeps a negative interval |
| `499b821` | `48a7a21` | fix(stage1): memory sampler survives a stalled docker listing |
| `1a7deb9` | `9502c3d` | docs(stage1): acceptance gate passed on stage1-v4 (ADR-0054, ADR-0055) |
