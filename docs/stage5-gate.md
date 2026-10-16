# Stage 5 gate report - historical jobs and exports

- Stage 5 - **complete** (software, tests, CI scenario, the ten-year run and its report);
  one measured deviation and one host incident recorded below.
- Branch `codex/stage-5` from `design/ocean-light` (`b688cd9`); pull request against
  `design/ocean-light` (ADR-0077). Plan: [docs/stage5-plan.md](stage5-plan.md); decisions
  ADR-0077 to ADR-0081.

## What was built

- Migration `infra/migrations/versions/0019_jobs_exports.sql`: the `historical` ingestion run
  mode (mode constraints, run trigger, `admit_run`, `persist_plan` with descriptor tiles,
  `query_environment` reference time from non-historical runs) and the tables `analysis_job`,
  `analysis_job_chunk`, `analysis_job_event`, `analysis_artefact`.
- Historical runs: `floatchat_core/ingestion/planning.py` (`RunPolicy` mode `historical`,
  `plan(tiles=...)`, `grid_tiles`), `repository.py` (descriptor tiles), the CLI
  `floatchat ingest --mode historical --tiles 50:0,...`.
- Jobs core `packages/core/src/floatchat_core/jobs/`: `model.py` (request schema
  `export-request-v1`, `JobLimits`, records), `store.py` (PostgreSQL and memory stores:
  idempotency, attachment, `SKIP LOCKED` claims, leases, versions, events, artefacts),
  `planner.py` (months × tiles against the catalogue; fetch chunks per calendar year of missing
  months; the export chunk), `runner.py` (claim, plan, fetch with bounded retries, export,
  finish, cancel, resume after a lease lapse), `export.py` (DuckDB `COPY` over the verified
  parts with members from PostgreSQL; manifest `export-manifest-v1` and provenance sidecar),
  `ingestion.py` (historical runs through the Stage 1 `Repository`), `artefacts.py` (HMAC
  download tokens).
- Worker `workers/src/floatchat_workers/jobs.py` (`floatchat jobs --queues export,forecast`),
  the reconciler (expiry: state before object; orphan sweep), `scripts/dev_worker.py` (waits
  for one adopted environment), the dev-stack services `acquire`, `process`, `supervisor`,
  `jobs`, the `floatchat_ingest` login and the environment adoption in `scripts/bootstrap_db.py`.
- API `apps/api/src/floatchat_api/jobs_api.py`: `POST /v1/exports` (202), `GET /v1/jobs`,
  `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/events` (SSE with `id:` lines, `Last-Event-ID`,
  keep-alive comments), `POST /v1/jobs/{id}/cancel` (version check), `GET
  /v1/artefacts/{id}/download?token=`; codes `job_not_found`, `job_conflict`,
  `artefact_unavailable`, `token_invalid`, `jobs_unavailable`; OpenAPI 0.4.0.
- Web `apps/web/src/jobs/`: `/jobs`, `/jobs/:jobId` (chunk table, artefacts with size, counts,
  checksum, expiry, citation, download; cancel), the dashboard `ExportAction` (format select,
  spans up to twenty years), the chat `JobOffer` card for a plan over the span bound
  (`chat/pipeline.py` outcome `job_offer`).
- Report script `scripts/stage5_report.py`; README section; `tests/stage5/`.

## How to run and see it

```bash
make dev                                 # the stack with the ingestion pool and the jobs worker
# live ingestion for historical months (the acquire service only):
scripts/with_argovis_key.sh python3 -m scripts.dev dev   # with FLOATCHAT_LIVE_INGESTION_ENABLED=true in the config
python scripts/stage5_report.py run --region "Arabian Sea" --start 2015-04-01 --end 2025-04-01
```

Open http://127.0.0.1:5173/dashboard, choose a region and period, "Export filtered dataset";
the job page at `/jobs/<id>` follows the chunks and offers the downloads.

## Tests and CI

- Python: `tests/stage5/` (runner over doubles: year grouping and reuse, attachment and
  idempotency, a worker killed mid-chunk resuming without repeating chunks and re-attaching to
  its running ingestion run, upstream down ending partial with the missing slots listed and
  bounded retries, overlap waiting, cancellation, export failure, months not ended; export
  writer over seed parts; jobs API incl. SSE replay and resume, tokens, client scoping;
  reconciler: expiry order and orphan removal), `tests/stage4/test_pipeline.py` (job offer),
  `tests/stage1/test_policies.py` (historical policy), bootstrap, compose and OpenAPI tests.
  Full non-integration suite: see the counts in the pull request's CI; locally 1985 passed with
  the three known intermittent `tests/test_refetch.py` HTTPS deadline cases (also on `main`).
- Web: Vitest (`src/jobs/JobsPage.test.tsx` and the updated app and dashboard tests), ESLint,
  Prettier, TypeScript, production build.
- CI integration (`scripts/integration.py`): an export over the seeded months completes with
  every slot reused and a verified signed download, a forged token is refused, and an export over
  unfetched months ends `partial` with the gaps listed because live ingestion is off there;
  Playwright `e2e/jobs.spec.ts` runs the dashboard-to-download path.

## Measured results

See [reports/historical_jobs_2026-10-16.md](../reports/historical_jobs_2026-10-16.md) (written
by `scripts/stage5_report.py report` from the job rows; the JSON sidecar holds every row).
Numbers are not repeated here by hand. What the three runs of the same ten-year Arabian Sea
request show, in words:

- Run 1 fetched nine of ten years through the job system across the clock jump, three worker
  rollouts and the defects found above; its 2015 chunk failed under the pre-retry runner and
  its export failed when the lease lapsed (both fixed, recorded above). The runs it created
  are in the catalogue.
- Run 2, the identical request, planned nine small fetch chunks for the 76 slots still
  missing, reused 94% of the slots, fetched the rest in one pass, skipped the slots the source
  policy had quarantined, and exported the ten years; it ended `partial` with the twelve
  quarantined month-tiles declared in the result and the manifest.
- Run 3 reused 99% of the slots, admitted no ingestion run, and produced a data artefact
  byte-identical to run 2's.

## Deviations from the PRD

- Queues are PostgreSQL, not Celery/Redis (ADR-0077, following ADR-0047).
- Historical months are stored in PostgreSQL as well as Parquet (ADR-0078 point 4); the report
  records the bytes the region added, which is the trigger input for a Parquet-only tier.
- Attachment is per client until Stage 7 brings users (ADR-0079).
- The signed URL is the API's own route with an HMAC token, not an object-store presigned URL
  (ADR-0079).

## Known issues and risks

- **Host clock jump during run 1.** The WSL2 clock jumped about seven hours at 00:48 UTC while
  the first historical run (2015) was fetching. The Stage 1 run passed its `work_deadline` at
  once and ended `deadline_expired` with 25 of 90 chunks complete, the supervisor's database
  session was lost and every tick failed until the container was restarted, and the job marked
  2015 failed. Two fixes followed: the supervisor rebuilds its connection after a failed tick,
  and a fetch chunk whose run ends short is re-planned for the still-missing slots and admitted
  again (at most three runs). The second run of the same request then fetched the 2015 gaps
  and reused everything else, which is what the report measures. Recorded timings that span
  the jump are not wall time; the report derives durations from chunk timestamps after it.
- The process pool was raised from one to three workers (`INGESTION_PROCESS_WORKERS=3`) and the
  jobs and supervisor containers were rebuilt and restarted while run 1 was in flight; the run
  recovered under Stage 1's lease recovery and the job resumed after its lease lapsed. This is
  the gate checklist's "stop the worker, start it again" check, done unplanned.
- **Found and fixed during run 1:** when another job's run had a lapsed controller lease
  (after a supervisor restart), `admit_run` answered `recover` with that run's id and the
  job runner treated it as its own: the Arabian Sea 2016 chunk recorded the Laccadive Sea
  2019 run as its retry and was marked complete with two slots still missing. The adapter now
  accepts only runs its request created, and a chunk is complete only when the catalogue
  covers it (never because a run said so); a regression test covers both. The second run of
  the request re-fetches those two slots, which the report shows.
- **Found and fixed during run 1 (fairness).** With three jobs queued and two single-threaded
  job workers, the Arabian Sea job sat unowned for over an hour because each worker was busy
  with another job and Stage 1 admits one historical run at a time anyway. A job now yields
  the ingestion scope after each run (`JOBS_YIELD_SECONDS`, default 20 s) so a waiting job
  can admit its own run, waiting jobs poll admission every 10 s, and the development stack
  runs three job replicas (`--scale jobs=3`). One worker process serves one job at a time; a
  queue longer than the replica count waits, which the job list shows as `queued`.
- **Found and fixed during run 1 (export spill).** The Bay of Bengal six-year export failed
  with a DuckDB I/O error: sorting the export under the 256 MiB memory limit spilled to
  DuckDB's default temp directory, which the non-root worker cannot create. The export and the
  series builder of Stage 6 now set `temp_directory` under their own allowed directory
  (`<export dir>/.duckdb-tmp`); the job was re-queued and exported over its already-fetched
  years (the report lists it).
- **Found and fixed during run 1 (quarantined slot).** The Arabian Sea tile 50:20 was
  quarantined in 2017-02 by every run that fetched it (`upstream_data_warning`: Stage 1
  quarantines the whole month-tile, ADR-0040/0046) and a quarantine writes no coverage receipt,
  so the runner fetched it three times per request and failed the 2017 chunk. The runner now
  reads quarantined leaves of closed runs and never admits them again; the chunk completes
  with the slot listed, the result and the export declare it, and the job ends `partial`
  (ADR-0086). A regression test covers the first and the second request.
- **Found and fixed during run 1 (finalisation budget).** With the historical months in the
  store, `finalize_run`'s whole-store evidence capture took about 75 s (`scientific_snapshot`
  29 s, the availability counts of `report_metrics_snapshot` 46 s, measured on this host)
  against the 60 s transaction bound; the supervisor failed every tick and no run could close.
  Finalisation now runs under `INGESTION_FINALIZE_BUDGET_SECONDS` (default 600). The
  snapshots stay O(store); ADR-0086 records the follow-up.
- **Found and fixed during run 1 (lease during the export).** The ten-year export's DuckDB
  sort ran for minutes without returning to the runner, so no heartbeat was sent, the 120 s
  lease lapsed, a second and then a third replica claimed the job and all three wrote the
  same spill file; the export failed with an I/O error on every replica. The runner now
  renews the lease from a thread while the export (and the forecast fits) run, and every
  worker process spills into its own directory. The job was then requested again; the
  report shows that run.
- **Found and fixed in CI review (seed coverage).** The CI export over the seeded months had
  ended `partial` since the first Stage 5 run: the Docker seed wrote receipts only for the
  three Arabian Sea month-tiles holding profiles, so 17 of the 20 slots in January-February
  2025 were uncovered. `scripts/science_seed.py` now stores the profile-free month-tiles of
  its acceptance run as empty slots with verified-empty receipts, as a real run does; the
  export completes with every slot reused. The Playwright jobs spec, which had never reached
  its download assertion, also passed a regex where the attribute name belongs; corrected.
- **Signed download tokens in history.** Commits `93d9753` and `18889e2` carried the signed
  download URLs of the report runs in `reports/historical_jobs_2026-10-16.json` (removed in
  `100a5d4`). They are local-only, bound to one export each, and expire on 2026-10-23; the
  development signing key was rotated and the twelve findings are allowlisted in
  `.gitleaksignore` on the design branch, because the history scan covers every branch.
- A supervisor restart leaves an open run to its controller lease (ten minutes) before
  another controller recovers it; a job waiting on that run waits the same time.
- `tests/test_refetch.py` HTTPS deadline cases are intermittent on this host (known since
  Stage 4).
- Exports of very large selections are bounded by the worker's 256 MiB DuckDB memory and its
  4 GiB part cache; a selection beyond them fails with `cost_over_budget` rather than
  degrading.

## Needs from Aayush

- Review and merge the design pull request, then this one (stacked on `design/ocean-light`).
- Keep `ARGOVIS_API_KEY` and `FLOATCHAT_LIVE_INGESTION_ENABLED=true` in the restricted
  configuration (or start the stack through `scripts/with_argovis_key.sh`) whenever historical
  months must be fetched; without them jobs over unfetched months end `partial`.
- Decide whether historical months should move to a Parquet-only tier once the recorded
  PostgreSQL growth per region is judged (ADR-0078 point 4).

## Proposed plan for the next stage

Stage 6 (forecasting) is built on `codex/stage-6` from this branch: forecast jobs on the
`forecast` queue, the monthly profile-balanced series over the committed parts, seasonal-naive
and SARIMA candidates with rolling-origin backtests, the workspace UI and `make eval-forecast`
(docs/stage6-plan.md, ADR-0082 to ADR-0085).
