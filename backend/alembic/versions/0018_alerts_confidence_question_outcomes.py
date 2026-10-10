"""call alerts, complaint confidence and question outcomes

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-10

- complaint_coverages: how sure the detector was of each complaint, and
  when it was first detected (an alert is raised when it goes unasked).
- call_alerts: the alerts raised on a call (complaint not asked about,
  severe category, low confidence, poor audio), kept with the call.
- question_outcomes: whether the executive accepted or skipped each
  suggested question.

Existing complaints keep the two new columns empty (NULL).
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("complaint_coverages", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("complaint_coverages", sa.Column("detected_at", sa.Float(), nullable=True))

    op.create_table(
        "call_alerts",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("alert_type", sa.String(), primary_key=True),
        sa.Column("subject", sa.String(), primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("raised_at", sa.Float(), nullable=False),
        sa.Column("cleared_at", sa.Float(), nullable=True),
    )

    op.create_table(
        "question_outcomes",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("question", sa.Text(), primary_key=True),
        sa.Column("target_category", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("question_outcomes")
    op.drop_table("call_alerts")
    op.drop_column("complaint_coverages", "detected_at")
    op.drop_column("complaint_coverages", "confidence")
