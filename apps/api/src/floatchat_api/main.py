from fastapi import FastAPI
from fastapi.responses import JSONResponse
from floatchat_core.config import Settings
from floatchat_core.query.router import QueryService

from floatchat_api.health import Check, dependency_checks, ready
from floatchat_api.query_api import QueryRuntime, install

API_VERSION = "0.2.0"


def create_app(
    checks: dict[str, Check] | None = None,
    timeout: float | None = None,
    query_service: QueryService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="FloatChat",
        version=API_VERSION,
        description="Argo ocean observations: catalogue, floats, profiles and validated query "
        "plans compiled to parameterised SQL or bounded DuckDB (Stage 2).",
    )
    install(app, QueryRuntime(service=query_service))

    @app.get("/v1/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/health/ready")
    async def readiness() -> JSONResponse:
        try:
            settings = Settings() if checks is None else None
            probes = dependency_checks(settings) if settings is not None else checks
            budget = (
                timeout
                if timeout is not None
                else (settings.readiness_timeout_seconds if settings is not None else 4.0)
            )
            usable = probes is not None and await ready(probes, budget)
        except Exception:
            usable = False
        return JSONResponse(
            {"status": "ok" if usable else "unavailable"}, status_code=200 if usable else 503
        )

    return app


app = create_app()
