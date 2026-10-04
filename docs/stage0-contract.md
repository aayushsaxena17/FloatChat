# Approved Stage 0 execution contract

Authority: corrected contract approved in this session, including the owner's local-only and zero-required-cloud-cost amendments.

1. Preserve tracked/untracked work before changes; backups containing contaminated content remain access-restricted outside Git and cloud-synced folders.
2. Reconcile authoritative PRD/prompt/prototype inputs. Do not blindly restore deleted files or remove untracked work.
3. Scan current files and history separately. Record scanner version, rules, exclusions, refs and limitations. Report only opaque finding IDs, type, commit, path, location and fully redacted values.
4. Sanitize notebook source, outputs, attachments and metadata before archiving. Exclude legacy from runtime packaging, not security scanning.
5. Implement only the local foundation. No paid/cloud resources, real LLM/Argovis calls, cloud DB/storage, or production credentials are required.
6. Use Python 3.12/uv and Node/pnpm workspaces; lock dependencies and image/source pins. Local services are PostgreSQL/PostGIS/pgvector, Redis, MinIO, FastAPI, Celery and React/Vite.
7. Bootstrap is bounded, ordered and idempotent; configuration and volumes are preserved. Expose loopback ports only and separate admin/application credentials.
8. Ready is 200 only when all required dependencies are usable, otherwise sanitized 503 within five seconds. Live remains 200 during dependency outages.
9. Validate empty startup (300 seconds after builds), repeated startup (120 seconds), migration repeat/refused downgrade, private application bucket access, actual broker task, browser/API connection, persistence, scanner/hook negative controls, and deterministic bounded fixture/refetch behavior.
10. Prepare history remediation only in an isolated clone. Inventory affected refs/paths and expected remote IDs. The owner explicitly authorized the scope, tested rewrite, publication and checked Stage 0 PR merge in this session. Keep raw mappings/reports outside Git. Produce an old-to-new commit map and sanitized evidence.
11. Do not publish unvalidated history, force-update unrelated refs, delete unrelated remote refs, rewrite the dirty checkout, discard local work, remove normal volumes, or drop extensions with CASCADE. Authorized publication uses explicit per-ref leases and remote-state verification.
12. Owner authorization covers revocation confirmation, tested scope/publication, foundation PR and checked merge, and repository protection. Remote changes require a rebuilt and revalidated candidate rather than blind overwrites. Fork/provider cleanup and safe old-clone recovery remain documented external responsibilities.
13. Preparation alone is partial. Complete requires approved publication, fresh-clone current/history scan success, green executed required CI and verified merge protection. No Stage 1 before completion.

Deferred: Stage 1 ingestion; Stages 2–3 domain queries/clients/dashboards/maps/charts; Stages 4–6 LLM/RAG/evaluations/jobs/exports/forecasting; Stage 7 identity/quotas/observability; Stage 8 cloud deployment/TLS/release/operational backup and recovery.
