"""call customers

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No foreign key to conversations: conversation saves delete and
    # re-insert that row. Existing calls simply have no caller recorded.
    op.create_table(
        "call_customers",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("caller_number", sa.String(), nullable=True),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.Column("vehicle_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_call_customers_customer_id", "call_customers", ["customer_id"])
    op.create_index("ix_call_customers_caller_number", "call_customers", ["caller_number"])


def downgrade() -> None:
    op.drop_index("ix_call_customers_caller_number", table_name="call_customers")
    op.drop_index("ix_call_customers_customer_id", table_name="call_customers")
    op.drop_table("call_customers")
