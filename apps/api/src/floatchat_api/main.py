from fastapi import FastAPI
from fastapi.responses import JSONResponse
from floatchat_core.config import Settings

from floatchat_api.health import Check, dependency_checks, ready


def create_app(checks: dict[str, Check] | None = None, timeout: float | None = None) -> FastAPI:
    app = FastAPI(title="FloatChat", version="0.0.0")

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
