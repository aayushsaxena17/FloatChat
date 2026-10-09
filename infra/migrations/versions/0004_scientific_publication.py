"""Controlled scientific replacement and catalogue activation share one commit."""

from pathlib import Path

from alembic import op

revision = "0004_scientific_publication"
down_revision = "0003_ingestion_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: committed scientific publication must be preserved")
