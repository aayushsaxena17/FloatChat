"""The job runner over doubles: planning, reuse, resume, failures (PRD section 22), cancel."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from floatchat_core.jobs.model import JobLimits, parse_export_request, plan_for
from floatchat_core.jobs.runner import JobRunner, RunStatus
from floatchat_core.jobs.store import MemoryJobStore
from floatchat_core.query.errors import QueryError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage5_doubles import FakeCatalogue, FakeExporter, FakeRuns  # noqa: E402

NOW = datetime(2026, 10, 16, tzinfo=UTC)
LIMITS = JobLimits(run_poll_seconds=0.01, overlap_wait_seconds=0.01, heartbeat_seconds=5)


def request(start="2016-01-01", end="2017-07-01", fmt="parquet", **extra):
    return parse_export_request(
        {
            "time_range": {"start": start + "T00:00:00Z", "end": end + "T00:00:00Z"},
            "geography": {"kind": "bbox", "west": 60, "south": 10, "east": 65, "north": 15},
            "format": fmt,
            **extra,
        }
    )


def create(store, req, client="c1"):
    plan = plan_for(req, LIMITS)
    job, created, attached = store.create(
        client_id=client,
        kind="export",
        queue="export",
        request=req.canonical(),
        request_sha256=req.sha256(),
        plan=plan.canonical(),
        idempotency_key=req.idempotency_key,
    )
    return job, created, attached


def runner(store, catalogue, runs, exporter, **kwargs):
    return JobRunner(
        store,
        catalogue,
        runs,
        exporter,
        limits=LIMITS,
        sleep=lambda s: None,
        clock=lambda: NOW,
        **kwargs,
    )


def test_first_run_fetches_per_calendar_year_then_exports_and_second_run_reuses_everything():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, polls=3), FakeExporter()
    job, _, _ = create(store, request())
    done = runner(store, catalogue, runs, exporter).run_once(("export",))
    assert done is not None and store.get(job.id).state == "completed"
    chunks = store.chunks(job.id)
    assert [c.label for c in chunks] == ["2016-01..2016-12", "2017-01..2017-06", "export"]
    assert all(c.state == "complete" for c in chunks)
    assert [i.start.year for i, _ in runs.admitted] == [2016, 2017]
    assert runs.admitted[0][1] == [[60, 10]]
    finished = store.get(job.id)
    assert finished.progress["slots_total"] == 18 and finished.progress["slots_reused"] == 0
    assert len(store.artefacts(job.id)) == 2
    kinds = [event.kind for event in store.events(job.id)]
    assert kinds[0] == "planned" and kinds[-1] == "finished"
    # Same request again: every slot is committed now, so no fetch chunk is planned.
    again, created, attached = create(store, request())
    assert created and not attached
    runner(store, catalogue, runs, exporter).run_once(("export",))
    assert store.get(again.id).state == "completed"
    assert [c.kind for c in store.chunks(again.id)] == ["export"]
    assert store.get(again.id).progress["reuse_ratio"] == 1.0
    assert len(runs.admitted) == 2


def test_identical_active_request_attaches_and_idempotency_key_returns_the_same_job():
    store = MemoryJobStore()
    job, created, attached = create(store, request(idempotency_key="k1"))
    same, created2, attached2 = create(store, request(idempotency_key="k1"))
    assert created and not created2 and same.id == job.id and not attached2
    other, created3, attached3 = create(store, request(idempotency_key="k2"))
    assert not created3 and attached3 and other.id == job.id
    foreign, created4, _ = create(store, request(idempotency_key="k2"), client="c2")
    assert created4 and foreign.id != job.id


def test_worker_killed_mid_chunk_resumes_without_repeating_complete_chunks():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, polls=2), FakeExporter()
    job, _, _ = create(store, request())

    class Dying(JobRunner):
        def _fetch(self, job, chunk, environment):
            super()._fetch(job, chunk, environment)
            if chunk.label.startswith("2016"):
                raise KeyboardInterrupt  # the process dies right after the first chunk

    first = Dying(
        store, catalogue, runs, exporter, limits=LIMITS, sleep=lambda s: None, clock=lambda: NOW
    )
    with pytest.raises(KeyboardInterrupt):
        first.run_once(("export",))
    states = {c.label: c.state for c in store.chunks(job.id)}
    assert states == {
        "2016-01..2016-12": "complete",
        "2017-01..2017-06": "pending",
        "export": "pending",
    }
    # The lease has not lapsed: nobody else can claim it yet.
    assert runner(store, catalogue, runs, exporter, worker="other").run_once(("export",)) is None
    store._jobs[job.id] = store._jobs[job.id].__class__(
        **{**store._jobs[job.id].__dict__, "lease_until": None}
    )
    runner(store, catalogue, runs, exporter, worker="other").run_once(("export",))
    assert store.get(job.id).state == "completed"
    assert len(runs.admitted) == 2  # the 2016 run was never admitted twice
    assert exporter.calls and store.chunks(job.id)[0].attempts == 1


def test_resume_reattaches_to_a_running_ingestion_run():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, polls=3), FakeExporter()
    job, _, _ = create(store, request(end="2016-07-01"))

    class Dying(JobRunner):
        def _pause(self, job, seconds):
            raise KeyboardInterrupt  # dies while waiting for the run

    with pytest.raises(KeyboardInterrupt):
        Dying(
            store, catalogue, runs, exporter, limits=LIMITS, sleep=lambda s: None, clock=lambda: NOW
        ).run_once(("export",))
    chunk = store.chunks(job.id)[0]
    assert chunk.state == "running" and chunk.ingestion_run_id is not None
    store._jobs[job.id] = store._jobs[job.id].__class__(
        **{**store._jobs[job.id].__dict__, "lease_until": None}
    )
    runner(store, catalogue, runs, exporter, worker="other").run_once(("export",))
    assert store.get(job.id).state == "completed"
    assert (
        len(runs.admitted) == 1
        and store.chunks(job.id)[0].ingestion_run_id == chunk.ingestion_run_id
    )


def test_upstream_down_ends_partial_with_missing_chunks_listed():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, fail_months={"2016-03", "2016-04"}), FakeExporter()
    job, _, _ = create(store, request(end="2016-07-01"))
    runner(store, catalogue, runs, exporter).run_once(("export",))
    finished = store.get(job.id)
    assert finished.state == "partial"
    chunk = store.chunks(job.id)[0]
    # The first run was partial; the chunk was re-planned twice for the two missing months
    # only (bounded retries), and the last of the three runs failed outright.
    assert chunk.state == "failed" and chunk.error["code"] == "fetch_failed"
    assert [run["state"] for run in chunk.evidence["runs"]] == ["partial", "failed", "failed"]
    assert len(runs.admitted) == 3
    assert [i.start.month for i, _ in runs.admitted] == [1, 3, 3]
    assert runs.admitted[1][0].end.month == 5
    assert chunk.evidence["missing_slots_after"] == 2
    assert "3 runs" in chunk.error["message"]
    assert chunk.evidence["missing_chunks"] == ["2016-03", "2016-04"]
    assert finished.result["failed_chunks"] == ["2016-01..2016-06"]
    assert {slot["month"] for slot in finished.result["missing_slots"]} == {"2016-03", "2016-04"}
    assert exporter.calls, "the export still runs over the committed coverage"


def test_overlap_skip_waits_then_proceeds():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, overlap_first=3), FakeExporter()
    job, _, _ = create(store, request(end="2016-03-01"))
    runner(store, catalogue, runs, exporter).run_once(("export",))
    assert store.get(job.id).state == "completed"
    assert any(e.payload.get("state") == "waiting" for e in store.events(job.id))


def test_cancel_during_fetch_cancels_the_run_and_the_job():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue, polls=50), FakeExporter()
    job, _, _ = create(store, request(end="2016-03-01"))
    polls = {"n": 0}

    def sleep(seconds):
        polls["n"] += 1
        if polls["n"] == 3:
            store.cancel(job.id, "c1", None)

    JobRunner(
        store, catalogue, runs, exporter, limits=LIMITS, sleep=sleep, clock=lambda: NOW
    ).run_once(("export",))
    finished = store.get(job.id)
    assert finished.state == "cancelled" and runs.cancelled
    assert {c.state for c in store.chunks(job.id)} == {"cancelled"}
    assert not exporter.calls
    with pytest.raises(QueryError, match="job_conflict"):
        store.cancel(job.id, "c1", None)


def test_queued_job_cancels_immediately_and_version_mismatch_conflicts():
    store = MemoryJobStore()
    job, _, _ = create(store, request())
    with pytest.raises(QueryError, match="job_conflict"):
        store.cancel(job.id, "c1", job.version + 5)
    cancelled = store.cancel(job.id, "c1", job.version)
    assert cancelled.state == "cancelled"
    assert MemoryJobStore().claim(("export",), "w", 60) is None
    assert store.claim(("export",), "w", 60) is None


def test_export_failure_fails_the_job_and_keeps_the_chunks():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue), FakeExporter(fail=True)
    job, _, _ = create(store, request(end="2016-03-01"))
    runner(store, catalogue, runs, exporter).run_once(("export",))
    finished = store.get(job.id)
    assert finished.state == "failed" and finished.error["code"] == "export_failed"
    assert store.chunks(job.id)[-1].state == "failed"


def test_months_not_yet_ended_are_left_missing_not_fetched():
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    runs, exporter = FakeRuns(catalogue), FakeExporter()
    job, _, _ = create(store, request(start="2026-09-01", end="2026-11-01"))
    runner(store, catalogue, runs, exporter).run_once(("export",))
    assert [i.start.month for i, _ in runs.admitted] == [9]
    assert store.get(job.id).state == "partial"


def test_a_complete_run_that_leaves_slots_missing_is_retried_not_trusted():
    # A run can end "complete" for an interval and tile set that is not the chunk's (the
    # adapter now refuses foreign runs, and the runner never trusts a run's state alone):
    # completion is read from the catalogue, and the still-missing slots are re-planned.
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    exporter = FakeExporter()
    job, _, _ = create(store, request(end="2016-04-01"))

    class Lying(FakeRuns):
        def status(self, run_id):
            status = super().status(run_id)
            return RunStatus(True, "complete", status.evidence)  # claims success

    lying = Lying(catalogue, fail_months={"2016-02"})
    runner(store, catalogue, lying, exporter).run_once(("export",))
    chunk = store.chunks(job.id)[0]
    assert chunk.state == "failed" and len(lying.admitted) == 3
    assert chunk.evidence["missing_slots_after"] == 1
    assert store.get(job.id).state == "partial"


def test_a_quarantined_slot_is_reported_not_fetched_again():
    # Stage 1 quarantines a whole month-tile on an upstream data warning and writes no
    # receipt for it; the runner leaves it out of the run, completes the chunk with the slot
    # listed, and the job ends partial with the quarantined slots in its result.
    store, catalogue = MemoryJobStore(), FakeCatalogue()
    exporter = FakeExporter()
    job, _, _ = create(store, request(end="2016-04-01"))
    runs = FakeRuns(catalogue, quarantine={("2016-02", 60, 10)})  # the request's one tile
    runner(store, catalogue, runs, exporter).run_once(("export",))
    chunk = store.chunks(job.id)[0]
    assert chunk.state == "complete" and len(runs.admitted) == 1
    assert [s["month"] for s in chunk.evidence["quarantined_slots"]] == ["2016-02"]
    assert chunk.evidence["missing_slots_after"] == 1
    finished = store.get(job.id)
    assert finished.state == "partial"
    assert len(finished.result["quarantined_slots"]) == 1
    assert finished.result["failed_chunks"] == []
    # The second identical request plans the quarantined slot, admits no run for it, and
    # ends the same way: no fetch is repeated for a slot the source policy rejected.
    job2, _, _ = create(store, request(end="2016-04-01"))
    runner(store, catalogue, runs, exporter).run_once(("export",))
    assert len(runs.admitted) == 1
    chunk2 = [c for c in store.chunks(job2.id) if c.kind == "fetch"][0]
    assert chunk2.state == "complete" and chunk2.evidence["run_state"] == "quarantined"
    assert store.get(job2.id).state == "partial"
