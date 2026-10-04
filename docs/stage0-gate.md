# Stage 0 - final verification in progress

The owner authorized completion, including tested history publication and a checked Stage 0 PR merge. Stage 1 remains blocked until the final gate passes.

## Verified evidence

| Check | Result and evidence |
|---|---|
| Preservation | 63,237 files / 1,524,631,548 bytes verified in restricted per-user storage outside OneDrive; `reports/stage0-preservation.json` |
| Original history findings | Eight fully redacted occurrences; `reports/stage0-history-findings.json` |
| Isolated rewrite | git-filter-repo 2.47.0; 33 mappings, 31 retained commits with original identities/timestamps, two emptied commits removed; `reports/stage0-rewrite.json` |
| Candidate validation | History scans of candidate and separate clone passed; all seven ref-tip directory scans passed; retained content compared to original |
| Published history | Seven affected refs atomically updated with explicit leases, remote IDs matched candidate, no unrelated ref deleted |
| Fresh remote verification | All advertised branches/tags fetched, zero current/history findings, removed dataset blobs unreachable; `reports/stage0-fresh-published.json` |
| Repository protection | Force pushes disabled, existing two-review rule retained, six strict checks required; before/after publication reports |
| Python | 22 tests passed; `reports/stage0-python.xml`; actual hook rejection verified from a clean script checkout |
| Python static checks | Ruff lint/format and mypy passed |
| Frontend | ESLint, Prettier, TypeScript, three unit tests and production build passed |
| Windows Docker acceptance | Empty startup 26.062 s, repeat 14.672 s; outages/recovery, migrations, worker, private storage, persistence and browser passed; prior local reports |
| Fixture | Deterministic first 128 preserved rows, 5,617 bytes, schema/checksum/provenance verified |

## Remaining executed checks

Ubuntu 24.04 Make-based setup/bootstrap and acceptance, the Stage 0 foundation PR and required CI, final protected merge, and fresh merged-main CI-equivalent verification are in progress. This report does not yet claim completion. Raw scanner data, replacement expressions, commit mappings and service diagnostics stay outside Git and CI artifacts.

No Stage 1 domain functionality or cloud resource was introduced. The preserved dirty Windows checkout still contains old Git objects and must never be pushed. See `docs/history-remediation.md` for old-clone/fork recovery and ref-scope limitations.
