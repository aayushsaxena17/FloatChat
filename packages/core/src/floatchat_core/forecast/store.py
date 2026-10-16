"""Forecast definitions, model versions and runs (ADR-0082) on the application login."""

import json
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine, Row

from ..query.errors import QueryError
from .model import Definition, ForecastModel, ForecastRun


class ForecastStore(Protocol):
    def definition(self, client_id: str, document: dict[str, Any], sha256: str) -> Definition: ...

    def get_definition(self, definition_id: str) -> Definition | None: ...

    def add_model(
        self,
        definition_id: str,
        *,
        family: str,
        model_order: dict[str, Any],
        training_snapshot: dict[str, Any],
        metrics: dict[str, Any],
        diagnostics: dict[str, Any],
        status: str,
        artefact_key: str | None,
    ) -> ForecastModel: ...

    def get_model(self, model_id: str) -> ForecastModel | None: ...

    def create_run(
        self, definition_id: str, client_id: str, job_id: str | None, horizon: int
    ) -> ForecastRun: ...

    def update_run(self, run_id: str, **fields: Any) -> ForecastRun: ...

    def get_run(self, run_id: str, client_id: str | None = None) -> ForecastRun | None: ...

    def list_runs(self, client_id: str, limit: int) -> list[ForecastRun]: ...

    def run_for_job(self, job_id: str) -> ForecastRun | None: ...


def validate_run_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise QueryError("forecast_not_found") from None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _definition(row: Row[Any]) -> Definition:
    return Definition(
        id=str(row.id),
        client_id=row.client_id,
        definition_sha256=row.definition_sha256,
        request=dict(row.request),
        variable=row.variable,
        region=row.region,
        depth_min=float(row.depth_min),
        depth_max=float(row.depth_max),
        min_profiles=int(row.min_profiles),
        series_start=row.series_start,
        series_end=row.series_end,
        created_at=row.created_at,
    )


def _model(row: Row[Any]) -> ForecastModel:
    return ForecastModel(
        id=str(row.id),
        definition_id=str(row.definition_id),
        version=int(row.version),
        family=row.family,
        model_order=dict(row.model_order or {}),
        training_snapshot=dict(row.training_snapshot or {}),
        metrics=dict(row.metrics or {}),
        diagnostics=dict(row.diagnostics or {}),
        status=row.status,
        artefact_key=row.artefact_key,
        created_at=row.created_at,
    )


def _run(row: Row[Any]) -> ForecastRun:
    return ForecastRun(
        id=str(row.id),
        definition_id=str(row.definition_id),
        model_id=None if row.model_id is None else str(row.model_id),
        job_id=None if row.job_id is None else str(row.job_id),
        client_id=row.client_id,
        horizon=int(row.horizon),
        status=row.status,
        reason=row.reason,
        history=dict(row.history or {}),
        forecast=dict(row.forecast or {}),
        backtest=dict(row.backtest or {}),
        warnings=list(row.warnings or []),
        limitations=row.limitations or "",
        seed=int(row.seed),
        versions=dict(row.versions or {}),
        generated_at=row.generated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


DEFINITION_COLUMNS = (
    "id, client_id, definition_sha256, request, variable, region, depth_min, depth_max,"
    " min_profiles, series_start, series_end, created_at"
)
MODEL_COLUMNS = (
    "id, definition_id, version, family, model_order, training_snapshot, metrics, diagnostics,"
    " status, artefact_key, created_at"
)
RUN_COLUMNS = (
    "id, definition_id, model_id, job_id, client_id, horizon, status, reason, history, forecast,"
    " backtest, warnings, limitations, seed, versions, generated_at, created_at, updated_at"
)
RUN_FIELDS = {
    "model_id",
    "status",
    "reason",
    "history",
    "forecast",
    "backtest",
    "warnings",
    "limitations",
    "seed",
    "versions",
    "generated_at",
}


class PostgresForecastStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def definition(self, client_id: str, document: dict[str, Any], sha256: str) -> Definition:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "INSERT INTO app.forecast_definition(client_id, definition_sha256, request,"
                    " variable, region, depth_min, depth_max, min_profiles, series_start,"
                    " series_end) VALUES (:client, :sha, CAST(:request AS jsonb), :variable,"
                    " :region, :depth_min, :depth_max, :min_profiles, :start, :end)"
                    " ON CONFLICT (client_id, definition_sha256) DO UPDATE SET request ="
                    " EXCLUDED.request"
                    f" RETURNING {DEFINITION_COLUMNS}"
                ),
                {
                    "client": client_id,
                    "sha": sha256,
                    "request": _json(document),
                    "variable": document["variable"],
                    "region": document["region"],
                    "depth_min": document["depth_dbar"]["min"],
                    "depth_max": document["depth_dbar"]["max"],
                    "min_profiles": document["min_profiles"],
                    "start": datetime.fromisoformat(
                        document["series_start"].replace("Z", "+00:00")
                    ),
                    "end": datetime.fromisoformat(document["series_end"].replace("Z", "+00:00")),
                },
            ).one()
        return _definition(row)

    def get_definition(self, definition_id: str) -> Definition | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {DEFINITION_COLUMNS} FROM app.forecast_definition"
                    " WHERE id = CAST(:id AS uuid)"
                ),
                {"id": definition_id},
            ).one_or_none()
        return None if row is None else _definition(row)

    def add_model(
        self,
        definition_id: str,
        *,
        family: str,
        model_order: dict[str, Any],
        training_snapshot: dict[str, Any],
        metrics: dict[str, Any],
        diagnostics: dict[str, Any],
        status: str,
        artefact_key: str | None,
    ) -> ForecastModel:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT id FROM app.forecast_definition WHERE id = CAST(:id AS uuid) FOR UPDATE"
                ),
                {"id": definition_id},
            )
            row = connection.execute(
                text(
                    "INSERT INTO app.forecast_model(definition_id, version, family, model_order,"
                    " training_snapshot, metrics, diagnostics, status, artefact_key)"
                    " SELECT CAST(:definition AS uuid), coalesce(max(version), 0) + 1, :family,"
                    " CAST(:order AS jsonb), CAST(:snapshot AS jsonb), CAST(:metrics AS jsonb),"
                    " CAST(:diagnostics AS jsonb), :status, :key FROM app.forecast_model"
                    " WHERE definition_id = CAST(:definition AS uuid)"
                    f" RETURNING {MODEL_COLUMNS}"
                ),
                {
                    "definition": definition_id,
                    "family": family,
                    "order": _json(model_order),
                    "snapshot": _json(training_snapshot),
                    "metrics": _json(metrics),
                    "diagnostics": _json(diagnostics),
                    "status": status,
                    "key": artefact_key,
                },
            ).one()
        return _model(row)

    def get_model(self, model_id: str) -> ForecastModel | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {MODEL_COLUMNS} FROM app.forecast_model WHERE id = CAST(:id AS uuid)"
                ),
                {"id": model_id},
            ).one_or_none()
        return None if row is None else _model(row)

    def create_run(
        self, definition_id: str, client_id: str, job_id: str | None, horizon: int
    ) -> ForecastRun:
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    "INSERT INTO app.forecast_run(definition_id, job_id, client_id, horizon,"
                    " status) VALUES (CAST(:definition AS uuid), CAST(:job AS uuid), :client,"
                    f" :horizon, 'pending') RETURNING {RUN_COLUMNS}"
                ),
                {
                    "definition": definition_id,
                    "job": job_id,
                    "client": client_id,
                    "horizon": horizon,
                },
            ).one()
        return _run(row)

    def update_run(self, run_id: str, **fields: Any) -> ForecastRun:
        unknown = set(fields) - RUN_FIELDS
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        assignments = ["updated_at = clock_timestamp()"]
        parameters: dict[str, Any] = {"id": run_id}
        for name, value in fields.items():
            if name in ("history", "forecast", "backtest", "warnings", "versions"):
                assignments.append(f"{name} = CAST(:{name} AS jsonb)")
                parameters[name] = _json(value)
            elif name == "model_id":
                assignments.append("model_id = CAST(:model_id AS uuid)")
                parameters[name] = value
            else:
                assignments.append(f"{name} = :{name}")
                parameters[name] = value
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    f"UPDATE app.forecast_run SET {', '.join(assignments)}"
                    f" WHERE id = CAST(:id AS uuid) RETURNING {RUN_COLUMNS}"
                ),
                parameters,
            ).one()
        return _run(row)

    def get_run(self, run_id: str, client_id: str | None = None) -> ForecastRun | None:
        statement = f"SELECT {RUN_COLUMNS} FROM app.forecast_run WHERE id = CAST(:id AS uuid)"
        parameters: dict[str, Any] = {"id": run_id}
        if client_id is not None:
            statement += " AND client_id = :client"
            parameters["client"] = client_id
        with self.engine.connect() as connection:
            row = connection.execute(text(statement), parameters).one_or_none()
        return None if row is None else _run(row)

    def list_runs(self, client_id: str, limit: int) -> list[ForecastRun]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {RUN_COLUMNS} FROM app.forecast_run WHERE client_id = :client"
                    " ORDER BY created_at DESC, id DESC LIMIT :limit"
                ),
                {"client": client_id, "limit": limit},
            ).all()
        return [_run(row) for row in rows]

    def run_for_job(self, job_id: str) -> ForecastRun | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {RUN_COLUMNS} FROM app.forecast_run WHERE job_id = CAST(:id AS uuid)"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": job_id},
            ).one_or_none()
        return None if row is None else _run(row)


class MemoryForecastStore:
    def __init__(self) -> None:
        self._definitions: dict[str, Definition] = {}
        self._models: dict[str, ForecastModel] = {}
        self._runs: dict[str, ForecastRun] = {}
        self._lock = threading.RLock()

    def definition(self, client_id: str, document: dict[str, Any], sha256: str) -> Definition:
        with self._lock:
            for existing in self._definitions.values():
                if existing.client_id == client_id and existing.definition_sha256 == sha256:
                    return existing
            definition = Definition(
                id=str(uuid.uuid4()),
                client_id=client_id,
                definition_sha256=sha256,
                request=dict(document),
                variable=document["variable"],
                region=document["region"],
                depth_min=float(document["depth_dbar"]["min"]),
                depth_max=float(document["depth_dbar"]["max"]),
                min_profiles=int(document["min_profiles"]),
                series_start=datetime.fromisoformat(
                    document["series_start"].replace("Z", "+00:00")
                ),
                series_end=datetime.fromisoformat(document["series_end"].replace("Z", "+00:00")),
            )
            self._definitions[definition.id] = definition
            return definition

    def get_definition(self, definition_id: str) -> Definition | None:
        return self._definitions.get(definition_id)

    def add_model(
        self,
        definition_id: str,
        *,
        family: str,
        model_order: dict[str, Any],
        training_snapshot: dict[str, Any],
        metrics: dict[str, Any],
        diagnostics: dict[str, Any],
        status: str,
        artefact_key: str | None,
    ) -> ForecastModel:
        with self._lock:
            version = 1 + sum(1 for m in self._models.values() if m.definition_id == definition_id)
            model = ForecastModel(
                id=str(uuid.uuid4()),
                definition_id=definition_id,
                version=version,
                family=family,
                model_order=model_order,
                training_snapshot=training_snapshot,
                metrics=metrics,
                diagnostics=diagnostics,
                status=status,
                artefact_key=artefact_key,
            )
            self._models[model.id] = model
            return model

    def get_model(self, model_id: str) -> ForecastModel | None:
        return self._models.get(model_id)

    def create_run(
        self, definition_id: str, client_id: str, job_id: str | None, horizon: int
    ) -> ForecastRun:
        with self._lock:
            run = ForecastRun(
                id=str(uuid.uuid4()),
                definition_id=definition_id,
                model_id=None,
                job_id=job_id,
                client_id=client_id,
                horizon=horizon,
                status="pending",
                reason=None,
                history={},
                forecast={},
                backtest={},
                warnings=[],
                limitations="",
                seed=20261016,
                versions={},
                generated_at=None,
            )
            self._runs[run.id] = run
            return run

    def update_run(self, run_id: str, **fields: Any) -> ForecastRun:
        unknown = set(fields) - RUN_FIELDS
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        with self._lock:
            run = replace(self._runs[run_id], updated_at=datetime.now(UTC), **fields)
            self._runs[run_id] = run
            return run

    def get_run(self, run_id: str, client_id: str | None = None) -> ForecastRun | None:
        run = self._runs.get(run_id)
        if run is None or (client_id is not None and run.client_id != client_id):
            return None
        return run

    def list_runs(self, client_id: str, limit: int) -> list[ForecastRun]:
        rows = [run for run in self._runs.values() if run.client_id == client_id]
        rows.sort(key=lambda run: (run.created_at, run.id), reverse=True)
        return rows[:limit]

    def run_for_job(self, job_id: str) -> ForecastRun | None:
        rows = [run for run in self._runs.values() if run.job_id == job_id]
        return max(rows, key=lambda run: run.created_at) if rows else None
