"""Stage 3: ingestion and source-retrieval timestamps on the query environment view (ADR-0064)."""

from pathlib import Path

from alembic import op

revision = "0017_query_environment_timestamps"
down_revision = "0016_query_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: the query environment view is retained")
