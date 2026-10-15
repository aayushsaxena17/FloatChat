"""Stage 5: historical runs and the job, chunk, event and artefact tables (ADR-0078/0079)."""

from pathlib import Path

from alembic import op

revision = "0019_jobs_exports"
down_revision = "0018_semantic_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: jobs and artefacts are retained")
