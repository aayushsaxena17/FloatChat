"""Artefact expiry and orphan objects (PRD section 8.4 order, section 22 row 7)."""

from datetime import UTC, datetime, timedelta

from floatchat_core.jobs.model import JobLimits
from floatchat_core.jobs.store import MemoryJobStore
from floatchat_workers.jobs import Reconciler

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
JOB = "33333333-3333-4333-8333-333333333333"


class FakeS3:
    def __init__(self, objects: dict[str, datetime]) -> None:
        self.objects = dict(objects)
        self.deleted: list[str] = []

    def list_objects_v2(self, **kwargs):
        prefix = kwargs.get("Prefix", "")
        return {
            "Contents": [
                {"Key": key, "LastModified": modified}
                for key, modified in sorted(self.objects.items())
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.objects.pop(Key, None)
        self.deleted.append(Key)


def artefact(store: MemoryJobStore, key: str, expires: datetime):
    return store.add_artefact(
        job_id=JOB,
        format="csv",
        role="data",
        object_key=key,
        bytes=1,
        sha256="a" * 64,
        row_count=1,
        profile_count=1,
        manifest={},
        expires_at=expires,
    )


def test_expired_artefacts_change_state_before_their_object_is_deleted() -> None:
    store = MemoryJobStore(clock=lambda: NOW - timedelta(days=8))
    old = artefact(store, f"exports/{JOB}/old.csv", NOW - timedelta(hours=1))
    fresh = artefact(store, f"exports/{JOB}/fresh.csv", NOW + timedelta(days=6))
    s3 = FakeS3({old.object_key: NOW - timedelta(days=7), fresh.object_key: NOW})
    summary = Reconciler(store, s3, "bucket", JobLimits()).tick(NOW)
    assert summary == {"expired": 1, "deleted": 1, "orphans_removed": 0}
    assert store.artefact(old.id).state == "deleted" and s3.deleted == [old.object_key]
    assert store.artefact(fresh.id).state == "available" and fresh.object_key in s3.objects


def test_an_object_written_without_a_catalogue_row_is_unreachable_and_removed_after_an_hour() -> None:
    # The worker crashed between the upload and the artefact row (PRD section 22): nothing
    # references the object, no download URL can name it, and the sweep removes it once old.
    store = MemoryJobStore(clock=lambda: NOW)
    kept = artefact(store, f"exports/{JOB}/kept.parquet", NOW + timedelta(days=7))
    orphan_old = f"exports/{JOB}/orphan-old.parquet"
    orphan_new = f"exports/{JOB}/orphan-new.parquet"
    s3 = FakeS3(
        {
            kept.object_key: NOW - timedelta(days=2),
            orphan_old: NOW - timedelta(hours=2),
            orphan_new: NOW - timedelta(minutes=5),
            "normalised/sha256/not-an-export.parquet": NOW - timedelta(days=30),
        }
    )
    summary = Reconciler(store, s3, "bucket", JobLimits()).tick(NOW)
    assert summary["orphans_removed"] == 1 and s3.deleted == [orphan_old]
    assert orphan_new in s3.objects and kept.object_key in s3.objects
    assert "normalised/sha256/not-an-export.parquet" in s3.objects
    assert store.artefact(kept.id).state == "available"
