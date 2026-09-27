"""post call summaries

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No foreign key to conversations: conversation saves delete and
    # re-insert that row. Existing completed calls are not backfilled.
    op.create_table(
        "post_call_summaries",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("overall_summary", sa.Text(), nullable=False),
        sa.Column("customer_summary", sa.Text(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("sentiment_label", sa.String(), nullable=False),
        sa.Column("sentiment_confidence", sa.Float(), nullable=False),
        sa.Column("sentiment_evidence", sa.Text(), nullable=False),
        sa.Column("complaints", sa.JSON(), nullable=False),
        sa.Column("unresolved_issues", sa.JSON(), nullable=False),
        sa.Column("actions_promised", sa.JSON(), nullable=False),
        sa.Column("follow_up_required", sa.Boolean(), nullable=False),
        sa.Column("service_estimate", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("post_call_summaries")
