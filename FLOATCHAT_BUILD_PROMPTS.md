# FloatChat: staged build prompts for a coding agent

Use these with Astra (or any long-running coding agent) together with `FLOATCHAT_PRD_v2.md`.

## How to use this file

1. **Before you start:** revoke every Gemini key that was in the old repo, then collect the accounts in "What you need ready" below.
2. Start an agent session with access to your `aayushsaxena17/FloatChat` repo and attach `FLOATCHAT_PRD_v2.md`.
3. Paste the **Master prompt** once, then the **Stage 0** prompt.
4. When the agent stops with a gate report, run the "How to run" commands yourself and tick the "Your gate checklist" for that stage. Only then paste the next stage prompt.
5. If a session gets long or you start a new one, paste the Master prompt again plus: *"Resume from PROGRESS.md. Current stage: N."*
6. After Stage 4 and Stage 6, copy the numbers from `reports/` into your resume in place of the mock numbers.

### What you need ready

| Item | Needed by | Notes |
|---|---|---|
| New Gemini API key | Stage 4 | Fresh key; never commit it |
| Argovis API key | Stage 1 | Free registration on the Argovis site |
| Cloudflare account (Pages + R2) | Stage 8 (R2 can start in Stage 5) | Free tier is enough to start |
| Ubuntu VM (≥4 vCPU, 8–16 GB RAM) | Stage 8 | Any VPS or free-tier cloud VM |
| Domain or subdomain | Stage 8 | Optional but looks better on applications |
| OIDC provider tenant (Auth0, Clerk or Keycloak) | Stage 7 | Free tier |
| Second LLM key (optional) | Stage 4 | Enables the two-model ablation in §30.3 |

---

## Master prompt

```text
You are the lead engineer building FloatChat from the attached specification
FLOATCHAT_PRD_v2.md ("the PRD"). Read the whole PRD before writing code.
§0 overrides later sections. §29 defines the build stages, §30 the evaluation
plan, §31 the repository layout and conventions.

The repository already contains a hackathon prototype (notebook, python.py, a
Parquet sample). It is being rebuilt from scratch into the system the PRD
describes. The prototype goes to legacy/prototype/ in Stage 0.

WORKING RULES
1. Build in stages 0-8, in order, and only the current stage. At the end of
   each stage, stop and write a Gate Report (format below). Wait for my
   approval before starting the next stage.
2. Keep state in the repo. PROGRESS.md holds the stage checklist, what is done,
   what is next and known issues. DECISIONS.md holds ADRs (decision,
   alternatives, reason). Update both before every gate. At the start of any
   session, re-read the PRD, PROGRESS.md and DECISIONS.md.
3. Do not deviate from the PRD silently. If something in it is wrong,
   impractical or ambiguous, write an ADR proposing the change and flag it in
   the gate report.
4. Tests are part of the work. A stage is done only when lint, type checks and
   tests pass locally and in CI. Never mark work done with skipped or failing
   tests.
5. Never invent results. Every number you report (accuracy, latency, MASE, row
   counts, sizes) must come from a script you ran, with its output saved under
   reports/. If you could not run something, say so plainly.
6. Never commit secrets. Use .env (gitignored) and keep .env.example complete.
   When you need a real value from me, ask for it by variable name.
7. Use real Argo data from Argovis, with recorded fixtures for tests. Respect
   rate limits; tests must never call upstream services.
8. Prefer the PRD's chosen tools. No new framework, service or paid dependency
   without an ADR and my approval.
9. Make small commits with conventional-commit messages. Use one branch and
   one pull request per stage.
10. If you are blocked on something only I can do (accounts, keys, DNS,
    payment, approving a force-push), list it under "Needs from Aayush" and
    continue with everything else.

GATE REPORT FORMAT
- Stage N - complete / partial
- What was built (bullets with file paths)
- How to run and see it (exact commands and URLs)
- Tests and CI (counts, pass/fail, coverage for packages/core)
- Measured results (only from files in reports/, with links)
- Deviations from the PRD (with ADR links)
- Known issues and risks
- Needs from Aayush
- Proposed plan for the next stage

Start with Stage 0 only.
```

---

## Stage 0: Foundations and repo hygiene

```text
STAGE 0 - Foundations and repo hygiene (PRD §0 change 7, §16.1, §19.1, §31)

Goal: a clean monorepo that starts locally with one command, has CI, and has
no secrets in it.

Scope
1. Secret remediation
   - Scan the full git history with gitleaks. List every secret found, masked
     (first 8 characters only), with the commit and file.
   - Tell me to revoke them. Prepare a history rewrite with git filter-repo,
     but do NOT force-push until I confirm the keys are revoked and approve
     the push.
   - Add gitleaks to pre-commit and CI.
2. Prototype
   - Move the notebook and python.py to legacy/prototype/ with a short README
     explaining what they were.
   - Remove the 10 MB Parquet file from the repo. Replace it with a script
     that re-fetches it, plus a small sampled fixture (under 1 MB) for tests.
3. Scaffold the layout in PRD §31 with a uv workspace (Python 3.12) and a pnpm
   workspace (web).
4. Add infra/docker-compose.dev.yml with: PostgreSQL with PostGIS and pgvector,
   Redis, MinIO, the API (FastAPI hello world), one Celery worker, and the web
   app (Vite).
5. API: /v1/health/live and /v1/health/ready. Ready checks the database,
   Redis and object storage.
6. Alembic set up with an initial migration that enables the postgis and
   vector extensions.
7. Makefile targets: dev, test, lint, typecheck, eval (stub that prints "not
   yet implemented").
8. GitHub Actions: Python lint, type and test; web lint, type and test; Docker
   image build; gitleaks. All required for merge.
9. README: one-paragraph description, the architecture diagram from PRD §4
   (Mermaid), "Status: under construction", and quick start. Also add
   PROGRESS.md, DECISIONS.md and .env.example.

Acceptance criteria
- `make dev` starts everything; /v1/health/ready returns OK.
- CI is green on the PR.
- gitleaks finds nothing in the working tree.
- The history rewrite is prepared but waiting on my approval.

Out of scope: any domain logic.
Stop at the gate.
```

**Your gate checklist:** run `make dev` and open the health URL, confirm CI is green, and confirm you revoked all the keys before approving the force-push.

---

## Stage 1: Data foundation

```text
STAGE 1 - Data foundation (PRD §6, §7)

Goal: real Argo data flows from Argovis into validated Parquet and PostgreSQL,
with provenance, idempotently.

Scope
1. Migrations for argo_float, argo_profile, core_measurement, bgc_measurement
   (created, unused in v1), ingestion_run and dataset_partition, with the
   keys, constraints and indexes in §6.
2. The ArgoSourceAdapter protocol (§7.1) and an Argovis adapter with plan,
   fetch, parse and source_revision. Implement the chunking in §7.2 with
   timeouts, exponential backoff with jitter, attempt limits, response-size
   limits and rate-limit handling.
3. The publication pipeline in §7.6, end to end: raw landing (hashed),
   canonical normalisation (§7.4), structural and scientific validation
   (§7.5), quarantine for unknown schemas, Parquet written to a temporary key,
   read back and verified, promoted to a content-addressed key, then the
   catalogue commit.
4. Bulk-load rows inside the rolling 12-month window with COPY into staging
   tables, then an idempotent merge into the target tables.
5. CLI: `floatchat ingest --region indian-ocean --from 2025-01 --to 2025-03`.
   Start with the Indian Ocean and core variables (pressure, temperature,
   practical salinity).
6. A daily scheduled ingestion with an overlap window (§7.7) using Celery
   beat.
7. Tests using recorded Argovis fixtures:
   - parsing and field mapping
   - schema drift goes to quarantine
   - re-ingesting the same data creates zero duplicates
   - a Parquet object without a committed catalogue record is not queryable
8. reports/ingestion_<date>.md with profile and measurement counts per stage,
   quarantine counts, timings, and Parquet size versus in-memory DataFrame
   size.

Acceptance criteria
- Jan-Mar 2025 Indian Ocean data ingests end to end on my machine.
- Running the same ingest again produces zero new rows.
- Counts reconcile across raw, normalised, Parquet and PostgreSQL in the report.

Stop at the gate.
```

**Your gate checklist:** run the ingest command twice and check the second run adds nothing. Open the report. Spot-check one float against the Argovis website.

---

## Stage 2: Query engine and API

```text
STAGE 2 - Query engine and API (PRD §8, §13)

Goal: one validated query-plan format that compiles safely to SQL or DuckDB
and is served through a documented API.

Scope
1. QueryPlan Pydantic models matching §8.1, with every rejection rule in §8.1.
2. Named-region table with polygons for at least: Indian Ocean, Arabian Sea,
   Bay of Bengal, Andaman Sea, Laccadive Sea, Southern Indian Ocean. Use
   polygons from a cited public source.
3. Compilers (§8.2):
   - PostgreSQL/PostGIS compiler using parameterised SQLAlchemy
   - DuckDB compiler over an explicit allow-list of catalogue-selected object
     URIs
   - Plotly chart-spec compiler from bounded result schemas (§11.3)
4. The coverage router in §8.3, with partial-coverage labelling, and the
   result sanitiser in §8.5.
5. Endpoints: catalog/parameters, catalog/coverage, floats, floats/{id},
   profiles, profiles/{id}, and POST /v1/query.
   - Use a read-only database role with a statement timeout.
   - Follow the API conventions in §13.2 (versioning, error codes,
     correlation ID, cursor pagination).
6. Publish OpenAPI and generate the TypeScript client into apps/web.
7. Tests:
   - compiler allow-lists
   - SQL injection attempts through every plan field
   - coverage interval arithmetic
   - longitude conventions and dateline cases
   - nearest-profile queries using ST_DWithin with geodesic ordering
8. reports/query_latency_<date>.md: p50/p95 latency for 10 representative
   queries per route (PostGIS, DuckDB hot tier).

Acceptance criteria
- No endpoint accepts raw SQL.
- All tests are green.
- The latency report is generated by a script.

Stop at the gate.
```

**Your gate checklist:** try a few queries in the API docs page (`/docs`). Ask the agent to show you one compiled SQL statement and explain it, because you'll be asked about this in interviews.

---

## Stage 3: Web dashboard

```text
STAGE 3 - Web dashboard (PRD §2.1, §14)

Goal: a usable research dashboard over local data.

Scope
1. React + TypeScript + Vite app.
   - Routes: /dashboard, /explore/map, /explore/profiles (others as stubs).
   - Use the generated API client and TanStack Query.
   - Filters live in the URL (§14.3).
2. Map view (MapLibre):
   - profile locations with clustering
   - float trajectories
   - clicking a profile loads it on demand
3. Charts (Plotly):
   - temperature versus depth and salinity versus depth
   - temperature-salinity diagram
   - time series
   - distribution views
4. Data panels:
   - coverage panel: date range, region, profile counts, missingness, source
     timestamp and ingestion timestamp
   - provenance panel (§17) on every result
5. Accessibility basics from §14.5: keyboard navigation, visible focus, units
   on every axis, colour-blind-safe palette.
6. Tests:
   - Vitest and React Testing Library for components
   - Playwright end-to-end: open the dashboard, filter to Arabian Sea,
     January 2025, 0-100 dbar, and see map points and a profile chart

Acceptance criteria
- The end-to-end test is green in CI.
- The dashboard works against data from Stage 1.

Stop at the gate.
```

**Your gate checklist:** use it like a researcher for 10 minutes and note anything confusing. Take screenshots now for your README later.

---

## Stage 4: Natural-language assistant, RAG and benchmark

```text
STAGE 4 - NL assistant, RAG and golden benchmark (PRD §9.2, §10, §30.1-§30.3)

Goal: the chat assistant produces validated query plans grounded by metadata
retrieval, and we can measure how accurate it is.

Scope
1. semantic_document table and an embedding pipeline. Pin the embedding model
   and record its version. Seed corpus:
   - parameter definitions, units and QC meanings
   - region aliases
   - at least 30 curated natural-language-to-plan examples
2. LLM provider adapter (§5.11):
   - Gemini as the default
   - structured output
   - timeouts, retries and a circuit breaker
   - token and cost logging
   - a daily spend cap from config
3. The chat flow in §9.2:
   classify -> retrieve -> plan -> validate -> execute -> sanitise -> narrate
   - Ask for clarification when an essential constraint is missing.
   - Stream answers over SSE.
   - Show a "How FloatChat interpreted your request" panel.
4. The prompt-injection controls in §10.3 and the hallucination controls in
   §10.4.
5. Golden benchmark in eval/golden/ (§30.2):
   - At least 150 items covering the §20.4 categories.
   - Split into about 50 development items and about 100 held-out test items.
   - Draft the gold plans yourself and mark every item "needs human review".
     I will review them before we report numbers.
6. Harness `make eval-nl` (§30.3):
   - metrics: plan exact match, field-level accuracy, result accuracy,
     clarification appropriateness, latency p50/p95, tokens per query
   - ablations: schema-only vs RAG vs RAG plus examples
   - two LLMs if I provide a second key
   - output: reports/eval_nl_<date>.md with commit hash, model and prompt
     versions, and seeds
7. If the LLM is unavailable, the dashboard and direct queries must keep
   working (§22). Add a test for this.

Acceptance criteria
- `make eval-nl` runs from a clean checkout and writes the report.
- Prompt and retrieval tuning used only the development split.
- Chat works in the UI.

Stop at the gate. In the gate report, list the 10 most common failure types
with examples.
```

**Your gate checklist:** actually review the gold plans. This is the research part, and you must be able to explain how the benchmark was built. Re-run `make eval-nl` after your corrections. The test-set plan accuracy is the real number for your resume (it replaces the mock "87% on 150 questions").

---

## Stage 5: Historical jobs and exports

```text
STAGE 5 - Historical jobs and exports (PRD §6.7, §8.4, §9.3, §21.2, §22)

Goal: multi-year requests run as durable, resumable background jobs and
produce research-ready downloads.

Scope
1. analysis_job and analysis_job_chunk tables. Separate Celery queues:
   ingestion, interactive-analysis, bulk-analysis, export, forecast (§21.2).
2. Endpoints:
   - POST /v1/exports
   - GET /v1/jobs and GET /v1/jobs/{id}
   - GET /v1/jobs/{id}/events (SSE)
   - POST /v1/jobs/{id}/cancel
   - Idempotency keys on job creation.
   - Identical active requests attach to the existing job (§8.4).
3. Chunked, resumable historical retrieval that reuses the Stage 1 pipeline.
   Completed chunks are never fetched again. Results are labelled partial or
   failed with a list of missing chunks (§9.3).
4. CSV and Parquet exports (NetCDF is deferred, §29.10), each with:
   - a manifest and provenance sidecar
   - a checksum and row/profile counts
   - the Argo citation
   - short-lived signed download URLs and expiry lifecycle rules
5. Jobs UI: list, detail with progress per chunk, cancel, download.
6. Failure tests from §22:
   - kill a worker mid-chunk; the job resumes with no duplicates
   - upstream down; retry, then partial completion
   - object written but catalogue commit failed; the object stays
     unqueryable and is cleaned up
7. reports/historical_jobs_<date>.md: a 10-year request for one region. Record
   chunks, duration, retries, and the cache reuse ratio when the same request
   runs a second time.

Acceptance criteria
- The 10-year request completes and survives a worker restart.
- The second identical run reuses cached partitions.

Stop at the gate.
```

**Your gate checklist:** start a long job, stop the worker container, start it again and watch the job resume. Download an export and open the manifest.

---

## Stage 6: Forecasting

```text
STAGE 6 - Forecasting (PRD §12, §30.4)

Goal: transparent, backtested statistical forecasts with honest refusals.

Scope
1. Tables forecast_definition, forecast_model and forecast_run (§6.9).
2. Series builder:
   - profile-balanced aggregation (§12.1)
   - an explicit missing-data policy
   - the eligibility and refusal rules in §12.3
3. Models and evaluation:
   - seasonal-naive baseline
   - ARIMA/SARIMA candidates with bounded parameter search (statsmodels)
   - rolling-origin backtests with at least 12 folds and 1-3 month horizons
   - MAE, RMSE, MASE, and 80%/95% interval coverage
   - residual diagnostics
   - model artefacts versioned in object storage
4. POST /v1/forecasts and a forecast workspace UI showing:
   - history, forecast and intervals
   - metrics against the baseline
   - limitations, and the §12.4 interpretation boundary text
5. `make eval-forecast` over at least 6 series (3 regions x temperature and
   salinity) -> reports/eval_forecast_<date>.md. Include series where SARIMA
   does not beat the baseline and series the system refuses. Use fixed seeds
   and data snapshot IDs.

Acceptance criteria
- The forecast report is reproducible from a clean checkout.
- The UI never shows a forecast without its backtest metrics.

Stop at the gate.
```

**Your gate checklist:** read the forecast report and make sure you can explain MASE and rolling-origin backtesting in your own words. The improvement over the baseline replaces the mock "21% on MASE", reported for the specific series it applies to.

---

## Stage 7: Auth, quotas, security and observability

```text
STAGE 7 - Auth, quotas, security, observability (PRD §15-§18)

Goal: safe to expose publicly, and debuggable.

Scope
1. Authentication:
   - OIDC Authorization Code with PKCE through the managed provider I set up
   - FastAPI validates signature, issuer, audience, expiry and claims
   - v1 roles: researcher and administrator
2. Quotas and rate limits (subset of §15.3):
   - requests per minute
   - concurrent jobs
   - maximum date range and area
   - LLM tokens per day
   - return 429 with Retry-After
3. Security, following §16 and §20.6:
   - tests for SQL injection, prompt injection, object-key traversal, broken
     object-level authorisation and oversized requests
   - non-root containers
   - dependency vulnerability scanning in CI
   - an SBOM
4. Observability:
   - OpenTelemetry traces across API -> queue -> worker -> storage
   - metrics from §18.1 and §18.2 (subset)
   - alerts for: no daily ingestion, queue age above threshold, job failure
     spike, LLM structured-output failure spike
5. Admin screens: usage and ingestion runs.

Acceptance criteria
- Unauthenticated calls are rejected.
- A chat request is visible as one trace end to end.
- The security test suite is green.

Stop at the gate.
```

**Your gate checklist:** log in, then try an API call without a token and confirm it's rejected. Find one trace in the telemetry UI.

---

## Stage 8: Deployment, release and write-up

```text
STAGE 8 - Deployment, release and write-up (PRD §19, §19.5, §26, §30.5)

Goal: a public, maintained deployment, plus documentation that a reviewer can
verify.

Scope
1. Infrastructure:
   - infra/ production Compose files
   - Caddy with automatic TLS
   - a VM bootstrap script for Ubuntu: non-root deploy user, SSH key-only,
     firewall with only 80/443 open, automatic security updates
2. Environments (§19.5): staging and production with separate databases,
   buckets, secrets and subdomains.
3. CI/CD:
   - Merges to main build images and push to GHCR, deploy to staging, then
     run smoke and end-to-end tests.
   - Version tags promote the same images to production behind health checks.
   - A one-command rollback.
4. Frontend on Cloudflare Pages. R2 buckets with lifecycle rules.
5. Backups: nightly pg_dump to R2 with 14-day retention, and an automated
   weekly restore test.
6. Runbooks in docs/ (§18.5 subset): upstream outage, schema change, stuck
   queue, database restore, key rotation, release rollback.
7. Public README:
   - what FloatChat is and why it exists
   - architecture diagram, screenshots and a short GIF
   - how to run it locally
   - a results table that links to the reports/ files
   - limitations
   - the Argo and Argovis citations (§3.2)
8. Technical report in docs/report/ (4-6 pages, §30.5): problem, system,
   evaluation method, results, limitations, future work.
9. The 10-minute demo script from §26, adapted to what was actually built.

Acceptance criteria
- A public HTTPS URL is live.
- The staging-to-production pipeline is proven with one rollback drill.
- The restore drill passed.
- Every number in the README matches a file in reports/.

Stop at the gate with the final report.
```

**Your gate checklist:** open the public URL on your phone. Run the demo script end to end once. Read the technical report, since an admissions reader may.

---

## Tips for running a long agent build

- **One stage at a time.** Agents drift on long jobs; the gates keep each run small enough to check.
- **Don't let it skip tests** to look "done". If CI isn't green, the stage isn't done.
- **Ask "show me"** at every gate: the compiled SQL, a trace, a report file. You need to understand everything you'll later claim.
- **Keep the PRD as the source of truth.** If the agent and the PRD disagree, settle it with an ADR, not silently.
- **Expect manual work** at Stages 4 (reviewing gold plans), 7 (identity provider setup) and 8 (VM, DNS, Cloudflare).
- **Update your resume only from `reports/`** once Stages 4 and 6 are done.
