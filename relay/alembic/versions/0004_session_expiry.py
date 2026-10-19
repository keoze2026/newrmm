"""Session codes expire.

Security review finding: a pending session stayed joinable for ever, so a code
shared over chat months ago still worked. A code is a credential and credentials
should not be immortal.

Revision ID: 0004_expiry
Revises: 0003_consent
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_expiry"
down_revision = "0003_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    # Sessions created before this migration have no expiry recorded; give them
    # one relative to when they were created rather than leaving them immortal.
    op.execute(
        "UPDATE sessions SET expires_at = created_at + interval '60 minutes' "
        "WHERE expires_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_column("sessions", "expires_at")
