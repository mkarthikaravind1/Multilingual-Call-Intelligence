"""price list versions

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07

The service centre's price list, uploaded and edited by supervisors. Each
save adds a version; the newest is in use. Until the first save the
estimator uses the built-in sample price list.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_list_versions",
        sa.Column("version_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("price_list_versions")
