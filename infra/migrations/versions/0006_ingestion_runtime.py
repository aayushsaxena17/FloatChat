"""Bounded month provisioning and durable runtime evidence, no retention."""

from pathlib import Path

from alembic import op

revision = "0006_ingestion_runtime"
down_revision = "0005_ingestion_admission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: runtime evidence and scientific partitions are retained")
