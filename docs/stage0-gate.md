# Stage 0 - corrective verification and review gate

## Astra corrective verification

The original results below are historical measurements, not approval of the subsequently
discovered defects. The correction starts on a clean branch from sanitized main
7e642a104d469e57c2857e8ad698bb8417553e18. The original Windows checkout and dirty Ubuntu
verification checkout are not used as source. Dirty verification artifacts were independently
preserved outside Git and inspected for local paths; they were not copied into this PR.

| Finding | Correction and executed regression |
|---|---|
| Readiness deadline | Concurrent probes use an independent deadline; database sockets are disposed synchronously, and cancellation cleanup is reaped outside the HTTP path. A delayed-cancellation regression enforces 50 ms budget + 50 ms scheduling tolerance. Real PostgreSQL pg_sleep also proves the response bound and disposal of client/server query resources. |
| PostGIS metadata | Revoke previous blanket/default public writes. Existing and future application tables use the dedicated app schema and migration owner; extension members are excluded and read-only. Real CRUD/identity-sequence access, all six prohibited metadata privileges, actual denied INSERT/UPDATE/DELETE and repeated-bootstrap repair pass. |
| Managed hook | The exact repository YAML runs the frozen uv workspace. A clean non-activated shell whose PATH has no python successfully commits clean source and rejects a synthetic staged finding with fully redacted output. |
| Refetch deadline | A spawned worker receives remaining connect/read budgets; an independent supervisor bounds DNS, TLS/header trickles, body trickles, EOF and cleanup. Termination/reaping has a reserve inside the unchanged 30-second budget. Real local HTTPS slow-body, delayed-EOF and slow-header tests enforce 500 ms budget + 100 ms scheduling tolerance; existing output and temporary-file/process cleanup are verified. |

[Committed corrective evidence](../reports/stage0-review-verification.json) records 28 Python tests,
three frontend tests, one real browser test, static checks, image builds, empty/repeat startup,
metadata permissions, readiness, worker, storage and persistence. The initial regressions failed
against the baseline before fixes. Test tolerances do not increase production deadlines.

Required checks remain python, web, docker, integration, secrets-current and secrets-history.
Their actual PR results are the authoritative CI gate. Merge also requires an Astra review
reporting no remaining P1 or P2 findings; that review is not claimed here.
No merge/check bypass, cloud resource, Stage 1 implementation or second history rewrite is part
of this PR. All evidence linked here exists in Git; raw operational logs and local final
attestations remain private and are not dependencies of a fresh clone.

## Original foundation verification

The gate passed on verified merged main `dc3d409c5fc9605c48ec0e7f8ca230d6c5e719b2`, containing tested source `608e4356b312f4422ad40996e1604fb1ef28a640`. [Foundation PR #1](https://github.com/aayushsaxena17/FloatChat/pull/1) was merged after all required checks passed. This documentation-only follow-up records measurements made after that merge. No Stage 1 implementation or cloud infrastructure was introduced.

## Preservation and publication

| Requirement | Executed evidence |
|---|---|
| Preserve active work before remediation | 63,237 files / 1,524,631,548 bytes, Git database, staged/working differences and ignored configuration verified; durable owner/SYSTEM-only copy outside Git/OneDrive. [Preservation](../reports/stage0-preservation.json) |
| Revocation | Owner confirmation is recorded in [PROGRESS.md](../PROGRESS.md); no credential values, fragments or derived hashes are recorded. |
| Findings and isolated candidate | Eight fully redacted occurrences; filter-repo 2.47.0; 33 commit mappings held privately, 31 retained identities/timestamps verified, 102 tree entries compared. [Findings](../reports/stage0-history-findings.json), [rewrite](../reports/stage0-rewrite.json) |
| Independent candidate validation | Separate clone full-history scan passed; all seven branch-tip directory scans passed. Two empty commits pruned; 29 old signatures invalidated by changed IDs. [Rewrite](../reports/stage0-rewrite.json) |
| Scoped publication | Seven affected heads atomically updated with explicit leases after exact remote-ID checks; no unrelated branch/tag deleted. Main subsequently advanced by the verified foundation merge. [Rewrite/ref inventory](../reports/stage0-rewrite.json) |
| Fresh published-history verification | All advertised heads/tags fetched, separate current/history scans passed, candidate ref IDs matched, both January dataset blobs unreachable. [Fresh publication](../reports/stage0-fresh-published.json) |
| Fresh merged-main verification | Completely fresh HTTPS Ubuntu clone: separate scans passed with zero findings, full CI-equivalent suite passed. Gitleaks 8.30.1, upstream rules and documented exclusions, decode depth 3, full redaction. [Fresh main](../reports/stage0-fresh-main.json) |
| Required CI | Six jobs actually completed successfully on the PR head and merged main. [PR run 37242811531](https://github.com/aayushsaxena17/FloatChat/actions/runs/37242811531), [main run 37243966049](https://github.com/aayushsaxena17/FloatChat/actions/runs/37243966049), [PR evidence](../reports/stage0-ci-source.json), [main evidence](../reports/stage0-ci-main.json) |
| Protection | Six strict checks bound to GitHub Actions app 15368; two reviews retained, administrators enforced, force pushes and deletion prohibited. [Final protection](../reports/stage0-protection-final.json), [before](../reports/stage0-protection-before.json) |

## Acceptance-test matrix

| Area | Executed test and result | Evidence |
|---|---|---|
| Supported platform | Non-root Ubuntu 24.04.5 on WSL2, Docker Desktop integration, exact Make entry points passed | [Ubuntu](../reports/stage0-ubuntu.json) |
| Empty bootstrap | Fresh distinct volume project ready in 34.366 s, below 300 s after builds | [Fresh main integration](../reports/stage0-fresh-main.json) |
| Repeat bootstrap | Ready in 28.430 s, below 120 s; DB/object data persisted; ordinary stop retained volumes | [Fresh main](../reports/stage0-fresh-main.json) |
| Normal Make startup | `make dev` and repeat passed; repeat including cached build 11.104 s; configuration unchanged | [Ubuntu](../reports/stage0-ubuntu.json) |
| Health outages | DB, Redis and MinIO independently stopped: sanitized readiness 503 within five seconds, liveness 200, recovery passed | [Fresh main](../reports/stage0-fresh-main.json), [test driver](../scripts/integration.py) |
| Database/migrations | Empty upgrade, repeat upgrade, both extensions and geometry/vector operations passed; downgrade safely refused on disposable DB | [Runtime SQL](../reports/stage0-runtime-ubuntu.json), [integration probes](../scripts/integration_probe.py) |
| Object storage | Private bucket initialized before readiness; application CRUD passed, anonymous denied, invalid credentials/missing bucket failed readiness | [Fresh main](../reports/stage0-fresh-main.json), [probes](../scripts/integration_probe.py) |
| Worker | Harmless Celery task submitted/completed through actual Redis broker | [Fresh main](../reports/stage0-fresh-main.json), [probes](../scripts/integration_probe.py) |
| Browser/API | Actual Playwright Chromium scaffold rendering and browser-to-API request passed | [Fresh main](../reports/stage0-fresh-main.json), [browser tests](../apps/web/e2e) |
| Local isolation | Six healthy services; only API/web ports published on 127.0.0.1; admin/app identities separated | [Runtime](../reports/stage0-runtime-ubuntu.json), [Compose tests](../tests/test_compose.py) |
| Python | 22 tests, Ruff lint/format, mypy passed in fresh Ubuntu clone and CI | [JUnit](../reports/stage0-python-fresh-main.xml), [fresh main](../reports/stage0-fresh-main.json) |
| Frontend | Three unit tests, ESLint, Prettier, TypeScript and production build passed | [Fresh main](../reports/stage0-fresh-main.json), CI web job |
| Images | All Compose image builds and explicit web production build target passed | [Fresh main](../reports/stage0-fresh-main.json), CI docker/integration jobs |
| Secret controls | Disposable synthetic finding rejected by directory/history/index scanner and actual commit hook; reports revealed no value; these negative tests executed in CI | [Security tests](../tests/test_security.py), JUnit and CI Python job |
| Fixture | First 128 preserved physical rows; 5,617 bytes under 1,000,000-byte cap; schema/checksum/provenance validated | [Manifest](../tests/fixtures/profiles.json), [fixture test](../tests/test_fixture.py) |
| Optional refetch | Mock success, failures, timeout, byte/checksum limits and interrupted download preserve existing data | [Tests](../tests/test_refetch.py), JUnit |
| Evaluation | `make eval` produces the expected Stage 0 stub | [Ubuntu](../reports/stage0-ubuntu.json) |
| Real upstream access | Not applicable: optional snapshot URL is not a Stage 0 dependency; no production ingestion, LLM or Argovis requests | [Contract](stage0-contract.md), ADR-0007 |
| Cloud deployment | Not applicable: Stage 8; Stage 0 created no cloud infrastructure or paid resource | [Decisions](../DECISIONS.md), local Compose configuration |

All applicable checks passed. No failed check or known leaked credential was suppressed to reach this gate. Runtime versions: Python 3.12.12, uv 0.10.4, Node 24.15.0, pnpm 10.33.0; PostgreSQL 17.6, PostGIS 3.6.4 and pgvector 0.8.2 verified by SQL. Lockfiles, image digests and source checksums are committed; actual image IDs are recorded. Public CI uses standard GitHub Actions runners; no billable runner or cloud account was created.

## Limits and recovery

The original dirty Windows checkout retains contaminated Git objects and is preservation material, with its push URL disabled. Use a fresh Ubuntu clone for development. Raw reports, replacement expressions and full commit mapping remain restricted outside Git/CI artifacts. Neither scanners nor rewritten advertised refs prove removal from provider caches or four existing forks. Other monthly historical datasets were outside the approved January removal scope and remain. The archive is excluded from runtime packaging and remains secret-scanned.

[Old-clone recovery](history-remediation.md): stop old-clone pushes, preserve unpublished work privately, clone the sanitized origin anew, reapply only reviewed sanitized source as new commits, and scan current files/full history before pushing. Never merge contaminated ancestry or publish backup refs. Fork owners/provider support must handle external cached copies. No direct collaborator messages were sent; PR documentation carries the recovery procedure. Do not begin Stage 1 without a separate instruction.
