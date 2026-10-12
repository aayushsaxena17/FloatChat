"""Stage 4: semantic documents, chat conversations and the LLM call ledger (ADR-0071, ADR-0072)."""

from pathlib import Path

from alembic import op

revision = "0018_semantic_chat"
down_revision = "0017_query_env_times"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(Path(__file__).with_suffix(".sql").read_text())


def downgrade() -> None:
    raise RuntimeError("Downgrade refused: conversations and the call ledger are retained")
