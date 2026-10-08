"""Add scientific identity, monthly levels and durable Stage 1 evidence.

Workers receive no target-table DML from this migration. Controlled procedures
are granted individually; existing Stage 0 objects and extension ownership survive.
"""

from pathlib import Path

from alembic import op

revision = "0002_ingestion_foundation"
down_revision = "0001_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: scientific and provenance state must be preserved")
