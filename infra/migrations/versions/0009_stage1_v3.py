"""stage1-v3: plan v2, run canonical cap, empty-delivery receipts, source exclusions."""

from pathlib import Path

from alembic import op

revision = "0009_stage1_v3"
down_revision = "0008_resource_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: stage1-v3 evidence and plan versions are retained")
