"""complaint categories an administrator added, renamed or retired

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-10

A new category could only come from accepting an emerging theme. An
administrator can now add one directly, rename one and retire one. One row
per category they have decided something about: builtin:<name> (retired or
not), theme:<candidate id> (its new name, or retired) or admin:<id> (a
category of their own). A renamed category keeps its former names, so
complaints stored under them need no rewriting.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "managed_complaint_categories",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("former_names", sa.JSON(), nullable=False),
        sa.Column("retired_at", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("managed_complaint_categories")
