"""Bind an attended session to the computer that joined it first.

Revision ID: 0006_guest_token
Revises: 0005_guest_ip
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_guest_token"
down_revision = "0005_guest_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("guest_token_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "guest_token_hash")
