"""Stage 6: forecast definitions, model versions and runs (ADR-0082)."""

from pathlib import Path

from alembic import op

revision = "0020_forecasts"
down_revision = "0019_jobs_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: forecast runs are retained for reproducibility")
