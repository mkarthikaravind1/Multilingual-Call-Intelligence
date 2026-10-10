"""who gave each piece of learning feedback

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10

Feedback recorded only the role (ICR or supervisor) of whoever gave it.
Corrections can change what the AI is told, so each now names its user.
Existing feedback has no user (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learning_feedback", sa.Column("created_by", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("learning_feedback", "created_by")
