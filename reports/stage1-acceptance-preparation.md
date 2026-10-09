# Isolated Stage 1 acceptance prepared for owner review

**Historical preparation snapshot.** The owner subsequently attempted the run
and interrupted it. Coverage is incomplete; the old execution command below is
withdrawn pending review. See the [interrupted-run report](stage1-acceptance-interruption-review.md).
The original source seal is retained and does not match the corrected wrapper.

No live execution or ingestion run occurred. All prepared services are stopped; data is retained. No development volume is shared.

Session: `6f3e7301f9789059`. Source SHA-256: `12cbb73e8bb70f28190d29a2afb5aa521aebda510bc06807d8917dede78eba3c`.

| Resource | Isolated identity |
|---|---|
| Compose project | `floatchat-s1-acceptance-6f3e7301f9789059` |
| PostgreSQL database | `floatchat_s1_6f3e7301f9789059` |
| MinIO bucket | `floatchat-s1-acceptance-6f3e7301f9789059` |
| Redis | dedicated server, database 13, prefix `floatchat-s1-acceptance-6f3e7301f9789059:` |
| Queue | `floatchat-s1-acceptance-6f3e7301f9789059.ingestion` |

Proof: migration 0007; restricted login/effective ingestion role; disposable acceptance marker; zero runs/profiles/levels; bucket SHA-256 read-back; actual denial on the existing empty control bucket; smoke-task acknowledgement; live-disabled admission refusal; internal-only network; no host ports; disjoint actual development volume IDs. Both Compose configurations validate without starting a live worker/network.

Fresh checks: 348 offline unit tests, including 16 preparation/owner-orchestration tests, zero failures/errors/skips; lint, format, types and current/history secret scans passed. The earlier 372-test implementation verification, fault and memory suites are historical evidence and were not relabelled as rerun this turn.

Review-only owner command; separate live authorization required:

```bash
cd /home/floatchat/FloatChat-stage1 && /opt/floatchat-tools/uv/bin/uv run --all-packages --frozen --offline python scripts/stage1_acceptance.py execute --session 6f3e7301f9789059 --live-opt-in
```

Expected persisted live/replay reports: closed complete runs, all leaf chunks complete, zero coverage gaps, balanced retained and eligible populations and level accounting; replay has unchanged science and active generation IDs. Audit/attempt increases are reported separately. Any incomplete run fails the wrapper and cannot produce its success marker.

No P1/P2 preparation blocker remains in these checks. Full acceptance certification and actual-head CI remain outstanding. F01-2 authentic direction/core-null limitations, component fault qualifications, writer-only memory proof and fresh selector byte availability remain explicit. Stage 2 remains blocked.

See [persisted proof](stage1-acceptance-preparation.json), [fresh checks](stage1-acceptance-preparation-checks.json), [policy](../docs/stage1-acceptance-preparation.md), [gate](../docs/stage1-gate.md).
