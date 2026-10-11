"""the audit log and the AI log

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-11

audit_log: one row per request that changes something and per read that
matters (who, in what role, when, which action, on what, with what result).
It never holds request content.

ai_inference_log: one row per request to the LLM (the call, the task, the
model, the prompt and answer when AI_LOG_MODE keeps them, the time taken,
the outcome and the token counts).

Both are emptied of old rows by a background job (AUDIT_LOG_RETENTION_DAYS,
AI_LOG_RETENTION_DAYS).
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.Float(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
    )
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"])
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_target_id", "audit_log", ["target_id"])

    op.create_table(
        "ai_inference_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("call_id", sa.String(), nullable=True),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("prompt_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answer_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_ai_inference_log_started_at", "ai_inference_log", ["started_at"])
    op.create_index(
        "ix_ai_inference_log_call_started", "ai_inference_log", ["call_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_table("ai_inference_log")
    op.drop_table("audit_log")
