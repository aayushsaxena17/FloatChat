"""Doubles for the job runner tests: a catalogue, historical runs and an exporter."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from floatchat_core.ingestion.objects import CatalogueRecord
from floatchat_core.ingestion.planning import Interval, Tile
from floatchat_core.query.catalogue import Coverage, EnvironmentInfo, SlotCoverage, months_of, slot_key
from floatchat_core.query.geography import ResolvedGeography, envelope_tiles
from floatchat_core.jobs.runner import ArtefactSpec, RunStatus

ENV = EnvironmentInfo(uuid.UUID(int=1), "test", "acceptance", datetime(2025, 4, 1, tzinfo=UTC), 2)


def record(key: str, ordinal: int = 1) -> CatalogueRecord:
    digest = uuid.uuid5(uuid.NAMESPACE_URL, key + str(ordinal)).hex * 2
    return CatalogueRecord(
        uuid.uuid4(), ENV.id, key, 1, 1, "active", True, True, "indian-ocean-v1",
        "core-parquet-v1", f"normalised/sha256/{digest}.parquet", digest, 1000, "part", ordinal,
    )


class FakeCatalogue:
    """Coverage is derived from a set of committed (month, tile) keys that fetches extend."""

    def __init__(self, covered: set[str] | None = None) -> None:
        self.covered: set[str] = set(covered or ())
        self.calls = 0

    def environment(self) -> EnvironmentInfo:
        return ENV

    def tiles_for(self, geography: ResolvedGeography) -> tuple[Tile, ...]:
        return envelope_tiles(geography.boxes)

    def coverage(self, environment_id: uuid.UUID, interval: Interval, tiles: tuple[Tile, ...]) -> Coverage:
        self.calls += 1
        slots = []
        manifests: dict[str, list[Any]] = {}
        for month in months_of(interval):
            for tile in tiles:
                key = slot_key(month, tile)
                if key in self.covered:
                    slots.append(SlotCoverage(key, f"{month:%Y-%m}", tile, "covered", (), 3, 300, (record(key),)))
                    manifests[key] = [{"profile_id": f"p-{key}", "hash": "h"}]
                else:
                    slots.append(SlotCoverage(key, f"{month:%Y-%m}", tile, "missing", ("no receipt",), 0, 0, ()))
        return Coverage(interval, tiles, tuple(slots), manifests)


@dataclass
class FakeRuns:
    """Historical runs that complete after ``polls`` status calls, or fail by label."""

    catalogue: FakeCatalogue
    polls: int = 1
    fail_months: set[str] = field(default_factory=set)
    overlap_first: int = 0
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    admitted: list[tuple[Interval, list[list[int]]]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    def admit(self, request_id, interval, tiles, job_id):
        if self.overlap_first > 0:
            self.overlap_first -= 1
            return "overlap_skip", None
        run_id = str(uuid.uuid4())
        self.admitted.append((interval, tiles))
        self.runs[run_id] = {"interval": interval, "tiles": tiles, "polls": 0}
        return "created", run_id

    def status(self, run_id):
        run = self.runs[run_id]
        run["polls"] += 1
        if run["polls"] < self.polls:
            return RunStatus(False, "fetching", {})
        months = [f"{m:%Y-%m}" for m in months_of(run["interval"])]
        failed = [m for m in months if m in self.fail_months]
        for month in months_of(run["interval"]):
            if f"{month:%Y-%m}" in self.fail_months:
                continue
            for west, south in run["tiles"]:
                self.catalogue.covered.add(slot_key(month, Tile(west, south)))
        state = "complete" if not failed else ("partial" if len(failed) < len(months) else "failed")
        return RunStatus(True, state, {"http_attempts": 3 * len(months), "missing_chunks": failed, "termination_reason": None})

    def cancel(self, run_id):
        self.cancelled.append(run_id)


class FakeExporter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[Coverage] = []

    def export(self, job, plan, geography, coverage, environment):
        self.calls.append(coverage)
        if self.fail:
            raise RuntimeError("disk full")
        key = f"exports/{job.id}/floatchat-export-{job.id[:8]}.{job.request['format']}"
        return [
            ArtefactSpec(job.request["format"], "data", key, 1234, "a" * 64, 10, 2, {"schema": "export-manifest-v1"}),
            ArtefactSpec("json", "manifest", key + ".manifest.json", 10, "b" * 64, 0, 0, {}),
        ]
