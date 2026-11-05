"""Record the guest's real IP address, for the Locate tab.

Read the same way the rate limiter already does (ratelimit.caller()) - behind
the reverse proxy, the raw TCP peer is always the proxy itself, never the
guest - and stored on the session so the console can show an approximate
location without needing a live connection.

Revision ID: 0005_guest_ip
Revises: 0004_expiry
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_guest_ip"
down_revision = "0004_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("guest_ip", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "guest_ip")
