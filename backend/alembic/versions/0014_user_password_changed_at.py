"""when a user's password was last reset

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09

Sessions signed in before a password reset no longer count. Existing users
have never been reset (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_changed_at", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
