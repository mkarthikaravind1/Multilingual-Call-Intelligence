"""call recordings kept on disk, and who listened to them

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-10

Recordings were held in memory only long enough to transcribe a call again.
With RECORDING_ENABLED they are also kept on disk, encrypted, until their
delete_after date: one row per call says where the file is and when it goes,
and every time someone listens is logged.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_recordings",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("delete_after", sa.Float(), nullable=False),
        sa.Column("deleted_at", sa.Float(), nullable=True),
    )
    op.create_index("ix_call_recordings_delete_after", "call_recordings", ["delete_after"])

    op.create_table(
        "recording_plays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("call_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("played_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_recording_plays_call_id", "recording_plays", ["call_id"])


def downgrade() -> None:
    op.drop_index("ix_recording_plays_call_id", table_name="recording_plays")
    op.drop_table("recording_plays")
    op.drop_index("ix_call_recordings_delete_after", table_name="call_recordings")
    op.drop_table("call_recordings")
