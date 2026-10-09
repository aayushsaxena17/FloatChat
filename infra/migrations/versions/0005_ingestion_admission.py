"""Fenced admission, landing evidence and restricted ingestion execution."""

from pathlib import Path

from alembic import op

revision = "0005_ingestion_admission"
down_revision = "0004_scientific_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: ingestion admission and evidence must be preserved")
