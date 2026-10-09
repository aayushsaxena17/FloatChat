# Preserved Stage 1 run terminalization — review only

**Not executed. Separate Astra/owner review is required before operating the
preserved database.** This procedure does not authorize another ingestion attempt,
restart a worker/scheduler/supervisor, extend a deadline, admit a run, publish data,
apply migration 0008 or delete objects/volumes. The old live command remains withdrawn.

Target: session `6f3e7301f9789059`, run
`fee47d4d-8e91-4cd4-ace2-a1c3d1129fdb`, Compose project
`floatchat-s1-acceptance-6f3e7301f9789059`, PostgreSQL database
`floatchat_s1_6f3e7301f9789059`. Use its existing deployed migration 0007 procedures.

Immutable work deadline: `2026-10-07T13:03:38.284791Z`.
Immutable final deadline: `2026-10-07T13:04:38.284791Z`.

## Preconditions and reason

After separate approval, verify every container with this exact project label is
stopped, including one-off clients and the owner live process. Record that preflight;
do not inspect owner process environment, logs, credentials or private originals.
Start **only the existing database**, then run a single live-disabled restricted
client with no Redis/MinIO worker, scheduler, network egress or credential argument.
Never run Compose up or the existing execution wrapper.

Read a serializable preflight snapshot and require the exact target database,
acceptance environment/project/bucket/queue markers and run ID. Verify original
deadlines/reference time and source seal against the saved evidence. Require current
counts/manifests to match the recorded 819 profiles, 572,347 levels, 67 active
partitions and the exact profile/generation hashes. Compare every complete chunk
ID/completion timestamp and catalogue record, rather than counts alone. Refuse any
unexpected difference for review. Capture chunk/attempt/intent/resource snapshots
and the already persisted baseline; missing provenance is not success.

The proposed command uses **deadline_expired only after database clock_timestamp()
reaches the immutable final deadline** (and therefore also the work cutoff). Before
that time it refuses without mutations.
Do not force clock values or choose execution_failed to bypass the guard. An earlier
operator_cancelled procedure needs its own explicit owner decision and must report
cancellation semantics; Ctrl+C in the old wrapper was process loss, not that decision.

## Atomic closing procedure

The one restricted repository operation is the existing
`app.finalize_run(run_id, 'deadline_expired')`. Do not invoke Controller.tick:
before its deadline path it can claim work and dispatch tasks. Do not call admit,
start_controller, claim_chunk or process_ticket.

The existing finalizer locks the run, establishes its closed flag and new control
epoch, fails every remaining nonterminal chunk under incremented fences, clears
leases, finishes interrupted attempts, charges outstanding canonical reservations
conservatively and abandons prepared publication intents while retaining references.
Already complete, failed and quarantined chunks remain unchanged. No active
catalogue or scientific state is merged, replaced, deactivated or deleted. A partial
run does not advance its scheduler watermark.

Run reduction and capture_final_evidence occur in that same transaction. Based on
the saved snapshot, expected leaf states are **120 complete, 1,132 failed and
8 quarantined**, with run **closed/partial** and deadline_expired. The 44 original
HTTP failures remain HTTP failures; the other 1,088 planned leaves become recorded
deadline failures. Original quarantine reasons stay intact. Do not promise these
exact counts if the preflight detects any difference: stop for review instead.

## Evidence and recovery

After commit, generate JSON and Markdown from the frozen database record, with
coverage derived only from its persisted metrics. Require
final_evidence_frozen=true, state=partial, closed=true,
coverage.proved_complete=false and explicit gaps. Availability, reconciliation,
timings, attempts, resource use and unknown source levels must derive from persisted
evidence. A balanced retained population does not make unfinished coverage successful.

Compare before/after exact scientific manifests and active generation IDs/hashes;
require equality. Verify all prior complete chunk IDs/completion times, failed 404
reasons and eight quarantines are unchanged. Verify every former planned chunk is
terminal with the closing reason and that prepared objects remain referenced by
abandoned intents. Preserve catalogue/raw/quarantine/object evidence. The saved
10,721,657,712 canonical bytes can only stay the same or increase for previously
outstanding reservations; never reset them. Saved evidence currently shows none.

If the client dies before commit, PostgreSQL rolls back the closing transaction;
retry only this terminalization operation after repeating open-state preflight.
If it dies after commit, **do not require the old open state or 1,088 planned rows**.
The closed-state preflight requires closed/partial/deadline_expired, one frozen row,
the original exact scientific/generation manifests and protected chunk IDs/reasons/
completion times. Each originally planned row must now be failed/deadline_expired
with fence incremented exactly once. The terminal state and unique run_final_evidence
record prove completion; validate that evidence and export it.
Repeated finalize_run returns the existing terminal state without charging again,
changing the deadline or freezing a different snapshot. Never recover by restarting
ingestion. If PostgreSQL is unavailable, report evidence persistence as outstanding.

Stop the restricted client and database after evidence capture, retaining all data.
Scan only the generated public reports for secrets before proposing Git changes.
The expected outcome is a **certified incomplete-run record**, not Stage 1 acceptance:
CLI/report aggregate exit is 3 (partial), never 0 or cancellation exit 130. Full
acceptance, actual-head CI and Stage 2 remain blocked.

## Concrete command — review only, not authorized to execute

After separate Astra/owner approval of this exact procedure:

```bash
cd /home/floatchat/FloatChat-stage1 && /opt/floatchat-tools/uv/bin/uv run --all-packages --frozen --offline python scripts/stage1_terminalize.py --session 6f3e7301f9789059 --review-approved
```

Omitting `--review-approved` returns 2 without reading the session or operating any
container. This command is **not another acceptance attempt**. It starts only the
existing database whose stopped container is discovered under the exact project
and service labels; no Compose up, other container start, migration or ingestion
operation exists in the script. A bounded readiness check precedes the restricted
`acceptance_ingestion` login. It neither reads an environment file nor loads a
credential. It hashes the public session manifest without displaying its contents.

One serializable transaction checks exact database/environment/reference/deadlines,
original counters, all 1,260 saved chunk identities and states, scientific manifest
and active IDs, migration 0007, and the pinned function bodies/signatures/security
definer/search path. Then the existing finalizer alone performs closure and final
freeze. No new procedure is installed. Temporary verification tables disappear
with the client; the restricted role receives no target DML/DDL privileges.

On success, safe stdout contains category `terminalized_incomplete`, state partial,
the public report path and exit 3. Both frozen JSON and a Markdown pointer are
written under reports; the JSON is scanned before writing. Exit 5 means refusal or
evidence/export/cleanup still pending, **not** successful acceptance. A commit can
already have succeeded before an export failure: repeat only this command after
review, using its closed-state validation. No raw exception, SQL error, response
body, header or environment value is printed.

The finally path stops only the database and retains its data. If a second interrupt
or Docker outage prevents cleanup, record cleanup as pending; stop only that same
database container after confirming its labels. Never use down, rm, volume removal,
worker/scheduler start or the withdrawn acceptance wrapper. This script does not
verify availability of the preserved MinIO objects or certify the underlying source.

Fresh disposable rehearsal: `reports/stage1-terminalization-0007-rehearsal.json`.
It installs only through 0007 in a new database, models exactly 120 complete, 44
failed, eight quarantined and 1,088 planned leaves, retains a small labelled science/
catalogue state fixture, and terminates actual client connections before and after
commit. It checks rollback, closed-state retry, idempotence, original protected
rows, one frozen record and unchanged budget/deadlines/science/generations. It is
not a copy of the original 819 profiles, 572,347 levels or object store.

Inspection limitation: the migration-0007 implementation and the saved deployed
revision attestation were reviewed offline. The preserved database was not opened;
its current function-body match remains a mandatory post-approval preflight check.
