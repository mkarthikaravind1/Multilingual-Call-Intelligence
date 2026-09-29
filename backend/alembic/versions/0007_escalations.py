"""escalations

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No foreign key to conversations: conversation saves delete and
    # re-insert that row.
    op.create_table(
        "escalations",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("first_detected_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.Float(), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.Float(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_escalations_status", "escalations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_escalations_status", table_name="escalations")
    op.drop_table("escalations")
