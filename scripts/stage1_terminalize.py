"""Review-gated, deadline-only closing of one stopped migration-0007 session.

Never imports the controller, worker, live client, configuration or credentials.
Default renders the proposed operation; execution needs separate human approval.
Only the existing database container can start; cleanup only stops that container.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION = "6f3e7301f9789059"
PROJECT = "floatchat-s1-acceptance-" + SESSION
DATABASE = "floatchat_s1_" + SESSION
RUN = "fee47d4d-8e91-4cd4-ace2-a1c3d1129fdb"
MANIFEST_SHA256 = "181cf9c708e1df3ccee107d66f81dfc7d0ce5942b4083174abd883dc2c1fd183"


def definition_pins():
    """Bodies independently inspected through migration 0007, never 0008."""
    wanted = {
        "finalize_run",
        "capture_final_evidence",
        "scientific_snapshot",
        "reconciliation_snapshot",
        "report_metrics_snapshot",
    }
    pins = {}
    files = sorted((ROOT / "infra/migrations/versions").glob("*.sql"))
    for file in files:
        if file.name[:4] not in {"0002", "0003", "0004", "0005", "0006", "0007"}:
            continue
        for match in re.finditer(
            r"CREATE(?: OR REPLACE)? FUNCTION app\.(\w+)\([^;]*?AS \$body\$(.*?)\$body\$;",
            file.read_text(),
            re.S,
        ):
            if match[1] in wanted:
                pins[match[1]] = hashlib.sha256(match[2].encode()).hexdigest()
    if set(pins) != wanted:
        raise ValueError("missing_reviewed_function_pin")
    return pins


def expected_target():
    files = {
        "stage1-acceptance-live-interrupted.json": (
            "d59191baac6f74c3db266d6de8ca117c2539794df3d18b9d7961196b61decb20"
        ),
        "stage1-coverage-failure-review.json": (
            "5c6f2fb11058c21bfd0983f70aa95c28e099fba1fccdfc6204f2810664cdfe48"
        ),
    }
    documents = {}
    for name, digest in files.items():
        data = (ROOT / "reports" / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("historical_target_evidence_changed")
        documents[name] = json.loads(data)
    report = documents["stage1-acceptance-live-interrupted.json"]
    review = documents["stage1-coverage-failure-review.json"]
    assert report["run_id"] == RUN and review["run"]["id"] == RUN
    science = report["after_at_report_snapshot"]
    return {
        "session": SESSION,
        "database": DATABASE,
        "run": RUN,
        "environment": "97d22e9f-c65d-4b45-a322-c3194867e3d7",
        "project": PROJECT,
        "bucket": PROJECT,
        "queue": PROJECT + ".ingestion",
        "work_deadline": "2026-10-07T13:03:38.284791Z",
        "deadline": "2026-10-07T13:04:38.284791Z",
        "reference_time": "2025-04-01T00:00:00Z",
        "canonical_bytes": 10721657712,
        "open_state": review["run"]["state"],
        "control_epoch": 1,
        "original_counters": {
            "raw_received_bytes": 30314644,
            "http_attempts": 1260,
            "accepted_profiles": 819,
            "accepted_levels": 572347,
            "controller_claims": 1,
        },
        "science": {
            k: science[k]
            for k in (
                "profiles",
                "measurement_levels",
                "floats",
                "profile_manifest_sha256",
                "active_partitions",
                "active_generation_sha256",
            )
        },
        "chunks": report["chunks"],
        "active_ids": sorted(report["active_generation_ids"]),
        "functions": definition_pins(),
    }


def literal(value):
    return "'" + json.dumps(value, separators=(",", ":")).replace("'", "''") + "'::jsonb"


def finalization_sql(expected, *, rollback=False):
    """All identity/state comparisons and closing occur in the same transaction.

    Test-only rollback represents loss before commit. No permanent helper/schema
    is installed: pg_temp contains only transaction-local verification snapshots.
    """
    value = literal(expected)
    return f"""
BEGIN ISOLATION LEVEL SERIALIZABLE;
SET LOCAL statement_timeout='60s';
SET LOCAL lock_timeout='5s';
SET LOCAL ROLE floatchat_ingestor;
CREATE TEMP TABLE terminal_expected(value jsonb);
INSERT INTO terminal_expected VALUES({value});
DO $verify$
DECLARE e jsonb; r app.ingestion_run; science jsonb; f record; closed_before boolean;
BEGIN
  SELECT value INTO e FROM terminal_expected;
  IF current_database()<>e->>'database' OR
      (SELECT version_num FROM public.alembic_version)<>'0007_http_replay'
    THEN RAISE EXCEPTION 'terminal_identity_mismatch'; END IF;
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=(e->>'run')::uuid;
  IF r.environment_id<>(e->>'environment')::uuid OR r.mode<>'acceptance'
      OR r.run_reference_time_utc<>(e->>'reference_time')::timestamptz
      OR r.requested_start<>'2025-01-01'::timestamptz
      OR r.requested_end<>'2025-04-01'::timestamptz
      OR r.work_deadline<>(e->>'work_deadline')::timestamptz
      OR r.deadline<>(e->>'deadline')::timestamptz
      OR r.canonical_bytes<>(e->>'canonical_bytes')::bigint
      OR r.control_epoch<>(e->>'control_epoch')::bigint+(CASE WHEN r.closed THEN 1 ELSE 0 END)
      OR clock_timestamp()<r.deadline OR NOT EXISTS(
        SELECT 1 FROM app.ingestion_environment m WHERE m.id=r.environment_id
        AND m.mode='acceptance' AND m.disposable AND m.bucket=e->>'bucket'
        AND m.queue_namespace=e->>'queue' AND m.compose_project=e->>'project')
    THEN RAISE EXCEPTION 'terminal_preflight_mismatch'; END IF;
  FOR f IN SELECT key,value FROM jsonb_each_text(e->'functions') LOOP
    IF NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='app' AND p.proname=f.key
      AND p.oid=to_regprocedure('app.'||f.key||
        CASE WHEN f.key='finalize_run' THEN '(uuid,text)'
             WHEN f.key='scientific_snapshot' THEN '()' ELSE '(uuid)' END)
      AND p.prosecdef AND replace(array_to_string(p.proconfig,','),' ','')=
        'search_path=pg_catalog,app'
      AND encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')=f.value)
      THEN RAISE EXCEPTION 'deployed_finalizer_definition_mismatch'; END IF;
  END LOOP;
  FOR f IN SELECT key,value FROM jsonb_each(e->'original_counters') LOOP
    IF to_jsonb(r)->f.key IS DISTINCT FROM f.value THEN RAISE EXCEPTION 'counter_mismatch'; END IF;
  END LOOP;
  science := app.scientific_snapshot();
  FOR f IN SELECT key,value FROM jsonb_each(e->'science') LOOP
    IF science->f.key IS DISTINCT FROM f.value THEN RAISE EXCEPTION 'science_mismatch'; END IF;
  END LOOP;
  IF (SELECT coalesce(jsonb_agg(id::text ORDER BY id::text),'[]'::jsonb)
      FROM app.committed_active_partitions)<>e->'active_ids'
    OR EXISTS(SELECT 1 FROM app.canonical_work w JOIN app.ingestion_chunk c ON c.id=w.chunk_id
      WHERE c.run_id=r.id AND w.status='reserved')
    OR (SELECT count(*) FROM app.ingestion_chunk WHERE run_id=r.id)
       <>jsonb_array_length(e->'chunks')
    THEN RAISE EXCEPTION 'catalogue_or_work_mismatch'; END IF;
  closed_before := r.closed;
  IF closed_before THEN
    IF r.state<>'partial' OR r.termination_reason<>'deadline_expired'
      OR (SELECT count(*) FROM app.run_final_evidence WHERE run_id=r.id)<>1
      THEN RAISE EXCEPTION 'unexpected_closed_state'; END IF;
  ELSIF r.state<>e->>'open_state' OR EXISTS(
      SELECT 1 FROM app.run_final_evidence WHERE run_id=r.id)
    THEN RAISE EXCEPTION 'unexpected_open_state'; END IF;
  IF EXISTS(
    SELECT 1 FROM jsonb_array_elements(e->'chunks') saved
    LEFT JOIN app.ingestion_chunk c ON c.id=(saved->>'id')::uuid AND c.run_id=r.id
    WHERE c.id IS NULL OR c.logical_chunk_key<>saved->>'logical_chunk_key'
      OR c.requested_start<>(saved->>'requested_start')::timestamptz
      OR c.requested_end<>(saved->>'requested_end')::timestamptz
      OR c.tile<>saved->'tile' OR c.leaf<>(saved->>'leaf')::boolean
      OR c.plan_version<>saved->>'plan_version'
      OR c.control_epoch<>(saved->>'control_epoch')::bigint
      OR c.processing_claims<>(saved->>'processing_claims')::integer
      OR c.publication_attempts<>(saved->>'publication_attempts')::integer
      OR c.parent_id IS DISTINCT FROM (saved->>'parent_id')::uuid
      OR c.completed_at IS DISTINCT FROM (saved->>'completed_at')::timestamptz
      OR c.state<>CASE WHEN closed_before AND saved->>'state'='planned'
                      THEN 'failed' ELSE saved->>'state' END
      OR c.reason IS DISTINCT FROM CASE WHEN closed_before AND saved->>'state'='planned'
                      THEN 'deadline_expired' ELSE saved->>'reason' END
      OR c.fence<>(saved->>'fence')::bigint+
           CASE WHEN closed_before AND saved->>'state'='planned' THEN 1 ELSE 0 END
  ) THEN RAISE EXCEPTION 'chunk_snapshot_mismatch'; END IF;
END $verify$;
CREATE TEMP TABLE terminal_before_science AS SELECT app.scientific_snapshot() AS value;
CREATE TEMP TABLE terminal_before_run AS SELECT to_jsonb(r) AS value FROM app.ingestion_run r
  WHERE r.id=({value}->>'run')::uuid;
CREATE TEMP TABLE terminal_protected AS SELECT to_jsonb(c) AS value FROM app.ingestion_chunk c
  WHERE c.run_id=({value}->>'run')::uuid AND c.state IN ('complete','failed','quarantined');
CREATE TEMP TABLE terminal_catalogue AS SELECT to_jsonb(p) AS value FROM app.dataset_partition p;
CREATE TEMP TABLE terminal_finished_attempts AS SELECT to_jsonb(a) AS value
  FROM app.ingestion_attempt a JOIN app.ingestion_chunk c ON c.id=a.chunk_id
  WHERE c.run_id=({value}->>'run')::uuid AND a.finished_at IS NOT NULL;
CREATE TEMP TABLE terminal_frozen_before AS SELECT evidence FROM app.run_final_evidence
  WHERE run_id=({value}->>'run')::uuid;
SELECT app.finalize_run(({value}->>'run')::uuid,'deadline_expired');
DO $after$
DECLARE e jsonb; r app.ingestion_run; f record; before jsonb;
BEGIN
  SELECT value INTO e FROM terminal_expected;
  SELECT * INTO STRICT r FROM app.ingestion_run WHERE id=(e->>'run')::uuid;
  SELECT value INTO before FROM terminal_before_run;
  IF NOT r.closed OR r.state<>'partial' OR r.termination_reason<>'deadline_expired'
      OR (SELECT count(*) FROM app.run_final_evidence WHERE run_id=r.id)<>1
    THEN RAISE EXCEPTION 'terminal_result_mismatch'; END IF;
  FOR f IN SELECT key,value FROM jsonb_each(e->'science') LOOP
    IF app.scientific_snapshot()->f.key IS DISTINCT FROM f.value
      THEN RAISE EXCEPTION 'science_changed'; END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM terminal_protected b WHERE NOT EXISTS(
      SELECT 1 FROM app.ingestion_chunk c WHERE c.run_id=r.id AND to_jsonb(c)=b.value))
    OR EXISTS(SELECT 1 FROM terminal_catalogue b WHERE NOT EXISTS(
      SELECT 1 FROM app.dataset_partition p WHERE to_jsonb(p)=b.value))
    OR (SELECT count(*) FROM terminal_catalogue)<>(SELECT count(*) FROM app.dataset_partition)
    OR EXISTS(SELECT 1 FROM terminal_finished_attempts b WHERE NOT EXISTS(
      SELECT 1 FROM app.ingestion_attempt a WHERE to_jsonb(a)=b.value))
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(e->'chunks') saved
      JOIN app.ingestion_chunk c ON c.id=(saved->>'id')::uuid
      WHERE saved->>'state'='planned' AND (c.state<>'failed'
        OR c.reason<>'deadline_expired' OR c.fence<>(saved->>'fence')::bigint+1
        OR c.lease_until IS NOT NULL))
    OR EXISTS(SELECT 1 FROM app.ingestion_chunk c WHERE c.run_id=r.id
      AND c.state NOT IN ('complete','failed','quarantined'))
    OR r.canonical_bytes<>(before->>'canonical_bytes')::bigint
    OR r.deadline<>(before->>'deadline')::timestamptz
    OR r.work_deadline<>(before->>'work_deadline')::timestamptz
    OR r.limits<>before->'limits' OR r.http_attempts<>(before->>'http_attempts')::bigint
    OR r.raw_received_bytes<>(before->>'raw_received_bytes')::bigint
    OR (SELECT coalesce(jsonb_agg(id::text ORDER BY id::text),'[]'::jsonb)
      FROM app.committed_active_partitions)<>e->'active_ids'
    OR (SELECT evidence->'active_generation_ids' FROM app.run_final_evidence
      WHERE run_id=r.id)<>(SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb)
      FROM app.committed_active_partitions)
    OR EXISTS(SELECT 1 FROM terminal_frozen_before b WHERE NOT EXISTS(
      SELECT 1 FROM app.run_final_evidence frozen WHERE frozen.run_id=r.id
      AND frozen.evidence=b.evidence))
    THEN RAISE EXCEPTION 'protected_evidence_changed'; END IF;
END $after$;
{"ROLLBACK" if rollback else "COMMIT"};
"""


def report_sql():
    # Only persisted evidence; no live HTTP, object reads or fresh reconciliation.
    return f"""BEGIN READ ONLY; SET LOCAL ROLE floatchat_ingestor;
SELECT jsonb_build_object('kind','persisted_incomplete_terminalization',
 'session','{SESSION}','run_id',r.id,'state',r.state,'closed',r.closed,
 'termination_reason',r.termination_reason,'work_deadline',r.work_deadline,'deadline',r.deadline,
 'canonical_bytes',r.canonical_bytes,'final_evidence_frozen',f.run_id IS NOT NULL,
 'coverage_complete',false,'acceptance_certified',false,'expected_exit_code',3,
 'states',(SELECT jsonb_object_agg(state,n) FROM(SELECT state,count(*) n
   FROM app.ingestion_chunk WHERE run_id=r.id GROUP BY state) s),
 'frozen_evidence',f.evidence)
FROM app.ingestion_run r JOIN app.run_final_evidence f ON f.run_id=r.id WHERE r.id='{RUN}';
COMMIT;"""


def command(arguments, *, input=None, timeout=30):
    result = subprocess.run(arguments, input=input, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError("terminal_operation_failed")
    return result.stdout.strip()


def execute_approved():
    manifest = ROOT / ".cache/stage1-acceptance" / SESSION / "manifest.json"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError("session_seal_changed")
    expected = expected_target()
    containers = command(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            "label=com.docker.compose.project=" + PROJECT,
            "--format",
            '{{.ID}}\t{{.Label "com.docker.compose.service"}}\t{{.State}}',
        ]
    )
    rows = [row.split("\t") for row in containers.splitlines() if row]
    if not rows or any(len(row) != 3 or row[2] not in ("exited", "created") for row in rows):
        raise ValueError("project_not_stopped")
    databases = [row[0] for row in rows if row[1] == "db"]
    if len(databases) != 1:
        raise ValueError("database_identity_unavailable")
    database = databases[0]
    started = False
    try:
        command(["docker", "start", database])
        started = True
        until = time.monotonic() + 30
        while True:
            try:
                command(
                    ["docker", "exec", database, "pg_isready", "-U", "postgres", "-d", DATABASE]
                )
                break
            except ValueError:
                if time.monotonic() >= until:
                    raise ValueError("database_readiness_timeout") from None
                time.sleep(0.25)
        base = [
            "docker",
            "exec",
            "-i",
            database,
            "psql",
            "-X",
            "-q",
            "-t",
            "-A",
            "-U",
            "acceptance_ingestion",
            "-d",
            DATABASE,
            "-v",
            "ON_ERROR_STOP=1",
        ]
        command(base, input=finalization_sql(expected), timeout=90)
        record = json.loads(command(base, input=report_sql(), timeout=90))
        if (
            not record["closed"]
            or record["state"] != "partial"
            or not record["final_evidence_frozen"]
        ):
            raise ValueError("frozen_evidence_unavailable")
        from uuid import UUID

        from floatchat_core.ingestion.reporting import coverage_evidence

        record["coverage"] = coverage_evidence(
            record["frozen_evidence"]["report_metrics"], UUID(expected["environment"])
        )
        if record["coverage"]["proved_complete"]:
            raise ValueError("unexpected_complete_coverage")
        serialized = json.dumps(record, indent=2) + "\n"
        command(
            [
                str(ROOT / ".cache/tools/gitleaks"),
                "stdin",
                "--redact=100",
                "--no-banner",
                "--config",
                str(ROOT / ".gitleaks.toml"),
            ],
            input=serialized,
            timeout=60,
        )
        output = ROOT / "reports/stage1-original-terminalization.json"
        output.write_text(serialized)
        (ROOT / "reports/stage1-original-terminalization.md").write_text(
            "# Preserved run — frozen incomplete evidence\n\n"
            "Closed/partial; deadline_expired; exit 3. Acceptance is not certified. "
            "Science, generations, original failed/quarantined leaves and budgets were checked "
            "against the reviewed saved snapshot in the closing transaction. "
            "Availability, attempts, timings, reconciliation and coverage gaps are in "
            "[the frozen JSON](stage1-original-terminalization.json). "
            "No ingestion was restarted. Stage 2 remains blocked.\n"
        )
        print(
            json.dumps(
                {
                    "category": "terminalized_incomplete",
                    "state": "partial",
                    "report": str(output.relative_to(ROOT)),
                    "exit_code": 3,
                }
            )
        )
        return 3
    finally:
        if started:
            command(["docker", "stop", "--time", "10", database], timeout=30)


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, "terminalization_arguments_invalid\n")

    parser = SafeParser(description=__doc__)
    parser.add_argument("--session", required=True, choices=[SESSION])
    parser.add_argument("--review-approved", action="store_true")
    args = parser.parse_args()
    if not args.review_approved:
        print("review_only; separate Astra/owner approval required; no services operated")
        return 2
    try:
        return execute_approved()
    except KeyboardInterrupt:
        print("terminalization_interrupted; retry this command only after review")
        return 130
    except Exception:
        print("terminalization_refused_or_evidence_pending; no exception details emitted")
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
