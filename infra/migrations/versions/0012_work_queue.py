"""Phase-based work queue, configurable worker concurrency and metadata cache (stage1-v4)."""

from pathlib import Path

from alembic import op

revision = "0012_work_queue"
down_revision = "0011_set_based_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: ingestion evidence and plan versions are retained")
