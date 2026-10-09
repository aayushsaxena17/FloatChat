-- Stage 3 (ADR-0064): the coverage panel shows the ingestion timestamp and the source retrieval
-- window. The view keeps its first six columns (CREATE OR REPLACE VIEW requires that) and adds
-- the latest completed run's id, its actual creation time and the earliest and latest raw
-- retrieval of that run. Grants on the view are retained by PostgreSQL.
CREATE OR REPLACE VIEW app.query_environment AS
SELECT e.id, e.name, e.mode, e.disposable,
  latest.run_reference_time_utc AS reference_time,
  (SELECT count(*) FROM app.ingestion_run r
    WHERE r.environment_id = e.id AND r.closed AND r.state IN ('complete','partial')) AS completed_runs,
  latest.id AS latest_run_id,
  latest.created_at_actual_utc AS ingested_at,
  (SELECT min(m.retrieved_at) FROM app.raw_manifest m WHERE m.run_id = latest.id) AS source_retrieved_from,
  (SELECT max(m.retrieved_at) FROM app.raw_manifest m WHERE m.run_id = latest.id) AS source_retrieved_to
FROM app.ingestion_environment e
LEFT JOIN LATERAL (
  SELECT r.id, r.run_reference_time_utc, r.created_at_actual_utc FROM app.ingestion_run r
  WHERE r.environment_id = e.id AND r.closed AND r.state IN ('complete','partial')
  ORDER BY r.run_reference_time_utc DESC, r.created_at_actual_utc DESC LIMIT 1
) latest ON true;
