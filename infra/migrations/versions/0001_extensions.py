"""Enable foundation extensions; never remove retained extensions on downgrade."""

from alembic import op

revision = "0001_extensions"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: Stage 0 extensions must be preserved")
