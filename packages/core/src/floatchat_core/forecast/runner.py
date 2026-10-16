"""The forecast job (ADR-0082): series chunk, model chunk, publication.

A refused forecast is a completed job whose run says why; an experimental one shows the
baseline with every candidate's metrics and no authoritative claim; a published one carries the
selected model, its version and the snapshot it was trained on.
"""

import json
import platform
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..ingestion.planning import Interval, Tile
from ..jobs.model import Job, JobChunk
from ..jobs.planner import ChunkSpec
from ..jobs.store import JobStore
from ..query.catalogue import Coverage, EnvironmentInfo
from ..query.errors import QueryError
from ..query.geography import ResolvedGeography, resolve_geography
from ..query.plan import NamedRegion
from . import models
from .model import BOUNDARY_TEXT, ForecastLimits, ForecastRequest, definition_sha256
from .series import Refusal, SeriesSnapshot, apply_missing_policy, check_eligibility
from .store import ForecastStore

Upload = Callable[[str, bytes], None]


class Catalogue(Protocol):
    def environment(self) -> EnvironmentInfo: ...

    def tiles_for(self, geography: ResolvedGeography) -> tuple[Tile, ...]: ...

    def coverage(
        self, environment_id: uuid.UUID, interval: Interval, tiles: tuple[Tile, ...]
    ) -> Coverage: ...


class Builder(Protocol):
    def build(
        self,
        definition: Any,
        geography: ResolvedGeography,
        environment: EnvironmentInfo,
        coverage_for: Callable[[Interval], Coverage],
    ) -> SeriesSnapshot: ...


def versions_record(limits: ForecastLimits) -> dict[str, Any]:
    import scipy
    import statsmodels

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "statsmodels": statsmodels.__version__,
        "seed": limits.seed,
        "protocol": "rolling-origin-v1",
        "grid": "sarima-grid-v1",
    }


def run_forecast(snapshot: SeriesSnapshot, horizon: int, limits: ForecastLimits) -> dict[str, Any]:
    """Pure computation from a snapshot to a run document (also what the harness runs).

    Returns ``status`` (``published``, ``experimental`` or ``refused``) and the history,
    forecast, backtest, selection, diagnostics and reason the run stores.
    """
    np.random.seed(limits.seed)
    try:
        regular = apply_missing_policy(snapshot.months, snapshot.values, snapshot.counts, limits)
        check_eligibility(regular, horizon, limits)
    except Refusal as refusal:
        return {
            "status": "refused",
            "reason": f"{refusal.code}: {refusal.message}",
            "refusal_code": refusal.code,
            "history": {
                "months": snapshot.months,
                "values": snapshot.values,
                "counts": snapshot.counts,
            },
            "versions": versions_record(limits),
        }
    series = np.asarray(regular.values, dtype=float)
    first_train = series[: series.size - limits.folds - max(limits.horizons) + 1]
    ranked, ledger = models.rank_candidates(first_train, limits)
    candidates = [models.BASELINE, *ranked]
    backtest = models.rolling_backtest(series, candidates, limits)
    selection = models.select(series, backtest, candidates, limits)
    chosen, prediction, params = models.final_forecast(series, selection, horizon, limits)
    last = datetime.strptime(regular.months[-1], "%Y-%m").replace(tzinfo=UTC)
    future = []
    cursor = last
    for _ in range(horizon):
        month = cursor.month % 12 + 1
        year = cursor.year + (1 if cursor.month == 12 else 0)
        cursor = cursor.replace(year=year, month=month)
        future.append(f"{cursor:%Y-%m}")
    warnings = list(selection.reasons)
    if regular.policy["months_missing"]:
        warnings.append(
            f"{regular.policy['months_missing']} months were interpolated: "
            + ", ".join(regular.policy["filled_months"][:12])
        )
    if selection.status == "experimental":
        warnings.append(
            "No SARIMA candidate beat the seasonal-naive baseline by the configured margin "
            "and passed diagnostics; the baseline forecast is shown and is not authoritative."
        )
    return {
        "status": selection.status,
        "reason": None,
        "history": {
            "months": regular.months,
            "values": regular.values,
            "filled": regular.filled,
            "counts": snapshot.counts[
                snapshot.months.index(regular.months[0]) : snapshot.months.index(regular.months[-1])
                + 1
            ],
            "policy": regular.policy,
        },
        "forecast": {
            "months": future,
            "mean": [float(v) for v in prediction.mean],
            "lower80": [float(v) for v in prediction.lower80],
            "upper80": [float(v) for v in prediction.upper80],
            "lower95": [float(v) for v in prediction.lower95],
            "upper95": [float(v) for v in prediction.upper95],
            "model": chosen.as_dict(),
        },
        "backtest": {
            "protocol": "rolling-origin, expanding window, refit per fold",
            "folds": limits.folds,
            "horizons": list(limits.horizons),
            "baseline": models.BASELINE.label,
            "results": backtest,
            "aicc_ranking": [entry for entry in ledger if entry["aicc"] is not None][:20],
            "candidates_carried": [candidate.label for candidate in ranked],
        },
        "selection": {
            "selected": None if selection.selected is None else selection.selected.as_dict(),
            "status": selection.status,
            "reasons": selection.reasons,
            "improvement_required": limits.improvement,
            "diagnostics": selection.diagnostics,
            "parameters": params,
        },
        "warnings": warnings,
        "versions": versions_record(limits),
    }


class ForecastRunner:
    """Runs a forecast job: the series chunk, then the model chunk; stores run and model."""

    def __init__(
        self,
        *,
        jobs: JobStore,
        forecasts: ForecastStore,
        catalogue: Catalogue,
        builder: Builder,
        upload: Upload,
        limits: ForecastLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.jobs = jobs
        self.forecasts = forecasts
        self.catalogue = catalogue
        self.builder = builder
        self.upload = upload
        self.limits = limits or ForecastLimits()
        self.clock = clock

    def process(self, job: Job, finish: Callable[..., Job]) -> Job:
        request = ForecastRequest.model_validate(
            {k: v for k, v in job.request.items() if k not in ("schema",)}
        )
        environment = self.catalogue.environment()
        reference = environment.reference_time or self.clock()
        document = request.definition(reference, self.limits.history_years)
        definition = self.forecasts.definition(job.client_id, document, definition_sha256(document))
        geography = resolve_geography(NamedRegion(kind="named_region", value=definition.region))
        tiles = self.catalogue.tiles_for(geography)
        chunks = self.jobs.chunks(job.id)
        if not chunks:
            chunks = self.jobs.set_chunks(
                job.id,
                [
                    ChunkSpec(
                        "series",
                        "series",
                        definition.series_start,
                        definition.series_end,
                        [[t.west, t.south] for t in tiles],
                    ),
                    ChunkSpec("model", "model", None, None, []),
                ],
            )
            self.jobs.emit(job.id, "planned", {"definition": definition.id, "chunks": 2})
        run = self.forecasts.run_for_job(job.id) or self.forecasts.create_run(
            definition.id, job.client_id, job.id, request.horizon
        )
        self.jobs.update(
            job.id, state="analysing", result={"forecast_run": run.id, "definition": definition.id}
        )
        series_chunk = next(c for c in chunks if c.kind == "series")
        model_chunk = next(c for c in chunks if c.kind == "model")
        snapshot = self._series(job, series_chunk, definition, geography, environment, tiles)
        self.jobs.update_chunk(model_chunk.id, state="running", attempt=True)
        self.jobs.emit(
            job.id, "chunk", {"seq": model_chunk.seq, "state": "running", "label": "model"}
        )
        outcome = run_forecast(snapshot, request.horizon, self.limits)
        model_id: str | None = None
        if outcome["status"] != "refused":
            selected = outcome["selection"]["selected"]
            family = "sarima" if selected else "seasonal_naive"
            order = selected or models.BASELINE.as_dict()
            artefact_key = (
                f"forecasts/{definition.id}/model-v{self._next_version(definition.id)}.json"
            )
            artefact = {
                "schema": "forecast-model-v1",
                "definition": definition.as_dict(),
                "snapshot_id": snapshot.id,
                "family": family,
                "order": order,
                "parameters": outcome["selection"]["parameters"],
                "metrics": outcome["backtest"]["results"],
                "diagnostics": outcome["selection"]["diagnostics"],
                "versions": outcome["versions"],
                "generated_at": self.clock().isoformat().replace("+00:00", "Z"),
            }
            self.upload(
                artefact_key, json.dumps(artefact, indent=2, sort_keys=True, default=str).encode()
            )
            model = self.forecasts.add_model(
                definition.id,
                family=family,
                model_order={**order, "parameters": outcome["selection"]["parameters"]},
                training_snapshot={
                    "snapshot_id": snapshot.id,
                    "dataset_version": snapshot.dataset_version,
                    "partitions": len(snapshot.partitions),
                    "months": [snapshot.months[0], snapshot.months[-1]] if snapshot.months else [],
                    "policy": outcome["history"].get("policy"),
                },
                metrics=outcome["backtest"]["results"],
                diagnostics=outcome["selection"]["diagnostics"],
                status="selected" if selected else "baseline",
                artefact_key=artefact_key,
            )
            model_id = model.id
        updated = self.forecasts.update_run(
            run.id,
            model_id=model_id,
            status=outcome["status"],
            reason=outcome.get("reason"),
            history=outcome["history"],
            forecast=outcome.get("forecast", {}),
            backtest={**outcome.get("backtest", {}), "selection": outcome.get("selection", {})},
            warnings=outcome.get("warnings", []),
            limitations=BOUNDARY_TEXT,
            seed=self.limits.seed,
            versions={**outcome["versions"], "snapshot_id": snapshot.id},
            generated_at=self.clock(),
        )
        self.jobs.update_chunk(
            model_chunk.id,
            state="complete",
            evidence={"status": updated.status, "model_id": model_id, "run_id": updated.id},
        )
        self.jobs.emit(
            job.id, "chunk", {"seq": model_chunk.seq, "state": "complete", "status": updated.status}
        )
        return finish(
            job,
            "completed",
            result={
                "forecast_run": updated.id,
                "definition": definition.id,
                "model": model_id,
                "status": updated.status,
                "reason": updated.reason,
            },
        )

    def _series(
        self,
        job: Job,
        chunk: JobChunk,
        definition: Any,
        geography: ResolvedGeography,
        environment: EnvironmentInfo,
        tiles: tuple[Tile, ...],
    ) -> SeriesSnapshot:
        if chunk.state == "complete" and chunk.evidence.get("snapshot"):
            return SeriesSnapshot.from_dict(chunk.evidence["snapshot"])
        self.jobs.update_chunk(chunk.id, state="running", attempt=True)
        self.jobs.emit(job.id, "chunk", {"seq": chunk.seq, "state": "running", "label": "series"})

        def coverage_for(interval: Interval) -> Coverage:
            return self.catalogue.coverage(environment.id, interval, tiles)

        try:
            snapshot = self.builder.build(definition, geography, environment, coverage_for)
        except QueryError as error:
            self.jobs.update_chunk(
                chunk.id, state="failed", error={"code": error.code, "message": error.text}
            )
            run = self.forecasts.run_for_job(job.id)
            if run is not None:
                # The run never stays "pending" behind a failed job: it is refused with the
                # engine's reason, and the job itself records the failure.
                self.forecasts.update_run(
                    run.id,
                    status="refused",
                    reason=f"{error.code}: {error.text}",
                    limitations=BOUNDARY_TEXT,
                    generated_at=self.clock(),
                )
            raise
        key = f"forecasts/{definition.id}/snapshot-{snapshot.id}.json"
        self.upload(
            key, json.dumps(snapshot.as_dict(), indent=2, sort_keys=True, default=str).encode()
        )
        self.jobs.update_chunk(
            chunk.id,
            state="complete",
            evidence={
                "snapshot": snapshot.as_dict(),
                "object_key": key,
                "months_with_values": sum(1 for v in snapshot.values if v is not None),
            },
        )
        self.jobs.emit(
            job.id, "chunk", {"seq": chunk.seq, "state": "complete", "snapshot": snapshot.id}
        )
        return snapshot

    def _next_version(self, definition_id: str) -> int:
        # The store assigns the version; the artefact key only needs to be unique.
        return int(self.clock().timestamp())


def snapshot_path(directory: Path, snapshot: SeriesSnapshot) -> Path:
    return directory / f"{snapshot.id}.json"
