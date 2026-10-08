"""One UTC Beat process per physical ingestion environment."""

from typing import Any

from celery.beat import PersistentScheduler
from floatchat_core.ingestion.numeric import Rejection
from floatchat_core.ingestion.repository import Repository

from .ingestion import Configuration


class SingleScheduler(PersistentScheduler):  # type: ignore[misc]
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.repository: Repository | None = None
        # Celery constructs a lazy scheduler solely for its startup banner.
        # That temporary object must not take the running scheduler's lock.
        if kwargs.get("lazy", False):
            super().__init__(*args, **kwargs)
            return
        configuration = Configuration.load()
        self.repository = configuration.repository()
        marker = self.repository.environment(configuration.environment)
        if marker["mode"] != "normal":
            self.repository.close()
            raise Rejection("acceptance_schedule_disabled")
        with self.repository.transaction() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(164993423,2) AS acquired")
            acquired = cursor.fetchone()["acquired"]
        if not acquired:
            self.repository.close()
            raise Rejection("beat_scheduler_already_running")
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            self.repository.close()
            raise Rejection("beat_scheduler_initialization_failed") from None

    def tick(self, **kwargs: Any) -> Any:
        if self.repository is None:
            raise Rejection("beat_scheduler_not_initialized")
        # A lost lock connection cannot continue dispatching scheduled work.
        with self.repository.transaction() as cursor:
            cursor.execute("SELECT 1")
        return super().tick(**kwargs)

    def close(self) -> None:
        if self.repository is None:
            return
        try:
            super().close()
        finally:
            self.repository.close()
            self.repository = None
