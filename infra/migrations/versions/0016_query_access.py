"""Stage 2 query access: read-only login, query views, regions, indexes (ADR-0058, ADR-0060)."""

from pathlib import Path

from alembic import op

revision = "0016_query_access"
down_revision = "0015_gdac_wiring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: query views and named regions are retained")
