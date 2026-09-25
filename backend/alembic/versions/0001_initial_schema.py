"""Initial PostgreSQL persistence schema

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=True),
    )

    op.create_table(
        "utterances",
        sa.Column("utterance_id", sa.String(), primary_key=True),
        sa.Column(
            "call_id",
            sa.String(),
            sa.ForeignKey("conversations.call_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("speaker_role", sa.String(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index("ix_utterances_call_id", "utterances", ["call_id"])

    op.create_table(
        "conversation_coverages",
        sa.Column("call_id", sa.String(), primary_key=True),
    )

    op.create_table(
        "complaint_coverages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "call_id",
            sa.String(),
            sa.ForeignKey("conversation_coverages.call_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.UniqueConstraint("call_id", "category", name="uq_coverage_call_category"),
    )
    op.create_index("ix_complaint_coverages_call_id", "complaint_coverages", ["call_id"])

    op.create_table(
        "learning_evidence",
        sa.Column("evidence_id", sa.String(), primary_key=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("human_correction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_learning_evidence_call_id", "learning_evidence", ["call_id"])

    op.create_table(
        "learning_observations",
        sa.Column("observation_id", sa.String(), primary_key=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("predicted_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=True),
    )
    op.create_index("ix_learning_observations_call_id", "learning_observations", ["call_id"])

    op.create_table(
        "learning_feedback",
        sa.Column("feedback_id", sa.String(), primary_key=True),
        sa.Column(
            "observation_id",
            sa.String(),
            sa.ForeignKey("learning_observations.observation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feedback_type", sa.String(), nullable=False),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=True),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_learning_feedback_observation_id", "learning_feedback", ["observation_id"]
    )
    op.create_index("ix_learning_feedback_call_id", "learning_feedback", ["call_id"])

    op.create_table(
        "improvement_candidates",
        sa.Column("candidate_id", sa.String(), primary_key=True),
        sa.Column("improvement_type", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("reviewed_at", sa.Float(), nullable=True),
        sa.Column("spec_component", sa.String(), nullable=True),
        sa.Column("spec_current_behavior", sa.Text(), nullable=True),
        sa.Column("spec_proposed_behavior", sa.Text(), nullable=True),
        sa.Column("spec_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "active_improvements",
        sa.Column("improvement_id", sa.String(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(),
            sa.ForeignKey("improvement_candidates.candidate_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("spec_component", sa.String(), nullable=False),
        sa.Column("spec_current_behavior", sa.Text(), nullable=False),
        sa.Column("spec_proposed_behavior", sa.Text(), nullable=False),
        sa.Column("spec_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("activated_at", sa.Float(), nullable=False),
        sa.Column("deactivated_at", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_active_improvements_candidate_id", "active_improvements", ["candidate_id"]
    )

    op.create_table(
        "improvement_usages",
        sa.Column("usage_id", sa.String(), primary_key=True),
        sa.Column(
            "improvement_id",
            sa.String(),
            sa.ForeignKey("active_improvements.improvement_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("output_value", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_improvement_usages_improvement_id", "improvement_usages", ["improvement_id"]
    )
    op.create_index("ix_improvement_usages_call_id", "improvement_usages", ["call_id"])

    op.create_table(
        "complaint_lifecycle_records",
        sa.Column("complaint_id", sa.String(), primary_key=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("first_detected_at", sa.Float(), nullable=False),
        sa.Column("last_updated_at", sa.Float(), nullable=False),
        sa.Column("follow_up_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("customer_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_complaint_lifecycle_call_id", "complaint_lifecycle_records", ["call_id"]
    )
    op.create_index(
        "ix_complaint_lifecycle_customer_id", "complaint_lifecycle_records", ["customer_id"]
    )


def downgrade() -> None:
    op.drop_table("complaint_lifecycle_records")
    op.drop_table("improvement_usages")
    op.drop_table("active_improvements")
    op.drop_table("improvement_candidates")
    op.drop_table("learning_feedback")
    op.drop_table("learning_observations")
    op.drop_table("learning_evidence")
    op.drop_table("complaint_coverages")
    op.drop_table("conversation_coverages")
    op.drop_table("utterances")
    op.drop_table("conversations")