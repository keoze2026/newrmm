"""Consent state on sessions, and device presence for unattended access.

Spec section 9: no capture happens outside an active, consented session, and
the endpoint always shows a visible presence indicator.

Revision ID: 0003_consent
Revises: 0002_session_ui
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_consent"
down_revision = "0002_session_ui"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("consent_state", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column("sessions", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sessions", sa.Column("agent_version", sa.String(32), nullable=True))
    op.create_check_constraint(
        "ck_sessions_consent_state",
        "sessions",
        "consent_state in ('pending','granted','denied')",
    )
    # Sessions that predate the consent gate are left as pending; nothing streams
    # from them because no agent is attached.
    op.add_column("devices", sa.Column("agent_version", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "agent_version")
    op.drop_constraint("ck_sessions_consent_state", "sessions", type_="check")
    op.drop_column("sessions", "agent_version")
    op.drop_column("sessions", "consent_at")
    op.drop_column("sessions", "consent_state")
