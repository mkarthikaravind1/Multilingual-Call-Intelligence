"""plain learning evidence descriptions

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02

AI-prediction evidence was stored as "AI predicted <component> '<value>'."
and corrections as "AI predicted <component> '<a>' and human corrected it to
'<b>'.". New records store "<value>" and "Corrected '<a>' to '<b>'."; this
rewrites existing rows the same way. Only rows whose text exactly matches the
old generated wording (rebuilt from their own columns) are touched.
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_OLD_PREDICTION = "'AI predicted ' || component || ' ''' || actual_value || '''.'"
_NEW_CORRECTION = "'Corrected ''' || actual_value || ''' to ''' || human_correction || '''.'"
_OLD_CORRECTION = (
    "'AI predicted ' || component || ' ''' || actual_value"
    " || ''' and human corrected it to ''' || human_correction || '''.'"
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE learning_evidence SET description = actual_value
        WHERE evidence_type = 'ai_prediction'
          AND actual_value IS NOT NULL
          AND description = {_OLD_PREDICTION}
        """
    )
    op.execute(
        f"""
        UPDATE learning_evidence SET description = {_NEW_CORRECTION}
        WHERE evidence_type = 'human_correction'
          AND actual_value IS NOT NULL
          AND human_correction IS NOT NULL
          AND description = {_OLD_CORRECTION}
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE learning_evidence SET description = {_OLD_PREDICTION}
        WHERE evidence_type = 'ai_prediction'
          AND actual_value IS NOT NULL
          AND description = actual_value
        """
    )
    op.execute(
        f"""
        UPDATE learning_evidence SET description = {_OLD_CORRECTION}
        WHERE evidence_type = 'human_correction'
          AND actual_value IS NOT NULL
          AND human_correction IS NOT NULL
          AND description = {_NEW_CORRECTION}
        """
    )
