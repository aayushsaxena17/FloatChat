# Stage progress

## Stage 0 - in progress; final verification pending

Owner confirmed revocation.

- [x] Inventory and verified restricted backup of original tracked/untracked work outside Git and OneDrive.
- [x] Current files and locally available Git history scanned separately with Gitleaks 8.30.1.
- [x] Fully redacted findings; raw reports restricted outside Git.
- [x] Sanitize current Python/notebook and create legacy copies before packaging.
- [x] Deterministic 128-row, 5,617-byte fixture and provenance manifest.
- [x] uv/Python and pnpm/React/Vite workspaces and lockfiles.
- [x] Local Compose scaffold, migration/storage bootstrap, health API and worker smoke task.
- [x] Unit tests, static checks, frontend build, and synthetic scanner/hook failure controls.
- [x] Separate isolated inventory clone; no rewrite performed and push URL disabled.
- [x] Explicit owner authorization of tested scope/publication, foundation PR and checked merge; old-clone recovery documented.
- [x] Tested isolated candidate and separate validation clone; 33-entry mapping retained outside Git.
- [x] Docker Desktop Linux-container startup, image builds, migrations, storage, worker, persistence, outages and browser integration verified from Windows.
- [ ] Ubuntu 24.04 WSL development checkout and exact Make entry points verified.
- [x] Preserve original folder outside runtime packaging; live scientific refetch is optional and excluded from normal startup/tests.
- [x] Atomic publication of seven affected branches using exact per-ref leases; force pushes disabled afterward.
- [x] Fresh published remote clone; current-file and full-history scans pass with full advertised head/tag coverage.
- [ ] CI executes and passes; merge protection verified within free usage.

Stage 1 must not begin. No cloud infrastructure, external credentials, or real upstream calls are part of Stage 0.

See `docs/stage0-gate.md` for measured validation and pending actions.
