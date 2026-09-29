"""complaint lifecycle history and emerging complaint candidates

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_complaint_lifecycle_status", "complaint_lifecycle_records", ["status"]
    )

    op.create_table(
        "complaint_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("complaint_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_complaint_lifecycle_events_complaint_id",
        "complaint_lifecycle_events",
        ["complaint_id"],
    )

    op.create_table(
        "emerging_complaint_candidates",
        sa.Column("candidate_id", sa.String(), primary_key=True),
        sa.Column("proposed_name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("call_ids", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("related_category", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.Float(), nullable=False),
        sa.Column("last_seen_at", sa.Float(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.Float(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_emerging_complaint_candidates_status",
        "emerging_complaint_candidates",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_emerging_complaint_candidates_status", table_name="emerging_complaint_candidates"
    )
    op.drop_table("emerging_complaint_candidates")
    op.drop_index(
        "ix_complaint_lifecycle_events_complaint_id", table_name="complaint_lifecycle_events"
    )
    op.drop_table("complaint_lifecycle_events")
    op.drop_index("ix_complaint_lifecycle_status", table_name="complaint_lifecycle_records")
