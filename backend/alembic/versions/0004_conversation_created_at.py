"""conversation created_at

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows receive the migration time; call_id breaks ties.
    op.add_column(
        "conversations",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_conversations_created_at", "conversations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_conversations_created_at", table_name="conversations")
    op.drop_column("conversations", "created_at")
