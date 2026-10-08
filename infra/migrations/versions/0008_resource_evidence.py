"""Add safe limit-scope evidence without changing budgets or dispositions."""

from pathlib import Path

from alembic import op

revision = "0008_resource_evidence"
down_revision = "0007_http_replay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: resource diagnostic evidence is retained")
