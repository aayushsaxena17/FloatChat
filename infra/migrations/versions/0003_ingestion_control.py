"""Fenced durable claims, phase changes and termination; no broker retry authority."""

from pathlib import Path

from alembic import op

revision = "0003_ingestion_control"
down_revision = "0002_ingestion_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: durable ingestion evidence must be preserved")
