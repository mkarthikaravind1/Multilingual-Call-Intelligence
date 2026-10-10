"""the complaint categories each line of a call raises

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-10

Complaint categories were kept per call only. Each line now carries the
categories it raises (more than one: the line covers several issues), so
the transcript shows where each complaint was said and reports can quote
the customer. Lines of existing calls keep it empty (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("utterances", sa.Column("complaint_categories", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("utterances", "complaint_categories")
