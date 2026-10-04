import os
from typing import Any

from celery import Celery

app: Any = Celery("floatchat", broker=os.environ.get("REDIS_URL"))
app.conf.update(
    result_backend=os.environ.get("REDIS_URL"),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_ignore_result=False,
    result_expires=300,
)


def smoke(value: str) -> str:
    return f"ok:{value}"


app.task(name="floatchat.smoke")(smoke)
