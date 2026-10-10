"""index on a call's status

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-10

The Live Calls page reads the calls in progress every few seconds. Without
an index on status, each read looked through every call ever made.
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_conversations_status", "conversations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_conversations_status", table_name="conversations")
