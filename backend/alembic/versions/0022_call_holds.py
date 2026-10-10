"""when a call was on hold

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-10

A call can be put on hold and taken off it. Each hold is kept with when it
started and ended (ended_at null while it is on), as a list on the call.
Calls from before keep it empty (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("holds", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "holds")
