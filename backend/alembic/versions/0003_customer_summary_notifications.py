"""customer summary notifications

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_summary_deliveries",
        sa.Column("delivery_id", sa.String(), primary_key=True),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
    )
    op.create_index("ix_customer_summary_deliveries_call_id", "customer_summary_deliveries", ["call_id"])
    op.create_index("ix_customer_summary_deliveries_customer_id", "customer_summary_deliveries", ["customer_id"])
    op.create_index("ix_customer_summary_deliveries_idempotency_key", "customer_summary_deliveries", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_customer_summary_deliveries_idempotency_key", table_name="customer_summary_deliveries")
    op.drop_index("ix_customer_summary_deliveries_customer_id", table_name="customer_summary_deliveries")
    op.drop_index("ix_customer_summary_deliveries_call_id", table_name="customer_summary_deliveries")
    op.drop_table("customer_summary_deliveries")
