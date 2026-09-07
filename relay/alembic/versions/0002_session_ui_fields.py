"""Session fields the operator console needs: editable name, guest presence,
reported host details (Appendix A).

Revision ID: 0002_session_ui
Revises: 0001_initial
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_session_ui"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("name", sa.String(64), nullable=True))
    op.add_column("sessions", sa.Column("host_name", sa.String(255), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("guest_connected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sessions", sa.Column("guest_joined_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("guest_last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("system_info", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "sessions",
        sa.Column("monitors", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    # Existing rows: the session name starts out as the join code.
    op.execute("UPDATE sessions SET name = code WHERE name IS NULL")
    op.alter_column("sessions", "name", nullable=False)


def downgrade() -> None:
    for column in (
        "monitors",
        "system_info",
        "guest_last_seen_at",
        "guest_joined_at",
        "guest_connected",
        "host_name",
        "name",
    ):
        op.drop_column("sessions", column)
