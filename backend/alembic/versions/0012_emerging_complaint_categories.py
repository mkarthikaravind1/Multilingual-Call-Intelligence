"""categories from accepted emerging complaint themes

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09

When a supervisor accepts an emerging complaint theme it becomes a complaint
category that detection reports: category_name is what it is called,
category_description tells the detector what counts. Themes accepted before
this migration have neither, so they add no category until a supervisor
reopens and accepts them again.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "emerging_complaint_candidates",
        sa.Column("category_name", sa.String(), nullable=True),
    )
    op.add_column(
        "emerging_complaint_candidates",
        sa.Column("category_description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("emerging_complaint_candidates", "category_description")
    op.drop_column("emerging_complaint_candidates", "category_name")
