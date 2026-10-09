"""stage1-v3 runtime amendment: 12-hour run wall-time bound (ADR-0043)."""

from pathlib import Path

from alembic import op

revision = "0010_stage1_v3_runtime"
down_revision = "0009_stage1_v3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: stage1-v3 run bounds and evidence are retained")
