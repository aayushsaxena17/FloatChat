import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from floatchat_core.chat.pipeline import ChatService
from floatchat_core.chat.store import ConversationStore
from floatchat_core.config import Settings
from floatchat_core.forecast.store import ForecastStore
from floatchat_core.jobs.store import JobStore
from floatchat_core.query.router import QueryService

from floatchat_api.chat_api import ChatRuntime, install_chat
from floatchat_api.forecast_api import ForecastRuntime, install_forecasts
from floatchat_api.health import Check, dependency_checks, ready
from floatchat_api.jobs_api import JobsRuntime, install_jobs
from floatchat_api.query_api import QueryRuntime, install

API_VERSION = "0.5.0"


def create_app(
    checks: dict[str, Check] | None = None,
    timeout: float | None = None,
    query_service: QueryService | None = None,
    chat_service: ChatService | None = None,
    chat_store: ConversationStore | None = None,
    jobs_store: JobStore | None = None,
    jobs_runtime: JobsRuntime | None = None,
    forecast_store: ForecastStore | None = None,
) -> FastAPI:
    runtime = QueryRuntime(service=query_service)
    chat_runtime = ChatRuntime(runtime, service=chat_service, store=chat_store)
    jobs = jobs_runtime or JobsRuntime(store=jobs_store)
    forecasts = ForecastRuntime(jobs, store=forecast_store)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        # The part cache warms in a background thread; readiness and requests never wait on it.
        runtime.start_warmup()
        yield

    app = FastAPI(
        title="FloatChat",
        version=API_VERSION,
        description="Argo ocean observations: catalogue, floats, profiles, validated query "
        "plans compiled to parameterised SQL or bounded DuckDB (Stage 2) and a conversational "
        "assistant whose plans pass the same validator (Stage 4), and durable export jobs "
        "over historical ingestion runs (Stage 5) and backtested statistical forecasts "
        "(Stage 6).",
        lifespan=lifespan,
    )
    install(app, runtime)
    install_chat(app, chat_runtime)
    install_jobs(app, jobs)
    install_forecasts(app, forecasts)
    _configure_logging()

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


def _configure_logging() -> None:
    """Query execution records (plan hash, route, timings) reach stdout under uvicorn."""
    logger = logging.getLogger("floatchat")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


app = create_app()
