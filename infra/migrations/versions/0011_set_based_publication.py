"""Set-based publication level validation/insert and owner-slot index (ADR-0044)."""

from pathlib import Path

from alembic import op

revision = "0011_set_based_publication"
down_revision = "0010_stage1_v3_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: publication evidence and plan versions are retained")
