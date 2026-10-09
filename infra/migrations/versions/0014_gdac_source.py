"""GDAC NetCDF source population and relaxed source checks (stage1-v4)."""

from pathlib import Path

from alembic import op

revision = "0014_gdac_source"
down_revision = "0013_publication_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: ingestion evidence and plan versions are retained")
