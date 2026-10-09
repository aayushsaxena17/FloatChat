"""Persist HTTP failures and bind captured replay to its predecessor topology."""

from pathlib import Path

from alembic import op

revision = "0007_http_replay"
down_revision = "0006_ingestion_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: attempt and replay evidence are retained")
