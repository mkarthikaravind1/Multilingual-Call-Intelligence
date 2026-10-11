"""a running number for call ids

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-11

Calls are named "CALL-" and a number (see app.domain.call_number). The
sequence hands the numbers out, so two servers never give the same one.
It starts after the highest number a call already has; calls with older
ids keep them (python -m app.cli renumber-calls renames those).
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS call_number_seq")
    op.execute(
        """
        SELECT setval(
            'call_number_seq',
            (SELECT max(substring(call_id from 6)::bigint)
               FROM conversations WHERE call_id ~ '^CALL-[0-9]+$')
        )
        WHERE EXISTS (SELECT 1 FROM conversations WHERE call_id ~ '^CALL-[0-9]+$')
        """
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS call_number_seq")
