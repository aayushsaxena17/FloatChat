import os
from typing import Any

from celery import Celery
from celery.schedules import crontab

from .ingestion import process_ticket

app: Any = Celery(
    "floatchat", broker=os.environ.get("INGESTION_REDIS_URL", os.environ.get("REDIS_URL"))
)
app.conf.update(
    result_backend=os.environ.get("REDIS_URL"),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_ignore_result=False,
    result_expires=300,
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "floatchat.ingest_chunk": {
            "queue": os.environ.get("INGESTION_QUEUE_NAMESPACE", "stage1-disabled")
        }
    },
    beat_scheduler="floatchat_workers.scheduler:SingleScheduler",
    beat_schedule={
        "stage1-utc-daily": {
            "task": "floatchat.schedule_ingestion",
            "schedule": crontab(hour=2, minute=0),
            "options": {"queue": os.environ.get("INGESTION_QUEUE_NAMESPACE", "stage1-disabled")},
        }
    },
)


def smoke(value: str) -> str:
    return f"ok:{value}"


app.task(name="floatchat.smoke")(smoke)
app.task(
    name="floatchat.ingest_chunk",
    max_retries=0,
    autoretry_for=(),
    acks_late=True,
    reject_on_worker_lost=False,
    ignore_result=True,
)(process_ticket)


def schedule_ingestion() -> str:
    from .cli import scheduled_admission

    return scheduled_admission()


app.task(name="floatchat.schedule_ingestion", max_retries=0, autoretry_for=(), ignore_result=True)(
    schedule_ingestion
)
