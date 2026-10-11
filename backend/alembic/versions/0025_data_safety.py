"""copies off the server, recording checksums and database backups

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-11

call_recordings gains the file's SHA-256 (noted when it is written), where
its copy off the server is, and when it was last checked and with what
result. transcript_archives: one row per call whose transcript has been
copied off the server. database_backups: every backup tried.
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_recordings", sa.Column("sha256", sa.String(), nullable=True))
    op.add_column("call_recordings", sa.Column("archive_key", sa.String(), nullable=True))
    op.add_column("call_recordings", sa.Column("archived_at", sa.Float(), nullable=True))
    op.add_column("call_recordings", sa.Column("verified_at", sa.Float(), nullable=True))
    op.add_column("call_recordings", sa.Column("integrity", sa.String(), nullable=True))

    op.create_table(
        "transcript_archives",
        sa.Column("call_id", sa.String(), primary_key=True),
        sa.Column("archive_key", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("archived_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "database_backups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("finished_at", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("archive_key", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("removed_at", sa.Float(), nullable=True),
    )
    op.create_index("ix_database_backups_started_at", "database_backups", ["started_at"])


def downgrade() -> None:
    op.drop_table("database_backups")
    op.drop_table("transcript_archives")
    for column in ("integrity", "verified_at", "archived_at", "archive_key", "sha256"):
        op.drop_column("call_recordings", column)
