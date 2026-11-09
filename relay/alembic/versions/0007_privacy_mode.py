"""Record the endpoint's privacy-blank capability so the console tells the truth.

Revision ID: 0007_privacy_mode
Revises: 0006_guest_token
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_privacy_mode"
down_revision = "0006_guest_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("privacy_mode", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "privacy_mode")
