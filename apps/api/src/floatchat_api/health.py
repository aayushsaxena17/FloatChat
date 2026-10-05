import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from floatchat_core.config import Settings
from redis.asyncio import Redis

Check = Callable[[], Awaitable[None]]
_cleanup_tasks: set[asyncio.Task[bool]] = set()
_CLEANUP_GRACE_SECONDS = 0.05


class _DatabaseCheck:
    def __init__(self, url: str) -> None:
        self.url = url
        self.connections: dict[asyncio.Task[Any], psycopg.AsyncConnection[Any]] = {}
        self.deadlines: dict[asyncio.Task[Any], float] = {}

    async def __call__(self) -> None:
        task = asyncio.current_task()
        assert task is not None
        try:
            remaining = self.deadlines.get(task, asyncio.get_running_loop().time() + 1)
            remaining -= asyncio.get_running_loop().time()
            statement_ms = max(1, int(min(1, max(0, remaining)) * 1000))
            connection = await psycopg.AsyncConnection.connect(
                self.url,
                connect_timeout=2,
                autocommit=True,
                options=f"-c statement_timeout={statement_ms}",
            )
            self.connections[task] = connection
            cursor = connection.cursor()
            await cursor.execute("SELECT 1")
            if await cursor.fetchone() != (1,):
                raise RuntimeError("database unavailable")
        finally:
            self.abort(task)

    def abort(self, task: asyncio.Task[Any]) -> None:
        connection = self.connections.pop(task, None)
        self.deadlines.pop(task, None)
        if connection is not None:
            # Direct, synchronous socket disposal: no query cancellation round trip,
            # transaction rollback, pool return, or awaited context-manager cleanup.
            connection.pgconn.finish()


def storage_client(settings: Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key.get_secret_value(),
        aws_secret_access_key=settings.object_storage_secret_key.get_secret_value(),
        region_name=settings.object_storage_region,
        config=Config(
            connect_timeout=1,
            read_timeout=1,
            retries={"total_max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )


def dependency_checks(settings: Settings) -> dict[str, Check]:
    async def redis() -> None:
        client = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=1, socket_timeout=1
        )
        try:
            if not await client.ping():
                raise RuntimeError("broker unavailable")
        finally:
            await client.aclose()

    async def storage() -> None:
        def access() -> None:
            client = storage_client(settings)
            try:
                client.head_bucket(Bucket=settings.object_storage_bucket)
            finally:
                client.close()

        await asyncio.to_thread(access)

    return {
        "database": _DatabaseCheck(settings.database_url.get_secret_value()),
        "redis": redis,
        "storage": storage,
    }


async def ready(checks: dict[str, Check], budget_seconds: float) -> bool:
    async def probe(check: Check) -> bool:
        try:
            await check()
            return True
        except Exception:
            return False

    if not checks:
        return False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0, budget_seconds)
    tasks = {asyncio.create_task(probe(check)): check for check in checks.values()}
    for task, check in tasks.items():
        if isinstance(check, _DatabaseCheck):
            check.deadlines[task] = deadline
    try:
        done, pending = await asyncio.wait(tasks, timeout=max(0, deadline - loop.time()))
        return not pending and all(not task.cancelled() and task.result() for task in done)
    finally:
        # asyncio.wait does not wait for cancellation cleanup. Retain and reap tasks
        # outside the HTTP response path, including when the caller itself is cancelled.
        for task, check in tasks.items():
            if task.done():
                continue
            if isinstance(check, _DatabaseCheck):
                try:
                    check.abort(task)
                except Exception:
                    pass  # Diagnostics never enter the health response.
            task.cancel()
            _cleanup_tasks.add(task)
            repeat_cancel = loop.call_later(_CLEANUP_GRACE_SECONDS, task.cancel)

            def reaped(
                finished: asyncio.Task[bool], timer: asyncio.TimerHandle = repeat_cancel
            ) -> None:
                timer.cancel()
                _cleanup_tasks.discard(finished)
                if not finished.cancelled():
                    finished.exception()

            task.add_done_callback(reaped)
