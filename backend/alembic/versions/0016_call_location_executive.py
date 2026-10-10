"""location, executive and direction on every call

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10

Reports are by location and by executive, so each call now records where it
was taken, who took it and whether the customer called or was called.
Locations are a list (each with the number customers dial); a user belongs
to one and has the number or SIP address their phone is reached at.
Existing calls and users keep these empty (NULL): they were not recorded.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("location_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("phone_number", name="uq_locations_phone_number"),
    )

    op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("location_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("dial_target", sa.String(), nullable=True))
    op.create_unique_constraint("uq_users_dial_target", "users", ["dial_target"])

    op.add_column("conversations", sa.Column("direction", sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("location_id", sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("executive_user_id", sa.String(), nullable=True))
    op.create_index("ix_conversations_location_id", "conversations", ["location_id"])
    op.create_index(
        "ix_conversations_executive_user_id", "conversations", ["executive_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_executive_user_id", table_name="conversations")
    op.drop_index("ix_conversations_location_id", table_name="conversations")
    op.drop_column("conversations", "executive_user_id")
    op.drop_column("conversations", "location_id")
    op.drop_column("conversations", "direction")

    op.drop_constraint("uq_users_dial_target", "users", type_="unique")
    op.drop_column("users", "dial_target")
    op.drop_column("users", "location_id")
    op.drop_column("users", "display_name")

    op.drop_table("locations")
