# Decisions

## ADR-0001 — Stage 0 amendments override stale build prompts

The approved execution contract and owner amendments govern Stage 0. `FLOATCHAT_PRD_v2.md` governs target architecture and layout; PRD §0 overrides its later sections. The supplied build prompts are historical planning inputs, with obsolete secret-prefix and completion language. `Prototype/FLOATCHAT_PRODUCTION_ARCHITECTURE.md` is archival reference, not an alternate Stage 0 specification. No supplied planning document is overwritten.

## ADR-0002 — Local services with zero required cloud infrastructure cost

Use WSL2 Ubuntu 24.04 and Docker Desktop with local PostgreSQL/PostGIS/pgvector, Redis, MinIO, FastAPI, Celery, and React/Vite. No Azure, Supabase, OpenAI API, cloud database, cloud object store, or paid resource is created. Portable environment configuration preserves a later migration path; demonstrations and deployment belong in Stage 8. Docker installation is owner-managed. Docker acceptance passed from Windows; the Ubuntu 24.04 development checkout remains unverified.

## ADR-0003 — Preserve originals; sanitize before archiving

The existing dirty tree was backed up and verified before source edits. Current `Prototype/python.py` matched HEAD; the working notebook differed and was preserved as the current input. Sanitized copies are in `legacy/prototype`. Notebook outputs/metadata/attachments are removed rather than carried into an archive. The original folder and large Parquet remain preserved and excluded from Git/runtime packaging pending final owner-controlled disposition. No blanket directory removal is performed.

## ADR-0004 — Separate preparation from completion

The original inventory was expanded into a tested candidate and a separate validation clone. The owner subsequently explicitly authorized the tested isolated rewrite, affected-ref publication, Stage 0 PR and checked merge. Seven branches were published atomically with exact leases; the dirty checkout remained intact. Known leaks are not allowlisted. CI must be rerun on the sanitized baseline after approved publication. Stage 1 remains blocked.

## ADR-0005 — MinIO community source build

The [official MinIO project](https://github.com/minio/minio) is archived and distributed as source only. Registry requests for historical images were unavailable. Build pinned upstream server/client releases from checksum-verified archives, with the preferred Go 1.24.8 compiler and upstream Go module sums. Preserve upstream licenses in the image. This adds a build prerequisite, not a cloud account or service. Image build and private-bucket runtime validation passed using Docker's Linux engine from Windows.

## ADR-0006 — Safe migration and configuration lifecycle

Administrative DB and MinIO identities are limited to initialization services. API/worker identities are distinct and buckets are private. Readiness checks run concurrently with a four-second overall budget; diagnostics are sanitized. Migration upgrade is idempotent; downgrade refuses extension removal. Configuration is generated outside the repository in a restricted non-synced directory and never overwritten. Ordinary lifecycle commands preserve volumes.

## ADR-0007 — Bounded fixture reproduction only

Commit a deterministic sample from preserved scientific data with byte/schema/checksum/provenance validation. Refetch is an optional owner-specified snapshot download, not an Argovis adapter. A durable snapshot URL remains unresolved; production source discovery, adapters, normalization and scheduling belong in Stage 1. No fabricated retrieval dates or production schema are introduced.

## ADR-0008 — Compatible PostgreSQL extension image

The original PostGIS image used Debian Bullseye repositories that failed during the extension build. Use digest-pinned official PostgreSQL 17.6 on Bookworm, install PostGIS from the configured package repository, and compile checksum-pinned pgvector 0.8.2 in a separate build stage. Runtime SQL verified PostgreSQL 17.6, PostGIS 3.6.4 and vector 0.8.2, including geometry/vector operations. The compiler headers resolved to PostgreSQL 17.11; runtime compatibility passed. Actual versions and built image IDs are recorded in `reports/stage0-runtime.json`.

## ADR-0009 — Windows driver and isolated acceptance diagnostics

Detect Docker Desktop's per-user installation and expose its credential helpers only in the driver's process PATH. Preserve restricted integration configuration and logs outside Git alongside retained volumes; prevent ambient application configuration from redirecting integration tests to cloud services. Run uv commands with `--all-packages --frozen` so workspace package dependencies remain installed. Windows-driven Docker acceptance passed; verification of the Ubuntu 24.04 development checkout and Make commands remains pending.

## ADR-0010 — Authorized publication and repository controls

Publish only the seven inventoried affected branch refs after rechecking remote IDs; use one atomic push with an explicit force-with-lease for each ref. Temporarily permit force updates only for that publication window, restore the force-push prohibition immediately, and add all six required CI checks while preserving the existing two-review rule. Preserve old/new commit mapping and raw diagnostics only outside Git. New foundation commits use the account?s GitHub noreply identity and current timestamps. Old clones and forks require the documented recovery procedure.

## ADR-0011 — Complete Windows/Ubuntu verification and formatting

Install Ubuntu 24.04 in WSL2 and verify the documented Make commands from a separate Linux-filesystem checkout using Docker Desktop integration. Pin Prettier 3.8.1 and include frontend formatting in Make lint and the web CI job. Match driver health URLs to configured loopback API/web ports, including Compose environment overrides. Optional live scientific refetch is not required for Stage 0; the deterministic fixture and mocked timeout/error/atomic-download tests supply the required contract evidence.

## ADR-0012 — Scan the committing repository's index

The scanner originally defaulted to the script's repository. A hook invoked in a separate repository therefore scanned the wrong index; the original dirty index concealed that defect by containing an unrelated known leak. Default the scan source to the caller's working directory, retain explicit `--source` for isolated scans, and verify rejection with the script's checkout clean. The disposable hook test exercises an actual Git commit and must fail because of that disposable repository's synthetic finding.

## ADR-0013 — Portable test invocation and preserved document formatting

Invoke tests through `python -m pytest` in Make and CI so the workspace root is on Python's import path. The standalone pytest launcher on Linux otherwise failed to import the root scripts package. Preserve the original PRD's Markdown hard breaks and archived prototype whitespace; their attributes exempt only those whitespace checks, never secret scanning.
