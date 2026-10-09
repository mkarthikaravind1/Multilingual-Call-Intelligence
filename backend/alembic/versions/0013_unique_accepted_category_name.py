"""unique category names for accepted emerging themes

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-09

EmergingComplaintService checks that an accepted theme's category name is
new, but only within one API instance. This index makes the database refuse
a second accepted theme with the same name (ignoring case), so two
supervisors accepting at once on different instances cannot both succeed.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_INDEX = "uq_emerging_complaint_candidates_accepted_category"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "emerging_complaint_candidates",
        [sa.text("lower(category_name)")],
        unique=True,
        postgresql_where=sa.text("status = 'accepted'"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="emerging_complaint_candidates")
