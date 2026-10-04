import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from floatchat_core.config import Settings
from redis.asyncio import Redis

Check = Callable[[], Awaitable[None]]


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
    async def database() -> None:
        connection = await psycopg.AsyncConnection.connect(
            settings.database_url.get_secret_value(), connect_timeout=2
        )
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                if await cursor.fetchone() != (1,):
                    raise RuntimeError("database unavailable")

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

    return {"database": database, "redis": redis, "storage": storage}


async def ready(checks: dict[str, Check], budget_seconds: float) -> bool:
    async def probe(check: Check) -> bool:
        try:
            await check()
            return True
        except Exception:
            return False

    try:
        async with asyncio.timeout(budget_seconds):
            return all(await asyncio.gather(*(probe(check) for check in checks.values())))
    except TimeoutError:
        return False
