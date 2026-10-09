# Stage 1 isolated acceptance preparation

**Superseded status (2026-10-09):** the live and captured-replay acceptance passed on session
`302412131a7c99fb`; see [the Stage 1 gate](stage1-gate.md). The text below is historical. Current
values: per-run budget 43,200 s (ADR-0043), migration head `0015_gdac_wiring`.

Current coverage review: **NO-GO for another live attempt or certification**.
All 44 HTTP 404s are inventory_before gaps, four source-warning chunks contain
degenerate_levels, and four canonical-limit chunks encountered an exhausted
run-wide allowance that splitting cannot restore. See the
[fresh coverage investigation](../reports/stage1-coverage-failure-review.md).
The original deadline/data and withdrawn session seal are preserved. No replacement
command, new session, budget adjustment or warning/empty-response waiver is approved.

**Execution status, 2026-10-07:** the owner attempted session
`6f3e7301f9789059`, then interrupted it after approximately 80 minutes. Persisted
evidence records 120 complete, 44 failed and 8 quarantined leaves out of 1,260;
819 profiles/572,347 levels/67 active partitions were committed. Coverage is
incomplete and no success is certified. See
[interruption evidence](../reports/stage1-acceptance-interruption-evidence.json)
and [provisional persisted report](../reports/stage1-acceptance-live-interrupted.json).
The remaining isolated containers were stopped without deleting data, inspecting
credentials/private originals or restarting a live worker. The run remains open
under its original persisted budget; CLI/process interruption does not imply an
operator cancellation or grant a new deadline.

The command below is now **historical and withdrawn pending review**: its sealed
source predates the progress/cleanup correction. Do not silently reseal the old
session or retry live ingestion. HTTP 404 outcomes remain failed coverage; data
warnings and canonical-output limits remain quarantined. They require separate
review, without converting absence or quarantine to success. Actual-head CI/full
acceptance/Stage 2 remain blocked.

The corrected wrapper prints persisted leaf-state counters at approximately
30-second intervals (plus a bounded read-only status query), checks live-acquire
process loss (stage1-v4, ADR-0047), and retains bounded client output without
forwarding exception text. First Ctrl+C stops the client process; cleanup ignores additional Ctrl+C
presses while stopping project-labelled service and one-off containers. It
records `last-cleanup.json`, preserves science/objects and exits 130 with a fixed
diagnostic. It does not automatically cancel, reset or extend the persisted run.
Only explicit cancellation through the existing CLI is operator cancellation.

Astra authorized preparation only on 2026-10-07. Live execution requires separate
owner opt-in. Stage 2 remains blocked pending full acceptance and actual-head CI.
This scaffolding does not change the Stage 1 scientific/source contract or F01-2.

Run preparation in the fresh WSL checkout with the cached dependencies and images:

```bash
cd /home/floatchat/FloatChat-stage1
/opt/floatchat-tools/uv/bin/uv run --all-packages --frozen --offline python scripts/stage1_acceptance.py prepare
```

The persisted `reports/stage1-acceptance-preparation.json` records the session and
reviewable resource names. Each session creates a separate Compose project,
PostgreSQL server/database and restricted login, private MinIO server/bucket and
bucket-scoped IAM identity, the PostgreSQL work queue inside that database (stage1-v4,
ADR-0047: no Redis server, database or broker keys), internal network and two named
volumes. There are no host port bindings, external/shared volumes, development
environment files, scheduler process, cloud resources or upstream calls. All images
are pinned to cached immutable image IDs; pull/build/install operations are
disabled. The acquire container has a 1 GiB cgroup limit; the process container
runs a pool of single-use workers bounded to 1 GiB each by `RLIMIT_DATA` inside a
2 GiB cgroup on this host (stage1-v4, ADR-0047).

Preparation migrates the empty disposable database through the current migration
head (0014 in stage1-v4), persists its acceptance-only environment marker, verifies
a benign bucket probe by read-back, checks that the bucket identity cannot list an
existing empty private control bucket belonging to this disposable project, and
runs a queue proof (stage1-v4: the ticket table is empty and a claim of each ticket
kind returns nothing). It checks that disabled live admission is refused and
leaves zero ingestion runs, profiles and measurement levels. It then stops all
services. Volumes and the benign isolation probe remain for review; nothing is
deleted. The evidence records actual project labels, mount identities, internal
network and absence of port bindings. Independent development volumes are never
mounted or read. An upstream bridge is absent throughout preparation.

Local disposable service credentials are generated inside ignored mode-0700
`.cache/stage1-acceptance/<session>` and stored in a mode-0600 environment file.
They are not printed, copied into reports or staged. The owner live command reads
`ARGOVIS_API_KEY` only after opt-in and transfers it through stdin to the live
acquire container (stage1-v4: `live-acquire`; the process container never receives
it). It never puts that key in Compose environment/configuration, argv, files
or reports. The agent never runs this branch or accesses the key. Future private
originals use a separate owner-only acceptance directory outside Git, separate
from the prior private captures; the agent must not inspect those originals.

After separate authorization, the owner runs this command from the private WSL
terminal, substituting only the public session ID from the preparation report:

```bash
cd /home/floatchat/FloatChat-stage1
/opt/floatchat-tools/uv/bin/uv run --all-packages --frozen --offline python scripts/stage1_acceptance.py execute --session <session> --live-opt-in
```

Execution refuses a changed source digest. It restarts only the isolated services,
uses the approved official Argovis request owner and existing contract limits,
and ingests the full Indian Ocean for `[2025-01-01T00:00:00Z,
2025-04-01T00:00:00Z)` with fixed reference `2025-04-01T00:00:00Z`.
Live ingestion is enabled only for the explicitly opted-in client and the
`live-acquire` container; no scheduler is launched. Existing persisted HTTP
attempt/retry/payload/profile/level/chunk ceilings apply; concurrency is one
acquire process with up to 4 upstream requests in flight (ADR-0048) plus a pool of
2 single-use process workers on this host (ADR-0047), and each run has a
21,600-second budget. The wrapper permits at most 21,900 seconds per ingestion
command to collect deadline finalization, with bounded local setup/report calls.
No destructive retention or orphan deletion is executed.

The second phase stops the live acquire container and uses the internal-network
acquire and process containers with live disabled and no credential to execute actual `--replay-run` against the
completed predecessor. Stable request IDs prevent retry from inventing a new run.
Expected evidence is `reports/stage1-acceptance-live.json` and
`reports/stage1-acceptance-replay.json`, both generated from persisted database
evidence: closed complete runs, all leaves complete, zero coverage gaps, matching
full stored/snapshot and fixed-time eligible populations, balanced level accounting,
and replay scientific/active-partition no-change. Audit/attempt counts may rise
and remain separately reported. Any quarantine, failed/partial run, missing
coverage or scientific/generation change fails this wrapper. Incomplete reports
remain available; failure does not become a success certificate. The services are
stopped and objects/database retained on exit.

`reports/stage1-acceptance-owner-result.json` indicates only live-plus-replay run
evidence ready for review. It cannot certify all 86 contract cases, actual-head CI,
whole-pipeline memory, current selector byte availability or Stage 2 readiness.
Those require the full gate review. The reviewed 372-test implementation evidence
remains historical relative to these preparation additions; new preparation
checks are recorded separately and do not relabel that suite as freshly rerun.
