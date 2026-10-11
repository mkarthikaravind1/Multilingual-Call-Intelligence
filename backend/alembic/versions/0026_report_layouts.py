"""the layout of exported reports, as an administrator set it

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-11

One row holds the complaint report's layout: the company name and title
printed on it, its sections in order, and the columns of its list of
complaints. No row: the built-in layout.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_layouts",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("layout", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("report_layouts")
