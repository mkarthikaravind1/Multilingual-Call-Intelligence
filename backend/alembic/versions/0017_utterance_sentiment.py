"""the tone of each line of a call

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-10

Tone was kept per call only. Each customer line now has its own (positive,
neutral, negative, frustrated or escalating), so the transcript can show
where a call turned. Lines of existing calls keep it empty (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("utterances", sa.Column("sentiment", sa.String(), nullable=True))
    op.add_column("utterances", sa.Column("sentiment_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("utterances", "sentiment_confidence")
    op.drop_column("utterances", "sentiment")
