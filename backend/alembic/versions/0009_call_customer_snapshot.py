"""call customer name and vehicle snapshot

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Filled in the next time each call's customer is resolved against the
    # CRM; `python -m app.cli backfill-call-customers` fills existing calls.
    op.add_column("call_customers", sa.Column("customer_name", sa.String(), nullable=True))
    op.add_column(
        "call_customers", sa.Column("vehicle_registration", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("call_customers", "vehicle_registration")
    op.drop_column("call_customers", "customer_name")
